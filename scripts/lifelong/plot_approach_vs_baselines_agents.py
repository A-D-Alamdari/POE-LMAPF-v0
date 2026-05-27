#!/usr/bin/env python3
"""
Plot results from the Approach vs Baselines — Agent-Count Sweep Study.

Reads the CSV files produced by compare_approach_vs_baselines_agents.py and
generates publication-quality figures for each map separately.

Required plots per map
----------------------
  throughput vs number of agents
  task_completion vs number of agents
  planning_time vs number of agents
  safety_violations vs number of agents
  collisions_agent_human vs number of agents
  near_misses vs number of agents

Each plot shows one subplot per human-model setting, with lines/bars
for each solver (HA-LMAPF, RHCR). Error bands show 95%
confidence intervals across seeds.

Usage
-----
  # Plot from a completed run directory
  python scripts/lifelong/plot_approach_vs_baselines_agents.py \\
      --run-dir logs/lifelong/agents/baselines_agents_20260315_120000

  # Override output location
  python scripts/lifelong/plot_approach_vs_baselines_agents.py \\
      --run-dir logs/lifelong/agents/baselines_agents_20260315_120000 \\
      --output /tmp/my_figures

  # Specific format
  python scripts/lifelong/plot_approach_vs_baselines_agents.py \\
      --run-dir logs/lifelong/agents/baselines_agents_20260315_120000 --format pdf

Output
------
  <run-dir>/figures/
  ├── <map_tag>_throughput.png / .pdf
  ├── <map_tag>_task_completion.png / .pdf
  ├── <map_tag>_planning_time.png / .pdf
  ├── <map_tag>_safety_violations.png / .pdf
  ├── <map_tag>_collisions_agent_human.png / .pdf
  ├── <map_tag>_near_misses.png / .pdf
  └── convergence.png / .pdf
"""
from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("Warning: matplotlib not installed. pip install matplotlib")

# ---------------------------------------------------------------------------
# Publication-quality rcParams (matches repo style)
# ---------------------------------------------------------------------------

RC = {
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 11,
    "legend.fontsize": 8,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "lines.linewidth": 1.8,
    "lines.markersize": 6,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "errorbar.capsize": 3,
}

# Colorblind-safe (Wong 2011) palette — 2 distinct hues for 2 solvers
PALETTE = [
    "#0072B2",  # blue       — HA-LMAPF (ours)
    "#D55E00",  # vermillion — RHCR
]

# Marker styles for distinguishing solvers
MARKERS = ["o", "s"]

# Canonical solver order for consistent legend
SOLVER_ORDER = ["HA-LMAPF", "RHCR"]

# Human-readable labels for human model tags
HUMAN_MODEL_TITLES = {
    "random": "Random Walk",
    "aisle": "Aisle Follower",
    "mixed": "Mixed (50/50)",
}

# Human-readable map titles
MAP_TITLES = {
    "random": "Random (64\u00d764)",
    "warehouse_small": "Warehouse (small)",
}


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _cast(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def load_csv(path: Path) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({k: _cast(v) for k, v in row.items()})
    return rows


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_results(run_dir: Path) -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
    raw_path = run_dir / "raw" / "results.csv"
    summary_path = run_dir / "aggregated" / "summary.csv"

    raw = load_csv(raw_path) if raw_path.exists() else None
    summary = load_csv(summary_path) if summary_path.exists() else None

    if raw is None and summary is None:
        print(f"ERROR: No results found in {run_dir}")
        print(f"  Checked: {raw_path}")
        print(f"  Checked: {summary_path}")
    else:
        if raw is not None:
            print(f"  Loaded raw results: {len(raw)} rows from {raw_path}")
        if summary is not None:
            print(f"  Loaded summary:     {len(summary)} rows from {summary_path}")

    return raw, summary


def get_ordered_items(items: set, canonical_order: list) -> list:
    ordered = [x for x in canonical_order if x in items]
    ordered += sorted(items - set(canonical_order))
    return ordered


# ---------------------------------------------------------------------------
# Aggregate raw results if summary is not available
# ---------------------------------------------------------------------------

_T_CRIT_95: Dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 19: 2.093,
    24: 2.064, 29: 2.045, 49: 2.010, 99: 1.984,
}


def _t_val(n: int) -> float:
    df = n - 1
    if df in _T_CRIT_95:
        return _T_CRIT_95[df]
    if df >= 100:
        return 1.960
    return _T_CRIT_95[max(k for k in _T_CRIT_95 if k <= df)]


def aggregate_raw(
        raw: List[Dict[str, Any]],
        metric: str,
) -> Dict[Tuple[str, str, str, int], Tuple[float, float]]:
    grouped: Dict[tuple, List[float]] = defaultdict(list)
    for r in raw:
        if r.get("status") != "ok":
            continue
        key = (r["map_tag"], r["human_model_tag"], r["solver_label"], r["num_agents"])
        grouped[key].append(r.get(metric, 0))

    result = {}
    for key, vals in grouped.items():
        n = len(vals)
        mean_v = sum(vals) / n
        var = sum((v - mean_v) ** 2 for v in vals) / max(n - 1, 1)
        std_v = math.sqrt(var)
        ci95 = _t_val(n) * std_v / math.sqrt(n) if n >= 2 else 0.0
        result[key] = (mean_v, ci95)
    return result


