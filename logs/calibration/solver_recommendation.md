# Solver Recommendation (calibration output)

Generated from 2160 plan_with_metadata invocations across 6 solvers, 3 maps, 72 (solver, map, |M|) cells.

## Cohort summary — completion rate by solver (all cells)

| Solver | Completion rate | |M| range tested |
|---|---:|---|
| cbsh2 | 43.33% | 20–450 |
| lacam3 | 43.61% | 20–450 |
| lacam_official | 43.61% | 20–450 |
| lns2 | 43.61% | 20–450 |
| pbs | 43.61% | 20–450 |
| pibt2 | 38.89% | 20–450 |

## Per-section recommendation

| Section | Cohort | Threshold | Solvers included | Solvers excluded |
|---|---|---:|---|---|
| §5.2 (solver substitutability) | 36 cells | 95% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |
| §5.3 (FoV / safety grid) | 12 cells | 95% | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 | _none_ |
| §5.4 (scaling (high density)) | 18 cells | 80% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |
| §5.5 (baselines) | 24 cells | 85% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |

### §5.2 exclusions — justification

* **cbsh2**: completion=74.44% < 95% threshold (134/180 successful invocations on §5.2 cohort cells)
* **lacam3**: completion=74.44% < 95% threshold (134/180 successful invocations on §5.2 cohort cells)
* **lacam_official**: completion=74.44% < 95% threshold (134/180 successful invocations on §5.2 cohort cells)
* **lns2**: completion=74.44% < 95% threshold (134/180 successful invocations on §5.2 cohort cells)
* **pbs**: completion=74.44% < 95% threshold (134/180 successful invocations on §5.2 cohort cells)
* **pibt2**: completion=66.67% < 95% threshold (120/180 successful invocations on §5.2 cohort cells)

### §5.4 exclusions — justification

* **cbsh2**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)
* **lacam3**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)
* **lacam_official**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)
* **lns2**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)
* **pbs**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)
* **pibt2**: completion=10.00% < 80% threshold (9/90 successful invocations on §5.4 cohort cells)

### §5.5 exclusions — justification

* **cbsh2**: completion=18.33% < 85% threshold (22/120 successful invocations on §5.5 cohort cells)
* **lacam3**: completion=19.17% < 85% threshold (23/120 successful invocations on §5.5 cohort cells)
* **lacam_official**: completion=19.17% < 85% threshold (23/120 successful invocations on §5.5 cohort cells)
* **lns2**: completion=19.17% < 85% threshold (23/120 successful invocations on §5.5 cohort cells)
* **pbs**: completion=19.17% < 85% threshold (23/120 successful invocations on §5.5 cohort cells)
* **pibt2**: completion=7.50% < 85% threshold (9/120 successful invocations on §5.5 cohort cells)

## Per-solver completion-rate matrix

### cbsh2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 60% | 7% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

### lacam3

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 60% | 10% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

### lacam_official

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 60% | 10% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

### lns2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 60% | 10% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

### pbs

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 60% | 10% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

### pibt2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 90% | — | 67% | 30% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 90% | — | — | 23% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 60% | — | 7% | 0% | 0% |

## Per-solver `solver_wall_ms` p50 / p95 (ms)

