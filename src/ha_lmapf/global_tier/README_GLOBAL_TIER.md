# Global Tier (Tier-1)

The global tier implements centralized, deliberative planning for multi-agent coordination. It operates on a rolling
horizon and handles task allocation and collision-free path planning.

## Overview

```
┌─────────────────────────────────────────────────────┐
│                  GLOBAL TIER (Tier-1)               │
├─────────────────────────────────────────────────────┤
│  Input:                                             │
│    • Agent states (positions, goals)                │
│    • Open tasks                                     │
│    • Static environment                             │
│                                                     │
│  Processing:                                        │
│    1. Task Allocation (assign tasks to agents)      │
│    2. Path Planning (compute collision-free paths)  │
│    3. Bundle Creation (package paths for Tier-2)    │
│                                                     │
│  Output:                                            │
│    • PlanBundle with timed paths for all agents     │
└─────────────────────────────────────────────────────┘
```

## Files

| File                   | Description                                           |
|------------------------|-------------------------------------------------------|
| `rolling_horizon.py`   | Periodic replanning scheduler                         |
| `one_shot_planner.py`  | One-shot global planner for classical MAPF            |
| `planner_interface.py` | Solver factory (`GlobalPlannerFactory`) and utilities |
| `solvers/`             | MAPF solver implementations                           |

> **Note:** Task allocators live in `src/ha_lmapf/task_allocator/task_allocator.py`,
> not in the global tier. One-shot mode is handled by `Simulator._generate_one_shot_tasks()`
> and the `mode="one_shot"` flag in `SimConfig`.

---

## rolling_horizon.py - Rolling Horizon Planner

Periodic replanning for lifelong MAPF.

### RollingHorizonPlanner

```python
class RollingHorizonPlanner:
    """
    Tier-1 global planner that replans every K steps.

    Parameters:
        solver: GlobalPlanner - MAPF solver (CBS or LaCAM)
        horizon: int - Planning horizon in steps
        replan_every: int - Steps between replanning
    """
```

### Key Features

- **Periodic Replanning**: Automatically triggers replanning at configured intervals
- **Horizon Management**: Plans only `horizon` steps ahead
- **Handoff Detection**: Tracks when current plans expire

### Usage

```python
from ha_lmapf.global_tier.rolling_horizon import RollingHorizonPlanner
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver

planner = RollingHorizonPlanner(
    solver_impl=LaCAMOfficialSolver(),
    horizon=50,
    replan_every=25
)

# Called every step by Simulator.maybe_global_replan()
# Returns a PlanBundle if replanning fired, else None
bundle = planner.step(sim_state, assignments)
```

---

## task_allocator/ - Task Assignment

Task allocators live in `src/ha_lmapf/task_allocator/task_allocator.py`
(not inside the global tier directory).

### Available Allocators

| Allocator                    | Strategy            | Complexity    | Quality |
|------------------------------|---------------------|---------------|---------|
| `GreedyNearestTaskAllocator` | Assign nearest task | O(n×m)        | Good    |
| `HungarianTaskAllocator`     | Optimal assignment  | O(n³)         | Optimal |
| `AuctionBasedTaskAllocator`  | Distributed bidding | O(n×m×rounds) | Good    |

### Interface

```python
class GreedyNearestTaskAllocator(TaskAllocator):
    """
    Assigns each task to the nearest available idle agent
    (goal is None or pos == goal) by Manhattan distance to pickup.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        """Returns {agent_id: assigned_task} for newly assigned tasks only."""
```

### Usage

```python
from ha_lmapf.task_allocator.task_allocator import GreedyNearestTaskAllocator

allocator = GreedyNearestTaskAllocator()
assignments = allocator.assign(agents, open_tasks, step=sim.step)
# assignments = {0: Task(...), 1: Task(...), ...}
```

---

## planner_interface.py - Utilities

Factory functions and helpers for solver instantiation.

### GlobalPlannerFactory

```python
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory

solver = GlobalPlannerFactory.create("lacam")  # or "cbs", "lacam3", etc.
```

Supported names: `"cbs"`, `"lacam"`, `"lacam3"`, `"lacam_official"`,
`"pibt2"`, `"eecbs"`, `"cbsh2"`, `"lns2"`, `"pbs"`, `"rhcr"`.

---

## Solvers Subdirectory

See [README_SOLVERS.md](solvers/README_SOLVERS.md) for detailed solver documentation.

| Solver | Type                  | Optimality         | Speed |
|--------|-----------------------|--------------------|-------|
| CBS    | Conflict-Based Search | Optimal            | Slow  |
| LaCAM  | Prioritized Planning  | Bounded-suboptimal | Fast  |

---

## Integration with Tier-2

The global tier produces a `PlanBundle` consumed by local controllers:

```python
@dataclass
class PlanBundle:
    paths: Dict[int, TimedPath]  # agent_id -> path
    created_step: int  # When plan was created
    horizon: int  # How far ahead plan extends
```

Tier-2 controllers follow these paths when safe, and deviate locally when humans block the way.

---

## Configuration

In YAML config files:

```yaml
# Global planning settings
global_solver: "lacam"     # or "cbs"
horizon: 50                # Planning horizon
replan_every: 25           # Replanning interval
task_allocator: "congestion_avoidance"   # or "greedy", "hungarian", "auction"
```

---

## Related Modules

- [Solvers](solvers/README_SOLVERS.md) - MAPF algorithm implementations
- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Consumes plan bundles
- [Core](../core/README_CORE.md) - Type definitions