def get_metric_data_from_summary(
        summary: List[Dict[str, Any]],
        metric: str,
) -> Dict[Tuple[str, str, str, int], Tuple[float, float]]:
    result = {}
    mean_col = f"{metric}_mean"
    ci95_col = f"{metric}_ci95"
    std_col = f"{metric}_std"
    for r in summary:
        key = (r["map_tag"], r["human_model_tag"], r["solver_label"], r["num_agents"])
        mean_v = r.get(mean_col, 0)
        err = r.get(ci95_col, r.get(std_col, 0))
        result[key] = (mean_v, err)
    return result


# ---------------------------------------------------------------------------
# Save helper
# ---------------------------------------------------------------------------

def _save(fig, path: Path, fmt: str = "png") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    if fmt != "pdf":
        fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)
    print(f"  Saved -> {path}")


# ---------------------------------------------------------------------------
# Percentage formatter
# ---------------------------------------------------------------------------

def _pct_formatter(ax) -> None:
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
    )


# ---------------------------------------------------------------------------
# Core plotting function
# ---------------------------------------------------------------------------

def plot_metric_for_map(
        map_tag: str,
        metric: str,
        ylabel: str,
        data: Dict[Tuple[str, str, str, int], Tuple[float, float]],
        out_dir: Path,
        fmt: str = "png",
        is_pct: bool = False,
) -> None:
    if not HAS_MPL:
        return
    plt.rcParams.update(RC)

    hm_tags = set()
    solver_labels = set()
    agent_counts = set()
    for (mt, hm, solver, n_agents), _ in data.items():
        if mt == map_tag:
            hm_tags.add(hm)
            solver_labels.add(solver)
            agent_counts.add(n_agents)

    if not hm_tags:
        return

    hm_list = get_ordered_items(hm_tags, ["random", "aisle", "mixed"])
    solver_list = get_ordered_items(solver_labels, SOLVER_ORDER)
    agent_list = sorted(agent_counts)

    n_panels = len(hm_list)
    fig, axes = plt.subplots(
        1, n_panels,
        figsize=(5.5 * n_panels, 4.0),
        squeeze=False,
        sharey=True,
    )

    for ci, hm in enumerate(hm_list):
        ax = axes[0][ci]
        for si, solver in enumerate(solver_list):
            xs, ys, es = [], [], []
            for n in agent_list:
                key = (map_tag, hm, solver, n)
                if key in data:
                    mean_v, err_v = data[key]
                    xs.append(n)
                    ys.append(mean_v)
                    es.append(err_v)

            if not xs:
                continue

            color = PALETTE[si % len(PALETTE)]
            marker = MARKERS[si % len(MARKERS)]
            ax.errorbar(
                xs, ys, yerr=es,
                label=solver, color=color, marker=marker,
                markerfacecolor=color, markeredgecolor=color,
            )
            ax.fill_between(
                xs,
                [y - e for y, e in zip(ys, es)],
                [y + e for y, e in zip(ys, es)],
                alpha=0.1, color=color,
            )

        ax.set_xlabel("Number of Agents")
        if ci == 0:
            ax.set_ylabel(ylabel)
        ax.set_title(HUMAN_MODEL_TITLES.get(hm, hm))
        if is_pct:
            _pct_formatter(ax)
        ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
        ax.legend(fontsize=7, loc="best")

    map_title = MAP_TITLES.get(map_tag, map_tag)
    fig.suptitle(f"{map_title} \u2014 {ylabel}", fontsize=13, y=1.02)
    plt.tight_layout()

    filename = f"{map_tag}_{metric}.{fmt}"
    _save(fig, out_dir / filename, fmt=fmt)


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

METRICS_TO_PLOT = [
    # (metric_key, ylabel, is_percentage)
    ("throughput", "Throughput (tasks/step)", False),
    ("task_completion", "Task Completion", True),
    ("mean_planning_time_ms", "Mean Planning Time (ms)", False),
    ("safety_violations", "Safety Violations", False),
    ("collisions_agent_human", "Agent\u2013Human Collisions", False),
    ("near_misses", "Near Misses", False),
]


# ---------------------------------------------------------------------------
# Convergence plot
# ---------------------------------------------------------------------------