### cbsh2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      0.7 |      1.6 |      2.0 |
| random-64-64-10 | 40 |      1.7 |      4.0 |      5.3 |
| random-64-64-10 | 60 |      4.6 |     10.4 |     11.8 |
| random-64-64-10 | 80 |      4.3 |     10.8 |     11.5 |
| warehouse-10-20-10-2-1 | 50 |     12.8 |     84.8 |    471.6 |
| warehouse-10-20-10-2-1 | 100 |    127.5 |   1111.2 |   1116.2 |
| warehouse-10-20-10-2-1 | 150 |    249.6 |    368.6 |    381.8 |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     46.8 |     84.8 |     85.9 |
| warehouse-10-20-10-2-2 | 200 |    936.8 |   1383.5 |   1433.1 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lacam3

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |     82.0 |  10008.6 |  10011.0 |
| random-64-64-10 | 40 |  10009.0 |  10015.4 |  10018.0 |
| random-64-64-10 | 60 |  10009.0 |  10023.0 |  10023.0 |
| random-64-64-10 | 80 |  10016.0 |  10018.0 |  10018.0 |
| warehouse-10-20-10-2-1 | 50 |  10011.5 |  10020.5 |  10021.0 |
| warehouse-10-20-10-2-1 | 100 |  10018.0 |  10025.3 |  10027.0 |
| warehouse-10-20-10-2-1 | 150 |  10021.0 |  10033.6 |  10035.0 |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |  10021.0 |  10025.3 |  10027.0 |
| warehouse-10-20-10-2-2 | 200 |  10022.5 |  10023.0 |  10023.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lacam_official

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      0.0 |      3.5 |      4.0 |
| random-64-64-10 | 40 |      1.0 |      4.7 |     10.0 |
| random-64-64-10 | 60 |      2.0 |      5.5 |     14.0 |
| random-64-64-10 | 80 |      2.0 |      4.6 |      5.0 |
| warehouse-10-20-10-2-1 | 50 |      2.0 |     28.2 |     55.0 |
| warehouse-10-20-10-2-1 | 100 |    301.0 |    766.5 |   1013.0 |
| warehouse-10-20-10-2-1 | 150 |   1271.0 |   2053.1 |   2140.0 |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |      6.5 |     14.1 |     15.0 |
| warehouse-10-20-10-2-2 | 200 |     17.5 |     21.5 |     22.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lns2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      0.7 |      0.9 |      1.2 |
| random-64-64-10 | 40 |      1.3 |      1.8 |      3.2 |
| random-64-64-10 | 60 |      1.9 |      2.4 |      2.5 |
| random-64-64-10 | 80 |      2.3 |      2.7 |      2.7 |
| warehouse-10-20-10-2-1 | 50 |      2.4 |      4.5 |      5.9 |
| warehouse-10-20-10-2-1 | 100 |      4.6 |     10.6 |     11.8 |
| warehouse-10-20-10-2-1 | 150 |     10.5 |     11.2 |     11.3 |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |      5.7 |      7.6 |      8.7 |
| warehouse-10-20-10-2-2 | 200 |     13.5 |     14.8 |     15.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### pbs

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      1.4 |      1.9 |      2.0 |
| random-64-64-10 | 40 |      2.9 |      4.0 |      4.2 |
| random-64-64-10 | 60 |      4.9 |      7.6 |      7.8 |
| random-64-64-10 | 80 |      8.9 |     13.6 |     14.7 |
| warehouse-10-20-10-2-1 | 50 |      6.8 |     12.6 |     14.7 |
| warehouse-10-20-10-2-1 | 100 |     22.4 |     55.2 |     75.1 |
| warehouse-10-20-10-2-1 | 150 |     35.9 |     60.4 |     63.1 |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     19.0 |     28.3 |     28.3 |
| warehouse-10-20-10-2-2 | 200 |     72.5 |     85.5 |     86.9 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### pibt2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      1.0 |      1.0 |      3.0 |
| random-64-64-10 | 40 |      3.0 |      4.7 |      8.0 |
| random-64-64-10 | 60 |      4.0 |      4.0 |      4.0 |
| random-64-64-10 | 80 |      6.0 |      8.6 |      9.0 |
| warehouse-10-20-10-2-1 | 50 |      4.0 |      7.7 |      8.0 |
| warehouse-10-20-10-2-1 | 100 |     10.0 |     13.1 |     14.0 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     15.0 |     23.7 |     28.0 |
| warehouse-10-20-10-2-2 | 200 |     32.0 |     36.5 |     37.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

## §5.1 budget recommendation

Current §5.1 per-replan budget is **5 s** (`SimConfig.solver_timeout_s`).

**INCONCLUSIVE** — LaCAM\* p95 at |M|=450 on warehouse-10-20-10-2-2 not measured (cell missing or all-error). Re-run calibration with that cell before deciding on §5.1 budget.

