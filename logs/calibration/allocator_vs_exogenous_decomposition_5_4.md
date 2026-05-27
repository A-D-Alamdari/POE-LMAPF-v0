# Allocator-vs-exogenous decomposition (§5.4 evidence)

Generated against commit: `b88c67d2a4234265a0eb061e031a80252e0df55a`

Sources:

* simulator-driven (per-map num_humans): `logs/calibration/raw_measurements_v2.csv` (648 rows, 72 cells)
* Stern bare: `logs/calibration/raw_measurements_benchmark.csv` (1800 rows, 72 cells)
* Stern + exogenous obstacles: `logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv` (1800 rows, 72 cells)

**Decomposition definition.**  For every (solver, map, \|M\|) cell present in all three CSVs:

* `exogenous_contribution = bench_bare − bench_exo` — the drop from adding \|X\| static obstacles drawn from the simulator's t=0 placement distribution.
* `allocator_lifelong_contribution = bench_exo − sim` — the additional drop from running the lifelong-MAPD pipeline (conflict_aware task allocator releasing tasks over time + exogenous agents moving + Tier-2 safety reactions).
* `total_gap = bench_bare − sim`. By construction `total_gap = exogenous_contribution + allocator_lifelong_contribution`.

Cells aggregated: **72** ((solver, map, \|M\|) keys present in all three CSVs).

## Headline three-way completion-rate table

Per-cell × per-solver, sorted by total gap descending.

