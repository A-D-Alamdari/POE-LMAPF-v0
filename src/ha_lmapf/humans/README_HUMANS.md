# Exogenous Agents Module

Exogenous-agent (a.k.a. *human*) motion simulation, prediction, and
safety utilities for the POE-LMAPF simulator.  The module retains its
``humans/`` directory name and ``Human``-prefixed class names for
backward compatibility with the SoCS2026 codebase; the paper text
calls these entities **exogenous agents**.

## Paper alignment (§5.1)

Two motion models are paper baselines:

* ``RandomWalkHumanModel`` — random walk with directional inertia
  (Boltzmann), used on ``random-*`` maps.
* ``AisleFollowerHumanModel`` — corridor-biased Boltzmann, used on
  ``warehouse-10-20-10-2-1`` and ``warehouse-10-20-10-2-2``.

The remaining classes (``AdversarialHumanModel``,
``MixedPopulationHumanModel``, ``ReplayHumanModel``) are auxiliary —
useful for stress tests and reproducibility runs but NOT part of the
paper's main evaluation sweep.  The per-map mapping
(``ha_lmapf.io.default_map_to_human_model``) is what the paper
configurations use.

## Overview

```
┌────────────────────────────────────────────────────────────────┐
│              EXOGENOUS AGENTS MODULE (humans/)                 │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   MODELS    │    │ PREDICTION  │    │   SAFETY    │         │
│  │ (Behaviour) │    │ (auxiliary) │    │  (buffer F) │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│        │                  │                  │                 │
│        v                  v                  v                 │
│  Simulates exo-     (NOT used by the    Computes B_r(.)        │
│  genous-agent       paper pipeline;      buffer around         │
│  movement in env    kept for back-       exogenous agents      │
│                     compat)              (forbidden set F)     │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

Note: ``prediction.py::MyopicPredictor`` is retained for backward
compatibility but is NOT used by the paper's reported pipeline (the
controller's FoV-based observation is sufficient).

## Files

| File | Description |
|------|-------------|
| `models.py` | Human motion behavior models |
| `prediction.py` | Human position forecasting |
| `safety.py` | Safety buffer utilities |

---

## models.py - Human Motion Models

Different behavioral models for simulating human movement.

### Available Models

| Model | Behavior | Parameters |
|-------|----------|------------|
| `RandomWalkHumanModel` | Random movement with inertia | `beta_go`, `beta_wait` |
| `AisleFollowerHumanModel` | Follows corridors/aisles | `alpha`, `beta` |
| `AdversarialHumanModel` | Seeks to block agents | `gamma`, `lambda` |
| `MixedPopulationHumanModel` | Mix of behaviors | Model weights |
| `ReplayHumanModel` | Replays recorded trajectories | Trajectory data |

### RandomWalkHumanModel

```python
class RandomWalkHumanModel(HumanModel):
    """
    Random walk with Boltzmann-distributed action selection.

    Features:
        - Inertia: prefers continuing in same direction
        - Avoids walls and agent positions
        - Stochastic movement

    Parameters:
        beta_go: float - Temperature for movement preference
        beta_wait: float - Probability bias for waiting
    """

    def step(
        self,
        env,
        humans: Dict[int, HumanState],
        rng,
        agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        """Advance all humans one step; returns updated humans dict."""
```

### AisleFollowerHumanModel

```python
class AisleFollowerHumanModel(HumanModel):
    """
    Human that follows warehouse aisles.

    Features:
        - Detects aisle structure
        - Prefers corridor movement
        - Turns at intersections

    Realistic for warehouse workers walking between shelves.
    """
```

### AdversarialHumanModel

```python
class AdversarialHumanModel(HumanModel):
    """
    Human that actively seeks congested areas.

    Features:
        - Moves toward agent-dense areas
        - Used for stress testing
        - Models worst-case human behavior
    """
```

### MixedPopulationHumanModel

```python
class MixedPopulationHumanModel(HumanModel):
    """
    Heterogeneous population with different behaviors.

    Assigns each human a behavior type:
        - 40% random walk
        - 30% aisle follower
        - 20% adversarial
        - 10% stationary
    """
```

### ReplayHumanModel

```python
class ReplayHumanModel(HumanModel):
    """
    Replays pre-recorded human trajectories.

    Used for:
        - Reproducible experiments
        - Debugging specific scenarios
        - Testing with real human data
    """
```

### Usage

```python
from ha_lmapf.humans.models import RandomWalkHumanModel, MixedPopulationHumanModel

# Single behavior
model = RandomWalkHumanModel(beta_go=2.0, beta_wait=-1.0)

# Mixed population
model = MixedPopulationHumanModel()

# Advance all humans one step
agent_positions = {a.pos for a in agents.values()}
humans = model.step(env, humans, rng, agent_positions)
# humans is now an updated Dict[int, HumanState]
```

---

## prediction.py - Human Motion Prediction

Conservative forecasting of human positions.

### MyopicPredictor

```python
class MyopicPredictor(HumanPredictor):
    """
    Conservative human position predictor.

    Strategy:
        - Assumes human might stay at current position
        - Optionally includes neighboring cells
        - Returns set of potentially occupied cells

    Parameters:
        include_neighbors: bool - Include adjacent cells (conservative)
    """

    def predict(
        self,
        humans: Dict[int, HumanState],
        horizon: int
    ) -> List[Set[Cell]]:
        """
        Predict human positions over horizon.

        Returns:
            {human_id: set of potentially occupied cells}
        """
```

### Prediction Strategy

```
For each human:
    occupied = {human.pos}  # Current position

    if include_neighbors:
        for each neighbor of human.pos:
            if neighbor is free:
                occupied.add(neighbor)

    # Human could be at any of these cells
    return occupied
```

### Usage

```python
from ha_lmapf.humans.prediction import MyopicPredictor

predictor = MyopicPredictor(include_neighbors=True)
predictions = predictor.predict(humans, horizon=10)

# predictions[human_id] = set of cells human might occupy
for human_id, cells in predictions.items():
    print(f"Human {human_id} might be at: {cells}")
```

---

## safety.py - Safety Buffer Utilities

Functions for computing safety zones around humans.

### inflate_cells

```python
def inflate_cells(
    cells: Set[Cell],
    radius: int,
    env,            # Environment — used to exclude walls from the buffer
) -> Set[Cell]:
    """
    Expand seed cells into a Manhattan ball of the given radius.

    Creates the safety buffer B_r(H_t) around human positions.
    Wall/out-of-bounds cells are excluded from the result.

    Args:
        cells: Seed positions (e.g., current human positions)
        radius: L1 inflation radius
        env: Environment (provides is_free() for wall filtering)

    Returns:
        Set of traversable cells within safety buffer
    """
```

### proximity_penalty

```python
def proximity_penalty(
    cell: Cell,
    human_cells: Set[Cell],
    radius: int,
) -> int:
    """
    Compute integer cost penalty for proximity to humans.

    Formula: max(0, radius - distance + 1)
    Used in soft safety mode for heuristic path cost.

    Returns:
        Integer penalty >= 0 (higher = closer to human)
    """
```

### Usage

```python
from ha_lmapf.humans.safety import inflate_cells

human_positions = {(5, 5), (10, 10)}
safety_radius = 1

blocked_cells = inflate_cells(human_positions, radius=safety_radius, env=env)
# blocked_cells includes (5,5), (4,5), (6,5), (5,4), (5,6), etc.
# (wall cells and out-of-bounds cells are automatically excluded)
```

---

## Safety Modes

### Hard Safety

```
Agents NEVER enter safety buffer:
    - Buffer cells are impassable
    - Agent waits if path blocked
    - Guarantees human safety
```

### Soft Safety

```
Agents avoid but CAN enter safety buffer:
    - Buffer cells have high cost
    - Prevents permanent deadlock
    - Small safety violation risk
```

---

## Configuration

```yaml
# Human behavior settings
human_model: "random_walk"  # Options: random_walk, aisle, adversarial, mixed
human_model_params:
  beta_go: 2.0
  beta_wait: -1.0

# Safety settings
safety_radius: 1           # Buffer distance around humans
hard_safety: true          # Hard vs soft safety mode
```

---

## Human State

```python
@dataclass
class HumanState:
    human_id: int
    pos: Tuple[int, int]         # Current position
    velocity: Tuple[int, int]    # Direction of movement (optional)
```

---

## Related Modules

- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Uses predictions for safety
- [Simulation](../simulation/README_SIMULATION.md) - Steps human models
- [Core](../core/README_CORE.md) - HumanState type definition