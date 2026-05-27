# HA-LMAPF Ablation Study

A complete, statistically-rigorous ablation study that justifies every key
architectural decision in the HA-LMAPF system.

---

## Overview

The study is organized into **two groups** that answer the system's core
research claims:

| Group                       | Research Claim                                                                                                                                      |
|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| **A** — Tier Architecture   | The two-tier (global + local) architecture outperforms a pure Tier-1 (RHCR-like) baseline, and each Tier-2 sub-component contributes independently. |
| **B** — Safety & Perception | Hard safety constraints reduce human-robot near-misses at an acceptable throughput cost compared to no safety or soft safety.                       |

### Maps (2 small maps)

| Map             | File                                   | Agents | Humans |
|-----------------|----------------------------------------|--------|--------|
| random          | `data/maps/random-64-64-10.map`        | 50     | 20     |
| warehouse_small | `data/maps/warehouse-10-20-10-2-1.map` | 250    | 100    |

### Ablation conditions (6 total)

```
Group A — Tier Architecture
  full_system             Control (all tiers enabled)
  no_local_replan         Tier-2 local replanning disabled
  no_conflict_resolution  Conflict resolution disabled
  global_only             Both Tier-2 features off (RHCR baseline)

Group B — Safety & Perception
  no_safety               Safety buffer completely disabled (throughput upper bound)
  soft_safety             Hard constraint → soft (high-cost zone)
```

---

## Prerequisites

```bash
pip install numpy scipy matplotlib
```

Verify the build before running:

```bash
python -c "from ha_lmapf.simulation.simulator import Simulator; print('OK')"
```

---

## Step-by-Step Instructions

### Step 0 — List all conditions (optional)

```bash
python scripts/ablation/run_ablation_study.py --list-conditions
```

### Step 1 — Run the ablation study

#### Full study (recommended for paper — both maps, 10 seeds)

```bash
# Both maps, parallel (all cores — recommended)
python scripts/ablation/run_ablation_study.py \
    --maps random warehouse_small \
    --workers 0 --label paper_v1
```

#### Run specific group only

```bash
# Architecture ablation only
python scripts/ablation/run_ablation_study.py --groups A --workers 0

# Quick smoke-test (3 seeds)
python scripts/ablation/run_ablation_study.py \
    --seeds 0 1 2 --workers 0
```

### Step 2 — Generate all paper figures

```bash
python scripts/ablation/plot_ablation.py \
    logs/ablation/<timestamp>/summary.csv \
    --raw logs/ablation/<timestamp>/results.csv
```

This produces 8 figure files (PDF + PNG) in `logs/ablation/<timestamp>/plots/`.

#### Generate specific figures only

```bash
# Main result (Fig 1) + effect sizes (Fig 4) + heatmap (Fig 6)
python scripts/ablation/plot_ablation.py \
    logs/ablation/<timestamp>/summary.csv \
    --figures 1 4 6

# With custom output directory
python scripts/ablation/plot_ablation.py \
    logs/ablation/<timestamp>/summary.csv \
    -o figures/paper/ablation/
```

---

## Output Files

Every run writes to `logs/ablation/<label>_<YYYY-MM-DD_HH-MM-SS>/`:

| File                  | Contents                                                                     |
|-----------------------|------------------------------------------------------------------------------|
| `results.csv`         | One row per (condition, seed) — raw simulation metrics                       |
| `summary.csv`         | One row per condition — mean ± std, 95% CI, Wilcoxon p, FDR q, effect r, % Δ |
| `table.tex`           | Ready-to-paste booktabs LaTeX table with significance markers                |
| `group_A_results.csv` | Raw data for Group A only                                                    |
| `group_A_summary.csv` | Aggregated stats for Group A only                                            |
| `group_B_*.csv`       | Same for Group B                                                             |

After running `plot_ablation.py`, a `plots/` subdirectory contains:

| Figure | File                                      | What it shows                                                                         |
|--------|-------------------------------------------|---------------------------------------------------------------------------------------|
| Fig 1  | `fig1_throughput_by_group.pdf/.png`       | Throughput for every condition, coloured by group, with 95% CI and significance stars |
| Fig 2  | `fig2_safety_panel.pdf/.png`              | Safety metrics (near_misses, collisions, violations) across conditions                |
| Fig 3  | `fig3_efficiency_panel.pdf/.png`          | Efficiency metrics (flowtime, wait steps, planning time, intervention rate)           |
| Fig 4  | `fig4_effect_size_forest.pdf/.png`        | Forest plot of rank-biserial r for 5 metrics — the primary effect-size figure         |
| Fig 5  | `fig5_safety_efficiency_scatter.pdf/.png` | Throughput vs near_misses scatter with Pareto front — safety-efficiency tradeoff      |
| Fig 6  | `fig6_comprehensive_heatmap.pdf/.png`     | All conditions × 10 metrics heatmap (% change vs Full System)                         |
| Fig 7  | `fig7_within_group_panels.pdf/.png`       | Within-group 4-metric detail, one row per group                                       |
| Fig 8  | `fig8_violin_distributions.pdf/.png`      | Seed distributions (violin + mean/CI) — requires `--raw results.csv`                  |

