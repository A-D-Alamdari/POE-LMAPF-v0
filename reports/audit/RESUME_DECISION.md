# Resume decision — POE-LMAPF audit (steps 00-11)

**Read this first.**  This document collapses 13 audit reports
(`reports/audit/00_inventory.md` through
`reports/audit/11_solver_fail_hardened.md`, plus
`reports/audit/physics_revert_reachability.md` and
`reports/audit/00_dependency_map.md`) into a single resume-decision
artifact.

If you are picking the project back up after a pause: do not
regenerate sweeps, do not change classifier code, do not "fix" the
solver until you have read sections **A** and **D**.  The cost of a
wrong-order resume is multiple wall-clock days of compute on the
wrong configuration.

---

## A. One-paragraph verdict

The committed experiments are **invalid under the project's own
validity contract**.  Audit 11 (the hardened verdict) shows that
**14 of 14** tuning sweeps fail their declared
`max_invalid_fraction = 0.0` threshold on the solver-fail clause
**alone** — taken verbatim from the YAML comment blocks, with no
audit-introduced gates.  Invalid fractions range from 0.591 to
0.999.  The root cause is the calibrated 10 s `lacam_official`
budget being exceeded on roughly two-thirds of global solver calls
at the operating points the sweeps actually use (audit 09 §5
showed 64.9% of horizon-sweep rows have
`solver_fail_fraction > 0.05`; in
`horizon_replan_full`, median `solver_errors = 9` on median
`global_replans = 146`).  Compounding the invalidity, the metric
repair from Prompts 1, 2, 6, C (Definition-1 classifier, event
debounce, arrival/utilization, four-bucket wait) exists only in
code and synthetic tests: audit 08 §1 shows **0 of 27** committed
CSVs carry the corrected columns.  Therefore every published §5.x
table rests on pre-repair metrics computed over a population that
already fails the config's own validity gate.  Salvage requires a
**single coupled decision**: (i) raise the solver budget or shrink
cell sizes so the validity gate clears, AND (ii) regenerate every
sweep so paper tables read the corrected columns.  Estimated cost
(audit 10 §4): ~55 wall-clock hours on 32 workers for the §5 paper
CSVs only; ~98 wall-clock hours for the full re-run including
tuning predecessors.  Re-running under the current 10 s budget
would reproduce the degeneracy under the new schema and waste the
compute.

---

## B. What is verified correct — DO NOT REDO

Each item is a settled finding with a pointer to where it was
proved.  None of these needs re-litigation in the resume work.

