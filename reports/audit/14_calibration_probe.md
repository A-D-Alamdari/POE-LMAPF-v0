# Audit step 14 — Phase 2 calibration probe (kill-switch for Phase 3)

Focused calibration probe under Phase 2 prompt 4.  Single question:
does the locked 30s solver budget (Phase 2 prompt 2, Decision 1a,
audit 09 §5) produce clean rows at the worst-case operating point of
`horizon_replan_full`?  The probe is a kill-switch for Phase 3 (B7,
~600h on 32 workers).

## Headline verdict

**Phase 3 NOT GREENLIT.**

The probe answers the brief's narrow budget question YES (every row's
solver-fail-fraction is below the validator's 0.05 gate at the 30s
budget; max observed 1.14%), but the strong-predicate gate the
validator enforces (Phase 2 prompt 1) rejects every cell on a
different clause — **clause 4 (deadlock-fraction)** at 22–43% per row,
2–4× over the 10% threshold.  Phase 3 cannot launch into a §5.4 grid
where this operating point will tank every sweep that touches the
warehouse map at high agent density.

**Important:** the remediation is NOT a budget revision (the brief's
anticipated remediation in §5).  At 30s the solver is doing zero
failure work on 10/12 cells; raising the budget cannot move
deadlock-fraction.  The remediation is a separate diagnostic prompt
to investigate the deadlock failure mode at this operating point.

## Probe scope

