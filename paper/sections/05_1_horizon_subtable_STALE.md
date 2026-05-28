# §5.1 Horizon-tuning Table 1 — N_x sub-table STALE

**Status: STALE.  Do not include this sub-table in the next paper
revision until its source is verified.  Source is currently
UNRESOLVED, not "deleted".**

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

The source formula that produced these values is **UNRESOLVED**.
A diagnostic
(`scripts/diagnostics/find_nx_source.py --paper-dataset horizon`)
tried a finite panel of candidate (column, transform) pairs and
named derived quantities; no candidate reproduced the 16 cells
within 5% per cell.  A finite candidate panel cannot enumerate
every possible formula, so this is **not** evidence that the
values came from a deleted source -- only that they are not
explained by the panel as currently configured.  See
`reports/nx_horizon_audit.md` (including its STATUS header) for
the audit history and the per-cell breakdowns.

## Why stale: source UNRESOLVED

**STATUS: source UNRESOLVED.**  An audit was attempted but the
diagnostic had a column-binding bug (see the STATUS block at the
top of `reports/nx_horizon_audit.md`).  The §5.1 N_x source is
**unknown** -- it was NOT shown to come from a deleted source,
and it was NOT shown to be unreproducible.  The question is
open.

The sub-table is held STALE because its source is unverified,
not because reproduction was ruled out.

For context, the §5.4 N_x column reproduces from the per-run
CSV via the identity transform on
`violations_exogenous_attributable` (audited in
`reports/table1_audit.md`, max rel err 0.007%).  The §5.1
values, in contrast, sit four orders of magnitude away from the
same CSV column (the CSV reports values in the thousands; the
paper reports 0.029 to 0.083), and no candidate in the current
diagnostic panel reproduces them within 5% per cell.  Neither
fact establishes that the §5.1 values came from a deleted
source -- a finite candidate panel cannot enumerate every
possible formula.

The earlier wording in this file (claiming the audit had
"exhausted every normalisation" and that the values "came from
a deleted source") was unsupported and is retracted.  Whoever resumes the project
should treat the §5.1 N_x source as an open question: either
locate the formula and add it to ``NAMED_DERIVED`` in
`scripts/diagnostics/find_nx_source.py`, or re-run the §5.1
horizon sweep against the current schema and recompute N_x from
``violations_def1_exogenous_attributable`` (the §5.4 audit's
identity formula).

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

### Rebuilt table available (Prompt B)

In parallel with the disposition options above,
`scripts/evaluation/build_table_horizon.py` now rebuilds the §5
horizon-tuning Table 1 from the per-run CSV.  The rebuilt
artifact lives at:

* `paper/tables/horizon_tuning.tex` (booktabs, with provenance
  comments mapping every column header to its source CSV
  column),
* `paper/tables/horizon_tuning.csv` (flat data, pandas-loadable).

Every saturated cell carries the standard `*` marker (per the
P10 convention in `paper/sections/05_1_load_regime.md`).  The
N_x column shows `--` because the committed horizon CSV
predates the P1 Def-1 columns; on the next re-run those cells
populate automatically.  The Local Replanning column now
correctly sources `local_replans` (the original mismatch with
`mean_service_time` is fixed).  See the "§5 horizon-tuning
Table 1 rebuild (Prompt B)" appendix at the bottom of
`reports/table1_audit.md` for the per-cell diff against the
old paper-text values.

### Narrative paragraph reconciliation

The paper's narrative paragraph beneath the old Table 1 quoted
``local_replans`` values of 19.5K (random) and 8.5K (warehouse)
at $H=10$.  Those numbers are correct; the table's "Number of
Local Replanning" column was the mismatch (it printed
`mean_service_time`).  After the Prompt B rebuild the narrative
and the table agree:

* H=10 random:     local_replans mean = 19,483 (cited as 19.5K).
* H=10 warehouse:  local_replans mean =  8,539 (cited as 8.5K).

If the narrative paragraph cited any throughput numbers as
planner-quality signals, those citations need the saturation
footnote from `paper/sections/05_1_load_regime.md`: at $|M|=100$
every (H, map) cell in the rebuilt table is arrival-saturated
(utilization $\ge 0.95$), so throughput in those cells measures
the task arrival cap $|M|/(H+W)$, not planner capacity.

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
