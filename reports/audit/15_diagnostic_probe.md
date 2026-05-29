# Audit step 15 — diagnostic probe: fleet-stability across (regime, variant)

Phase 2 prompt 6 research-diagnostic probe.  The calibration probe
(audit 14) showed (False, baseline) fails clause 4 (deadlock-fraction)
at 100 % of cells at the §5 worst-case operating point.  This probe
characterizes the other three (regime, variant) combinations the
calibration probe did not test, so B7's launch parameters can be set
on evidence.

## Headline verdict

**B7 is NOT greenlit at the current §5 worst-case grid.**

The deadlock failure is **regime-independent and operating-point-
intrinsic**, not a (False, baseline) artifact.  All four combinations
fail clause 4 on **every one of the 12 cells** (48/48 runs invalid).
The controlling decision-tree arm is "(True, baseline) fails cell A →
the operating point is past system capacity regardless of regime; the
§5 grid scales down before B7."  A refinement this probe adds: the
**smaller cells in this grid (B/C/D, 75-100 agents) also fail for
every combo**, so a re-probe must target agent counts *below 75* on
this map -- scaling within the probe's existing grid will not rescue
it.

γ (algorithm_variant=evade) has a **real, large, but insufficient**
effect under False: it nearly halves median deadlock-fraction
(0.325 → 0.177) and pulls the best individual cells to 0.120 — close
to but still above the 0.10 gate.  Under True, γ is **byte-identical**
to baseline (the prompt-4 stage-3 guard holds at §5 worst-case scale,
verified on every metric), so it neither helps nor harms there.

## Probe scope

