## Metric: `throughput`  vs. `priority`

| Condition | n | mean diff [95% CI] | Wilcoxon p (FDR) | Cohen's d | rank-biserial r | verdict |
|---|---|---|---|---|---|---|
| 150 / token | 10 | 0 [-0.0014, 0.0014] | 0.865 (0.865) | 0.00 | -0.07 | ns |
| 250 / token | 10 | -0.00193 [-0.0051, 0.0011] | 0.359 (0.797) | -0.36 | -0.33 | ns |
| 50 / token | 10 | 0.000467 [-0.00053, 0.0014] | 0.531 (0.797) | 0.29 | 0.25 | ns |

## Metric: `violations_exogenous_attributable`  vs. `priority`

| Condition | n | mean diff [95% CI] | Wilcoxon p (FDR) | Cohen's d | rank-biserial r | verdict |
|---|---|---|---|---|---|---|
| 150 / token | 10 | -13.2 [-1.7e+02, 1e+02] | 0.922 (0.922) | -0.06 | -0.05 | ns |
| 250 / token | 10 | 2.5 [-1.8e+02, 1.5e+02] | 0.922 (0.922) | 0.01 | -0.05 | ns |
| 50 / token | 10 | -17.1 [-85, 48] | 0.492 (0.922) | -0.15 | -0.27 | ns |

## Metric: `wait_fraction`  vs. `priority`

| Condition | n | mean diff [95% CI] | Wilcoxon p (FDR) | Cohen's d | rank-biserial r | verdict |
|---|---|---|---|---|---|---|
| 150 / token | 10 | -0.00224 [-0.0054, 0.0024] | 0.275 (0.413) | -0.34 | -0.42 | ns |
| 250 / token | 10 | -0.00131 [-0.0045, 0.001] | 0.695 (0.695) | -0.28 | -0.16 | ns |
| 50 / token | 10 | -0.00292 [-0.0058, -0.00028] | 0.131 (0.393) | -0.61 | -0.56 | ns |
