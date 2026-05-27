# Simulation Module

The simulation module is the central orchestration engine for
**Partially Observable Exogenous-agent Lifelong MAPF (POE-LMAPF)**
experiments.  It manages the complete simulation lifecycle: entity
dynamics, planning integration, collision detection, and metrics
recording.

> *Terminology.*  The paper text refers to dynamic non-controlled
> entities as **exogenous agents**.  The codebase uses ``human``
> (e.g. ``HumanState``, ``humans/`` package) for the same concept.

## Module Overview

```
simulation/
├── __init__.py
├── simulator.py       # Central simulation engine
├── environment.py     # Static grid environment
├── agent_dynamics.py  # Agent physics and state transitions
└── events.py          # Discrete event definitions
```

## Components

### Simulator (`simulator.py`)

The `Simulator` class is the main orchestration engine that manages:

1. **Environment Loading** - Static grid maps from MovingAI format
2. **Task Stream Management** - Lifelong task release and tracking
3. **Two-Tier Planning** - Global (RHCR) and Local (reactive) integration
4. **Human Motion Simulation** - Stochastic movement models
5. **Collision Detection** - Safety violation tracking
6. **Metrics Recording** - Performance statistics collection

#### Key Methods

```python
class Simulator:
    def __init__(self, config: SimConfig) -> None:
        """Initialize simulation with configuration."""

    def step_once(self) -> None:
        """Execute one simulation tick (game loop)."""

    def run(self, steps: Optional[int] = None) -> Metrics:
        """Run simulation for specified steps."""
```

#### Initialization invariant (Theorem 1 base case)

Theorem 1's induction has a base case: at $t = 0$, no exogenous agent
sits within $r_{\mathit{safe}}$ of any controlled agent.  Otherwise
the very first invocation of the violation classifier at phase 8
would record a nonzero ``violations_agent_attributable`` from
placement geometry alone — independent of any algorithmic choice.

``Simulator._place_entities`` enforces this:

1. Place each controlled agent on a free cell that is not already
   occupied by another controlled agent (vertex-collision-free at
   $t = 0$).
2. Compute
   $F_{\mathit{init}} = B_{r_{\mathit{safe}}}(\{a_i.\mathit{pos}\}_i)$
   via ``humans/safety.py::inflate_cells``.
3. Sample each exogenous agent's spawn cell with
   ``exclude = occupied ∪ F_init``, so no spawn lands inside any
   controlled agent's buffer.

If $F_{\mathit{init}}$ exhausts the free-cell pool (high-density
scenarios where the invariant cannot be satisfied), the constructor
raises :class:`InitializationError` with a message naming the knobs
the user can turn (``|X|``, ``|M|``, ``r_safe``).  Silently relaxing
the invariant is forbidden — it would invalidate the paper's central
guarantee.

A post-init regression guard
(``Simulator._assert_init_invariant``) re-checks both the
vertex-collision and Theorem-1-base-case conditions before any tick
runs, so a future refactor that drops the invariant fails loudly.
Pinned by ``tests/test_init_invariant.py``.

#### Simulation step order  (paper Algorithm 2 driver)

Each `step_once()` call executes the following 10 phases.  The phase
numbers are stable contracts — referenced by tests, by
``docs/REVISION_AUDIT.md``, and by the agent-attributable /
exogenous-attributable classifier in phase 8.

1. **Task release** — move pending tasks from `_pending_tasks` to
   `open_tasks` when `release_step ≤ t`.
2. **Task assignment** — run the task allocator; honour commitment
   persistence (``commit_horizon`` / ``delay_threshold``); attach
   newly assigned goals.
3. **Global planning (Tier-1)** — invoke
   ``RollingHorizonPlanner.step``; periodic / deviation / exhaustion /
   safety-wait / **eta_w** triggers fire here.
4. **Exogenous-agent dynamics** — ``self.human_model.step`` advances
   $X(t)$.  *The post-step-4 state is the formal* **decision-time
   snapshot** *used by phase 8.*
5. **Sense-Plan-Resolve (Tier-2)** — build per-agent observations
   from FoV; decide actions in sorted-`agent_id` order; each agent
   writes its committed next position to
   ``_decided_next_positions[aid]`` *before* the next agent decides
   (sequential decision-table semantics, see
   ``tests/test_decision_table.py``).
6. **Execution-delay injection** — probabilistic forced WAITs for
   robust-MAPF studies; counted as ``delay_events``.
7. **Physics update** — apply each agent's action; resolve any
   residual vertex / edge conflicts by reverting the lower-priority
   mover to WAIT (rare with the resolver running upstream).
8. **Collision & violation classification** — `prev_pos`, `new_pos`,
   and the decision-time exogenous-agent snapshot `humans_at_decision`
   are passed to ``_detect_collisions_and_near_misses``.  This is
   where the **agent-attributable** vs. **exogenous-attributable**
   split is computed (paper §3.4) and where Theorem 1's empirical
   counter ``violations_agent_attributable`` is incremented (or, on
   correct runs, *not* incremented).  Other counters logged here:
   agent-agent collisions, agent-human collisions, near-misses,
   human-passive-wait.
9. **Task completion** — pickup → delivery transition, makespan / SoC
   updates, mid-horizon re-assignment.
10. **Replay record** — append agent / human positions to the replay
    buffer.

After phase 10 the simulator advances `self.step += 1`.

