# !/usr/bin/env python3
"""Step 5 — Tune *safety_radius* with best horizon, replan_every, fov_radius fixed.

safety_radius defines the forbidden zone around humans (Manhattan distance).
This is the most direct safety-efficiency tradeoff in the system:

  ↑ safety_radius → fewer near_misses, but agents must detour more →
                    throughput ↓, total_wait_steps ↑, risk of deadlock ↑

CRITICAL NOTE: Use *near_misses* as the primary safety metric here, NOT
safety_violations.  safety_violations counts any entry into the zone, so
a larger radius trivially raises the violation count — the metric is
confounded by the parameter being swept.  near_misses counts contacts at
exactly distance ≤ 1 and is independent of safety_radius.

Primary metrics:   near_misses, throughput (two objectives — Pareto analysis)
Secondary:         total_wait_steps, safety_violation_rate, collisions_agent_human

Statistical analysis:
  - Wilcoxon signed-rank (paired) vs baseline (safety_radius=0)
  - BH FDR correction, rank-biserial r, 95% bootstrap CI
  - Pareto front: (throughput, near_misses) — explicit safety-efficiency curve

Sweep values: [0, 1, 2, 3, 4, 5]

Usage:
    python scripts/tuning/tune_safety_radius.py \\
        --best-horizon 50 --best-replan-every 25 --best-fov-radius 4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.tuning.tuning_utils import (
    add_common_args, aggregate_results, compute_pareto_front,
    compute_sensitivity, find_best, get_base_config, make_output_dir,
    print_best, print_statistical_summary, resolve_workers, run_sweep,
    save_results,
)

SWEEP_VALUES = [0, 1, 2, 3, 4, 5]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune safety_radius (Step 5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "IMPORTANT: Use near_misses (not safety_violations) as primary\n"
            "  safety metric — safety_violations is confounded by radius size.\n"
            "\nPareto CSV shows the safety-efficiency frontier — use this to\n"
            "  justify your chosen safety_radius in the paper.\n"
        ),
    )
    add_common_args(parser)
    parser.add_argument("--best-horizon", type=int, required=True,
                        help="Best horizon from Step 1/3")
    parser.add_argument("--best-replan-every", type=int, required=True,
                        help="Best replan_every from Step 2/3")
    parser.add_argument("--best-fov-radius", type=int, required=True,
                        help="Best fov_radius from Step 4")
    parser.add_argument(
        "--values", type=int, nargs="+", default=SWEEP_VALUES,
        help=f"safety_radius values to sweep (default: {SWEEP_VALUES})",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    base = get_base_config(
        map_path=args.map, num_agents=args.agents,
        num_humans=args.humans, steps=args.steps,
    )
    base["horizon"] = args.best_horizon
    base["replan_every"] = args.best_replan_every
    base["fov_radius"] = args.best_fov_radius

    # Warn if any safety value exceeds fov_radius
    risky = [v for v in args.values if v > args.best_fov_radius]
    if risky:
        print(f"WARNING: safety_radius values {risky} exceed "
              f"fov_radius={args.best_fov_radius}. Agents won't detect\n"
              f"  humans before entering the safety zone → expect near_misses ↑.")

    out = make_output_dir("safety_radius", run_label=args.label, base_dir=args.output)
    print(f"Output directory: {out}")
    print(f"Fixed:  horizon={args.best_horizon}  "
          f"replan_every={args.best_replan_every}  "
          f"fov_radius={args.best_fov_radius}")

    results = run_sweep(
        param_name="safety_radius",
        values=args.values,
        seeds=args.seeds,
        base_config=base,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)
    # Pareto front: maximize throughput, minimize near_misses
    pareto = compute_pareto_front(agg, obj1="throughput", obj2="near_misses")

    save_results(results, agg, out,
                 pareto=pareto if pareto else None,
                 latex=not args.no_latex)

    # ---- Sensitivity analysis -----------------------------------------------
    for metric in ("near_misses", "throughput", "total_wait_steps"):
        sens = compute_sensitivity(agg, metric=metric)
        print(f"Sensitivity — {metric} range: {sens.get('global_range', '?'):.4f}")

    # ---- Statistical summary table ----------------------------------------
    print("\n*** near_misses — primary safety metric ***")
    print_statistical_summary(
        agg,
        primary_metric="near_misses",
        secondary_metrics=[
            "throughput", "total_wait_steps", "collisions_agent_human",
        ],
    )

    print("\n*** throughput — primary efficiency metric ***")
    print_statistical_summary(
        agg,
        primary_metric="throughput",
        secondary_metrics=[
            "near_misses", "total_wait_steps", "safety_violation_rate",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    best_safe = find_best(agg, metric="near_misses", higher_is_better=False)
    print("--- Best by near_misses (fewest — safety priority) ---")
    print_best(best_safe, metric="near_misses")

    best_tp = find_best(agg, metric="throughput")
    print("--- Best by throughput (efficiency priority) ---")
    print_best(best_tp, metric="throughput")

    if pareto:
        print(f"\nSafety-efficiency Pareto front ({len(pareto)} configs):")
        print("  (Non-dominated — no config is better on both throughput AND near_misses)")
        for p in pareto:
            tp = p.get("throughput_mean", float("nan"))
            nm = p.get("near_misses_mean", float("nan"))
            wt = p.get("total_wait_steps_mean", float("nan"))
            print(f"  safety_radius={p['value']}  "
                  f"throughput={tp:.4f}  near_misses={nm:.1f}  "
                  f"wait={wt:.0f}")
        print("  → Choose based on deployment safety requirements.")

    print(f"\nRecommended next step:")
    print(f"  python scripts/tuning/tune_fov_safety.py "
          f"--best-horizon {args.best_horizon} "
          f"--best-replan-every {args.best_replan_every}")
    print(f"  (joint grid confirms Step 4+5 or finds a better pair)")


if __name__ == "__main__":
    main()
