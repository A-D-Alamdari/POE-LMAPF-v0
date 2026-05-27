# Three-way decomposition summary (§5.4 + §5.5)

Generated against commit: `b88c67d2a4234265a0eb061e031a80252e0df55a`

Sources:

* §5.4 simulator: `logs/calibration/raw_measurements_v2.csv`
* §5.5 simulator: `logs/calibration/raw_measurements_v2_5_5.csv`
* Stern bare (shared):    `logs/calibration/raw_measurements_benchmark.csv`
* §5.4 Stern + exogenous: `logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv`
* §5.5 Stern + exogenous: `logs/calibration/raw_measurements_benchmark_with_exo_5_5.csv`

Per-cohort detailed tables: see `allocator_vs_exogenous_decomposition_5_4.md` and `allocator_vs_exogenous_decomposition_5_5.md`.

## §5.4 cohort headline

Cells in decomposition (present in all three CSVs): **72**.

**Most extreme cell:**

Most extreme cell (largest total gap): **lacam3** on **warehouse-10-20-10-2-1** at \|M\|=200, \|X\|=40.

| Regime | Completion |
|---|---:|
| Stern bare (no exogenous) | 100% |
| Stern + 40 exogenous obstacles | 96% |
| Simulator-driven (lifelong) | 0% |
| **Exogenous-only contribution** | +4 pp |
| **Allocator + lifelong contribution** | +96 pp |
| Total gap | +100 pp |

**High-density aggregate (warehouse \|M\| ≥ 150):**

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

## §5.5 cohort headline

Cells in decomposition (present in all three CSVs): **48**.

**Most extreme cell:**

Most extreme cell (largest total gap): **lacam3** on **warehouse-10-20-10-2-2** at \|M\|=200, \|X\|=100.

| Regime | Completion |
|---|---:|
| Stern bare (no exogenous) | 100% |
| Stern + 100 exogenous obstacles | 100% |
| Simulator-driven (lifelong) | 0% |
| **Exogenous-only contribution** | +0 pp |
| **Allocator + lifelong contribution** | +100 pp |
| Total gap | +100 pp |

**High-density aggregate (warehouse \|M\| ≥ 150):**

| Metric | Value |
|---|---:|
| Cells aggregated | 18 (warehouse maps, \|M\| ≥ 150) |
| Mean Stern bare completion | 86% |
| Mean Stern + exogenous completion | 81% |
| Mean simulator-driven completion | 0% |
| Mean exogenous-only contribution | +4 pp |
| Mean allocator + lifelong-state contribution | +81 pp |
| Mean total gap | +86 pp |
| Allocator-vs-exogenous ratio | 19.3× |

## Cross-cohort comparison

| Metric | §5.4 (\|X\|=20/40/60) | §5.5 (\|X\|=20/100) | Δ (5.5 − 5.4) |
|---|---:|---:|---:|
| Mean exogenous-only Δ | +3 pp | +4 pp | +1 pp |
| Mean allocator + lifelong Δ | +67 pp | +81 pp | +14 pp |
| Mean total Δ | +70 pp | +86 pp | +15 pp |
| Allocator-vs-exogenous ratio | 21.9× | 19.3× | — |

## Single-sentence implications for paper prose

* **§5.4:** at high density the allocator + lifelong contribution (+67 pp) is 21.9× larger than the exogenous-as-obstacles contribution (+3 pp), identifying **conflict_aware task allocation under rolling-horizon execution** as the dominant source of difficulty in the cohort.
* **§5.5:** at high density the allocator + lifelong contribution (+81 pp) is 19.3× larger than the exogenous-as-obstacles contribution (+4 pp), identifying **conflict_aware task allocation under rolling-horizon execution** as the dominant source of difficulty in the cohort.
