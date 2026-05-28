# Audit step 10 — metric-repair validation, end-to-end

Audit 08 §1 established that **0 of 27 committed `results.csv` files**
carry the columns added by Prompts 1, 2, 6, and C
(`violations_def1_*`, `arrival_rate_per_step`,
`throughput_utilization`, `physics_revert_wait_steps`,
`delay_wait_steps`, `safety_violation_events`, and the per-bucket
`*_events` aliases).

Audit 08's verdict line said "BUGS FOUND: none" because every row of
every committed CSV passes every invariant the columns it has allow
checking.  Audit 10 reframes that: the absence of the new columns
means **the repair is not validated end-to-end** — only the rows the
repair changed cannot be inspected on committed data, so the
guarantee "the live code produces the corrected values on real
runs" is asserted, not measured.

This audit:
1. States the reframed verdict precisely.
2. Tabulates per paper section which committed CSV backs it and
   which corrected columns it needs.
3. Runs ONE small real config on head, populates the corrected
   columns, and tests the identity claim row-for-row on real data.
4. Confirms `violations_def1_agent_attributable == 0` on real data
   (Theorem-1 empirical invariant).
5. Estimates the wall-clock cost of regenerating each sweep under
   the corrected schema, so the resume decision has a number.

---

## 1. Reframed audit-08 verdict

Audit 08 §2 stated "every checkable invariant holds on every row of
every CSV" — true and unchanged.  But the *checkability* of the
invariants depends on the columns present, and the columns the
metric repair added are present on **0 of 27 CSVs**:

| Repair | Columns added | CSVs carrying them |
|---|---|---:|
| Prompt 1 (Def-1 classifier) | `violations_def1_agent_attributable`, `violations_def1_exogenous_attributable`, `violations_def1_safety_violations` | **0 / 27** |
| Prompt 2 (event debounce) | `safety_violation_events`, `violations_agent_attributable_events`, `violations_exogenous_attributable_events` | **0 / 27** |
| Prompt 6 (load regime) | `arrival_rate_per_step`, `throughput_utilization` | **0 / 27** |
| Prompt C / P11 (wait-kind) | `physics_revert_wait_steps`, `delay_wait_steps` | **0 / 27** |

Reframed verdict:

> **The metric repair (Prompts 1, 2, 6, C) exists only in the live
> code and in synthetic tests.  No committed sweep has been
> regenerated under the corrected schema.  Every paper table currently
> rebuilds from the legacy (pre-fix) schema, so the §5.x numbers
> the paper publishes reflect the OLD definitions of N_x / N_a /
> wait_fraction-by-kind / arrival utilization — not the
> corrected ones the live code now emits.**

The fix is not invalid; it is **unmeasured at the sweep level**.

---

## 2. Per-section regeneration requirement

For each paper section, the source CSV and the columns the
corrected rebuild would need:

| Section | Source CSV(s) | Missing columns it needs | Rebuildable from committed CSV? |
|---|---|---|:--:|
| §5.1 horizon tuning | `logs/tuning/horizon_replan_full/results.csv` (and the legacy `logs/tuning/horizon/2026-05-11_17-01-13/`) | `violations_def1_*`, `arrival_rate_per_step`, `throughput_utilization`, `physics_revert_wait_steps`, `delay_wait_steps`, `safety_violation_events` | **NO** — needs Def-1 + arrival-rate + 4-bucket wait |
| §5.3 FoV / safety | `logs/paper/fov_safety/results.csv`, `logs/tuning/fov_safety_sweep/results.csv` | same as above | **NO** |
| §5.4 scaling | `logs/paper/scaling_agents/results.csv`, `logs/paper/scaling_exogenous/results.csv`, `logs/tuning/scaling_*` | same as above, AND `deadlock_count` (the two paper/ CSVs lack it; see audit 08 §1) | **NO** |
| §5.5 baseline comparison | `logs/paper/baseline_comparison_v2/results.csv`, `logs/paper/allocator_alternatives/`, `logs/paper/token_passing_ablation/`, `logs/tuning/allocator_comparison_*` | same as above | **NO** |
| §5.6 soft-safety ablation | `logs/tuning/soft_safety_ablation/results.csv` | same as above | **NO** |
| §5.7 deadlock | `logs/paper/scaling_agents`, `logs/paper/scaling_exogenous` | `deadlock_count` (universally absent from these two), plus Def-1 + 4-bucket | **NO** — even the §5.7 headline column is missing |
| §5.8 temporal | `logs/paper/temporal_progression/results.csv` | same as §5.1, plus the per-tick timeline sidecar JSONs (audit 08 noted not inspected) | **NO** |
| appendix: H/R | `logs/paper/aux_h_r_decoupling/results.csv` | same as §5.1; also lacks `deadlock_count` | **NO** |
| appendix: solver / budget | `logs/paper/solver_sensitivity/`, `logs/paper/budget_sensitivity/` | same as §5.1; also lacks `deadlock_count` | **NO** |

**Every section needs at least one sweep re-run.**  No section can
be rebuilt under the corrected schema from data on disk today.

