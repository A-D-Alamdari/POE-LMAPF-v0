# !/usr/bin/env python3
"""Conference-quality plots for the sequential hyperparameter tuning pipeline.

Reads summary.csv files and generates:
  1. Line plots with 95% CI ribbons and Wilcoxon significance bars
  2. Violin plots showing full seed distributions
  3. Heatmaps (for grid sweeps) with cell annotations and best-cell stars
  4. Pareto scatter plots (throughput vs near_misses)
  5. LaTeX table of key results (if --latex flag set)

Color palette: IBM colorblind-safe (blue, orange, red, purple, green).

Usage:
    # Single-parameter sweep (line plots + violins)
    python scripts/tuning/plot_tuning.py \\
        logs/tuning/horizon/<timestamp>/summary.csv

    # Grid sweep (heatmaps + Pareto scatter)
    python scripts/tuning/plot_tuning.py \\
        logs/tuning/horizon_replan/<timestamp>/summary.csv --heatmap

    # Specify output dir
    python scripts/tuning/plot_tuning.py ... -o figures/tuning/

    # Plot raw results (violin plots require results.csv)
    python scripts/tuning/plot_tuning.py \\
        logs/tuning/horizon/<timestamp>/summary.csv \\
        --raw logs/tuning/horizon/<timestamp>/results.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ---------------------------------------------------------------------------
# IBM colorblind-safe palette (6 colors)
# ---------------------------------------------------------------------------
IBM_COLORS = [
    "#648FFF",  # blue
    "#FE6100",  # orange
    "#DC267F",  # magenta
    "#785EF0",  # purple
    "#FFB000",  # gold
    "#009E73",  # green (Okabe-Ito)
]

# ---------------------------------------------------------------------------
# Metrics to plot in line/violin panels (label, higher_better)
# ---------------------------------------------------------------------------
PANEL_METRICS: List[Tuple[str, str, bool]] = [
    ("throughput", "Throughput (tasks/step)", True),
    ("completed_tasks", "Completed Tasks", True),
    ("sum_of_costs", "Total Steps (sum of costs)", False),
    ("mean_path_cost", "Mean Path Cost (steps/task)", False),
    ("task_completion", "Task Completion Rate", True),
    ("mean_flowtime", "Mean Flowtime (steps)", False),
    ("near_misses", "Near Misses", False),
    ("safety_violations", "Safety Violations", False),
    ("mean_planning_time_ms", "Plan. Time (ms)", False),
    ("total_wait_steps", "Total Wait Steps", False),
]

SAFETY_METRICS: List[Tuple[str, str, bool]] = [
    ("near_misses", "Near Misses", False),
    ("safety_violations", "Safety Violations", False),
    ("collisions_agent_human", "Agent-Human Collisions", False),
    ("safety_violation_rate", "Violation Rate (/1000 steps)", False),
    ("total_wait_steps", "Total Wait Steps", False),
    ("human_passive_wait_steps", "Human Wait Steps", False),
]

ALLOCATION_METRICS: List[Tuple[str, str, bool]] = [
    ("throughput", "Throughput (tasks/step)", True),
    ("mean_flowtime", "Mean Flowtime (steps)", False),
    ("assignments_kept", "Assignments Kept", True),
    ("assignments_broken", "Assignments Broken", False),
    ("delay_events", "Delay Events", False),
    ("total_wait_steps", "Total Wait Steps", False),
]

# ---------------------------------------------------------------------------
# Significance threshold markers
# ---------------------------------------------------------------------------
SIG_LEVELS = [(0.001, "***"), (0.01, "**"), (0.05, "*")]


def _stars(p: float) -> str:
    if np.isnan(p):
        return ""
    for thresh, marker in SIG_LEVELS:
        if p < thresh:
            return marker
    return ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _cast(v: str):
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _derive_columns(row: Dict[str, Any]) -> Dict[str, Any]:
    """Add derived metrics that may be missing from older CSV files."""
    # Raw results row: derive mean_path_cost from sum_of_costs / completed_tasks
    if "mean_path_cost" not in row or row.get("mean_path_cost") in (None, ""):
        soc = _try_float(row.get("sum_of_costs", 0))
        ct = _try_float(row.get("completed_tasks", 0))
        row["mean_path_cost"] = soc / ct if ct > 0 else 0.0
    # Summary row: derive mean_path_cost_mean etc. from sum_of_costs / completed_tasks stats
    if "mean_path_cost_mean" not in row and "sum_of_costs_mean" in row:
        soc_mean = _try_float(row.get("sum_of_costs_mean", 0))
        ct_mean = _try_float(row.get("completed_tasks_mean", 0))
        mpc = soc_mean / ct_mean if ct_mean > 0 else 0.0
        row["mean_path_cost_mean"] = mpc
        # Approximate CI from sum_of_costs CI / completed_tasks mean
        for suffix in ("std", "ci95_lo", "ci95_hi"):
            soc_val = _try_float(row.get(f"sum_of_costs_{suffix}", 0))
            row[f"mean_path_cost_{suffix}"] = soc_val / ct_mean if ct_mean > 0 else 0.0
    return row


def load_csv(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(_derive_columns({k: _cast(v) for k, v in row.items()}))
    return rows


def _try_float(v) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return float("nan")


def _is_grid(rows: List[Dict]) -> bool:
    return "+" in str(rows[0].get("param", "")) if rows else False


def _sort_key(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return str(v)


# ---------------------------------------------------------------------------
# 1. Line plots with CI ribbon and significance annotation
# ---------------------------------------------------------------------------
def plot_line_sweep(
        rows: List[Dict[str, Any]],
        output_dir: Path,
        title_prefix: str = "",
        panel_metrics=PANEL_METRICS,
) -> None:
    if not rows:
        return
    param = rows[0]["param"]
    values = sorted({r["value"] for r in rows}, key=_sort_key)
    x = np.arange(len(values))
    x_labels = [str(v) for v in values]

    n_panels = len(panel_metrics)
    ncols = 3
    nrows = (n_panels + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4.5 * nrows))
    axes = np.array(axes).flatten()

    lookup = {r["value"]: r for r in rows}

    for idx, (metric, ylabel, higher_better) in enumerate(panel_metrics):
        ax = axes[idx]
        means, stds, ci_lo, ci_hi, ps, qs = [], [], [], [], [], []
        for v in values:
            r = lookup.get(v, {})
            means.append(r.get(f"{metric}_mean", float("nan")))
            stds.append(r.get(f"{metric}_std", float("nan")))
            ci_lo.append(r.get(f"{metric}_ci95_lo", float("nan")))
            ci_hi.append(r.get(f"{metric}_ci95_hi", float("nan")))
            ps.append(r.get(f"{metric}_wilcoxon_p", float("nan")))
            qs.append(r.get(f"{metric}_fdr_q", float("nan")))

        means = np.array(means, dtype=float)
        ci_lo = np.array(ci_lo, dtype=float)
        ci_hi = np.array(ci_hi, dtype=float)

        # Line + CI ribbon
        color = IBM_COLORS[idx % len(IBM_COLORS)]
        ax.plot(x, means, "o-", color=color, linewidth=2, markersize=6,
                label="mean")
        ax.fill_between(x, ci_lo, ci_hi, alpha=0.20, color=color,
                        label="95% CI")

        # Significance stars above each point (FDR-corrected)
        y_max = np.nanmax(ci_hi) if not np.all(np.isnan(ci_hi)) else np.nanmax(means)
        y_range = y_max - np.nanmin(means)
        for i, (p, q) in enumerate(zip(ps, qs)):
            s = _stars(q)  # use FDR-corrected q
            if s:
                ax.text(x[i], means[i] + 0.05 * y_range, s,
                        ha="center", va="bottom", fontsize=9, color="dimgray")

        # Highlight best value
        valid = ~np.isnan(means)
        if valid.any():
            best_idx = int(np.nanargmax(means) if higher_better
                           else np.nanargmin(means))
            ax.scatter([x[best_idx]], [means[best_idx]],
                       color="red", s=150, zorder=5, marker="*",
                       label="best")
            ax.axvline(x=best_idx, color="red", linestyle="--",
                       alpha=0.35, linewidth=1.2)

        ax.set_xticks(x)
        ax.set_xticklabels(x_labels,
                           rotation=45 if len(x_labels) > 5 else 0,
                           fontsize=9)
        ax.set_xlabel(param, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(ylabel, fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.25, linestyle="--")
        ax.legend(fontsize=8, loc="best")

    # Hide unused panels
    for idx in range(n_panels, len(axes)):
        axes[idx].set_visible(False)

    suptitle = f"{title_prefix}Sweep: {param}" if title_prefix else f"Sweep: {param}"
    fig.suptitle(suptitle + "\n(★ = best value; stars = FDR-corrected significance)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = output_dir / f"sweep_{param}_lines.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# 2. Violin plots (requires raw results.csv)
# ---------------------------------------------------------------------------
def plot_violin_sweep(
        summary_rows: List[Dict[str, Any]],
        raw_rows: List[Dict[str, Any]],
        output_dir: Path,
        title_prefix: str = "",
        panel_metrics=PANEL_METRICS,
) -> None:
    """Violin plots showing full seed distributions per parameter value."""
    if not raw_rows or not summary_rows:
        return
    param = summary_rows[0]["param"]
    values = sorted({r["value"] for r in summary_rows}, key=_sort_key)

    # Filter raw rows to match the summary group (solver/map/agents) if present
    filter_keys = ("solver", "map_tag", "num_agents")
    ref = summary_rows[0]
    if any(k in ref for k in filter_keys):
        filtered = []
        for r in raw_rows:
            if all(r.get(k) == ref.get(k) for k in filter_keys if k in ref):
                filtered.append(r)
        raw_rows = filtered if filtered else raw_rows

    # Group raw results by value
    by_value: Dict[Any, List[float]] = defaultdict(list)
    for r in raw_rows:
        by_value[r["value"]] = by_value.get(r["value"], [])

    # Rebuild with correct metric grouping
    def _get_vals(metric, val):
        return [float(r.get(metric, float("nan")))
                for r in raw_rows if r.get("value") == val]

    n_panels = len(panel_metrics)
    ncols = 3
    nrows = (n_panels + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4.5 * nrows))
    axes = np.array(axes).flatten()

    for idx, (metric, ylabel, higher_better) in enumerate(panel_metrics):
        ax = axes[idx]
        data_per_value = [
            [v for v in _get_vals(metric, val) if not np.isnan(v)]
            for val in values
        ]
        data_to_plot = [d if d else [float("nan")] for d in data_per_value]

        # Skip violin if any group has fewer than 2 valid points (KDE needs >1)
        can_violin = all(len(d) >= 2 and not all(np.isnan(d)) for d in data_to_plot)
        if not can_violin:
            # Fallback: strip plot (scatter) instead of violin
            for i, d in enumerate(data_to_plot):
                valid = [v for v in d if not np.isnan(v)]
                if valid:
                    jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(valid))
                    ax.scatter(i + jitter, valid,
                               color=IBM_COLORS[i % len(IBM_COLORS)],
                               alpha=0.6, s=30, zorder=3)
            parts = {}
        else:
            # Violin
            parts = ax.violinplot(data_to_plot, positions=range(len(values)),
                                  showmedians=True, showextrema=True)
        for i, pc in enumerate(parts.get("bodies", [])):
            pc.set_facecolor(IBM_COLORS[i % len(IBM_COLORS)])
            pc.set_alpha(0.6)
        for key in ("cbars", "cmins", "cmaxes", "cmedians"):
            if key in parts:
                parts[key].set_color("black")
                parts[key].set_linewidth(1.2)

        # Overlay mean + CI
        lookup = {r["value"]: r for r in summary_rows}
        for i, val in enumerate(values):
            r = lookup.get(val, {})
            mean = r.get(f"{metric}_mean", float("nan"))
            ci_lo = r.get(f"{metric}_ci95_lo", float("nan"))
            ci_hi = r.get(f"{metric}_ci95_hi", float("nan"))
            if not np.isnan(mean):
                ax.scatter([i], [mean], color="black", zorder=5, s=40,
                           marker="D")
            if not np.isnan(ci_lo) and not np.isnan(ci_hi):
                ax.plot([i, i], [ci_lo, ci_hi], color="black",
                        linewidth=2, zorder=4)

        ax.set_xticks(range(len(values)))
        ax.set_xticklabels([str(v) for v in values],
                           rotation=45 if len(values) > 5 else 0,
                           fontsize=9)
        ax.set_xlabel(param, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(ylabel, fontsize=11, fontweight="bold")
        ax.grid(True, alpha=0.25, linestyle="--", axis="y")

    for idx in range(n_panels, len(axes)):
        axes[idx].set_visible(False)

    suptitle = (f"{title_prefix}Distributions: {param}"
                if title_prefix else f"Distributions: {param}")
    fig.suptitle(suptitle + "\n(◆ = mean; bars = 95% CI)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = output_dir / f"sweep_{param}_violin.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# 3. Heatmaps for grid sweeps
# ---------------------------------------------------------------------------
HEATMAP_METRICS = [
    ("throughput", "Throughput (tasks/step)", True, "RdYlGn"),
    ("task_completion", "Task Completion Rate", True, "RdYlGn"),
    ("mean_flowtime", "Mean Flowtime (steps)", False, "RdYlGn_r"),
    ("near_misses", "Near Misses", False, "RdYlGn_r"),
    ("mean_planning_time_ms", "Plan. Time (ms)", False, "RdYlGn_r"),
]


def plot_grid_heatmap(
        rows: List[Dict[str, Any]],
        output_dir: Path,
        title_prefix: str = "",
) -> None:
    if not rows:
        return
    param = rows[0]["param"]
    parts = param.split("+")
    if len(parts) != 2:
        print(f"Cannot parse grid param '{param}' for heatmap.")
        return
    param_a, param_b = parts

    def _extract(r, key, fallback):
        if key in r:
            return _try_float(r[key])
        val_parts = str(r["value"]).split(",")
        if len(val_parts) == 2:
            return _try_float(val_parts[fallback])
        return float("nan")

    vals_a = sorted({_extract(r, param_a, 0) for r in rows},
                    key=lambda x: x if not np.isnan(x) else float("inf"))
    vals_b = sorted({_extract(r, param_b, 1) for r in rows},
                    key=lambda x: x if not np.isnan(x) else float("inf"))

    lookup = {}
    for r in rows:
        ka = _extract(r, param_a, 0)
        kb = _extract(r, param_b, 1)
        lookup[(ka, kb)] = r

    n_metrics = len(HEATMAP_METRICS)
    ncols = 2
    nrows = (n_metrics + 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(8 * ncols, 6 * nrows))
    axes = np.array(axes).flatten()

    for idx, (metric, label, higher_better, cmap) in enumerate(HEATMAP_METRICS):
        ax = axes[idx]
        col = f"{metric}_mean"
        grid = np.full((len(vals_b), len(vals_a)), np.nan)
        for i, va in enumerate(vals_a):
            for j, vb in enumerate(vals_b):
                r = lookup.get((va, vb))
                if r:
                    grid[j, i] = r.get(col, float("nan"))

        # Find best cell
        if higher_better:
            best_flat = np.nanargmax(grid)
        else:
            best_flat = np.nanargmin(grid)
        best_j, best_i = np.unravel_index(best_flat, grid.shape)

        im = ax.imshow(grid, aspect="auto", origin="lower", cmap=cmap,
                       interpolation="nearest")
        cbar = fig.colorbar(im, ax=ax, pad=0.02)
        cbar.set_label(label, fontsize=9)

        ax.set_xticks(range(len(vals_a)))
        ax.set_xticklabels([str(v) for v in vals_a], rotation=45, fontsize=9)
        ax.set_yticks(range(len(vals_b)))
        ax.set_yticklabels([str(v) for v in vals_b], fontsize=9)
        ax.set_xlabel(param_a, fontsize=10)
        ax.set_ylabel(param_b, fontsize=10)
        ax.set_title(label, fontsize=11, fontweight="bold")

        # Cell annotations with significance stars
        for i in range(len(vals_a)):
            for j in range(len(vals_b)):
                v = grid[j, i]
                if np.isnan(v):
                    continue
                r = lookup.get((vals_a[i], vals_b[j]))
                p = r.get(f"{metric}_wilcoxon_p", float("nan")) if r else float("nan")
                q = r.get(f"{metric}_fdr_q", float("nan")) if r else float("nan")
                fmt = f"{v:.3f}" if v < 10 else f"{v:.1f}"
                stars = _stars(q)
                cell_text = f"{fmt}{stars}"
                ax.text(i, j, cell_text, ha="center", va="center",
                        fontsize=7, color="black",
                        fontweight="bold" if (i == best_i and j == best_j) else "normal")

        # Mark best cell
        rect = plt.Rectangle((best_i - 0.5, best_j - 0.5), 1, 1,
                             linewidth=2.5, edgecolor="red",
                             facecolor="none")
        ax.add_patch(rect)

    for idx in range(n_metrics, len(axes)):
        axes[idx].set_visible(False)

    suptitle = (f"{title_prefix}Grid: {param_a} × {param_b}"
                if title_prefix else f"Grid: {param_a} × {param_b}")
    fig.suptitle(suptitle + "\n(red box = best cell; stars = FDR-corrected sig.)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    out_path = output_dir / f"grid_{param_a}_{param_b}_heatmap.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# 4. Pareto scatter plot
# ---------------------------------------------------------------------------
def plot_pareto_scatter(
        summary_rows: List[Dict[str, Any]],
        pareto_rows: Optional[List[Dict[str, Any]]],
        output_dir: Path,
        obj1: str = "throughput",
        obj2: str = "near_misses",
        title_prefix: str = "",
) -> None:
    if not summary_rows:
        return
    param = summary_rows[0]["param"]
    col1, col2 = f"{obj1}_mean", f"{obj2}_mean"

    fig, ax = plt.subplots(figsize=(8, 6))

    # All configurations (background)
    xs = [r.get(col1, float("nan")) for r in summary_rows]
    ys = [r.get(col2, float("nan")) for r in summary_rows]
    labels = [str(r["value"]) for r in summary_rows]

    ax.scatter(xs, ys, s=80, alpha=0.5, color=IBM_COLORS[0],
               zorder=2, label="all configs")
    for x, y, lbl in zip(xs, ys, labels):
        if not (np.isnan(x) or np.isnan(y)):
            ax.annotate(lbl, (x, y), textcoords="offset points",
                        xytext=(4, 4), fontsize=7, alpha=0.8)

    # Pareto front (overlay)
    if pareto_rows:
        px = [r.get(col1, float("nan")) for r in pareto_rows]
        py = [r.get(col2, float("nan")) for r in pareto_rows]
        # Sort by obj1 for staircase
        paired = sorted(zip(px, py), key=lambda t: t[0])
        px_s = [t[0] for t in paired]
        py_s = [t[1] for t in paired]
        ax.step(px_s, py_s, where="post", color=IBM_COLORS[1],
                linewidth=2, alpha=0.8, label="Pareto front")
        ax.scatter(px, py, s=160, color=IBM_COLORS[1], zorder=4,
                   marker="*", label="Pareto-optimal")

    # Labels
    obj1_label = obj1.replace("_", " ").title()
    obj2_label = obj2.replace("_", " ").title()
    ax.set_xlabel(f"{obj1_label} (↑ better)", fontsize=12)
    ax.set_ylabel(f"{obj2_label} (↓ better)", fontsize=12)
    suptitle = (f"{title_prefix}Safety-efficiency tradeoff: {param}"
                if title_prefix else f"Safety-efficiency tradeoff: {param}")
    ax.set_title(suptitle, fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.25, linestyle="--")

    fig.tight_layout()
    fname = f"pareto_{obj1}_vs_{obj2}.png"
    out_path = output_dir / fname
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# 5. Sensitivity / tornado plot
# ---------------------------------------------------------------------------
def plot_sensitivity(
        rows: List[Dict[str, Any]],
        output_dir: Path,
        metrics=None,
        title_prefix: str = "",
) -> None:
    """Tornado chart: range of each metric across the sweep."""
    if not rows:
        return
    if metrics is None:
        metrics = [m for m, _, _ in PANEL_METRICS]

    param = rows[0]["param"]
    ranges = []
    for metric in metrics:
        col = f"{metric}_mean"
        vals = [_try_float(r.get(col, float("nan"))) for r in rows]
        vals = [v for v in vals if not np.isnan(v)]
        if vals:
            ranges.append((metric, max(vals) - min(vals)))
        else:
            ranges.append((metric, 0.0))

    # Normalize to [0, 1]
    max_range = max(r for _, r in ranges) if ranges else 1.0
    if max_range == 0:
        return
    ranges_norm = [(m, r / max_range) for m, r in ranges]
    ranges_norm.sort(key=lambda x: x[1])

    fig, ax = plt.subplots(figsize=(8, 0.5 * len(ranges_norm) + 2))
    ys = range(len(ranges_norm))
    for y, (metric, rng) in zip(ys, ranges_norm):
        ax.barh(y, rng, color=IBM_COLORS[y % len(IBM_COLORS)], alpha=0.75)
        ax.text(rng + 0.01, y, f"{rng:.2f}", va="center", fontsize=9)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([m.replace("_", "\n") for m, _ in ranges_norm], fontsize=9)
    ax.set_xlabel("Normalized metric range across sweep", fontsize=11)
    ax.set_xlim(0, 1.15)
    suptitle = (f"{title_prefix}Sensitivity: {param}"
                if title_prefix else f"Sensitivity: {param}")
    ax.set_title(suptitle, fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.3, axis="x", linestyle="--")
    fig.tight_layout()

    out_path = output_dir / f"sensitivity_{param}.png"
    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot tuning results (conference quality)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "csv_files", nargs="+",
        help="Path(s) to summary.csv files",
    )
    parser.add_argument(
        "--raw", type=str, nargs="+", default=None,
        help="Path(s) to results.csv (raw per-seed) for violin plots",
    )
    parser.add_argument(
        "--pareto", type=str, nargs="+", default=None,
        help="Path(s) to pareto.csv files",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output directory (default: <csv_dir>/plots/)",
    )
    parser.add_argument(
        "--heatmap", action="store_true",
        help="Force heatmap mode for grid sweeps",
    )
    parser.add_argument(
        "--safety", action="store_true",
        help="Use safety-focused metric panels (for fov/safety sweeps)",
    )
    parser.add_argument(
        "--allocation", action="store_true",
        help="Use task-allocation metric panels (for commit_delay sweeps)",
    )
    parser.add_argument(
        "--prefix", type=str, default="",
        help="Title prefix for all plots",
    )
    args = parser.parse_args()

    panel_metrics = (
        SAFETY_METRICS if args.safety else
        ALLOCATION_METRICS if args.allocation else
        PANEL_METRICS
    )

    raw_files = args.raw or []
    pareto_files = args.pareto or []

    for csv_idx, csv_path_str in enumerate(args.csv_files):
        csv_path = Path(csv_path_str)
        if not csv_path.exists():
            print(f"Not found: {csv_path}")
            continue

        rows = load_csv(str(csv_path))
        if not rows:
            print(f"No data: {csv_path}")
            continue

        out_dir = Path(args.output) if args.output else csv_path.parent / "plots"
        out_dir.mkdir(parents=True, exist_ok=True)

        is_grid = _is_grid(rows)

        # Load raw results for violin plots
        raw_rows: List[Dict] = []
        if csv_idx < len(raw_files):
            raw_path = Path(raw_files[csv_idx])
            if raw_path.exists():
                raw_rows = load_csv(str(raw_path))
                print(f"Loaded raw data: {raw_path}")

        # Load Pareto front
        pareto_rows: List[Dict] = []
        if csv_idx < len(pareto_files):
            pf_path = Path(pareto_files[csv_idx])
            if pf_path.exists():
                pareto_rows = load_csv(str(pf_path))
                print(f"Loaded Pareto front: {pf_path}")
        else:
            # Try auto-detect pareto.csv in same directory
            auto_pf = csv_path.parent / "pareto.csv"
            if auto_pf.exists():
                pareto_rows = load_csv(str(auto_pf))
                print(f"Auto-detected Pareto: {auto_pf}")

        # Generate plots
        if args.heatmap or is_grid:
            plot_grid_heatmap(rows, out_dir, title_prefix=args.prefix)

        if not is_grid or not (args.heatmap):
            plot_line_sweep(rows, out_dir, title_prefix=args.prefix,
                            panel_metrics=panel_metrics)

        if raw_rows:
            plot_violin_sweep(rows, raw_rows, out_dir,
                              title_prefix=args.prefix,
                              panel_metrics=panel_metrics)

        # Pareto scatter (both configurations)
        plot_pareto_scatter(rows, pareto_rows or None, out_dir,
                            obj1="throughput", obj2="near_misses",
                            title_prefix=args.prefix)
        plot_pareto_scatter(rows, None, out_dir,
                            obj1="throughput", obj2="mean_flowtime",
                            title_prefix=args.prefix)

        # Sensitivity tornado
        if not is_grid:
            plot_sensitivity(rows, out_dir,
                             metrics=[m for m, _, _ in panel_metrics],
                             title_prefix=args.prefix)

    print(f"\nAll plots saved.")


if __name__ == "__main__":
    main()
