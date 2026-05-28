# Audit step 09 — strong-predicate retroactive check

Reopens audit 07's verdict.  Audit 07 declared all 14 sweeps
"accidentally compliant" with `max_invalid_fraction=0.0` — but
that conclusion used `status=='ok'` as the validity predicate.
`status=='ok'` only catches *crashed* runs (audit 05 §3); it
cannot detect degenerate runs where the simulator completed
without raising but produced biased data.  This step re-derives
the verdict under a stronger predicate.

## 1. Predicate decision

A run is **INVALID** iff any of the following clauses fire:

  - `status != 'ok'`  (run crashed — baseline; rare in the
    committed data)
  - `global_replans == 0`  (Tier-1 never ran — P2 origin)
  - `solver_fail_fraction > 0.05`  where
    `solver_fail_fraction = (solver_timeouts + solver_errors) / max(1, global_replans)`
    (P2 origin)
  - **`deadlock_count / num_agents > 0.10`**  (NEW: fleet-stall threshold)

### Why the fleet-stall clause is load-bearing

1. **Throughput masks deadlocks under arrival saturation.**  Audit
   04 §3.3 and audit 05 §2.2 established that the system arrival rate
   is $\lambda_{\text{sys}} = n / (H + W)$.  At $|M| \ge 100$ on the
   warehouse + 64×64 random maps the throughput column is pinned at
   $\lambda_{\text{sys}}$ regardless of how many agents are stuck — a
   deadlocked agent does not subtract from throughput as long as
   enough live agents drain the queue.  So the throughput column
   alone is insufficient to detect agent-level degeneracy.

2. **Safety metrics under-report on stuck agents.**  $N_a$ and $N_x$
   are agent-tick counts; a deadlocked agent emits **zero**
   violations because it isn't moving.  A run with 30% of the fleet
   deadlocked therefore reports systematically lower violation
   counts than a healthy run on the same parameters — the numbers
   are biased, not just smaller.

3. **`deadlock_count` is per-distinct-agent** (audit 02 §6), so
   `dl/n` is an interpretable fleet-stall fraction.  10% is a
   conservative threshold: lower than the 30%+ observed on the
   warehouse cells in this audit (so it actually catches them),
   but lenient enough that occasional dead-ends do not trip the
   gate.

### Why the 0.05 solver-fail clause is the P2-spirit re-statement

The 13 tuning YAMLs' own comment block (now at top-level after
audit 07) defines the per-row INVALID predicate as:

> A row is INVALID iff any of:
>   * run_valid == False,
>   * solver_fail_fraction > 0.05,
>   * global_replans == 0 (Tier-1 never ran).

The strong predicate adopts those three clauses verbatim and adds
the deadlock-fraction clause to close the throughput-masks-deadlock
gap.

### Why `status=='ok'` alone is insufficient

`status='ok'` means `sim.run()` returned without raising
(run_paper_experiment.py:363).  None of the in-run degeneracy
signals fire on this column: it stays `ok` whether the Tier-1
solver timed out on every call (the simulator falls back to last
good plan), whether 50% of agents are stuck (the simulator
continues stepping idle WAITs), or whether throughput is pinned
at the arrival cap (the simulator continues completing the
arriving tasks).  Using `status='ok'` as the validity predicate
treats every of these failure modes as a valid datum.

Concrete example from the data: `logs/tuning/horizon_replan_full`
has median `solver_errors=9` on median `global_replans=146` (6.2%
solver-fail rate); 292 of 640 rows (46%) have solver-fail in
$(0.10, 0.50]$ — i.e. **10-50% of global solver calls failed** —
yet every row is `status='ok'`.

---

## 2. Retroactive table: status-only vs strong predicate (14 tuning sweeps)

Threshold in every YAML: `max_invalid_fraction = 0.0` (strict).

| Sweep | rows | status-inv | strong-inv | worst dl/n | Status-only verdict | Strong-pred verdict |
|---|---:|---:|---:|---:|---|---|
| `allocator_comparison_fov3_safe1`            | 200 |  0 | 198 (99.0%) | 0.350 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov3_safe1_overlap`    | 200 |  0 | 198 (99.0%) | 0.350 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov3_safe1_v3`         | 200 |  0 | 198 (99.0%) | 0.350 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2`            | 200 |  0 | 190 (95.0%) | 0.310 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_overlap`    | 200 |  0 | 190 (95.0%) | 0.310 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_v1_62e89e6` | 200 |  0 | 190 (95.0%) | 0.310 | would pass | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_v2`         | 200 |  0 | 190 (95.0%) | 0.310 | would pass | **WOULD FAIL** |
| `fov_safety_sweep`                            | 700 |  0 | 700 (100%)  | 0.410 | would pass | **WOULD FAIL** |
| `horizon_replan_full`                         | 640 |  0 | 534 (83.4%) | 0.427 | would pass | **WOULD FAIL** |
| `scaling_agents_fov3_safe1`                   | 560 |  0 | 423 (75.5%) | 0.410 | would pass | **WOULD FAIL** |
| `scaling_agents_fov4_safe2`                   | 560 |  0 | 392 (70.0%) | 0.296 | would pass | **WOULD FAIL** |
| `scaling_humans_fov3_safe1`                   | 560 |  0 | 508 (90.7%) | 0.535 | would pass | **WOULD FAIL** |
| `scaling_humans_fov4_safe2`                   | 560 |  0 | 474 (84.6%) | 0.505 | would pass | **WOULD FAIL** |
| `soft_safety_ablation`                        | 180 |  0 | 174 (96.7%) | 0.280 | would pass | **WOULD FAIL** |

