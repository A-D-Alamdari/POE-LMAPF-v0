"""
Local A* Planner for Tier-2 reactive pathfinding.

This planner is used for local detours when the global plan is blocked
by dynamic obstacles (humans).

Supports two safety modes matching the paper's constraints:
  - Hard Safety (default): B_r(H_t) cells are impassable barriers.
    Agents MUST NOT enter the safety buffer (paper's strict constraint).
  - Soft Safety: B_r(H_t) cells incur high cost but are passable.
    Prevents permanent deadlock when humans surround an agent.
"""
from __future__ import annotations

from heapq import heappop, heappush
from typing import Dict, List, Optional, Set, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import LocalPlanner

Cell = Tuple[int, int]


class AStarLocalPlanner(LocalPlanner):
    """
    Single-agent A* planner for local detours.

    Safety Modes:
    - hard_safety=True (default): Blocked cells (dynamic obstacles/safety
      buffers) are treated as IMPASSABLE (Hard Constraints), matching the
      paper's requirement: s_i(t) not in B_r(H_t).
    - hard_safety=False: Blocked cells are HIGH COST (Soft Constraints).
      Agents can path through human zones if necessary (cost=50 per cell).
      This prevents agents from freezing when completely surrounded.
    """

    # Cost for moving through a blocked/safety zone cell (soft mode only)
    BLOCKED_CELL_COST = 50

    # Extra cost added per step for cells that deviate from the global guidance path.
    # Keeps A* path-aligned when a safe detour exists along the original route.
    GUIDANCE_DEVIATION_COST = 1

    # Maximum search expansions to prevent lag.
    # Must be large enough to handle long-range paths (e.g. 100+ step delivery
    # routes in pickup-delivery mode after Phase-1 completion).
    MAX_EXPANSIONS = 10_000

    def __init__(self, hard_safety: bool = True) -> None:
        """
        Initialize the local planner.

        Args:
            hard_safety: If True, blocked cells are impassable (paper's
                         strict B_r(H_t) constraint). If False, blocked
                         cells have high cost but are passable.
        """
        self.hard_safety = hard_safety

    def plan(
            self,
            env,
            start: Cell,
            goal: Cell,
            blocked: Set[Cell],
            guidance_cells: Optional[Set[Cell]] = None,
    ) -> List[Cell]:
        """
        Plan a path from start to goal, avoiding blocked cells.

        In hard safety mode, blocked cells cannot be traversed at all.
        In soft safety mode, blocked cells can be traversed at high cost.

        When guidance_cells is provided (remaining cells from the current
        global TimedPath), cells outside that set incur an extra
        GUIDANCE_DEVIATION_COST per step. This biases A* to stay close to
        the original global guidance when a safe on-path detour exists,
        while still routing freely when the guidance path is fully blocked.

        Args:
            env: The environment providing is_free() checks for static walls.
            start: Starting cell (row, col).
            goal: Target cell (row, col).
            blocked: Set of cells to avoid (dynamic obstacles, safety buffers).
            guidance_cells: Optional set of cells from the current global path
                            (from current step onward). Off-path cells get a
                            small extra cost to prefer path-aligned detours.

        Returns:
            A list of cells forming the path from start to goal (inclusive).
            Returns [start] if start == goal.
            Returns [] if no path exists.
        """
        if start == goal:
            return [start]

        # Static obstacles (Walls) are Hard Constraints - cannot pass through
        if not env.is_free(start):
            return []

        # If goal is a wall, no path possible
        if not env.is_free(goal):
            return []

        # Priority Queue: (f_score, g_score, current_cell)
        open_heap: List[Tuple[int, int, Cell]] = []

        # Start cost includes penalty if starting in a blocked zone (soft mode)
        if not self.hard_safety:
            start_cost = self.BLOCKED_CELL_COST if start in blocked else 0
        else:
            start_cost = 0

        heappush(open_heap, (start_cost + manhattan(start, goal), start_cost, start))

        came_from: Dict[Cell, Cell] = {}
        g_score: Dict[Cell, int] = {start: start_cost}

        expansions = 0

        while open_heap:
            _, g, cur = heappop(open_heap)
            expansions += 1

            if expansions > self.MAX_EXPANSIONS:
                # Expansion budget exhausted — abort (caller Safe-Waits).
                # The post-loop ``return []`` (~40 lines below) is reached
                # via this break; no partial path is reconstructed.
                break

            if cur == goal:
                return self._reconstruct(came_from, cur)

            # Skip if we've already found a better path to this cell
            if g > g_score.get(cur, float('inf')):
                continue

            for nb in neighbors(cur):
                # Hard Constraint: Cannot pass through static walls
                if not env.is_free(nb):
                    continue

                if nb in blocked:
                    if self.hard_safety:
                        # Hard Safety: blocked cells are impassable
                        continue
                    else:
                        # Soft Safety: high penalty but passable
                        step_cost = self.BLOCKED_CELL_COST
                else:
                    step_cost = 1

                # Prefer cells that lie on the original global guidance path.
                # Off-path cells get a small extra cost so A* stays aligned
                # with the global plan when a safe on-path detour exists.
                if guidance_cells is not None and nb not in guidance_cells:
                    step_cost += self.GUIDANCE_DEVIATION_COST

                ng = g + step_cost

                if ng < g_score.get(nb, float('inf')):
                    g_score[nb] = ng
                    came_from[nb] = cur
                    # Heuristic is standard Manhattan distance
                    f_score = ng + manhattan(nb, goal)
                    heappush(open_heap, (f_score, ng, nb))

        return []

    @staticmethod
    def _reconstruct(came_from: Dict[Cell, Cell], cur: Cell) -> List[Cell]:
        """Reconstruct the path by following came_from pointers."""
        path = [cur]
        while cur in came_from:
            cur = came_from[cur]
            path.append(cur)
        return path[::-1]