| Solver | Map | \|M\| | \|X\| | Bare | +Exo | Sim | Exo Δ | Alloc Δ | Total Δ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| lacam3 | warehouse-10-20-10-2-1 | 200 | 40 | 100% | 96% | 0% | +4 pp | +96 pp | +100 pp |
| lacam3 | warehouse-10-20-10-2-2 | 200 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lacam3 | warehouse-10-20-10-2-2 | 300 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lacam3 | warehouse-10-20-10-2-2 | 450 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lacam_official | warehouse-10-20-10-2-2 | 200 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lacam_official | warehouse-10-20-10-2-2 | 300 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lacam_official | warehouse-10-20-10-2-2 | 450 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lns2 | warehouse-10-20-10-2-1 | 200 | 40 | 100% | 96% | 0% | +4 pp | +96 pp | +100 pp |
| lns2 | warehouse-10-20-10-2-2 | 200 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lns2 | warehouse-10-20-10-2-2 | 300 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| lns2 | warehouse-10-20-10-2-2 | 450 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| pbs | warehouse-10-20-10-2-1 | 200 | 40 | 100% | 96% | 0% | +4 pp | +96 pp | +100 pp |
| pbs | warehouse-10-20-10-2-2 | 200 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| pbs | warehouse-10-20-10-2-2 | 300 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| pbs | warehouse-10-20-10-2-2 | 450 | 60 | 100% | 28% | 0% | +72 pp | +28 pp | +100 pp |
| pibt2 | warehouse-10-20-10-2-2 | 200 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| pibt2 | warehouse-10-20-10-2-2 | 300 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| pibt2 | warehouse-10-20-10-2-2 | 450 | 60 | 100% | 100% | 0% | +0 pp | +100 pp | +100 pp |
| cbsh2 | random-64-64-10 | 80 | 20 | 100% | 96% | 33% | +4 pp | +63 pp | +67 pp |
| lacam3 | random-64-64-10 | 80 | 20 | 100% | 100% | 33% | +0 pp | +67 pp | +67 pp |
| lacam3 | warehouse-10-20-10-2-1 | 150 | 40 | 100% | 96% | 33% | +4 pp | +63 pp | +67 pp |
| lacam_official | random-64-64-10 | 80 | 20 | 100% | 100% | 33% | +0 pp | +67 pp | +67 pp |
| lacam_official | warehouse-10-20-10-2-1 | 150 | 40 | 100% | 92% | 33% | +8 pp | +59 pp | +67 pp |
| lns2 | random-64-64-10 | 80 | 20 | 100% | 100% | 33% | +0 pp | +67 pp | +67 pp |
| lns2 | warehouse-10-20-10-2-1 | 150 | 40 | 100% | 96% | 33% | +4 pp | +63 pp | +67 pp |
| pbs | random-64-64-10 | 80 | 20 | 100% | 100% | 33% | +0 pp | +67 pp | +67 pp |
| pbs | warehouse-10-20-10-2-1 | 150 | 40 | 100% | 96% | 33% | +4 pp | +63 pp | +67 pp |
| pibt2 | random-64-64-10 | 80 | 20 | 100% | 100% | 33% | +0 pp | +67 pp | +67 pp |
| cbsh2 | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| lacam3 | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| lacam_official | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| lns2 | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| pbs | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| pibt2 | random-64-64-10 | 60 | 20 | 100% | 100% | 44% | +0 pp | +56 pp | +56 pp |
| lacam_official | warehouse-10-20-10-2-1 | 200 | 40 | 48% | 56% | 0% | -8 pp | +56 pp | +48 pp |
| lacam3 | warehouse-10-20-10-2-1 | 100 | 40 | 100% | 92% | 56% | +8 pp | +36 pp | +44 pp |
| lacam_official | warehouse-10-20-10-2-1 | 100 | 40 | 100% | 88% | 56% | +12 pp | +32 pp | +44 pp |
| lns2 | warehouse-10-20-10-2-1 | 100 | 40 | 100% | 92% | 56% | +8 pp | +36 pp | +44 pp |
| pbs | warehouse-10-20-10-2-1 | 100 | 40 | 100% | 92% | 56% | +8 pp | +36 pp | +44 pp |
| cbsh2 | warehouse-10-20-10-2-2 | 200 | 60 | 40% | 32% | 0% | +8 pp | +32 pp | +40 pp |
| cbsh2 | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| cbsh2 | random-64-64-10 | 40 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| cbsh2 | warehouse-10-20-10-2-1 | 50 | 40 | 100% | 92% | 67% | +8 pp | +25 pp | +33 pp |
| lacam3 | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lacam3 | random-64-64-10 | 40 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lacam3 | warehouse-10-20-10-2-1 | 50 | 40 | 100% | 92% | 67% | +8 pp | +25 pp | +33 pp |
| lacam_official | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lacam_official | random-64-64-10 | 40 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lacam_official | warehouse-10-20-10-2-1 | 50 | 40 | 100% | 92% | 67% | +8 pp | +25 pp | +33 pp |
| lns2 | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lns2 | random-64-64-10 | 40 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| lns2 | warehouse-10-20-10-2-1 | 50 | 40 | 100% | 92% | 67% | +8 pp | +25 pp | +33 pp |
| pbs | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| pbs | random-64-64-10 | 40 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| pbs | warehouse-10-20-10-2-1 | 50 | 40 | 100% | 92% | 67% | +8 pp | +25 pp | +33 pp |
| pibt2 | random-64-64-10 | 20 | 20 | 100% | 100% | 67% | +0 pp | +33 pp | +33 pp |
| pibt2 | random-64-64-10 | 40 | 20 | 100% | 96% | 67% | +4 pp | +29 pp | +33 pp |
| cbsh2 | warehouse-10-20-10-2-1 | 100 | 40 | 84% | 44% | 56% | +40 pp | -12 pp | +28 pp |
| pibt2 | warehouse-10-20-10-2-1 | 50 | 40 | 72% | 68% | 67% | +4 pp | +1 pp | +5 pp |
| cbsh2 | warehouse-10-20-10-2-1 | 200 | 40 | 0% | 0% | 0% | +0 pp | +0 pp | +0 pp |
| cbsh2 | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| cbsh2 | warehouse-10-20-10-2-2 | 300 | 60 | 0% | 0% | 0% | +0 pp | +0 pp | +0 pp |
| cbsh2 | warehouse-10-20-10-2-2 | 450 | 60 | 0% | 0% | 0% | +0 pp | +0 pp | +0 pp |
| lacam3 | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| lacam_official | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| lns2 | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| pbs | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| pibt2 | warehouse-10-20-10-2-1 | 200 | 40 | 0% | 4% | 0% | -4 pp | +4 pp | +0 pp |
| pibt2 | warehouse-10-20-10-2-2 | 100 | 60 | 100% | 100% | 100% | +0 pp | +0 pp | +0 pp |
| pibt2 | warehouse-10-20-10-2-1 | 100 | 40 | 28% | 32% | 44% | -4 pp | -12 pp | -16 pp |
| pibt2 | warehouse-10-20-10-2-1 | 150 | 40 | 4% | 16% | 22% | -12 pp | -6 pp | -18 pp |
| cbsh2 | warehouse-10-20-10-2-1 | 150 | 40 | 4% | 0% | 33% | +4 pp | -33 pp | -29 pp |