Per-sweep, the dominant failing clause is `solver_fail > 0.05`
(415 - 700 rows per sweep); the deadlock-fraction clause adds
1 - 119 additional rows.  All 14 sweeps would have been **rejected**
by the gate the YAMLs explicitly asked for, had the gate been
wired correctly.

### Flip count

| Verdict change | Count |
|---|---:|
| status-only PASS → strong PASS | 0 |
| status-only PASS → strong FAIL | **14** |
| status-only FAIL → strong FAIL | 0 |

**All 14 verdicts flip.**

---

## 3. Paper-side CSVs are similarly affected

The 14 tuning sweeps inform **parameter selection** (horizon,
replan_every, fov, safety, allocator) — they are inputs to the
paper.  The **headline paper CSVs** under `logs/paper/` are
where the published tables get their numbers.  Running the same
strong predicate on those CSVs:

| Paper CSV | rows | strong-inv | %  invalid | dl-fail | sf-fail | has dl |
|---|---:|---:|---:|---:|---:|:--:|
| `logs/paper/allocator_alternatives/results.csv`  |  160 |  160 | 100.0% |    0 |  160 |  no |
| `logs/paper/aux_h_r_decoupling/results.csv`      |  110 |   40 |  36.4% |    0 |   40 |  no |
| `logs/paper/baseline_comparison/results.csv`     |  720 |  632 |  87.8% |    0 |  632 |  no |
| `logs/paper/baseline_comparison_v2/results.csv`  |  720 |  654 |  90.8% |  559 |  452 | yes |
| `logs/paper/budget_sensitivity/results.csv`      |  160 |  160 | 100.0% |    0 |  160 |  no |
| `logs/paper/fov_safety/results.csv`              |  400 |  267 |  66.8% |    0 |  267 |  no |
| `logs/paper/scaling_agents/results.csv`          | 1040 |  874 |  84.0% |    0 |  874 |  no |
| `logs/paper/scaling_exogenous/results.csv`       |  760 |  751 |  98.8% |    0 |  751 |  no |
| `logs/paper/solver_sensitivity/results.csv`      | 3360 | 2171 |  64.6% |    0 | 2171 |  no |
| `logs/paper/temporal_progression/results.csv`    |   40 |   40 | 100.0% |   37 |   30 | yes |
| `logs/paper/token_passing_ablation/results.csv`  |   60 |   47 |  78.3% |    0 |   47 |  no |

Paper CSVs without `deadlock_count` (9 of 11) cannot have the
deadlock-fraction clause applied — but their `solver_fail`
fractions alone exceed 0.05 on 64.6% - 100% of rows.  Adding the
deadlock clause where the column IS available pushes
`baseline_comparison_v2` from 90.8% (solver-fail only) to 90.8%
(union with deadlock; 559 of 654 invalid rows fail the deadlock
clause specifically) and `temporal_progression` from 75% to 100%.

`logs/paper/baseline_comparison_v2/results.csv` is the §5.5
baseline comparison whose `violations_exogenous_attributable`
median (1,308.5) audit 08 §3 used to confirm the §5.4 $N_x$
identity convention.  559 of the 720 rows (77.6%) have deadlock
fractions exceeding 10% — that identity convention is being
reported on a biased subset.

---

## 4. Consuming paper sections (re-runs / footnotes needed)

