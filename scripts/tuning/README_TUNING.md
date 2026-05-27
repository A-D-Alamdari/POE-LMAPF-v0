# HA-LMAPF Hyperparameter Tuning Pipeline

Sequential, statistically-rigorous tuning of the six system parameters that
most affect throughput and human-robot safety.

---

## Prerequisites

```bash
pip install numpy scipy matplotlib
```

Verify your build is working before running any tuning:

```bash
python -c "from ha_lmapf.simulation.simulator import Simulator; print('OK')"
```

---

## Pipeline Overview

```
Step 1: tune_horizon.py          ──┐
Step 2: tune_replan_every.py     ──┤ (planning tier)
Step 3: tune_horizon_replan.py   ──┘ joint grid (confirms 1+2)

Step 4: tune_fov_radius.py       ──┐
Step 5: tune_safety_radius.py    ──┤ (perception / safety tier)
Step 6: tune_fov_safety.py       ──┘ joint grid (confirms 4+5)

Step 7: tune_commit_delay.py          (task allocation tier)
```

Each step feeds its best values forward to the next via `--best-*` flags.
Every script writes results to `logs/tuning/<param>/<label>_<timestamp>/`
so repeated runs **never overwrite** previous ones.

### Outputs per run

| File          | Contents                                                            |
|---------------|---------------------------------------------------------------------|
| `results.csv` | One row per (value, seed) — raw simulation metrics                  |
| `summary.csv` | One row per value — mean ± std, 95% CI, Wilcoxon p, FDR q, effect r |
| `pareto.csv`  | Pareto-optimal configs on (throughput, near\_misses)                |
| `table.tex`   | Copy-paste LaTeX table with significance markers                    |
| `plots/`      | Line plots, violin plots, heatmaps, Pareto scatter (see §Plotting)  |

---

## Global Solver

All tuning uses **LaCAM** (C++ official wrapper via `lacam_official_wrapper.py`)
as the default global solver. This is the same solver used in the comparison
study (`compare_global_study_agents.py`).

Step 1 (`tune_horizon.py`) supports a `--solver` flag to compare horizon
sensitivity across all solvers (lacam, lacam3, pibt2, lns2, pbs, cbsh2-rtc).

---

## Experimental Settings

Step 1 (`tune_horizon.py`) uses settings that match the global comparison study
(`compare_global_study_agents.py`) to ensure consistency:

| Setting          | Value                                               |
|------------------|-----------------------------------------------------|
| Maps             | random, warehouse\_small, warehouse\_large |
| Agents (small)   | [25, 50, 75, 100]                                   |
| Agents (large)   | [100, 200, 300, 400]                                |
| Humans (small)   | 50                                                  |
| Humans (large)   | 200                                                 |
| Seeds            | 15 (0..14)                                          |
| Steps            | 2000                                                |
| `fov_radius`     | 5                                                   |
| `safety_radius`  | 2                                                   |
| `time_budget_ms` | 5000                                                |
| `task_mode`      | immediate                                           |
| `communication`  | token                                               |
| `task_allocator` | congestion_avoidance (was greedy prior to v1.4-pre-direction-a-activation) |

**Small maps:** random (64×64, 10% obstacles), warehouse\_small (63×161)
**Large maps:** warehouse\_large (123×321)

---

## Step-by-Step Instructions

### Quick sanity check (< 5 min)

Run Step 1 with `--sanity` to verify the pipeline runs end-to-end:

```bash
python scripts/tuning/tune_horizon.py --sanity --workers 0
# 12 runs: 4 maps × 1 agent count × 3 horizon values × 1 seed × 200 steps

# With all solvers:
python scripts/tuning/tune_horizon.py --sanity --solver all --workers 0
# 72 runs: 6 solvers × 4 maps × 1 agent count × 3 horizons × 1 seed
```

For subsequent steps:

```bash
python scripts/tuning/tune_replan_every.py --best-horizon 50 --seeds 0 --steps 500
# ... and so on
```

---

