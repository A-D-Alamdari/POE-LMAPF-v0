# 1. Types (Data Structures)
from .types import (
    AgentState,
    HumanState,
    Task,
    TimedPath,
    PlanBundle,
    Observation,
    Metrics,
    SimConfig,
    StepAction,
)

# 2. Geometry Utilities
from .grid import (
    manhattan,
    neighbors,
    in_bounds,
    rc_to_index,
    index_to_rc,
    apply_action,
    line_of_sight_circle,
    iter_manhattan_ball,
)

# 3. Interfaces (Protocols)
from .interfaces import (
    SimStateView,
    TaskAllocator,
    GlobalPlanner,
    LocalPlanner,
    ConflictResolver,
    HumanPredictor,
)

# 4. Metrics Tracker
from .metrics import MetricsTracker

# Optional: Define __all__ to strictly control what 'from ha_lmapf.core import *' does
__all__ = [
    "AgentState", "HumanState", "Task", "TimedPath", "PlanBundle", 
    "Observation", "Metrics", "SimConfig", "StepAction",
    "manhattan", "neighbors", "in_bounds", "rc_to_index", "index_to_rc",
    "apply_action", "line_of_sight_circle", "iter_manhattan_ball",
    "SimStateView", "TaskAllocator", "GlobalPlanner", "LocalPlanner", 
    "ConflictResolver", "HumanPredictor",
    "MetricsTracker"
]