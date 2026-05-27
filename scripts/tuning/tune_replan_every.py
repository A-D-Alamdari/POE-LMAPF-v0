# !/usr/bin/env python3
"""Step 2 — Tune *replan_every* with the best horizon from Step 1 fixed.

replan_every controls how often the global planner is invoked.
Too frequent  → planning overhead reduces throughput (intervention_rate ↑).
Too infrequent → paths become stale, agents block each other (wait_steps ↑).

Key metrics to watch:
  - throughput and mean_flowtime — primary quality objectives
  - intervention_rate — global replans per 1000 steps (overhead proxy)
  - total_wait_steps — proxy for path staleness and deadlock risk
  - mean_planning_time_ms — computational budget consumed

Statistical output:
  - Wilcoxon signed-rank (paired) vs baseline (smallest replan_every)
  - BH FDR correction, rank-biserial effect size, 95% bootstrap CI

Usage:
    python scripts/tuning/tune_replan_every.py --best-horizon 50
    python scripts/tuning/tune_replan_every.py --best-horizon 50 \\
        --seeds 0 --steps 1000 --workers 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.tuning.tuning_utils import (
    add_common_args, aggregate_results, compute_sensitivity, find_best,
    get_base_config, make_output_dir, print_best, print_statistical_summary,
    resolve_workers, run_sweep, save_results,
)

SWEEP_VALUES = [5, 10, 15, 20, 25, 30, 40, 50]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune replan_every (Step 2 — requires --best-horizon)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Constraint: only values ≤ best_horizon are tested.\n"
            "Outputs: results.csv  summary.csv  table.tex\n"
        ),
    )
    add_common_args(parser)
    parser.add_argument(
        "--best-horizon", type=int, required=True,
        help="Best horizon value from Step 1 (tune_horizon.py)",
    )
    parser.add_argument(
        "--values", type=int, nargs="+", default=SWEEP_VALUES,
        help=f"replan_every values to sweep (default: {SWEEP_VALUES})",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    base = get_base_config(
        map_path=args.map, num_agents=args.agents,
        num_humans=args.humans, steps=args.steps,
    )
    base["horizon"] = args.best_horizon

    # Enforce constraint: replan_every ≤ horizon
    valid_values = [v for v in args.values if v <= args.best_horizon]
    dropped = [v for v in args.values if v > args.best_horizon]
    if dropped:
        print(f"Dropped values {dropped}: exceed horizon={args.best_horizon}")

    out = make_output_dir("replan_every", run_label=args.label, base_dir=args.output)
    print(f"Output directory: {out}")
    print(f"Fixed:  horizon={args.best_horizon}")

    results = run_sweep(
        param_name="replan_every",
        values=valid_values,
        seeds=args.seeds,
        base_config=base,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)
    save_results(results, agg, out, latex=not args.no_latex)

    # ---- Sensitivity analysis ---------------------------------------------
    for metric in ("throughput", "intervention_rate", "total_wait_steps"):
        sens = compute_sensitivity(agg, metric=metric)
        print(f"Sensitivity — {metric} range: {sens.get('global_range', '?'):.4f}")

    # ---- Statistical summary table ----------------------------------------
    print_statistical_summary(
        agg,
        primary_metric="throughput",
        secondary_metrics=[
            "mean_flowtime", "intervention_rate", "total_wait_steps",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    best_tp = find_best(agg, metric="throughput")
    print("--- Best by throughput ---")
    print_best(best_tp, metric="throughput")

    best_wait = find_best(agg, metric="total_wait_steps", higher_is_better=False)
    print("--- Best by total_wait_steps (fewest) ---")
    print_best(best_wait, metric="total_wait_steps")

    print(f"\nRecommended next step:")
    print(f"  python scripts/tuning/tune_horizon_replan.py")
    print(f"  (joint grid search — confirms Steps 1+2)")
    print(f"\n  OR skip to Step 4 with:")
    print(f"  python scripts/tuning/tune_fov_radius.py "
          f"--best-horizon {args.best_horizon} "
          f"--best-replan-every {best_tp['value']}")


if __name__ == "__main__":
    main()