## Per-solver aggregate

| Solver | Cells | Mean Bare | Mean +Exo | Mean Sim | Mean Exo Δ | Mean Alloc Δ | Mean Total Δ | Alloc/Exo ratio |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| cbsh2 | 12 | 61% | 55% | 39% | +5 pp | +16 pp | +22 pp | 3.1× |
| lacam3 | 12 | 100% | 98% | 39% | +2 pp | +59 pp | +61 pp | 29.6× |
| lacam_official | 12 | 96% | 94% | 39% | +2 pp | +55 pp | +57 pp | 33.1× |
| lns2 | 12 | 100% | 98% | 39% | +2 pp | +59 pp | +61 pp | 29.6× |
| pbs | 12 | 100% | 92% | 39% | +8 pp | +53 pp | +61 pp | 6.6× |
| pibt2 | 12 | 75% | 76% | 37% | -1 pp | +39 pp | +38 pp | -39.3× |

## Most extreme cell

Most extreme cell (largest total gap): **lacam3** on **warehouse-10-20-10-2-1** at \|M\|=200, \|X\|=40.

| Regime | Completion |
|---|---:|
| Stern bare (no exogenous) | 100% |
| Stern + 40 exogenous obstacles | 96% |
| Simulator-driven (lifelong) | 0% |
| **Exogenous-only contribution** | +4 pp |
| **Allocator + lifelong contribution** | +96 pp |
| Total gap | +100 pp |

## High-density aggregate (warehouse \|M\| ≥ 150)

| Metric | Value |
|---|---:|
| Cells aggregated | 30 (warehouse maps, \|M\| ≥ 150) |
| Mean Stern bare completion | 77% |
| Mean Stern + exogenous completion | 73% |
| Mean simulator-driven completion | 6% |
| Mean exogenous-only contribution | +3 pp |
| Mean allocator + lifelong-state contribution | +67 pp |
| Mean total gap | +70 pp |
| Allocator-vs-exogenous ratio | 21.9× |

## Implication for §5.4 prose

Of the 100-pp gap between Stern benchmark completion (100%) and simulator-driven completion (0%) at the most extreme cell (lacam3 on warehouse-10-20-10-2-1, \|M\|=200, \|X\|=40), 4 pp is attributable to exogenous-agent obstacles and 96 pp to conflict_aware task allocation under rolling-horizon execution.  Across all 30 high-density warehouse cells (\|M\| ≥ 150), the mean allocator-driven contribution (67 pp) is 21.9× larger than the mean exogenous-driven contribution (3 pp), identifying **task allocation under rolling-horizon execution** as the dominant source of difficulty in our lifelong-MAPD setting.

## Anomalies and caveats

### Negative exogenous contribution (Stern + obstacles OUTPERFORMS Stern bare): 2 cells

* lacam_official / warehouse-10-20-10-2-1 / |M|=200: bare=48%, +exo=56% (-8 pp)
* pibt2 / warehouse-10-20-10-2-1 / |M|=150: bare=4%, +exo=16% (-12 pp)

### Negative allocator contribution (simulator OUTPERFORMS Stern + obstacles): 4 cells

* cbsh2 / warehouse-10-20-10-2-1 / |M|=100: +exo=44%, sim=56% (-12 pp)
* cbsh2 / warehouse-10-20-10-2-1 / |M|=150: +exo=0%, sim=33% (-33 pp)
* pibt2 / warehouse-10-20-10-2-1 / |M|=100: +exo=32%, sim=44% (-12 pp)
* pibt2 / warehouse-10-20-10-2-1 / |M|=150: +exo=16%, sim=22% (-6 pp)


