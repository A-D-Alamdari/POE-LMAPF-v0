# Solver Recommendation (calibration output)

Generated from 2160 plan_with_metadata invocations across 6 solvers, 3 maps, 72 (solver, map, |M|) cells.

## Cohort summary — completion rate by solver (all cells)

| Solver | Completion rate | |M| range tested |
|---|---:|---|
| cbsh2 | 41.39% | 20–450 |
| lacam3 | 41.39% | 20–450 |
| lacam_official | 41.39% | 20–450 |
| lns2 | 41.67% | 20–450 |
| pbs | 41.39% | 20–450 |
| pibt2 | 34.17% | 20–450 |

## Per-section recommendation

| Section | Cohort | Threshold | Solvers included | Solvers excluded |
|---|---|---:|---|---|
| §5.2 (solver substitutability) | 36 cells | 95% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |
| §5.3 (FoV / safety grid) | 12 cells | 95% | cbsh2, lacam3, lacam_official, lns2, pbs | pibt2 |
| §5.4 (scaling (high density)) | 18 cells | 80% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |
| §5.5 (baselines) | 24 cells | 85% | _none_ | cbsh2, lacam3, lacam_official, lns2, pbs, pibt2 |

### §5.2 exclusions — justification

* **cbsh2**: completion=71.67% < 95% threshold (129/180 successful invocations on §5.2 cohort cells)
* **lacam3**: completion=71.67% < 95% threshold (129/180 successful invocations on §5.2 cohort cells)
* **lacam_official**: completion=71.67% < 95% threshold (129/180 successful invocations on §5.2 cohort cells)
* **lns2**: completion=71.67% < 95% threshold (129/180 successful invocations on §5.2 cohort cells)
* **pbs**: completion=71.67% < 95% threshold (129/180 successful invocations on §5.2 cohort cells)
* **pibt2**: completion=57.22% < 95% threshold (103/180 successful invocations on §5.2 cohort cells)

### §5.3 exclusions — justification

* **pibt2**: completion=83.33% < 95% threshold (50/60 successful invocations on §5.3 cohort cells)

### §5.4 exclusions — justification

* **cbsh2**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)
* **lacam3**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)
* **lacam_official**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)
* **lns2**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)
* **pbs**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)
* **pibt2**: completion=11.11% < 80% threshold (10/90 successful invocations on §5.4 cohort cells)

### §5.5 exclusions — justification

* **cbsh2**: completion=16.67% < 85% threshold (20/120 successful invocations on §5.5 cohort cells)
* **lacam3**: completion=16.67% < 85% threshold (20/120 successful invocations on §5.5 cohort cells)
* **lacam_official**: completion=16.67% < 85% threshold (20/120 successful invocations on §5.5 cohort cells)
* **lns2**: completion=17.50% < 85% threshold (21/120 successful invocations on §5.5 cohort cells)
* **pbs**: completion=16.67% < 85% threshold (20/120 successful invocations on §5.5 cohort cells)
* **pibt2**: completion=3.33% < 85% threshold (4/120 successful invocations on §5.5 cohort cells)

## Per-solver completion-rate matrix

### cbsh2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 57% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 10% | 0% | 0% |

### lacam3

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 57% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 10% | 0% | 0% |

### lacam_official

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 57% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 10% | 0% | 0% |

### lns2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 57% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 13% | 0% | 0% |

### pbs

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 100% | — | — | 57% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 10% | 0% | 0% |

### pibt2

| Map | 20 | 40 | 50 | 60 | 80 | 100 | 150 | 200 | 300 | 450 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random-64-64-10 | 100% | 83% | — | 57% | 33% | — | — | — | — | — |
| warehouse-10-20-10-2-1 | — | — | 67% | — | — | 3% | 0% | 0% | — | — |
| warehouse-10-20-10-2-2 | — | — | — | — | — | 57% | — | 10% | 0% | 0% |

## Per-solver `solver_wall_ms` p50 / p95 (ms)