### Step 1 — Tune `horizon`

**What it does:** sweeps the global planning horizon [10, 20, 30, 40, 50, 60, 75, 100]
across 4 maps, multiple agent counts per map, and optionally multiple solvers.
`replan_every` is automatically coupled to `horizon // 2` during this sweep.

**Primary metric:** throughput (tasks/step)
**Watch also:** `mean_planning_time_ms` — longer horizon = slower planning.

#### A. Default (lacam only, all maps)

```bash
python scripts/tuning/tune_horizon.py --workers 0
# 1920 runs: 1 solver × 16 (map,agent) combos × 8 horizons × 15 seeds
```

#### B. Per-solver comparison (paper-ready)

Run across all 6 solvers to verify that the chosen horizon is robust:

```bash
# All solvers
python scripts/tuning/tune_horizon.py --solver all --workers 0
# 11520 runs: 6 solvers × 16 combos × 8 horizons × 15 seeds

# Specific solvers
python scripts/tuning/tune_horizon.py --solver lacam lacam3 lns2 --workers 0

# Single solver
python scripts/tuning/tune_horizon.py --solver pbs --workers 0
```

Available solvers: `lacam`, `lacam3`, `pibt2`, `lns2`, `pbs`, `cbsh2-rtc`

#### C. Specific maps or fewer seeds

```bash
# Small maps only (faster)
python scripts/tuning/tune_horizon.py --maps random warehouse_small --workers 0

# Fewer seeds for quick iteration
python scripts/tuning/tune_horizon.py --seeds 0 1 2 3 4 --workers 0

# Custom horizon range
python scripts/tuning/tune_horizon.py --values 30 40 50 60 75 --workers 0
```

#### D. With a label

```bash
python scripts/tuning/tune_horizon.py --solver all --label paper --workers 0
```

**Read the output:**

- Per-group tables show `mean ± std`, `95% CI`, Wilcoxon `p` / FDR `q`, effect `|r|`.
- `***` = p < 0.001, `**` = p < 0.01, `*` = p < 0.05, `ns` = not significant.
- Effect `|r|`: 0.1 small · 0.3 medium · 0.5 large.
- The cross-solver summary table shows whether all solvers agree on the same
  optimal horizon (solver-agnostic) or disagree (solver-specific tuning needed).

**Output structure:**

```
logs/tuning/horizon/<label>_<timestamp>/
├── results.csv                          ← all raw results
├── cross_solver_summary.csv             ← best horizon per solver
├── table_cross_solver.tex               ← LaTeX cross-solver table
├── lacam/
│   ├── random/agents_25/summary.csv     ← per (solver,map,agents) aggregation
│   ├── random/agents_50/summary.csv
│   ├── warehouse_small/agents_25/...
│   └── ...
├── lacam3/...
└── ...
```

**Record:** `BEST_HORIZON=<value>`

---

### Step 2 — Tune `replan_every`

**What it does:** sweeps replan\_every [5, 10, 15, 20, 25, 30, 40, 50]
with the best horizon from Step 1 fixed. Values that exceed the horizon
are automatically dropped.

**Primary metric:** throughput
**Watch also:** `intervention_rate` (planning overhead), `total_wait_steps` (staleness).

```bash
python scripts/tuning/tune_replan_every.py \
    --best-horizon $BEST_HORIZON --workers 0
```

**Record:** `BEST_REPLAN=$value`

---

### Step 3 — Joint `horizon × replan_every` grid (recommended)

**What it does:** full grid search across all valid (horizon, replan\_every)
pairs with constraint `replan_every ≤ horizon`. Detects interactions
that sequential tuning might miss.

```bash
python scripts/tuning/tune_horizon_replan.py --workers 0

# Narrow search around known good region (cheaper)
python scripts/tuning/tune_horizon_replan.py \
    --horizon-values 30 40 50 60 \
    --replan-values 10 15 20 25 30 \
    --workers 0
```

**Outputs also:** `pareto_cost.csv` — Pareto front on (throughput, planning\_time).

