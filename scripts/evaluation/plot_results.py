# !/usr/bin/env python3
"""
Visualization and Analysis Script for HA-LMAPF Evaluation Results.

Reads CSV results produced by run_evaluation.py and generates
publication-quality figures for the paper's evaluation section.

Usage:
    python scripts/plot_results.py --results logs/eval --out figures/

Generates:
    1. Throughput vs Agents (scalability curve)
    2. Baseline comparison bar charts (throughput, safety, flowtime, wait)
    3. Planning time comparison (mean + p95 across baselines)
    4. Human density impact line plot
    5. Human model robustness grouped bar chart
    6. Map topology comparison
    7. Delay robustness curves (throughput/safety vs delay probability)
    8. Task arrival rate impact curves
    9. Component ablation study bars
   10. Scalability with planning time overlay
   11. Ablation results table (LaTeX)
   12. Baseline results table (LaTeX) with timing columns
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def load_results(csv_path: Path) -> List[Dict[str, str]]:
    """Load a results CSV into a list of row dicts."""
    rows = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def aggregate_by_key(
        rows: List[Dict[str, str]],
        group_key: str,
        metric: str,
) -> Dict[str, Tuple[float, float]]:
    """
    Group rows by group_key and compute mean +/- std of metric.
    Returns {group_value: (mean, std)}.
    """
    buckets: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        key = row.get(group_key, "")
        val = float(row.get(metric, 0))
        buckets[key].append(val)

    result = {}
    for k, vals in buckets.items():
        result[k] = (float(np.mean(vals)), float(np.std(vals)))
    return result


def _try_import_matplotlib():
    """Try to import matplotlib; return (plt, True) or (None, False)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams.update({
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "legend.fontsize": 10,
            "figure.figsize": (7, 5),
            "figure.dpi": 150,
        })
        return plt, True
    except ImportError:
        return None, False


# ---------------------------------------------------------------------------
# Plot functions
# ---------------------------------------------------------------------------