#### Supported Modes

- **Lifelong Mode**: Continuous task stream with pickup-delivery workflow
- **One-Shot Mode**: Classical MAPF with direct goal assignments

### Environment (`environment.py`)

The `Environment` class represents the static grid world:

```python
class Environment:
    def __init__(self, width: int, height: int, blocked: Set[Cell]) -> None:
        """Initialize grid with dimensions and obstacles."""

    def is_blocked(self, cell: Cell) -> bool:
        """Check if cell is blocked or out of bounds."""

    def is_free(self, cell: Cell) -> bool:
        """Check if cell is valid for occupancy."""

    def sample_free_cell(self, rng, exclude: Iterable[Cell] | None = None) -> Cell:
        """Sample random free cell for entity placement."""

    @classmethod
    def load_from_map(cls, path: str) -> "Environment":
        """Load from MovingAI .map file."""
```

#### Coordinate System

- Uses `(row, col)` format
- `(0, 0)` is top-left corner
- Rows increase downward, columns increase rightward

### Agent Dynamics (`agent_dynamics.py`)

Handles state transitions for agents:

```python
def apply_action(env, agent_state: AgentState, action: StepAction) -> AgentState:
    """
    Compute next agent state after applying action.

    - WAIT: Stay in place, increment wait_steps (consecutive streak counter)
    - Movement: Check static obstacles; if valid, update position and reset wait_steps to 0
    """
```

#### Physics Rules

- Static obstacles block movement (walls)
- Invalid moves result in implicit wait
- Dynamic constraints checked separately by Simulator

### Events (`events.py`)

Immutable event definitions for logging and metrics:

| Event             | Description                       |
|-------------------|-----------------------------------|
| `TaskAssigned`    | Agent assigned new task           |
| `TaskCompleted`   | Agent reached goal                |
| `HumanDetected`   | Agent sensed human in FOV         |
| `ReplanTriggered` | Path recalculation initiated      |
| `Collision`       | Safety violation (entity overlap) |
| `NearMiss`        | Close proximity without collision |

## Configuration

The simulator is configured via `SimConfig`:

```python
@dataclass
class SimConfig:
    map_path: str  # Path to .map file
    num_agents: int  # Number of agents
    num_humans: int  # Number of dynamic obstacles
    steps: int  # Simulation duration
    seed: int  # Random seed

    # Planning
    global_solver: str  # "cbs" or "lacam"
    horizon: int  # Planning horizon
    replan_every: int  # Replan interval

    # Perception
    fov_radius: int  # Field of view radius
    safety_radius: int  # Safety buffer around humans

    # Human Model
    human_model: str  # "random_walk", "aisle", "adversarial", etc.
    human_model_params: dict  # Model-specific parameters

    # Ablation Flags
    disable_local_replan: bool
    disable_conflict_resolution: bool
    disable_safety: bool
```

## Collision Detection

The simulator tracks multiple safety metrics:

```python
def _detect_collisions_and_near_misses(prev_pos, new_pos) -> None:
    """
    Checks:
    1. Agent-Agent Vertex Collision (same cell)
    2. Agent-Agent Edge Collision (swapped cells)
    3. Agent-Human Collision (agent on human cell)
    4. Near Miss (Manhattan distance <= 1)
    5. Safety Buffer Violation (inside B_r(H_t))
    6. Human Passive Waiting (human blocked by agent)
    """
```

## Task Workflow

### Pickup-Delivery Tasks

```
Phase 1: Agent navigates to start (pickup) location
         carrying = False
         goal = task.start

Phase 2: Agent navigates to goal (delivery) location
         carrying = True
         goal = task.goal

Completion: Agent freed for next task
            done_tasks incremented
```

### One-Shot Tasks

- No pickup phase (`start = (-1, -1)`)
- Agent goes directly to goal
- Simulation terminates when all agents idle

## Integration Points

### Global Planner Interface

```python
# Simulator provides state view for planners
sim_state.agents  # Current agent states
sim_state.env  # Static environment
sim_state.open_tasks  # Released but unassigned tasks
sim_state.plans()  # Current plan bundle

# Planner callbacks
sim_state.mark_task_assigned(task, agent_id)
```

### Local Controller Interface

```python
# Controller receives observation and state
controller.decide_action(sim_state, observation, rng)

# Observation contains:
observation.visible_humans  # Detected humans
observation.visible_agents  # Detected agents
observation.blocked  # Occupied cells
```

## Usage Example

```python
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator

# Configure simulation
config = SimConfig(
    map_path="maps/warehouse.map",
    num_agents=10,
    num_humans=5,
    steps=1000,
    seed=42,
    global_solver="lacam",
    horizon=50,
    replan_every=25,
    fov_radius=5,
    safety_radius=2,
    human_model="random_walk",
)

# Run simulation
sim = Simulator(config)
metrics = sim.run()

# Access results
print(f"Tasks completed: {metrics.completed_tasks}")
print(f"Agent-Human collisions: {metrics.collisions_agent_human}")
print(f"Makespan: {metrics.makespan}")
```

## Related Modules

- [Core Types](../core/README_CORE.md) - Data structures and interfaces
- [Global Tier](../global_tier/README_GLOBAL_TIER.md) - Planning algorithms
- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Reactive control
- [Humans](../humans/README_HUMANS.md) - Motion models
- [I/O](../io/README_IO.md) - Map and task loading