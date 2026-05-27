# Baselines Module

The baselines module provides comparison algorithms and ablation variants for evaluating the two-tier HA-LMAPF architecture. These baselines help isolate the contribution of different system components.

## Module Overview

```
baselines/
├── __init__.py
├── global_only_replan.py  # No local reactive planning
├── ignore_humans.py       # Human-unaware ablation
├── pibt_only.py           # Decentralized greedy baseline
├── rhcr_like.py           # RHCR-style periodic replanning
└── whca_star.py           # WHCA* prioritized planning
```

## Baseline Controllers

### Global-Only Controller (`global_only_replan.py`)

**Purpose**: Evaluate the contribution of Tier-2 local replanning.

**Behavior**:
- Follows Tier-1 global plan exactly
- No local detours around humans
- WAITs if next planned cell is blocked by visible human
- Uses ConflictResolver for agent-agent conflicts only

```python
@dataclass
class GlobalOnlyController:
    agent_id: int
    conflict_resolver: ConflictResolver

    def decide_action(self, sim_state, observation, rng=None) -> StepAction:
        """
        Follow global plan; WAIT if blocked by human.
        No local replanning or dynamic avoidance.
        """
```

**Expected Outcome**: Higher collision rates and more waiting when humans block planned paths.

### Ignore Humans Helper (`ignore_humans.py`)

**Purpose**: Ablation for human-awareness evaluation.

**Behavior**:
- Removes all human information from observations
- Controllers/planners see no humans
- Simulates classical MAPF behavior in human-populated environments

```python
def mask_out_humans(observation: Observation) -> Observation:
    """
    Returns modified observation with:
    - visible_humans: empty
    - blocked: human cells removed
    - visible_agents: unchanged
    """
```

**Usage**:
```python
# Apply to observation before controller decision
masked_obs = mask_out_humans(observation)
action = controller.decide_action(sim_state, masked_obs)
```

**Expected Outcome**: Maximum collision rates, baseline for safety metrics.

### PIBT-Only Controller (`pibt_only.py`)

**Purpose**: Evaluate fully decentralized planning without global coordination.

**Behavior**:
- Ignores global plans entirely
- Greedy movement toward current goal (minimize Manhattan distance)
- Uses PriorityRulesResolver for agent-agent conflicts
- No centralized path computation

```python
@dataclass
class PIBTOnlyController:
    agent_id: int
    resolver: PriorityRulesResolver

    def decide_action(self, sim_state, observation, rng=None) -> StepAction:
        """
        Greedy move toward goal with priority-based conflict resolution.
        """
```

**Algorithm**:
1. Get feasible neighbors (free, unblocked)
2. Select cell minimizing Manhattan distance to goal
3. Resolve conflicts via priority rules
4. Tie-break: prefer current position, then deterministic ordering

**Expected Outcome**: Sub-optimal paths, potential for congestion and deadlocks.

## Baseline Planners

### RHCR-Like Planner (`rhcr_like.py`)

**Purpose**: Implement Receding Horizon Conflict Resolution baseline.

**Behavior**:
- Periodic replanning at fixed intervals
- Solves horizon-H MAPF from current positions
- Agents execute k steps before next replan
- Uses standard CBS or LaCAM solver

```python
@dataclass
class RHCRPlanner:
    horizon: int        # Planning horizon H
    replan_every: int   # Replan interval
    solver_name: str    # "cbs" or "lacam"
    k: int = 1          # Steps before replan

    def step(self, sim_state) -> Optional[PlanBundle]:
        """
        Periodic MAPF solve; allocates tasks and plans paths.
        """
```

**Configuration**:
- `replan_every=1`: Strict k=1 RHCR (replan every step)
- Higher values trade optimality for computation

**Expected Outcome**: Good path quality, high computational cost for large k.

### WHCA* Planner (`whca_star.py`)

**Purpose**: Implement Windowed Hierarchical Cooperative A* baseline.

**Behavior**:
- Prioritized planning with reservation tables
- Each agent plans window-W path respecting reservations
- Priority based on distance to goal (closer = higher)
- Sub-optimal but fast

```python
@dataclass
class WHCAStarPlanner:
    horizon: int = 50     # Full planning horizon
    replan_every: int = 25
    window: int = 16      # WHCA* window W

    def step(self, sim_state) -> Optional[PlanBundle]:
        """
        Prioritized planning with temporal reservations.
        """
```

**Algorithm**:
1. Order agents by goal distance (ascending)
2. For each agent:
   - Plan A* path over window W
   - Avoid vertex/edge conflicts with reservations
   - Reserve the computed path
3. Pad paths to horizon length

**Reservation Table**:
```python
class _ReservationTable:
    def reserve_path(agent_id, cells, start_step) -> None
    def is_vertex_free(cell, time, agent_id) -> bool
    def is_edge_free(from_cell, to_cell, time, agent_id) -> bool
```

**Expected Outcome**: Fast but potentially incomplete; may fail on tight scenarios.

## Comparison Matrix

| Baseline | Global Plan | Local Replan | Human-Aware | Optimal |
|----------|-------------|--------------|-------------|---------|
| Full System (Two-Tier) | Yes | Yes | Yes | Near-optimal |
| Global-Only | Yes | No | Partial | Near-optimal |
| Ignore Humans | Yes | Yes | No | N/A |
| PIBT-Only | No | Yes | Yes | No |
| RHCR-Like | Yes | No | No | Near-optimal |
| WHCA* | Yes | No | No | No |

## Usage in Experiments

### Controller-Level Baselines

```python
from ha_lmapf.baselines.global_only_replan import make_global_only_controllers
from ha_lmapf.baselines.pibt_only import PIBTOnlyController

# Use global-only controllers instead of full AgentController
controllers = make_global_only_controllers(
    sim_state=sim,
    conflict_resolver=resolver,
    fov_radius=5,
    safety_radius=2,
)
```

### Planner-Level Baselines

```python
from ha_lmapf.baselines.rhcr_like import RHCRPlanner
from ha_lmapf.baselines.whca_star import WHCAStarPlanner

# Replace RollingHorizonPlanner
planner = RHCRPlanner(horizon=50, replan_every=10, solver_name="lacam")
# or
planner = WHCAStarPlanner(horizon=50, replan_every=25, window=16)
```

### Ablation Studies

```python
from ha_lmapf.baselines.ignore_humans import mask_out_humans

# Run human-unaware experiment
for step in range(num_steps):
    for aid in agents:
        obs = build_observation(aid, sim, fov_radius)
        masked_obs = mask_out_humans(obs)  # Ablate human awareness
        action = controller.decide_action(sim, masked_obs)
```

## Experimental Design

### Recommended Comparisons

1. **Two-Tier vs. Global-Only**: Measures value of local reactive planning
2. **Two-Tier vs. Ignore-Humans**: Measures value of human awareness
3. **Two-Tier vs. PIBT-Only**: Measures value of global coordination
4. **RHCR vs. WHCA***: Compares centralized replanning approaches

### Key Metrics

| Metric | Measures |
|--------|----------|
| Tasks Completed | Overall efficiency |
| Agent-Human Collisions | Safety |
| Wait Steps | Congestion/deadlock |
| Makespan | Time to completion |
| Sum-of-Costs | Path optimality |
| Planning Time | Computational overhead |

## Related Modules

- [Global Tier](../global_tier/README_GLOBAL_TIER.md) - Full global planner
- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Full local controller
- [Conflict Resolution](../local_tier/conflict_resolution/README_CONFLICT_RESOLUTION.md) - Resolvers used by baselines
- [Core Interfaces](../core/README_CORE.md) - SimStateView protocol
