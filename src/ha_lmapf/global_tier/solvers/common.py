from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.types import TimedPath

Cell = Tuple[int, int]


# ----------------------------
# CBS Constraints
# ----------------------------

@dataclass(frozen=True)
class VertexConstraint:
    agent_id: int
    cell: Cell
    time: int  # absolute timestep


@dataclass(frozen=True)
class EdgeConstraint:
    agent_id: int
    from_cell: Cell
    to_cell: Cell
    time: int  # absolute timestep for the transition (time-1 -> time)


class ConstraintSet:
    """
    Fast lookup structure for constraints for a single CBS node.
    Stores both vertex and edge constraints keyed by (agent_id, time).
    """

    def __init__(
            self,
            vertex: Optional[Iterable[VertexConstraint]] = None,
            edge: Optional[Iterable[EdgeConstraint]] = None,
    ) -> None:
        self._v: Dict[Tuple[int, int], Set[Cell]] = {}
        self._e: Dict[Tuple[int, int], Set[Tuple[Cell, Cell]]] = {}

        if vertex is not None:
            for vc in vertex:
                self.add_vertex(vc)
        if edge is not None:
            for ec in edge:
                self.add_edge(ec)

    def add_vertex(self, vc: VertexConstraint) -> None:
        key = (vc.agent_id, vc.time)
        self._v.setdefault(key, set()).add(vc.cell)

    def add_edge(self, ec: EdgeConstraint) -> None:
        key = (ec.agent_id, ec.time)
        self._e.setdefault(key, set()).add((ec.from_cell, ec.to_cell))

    def violates_vertex(self, agent_id: int, cell: Cell, time: int) -> bool:
        return cell in self._v.get((agent_id, time), set())

    def violates_edge(self, agent_id: int, from_cell: Cell, to_cell: Cell, time: int) -> bool:
        return (from_cell, to_cell) in self._e.get((agent_id, time), set())

    def copy(self) -> ConstraintSet:
        """
        Create a deep copy of the constraint set.
        This handles the internal dictionary copying safely within the class.
        """
        new_cs = ConstraintSet()
        # Direct dict comprehension is more efficient than iterating and re-adding
        new_cs._v = {k: set(v) for k, v in self._v.items()}
        new_cs._e = {k: set(v) for k, v in self._e.items()}
        return new_cs


# --------------------------------------------------------------------
# Low-level A* with constraints --------------------------------------

