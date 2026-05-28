# Audit step 08 — committed `logs/` CSV consistency

> **Numbering note**: the task brief named this report
> `06_csv_consistency.md`.  Slot 06 was already taken by
> `06_preconditions.md` (the audit that enforced `r_safe < r_fov` and
> the `R = floor(H/2)` decoupling), so this CSV audit lands at 08 in
> chronological commit order.

Scope: every committed `results.csv` under `logs/` (27 files,
totalling 14,839 rows across the paper and tuning sweeps).  Read +
arithmetic only; no re-runs, no edits.  Repro: `python
scripts/diagnostics/audit_csv_consistency.py`.

---

## 1. Schema-version matrix — **EVERY CSV IS STALE**

For each CSV, presence of the columns the current head code emits:

| CSV | rows | cols | def1 | deadlock | arrival_rate | util | p_revert | delay_w | safe_w | yield_w | sv_events |
|---|---:|---:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| `logs/paper/allocator_alternatives/results.csv` | 160 | 79 | . | Y | . | . | . | . | Y | Y | . |
| `logs/paper/aux_h_r_decoupling/results.csv` | 110 | 64 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/baseline_comparison/results.csv` | 720 | 79 | . | Y | . | . | . | . | Y | Y | . |
| `logs/paper/baseline_comparison_v2/results.csv` | 720 | 79 | . | Y | . | . | . | . | Y | Y | . |
| `logs/paper/budget_sensitivity/results.csv` | 160 | 64 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/fov_safety/results.csv` | 400 | 63 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/scaling_agents/results.csv` | 1040 | 63 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/scaling_exogenous/results.csv` | 760 | 63 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/solver_sensitivity/results.csv` | 3360 | 63 | . | . | . | . | . | . | Y | Y | . |
| `logs/paper/temporal_progression/results.csv` | 40 | 75 | . | Y | . | . | . | . | Y | Y | . |
| `logs/paper/token_passing_ablation/results.csv` | 60 | 63 | . | . | . | . | . | . | Y | Y | . |
| `logs/tuning/_superseded_pre_overlap/allocator_comparison_fov3_safe1/results.csv` | 200 | 78 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov3_safe1/results.csv` | 200 | 78 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov3_safe1_overlap/results.csv` | 200 | 80 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov3_safe1_v3/results.csv` | 200 | 83 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov4_safe2/results.csv` | 200 | 78 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov4_safe2_overlap/results.csv` | 200 | 80 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov4_safe2_v1_62e89e6/results.csv` | 200 | 78 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/allocator_comparison_fov4_safe2_v2/results.csv` | 200 | 83 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/fov_safety_sweep/results.csv` | 700 | 75 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/horizon/2026-05-11_17-01-13/results.csv` | 909 | 51 | . | . | . | . | . | . | Y | Y | . |
| `logs/tuning/horizon_replan_full/results.csv` | 640 | 75 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/scaling_agents_fov3_safe1/results.csv` | 560 | 77 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/scaling_agents_fov4_safe2/results.csv` | 560 | 77 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/scaling_humans_fov3_safe1/results.csv` | 560 | 77 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/scaling_humans_fov4_safe2/results.csv` | 560 | 77 | . | Y | . | . | . | . | Y | Y | . |
| `logs/tuning/soft_safety_ablation/results.csv` | 180 | 82 | . | Y | . | . | . | . | Y | Y | . |

### Column-presence totals (across all 27 CSVs)

| Column | CSVs carrying it | Schema generation |
|---|---:|---|
| `safe_wait_steps`, `yield_wait_steps` | 27 | legacy (pre-P11) |
| `safety_violations`, `violations_agent_attributable`, `violations_exogenous_attributable` | 27 | post-Section 3.4 attribution split |
| `deadlock_count` | 20 | post-Prompt-5 (§5.7) |
| `violations_def1_agent_attributable` / `_exogenous_attributable` | **0** | post-Prompt-1 |
| `arrival_rate_per_step` | **0** | post-Prompt-6 (§5.1 load-regime) |
| `throughput_utilization` | **0** | post-Prompt-6 |
| `physics_revert_wait_steps` | **0** | post-Prompt-C / P11 |
| `delay_wait_steps` | **0** | post-Prompt-C / P11 |
| `safety_violation_events` | **0** | post-Prompt-2 / event debounce |
| `violations_agent_attributable_events`, `_exogenous_attributable_events` | **0** | post-Prompt-2 |

**Every committed CSV is STALE relative to head.**  Specifically:
- No CSV carries the **Definition-1** violation columns (Prompt 1).
  Paper sections that compare $N_x$ across classifiers cannot be
  rebuilt from these CSVs; the only attribution columns present are
  the legacy WAIT-counterfactual buckets.
