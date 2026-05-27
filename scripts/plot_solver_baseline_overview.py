#!/usr/bin/env python3
"""
Single-figure overview of the Global Solver Baseline comparison.

Produces ONE figure with five side-by-side bar panels, each solver
given a unique color and error bars showing ±1 std:

  Panel 1  Throughput         (tasks/step)
  Panel 2  Task Completion    (%)
  Panel 3  Local Replans      (count)
  Panel 4  Mean Plan Time     (ms)
  Panel 5  Safety Violations  (count)

This replicates the style in the target image (Global Solver Baseline
Comparison) which is NOT produced by plot_solver_study.py.

Input
-----
  summary_solver_baseline.csv  produced by run_solver_study.py
  Columns expected:  entry, map_tag, {metric}_mean, {metric}_std, …

Usage
-----
  # Point at the run directory (finds summary_solver_baseline.csv automatically)
  python scripts/plot_solver_baseline_overview.py \\
      --log-dir logs/solver_study/run_20260313_165817 \\
      --output  logs/solver_study/run_20260313_165817/plots

  # Pass the CSV directly
  python scripts/plot_solver_baseline_overview.py \\
      --input logs/solver_study/run_20260313_165817/summary_solver_baseline.csv \\
      --output logs/solver_study/run_20260313_165817/plots

  # Only warehouse map rows
  python scripts/plot_solver_baseline_overview.py \\
      --log-dir logs/solver_study/run_20260313_165817 \\
      --map warehouse

  # Custom title and bar width
  python scripts/plot_solver_baseline_overview.py \\
      --log-dir logs/solver_study/run_20260313_165817 \\
      --title "My Solver Study" --bar-width 0.55
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
except ImportError:
    print("ERROR: matplotlib is required.  pip install matplotlib")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.labelsize": 11,
    "axes.titlesize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "errorbar.capsize": 4,
})

# 10 visually distinct colors (tab10); cycle if more solvers
TAB10 = [
    "#1f77b4",  # blue
    "#d62728",  # red
    "#2ca02c",  # green
    "#9467bd",  # purple
    "#ff7f0e",  # orange
    "#17becf",  # cyan
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # grey
    "#bcbd22",  # yellow-green
]

# Canonical left-to-right solver order (extend as needed)
SOLVER_ORDER = [
    "cbsh2", "lacam", "lacam3", "lns2", "pbs",
    "pibt2", "pylacam", "rhcr", "rt_lacam",
]

# The five panels — (csv_base_name, y_label, is_percent, higher_is_better)
PANELS: List[Tuple[str, str, bool, bool]] = [
    ("throughput", "Throughput\n(tasks/step)", False, True),
    ("task_completion", "Task\nCompletion", True, True),
    ("local_replans", "Local\nReplans", False, False),
    ("mean_planning_time_ms", "Mean Plan\nTime (ms)", False, False),
    ("safety_violations", "Safety\nViolations", False, False),
]


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
    with open(path, newline="") as f:
        return [{k: _cast(v) for k, v in row.items()} for row in csv.DictReader(f)]


def find_summary(log_dir: Path) -> Optional[Path]:
    candidates = [
        log_dir / "summary_solver_baseline.csv",
        log_dir / "summary_solver_study.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback: any summary_*.csv
    found = sorted(log_dir.glob("summary_*.csv"))
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _filter_map(rows: List[Dict], map_tag: Optional[str]) -> List[Dict]:
    if not map_tag:
        return rows
    filtered = [r for r in rows if r.get("map_tag", "") == map_tag]
    if not filtered:
        available = sorted({r.get("map_tag", "") for r in rows})
        print(f"WARNING: map_tag={map_tag!r} not found. "
              f"Available: {available}. Using all rows.")
        return rows
    return filtered


def _aggregate_maps(rows: List[Dict]) -> List[Dict]:
    """Average across map_tags for each entry (solver)."""
    from collections import defaultdict
    by_entry: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        by_entry[r["entry"]].append(r)

    out = []
    for entry, entry_rows in by_entry.items():
        agg: Dict[str, Any] = {"entry": entry, "map_tag": "all"}
        # Collect all numeric columns and average them
        keys = [k for k in entry_rows[0] if k not in ("entry", "map_tag")]
        for k in keys:
            vals = [r[k] for r in entry_rows if isinstance(r.get(k), (int, float))]
            if vals:
                agg[k] = sum(vals) / len(vals)
        out.append(agg)
    return out


def _solver_order(rows: List[Dict]) -> List[str]:
    present = {r["entry"] for r in rows}
    ordered = [s for s in SOLVER_ORDER if s in present]
    extras = sorted(present - set(ordered))
    return ordered + extras


# ---------------------------------------------------------------------------
# Main plot
# ---------------------------------------------------------------------------

def plot_overview(
        rows: List[Dict],
        out_dir: Path,
        map_tag: Optional[str] = None,
        title: str = "Global Solver Baseline Comparison",
        bar_width: float = 0.6,
        aggregate: bool = True,
) -> None:
    """Draw the 5-panel single-row overview figure."""

    # Filter / aggregate map tags
    if map_tag:
        plot_rows = _filter_map(rows, map_tag)
        subtitle = f"Map: {map_tag}"
    elif aggregate:
        n_maps = len({r.get("map_tag") for r in rows})
        if n_maps > 1:
            plot_rows = _aggregate_maps(rows)
            subtitle = f"Averaged over {n_maps} map types"
        else:
            plot_rows = rows
            subtitle = ""
    else:
        plot_rows = rows
        subtitle = ""

    solvers = _solver_order(plot_rows)
    n = len(solvers)
    if n == 0:
        print("ERROR: no solver entries found in data.")
        return

    # Assign one colour per solver (stable across panels)
    colors = {s: TAB10[i % len(TAB10)] for i, s in enumerate(solvers)}

    # Build lookup: solver → row
    lookup: Dict[str, Dict] = {r["entry"]: r for r in plot_rows}

    xs = list(range(n))
    n_panels = len(PANELS)

    fig, axes = plt.subplots(
        1, n_panels,
        figsize=(2.6 * n_panels + 1.0, 4.5),
    )

    for ax, (base, ylabel, is_pct, _) in zip(axes, PANELS):
        mean_col = f"{base}_mean"
        std_col = f"{base}_std"

        means = [float(lookup.get(s, {}).get(mean_col) or 0) for s in solvers]
        stds = [float(lookup.get(s, {}).get(std_col) or 0) for s in solvers]
        bar_colors = [colors[s] for s in solvers]

        bars = ax.bar(
            xs, means, yerr=stds,
            color=bar_colors,
            width=bar_width,
            error_kw={"elinewidth": 1.2, "capthick": 1.2, "ecolor": "black"},
            zorder=3,
        )

        # Percent formatter for task_completion
        if is_pct:
            ax.yaxis.set_major_formatter(
                mticker.FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
            )

        # Safety violations: dashed zero-line because some solvers may be 0
        if base == "safety_violations":
            ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.6)

        ax.set_xticks(xs)
        ax.set_xticklabels(solvers, rotation=40, ha="right")
        ax.set_ylabel(ylabel)
        ax.set_xlim(-0.6, n - 0.4)

        # Start y-axis from 0 unless data goes negative
        if min(means) >= 0:
            ax.set_ylim(bottom=0)

    # Title
    full_title = title
    if subtitle:
        full_title = f"{title}\n{subtitle}"
    fig.suptitle(full_title, fontsize=12, fontweight="bold", y=1.01)

    plt.tight_layout()

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "solver_baseline_overview"
    for ext in (".png", ".pdf"):
        p = out_dir / (stem + ext)
        fig.savefig(p)
        print(f"  Saved → {p}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="5-panel solver baseline overview (replicates target image)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i", type=str, default=None,
        help="Direct path to summary_solver_baseline.csv",
    )
    parser.add_argument(
        "--log-dir", "-l", type=str,
        default="logs/solver_study",
        help="Run directory containing summary_solver_baseline.csv "
             "(default: logs/solver_study)",
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Output directory (default: <log-dir>/plots)",
    )
    parser.add_argument(
        "--map", type=str, default=None,
        help="Filter to a single map_tag (e.g. warehouse). "
             "Default: average across all maps.",
    )
    parser.add_argument(
        "--no-aggregate", action="store_true",
        help="Do not average across maps; use all rows as-is "
             "(useful when only one map was run).",
    )
    parser.add_argument(
        "--title", type=str,
        default="Global Solver Baseline Comparison",
        help="Figure title.",
    )
    parser.add_argument(
        "--bar-width", type=float, default=0.6,
        help="Bar width (default: 0.6).",
    )
    args = parser.parse_args()

    # Locate CSV
    if args.input:
        csv_path = Path(args.input)
        if not csv_path.exists():
            print(f"ERROR: {csv_path} not found.")
            sys.exit(1)
    else:
        log_dir = Path(args.log_dir)
        csv_path = find_summary(log_dir)
        if csv_path is None:
            print(f"ERROR: no summary_solver_baseline.csv found in {log_dir}")
            print("  Pass the file directly with --input <path/to/summary.csv>")
            sys.exit(1)

    print(f"Reading: {csv_path}")
    rows = load_csv(csv_path)
    if not rows:
        print("ERROR: CSV is empty.")
        sys.exit(1)

    # Locate output directory
    if args.output:
        out_dir = Path(args.output)
    else:
        out_dir = Path(args.log_dir) / "plots"

    print(f"Output:  {out_dir}")

    plot_overview(
        rows,
        out_dir=out_dir,
        map_tag=args.map,
        title=args.title,
        bar_width=args.bar_width,
        aggregate=not args.no_aggregate,
    )


if __name__ == "__main__":
    main()
