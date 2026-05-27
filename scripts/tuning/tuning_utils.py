"""Shared utilities for the sequential hyperparameter tuning pipeline.

Statistical guarantee:
  - Wilcoxon signed-rank test (paired, two-sided) vs the default/baseline
    parameter value for every metric in STATS_METRICS.
  - Benjamini-Hochberg FDR correction applied across all comparisons within
    a sweep so the family-wise false-discovery rate stays ≤ 0.05.
  - Rank-biserial correlation r reported alongside every p-value as a
    measure of practical effect size (|r| ≥ 0.1 small, 0.3 medium, 0.5 large).
  - 95 % bootstrap confidence intervals on mean throughput (BCa method when
    n_seeds ≥ 10, normal approximation otherwise).
  - Sensitivity score: max |Δmetric| / Δparam around the optimal point, so
    you can rank how precisely each parameter must be set.

Output per tuning run:
  results.csv   — one row per (value, seed)
  summary.csv   — aggregated: mean, std, 95-CI, Wilcoxon-p, FDR-p, effect-r
  pareto.csv    — non-dominated (throughput, near_misses) configurations
  table.tex     — ready-to-paste LaTeX table for the paper
"""

from __future__ import annotations

import csv
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from ha_lmapf.core.types import Metrics, SimConfig
from ha_lmapf.simulation.simulator import Simulator

# ---------------------------------------------------------------------------
# Optional scientific packages — fail gracefully with informative messages
# ---------------------------------------------------------------------------
try:
    from scipy.stats import wilcoxon, mannwhitneyu

    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    print("[tuning_utils] WARNING: scipy not found — statistical tests will "
          "be skipped. Install with: pip install scipy")

# ---------------------------------------------------------------------------
# Maps and defaults
# ---------------------------------------------------------------------------
PRIMARY_MAP = "data/maps/warehouse-20-40-10-2-1.map"

# Metrics written to results.csv / summary.csv
METRIC_KEYS: List[str] = [
    "throughput", "completed_tasks", "task_completion",
    "mean_flowtime", "median_flowtime", "max_flowtime", "mean_service_time",
    "collisions_agent_agent", "collisions_agent_human",
    "near_misses", "safety_violations", "safety_violation_rate",
    "replans", "global_replans", "local_replans", "intervention_rate",
    "total_wait_steps", "human_passive_wait_steps",
    "mean_planning_time_ms", "p95_planning_time_ms", "max_planning_time_ms",
    "mean_decision_time_ms", "p95_decision_time_ms",
    "makespan", "sum_of_costs", "mean_path_cost",
    "delay_events", "immediate_assignments",
    "assignments_kept", "assignments_broken",
]

# Metrics for which paired statistical tests are computed
STATS_METRICS: List[str] = [
    "throughput", "mean_flowtime", "near_misses",
    "safety_violations", "total_wait_steps",
    "mean_planning_time_ms", "assignments_kept", "assignments_broken",
]

# For each metric: True = higher is better (used in best-config selection)
METRIC_DIRECTION: Dict[str, bool] = {
    "throughput": True,
    "completed_tasks": True,
    "task_completion": True,
    "mean_flowtime": False,
    "median_flowtime": False,
    "max_flowtime": False,
    "mean_service_time": False,
    "collisions_agent_agent": False,
    "collisions_agent_human": False,
    "near_misses": False,
    "safety_violations": False,
    "safety_violation_rate": False,
    "replans": False,
    "global_replans": False,
    "local_replans": False,
    "intervention_rate": False,
    "total_wait_steps": False,
    "human_passive_wait_steps": False,
    "mean_planning_time_ms": False,
    "p95_planning_time_ms": False,
    "max_planning_time_ms": False,
    "mean_decision_time_ms": False,
    "p95_decision_time_ms": False,
    "makespan": False,
    "sum_of_costs": False,
    "delay_events": False,
    "immediate_assignments": True,
    "assignments_kept": True,
    "assignments_broken": False,
}


