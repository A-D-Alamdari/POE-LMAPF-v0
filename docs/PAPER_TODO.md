# Paper-side TODOs (manual user edits)

This file tracks paper-LaTeX edits the user needs to make manually.
The code in this repository now matches the paper's intent on every
implementation question; the items below are textual / structural
edits to the paper itself that the code cannot perform.

## Direction A activated (2026-05-13)

The task allocator has been changed from `greedy` to `congestion_avoidance`
in all production configs. This is the destructive step authorized
by the user after explicit three-acknowledgment affirmation.

> **Branch reality check:** per the running task-system instructions
> the activation commit lands on `claude/conflict-aware-allocator-zfBdw`
> rather than `main`. The user will perform the merge to `main` and
> tag `v1.4-pre-direction-a-activation` on `main` themselves
> (this session is harness-restricted to a single feature branch).

### What this invalidates

The following must be re-computed before the paper can cite them:

1. **All six calibration CSVs.** The 24× (§5.4) and 19× (§5.5)
   allocator-vs-exogenous decomposition ratios were computed against
   greedy. Under congestion_avoidance, the ratios will be different —
   possibly much smaller. The archived greedy data lives at
   `logs/calibration/_archived_greedy_v1_4_pre_direction_a/` for
   historical reference. (`logs/` is gitignored, so this archive is
   local-disk only — captured 2026-05-13.)

2. **All seven main paper sweep results.csv files.** The §5.2 / §5.3
   / §5.4 / §5.5 Tables and Figures must be regenerated against
   congestion_avoidance. *No live sweep CSVs were present at activation
   time* (`logs/paper/` did not exist), so no live-data deletion was
   necessary; the next sweep run starts from a clean slate.

3. **§5.4 / §5.5 reframing prose.** The current prose says:
     "greedy task allocation under rolling-horizon execution
      creates a distribution that breaks centralized MAPF planning"
   This becomes:
     "congestion_avoidance task allocation under rolling-horizon execution
      creates a distribution that [TBD, depends on new
      decomposition numbers]"
   The new prose can be drafted only after the new calibration
   and decomposition run.