def _parse_scalability_rows(rows: List[Dict[str, str]]) -> Dict[str, Dict[int, List[Dict[str, str]]]]:
    """Group scalability rows by map tag and agent count.

    Returns {map_tag: {num_agents: [rows]}}.
    Supports both old format (scale_agents_N) and new format (scale_{map}_{N}).
    Uses the ``num_agents`` CSV column when available, otherwise falls back
    to parsing the experiment name.
    """
    result: Dict[str, Dict[int, List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        name = row.get("experiment", "")
        # Try to read num_agents column first
        if "num_agents" in row and row["num_agents"]:
            n = int(row["num_agents"])
        else:
            # Fallback: parse from experiment name
            n = int(name.split("_")[-1])

        # Determine map tag from experiment name
        if name.startswith("scale_agents_"):
            map_tag = "warehouse_large"
        elif name.startswith("scale_"):
            # scale_{map_tag}_{n} — map_tag may contain underscores
            parts = name[len("scale_"):].rsplit("_", 1)
            map_tag = parts[0] if len(parts) == 2 else "unknown"
        else:
            continue

        result[map_tag][n].append(row)
    return dict(result)


# Map tag display labels and colors for scalability plots
_SCALABILITY_STYLES: Dict[str, Tuple[str, str, str]] = {
    "random": ("Random 64×64", "#4CAF50", "o"),
    "warehouse_small": ("Warehouse Small", "#FF9800", "s"),
    "warehouse_large": ("Warehouse Large", "#2196F3", "^"),
}


def plot_scalability(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 1: Throughput vs Number of Agents (one line per map)."""
    csv_path = results_dir / "scalability" / "results.csv"
    if not csv_path.exists():
        print("  [skip] scalability results not found")
        return

    rows = load_results(csv_path)
    per_map = _parse_scalability_rows(rows)

    if not per_map:
        return

    fig, ax = plt.subplots(figsize=(9, 6))

    for map_tag in per_map:
        data = per_map[map_tag]
        agents = sorted(data.keys())
        means = [np.mean([float(r.get("throughput", 0)) for r in data[n]]) for n in agents]
        stds = [np.std([float(r.get("throughput", 0)) for r in data[n]]) for n in agents]

        label, color, marker = _SCALABILITY_STYLES.get(
            map_tag, (map_tag, "#607D8B", "x"))

        ax.errorbar(agents, means, yerr=stds, marker=marker, capsize=4,
                    linewidth=2, markersize=6, color=color, label=label)

    ax.set_xlabel("Number of Agents")
    ax.set_ylabel("Throughput (tasks/step)")
    ax.set_title("Scalability: Throughput vs Agent Count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_scalability.pdf")
    fig.savefig(out_dir / "fig_scalability.png")
    plt.close(fig)
    print("  [done] fig_scalability")


def plot_baselines(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 2: Baseline comparison grouped bar chart."""
    csv_path = results_dir / "baselines" / "results.csv"
    if not csv_path.exists():
        print("  [skip] baselines results not found")
        return

    rows = load_results(csv_path)

    metrics_to_plot = [
        ("throughput", "Throughput"),
        ("safety_violations", "Safety Violations"),
        ("mean_flowtime", "Mean Flowtime"),
        ("total_wait_steps", "Total Wait Steps"),
    ]

    baselines_order = ["ours", "global_only", "pibt_only", "rhcr", "whca_star", "ignore_humans"]
    baseline_labels = {
        "ours": "Ours (Two-Tier)",
        "global_only": "Global Only",
        "pibt_only": "PIBT Only",
        "rhcr": "RHCR",
        "whca_star": "WHCA*",
        "ignore_humans": "Ignore Humans",
    }

    for metric_key, metric_label in metrics_to_plot:
        agg = aggregate_by_key(rows, "baseline", metric_key)

        present = [b for b in baselines_order if b in agg]
        if not present:
            continue

        means = [agg[b][0] for b in present]
        stds = [agg[b][1] for b in present]
        labels = [baseline_labels.get(b, b) for b in present]

        colors = ["#4CAF50", "#FF9800", "#F44336", "#2196F3", "#673AB7", "#9C27B0"]

        fig, ax = plt.subplots()
        x = np.arange(len(present))
        bars = ax.bar(x, means, yerr=stds, capsize=4,
                      color=colors[:len(present)], alpha=0.85, edgecolor="black", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_ylabel(metric_label)
        ax.set_title(f"Baseline Comparison: {metric_label}")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()

        safe_name = metric_key.replace(" ", "_").lower()
        fig.savefig(out_dir / f"fig_baselines_{safe_name}.pdf")
        fig.savefig(out_dir / f"fig_baselines_{safe_name}.png")
        plt.close(fig)

    print("  [done] fig_baselines_*")


def plot_human_density(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 3: Impact of human density on throughput and safety."""
    csv_path = results_dir / "human_density" / "results.csv"
    if not csv_path.exists():
        print("  [skip] human_density results not found")
        return

    rows = load_results(csv_path)

    data_tput: Dict[int, List[float]] = defaultdict(list)
    data_safety: Dict[int, List[float]] = defaultdict(list)

    for row in rows:
        name = row.get("experiment", "")
        if "humans_" in name:
            h = int(name.split("_")[-1])
            data_tput[h].append(float(row.get("throughput", 0)))
            data_safety[h].append(float(row.get("safety_violation_rate", 0)))

    if not data_tput:
        return

    humans = sorted(data_tput.keys())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Throughput
    means = [np.mean(data_tput[h]) for h in humans]
    stds = [np.std(data_tput[h]) for h in humans]
    ax1.errorbar(humans, means, yerr=stds, marker="s", capsize=4,
                 linewidth=2, color="#4CAF50")
    ax1.set_xlabel("Number of Humans")
    ax1.set_ylabel("Throughput (tasks/step)")
    ax1.set_title("Throughput vs Human Density")
    ax1.grid(True, alpha=0.3)

    # Safety violation rate
    means = [np.mean(data_safety[h]) for h in humans]
    stds = [np.std(data_safety[h]) for h in humans]
    ax2.errorbar(humans, means, yerr=stds, marker="^", capsize=4,
                 linewidth=2, color="#F44336")
    ax2.set_xlabel("Number of Humans")
    ax2.set_ylabel("Safety Violations / 1000 steps")
    ax2.set_title("Safety Violation Rate vs Human Density")
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fig_human_density.pdf")
    fig.savefig(out_dir / "fig_human_density.png")
    plt.close(fig)
    print("  [done] fig_human_density")


def plot_human_models(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 4: Robustness across human motion models."""
    csv_path = results_dir / "human_models" / "results.csv"
    if not csv_path.exists():
        print("  [skip] human_models results not found")
        return

    rows = load_results(csv_path)

    model_labels = {
        "hmodel_random_walk": "Random Walk",
        "hmodel_aisle": "Aisle Follower",
        "hmodel_adversarial": "Adversarial",
        "hmodel_mixed": "Mixed",
    }

    metrics = [
        ("throughput", "Throughput"),
        ("safety_violation_rate", "Safety Viol./1000 steps"),
        ("mean_flowtime", "Mean Flowtime"),
    ]

    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 5))
    if len(metrics) == 1:
        axes = [axes]

    for ax, (mkey, mlabel) in zip(axes, metrics):
        agg = aggregate_by_key(rows, "experiment", mkey)
        present = [k for k in model_labels if k in agg]

        if not present:
            continue

        means = [agg[k][0] for k in present]
        stds = [agg[k][1] for k in present]
        labels = [model_labels[k] for k in present]

        x = np.arange(len(present))
        ax.bar(x, means, yerr=stds, capsize=4, alpha=0.85,
               color=["#4CAF50", "#2196F3", "#F44336", "#FF9800"][:len(present)],
               edgecolor="black", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15, ha="right")
        ax.set_ylabel(mlabel)
        ax.set_title(mlabel)
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Robustness to Human Motion Models", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_human_models.pdf", bbox_inches="tight")
    fig.savefig(out_dir / "fig_human_models.png", bbox_inches="tight")
    plt.close(fig)
    print("  [done] fig_human_models")


def plot_map_types(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 5: Performance across map topologies."""
    csv_path = results_dir / "map_types" / "results.csv"
    if not csv_path.exists():
        print("  [skip] map_types results not found")
        return

    rows = load_results(csv_path)
    agg_tput = aggregate_by_key(rows, "experiment", "throughput")
    agg_safety = aggregate_by_key(rows, "experiment", "safety_violation_rate")

    map_order = ["map_warehouse", "map_random", "map_room", "map_maze", "map_empty"]
    map_labels = {
        "map_warehouse": "Warehouse",
        "map_random": "Random 20%",
        "map_room": "Room",
        "map_maze": "Maze",
        "map_empty": "Empty",
    }

    present = [k for k in map_order if k in agg_tput]
    if not present:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    x = np.arange(len(present))
    labels = [map_labels.get(k, k) for k in present]

    # Throughput
    means = [agg_tput[k][0] for k in present]
    stds = [agg_tput[k][1] for k in present]
    ax1.bar(x, means, yerr=stds, capsize=4, color="#2196F3", alpha=0.85,
            edgecolor="black", linewidth=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15)
    ax1.set_ylabel("Throughput")
    ax1.set_title("Throughput by Map Topology")
    ax1.grid(True, axis="y", alpha=0.3)

    # Safety
    means = [agg_safety[k][0] for k in present]
    stds = [agg_safety[k][1] for k in present]
    ax2.bar(x, means, yerr=stds, capsize=4, color="#F44336", alpha=0.85,
            edgecolor="black", linewidth=0.5)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=15)
    ax2.set_ylabel("Safety Viol. / 1000 steps")
    ax2.set_title("Safety Violation Rate by Map")
    ax2.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fig_map_types.pdf")
    fig.savefig(out_dir / "fig_map_types.png")
    plt.close(fig)
    print("  [done] fig_map_types")


def plot_planning_time(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 6: Planning time comparison across baselines (mean + p95)."""
    csv_path = results_dir / "baselines" / "results.csv"
    if not csv_path.exists():
        print("  [skip] baselines results not found (planning time)")
        return

    rows = load_results(csv_path)

    baselines_order = ["ours", "global_only", "pibt_only", "rhcr", "whca_star", "ignore_humans"]
    baseline_labels = {
        "ours": "Ours",
        "global_only": "Global Only",
        "pibt_only": "PIBT Only",
        "rhcr": "RHCR",
        "whca_star": "WHCA*",
        "ignore_humans": "Ignore Humans",
    }

    agg_mean = aggregate_by_key(rows, "baseline", "mean_planning_time_ms")
    agg_p95 = aggregate_by_key(rows, "baseline", "p95_planning_time_ms")
    agg_decision = aggregate_by_key(rows, "baseline", "mean_decision_time_ms")

    present = [b for b in baselines_order if b in agg_mean]
    if not present:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    x = np.arange(len(present))
    labels = [baseline_labels.get(b, b) for b in present]
    width = 0.35

    # Planning time: mean + p95
    means_m = [agg_mean[b][0] for b in present]
    means_p95 = [agg_p95[b][0] for b in present]

    ax1.bar(x - width / 2, means_m, width, label="Mean", color="#2196F3",
            alpha=0.85, edgecolor="black", linewidth=0.5)
    ax1.bar(x + width / 2, means_p95, width, label="P95", color="#F44336",
            alpha=0.85, edgecolor="black", linewidth=0.5)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=20, ha="right")
    ax1.set_ylabel("Planning Time (ms)")
    ax1.set_title("Global Planning Time per Call")
    ax1.legend()
    ax1.grid(True, axis="y", alpha=0.3)

    # Decision latency
    means_dec = [agg_decision[b][0] for b in present]
    stds_dec = [agg_decision[b][1] for b in present]
    ax2.bar(x, means_dec, yerr=stds_dec, capsize=4, color="#4CAF50",
            alpha=0.85, edgecolor="black", linewidth=0.5)
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=20, ha="right")
    ax2.set_ylabel("Decision Time (ms/step)")
    ax2.set_title("Per-Step Decision Latency")
    ax2.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fig_planning_time.pdf")
    fig.savefig(out_dir / "fig_planning_time.png")
    plt.close(fig)
    print("  [done] fig_planning_time")


def plot_delay_robustness(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 7: Delay robustness — throughput and safety vs delay probability."""
    csv_path = results_dir / "delay_robustness" / "results.csv"
    if not csv_path.exists():
        print("  [skip] delay_robustness results not found")
        return

    rows = load_results(csv_path)

    data_tput: Dict[int, List[float]] = defaultdict(list)
    data_sv: Dict[int, List[float]] = defaultdict(list)
    data_delays: Dict[int, List[float]] = defaultdict(list)

    for row in rows:
        name = row.get("experiment", "")
        if "delay_" in name and "pct" in name:
            pct = int(name.split("_")[1].replace("pct", ""))
            data_tput[pct].append(float(row.get("throughput", 0)))
            data_sv[pct].append(float(row.get("safety_violation_rate", 0)))
            data_delays[pct].append(float(row.get("delay_events", 0)))

    if not data_tput:
        return

    pcts = sorted(data_tput.keys())

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # Throughput vs delay
    means = [np.mean(data_tput[p]) for p in pcts]
    stds = [np.std(data_tput[p]) for p in pcts]
    axes[0].errorbar(pcts, means, yerr=stds, marker="o", capsize=4,
                     linewidth=2, color="#2196F3")
    axes[0].set_xlabel("Execution Delay Probability (%)")
    axes[0].set_ylabel("Throughput (tasks/step)")
    axes[0].set_title("Throughput vs Delay Rate")
    axes[0].grid(True, alpha=0.3)

    # Safety violation rate vs delay
    means = [np.mean(data_sv[p]) for p in pcts]
    stds = [np.std(data_sv[p]) for p in pcts]
    axes[1].errorbar(pcts, means, yerr=stds, marker="^", capsize=4,
                     linewidth=2, color="#F44336")
    axes[1].set_xlabel("Execution Delay Probability (%)")
    axes[1].set_ylabel("Safety Violations / 1000 steps")
    axes[1].set_title("Safety Violation Rate vs Delay Rate")
    axes[1].grid(True, alpha=0.3)

    # Total delay events
    means = [np.mean(data_delays[p]) for p in pcts]
    stds = [np.std(data_delays[p]) for p in pcts]
    axes[2].errorbar(pcts, means, yerr=stds, marker="s", capsize=4,
                     linewidth=2, color="#FF9800")
    axes[2].set_xlabel("Execution Delay Probability (%)")
    axes[2].set_ylabel("Total Delay Events")
    axes[2].set_title("Injected Delay Events")
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fig_delay_robustness.pdf")
    fig.savefig(out_dir / "fig_delay_robustness.png")
    plt.close(fig)
    print("  [done] fig_delay_robustness")


def plot_arrival_rate(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 8: Task arrival rate impact on throughput and service time."""
    csv_path = results_dir / "arrival_rate" / "results.csv"
    if not csv_path.exists():
        print("  [skip] arrival_rate results not found")
        return

    rows = load_results(csv_path)

    data_tput: Dict[int, List[float]] = defaultdict(list)
    data_svc: Dict[int, List[float]] = defaultdict(list)
    data_comp: Dict[int, List[float]] = defaultdict(list)
    data_tc: Dict[int, List[float]] = defaultdict(list)

    for row in rows:
        name = row.get("experiment", "")
        if "arrival_rate_" in name:
            rate = int(name.split("_")[-1])
            data_tput[rate].append(float(row.get("throughput", 0)))
            data_svc[rate].append(float(row.get("mean_service_time", 0)))
            data_comp[rate].append(float(row.get("completed_tasks", 0)))
            data_tc[rate].append(float(row.get("task_completion", 0.)))

    if not data_tput:
        return

    rates = sorted(data_tput.keys())

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(1, 4, figsize=(16, 5))

    # Throughput
    means = [np.mean(data_tput[r]) for r in rates]
    stds = [np.std(data_tput[r]) for r in rates]
    ax1.errorbar(rates, means, yerr=stds, marker="o", capsize=4,
                 linewidth=2, color="#4CAF50")
    ax1.set_xlabel("Task Arrival Interval (steps)")
    ax1.set_ylabel("Throughput (tasks/step)")
    ax1.set_title("Throughput vs Task Arrival Rate")
    ax1.grid(True, alpha=0.3)

    # Service time
    means = [np.mean(data_svc[r]) for r in rates]
    stds = [np.std(data_svc[r]) for r in rates]
    ax2.errorbar(rates, means, yerr=stds, marker="s", capsize=4,
                 linewidth=2, color="#FF9800")
    ax2.set_xlabel("Task Arrival Interval (steps)")
    ax2.set_ylabel("Mean Service Time (steps)")
    ax2.set_title("Service Time vs Arrival Rate")
    ax2.grid(True, alpha=0.3)

    # Completed tasks
    means = [np.mean(data_comp[r]) for r in rates]
    stds = [np.std(data_comp[r]) for r in rates]
    ax3.errorbar(rates, means, yerr=stds, marker="^", capsize=4,
                 linewidth=2, color="#2196F3")
    ax3.set_xlabel("Task Arrival Interval (steps)")
    ax3.set_ylabel("Completed Tasks")
    ax3.set_title("Tasks Completed vs Arrival Rate")
    ax3.grid(True, alpha=0.3)

    means = [np.mean(data_tc[r]) for r in rates]
    stds = [np.std(data_tc[r]) for r in rates]
    ax3.errorbar(rates, means, yerr=stds, marker="^", capsize=4,
                 linewidth=2, color="#2196F3")
    ax4.set_xlabel("Task Arrival Interval (steps)")
    ax4.set_ylabel("Task Completion Percentage")
    ax4.set_title("Task Completion Percentage vs Arrival Rate")
    ax4.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "fig_arrival_rate.pdf")
    fig.savefig(out_dir / "fig_arrival_rate.png")
    plt.close(fig)
    print("  [done] fig_arrival_rate")


def plot_component_ablation(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 9: Component ablation — impact of disabling individual components."""
    csv_path = results_dir / "ablations" / "results.csv"
    if not csv_path.exists():
        print("  [skip] ablations results not found (component ablation)")
        return

    rows = load_results(csv_path)

    # Focus on component ablation entries
    ablation_keys = {
        "safety_hard": "Full System",
        "no_local_replan": "- Local Replan",
        "no_conflict_res": "- Conflict Res.",
        "no_safety_buffer": "- Safety Buffer",
        "safety_soft": "Soft Safety",
    }

    metrics_to_plot = [
        ("throughput", "Throughput", "#4CAF50"),
        ("safety_violation_rate", "Safety Viol./1000 steps", "#F44336"),
        ("mean_flowtime", "Mean Flowtime", "#FF9800"),
        ("intervention_rate", "Intervention Rate/1000 steps", "#9C27B0"),
    ]

    fig, axes = plt.subplots(1, len(metrics_to_plot), figsize=(5 * len(metrics_to_plot), 5.5))
    if len(metrics_to_plot) == 1:
        axes = [axes]

    for ax, (mkey, mlabel, color) in zip(axes, metrics_to_plot):
        agg = aggregate_by_key(rows, "experiment", mkey)
        present = [k for k in ablation_keys if k in agg]
        if not present:
            continue

        means = [agg[k][0] for k in present]
        stds = [agg[k][1] for k in present]
        labels = [ablation_keys[k] for k in present]

        x = np.arange(len(present))
        bars = ax.bar(x, means, yerr=stds, capsize=4, color=color,
                      alpha=0.85, edgecolor="black", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=9)
        ax.set_ylabel(mlabel)
        ax.set_title(mlabel)
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Component Ablation Study", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_component_ablation.pdf", bbox_inches="tight")
    fig.savefig(out_dir / "fig_component_ablation.png", bbox_inches="tight")
    plt.close(fig)
    print("  [done] fig_component_ablation")


def plot_scalability_with_timing(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 10: Scalability with planning time overlay (one subplot per map)."""
    csv_path = results_dir / "scalability" / "results.csv"
    if not csv_path.exists():
        print("  [skip] scalability results not found (timing overlay)")
        return

    rows = load_results(csv_path)
    per_map = _parse_scalability_rows(rows)

    if not per_map:
        return

    n_maps = len(per_map)
    fig, axes = plt.subplots(1, n_maps, figsize=(7 * n_maps, 5))
    if n_maps == 1:
        axes = [axes]

    for ax1, map_tag in zip(axes, per_map):
        data = per_map[map_tag]
        agents = sorted(data.keys())

        label, color, marker = _SCALABILITY_STYLES.get(
            map_tag, (map_tag, "#607D8B", "x"))

        means_t = [np.mean([float(r.get("throughput", 0)) for r in data[n]]) for n in agents]
        stds_t = [np.std([float(r.get("throughput", 0)) for r in data[n]]) for n in agents]
        means_p = [np.mean([float(r.get("mean_planning_time_ms", 0)) for r in data[n]]) for n in agents]
        means_95 = [np.mean([float(r.get("p95_planning_time_ms", 0)) for r in data[n]]) for n in agents]

        ax2 = ax1.twinx()

        ln1 = ax1.errorbar(agents, means_t, yerr=stds_t, marker=marker, capsize=4,
                           linewidth=2, color=color, label="Throughput")
        ax1.set_xlabel("Number of Agents")
        ax1.set_ylabel("Throughput (tasks/step)", color=color)
        ax1.tick_params(axis="y", labelcolor=color)

        ln2 = ax2.plot(agents, means_p, marker="s", linewidth=2, color="#F44336",
                       linestyle="--", label="Mean Plan Time")
        ln3 = ax2.plot(agents, means_95, marker="^", linewidth=2, color="#FF9800",
                       linestyle=":", label="P95 Plan Time")
        ax2.set_ylabel("Planning Time (ms)", color="#F44336")
        ax2.tick_params(axis="y", labelcolor="#F44336")

        lines = [ln1] + ln2 + ln3
        labs = [l.get_label() for l in lines]
        ax1.legend(lines, labs, loc="upper left", fontsize=8)

        ax1.set_title(label)
        ax1.grid(True, alpha=0.3)

    fig.suptitle("Scalability: Throughput and Planning Time vs Agent Count", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_scalability_timing.pdf", bbox_inches="tight")
    fig.savefig(out_dir / "fig_scalability_timing.png", bbox_inches="tight")
    plt.close(fig)
    print("  [done] fig_scalability_timing")


def plot_robustness(results_dir: Path, out_dir: Path, plt) -> None:
    """Fig 11: Robustness tests — narrow corridor, dense map, adversarial."""
    csv_path = results_dir / "robustness" / "results.csv"
    if not csv_path.exists():
        print("  [skip] robustness results not found")
        return

    rows = load_results(csv_path)

    scenario_labels = {
        "narrow_corridor": "Narrow Corridor",
        "dense_map": "Dense Map",
        "adversarial_humans": "Adversarial Humans",
    }

    metrics = [
        ("throughput", "Throughput"),
        ("safety_violation_rate", "Safety Viol./1000 steps"),
        ("mean_flowtime", "Mean Flowtime"),
        ("intervention_rate", "Intervention Rate/1000 steps"),
    ]

    fig, axes = plt.subplots(1, len(metrics), figsize=(5 * len(metrics), 5))
    if len(metrics) == 1:
        axes = [axes]

    colors = ["#2196F3", "#F44336", "#FF9800"]

    for ax, (mkey, mlabel) in zip(axes, metrics):
        agg = aggregate_by_key(rows, "experiment", mkey)
        present = [k for k in scenario_labels if k in agg]
        if not present:
            continue

        means = [agg[k][0] for k in present]
        stds = [agg[k][1] for k in present]
        labels = [scenario_labels[k] for k in present]

        x = np.arange(len(present))
        ax.bar(x, means, yerr=stds, capsize=4,
               color=colors[:len(present)], alpha=0.85,
               edgecolor="black", linewidth=0.5)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15, ha="right")
        ax.set_ylabel(mlabel)
        ax.set_title(mlabel)
        ax.grid(True, axis="y", alpha=0.3)

    fig.suptitle("Robustness Tests: Challenging Scenarios", y=1.02)
    fig.tight_layout()
    fig.savefig(out_dir / "fig_robustness.pdf", bbox_inches="tight")
    fig.savefig(out_dir / "fig_robustness.png", bbox_inches="tight")
    plt.close(fig)
    print("  [done] fig_robustness")


def generate_ablation_latex(results_dir: Path, out_dir: Path) -> None:
    """Generate LaTeX table for ablation study results."""
    csv_path = results_dir / "ablations" / "results.csv"
    if not csv_path.exists():
        print("  [skip] ablations results not found")
        return

    rows = load_results(csv_path)

    experiments = {}
    for row in rows:
        name = row.get("experiment", "")
        if name not in experiments:
            experiments[name] = []
        experiments[name].append(row)

    # Build table
    latex_lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Ablation study results (mean $\pm$ std over 5 seeds).}",
        r"\label{tab:ablation}",
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{l c c c c c}",
        r"\toprule",
        r"Configuration & Throughput & Mean Flowtime & Safety Viol. & Replans & Wait Steps \\",
        r"\midrule",
    ]

    label_map = {
        "safety_hard": r"\textbf{Full System (Hard Safety)}",
        "safety_soft": "Soft Safety",
        "solver_cbs": "CBS Solver",
        "solver_lacam": "LaCAM Solver",
        "allocator_greedy": "Greedy Alloc.",
        "allocator_hungarian": "Hungarian Alloc.",
        "allocator_auction": "Auction Alloc.",
        "comm_token": "Token Passing",
        "comm_priority": "Priority Rules",
        "no_local_replan": r"$-$ Local Replan",
        "no_conflict_res": r"$-$ Conflict Resolution",
        "no_safety_buffer": r"$-$ Safety Buffer",
    }

    for exp_name in [
        "safety_hard", "safety_soft",
        "no_local_replan", "no_conflict_res", "no_safety_buffer",
        "solver_cbs", "solver_lacam",
        "allocator_greedy", "allocator_hungarian", "allocator_auction",
        "comm_token", "comm_priority",
    ]:
        if exp_name not in experiments:
            continue
        exp_rows = experiments[exp_name]
        label = label_map.get(exp_name, exp_name)

        def _stat(key):
            vals = [float(r.get(key, 0)) for r in exp_rows]
            return np.mean(vals), np.std(vals)

        tput_m, tput_s = _stat("throughput")
        flow_m, flow_s = _stat("mean_flowtime")
        sv_m, sv_s = _stat("safety_violations")
        rep_m, rep_s = _stat("replans")
        wait_m, wait_s = _stat("total_wait_steps")

        latex_lines.append(
            f"{label} & {tput_m:.4f}$\\pm${tput_s:.4f} "
            f"& {flow_m:.1f}$\\pm${flow_s:.1f} "
            f"& {sv_m:.0f}$\\pm${sv_s:.0f} "
            f"& {rep_m:.0f}$\\pm${rep_s:.0f} "
            f"& {wait_m:.0f}$\\pm${wait_s:.0f} \\\\"
        )

    latex_lines.extend([
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table}",
    ])

    tex_path = out_dir / "table_ablation.tex"
    with open(tex_path, "w") as f:
        f.write("\n".join(latex_lines) + "\n")
    print(f"  [done] {tex_path}")