| Verified | Where | Evidence |
|---|---|---|
| Repository inventory + dependency graph | `00_inventory.md`, `00_dependency_map.md` | 212 Python files / 92 YAMLs / 27 CSVs catalogued; no import cycles; 5 orphan modules identified |
| Every `MetricsTracker.finalize()` assert has teeth | `01_core_types.md` §4 | 5 invariants × (valid, invalid) teeth-test: all PASS; raises on bad input, quiet on good |
| `csv_header()` ↔ `to_csv_row()` length alignment | `01_core_types.md` §2; reconfirmed end-to-end in `05_io_runners.md` §3.3 | 67 == 67 in-process; 67 == 67 byte-stream + parsed-back |
| Per-tick step ordering in `step_once()` | `02_simulator.md` §1 | Full numbered table with line ranges; cosmetic only: two block comments both labelled "7c" |
| `humans_pre_move` / `humans_at_decision` name vs content | `02_simulator.md` §2 | Names match content; contract documented inline |
| Definition-1 classifier (FoV gate + pre-move + two clauses) | `02_simulator.md` §3 | 3 synthetic single-tick scenarios PASS; classifier docstring labelled diagnostic where appropriate |
| Definition-1 construction claim (`def1_agent == 0` on real run) | `10_metric_repair_endtoend.md` §3 | All 3 seeds on `empty-16-16` produced `def1_agent_attributable = 0`; must be re-validated at real operating points (see C, Tier 1) |
| Identity claim: `def1_exo == legacy_exo` when `def1_agent == 0` | `10_metric_repair_endtoend.md` §3 | All 3 seeds: identity holds on real data |
| Physics-revert WAITs are reachable and counted | `02_simulator.md` §4; `physics_revert_reachability.md` | Reproduced 11/12 seeds in audit-07 probe; tagged + counted via post-physics bucketing block |
| Task-completion idempotence (`_completed_tasks++` exactly once) | `02_simulator.md` §5 | `on_task_completed` guarded by `if record.completed_step is None`; double-call test passes |
| Deadlock detector: per-run distinct-agent set | `02_simulator.md` §6 | `_deadlocked_agents: Set[int]`; reported as `len()` |
| `WaitBasedResolver` priority tuple matches paper | `03_local_tier.md` §2 | Synthetic verified `(urgency, w, -id)` with β·𝟙[w>w*] boost |
| Resolvers do not mutate `forbidden` set | `03_local_tier.md` §3 | Synthetic check: tagged set unchanged after `resolve()` (priority + token) |
| Rolling-horizon prefix commitment | `04_global_humans.md` §1.2 | Replan reads realized `sim_state.agents`; `_reanchor_last_good` clips at `offset ≥ 0` |
| `η_w` emergency-replan trigger wired correctly | `04_global_humans.md` §1.3 | Reads `last_action_was_safe_wait` flag; defaults `η_w=0.20`, `replan_min_gap=3` |
| Congestion-Avoidance narrowness `ν(c) = 4/max(1, deg(c))` | `04_global_humans.md` §2.2 | Synthetic: interior=1.0, corner=2.0, edge=4/3 |
| Cost matrix `C[i,j] = D[i,j] + λω` | `04_global_humans.md` §2.2 | λ=0.5, R_max=5 defaults; 2-agent cross-paths converge in 2 rounds |
| Humans-blocked-on-agent-cells (vertex coordination) | `04_global_humans.md` §3.3 | 0/500 trials of forced-forward RandomWalk entered agent cell |
| Safety inflation `B_{r_safe}(X)` Manhattan ball | `04_global_humans.md` §4 | `r=0`, `r=1`, walls-excluded synthetic checks |
| `r_safe < r_fov` precondition (Theorem 1) | `06_preconditions.md` §1 | Now ENFORCED at `SimConfig.__post_init__`; 5 regression tests; `test_committed_configs_have_zero_violations` walks every YAML |
| `R = floor(H/2)` is a default, not a code-invariant | `06_preconditions.md` §2 | Grep proves no code dependency; `test_horizon_replan_every_decoupled_run_succeeds` pins decoupling |
| Runner status semantics: no crash-writes-ok path | `05_io_runners.md` §3.2 | `status='ok'` assigned only after `sim.run()` returns inside `try` block |
| Arrival-rate formula `release_rate = H + W` per agent | `05_io_runners.md` §2.1 | Live in `simulator.py:582-583` |
| `max_invalid_fraction` canonical placement + enforcement | `07_max_invalid_fraction.md` §1, §2 | Top-level placement enforced (wrong placement raises); sweep-level gate wired in `run_paper_experiment.main` |
| In-row data invariants on committed CSVs | `08_csv_consistency.md` §2 | 14,839 / 14,839 rows pass every checkable invariant (two-bucket wait, attribution split, wait_fraction formula, throughput formula) |
| §5.4 N_x by identity convention | `08_csv_consistency.md` §3 | `baseline_comparison_v2` median 1,308.5 = paper N_x by identity (no transform) |
| `solver_fail_fraction` arithmetic | `11_solver_fail_hardened.md` §4 | 3 rows hand-recomputed; all match audit's computed value to 1e-12 |

---

## C. What is broken or open — severity-ranked

### TIER 1 — invalidates experimental claims

| # | Issue | Source | Effect on paper |
|---|---|---|---|
| 1.1 | **Solver budget breach at sweep operating points.**  `lacam_official` `solver_timeout_s = 10.0` was calibrated against the P3 cohort (p99 ≈ 17 ms) but the sweep cells exceed it on 64.9% of replans.  In `horizon_replan_full`, 46% of rows have `solver_fail_fraction` in (10%, 50%). | `09_strong_validity_predicate.md` §5; `11_solver_fail_hardened.md` §1 | Every tuning sweep produces rows where the Tier-1 solver mostly fails; the displayed numbers aggregate over a degenerate population |
| 1.2 | **14 / 14 committed tuning sweeps WOULD FAIL their own `max_invalid_fraction = 0.0` gate.**  Invalid fractions range from 0.591 to 0.999 on the solver clause alone.  No deadlock threshold is needed for the verdict. | `11_solver_fail_hardened.md` §1, §5 | Every §5.x table is built on data that does not meet its declared validity contract |
| 1.3 | **The metric repair (Prompts 1, 2, 6, C) is unvalidated end-to-end.**  0 / 27 committed CSVs carry the corrected columns (`violations_def1_*`, `arrival_rate_per_step`, `throughput_utilization`, `physics_revert_wait_steps`, `delay_wait_steps`, `safety_violation_events`). | `08_csv_consistency.md` §1; `10_metric_repair_endtoend.md` §1 | Every published §5.x N_x / wait-by-kind / utilization-flag number is the OLD definition; the live code's corrected definitions have never been read into a paper-side aggregation |
| 1.4 | **Throughput is arrival-limited and therefore non-discriminating** at the headline operating points.  `λ_sys = n/(H+W)`.  At |M|≥100 on the warehouse + 64×64 random maps every cell is arrival-saturated. | `04_global_humans.md` §1.3, §2.2; `05_io_runners.md` §2.2; `09_strong_validity_predicate.md` §1 | Paper tables that compare throughput across methods / horizons / fleet sizes at these cells are comparing against the same cap — not against planner capacity.  Need explicit saturation markers (Prompt 6) or smaller cells |
| 1.5 | **Theorem 1's empirical claim (`def1_agent_attributable == 0`) confirmed on the smoke run only.**  3 seeds × 4 agents × `empty-16-16` × 300 steps.  Not yet re-validated at real operating points (100 agents × warehouse × 2000 steps). | `10_metric_repair_endtoend.md` §3; same audit's caveat block | The construction-level proof + smoke + synthetic single-tick checks all hold, but the claim has never been measured at the regimes the paper publishes |

