#!/usr/bin/env python3
"""
Publication-Quality Plotting for Hyperparameter Tuning Results.

Generates figures suitable for academic papers from tuning experiment results.

Usage:
    # Generate all plots
    python scripts/plot_tuning_results.py --input logs/tuning/results.csv --all

    # Generate specific plot type
    python scripts/plot_tuning_results.py --input logs/tuning/results.csv \
        --plot sensitivity --param replan_every

    # Generate Pareto front
    python scripts/plot_tuning_results.py --input logs/tuning/results.csv \
        --plot pareto --x throughput --y safety_violations

Output:
    logs/tuning/plots/
    ├── sensitivity_replan_every.pdf
    ├── sensitivity_safety_radius.pdf
    ├── scalability_agents.pdf
    ├── solver_comparison.pdf
    ├── ablation_study.pdf
    ├── pareto_front.pdf
    └── ...
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Check if matplotlib is available
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for servers
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Warning: matplotlib not installed. Install with: pip install matplotlib")


# Publication-quality plot settings
PLOT_SETTINGS = {
    "figure.figsize": (6, 4),
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.size": 11,
    "axes.labelsize": 12,
    "axes.titlesize": 13,
    "legend.fontsize": 10,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "lines.linewidth": 2,
    "lines.markersize": 8,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "axes.spines.top": False,
    "axes.spines.right": False,
}

# Color palette (colorblind-friendly)
COLORS = {
    "primary": "#2563eb",      # Blue
    "secondary": "#dc2626",    # Red
    "tertiary": "#16a34a",     # Green
    "quaternary": "#9333ea",   # Purple
    "quinary": "#ea580c",      # Orange
}

COLOR_CYCLE = [
    "#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c",
    "#0891b2", "#be123c", "#65a30d", "#7c3aed", "#c2410c",
]

# Metric display names
METRIC_LABELS = {
    "throughput": "Throughput (tasks/step)",
    "mean_flowtime": "Mean Flowtime (steps)",
    "median_flowtime": "Median Flowtime (steps)",
    "near_misses": "Near Misses (distance ≤ 1)",
    "safety_violations": "Safety Violations",
    "safety_violation_rate": "Safety Violation Rate (per 1000 steps)",
    "collisions_agent_agent": "Robot-Robot Collisions",
    "collisions_agent_human": "Robot-Human Collisions",
    "total_wait_steps": "Total Wait Steps",
    "mean_planning_time_ms": "Mean Planning Time (ms)",
    "p95_planning_time_ms": "P95 Planning Time (ms)",
    "completed_tasks": "Completed Tasks",
    "immediate_assignments": "Immediate Assignments",
}

# Parameter display names
PARAM_LABELS = {
    "replan_every": "Replanning Interval (steps)",
    "safety_radius": "Safety Radius (cells)",
    "fov_radius": "Field of View Radius (cells)",
    "num_agents": "Number of Agents",
    "num_humans": "Number of Humans",
    "task_arrival_rate": "Task Arrival Rate (steps)",
    "horizon": "Planning Horizon (steps)",
    "global_solver": "MAPF Solver",
    "task_allocator": "Task Allocator",
    "human_model": "Human Model",
    "hard_safety": "Safety Mode",
    "ablation": "System Configuration",
}


def load_results(filepath: Path) -> List[Dict[str, Any]]:
    """Load results from CSV file."""
    results = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric values
            for key, value in row.items():
                try:
                    if "." in value:
                        row[key] = float(value)
                    else:
                        row[key] = int(value)
                except (ValueError, TypeError):
                    pass  # Keep as string
            results.append(row)
    return results


def aggregate_by_value(
    results: List[Dict[str, Any]],
    sweep: str,
    param: str,
) -> Dict[Any, Dict[str, Tuple[float, float]]]:
    """
    Aggregate results by parameter value.

    Returns:
        Dict mapping value -> {metric: (mean, std)}
    """
    # Group by value
    groups = defaultdict(list)
    for r in results:
        if r.get("sweep") == sweep and r.get("param") == param:
            groups[r["value"]].append(r)

    # Compute statistics
    aggregated = {}
    for value, group in groups.items():
        stats = {}
        for key in group[0].keys():
            if key in ["sweep", "param", "value", "seed"]:
                continue
            try:
                values = [float(r[key]) for r in group]
                stats[key] = (np.mean(values), np.std(values))
            except (ValueError, TypeError):
                pass
        aggregated[value] = stats

    return aggregated


def _clip_yerr(
    means: List[float], stds: List[float]
) -> Tuple[List[float], List[float]]:
    """Return asymmetric error bars with the lower bound clipped at 0.

    All metrics in this domain are non-negative (throughput, flowtime, counts,
    times).  Passing raw stds as symmetric yerr can produce negative y-values
    on plots, which are physically meaningless and confusing to readers.
    """
    lower = [min(s, m) for m, s in zip(means, stds)]
    upper = list(stds)
    return lower, upper


def plot_sensitivity(
    results: List[Dict[str, Any]],
    sweep: str,
    param: str,
    metrics: List[str],
    output_dir: Path,
    title: Optional[str] = None,
) -> None:
    """
    Plot parameter sensitivity analysis.

    Creates a multi-panel figure showing how metrics change with parameter value.
    """
    if not HAS_MATPLOTLIB:
        print("Skipping plot (matplotlib not available)")
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, sweep, param)
    if not aggregated:
        print(f"No data found for sweep={sweep}, param={param}")
        return

    # Sort values (handle mixed types)
    try:
        values = sorted(aggregated.keys())
    except TypeError:
        values = list(aggregated.keys())

    n_metrics = len(metrics)
    fig, axes = plt.subplots(1, n_metrics, figsize=(4 * n_metrics, 4))
    if n_metrics == 1:
        axes = [axes]

    for ax, metric in zip(axes, metrics):
        means = [aggregated[v].get(metric, (0, 0))[0] for v in values]
        stds = [aggregated[v].get(metric, (0, 0))[1] for v in values]
        yerr = _clip_yerr(means, stds)

        # Convert boolean values to strings for plotting
        x_labels = [str(v) for v in values]
        x_positions = range(len(values))

        ax.errorbar(
            x_positions, means, yerr=yerr,
            marker="o", capsize=4, capthick=2,
            color=COLORS["primary"], ecolor=COLORS["secondary"],
        )

        ax.set_xlabel(PARAM_LABELS.get(param, param))
        ax.set_ylabel(METRIC_LABELS.get(metric, metric))
        ax.set_xticks(x_positions)
        ax.set_xticklabels(x_labels, rotation=45 if len(x_labels) > 5 else 0)

    if title:
        fig.suptitle(title, fontsize=14, y=1.02)

    plt.tight_layout()

    output_path = output_dir / f"sensitivity_{param}.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_scalability(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Plot scalability analysis (throughput and planning time vs num_agents).
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, "num_agents", "num_agents")
    if not aggregated:
        print("No scalability data found")
        return

    values = sorted(aggregated.keys())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    # Throughput
    means = [aggregated[v].get("throughput", (0, 0))[0] for v in values]
    stds = [aggregated[v].get("throughput", (0, 0))[1] for v in values]
    ax1.errorbar(values, means, yerr=_clip_yerr(means, stds), marker="o", capsize=4,
                 color=COLORS["primary"], label="Throughput")
    ax1.set_xlabel("Number of Agents")
    ax1.set_ylabel("Throughput (tasks/step)")
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))

    # Planning time
    means = [aggregated[v].get("mean_planning_time_ms", (0, 0))[0] for v in values]
    stds = [aggregated[v].get("mean_planning_time_ms", (0, 0))[1] for v in values]
    ax2.errorbar(values, means, yerr=_clip_yerr(means, stds), marker="s", capsize=4,
                 color=COLORS["secondary"], label="Planning Time")
    ax2.set_xlabel("Number of Agents")
    ax2.set_ylabel("Mean Planning Time (ms)")
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))

    fig.suptitle("Scalability Analysis", fontsize=14)
    plt.tight_layout()

    output_path = output_dir / "scalability_agents.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_solver_comparison(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Plot bar chart comparing different MAPF solvers.
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, "solver", "global_solver")
    if not aggregated:
        print("No solver comparison data found")
        return

    solvers = list(aggregated.keys())
    metrics = ["throughput", "mean_flowtime", "mean_planning_time_ms"]

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    for ax, metric in zip(axes, metrics):
        means = [aggregated[s].get(metric, (0, 0))[0] for s in solvers]
        stds = [aggregated[s].get(metric, (0, 0))[1] for s in solvers]

        x = range(len(solvers))
        bars = ax.bar(x, means, yerr=stds, capsize=4,
                      color=[COLOR_CYCLE[i % len(COLOR_CYCLE)] for i in x])

        ax.set_xlabel("Solver")
        ax.set_ylabel(METRIC_LABELS.get(metric, metric))
        ax.set_xticks(x)
        ax.set_xticklabels([s.upper() for s in solvers])

    fig.suptitle("MAPF Solver Comparison", fontsize=14)
    plt.tight_layout()

    output_path = output_dir / "solver_comparison.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_ablation_study(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Plot ablation study results as grouped bar chart.
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, "ablation", "ablation")
    if not aggregated:
        print("No ablation data found")
        return

    configs = list(aggregated.keys())
    metrics = ["throughput", "safety_violations", "mean_flowtime"]

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    # Pretty names for ablation configs
    config_names = {
        "full_system": "Full System",
        "no_local_replan": "No Local Replan",
        "no_conflict_resolution": "No Conflict Res.",
        "global_only": "Global Only (Tier-1)",
        "no_safety": "No Safety",
        "soft_safety": "Soft Safety",
    }

    for ax, metric in zip(axes, metrics):
        means = [aggregated[c].get(metric, (0, 0))[0] for c in configs]
        stds = [aggregated[c].get(metric, (0, 0))[1] for c in configs]

        x = range(len(configs))
        colors = [COLORS["primary"] if c == "full_system" else COLORS["secondary"]
                  for c in configs]

        bars = ax.bar(x, means, yerr=stds, capsize=4, color=colors)

        ax.set_xlabel("Configuration")
        ax.set_ylabel(METRIC_LABELS.get(metric, metric))
        ax.set_xticks(x)
        ax.set_xticklabels([config_names.get(c, c) for c in configs], rotation=30, ha="right")

    fig.suptitle("Ablation Study: Component Contributions", fontsize=14)
    plt.tight_layout()

    output_path = output_dir / "ablation_study.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_pareto_front(
    results: List[Dict[str, Any]],
    x_metric: str,
    y_metric: str,
    color_by: str,
    output_dir: Path,
) -> None:
    """
    Plot Pareto front showing trade-off between two metrics.
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    # Group by color_by parameter
    groups = defaultdict(list)
    for r in results:
        key = r.get(color_by, "unknown")
        groups[key].append(r)

    fig, ax = plt.subplots(figsize=(8, 6))

    for i, (label, group) in enumerate(groups.items()):
        x_values = [r.get(x_metric, 0) for r in group]
        y_values = [r.get(y_metric, 0) for r in group]

        color = COLOR_CYCLE[i % len(COLOR_CYCLE)]
        ax.scatter(x_values, y_values, label=str(label), color=color, alpha=0.7, s=50)

    ax.set_xlabel(METRIC_LABELS.get(x_metric, x_metric))
    ax.set_ylabel(METRIC_LABELS.get(y_metric, y_metric))
    ax.legend(title=PARAM_LABELS.get(color_by, color_by), loc="best")

    x_label = METRIC_LABELS.get(x_metric, x_metric)
    y_label = METRIC_LABELS.get(y_metric, y_metric)
    plt.title(f"Trade-off: {x_label} vs {y_label}")
    plt.tight_layout()

    output_path = output_dir / f"pareto_{x_metric}_vs_{y_metric}.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_human_density(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Plot effect of human density on performance.
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, "num_humans", "num_humans")
    if not aggregated:
        print("No human density data found")
        return

    values = sorted(aggregated.keys())

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    metrics = ["throughput", "safety_violations", "total_wait_steps"]

    for ax, metric in zip(axes, metrics):
        means = [aggregated[v].get(metric, (0, 0))[0] for v in values]
        stds = [aggregated[v].get(metric, (0, 0))[1] for v in values]

        ax.errorbar(values, means, yerr=_clip_yerr(means, stds), marker="o", capsize=4,
                    color=COLORS["primary"])
        ax.set_xlabel("Number of Humans")
        ax.set_ylabel(METRIC_LABELS.get(metric, metric))
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))

    fig.suptitle("Effect of Human Density", fontsize=14)
    plt.tight_layout()

    output_path = output_dir / "human_density.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def plot_safety_tradeoff(
    results: List[Dict[str, Any]],
    output_dir: Path,
) -> None:
    """
    Plot safety radius vs throughput/violations trade-off.
    """
    if not HAS_MATPLOTLIB:
        return

    plt.rcParams.update(PLOT_SETTINGS)

    aggregated = aggregate_by_value(results, "safety_radius", "safety_radius")
    if not aggregated:
        print("No safety radius data found")
        return

    values = sorted(aggregated.keys())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))

    # Throughput vs safety radius
    means = [aggregated[v].get("throughput", (0, 0))[0] for v in values]
    stds = [aggregated[v].get("throughput", (0, 0))[1] for v in values]
    ax1.errorbar(values, means, yerr=_clip_yerr(means, stds), marker="o", capsize=4,
                 color=COLORS["primary"])
    ax1.set_xlabel("Safety Radius (cells)")
    ax1.set_ylabel("Throughput (tasks/step)")
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))

    # Near misses vs safety radius (radius-independent metric: distance <= 1).
    # safety_violations is confounded — a larger radius counts more cells as
    # "in zone", making violations grow even when the system is safer.
    means = [aggregated[v].get("near_misses", (0, 0))[0] for v in values]
    stds = [aggregated[v].get("near_misses", (0, 0))[1] for v in values]
    ax2.errorbar(values, means, yerr=_clip_yerr(means, stds), marker="s", capsize=4,
                 color=COLORS["secondary"])
    ax2.set_xlabel("Safety Radius (cells)")
    ax2.set_ylabel(METRIC_LABELS.get("near_misses", "Near Misses (distance ≤ 1)"))
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))

    fig.suptitle("Safety Radius: Throughput vs Near Misses", fontsize=14)
    plt.tight_layout()

    output_path = output_dir / "safety_tradeoff.pdf"
    plt.savefig(output_path)
    plt.savefig(output_path.with_suffix(".png"))
    plt.close()
    print(f"Saved: {output_path}")