def generate_baseline_latex(results_dir: Path, out_dir: Path) -> None:
    """Generate LaTeX table for baseline comparison."""
    csv_path = results_dir / "baselines" / "results.csv"
    if not csv_path.exists():
        print("  [skip] baselines results not found")
        return

    rows = load_results(csv_path)

    baselines = {}
    for row in rows:
        bl = row.get("baseline", "")
        if bl not in baselines:
            baselines[bl] = []
        baselines[bl].append(row)

    latex_lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Comparison with baselines (mean $\pm$ std over 5 seeds, 20 agents, 5 humans).}",
        r"\label{tab:baselines}",
        r"\resizebox{\textwidth}{!}{%",
        r"\begin{tabular}{l c c c c c c c c}",
        r"\toprule",
        r"Method & Throughput$\uparrow$ & Flowtime$\downarrow$ & Safety Viol.$\downarrow$ "
        r"& Near Miss$\downarrow$ & Plan Time (ms) & P95 Plan (ms) & Replans & Wait$\downarrow$ \\",
        r"\midrule",
    ]

    bl_order = ["ours", "global_only", "pibt_only", "rhcr", "whca_star", "ignore_humans"]
    bl_labels = {
        "ours": r"\textbf{Ours (Two-Tier)}",
        "global_only": "Global Only",
        "pibt_only": "PIBT Only",
        "rhcr": "RHCR",
        "whca_star": "WHCA*",
        "ignore_humans": "Ignore Humans",
    }

    for bl in bl_order:
        if bl not in baselines:
            continue
        bl_rows = baselines[bl]
        label = bl_labels.get(bl, bl)

        def _stat(key):
            vals = [float(r.get(key, 0)) for r in bl_rows]
            return np.mean(vals), np.std(vals)

        tput_m, tput_s = _stat("throughput")
        flow_m, flow_s = _stat("mean_flowtime")
        sv_m, sv_s = _stat("safety_violations")
        nm_m, nm_s = _stat("near_misses")
        plan_m, plan_s = _stat("mean_planning_time_ms")
        p95_m, p95_s = _stat("p95_planning_time_ms")
        rep_m, rep_s = _stat("replans")
        wait_m, wait_s = _stat("total_wait_steps")

        latex_lines.append(
            f"{label} & {tput_m:.4f}$\\pm${tput_s:.4f} "
            f"& {flow_m:.1f}$\\pm${flow_s:.1f} "
            f"& {sv_m:.0f}$\\pm${sv_s:.0f} "
            f"& {nm_m:.0f}$\\pm${nm_s:.0f} "
            f"& {plan_m:.1f}$\\pm${plan_s:.1f} "
            f"& {p95_m:.1f}$\\pm${p95_s:.1f} "
            f"& {rep_m:.0f}$\\pm${rep_s:.0f} "
            f"& {wait_m:.0f}$\\pm${wait_s:.0f} \\\\"
        )

    latex_lines.extend([
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table*}",
    ])

    tex_path = out_dir / "table_baselines.tex"
    with open(tex_path, "w") as f:
        f.write("\n".join(latex_lines) + "\n")
    print(f"  [done] {tex_path}")