### TIER 2 — weakens a comparison (does not invalidate, but should be disclosed)

| # | Issue | Source | Effect on paper |
|---|---|---|---|
| 2.1 | **`WaitBasedResolver` and `TokenBasedResolver` use the same `(-d, w, -id)` priority tuple.**  TokenBased's only differentiator is per-cell single-owner + K-rotation; the paper claims `(τ, -d, w)` with a per-(agent, cell) token count.  Code does not implement the count term at all. | `03_local_tier.md` §2.token | A §5.5 "WaitBased vs TokenBased" comparison may be measuring two implementations of the same priority function, with only the rotation policy differing |
| 2.2 | **`PIBTResolver` is depth-2 push, not full PIBT-PP recursion.**  No global priority tuple; per-blocker scoring `(d, is_wait, r, c)`. | `03_local_tier.md` §2 | If the paper names "PIBT" as a baseline, the published numbers reflect a depth-2 truncation, not the algorithm the name suggests |
| 2.3 | **Externals are vertex-coordinated.**  Humans block on agent-occupied cells via `agent_positions` passed to every model's `step()`.  $N_x$ measures buffer overlaps, not vertex collisions, because vertex collisions cannot occur. | `04_global_humans.md` §3.3 | Paper phrasing "externals are not coordinated with the planner" is true at the buffer / safety-radius level only.  Should be disclosed; affects interpretation of $N_x$ as a "human–agent collision" proxy |

### TIER 3 — unresolved / hygiene (no paper claim depends on these)

| # | Issue | Source | Recommended disposition |
|---|---|---|---|
| 3.1 | **§5.1 N_x sub-table source remains UNRESOLVED.**  Printed paper values 0.029-0.083 are four orders of magnitude smaller than `violations_exogenous_attributable` median 1,053.5 in the committed CSV.  No simple transform reproduces the paper values. | `08_csv_consistency.md` §3; `paper/sections/05_1_horizon_subtable_STALE.md` | After the resume sweeps land, recompute the sub-table from the new `violations_def1_exogenous_attributable` column |
| 3.2 | **Horizon Table 1 rebuild (Prompt B) shipped but never regenerated under corrected metrics.** | `paper/tables/horizon_tuning.tex`; mentioned in `08_csv_consistency.md` | Regenerate after the resume sweeps |
| 3.3 | **8 permanently deselected tests across the audit series.**  The 3 in `test_paper_claims.py` are a pre-existing 3-tuple unpacking error from commit `812fc90` (audit 05); the 6 in `test_full_migration_manifest.py::test_wrapper_round_trip_consistency` are an `lacam3` wall-time flake (passes in isolation). | `05_io_runners.md` summary; subsequent audits' `--deselect` lines | Fix the `validate_paper_claims.run_validation` return tuple unpacking; consider widening the lacam3 timing tolerance |
| 3.4 | **`PIBTResolver._safe_side_step` ignores `forbidden` when `allow_side_step=True`.**  Default is `False`, so not active in any committed config. | `03_local_tier.md` §3; `06_preconditions.md` §3 | Plumb `forbidden` through when allow_side_step is set, matching `priority_rules.py:115` |
| 3.5 | **Dead module `global_tier/task_allocator.py`** (orphan, carries stale `PersistentTaskAllocator`). | `00_dependency_map.md`; `04_global_humans.md` §2.1 | Delete or move to `_archive/` |
| 3.6 | **22 `SimConfig` fields untunable from any YAML.**  Most by design (`seed` injected from `seeds:`, ablation toggles pinned); a few (`eta_w`, `deadlock_streak_threshold`, `execution_delay_prob`) are arguably worth a knob. | `05_io_runners.md` §1 | Add YAML knobs case by case if a future sweep needs them |

