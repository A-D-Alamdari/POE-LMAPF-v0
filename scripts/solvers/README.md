# Global Planner Comparison Studies

This directory contains two complementary studies that compare global
MAPF planners under different scaling axes:

| Study           | Script                           | Sweep variable   | Fixed variable   |
|-----------------|----------------------------------|------------------|------------------|
| **Agent sweep** | `compare_global_study_agents.py` | Number of agents | Number of humans |
| **Human sweep** | `compare_global_study_human.py`  | Number of humans | Number of agents |

Both studies share the same maps, human models, and core parameters.
Solver sets and safety radius vary per map size.

---

## Common configuration

### Solvers compared

Both studies use a **per-map-size** solver set:

**Small maps** (random, warehouse_small) — 6 solvers:

| Label     | Factory name | Description                                  |
|-----------|--------------|----------------------------------------------|
| lacam     | `lacam`      | LaCAM official (C++ wrapper)                 |
| lacam3    | `lacam3`     | LaCAM3 anytime with refinement (C++ wrapper) |
| pibt2     | `pibt2`      | Priority Inheritance with Backtracking (C++) |
| lns2      | `lns2`       | MAPF-LNS2 Large Neighbourhood Search (C++)   |
| PBS       | `pbs`        | Priority-Based Search (C++ wrapper)          |
| cbsh2-rtc | `cbsh2`      | CBS with Heuristics 2 (C++ wrapper)          |

**Large maps** (warehouse_large) — 4 solvers:

| Label  | Factory name | Description                                  |
|--------|--------------|----------------------------------------------|
| lacam  | `lacam`      | LaCAM official (C++ wrapper)                 |
| lacam3 | `lacam3`     | LaCAM3 anytime with refinement (C++ wrapper) |
| pibt2  | `pibt2`      | Priority Inheritance with Backtracking (C++) |
| lns2   | `lns2`       | MAPF-LNS2 Large Neighbourhood Search (C++)   |

### Maps (4 total)

| Tag             | File                       | Size    | Category | Safety radius |
|-----------------|----------------------------|---------|----------|---------------|
| random          | random-64-64-10.map        | 64x64   | SMALL    | 2             |
| warehouse_small | warehouse-10-20-10-2-2.map | 170x84  | SMALL    | 1             |
| warehouse_large | warehouse-20-40-10-2-2.map | 340x164 | LARGE    | 1             |

### Human model settings

| Tag    | Model       | Description                        |
|--------|-------------|------------------------------------|
| random | random_walk | Boltzmann-distributed random walk  |
| aisle  | aisle       | Corridor/aisle-following behaviour |
| mixed  | mixed       | 50% random_walk + 50% aisle        |

### Conflict resolution

Both studies use **token-passing** (`communication_mode: "token"`) for Tier-2
(local) conflict resolution. This is held constant so that performance
differences are attributable solely to the global planner.

### Fixed parameters

| Parameter      | Value  | Notes                                        |
|----------------|--------|----------------------------------------------|
| horizon        | 50     | Global planning lookahead                    |
| replan_every   | 25     | Steps between Tier-1 replans                 |
| fov_radius     | 5      | Agent field of view (Manhattan)              |
| safety_radius  | 1 or 2 | 1 for warehouse maps, 2 for others (per-map) |
| time_budget_ms | 3000   | 3-second planning budget                     |
| steps          | 2000   | Simulation duration                          |
| seeds          | 10     | Seeds 0–9                                    |
| hard_safety    | True   | Hard constraint on human buffer              |
| task_allocator | congestion_avoidance (was greedy prior to v1.4-pre-direction-a-activation) | Iterated Hungarian on BFS distances with path-overlap penalty |
| local_planner  | astar  | Tier-2 A* pathfinding                        |

---

## Prerequisites (both studies)