Sections that **only** report columns the legacy schema already
emits (e.g. raw `throughput`, raw `safety_violations` as a single
scalar, `total_wait_steps`, sum-of-costs) could in principle be
rebuilt from committed data — but every committed §5.x table this
audit could inspect surfaces at least one of the new columns
(typically `arrival_rate_per_step` for saturation marking,
`violations_def1_*` for N_x, or the wait-kind breakdown), so the
exception is theoretical.

---

## 3. Real-run validation: identity claim on live data

The classifier docstring at `simulator.py:1192-1245` and the audit
history in `reports/table1_audit.md` claim:

> When `violations_def1_agent_attributable == 0` (the Theorem-1
> empirical invariant), `violations_def1_exogenous_attributable`
> equals `violations_exogenous_attributable` — both classifiers
> iterate the **same** post-move violation-pair set; the
> disagreement is solely in the agent-attribution clause.

This audit tests the claim **on a real run** for the first time
(prior synthetic checks in audit 02 §3 used hand-built single ticks).

### Configuration

| Setting | Value |
|---|---|
| Map | `data/maps/empty-16-16.map` (16×16 open) |
| Agents | 4 |
| Humans | 5 |
| `fov_radius` / `safety_radius` | 2 / 1 (satisfies audit-06 precondition) |
| Steps | 300 |
| Human model | `random_walk` |
| Mode | `lifelong` |
| Allocator | `congestion_avoidance` |
| Hard safety | True |
| Seeds | 0, 1, 2 |

### Per-seed observations

| Seed | wall (s) | `sv` | legacy_agent | legacy_exo | **def1_agent** | **def1_exo** | def1_sum | identity? | def1_agent == 0? |
|---:|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| 0 | 0.62 | 11 | 0 | 11 | **0** | **11** | 11 | **Y** | **Y** |
| 1 | 0.27 | 30 | 0 | 30 | **0** | **30** | 30 | **Y** | **Y** |
| 2 | 0.29 | 24 | 0 | 24 | **0** | **24** | 24 | **Y** | **Y** |

### Verdicts