---

## D. The resume sequence — ordered, with gate logic

Each step's gate refers to a measurable result from a prior step.
Skipping a step or reordering them wastes compute or invalidates
the next step's verdict.

### Step 1 — Decide the experimental setup (NO COMPUTE YET)

**Required deliverable**: a one-page note pinning
`solver_timeout_s`, the cell-size range (per `num_agents`,
`num_humans`, `horizon`), and the `max_invalid_fraction` threshold
that together produce a sweep where `solver_fail_fraction > 0.05`
fires on ≤ the chosen threshold of rows.  Three lever options:

1. Raise `solver_timeout_s` (e.g. 30 s, 60 s).  Cheap if the
   solver actually finishes within the larger budget; costly if it
   doesn't (the anytime backend will just use the full budget).
2. Shrink the maximum cell size (drop the |M|=100, |X|=100 cells
   from sweeps where the solver demonstrably struggles).
3. Relax `max_invalid_fraction` from 0.0 to a justified value
   (e.g. 0.10), with a written rationale in the YAML comment block.

**Gate**: do not move to step 2 until this decision is recorded.
Re-running under the current setup reproduces the audit-09 verdict
verbatim — the cost of step 2 is wasted otherwise.

Inputs: `09_strong_validity_predicate.md` §5,
`11_solver_fail_hardened.md` §1, the per-sweep `solver_fail_fraction`
distribution in audit 09 task-4 spot-check.

### Step 2 — Regenerate sweeps under the corrected config

Run every committed sweep under the step-1 setup.  Cost
(audit 10 §4):

| Scope | Runs | Core-h | 32-worker wall |
|---|---:|---:|---|
| §5.1 + §5.5 headline only | ~1,360 | 370 | ~12 h |
| All §5 paper CSVs | 7,530 | 1,758 | ~55 h |
| All sweeps (tuning + paper) | 12,690 | 3,127 | ~98 h |

**Gate**: every regenerated CSV must populate the corrected columns
(`violations_def1_*`, `arrival_rate_per_step`, `throughput_utilization`,
`physics_revert_wait_steps`, `delay_wait_steps`,
`safety_violation_events`).  Audit 08 §1 lists the missing columns
per CSV.

**Gate**: the new sweep-level invalid fraction (under whatever
predicate step 1 chose) must clear `max_invalid_fraction`.  If it
doesn't, return to step 1 — the setup is still wrong.

### Step 3 — Rebuild every §5 table from the def1 columns

Apply audit 08 §1's per-section table to drive which CSV feeds
which table.  Each §5.x section must use:

- `violations_def1_exogenous_attributable` for N_x (not the legacy
  `violations_exogenous_attributable`)
- `violations_def1_agent_attributable` for N_a (must be 0)
- `physics_revert_wait_steps + delay_wait_steps` added to the
  wait-fraction breakdown
- `arrival_rate_per_step` and `throughput_utilization` for the
  load-regime saturation marker

Audit 10 §2 enumerates which sections need which columns.

**Gate**: the regenerated horizon Table 1 (`paper/tables/
horizon_tuning.tex`) must drop the "STALE" sub-table marker
(`paper/sections/05_1_horizon_subtable_STALE.md`) only after
audit-08-§3 §5.1 N_x is recomputed from the new
`violations_def1_exogenous_attributable` column.

### Step 4 — Re-validate the safety claims AT REAL operating points

Audit 10 §3 confirmed `def1_agent_attributable == 0` and the
identity claim on `empty-16-16` × 4 agents × 300 steps — a clean
regime.  Re-validate at the paper's headline regime: 100 agents,
warehouse-10-20-10-2-2, 2000 steps, multiple seeds.  Use the
regenerated CSVs from step 2.

**Gate**: if `def1_agent_attributable` is nonzero on any
regenerated row, Theorem 1's empirical claim has been violated
under the corrected schema at real scale — investigate before
publishing.

### Step 5 — Only then: Tier-2 and Tier-3 hygiene

The Tier-2 disclosure items (resolver tuples, PIBT depth, externals
vertex-coordination) and Tier-3 hygiene items (broken tests, dead
allocator, side-step guard) can be addressed in parallel with
steps 2-4 OR deferred.  None blocks the resume sequence above.
None affects the regenerated numbers.

