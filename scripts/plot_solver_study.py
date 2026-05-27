# !/usr/bin/env python3
"""
Plot results from the global solver selection study.

Reads the summary CSV files produced by run_solver_study.py (schema v2:
includes a map_tag column) and generates publication-quality figures for
publication.

Studies covered
---------------
  solver_baseline  – bar chart grid: solvers × metrics, faceted by map type
  scalability      – line chart grid: fleet size × metrics, one series per solver
  time_limit       – line chart grid: time budget × metrics, one series per solver

Usage
-----
  # Plot all studies from the default log directory
  python scripts/plot_solver_study.py --study all

  # Plot a single study
  python scripts/plot_solver_study.py --study solver_baseline

  # Point directly at a summary CSV
  python scripts/plot_solver_study.py --input logs/solver_study/summary_solver_baseline.csv

Output
------
  logs/solver_study/plots/
  ├── solver_baseline_performance.png / .pdf
  ├── solver_baseline_overhead.png    / .pdf
  ├── scalability_performance.png     / .pdf
  ├── scalability_overhead.png        / .pdf
  ├── time_limit_performance.png      / .pdf
  └── time_limit_overhead.png         / .pdf
"""
from __future__ import annotations

import argparse
import csv
import re
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
# Publication-quality rcParams
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

# Colorblind-safe (Wong 2011) palette — 7 distinct hues
PALETTE = [
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # green
    "#CC79A7",  # pink
    "#E69F00",  # amber
    "#56B4E9",  # sky blue
    "#F0E442",  # yellow (use last — low contrast on white)
]

MAP_TITLE = {
    "warehouse": "Warehouse",
    "room": "Room-divided",
    "random": "Random obstacles",
}

SOLVER_ORDER = ["lacam", "lacam3", "rt_lacam", "lns2", "pibt2", "pbs", "cbsh2"]


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


def find_summary(study: str, log_dir: Path) -> Optional[Path]:
    p = log_dir / f"summary_{study}.csv"
    return p if p.exists() else None


def _map_tags(rows: List[Dict[str, Any]]) -> List[str]:
    """Return map tags in canonical order (warehouse, room, random)."""
    seen = {r.get("map_tag", "unknown") for r in rows}
    order = ["warehouse", "room", "random"]
    return [t for t in order if t in seen] + sorted(seen - set(order))


# ---------------------------------------------------------------------------
# Save helper
# ---------------------------------------------------------------------------

def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    fig.savefig(path.with_suffix(".pdf"))
    plt.close(fig)
    print(f"  Saved → {path}")


# ---------------------------------------------------------------------------
# Percentage formatter
# ---------------------------------------------------------------------------

def _pct_formatter(ax) -> None:
    ax.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
    )


# ===========================================================================
# Study 1: solver_baseline
# ===========================================================================