### cbsh2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      1.0 |      2.2 |      4.1 |
| random-64-64-10 | 40 |      1.9 |      5.4 |      6.6 |
| random-64-64-10 | 60 |      4.7 |      7.3 |     10.7 |
| random-64-64-10 | 80 |      8.8 |     12.7 |     13.1 |
| warehouse-10-20-10-2-1 | 50 |     22.6 |     48.6 |     51.2 |
| warehouse-10-20-10-2-1 | 100 |    121.6 |   2051.3 |   3297.7 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     68.7 |     95.3 |    128.9 |
| warehouse-10-20-10-2-2 | 200 |    769.7 |   3225.4 |   3498.2 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lacam3

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |    105.0 |  10020.5 |  10031.0 |
| random-64-64-10 | 40 |     98.0 |  10017.8 |  10023.0 |
| random-64-64-10 | 60 |  10018.0 |  10024.0 |  10028.0 |
| random-64-64-10 | 80 |  10018.0 |  10029.9 |  10033.0 |
| warehouse-10-20-10-2-1 | 50 |  10017.0 |  10025.5 |  10027.0 |
| warehouse-10-20-10-2-1 | 100 |  10027.0 |  10036.8 |  10048.0 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |  10031.0 |  10042.0 |  10046.0 |
| warehouse-10-20-10-2-2 | 200 |  10034.0 |  10043.9 |  10045.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lacam_official

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      0.0 |      1.5 |      3.0 |
| random-64-64-10 | 40 |      1.0 |      1.0 |      1.0 |
| random-64-64-10 | 60 |      2.0 |      2.6 |      5.0 |
| random-64-64-10 | 80 |      2.0 |      3.0 |      3.0 |
| warehouse-10-20-10-2-1 | 50 |      2.0 |    107.8 |    125.0 |
| warehouse-10-20-10-2-1 | 100 |    380.0 |    865.0 |   1633.0 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |      6.0 |     13.8 |     17.0 |
| warehouse-10-20-10-2-2 | 200 |     15.0 |     15.0 |     15.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### lns2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      0.9 |      2.1 |      4.9 |
| random-64-64-10 | 40 |      1.8 |      3.4 |      4.5 |
| random-64-64-10 | 60 |      3.0 |      5.1 |      5.4 |
| random-64-64-10 | 80 |      3.4 |      4.7 |      4.8 |
| warehouse-10-20-10-2-1 | 50 |      3.8 |      9.9 |     13.2 |
| warehouse-10-20-10-2-1 | 100 |      7.2 |     30.8 |     32.4 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |      8.4 |     10.0 |     11.8 |
| warehouse-10-20-10-2-2 | 200 |     16.6 |     20.1 |     20.4 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### pbs

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      1.6 |      2.0 |      2.2 |
| random-64-64-10 | 40 |      3.4 |      4.7 |      5.0 |
| random-64-64-10 | 60 |      6.7 |      8.7 |      9.0 |
| random-64-64-10 | 80 |      9.9 |     15.2 |     16.2 |
| warehouse-10-20-10-2-1 | 50 |      8.5 |     12.8 |     13.7 |
| warehouse-10-20-10-2-1 | 100 |     26.6 |     49.0 |     70.4 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     25.6 |     32.4 |     42.7 |
| warehouse-10-20-10-2-2 | 200 |    104.3 |    131.8 |    134.9 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

### pibt2

| Map | |M| | p50 | p95 | max |
|---|---:|---:|---:|---:|
| random-64-64-10 | 20 |      1.0 |      3.5 |      5.0 |
| random-64-64-10 | 40 |      3.0 |      4.8 |      5.0 |
| random-64-64-10 | 60 |      5.0 |      7.2 |      8.0 |
| random-64-64-10 | 80 |      7.0 |      8.5 |      9.0 |
| warehouse-10-20-10-2-1 | 50 |      5.0 |      8.1 |      9.0 |
| warehouse-10-20-10-2-1 | 100 |     14.0 |     14.0 |     14.0 |
| warehouse-10-20-10-2-1 | 150 |        — |        — |        — |
| warehouse-10-20-10-2-1 | 200 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 100 |     26.0 |     33.0 |     37.0 |
| warehouse-10-20-10-2-2 | 200 |     46.0 |     46.9 |     47.0 |
| warehouse-10-20-10-2-2 | 300 |        — |        — |        — |
| warehouse-10-20-10-2-2 | 450 |        — |        — |        — |

## §5.1 budget recommendation

Current §5.1 per-replan budget is **5 s** (`SimConfig.solver_timeout_s`).

**INCONCLUSIVE** — LaCAM\* p95 at |M|=450 on warehouse-10-20-10-2-2 not measured (cell missing or all-error). Re-run calibration with that cell before deciding on §5.1 budget.

