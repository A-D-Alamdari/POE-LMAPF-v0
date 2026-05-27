"""
Static Simulation Environment.

This module defines the `Environment` class, which represents the immutable
grid world where the simulation takes place. It serves as the single source
of truth for:
  1. Grid dimensions (width, height).
  2. Static obstacles (walls, trees, etc.).
  3. Valid coordinate checks (bounds checking).

The Environment is designed for fast O(1) lookups to support high-frequency
validity checks during planning and execution.
"""
from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from ha_lmapf.io.movingai_map import load_movingai_map

Cell = Tuple[int, int]


class Environment:
    """
    Discrete grid environment for MAPF-style simulations.

    Coordinate System:
      - Uses (row, col) format.
      - (0, 0) is the top-left corner.
      - Rows increase downwards, Columns increase rightwards.

    Attributes:
        width: Number of columns.
        height: Number of rows.
        blocked: Set of (row, col) coordinates that are static obstacles.
    """

    def __init__(self, width: int, height: int, blocked: Set[Cell]) -> None:
        """
        Initialize the environment.

        Args:
            width: Grid width (cols).
            height: Grid height (rows).
            blocked: Set of blocked coordinates.

        Raises:
            ValueError: If the resulting map has 0 free cells (impossible to place agents).
        """
        self.width = int(width)
        self.height = int(height)
        self.blocked: Set[Cell] = set(blocked)

        # Precompute free cells for fast sampling
        self._free_cells: List[Cell] = [
            (row, col)
            for row in range(self.height)
            for col in range(self.width)
            if (row, col) not in self.blocked
        ]

        if not self._free_cells:
            raise ValueError("Environment has no free cells.")

    def is_blocked(self, cell: Cell) -> bool:
        """
        Check if a cell is statically blocked or out of bounds.

        Args:
            cell: The (row, col) coordinate.

        Returns:
            True if the cell is a wall OR outside the grid limits.
        """
        row, col = cell
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return True
        return cell in self.blocked

    def is_free(self, cell: Cell) -> bool:
        """
        Check if a cell is valid for agent occupancy.

        Args:
            cell: The (row, col) coordinate.

        Returns:
            True if the cell is inside bounds AND not a wall.
        """
        row, col = cell
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return False
        return cell not in self.blocked

    def sample_free_cell(self, rng, exclude: Iterable[Cell] | None = None) -> Cell:
        """
        Sample a free cell uniformly at random.

        Used for:
          - Initial agent placement.
          - Generating random tasks.
          - Spawning humans.

        Args:
            rng: A numpy random generator (or similar with .integers method).
            exclude: Optional set of cells to avoid (e.g., already occupied cells).

        Returns:
            A valid (row, col) coordinate.

        Raises:
            RuntimeError: If no free cells remain after applying exclusions.
        """
        if exclude is None:
            exclude_set: Set[Cell] = set()
        else:
            exclude_set = set(exclude)

        candidates = [c for c in self._free_cells if c not in exclude_set]

        if not candidates:
            raise RuntimeError("No free cells available for sampling (after exclusion).")

        idx = int(rng.integers(0, len(candidates)))
        return candidates[idx]

    @classmethod
    def load_from_map(cls, path: str) -> "Environment":
        """
        Factory method to load an Environment from a MovingAI .map file.

        Args:
            path: Path to the .map file.

        Returns:
            A configured Environment instance.
        """
        map_data = load_movingai_map(path)
        return cls(
            width=map_data.width,
            height=map_data.height,
            blocked=map_data.blocked,
        )