# ---------------------------------------------------------------------------
# Text-based fallback (no matplotlib)
# ---------------------------------------------------------------------------

def text_summary(results_dir: Path, out_dir: Path) -> None:
    """Generate a text summary when matplotlib is not available."""
    summary_path = out_dir / "results_summary.txt"

    with open(summary_path, "w") as f:
        f.write("=" * 70 + "\n")
        f.write("HA-LMAPF Evaluation Results Summary\n")
        f.write("=" * 70 + "\n\n")

        for group_dir in sorted(results_dir.iterdir()):
            csv_path = group_dir / "results.csv"
            if not csv_path.exists():
                continue

            rows = load_results(csv_path)
            if not rows:
                continue

            f.write(f"\n{'─' * 50}\n")
            f.write(f"Group: {group_dir.name}\n")
            f.write(f"{'─' * 50}\n")

            # Group by experiment+baseline
            groups: Dict[str, List[Dict]] = defaultdict(list)
            for row in rows:
                key = f"{row.get('experiment', '?')} | {row.get('baseline', '?')}"
                groups[key].append(row)

            for key in sorted(groups.keys()):
                g_rows = groups[key]

                def _stat(mkey):
                    vals = [float(r.get(mkey, 0)) for r in g_rows]
                    return np.mean(vals), np.std(vals)

                tput_m, tput_s = _stat("throughput")
                flow_m, flow_s = _stat("mean_flowtime")
                sv_m, sv_s = _stat("safety_violations")
                plan_m, _ = _stat("mean_planning_time_ms")
                p95_m, _ = _stat("p95_planning_time_ms")
                dec_m, _ = _stat("mean_decision_time_ms")

                f.write(
                    f"  {key:45s}  "
                    f"tput={tput_m:.4f}±{tput_s:.4f}  "
                    f"flow={flow_m:.1f}±{flow_s:.1f}  "
                    f"sv={sv_m:.0f}±{sv_s:.0f}  "
                    f"plan={plan_m:.1f}ms  "
                    f"p95={p95_m:.1f}ms  "
                    f"dec={dec_m:.2f}ms\n"
                )

    print(f"  [done] {summary_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Plot HA-LMAPF evaluation results")
    parser.add_argument("--results", type=str, default="logs/eval",
                        help="Directory containing evaluation results")
    parser.add_argument("--out", type=str, default="figures",
                        help="Output directory for figures")
    args = parser.parse_args()

    results_dir = Path(args.results)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        print("Run scripts/run_evaluation.py first.")
        return

    print("Generating evaluation figures...")

    plt, has_mpl = _try_import_matplotlib()

    if has_mpl:
        plot_scalability(results_dir, out_dir, plt)
        plot_baselines(results_dir, out_dir, plt)
        plot_planning_time(results_dir, out_dir, plt)
        plot_human_density(results_dir, out_dir, plt)
        plot_human_models(results_dir, out_dir, plt)
        plot_map_types(results_dir, out_dir, plt)
        plot_delay_robustness(results_dir, out_dir, plt)
        plot_arrival_rate(results_dir, out_dir, plt)
        plot_component_ablation(results_dir, out_dir, plt)
        plot_scalability_with_timing(results_dir, out_dir, plt)
        plot_robustness(results_dir, out_dir, plt)
    else:
        print("  [warn] matplotlib not available, generating text summary only")

    # LaTeX tables (always generated)
    generate_ablation_latex(results_dir, out_dir)
    generate_baseline_latex(results_dir, out_dir)

    # Text summary (always generated)
    text_summary(results_dir, out_dir)

    print(f"\nAll figures saved to {out_dir}/")


if __name__ == "__main__":
    main()