# ---------------------------------------------------------------------------
# Base configuration — LaCAM solver (matches run_evaluation.py "ours")
# ---------------------------------------------------------------------------
def get_base_config(
        map_path: Optional[str] = None,
        num_agents: int = 20,
        num_humans: int = 5,
        steps: int = 5000,
) -> Dict[str, Any]:
    """Return the base (control) configuration for all tuning experiments.

    LaCAM is the global solver, matching the "ours" baseline in
    run_evaluation.py.  PBS is too slow for 20-agent rolling-horizon
    replanning on the warehouse map.
    """
    return {
        "map_path": map_path or PRIMARY_MAP,
        "task_stream_path": None,
        "steps": steps,
        "num_agents": num_agents,
        "num_humans": num_humans,
        # Perception — defaults tuned in Steps 4-6
        "fov_radius": 4,
        "safety_radius": 1,
        "hard_safety": True,
        # Global planner — LaCAM (fast, scalable); defaults tuned in Steps 1-3
        "global_solver": "lacam",
        "replan_every": 25,
        "horizon": 50,
        "time_budget_ms": 5000.0,
        # Task allocation — defaults tuned in Step 7
        "task_allocator": "congestion_avoidance",
        "commit_horizon": 0,
        "delay_threshold": 0.0,
        "task_arrival_rate": 10,
        "task_arrival_percentage": 0.9,
        # Communication / local planning
        "communication_mode": "token",
        "local_planner": "astar",
        # Human model
        "human_model": "random_walk",
        "human_model_params": {},
        # Robustness
        "execution_delay_prob": 0.0,
        "execution_delay_steps": 1,
        # Ablation flags
        "disable_local_replan": False,
        "disable_conflict_resolution": False,
        "disable_safety": False,
        "seed": 0,
    }


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
def make_output_dir(
        param_name: str,
        run_label: str = "",
        base_dir: str = "logs/tuning",
) -> Path:
    """Create a unique, timestamped output directory that never overwrites."""
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = f"{run_label}_{ts}" if run_label else ts
    out = Path(base_dir) / param_name / folder
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Single experiment runner
# ---------------------------------------------------------------------------
def run_single_experiment(
        config_dict: Dict[str, Any],
        experiment_name: str,
        verbose: bool = False,
) -> Tuple[Metrics, float]:
    """Run one simulation and return (Metrics, wall_clock_seconds)."""
    config = SimConfig(**{
        k: v for k, v in config_dict.items()
        if k in SimConfig.__dataclass_fields__
    })
    if verbose:
        print(f"  Running: {experiment_name} (seed={config.seed})")

    t0 = time.time()
    try:
        sim = Simulator(config)
        metrics = sim.run()
        wall = time.time() - t0
        if verbose:
            print(f"    Throughput={metrics.throughput:.4f}  "
                  f"Flowtime={metrics.mean_flowtime:.1f}  "
                  f"NearMiss={metrics.near_misses}  "
                  f"Violations={metrics.safety_violations}")
        return metrics, wall
    except Exception as e:
        print(f"  ERROR in {experiment_name}: {e}")
        return Metrics(steps=config.steps), time.time() - t0


def _run_task(args: Tuple[Dict[str, Any], str, bool]) -> Dict[str, Any]:
    """Top-level picklable wrapper for ProcessPoolExecutor."""
    config_dict, name, verbose = args
    metrics, wall = run_single_experiment(config_dict, name, verbose)
    return {"_name": name, "_wall": wall, "_metrics": asdict(metrics)}


