# !/usr/bin/env python3
"""Step 4 — Tune *fov_radius* with best horizon + replan_every fixed.

fov_radius (field of view) is the Manhattan-distance radius in which agents
can detect humans.  It must exceed safety_radius (the forbidden zone size)
for agents to have sufficient warning to avoid the safety zone.

Key insight:  fov_radius < safety_radius → agent enters safety zone before
it detects the human → near_misses ↑ sharply.
fov_radius >> safety_radius → large perception overhead, diminishing returns.

PRIMARY metric:   near_misses (safety-critical — use this to pick fov_radius)
SECONDARY:        safety_violations, throughput, total_wait_steps

The joint fov+safety sweep in Step 6 refines both together.

Statistical analysis:
  - Wilcoxon signed-rank (paired) vs baseline (fov_radius=1)
  - BH FDR correction, rank-biserial r, 95% bootstrap CI
  - Pareto front: (throughput, near_misses) — efficiency-safety tradeoff

Sweep values: [1, 2, 3, 4, 5, 6, 8, 10]

Usage:
    python scripts/tuning/tune_fov_radius.py \\
        --best-horizon 50 --best-replan-every 25
    python scripts/tuning/tune_fov_radius.py \\
        --best-horizon 50 --best-replan-every 25 --seeds 0 --steps 1000
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

SWEEP_VALUES = [1, 2, 3, 4, 5, 6, 8, 10]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune fov_radius (Step 4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PRIMARY metric: near_misses — choose the lowest value\n"
            "  where near_misses plateaus (diminishing returns beyond that).\n"
        ),
    )
    add_common_args(parser)
    parser.add_argument("--best-horizon", type=int, required=True,
                        help="Best horizon from Step 1/3")
    parser.add_argument("--best-replan-every", type=int, required=True,
                        help="Best replan_every from Step 2/3")
    parser.add_argument(
        "--values", type=int, nargs="+", default=SWEEP_VALUES,
        help=f"fov_radius values to sweep (default: {SWEEP_VALUES})",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    base = get_base_config(
        map_path=args.map, num_agents=args.agents,
        num_humans=args.humans, steps=args.steps,
    )
    base["horizon"] = args.best_horizon
    base["replan_every"] = args.best_replan_every

    out = make_output_dir("fov_radius", run_label=args.label, base_dir=args.output)
    print(f"Output directory: {out}")
    print(f"Fixed:  horizon={args.best_horizon}  "
          f"replan_every={args.best_replan_every}")
    print(f"Note: fov_radius must exceed safety_radius={base['safety_radius']} "
          f"to be effective.")

    results = run_sweep(
        param_name="fov_radius",
        values=args.values,
        seeds=args.seeds,
        base_config=base,
        verbose=args.verbose,
        workers=args.workers,
    )

    agg = aggregate_results(results)
    pareto = compute_pareto_front(agg, obj1="throughput", obj2="near_misses")

    save_results(results, agg, out,
                 pareto=pareto if pareto else None,
                 latex=not args.no_latex)

    # ---- Sensitivity analysis -----------------------------------------------
    for metric in ("near_misses", "throughput", "safety_violations"):
        sens = compute_sensitivity(agg, metric=metric)
        print(f"Sensitivity — {metric} range: {sens.get('global_range', '?'):.4f}")

    # ---- Statistical summary (primary = near_misses for safety) ---------------
    print_statistical_summary(
        agg,
        primary_metric="near_misses",
        secondary_metrics=[
            "safety_violations", "throughput", "total_wait_steps",
        ],
    )

    # ---- Best configurations -----------------------------------------------
    # Near misses: lower is better (safety-first)
    best_safe = find_best(agg, metric="near_misses", higher_is_better=False)
    print("--- Best by near_misses (fewest — safety priority) ---")
    print_best(best_safe, metric="near_misses")

    # Throughput: higher is better
    best_tp = find_best(agg, metric="throughput")
    print("--- Best by throughput (efficiency priority) ---")
    print_best(best_tp, metric="throughput")

    if pareto:
        print(f"\nPareto-optimal configs ({len(pareto)}):")
        for p in pareto:
            tp = p.get("throughput_mean", float("nan"))
            nm = p.get("near_misses_mean", float("nan"))
            print(f"  fov_radius={p['value']}  "
                  f"throughput={tp:.4f}  near_misses={nm:.1f}")

    print(f"\nRecommended: choose smallest fov_radius where near_misses plateaus.")
    print(f"\nRecommended next step:")
    print(f"  python scripts/tuning/tune_safety_radius.py "
          f"--best-horizon {args.best_horizon} "
          f"--best-replan-every {args.best_replan_every} "
          f"--best-fov-radius {best_safe['value']}")


if __name__ == "__main__":
    main()