**If the joint best differs from Steps 1+2:** use the joint best.

**Record:** `BEST_HORIZON=<h>`, `BEST_REPLAN=<r>`

---

### Step 4 — Tune `fov_radius`

**What it does:** sweeps fov\_radius [1, 2, 3, 4, 5, 6, 8, 10].

**PRIMARY metric: `near_misses`** — use this to pick `fov_radius`.
`safety_violations` is confounded by safety\_radius size; always prefer
`near_misses` when reporting safety.

**Key insight:** `fov_radius` must exceed `safety_radius` for agents to
react before entering the forbidden zone.

```bash
python scripts/tuning/tune_fov_radius.py \
    --best-horizon $BEST_HORIZON \
    --best-replan-every $BEST_REPLAN \
    --workers 0
```

Choose the **smallest** `fov_radius` where `near_misses` plateaus
(diminishing safety returns beyond that point reduce efficiency).

**Record:** `BEST_FOV=$value`

---

### Step 5 — Tune `safety_radius`

**What it does:** sweeps safety\_radius [0, 1, 2, 3, 4, 5].

**This is the most direct safety-efficiency tradeoff.**  Output includes
an explicit Pareto front on `(throughput, near_misses)`.

```bash
python scripts/tuning/tune_safety_radius.py \
    --best-horizon $BEST_HORIZON \
    --best-replan-every $BEST_REPLAN \
    --best-fov-radius $BEST_FOV \
    --workers 0
```

**How to choose:** examine `pareto.csv`. Pick the Pareto-optimal
`safety_radius` that meets your deployment safety requirement (e.g., the
smallest radius where `near_misses` drops below your threshold).

**Record:** `BEST_SAFETY=$value`

---

### Step 6 — Joint `fov_radius × safety_radius` grid (recommended)

**What it does:** full grid of all (fov, safety) pairs with
`fov ≥ safety` enforced. This is the **primary safety-efficiency result**
for the paper.

```bash
python scripts/tuning/tune_fov_safety.py \
    --best-horizon $BEST_HORIZON \
    --best-replan-every $BEST_REPLAN \
    --workers 0

# Narrow search
python scripts/tuning/tune_fov_safety.py \
    --best-horizon $BEST_HORIZON \
    --best-replan-every $BEST_REPLAN \
    --fov-values 3 4 5 6 --safety-values 1 2 3 \
    --workers 0
```

The `pareto.csv` table from this step should appear in the paper as the
**safety-efficiency tradeoff figure**.

**Record:** `BEST_FOV=<f>`, `BEST_SAFETY=<s>`

---

### Step 7 — Joint `commit_horizon × delay_threshold` grid

**What it does:** grid of task-allocation stability parameters.

- `commit_horizon = 0` (default) = memoryless greedy — lowest latency,
  highest assignment thrashing (`assignments_broken ↑`).
- `commit_horizon > 0` = assignments locked for up to N steps — reduces
  thrashing, may slightly reduce responsiveness.
- `delay_threshold > 0` = early revocation when agent falls behind.

**Metrics to watch:** `throughput`, `mean_flowtime`, `assignments_broken`,
`delay_events`.

```bash
python scripts/tuning/tune_commit_delay.py \
    --best-horizon $BEST_HORIZON \
    --best-replan-every $BEST_REPLAN \
    --best-fov-radius $BEST_FOV \
    --best-safety-radius $BEST_SAFETY \
    --workers 0
```

At the end, the script prints the **complete tuned configuration** — use
this in all paper experiments.

---

## Plotting

### Step 1 horizon tuning — multi-solver plots

The new `tune_horizon.py` produces per-group subdirectories. Plot them:

