# Experiments coverage matrix

Generated against commit: `31bd5e9cd6bd915fcccb460d10a2e4e1f2631969`
Last regenerated: 2026-05-13T08:06:53Z

Working tree status at audit time: clean (only this file is untracked).

## Status summary

- **READY** (can launch immediately): **6**
- **DATA EXISTS** (already complete): **6**
- **PARTIAL** (some artifacts present): **2**
- **MISSING** (needs to be built): **5**

Total: 19 experiments.

---

## Phase 1 — Mandatory paper sweeps

All seven launchers reference `configs/eval/paper/${SWEEP_NAME}.yaml` via a
shared `CONFIG_PATH=` template; the variable resolves to the correct yaml in
each case. All seven YAMLs parse with `yaml.safe_load`. All seven shell
launchers pass `bash -n`.

| # | Experiment | Status | Script | Config | Data | Notes |
|---|---|---|---|---|---|---|
| E1 | Token-passing ablation | PARTIAL | `scripts/run_sweeps/run_token_passing_ablation.sh` (bash -n OK) | `configs/eval/paper/token_passing_ablation.yaml` (parse OK) | `logs/paper/token_passing_ablation/results.csv` (26 lines = 25 data rows; expected ~60) | Existing CSV is a partial run (~42% of expected). Resume via `--resume` flag in the launcher. Header has all 63 expected columns. |
| E2 | H/R decoupling auxiliary | READY | `scripts/run_sweeps/run_aux_h_r_decoupling.sh` (bash -n OK) | `configs/eval/paper/aux_h_r_decoupling.yaml` (parse OK) | — at `logs/paper/aux_h_r_decoupling/results.csv`. A smoke run exists at `logs/paper/aux_h_r_decoupling_smoke/results.csv` (45 rows) but is a separate directory. | Smoke directory is not the production output path; launcher writes to `aux_h_r_decoupling/`. |
| E3 | FoV × safety-radius grid | READY | `scripts/run_sweeps/run_fov_safety.sh` (bash -n OK) | `configs/eval/paper/fov_safety.yaml` (parse OK) | — | No CSV yet. ~400 rows expected. |
| E4 | Baseline comparison | READY | `scripts/run_sweeps/run_baseline_comparison.sh` (bash -n OK) | `configs/eval/paper/baseline_comparison.yaml` (parse OK) | — | ~720 rows expected. |
| E5 | Scaling exogenous | READY | `scripts/run_sweeps/run_scaling_exogenous.sh` (bash -n OK) | `configs/eval/paper/scaling_exogenous.yaml` (parse OK) | — | ~760 rows expected. |
| E6 | Scaling agents | READY | `scripts/run_sweeps/run_scaling_agents.sh` (bash -n OK) | `configs/eval/paper/scaling_agents.yaml` (parse OK) | — | ~1040 rows expected; three-group config (random-64-64-10, warehouse-10-20-10-2-1, -2-2). |
| E7 | Solver substitutability | READY | `scripts/run_sweeps/run_solver_sensitivity.sh` (bash -n OK) | `configs/eval/paper/solver_sensitivity.yaml` (parse OK) | — | ~3360 rows expected — largest sweep. |

---

## Phase 2 — Already-done calibration

All six CSVs are present with the expected schema. Row counts are within tolerance.

| # | Experiment | Status | Script | Config | Data | Notes |
|---|---|---|---|---|---|---|
| E8 | Calibration v1 | DATA EXISTS | `scripts/calibrate_solver_budgets.py` | — | `logs/calibration/raw_measurements.csv` (2161 lines = 2160 data rows) | Matches upper-bound expectation (2160). Schema: solver, map, num_agents, num_humans, seed, replan_idx, status, … |
| E9 | Calibration v2 §5.4 | DATA EXISTS | `scripts/calibrate_solver_budgets.py` | — | `logs/calibration/raw_measurements_v2.csv` (649 lines = 648 data rows) | Exactly 648. Used by decomposition §5.4 (72 cells). |
| E10 | Calibration v2 §5.5 | DATA EXISTS | `scripts/calibrate_solver_budgets.py` | — | `logs/calibration/raw_measurements_v2_5_5.csv` (973 lines = 972 data rows) | Exactly 972. Used by decomposition §5.5 (108 cells). |
| E11 | Stern bare benchmark | DATA EXISTS | `scripts/calibrate_solver_benchmarks.py` | — | `logs/calibration/raw_measurements_benchmark.csv` (1801 lines = 1800 data rows) | Exactly 1800. |
| E12 | Stern + exo §5.4 | DATA EXISTS | `scripts/calibrate_solver_benchmarks_with_exo.py` | — | `logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv` (1801 lines = 1800 data rows) | Exactly 1800. |
| E13 | Stern + exo §5.5 | DATA EXISTS | `scripts/calibrate_solver_benchmarks_with_exo.py` | — | `logs/calibration/raw_measurements_benchmark_with_exo_5_5.csv` (2701 lines = 2700 data rows) | Exactly 2700. |