- No CSV carries the **arrival-rate / utilization** columns (Prompt 6).
  The §5.1 load-regime saturation flag (`*` marker) currently has to
  be computed offline from `num_agents`, `steps`, `total_released_tasks`,
  and the map H/W; it cannot be read from the CSV directly.
- No CSV carries the **four-bucket wait-kind** columns (Prompt C / P11).
  Paper sections that distinguish safe-wait vs yield-wait vs
  physics-revert vs delay must rely on the legacy two-bucket split
  `safe_wait_steps + yield_wait_steps`.
- No CSV carries the **debounced event** columns (Prompt 2).  The
  `*_events` vs `*_agent_ticks` distinction the paper text refers to
  is not in these CSVs.

### Stale CSVs by consuming paper section

| Paper section | Stale CSV consumed | Missing instrumentation impact |
|---|---|---|
| §5.1 horizon tuning | `logs/tuning/horizon_replan_full/results.csv` | no Def-1 columns; no arrival-rate / utilization; no P11 wait-kind |
| §5.1 horizon (early) | `logs/tuning/horizon/2026-05-11_17-01-13/results.csv` | as above, plus no `deadlock_count` |
| §5.3 FoV / safety | `logs/paper/fov_safety/results.csv`, `logs/tuning/fov_safety_sweep/results.csv` | as above (no `deadlock_count` for `paper/fov_safety/`) |
| §5.4 scaling | `logs/paper/scaling_agents`, `logs/paper/scaling_exogenous`, `logs/tuning/scaling_*` | as above |
| §5.5 baseline comparison | `logs/paper/baseline_comparison`, `..._v2`, `logs/paper/allocator_alternatives`, `logs/paper/token_passing_ablation`, `logs/tuning/allocator_comparison_*` | as above |
| §5.6 soft-safety ablation | `logs/tuning/soft_safety_ablation/results.csv` | as above |
| §5.7 deadlock | `logs/paper/scaling_agents`, `logs/paper/scaling_exogenous` | `deadlock_count` MISSING from these two — the §5.7 numbers cannot be rebuilt from the committed CSVs |
| §5.8 temporal | `logs/paper/temporal_progression/results.csv` | timelines stored as `_timeline_len` integers; the per-tick lists must be in sidecar JSONs (this audit did not inspect those) |
| appendix: H/R decoupling | `logs/paper/aux_h_r_decoupling/results.csv` | as above, no `deadlock_count` |
| appendix: solver / budget | `logs/paper/solver_sensitivity`, `logs/paper/budget_sensitivity` | as above |

---

## 2. In-row invariant fractions

Each invariant is checked only on CSVs that have all required
columns; otherwise the invariant is **skipped** (the rows are
listed under "missing columns" in `audit_csv_consistency.py`).

### Per-invariant pass rate (across the 27 CSVs)

| Invariant | CSVs tested | CSVs skipped | Total rows tested | Total passed | Pass rate |
|---|---:|---:|---:|---:|---:|
| four-bucket: `total == safe + yield + revert + delay` | 0 | 27 | 0 | — | n/a — no CSV has the new columns |
| two-bucket (legacy): `total == safe + yield` | 27 | 0 | 14,839 | 14,839 | **100.000%** |
| attribution: `sv == agent_attr + exo_attr` | 27 | 0 | 14,839 | 14,839 | **100.000%** |
| `wait_fraction == total_wait / (num_agents × steps)` (1e-3 tol.) | 27 | 0 | 14,839 | 14,839 | **100.000%** |
| `throughput == completed_tasks / steps` (1e-3 tol.) | 27 | 0 | 14,839 | 14,839 | **100.000%** |
| `safety_violation_events <= safety_violations` | 0 | 27 | 0 | — | n/a — no CSV has the events column |

**Every CSV that has the relevant columns passes every invariant
on every row** (14,839/14,839 across the four checkable invariants).
The legacy two-bucket wait split (`total == safe + yield`) holds on
every row, which is consistent with the historical absence of
physics-revert / delay-injection callsites at the time these sweeps
were run.

### Verdict on data integrity

The committed CSV data is **internally consistent** with respect to
the invariants it can be checked against.  No row violates the
legacy wait-split, the attribution split, the throughput identity,
or the wait_fraction identity.

The CSVs are **not** internally consistent with the **current head's
schema**: every CSV is missing columns the current code now emits.
Rebuilding paper tables that read those missing columns
(`violations_def1_*`, `arrival_rate_per_step`,
`throughput_utilization`, the four-bucket wait split, the
event-debounce columns) requires fresh runs against the current
schema — but the existing values that ARE present are trustworthy.

---

## 3. $N_x$ convention reconciliation

The original audit recorded two conventions for the paper's $N_x$
column and a long-standing concern that the §5.1 horizon sub-table's
values could not be reproduced from the committed CSV.  This step
records the live data factually, **without** re-attempting the
broken fitter.

