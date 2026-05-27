"""
WHCA* (Windowed Hierarchical Cooperative A*) Baseline.

Implementation of the classic Silver (2005) WHCA* algorithm as a
global planner baseline. Each agent plans a short-window path using
a reservation table built from all previously planned agents' paths.

This is a prioritized planning approach:
  1. Order agents by priority (e.g., distance to goal).
  2. For each agent, plan a shortest path over a window W
     while respecting reservations from higher-priority agents.
  3. Reserve the new path in the reservation table.
  4. Repeat for next agent.

Key characteristics:
  - Sub-optimal but fast (O(k * A* cost) per replan).
  - Incomplete (may fail if prioritization causes deadlock).
  - The 'window' W limits how far ahead each agent plans.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Dict, List, Optional, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import SimStateView
from ha_lmapf.core.types import PlanBundle, Task, TimedPath
from ha_lmapf.task_allocator.task_allocator import GreedyNearestTaskAllocator

Cell = Tuple[int, int]


class _ReservationTable:
    """Time-indexed reservation table for vertex and edge reservations."""

    def __init__(self) -> None:
        # vertex: (cell, time) -> agent_id
        self._vertex: Dict[Tuple[Cell, int], int] = {}
        # edge: (from_cell, to_cell, time) -> agent_id
        self._edge: Dict[Tuple[Cell, Cell, int], int] = {}

    def reserve_path(self, agent_id: int, cells: List[Cell], start_step: int) -> None:
        """Reserve all vertices and edges along a path."""
        for i, cell in enumerate(cells):
            t = start_step + i
            self._vertex[(cell, t)] = agent_id
            if i > 0:
                self._edge[(cells[i - 1], cell, t)] = agent_id

    def is_vertex_free(self, cell: Cell, time: int, agent_id: int) -> bool:
        """Check if a vertex is free at a given time (ignoring own reservations)."""
        occupier = self._vertex.get((cell, time))
        return occupier is None or occupier == agent_id

    def is_edge_free(self, from_cell: Cell, to_cell: Cell, time: int, agent_id: int) -> bool:
        """Check if an edge is free (no swap conflict)."""
        # Forward edge
        occupier = self._edge.get((from_cell, to_cell, time))
        if occupier is not None and occupier != agent_id:
            return False
        # Swap check: the other agent going from to_cell to from_cell at same time
        occupier = self._edge.get((to_cell, from_cell, time))
        if occupier is not None and occupier != agent_id:
            return False
        return True


def _whca_star_single(
        env,
        agent_id: int,
        start: Cell,
        goal: Cell,
        start_step: int,
        window: int,
        table: _ReservationTable,
) -> List[Cell]:
    """
    Plan a single agent's path using windowed A* with reservation table.

    Returns a list of cells of length (window + 1).
    Falls back to waiting at start if no path found.
    """
    t0 = start_step
    t_max = start_step + window

    open_heap: List[Tuple[int, int, Tuple[Cell, int]]] = []
    heappush(open_heap, (manhattan(start, goal), 0, (start, t0)))

    came_from: Dict[Tuple[Cell, int], Tuple[Cell, int]] = {}
    g_score: Dict[Tuple[Cell, int], int] = {(start, t0): 0}

    best_state: Tuple[Cell, int] = (start, t0)
    best_h: int = manhattan(start, goal)

    while open_heap:
        f, g, (cell, t) = heappop(open_heap)

        if not table.is_vertex_free(cell, t, agent_id):
            continue

        h = manhattan(cell, goal)
        if h < best_h:
            best_h = h
            best_state = (cell, t)

        # Goal reached within window
        if cell == goal:
            path = _reconstruct(came_from, (cell, t), t0)
            while len(path) < window + 1:
                path.append(goal)
            return path[:window + 1]

        if t >= t_max:
            continue

        for nb in neighbors(cell) + [cell]:
            if not env.is_free(nb):
                continue

            nt = t + 1
            if not table.is_vertex_free(nb, nt, agent_id):
                continue
            if nb != cell and not table.is_edge_free(cell, nb, nt, agent_id):
                continue

            state = (nb, nt)
            ng = g + 1
            if ng < g_score.get(state, 10 ** 9):
                g_score[state] = ng
                came_from[state] = (cell, t)
                heappush(open_heap, (ng + manhattan(nb, goal), ng, state))

    # No path to goal; return best-effort path toward closest point
    path = _reconstruct(came_from, best_state, t0)
    while len(path) < window + 1:
        path.append(path[-1])
    return path[:window + 1]


def _reconstruct(
        came_from: Dict[Tuple[Cell, int], Tuple[Cell, int]],
        end_state: Tuple[Cell, int],
        start_step: int,
) -> List[Cell]:
    cell, t = end_state
    seq: List[Tuple[Cell, int]] = [(cell, t)]
    while seq[-1] in came_from:
        seq.append(came_from[seq[-1]])
    seq.reverse()
    if not seq or seq[0][1] != start_step:
        return [end_state[0]]
    return [c for c, _ in seq]


@dataclass
class WHCAStarPlanner:
    """
    WHCA* global planner baseline.

    Replans periodically using prioritized planning with a reservation table.
    Priority is assigned by distance to goal (closer = higher priority).
    """

    horizon: int = 50
    replan_every: int = 25
    window: int = 16  # WHCA* planning window (W)

    allocator: object = field(init=False)
    last_planned_step: int = field(default=-10 ** 9, init=False)

    def __post_init__(self) -> None:
        self.horizon = int(self.horizon)
        self.replan_every = max(1, int(self.replan_every))
        self.window = max(1, int(self.window))
        self.allocator = GreedyNearestTaskAllocator()

    def step(self, sim_state: SimStateView) -> Optional[PlanBundle]:
        cur_step = int(sim_state.step)

        if cur_step % self.replan_every != 0:
            return None

        # Task allocation
        open_tasks: List[Task] = []
        if hasattr(sim_state, "pop_open_tasks"):
            open_tasks = list(getattr(sim_state, "pop_open_tasks")())
        elif hasattr(sim_state, "open_tasks"):
            open_tasks = list(getattr(sim_state, "open_tasks"))

        assignments = self.allocator.assign(
            sim_state.agents, open_tasks, cur_step, rng=None
        )

        if hasattr(sim_state, "mark_task_assigned"):
            for aid, task in assignments.items():
                getattr(sim_state, "mark_task_assigned")(task, aid)

        # Return unassigned tasks
        assigned_ids = {t.task_id for t in assignments.values()}
        leftover = [t for t in open_tasks if t.task_id not in assigned_ids]
        if leftover and hasattr(sim_state, "open_tasks"):
            getattr(sim_state, "open_tasks").extend(leftover)

        # Build goals (phase-aware)
        goals: Dict[int, Cell] = {}
        for aid, a in sim_state.agents.items():
            if a.goal is not None:
                goals[aid] = a.goal
            elif aid in assignments:
                goals[aid] = assignments[aid].goal
            else:
                goals[aid] = a.pos

        # Prioritized planning with reservation table
        table = _ReservationTable()
        paths: Dict[int, TimedPath] = {}

        # Sort agents by distance to goal (ascending = higher priority)
        agent_order = sorted(
            goals.keys(),
            key=lambda aid: manhattan(sim_state.agents[aid].pos, goals[aid]),
        )

        w = min(self.window, self.horizon)

        for aid in agent_order:
            start = sim_state.agents[aid].pos
            goal = goals[aid]

            cells = _whca_star_single(
                env=sim_state.env,
                agent_id=aid,
                start=start,
                goal=goal,
                start_step=cur_step,
                window=w,
                table=table,
            )

            table.reserve_path(aid, cells, cur_step)

            # Pad to full horizon
            while len(cells) < self.horizon + 1:
                cells.append(cells[-1])

            paths[aid] = TimedPath(cells=cells[:self.horizon + 1], start_step=cur_step)

        self.last_planned_step = cur_step

        return PlanBundle(
            paths=paths,
            created_step=cur_step,
            horizon=self.horizon,
        )