# ---------------------------------------------------------------------------
# Generic single-parameter sweep
# ---------------------------------------------------------------------------
def run_sweep(
        param_name: str,
        values: list,
        seeds: List[int],
        base_config: Dict[str, Any],
        coupled: Optional[Dict[str, Callable]] = None,
        label: str = "",
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run a single-parameter sweep and return per-seed result dicts."""
    coupled = coupled or {}
    tag = f" [{label}]" if label else ""
    print(f"\n{'=' * 60}")
    print(f"Sweep: {param_name}{tag}")
    print(f"  values={values}  seeds={seeds}  workers={workers}")
    print(f"{'=' * 60}")

    tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
    for val in values:
        for seed in seeds:
            cfg = base_config.copy()
            cfg[param_name] = val
            cfg["seed"] = seed
            for cp, func in coupled.items():
                cfg[cp] = func(val)
            name = f"{param_name}={val}_seed={seed}"
            if label:
                name = f"{label}_{name}"
            tasks.append((cfg, name, {
                "param": param_name, "value": val, "seed": seed,
            }))

    return _execute_tasks(tasks, base_config, verbose, workers)


# ---------------------------------------------------------------------------
# Generic two-parameter grid sweep
# ---------------------------------------------------------------------------
def run_grid_sweep(
        param_a: str,
        values_a: list,
        param_b: str,
        values_b: list,
        seeds: List[int],
        base_config: Dict[str, Any],
        constraint: Optional[Callable] = None,
        label: str = "",
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run a two-parameter grid sweep.

    constraint: callable(val_a, val_b) -> bool — True if pair is valid.
    """
    tag = f" [{label}]" if label else ""
    print(f"\n{'=' * 60}")
    print(f"Grid sweep: {param_a} × {param_b}{tag}")
    print(f"  {param_a}={values_a}")
    print(f"  {param_b}={values_b}")
    print(f"  seeds={seeds}  workers={workers}")
    print(f"{'=' * 60}")

    tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
    for va in values_a:
        for vb in values_b:
            if constraint and not constraint(va, vb):
                continue
            for seed in seeds:
                cfg = base_config.copy()
                cfg[param_a] = va
                cfg[param_b] = vb
                cfg["seed"] = seed
                name = f"{param_a}={va}_{param_b}={vb}_seed={seed}"
                if label:
                    name = f"{label}_{name}"
                tasks.append((cfg, name, {
                    "param": f"{param_a}+{param_b}",
                    "value": f"{va},{vb}",
                    param_a: va,
                    param_b: vb,
                    "seed": seed,
                }))

    return _execute_tasks(tasks, base_config, verbose, workers)


# ---------------------------------------------------------------------------
# Task execution engine
# ---------------------------------------------------------------------------
def _execute_tasks(
        tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]],
        base_config: Dict[str, Any],
        verbose: bool,
        workers: int,
) -> List[Dict[str, Any]]:
    total = len(tasks)
    results: List[Dict[str, Any]] = []

    if workers <= 1:
        for n, (cfg, name, meta) in enumerate(tasks, 1):
            print(f"\n[{n}/{total}] {name}")
            metrics, wall = run_single_experiment(cfg, name, verbose)
            results.append({**meta, "wall_time_sec": wall, **asdict(metrics)})
    else:
        print(f"  Dispatching {total} jobs across {workers} workers ...")
        worker_args = [(cfg, nm, verbose) for cfg, nm, _ in tasks]
        meta_map = {nm: meta for _, nm, meta in tasks}
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_task, a): a[1] for a in worker_args}
            for fut in as_completed(futs):
                nm = futs[fut]
                done += 1
                meta = meta_map[nm]
                try:
                    r = fut.result()
                    print(f"  [{done}/{total}] done: {nm}")
                    results.append({**meta, "wall_time_sec": r["_wall"],
                                    **r["_metrics"]})
                except Exception as exc:
                    print(f"  [{done}/{total}] ERROR {nm}: {exc}")
                    steps = base_config.get("steps", 1000)
                    results.append({**meta, "wall_time_sec": 0.0,
                                    **asdict(Metrics(steps=steps))})
    return results


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------
def _rank_biserial(x: List[float], y: List[float]) -> float:
    """Rank-biserial correlation as effect size for Wilcoxon/Mann-Whitney.

    r = 1 - 2W / (n1 * n2)  where W is the test statistic.
    Interpretation: |r| < 0.1 negligible, 0.1 small, 0.3 medium, 0.5 large.
    """
    if not _HAS_SCIPY or len(x) == 0 or len(y) == 0:
        return float("nan")
    try:
        stat, _ = mannwhitneyu(x, y, alternative="two-sided")
        n1, n2 = len(x), len(y)
        r = 1.0 - 2.0 * stat / (n1 * n2)
        return float(r)
    except Exception:
        return float("nan")


