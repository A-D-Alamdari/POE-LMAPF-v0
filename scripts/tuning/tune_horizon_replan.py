# !/usr/bin/env python3
"""Step 3 — Joint grid sweep of *horizon* × *replan_every*.

Steps 1 and 2 tune each parameter in isolation; this script finds the true
joint optimum and quantifies the interaction between the two parameters.
A strong interaction (metric surfaces are not separable) means the sequential
approach in Steps 1-2 may have missed the global optimum.

Design:
  Constraint:  replan_every ≤ horizon  (plan always outlives one interval)
  Grid:        horizon in [20, 30, 40, 50, 60, 75, 100]
               replan_every in [5, 10, 15, 20, 25, 30, 40, 50]
               (invalid pairs are automatically skipped)

Primary objective:     throughput
Secondary objectives:  mean_flowtime, mean_planning_time_ms, near_misses

Statistical analysis:
  - Each cell vs the baseline cell (min horizon, min replan_every) via
    Wilcoxon signed-rank + BH FDR correction.
  - Pareto front across (throughput, near_misses) and
    (throughput, mean_planning_time_ms) — the quality-vs-cost tradeoff.

Usage:
    python scripts/tuning/tune_horizon_replan.py
    python scripts/tuning/tune_horizon_replan.py \\
        --horizon-values 30 40 50 60 --replan-values 10 15 20 25 30
    python scripts/tuning/tune_horizon_replan.py --seeds 0 --steps 1000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.tuning.tuning_utils import (
    add_common_args, aggregate_results, compute_pareto_front, find_best,
    get_base_config, make_output_dir, print_best, print_statistical_summary,
    resolve_workers, run_grid_sweep, save_results,
)

HORIZON_VALUES = [20, 30, 40, 50, 60, 75, 100]
REPLAN_VALUES = [5, 10, 15, 20, 25, 30, 40, 50]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Joint horizon × replan_every grid sweep (Step 3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Outputs: results.csv  summary.csv  pareto.csv  table.tex\n"
            "Plots (heatmaps + Pareto): python scripts/tuning/plot_tuning.py "
            "logs/tuning/horizon_replan/.../summary.csv --heatmap\n"
        ),
    )
    add_common_args(parser)
    parser.add_argument(
        "--horizon-values", type=int, nargs="+", default=HORIZON_VALUES,
        help=f"Horizon values to include in the grid (default: {HORIZON_VALUES})",
    )
    parser.add_argument(
        "--replan-values", type=int, nargs="+", default=REPLAN_VALUES,
        help=f"replan_every values (default: {REPLAN_VALUES})",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    base = get_base_config(
        map_path=args.map, num_agents=args.agents,
        num_humans=args.humans, steps=args.steps,
    )

    out = make_output_dir("horizon_replan", run_label=args.label,
                          base_dir=args.output)
    print(f"Output directory: {out}")
    total_valid = sum(
        1 for h in args.horizon_values for r in args.replan_values if r <= h
    )
    print(f"Grid: {total_valid} valid (horizon, replan_every) pairs × "
          f"{len(args.seeds)} seeds = {total_valid * len(args.seeds)} runs")

    results = run_grid_sweep(
        param_a="horizon",
        values_a=args.horizon_values,
        param_b="replan_every",
        values_b=args.replan_values,
        seeds=args.seeds,
        base_config=base,
        constraint=lambda h, r: r <= h,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)

    # Pareto front: throughput vs near_misses (safety-efficiency tradeoff)
    pareto_safety = compute_pareto_front(
        agg, obj1="throughput", obj2="near_misses",
    )
    # Pareto front: throughput vs planning time (quality-cost tradeoff)
    pareto_cost = compute_pareto_front(
        agg, obj1="throughput", obj2="mean_planning_time_ms",
    )

    save_results(results, agg, out,
                 pareto=pareto_safety if pareto_safety else None,
                 latex=not args.no_latex)

    # Save cost Pareto separately
    if pareto_cost:
        import csv
        cost_path = out / "pareto_cost.csv"
        with open(cost_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=pareto_cost[0].keys())
            writer.writeheader()
            writer.writerows(pareto_cost)
        print(f"Saved cost Pareto:  {cost_path}")

    # ---- Statistical summary -----------------------------------------------
    print_statistical_summary(
        agg,
        primary_metric="throughput",
        secondary_metrics=[
            "mean_flowtime", "near_misses", "mean_planning_time_ms",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    best_tp = find_best(agg, metric="throughput")
    print("--- Best by throughput ---")
    print_best(best_tp, metric="throughput")

    best_ft = find_best(agg, metric="mean_flowtime", higher_is_better=False)
    print("--- Best by mean_flowtime ---")
    print_best(best_ft, metric="mean_flowtime")

    best_cost = find_best(agg, metric="mean_planning_time_ms",
                          higher_is_better=False)
    print("--- Cheapest planning (lowest mean_planning_time_ms) ---")
    print_best(best_cost, metric="mean_planning_time_ms")

    # Pareto summaries
    if pareto_safety:
        print(f"\nSafety-efficiency Pareto front ({len(pareto_safety)} configs):")
        for p in pareto_safety:
            print(f"  value={p['value']}  "
                  f"throughput={p.get('throughput_mean', '?'):.4f}  "
                  f"near_misses={p.get('near_misses_mean', '?'):.1f}")

    if pareto_cost:
        print(f"\nQuality-cost Pareto front ({len(pareto_cost)} configs):")
        for p in pareto_cost:
            print(f"  value={p['value']}  "
                  f"throughput={p.get('throughput_mean', '?'):.4f}  "
                  f"plan_time_ms={p.get('mean_planning_time_ms_mean', '?'):.1f}")

    h_best, r_best = best_tp["value"].split(",")
    print(f"\nBest joint pair:  horizon={h_best}  replan_every={r_best}")
    print(f"\nRecommended next step:")
    print(f"  python scripts/tuning/tune_fov_radius.py "
          f"--best-horizon {h_best} --best-replan-every {r_best}")


if __name__ == "__main__":
    main()