- **Identity claim** (`def1_exo == legacy_exo` when `def1_agent == 0`): **PASS** on all 3 seeds.  This is the first real-data confirmation; prior verification was synthetic single ticks (audit 02 §3).
- **Construction claim** (`def1_agent == 0` on healthy hard-safety runs — paper Theorem 1's empirical witness): **PASS** on all 3 seeds.  Theorem 1's "zero agent-attributable violations on Algorithm-2 trajectories" holds on real data, matching the synthetic proof in `docs/proposed_approach.md` §F and the audit 02 §3 single-tick check.
- **All new columns populated**: `arrival_rate_per_step=0.12`, `throughput_utilization=1.00`, `physics_revert_wait_steps=4`, `delay_wait_steps=0`, `deadlock_count=0`, `safety_violation_events=10` (≤ `sv=11`, debounce bound holds).

The seed-0 run produced 4 physics-revert WAITs naturally — independent confirmation of the audit-07 reachability finding from a different scenario.

`throughput_utilization = 1.00` means even this small config is arrival-saturated; the load-regime concern from audit 04 §3.3 applies to almost any non-trivial run.

The data file is committed at `logs/audit/audit10_smoke.csv` (~3 KB, 3 rows).

---

## 4. Regeneration cost estimate

Per-sweep wall-clock cost, computed by summing `wall_clock_s`
across every row of each committed CSV (single-worker
equivalent).  Parallel-worker estimates assume linear scaling
(optimistic; ignores I/O and contention).

### Tuning sweeps (the 14 from audit 09)

| Sweep | rows | median (s) | p95 (s) | total (core-h) | 8-worker wall (h) | 32-worker wall (h) |
|---|---:|---:|---:|---:|---:|---:|
| `horizon_replan_full`                        | 640 |   323 | 1085 |   73.7 |  9.2 | 2.3 |
| `fov_safety_sweep`                           | 700 |   910 | 1342 |  178.6 | 22.3 | 5.6 |
| `scaling_agents_fov3_safe1`                  | 560 |   499 | 2015 |  117.3 | 14.7 | 3.7 |
| `scaling_agents_fov4_safe2`                  | 560 |   694 | 2522 |  153.6 | 19.2 | 4.8 |
| `scaling_humans_fov3_safe1`                  | 560 |  1516 | 3622 |  256.7 | 32.1 | 8.0 |
| `scaling_humans_fov4_safe2`                  | 560 |  1360 | 2830 |  214.8 | 26.8 | 6.7 |
| `allocator_comparison_fov3_safe1`            | 200 |   491 | 1417 |   34.5 |  4.3 | 1.1 |
| `allocator_comparison_fov3_safe1_overlap`    | 200 |   560 | 1705 |   40.6 |  5.1 | 1.3 |
| `allocator_comparison_fov3_safe1_v3`         | 200 |   502 | 1418 |   34.8 |  4.4 | 1.1 |
| `allocator_comparison_fov4_safe2`            | 200 |   741 | 1839 |   48.6 |  6.1 | 1.5 |
| `allocator_comparison_fov4_safe2_overlap`    | 200 |   684 | 1696 |   44.7 |  5.6 | 1.4 |
| `allocator_comparison_fov4_safe2_v1_62e89e6` | 200 |   741 | 1839 |   48.6 |  6.1 | 1.5 |
| `allocator_comparison_fov4_safe2_v2`         | 200 |   749 | 1864 |   49.1 |  6.1 | 1.5 |
| `soft_safety_ablation`                       | 180 |  1667 | 2320 |   73.8 |  9.2 | 2.3 |
| **Subtotal — tuning** | **5,160** | — | — | **1,369** | **171** | **42.8** |

### Paper sweeps (consumed directly by paper tables)

| Sweep | rows | median (s) | total (core-h) | 8-worker (h) | 32-worker (h) |
|---|---:|---:|---:|---:|---:|
| `allocator_alternatives`         |  160 | 1197 |   58.2 |  7.3 |  1.8 |
| `aux_h_r_decoupling`             |  110 |  347 |   20.8 |  2.6 |  0.7 |
| `baseline_comparison`            |  720 |  351 |  162.1 | 20.3 |  5.1 |
| `baseline_comparison_v2`         |  720 | 1216 |  296.3 | 37.0 |  9.3 |
| `budget_sensitivity`             |  160 | 1276 |   62.9 |  7.9 |  2.0 |
| `fov_safety`                     |  400 |  363 |   46.7 |  5.8 |  1.5 |
| `scaling_agents`                 | 1040 | 1004 |  493.9 | 61.7 | 15.4 |
| `scaling_exogenous`              |  760 |  836 |  193.6 | 24.2 |  6.1 |
| `solver_sensitivity`             | 3360 |  301 |  384.6 | 48.1 | 12.0 |
| `temporal_progression`           |   40 | 1440 |   15.1 |  1.9 |  0.5 |
| `token_passing_ablation`         |   60 | 1394 |   23.5 |  2.9 |  0.7 |
| **Subtotal — paper** | **7,530** | — | **1,758** | **220** | **55.0** |

### Grand total

- **Total runs to regenerate: 12,690**
- **Single-worker cost: ~3,127 core-hours (~130 days)**
- **8-worker wall: ~390 hours (~16 days)**
- **32-worker wall: ~98 hours (~4 days)**

### Cost-prioritized resume options

If a full regeneration is impractical, three smaller alternatives:

1. **Just §5.1 + §5.5 headline** (the two tables with stable
   committed paper text): `horizon_replan_full` +
   `baseline_comparison_v2` = 370 core-h = **12 h on 32 workers**.

2. **All §5 paper-section CSVs, skip tuning predecessors**: paper
   subtotal = 1,758 core-h = **55 h on 32 workers** (~2.3 days).

3. **All sweeps, full regeneration**: 3,127 core-h = **~4 days on
   32 workers**.

### Caveat (per audit 09)

The strong-predicate verdict in audit 09 showed that the *current*
solver budget (`solver_timeout_s = 10.0`) is exceeded on 64.9% of
calls in the horizon sweep.  A regeneration that does not also
raise the budget (or shrink the cells) would inherit the same
solver-fail / deadlock-fraction degeneracy under the new schema.
The resume decision should bundle these two questions: regenerate
under what budget?  Audit 09 left the calibration question open.

---

## Summary

| Acceptance criterion | Status | Evidence |
|---|:--:|---|
| Audit 08 verdict reframed: repair unvalidated end-to-end | **PASS** | §1 above |
| Per-section table of CSV + missing columns + rebuildable | **PASS** | §2 table (every section "NO") |
| One small real run on head produces def1 columns | **PASS** | §3, `logs/audit/audit10_smoke.csv` |
| Identity claim tested row-for-row on real data | **PASS** | §3 per-seed table: all 3 seeds identity == Y |
| `def1_agent == 0` confirmed (or flagged) on real run | **PASS** | §3 per-seed table: all 3 seeds def1_agent == 0 |
| Regeneration cost estimate per sweep | **PASS** | §4 tables (tuning + paper) |

## BUGS FOUND

None at the code level — the live code emits the corrected columns
and the identity / construction invariants hold on real runs.  The
finding is at the **provenance** level: every paper table is built
from a CSV that pre-dates the metric repair, so the published §5.x
numbers reflect the legacy classifier / counter definitions.

## SCOPED FOR RESUME (not launched in this audit step)

- 12,690 runs across 25 committed sweep directories require
  regeneration to validate the metric repair end-to-end.
- Estimated cost: ~3,130 core-hours sequential / ~4 days on 32
  workers.
- Per-section breakdowns and three cost-prioritized resume paths
  are in §4 above.
- The audit-09 calibration question (10s solver budget exceeded
  on 64.9% of horizon-sweep calls) must be bundled with the
  regeneration decision; without a larger budget, the new CSVs
  will inherit the same strong-predicate degeneracy.