---

## Statistical Methodology

### Tests

| Method                                       | Purpose                                                                                                                    |
|----------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| **Wilcoxon signed-rank** (paired, two-sided) | Tests whether each condition differs from `full_system`. Pairing by seed gives maximum power without normality assumption. |
| **Benjamini-Hochberg FDR correction**        | Applied within each group. Report FDR-corrected **q-values**, not raw p-values.                                            |
| **Rank-biserial r**                          | Standardised effect size. `                                                                                                |r|`: < 0.1 negligible · 0.1 small · 0.3 medium · 0.5 large. |
| **95% bootstrap CI**                         | BCa method when n ≥ 10 seeds; normal approximation otherwise.                                                              |

### Number of seeds

- **15 seeds** (default) — provides ~80% power for medium effects (|r| ≈ 0.3) at α = 0.05 after FDR correction.
- Minimum 5 seeds for Wilcoxon test to be valid. 10 seeds is acceptable if 15 is too slow.

### Interpretation guide

| q-value   | Stars | Meaning                |
|-----------|-------|------------------------|
| q < 0.001 | ***   | Highly significant     |
| q < 0.01  | **    | Significant            |
| q < 0.05  | *     | Marginally significant |
| q ≥ 0.05  | ns    | Not significant        |

---

## How to Report in a Paper

### In the text

> "We conduct an ablation study across four groups (Table N, Figure N).
> Each group isolates one architectural component by disabling it or
> replacing it with a simpler alternative.
> All comparisons are against the **Full System** (control).
> We run 15 independent seeds per condition (same seed for control and
> ablation, enabling paired tests) with 5000 simulation steps each.
> Statistical significance is assessed with the Wilcoxon signed-rank test
> (paired, two-sided) with Benjamini-Hochberg FDR correction;
> practical significance is measured with the rank-biserial correlation r."

### Citing individual results

> "Removing Tier-2 local replanning (**no_local_replan**) reduces throughput
> by 12.3% (q < 0.01, r = 0.52 — large effect), confirming that local
> reactive planning is essential for agent performance in dynamic environments."

### Figures for the paper

Recommended figure selections for a conference paper:

| Figure    | Use case                                                                |
|-----------|-------------------------------------------------------------------------|
| **Fig 1** | Main ablation result — always include                                   |
| **Fig 4** | Effect size forest — replaces or complements Fig 1 for concise papers   |
| **Fig 5** | Safety-efficiency scatter — essential for human-robot interaction claim |
| **Fig 6** | Heatmap — appendix or supplementary material                            |
| **Fig 7** | Within-group detail — supplementary                                     |

LaTeX table (`table.tex`) contains all metrics; trim columns to fit page.

---

## Estimated Runtime

Assuming 15 seeds, 5000 steps, 20 agents, 5 humans, warehouse-20-40 map, PBS solver.

| Group   | Conditions | Total runs | Est. (1 core) | Est. (all cores) |
|---------|------------|------------|---------------|------------------|
| A       | 4          | 60         | ~5 h          | ~25 min          |
| B       | 2          | 30         | ~2.5 h        | ~15 min          |
| **All** | **6**      | **90**     | **~7.5 h**    | **~40 min**      |

Always use `--workers 0` (auto-detect all cores) for full runs.

---

## Directory Structure

```
scripts/ablation/
├── README_ABLATION.md         ← this file
├── __init__.py
├── ablation_utils.py          ← conditions dict, stats, I/O, runners
├── run_ablation_study.py      ← main CLI runner
└── plot_ablation.py           ← 8 figure types

logs/ablation/                 ← auto-created
└── paper_v1_2026-03-13_10-00-00/
    ├── results.csv
    ├── summary.csv
    ├── table.tex
    ├── group_A_results.csv
    ├── group_A_summary.csv
    ├── group_B_results.csv
    ├── group_B_summary.csv
    └── plots/
        ├── fig1_throughput_by_group.pdf
        ├── fig1_throughput_by_group.png
        ├── fig2_safety_panel.pdf
        ├── ...
        └── fig8_violin_distributions.png
```

---

## Connection to the Tuning Pipeline

The ablation study should run **on top of the fully-tuned configuration**
from `scripts/tuning/`. Pass the tuned values via `--best-*` flags:

```
Tuning Step 1/3  →  --best-horizon  --best-replan-every
Tuning Step 4/6  →  --best-fov-radius  --best-safety-radius
Tuning Step 7    →  --best-commit-horizon  --best-delay-threshold
```

This ensures ablation comparisons are fair: the Full System uses the
optimal configuration, and each ablation changes exactly one thing.