def generate_all_plots(results: List[Dict[str, Any]], output_dir: Path) -> None:
    """Generate all available plots from results."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find available sweeps
    sweeps = set(r.get("sweep") for r in results if r.get("sweep"))

    print(f"\nGenerating plots for sweeps: {sweeps}")

    # Sensitivity plots for each parameter sweep.
    # Use near_misses (always distance<=1, radius-independent) wherever a
    # safety metric is shown alongside safety_radius — safety_violations is
    # confounded because a larger radius counts more cells as "in zone".
    sensitivity_sweeps = {
        "replan_every": ["throughput", "mean_flowtime", "mean_planning_time_ms"],
        "safety_radius": ["throughput", "near_misses", "total_wait_steps"],
        "fov_radius": ["throughput", "near_misses", "mean_flowtime"],
        "horizon": ["throughput", "mean_flowtime", "mean_planning_time_ms"],
        "task_arrival_rate": ["throughput", "mean_flowtime", "completed_tasks"],
    }

    for sweep, metrics in sensitivity_sweeps.items():
        if sweep in sweeps:
            plot_sensitivity(results, sweep, sweep, metrics, output_dir)

    # Scalability
    if "num_agents" in sweeps:
        plot_scalability(results, output_dir)

    # Solver comparison
    if "solver" in sweeps:
        plot_solver_comparison(results, output_dir)

    # Ablation study
    if "ablation" in sweeps:
        plot_ablation_study(results, output_dir)

    # Human density
    if "num_humans" in sweeps:
        plot_human_density(results, output_dir)

    # Safety trade-off
    if "safety_radius" in sweeps:
        plot_safety_tradeoff(results, output_dir)

    # Pareto front (throughput vs near_misses — radius-independent safety metric)
    plot_pareto_front(
        results,
        x_metric="throughput",
        y_metric="near_misses",
        color_by="sweep",
        output_dir=output_dir,
    )

    print(f"\nAll plots saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate publication-quality plots from tuning results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Path to results.csv file",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for plots (default: same as input with /plots)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all available plots",
    )
    parser.add_argument(
        "--plot",
        type=str,
        choices=["sensitivity", "scalability", "solver", "ablation", "pareto", "human_density", "safety"],
        help="Generate specific plot type",
    )
    parser.add_argument(
        "--param",
        type=str,
        help="Parameter name for sensitivity plot",
    )
    parser.add_argument(
        "--x",
        type=str,
        default="throughput",
        help="X-axis metric for pareto plot",
    )
    parser.add_argument(
        "--y",
        type=str,
        default="safety_violations",
        help="Y-axis metric for pareto plot",
    )

    args = parser.parse_args()

    if not HAS_MATPLOTLIB:
        print("Error: matplotlib is required for plotting. Install with: pip install matplotlib")
        return

    # Load results
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {input_path}")
        return

    results = load_results(input_path)
    print(f"Loaded {len(results)} results from {input_path}")

    # Determine output directory
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = input_path.parent / "plots"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate plots
    if args.all:
        generate_all_plots(results, output_dir)

    elif args.plot == "sensitivity":
        if not args.param:
            print("Error: --param required for sensitivity plot")
            return
        metrics = ["throughput", "mean_flowtime", "safety_violations"]
        plot_sensitivity(results, args.param, args.param, metrics, output_dir)

    elif args.plot == "scalability":
        plot_scalability(results, output_dir)

    elif args.plot == "solver":
        plot_solver_comparison(results, output_dir)

    elif args.plot == "ablation":
        plot_ablation_study(results, output_dir)

    elif args.plot == "pareto":
        plot_pareto_front(results, args.x, args.y, "sweep", output_dir)

    elif args.plot == "human_density":
        plot_human_density(results, output_dir)

    elif args.plot == "safety":
        plot_safety_tradeoff(results, output_dir)

    else:
        print("Specify --all or --plot <type>")


if __name__ == "__main__":
    main()
