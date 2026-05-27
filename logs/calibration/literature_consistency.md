# Literature consistency check

Measured `solver_wall_ms` vs published runtime claims at the most-comparable cell in our grid.

| Solver | Cell | Published claim | Source | Measured p50 (ms) | Measured p95 (ms) | Verdict |
|---|---|---|---|---:|---:|---|
| lacam_official | warehouse-10-20-10-2-2, |M|=200 | median ~1 s for 400 agents on 32×32 | Okumura 2023 (LaCAM), AAAI | 17.5 | 21.5 | Faster — verify parser reads correct field |
| lacam3 | warehouse-10-20-10-2-2, |M|=200 | 99% of MAPF benchmarks within 10 s up to 1000 agents | Okumura 2024 (LaCAM*), AAMAS | 10022.5 | 10023.0 | Slower — check end_to_end vs solver_wall gap |
| pibt2 | warehouse-10-20-10-2-1, |M|=200 | <200 ms for hundreds of agents on warehouse | Okumura et al. 2022, AIJ | — | — | Unmeasurable — cell not in grid or all-error |
| lns2 | warehouse-10-20-10-2-1, |M|=100 | sub-second initial solution at 100 agents | Li et al. 2022, IJCAI | 4.6 | 10.6 | Faster — verify parser reads correct field |
| cbsh2 | random-64-64-10, |M|=40 | optimal CBS variant; runtime varies widely with density | Li et al. 2021, ICAPS | 1.7 | 4.0 | Faster — verify parser reads correct field |
| pbs | random-64-64-10, |M|=40 | suboptimal, sub-second when feasible | Ma et al. 2019, AAAI | 2.9 | 4.0 | Faster — verify parser reads correct field |

### lacam_official — measured 0.0× faster than literature

Possible causes: (1) the parser is reading a sub-field instead of the total runtime (e.g. `comp_time_initial_solution` rather than `comp_time` in LaCAM\*'s result file); (2) the literature cell is harder than ours (different map / density); (3) the benchmark machine in the cited paper was slower than this CI host.

### lacam3 — measured 20.0× slower than literature

`end_to_end_wall_ms` p50 = 10090.1 ms; wrapper overhead (end_to_end − solver_wall) = 67.6 ms.  If overhead is >50% of solver_wall, the gap is subprocess-startup dominated.  Otherwise the binary itself is slower on this host.

### lns2 — measured 0.0× faster than literature

Possible causes: (1) the parser is reading a sub-field instead of the total runtime (e.g. `comp_time_initial_solution` rather than `comp_time` in LaCAM\*'s result file); (2) the literature cell is harder than ours (different map / density); (3) the benchmark machine in the cited paper was slower than this CI host.

### cbsh2 — measured 0.0× faster than literature

Possible causes: (1) the parser is reading a sub-field instead of the total runtime (e.g. `comp_time_initial_solution` rather than `comp_time` in LaCAM\*'s result file); (2) the literature cell is harder than ours (different map / density); (3) the benchmark machine in the cited paper was slower than this CI host.

### pbs — measured 0.0× faster than literature

Possible causes: (1) the parser is reading a sub-field instead of the total runtime (e.g. `comp_time_initial_solution` rather than `comp_time` in LaCAM\*'s result file); (2) the literature cell is harder than ours (different map / density); (3) the benchmark machine in the cited paper was slower than this CI host.

## Summary

* **Faster**: 4 solver(s)
* **Slower**: 1 solver(s)
* **Unmeasurable**: 1 solver(s)

> **WARNING**: ≥3 solvers diverge from literature.  This is a wrapper-overhead pattern worth investigating before relying on the calibration's numbers for §5.x decisions.

