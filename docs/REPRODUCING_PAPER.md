# Reproducing the POE-LMAPF Paper Results

This document lists the exact commands required to reproduce every
figure and table in paper Section 5 from a clean checkout of this
repository.  All commands assume the repo root as CWD.

## 0.  One-time setup

```bash
# Create / activate a virtualenv (Python 3.10+).
python3 -m venv .venv
source .venv/bin/activate

# Install runtime dependencies and the package itself.
pip install -r requirements.txt
pip install -e .

# Maps — the three paper maps are checked in; this is just an
# idempotent integrity check that re-fetches from MovingAI if needed.
bash scripts/download_maps.sh

# Solver binaries — all six paper solvers ship under
# src/ha_lmapf/global_tier/solvers/.  CBSH2-RTC, MAPF-LNS2, and PBS
# dynamically link against libboost-program-options 1.74; on
# Ubuntu 24.04 LTS:
sudo apt-get install -y libboost-program-options1.74.0 libboost-filesystem1.74.0

# Sanity-check the solver and harness wiring.
python -m pytest tests/ -q
```

The full test suite (~420 tests, 11 skipped if no PIBT2/RHCR build) takes
about 30 s.  Three solver binaries (PIBT2, RHCR) are non-functional on
some CI images — see ``docs/SOLVER_STATUS.md``; rebuild from upstream if
you need them.

## 1.  Per-section commands

Each section runs three steps:

1.  **Run sweep** — ``run_paper_experiment.py`` with the corresponding
    YAML.  Use ``--workers N`` to parallelise across cores; on a
    cluster, shard with ``--seed-shard i/N`` and merge the
    ``results.csv`` files afterwards.
2.  **Plot figure** — ``plot_paper_figures.py``.
3.  **Summary table** *(when applicable)* —
    ``build_summary_tables.py``.

Pass ``--resume`` on subsequent runs to skip already-completed
configs.

### Section 5.2 — Tier-1 solver sensitivity

Sweep size: **3360 runs** (6 solvers × 7 horizons × 4 agent counts ×
2 maps × 10 seeds).  At a per-run cost of roughly 30–60 s on the paper
maps, expect ~30–60 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/solver_sensitivity.yaml \
    --out logs/paper/solver_sensitivity \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/solver_sensitivity \
    --out figures/paper --figure horizon

python scripts/evaluation/build_summary_tables.py \
    --results logs/paper/solver_sensitivity \
    --out tables/paper --table 1
```

Outputs: ``figures/paper/horizon_sweep_*.png`` and
``tables/paper/table1_solver_substitutability.{md,tex}``.

### Section 5.3 — FoV / safety-radius sweep

Sweep size: **400 runs** (5 r_fov × 4 r_safe × 2 maps × 10 seeds).
Roughly 4–8 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/fov_safety.yaml \
    --out logs/paper/fov_safety \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/fov_safety \
    --out figures/paper --figure fov_safety
```

Outputs: ``figures/paper/fov_safety_<map>.png`` per map.

### Section 5.4 part 1 — scaling in number of controlled agents |M|

Sweep size: **1040 runs** (4 solvers × asymmetric per-map |M| grids ×
10 seeds).  Larger agent counts on the warehouse maps dominate cost;
budget ~20–40 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/scaling_agents.yaml \
    --out logs/paper/scaling_agents \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/scaling_agents \
    --out figures/paper --figure scaling_agents
```

### Section 5.4 part 2 — scaling in number of exogenous agents |X|

Sweep size: **760 runs**.  Budget ~15–30 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/scaling_exogenous.yaml \
    --out logs/paper/scaling_exogenous \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/scaling_exogenous \
    --out figures/paper --figure scaling_exogenous
```

### Section 5.5 — baseline comparison

Sweep size: **720 runs** (4 methods × asymmetric per-map |M| grids ×
10 seeds × 1500 steps).  Budget ~10–20 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/baseline_comparison.yaml \
    --out logs/paper/baseline_comparison \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/baseline_comparison \
    --out figures/paper --figure baselines

python scripts/evaluation/build_summary_tables.py \
    --results logs/paper/baseline_comparison \
    --out tables/paper --table 2
```

Outputs: ``figures/paper/baseline_<map>.png`` and
``tables/paper/table2_baseline_comparison.{md,tex}``.

### Token Passing Ablation (§4.3 hanging promise)

Paper §4.3 says *"Token Passing is treated as an ablation in §5.5"*
but the §5.5 baseline matrix as written has no Token Passing row.
This sweep stages the data the user needs to either add a Token
Passing comparison to §5.5 or remove the §4.3 forward reference.
See ``docs/PAPER_TODO.md``.

Sweep size: **60 runs** (2 modes × 3 densities × 10 seeds).
``warehouse-10-20-10-2-2``, $|X| = 100$, $|M| \in \{50, 150, 250\}$,
``simulation_steps = 1500`` (matches the §5.5 baseline_comparison
length so the bar charts are directly comparable to the §5.5
figures).  Budget ~1–2 core-hours.

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/token_passing_ablation.yaml \
    --out logs/paper/token_passing_ablation \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/token_passing_ablation \
    --out figures/paper --figure token_passing_ablation
```

