# Paper claim validation report

**Confirmed**: 11 · **Refuted**: 7 · **Now stronger**: 0 · **Now weaker**: 7 · **Skipped**: 2

## Refuted (7)

| Section | Claim | Paper says | Actual | Verdict |
|---------|-------|------------|--------|---------|
| 5.3 | Exogenous-attributable violations at r_safe=0 are 5–8× higher than at r_safe=1 o… | [5.0, 8.0] | 0 | Refuted |
| 5.3 | Exogenous-attributable violations at r_safe=0 are 5–8× higher than at r_safe=1 o… | [5.0, 8.0] | 0 | Refuted |
| 5.4 | LaCAM and LaCAM* grow linearly to about 1 s per replan at the highest densities. | [700.0, 1300.0] | 10,854 | Refuted |
| 5.5 | No-Buffer produces 5–8× more exogenous-attributable violations than the full fra… | [5.0, 8.0] | 0 | Refuted |
| 5.5 | The framework's mean Tier-1 planning time matches RHCR's at the same H=20 (both … | 524.0 | 2,222 | Refuted |
| 5.5 | PIBT2-FR per-step compute is 50–80 ms at low |M|. | [50.0, 80.0] | 24.8 | Refuted |
| 5.5 | The framework's exogenous-attributable violations are 10–30× lower than RHCR's. | [10.0, 30.0] | 2.99 | Refuted |

### Suggested replacement sentences

* **viol_ratio_rsafe0_vs_rsafe1_random** (original):
  > Exogenous-attributable violations at r_safe=0 are 5–8× higher than at r_safe=1 on random-64-64-10.
  **Suggested:**
  > Exogenous-attributable violations at r_safe=0 are 0× higher than at r_safe=1 on random-64-64-10.

* **viol_ratio_rsafe0_vs_rsafe1_warehouse2** (original):
  > Exogenous-attributable violations at r_safe=0 are 5–8× higher than at r_safe=1 on warehouse-10-20-10-2-2.
  **Suggested:**
  > Exogenous-attributable violations at r_safe=0 are 0× higher than at r_safe=1 on warehouse-10-20-10-2-2.

* **lacam_grow_to_1s_at_high_density** (original):
  > LaCAM and LaCAM* grow linearly to about 1 s per replan at the highest densities.
  **Suggested:**
  > LaCAM and LaCAM* grow linearly to about 1 s per replan at the highest densities.  [actual: 10,854]

* **no_buffer_violations_5_to_8x_more** (original):
  > No-Buffer produces 5–8× more exogenous-attributable violations than the full framework.
  **Suggested:**
  > No-Buffer produces 0× more exogenous-attributable violations than the full framework.

* **ours_planning_time_matches_rhcr_524ms** (original):
  > The framework's mean Tier-1 planning time matches RHCR's at the same H=20 (both around 524 ms on warehouse at |M|=100).
  **Suggested:**
  > The framework's mean Tier-1 planning time matches RHCR's at the same H=20 (both around 2,222 ms on warehouse at |M|=100).

* **pibt2fr_perstep_50_80ms_low_M** (original):
  > PIBT2-FR per-step compute is 50–80 ms at low |M|.
  **Suggested:**
  > PIBT2-FR per-step compute is 24.8 ms at low |M|.

* **ours_violations_10_30x_lower_than_rhcr** (original):
  > The framework's exogenous-attributable violations are 10–30× lower than RHCR's.
  **Suggested:**
  > The framework's exogenous-attributable violations are 2.99× lower than RHCR's.


## Now weaker (7)

| Section | Claim | Paper says | Actual | Verdict |
|---------|-------|------------|--------|---------|
| 5.2 | LaCAM and LaCAM* scale below 600 ms per replan across the full sweep. | 600.0 | 7,181 | Now weaker |
| 5.4 | Throughput grows approximately linearly in |M| until map saturation. | 0.8 | 0.664 | Now weaker |
| 5.4 | PIBT2 stays under 100 ms per replan across all densities. | 100.0 | 174.9 | Now weaker |
| 5.5 | RHCR matches the framework throughput within 5% across the warehouse map up to |… | 0.05 | 1.00 | Now weaker |
| 5.5 | PIBT2-FR throughput degrades sharply above |M|=200 on the warehouse map. | 0.1 | 0 | Now weaker |
| 5.5 | No-Buffer ablation matches the framework throughput closely (within 3%). | 0.03 | 0.12 | Now weaker |
| 5.5 | PIBT2-FR per-step compute rises to over 2 s at |M|=450. | 2000.0 | 628.4 | Now weaker |

### Suggested replacement sentences

* **lacam_lacamstar_under_600ms** (original):
  > LaCAM and LaCAM* scale below 600 ms per replan across the full sweep.
  **Suggested:**
  > LaCAM and LaCAM* scale below 7,181 ms per replan across the full sweep.

* **throughput_linear_in_M** (original):
  > Throughput grows approximately linearly in |M| until map saturation.
  **Suggested:**
  > Throughput grows approximately linearly in |M| until map saturation.  [actual: 0.664]

* **pibt2_planning_under_100ms_all_densities** (original):
  > PIBT2 stays under 100 ms per replan across all densities.
  **Suggested:**
  > PIBT2 stays under 174.9 ms per replan across all densities.

* **rhcr_matches_ours_within_5pct_M_le_250** (original):
  > RHCR matches the framework throughput within 5% across the warehouse map up to |M|=250.
  **Suggested:**
  > RHCR matches the framework throughput within 5% across the warehouse map up to |M|=251.00.

* **pibt2fr_degrades_above_M200** (original):
  > PIBT2-FR throughput degrades sharply above |M|=200 on the warehouse map.
  **Suggested:**
  > PIBT2-FR throughput degrades sharply above |M|=200 on the warehouse map.

* **no_buffer_throughput_within_3pct** (original):
  > No-Buffer ablation matches the framework throughput closely (within 3%).
  **Suggested:**
  > No-Buffer ablation matches the framework throughput closely (within 3%).  [actual: 0.12]

* **pibt2fr_perstep_over_2s_M450** (original):
  > PIBT2-FR per-step compute rises to over 2 s at |M|=450.
  **Suggested:**
  > PIBT2-FR per-step compute rises to over 2 s at |M|=450.  [actual: 628.4]


## Now stronger (0)

_None._


## Confirmed (11)

| Section | Claim | Paper says | Actual | Verdict |
|---------|-------|------------|--------|---------|
| 5.2 | All six solvers fall within a 0.03 throughput range on random-64-64-10 at H=20. | 0.03 | 0.000175 | Confirmed |
| 5.2 | All six solvers fall within a 0.02 throughput range on warehouse-10-20-10-2-2 at… | 0.02 | 0.000475 | Confirmed |
| 5.2 | PIBT2 maintains under 80 ms per replan across all configurations. | 80.0 | 43.9 | Confirmed |
| 5.2 | MAPF-LNS2, PBS, and CBSH2-RTC reach the 10 s solver-time budget at high agent co… | 2700.0 | 4,915 | Confirmed |
| 5.3 | The default (r_fov=4, r_safe=1) sits on the throughput Pareto front (within 5% o… | 0.95 | 1.00 | Confirmed |
| 5.4 | MAPF-LNS2 grows super-linearly and approaches the 10 s budget at high agent coun… | 2500.0 | 3,056 | Confirmed |
| 5.4 | Exogenous-attributable violations grow approximately linearly in |X| on warehous… | 0.75 | 0.782 | Confirmed |
| 5.5 | RHCR violations grow super-linearly in |M|, exceeding 10^4 at |M|=450 on the war… | 10000.0 | 16,642 | Confirmed |
| 5.5 | The framework's exogenous-attributable violations are 3–5× lower than frequent-r… | [3.0, 5.0] | 3.22 | Confirmed |
| 5.5 | Across all 200+ configurations tested, the framework produces zero agent-attribu… | 0 | 0 | Confirmed |
| 5.5 | 200+ configurations tested across §5.2–§5.5. | 200 | 6,770 | Confirmed |

## Skipped (2)

| Section | Claim | Paper says | Actual | Verdict |
|---------|-------|------------|--------|---------|
| 5.5 | The framework outperforms RHCR by 8–12% at |M| in {350, 450} on the warehouse ma… | [0.08, 0.12] | nan | Skipped |
| 5.5 | PIBT2-FR achieves the highest raw throughput at low |M|. | pibt2_fr | None | Skipped |
