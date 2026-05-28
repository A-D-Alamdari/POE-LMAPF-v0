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

## Why stale (outcome (ii))

The §5.4 N_x column reproduces from the per-run CSV via the
identity transform on `violations_exogenous_attributable`
(audited in `reports/table1_audit.md`, max rel err 0.007%).  The
§5.1 N_x values, in contrast, sit four orders of magnitude away
from the same CSV column (the CSV reports values in the
thousands; the paper reports 0.029 to 0.083) and the candidate
panel exhausted every plausible per-tick, per-agent, per-human,
and per-replan normalisation of every numeric column.  Either:

* the §5.1 N_x values were typed by hand from a deleted or
  external source that is no longer reachable from the
  committed CSVs;
* OR the §5.1 N_x convention is a different formula than the
  §5.4 one and the formula was not preserved in the runtime
  schema (e.g. it was an interim metric that the
  WAIT-counterfactual rewrite in P5 / Definition-1 restore in
  P1 retired without a deprecation note).

The audit's outcome is recorded in `reports/nx_horizon_audit.md`
as **Outcome (ii) -- the paper N_x values do not reproduce from
any (column, transform) tuple in the candidate panel; they came
from a deleted / external source.**

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
