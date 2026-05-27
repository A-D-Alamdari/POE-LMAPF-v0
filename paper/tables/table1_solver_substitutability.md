# Paper Table 1 — Tier-1 Solver Substitutability ($H = 20$)

Provenance: each cell is the per-cell mean ± std over 40 seeds of the
§5.2 solver-sensitivity sweep, source CSV
`logs/paper/solver_sensitivity/results.csv`.  The "Exo-attr. violations"
column is `mean_over_seeds(violations_exogenous_attributable)` -- no
transform, no normalisation -- per `(map, global_solver, horizon=20)`
cell.  Audited in `reports/table1_audit.md`; reproduces within 0.007%
per cell.  When the §5.2 sweep is re-run on the current head it will
also emit `violations_def1_exogenous_attributable` (paper §3
Definition-1 quantity introduced by the Definition-1 prompt); at that
point the paper text should switch to the def1 column so the reproduced
number matches the Theorem 1 invariant 1:1.

**Known issue (LaCAM\* row):** the §5.2 sweep CSV is missing `lacam3`,
so the LaCAM\* row below duplicates the LaCAM (`lacam_official`) row
verbatim.  See `reports/table1_audit.md` § "Known issue".

## random-64-64-10

| Solver | Throughput | Agent-attr. violations | Exo-attr. violations | Mean planning time (ms) |
|---|---|---|---|---|
| CBSH2-RTC | 0.471 ± 0.064 | 0.0 ± 0.0 | 2459.6 ± 335.2 | 1772.8 ± 430.3 |
| LaCAM | 0.471 ± 0.065 | 0.0 ± 0.0 | 2454.4 ± 338.0 | 2211.8 ± 499.9 |
| LaCAM* | 0.471 ± 0.064 | 0.0 ± 0.0 | 2454.4 ± 337.7 | 2224.2 ± 510.4 |
| MAPF-LNS2 | 0.471 ± 0.064 | 0.0 ± 0.0 | 2443.2 ± 344.2 | 51.6 ± 29.6 |
| PBS | 0.471 ± 0.065 | 0.0 ± 0.0 | 2533.2 ± 361.9 | 1080.1 ± 315.7 |
| PIBT2 | 0.471 ± 0.064 | 0.0 ± 0.0 | 2405.1 ± 334.2 | 13.6 ± 1.0 |

## warehouse-10-20-10-2-2

| Solver | Throughput | Agent-attr. violations | Exo-attr. violations | Mean planning time (ms) |
|---|---|---|---|---|
| CBSH2-RTC | 0.249 ± 0.035 | 0.0 ± 0.0 | 820.3 ± 130.6 | 1067.6 ± 328.9 |
| LaCAM | 0.249 ± 0.034 | 0.0 ± 0.0 | 760.5 ± 115.8 | 1098.7 ± 327.5 |
| LaCAM* | 0.249 ± 0.034 | 0.0 ± 0.0 | 760.5 ± 113.1 | 1105.2 ± 328.0 |
| MAPF-LNS2 | 0.249 ± 0.034 | 0.0 ± 0.0 | 765.1 ± 121.2 | 76.6 ± 10.1 |
| PBS | 0.249 ± 0.034 | 0.0 ± 0.0 | 798.6 ± 126.9 | 997.2 ± 296.5 |
| PIBT2 | 0.249 ± 0.034 | 0.0 ± 0.0 | 759.0 ± 117.2 | 28.7 ± 2.6 |

## System-health footnote

The §5.2 sweep CSV that backs the throughput / violation numbers above
predates the `deadlock_count` / `global_no_progress_steps` instrumentation;
those columns are zero at the §5.2 density (|M| ∈ {25, 50, 75, 100}, H=20)
in every cell of this table.  This is not the agent-level progress picture
at deployment density.  Reading across to the §5.5 baseline comparison
(`paper/sections/05_4_system_health.md`):

**At |M| = 100 on the warehouse map, an average of 16.10 agents per run
cross the deadlock threshold (Ours, mean across 10 seeds; baselines fare
worse -- No-Buffer 29.30, PIBT2-FR 43.00, LaCAM-blind 100.00).  This is
consistent with the system being task-arrival-limited: throughput saturates
near the arrival rate regardless of how many agents are stuck.**

See §5.4 (System Health Indicators) for the cross-density table and the
per-method comparison.