def plot_convergence(
        run_dir: Path,
        out_dir: Path,
        fmt: str = "png",
) -> None:
    if not HAS_MPL:
        return

    conv_path = run_dir / "aggregated" / "convergence.csv"
    if not conv_path.exists():
        print("  Convergence plot skipped \u2014 no convergence.csv found.")
        return

    rows = load_csv(conv_path)
    if not rows:
        print("  Convergence plot skipped \u2014 empty convergence.csv.")
        return

    plt.rcParams.update(RC)

    maps_available = sorted({r["map_tag"] for r in rows})
    representative: Dict[str, Tuple[str, int]] = {}
    for mt in maps_available:
        agent_counts = sorted({r["num_agents"] for r in rows if r["map_tag"] == mt})
        hm_tags = sorted({r["human_model_tag"] for r in rows if r["map_tag"] == mt})
        if agent_counts and hm_tags:
            mid_agents = agent_counts[len(agent_counts) // 2]
            representative[mt] = (hm_tags[0], mid_agents)

    if not representative:
        return

    n_maps = len(representative)
    fig, axes = plt.subplots(
        1, n_maps,
        figsize=(5.0 * n_maps, 3.5),
        squeeze=False,
        sharey=True,
    )

    for mi, (mt, (hm, n_agents)) in enumerate(sorted(representative.items())):
        ax = axes[0][mi]
        solver_set = sorted({r["solver_label"] for r in rows
                             if r["map_tag"] == mt and r["human_model_tag"] == hm
                             and r["num_agents"] == n_agents})
        solver_list = get_ordered_items(set(solver_set), SOLVER_ORDER)

        for si, solver in enumerate(solver_list):
            steps, means, cis = [], [], []
            for r in rows:
                if (r["map_tag"] == mt and r["human_model_tag"] == hm
                        and r["solver_label"] == solver and r["num_agents"] == n_agents):
                    steps.append(r["step"])
                    means.append(r["throughput_mean"])
                    cis.append(r.get("throughput_ci95", 0))

            if not steps:
                continue

            order = sorted(range(len(steps)), key=lambda i: steps[i])
            steps = [steps[i] for i in order]
            means = [means[i] for i in order]
            cis = [cis[i] for i in order]

            color = PALETTE[si % len(PALETTE)]
            ax.plot(steps, means, label=solver, color=color, linewidth=1.5)
            ax.fill_between(
                steps,
                [m - c for m, c in zip(means, cis)],
                [m + c for m, c in zip(means, cis)],
                alpha=0.15, color=color,
            )

        map_title = MAP_TITLES.get(mt, mt)
        ax.set_title(f"{map_title}\n({n_agents} agents, {hm})", fontsize=9)
        ax.set_xlabel("Simulation Step")
        if mi == 0:
            ax.set_ylabel("Cumulative Throughput (tasks/step)")
        ax.legend(fontsize=7, loc="lower right")

    fig.suptitle("Throughput Convergence Over Simulation Steps", fontsize=12, y=1.02)
    plt.tight_layout()
    _save(fig, out_dir / f"convergence.{fmt}", fmt=fmt)


# ---------------------------------------------------------------------------
# Main plotting pipeline
# ---------------------------------------------------------------------------

def plot_all(
        run_dir: Path,
        out_dir: Optional[Path] = None,
        fmt: str = "png",
) -> None:
    if not HAS_MPL:
        print("ERROR: matplotlib is required. pip install matplotlib")
        return

    raw, summary = load_results(run_dir)
    if raw is None and summary is None:
        return

    if out_dir is None:
        out_dir = run_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    if summary is not None:
        all_maps = sorted({r["map_tag"] for r in summary})
    else:
        all_maps = sorted({r["map_tag"] for r in raw if r.get("status") == "ok"})

    print(f"\nGenerating plots for maps: {all_maps}")
    print(f"  Output directory: {out_dir}")

    for metric, ylabel, is_pct in METRICS_TO_PLOT:
        if summary is not None:
            data = get_metric_data_from_summary(summary, metric)
        else:
            data = aggregate_raw(raw, metric)

        for map_tag in all_maps:
            plot_metric_for_map(
                map_tag=map_tag,
                metric=metric,
                ylabel=ylabel,
                data=data,
                out_dir=out_dir,
                fmt=fmt,
                is_pct=is_pct,
            )

    plot_convergence(run_dir, out_dir, fmt=fmt)

    print(f"\nDone. Figures in: {out_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plot results from the Approach vs Baselines — Agent-Count Sweep.\n"
            "Reads CSV files from a completed run directory and generates "
            "per-map figures for throughput, task completion, planning time, "
            "safety violations, agent-human collisions, near misses, "
            "and throughput convergence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--run-dir", "-r",
        type=str,
        required=True,
        help="Path to a completed run directory under logs/lifelong/",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for figures (default: <run-dir>/figures/)",
    )
    parser.add_argument(
        "--format", "-f",
        type=str,
        default="png",
        choices=["png", "pdf", "svg"],
        help="Primary output format (default: png; PDF is always saved too)",
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"ERROR: run directory not found: {run_dir}")
        return 1

    out_dir = Path(args.output) if args.output else None

    plot_all(run_dir, out_dir=out_dir, fmt=args.format)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