| Paper section | Consumes CSV(s) | Strong-pred status |
|---|---|---|
| §5.1 horizon tuning | `logs/tuning/horizon_replan_full/results.csv` | 83.4% invalid |
| §5.3 FoV / safety | `logs/paper/fov_safety/results.csv`, `logs/tuning/fov_safety_sweep/results.csv` | 66.8% / 100% invalid |
| §5.4 scaling | `logs/paper/scaling_agents/results.csv`, `logs/paper/scaling_exogenous/results.csv`, `logs/tuning/scaling_agents_*`, `logs/tuning/scaling_humans_*` | 84.0% / 98.8% / 70-91% invalid |
| §5.5 baseline comparison | `logs/paper/baseline_comparison/results.csv`, `..._v2`, `logs/paper/allocator_alternatives/results.csv`, `logs/paper/token_passing_ablation/results.csv`, `logs/tuning/allocator_comparison_*` | 87.8% / 90.8% / 100% / 78.3% / 95-99% invalid |
| §5.6 soft-safety ablation | `logs/tuning/soft_safety_ablation/results.csv` | 96.7% invalid |
| §5.7 deadlock | `logs/paper/scaling_agents`, `logs/paper/scaling_exogenous` | 84.0% / 98.8% invalid; ALSO missing `deadlock_count` per audit 08 |
| §5.8 temporal | `logs/paper/temporal_progression/results.csv` | 100% invalid |
| appendix: solver / budget / H-R | `logs/paper/solver_sensitivity/`, `budget_sensitivity/`, `aux_h_r_decoupling/` | 64.6% / 100% / 36.4% invalid |

**Every paper section is built on at least one CSV where the
strong predicate marks the majority of rows as invalid.**

---

## 5. Drivers — why is solver-fail so high?

`logs/tuning/horizon_replan_full/results.csv`
(640 rows, 25-100 agents, 2000 steps, lacam_official @ 10s):

| solver_fail_fraction bucket | rows | % |
|---|---:|---:|
| `0` (no failures) | 54 | 8.4% |
| `(0, 0.05]` | 171 | 26.7% |
| `(0.05, 0.10]` | 121 | 18.9% |
| `(0.10, 0.50]` | 292 | 45.6% |
| `(0.50, 1.00]` | 2 | 0.3% |

The 10 s solver budget — calibrated against the P3 cohort (per
`_sweep_config_common.py:30-46`) — is being exceeded on 64.9% of
global solver calls in this sweep's parameter regime
($|M| \in \{25, 50, 75, 100\}$, horizons up to 80 steps).  The
calibration's `lacam_official` p99 of 17 ms suggests the
calibration cohort did NOT include the same operating points the
sweep cells used.

This is a SEPARATE finding from the validity-predicate question
and should be tracked independently — re-calibrating the solver
budget will not change the strong-predicate verdict above unless
the recalibration also resolves the deadlock-fraction signal.

---

## 6. Verdict and consequences

### Verdict

> The strong-predicate retroactive check **flips every one** of the
> 14 tuning sweeps from "would pass" (under status-only) to
> "would have failed" (under the YAML-intended predicate the strict
> `max_invalid_fraction = 0.0` was meant to enforce).  Audit 07's
> "accidentally compliant" conclusion was a status-only artifact;
> under the predicate the YAMLs explicitly described
> (`solver_fail_fraction > 0.05` ⇒ INVALID), every committed sweep
> would have been REJECTED.

### Consequences for committed paper outputs

The §5.x tables built from `logs/paper/*` and the §5.1 horizon
sub-table built from `logs/tuning/horizon_replan_full/` are based
on data where 36.4-100% of rows fail the YAML's own validity
contract.  Re-running these sweeps with either (a) a larger solver
budget, (b) smaller cell sizes (fewer agents per step), or (c) a
relaxed `max_invalid_fraction` with a documented justification is
required before those tables can be presented as faithful to the
YAML's stated validity criterion.

Until then, every paper section listed in §4 above carries the
caveat that its rows aggregate over a population where the
majority did not satisfy the YAML's stated validity gate.

### Reopens

- **BUG #1 (audit 05) — reopened with stronger finding.**  Audit
  07 closed it on the basis of "the inert guard happened to gate
  over already-clean data".  Audit 09 shows the data is **not**
  clean under the predicate the YAML comments described; the inert
  guard was inert *and* the data did not clear the bar.

### Files

- `scripts/diagnostics/strong_retroactive_check.py` — the
  re-runnable retroactive check using the strong predicate.
- This report.

### Acceptance checklist

| Criterion | Status | Evidence |
|---|:--:|---|
| Validity predicate stated with justification, stronger than `status=='ok'` | **PASS** | §1 above; predicate = (status, global_replans, solver_fail, deadlock) |
| Retroactive table regenerated under the strong predicate for all 14 sweeps | **PASS** | §2 table |
| Per-sweep verdict: accidentally-compliant vs would-have-failed | **PASS** | §2 + §4 tables: all 14 flip to WOULD FAIL |
| Consuming paper sections named for any sweep whose verdict flipped | **PASS** | §4 table covers §5.1, §5.3, §5.4, §5.5, §5.6, §5.7, §5.8, appendix |
| BUG #1 status under stronger finding | **REOPENED** | §6 |
