# Hyperparameter Tuning Guide

This document is the authoritative reference for running hyperparameter
experiments with the HA-LMAPF system using
`scripts/run_hyperparameter_tuning.py`.

## Table of Contents

1. [Submission Checklist](#submission-checklist)
2. [Hyperparameter Reference](#hyperparameter-reference)
3. [Parameter Interactions](#parameter-interactions)
4. [Tuning Script Reference](#tuning-script-reference)
5. [Running Experiments](#running-experiments)
6. [Multi-Map Generalization](#multi-map-generalization)
7. [Ablation Study](#ablation-study)
8. [Analyzing Results](#analyzing-results)
9. [Plotting Script Reference](#plotting-script-reference)
10. [Complete Workflow for Papers](#complete-workflow-for-papers)

---

## Submission Checklist

The script is designed to satisfy the following submission requirements
out of the box:

| Requirement                   | How it is met                                                      |
|-------------------------------|--------------------------------------------------------------------|
| ≥ 5 seeds                     | Default `--seeds 0 1 2 3 4`                                        |
| ≥ 5000 simulation steps       | Default `--steps 5000` → ~500 completed tasks per run              |
| 3 topologically distinct maps | `--multi-map` runs the 4 core sweeps on all 3 canonical maps       |
| Generalization evidence       | Core sweeps run on all maps; sensitivity sweeps on the primary map |
| Robustness analysis           | `execution_delay` sweep (actuation noise 0–30 %)                   |
| Statistical significance      | Wilcoxon signed-rank p-values in `summary.csv` (requires `scipy`)  |
| Reproducible smoke-test       | `--sanity` verifies every code path before a full battery          |
| Complete ablation             | 6-condition ablation study (one component disabled per condition)  |

---

## Hyperparameter Reference

### Tier 1 — High-Impact Parameters

These directly control the throughput / safety trade-off. Tune these first.

| Parameter         | Default    | `SimConfig` field | Description                                          | Typical Range              |
|-------------------|------------|-------------------|------------------------------------------------------|----------------------------|
| `replan_every`    | 25         | `replan_every`    | Steps between global replanning cycles               | 5–50                       |
| `horizon`         | 50         | `horizon`         | Planning horizon length (timesteps)                  | 20–100                     |
| `safety_radius`   | 1          | `safety_radius`   | Buffer distance around humans (cells)                | 0–5                        |
| `fov_radius`      | 4          | `fov_radius`      | Agent field-of-view radius (Manhattan)               | 1–10                       |
| `global_solver`   | `"lacam"`  | `global_solver`   | MAPF solver: `"cbs"` (optimal) or `"lacam"` (fast)   | cbs, lacam                 |
| `task_allocator`  | `"congestion_avoidance"` (was `"greedy"` prior to v1.4-pre-direction-a-activation) | `task_allocator`  | Task assignment strategy                             | greedy, hungarian, auction, congestion_avoidance |
| `commit_horizon`  | `0`        | `commit_horizon`  | Steps a task assignment stays locked (0 = disabled)  | 0–100                      |
| `delay_threshold` | `0.0`      | `delay_threshold` | Revoke if distance > threshold × d₀ (0.0 = disabled) | 0.0–4.0                    |
| `hard_safety`     | `True`     | `hard_safety`     | Hard constraint (blocked) vs soft (high cost)        | True / False               |

### Tier 2 — Medium-Impact Parameters

Tune these per-scenario after Tier 1 is set.

| Parameter              | Default         | `SimConfig` field      | Description                                                |
|------------------------|-----------------|------------------------|------------------------------------------------------------|
| `task_arrival_rate`    | 10              | `task_arrival_rate`    | Steps between consecutive task releases (higher = slower)  |
| `num_agents`           | 20              | `num_agents`           | Fleet size                                                 |
| `num_humans`           | 5               | `num_humans`           | Number of dynamic human obstacles                          |
| `execution_delay_prob` | 0.0             | `execution_delay_prob` | Probability per step that an agent's move is delayed       |
| `time_budget_ms`       | 5000.0          | `time_budget_ms`       | Max wall-clock ms per global planning call (0 = unlimited) |
| `communication_mode`   | `"token"`       | `communication_mode`   | Conflict resolution protocol: `"token"` or `"priority"`    |
| `human_model`          | `"random_walk"` | `human_model`          | Motion model for humans                                    |

#### Human Model Parameters

**RandomWalkHumanModel** (`src/ha_lmapf/humans/models.py`):

| Parameter   | Default | Description                                           |
|-------------|---------|-------------------------------------------------------|
| `beta_go`   | 2.0     | Boltzmann weight for continuing in the same direction |
| `beta_wait` | -1.0    | Boltzmann weight for staying stationary               |
| `beta_turn` | 0.0     | Boltzmann weight for changing direction               |

**AisleFollowerHumanModel** (`"aisle"` / `"aisle_follower"` / `"corridor"`):

| Parameter | Default | Description                  |
|-----------|---------|------------------------------|
| `alpha`   | 1.0     | Corridor attraction strength |
| `beta`    | 1.5     | Directional inertia strength |

**AdversarialHumanModel** (`"adversarial"` / `"adversary"`):

| Parameter | Default | Description                                                    |
|-----------|---------|----------------------------------------------------------------|
| `gamma`   | 2.0     | Aggressiveness factor                                          |
| `lambda_` | 0.5     | Balance between chasing agents (0) and seeking bottlenecks (1) |

**MixedPopulationHumanModel** (`"mixed"`):

| Parameter    | Default                                                  | Description                                       |
|--------------|----------------------------------------------------------|---------------------------------------------------|
| `weights`    | `{"random_walk": 0.4, "aisle": 0.4, "adversarial": 0.2}` | Per-type probability weights                      |
| `sub_params` | `{}`                                                     | Model-specific params forwarded to each sub-model |

#### Conflict Resolution Parameters

**TokenPassingResolver** (`src/ha_lmapf/local_tier/conflict_resolution/token_passing.py`):

| Parameter    | Default | Description                                   |
|--------------|---------|-----------------------------------------------|
| `fairness_k` | 5       | Win-streak limit before forced token rotation |

**PriorityRulesResolver** (`src/ha_lmapf/local_tier/conflict_resolution/priority_rules.py`):

| Parameter              | Default | Description                       |
|------------------------|---------|-----------------------------------|
| `starvation_threshold` | 10      | Wait steps before urgency boost   |
| `boost`                | 50      | Urgency bonus for starving agents |
| `allow_side_step`      | True    | Allow lateral escape moves        |

### Tier 3 — Low-Impact / Internal Parameters

Rarely need changing; only adjust if you hit specific bottlenecks.

| Parameter             | Default | Location                    | Description                                       |
|-----------------------|---------|-----------------------------|---------------------------------------------------|
| `MAX_EXPANSIONS`      | 500     | `AStarLocalPlanner`         | A* search budget per call                         |
| `BLOCKED_CELL_COST`   | 50      | `AStarLocalPlanner`         | Soft-safety penalty weight                        |
| `MAX_NODES`           | 5000    | `CBSH2Solver`               | CBS high-level node limit                         |
| `max_iterations`      | 100     | `AuctionBasedTaskAllocator` | Auction rounds                                    |
| `epsilon`             | 0.01    | `AuctionBasedTaskAllocator` | Minimum bid increment                             |
| `deviation_threshold` | 1.0     | `SimConfig`                 | Min. path-change ratio to trigger a global replan |

---

## Parameter Interactions

Some parameters interact strongly and must be tuned together.

### `replan_every` ↔ `horizon` (bidirectional coupling)

The horizon must always be ≥ `replan_every`, otherwise the global plan
expires before the next replanning cycle, leaving agents without guidance.

**Rule of thumb**: `horizon = 2 × replan_every`

The script enforces this automatically via coupled parameters:

- `replan_every` sweep → sets `horizon = 2 × replan_every`
- `horizon` sweep → sets `replan_every = max(1, horizon ÷ 2)`

### `safety_radius` ↔ `fov_radius`

If `fov_radius < safety_radius`, agents cannot detect humans until they are
already inside the forbidden zone.

**Hard constraint**: always keep `fov_radius > safety_radius`.

> **Note on metrics**: when analysing the `safety_radius` sweep, use
> `near_misses` (proximity events at distance ≤ 1, independent of radius) as
> the primary safety metric.  `safety_violations` is confounded because a
> larger radius counts more cells as violations by definition.

### `safety_radius` + `hard_safety`

| Configuration                      | Typical behaviour                         |
|------------------------------------|-------------------------------------------|
| Large radius + `hard_safety=True`  | Frequent deadlocks, low violations        |
| Large radius + `hard_safety=False` | Fewer deadlocks, more violations          |
| Small radius + `hard_safety=True`  | Good balance for sparse human populations |

Tune together; watch both `safety_violations` and `total_wait_steps`.

### `num_agents` ↔ `global_solver`

| Agent count | Recommended solver                                    |
|-------------|-------------------------------------------------------|
| ≤ 15        | `"cbs"` (optimal)                                     |
| 16–50       | `"lacam"` (fast, bounded-suboptimal)                  |
| > 50        | `"lacam"` forced (CBS does not scale past ~30 agents) |

The `num_agents` sweep automatically applies `"overrides": {"global_solver": "lacam"}`.

### `commit_horizon` + `delay_threshold` (Commitment Persistence)

These two parameters implement the 3-condition commitment persistence for task
allocation. Once an agent is assigned a task its assignment is locked until
**one** of three events:

1. **Task completed** — agent reaches the delivery location (always active).
2. **Horizon expired** — `step − t_assign ≥ commit_horizon` (when `commit_horizon > 0`).
3. **Excessive delay** — `manhattan(pos, goal) > delay_threshold × d₀`, where
   `d₀` is the Manhattan distance to the goal **at the moment of assignment**
   (when `delay_threshold > 0.0`).  `d₀` resets at the pickup→delivery phase
   transition so the check remains meaningful throughout both phases.

When a commitment is revoked (condition 2 or 3) the task is returned to the
open pool and the agent is freed for immediate reassignment.

| Metric               | Meaning                                          |
|----------------------|--------------------------------------------------|
| `assignments_kept`   | Tasks completed without commitment being revoked |
| `assignments_broken` | Commitments forcibly revoked (conditions 2 or 3) |

| Configuration                           | Behaviour                                                               |
|-----------------------------------------|-------------------------------------------------------------------------|
| `commit_horizon=0, delay_threshold=0.0` | Fully memoryless; assignments held only until task completion (default) |
| `commit_horizon=25`                     | Lock for 25 steps max; prevents rapid reassignment oscillations         |
| `delay_threshold=2.0`                   | Revoke if agent is taking 2× the expected distance to reach the goal    |
| Both enabled                            | Either condition can revoke; use together for maximum stability         |

### `execution_delay_prob` ↔ `hard_safety`

High execution-delay probabilities combined with `hard_safety=True` can
cause agents to miss safety-zone windows, increasing both `safety_violations`
and `total_wait_steps`. Consider `hard_safety=False` in high-noise
environments to prevent deadlock.

---

## Tuning Script Reference

### Script: `scripts/run_hyperparameter_tuning.py`

### Command-Line Arguments

| Argument           | Type             | Default                      | Description                                               |
|--------------------|------------------|------------------------------|-----------------------------------------------------------|
| `--sweep SWEEP`    | str (repeatable) | —                            | Sweep(s) to run; may be given multiple times              |
| `--all`            | flag             | —                            | Run ALL sweeps on the primary map                         |
| `--multi-map`      | flag             | —                            | Run core sweeps on all 3 canonical maps                         |
| `--ablations`      | flag             | —                            | Run the 6-condition ablation study                        |
| `--sanity`         | flag             | —                            | Smoke-test every code path (3 values, 1 seed, 1000 steps) |
| `--seeds`          | int[]            | `[0 1 2 3 4]`                | Random seeds (≥ 5 required)                                     |
| `--map`            | str              | `warehouse-20-40-10-2-1.map` | Primary map for single-map sweeps                         |
| `--agents`         | int              | `20`                         | Number of agents in the base config                       |
| `--humans`         | int              | `5`                          | Number of humans in the base config                       |
| `--steps`          | int              | `5000`                       | Simulation steps per experiment                           |
| `--output`         | str              | `logs/tuning`                | Output directory                                          |
| `--workers` / `-j` | int              | `1`                          | Parallel worker processes (0 = all CPU cores)             |
| `--verbose` / `-v` | flag             | —                            | Print per-run metrics                                     |

### Available Sweeps

| Sweep name          | `SimConfig` field      | Values                                    | Notes                                       |
|---------------------|------------------------|-------------------------------------------|---------------------------------------------|
| `num_agents`        | `num_agents`           | [5, 10, 15, 20, 30, 40, 50, 75, 100, 150] | Forces `global_solver="lacam"`              |
| `num_humans`        | `num_humans`           | [0, 2, 5, 10, 15, 20, 30]                 |                                             |
| `task_arrival_rate` | `task_arrival_rate`    | [2, 5, 10, 15, 20, 30, 50, 100]           |                                             |
| `safety_radius`     | `safety_radius`        | [0, 1, 2, 3, 4, 5]                        | Use `near_misses` for analysis              |
| `fov_radius`        | `fov_radius`           | [1, 2, 3, 4, 5, 6, 8, 10]                 |                                             |
| `hard_safety`       | `hard_safety`          | [True, False]                             |                                             |
| `solver`            | `global_solver`        | ["cbs", "lacam"]                          |                                             |
| `replan_every`      | `replan_every`         | [5, 10, 15, 20, 25, 30, 40, 50]           | Coupled: `horizon = 2 × value`              |
| `horizon`           | `horizon`              | [20, 30, 50, 75, 100]                     | Coupled: `replan_every = max(1, value ÷ 2)` |
| `allocator`         | `task_allocator`       | ["greedy", "hungarian", "auction", "congestion_avoidance"] |                                             |
| `commit_horizon`    | `commit_horizon`       | [0, 5, 10, 25, 50, 100]                   | 0 = disabled                                |
| `delay_threshold`   | `delay_threshold`      | [0.0, 1.5, 2.0, 2.5, 3.0, 4.0]            | 0.0 = disabled                              |
| `human_model`       | `human_model`          | ["random_walk", "aisle", "mixed"]         |                                             |
| `execution_delay`   | `execution_delay_prob` | [0.0, 0.05, 0.1, 0.15, 0.2, 0.3]          | Robustness sweep                            |

> **Core sweeps** (run on all 3 maps with `--multi-map`):
> `num_agents`, `num_humans`, `human_model`, `task_arrival_rate`
>
> **Sensitivity sweeps** (run on the primary map only; show internal trade-offs):
> `safety_radius`, `fov_radius`, `hard_safety`, `solver`,
> `replan_every`, `horizon`, `allocator`, `execution_delay`

### Ablation Conditions

When running `--ablations`, six conditions are tested (one component disabled
per condition):

| Condition                | Description                                 | Flags set                                                       |
|--------------------------|---------------------------------------------|-----------------------------------------------------------------|
| `full_system`            | Complete two-tier system (control)          | *(all enabled)*                                                 |
| `no_local_replan`        | Disable Tier-2 local replanning             | `disable_local_replan=True`                                     |
| `no_conflict_resolution` | Disable conflict resolution                 | `disable_conflict_resolution=True`                              |
| `global_only`            | Disable both Tier-2 and conflict resolution | `disable_local_replan=True`, `disable_conflict_resolution=True` |
| `no_safety`              | Remove human safety buffers entirely        | `disable_safety=True`                                           |
| `soft_safety`            | Use soft safety (high cost, not hard block) | `hard_safety=False`                                             |

`global_only` is the closest approximation to a pure Tier-1 (RHCR-like)
baseline within the HA-LMAPF infrastructure.

### Base Configuration

All experiments inherit from this base config (equivalent to
`configs/tuning/base.yaml`):

```yaml
map_path: "data/maps/warehouse-20-40-10-2-1.map"
task_stream_path: null
steps: 5000
num_agents: 20
num_humans: 5
fov_radius: 4
safety_radius: 1
hard_safety: true
global_solver: "lacam"
replan_every: 25
horizon: 50
time_budget_ms: 5000.0      # cap global planning at 5 s
task_allocator: "congestion_avoidance"
task_arrival_rate: 10
task_arrival_percentage: 0.9
communication_mode: "token"
local_planner: "astar"
human_model: "random_walk"
human_model_params: { }
execution_delay_prob: 0.0
execution_delay_steps: 1
disable_local_replan: false
disable_conflict_resolution: false
disable_safety: false
seed: 0
```

> **Note**: `time_budget_ms=5000` caps each global planning call at 5 s,
> keeping large-horizon or CBS runs tractable. Set to `0` to disable.

### Output Files

```
logs/tuning/
├── results.csv        # One row per (sweep, value, seed)
├── summary.csv        # Aggregated statistics (mean ± std + Wilcoxon p-values)
└── sanity/            # Written by --sanity runs
    ├── results.csv
    └── summary.csv
```

**`results.csv` columns**:

| Column                     | Description                                                       |
|----------------------------|-------------------------------------------------------------------|
| `sweep`                    | Sweep name (or `"ablation"`)                                      |
| `map`                      | Map identifier (label or path; populated by `--multi-map`)        |
| `param`                    | `SimConfig` field being swept                                     |
| `value`                    | Parameter value for this row                                      |
| `seed`                     | Random seed                                                       |
| `wall_time_sec`            | Experiment wall-clock time                                        |
| `throughput`               | Tasks completed per simulation step                               |
| `completed_tasks`          | Total tasks finished                                              |
| `task_completion`          | Fraction of tasks completed                                       |
| `mean_flowtime`            | Mean task release-to-completion time                              |
| `median_flowtime`          | Median flowtime                                                   |
| `max_flowtime`             | Maximum flowtime                                                  |
| `mean_service_time`        | Mean assignment-to-completion time                                |
| `collisions_agent_agent`   | Agent–agent collision count                                       |
| `collisions_agent_human`   | Agent–human collision count                                       |
| `near_misses`              | Proximity events at distance ≤ 1 (independent of `safety_radius`) |
| `safety_violations`        | Entries into the human safety buffer zone                         |
| `safety_violation_rate`    | Safety violations per 1 000 steps                                 |
| `replans`                  | Total replanning events                                           |
| `global_replans`           | Tier-1 global replanning events                                   |
| `local_replans`            | Tier-2 local replanning events                                    |
| `intervention_rate`        | Global replans per 1 000 steps                                    |
| `total_wait_steps`         | Sum of steps all agents spent waiting                             |
| `human_passive_wait_steps` | Steps humans spent waiting due to agent proximity                 |
| `mean_planning_time_ms`    | Mean wall-clock time per planning call                            |
| `p95_planning_time_ms`     | 95th-percentile planning time                                     |
| `max_planning_time_ms`     | Maximum planning time                                             |
| `mean_decision_time_ms`    | Mean decision time per step                                       |
| `p95_decision_time_ms`     | 95th-percentile decision time                                     |
| `makespan`                 | Steps until all initially released tasks are complete             |
| `sum_of_costs`             | Sum of individual agent path lengths                              |
| `delay_events`             | Actuation delay events injected                                   |
| `immediate_assignments`    | Tasks assigned at the moment of release                           |
| `assignments_kept`         | Assignments preserved across replanning                           |
| `assignments_broken`       | Assignments changed at a replanning cycle                         |

**`summary.csv` additional columns** (beyond `{metric}_mean` / `{metric}_std`):

| Column                | Description                                                       |
|-----------------------|-------------------------------------------------------------------|
| `n_seeds`             | Number of seeds aggregated                                        |
| `map`                 | Map identifier                                                    |
| `{metric}_wilcoxon_p` | Wilcoxon signed-rank p-value vs sweep baseline (requires `scipy`) |

Wilcoxon p-values are computed for: `throughput`, `mean_flowtime`,
`near_misses`, `safety_violations`, `total_wait_steps`. The baseline is the
group with the **lowest numeric parameter value** in the same sweep (or
`full_system` for ablations). Values < 0.05 indicate a statistically
significant difference. Requires `pip install scipy`; gracefully falls back
to `NaN` if absent.

---

## Running Experiments

### Smoke-Test First

Before running a full battery, always verify every code path executes without
error:

```bash
# Test all sweeps + ablations (3 values each, 1 seed, 1000 steps — fast)
python scripts/run_hyperparameter_tuning.py --sanity

# Test specific sweeps only
python scripts/run_hyperparameter_tuning.py --sanity \
    --sweep num_agents --sweep solver
```

### Single Sweep

```bash
# One sweep, default 5 seeds
python scripts/run_hyperparameter_tuning.py --sweep replan_every

# Multiple sweeps in one call
python scripts/run_hyperparameter_tuning.py \
    --sweep num_agents --sweep num_humans --sweep human_model
```

### Full Single-Map Battery

```bash
# All sweeps, 5 seeds, 5000 steps (default)
python scripts/run_hyperparameter_tuning.py --all

# With parallel execution (uses all CPU cores)
python scripts/run_hyperparameter_tuning.py --all --workers 0

# Custom map and scale
python scripts/run_hyperparameter_tuning.py --all \
    --map data/maps/warehouse-10-20-10-2-1.map \
    --agents 15 --humans 3 --steps 5000
```

### Full Battery

```bash
# All sweeps + multi-map generalization + ablation (several hours)
python scripts/run_hyperparameter_tuning.py \
    --all --multi-map --ablations \
    --workers 0 \
    --output logs/paper_experiments
```

### Parallel Execution

| Flag          | Behaviour                                    |
|---------------|----------------------------------------------|
| `--workers 1` | Sequential (default, original behaviour)     |
| `--workers 0` | Use all logical CPU cores (`os.cpu_count()`) |
| `--workers N` | Use exactly N parallel processes             |

Each `(value, seed)` pair is an independent job dispatched to the pool.
Progress is reported as futures complete.

```bash
# 8 workers
python scripts/run_hyperparameter_tuning.py --all --workers 8

# All cores
python scripts/run_hyperparameter_tuning.py --all --workers $(nproc)
```

---

## Multi-Map Generalization

The `--multi-map` flag runs the four **core sweeps** on all three canonical
maps to provide cross-environment generalization evidence.

### Canonical Maps

| Key               | Map file                     | Label               | Max agents |
|-------------------|------------------------------|---------------------|------------|
| `warehouse_small` | `warehouse-10-20-10-2-1.map` | Warehouse-S (10×20) | 40         |
| `warehouse_large` | `warehouse-20-40-10-2-1.map` | Warehouse-L (20×40) | 100        |
| `room`            | `room-32-32-4.map`           | Room-32 (32×32-4)   | 60         |

- **Warehouse-S** — tight aisles, high agent density, strong contention.
- **Warehouse-L** — primary map used for all single-map sensitivity sweeps.
- **Room-32** — narrow doorways create bottlenecks; tests the local planner.

### Core vs Sensitivity Sweeps

| Sweep type                                                            | Maps             | Purpose                     |
|-----------------------------------------------------------------------|------------------|-----------------------------|
| Core (`num_agents`, `num_humans`, `human_model`, `task_arrival_rate`) | All 3            | Generalization evidence     |
| Sensitivity (all others)                                              | Primary map only | Internal trade-off analysis |

For the `num_agents` sweep, values are automatically capped at each map's
recommended maximum to avoid over-saturation.

```bash
# Run core sweeps on all 3 maps
python scripts/run_hyperparameter_tuning.py --multi-map --workers 0
```

Results include a `map` column in `results.csv` and `summary.csv` so you can
compare performance across maps with a simple `groupby("map")`.

---

## Ablation Study

The 6-condition ablation isolates the contribution of each system component.
Each condition differs from `full_system` by **exactly one flag**, making the
marginal contribution of each tier identifiable.

```bash
python scripts/run_hyperparameter_tuning.py --ablations --seeds 0 1 2 3 4
```

### Interpreting Ablation Results

| Condition removed        | Expected impact                                                      |
|--------------------------|----------------------------------------------------------------------|
| `no_local_replan`        | Higher `total_wait_steps`, more deadlocks in narrow corridors        |
| `no_conflict_resolution` | More `collisions_agent_agent`, lower throughput at high density      |
| `global_only`            | Combines both effects above; approximates a pure Tier-1 baseline     |
| `no_safety`              | Near-zero `safety_violations` but increased `collisions_agent_human` |
| `soft_safety`            | Fewer deadlocks than `full_system` but more `safety_violations`      |

Wilcoxon p-values in `summary.csv` are computed against `full_system` so you
can directly report statistical significance for each ablation claim.

---

## Analyzing Results

### Key Metrics for Papers

| Metric                   | What it measures                                | Goal     |
|--------------------------|-------------------------------------------------|----------|
| `throughput`             | Tasks completed per step                        | Maximize |
| `mean_flowtime`          | Average task release-to-completion time         | Minimize |
| `near_misses`            | Proximity events at distance ≤ 1 (safety proxy) | Minimize |
| `safety_violations`      | Entries into the human buffer zone              | Minimize |
| `collisions_agent_human` | Actual robot–human collisions                   | Zero     |
| `mean_planning_time_ms`  | Computational cost per planning call            | Minimize |
| `task_completion`        | Fraction of tasks completed                     | Maximize |

### Reading Results

```bash
# View raw results (first 20 rows)
head -20 logs/tuning/results.csv

# View summary with Wilcoxon p-values
cat logs/tuning/summary.csv

# Filter one sweep
grep "^num_agents" logs/tuning/results.csv

# Sort by throughput descending
sort -t',' -k$(head -1 logs/tuning/results.csv | tr ',' '\n' | \
    grep -n throughput | cut -d: -f1) -rn logs/tuning/results.csv | head -10
```

### Pandas Analysis

```python
import pandas as pd

df = pd.read_csv("logs/tuning/results.csv")

# --- Single sweep ---
replan = df[df["sweep"] == "replan_every"]
stats = replan.groupby("value").agg(
    throughput_mean=("throughput", "mean"),
    throughput_std=("throughput", "std"),
    near_misses_mean=("near_misses", "mean"),
    planning_ms_mean=("mean_planning_time_ms", "mean"),
)
print(stats)

# --- Multi-map comparison ---
mm = df[df["sweep"] == "num_agents"]
for map_key, grp in mm.groupby("map"):
    print(f"\n{map_key}")
    print(grp.groupby("value")[["throughput", "near_misses"]].mean())

# --- Ablation significance (from summary.csv) ---
summary = pd.read_csv("logs/tuning/summary.csv")
ablation = summary[summary["sweep"] == "ablation"]
print(ablation[["value", "throughput_mean", "throughput_std",
                "throughput_wilcoxon_p"]])

# --- Find optimal config ---
best = df.loc[df["throughput"].idxmax()]
print(f"Best: value={best['value']}, throughput={best['throughput']:.4f}")
```

### Interpreting Wilcoxon p-values

```python
summary = pd.read_csv("logs/tuning/summary.csv")

# Report significant differences (p < 0.05) for a sweep
sw = summary[summary["sweep"] == "num_agents"].copy()
sw["significant"] = sw["throughput_wilcoxon_p"] < 0.05
print(sw[["value", "throughput_mean", "throughput_wilcoxon_p", "significant"]])
```

> `NaN` means the group had < 5 seeds, matched the baseline exactly, or
> `scipy` was not installed. Install with `pip install scipy`.

---

## Plotting Script Reference

### Script: `scripts/plot_tuning_results.py`

Generates publication-quality figures from tuning results.

```bash
pip install matplotlib  # required
```

### Command-Line Arguments

| Argument          | Type | Default             | Description                            |
|-------------------|------|---------------------|----------------------------------------|
| `--input` / `-i`  | str  | **required**        | Path to `results.csv`                  |
| `--output` / `-o` | str  | `<input_dir>/plots` | Output directory                       |
| `--all`           | flag | —                   | Generate all available plots           |
| `--plot`          | str  | —                   | Generate a specific plot type          |
| `--param`         | str  | —                   | Parameter name for `sensitivity` plots |
| `--x`             | str  | `throughput`        | X-axis metric for `pareto` plots       |
| `--y`             | str  | `safety_violations` | Y-axis metric for `pareto` plots       |

### Available Plot Types

| Plot type       | Description                                  | Required extra args     |
|-----------------|----------------------------------------------|-------------------------|
| `sensitivity`   | Metric vs parameter value line plot          | `--param <name>`        |
| `scalability`   | Throughput and planning time vs `num_agents` | —                       |
| `solver`        | Bar chart comparing MAPF solvers             | —                       |
| `ablation`      | Bar chart of 6-condition ablation            | —                       |
| `pareto`        | Pareto-front scatter plot                    | `--x`, `--y` (optional) |
| `human_density` | Effect of `num_humans` on metrics            | —                       |
| `safety`        | `safety_radius` vs throughput / violations   | —                       |

### Usage Examples

```bash
# All plots at once
python scripts/plot_tuning_results.py -i logs/tuning/results.csv --all

# Sensitivity for a specific parameter
python scripts/plot_tuning_results.py -i logs/tuning/results.csv \
    --plot sensitivity --param replan_every

python scripts/plot_tuning_results.py -i logs/tuning/results.csv \
    --plot sensitivity --param execution_delay

# Scalability curve
python scripts/plot_tuning_results.py -i logs/tuning/results.csv \
    --plot scalability

# 6-condition ablation bar chart
python scripts/plot_tuning_results.py -i logs/tuning/results.csv \
    --plot ablation

# Pareto front: throughput vs near_misses
python scripts/plot_tuning_results.py -i logs/tuning/results.csv \
    --plot pareto --x throughput --y near_misses

# Save to custom directory
python scripts/plot_tuning_results.py -i logs/paper_experiments/results.csv \
    --all --output paper/figures
```

### Output Files

Plots are saved in both PDF (for papers) and PNG (for preview):

```
logs/tuning/plots/
├── sensitivity_replan_every.pdf / .png
├── sensitivity_safety_radius.pdf / .png
├── sensitivity_execution_delay.pdf / .png
├── scalability_agents.pdf / .png
├── solver_comparison.pdf / .png
├── ablation_study.pdf / .png
├── pareto_throughput_vs_safety_violations.pdf / .png
├── human_density.pdf / .png
└── safety_tradeoff.pdf / .png
```

**Plot settings**: 300 DPI, 6×4 in (single column) or 10×4 in (double
column), colorblind-friendly palette, error bars = standard deviation.

---

## Complete Workflow for Papers

### Step 0: Smoke-Test

```bash
python scripts/run_hyperparameter_tuning.py --sanity
```

Verify all sweeps and ablations run without errors before committing to a
multi-hour battery.

### Step 1: Run the Full Battery

```bash
python scripts/run_hyperparameter_tuning.py \
    --all --multi-map --ablations \
    --seeds 0 1 2 3 4 \
    --steps 5000 \
    --workers 0 \
    --output logs/paper_experiments
```

This runs:

- All sensitivity sweeps on the primary map
- Core sweeps (`num_agents`, `num_humans`, `human_model`, `task_arrival_rate`)
  on all 3 canonical maps
- 6-condition ablation study
- Total: ~900+ experiments across 5 seeds

### Step 2: Generate All Figures

```bash
python scripts/plot_tuning_results.py \
    --input logs/paper_experiments/results.csv \
    --output paper/figures \
    --all
```

### Step 3: Review Summary Statistics

```bash
# Human-readable summary
column -t -s',' logs/paper_experiments/summary.csv | less -S

# Check Wilcoxon significance for the scalability claim
python - <<'EOF'
import pandas as pd
df = pd.read_csv("logs/paper_experiments/summary.csv")
cols = ["sweep", "map", "value",
        "throughput_mean", "throughput_std", "throughput_wilcoxon_p"]
print(df[df["sweep"] == "num_agents"][cols].to_string(index=False))
EOF
```

### Step 4: Copy Figures to Paper

```bash
cp logs/paper_experiments/plots/*.pdf paper/figures/
```

### One-Liner (after sanity check)

```bash
python scripts/run_hyperparameter_tuning.py \
    --all --multi-map --ablations --workers 0 \
    --output logs/paper_experiments && \
python scripts/plot_tuning_results.py \
    --input logs/paper_experiments/results.csv --all && \
echo "Done! See logs/paper_experiments/"
```

---

## Recommended Tuning Order (new scenario)

For a new map or scenario, run sweeps in this order to avoid wasted compute:

1. **Solver selection** — determines feasibility at your agent count

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep solver
   ```

2. **Replan interval** — most sensitive parameter; find the knee of the
   throughput vs planning-time curve

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep replan_every
   ```

3. **Safety radius** — pick the smallest radius with an acceptable violation
   rate; use `near_misses` as the metric

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep safety_radius
   ```

4. **Field of view** — diminishing returns above `fov_radius ≈ 6`

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep fov_radius
   ```

5. **Task allocator** — Hungarian is optimal but O(n³); greedy is adequate for
   most scenarios

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep allocator
   ```

6. **Human model** — only if you are modelling a specific real-world population

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep human_model
   ```

7. **Robustness** — inject actuation noise and verify graceful degradation

   ```bash
   python scripts/run_hyperparameter_tuning.py --sweep execution_delay
   ```

---

## References

- CBS: Sharon et al., "Conflict-Based Search for Optimal Multi-Agent
  Pathfinding," 2012
- LaCAM: Okumura et al., "LaCAM: Search-Based Algorithm for Quick
  Multi-Agent Pathfinding," 2023
- PIBT: Okumura et al., "Priority Inheritance with Backtracking for Iterative
  Multi-agent Path Finding," 2022