```bash
RUN=logs/tuning/horizon/paper_<timestamp>

# --- Per (solver, map, agent_count) group: line + violin + Pareto ---
# Example: lacam on random map with 50 agents
python scripts/tuning/plot_tuning.py \
    $RUN/lacam/random/agents_50/summary.csv

# --- Batch: all groups for a solver ---
for dir in $RUN/lacam/*/*; do
    python scripts/tuning/plot_tuning.py \
        $dir/summary.csv -o $dir/plots/
done

# --- Batch: all groups for all solvers ---
for dir in $RUN/*/*/*; do
    [ -f "$dir/summary.csv" ] && \
    python scripts/tuning/plot_tuning.py \
        $dir/summary.csv -o $dir/plots/
done

# --- Plot from raw results (violin plots, requires results.csv) ---
# The raw results.csv is at the top level; filter per-group manually
# or use the summary.csv-only mode (line plots + Pareto)
```

### Steps 2-7 — standard plots

```bash
# Single-parameter sweep — line plots + violin + Pareto + sensitivity
python scripts/tuning/plot_tuning.py \
    logs/tuning/replan_every/<timestamp>/summary.csv \
    --raw logs/tuning/replan_every/<timestamp>/results.csv

# Grid sweep — heatmaps + Pareto scatter
python scripts/tuning/plot_tuning.py \
    logs/tuning/horizon_replan/<timestamp>/summary.csv \
    --heatmap

# Safety-focused panels (fov/safety sweeps)
python scripts/tuning/plot_tuning.py \
    logs/tuning/fov_safety/<timestamp>/summary.csv \
    --heatmap --safety

# Task-allocation panels (commit_delay sweep)
python scripts/tuning/plot_tuning.py \
    logs/tuning/commit_delay/<timestamp>/summary.csv \
    --allocation

# Custom output directory
python scripts/tuning/plot_tuning.py \
    logs/tuning/horizon/<timestamp>/summary.csv \
    -o figures/tuning/

# With Pareto file explicitly
python scripts/tuning/plot_tuning.py \
    logs/tuning/fov_safety/<timestamp>/summary.csv \
    --pareto logs/tuning/fov_safety/<timestamp>/pareto.csv \
    --heatmap --safety
```

### Plot types generated

| Plot file                                | Description                                       |
|------------------------------------------|---------------------------------------------------|
| `sweep_<param>_lines.png`                | Line plot with 95% CI ribbon + significance stars |
| `sweep_<param>_violin.png`               | Violin + mean/CI overlay (requires `--raw`)       |
| `grid_<a>_<b>_heatmap.png`               | Heatmap per metric (grid sweeps)                  |
| `pareto_throughput_vs_near_misses.png`   | Safety-efficiency Pareto scatter                  |
| `pareto_throughput_vs_mean_flowtime.png` | Quality-flowtime Pareto                           |
| `sensitivity_<param>.png`                | Tornado chart: normalized metric range            |

---

## Statistical Methodology

### Tests used

- **Wilcoxon signed-rank test** (paired, two-sided): compares each parameter
  value against the baseline (smallest numeric value in the sweep) using
  the per-seed paired observations. Appropriate for small samples (n < 30)
  with no normality assumption.

### Multiple comparison correction

- **Benjamini-Hochberg FDR** correction is applied across all comparisons
  within each sweep. Report FDR-corrected q-values (`fdr_q` column in
  `summary.csv`), not raw p-values.

### Effect size

- **Rank-biserial correlation r** (from Mann-Whitney U statistic).
  |r| < 0.1 negligible · 0.1 small · 0.3 medium · 0.5 large.
  Report alongside p-values — statistical significance without effect size
  is not sufficient for a conference submission.

### Confidence intervals

- **95% bootstrap CI** (percentile method, 1000 resamples) when n ≥ 10
  seeds; normal approximation otherwise.

### Minimum seeds

- 5 seeds are the minimum for Wilcoxon tests and stable statistics.
- Default for Step 1: **15 seeds** (matching the comparison study).
- For final results, use 15 seeds across all steps.

---

## Reporting in a Paper

### In the text

