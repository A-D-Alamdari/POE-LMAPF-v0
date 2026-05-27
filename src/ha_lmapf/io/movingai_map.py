"""
MovingAI Map Loader.

This module provides functionality to parse map files in the MovingAI format (.map),
which is the standard benchmark format for Multi-Agent Pathfinding (MAPF).

The MovingAI format consists of a header specifying dimensions and a grid of
ASCII characters representing the terrain.

Format Reference:
    type octile
    height <int>
    width <int>
    map
    <grid rows...>

Character Interpretation:
    - '@': Static wall/obstacle (Blocked)
    - 'T': Tree/obstacle (Blocked)
    - '.': Open ground (Free)
    - 'G', 'S': Often used for swamp/water, treated here as Free for simplicity.
"""
from __future__ import annotations

import os.path
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Tuple

Cell = Tuple[int, int]


@dataclass(frozen=True)
class MapData:
    """
    Immutable container for static map information.

    Attributes:
        grid: A list of strings, where grid[r][c] is the character at row r, col c.
              Useful for visualization or debugging.
        width: The number of columns in the grid.
        height: The number of rows in the grid.
        blocked: A set of (row, col) coordinates representing static obstacles.
                 Used for fast collision checking (O(1) lookup).
    """
    grid: List[str]
    width: int
    height: int
    blocked: Set[Cell]


def load_movingai_map(path: str) -> MapData:
    """
    Load and parse a MovingAI .map file from disk.

    This function reads the header to determine dimensions and then parses the
    ASCII grid. It normalizes rows to ensure they match the specified width
    (handling potential trailing whitespace issues common in some benchmark files).

    Args:
        path: Absolute or relative file path to the .map file.

    Returns:
        A MapData object containing the parsed grid and the set of blocked cells.

    Raises:
        ValueError: If the file header is missing required fields (height, width, map)
                    or if the grid data does not match the header dimensions.
        FileNotFoundError: If the path does not exist.

    Example:
        >>> map_data = load_movingai_map("data/maps/warehouse.map")
        >>> (5, 10) in map_data.blocked
        True
    """
    assert os.path.exists(path), f"Invalid path: {path}"

    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f.readlines()]

    width = None
    height = None
    grid_start = None

    for idx, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("height"):
            height = int(line.split()[1])
        elif low.startswith("width"):
            width = int(line.split()[1])
        elif low == "map":
            grid_start = idx + 1
            break

    if width is None or height is None or grid_start is None:
        raise ValueError(f"Invalid MovingAI map format: {path}")

    grid = lines[grid_start: grid_start + height]
    if len(grid) != height:
        raise ValueError(f"Expected {height} map rows, got {len(grid)} in {path}")

    # Normalize row lengths (pad with spaces if short, though usually they shouldn't be)
    # Note: We slice [:width] to handle files that might have extra padding chars.
    grid = [row[:width].ljust(width) for row in grid]

    blocked: Set[Cell] = set()
    for r in range(height):
        row = grid[r]
        if len(row) < width:
            raise ValueError(f"Row {r} shorter than width={width} in {path}")
        for c in range(width):
            ch = row[c]
            # Standard MovingAI blocked characters
            if ch in ("@", "T"):
                blocked.add((r, c))
            # permissive: everything else is considered free

    return MapData(grid=grid, width=width, height=height, blocked=blocked)
