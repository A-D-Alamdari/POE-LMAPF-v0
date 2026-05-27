"""
Grid Geometry and Graph Utilities.

This module provides essential helper functions for navigating a 2D grid environment.
It handles:
  - Coordinate validity checks (bounds).
  - Distance metrics (Manhattan L1).
  - Neighbor generation (4-connected Von Neumann neighborhood).
  - Coordinate system conversions (2D (row, col) <-> 1D index).
  - Action application (calculating next state).
  - Field-of-view calculations (Manhattan balls).

Conventions:
  - Coordinates are given as (row, col).
  - Grid origin (0, 0) is the top-left corner.
  - 'width' corresponds to columns (x-axis), 'height' to rows (y-axis).
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

from ha_lmapf.core.types import StepAction

Cell = Tuple[int, int]


def in_bounds(cell: Cell, width: int, height: int) -> bool:
    """
    Check if a cell coordinate is strictly inside the grid boundaries.

    Args:
        cell: The (row, col) coordinate to check.
        width: The total width (number of columns) of the grid.
        height: The total height (number of rows) of the grid.

    Returns:
        True if 0 <= row < height and 0 <= col < width, False otherwise.
    """
    row, col = cell
    return 0 <= row < height and 0 <= col < width

def manhattan(cell1: Cell, cell2: Cell) -> int:
    """
    Calculate the Manhattan (L1) distance between two cells.

    Args:
        cell1: The first (row, col) coordinate.
        cell2: The second (row, col) coordinate.

    Returns:
        The sum of absolute differences in rows and columns:
        |r1 - r2| + |c1 - c2|.
    """
    row1, col1 = cell1
    row2, col2 = cell2
    return abs(row1 - row2) + abs(col1 - col2)

def neighbors(cell: Cell) -> List[Cell]:
    """
    Generate the 4-connected neighbors (Von Neumann neighborhood) of a cell.

    Note:
        This function returns potential coordinates (Up, Down, Left, Right)
        without checking if they are within grid bounds or blocked by obstacles.
        Bounds checking is the caller's responsibility.

    Args:
        cell: The center (row, col) coordinate.

    Returns:
        A list of four (row, col) tuples representing adjacent cells.
    """
    row, col = cell
    return [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]


def rc_to_index(cell: Cell, width: int) -> int:
    """
    Convert a 2D (row, col) coordinate to a flattened 1D index.

    This is useful for array-based map representations or hashing.

    Args:
        cell: The (row, col) coordinate.
        width: The number of columns in the grid.

    Returns:
        The scalar index: row * width + col.
    """
    row, col = cell
    return row * width + col

def index_to_rc(index: int, width: int) -> Cell:
    """
    Convert a flattened 1D index back to a 2D (row, col) coordinate.

    Args:
        index: The scalar index.
        width: The number of columns in the grid.

    Returns:
        A tuple (row, col).
    """
    row = index // width
    col = index % width
    return row, col

def apply_action(cell: Cell, action: StepAction) -> Cell:
    """
    Compute the resulting coordinate after applying a discrete action.

    Args:
        cell: The current (row, col) position.
        action: The StepAction to apply (UP, DOWN, LEFT, RIGHT, WAIT).

    Returns:
        The new (row, col) coordinate. This does not check for bounds/obstacles.

    Raises:
        ValueError: If an unknown action type is provided.
    """
    row, col = cell

    if action == StepAction.UP:
        return row - 1, col
    if action == StepAction.DOWN:
        return row + 1, col
    if action == StepAction.LEFT:
        return row, col - 1
    if action == StepAction.RIGHT:
        return row, col + 1
    if action == StepAction.WAIT:
        return row, col

    raise ValueError(f"Invalid action: {action}")


def line_of_sight_circle(center: Cell, radius: int) -> List[Cell]:
    """
    Return all cells within a Manhattan distance <= radius from the center.

    This defines a "Manhattan Ball" (a diamond shape). It is primarily used
    for simulating field-of-view (FOV) or proximity safety zones.

    Note:
        - "Circle" in the function name refers to the radius concept, but the
          shape is geometric L1 diamond.
        - No ray-casting is performed; walls do not block "sight" in this specific
          utility. Occlusion logic belongs in the sensor module.

    Args:
        center: The (row, col) center point.
        radius: The L1 radius (integer).

    Returns:
        A list of all (row, col) coordinates within the diamond area.
    """
    c_row, c_col = center
    cells: List[Cell] = []

    for d_row in range(-radius, radius + 1):
        rem = radius - abs(d_row)

        for d_col in range(-rem, rem + 1):
            cells.append((c_row + d_row, c_col + d_col))

    return cells


def iter_manhattan_ball(center: Cell, radius: int) -> Iterable[Cell]:
    """
    Generator version of `line_of_sight_circle`.

    Yields cells within the Manhattan ball one by one, which is more memory
    efficient for iterating over large areas or when early exit is possible.

    Args:
        center: The (row, col) center point.
        radius: The L1 radius.

    Yields:
        (row, col) coordinates within range.
    """
    c_row, c_col = center
    for d_row in range(-radius, radius + 1):
        rem = radius - abs(d_row)
        for d_col in range(-rem, rem + 1):
            yield c_row + d_row, c_col + d_col