> "We swept the planning horizon *H* over {10, 20, 30, 40, 50, 60, 75, 100}
> across 4 maps, 4 agent counts per map, 6 global solvers, and 15 independent
> seeds with 2000 simulation steps each. Differences from the baseline were
> tested with the Wilcoxon signed-rank test (paired, two-sided) with
> Benjamini-Hochberg FDR correction; we report effect size r (rank-biserial
> correlation)."

### Tables

Use `table.tex` directly — it includes `\toprule`, `\midrule`, `\bottomrule`
(requires `booktabs` package) and bold-faces the best configuration.

For Step 1 multi-solver mode, use `table_cross_solver.tex` which compares
the best horizon per solver.

### Figures

- **Sweep figures:** `sweep_horizon_lines.png` — response curve per
  (solver, map, agent-count) group with CI ribbon and significance markers.
- **Safety-efficiency tradeoff:** `pareto_throughput_vs_near_misses.png`
  from Steps 5 or 6 — the Pareto front is the primary safety result.
- **Grid heatmaps:** `grid_horizon_replan_heatmap.png` and
  `grid_fov_radius_safety_radius_heatmap.png`.

---

## Full Pipeline — One-Shot Example

```bash
# =====================================================================
# Step 1: Tune horizon (multi-solver, paper-ready)
# =====================================================================
# Full study: all 6 solvers, 4 maps, 15 seeds, 2000 steps
python scripts/tuning/tune_horizon.py \
    --solver all --label paper --workers 0
# → cross_solver_summary.csv shows best horizon per solver
# → If all solvers agree: BEST_HORIZON=50 (for example)

# Quick alternative: lacam only
python scripts/tuning/tune_horizon.py --label paper --workers 0

# Plot all per-group results
RUN_H=$(ls -td logs/tuning/horizon/paper_* | head -1)
for dir in $RUN_H/*/*/*; do
    [ -f "$dir/summary.csv" ] && \
    python scripts/tuning/plot_tuning.py \
        $dir/summary.csv -o $dir/plots/
done

# =====================================================================
# Step 2: Tune replan_every (with best horizon from Step 1)
# =====================================================================
python scripts/tuning/tune_replan_every.py \
    --best-horizon 50 --workers 0 --label paper
# → Best replan_every = 25

RUN_R=$(ls -td logs/tuning/replan_every/paper_* | head -1)
python scripts/tuning/plot_tuning.py \
    $RUN_R/summary.csv --raw $RUN_R/results.csv

# =====================================================================
# Step 3: Joint horizon × replan_every grid (confirms Steps 1+2)
# =====================================================================
python scripts/tuning/tune_horizon_replan.py \
    --horizon-values 30 40 50 60 --replan-values 10 15 20 25 30 \
    --workers 0 --label paper
# → Confirms: horizon=50, replan_every=25

RUN_HR=$(ls -td logs/tuning/horizon_replan/paper_* | head -1)
python scripts/tuning/plot_tuning.py $RUN_HR/summary.csv --heatmap

# =====================================================================
# Step 4: Tune fov_radius
# =====================================================================
python scripts/tuning/tune_fov_radius.py \
    --best-horizon 50 --best-replan-every 25 \
    --workers 0 --label paper
# → Best fov_radius = 5

RUN_F=$(ls -td logs/tuning/fov_radius/paper_* | head -1)
python scripts/tuning/plot_tuning.py \
    $RUN_F/summary.csv --raw $RUN_F/results.csv --safety

# =====================================================================
# Step 5: Tune safety_radius
# =====================================================================
python scripts/tuning/tune_safety_radius.py \
    --best-horizon 50 --best-replan-every 25 --best-fov-radius 5 \
    --workers 0 --label paper
# → Best safety_radius = 2

RUN_S=$(ls -td logs/tuning/safety_radius/paper_* | head -1)
python scripts/tuning/plot_tuning.py \
    $RUN_S/summary.csv --raw $RUN_S/results.csv --safety

# =====================================================================
# Step 6: Joint fov × safety grid (confirms Steps 4+5)
# =====================================================================
python scripts/tuning/tune_fov_safety.py \
    --best-horizon 50 --best-replan-every 25 \
    --fov-values 3 4 5 6 --safety-values 1 2 3 \
    --workers 0 --label paper
# → Confirms: fov_radius=5, safety_radius=2

RUN_FS=$(ls -td logs/tuning/fov_safety/paper_* | head -1)
python scripts/tuning/plot_tuning.py $RUN_FS/summary.csv --heatmap --safety

# =====================================================================
# Step 7: Joint commit_horizon × delay_threshold grid
# =====================================================================
python scripts/tuning/tune_commit_delay.py \
    --best-horizon 50 --best-replan-every 25 \
    --best-fov-radius 5 --best-safety-radius 2 \
    --workers 0 --label paper
# → Prints complete tuned configuration

RUN_CD=$(ls -td logs/tuning/commit_delay/paper_* | head -1)
python scripts/tuning/plot_tuning.py $RUN_CD/summary.csv --allocation
```

