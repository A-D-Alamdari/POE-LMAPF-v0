# Audit step 11 — harden audit 09's strong-predicate verdict

Audit 09 flipped every committed sweep from "would pass" (status-only)
to "WOULD FAIL" under a four-clause strong predicate.  The dominant
contributor was the YAML-verbatim `solver_fail_fraction > 0.05`
clause; the new deadlock-fraction clause used a chosen 10% threshold.

This step removes the choice-of-threshold load-bearing-ness from the
headline finding by isolating each clause independently and
reporting threshold sensitivity.

---

## 1. Solver-fail clause ALONE (unarguable floor)

Predicate: a row is INVALID iff any of
- `status != 'ok'`
- `global_replans == 0`
- `solver_fail_fraction > 0.05`  where
  `solver_fail_fraction = (solver_timeouts + solver_errors) / max(1, global_replans)`

These three clauses are the YAML comment block verbatim
(`_sweep_config_common.py:94-101`).  No deadlock gate.

| Sweep | rows | threshold | solver-invalid | fraction | verdict |
|---|---:|---:|---:|---:|---|
| `allocator_comparison_fov3_safe1`            | 200 | 0.0000 | 179 | 0.895 | **WOULD FAIL** |
| `allocator_comparison_fov3_safe1_overlap`    | 200 | 0.0000 | 179 | 0.895 | **WOULD FAIL** |
| `allocator_comparison_fov3_safe1_v3`         | 200 | 0.0000 | 179 | 0.895 | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2`            | 200 | 0.0000 | 177 | 0.885 | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_overlap`    | 200 | 0.0000 | 177 | 0.885 | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_v1_62e89e6` | 200 | 0.0000 | 177 | 0.885 | **WOULD FAIL** |
| `allocator_comparison_fov4_safe2_v2`         | 200 | 0.0000 | 177 | 0.885 | **WOULD FAIL** |
| `fov_safety_sweep`                            | 700 | 0.0000 | 699 | 0.999 | **WOULD FAIL** |
| `horizon_replan_full`                         | 640 | 0.0000 | 415 | 0.648 | **WOULD FAIL** |
| `scaling_agents_fov3_safe1`                   | 560 | 0.0000 | 331 | 0.591 | **WOULD FAIL** |
| `scaling_agents_fov4_safe2`                   | 560 | 0.0000 | 339 | 0.605 | **WOULD FAIL** |
| `scaling_humans_fov3_safe1`                   | 560 | 0.0000 | 420 | 0.750 | **WOULD FAIL** |
| `scaling_humans_fov4_safe2`                   | 560 | 0.0000 | 420 | 0.750 | **WOULD FAIL** |
| `soft_safety_ablation`                        | 180 | 0.0000 | 170 | 0.944 | **WOULD FAIL** |

**Sweeps failing on the solver clause alone: 14 / 14.**  Minimum
invalid fraction observed: 0.591 (scaling_agents_fov3_safe1).
Maximum: 0.999 (fov_safety_sweep).  Every sweep is at least an order
of magnitude above the 0.0 threshold the YAMLs set.

This is the unarguable floor: it uses only the predicate the YAMLs'
own comment blocks describe, with no audit-introduced gate.

---

## 2. Deadlock clause ALONE — threshold sensitivity

Predicate: a row is INVALID iff `status != 'ok'` OR
`deadlock_count / num_agents > T` for `T ∈ {0.10, 0.20, 0.30}`.
Solver clause disabled.

| Sweep | rows | dl@0.10 | dl@0.20 | dl@0.30 | T=0.10 | T=0.20 | T=0.30 |
|---|---:|---:|---:|---:|:--:|:--:|:--:|
| `allocator_comparison_fov3_safe1`            | 200 | 0.675 | 0.250 | 0.035 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov3_safe1_overlap`    | 200 | 0.675 | 0.250 | 0.035 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov3_safe1_v3`         | 200 | 0.675 | 0.250 | 0.035 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov4_safe2`            | 200 | 0.440 | 0.080 | 0.005 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov4_safe2_overlap`    | 200 | 0.440 | 0.080 | 0.005 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov4_safe2_v1_62e89e6` | 200 | 0.440 | 0.080 | 0.005 | FAIL | FAIL | FAIL |
| `allocator_comparison_fov4_safe2_v2`         | 200 | 0.440 | 0.080 | 0.005 | FAIL | FAIL | FAIL |
| `fov_safety_sweep`                            | 700 | 0.323 | 0.173 | 0.031 | FAIL | FAIL | FAIL |
| `horizon_replan_full`                         | 640 | 0.486 | 0.272 | 0.073 | FAIL | FAIL | FAIL |
| `scaling_agents_fov3_safe1`                   | 560 | 0.289 | 0.102 | 0.025 | FAIL | FAIL | FAIL |
| `scaling_agents_fov4_safe2`                   | 560 | 0.134 | 0.025 | 0.000 | FAIL | FAIL | **pass** |
| `scaling_humans_fov3_safe1`                   | 560 | 0.270 | 0.143 | 0.077 | FAIL | FAIL | FAIL |
| `scaling_humans_fov4_safe2`                   | 560 | 0.155 | 0.089 | 0.041 | FAIL | FAIL | FAIL |
| `soft_safety_ablation`                        | 180 | 0.222 | 0.039 | 0.000 | FAIL | FAIL | **pass** |
| **Failing sweeps** | — | — | — | — | **14 / 14** | **14 / 14** | **12 / 14** |