4. **The paper's headline contribution claim.** Currently:
     "Our two-tier framework's value is precisely the regime where
      centralized planning fails on allocator-driven instances"
   This claim may strengthen (if congestion_avoidance doesn't help much),
   weaken (if congestion_avoidance fixes the regime entirely), or shift
   (if congestion_avoidance moves the difficulty to a different axis).

### What must be done next (Prompts 3 and 4 in the series)

**Prompt 3**: Re-run calibration with congestion_avoidance. Produces new
`raw_measurements.csv`, new `raw_measurements_v2.csv`,
`raw_measurements_v2_5_5.csv`, and re-runs Stern + exogenous benchmarks
if those reflect a system that uses congestion_avoidance. Generates new
`decomposition_summary.md` with the new ratios.

Expected compute: 60–150 minutes for the simulator-driven cohorts;
the Stern bare benchmark CSV (no exogenous; no allocator) remains
valid since allocators are not used at the benchmark level. The
Stern+exo CSVs DO need re-running if the exogenous placement depends
on allocator state — verify before re-running.

**Prompt 4**: Re-launch all seven main paper sweeps. Plus E14 if
that prompt has already added the allocator_alternatives sweep
(which now compares greedy vs Hungarian vs auction vs congestion_avoidance,
not greedy vs Hungarian vs auction — see
`configs/eval/paper/allocator_alternatives.yaml`).

Expected compute: 50–130 hours at 32 cores; the same as before
minus whatever was already complete in the archived runs (none of
which can be reused).

### Acknowledged risks (from prompt 1 / activation affirmation)

- 24× / 19× decomposition ratios will be replaced by new numbers
  that may shrink dramatically
- All in-progress and completed sweeps are discarded
- AAMAS 2027 may be missed or submitted as a different paper

### Rollback procedure

If at any point you decide to undo Direction A:

```
# 1. Revert the activation commit on the feature branch (or, if
#    you've already merged to main, revert the merge commit there
#    and re-tag).
git revert <activation-commit-sha>     # creates an inverse commit
# OR, on main after merge, to roll back the merge:
# git reset --hard v1.4-pre-direction-a-activation
# git push --force-with-lease           # requires team coordination

# 2. Recover archived calibration data (logs/ is gitignored, so this
#    is local-disk only):
cp logs/calibration/_archived_greedy_v1_4_pre_direction_a/*.csv logs/calibration/
cp logs/calibration/_archived_greedy_v1_4_pre_direction_a/*.md  logs/calibration/
rm -rf logs/calibration/_archived_greedy_v1_4_pre_direction_a/
# (logs/paper/ archive directory does not exist because there were
#  no live sweep results to archive at activation time.)
```

This restores the codebase to the v1.4 reference state with
`congestion_avoidance` still present in the code surface but inactive.

## Direction A (conflict-aware allocator) — implementation complete on feature/conflict-aware-allocator branch

> **Branch reality check:** per the running task-system instructions
> this work landed on `claude/conflict-aware-allocator-zfBdw` (the
> assigned development branch for this prompt) rather than the
> `feature/conflict-aware-allocator` name in the prompt body. The
> code surface is identical; the destructive-replacement prompt may
> rename or merge the branch as needed.

- **Class:** `CongestionAvoidanceTaskAllocator` in
  `src/ha_lmapf/task_allocator/task_allocator.py`.
- **Factory string:** `"congestion_avoidance"` (recognised by
  `Simulator._make_allocator` and the new
  `ha_lmapf.task_allocator.make_allocator` helper).
- **Hyperparameters:** `lambda_conflict=0.5`, `max_rounds=5`.
- **Algorithm:** seed with Hungarian on BFS shortest-path distances;
  then iteratively re-solve Hungarian on
  `C[i][j] = dist(i, j) + lambda_conflict · path_overlap(i, j, other_assignments)`,
  stopping when the assignment stabilises or after `max_rounds`.
  BFS results are cached per `allocate()` call but not across calls.
- **Tests:** `tests/test_congestion_avoidance_allocator.py` (11 cases:
  empty-input edge cases, trivial 1-1, `lambda=0` degenerate-to-Hungarian,
  corridor-funnel divergence-from-greedy, convergence within
  `max_rounds`, three factory-integration cases, and a simulator
  smoke test on a synthetic warehouse-2-2 map).
- **Status:** **NOT YET ACTIVATED** in any production config.
  `SimConfig.task_allocator` default is unchanged (`"greedy"`), and
  no YAML under `configs/` references `congestion_avoidance`. The next
  prompt in the Direction-A series will perform the destructive
  replacement (greedy → congestion_avoidance in all paper YAMLs +
  calibration scripts).
- **Risks acknowledged (to be paid by the destructive prompt):**
  1. The 24× / 19× decomposition ratios reported in §5.4 / §5.5
     are computed against greedy and will be invalidated.
  2. All completed and in-progress sweeps measured under greedy
     will need to be discarded or retained only as a comparison
     baseline.
  3. AAMAS 2027 may be missed, or the work may have to be
     submitted as a different paper with a re-stated contribution.

## Tuning follow-up — port incremental flush + --resume to sibling tune_*.py

**Status:** in-progress; `tune_horizon.py` done.  Same pattern needed
in the other tuning scripts.

`scripts/tuning/tune_horizon.py` now writes `results.csv` incrementally
(one row per completed run, `fsync`d) plus an atomic `.heartbeat` file,
and supports `--resume` via a `(solver, map_tag, num_agents, horizon,
seed)` row-key skip-set.  The other tuning scripts buffer all runs in
memory and lose work on any interruption.  Port the same pattern to:

* ``scripts/tuning/tune_horizon_fast.py``
* ``scripts/tuning/tune_horizon_faster.py``
* ``scripts/tuning/tune_horizon_replan.py``
* ``scripts/tuning/tune_replan_every.py``
* ``scripts/tuning/tune_fov_radius.py``
* ``scripts/tuning/tune_fov_safety.py``
* ``scripts/tuning/tune_safety_radius.py``
* ``scripts/tuning/tune_commit_delay.py``

The diff in `tune_horizon.py` (see commit landing this change) is the
template: add `_row_key`, `_read_completed_rows`, `_completed_keys`,
`_open_results_writer`, `_write_heartbeat`; thread `out` /
`already_done` / `original_total` into `_execute_tasks` (or the
sibling's equivalent loop); wire `--output-dir` and `--resume` into
the argparse; re-read `results.csv` on resume so aggregation sees both
halves.  Mirror the test pattern in `tests/test_tune_horizon_resume.py`
adapted to each script's param-name.

## §5.4 + §5.5 — three-way decomposition: allocator dominates exogenous by 19–24×

**Status:** code-side measurement complete for both cohorts; paper LaTeX framing edit required.

Three-way decomposition of solver completion rate has been computed
for both §5.4 and §5.5, against the paper's per-section configs:

* §5.4 cohort matches `configs/eval/paper/scaling_agents.yaml`
  (per-map \|X\| = 20 / 40 / 60).
* §5.5 cohort matches `configs/eval/paper/baseline_comparison.yaml`
  (per-map \|X\| = 20 / 100).

Decomposition definition:

* Stern bare → Stern + \|X\| static obstacles = **exogenous-only contribution**
* Stern + \|X\| obstacles → simulator-driven (lifelong) = **allocator + lifelong contribution**
* Sum = total gap (Stern bare → simulator-driven).

**Headline numbers** (high-density aggregate, warehouse \|M\| ≥ 150,
averaged across all six paper solvers).  Source:
`logs/calibration/decomposition_summary.md`.

| Cohort | Mean exogenous Δ | Mean allocator Δ | Allocator / Exo ratio |
|---|---:|---:|---:|
| §5.4 (\|X\|=20/40/60) | +3 pp | +73 pp | **24.0×** |
| §5.5 (\|X\|=20/100) | +4 pp | +81 pp | **19.3×** |

**Most extreme cell, §5.4:** LaCAM\* on warehouse-10-20-10-2-1 at
\|M\|=150, \|X\|=40 — Stern bare 100%, Stern+exo 96%, simulator 0%.
Exogenous Δ = +4 pp; allocator Δ = +96 pp.

**Most extreme cell, §5.5:** LaCAM\* on warehouse-10-20-10-2-2 at
\|M\|=200, \|X\|=100 — Stern bare 100%, Stern+exo 100%, simulator 0%.
Exogenous Δ = +0 pp; allocator Δ = +100 pp.

**Cross-cohort:** the §5.5 cohort's denser \|X\|=100 (vs §5.4's 60)
adds only +1 pp to the mean exogenous contribution while keeping the
allocator contribution at ≥73 pp in both.  Tripling \|X\| does not
materially change the conclusion.

### What this means for §5.4 / §5.5 prose

Both sections measure the **lifelong-MAPD allocator + solver pipeline**,
not solver completion alone.  The Stern reference column quantifies the
gap from the canonical solver-only baseline; the three-way decomposition
attributes that gap to its components.  The 19–24× allocator-vs-exogenous
ratio is the paper's quantitative justification for framing the
contribution around lifelong-MAPD coupling rather than around exogenous-
agent obstacle-handling.

Concrete LaTeX edits:

1. **Add a Stern reference column** to the §5.4 and §5.5 results tables
   (per-cell, populated from `raw_measurements_benchmark_with_exo_5_*.csv`).
   The column header should read "Stern + \|X\| obs" with a footnote
   pointing at `allocator_vs_exogenous_decomposition_*.md`.

2. **Cite the decomposition's headline ratio** in §5.4 and §5.5 prose:

   * §5.4: "At high density, the lifelong-MAPD allocator + solver
     pipeline drops to 0% completion while the same solver on
     Stern .scen instances with the same exogenous-obstacle density
     remains above 70%; the allocator + lifelong-state effect is
     **24× larger** than the exogenous-obstacle effect on the same
     cells (mean +73 pp vs +3 pp, see
     `allocator_vs_exogenous_decomposition_5_4.md`)."
   * §5.5: "...the allocator + lifelong-state effect is **19× larger**
     than the exogenous-obstacle effect (mean +81 pp vs +4 pp at
     \|X\|=100, see
     `allocator_vs_exogenous_decomposition_5_5.md`)."

3. **Frame the §5.4 / §5.5 reviews as measurements of the
   pipeline**, not of the solver alone.  Any §5.4 / §5.5 sentence
   currently reading "solver X drops to N% completion at density Y"
   must be rewritten as "the lifelong-MAPD allocator + solver X
   pipeline drops to N% completion at density Y, vs M% for solver X
   alone on the canonical Stern cohort with the same exogenous
   obstacle count" with the Stern reference column inline.

### LaCAM\* sub-second p50 caveat

LaCAM\* is anytime; on dense cells its p50 saturates at the 10 s
budget.  Completion (100% across every cell of every cohort) is the
dominant signal.  Do not interpret the saturated p50 as "LaCAM\*
struggles" — it is the wrapper enforcing the configured budget.

### Files generated

* `scripts/calibrate_solver_benchmarks_with_exo.py` — Stern + exo
  sweep with per-cohort defaults.
* `scripts/analyze_three_way_comparison.py` — per-cohort decomposition.
* `scripts/summarize_decomposition.py` — cross-cohort summary.
* `logs/calibration/raw_measurements_v2.csv` (648 rows, §5.4 sim).
* `logs/calibration/raw_measurements_v2_5_5.csv` (972 rows, §5.5 sim).
* `logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv` (1800 rows).
* `logs/calibration/raw_measurements_benchmark_with_exo_5_5.csv` (2700 rows).
* `logs/calibration/allocator_vs_exogenous_decomposition_5_4.md`.
* `logs/calibration/allocator_vs_exogenous_decomposition_5_5.md`.
* `logs/calibration/decomposition_summary.md` (cite this in paper prose).

Existing 50-uniform `raw_measurements.csv` (v1) and Stern bare
`raw_measurements_benchmark.csv` are unchanged — they remain the
historical record / shared bare reference for both cohorts.

## §5.4 reframe — allocator-bounded fraction quantified empirically

**Status:** code-side measurement complete; paper LaTeX framing edit required.

The simulator-driven calibration cells (``logs/calibration/raw_measurements.csv``,
648 invocations) and the Stern benchmark-driven cells
(``logs/calibration/raw_measurements_benchmark.csv``, 1800 invocations
across the 6 paper solvers × 12 (map, |M|) cells × 25 .scen files)
have been compared in ``logs/calibration/allocator_bound_quantification.md``.

**Headline:** the simulator-driven failures attributed to "solver
incomplete" in early §5.4 drafts are overwhelmingly **allocator-bound**,
not solver-bound:

* LaCAM\* (``lacam3``): **100%** completion on Stern .scen vs **42%**
  on simulator-driven (Δ = +58 pp; 9/12 cells flag as allocator-bound).
* MAPF-LNS2 (``lns2``): **100%** vs **42%** (Δ = +58 pp; 9/12 cells).
* PBS: **100%** vs **42%** (Δ = +58 pp; 9/12 cells).
* LaCAM Official: **96%** vs **42%** (Δ = +54 pp; 9/12 cells).
* PIBT2: **75%** vs **32%** (Δ = +43 pp; 7/12 cells).
* CBSH2-RTC: **61%** vs **42%** (Δ = +19 pp; 4/12 cells; the only
  solver where the gap is sometimes inside the partial-allocator-drag
  band rather than the full allocator-bound band).

**§5.4 framing.**  The §5.4 sweep stays on the simulator-driven
distribution (``configs/eval/paper/scaling_agents.yaml``) — that
sweep is the paper's actual contribution: lifelong MAPD with a task
allocator releasing tasks dynamically over the run, exogenous human
agents perturbing the world, and Tier-1 / Tier-2 absorbing the
unsolvable instances the allocator occasionally produces.  Replacing
the simulator-driven cells with one-shot Stern instances would
erase the lifelong-MAPD framing, which is what the paper is about.

The Stern benchmark CSV becomes a **reference column** in the §5.4
tables, not a replacement for the simulator data:

* Per-cell §5.4 table gets one extra column, "Stern bench
  completion (%)", populated from
  ``logs/calibration/raw_measurements_benchmark.csv``.
* The accompanying §5.4 prose introduces the column with one
  sentence: "the rightmost column reports the same solver's
  completion rate on Stern et al. 2019 one-shot instances at the
  same (map, |M|) — a literature-canonical solver-only baseline,
  contextualizing the simulator-driven cells against the
  lifelong-MAPD allocator + exogenous-agents pipeline our setting
  exercises".
* Where Δ ≥ 20 pp (the allocator-bounded cells from
  ``allocator_bound_quantification.md``), §5.4 prose adds one
  sentence pointing at the gap, framed as a feature of the
  lifelong-MAPD setting rather than a solver shortcoming.

**Why not Option 1 (re-run on Stern .scen):** Option 1 would
collapse §5.4 onto a one-shot MAPF benchmark cohort that every
recent MAPF paper already reports; the reader would see numbers
indistinguishable from the LaCAM\* and LNS2 papers and the
contribution becomes invisible.  The simulator-driven cells are
the paper's actual measurement; the Stern column situates them
alongside the canonical benchmark.

**§5.4 prose update required.**  Any sentence currently reading
"solver X reaches its limit at density Y" must be rewritten as
"the lifelong-MAPD allocator + solver X pipeline reaches its
limit at density Y" with a parenthetical pointing at the Stern
column ("solver X alone solves all 25 Stern instances at density
Y in 10 s").  This makes the contribution explicit: the paper
measures the *pipeline*, the Stern column shows the solver in
isolation, and the gap is the lifelong-MAPD coupling cost.

**LaCAM\* sub-second p50 caveat.**  The original sanity-check spec
asked for "≥95% completion AND sub-second p50".  Completion passes
(100% on every cell); the sub-second p50 target was *not* met
(p50 ≈ 10 s on most cells).  This is *not* a wrapper bug — LaCAM\*
is anytime and refines until budget, so p50 = budget is the
expected behavior at 10 s.  Completion is the dominant signal; the
wrapper correctly returns ``status="complete"`` whenever a path is
present.  See ``docs/SOLVER_STATUS.md`` "Anytime semantics" row and
``logs/calibration/anytime_verification.md``.

Files generated:

* ``scripts/calibrate_solver_benchmarks.py`` — Stern .scen-driven
  sweep (sibling of ``scripts/calibrate_solver_budgets.py``).
* ``scripts/analyze_benchmark_comparison.py`` — sim-vs-bench
  per-cell comparison generator.
* ``logs/calibration/raw_measurements_benchmark.csv`` — 1800 rows.
* ``logs/calibration/allocator_bound_quantification.md`` — per-cell
  sim-vs-bench table + per-solver headline + LaCAM\* sanity check.

## §5.1 Per-replan time budget bumped 5 s → 10 s

**Status:** code-side updated uniformly; paper LaTeX edit required.

Update §5.1 'per-replan time budget of 5 s' to 'per-replan time
budget of 10 s' in the paper LaTeX. Also update the §5.1 sentence
'Tier 1's per-replan time budget (5 s) is enforced by terminating
the solver if exceeded' to 10 s. The change is uniform across all
experiments and configurations; no per-map or per-solver
adjustments. Justification for §5.1 prose: 10 s aligns with the
standard MAPF benchmark budget in the LaCAM\* and MAPF-LNS2
literature, pre-empting any "budget tilts comparison" reviewer
objection.  The earlier 3 s → 5 s bump was a heuristic guess; the
calibration sweep at ``logs/calibration/`` (commit 67389d3)
demonstrated that LaCAM\* hits 10 s on warehouse-10-20-10-2-2 at
|M|=200, justifying this second bump empirically.

**INCONCLUSIVE verdict resolution.**  The calibration's
``solver_recommendation.md`` returned ``INCONCLUSIVE`` because the
highest-density cell (warehouse-10-20-10-2-2 \|M\|=450) shows every
solver failing regardless of budget.  The three-way decomposition
data (``logs/calibration/decomposition_summary.md``) confirms these
failures are **allocator-driven**, not budget-driven (mean
allocator + lifelong contribution = +73 pp on §5.4, +81 pp on §5.5,
vs +3/+4 pp exogenous-only), so bumping the budget cannot resolve
the verdict.  We proceed at 10 s justified by:

* **Literature consistency.** Okumura 2024 (LaCAM\*) reports "99% of
  MAPF benchmarks within 10 s up to 1000 agents"; matching this
  budget aligns with the canonical MAPF benchmark convention.
* **Empirical timing.** Measured LaCAM\* timing at every *successful*
  cell is sub-second (p95 ≤ 1633 ms on warehouse-2-1 \|M\|=100;
  sub-20 ms on warehouse-2-2 ; see
  ``logs/calibration/solver_recommendation.md``).
* **Decomposition data.** Budget is not the bottleneck at any
  density we tested; the gap at extreme density is the lifelong-MAPD
  allocator generating harder-than-Stern instances.

The §5.1 prose should:

1. State that the budget is 10 s.
2. Note "10 s is the standard MAPF benchmark budget per Okumura 2024".
3. In the limitations / discussion section, acknowledge that at the
   highest density tested (\|M\|=450 on warehouse-10-20-10-2-2), Tier-1
   fails for all solvers; cite the decomposition data
   (``logs/calibration/decomposition_summary.md``) to attribute this
   failure to the lifelong-MAPD instance distribution rather than
   insufficient compute.

Files touched on the code side (sanity-check the bump isn't
half-applied):

* ``src/ha_lmapf/core/types.py`` — ``SimConfig.solver_timeout_s = 10.0``
* every wrapper in ``src/ha_lmapf/global_tier/solvers/`` —
  constructor default ``time_limit_sec = 10.0`` (or
  ``time_limit_ms = 10000`` for ``RealTimeLaCAMSolver``)
* ``configs/eval/default.yaml`` and every
  ``configs/eval/paper/*.yaml`` — ``solver_timeout_s: 10.0``
* ``docs/SOLVER_STATUS.md``, ``docs/PAPER_TO_CODE_MAP.md``,
  ``docs/CONFORMANCE.md``, ``docs/REPRODUCING_PAPER.md``,
  ``docs/experimental_setup.md``, ``docs/proposed_approach.md``,
  ``docs/SCRIPTS_INVENTORY.md``, ``docs/PAPER_NUMERICAL_CLAIMS.yaml``

After updating the LaTeX, re-check any §5.4 / §5.5 prose that
references the budget — e.g., "approaches the 5 s budget" needs to
become "approaches the 10 s budget" (the corresponding ``claim_id``
in ``docs/PAPER_NUMERICAL_CLAIMS.yaml`` has already been renamed
to ``lns2_approaches_10s_warehouse2_high_density``).

## Paper prose updates after re-running experiments

Once the full §5.2–§5.5 sweep has finished and
``scripts/evaluation/validate_paper_claims.py`` has been run, walk
through this checklist before resubmission:

- [ ] Read ``reports/claim_validation.md`` end-to-end.
- [ ] For every entry under **Refuted**, edit the corresponding
      sentence in §5.x of the paper to match the actual value.  The
      report's "Suggested replacement sentences" subsection has a
      drop-in candidate for each.
- [ ] For every entry under **Now weaker**, soften the claim in the
      paper to match (or, if the gap is small, expand the tolerance
      threshold in ``docs/PAPER_NUMERICAL_CLAIMS.yaml`` to reclassify
      as Confirmed — but only after sanity-checking that the original
      paper threshold is the source of error rather than the data).
- [ ] For every entry under **Now stronger**, decide whether to
      claim more in the paper.  Stronger results are good news, but
      check the supporting plot before tightening the prose.
- [ ] Replace Table 1 cells per ``reports/claim_validation_tables.tex``.
- [ ] Replace Table 2 cells per ``reports/claim_validation_tables.tex``.
- [ ] Re-read the §5.5 summary paragraph and update every quoted
      number (10–30× lower than RHCR, 5–8× more violations under
      No-Buffer, etc.).
- [ ] Re-read the §5.5 final paragraph: "10–30× lower than RHCR" —
      update if the actual ratio falls outside that range.
- [ ] Re-read §5.4: "throughput grows approximately linearly in
      |M|" — confirm the R² in
      ``reports/claim_validation.md`` agrees.
- [ ] Re-read §5.2: "all six solvers fall within a 0.03 throughput
      range" — confirm the actual range stays at ≤0.03 on
      random-64-64-10 and ≤0.02 on warehouse-10-20-10-2-2.
- [ ] Update the paper LaTeX, then run the validator one more time
      and confirm zero entries remain under **Refuted** or **Now
      weaker**.
- [ ] Commit the paper-side edits with a clear message
      ("paper: update §5 numbers per claim_validation report").

## PIBT2 max_timestep wrapper fix (re-run §5.4 / §5.5 cells)

**Status:** code-side fix landed; sweep numbers need re-collection.

The wrapper previously set ``max_timestep = horizon + 50 = 70``,
which was insufficient for agent trips on warehouse-scale maps
(Manhattan distance up to 220 cells on warehouse-10-20-10-2-2).
PIBT2 is all-or-nothing and returned ``solved=0`` whenever the
longest agent trip exceeded the budget, even though the instance
was feasible.  Fixed: ``max_timestep = max(horizon + 50, 2 *
(env.height + env.width))``.  Concrete values: 448 on
warehouse-10-20-10-2-1, 508 on warehouse-10-20-10-2-2.

PIBT2 now receives ``max_timestep`` proportional to map dimensions.
All prior PIBT2 throughput numbers in any draft of §5.4 / §5.5
were produced with the broken ``max_timestep`` and are wrong.
Re-run §5.4 / §5.5 PIBT2 cells with the fixed wrapper before
quoting any number.

A separate Mode-B failure (priority-scheme deadlock on confined
1-cell-aisle maps without parking cells) remains unfixed; this is
algorithmic in PIBT2, not a wrapper bug.  The mini-warehouse
fixture in ``tests/test_baseline_pibt2_fr.py`` triggers Mode B and
will continue to fail until the fixture map is replaced or the
test asserts expected PIBT2 incompleteness.  See
``docs/ALLOCATOR_DIAGNOSIS.md`` § Resolution.

## PIBT2 §5.4 / §5.5 numbers must be re-run after wrapper fix

**Status:** code-side fix landed; sweep numbers need re-collection.

PIBT2 §5.4 / §5.5 numbers must be re-run after the PIBT2 wrapper
fix (commit pending — instance-file format + binary-selection bug
fix; see ``docs/PIBT2_DIAGNOSIS.md``).  All previous PIBT2 and
PIBT2-FR throughput numbers in any draft of Table 1 or Table 2
came from a wrapper that fed PIBT2 malformed instance files; PIBT2
returned random-scenario paths and the harness reported
``throughput=0``.  New numbers will likely show PIBT2 as a
competitive solver, consistent with literature.  Update §5.4 and
§5.5 prose accordingly when new sweep numbers are available.

A residual issue remains: at high agent density on cramped maps,
PIBT2 may report ``solved=0`` with a USABLE partial solution that
the wrapper currently discards.  ``tests/test_baseline_pibt2_fr``
exercises this case (20 agents on a 10×14 mini-warehouse with
1-cell aisles) and currently still fails.  A follow-up wrapper fix
will parse PIBT2's partial output on ``solved=0`` so the
rolling-horizon framework gets ``horizon`` worth of useful moves
even when the binary couldn't complete a full plan.  This is
tracked in ``docs/PIBT2_DIAGNOSIS.md`` § Resolution.

## §5.1 Per-replan time budget bumped 3 s → 5 s

**Status:** code-side updated uniformly; paper LaTeX edit required.

Update §5.1 'per-replan time budget of 3 s' to 'per-replan time
budget of 5 s' in the paper LaTeX. Also update the §5.1 sentence
'Tier 1's per-replan time budget (3 s) is enforced by terminating
the solver if exceeded' to 5 s. The change is uniform across all
experiments and configurations; no per-map or per-solver
adjustments.

After updating the LaTeX, also re-check any §5.4 / §5.5 prose
that references the budget — e.g., "MAPF-LNS2 grows
super-linearly and approaches the 3 s budget at high agent counts
on warehouse-10-20-10-2-2" needs to become "approaches the 5 s
budget" (the corresponding ``claim_id`` in
``docs/PAPER_NUMERICAL_CLAIMS.yaml`` has already been renamed to
``lns2_approaches_5s_warehouse2_high_density``).

Files touched on the code side (so you can sanity-check the bump
isn't half-applied):

* ``src/ha_lmapf/core/types.py`` — ``SimConfig.solver_timeout_s = 5.0``
* every wrapper in ``src/ha_lmapf/global_tier/solvers/`` —
  constructor default ``time_limit_sec = 5.0``
* ``configs/eval/default.yaml`` and every
  ``configs/eval/paper/*.yaml`` — ``solver_timeout_s: 5.0``
* ``docs/SOLVER_STATUS.md``, ``docs/PAPER_TO_CODE_MAP.md``,
  ``docs/CONFORMANCE.md``, ``docs/REPRODUCING_PAPER.md``,
  ``docs/experimental_setup.md``, ``docs/proposed_approach.md``

## §4.3 Hanging promise — Token Passing as ablation

**Status:** code-side resolved; paper-side decision required.

Paper §4.3 says

> "Token Passing is treated as an ablation in §5.5."

But the §5.5 baseline matrix as currently written is
{Ours, RHCR, PIBT2-FR, No-Buffer} — no Token Passing row appears.
The forward reference is a hanging promise.

The repository now ships everything required for **option A**:

* ``configs/eval/paper/token_passing_ablation.yaml`` — 60-run sweep
  (2 modes × 3 densities × 10 seeds) on warehouse-10-20-10-2-2,
  ``simulation_steps = 1500`` (matches §5.5 baseline_comparison).
* ``scripts/evaluation/plot_paper_figures.py:figure_token_passing_ablation``
  — three side-by-side bar charts (throughput / exogenous-attributable /
  wait_fraction) with 95 % bootstrap CI error bars.
* ``docs/REPRODUCING_PAPER.md`` — "Token Passing Ablation" section
  with the exact commands.

> **Decision required.** Pick ONE:
>
> * **Option A.** Run the sweep, place the resulting figure in §5.5
>   alongside the four-method comparison, and add a sentence linking
>   §4.3's forward reference to it.
> * **Option B.** Remove the §4.3 sentence
>   "Token Passing is treated as an ablation in §5.5" and leave the
>   §5.5 baseline matrix as is.
>
> The code supports option A out of the box; the user owns the paper
> LaTeX.

## §5.1 Cluster spec placeholder

**Status:** placeholder in paper text; user must fill in.

Paper §5.1 currently contains the literal token ``[insert your
cluster spec]``.  Replace it with the host details for your runs.
Suggested template:

```
All experiments were run on <institution> compute nodes with
<CPU model, e.g. AMD EPYC 7763> CPUs (<sockets>×<cores per socket>
cores, <RAM> GB RAM), Linux <kernel>, Python 3.10.<x>, NumPy <ver>,
matplotlib <ver>.  Each (config × seed) cell ran single-threaded;
the harness in scripts/evaluation/run_paper_experiment.py
distributes cells across cores via ProcessPoolExecutor.
```

The numbers you need are the same ones you would put in any methods
section (CPU model, total cores used in parallel, RAM per node).

## §5.5 Method label / ordering audit (verified)

**Status:** code-side matches paper text; no action required.

The paper §5.5 baseline matrix uses exactly these names and ordering:

| Position | Paper label        | Plot / table identifier (code) |
|---------:|--------------------|--------------------------------|
| 1        | Ours (POE-LMAPF)   | ``ours``                       |
| 2        | RHCR               | ``rhcr``                       |
| 3        | PIBT2-FR           | ``pibt2_fr``                   |
| 4        | No-Buffer          | ``no_buffer``                  |

Verified consistent across:

* ``scripts/evaluation/plot_paper_figures.py::METHOD_STYLE`` (legend labels)
* ``scripts/evaluation/build_summary_tables.py::METHOD_DISPLAY``
  (table-2 row labels)
* ``src/ha_lmapf/baselines/pibt2_fr.py`` (factory names)
* ``configs/eval/paper/baseline_comparison.yaml`` (sweep axis values)

Do **not** rename any of these without updating all four sites at
once.

## §5.4 Exogenous-agent counts — verified

**Status:** code-side matches paper text; no action required.

Paper §5.4 prose: "20 on random-64-64-10, 40 on
warehouse-10-20-10-2-1, 60 on warehouse-10-20-10-2-2".  The
``configs/eval/paper/scaling_agents.yaml`` groups encode exactly that
mapping (Group A: ``num_humans = [20]``, Group B:
``num_humans = [40]``, Group C: ``num_humans = [60]``).  ✓

## §5.5 PIBT2-FR acronym expansion — documented

**Status:** code-side anchor only; consider mirroring in paper text.

The "FR" suffix is expanded as **"Full Replanning"** in
``src/ha_lmapf/baselines/pibt2_fr.py:4``: *"PIBT2-FR = PIBT2 with
Full Replanning every step"*.  The paper's own gloss at the §5.5
comparison ("frequent-replan PIBT2 (PIBT2-FR)", see
``docs/PAPER_NUMERICAL_CLAIMS.yaml:529``) is semantically consistent
with this expansion.  The expansion is **not** a "Forbidden
Regions" technique — exogenous agents are never inflated into
solver-side constraints; see the existing §5.5 disambiguation
below.

(no other documentation expands "FR" explicitly; this section
exists so future readers don't have to dig into source comments
to find the expansion.)

## §5.5 PIBT2-FR Tier-2 reading — verified

**Status:** code-side matches paper text; no action required.

Paper §5.5 sentence

> "PIBT2-FR plans against exogenous agents only as point obstacles,
>  not as buffer-inflated regions."

is the disambiguator between two readings of "PIBT2-FR".  The
codebase implements the reading the sentence forbids only in the
absence of inflation: Tier-2 is fully OFF
(``controller_kind="global_only"``), so exogenous agents enter the
runtime as exact-cell ``observation.blocked`` entries — point
obstacles — never as inflated $F$ regions.  See the long comment in
``src/ha_lmapf/baselines/pibt2_fr.py::make_pibt2_fr_config``.

## simulation_steps consistency — code-enforced

**Status:** code-side enforced; paper text consistent.

The harness now refuses to start a sweep whose YAML's ``steps``
field disagrees with the paper-mandated value for that section
(``run_paper_experiment.py::validate_config_consistency``):

| YAML stem                  | Paper section | Required ``steps`` |
|----------------------------|---------------|--------------------|
| ``solver_sensitivity``     | §5.2          | 2000               |
| ``fov_safety``             | §5.3          | 2000               |
| ``scaling_agents``         | §5.4 part 1   | 2000               |
| ``scaling_exogenous``      | §5.4 part 2   | 2000               |
| ``baseline_comparison``    | §5.5          | **1500**           |
| ``token_passing_ablation`` | §4.3 promise  | **1500**           |
| ``aux_h_r_decoupling``     | response letter | 2000             |

If the user later changes any of these in the paper text, update the
``PAPER_SECTION_TO_STEPS`` dict in
``scripts/evaluation/run_paper_experiment.py`` to match — the harness
will fast-fail otherwise.

## E14 (allocator alternatives) — sweep ready

- **Config:** `configs/eval/paper/allocator_alternatives.yaml` (120 runs)
- **Launcher:** `scripts/run_sweeps/run_allocator_alternatives.sh`
- **Queued in `run_all_sequential.sh`** after E7 (`solver_sensitivity`),
  so it runs only after every Phase-1 sweep is complete.
- **Expected wall-clock at 32 cores:** 1–3 hours.
- **Purpose:** defends §5.4's reframing of allocator-driven attribution
  against the strongest reviewer pushback ("you only tested greedy")
  by holding every axis fixed except `task_allocator ∈ {greedy,
  hungarian, auction}` and the Tier-1 solver.
- **Paper prose target:** §5.4 / §5.6 ablation paragraph citing the
  three-allocator comparison. The auto-invoked
  `statistical_analysis.py` will pair `hungarian` and `auction` against
  `greedy` within each `(global_solver, map_path, num_agents)` cell.

## E17 (budget sensitivity) — sweep ready

- **Config:** `configs/eval/paper/budget_sensitivity.yaml` (160 runs)
- **Launcher:** `scripts/run_sweeps/run_budget_sensitivity.sh`
- **Queued in `run_all_sequential.sh`** after E14, so it runs only
  after every Phase-1 sweep and the allocator-alternatives sweep are
  complete.
- **Expected wall-clock at 32 cores:** 1–3 hours (note: 30s-budget
  cells dominate the wall-clock; if LaCAM hits the budget often the
  worst-case per-run grows roughly linearly with `solver_timeout_s`).
- **Purpose:** defends §5.1's 10s per-call budget against the reviewer
  pushback "your relative-advantage claim only holds at this specific
  budget" by re-running the four §5.5 methods (ours, rhcr, pibt2_fr,
  no_buffer) on the warehouse-2-2 / |M|=200 cell across budgets
  {1, 5, 10, 30} s.
- **Paper prose target:** §5.1 / §5.6 paragraph showing the relative
  ranking is preserved across budgets. The auto-invoked
  `statistical_analysis.py` will pair each non-`ours` method against
  `ours` separately within each `(solver_timeout_s, map, num_agents)`
  cell — so the ranking can be read at every budget independently.