def a_star_constrained(
        env,
        start: Cell,
        goal: Cell,
        agent_id: int,
        start_step: int,
        horizon: int,
        constraints: ConstraintSet,
) -> List[Cell]:
    """
    Low-level planner used by CBS and prioritized planning.

    Plans on a time-expanded state space (cell, t) from t=start_step to t=start_step+horizon,
    respecting:
      - static obstacles via env.is_free
      - vertex constraints (agent_id, cell, t)
      - edge constraints (agent_id, from, to, t) for transitions to time t

    Returns a list of cells of length (horizon+1) including start cell at start_step.
    If goal is reached early, the path is padded with goal (WAIT).
    If no path is found, returns an empty list.
    """
    if horizon < 0:
        return []

    # Quick reject: start or goal invalid
    if not env.is_free(start) or (goal is not None and not env.is_free(goal)):
        return []

    t0 = start_step
    t_max = start_step + horizon

    # Each node: (f, g, (cell, t))
    open_heap: List[Tuple[int, int, Tuple[Cell, int]]] = []
    heappush(open_heap, (manhattan(start, goal), 0, (start, t0)))

    came_from: Dict[Tuple[Cell, int], Tuple[Cell, int]] = {}
    g_score: Dict[Tuple[Cell, int], int] = {(start, t0): 0}

    def heuristic(c: Cell) -> int:
        return manhattan(c, goal)

    while open_heap:
        _, g, (cell, t) = heappop(open_heap)

        if t > t_max:
            continue

        # Vertex constraint at current state time
        if constraints.violates_vertex(agent_id, cell, t):
            continue

        # Goal test: we allow reaching goal before t_max
        if cell == goal:
            # Reconstruct and pad to horizon
            path = _reconstruct_path(came_from, (cell, t), start_step=t0)
            if not path:
                return []
            # Pad with goal to exact length horizon+1
            while len(path) < (horizon + 1):
                path.append(goal)
            return path[: horizon + 1]

        if t == t_max:
            # Can't go beyond horizon
            continue

        # Expand moves: 4-neighbors + WAIT
        for nb in neighbors(cell) + [cell]:
            if not env.is_free(nb):
                continue

            nt = t + 1

            # Vertex constraint at next time
            if constraints.violates_vertex(agent_id, nb, nt):
                continue
            # Edge constraint for the transition to time nt
            if constraints.violates_edge(agent_id, cell, nb, nt):
                continue

            state = (nb, nt)
            ng = g + 1
            if ng < g_score.get(state, 10 ** 9):
                g_score[state] = ng
                came_from[state] = (cell, t)
                heappush(open_heap, (ng + heuristic(nb), ng, state))

    # Goal not reachable within horizon — return best partial path (node at t_max closest to goal).
    # This avoids the all-WAIT fallback in LaCAM when goals are farther than `horizon` steps away,
    # which caused near-zero throughput for short horizons (e.g. horizon=20 on large maps).
    best_partial_state = None
    best_dist = float('inf')
    for state in g_score:
        cell, t = state
        if t == t_max:
            d = manhattan(cell, goal)
            if d < best_dist:
                best_dist = d
                best_partial_state = state

    if best_partial_state is not None:
        path = _reconstruct_path(came_from, best_partial_state, start_step=t0)
        if path:
            while len(path) < (horizon + 1):
                path.append(path[-1])
            return path[:horizon + 1]

    return []


def _reconstruct_path(
        came_from: Dict[Tuple[Cell, int], Tuple[Cell, int]],
        end_state: Tuple[Cell, int],
        start_step: int,
) -> List[Cell]:
    cell, t = end_state
    seq: List[Tuple[Cell, int]] = [(cell, t)]
    while seq[-1] in came_from:
        seq.append(came_from[seq[-1]])
    seq.reverse()

    # Ensure path starts at start_step
    if not seq or seq[0][1] != start_step:
        return []
    return [c for (c, _) in seq]


# --------------------------------------------------------------------
# Conflict detection -------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    kind: str  # "vertex" or "edge"
    time: int  # absolute time
    a1: int
    a2: int
    cell: Optional[Cell] = None
    edge: Optional[Tuple[Cell, Cell]] = None  # (a1_from->a1_to) for edge conflict


def detect_first_conflict(
        a1: int,
        path1: TimedPath,
        a2: int,
        path2: TimedPath,
) -> Optional[Conflict]:
    """
    Detect the first conflict between two timed paths.

    Assumptions:
      - Paths are sequences of cells; time for index i is (start_step + i).
      - If paths have different start_step, we compare on overlapping times by querying cell_at(t).

    Returns:
      - Conflict(kind="vertex", time=t, cell=cell) if both occupy same cell at time t
      - Conflict(kind="edge", time=t, edge=(from,to)) if they swap edges between t-1 and t
    """
    t_start = max(path1.start_step, path2.start_step)
    t_end = min(path1.start_step + len(path1.cells) - 1, path2.start_step + len(path2.cells) - 1)
    if t_end < t_start:
        return None

    # Vertex conflicts
    for t in range(t_start, t_end + 1):
        c1 = path1(t)
        c2 = path2(t)
        if c1 == c2:
            return Conflict(kind="vertex", time=t, a1=a1, a2=a2, cell=c1)

    # Edge swap conflicts
    for t in range(t_start + 1, t_end + 1):
        p1_prev = path1(t - 1)
        p1_cur = path1(t)
        p2_prev = path2(t - 1)
        p2_cur = path2(t)
        if p1_prev == p2_cur and p2_prev == p1_cur and p1_prev != p1_cur:
            return Conflict(kind="edge", time=t, a1=a1, a2=a2, edge=(p1_prev, p1_cur))

    return None
