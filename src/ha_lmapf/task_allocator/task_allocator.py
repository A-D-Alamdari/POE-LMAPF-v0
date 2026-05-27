from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Tuple, Optional, Iterable

import numpy as np

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import TaskAllocator
from ha_lmapf.core.types import AgentState, Task

Cell = Tuple[int, int]


def _get_task_pickup_location(task: Task) -> Cell:
    """
    Get the pickup location for a task.

    For pickup-delivery tasks, this is task.start.
    For legacy delivery-only tasks (start = (-1,-1)), this falls back to task.goal.
    """
    if task.start != (-1, -1):
        return task.start
    return task.goal


class GreedyNearestTaskAllocator(TaskAllocator):
    """
    Greedy task allocator for lifelong pickup-delivery MAPF.

    For each released task (sorted by release_step, then id), assign it to the
    nearest available agent according to Manhattan distance to the task's
    START (pickup) location. Each agent receives at most one task per planning epoch.

    This ensures agents are assigned tasks they can reach quickly for pickup,
    rather than being assigned based on the delivery destination.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng=None,  # Unused; kept for interface compatibility
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents: no current goal or already reached goal
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        # Deterministic ordering of tasks
        tasks_ordered = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        # Track which agents are still free to assign
        free_agents = dict(available_agents)

        for task in tasks_ordered:
            if not free_agents:
                break

            # Get the pickup location for this task
            pickup_loc = _get_task_pickup_location(task)

            # Choose nearest agent by Manhattan distance to PICKUP location (tie-break by agent ID)
            best_aid = min(
                free_agents.keys(),
                key=lambda aid: (manhattan(free_agents[aid].pos, pickup_loc), aid)
            )

            assignments[best_aid] = task

            del free_agents[best_aid]

        return assignments


class HungarianTaskAllocator(TaskAllocator):
    """
    Optimal task allocator using the Hungarian algorithm.

    Computes the globally optimal assignment that minimizes the total
    Manhattan distance from agents to their assigned task pickup locations.

    Falls back to greedy assignment if scipy is not available.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents: no current goal or already reached goal
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        agent_ids = sorted(available_agents.keys())
        task_list = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        n_agents = len(agent_ids)
        n_tasks = len(task_list)

        # Build cost matrix
        cost_matrix = np.zeros((n_agents, n_tasks), dtype=np.float64)
        for i, aid in enumerate(agent_ids):
            agent_pos = available_agents[aid].pos
            for j, task in enumerate(task_list):
                pickup_loc = _get_task_pickup_location(task)
                cost_matrix[i, j] = manhattan(agent_pos, pickup_loc)

        try:
            from scipy.optimize import linear_sum_assignment
            row_ind, col_ind = linear_sum_assignment(cost_matrix)

            for i, j in zip(row_ind, col_ind):
                if j < n_tasks:  # Ensure task index is valid
                    assignments[agent_ids[i]] = task_list[j]

        except ImportError:
            # Fallback to greedy if scipy not available
            greedy = GreedyNearestTaskAllocator()
            return greedy.assign(agents, open_tasks, step, rng)

        return assignments