Output: ``figures/paper/token_passing_ablation.png`` — three side-by-
side bar charts (throughput, exogenous-attributable violations,
wait_fraction) with 95 % bootstrap CI error bars, comparing Priority
Rules vs. Token Passing at each $|M|$.

### Auxiliary: H/R decoupling (response-letter material, not in main paper)

Reviewer-3 of the previous round questioned the paper §5.2 attribution
that the throughput drop with $H$ is driven by the
$R = \lfloor H/2 \rfloor$ coupling used in the main sweep.  This
auxiliary sweep holds $R$ fixed and varies $H$, isolating the horizon
contribution from the replan cadence.

Sweep size: **110 runs** (11 valid $(H, R)$ cells × 10 seeds).
``warehouse-10-20-10-2-2`` only, $|M| = |X| = 50$, LaCAM\*, paper
10 s solver budget, 2000 lifelong steps.  Cells with $R \ge H$ are
omitted as degenerate (the rolling-horizon planner replans only after
the horizon is exhausted, so $H$ plays no role).

```bash
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/aux_h_r_decoupling.yaml \
    --out logs/paper/aux_h_r_decoupling \
    --workers 16 --resume

python scripts/evaluation/plot_paper_figures.py \
    --results logs/paper/aux_h_r_decoupling \
    --out figures/paper --figure h_r_decoupling
```

Output: ``figures/paper/aux_h_r_decoupling.png`` — one line per $H$
value, x-axis is $R$, y-axis is throughput, with shaded 95 % CI bands.

**Interpretation rule.** If the curves are roughly flat in $H$ at
fixed $R$ (the $H = 20$ / $40$ / $80$ lines stack on top of each
other for a given $R$), the paper's coupling-attribution claim
holds.  If they separate vertically at fixed $R$, the $H$ effect is
real and the paper interpretation needs revising before resubmission.

## 1.4  Validating paper numerical claims

After the full experiment matrix has been run, validate every
numerical claim in §5.2-§5.5 against the actual results:

```bash
python scripts/evaluation/validate_paper_claims.py \
    --claims        docs/PAPER_NUMERICAL_CLAIMS.yaml \
    --results-root  logs/paper \
    --out           reports/claim_validation.md \
    --tables-out    reports/claim_validation_tables.tex \
    --section       all
```

Outputs:

* ``reports/claim_validation.md`` — Markdown report grouped by
  verdict (**Refuted** / **Now weaker** / **Now stronger** /
  **Confirmed** / **Skipped**), with a suggested replacement
  sentence under every Refuted / Now-weaker entry.
* ``reports/claim_validation_tables.tex`` — booktabs LaTeX with
  cell-level auto-tabulation for Tables 1 and 2 (cells highlighted
  yellow as a hint that the user should cross-check against the
  paper PDF).

The user reads the Markdown report and edits the paper accordingly.
``docs/PAPER_TODO.md`` carries the checklist of paper-prose updates
required before resubmission.

## 1.5  Statistical Appendix

For every sweep that names a ``reference_condition`` in its YAML
(currently ``baseline_comparison.yaml`` against ``ours`` and
``solver_sensitivity.yaml`` against ``lacam_official``), the harness
auto-invokes the appendix-grade pairwise pipeline at the end of the
sweep.  Output lands under ``<out>/stats/``.

The pipeline can also be run standalone on any ``results.csv``:

```bash
# Section 5.5 — paired comparisons against Ours.
python scripts/evaluation/statistical_analysis.py \
    --results logs/paper/baseline_comparison \
    --out     stats/paper/baseline_comparison \
    --groupby method,map_path,num_agents,num_humans \
    --against ours \
    --metrics throughput,violations_agent_attributable,violations_exogenous_attributable,wait_fraction

# Section 5.2 — paired comparisons against LaCAM (reference_condition: lacam_official).
python scripts/evaluation/statistical_analysis.py \
    --results logs/paper/solver_sensitivity \
    --out     stats/paper/solver_sensitivity \
    --groupby global_solver,map_path,horizon,num_agents \
    --against lacam_official \
    --metrics throughput,violations_agent_attributable,mean_planning_time_ms
```

Outputs (per invocation):