def plot_solver_baseline(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    """
    Two figures, each a grid of subplots: rows = map type, cols = metric.

    Figure 1 (performance):  throughput | task_completion | mean_flowtime
    Figure 2 (overhead):     mean_planning_time_ms | p95_planning_time_ms | safety_violations
    """
    if not HAS_MPL:
        return
    plt.rcParams.update(RC)

    map_tags = _map_tags(rows)

    # Determine solver order (use canonical order, keep only those present)
    entries_seen = sorted({r["entry"] for r in rows})
    solvers = [s for s in SOLVER_ORDER if s in entries_seen]
    solvers += [s for s in entries_seen if s not in solvers]

    # Build lookup: (map_tag, entry) → row
    lookup: Dict[Tuple[str, str], Dict] = {
        (r["map_tag"], r["entry"]): r for r in rows
    }

    def _draw_grid(
            metric_specs: List[Tuple[str, str, bool]],  # (col_base, ylabel, is_pct)
            fig_path: Path,
            fig_title: str,
    ) -> None:
        n_rows, n_cols = len(map_tags), len(metric_specs)
        fig, axes = plt.subplots(
            n_rows, n_cols,
            figsize=(4.2 * n_cols, 3.5 * n_rows),
            squeeze=False,
        )

        x = list(range(len(solvers)))
        colors = [PALETTE[i % len(PALETTE)] for i in x]

        for ri, mt in enumerate(map_tags):
            for ci, (base, ylabel, is_pct) in enumerate(metric_specs):
                ax = axes[ri][ci]

                means = [lookup.get((mt, s), {}).get(f"{base}_mean", 0) for s in solvers]
                stds = [lookup.get((mt, s), {}).get(f"{base}_std", 0) for s in solvers]
                # Grey-out missing / zero entries
                colors_used = [
                    colors[i] if lookup.get((mt, s)) else "#cccccc"
                    for i, s in enumerate(solvers)
                ]

                ax.bar(x, means, yerr=stds, color=colors_used,
                       error_kw={"elinewidth": 1.0, "capthick": 1.0})

                if is_pct:
                    _pct_formatter(ax)
                ax.set_xticks(x)
                if ri == n_rows - 1:
                    ax.set_xticklabels(solvers, rotation=40, ha="right")
                else:
                    ax.set_xticklabels([])
                if ci == 0:
                    ax.set_ylabel(MAP_TITLE.get(mt, mt), fontweight="bold")
                if ri == 0:
                    ax.set_title(ylabel)

        fig.suptitle(fig_title, fontsize=13, y=1.01)
        plt.tight_layout()
        _save(fig, fig_path)

    _draw_grid(
        [
            ("throughput", "Throughput\n(tasks/step)", False),
            ("task_completion", "Task Completion", True),
            ("mean_flowtime", "Mean Flowtime (steps)", False),
        ],
        out_dir / "solver_baseline_performance.png",
        "Global Solver Comparison — Performance",
    )

    _draw_grid(
        [
            ("mean_planning_time_ms", "Mean Plan Time (ms)", False),
            ("p95_planning_time_ms", "P95 Plan Time (ms)", False),
            ("safety_violations", "Safety Violations", False),
        ],
        out_dir / "solver_baseline_overhead.png",
        "Global Solver Comparison — Overhead & Safety",
    )


# ===========================================================================
# Study 2: scalability
# ===========================================================================

def plot_scalability(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    """
    Two figures, each a grid: rows = map type, cols = metric.

    Figure 1 (performance):  throughput vs fleet size
    Figure 2 (overhead):     mean planning time vs fleet size
    """
    if not HAS_MPL:
        return
    plt.rcParams.update(RC)

    map_tags = _map_tags(rows)

    # Parse entries: "{solver}_a{n}"
    SolverData = Dict[int, Tuple[float, float]]  # agent_count → (mean, std)
    data: Dict[str, Dict[str, SolverData]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        m = re.match(r"^(.+)_a(\d+)$", r["entry"])
        if not m:
            continue
        solver, n = m.group(1), int(m.group(2))
        mt = r["map_tag"]
        data[mt][solver][n] = (
            r.get("throughput_mean", 0), r.get("throughput_std", 0),
        )

    # Also collect planning time
    pt_data: Dict[str, Dict[str, SolverData]] = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        m = re.match(r"^(.+)_a(\d+)$", r["entry"])
        if not m:
            continue
        solver, n = m.group(1), int(m.group(2))
        mt = r["map_tag"]
        pt_data[mt][solver][n] = (
            r.get("mean_planning_time_ms_mean", 0), r.get("mean_planning_time_ms_std", 0),
        )

    def _draw_grid(
            source: Dict[str, Dict[str, SolverData]],
            ylabel: str,
            fig_path: Path,
            fig_title: str,
            log_y: bool = False,
    ) -> None:
        n_rows = len(map_tags)
        fig, axes = plt.subplots(
            n_rows, 1,
            figsize=(6, 3.5 * n_rows),
            squeeze=False,
        )

        # Consistent solver order
        all_solvers = sorted({s for mt in source for s in source[mt]})
        solvers = [s for s in SOLVER_ORDER if s in all_solvers] + \
                  [s for s in all_solvers if s not in SOLVER_ORDER]

        for ri, mt in enumerate(map_tags):
            ax = axes[ri][0]
            mt_data = source.get(mt, {})

            for i, solver in enumerate(solvers):
                sdata = mt_data.get(solver, {})
                if not sdata:
                    continue
                ns = sorted(sdata)
                means = [sdata[n][0] for n in ns]
                stds = [sdata[n][1] for n in ns]
                c = PALETTE[i % len(PALETTE)]
                ax.errorbar(ns, means, yerr=stds, label=solver, color=c,
                            marker="o")
                if log_y:
                    ax.set_yscale("log")

            ax.set_ylabel(ylabel)
            ax.set_title(MAP_TITLE.get(mt, mt))
            ax.xaxis.set_major_locator(mticker.MaxNLocator(integer=True))
            ax.set_xlabel("Number of Agents")
            ax.legend(fontsize=8, ncol=2)

        fig.suptitle(fig_title, fontsize=13)
        plt.tight_layout()
        _save(fig, fig_path)

    _draw_grid(
        data, "Throughput (tasks/step)",
        out_dir / "scalability_throughput.png",
        "Scalability — Throughput vs Fleet Size",
    )
    _draw_grid(
        pt_data, "Mean Planning Time (ms)",
        out_dir / "scalability_planning_time.png",
        "Scalability — Planning Time vs Fleet Size",
        log_y=True,
    )


# ===========================================================================
# Study 3: time_limit
# ===========================================================================

def plot_time_limit(rows: List[Dict[str, Any]], out_dir: Path) -> None:
    """
    Two figures, each a grid: rows = map type, cols = metric.

    X-axis is planning time budget (seconds, log scale).
    One line per solver.
    """
    if not HAS_MPL:
        return
    plt.rcParams.update(RC)

    map_tags = _map_tags(rows)

    # Parse entries:
    #   "{solver}_t{val}s"   → time_limit in seconds
    #   "{solver}_t{val}ms"  → time_limit in ms, convert to seconds
    TData = Dict[float, Tuple[float, float]]  # time_sec → (mean, std)

    def _parse_time(entry: str) -> Tuple[Optional[str], Optional[float]]:
        m = re.match(r"^(.+)_t([\d.]+)(ms|s)$", entry)
        if not m:
            return None, None
        solver = m.group(1)
        val = float(m.group(2))
        unit = m.group(3)
        t_sec = val / 1000.0 if unit == "ms" else val
        return solver, t_sec

    thr_data: Dict[str, Dict[str, TData]] = defaultdict(lambda: defaultdict(dict))
    pt_data: Dict[str, Dict[str, TData]] = defaultdict(lambda: defaultdict(dict))

    for r in rows:
        solver, t_sec = _parse_time(r["entry"])
        if solver is None:
            continue
        mt = r["map_tag"]
        thr_data[mt][solver][t_sec] = (
            r.get("throughput_mean", 0), r.get("throughput_std", 0),
        )
        pt_data[mt][solver][t_sec] = (
            r.get("mean_planning_time_ms_mean", 0), r.get("mean_planning_time_ms_std", 0),
        )

    if not thr_data:
        print("  [time_limit] No parseable data found — skipping plot")
        return

    def _draw_grid(
            source: Dict[str, Dict[str, TData]],
            ylabel: str,
            fig_path: Path,
            fig_title: str,
    ) -> None:
        n_rows = len(map_tags)
        fig, axes = plt.subplots(
            n_rows, 1,
            figsize=(6, 3.5 * n_rows),
            squeeze=False,
        )

        all_solvers = sorted({s for mt in source for s in source[mt]})
        solvers = [s for s in SOLVER_ORDER if s in all_solvers] + \
                  [s for s in all_solvers if s not in SOLVER_ORDER]

        for ri, mt in enumerate(map_tags):
            ax = axes[ri][0]
            mt_data = source.get(mt, {})

            for i, solver in enumerate(solvers):
                sdata = mt_data.get(solver, {})
                if not sdata:
                    continue
                ts = sorted(sdata)
                means = [sdata[t][0] for t in ts]
                stds = [sdata[t][1] for t in ts]
                c = PALETTE[i % len(PALETTE)]
                ax.errorbar(ts, means, yerr=stds, label=solver, color=c,
                            marker="o")

            ax.set_xscale("log")
            ax.set_xlabel("Time Budget (s)")
            ax.set_ylabel(ylabel)
            ax.set_title(MAP_TITLE.get(mt, mt))
            ax.legend(fontsize=8, ncol=2)

        fig.suptitle(fig_title, fontsize=13)
        plt.tight_layout()
        _save(fig, fig_path)

    _draw_grid(
        thr_data, "Throughput (tasks/step)",
        out_dir / "time_limit_throughput.png",
        "Anytime Solver — Throughput vs Planning Budget",
    )
    _draw_grid(
        pt_data, "Mean Planning Time (ms)",
        out_dir / "time_limit_planning_time.png",
        "Anytime Solver — Planning Latency vs Budget",
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

PLOT_FN = {
    "solver_baseline": plot_solver_baseline,
    "scalability": plot_scalability,
    "time_limit": plot_time_limit,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot results from run_solver_study.py (schema v2 with map_tag)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--study", "-s",
        default="all",
        choices=list(PLOT_FN) + ["all"],
        help="Which study to plot (default: all)",
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Direct path to a summary CSV (overrides --study auto-detection)",
    )
    parser.add_argument(
        "--log-dir", "-l",
        type=str,
        default="logs/solver_study",
        help="Directory containing solver study CSVs (default: logs/solver_study)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output directory for plots (default: <log-dir>/plots)",
    )
    args = parser.parse_args()

    if not HAS_MPL:
        print("ERROR: matplotlib is required. pip install matplotlib")
        return 1

    log_dir = Path(args.log_dir)
    out_dir = Path(args.output) if args.output else log_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.input:
        p = Path(args.input)
        if not p.exists():
            print(f"ERROR: {p} not found")
            return 1
        for name in PLOT_FN:
            if name in p.name:
                print(f"Plotting {name} from {p}")
                PLOT_FN[name](load_csv(p), out_dir)
                return 0
        print(f"ERROR: cannot determine study type from {p.name}")
        return 1

    studies = list(PLOT_FN) if args.study == "all" else [args.study]

    for study in studies:
        p = find_summary(study, log_dir)
        if p is None:
            print(f"  [{study}] summary CSV not found in {log_dir} — skipping")
            continue
        print(f"Plotting {study} from {p}")
        rows = load_csv(p)
        if not rows:
            print(f"  [{study}] empty — skipping")
            continue
        PLOT_FN[study](rows, out_dir)

    print(f"\nDone. Plots in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
