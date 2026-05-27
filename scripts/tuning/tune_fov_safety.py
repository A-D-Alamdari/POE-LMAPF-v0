# !/usr/bin/env python3
"""Step 6 — Joint grid sweep of *fov_radius* × *safety_radius*.

Steps 4 and 5 optimise fov and safety radius independently.
This script finds the true joint optimum and produces the full
safety-efficiency Pareto frontier — the primary result for conference
submission (Figure: "throughput vs. near_misses for all fov/safety pairs").

Design:
  Hard constraint:  fov_radius > safety_radius
    (agents must see strictly farther than the forbidden zone to react in time)

  Maps:  warehouse_small  and  random-64-64-10
    Both are swept with num_agents=100, num_humans=50.

Dual-objective analysis (primary deliverable):
  Objective 1 (maximize):  throughput
  Objective 2 (minimize):  near_misses
  The Pareto front is written to pareto.csv and plotted as a scatter.

Secondary analysis:
  total_wait_steps, collisions_agent_human, safety_violation_rate

Statistical analysis:
  - Wilcoxon signed-rank + BH FDR vs the (fov=2, safety=1) baseline cell
  - Rank-biserial r effect size per cell
  - 95% bootstrap CI per cell

Usage:
    python scripts/tuning/tune_fov_safety.py
    python scripts/tuning/tune_fov_safety.py \\
        --best-horizon 30 --best-replan-every 15
    python scripts/tuning/tune_fov_safety.py \\
        --fov-values 3 4 5 6 --safety-values 1 2 3  # narrow search
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.tuning.tuning_utils import (
    add_common_args, aggregate_results, compute_pareto_front, find_best,
    get_base_config, make_output_dir, print_best, print_statistical_summary,
    resolve_workers, run_grid_sweep, save_results,
)

FOV_VALUES = [2, 3, 4, 5, 6, 7, 8, 9, 10]
SAFETY_VALUES = [1, 2, 3, 4, 5]

MAPS = [
    "data/maps/warehouse-10-20-10-2-1.map",
    "data/maps/random-64-64-10.map",
]

DEFAULT_SEEDS = list(range(10))  # [0, 1, 2, ..., 9]


def _run_for_map(map_path: str, args) -> None:
    """Run the full fov × safety grid sweep for a single map."""
    map_name = Path(map_path).stem
    print(f"\n{'=' * 70}")
    print(f"  Map: {map_name}  ({map_path})")
    print(f"{'=' * 70}")

    base = get_base_config(
        map_path=map_path, num_agents=args.agents,
        num_humans=args.humans, steps=args.steps,
    )
    base["horizon"] = args.best_horizon
    base["replan_every"] = args.best_replan_every
    base["global_solver"] = "lacam3"
    base["time_budget_ms"] = 5000.0

    out = make_output_dir(
        f"fov_safety/{map_name}", run_label=args.label, base_dir=args.output,
    )
    total_valid = sum(
        1 for f in args.fov_values for s in args.safety_values if f > s
    )
    print(f"Output directory: {out}")
    print(f"Fixed:  horizon={args.best_horizon}  "
          f"replan_every={args.best_replan_every}")
    print(f"Grid: {total_valid} valid (fov, safety) pairs × "
          f"{len(args.seeds)} seeds = {total_valid * len(args.seeds)} runs")

    results = run_grid_sweep(
        param_a="fov_radius",
        values_a=args.fov_values,
        param_b="safety_radius",
        values_b=args.safety_values,
        seeds=args.seeds,
        base_config=base,
        constraint=lambda fov, safety: fov > safety,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)

    # PRIMARY: Pareto front throughput vs near_misses
    pareto_safety = compute_pareto_front(
        agg, obj1="throughput", obj2="near_misses",
    )
    # SECONDARY: Pareto front throughput vs total_wait_steps
    pareto_wait = compute_pareto_front(
        agg, obj1="throughput", obj2="total_wait_steps",
    )

    save_results(results, agg, out,
                 pareto=pareto_safety if pareto_safety else None,
                 latex=not args.no_latex)

    if pareto_wait:
        wait_path = out / "pareto_wait.csv"
        with open(wait_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=pareto_wait[0].keys())
            writer.writeheader()
            writer.writerows(pareto_wait)
        print(f"Saved wait Pareto:  {wait_path}")

    # ---- Statistical summary (primary = near_misses) -----------------------
    print(f"\n*** near_misses vs (fov_radius, safety_radius) — {map_name} ***")
    print_statistical_summary(
        agg,
        primary_metric="near_misses",
        secondary_metrics=[
            "throughput", "total_wait_steps", "collisions_agent_human",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    # Safety-priority: fewest near_misses
    best_safe = find_best(agg, metric="near_misses", higher_is_better=False)
    print(f"--- Best by near_misses (safety priority) — {map_name} ---")
    print_best(best_safe, metric="near_misses")

    # Efficiency-priority: highest throughput
    best_tp = find_best(agg, metric="throughput")
    print(f"--- Best by throughput (efficiency priority) — {map_name} ---")
    print_best(best_tp, metric="throughput")

    # ---- Pareto summaries ---------------------------------------------------
    if pareto_safety:
        print(f"\n*** Safety-efficiency Pareto front ({len(pareto_safety)} configs) — {map_name} ***")
        print("  (Non-dominated; no config is simultaneously safer AND faster)")
        print(f"  {'fov':>4}  {'safety':>6}  {'throughput':>12}  {'near_misses':>11}")
        for p in pareto_safety:
            fv, sv = str(p["value"]).split(",")
            tp = p.get("throughput_mean", float("nan"))
            nm = p.get("near_misses_mean", float("nan"))
            print(f"  {fv:>4}  {sv:>6}  {tp:>12.4f}  {nm:>11.1f}")
        print("  → Report this table in the paper as the fov-safety tradeoff.")

    fov_best, safety_best = best_safe["value"].split(",")
    print(f"\nBest pair (safety-priority) — {map_name}: "
          f"fov_radius={fov_best}  safety_radius={safety_best}")
    print(f"\nRecommended next step for {map_name}:")
    print(f"  python scripts/tuning/tune_commit_delay.py "
          f"--best-horizon {args.best_horizon} "
          f"--best-replan-every {args.best_replan_every} "
          f"--best-fov-radius {fov_best} "
          f"--best-safety-radius {safety_best}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Joint fov_radius × safety_radius grid sweep (Step 6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Constraint: fov_radius > safety_radius (strict; always enforced).\n"
            "Maps: warehouse_small and random-64-64-10 (both swept by default).\n"
            "Outputs per map: results.csv  summary.csv  pareto.csv  table.tex\n"
            "Plots (heatmap + Pareto scatter):\n"
            "  python scripts/tuning/plot_tuning.py "
            "logs/tuning/fov_safety/.../summary.csv --heatmap\n"
        ),
    )
    add_common_args(parser)
    # Override defaults from add_common_args
    parser.set_defaults(agents=100, humans=50, seeds=DEFAULT_SEEDS)
    parser.add_argument("--best-horizon", type=int, default=20,
                        help="Best horizon from Step 1/3 (default: 20)")
    parser.add_argument("--best-replan-every", type=int, default=10,
                        help="Best replan_every from Step 2/3 (default: 10)")
    parser.add_argument(
        "--fov-values", type=int, nargs="+", default=FOV_VALUES,
        help=f"fov_radius values in the grid (default: {FOV_VALUES})",
    )
    parser.add_argument(
        "--safety-values", type=int, nargs="+", default=SAFETY_VALUES,
        help=f"safety_radius values (default: {SAFETY_VALUES})",
    )
    parser.add_argument(
        "--maps", type=str, nargs="+", default=MAPS,
        help=f"Map paths to sweep (default: {MAPS})",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    for map_path in args.maps:
        _run_for_map(map_path, args)


if __name__ == "__main__":
    main()
