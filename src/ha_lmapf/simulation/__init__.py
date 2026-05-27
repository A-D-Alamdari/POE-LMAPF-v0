"""
Simulation Engine.

This package orchestrates the interaction between:
1. The Static Environment (grid/map).
2. The Dynamic Agents (agents).
3. The Dynamic Obstacles (humans).
4. The Planners (Global Tier-1 and Local Tier-2).
"""

from .environment import Environment
from .simulator import Simulator
from .events import (
    Collision,
    NearMiss,
    TaskAssigned,
    TaskCompleted,
)

__all__ = [
    "Environment",
    "Simulator",
    "Collision",
    "NearMiss",
    "TaskAssigned",
    "TaskCompleted",
]