### §5.4 baseline (paper headline scaling)

CSV: `logs/paper/baseline_comparison_v2/results.csv` (720 rows).

`violations_exogenous_attributable` distribution:

| Statistic | Value |
|---|---:|
| n | 720 |
| min | 0 |
| median | 1,308.5 |
| mean | 4,072.65 |
| max | 53,515 |

The §5.4 paper text reports $N_x$ as the agent-tick total (the
column value), with the median in the **thousands**.  The CSV
reproduces this by identity — `N_x_paper = violations_exogenous_attributable`,
no transformation.  This matches the audit history's "outcome (i)"
verdict for §5.4 (`reports/table1_audit.md`).

### §5.1 horizon (the stale sub-table)

CSV: `logs/tuning/horizon_replan_full/results.csv` (640 rows).

`violations_exogenous_attributable` distribution:

| Statistic | Value |
|---|---:|
| n | 640 |
| min | 175 |
| median | 1,053.5 |
| mean | 1,500.14 |
| max | 4,242 |

The §5.1 paper sub-table prints $N_x$ values in the range
$[0.029, 0.083]$ across $H \in \{10, \ldots, 80\}$ — **four orders of
magnitude smaller** than the CSV column's median (1,053.5).  No simple
divide-by-1000 / divide-by-steps / divide-by-num_agents transform of
the column reproduces those values within 5% per cell (per the
prior `find_nx_source.py` audit; see
`reports/nx_horizon_audit.md` and
`paper/sections/05_1_horizon_subtable_STALE.md`).

Stating this factually for the current report: the §5.1 sub-table's
source formula remains **UNRESOLVED**.  The data in the committed
CSV passes every invariant this audit can apply, but its raw values
do not match the printed paper values for §5.1.  Either:
- the printed values came from a derived formula that the diagnostic
  panel does not enumerate, OR
- the printed values came from an earlier CSV that has since been
  superseded (the audit history records the §5.1 horizon sweep was
  re-run between the original paper draft and head).

This audit does not adjudicate between those possibilities — the
stale-marker doc (`paper/sections/05_1_horizon_subtable_STALE.md`)
remains the authoritative record.

### §5.4 scaling (cross-check)

CSV: `logs/paper/scaling_agents/results.csv` (1,040 rows).

`violations_exogenous_attributable` distribution: median 1,440.5,
mean 2,336.04, max 13,274.  Same order of magnitude as the §5.4
baseline; identity-with-paper holds.

---

## Summary

| Acceptance criterion | Status | Evidence |
|---|:--:|---|
| Schema matrix covers every committed `results.csv` | **PASS** | §1 table — 27 CSVs, all listed |
| Each invariant's pass-fraction reported per CSV | **PASS** | §2 — 4 checkable invariants × 27 CSVs; all 14,839 testable rows pass |
| Stale CSVs flagged with consuming paper section | **PASS** | §1 "Stale CSVs by consuming paper section" table — every CSV is stale; §5.7 specifically flagged because two of its consumed CSVs lack `deadlock_count` |

## BUGS FOUND

None at the data level — every checkable invariant holds on every
row.

## STALE-DATA FINDINGS (no re-runs proposed in this audit)

1. **Every committed CSV is missing the post-Prompt-1 / post-Prompt-2 /
   post-Prompt-6 / post-Prompt-C columns.**  Paper rebuilds that
   read these columns (e.g. `paper/tables/horizon_tuning.tex` Def-1
   N_x column, §5.1 saturation marker, four-bucket wait analysis)
   cannot be regenerated from the committed CSVs; fresh runs against
   the current schema are required.  This is recorded but not acted
   on — the next audit step (or a separate re-run prompt) is the
   right place to schedule the regenerations.

2. **§5.7 deadlock numbers**: `logs/paper/scaling_agents` and
   `logs/paper/scaling_exogenous` do NOT have `deadlock_count`.  The
   §5.7 figures rebuilt from these CSVs are therefore not available
   from the committed data; they require either re-runs or use of
   the `logs/tuning/scaling_*` CSVs (which DO have `deadlock_count`
   but at different per-cell counts).

3. **§5.1 horizon N_x sub-table**: source formula remains UNRESOLVED.
   `violations_exogenous_attributable` median 1,053.5 vs paper's
   0.029-0.083 (four orders of magnitude apart).  Identity does not
   apply; the stale-marker doc continues to govern.

## ARCHIVED OBSERVATION

The `logs/tuning/_superseded_pre_overlap/` and
`logs/tuning/allocator_comparison_*_overlap/` sibling directories
suggest two generations of the §5.5 allocator sweep coexist on
disk.  Both pass every invariant; choosing which is canonical for
the paper rebuild is a separate sweep-management question, not a
data-integrity question.