1. Navigate to the repository root:
   ```bash
   cd /path/to/ha_lmapf
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Verify that C++ solver binaries are built and accessible.
   Both scripts report `SKIP` for any solver whose binary is missing and
   continue running the remaining solvers.

4. Verify map files exist:
   ```bash
   ls data/maps/random-64-64-10.map \
      data/maps/warehouse-10-20-10-2-2.map \
      data/maps/warehouse-20-40-10-2-2.map
   ```

---

# Study A: Agent Sweep

**Question:** How does solver performance scale as the number of agents increases?

### Scaling rules

| Variable    | Formula                                         |
|-------------|-------------------------------------------------|
| max_agents  | `floor_to_lower_100(0.05 * free_cells)`         |
| agent sweep | Tiered by map size (see docstring)              |
| num_humans  | `floor_to_lower_10(0.005 * free_cells)` (fixed) |

Small maps use tiered agent counts (`[15,30,...,100]`, `[25,50,...,200]`, or
`[50,100,...,400]` depending on `max_agents`). Large maps use fixed counts:
`[100, 250, 400, 550, 700, 850, 1000, 1150]`.

### Study matrix

- 2 small maps x 3 human models x 6 solvers x variable agent counts x 10 seeds
- 2 large maps x 3 human models x 4 solvers x 8 agent counts x 10 seeds

### Results directory

```
logs/solvers/agents/<unique_run_name>/
```

---

## Step-by-step: Agent sweep

### Step 1: Smoke test (optional but recommended)

```bash
python scripts/solvers/compare_global_study_agents.py --sanity
```

Check console output for `SKIP` (missing binary) or `ERROR` messages.

### Step 2: Run the full study

#### Option A: Sequential

```bash
python scripts/solvers/compare_global_study_agents.py
```

#### Option B: Parallel

```bash
python scripts/solvers/compare_global_study_agents.py --workers 8
```

Use `--workers 0` for all CPU cores.

#### Option C: Subset run

```bash
# Only warehouse maps, only lacam and lns2
python scripts/solvers/compare_global_study_agents.py \
    --maps warehouse_small warehouse_large \
    --solvers lacam lns2

# Only random human model, 5 seeds
python scripts/solvers/compare_global_study_agents.py \
    --human-models random \
    --seeds 0 1 2 3 4
```

#### Option D: Custom simulation length

```bash
python scripts/solvers/compare_global_study_agents.py --steps 1000
```

### Step 3: Check outputs

```
logs/solvers/agents/compare_YYYYMMDD_HHMMSS/
├── raw/
│   └── results.csv              # One row per seed per configuration
├── aggregated/
│   └── summary.csv              # Mean ± std aggregated over seeds
├── metadata/
│   └── config.json              # Full experiment configuration
└── figures/                     # Empty until plotting step
```

Verify:

```bash
head -5 logs/solvers/agents/compare_*/raw/results.csv
grep -c ",ok," logs/solvers/agents/compare_*/raw/results.csv
```

### Step 4: Generate plots

```bash
python scripts/solvers/plot_compare_global_results_agents.py \
    --run-dir logs/solvers/agents/compare_YYYYMMDD_HHMMSS
```

Replace the timestamp with your actual run directory name.

Format options:

```bash
# SVG + PDF
python scripts/solvers/plot_compare_global_results_agents.py \
    --run-dir logs/solvers/agents/compare_YYYYMMDD_HHMMSS --format svg

# Custom output directory
python scripts/solvers/plot_compare_global_results_agents.py \
    --run-dir logs/solvers/agents/compare_YYYYMMDD_HHMMSS \
    --output /path/to/custom/figures