The deadlock clause alone fails 14/14 at T=0.10 and T=0.20.  At
T=0.30 (deliberately lenient), 12 of 14 still fail; the two
exceptions are `scaling_agents_fov4_safe2` (0.0% of rows exceed 30%
deadlock fraction) and `soft_safety_ablation` (0.0%).  Both still
fail under the solver clause alone.

So the deadlock-clause threshold is not load-bearing for the
headline: the audit-09 finding holds at every threshold considered.

---

## 3. Cross-tab at deadlock T=0.30 (most conservative): contribution of each clause

For each sweep, how many of the strong-invalid rows are caught by
each clause?

| Sweep | rows | solver | dl≥30% | both | solver-only | dl-only | either |
|---|---:|---:|---:|---:|---:|---:|---:|
| `allocator_comparison_fov3_safe1`            | 200 | 179 |  7 |  5 | 174 |  2 | 181 |
| `allocator_comparison_fov3_safe1_overlap`    | 200 | 179 |  7 |  5 | 174 |  2 | 181 |
| `allocator_comparison_fov3_safe1_v3`         | 200 | 179 |  7 |  5 | 174 |  2 | 181 |
| `allocator_comparison_fov4_safe2`            | 200 | 177 |  1 |  1 | 176 |  0 | 177 |
| `allocator_comparison_fov4_safe2_overlap`    | 200 | 177 |  1 |  1 | 176 |  0 | 177 |
| `allocator_comparison_fov4_safe2_v1_62e89e6` | 200 | 177 |  1 |  1 | 176 |  0 | 177 |
| `allocator_comparison_fov4_safe2_v2`         | 200 | 177 |  1 |  1 | 176 |  0 | 177 |
| `fov_safety_sweep`                            | 700 | 699 | 22 | 21 | 678 |  1 | 700 |
| `horizon_replan_full`                         | 640 | 415 | 47 | 42 | 373 |  5 | 420 |
| `scaling_agents_fov3_safe1`                   | 560 | 331 | 14 |  0 | 331 | 14 | 345 |
| `scaling_agents_fov4_safe2`                   | 560 | 339 |  0 |  0 | 339 |  0 | 339 |
| `scaling_humans_fov3_safe1`                   | 560 | 420 | 43 |  2 | 418 | 41 | 461 |
| `scaling_humans_fov4_safe2`                   | 560 | 420 | 23 |  1 | 419 | 22 | 442 |
| `soft_safety_ablation`                        | 180 | 170 |  0 |  0 | 170 |  0 | 170 |

The cross-tab makes the contributions explicit:

- **`solver-only`** column dominates everywhere (170-678 rows per
  sweep are caught only by the solver clause).  Removing the
  deadlock clause from the union changes nothing — the solver
  clause already catches the rows.
- **`dl-only`** column is small (0-41 rows per sweep).  These are
  rows with high deadlock fraction but acceptable solver-fail
  rate; deadlock catches them as an additional layer.
- **`both`** column is small (0-42 rows per sweep).  The two
  failure modes overlap weakly; high-deadlock runs aren't
  predominantly the same runs as high-solver-fail runs.