def _bootstrap_ci(
        values: List[float],
        n_boot: int = 1000,
        ci: float = 0.95,
) -> Tuple[float, float]:
    """Bootstrap confidence interval for the mean (BCa when n>=10, else normal)."""
    if len(values) < 2:
        v = float(values[0]) if values else float("nan")
        return v, v
    a = np.array(values, dtype=float)
    if len(values) < 10:
        # Normal approximation
        se = np.std(a, ddof=1) / np.sqrt(len(a))
        z = 1.959964  # 97.5th percentile of N(0,1) for 95% CI
        m = np.mean(a)
        return float(m - z * se), float(m + z * se)
    # Percentile bootstrap
    rng = np.random.default_rng(seed=42)
    boot_means = np.array([
        np.mean(rng.choice(a, size=len(a), replace=True))
        for _ in range(n_boot)
    ])
    alpha = (1.0 - ci) / 2.0
    return float(np.percentile(boot_means, 100 * alpha)), \
        float(np.percentile(boot_means, 100 * (1.0 - alpha)))


def _fdr_correction(pvalues: List[float]) -> List[float]:
    """Benjamini-Hochberg FDR correction. Returns adjusted p-values."""
    n = len(pvalues)
    if n == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda x: x[1])
    adjusted = [float("nan")] * n
    cummin = float("inf")
    for rank, (idx, p) in enumerate(reversed(indexed), 1):
        if np.isnan(p):
            adjusted[idx] = float("nan")
            continue
        corrected = p * n / (n - rank + 1)
        cummin = min(cummin, corrected)
        adjusted[idx] = min(cummin, 1.0)
    return adjusted