**Decomposition reports** (all three present and load):

- `logs/calibration/decomposition_summary.md` — references both 24.0× (§5.4) and 19.3× (§5.5) headline ratios.
- `logs/calibration/allocator_vs_exogenous_decomposition_5_4.md` — headline ratio **24.0×** (mean allocator-driven contribution vs. mean exogenous-driven contribution across high-density warehouse cells).
- `logs/calibration/allocator_vs_exogenous_decomposition_5_5.md` — headline ratio **19.3×** with identical structure on the §5.5 cohort.

Cross-check: each report cites the same row counts found in the CSVs (648 / 1800 / 1800 for §5.4; 972 / 1800 / 2700 for §5.5), so the underlying data is sufficient to compute the published ratios.

---

## Phase 3 — Defensive experiments

| # | Experiment | Status | Script | Config | Data | Notes |
|---|---|---|---|---|---|---|
| E14 | Allocator alternatives | PARTIAL | — (no dedicated sweep script) | — | — | Four allocator implementations exist in code: `GreedyNearestTaskAllocator`, `HungarianTaskAllocator`, `AuctionBasedTaskAllocator`, `CongestionAvoidanceTaskAllocator` in `src/ha_lmapf/task_allocator/task_allocator.py`. No directory `src/ha_lmapf/global_tier/allocators/` exists. `scripts/run_hyperparameter_tuning.py` enumerates `["greedy", "hungarian", "auction", "congestion_avoidance"]`; `scripts/evaluation/run_evaluation.py:390` iterates over them; `scripts/evaluation/plot_results.py` knows the labels. As of v1.4-pre-direction-a-activation every paper config hard-codes `task_allocator: congestion_avoidance` (was `greedy` prior). So: implementations + tuning hooks present, paper-ready sweep config is `configs/eval/paper/allocator_alternatives.yaml`. |
| E15 | Map diversity | MISSING | — | — | — | Every Phase-1 config uses only `random-64-64-10`, `warehouse-10-20-10-2-1`, `warehouse-10-20-10-2-2`. `room-32-32-4.map` and `den520d.map` exist on disk under `data/maps/` but are not referenced by any paper YAML. Commits `a534436` ("drop den520d from all tuning + solver-comparison + evaluation scripts") and `16ef0dd` ("tune_horizon: drop den520d") explicitly removed den520d from the experimental set, so re-adding den520d would reverse a deliberate decision. |
| E16 | Alternative human model | MISSING | — | — | — | `src/ha_lmapf/humans/models.py` defines `RandomWalkHumanModel`, `AisleFollowerHumanModel`, `AdversarialHumanModel`, `MixedPopulationHumanModel`, `ReplayHumanModel`. No `biased_walk` or `boltzmann` class is defined. All paper configs set `human_model: random_walk` (with `map_to_human_model` overriding warehouse maps to `aisle`). No paper config exercises `adversarial` or `mixed_population` as the headline variant; would need both a new YAML and possibly a new model class for Boltzmann-rational. |
| E17 | Budget sensitivity | MISSING | — | — | — | All seven paper YAMLs hard-code `solver_timeout_s: 10.0`. No axis sweeps the budget across {1, 5, 10, 30}s. `scripts/calibrate_solver_budgets.py` exists for the calibration cohort but does not write into `logs/paper/`. |

---

## Phase 4 — Strengthening

| # | Experiment | Status | Script | Config | Data | Notes |
|---|---|---|---|---|---|---|
| E18 | Extra seeds (≥30) on headline cells | MISSING | — | — | — | Every paper config sets `seeds: [0..9]` (10 seeds). No high-seed (≥30) override config exists. |
| E19 | Horizon-defense combined plot | MISSING | — | — | — | `scripts/tuning/tune_horizon.py`, `tune_horizon_fast.py`, `tune_horizon_faster.py`, `tune_horizon_replan.py` exist. `configs/eval/paper/solver_sensitivity.yaml` has horizon-axis support (`statistical_groupby: global_solver,map_path,horizon,num_agents`). But no combined-plot generator stitches `tune_horizon` output with the `solver_sensitivity` horizon slice. |

---

## Per-status detail

### MISSING experiments

**E15 — Map diversity (room-32-32-4 / den520d)**
- Closest existing template: `configs/eval/paper/baseline_comparison.yaml` (multi-map sweep).
- Estimated effort: small (add map entries) but den520d-specific re-addition reverses commit `a534436`. Recommend `room-32-32-4` only, or skip.
- Compute cost: roughly the per-map share of baseline_comparison (~720 / 3 ≈ 240 runs per added map).

