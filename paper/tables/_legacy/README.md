# Legacy paper-table archive

This directory captures pre-rebuild copies of paper-table files so a
diff against the regenerated version is auditable.

## What's not here

There was **no pre-existing horizon_tuning.tex in this code repo**
before Prompt B's `scripts/evaluation/build_table_horizon.py` was
introduced.  The §5.1 horizon-tuning Table 1 currently in the paper
lives in a separate paper-text repo; that repo's copy is what
Prompt B's diff appendix in `reports/table1_audit.md` references as
"old values".  Specifically, the "old" rows the paper currently
prints carry:

* **"Number of Local Replanning"** column showing
  `mean_service_time` values (60-150 step range), not
  `local_replans` (10^3-10^4 range).
* **"N_x"** column with values 0.029-0.083 whose source could not
  be reproduced from any (column, transform) tuple in the
  diagnostic panel (status: UNRESOLVED, see
  `paper/sections/05_1_horizon_subtable_STALE.md`).

The rebuilt table `paper/tables/horizon_tuning.tex` corrects both.