| File                          | Content                                                                                  |
|-------------------------------|-------------------------------------------------------------------------------------------|
| ``pairwise_comparisons.csv``  | one row per (condition × metric) — n, means, mean diff, BCa CI, Shapiro-Wilk, Wilcoxon, sign test, Cohen's $d$, rank-biserial $r$, post-hoc power, raw / BH-FDR-adjusted $p$, verdict |
| ``friedman_omnibus.csv``      | one row per metric — $\chi^2$, df, $p$, Kendall's $W$                                    |
| ``descriptive_stats.csv``     | one row per (condition × metric) — n, mean, std, median, IQR, min, max, skew, kurtosis  |
| ``significance_report.tex``   | booktabs LaTeX table per metric — drop-in appendix material                              |
| ``significance_report.md``    | same content as Markdown                                                                  |

Methodology notes (mirrored in ``docs/experimental_setup.md``):

* Paired across seeds within each $(\textsf{groupby} \setminus \textsf{reference\_field})$ cell.
* Wilcoxon signed-rank, two-sided.  Sign test reported as a sanity backup.
* BH-FDR correction within each metric across all conditions.
* BCa bootstrap (4 000 resamples) for the mean of paired differences when $n \ge 10$; percentile fallback otherwise.
* Post-hoc power approximated by paired-$t$ analytic power at the observed Cohen's $d$ (Pitman ARE of Wilcoxon vs.\ paired-$t$ ≈ 0.955 under normality).
* Verdict thresholds: ``***`` $p_{\mathrm{adj}} < 0.001$, ``**`` $< 0.01$, ``*`` $< 0.05$, ``ns`` otherwise.

## 2.  Sharding across a cluster

For very large sweeps (5.2 in particular), split by seed across nodes:

```bash
# Node 0 (handles seeds 0, 4, 8 if N=4):
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/solver_sensitivity.yaml \
    --out logs/paper/solver_sensitivity_shard0 \
    --workers 16 --seed-shard 0/4 --resume

# Node 1 (handles seeds 1, 5, 9):
... --seed-shard 1/4 --out logs/paper/solver_sensitivity_shard1 ...

# After all shards finish, concatenate:
python -c "
import pandas as pd, glob
dfs = [pd.read_csv(f) for f in sorted(glob.glob('logs/paper/solver_sensitivity_shard*/results.csv'))]
pd.concat(dfs, ignore_index=True).drop_duplicates(subset='run_id').to_csv(
    'logs/paper/solver_sensitivity/results.csv', index=False)
"
```

## 3.  Total run counts (sanity)

| YAML                                                      | Runs |
|-----------------------------------------------------------|-----:|
| ``solver_sensitivity.yaml``  (Section 5.2)                | 3360 |
| ``fov_safety.yaml``          (Section 5.3)                |  400 |
| ``scaling_agents.yaml``      (Section 5.4 part 1)         | 1040 |
| ``scaling_exogenous.yaml``   (Section 5.4 part 2)         |  760 |
| ``baseline_comparison.yaml`` (Section 5.5)                |  720 |
| **Total**                                                 | **6280** |

These counts are pinned by ``tests/test_harness_smoke.py``.

## 4.  Recommended execution order

If you want diagnostic value as fast as possible, run sweeps in this
order:

1. **Section 5.5 — baselines** (720 runs).  Cheapest paper-figure
   sweep, validates that the four methods (Ours / RHCR / PIBT2-FR /
   No-Buffer) execute end-to-end and that ``violations_agent_attributable``
   is exactly zero for Ours and No-Buffer (Theorem 1 invariant).
2. **Section 5.3 — FoV / safety** (400 runs).  Small and self-
   contained; produces the r_safe = 0 ablation point used by
   No-Buffer.
3. **Section 5.5 — baseline comparison plot** (uses the same
   results).
4. **Section 5.4 — scaling sweeps** (1040 + 760 = 1800 runs).  Higher
   compute cost but the runs are independent, so they shard cleanly.
5. **Section 5.2 — solver sensitivity** (3360 runs, the longest sweep)
   last.

This order lets you spot-check the Theorem 1 invariant on a small
sweep first, then the scaling shape, before committing to the full
solver-sensitivity matrix.

## 5.  Troubleshooting

* **``solver_timeouts > 0`` for many rows** — possible at high agent
  counts when CBSH2-RTC or PBS hits the 10 s budget.  Increase
  ``solver_timeout_s`` in the YAML's ``base`` block, or read
  ``docs/SOLVER_STATUS.md`` for the per-solver expected behaviour.
* **PIBT2 binary returns all-WAIT** — the shipped binary was compiled
  with a hardcoded map directory; rebuild from
  https://github.com/Kei18/pibt2 and copy the new binary to
  ``src/ha_lmapf/global_tier/solvers/mapf_pibt2``.
* **RHCR binary segfaults** — same root cause; rebuild from
  https://github.com/Jiaoyang-Li/RHCR.
* **Resume not skipping** — confirm the existing ``results.csv`` has
  ``status=ok`` for the rows you expect skipped.  Rows with
  ``status=error`` or ``status=timeout`` are re-attempted.