| Axis | Value |
|---|---|
| Sweep | `horizon_replan_full` (the worst sweep in audit 11 §1) |
| Map | `warehouse-10-20-10-2-2` (largest map in the sweep) |
| Cells | 4: (na, H) ∈ {(100,80), (100,60), (75,80), (75,60)} |
| `replan_every` | `H / 2` (coupling preserved) |
| Seeds | 3 (0, 1, 2) |
| Total runs | 12 |
| Regime | `humans_block_on_agent_cells: false` (more pressure than `true`) |
| Variant | `algorithm_variant: baseline` (γ off; out of scope for the budget question) |
| Solver | `lacam_official` |
| Solver budget | 30.0s |
| `max_invalid_fraction` | 0.05 (calibrating, not validating) |
| `fov_radius / safety_radius` | 4 / 1 |
| `human_model` on warehouse | `aisle` (`map_to_human_model` inherited from `horizon_replan_full`) |
| `num_humans` | 50 |
| `steps` | 2000 |
| Worker count | 4 |
| Wall time | 872.5s aggregate (≈ 14.5 min, not the brief's 2 min estimate) |

The brief's worst-case map (`warehouse_10_20_10_2_2`) IS in
`horizon_replan_full`'s set, so no substitution was required.

## 12-run results table

| cell | seed | na  | H  | replans | sf%   | dl  | dl/na | util | thru  | wall_s | strong-predicate verdict |
|------|-----:|----:|---:|--------:|------:|----:|------:|-----:|------:|-------:|--------------------------|
| A    |  0   | 100 | 80 |      88 | 1.14  |  35 | 0.350 | 0.98 | 0.395 | 354.2  | **invalid: deadlock-fraction** |
| A    |  1   | 100 | 80 |      81 | 0.00  |  33 | 0.330 | 0.98 | 0.386 | 324.8  | **invalid: deadlock-fraction** |
| A    |  2   | 100 | 80 |      90 | 0.00  |  40 | 0.400 | 0.97 | 0.391 | 333.7  | **invalid: deadlock-fraction** |
| B    |  0   | 100 | 60 |      92 | 1.09  |  37 | 0.370 | 0.98 | 0.396 | 369.9  | **invalid: deadlock-fraction** |
| B    |  1   | 100 | 60 |      97 | 0.00  |  43 | 0.430 | 0.97 | 0.382 | 311.1  | **invalid: deadlock-fraction** |
| B    |  2   | 100 | 60 |      91 | 0.00  |  42 | 0.420 | 0.97 | 0.392 | 334.2  | **invalid: deadlock-fraction** |
| C    |  0   |  75 | 80 |      91 | 0.00  |  21 | 0.280 | 0.98 | 0.287 | 217.2  | **invalid: deadlock-fraction** |
| C    |  1   |  75 | 80 |      89 | 0.00  |  20 | 0.267 | 0.98 | 0.294 | 216.7  | **invalid: deadlock-fraction** |
| C    |  2   |  75 | 80 |      90 | 0.00  |  24 | 0.320 | 0.98 | 0.304 | 209.0  | **invalid: deadlock-fraction** |
| D    |  0   |  75 | 60 |      97 | 0.00  |  24 | 0.320 | 0.98 | 0.288 | 210.1  | **invalid: deadlock-fraction** |
| D    |  1   |  75 | 60 |      92 | 0.00  |  17 | 0.227 | 0.98 | 0.293 | 214.5  | **invalid: deadlock-fraction** |
| D    |  2   |  75 | 60 |      96 | 0.00  |  22 | 0.293 | 0.98 | 0.304 | 204.3  | **invalid: deadlock-fraction** |

`sf%` = `(solver_timeouts + solver_errors) / max(1, global_replans) * 100`.
`dl/na` = `deadlock_count / num_agents`.  Every row is `status = ok`
and every row has `global_replans > 0`, so clauses 1 and 2 of the
strong predicate are clean.

## Aggregate statistics

### Solver-fail-fraction (clause 3 — the brief's primary question)

| statistic | value | gate | verdict |
|---|---:|---:|---|
| median | 0.0000 | 0.05 | PASS |
| max    | 0.0114 | 0.05 | PASS |
| p95    | 0.0114 | 0.05 | PASS |

**Solver budget verdict: the 30s budget is sufficient at the
worst-case operating point.**  Cell A (100 agents, H=80, the brief's
"absolute worst") has solver-fail ∈ {0.0%, 0.0%, 1.14%} — the worst
seed is 4.4× under the 0.05 gate.  Raising the budget to 60s or 90s
would change ZERO of clause 3's verdicts.

### Deadlock-fraction (clause 4)

| statistic | value | gate | verdict |
|---|---:|---:|---|
| median | 0.3250 | 0.10 | **FAIL** |
| max    | 0.4300 | 0.10 | **FAIL** |
| min    | 0.2267 | 0.10 | **FAIL** |
| p95    | 0.4286 | 0.10 | **FAIL** |

**Every cell × seed combination fails clause 4** by a factor of
2.27× (minimum) to 4.30× (maximum).  Cell A (the brief's worst case)
is at 0.330–0.400 — comfortably the high end of the distribution but
not dramatically worse than cells C/D at 0.227–0.320.  The deadlock
failure mode is intrinsic to this operating point, not concentrated at
cell A.

### Throughput utilization (clause 5 context)

| statistic | value | gate | verdict |
|---|---:|---:|---|
| median | 0.98 | 0.95 (sat) | saturated |
| min    | 0.97 | 0.95 (sat) | saturated |
| max    | 0.98 | 0.95 (sat) | saturated |

All 12 rows are above the saturation threshold AND have deadlock-fraction
> 0.10 — clause 5 (saturation-hiding-deadlock) would fire on every row
if clause 4 didn't catch them first.  This is the exact "throughput
masks deadlock under arrival saturation" failure mode audit 09 §1
characterised, now empirically reproduced.

## Validator output (manifest mode)

Standalone validator run via the Phase 2 prompt 1 manifest CLI:

```
$ python scripts/evaluation/validate_paper_claims.py \
    --manifest configs/probe/calibration_probe_manifest.yaml \
    --log-level WARNING
[sweep:calibration_probe] n_rows=12 invalid=12 (100.0%) threshold=5.0% FAIL
  reasons: deadlock-fraction=12
ERROR paper_claims | 1 of 1 sweep(s) failed the validity gate; exit 3.
exit=3
```

`logs/probe/calibration/validity_report.json` and
`configs/probe/validity_report.json` carry the same payload:

```json
{
  "n_failed_sweeps": 1,
  "overall_passed": false,
  "sweeps": {
    "calibration_probe": {
      "n_rows": 12, "n_invalid": 12,
      "invalid_fraction": 1.0, "threshold": 0.05, "passed": false,
      "reasons": {"deadlock-fraction": 12}
    }
  }
}
```

### Runner-vs-validator divergence (separate finding — resolved)

At probe time, the runner's internal gate
(`run_paper_experiment.py`) reported
`PASSED: 0/12 invalid runs = 0.0000 <= max_invalid_fraction=0.0500`
on the same CSV.  The runner checked only `solver_fail_fraction` +
`status`; the validator's strong predicate (Phase 2 prompt 1) checks
all five clauses (+ a missing-columns precondition).  Both readings
were internally consistent but they disagreed by 12 rows.

This divergence is the same gap audit 05 §3.1 / audit 09 §5 flagged
and audit 07 + Phase 2 prompt 1 partly closed.

**Resolved in Phase 2 prompt 5.**  The runner's `_row_is_valid` now
delegates to `validate_paper_claims.is_row_invalid` — the same
canonical predicate the standalone validator uses.  The runner's
per-record stamping path also re-evaluates the strong predicate and
writes the canonical reason name to `validity_reason` on every row;
the post-sweep log surfaces a reason breakdown (`reasons:
solver-fail-fraction=N1 deadlock-fraction=N2 ...`) matching the
standalone validator's CLI output.  A regression test
(`test_runner_predicate_matches_validator` in
tests/test_max_invalid_fraction.py) constructs one row per canonical
reason name and asserts the two functions agree; a future fork of the
runner's predicate fails this test loudly.

Verification on the existing probe CSV (CSV unchanged; runner and
validator code both now consult `is_row_invalid`):

```
$ python scripts/evaluation/validate_paper_claims.py \
    --manifest configs/probe/calibration_probe_manifest.yaml
[sweep:calibration_probe] n_rows=12 invalid=12 (100.0%) threshold=5.0% FAIL
  reasons: deadlock-fraction=12

$ diff configs/probe/validity_report.json \
       logs/probe/calibration/validity_report.json
# (empty -- BYTE-IDENTICAL to the pre-alignment JSON, because the
# validator itself wasn't changed; only the runner was)

$ python -c '...                       # runner-side reclassification
runner    : 12/12 invalid, reasons={"deadlock-fraction": 12}
validator : 12/12 invalid, reasons={"deadlock-fraction": 12}
agree     : True
'
```

The runner and validator agree on every row.  The divergence cannot
recur because both now call into the same function.

## Acceptance decision (brief §5 decision tree)

The brief's decision tree enumerates four arms.  This probe's outcome
matches NONE of them cleanly:

1. **"All 12 cells pass the strong predicate → PASS, Phase 3
   greenlit."**  Does not apply — all 12 cells FAIL the predicate.

2. **"Any cell-A run fails on solver-fail-fraction → FAIL, revise the
   budget upward."**  Does not apply — cell-A solver-fail is
   {0.0%, 0.0%, 1.14%}.  The budget is NOT the bottleneck; raising it
   to 60s / 90s would not change a single verdict.

3. **"Cell-A passes, easier cells fail → STRANGE, investigate."**
   Does not apply — the failure is uniform across all 12 cells; not
   non-monotonic in (na, H).

4. **"Predicate passes but deadlock_fraction > 0.05 → CONCERNING,
   caveat in RESUME_DECISION."**  Closest analogue, but the predicate
   does NOT pass — every cell fails clause 4, not just edges toward
   it.

The honest read of the data and the brief's deeper intent: the probe
is a kill-switch, and the kill-switch fires.  **Phase 3 (B7) is NOT
GREENLIT.**

But the remediation the brief anticipated (budget revision) does not
fit the observation: at 30s, the solver budget is verified sufficient.
The bottleneck is a deadlock failure mode at the warehouse high-density
operating point, not the per-call solver budget.  Phase 3 cannot
launch into this corner of the §5.4 grid with the current allocator /
coordination configuration; a budget-revision pass would be wasted
compute.

### What this probe DOES establish

- The 30s solver budget answers its own kill-switch test in the
  affirmative.  No budget revision warranted.
- The validator's strong predicate (Phase 2 prompt 1) correctly fires
  on the failure mode audit 09 §1 characterised, on real data, at the
  operating point it was designed to catch.  The wiring works
  end-to-end.

### What this probe LEAVES open (out of scope for Phase 2 prompt 4)

- Why does this operating point produce 22–43% deadlocked fleet?
  Candidates: the allocator (`congestion_avoidance`), the §5.4
  coordination policy at high density on a corridor-heavy map, the
  `aisle` human model adding extra obstacles, the `priority`
  (Wait-Based) resolver's behavior under saturation.  Diagnosis is
  the natural next prompt.
- Does the same failure mode appear on `random-64-64-10` at high
  density?  The probe ran only on warehouse; checking random
  (the other sweep map) would tell us whether this is map-specific
  or fleet-density-intrinsic.  Out of scope here.
- Token-Based resolver (Phase 2 prompt 0 / resume-prompt-6) vs
  Wait-Based at high density — the probe used Wait-Based (`priority`)
  matching `horizon_replan_full`'s default.  The new Token-Based
  scheme is untested at this operating point.

## Wall-time observation (brief §2 anomaly flag)

The brief said "if each run is hitting the full 30s budget on every
replan, that itself is a probe finding."  Per-run wall times were
205–370s, well above the brief's ~30s estimate, but they are NOT
budget-pressured:

- Median replans per run: ≈90.  Average solver call: 333s / 90 ≈ 3.7s.
- 30s budget → solver call cap.  Average is 12% of the cap.
- Solver-fail-fraction (the budget-saturation signal) is 0.00 on
  10/12 rows.

The wall time is dominated by the per-tick simulation cost of 100
agents × 2000 ticks × the controller's local-tier work (FOV
construction, conflict detection, resolver), not by the global solver.
This is normal scale, not a calibration finding.

## Artifacts

- `configs/probe/calibration_probe.yaml` — runner config (4 cells × 3 seeds)
- `configs/probe/calibration_probe_manifest.yaml` — validator manifest
- `logs/probe/calibration/results.csv` — 12 rows
- `logs/probe/calibration/validity_report.json` — manifest-mode validator output
- `logs/probe/calibration/run_validity_summary.csv` — runner's internal-gate output
- This file: `reports/audit/14_calibration_probe.md`

## Decision recorded

**Phase 3 (B7 full re-run) is NOT GREENLIT.**

Justification: every cell of the worst-case probe (12/12 runs) fails
the strong-predicate gate the validator enforces, on clause 4
(deadlock-fraction).  Phase 3 cannot launch into a §5 grid where this
operating point will reject every sweep that touches it.

The 30s solver budget passes its own kill-switch test (max sf =
1.14%); a budget revision is NOT the right remediation.  The natural
next prompt is a deadlock diagnosis at this operating point — out of
scope here.

`RESUME_DECISION.md` §D is updated to reflect this decision.