- **`either`** column (the strong-predicate union) is at most 9%
  larger than the solver-only column (`scaling_humans_fov3_safe1`:
  461 vs 420, +9.8%).  At the tight deadlock=0.30 threshold the
  deadlock clause adds at most ~10% to the solver clause's verdict.

---

## 4. Hand-verification of solver_fail arithmetic (3 rows)

The whole finding rests on the arithmetic
`solver_fail_fraction = (solver_timeouts + solver_errors) / max(1, global_replans)`
being computed correctly.  Three rows from
`logs/tuning/horizon_replan_full/results.csv` recomputed by hand:

### Row #307 — LOW (clean run)
```
run_id            = e713d277
solver_timeouts   = 0
solver_errors     = 0
global_replans    = 400
deadlock_count    = 5
num_agents        = 25
```
By hand: `(0 + 0) / max(1, 400) = 0 / 400 = 0.000000`
Audit value: `0.000000`  ⇒ **MATCH**.  Deadlock fraction
5/25 = 0.200 — would still flag at T=0.10 but solver clause
exempts it.

### Row #4 — NEAR-THRESHOLD
```
run_id            = 731d2b35
solver_timeouts   = 11
solver_errors     = 2
global_replans    = 419
deadlock_count    = 2
num_agents        = 25
```
By hand: `(11 + 2) / max(1, 419) = 13 / 419 = 0.031026`
Audit value: `0.031026`  ⇒ **MATCH**.  Below 0.05 threshold:
solver clause does not flag.  Deadlock fraction 2/25 = 0.080
also below T=0.10: deadlock clause does not flag either.  Row is
VALID under the strong predicate.

### Row #296 — HIGH (well above 0.05)
```
run_id            = c719e3fd
solver_timeouts   = 0
solver_errors     = 48
global_replans    = 82
deadlock_count    = 7
num_agents        = 100
```
By hand: `(0 + 48) / max(1, 82) = 48 / 82 = 0.585366`
Audit value: `0.585366`  ⇒ **MATCH**.  Solver clause flags at 58.5%
fail rate — over an order of magnitude above 0.05.  Deadlock
fraction 7/100 = 0.070, below T=0.10: deadlock clause does not flag.
Row is INVALID by the solver clause alone.

**All 3 hand-recomputed values match the audit's computed value
exactly (1e-12 tolerance).**  The arithmetic is correct.

---

## 5. Hardened headline

> **Even under the most conservative reasonable predicate — the
> solver-fail clause taken verbatim from the YAML comment blocks,
> with NO deadlock gate — 14 of 14 committed tuning sweeps would
> have FAILED their stated `max_invalid_fraction = 0.0` threshold.
> Invalid fractions on this minimal predicate range from 0.591 to
> 0.999 across the 14 sweeps; the minimum is more than ten times
> the strict threshold.  Audit 09's verdict is hardened.**

The deadlock-fraction clause is supplementary, not load-bearing:
the verdict survives without it at every threshold considered
(0.10, 0.20, 0.30).  The cross-tab in §3 shows the deadlock clause
adds at most ~10% to the solver clause's verdict at the tightest
deadlock threshold (T=0.30).

---

## Summary

| Acceptance criterion | Status | Evidence |
|---|:--:|---|
| Solver-fail-only verdict reported for all 14 sweeps | **PASS** | §1: 14/14 fail; invalid fractions 0.591-0.999 |
| Deadlock-clause sensitivity at 10/20/30% reported | **PASS** | §2: 14/14 at T=0.10 and T=0.20; 12/14 at T=0.30 |
| 3 hand-recomputed `solver_fail_fraction` rows | **PASS** | §4: all 3 match to 1e-12 |
| Hardened headline | **PASS** | §5: 14 of 14 sweeps fail on solver clause alone |

## CLOSED

- The audit-09 verdict no longer rests on a chosen deadlock
  threshold.  The solver-fail clause alone — derived verbatim from
  the YAMLs' own comment blocks — is sufficient to flip every
  sweep.

- The arithmetic was hand-verified on 3 rows from
  `horizon_replan_full`: every value matches to 1e-12.

- The deadlock-fraction clause's contribution is quantified: at
  T=0.30 it adds at most ~10% to the solver clause's verdict; at
  T=0.10 / 0.20 it is dominated by but consistent with the solver
  clause.

- The horizontal axis (which threshold is "right" for the
  deadlock fraction) does not change the headline at any
  threshold considered.