```

### Step 5: Review figures

Figures are saved to `<run-dir>/figures/`:

```
figures/
├── random_throughput.png / .pdf
├── random_task_completion.png / .pdf
├── ...
├── warehouse_small_throughput.png / .pdf
├── ...
├── warehouse_large_throughput.png / .pdf
└── ...
```

Each figure has:

- **X-axis**: number of agents
- **Lines**: one per solver (4–6 solvers, color-coded)
- **Subplots**: one per human model (random, aisle, mixed)
- **Error bands**: 95% CI shading across 10 seeds

---

# Study B: Human Sweep

**Question:** How does solver performance degrade as the number of humans
(dynamic obstacles) increases, with a fixed fleet of agents?

### Scaling rules

| Variable    | Formula                                         |
|-------------|-------------------------------------------------|
| num_agents  | `floor_to_lower_100(0.02 * free_cells)` (fixed) |
| max_humans  | `floor_to_lower_100(0.02 * free_cells)`         |
| human sweep | Tiered by max_humans (see below)                |

Human count tiers:

| max_humans | Candidates                              |
|------------|-----------------------------------------|
| <= 100     | [15, 30, 45, 60, 75, 100]               |
| <= 200     | [25, 50, 75, 100, 125, 150, 175, 200]   |
| <= 400     | [50, 100, 150, 200, 250, 300, 350, 400] |

**Override:** The `random` map uses `num_agents=50` and
`human_counts=[15, 30, 45, 60, 75]` (auto-scaling produces 0 for this small map).

### Study matrix

- 2 small maps x 3 human models x 6 solvers x variable human counts x 10 seeds
- 2 large maps x 3 human models x 4 solvers x variable human counts x 10 seeds

### Results directory

```
logs/solvers/human/<unique_run_name>/
```

---

## Step-by-step: Human sweep

### Step 1: Smoke test (optional but recommended)

```bash
python scripts/solvers/compare_global_study_human.py --sanity
```

This runs 1 seed, 200 steps, and the first human count only. Check for
`SKIP` or `ERROR` messages.

### Step 2: Run the full study

#### Option A: Sequential

```bash
python scripts/solvers/compare_global_study_human.py
```

#### Option B: Parallel

```bash
python scripts/solvers/compare_global_study_human.py --workers 8
```

Use `--workers 0` for all CPU cores.

#### Option C: Subset run

```bash
# Only warehouse_large map, only lacam and lns2
python scripts/solvers/compare_global_study_human.py \
    --maps warehouse_large \
    --solvers lacam lns2

# Only aisle human model, 3 seeds
python scripts/solvers/compare_global_study_human.py \
    --human-models aisle \
    --seeds 0 1 2
```

#### Option D: Custom simulation length

```bash
python scripts/solvers/compare_global_study_human.py --steps 1000
```

### Step 3: Check outputs

```
logs/solvers/human/human_sweep_YYYYMMDD_HHMMSS/
├── raw/
│   └── results.csv              # One row per seed per configuration
├── aggregated/
│   └── summary.csv              # Mean ± std aggregated over seeds
├── metadata/
│   └── config.json              # Full experiment configuration
└── figures/                     # Empty until plotting step
```

Verify:

```bash
head -5 logs/solvers/human/human_sweep_*/raw/results.csv
grep -c ",ok," logs/solvers/human/human_sweep_*/raw/results.csv
```

Check for skipped solvers:

```bash
grep ",skip," logs/solvers/human/human_sweep_*/raw/results.csv | cut -d, -f8 | sort -u
```

### Step 4: Generate plots

```bash
python scripts/solvers/plot_compare_global_results_human.py \
    --run-dir logs/solvers/human/human_sweep_YYYYMMDD_HHMMSS
```

Replace the timestamp with your actual run directory name.

Format options:

```bash
# SVG + PDF
python scripts/solvers/plot_compare_global_results_human.py \
    --run-dir logs/solvers/human/human_sweep_YYYYMMDD_HHMMSS --format svg

# Custom output directory
python scripts/solvers/plot_compare_global_results_human.py \
    --run-dir logs/solvers/human/human_sweep_YYYYMMDD_HHMMSS \
    --output /path/to/custom/figures