| Axis | Value |
|---|---|
| Cells | A=(100,80) B=(100,60) C=(75,80) D=(75,60) |
| `replan_every` | H/2 (coupling preserved) |
| Map | `warehouse-10-20-10-2-2` |
| Seeds | 0, 1, 2 |
| Solver budget | 30.0s |
| Combinations | (True,baseline) (True,evade) (False,evade) |
| Runs | 3 combos × 4 cells × 3 seeds = 36 (+12 from audit 14's (False,baseline)) |
| Gate | strong predicate (locked); `max_invalid_fraction=0.05` |
| Runner | sequential per combo, 4 workers each |
| Wall time | T-B ≈ 20 min, T-E ≈ 20 min, F-E ≈ 31 min (sequential) |

The runs were sequential (not parallel) per the brief, to keep
wall-clock + any load-dependent deadlock-detector behavior clean.

## 4×4×3 results matrix (48 runs)

`sf%` = `(solver_timeouts+solver_errors)/max(1,global_replans)*100`;
`dlf` = `deadlock_count/num_agents`; all rows `status=ok`,
`global_replans>0` (clauses 1+2 clean throughout); all rows
`utilization ∈ [0.96, 0.99]` (saturated, clause-5 context).

| combo | cell | seed | replans | sf%  | deadlock | na  | dlf   | util | verdict | reason |
|-------|:----:|:----:|--------:|-----:|---------:|----:|------:|-----:|---------|--------|
| F-B   | A | 0 | 88 | 1.14 | 35 | 100 | 0.350 | 0.98 | INVALID | deadlock-fraction |
| F-B   | A | 1 | 81 | 0.00 | 33 | 100 | 0.330 | 0.98 | INVALID | deadlock-fraction |
| F-B   | A | 2 | 90 | 0.00 | 40 | 100 | 0.400 | 0.97 | INVALID | deadlock-fraction |
| F-B   | B | 0 | 92 | 1.09 | 37 | 100 | 0.370 | 0.98 | INVALID | deadlock-fraction |
| F-B   | B | 1 | 97 | 0.00 | 43 | 100 | 0.430 | 0.97 | INVALID | deadlock-fraction |
| F-B   | B | 2 | 91 | 0.00 | 42 | 100 | 0.420 | 0.97 | INVALID | deadlock-fraction |
| F-B   | C | 0 | 91 | 0.00 | 21 |  75 | 0.280 | 0.98 | INVALID | deadlock-fraction |
| F-B   | C | 1 | 89 | 0.00 | 20 |  75 | 0.267 | 0.98 | INVALID | deadlock-fraction |
| F-B   | C | 2 | 90 | 0.00 | 24 |  75 | 0.320 | 0.98 | INVALID | deadlock-fraction |
| F-B   | D | 0 | 97 | 0.00 | 24 |  75 | 0.320 | 0.98 | INVALID | deadlock-fraction |
| F-B   | D | 1 | 92 | 0.00 | 17 |  75 | 0.227 | 0.98 | INVALID | deadlock-fraction |
| F-B   | D | 2 | 96 | 0.00 | 22 |  75 | 0.293 | 0.98 | INVALID | deadlock-fraction |
| T-B   | A | 0 | 89 | 0.00 | 31 | 100 | 0.310 | 0.98 | INVALID | deadlock-fraction |
| T-B   | A | 1 | 86 | 0.00 | 29 | 100 | 0.290 | 0.98 | INVALID | deadlock-fraction |
| T-B   | A | 2 | 89 | 0.00 | 37 | 100 | 0.370 | 0.97 | INVALID | deadlock-fraction |
| T-B   | B | 0 | 91 | 0.00 | 39 | 100 | 0.390 | 0.98 | INVALID | deadlock-fraction |
| T-B   | B | 1 | 94 | 0.00 | 43 | 100 | 0.430 | 0.98 | INVALID | deadlock-fraction |
| T-B   | B | 2 | 98 |11.22 | 56 | 100 | 0.560 | 0.96 | INVALID | solver-fail-fraction |
| T-B   | C | 0 | 88 | 0.00 | 19 |  75 | 0.253 | 0.99 | INVALID | deadlock-fraction |
| T-B   | C | 1 | 88 | 0.00 | 21 |  75 | 0.280 | 0.99 | INVALID | deadlock-fraction |
| T-B   | C | 2 | 91 | 1.10 | 23 |  75 | 0.307 | 0.97 | INVALID | deadlock-fraction |
| T-B   | D | 0 | 94 | 0.00 | 20 |  75 | 0.267 | 0.99 | INVALID | deadlock-fraction |
| T-B   | D | 1 | 95 | 0.00 | 32 |  75 | 0.427 | 0.98 | INVALID | deadlock-fraction |
| T-B   | D | 2 | 98 | 0.00 | 22 |  75 | 0.293 | 0.98 | INVALID | deadlock-fraction |
| T-E   | A | 0 | 89 | 0.00 | 31 | 100 | 0.310 | 0.98 | INVALID | deadlock-fraction |
| T-E   | A | 1 | 86 | 0.00 | 29 | 100 | 0.290 | 0.98 | INVALID | deadlock-fraction |
| T-E   | A | 2 | 89 | 0.00 | 37 | 100 | 0.370 | 0.97 | INVALID | deadlock-fraction |
| T-E   | B | 0 | 91 | 0.00 | 39 | 100 | 0.390 | 0.98 | INVALID | deadlock-fraction |
| T-E   | B | 1 | 94 | 0.00 | 43 | 100 | 0.430 | 0.98 | INVALID | deadlock-fraction |
| T-E   | B | 2 | 98 |11.22 | 56 | 100 | 0.560 | 0.96 | INVALID | solver-fail-fraction |
| T-E   | C | 0 | 88 | 0.00 | 19 |  75 | 0.253 | 0.99 | INVALID | deadlock-fraction |
| T-E   | C | 1 | 88 | 0.00 | 21 |  75 | 0.280 | 0.99 | INVALID | deadlock-fraction |
| T-E   | C | 2 | 91 | 1.10 | 23 |  75 | 0.307 | 0.97 | INVALID | deadlock-fraction |
| T-E   | D | 0 | 94 | 0.00 | 20 |  75 | 0.267 | 0.99 | INVALID | deadlock-fraction |
| T-E   | D | 1 | 95 | 0.00 | 32 |  75 | 0.427 | 0.98 | INVALID | deadlock-fraction |
| T-E   | D | 2 | 98 | 0.00 | 22 |  75 | 0.293 | 0.98 | INVALID | deadlock-fraction |
| F-E   | A | 0 |104 | 0.00 | 23 | 100 | 0.230 | 0.98 | INVALID | deadlock-fraction |
| F-E   | A | 1 | 98 | 0.00 | 18 | 100 | 0.180 | 0.99 | INVALID | deadlock-fraction |
| F-E   | A | 2 |103 | 0.00 | 17 | 100 | 0.170 | 0.98 | INVALID | deadlock-fraction |
| F-E   | B | 0 |110 | 0.00 | 22 | 100 | 0.220 | 0.99 | INVALID | deadlock-fraction |
| F-E   | B | 1 |106 | 0.00 | 18 | 100 | 0.180 | 0.98 | INVALID | deadlock-fraction |
| F-E   | B | 2 |111 | 0.00 | 23 | 100 | 0.230 | 0.98 | INVALID | deadlock-fraction |
| F-E   | C | 0 |102 | 4.90 | 35 |  75 | 0.467 | 0.99 | INVALID | deadlock-fraction |
| F-E   | C | 1 |106 | 0.00 | 11 |  75 | 0.147 | 0.99 | INVALID | deadlock-fraction |
| F-E   | C | 2 |108 | 0.00 |  9 |  75 | 0.120 | 0.99 | INVALID | deadlock-fraction |
| F-E   | D | 0 |118 | 2.54 | 11 |  75 | 0.147 | 0.98 | INVALID | deadlock-fraction |
| F-E   | D | 1 |112 | 0.00 | 10 |  75 | 0.133 | 0.99 | INVALID | deadlock-fraction |
| F-E   | D | 2 |108 | 0.00 | 13 |  75 | 0.173 | 0.98 | INVALID | deadlock-fraction |

(F-B = the audit-14 calibration probe rows, reproduced here for the
full 4×combo picture.)

## Per-combination summary statistics

| combo | n | median dlf | max dlf | min dlf | cells passing clause 4 |
|-------|--:|-----------:|--------:|--------:|:----------------------:|
| False, baseline (audit 14) | 12 | 0.325 | 0.430 | 0.227 | 0/12 |
| True, baseline             | 12 | 0.308 | 0.560 | 0.253 | 0/12 |
| True, evade                | 12 | 0.308 | 0.560 | 0.253 | 0/12 |
| False, evade               | 12 | 0.177 | 0.467 | 0.120 | 0/12 |

### Per-cell median deadlock-fraction (combo × cell)

| combo | A (100/80) | B (100/60) | C (75/80) | D (75/60) |
|-------|:----------:|:----------:|:---------:|:---------:|
| False, baseline | 0.350 | 0.420 | 0.280 | 0.293 |
| True, baseline  | 0.310 | 0.430 | 0.280 | 0.293 |
| True, evade     | 0.310 | 0.430 | 0.280 | 0.293 |
| False, evade    | **0.180** | **0.220** | **0.147** | **0.147** |

Every cell of every combo is above the 0.10 gate.  The lowest single
run anywhere is F-E / cell C / seed 2 at **0.120** — still 1.2× over.

## Validator output per combo

All three diagnostic combos: `exit=3`, 12/12 invalid.

```
diagnostic_probe_true_baseline : 12/12 invalid; reasons deadlock-fraction=11 solver-fail-fraction=1
diagnostic_probe_true_evade    : 12/12 invalid; reasons deadlock-fraction=11 solver-fail-fraction=1
diagnostic_probe_false_evade   : 12/12 invalid; reasons deadlock-fraction=12
```

Per-combo `validity_report.json` written to
`logs/probe/diagnostic/<combo>/validity_report.json`.

> Note on CSV layout: the prompt-5-aligned runner routes every row that
> fails the strong predicate to `results_INVALID.csv` (not
> `results.csv`).  Because all 12 rows of each diagnostic combo fail,
> the runner produced only `results_INVALID.csv`; the full 12-row set
> was consolidated to `results.csv` per combo for this audit's
> manifest + artifact (the rows are identical; only the filename the
> runner chose differs).  The audit-14 (False, baseline) CSV predates
> the prompt-5 alignment, so its rows are in `results.csv` directly
> (the old runner stamped them valid).

## Cross-combination comparison

### Q1 — Is the deadlock specific to the False regime?

**No.**  (True, baseline) median 0.308 / max 0.560 fails clause 4 on
all 12 cells, essentially the same distribution as (False, baseline)
median 0.325.  Deadlock at this operating point is **regime-
independent**.  Whatever the human-block toggle does, it is not the
driver of the fleet stall.

### Q2 — Does γ reduce deadlock under False?

**Yes, substantially — but not enough.**  (False, evade) median 0.177
vs (False, baseline) 0.325: a **46 % reduction** in median deadlock-
fraction, consistent across cells (A 0.350→0.180, B 0.420→0.220, C
0.280→0.147, D 0.293→0.147).  γ's predictive evasion genuinely keeps
more of the fleet moving.  But the best cell still sits at 0.147
median (0.120 best single run), above the 0.10 gate — γ helps, does
not fully defend, at this operating point.

### Q3 — Does γ harm or help under True?

**Neither — γ is a byte-identical no-op under True.**  (True,
baseline) and (True, evade) match on every metric of every one of the
12 cells (deadlock_count, global_replans, solver_errors/timeouts,
throughput, utilization, status — 0 differences).  This is the
*expected* branch of the decision tree (prompt-4 stage-3 guarded γ to
collapse to baseline under True by construction); the byte-identity
verification holds at the §5 worst-case scale, not just the
prompt-4 smoke fixture.  The investigation branch ("γ harms under
True") does **not** fire.

### Q4 — Is the operating point past capacity for every combo?

**Yes.**  48/48 runs fail clause 4.  No cell of any combination
clears the 0.10 gate.  The cleanest combination (False, evade) gets
closest (0.120 best run) but still fails everywhere.

## Acceptance decision (brief §6 decision tree)

Two arms of the tree are satisfied simultaneously; the more
restrictive one controls.

* **"(False, evade) > 0.10 on cell A but improves over (False,
  baseline)"** — FIRES.  γ helps (0.350→0.180 on cell A) but does not
  fully defend.  On its own this arm would say "launch False sweeps
  with γ and drop the False worst-case to whatever (False, evade)
  clears."  But (False, evade) clears *no* cell in this grid, so there
  is no smaller cell to drop to within the probe's range.

* **"(True, baseline) > 0.10 on cell A → operating point past system
  capacity REGARDLESS of regime; §5 grid scales down before B7; probe
  again at the smaller worst-case before greenlight"** — FIRES and
  **controls.**  (True, baseline) cell A median 0.310.  Since True is
  the *easier* regime (no distance-0 events) and it still fails, the
  operating point is intrinsically past capacity.

* **"(True, evade) ≫ (True, baseline)"** (investigate) — does NOT
  fire (byte-identical, as designed).

* **noise branch** — does NOT fire; seeds cluster tightly (e.g.
  F-E cell A: 0.230/0.180/0.170; T-B cell A: 0.310/0.290/0.370).

**Decision: B7 is NOT greenlit at the current §5 worst-case grid.**

Refinement beyond the brief's tree: the brief's controlling arm says
"probe again at the smaller worst-case (cell B or D)."  This probe
already ran cells B, C, D — and **they also fail for every combo**
(B/C/D medians 0.147–0.430).  So scaling down *within this grid* is
not a path to a passing cell.  The re-probe must target agent counts
**below 75** on `warehouse-10-20-10-2-2` (or a less corridor-dense
map), OR the deadlock root cause must be diagnosed and fixed first.

## What B7 needs before it can launch (none of which is in scope here)

1. **Deadlock root-cause diagnosis at high density** — the dominant
   blocker.  The failure is regime-independent and saturated-throughput
   (util ≈ 0.98 while 18–56 % of the fleet is stalled): the classic
   audit-09-§1 "throughput masks deadlock" signature.  Candidates:
   the `congestion_avoidance` allocator, the §5.4 coordination policy
   at high density on a corridor-heavy map, the Wait-Based (`priority`)
   resolver under saturation, the deadlock detector's own threshold.
   γ's 46 % reduction is a hint that *predictive* coordination
   matters, but the floor is set by something regime-independent.

2. **A density re-probe below 75 agents** on this map once (1) is
   understood — to find the agent count at which (False, evade) and/or
   (True, baseline) clear clause 4, which sets the §5 grid's true
   worst-case.

3. **A map-sensitivity check** — does `random-64-64-10` (the other
   `horizon_replan_full` map, far less corridor-constrained) show the
   same wall?  If random clears at 100 agents while warehouse doesn't,
   the §5 grid can keep 100 agents on random and cap warehouse lower.
   Out of scope here (the probe ran only warehouse).

## γ recommendation for whenever B7 does launch

The data support launching **False-regime sweeps with
`algorithm_variant=evade`** (46 % median deadlock reduction, no
downside observed) and **True-regime sweeps with either variant**
(byte-identical; baseline is the simpler default).  This recommendation
is conditional on the density question above being resolved — γ
reduces but does not eliminate the deadlock, so it is necessary-not-
sufficient for the False regime.

## Artifacts

- `configs/probe/diagnostic_probe_{true_baseline,true_evade,false_evade}.yaml`
- `configs/probe/diagnostic_probe_{...}_manifest.yaml`
- `logs/probe/diagnostic/{true_baseline,true_evade,false_evade}/results.csv` (12 rows each)
- `logs/probe/diagnostic/{...}/results_INVALID.csv` (runner split; same rows)
- `logs/probe/diagnostic/{...}/validity_report.json`
- `logs/probe/diagnostic/{...}/run_validity_summary.csv`
- This file: `reports/audit/15_diagnostic_probe.md`

## Decision recorded

**B7 (Phase 3 full re-run) is NOT greenlit at the §5 worst-case grid
(75-100 agents, warehouse-10-20-10-2-2).**  Justification: every cell
of every (regime, variant) combination fails clause 4; the deadlock is
regime-independent and operating-point-intrinsic.  γ halves False-
regime deadlock but clears no cell; γ is a verified no-op under True.
B7 is blocked on (1) a deadlock root-cause diagnosis and (2) a density
re-probe below 75 agents — both separate prompts.

`RESUME_DECISION.md` §D is updated to fold this into the combined
Phase 2 prompts 3+6 outcome.