---

## E. The compute number and the coupling caveat

**Compute (audit 10 §4)**:

- Sequential: ~3,130 core-hours total (12,690 runs)
- 8 workers parallel: ~390 wall-clock hours (~16 days)
- 32 workers parallel: ~98 wall-clock hours (~4 days)

**Coupling caveat — load-bearing**: the budget fix and the re-run
are ONE decision, not two.  Re-running under the current 10 s
`solver_timeout_s` would produce CSVs where the new
`solver_fail_fraction` column reproduces the audit-09 / audit-11
verdict — every sweep would still fail its own
`max_invalid_fraction = 0.0` gate, just with the corrected schema
columns populated.  The compute would not move the project closer
to a publishable result; it would just refresh the timestamps.

Three valid resume paths:

1. **Raise the budget**, regenerate, hope the new solver-fail
   fraction clears the gate.  Risk: anytime backends use the full
   budget as quality knob (`lacam3` p99 ≈ 10 030 ms per
   `_sweep_config_common.py:32`); raising to 60 s gives a 60 s
   per-call cost.  At 12,690 runs × 100+ replans per run, the
   budget multiplier scales the full re-run cost linearly.
2. **Shrink the cells**, regenerate, accept that the paper's
   headline cell sizes are smaller than originally planned.
   Cheaper compute; weakens the scaling-comparison story unless
   the paper text is adjusted.
3. **Relax `max_invalid_fraction`**, regenerate, disclose the
   threshold in the paper text.  Cheapest; trades the
   experimental contract for a documented tolerance.

**Do not pick a path before reading the audit-09 / audit-11 data
distribution**: the right answer depends on how heavy the
solver-fail tail is, which only the per-row data shows.

---

## Audit-step cross-reference (every step 00-11 cited above)

| Step | Cited in |
|---|---|
| `00_inventory.md` | §B (inventory line); §C-3.5 (dead allocator via `00_dependency_map.md`) |
| `00_dependency_map.md` | §B; §C-3.5 |
| `01_core_types.md` | §B (csv-header alignment; finalize asserts) |
| `02_simulator.md` | §B (tick order, snapshots, Def-1 classifier, physics-revert, task completion, deadlock) |
| `03_local_tier.md` | §B (WaitBased tuple, resolver immutability); §C-2.1 (TokenBased tuple), §C-2.2 (PIBT depth), §C-3.4 (allow_side_step guard) |
| `04_global_humans.md` | §B (prefix commitment, η_w, narrowness, cost matrix, vertex coordination, safety inflation); §C-1.4 (arrival-limited throughput); §C-2.3 (externals vertex-coordination disclosure) |
| `05_io_runners.md` | §A (verdict re: throughput / runner status); §B (status semantics, arrival formula, csv alignment); §C-3.3 (deselected tests origin); §C-3.6 (untunable fields) |
| `06_preconditions.md` | §B (`r_safe < r_fov` enforcement, H/R decoupling); §C-3.4 (PIBT allow_side_step deferred) |
| `07_max_invalid_fraction.md` | §B (placement + enforcement wiring); cited indirectly by §A as the gate this audit closed |
| `08_csv_consistency.md` | §A (0/27 corrected-column CSVs); §B (in-row invariants on 14,839 rows; §5.4 N_x identity); §C-1.3 (metric repair unvalidated); §C-3.1 (§5.1 N_x source UNRESOLVED); §D-step3 (per-section column requirements) |
| `09_strong_validity_predicate.md` | §A (14/14 sweeps would fail); §C-1.1 (solver budget breach); §C-1.4 (load-regime); §D-step1 (gate inputs); §E (coupling caveat) |
| `10_metric_repair_endtoend.md` | §A (compute estimates); §B (identity claim, construction claim, smoke); §C-1.3 (repair unvalidated); §C-1.5 (Theorem 1 smoke-only); §D-step2 (cost), §D-step3 (per-section table), §D-step4 (real-operating-point validation); §E (compute number) |
| `11_solver_fail_hardened.md` | §A (hardened headline: 14/14 on solver clause alone); §B (arithmetic hand-verified); §C-1.2 (solver clause invalid fractions); §D-step1 (gate inputs) |
| `physics_revert_reachability.md` | §B (physics-revert reachable + counted) |

Every audit step is cited at least once.

---

## File pointer

The repo-root pointer at `RESUME.md` directs a fresh reader to
this document.  Both files travel with the branch
`claude/keen-ride-4kmaM`.
