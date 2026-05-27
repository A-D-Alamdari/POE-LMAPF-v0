# Core Module

The core module provides fundamental data structures, type definitions, interfaces, and grid utilities used throughout
the HA-LMAPF system.

## Files

| File            | Description                               |
|-----------------|-------------------------------------------|
| `types.py`      | Core data type definitions                |
| `interfaces.py` | Protocol interfaces for system components |
| `grid.py`       | Grid geometry and graph utilities         |
| `metrics.py`    | Simulation metrics tracking               |

---

## `types.py` - Core Type Definitions

Defines fundamental data structures with serialization support.

### Enums

```python
class StepAction(Enum):
    """Discrete movement actions for grid navigation."""
    UP = "UP"  # Decrease row (move north)
    DOWN = "DOWN"  # Increase row (move south)
    LEFT = "LEFT"  # Decrease column (move west)
    RIGHT = "RIGHT"  # Increase column (move east)
    WAIT = "WAIT"  # Stay in place
```

### Data Classes

| Class         | Description                | Key Fields                                    |
|---------------|----------------------------|-----------------------------------------------|
| `AgentState`  | Agent state representation | `agent_id`, `pos`, `goal`, `wait_steps`       |
| `HumanState`  | Human state representation | `human_id`, `pos`, `velocity`                 |
| `Task`        | Pickup-delivery task       | `task_id`, `start`, `goal`, `release_step`    |
| `TimedPath`   | Time-indexed path          | `cells`, `start_step`                         |
| `PlanBundle`  | Collection of agent plans  | `paths`, `created_step`, `horizon`            |
| `Observation` | Agent's local observation  | `visible_humans`, `visible_agents`, `blocked` |
| `Metrics`     | Performance metrics        | `throughput`, `collisions`, `flowtime`, etc.  |
| `SimConfig`   | Simulation configuration   | `mode`, `map_path`, `num_agents`, etc.        |

### Example Usage

```python
from ha_lmapf.core.types import AgentState, Task, StepAction

# Create an agent
agent = AgentState(agent_id=0, pos=(5, 3), goal=(10, 8))

# Create a task
task = Task(task_id="task_001", start=(2, 2), goal=(8, 8), release_step=0)

# Access action
action = StepAction.RIGHT
```

---

## `interfaces.py` - Protocol Interfaces

Defines architectural boundaries using Python Protocols.

### Core Protocols

| Protocol           | Purpose                               | Key Methods                                       |
|--------------------|---------------------------------------|---------------------------------------------------|
| `GlobalPlanner`    | Tier-1 multi-agent path planning      | `plan(agents, env, start_step, horizon)`          |
| `LocalPlanner`     | Tier-2 single-agent reactive planning | `plan(env, start, goal, blocked)`                 |
| `TaskAllocator`    | Task assignment to agents             | `allocate(agents, open_tasks, env)`               |
| `ConflictResolver` | Agent-agent conflict resolution       | `resolve(agent_id, desired_cell, sim_state, obs)` |
| `HumanPredictor`   | Human motion forecasting              | `predict(humans, horizon, rng)`                   |

### SimStateView Protocol

Read-only view of simulation state for controllers:

```python
class SimStateView(Protocol):
    @property
    def agents(self) -> Dict[int, AgentState]: ...

    @property
    def humans(self) -> Dict[int, HumanState]: ...

    @property
    def env(self) -> Environment: ...

    @property
    def step(self) -> int: ...

    def plans(self) -> Optional[PlanBundle]: ...

    def decided_next_positions(self) -> Dict[int, Cell]: ...
```

---

## `grid.py` - Grid Geometry Utilities

Helper functions for 2D grid navigation.

### Functions

| Function                          | Description                       | Example                                           |
|-----------------------------------|-----------------------------------|---------------------------------------------------|
| `in_bounds(cell, width, height)`  | Check if cell is within grid      | `in_bounds((5,3), 10, 10) → True`                 |
| `manhattan(a, b)`                 | Manhattan distance                | `manhattan((0,0), (3,4)) → 7`                     |
| `neighbors(cell)`                 | Get 4-connected neighbors         | `neighbors((2,2)) → [(1,2), (3,2), (2,1), (2,3)]` |
| `rc_to_index(cell, width)`        | Convert (row,col) to linear index | `rc_to_index((1, 2), 10) → 12`                    |
| `index_to_rc(idx, width)`         | Convert linear index to (row,col) | `index_to_rc(12, 10) → (1, 2)`                    |
| `apply_action(cell, action)`      | Apply action to get new position  | `apply_action((2,2), UP) → (1,2)`                 |
| `line_of_sight_circle(center, r)` | Get cells within Manhattan radius | Returns set of cells                              |

### Example Usage

```python
from ha_lmapf.core.grid import manhattan, neighbors, apply_action
from ha_lmapf.core.types import StepAction

# Distance calculation
dist = manhattan((0, 0), (5, 3))  # Returns 8

# Get neighboring cells
nbrs = neighbors((2, 2))  # [(1,2), (3,2), (2,1), (2,3)]

# Apply movement
new_pos = apply_action((2, 2), StepAction.UP)  # (1, 2)
```

---

## `metrics.py` - Metrics Tracking

Comprehensive performance metrics collection.

### MetricsTracker Class

Tracks simulation statistics:

| Category            | Metrics                                                                 |
|---------------------|-------------------------------------------------------------------------|
| **Service Quality** | `throughput`, `mean_flowtime`, `median_flowtime`, `max_flowtime`        |
| **Safety**          | `collisions_agent_agent`, `collisions_agent_human`, `safety_violations` |
| **Efficiency**      | `replans`, `global_replans`, `local_replans`, `total_wait_steps`        |
| **Timing**          | `mean_planning_time_ms`, `p95_planning_time_ms`, `max_planning_time_ms` |
| **Cost**            | `makespan`, `sum_of_costs`                                              |

### Methods

```python
tracker = MetricsTracker()

# Task lifecycle
tracker.on_task_released("task_001", release_step=0)
tracker.on_task_assigned("task_001", agent_id=0, step=5)
tracker.on_task_completed("task_001", agent_id=0, step=20)

# Event counters
tracker.add_agent_agent_collision()
tracker.add_safety_violation()
tracker.record_planning_time_ms(150.5)

# Finalize and export
metrics = tracker.finalize(total_steps=1000)
csv_row = tracker.to_csv_row(metrics)
```

---

## Dependencies

This module has minimal external dependencies:

- `numpy` for statistical calculations in metrics
- Standard library: `dataclasses`, `enum`, `typing`

---

## Related Modules

- [Simulation](../simulation/README_SIMULATION.md) - Uses core types for state management
- [Global Tier](../global_tier/README_GLOBAL_TIER.md) - Implements GlobalPlanner protocol
- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Implements LocalPlanner, ConflictResolver protocols