**E16 — Alternative human model**
- Closest template: any Phase-1 config; swap `human_model: random_walk` for `adversarial` or `mixed_population` (already implemented).
- Estimated effort: small for swapping to existing classes; medium for adding Boltzmann-rational (new class in `src/ha_lmapf/humans/models.py`).
- Compute cost: per swap, repeat baseline_comparison-scale runs (~720 rows).

**E17 — Budget sensitivity**
- Closest template: `configs/eval/paper/solver_sensitivity.yaml` (already uses `solver_timeout_s` in `base:`).
- Estimated effort: small — add `solver_timeout_s` to the sweep block with values `[1.0, 5.0, 10.0, 30.0]`; restrict to warehouse-10-20-10-2-2 at |M|=200.
- Compute cost: 1 map × 1 |M| × 4 budgets × 4–6 solvers × 10 seeds = 160–240 runs.

**E18 — Extra seeds (≥30)**
- Closest template: any Phase-1 config; pick the 3–5 headline cells from the abstract and override `seeds: [0..29]`.
- Estimated effort: small (config) but large (compute) — 3× the seed budget of those cells.
- Compute cost: depends on which cells; roughly 3× their current row count.

**E19 — Horizon-defense combined plot**
- Closest template: `scripts/tuning/tune_horizon.py` output + horizon slice of `logs/paper/solver_sensitivity/results.csv` (not yet produced — E7 must complete first).
- Estimated effort: medium — write a plot script that reads both sources and overlays.
- Compute cost: zero new compute once E7 is done; only plotting.

### PARTIAL experiments

**E1 — Token-passing ablation**
- Present: launcher, config (parse OK), 25 data rows in `logs/paper/token_passing_ablation/results.csv`, full 63-column header.
- Missing: ~35 additional rows to reach the expected ~60. The launcher's `--resume` mode should finish the run.

**E14 — Allocator alternatives**
- Present: three allocator classes (`GreedyNearestTaskAllocator`, `HungarianTaskAllocator`, `AuctionBasedTaskAllocator`) in `src/ha_lmapf/task_allocator/task_allocator.py`; tuning hook (`scripts/run_hyperparameter_tuning.py`); evaluation hook (`scripts/evaluation/run_evaluation.py:390`); plot labels (`scripts/evaluation/plot_results.py`).
- Missing: no `configs/eval/paper/allocator_alternatives.yaml`; no `scripts/run_sweeps/run_allocator_alternatives.sh`; no entry in `run_all_sequential.sh`; no results.csv.

---

## Recommended next actions

1. **Finish E1 (token-passing ablation) and launch the remaining six Phase-1 sweeps.** The smallest sweep is already 42% done; resuming and then chaining E2–E7 produces the full headline table. This is the highest-priority item because it unblocks every paper figure that depends on the `logs/paper/*/results.csv` tree, and because the Phase-2 calibration evidence (24.0× / 19.3× ratios) is already complete and only waits on Phase-1 to be cross-referenced.
2. **Author E14 (allocator alternatives) as the cheapest defensive add.** All three allocator implementations already work in the simulator; a single new YAML + launcher restricted to one warehouse map × |M|=200 × 3 allocators × 4 solvers × 10 seeds (~120 rows) directly answers "is the allocator-driven gap an artifact of greedy?" — which is the §5.4 narrative.
3. **Add E17 (budget sensitivity) as the second defensive add.** It is a one-line config change (extend `solver_timeout_s` to a list in solver_sensitivity), small compute (~200 rows), and directly defends the §5.1 "10s is enough" verdict referenced in `docs/REVISION_AUDIT.md`. Defer E15 (recommend `room-32-32-4` only, not den520d, given commit `a534436`), E16, E18, E19 until reviewer feedback indicates which is required.

---

## Phase 1 launch readiness

**Status: NO (one blocker).**

- 6 of 7 Phase-1 experiments are READY (E2–E7).
- 1 is PARTIAL (E1, token-passing ablation): 25 of ~60 rows present.
- `scripts/run_sweeps/run_all_sequential.sh` exists, syntax checks clean, lists exactly the seven sweeps in size order (smallest first) with expected row counts, and is designed to skip fully-complete sweeps and resume partial ones via each launcher's `--resume` flag.

**Recommended launch command** (the script handles the E1 partial state automatically):

```
tmux new -d -s paper_sweeps bash scripts/run_sweeps/run_all_sequential.sh
```

Detach with `Ctrl-B D`. Reattach with `tmux attach -t paper_sweeps`. Once this run completes, all seven Phase-1 cells become DATA EXISTS and only Phase-3/4 entries remain MISSING.