---

## Estimated Runtimes

### Step 1 (tune\_horizon) — new multi-map/multi-solver

| Configuration                           | Runs   | Est. wall time (32 cores) |
|-----------------------------------------|--------|---------------------------|
| `--sanity` (lacam)                      | 12     | ~1 min                    |
| `--sanity --solver all`                 | 72     | ~5 min                    |
| Default (lacam, all maps)               | 1,920  | ~2–4 h                    |
| `--solver all` (6 solvers)              | 11,520 | ~12–24 h                  |
| `--solver lacam lacam3 lns2`            | 5,760  | ~6–12 h                   |
| `--maps random warehouse_small` (lacam) | 960    | ~1–2 h                    |

### Steps 2-7

Assuming 5 seeds, 5000 steps, 20 agents, 5 humans on the primary warehouse map.
Times scale linearly with seeds/steps.

| Script                | Configs | Est. wall time (1 core) | Est. (all cores) |
|-----------------------|---------|-------------------------|------------------|
| tune\_replan\_every   | ≤8      | ~40 min                 | ~8 min           |
| tune\_horizon\_replan | ~35     | ~3 h                    | ~20 min          |
| tune\_fov\_radius     | 8       | ~40 min                 | ~8 min           |
| tune\_safety\_radius  | 6       | ~30 min                 | ~6 min           |
| tune\_fov\_safety     | ~28     | ~2.5 h                  | ~18 min          |
| tune\_commit\_delay   | ~31     | ~2.5 h                  | ~20 min          |

---

## Directory Structure

```
scripts/tuning/
├── README_TUNING.md           ← this file
├── tuning_utils.py            ← shared utilities (stats, I/O, sweep runners)
├── tune_horizon.py            ← Step 1 (multi-map, multi-solver, multi-agent)
├── tune_replan_every.py       ← Step 2
├── tune_horizon_replan.py     ← Step 3 (joint)
├── tune_fov_radius.py         ← Step 4
├── tune_safety_radius.py      ← Step 5
├── tune_fov_safety.py         ← Step 6 (joint)
├── tune_commit_delay.py       ← Step 7 (joint, final)
└── plot_tuning.py             ← plotting

logs/tuning/                   ← auto-created by runs
├── horizon/
│   └── paper_2026-03-16_12-00-00/
│       ├── results.csv                    ← all raw results
│       ├── cross_solver_summary.csv       ← best horizon per solver
│       ├── table_cross_solver.tex         ← LaTeX cross-solver table
│       ├── lacam/
│       │   ├── random/
│       │   │   ├── agents_25/summary.csv
│       │   │   ├── agents_50/summary.csv
│       │   │   ├── agents_75/summary.csv
│       │   │   └── agents_100/summary.csv
│       │   ├── warehouse_small/...
│       │   └── warehouse_large/...
│       ├── lacam3/...
│       ├── pibt2/...
│       ├── lns2/...
│       ├── pbs/...
│       └── cbsh2-rtc/...
├── replan_every/
├── horizon_replan/
├── fov_radius/
├── safety_radius/
├── fov_safety/
└── commit_delay/
```