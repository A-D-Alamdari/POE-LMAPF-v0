"""
Safety and Proximity Utilities.

This module provides geometric functions to manage the interaction between
agents and dynamic obstacles (humans). It handles:
  1. Safety Buffers: Creating "forbidden zones" around humans using Manhattan distance inflation.
  2. Proximity Costs: Calculating soft penalties for heuristic search to encourage distancing.

These utilities rely on the environment (grid) to ensure that safety masks do not
incorrectly label static obstacles (walls) as "safe but occupied".
"""
from __future__ import annotations

from typing import Dict, Set, Tuple

from ha_lmapf.core.types import HumanState

Cell = Tuple[int, int]


def inflate_cells(cells: Set[Cell], radius: int, env) -> Set[Cell]:
    """
    Inflate a set of seed cells into a 'Manhattan Ball' (diamond) of a given radius.

    This is used to create a hard safety buffer around humans. If a human is at (r, c)
    and radius is 1, the result includes (r, c) plus the 4 adjacent neighbors.

    Constraint Logic:
      - Boundary Check: Cells outside the grid are ignored.
      - Static Obstacle Check: Cells that are walls/obstacles in `env` are ignored.
        This keeps the mask "tight" and prevents the planner from trying to wait
        inside a wall just because it's technically inside the safety radius.

    Args:
        cells: A set of (row, col) coordinates (e.g., current human positions).
        radius: The L1 (Manhattan) radius of inflation.
        env: The environment object (must expose .width, .height, and .is_free()).

    Returns:
        A set of (row, col) coordinates representing the inflated safety zone.
    """
    if radius <= 0 or not cells:
        # Optimization: Return only valid free cells from input set
        return {c for c in cells if env.is_free(c)}

    inflated: Set[Cell] = set()
    w, h = env.width, env.height

    for (cr, cc) in cells:
        # Manhattan ball enumeration (deterministic order in loops)
        # Iterate over the Manhattan Diamond (L1 Ball)
        # abs(dr) + abs(dc) <= radius
        for dr in range(-radius, radius + 1):
            rem = radius - abs(dr)
            rr = cr + dr

            # Fast boundary check for rows
            if rr < 0 or rr >= h:
                continue

            for dc in range(-rem, rem + 1):
                cc2 = cc + dc

                # Fast boundary check for cols
                if cc2 < 0 or cc2 >= w:
                    continue

                cell = (rr, cc2)

                # Only mark as unsafe if it's actually traversable ground
                if env.is_free(cell):
                    inflated.add(cell)

    return inflated


def proximity_penalty(cell: Cell, human_cells: Set[Cell], radius: int) -> int:
    """
    Calculate a soft heuristic penalty based on proximity to the nearest human.

    Used by local search algorithms (like A*) to differentiate between "safe" cells.
    Even if a cell is not strictly forbidden, being adjacent to a human might incur
    a cost to prefer paths with higher clearance.

    Formula:
      Cost = max(0, radius - distance + 1)

      Example (Radius=2):
        - Distance 0 (on top of human): Cost 3
        - Distance 1 (adjacent): Cost 2
        - Distance 2: Cost 1
        - Distance 3+: Cost 0

    Args:
        cell: The (row, col) to evaluate.
        human_cells: The set of current human positions.
        radius: The distance threshold where the penalty drops to zero.

    Returns:
        An integer penalty value >= 0.
    """
    if radius <= 0 or not human_cells:
        return 0

    r, c = cell
    min_dist = None

    # Find distance to the closest human
    # Note: For very large numbers of humans, a spatial index (k-d tree)
    # would be faster, but linear scan is fine for <100 humans.
    for (hr, hc) in human_cells:
        d = abs(r - hr) + abs(c - hc)

        if min_dist is None or d < min_dist:
            min_dist = d
            if min_dist == 0:
                break

    if min_dist is None or min_dist > radius:
        return 0

    return int(radius - min_dist + 1)


def forbidden_mask(visible_humans: Dict[int, HumanState], radius: int, env) -> Set[Cell]:
    """
    Compute the complete set of forbidden cells based on visible humans.

    This is the primary interface used by the Local Planner (Algorithm 2) to
    determine which cells are temporarily blocked by dynamic obstacles.

    Args:
        visible_humans: Dictionary of humans currently in the agent's FOV.
        radius: The safety buffer radius.
        env: The simulation environment.

    Returns:
        A set of (row, col) coordinates that agents must not enter.
    """
    human_cells: Set[Cell] = {h.pos for h in visible_humans.values()}
    return inflate_cells(human_cells, radius=radius, env=env)
