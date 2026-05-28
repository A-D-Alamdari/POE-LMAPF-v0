# Repository status on pause

A short index of what is trustworthy and what is not, for whoever
resumes.  Drafted at the close of the P5/P10/P11/P12/P14 series.

## Sound and verified

* **§5.4 N_x audit (outcome (i)).**  The per-cell numbers in
  `paper/tables/table1_solver_substitutability.{md,tex}`
  reproduce from the §5.4 sweep CSV
  (`logs/paper/solver_sensitivity/results.csv`) via the identity
  transform on `violations_exogenous_attributable` -- max
  per-cell relative error 0.007%.  See `reports/table1_audit.md`.
* **Definition-1 classifier + construction-level proof
  (Prompt 1).**  The FOV-gated, pre-step-4, two-clause
  classifier in `simulator.py::_detect_collisions_and_near_misses`
  block (A) emits `violations_def1_{agent,exogenous}_attributable`
  alongside the existing WAIT-counterfactual diagnostic.
  Theorem 1 (paper §F) is restated as a construction-level
  invariant with a five-line proof; the empirical witness is
  the `violations_def1_agent_attributable` counter.  Tests:
  `tests/test_def1_violation_classifier.py`.
* **Event-debounce emission (Prompt 2).**  The
  ``safety_violation_events`` + ``violations_*_events`` counters
  computed inside `MetricsTracker` are emitted in the CSV header
  and row writer.  Finalize-time asserts pin the alias /
  per-tick / events contract.  Tests:
  `tests/test_event_debounce_emission.py`.
* **Deadlock + GNP columns + §5.4 system health (Prompt 5 / P9).**
  Four new `HEALTH_COLS` are appended to every paper table; the
  §5.4 system-health section (`paper/sections/05_4_system_health.{md,tex}`)
  carries the canonical "throughput task-arrival-limited" claim
  with cross-density + cross-method tables backed by
  `logs/paper/baseline_comparison_v2/`.  Tests:
  `tests/test_system_health_columns.py`.
* **Load regime / arrival saturation (Prompt 6 / P10).**
  `arrival_rate_per_step` and `throughput_utilization` are
  emitted in every CSV; the §5.1 load-regime section
  (`paper/sections/05_1_load_regime.{md,tex}`) carries the
  arithmetic that throughput in the headline configs equals
  $|M|/(H+W)$.  Diagnostic:
  `scripts/diagnostics/check_arrival_saturation.py`.  Tests:
  `tests/test_load_regime_columns.py`.
* **Wait-kind four-bucket invariant (Prompt 7 / P11).**
  Physics-revert and execution-delay WAITs are now counted;
  `total_wait_steps == safe + yield + physics_revert + delay`
  is asserted at finalize.  Tests:
  `tests/test_wait_kind_invariant_extended.py`.
* **Six paper-metric invariants (Prompt D-ish / P12).**
  `tests/test_paper_metric_invariants.py` carries the regression
  net: Definition-1 FOV gate, wait-fraction four-bucket,
  table-column CSV provenance, throughput-saturation cap,
  orphan-field detection, Definition-1 documentation match.

## Open / unresolved

* **§5.1 N_x source.**  The audit verdict in
  `reports/nx_horizon_audit.md` was originally declared
  outcome (ii) ("came from a deleted source") on the strength of
  a candidate search whose column dimension had collapsed.  P14
  fixed the collapse and added a runtime assertion against
  recurrence; the post-fix search still finds no match within
  5% per cell, but a finite candidate panel cannot enumerate
  every possible formula.  The §5.1 source is therefore
  **UNRESOLVED**, not closed.  See the STATUS block at the top
  of `reports/nx_horizon_audit.md` and the disposition note in
  `paper/sections/05_1_horizon_subtable_STALE.md`.
* **Horizon Table 1 not yet regenerated.**  The §5.1
  horizon-tuning Table 1 currently in the paper carries N_x
  values from an unverified source; until the source is
  identified or the sweep is re-run from
  `configs/tuning/horizon_replan_full.yaml` against the
  post-Prompt-1 schema, the sub-table is held STALE.
* **Extended WAIT counting (Prompt C from the original
  multi-prompt plan) was never run as its own dedicated audit.**
  The P11 work covered the four-bucket invariant, but a wider
  decomposition (e.g. WAIT-by-cause histograms across the
  paper sweeps) has not been done.
* **Full invariant test suite is partial.**  P12 added six
  invariants and three follow-up guards (10 tests total in the
  paper-metric file).  Several additional guards from the
  original plan -- e.g. "every paper LaTeX cell value
  reproduces from results.csv", "deadlock_count > 0 implies
  a buffer-stuck warning in the log" -- were never written.

## Known data issue

The LaCAM\* row in
`paper/tables/table1_solver_substitutability.{md,tex}` is a
**copy of the LaCAM (`lacam_official`) row**, not a separate
measurement.  The §5.2 sweep CSV does not include `lacam3` so
the table's LaCAM\* line carries the lacam_official numbers
verbatim.  Documented in `reports/table1_audit.md`; to fix,
add `lacam3` to the §5.2 sweep config and regenerate.

## Two things to reconsider before resuming experiments

1. **Throughput is task-arrival-limited in the headline configs.**
   With $|M|/(H+W)$ tasks released per step and arrival
   approximately equal to service in the lifelong regime, every
   §5.2 cell saturates near the arrival cap (utilization $\ge$
   0.957 across the 8 cells at H=20).  Cross-config throughput
   comparisons under these conditions are uninformative: the
   number being compared is the arrival rate, not the planner.
   Algorithm-discriminating comparisons should run at points
   where the planner is the bottleneck (§5.3 FoV / r_safe
   sweeps, §5.5 baseline comparison + deadlock context, §5.6
   allocator study under a fixed arrival stream).  See
   `paper/sections/05_1_load_regime.{md,tex}`.

2. **$N_a = 0$ is a construction-level identity, not an
   empirical test.**  Under hard_safety + r_safe < r_fov +
   Manhattan-1 moves, the forbidden set the local controller
   respects contains every reachable buffer cell; no Algorithm-2
   action lands inside an observed pre-move buffer; therefore
   `violations_def1_agent_attributable == 0` on every run.
   Citing the empirical zero as evidence for Theorem 1 conflates
   the proof with its observation.  The construction-level proof
   is in `docs/proposed_approach.md` §F.  Empirical observation
   of the zero is still useful as a regression guard (a future
   edit that breaks the forbidden-set logic would surface a
   nonzero count), but it is not a discovery.

## Pointers

* All commits in this branch carry the prompt label in their
  message; `git log --oneline` is the chronology.
* The regression smoke (`scripts/regression_smoke.py`) is the
  single fastest gate; run it before any large sweep.
* The full test suite (`pytest tests/`) is ~780 cases, ~2 min;
  one pre-existing host-noise flake on LaCAM3 binary timing
  that passes on re-run.