```

### Step 5: Review figures

Figures are saved to `<run-dir>/figures/`:

```
figures/
├── random_throughput.png / .pdf
├── ...
├── warehouse_small_throughput.png / .pdf
├── ...
├── warehouse_large_throughput.png / .pdf
└── ...
```

Each figure has:

- **X-axis**: number of humans
- **Lines**: one per solver (4–6 solvers, color-coded)
- **Subplots**: one per human model (random, aisle, mixed)
- **Error bands**: 95% CI shading across 10 seeds

---

# Rounding rules

Both studies use the same rounding function:

```
floor_to_lower_100(x) = floor(x / 100) * 100
```

| Input | Result |
|-------|--------|
| 1182  | 1100   |
| 1100  | 1100   |
| 473   | 400    |
| 99    | 0      |

The agents study also uses `floor_to_lower_10(x)` for computing human counts:

```
floor_to_lower_10(x) = floor(x / 10) * 10
```

---

# Re-running without overwriting

Both studies create uniquely-named directories using timestamps. Previous
runs are never overwritten.

| Study       | Default folder name pattern                      |
|-------------|--------------------------------------------------|
| Agent sweep | `logs/solvers/agents/compare_YYYYMMDD_HHMMSS`    |
| Human sweep | `logs/solvers/human/human_sweep_YYYYMMDD_HHMMSS` |

Override with `--run-name`:

```bash
python scripts/solvers/compare_global_study_agents.py --run-name my_agents_v2
python scripts/solvers/compare_global_study_human.py --run-name my_humans_v2
```

---

# Full CLI reference

## Agent sweep — run script

```
python scripts/solvers/compare_global_study_agents.py --help
```

| Argument         | Default               | Description                      |
|------------------|-----------------------|----------------------------------|
| `--maps`         | all 4                 | Map tags to include              |
| `--human-models` | all 3                 | Human model settings             |
| `--solvers`      | all 6                 | Solver labels                    |
| `--seeds`        | 0–9                   | Random seeds                     |
| `--steps`        | 2000                  | Simulation length                |
| `--out`          | `logs/solvers/agents` | Base output directory            |
| `--run-name`     | timestamp             | Custom run directory name        |
| `--workers`      | 1                     | Parallel workers (0 = all cores) |
| `--verbose`      |                       | Print per-run metrics            |
| `--sanity`       |                       | Quick smoke-test mode            |

## Agent sweep — plot script

```
python scripts/solvers/plot_compare_global_results_agents.py --help
```

| Argument    | Default              | Description                     |
|-------------|----------------------|---------------------------------|
| `--run-dir` | (required)           | Path to completed run directory |
| `--output`  | `<run-dir>/figures/` | Custom figure output directory  |
| `--format`  | `png`                | Output format (png, pdf, svg)   |

## Human sweep — run script

```
python scripts/solvers/compare_global_study_human.py --help
```

| Argument         | Default              | Description                      |
|------------------|----------------------|----------------------------------|
| `--maps`         | all 4                | Map tags to include              |
| `--human-models` | all 3                | Human model settings             |
| `--solvers`      | all 6                | Solver labels                    |
| `--seeds`        | 0–9                  | Random seeds                     |
| `--steps`        | 2000                 | Simulation length                |
| `--out`          | `logs/solvers/human` | Base output directory            |
| `--run-name`     | timestamp            | Custom run directory name        |
| `--workers`      | 1                    | Parallel workers (0 = all cores) |
| `--verbose`      |                      | Print per-run metrics            |
| `--sanity`       |                      | Quick smoke-test mode            |

## Human sweep — plot script

```
python scripts/solvers/plot_compare_global_results_human.py --help
```

| Argument    | Default              | Description                     |
|-------------|----------------------|---------------------------------|
| `--run-dir` | (required)           | Path to completed run directory |
| `--output`  | `<run-dir>/figures/` | Custom figure output directory  |
| `--format`  | `png`                | Output format (png, pdf, svg)   |

---

# Scripts in this directory

| File                                    | Purpose                                |
|-----------------------------------------|----------------------------------------|
| `compare_global_study_agents.py`        | Run script: agent-count sweep study    |
| `plot_compare_global_results_agents.py` | Plot script: agent-count sweep results |
| `compare_global_study_human.py`         | Run script: human-count sweep study    |
| `plot_compare_global_results_human.py`  | Plot script: human-count sweep results |
| `README.md`                             | This file                              |