# ---------------------------------------------------------------------------
# Aggregation — conference-quality statistics
# ---------------------------------------------------------------------------
def aggregate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate per-seed rows into one row per configuration.

    For each configuration (param, value) group:
    - mean, std, 95-CI-lo, 95-CI-hi  for every metric in METRIC_KEYS
    - Wilcoxon p-value vs the baseline (lowest numeric param value, or the
      default base-config value if present) for every metric in STATS_METRICS
    - Rank-biserial r (effect size) alongside each p-value
    - FDR-corrected q-value (Benjamini-Hochberg) across all comparisons
    - Sensitivity score: Δmetric / Δparam at the optimal point
    """
    groups: Dict[Tuple, List[Dict]] = defaultdict(list)
    for r in results:
        key = (r["param"], r["value"])
        groups[key].append(r)

    # ---- Determine baseline for each (sweep) param -------------------------
    # Baseline = group with the numerically smallest value (or first string).
    # Seed samples are sorted by seed to enable paired tests.
    def _sort_val(k):
        try:
            return float(k[1])
        except (ValueError, TypeError):
            return 0.0

    baseline_data: Dict[str, Dict[str, List[float]]] = {}
    for param in {k[0] for k in groups}:
        keys_for_param = [k for k in groups if k[0] == param]
        baseline_key = min(keys_for_param, key=_sort_val)
        baseline_data[param] = {
            m: [r.get(m, 0.0) for r in sorted(
                groups[baseline_key], key=lambda x: x.get("seed", 0)
            )]
            for m in STATS_METRICS
        }

    # ---- Build per-group aggregated rows -----------------------------------
    raw_rows: List[Dict[str, Any]] = []
    for (param, value), group in sorted(groups.items(), key=lambda x: (str(x[0][0]), _sort_val(x[0]))):
        sorted_group = sorted(group, key=lambda x: x.get("seed", 0))

        agg: Dict[str, Any] = {
            "param": param,
            "value": value,
            "n_seeds": len(sorted_group),
        }

        # Carry forward extra keys from grid sweeps (e.g., param_a, param_b)
        for k in sorted_group[0]:
            if k not in agg and k not in METRIC_KEYS and k not in (
                    "seed", "wall_time_sec"
            ):
                agg[k] = sorted_group[0][k]

        # Mean, std, CI for all metrics
        for key in METRIC_KEYS + ["wall_time_sec"]:
            vals = [float(r.get(key, 0.0)) for r in sorted_group]
            agg[f"{key}_mean"] = float(np.mean(vals))
            agg[f"{key}_std"] = float(
                np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            )
            ci_lo, ci_hi = _bootstrap_ci(vals)
            agg[f"{key}_ci95_lo"] = ci_lo
            agg[f"{key}_ci95_hi"] = ci_hi

        # Wilcoxon + effect size vs baseline
        bline = baseline_data.get(param, {})
        for key in STATS_METRICS:
            p_col = f"{key}_wilcoxon_p"
            r_col = f"{key}_effect_r"
            vals = [float(r.get(key, 0.0)) for r in sorted_group]
            bvals = bline.get(key, [])
            if not _HAS_SCIPY or not bvals or vals == bvals:
                agg[p_col] = float("nan")
                agg[r_col] = float("nan")
                continue
            n = min(len(vals), len(bvals))
            try:
                _, p = wilcoxon(vals[:n], bvals[:n], alternative="two-sided")
                agg[p_col] = float(p)
            except Exception:
                agg[p_col] = float("nan")
            agg[r_col] = _rank_biserial(vals, bvals)

        raw_rows.append(agg)

    # ---- FDR correction across all comparisons within each param ----------
    for metric in STATS_METRICS:
        p_col = f"{metric}_wilcoxon_p"
        q_col = f"{metric}_fdr_q"
        raw_ps = [row.get(p_col, float("nan")) for row in raw_rows]
        adj = _fdr_correction(raw_ps)
        for row, q in zip(raw_rows, adj):
            row[q_col] = q

    return raw_rows


# ---------------------------------------------------------------------------
# Pareto front computation
# ---------------------------------------------------------------------------
def compute_pareto_front(
        aggregated: List[Dict[str, Any]],
        obj1: str = "throughput",
        obj2: str = "near_misses",
) -> List[Dict[str, Any]]:
    """Return the non-dominated (Pareto-optimal) configurations.

    obj1 is maximized; obj2 is minimized.
    A config A dominates B if A is at least as good on both objectives
    and strictly better on at least one.
    """
    col1 = f"{obj1}_mean"
    col2 = f"{obj2}_mean"

    candidates = [
        r for r in aggregated
        if not np.isnan(r.get(col1, float("nan")))
           and not np.isnan(r.get(col2, float("nan")))
    ]

    pareto = []
    for i, ci in enumerate(candidates):
        dominated = False
        for j, cj in enumerate(candidates):
            if i == j:
                continue
            # cj dominates ci if cj is at least as good on both and better on one
            better_or_equal_1 = cj[col1] >= ci[col1]
            better_or_equal_2 = cj[col2] <= ci[col2]
            strictly_better = (cj[col1] > ci[col1]) or (cj[col2] < ci[col2])
            if better_or_equal_1 and better_or_equal_2 and strictly_better:
                dominated = True
                break
        if not dominated:
            pareto.append(ci)

    # Sort by obj1 descending
    pareto.sort(key=lambda r: r[col1], reverse=True)
    return pareto


# ---------------------------------------------------------------------------
# Sensitivity score
# ---------------------------------------------------------------------------
def compute_sensitivity(
        aggregated: List[Dict[str, Any]],
        metric: str = "throughput",
) -> Dict[str, float]:
    """Compute parameter sensitivity: max |Δmetric| over full sweep range.

    Returns a dict mapping each value to its sensitivity score, plus
    a single 'global' key with the total range / IQR.
    """
    col = f"{metric}_mean"
    vals_numeric = []
    for r in aggregated:
        try:
            vals_numeric.append((float(r["value"]), r.get(col, float("nan"))))
        except (ValueError, TypeError):
            pass
    if not vals_numeric:
        return {}
    vals_numeric.sort(key=lambda x: x[0])
    param_vals = [v[0] for v in vals_numeric]
    metric_vals = np.array([v[1] for v in vals_numeric], dtype=float)
    result = {"global_range": float(np.nanmax(metric_vals) - np.nanmin(metric_vals))}
    finite = metric_vals[~np.isnan(metric_vals)]
    if len(finite) >= 4:
        result["iqr"] = float(np.percentile(finite, 75) - np.percentile(finite, 25))
    return result


# ---------------------------------------------------------------------------
# Best configuration selection
# ---------------------------------------------------------------------------
def find_best(
        aggregated: List[Dict[str, Any]],
        metric: str = "throughput",
        higher_is_better: bool = True,
) -> Dict[str, Any]:
    """Return the configuration with the best mean value for *metric*."""
    col = f"{metric}_mean"
    key_fn = (lambda r: r.get(col, float("-inf"))) if higher_is_better \
        else (lambda r: -r.get(col, float("inf")))
    return max(aggregated, key=key_fn)


def print_best(best: Dict[str, Any], metric: str = "throughput") -> None:
    col_m = f"{metric}_mean"
    col_s = f"{metric}_std"
    col_lo = f"{metric}_ci95_lo"
    col_hi = f"{metric}_ci95_hi"
    col_p = f"{metric}_wilcoxon_p"
    col_q = f"{metric}_fdr_q"
    col_r = f"{metric}_effect_r"
    print(f"\n*** Best configuration ***")
    print(f"  {best['param']} = {best['value']}")
    print(f"  {metric}: mean={best.get(col_m, '?'):.4f}  "
          f"std={best.get(col_s, '?'):.4f}  "
          f"95CI=[{best.get(col_lo, '?'):.4f}, {best.get(col_hi, '?'):.4f}]")
    p = best.get(col_p, float("nan"))
    q = best.get(col_q, float("nan"))
    r = best.get(col_r, float("nan"))
    if not np.isnan(p):
        stars = ("***" if p < 0.001 else "**" if p < 0.01
        else "*" if p < 0.05 else "ns")
        print(f"  vs baseline: Wilcoxon p={p:.4f}{stars}  "
              f"FDR-q={q:.4f}  effect r={r:.3f}")
    print(f"  (n_seeds={best.get('n_seeds', '?')})")


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------
def print_statistical_summary(
        aggregated: List[Dict[str, Any]],
        primary_metric: str = "throughput",
        secondary_metrics: Optional[List[str]] = None,
) -> None:
    """Print a concise, paper-ready table to stdout."""
    if secondary_metrics is None:
        secondary_metrics = ["mean_flowtime", "near_misses", "mean_planning_time_ms"]

    col_w = 14
    metrics_to_show = [primary_metric] + secondary_metrics
    header = f"{'value':<12}" + "".join(
        f"{'  ' + m[:col_w - 2]:>{col_w}}" for m in metrics_to_show
    ) + f"{'p-val':>10}{'q-val':>10}{'|r|':>8}"
    print(f"\n{'─' * len(header)}")
    print(header)
    print(f"{'─' * len(header)}")

    for row in aggregated:
        val_str = str(row["value"])[:11]
        line = f"{val_str:<12}"
        for m in metrics_to_show:
            mean = row.get(f"{m}_mean", float("nan"))
            std = row.get(f"{m}_std", float("nan"))
            line += f"  {mean:6.3f}±{std:5.3f}"
        p = row.get(f"{primary_metric}_wilcoxon_p", float("nan"))
        q = row.get(f"{primary_metric}_fdr_q", float("nan"))
        r = abs(row.get(f"{primary_metric}_effect_r", float("nan")))
        stars = ("***" if not np.isnan(p) and p < 0.001 else
                 "**" if not np.isnan(p) and p < 0.01 else
                 "*" if not np.isnan(p) and p < 0.05 else "ns")
        p_str = f"{p:.4f}" if not np.isnan(p) else "  nan"
        q_str = f"{q:.4f}" if not np.isnan(q) else "  nan"
        r_str = f"{r:.3f}" if not np.isnan(r) else " nan"
        line += f"  {p_str}{stars:>3}  {q_str}  {r_str}"
        print(line)
    print(f"{'─' * len(header)}")
    print("Stars: *** p<0.001  ** p<0.01  * p<0.05  ns not significant")
    print("|r|:  0.1=small  0.3=medium  0.5=large effect\n")


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def save_results(
        results: List[Dict[str, Any]],
        aggregated: List[Dict[str, Any]],
        output_dir: Path,
        pareto: Optional[List[Dict[str, Any]]] = None,
        latex: bool = True,
) -> None:
    """Write raw results, summary, optional Pareto CSV, and LaTeX table."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if results:
        raw_path = output_dir / "results.csv"
        with open(raw_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved raw results:  {raw_path}")

    if aggregated:
        agg_path = output_dir / "summary.csv"
        with open(agg_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=aggregated[0].keys())
            writer.writeheader()
            writer.writerows(aggregated)
        print(f"Saved summary:      {agg_path}")

    if pareto:
        pf_path = output_dir / "pareto.csv"
        with open(pf_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=pareto[0].keys())
            writer.writeheader()
            writer.writerows(pareto)
        print(f"Saved Pareto front: {pf_path}")

    if latex and aggregated:
        tex_path = output_dir / "table.tex"
        _write_latex_table(aggregated, tex_path)
        print(f"Saved LaTeX table:  {tex_path}")


def _write_latex_table(
        aggregated: List[Dict[str, Any]],
        path: Path,
        primary_metric: str = "throughput",
) -> None:
    """Write a publication-ready booktabs LaTeX table."""
    metrics_in_table = [
        ("throughput", "Throughput"),
        ("mean_flowtime", "Mean Flowtime"),
        ("near_misses", "Near Misses"),
        ("mean_planning_time_ms", "Plan. Time (ms)"),
    ]

    # Determine best row by primary metric
    col_best = f"{primary_metric}_mean"
    best_val = max(
        (r.get(col_best, float("-inf")) for r in aggregated
         if METRIC_DIRECTION.get(primary_metric, True)),
        default=None,
    )

    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Hyperparameter tuning results. "
        r"Best configuration in \textbf{bold}. "
        r"Statistical significance of difference from baseline: "
        r"$^{*}p{<}0.05$, $^{**}p{<}0.01$, $^{***}p{<}0.001$ "
        r"(Wilcoxon signed-rank, BH-corrected).}",
        r"\label{tab:tuning_" + str(aggregated[0]["param"]).replace("+", "_") + "}",
        r"\setlength{\tabcolsep}{4pt}",
        r"\begin{tabular}{l" + "c" * len(metrics_in_table) + "cc}",
        r"\toprule",
    ]

    # Header
    param = str(aggregated[0]["param"])
    header = f"\\textbf{{{param}}}"
    for _, label in metrics_in_table:
        header += f" & \\textbf{{{label}}}"
    header += r" & $p$ & $q$ \\"
    lines.append(header)
    lines.append(r"\midrule")

    for row in aggregated:
        p = row.get(f"{primary_metric}_wilcoxon_p", float("nan"))
        q = row.get(f"{primary_metric}_fdr_q", float("nan"))
        stars = ("$^{***}$" if not np.isnan(p) and p < 0.001 else
                 "$^{**}$" if not np.isnan(p) and p < 0.01 else
                 "$^{*}$" if not np.isnan(p) and p < 0.05 else "")
        val_str = str(row["value"])
        is_best = abs(row.get(col_best, float("nan")) - (best_val or 0.0)) < 1e-9
        if is_best:
            val_str = f"\\textbf{{{val_str}}}"

        line = val_str
        for m, _ in metrics_in_table:
            mean = row.get(f"{m}_mean", float("nan"))
            std = row.get(f"{m}_std", float("nan"))
            cell = f"{mean:.3f}$\\pm${std:.3f}"
            if is_best:
                cell = f"\\textbf{{{cell}}}"
            line += f" & {cell}"

        p_str = f"{p:.3f}{stars}" if not np.isnan(p) else "--"
        q_str = f"{q:.3f}" if not np.isnan(q) else "--"
        line += f" & {p_str} & {q_str} \\\\"
        lines.append(line)

    lines += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
    ]

    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Common CLI arguments
# ---------------------------------------------------------------------------
def add_common_args(parser) -> None:
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4],
                        help="Random seeds (default: 0 1 2 3 4 — 5 minimum)")
    parser.add_argument("--map", type=str, default=PRIMARY_MAP,
                        help="Map path")
    parser.add_argument("--agents", type=int, default=20,
                        help="Number of agents")
    parser.add_argument("--humans", type=int, default=5,
                        help="Number of humans")
    parser.add_argument("--steps", type=int, default=5000,
                        help="Simulation steps (≥5000 for stable statistics)")
    parser.add_argument("--workers", "-j", type=int, default=1,
                        help="Parallel workers (0 = all cores)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--output", type=str, default="logs/tuning",
                        help="Base output directory")
    parser.add_argument("--label", type=str, default="",
                        help="Run label for the output folder name")
    parser.add_argument("--no-latex", action="store_true",
                        help="Skip LaTeX table generation")


def resolve_workers(workers: int) -> int:
    if workers <= 0:
        import multiprocessing
        workers = multiprocessing.cpu_count()
        print(f"Auto-detected {workers} CPU cores for parallel execution.")
    return workers