class AuctionBasedTaskAllocator(TaskAllocator):
    """
    Auction-based task allocator using sequential single-item auctions.

    Each task is auctioned off to the highest bidder (lowest distance),
    and agents bid based on their proximity to the task's pickup location.
    This provides a balance between optimality and computational efficiency.
    """

    def __init__(self, max_iterations: int = 100, epsilon: float = 0.01):
        """
        Initialize the auction allocator.

        Args:
            max_iterations: Maximum number of auction iterations.
            epsilon: Price increment for bidding.
        """
        self.max_iterations = max_iterations
        self.epsilon = epsilon

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        agent_ids = sorted(available_agents.keys())
        task_list = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        n_agents = len(agent_ids)
        n_tasks = len(task_list)

        # Compute benefit matrix (negative distance = higher benefit for closer tasks)
        max_dist = 0
        benefit_matrix = np.zeros((n_agents, n_tasks), dtype=np.float64)
        for i, aid in enumerate(agent_ids):
            agent_pos = available_agents[aid].pos
            for j, task in enumerate(task_list):
                pickup_loc = _get_task_pickup_location(task)
                dist = manhattan(agent_pos, pickup_loc)
                max_dist = max(max_dist, dist)
                benefit_matrix[i, j] = -dist

        # Normalize benefits to positive values
        benefit_matrix += max_dist + 1

        # Task prices (start at 0)
        prices = np.zeros(n_tasks, dtype=np.float64)

        # Agent assignments (-1 = unassigned)
        agent_to_task = {aid: -1 for aid in agent_ids}
        task_to_agent: Dict[int, int] = {}

        for _ in range(self.max_iterations):
            # Find unassigned agents
            unassigned = [aid for aid in agent_ids if agent_to_task[aid] == -1]
            if not unassigned:
                break

            for aid in unassigned:
                i = agent_ids.index(aid)

                # Compute net values for each task
                net_values = benefit_matrix[i] - prices
                best_task = int(np.argmax(net_values))
                best_value = net_values[best_task]

                # Find second best value for price increment
                net_values_copy = net_values.copy()
                net_values_copy[best_task] = -np.inf
                second_best = np.max(net_values_copy)

                # Only bid if beneficial
                if best_value <= 0:
                    continue

                # Compute bid increment
                bid_increment = best_value - second_best + self.epsilon

                # If task is already assigned, unassign previous owner
                if best_task in task_to_agent:
                    prev_owner = task_to_agent[best_task]
                    agent_to_task[prev_owner] = -1

                # Assign task and update price
                agent_to_task[aid] = best_task
                task_to_agent[best_task] = aid
                prices[best_task] += bid_increment

        # Build final assignments
        for aid, task_idx in agent_to_task.items():
            if task_idx >= 0 and task_idx < n_tasks:
                assignments[aid] = task_list[task_idx]

        return assignments


