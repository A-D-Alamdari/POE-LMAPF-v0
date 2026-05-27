"""
GUI Visualization Package.

This package provides a lightweight PyGame-based visualizer for the HAL-MAPF simulation.
It handles:
  - Rendering the grid, static obstacles, and entities.
  - Interactive controls (Pause, Step).
  - UI State management (toggling layers).
"""

from .visualizer import Visualizer
from .ui_state import UIState

__all__ = [
    "Visualizer",
    "UIState",
]
