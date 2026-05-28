# §5.1 Horizon-tuning Table 1 — N_x sub-table STALE

**Status: STALE.  Do not include this sub-table in the next paper
revision until a re-run against the post-Prompt-1 schema is
performed.**

## What is stale

The paper's §5.1 horizon-tuning Table 1 includes a column named
`N_x` with the following values across $|M|=100,\ |X|=50$ on the
two headline maps and $H \in \{10, 20, \ldots, 80\}$:

| $H$ | random-64-64-10 | warehouse-10-20-10-2-2 |
|---:|---:|---:|
| 10 | 0.029 | 0.033 |
| 20 | 0.040 | 0.044 |
| 30 | 0.046 | 0.050 |
| 40 | 0.052 | 0.057 |
| 50 | 0.061 | 0.058 |
| 60 | 0.064 | 0.063 |
| 70 | 0.072 | 0.066 |
| 80 | 0.083 | 0.067 |

None of these 16 cells reproduce from any (column, transform)
combination in the candidate-transform panel of
`scripts/diagnostics/find_nx_source.py --paper-dataset horizon`:
best fit max per-cell relative error is **21.035%**, more than 4x
the audit's 5% acceptance threshold.  Per-cell breakdown:
`reports/nx_horizon_audit.md`.

## Why stale (Outcome (ii), post-collapse-fix)

The §5.4 N_x column reproduces from the per-run CSV via the
identity transform on `violations_exogenous_attributable`
(audited in `reports/table1_audit.md`, max rel err 0.007%).  The
§5.1 N_x values, in contrast, sit four orders of magnitude away
from the same CSV column (the CSV reports values in the
thousands; the paper reports 0.029 to 0.083).

**Honest description of the search** (P14 follow-up).  An earlier
version of the diagnostic claimed to have "exhausted every
normalisation" but in fact had a column-dimension-collapse bug:
several transforms in the candidate panel ignored their column
argument and read named columns from the row directly
(e.g. `wait_fraction*0.60` read `wait_fraction` regardless of
which column was being iterated), so the cross-product over
numeric columns produced identical residuals for every
(column, transform) pair.  That bug was fixed in this commit by
splitting the search into two clearly separated panels:

* **Panel A** -- column × unary-transform grid.  Every transform
  uses its column argument; a runtime assertion
  (`assert_no_column_collapse`) raises if two distinct columns
  under the same transform tie to 1e-9, so the collapse cannot
  recur silently.  Best Panel A fit on the §5.1 horizon dataset:
  `wait_fraction` under `x/T * 1000` (i.e. ``wait_fraction *
  1000 / steps``) at **L2 = 0.0121, max per-cell rel err =
  32.16%**.
* **Panel B** -- named derived quantities, evaluated once per
  row, with the free-scaling constant
  `c = argmin_c L2(paper, c*q)`.  Best Panel B fit (shape match):
  ``(safe_wait_steps + yield_wait_steps)/(2*M*T)`` with
  **c = 1.1918, L2 = 0.0079, max per-cell rel err = 20.21%**.
  Tied with `wait_fraction` itself at c = 0.5959 (the two
  quantities are functionally proportional within the committed
  data, ``wait_fraction = total_wait/(M*T)``).

Both panels combined report a best max per-cell rel err of
**20.21%** -- still four times the 5% acceptance threshold and
the free-scaling constant 1.19 is far from any plausible
canonical value (e.g. it is not 1, 1/2, 1/H, or M/X).  The
diagnostic now honestly reports: "no (column, transform) tuple
in Panel A and no named-derived quantity (with free scaling) in
Panel B reproduces the §5.1 N_x values within 5% per cell."  The
shape that gets closest is some monotone-in-H function of the
wait-step counters, but it does not match in either constant or
extreme-cell residual.  See `reports/nx_horizon_audit.md` for the
sorted candidate table and per-cell breakdowns.

This rules out (with high confidence) that the §5.1 N_x came
from any present-day CSV column.  Either:

* the §5.1 N_x values were typed by hand from a deleted or
  external source that is no longer reachable from the
  committed CSVs;
* OR the formula uses a different combination of the wait-step
  counters that this panel does not include (e.g. a per-tick
  rolling average or a specific subset of agents).  Future
  audits that locate the formula should add it to
  ``NAMED_DERIVED`` in `scripts/diagnostics/find_nx_source.py`.

## Disposition

Until the §5.1 horizon sweep is re-run against the current schema
on a fresh checkout (which will populate
`violations_def1_exogenous_attributable` -- the Definition-1
quantity introduced by Prompt 1), the H-sweep N_x sub-table
**must not appear in the paper**.  Two acceptable resolutions:

1. **Re-run + replace** (preferred).  Re-launch the horizon sweep
   YAML (`configs/tuning/horizon_replan_full.yaml`) and recompute
   N_x from `violations_def1_exogenous_attributable` in the new
   CSV.  The §5.4 audit's identity formula
   (`mean_over_seeds(violations_def1_exogenous_attributable)`)
   then applies uniformly; the §5.1 / §5.4 conventions become
   identical and the sub-table can be restored.
2. **Single-point replacement**.  If the full H-sweep cannot be
   re-run in time, replace the sub-table with the
   `violations_def1_exogenous_attributable` value at $H = 40$
   only and a note: "the full H-sweep N_x sub-table is removed
   pending re-runs against the post-Prompt-1 schema; see
   `paper/sections/05_1_horizon_subtable_STALE.md`."

## Why this file is committed

The paper text lives in a separate repository; this file is the
code-repo-side marker that a paper editor must consult before
re-introducing the §5.1 N_x sub-table.  Removing this file before
the sub-table is re-derived from a fresh CSV silently re-opens
the verifiability hole the audit exists to close.

See also:

* `reports/nx_horizon_audit.md` -- diagnostic output, sorted
  candidates, top-three per-cell breakdown.
* `reports/table1_audit.md` -- the §5.4 audit (outcome (i)) and
  the cross-section convention divergence note.
* `scripts/diagnostics/find_nx_source.py` -- the fitter; rerun
  with `--paper-dataset horizon` after any change to the
  candidate-transform panel.