class CongestionAvoidanceTaskAllocator(TaskAllocator):
    """
    Congestion-avoidance task allocator with iterative refinement.

    Direction A foundation for the paper (the paper's Section 4.2
    "Congestion-Avoidance" allocator): instead of picking the
    nearest task per agent (greedy) or the globally cheapest total
    distance (Hungarian), this allocator incorporates an
    *expected planning difficulty* term into the assignment cost.
    The intuition is that two agents whose shortest paths overlap
    will conflict at the low-level solver, so we charge a penalty
    proportional to path overlap and let the Hungarian matcher
    spread agents across less-contested tasks.

    Pseudocode
    ----------
        Inputs:
          A = available agents (no goal or already at goal)
          T = open tasks (sorted by release_step, task_id)
          map = static obstacles
          lambda_conflict = weighting (default 0.5)
          max_rounds = iteration cap (default 5)

        # Round 0 — seed with greedy nearest-task assignment.
        bfs_cache = {}               # start_cell -> dist_map, parent_map
        path_cache = {}              # (agent, task) -> list[cell]
        D[i][j] = BFS_dist(agent_i.pos, pickup(task_j))   # cache BFS
        assignment_prev = greedy_match(D)                 # Hungarian on D
        path_prev = shortest_path(agent_i, task_j) for each (i,j) in assignment_prev

        # Iterative refinement.
        for r in 1 .. max_rounds:
          # Recompute cost matrix with overlap penalty against
          # the OTHER tentative assignments from the previous round.
          for each agent i, task j:
              path_ij = shortest_path(agent_i, pickup(task_j))
              overlap = 0
              for each (i', j') in assignment_prev with i' != i:
                  overlap += | set(path_ij) ∩ set(path_{i'j'}) |
              C[i][j] = D[i][j] + lambda_conflict * overlap
          assignment = hungarian(C)
          if assignment == assignment_prev:
              break                                       # converged
          assignment_prev = assignment

        return assignment

    Notes
    -----
    * BFS (not A*) is used so the path distances are exact on the
      4-connected grid with unit edge weights. Manhattan distance
      would ignore walls and reduce the penalty's signal when
      bottlenecks are caused by map structure (warehouse aisles).
    * BFS results are cached *within a single allocate() call* by
      start cell. They are NOT cached across calls because agent
      positions change between epochs.
    * When the env is not provided (set_env() never called), the
      allocator transparently falls back to Manhattan distance —
      the overlap-penalty term degenerates because Manhattan
      "paths" are not constructed, so behavior reduces to
      Hungarian assignment.
    """

    def __init__(self, lambda_conflict: float = 0.5, max_rounds: int = 5) -> None:
        """
        Args:
            lambda_conflict: Weight on the path-overlap penalty. With
                lambda_conflict=0 the allocator degenerates to Hungarian
                on BFS distances (a strict generalization). Default 0.5.
            max_rounds: Hard cap on iterative refinement rounds. Default 5.
        """
        self.lambda_conflict = float(lambda_conflict)
        self.max_rounds = int(max_rounds)
        self._env: Any = None
        # Narrowness weights, keyed by free cell. Computed once when an
        # env is bound via ``set_env``; ``None`` until then. Falls back
        # to uniform-weight (1.0) per cell when ``None`` so the
        # constructor remains usable without an env.
        self._narrowness: Optional[Dict[Cell, float]] = None
        # Diagnostics filled by the most recent allocate() call.
        self.last_rounds_used: int = 0

    def set_env(self, env: Any) -> None:
        """
        Bind the static environment so BFS can respect walls.

        The simulator calls this once after constructing the allocator.
        If never called, the allocator falls back to Manhattan distance
        and the conflict-overlap term is dropped.

        Also caches the per-cell narrowness map so each
        ``assign()`` call does not pay the O(|free cells|) cost.
        """
        self._env = env
        self._narrowness = self._compute_narrowness_map(env)

    @staticmethod
    def _compute_narrowness_map(env: Any) -> Dict[Cell, float]:
        """Per-cell narrowness weights for the path-overlap penalty.

        ``narrowness(c) = 4.0 / max(1, degree(c))`` where ``degree(c)``
        is the count of free 4-neighbors of c.  Open interior cells
        (degree 4) get weight 1.0; corridor cells (degree 2) get
        weight 2.0; dead ends and isolated cells (degree ≤ 1) get
        weight 4.0.  The map is built once when the env is bound and
        cached on the allocator instance.

        The function tolerates envs that do not expose ``_free_cells``
        by enumerating the bounding box; that path is intended for
        the hand-crafted test envs in ``tests/``.
        """
        result: Dict[Cell, float] = {}
        free_cells = getattr(env, "_free_cells", None)
        if free_cells is None:
            # Reconstruct from width/height when the env did not
            # precompute the list (some test doubles).
            w = int(getattr(env, "width", 0))
            h = int(getattr(env, "height", 0))
            free_cells = [
                (r, c) for r in range(h) for c in range(w)
                if env.is_free((r, c))
            ]
        for cell in free_cells:
            degree = 0
            for n in neighbors(cell):
                if env.is_free(n):
                    degree += 1
            result[cell] = 4.0 / max(1, degree)
        return result

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents: no current goal or already reached goal.
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            self.last_rounds_used = 0
            return assignments

        agent_ids = sorted(available_agents.keys())
        task_list = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        n_agents = len(agent_ids)
        n_tasks = len(task_list)

        try:
            from scipy.optimize import linear_sum_assignment
        except ImportError:
            # Match HungarianTaskAllocator's fallback behavior.
            greedy = GreedyNearestTaskAllocator()
            self.last_rounds_used = 0
            return greedy.assign(agents, open_tasks, step, rng)

        # Per-call BFS cache, keyed by start cell.
        bfs_cache: Dict[Cell, Tuple[Dict[Cell, int], Dict[Cell, Optional[Cell]]]] = {}

        def get_bfs(start: Cell):
            cached = bfs_cache.get(start)
            if cached is not None:
                return cached
            result = self._bfs(start)
            bfs_cache[start] = result
            return result

        # Distance matrix D (path-length on grid; falls back to Manhattan
        # if env is unavailable or BFS returns infinity).
        D = np.zeros((n_agents, n_tasks), dtype=np.float64)
        # Path matrix: P[i][j] = list of cells from agent i to task j pickup.
        # Empty list if env unavailable or path not found.
        P: List[List[List[Cell]]] = [[[] for _ in range(n_tasks)] for _ in range(n_agents)]
        BIG = 10 ** 9

        for i, aid in enumerate(agent_ids):
            agent_pos = available_agents[aid].pos
            if self._env is not None:
                dist_map, parent_map = get_bfs(agent_pos)
            else:
                dist_map, parent_map = None, None
            for j, task in enumerate(task_list):
                pickup_loc = _get_task_pickup_location(task)
                if dist_map is not None and pickup_loc in dist_map:
                    D[i, j] = float(dist_map[pickup_loc])
                    P[i][j] = self._reconstruct_path(parent_map, agent_pos, pickup_loc)
                else:
                    # Unreachable on map OR no env — use Manhattan as fallback.
                    D[i, j] = float(manhattan(agent_pos, pickup_loc))
                    P[i][j] = []

        # Round 0: seed with Hungarian on D (no penalty yet).
        prev_assignment = self._hungarian(D, linear_sum_assignment, n_agents, n_tasks)
        self.last_rounds_used = 1

        # Iterative refinement.
        for round_idx in range(1, self.max_rounds + 1):
            self.last_rounds_used = round_idx + 1
            # Precompute the set of cells occupied by each previous-round path.
            prev_path_sets: Dict[int, frozenset] = {}
            for i_prev, j_prev in prev_assignment.items():
                cells = P[i_prev][j_prev] if j_prev is not None else []
                prev_path_sets[i_prev] = frozenset(cells)

            C = np.copy(D)
            if self.lambda_conflict > 0.0:
                narrowness = self._narrowness
                for i in range(n_agents):
                    for j in range(n_tasks):
                        path_cells = P[i][j]
                        if not path_cells:
                            continue
                        path_set = frozenset(path_cells)
                        weighted_overlap = 0.0
                        for i_prev, prev_cells in prev_path_sets.items():
                            if i_prev == i:
                                continue
                            shared = path_set & prev_cells
                            if not shared:
                                continue
                            if narrowness is None:
                                weighted_overlap += float(len(shared))
                            else:
                                for c in shared:
                                    weighted_overlap += narrowness.get(c, 1.0)
                        C[i, j] += self.lambda_conflict * weighted_overlap

            new_assignment = self._hungarian(C, linear_sum_assignment, n_agents, n_tasks)
            if new_assignment == prev_assignment:
                break
            prev_assignment = new_assignment

        # Build final output dict: agent_id -> Task. Skip agents that
        # didn't get matched (when n_tasks < n_agents).
        for i, j in prev_assignment.items():
            if j is None:
                continue
            assignments[agent_ids[i]] = task_list[j]

        return assignments

    @staticmethod
    def _hungarian(
            cost_matrix: np.ndarray,
            linear_sum_assignment_fn,
            n_agents: int,
            n_tasks: int,
    ) -> Dict[int, Optional[int]]:
        """Run Hungarian assignment; return dict agent_idx -> task_idx (or None)."""
        out: Dict[int, Optional[int]] = {i: None for i in range(n_agents)}
        if n_agents == 0 or n_tasks == 0:
            return out
        row_ind, col_ind = linear_sum_assignment_fn(cost_matrix)
        for i, j in zip(row_ind, col_ind):
            if int(j) < n_tasks:
                out[int(i)] = int(j)
        return out

    def _bfs(
            self,
            start: Cell,
    ) -> Tuple[Dict[Cell, int], Dict[Cell, Optional[Cell]]]:
        """
        4-connected BFS from start over free cells in self._env.

        Returns (dist_map, parent_map). dist_map[cell] = shortest hop
        count from start; parent_map[cell] = predecessor cell on the
        shortest path (None for start). Unreachable cells are absent
        from both maps.
        """
        dist_map: Dict[Cell, int] = {start: 0}
        parent_map: Dict[Cell, Optional[Cell]] = {start: None}
        env = self._env
        if env is None or env.is_blocked(start):
            # If the agent's own cell is "blocked" we still treat it as
            # reachable from itself (distance 0) — this can happen if
            # the agent occupies an otherwise-walkable cell that was
            # not registered as free. Just return the trivial map.
            return dist_map, parent_map

        queue = deque([start])
        while queue:
            cur = queue.popleft()
            d_cur = dist_map[cur]
            for nxt in neighbors(cur):
                if nxt in dist_map:
                    continue
                if env.is_blocked(nxt):
                    continue
                dist_map[nxt] = d_cur + 1
                parent_map[nxt] = cur
                queue.append(nxt)
        return dist_map, parent_map

    @staticmethod
    def _reconstruct_path(
            parent_map: Dict[Cell, Optional[Cell]],
            start: Cell,
            goal: Cell,
    ) -> List[Cell]:
        """Reconstruct path from BFS parent map. Empty list if goal not reached."""
        if goal not in parent_map:
            return []
        path: List[Cell] = []
        cur: Optional[Cell] = goal
        while cur is not None:
            path.append(cur)
            cur = parent_map[cur]
        path.reverse()
        return path
