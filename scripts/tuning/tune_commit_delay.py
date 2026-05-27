# !/usr/bin/env python3
"""Step 7 — Joint grid sweep of *commit_horizon* × *delay_threshold*.

commit_horizon controls how long a task assignment is kept ("committed")
before the allocator is allowed to reassign it.

  commit_horizon = 0  →  memoryless greedy (default): reassigns every step
                         → high assignment thrashing (assignments_broken ↑)
  commit_horizon > 0  →  assignment locked for at most commit_horizon steps
                         → more stable but slower reaction to better opportunities

delay_threshold triggers *early revocation*: if the agent's current distance
to the target exceeds delay_threshold × the initial assignment distance,
the assignment is revoked even before commit_horizon expires.

  delay_threshold = 0.0  →  no early revocation
  delay_threshold = 1.5  →  revoke if 50% farther than at assignment time

NOTE: delay_threshold > 0 is meaningless when commit_horizon = 0 (no
commitment to revoke). These pairs are excluded from the sweep.

Primary metrics:   throughput, mean_flowtime
Stability metrics: assignments_kept, assignments_broken, delay_events
                   (high assignments_broken with low throughput → thrashing)

Statistical analysis:
  - Wilcoxon signed-rank (paired) vs baseline (commit=0, delay=0.0)
  - BH FDR correction, rank-biserial r, 95% bootstrap CI
  - Pareto front: (throughput, assignments_broken)

Usage:
    python scripts/tuning/tune_commit_delay.py \\
        --best-horizon 50 --best-replan-every 25 \\
        --best-fov-radius 4 --best-safety-radius 1

    # After this step, you have the complete tuned configuration.
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

COMMIT_VALUES = [0, 5, 10, 25, 50, 100]
DELAY_VALUES = [0.0, 1.5, 2.0, 2.5, 3.0, 4.0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Joint commit_horizon × delay_threshold grid sweep (Step 7 — final)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Constraint: delay_threshold > 0 requires commit_horizon > 0.\n"
            "\nAfter this step, print the complete tuned configuration and\n"
            "  use it as the 'system configuration' in all paper experiments.\n"
        ),
    )
    add_common_args(parser)
    parser.add_argument("--best-horizon", type=int, required=True,
                        help="Best horizon from Step 1/3")
    parser.add_argument("--best-replan-every", type=int, required=True,
                        help="Best replan_every from Step 2/3")
    parser.add_argument("--best-fov-radius", type=int, required=True,
                        help="Best fov_radius from Step 4/6")
    parser.add_argument("--best-safety-radius", type=int, required=True,
                        help="Best safety_radius from Step 5/6")
    parser.add_argument(
        "--commit-values", type=int, nargs="+", default=COMMIT_VALUES,
        help=f"commit_horizon values (default: {COMMIT_VALUES})",
    )
    parser.add_argument(
        "--delay-values", type=float, nargs="+", default=DELAY_VALUES,
        help=f"delay_threshold values (default: {DELAY_VALUES})",
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
    base["safety_radius"] = args.best_safety_radius

    out = make_output_dir("commit_delay", run_label=args.label, base_dir=args.output)
    total_valid = (
        # commit=0 with delay=0 only
            1 +
            # commit>0 with all delay values
            sum(1 for c in args.commit_values if c > 0) * len(args.delay_values)
    )
    print(f"Output directory: {out}")
    print(f"Fixed:  horizon={args.best_horizon}  "
          f"replan_every={args.best_replan_every}  "
          f"fov_radius={args.best_fov_radius}  "
          f"safety_radius={args.best_safety_radius}")
    print(f"Grid: ~{total_valid} valid (commit, delay) pairs × "
          f"{len(args.seeds)} seeds")

    def valid_pair(commit, delay):
        # delay_threshold > 0 only makes sense when commit_horizon > 0
        return not (commit == 0 and delay > 0.0)

    results = run_grid_sweep(
        param_a="commit_horizon",
        values_a=args.commit_values,
        param_b="delay_threshold",
        values_b=args.delay_values,
        seeds=args.seeds,
        base_config=base,
        constraint=valid_pair,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)

    # Pareto: throughput vs assignments_broken (efficiency vs stability)
    pareto_stable = compute_pareto_front(
        agg, obj1="throughput", obj2="assignments_broken",
    )

    save_results(results, agg, out,
                 pareto=pareto_stable if pareto_stable else None,
                 latex=not args.no_latex)

    # ---- Statistical summary tables -----------------------------------------
    print("\n*** throughput vs (commit_horizon, delay_threshold) ***")
    print_statistical_summary(
        agg,
        primary_metric="throughput",
        secondary_metrics=[
            "mean_flowtime", "assignments_broken", "delay_events",
        ],
    )

    print("\n*** assignment stability: assignments_kept vs broken ***")
    print_statistical_summary(
        agg,
        primary_metric="assignments_kept",
        secondary_metrics=[
            "assignments_broken", "throughput", "mean_flowtime",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    best_tp = find_best(agg, metric="throughput")
    print("--- Best by throughput ---")
    print_best(best_tp, metric="throughput")

    best_ft = find_best(agg, metric="mean_flowtime", higher_is_better=False)
    print("--- Best by mean_flowtime ---")
    print_best(best_ft, metric="mean_flowtime")

    if pareto_stable:
        print(f"\nThroughput-stability Pareto front ({len(pareto_stable)} configs):")
        for p in pareto_stable:
            tp = p.get("throughput_mean", float("nan"))
            ab = p.get("assignments_broken_mean", float("nan"))
            print(f"  value={p['value']}  throughput={tp:.4f}  "
                  f"assignments_broken={ab:.1f}")

    c_best, d_best = best_tp["value"].split(",")

    # ---- Final complete configuration summary --------------------------------
    print(f"\n{'=' * 60}")
    print(f"COMPLETE TUNED CONFIGURATION (use in paper experiments)")
    print(f"{'=' * 60}")
    print(f"  global_solver:    lacam      (from solver study)")
    print(f"  horizon:          {args.best_horizon:<10} (Step 1/3)")
    print(f"  replan_every:     {args.best_replan_every:<10} (Step 2/3)")
    print(f"  fov_radius:       {args.best_fov_radius:<10} (Step 4/6)")
    print(f"  safety_radius:    {args.best_safety_radius:<10} (Step 5/6)")
    print(f"  commit_horizon:   {c_best:<10} (Step 7)")
    print(f"  delay_threshold:  {d_best:<10} (Step 7)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
