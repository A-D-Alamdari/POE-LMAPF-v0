#!/usr/bin/env python3
"""Conference-quality ablation figures for HA-LMAPF.

Generates eight figure types from a summary.csv produced by
run_ablation_study.py:

  Fig 1  Grouped bar chart — throughput per group (main result)
  Fig 2  Safety panel — near_misses + collisions per group
  Fig 3  Efficiency panel — flowtime + wait-steps per group
  Fig 4  Forest plot — effect sizes (rank-biserial r) for all conditions
  Fig 5  Safety-efficiency scatter — Pareto view across conditions
  Fig 6  Comprehensive heatmap — all conditions × key metrics
  Fig 7  Within-group detail — one subplot per group (4-metric)
  Fig 8  Violin plots — seed distributions per condition (requires
         results.csv via --raw)
  Fig 9  Normality diagnostics — Shapiro-Wilk p-values for paired
         differences (justifies non-parametric choice)
  Fig 10 Power analysis — post-hoc power per condition × metric

Usage
-----
  # All figures from combined summary
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv

  # With raw data for violin plots
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      --raw logs/ablation/<ts>/results.csv

  # Custom output directory
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      -o figures/ablation/

  # Only specific figures
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      --figures 1 4 5 6
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
import matplotlib.gridspec as gridspec
import numpy as np

# ---------------------------------------------------------------------------
# Design constants
# ---------------------------------------------------------------------------
# IBM colorblind-safe colours (one per group A/B/C/D + extras)
GROUP_COLORS = {
    "A": "#648FFF",  # blue
    "B": "#DC267F",  # magenta
}
CTRL_COLOR = "#009E73"  # green — full_system control

# Matplotlib style
plt.rcParams.update({
    "font.family": "serif",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": "--",
})

CONTROL = "full_system"

GROUP_ORDER = ["A", "B"]
GROUP_LABELS = {
    "A": "Tier Architecture",
    "B": "Safety & Perception",
}

CONDITION_ORDER = [
    "full_system",
    "no_local_replan", "no_conflict_resolution", "global_only",
    "no_safety", "soft_safety",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _cast(v: str):
    for fn in (int, float):
        try:
            return fn(v)
        except ValueError:
            pass
    return v


def load_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="") as f:
        return [{k: _cast(v) for k, v in r.items()} for r in csv.DictReader(f)]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _sig_annotation(q: float) -> str:
    if np.isnan(q):
        return ""
    if q < 0.001:
        return "***"
    if q < 0.01:
        return "**"
    if q < 0.05:
        return "*"
    return "ns"


def _row_by_cond(rows: List[Dict], cond: str) -> Optional[Dict]:
    for r in rows:
        if r.get("condition") == cond:
            return r
    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _bar_with_ci(
        ax, x, mean, ci_lo, ci_hi, color, width=0.7,
        alpha=0.85, edgecolor="white", **kw
):
    bar = ax.bar(x, mean, width=width, color=color, alpha=alpha,
                 edgecolor=edgecolor, linewidth=0.8, **kw)
    if not (np.isnan(ci_lo) or np.isnan(ci_hi)):
        ax.errorbar(x, mean, yerr=[[mean - ci_lo], [ci_hi - mean]],
                    fmt="none", color="black", capsize=3, linewidth=1.2)
    return bar


def _annotate_sig(ax, x, y_top, stars: str, fontsize: int = 8):
    if stars and stars != "ns":
        ax.text(x, y_top * 1.01, stars, ha="center", va="bottom",
                fontsize=fontsize, color="dimgray", fontweight="bold")


def _build_order(rows: List[Dict]) -> List[Dict]:
    """Return rows in CONDITION_ORDER (skip missing)."""
    lookup = {r["condition"]: r for r in rows}
    return [lookup[c] for c in CONDITION_ORDER if c in lookup]


# ---------------------------------------------------------------------------
# Figure 1 — Grouped bar: throughput (main result)
# ---------------------------------------------------------------------------
def fig1_throughput_by_group(rows: List[Dict], out: Path) -> None:
    ordered = _build_order(rows)
    ctrl = _row_by_cond(rows, CONTROL)
    ctrl_mean = _f(ctrl.get("throughput_mean", float("nan"))) if ctrl else 1.0

    fig, ax = plt.subplots(figsize=(12, 5))

    xs, colors, labels, means, ci_los, ci_his, stars_list = [], [], [], [], [], [], []
    group_boundaries = {}
    prev_group = None
    x = 0
    for row in ordered:
        g = row.get("group", "A")
        if g != prev_group:
            group_boundaries[x] = g
            prev_group = g
        color = CTRL_COLOR if row["condition"] == CONTROL else GROUP_COLORS.get(g, "#888")
        mean = _f(row.get("throughput_mean", float("nan")))
        ci_lo = _f(row.get("throughput_ci95_lo", mean))
        ci_hi = _f(row.get("throughput_ci95_hi", mean))
        q = _f(row.get("throughput_fdr_q", float("nan")))
        xs.append(x)
        colors.append(color)
        labels.append(row.get("label", row["condition"]))
        means.append(mean)
        ci_los.append(ci_lo)
        ci_his.append(ci_hi)
        stars_list.append(_sig_annotation(q))
        x += 1

    for i, (xi, m, clo, chi, color, s) in enumerate(
            zip(xs, means, ci_los, ci_his, colors, stars_list)):
        _bar_with_ci(ax, xi, m, clo, chi, color)
        _annotate_sig(ax, xi, chi, s)

    # Reference line at full_system mean
    if not np.isnan(ctrl_mean):
        ax.axhline(ctrl_mean, color=CTRL_COLOR, linestyle="--",
                   linewidth=1.5, alpha=0.7, label="Full System")

    # Group background shading
    shade_x = 0
    shade_toggle = True
    prev_g = None
    for xi, row in zip(xs, ordered):
        g = row["group"]
        if g != prev_g:
            if prev_g is not None:
                ax.axvspan(shade_x - 0.5, xi - 0.5,
                           alpha=0.06 if shade_toggle else 0.0,
                           color=GROUP_COLORS.get(prev_g, "#888"), zorder=0)
                shade_toggle = not shade_toggle
            shade_x = xi
            prev_g = g
    ax.axvspan(shade_x - 0.5, max(xs) + 0.5,
               alpha=0.06 if shade_toggle else 0.0,
               color=GROUP_COLORS.get(prev_g, "#888"), zorder=0)

    # Group labels at top
    grp_starts: Dict[str, int] = {}
    grp_ends: Dict[str, int] = {}
    for xi, row in zip(xs, ordered):
        g = row["group"]
        if g not in grp_starts:
            grp_starts[g] = xi
        grp_ends[g] = xi

    y_max = ax.get_ylim()[1]
    for g in GROUP_ORDER:
        if g in grp_starts:
            mid = (grp_starts[g] + grp_ends[g]) / 2
            ax.text(mid, ax.get_ylim()[1] * 0.98,
                    f"Group {g}\n{GROUP_LABELS[g]}",
                    ha="center", va="top", fontsize=8,
                    color=GROUP_COLORS.get(g, "#888"), fontweight="bold")

    # Legend for significance
    legend_handles = [
        mpatches.Patch(color=CTRL_COLOR, label="Full System (control)"),
        mpatches.Patch(color=GROUP_COLORS["A"], label="Group A: Architecture"),
        mpatches.Patch(color=GROUP_COLORS["B"], label="Group B: Safety"),
    ]
    ax.legend(handles=legend_handles, loc="upper right", fontsize=8)

    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=8)
    ax.set_ylabel("Throughput (tasks / step)", fontsize=11)
    ax.set_title(
        "Fig. 1 — Ablation Study: Throughput\n"
        "(* bar = best; stars above = FDR-corrected significance vs Full System)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlim(-0.6, max(xs) + 0.6)

    fig.tight_layout()
    p = out / "fig1_throughput_by_group.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 2 — Safety panel: near_misses + collisions
# ---------------------------------------------------------------------------
def fig2_safety_panel(rows: List[Dict], out: Path) -> None:
    ordered = _build_order(rows)
    safety_metrics = [
        ("near_misses", "Near Misses"),
        ("collisions_agent_human", "Agent-Human Collisions"),
        ("safety_violations", "Safety Violations"),
        ("safety_violation_rate", "Violation Rate (/1000 steps)"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    axes = axes.flatten()

    for idx, (metric, title) in enumerate(safety_metrics):
        ax = axes[idx]
        for xi, row in enumerate(ordered):
            g = row.get("group", "A")
            color = CTRL_COLOR if row["condition"] == CONTROL \
                else GROUP_COLORS.get(g, "#888")
            mean = _f(row.get(f"{metric}_mean", float("nan")))
            clo = _f(row.get(f"{metric}_ci95_lo", mean))
            chi = _f(row.get(f"{metric}_ci95_hi", mean))
            q = _f(row.get(f"{metric}_fdr_q", float("nan")))
            _bar_with_ci(ax, xi, mean, clo, chi, color)
            _annotate_sig(ax, xi, chi, _sig_annotation(q))

        ax.set_xticks(range(len(ordered)))
        ax.set_xticklabels(
            [r.get("label", r["condition"]) for r in ordered],
            rotation=45, ha="right", fontsize=7,
        )
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(title)

    fig.suptitle(
        "Fig. 2 — Ablation Study: Safety Metrics\n"
        "(lower is safer; stars = FDR-corrected vs Full System)",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = out / "fig2_safety_panel.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 3 — Efficiency panel: flowtime + wait steps
# ---------------------------------------------------------------------------
def fig3_efficiency_panel(rows: List[Dict], out: Path) -> None:
    ordered = _build_order(rows)
    eff_metrics = [
        ("mean_flowtime", "Mean Flowtime (steps)"),
        ("total_wait_steps", "Total Wait Steps"),
        ("mean_planning_time_ms", "Mean Planning Time (ms)"),
        ("intervention_rate", "Intervention Rate (/1000 steps)"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    axes = axes.flatten()

    for idx, (metric, title) in enumerate(eff_metrics):
        ax = axes[idx]
        for xi, row in enumerate(ordered):
            g = row.get("group", "A")
            color = CTRL_COLOR if row["condition"] == CONTROL \
                else GROUP_COLORS.get(g, "#888")
            mean = _f(row.get(f"{metric}_mean", float("nan")))
            clo = _f(row.get(f"{metric}_ci95_lo", mean))
            chi = _f(row.get(f"{metric}_ci95_hi", mean))
            q = _f(row.get(f"{metric}_fdr_q", float("nan")))
            _bar_with_ci(ax, xi, mean, clo, chi, color)
            _annotate_sig(ax, xi, chi, _sig_annotation(q))

        ax.set_xticks(range(len(ordered)))
        ax.set_xticklabels(
            [r.get("label", r["condition"]) for r in ordered],
            rotation=45, ha="right", fontsize=7,
        )
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(title)

    fig.suptitle(
        "Fig. 3 — Ablation Study: Efficiency Metrics\n"
        "(lower is better; stars = FDR-corrected vs Full System)",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = out / "fig3_efficiency_panel.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 4 — Forest plot: effect sizes (rank-biserial r)
# ---------------------------------------------------------------------------
def fig4_effect_size_forest(rows: List[Dict], out: Path) -> None:
    """Horizontal lollipop chart of rank-biserial r for key metrics."""
    metrics_shown = [
        ("throughput", "Throughput ↑", True),
        ("near_misses", "Near Misses ↓", False),
        ("mean_flowtime", "Mean Flowtime ↓", False),
        ("total_wait_steps", "Wait Steps ↓", False),
        ("mean_planning_time_ms", "Planning Time ↓", False),
    ]

    # Only non-control conditions
    conds = [r for r in _build_order(rows) if r["condition"] != CONTROL]

    n_conds = len(conds)
    n_metrics = len(metrics_shown)
    fig, axes = plt.subplots(
        1, n_metrics, figsize=(3.5 * n_metrics, 0.45 * n_conds + 2),
        sharey=True,
    )
    if n_metrics == 1:
        axes = [axes]

    y_pos = range(n_conds)
    y_labels = [r.get("label", r["condition"]) for r in conds]
    y_groups = [r.get("group", "A") for r in conds]

    for ax, (metric, title, higher_better) in zip(axes, metrics_shown):
        rs = [_f(r.get(f"{metric}_effect_r", float("nan"))) for r in conds]
        qs = [_f(r.get(f"{metric}_fdr_q", float("nan"))) for r in conds]
        colors = [GROUP_COLORS.get(g, "#888") for g in y_groups]

        for yi, (r_val, q_val, color) in enumerate(zip(rs, qs, colors)):
            if np.isnan(r_val):
                continue
            # Positive r for a "good" direction metric
            plot_r = r_val if higher_better else -r_val
            ax.plot([0, plot_r], [yi, yi], color=color, linewidth=1.5,
                    alpha=0.7)
            marker = "o" if abs(r_val) >= 0.1 else "^"
            ax.scatter([plot_r], [yi], color=color, s=60, zorder=4,
                       marker=marker)
            sig = _sig_annotation(q_val)
            if sig and sig != "ns":
                ax.text(plot_r + 0.02, yi, sig, va="center", fontsize=7,
                        color="dimgray")

        ax.axvline(0, color="black", linewidth=0.8, linestyle="-")
        ax.axvline(-0.3, color="gray", linewidth=0.5, linestyle=":")
        ax.axvline(0.3, color="gray", linewidth=0.5, linestyle=":")
        ax.axvline(-0.5, color="gray", linewidth=0.5, linestyle="--")
        ax.axvline(0.5, color="gray", linewidth=0.5, linestyle="--")
        ax.set_xlabel("Rank-biserial r\n(+ve = better than Full System)",
                      fontsize=8)
        ax.set_title(title, fontweight="bold", fontsize=9)
        ax.set_xlim(-1.1, 1.1)
        ax.set_yticks(list(y_pos))
        ax.set_yticklabels(y_labels, fontsize=8)
        # Shade regions
        ax.axvspan(-0.1, 0.1, alpha=0.05, color="gray")
        ax.axvspan(0.3, 1.1, alpha=0.05, color="green")
        ax.axvspan(-1.1, -0.3, alpha=0.05, color="red")

    # Legend
    legend_els = [
        mpatches.Patch(color=GROUP_COLORS["A"], label="Group A"),
        mpatches.Patch(color=GROUP_COLORS["B"], label="Group B"),
    ]
    axes[-1].legend(handles=legend_els, loc="lower right", fontsize=8)

    fig.suptitle(
        "Fig. 4 — Effect Sizes (rank-biserial r) vs Full System\n"
        "dotted=small (|r|=0.1)  dashed=large (|r|=0.5)",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = out / "fig4_effect_size_forest.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 5 — Safety-efficiency scatter (Pareto view)
# ---------------------------------------------------------------------------
def fig5_safety_efficiency_scatter(rows: List[Dict], out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    scatter_pairs = [
        ("throughput_mean", "Throughput ↑",
         "near_misses_mean", "Near Misses ↓"),
        ("throughput_mean", "Throughput ↑",
         "mean_flowtime_mean", "Mean Flowtime ↓"),
    ]

    for ax, (xm, xl, ym, yl) in zip(axes, scatter_pairs):
        ordered = _build_order(rows)
        xs = [_f(r.get(xm)) for r in ordered]
        ys = [_f(r.get(ym)) for r in ordered]
        colors = [
            CTRL_COLOR if r["condition"] == CONTROL
            else GROUP_COLORS.get(r.get("group", "A"), "#888")
            for r in ordered
        ]
        for xi, yi, color, row in zip(xs, ys, colors, ordered):
            if np.isnan(xi) or np.isnan(yi):
                continue
            marker = "*" if row["condition"] == CONTROL else "o"
            size = 200 if row["condition"] == CONTROL else 80
            ax.scatter([xi], [yi], color=color, s=size, marker=marker,
                       zorder=4, alpha=0.85, edgecolors="white", linewidths=0.5)
            ax.annotate(
                row.get("label", "")[:12],
                (xi, yi), textcoords="offset points",
                xytext=(5, 3), fontsize=6.5, alpha=0.9,
            )

        ax.set_xlabel(xl, fontsize=10)
        ax.set_ylabel(yl, fontsize=10)
        ax.set_title(f"{xl.split('↑')[0].strip()} vs {yl.split('↓')[0].strip()}",
                     fontweight="bold")

        # Pareto front (maximise x, minimise y)
        valid = [(xi, yi) for xi, yi in zip(xs, ys)
                 if not (np.isnan(xi) or np.isnan(yi))]
        valid.sort(key=lambda p: p[0], reverse=True)
        pareto = []
        best_y = float("inf")
        for vx, vy in valid:
            if vy < best_y:
                pareto.append((vx, vy))
                best_y = vy
        if len(pareto) > 1:
            px, py = zip(*sorted(pareto, key=lambda p: p[0]))
            ax.step(px, py, where="post", color="gray",
                    linewidth=1.5, linestyle="--", alpha=0.6,
                    label="Pareto front")
            ax.legend(fontsize=8)

    # Group legend
    legend_handles = [
        mpatches.Patch(color=CTRL_COLOR, label="Full System"),
        mpatches.Patch(color=GROUP_COLORS["A"], label="Group A"),
        mpatches.Patch(color=GROUP_COLORS["B"], label="Group B"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=3,
               bbox_to_anchor=(0.5, -0.03), fontsize=8)

    fig.suptitle(
        "Fig. 5 — Safety-Efficiency Trade-off Across Ablation Conditions",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.95])
    p = out / "fig5_safety_efficiency_scatter.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 6 — Heatmap: all conditions × key metrics
# ---------------------------------------------------------------------------
def fig6_comprehensive_heatmap(rows: List[Dict], out: Path) -> None:
    ordered = _build_order(rows)
    ctrl = _row_by_cond(rows, CONTROL)

    heatmap_metrics = [
        ("throughput", "Throughput ↑", True),
        ("mean_flowtime", "Flowtime ↓", False),
        ("near_misses", "Near Misses ↓", False),
        ("safety_violations", "SafetyViol ↓", False),
        ("collisions_agent_human", "H-Collisions ↓", False),
        ("total_wait_steps", "Wait Steps ↓", False),
        ("mean_planning_time_ms", "Plan Time ↓", False),
        ("local_replans", "Local Replans ↓", False),
        ("intervention_rate", "Interv. Rate ↓", False),
        ("assignments_broken", "Assign. Broken ↓", False),
    ]

    n_cond = len(ordered)
    n_met = len(heatmap_metrics)
    # Build matrix of percent-change vs control
    matrix = np.full((n_cond, n_met), float("nan"))
    sig_matrix = np.full((n_cond, n_met), False)

    ctrl_means = {}
    if ctrl:
        for metric, _, _ in heatmap_metrics:
            ctrl_means[metric] = _f(ctrl.get(f"{metric}_mean", float("nan")))

    for ri, row in enumerate(ordered):
        for ci, (metric, _, higher_better) in enumerate(heatmap_metrics):
            m = _f(row.get(f"{metric}_mean", float("nan")))
            ref = ctrl_means.get(metric, float("nan"))
            if not (np.isnan(m) or np.isnan(ref) or ref == 0):
                pct = (m - ref) / abs(ref) * 100.0
                # For "lower is better" metrics, flip sign so green=good
                matrix[ri, ci] = pct if higher_better else -pct
            q = _f(row.get(f"{metric}_fdr_q", float("nan")))
            sig_matrix[ri, ci] = (not np.isnan(q)) and (q < 0.05)

    vmax = np.nanpercentile(np.abs(matrix), 90)
    vmax = max(vmax, 5.0)

    fig, ax = plt.subplots(figsize=(n_met * 1.5 + 2, n_cond * 0.55 + 2))
    im = ax.imshow(
        matrix, aspect="auto", cmap="RdYlGn",
        vmin=-vmax, vmax=vmax, interpolation="nearest",
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02, shrink=0.8)
    cbar.set_label("% change vs Full System\n(green = better)", fontsize=9)

    # Annotations
    for ri in range(n_cond):
        for ci in range(n_met):
            v = matrix[ri, ci]
            text = f"{v:+.1f}" if not np.isnan(v) else "–"
            star = "*" if sig_matrix[ri, ci] else ""
            color = "white" if abs(v) > 0.6 * vmax else "black"
            ax.text(ci, ri, f"{text}{star}", ha="center", va="center",
                    fontsize=6.5, color=color)

    ax.set_xticks(range(n_met))
    ax.set_xticklabels(
        [m[1] for m in heatmap_metrics],
        rotation=40, ha="right", fontsize=8,
    )
    ax.set_yticks(range(n_cond))
    ax.set_yticklabels(
        [r.get("label", r["condition"]) for r in ordered],
        fontsize=8,
    )

    # Group dividers
    prev_g = None
    for ri, row in enumerate(ordered):
        g = row.get("group", "A")
        if g != prev_g and ri > 0:
            ax.axhline(ri - 0.5, color="white", linewidth=2.5)
        prev_g = g

    # Group labels on left margin (via text outside axes)
    prev_g = None
    g_start = 0
    for ri, row in enumerate(ordered):
        g = row.get("group", "A")
        if g != prev_g:
            if prev_g is not None:
                mid = (g_start + ri - 1) / 2
                ax.text(-0.7, mid, f"G{prev_g}", ha="center", va="center",
                        fontsize=9, color=GROUP_COLORS.get(prev_g, "#888"),
                        fontweight="bold", transform=ax.transData)
            g_start = ri
            prev_g = g
    if prev_g:
        mid = (g_start + len(ordered) - 1) / 2
        ax.text(-0.7, mid, f"G{prev_g}", ha="center", va="center",
                fontsize=9, color=GROUP_COLORS.get(prev_g, "#888"),
                fontweight="bold", transform=ax.transData)

    ax.set_title(
        "Fig. 6 — Comprehensive Ablation Heatmap\n"
        "(% change vs Full System; green = improvement; * = FDR-sig. p<0.05)",
        fontsize=11, fontweight="bold", pad=12,
    )
    fig.tight_layout()
    p = out / "fig6_comprehensive_heatmap.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 7 — Within-group 4-metric bar panels
# ---------------------------------------------------------------------------
def fig7_within_group_panels(rows: List[Dict], out: Path) -> None:
    group_metrics = {
        "A": [
            ("throughput", "Throughput ↑"),
            ("near_misses", "Near Misses ↓"),
            ("total_wait_steps", "Wait Steps ↓"),
            ("local_replans", "Local Replans"),
        ],
        "B": [
            ("near_misses", "Near Misses ↓"),
            ("collisions_agent_human", "H-Collisions ↓"),
            ("throughput", "Throughput ↑"),
            ("safety_violation_rate", "Violation Rate ↓"),
        ],
        "C": [
            ("throughput", "Throughput ↑"),
            ("mean_flowtime", "Flowtime ↓"),
            ("assignments_broken", "Assign. Broken ↓"),
            ("delay_events", "Delay Events"),
        ],
        "D": [
            ("throughput", "Throughput ↑"),
            ("local_replans", "Local Replans"),
            ("near_misses", "Near Misses ↓"),
            ("total_wait_steps", "Wait Steps ↓"),
        ],
    }

    groups_present = sorted({r.get("group", "A") for r in rows})
    n_groups = len(groups_present)
    fig = plt.figure(figsize=(14, 4.5 * n_groups))
    outer = gridspec.GridSpec(n_groups, 1, hspace=0.55)

    for gi, group in enumerate(groups_present):
        grp_rows = [r for r in _build_order(rows)
                    if r.get("group") == group or r["condition"] == CONTROL]
        # De-duplicate CONTROL (may appear multiple times across groups)
        seen = set()
        grp_rows = [r for r in grp_rows
                    if r["condition"] not in seen
                    and not seen.add(r["condition"])]

        metrics = group_metrics.get(group, [])
        inner = gridspec.GridSpecFromSubplotSpec(
            1, len(metrics), subplot_spec=outer[gi], hspace=0.1, wspace=0.4,
        )

        for mi, (metric, title) in enumerate(metrics):
            ax = fig.add_subplot(inner[mi])
            for xi, row in enumerate(grp_rows):
                color = CTRL_COLOR if row["condition"] == CONTROL \
                    else GROUP_COLORS.get(group, "#888")
                mean = _f(row.get(f"{metric}_mean", float("nan")))
                clo = _f(row.get(f"{metric}_ci95_lo", mean))
                chi = _f(row.get(f"{metric}_ci95_hi", mean))
                q = _f(row.get(f"{metric}_fdr_q", float("nan")))
                _bar_with_ci(ax, xi, mean, clo, chi, color, width=0.6)
                _annotate_sig(ax, xi, chi if not np.isnan(chi) else mean,
                              _sig_annotation(q))

            ax.set_xticks(range(len(grp_rows)))
            ax.set_xticklabels(
                [r.get("label", "")[:10] for r in grp_rows],
                rotation=40, ha="right", fontsize=7,
            )
            ax.set_title(title, fontsize=9, fontweight="bold")
            if mi == 0:
                ax.set_ylabel(
                    f"Group {group}: {GROUP_LABELS.get(group, '')}",
                    fontsize=9, color=GROUP_COLORS.get(group, "#888"),
                )

    fig.suptitle(
        "Fig. 7 — Within-Group Ablation Details\n"
        "(95% CI bars; stars = FDR-corrected significance vs Full System)",
        fontsize=12, fontweight="bold",
    )
    p = out / "fig7_within_group_panels.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 8 — Violin plots (requires raw results.csv)
# ---------------------------------------------------------------------------
def fig8_violin_distributions(
        summary_rows: List[Dict],
        raw_rows: List[Dict],
        out: Path,
) -> None:
    if not raw_rows:
        print("  Skipping Fig 8 (no raw results; pass --raw results.csv)")
        return

    metrics_to_plot = [
        ("throughput", "Throughput ↑"),
        ("near_misses", "Near Misses ↓"),
        ("mean_flowtime", "Mean Flowtime ↓"),
        ("total_wait_steps", "Wait Steps ↓"),
    ]

    ordered = _build_order(summary_rows)
    n_cond = len(ordered)
    labels = [r.get("label", r["condition"]) for r in ordered]

    by_cond: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in raw_rows:
        cond = row.get("condition", "")
        for metric, _ in metrics_to_plot:
            v = _f(row.get(metric, float("nan")))
            if not np.isnan(v):
                by_cond[cond][metric].append(v)

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    axes = axes.flatten()

    for idx, (metric, title) in enumerate(metrics_to_plot):
        ax = axes[idx]
        data = [by_cond[r["condition"]][metric] or [float("nan")]
                for r in ordered]
        parts = ax.violinplot(
            data, positions=range(n_cond),
            showmedians=True, showextrema=True,
        )
        for i, (pc, row) in enumerate(zip(parts["bodies"], ordered)):
            g = row.get("group", "A")
            color = CTRL_COLOR if row["condition"] == CONTROL \
                else GROUP_COLORS.get(g, "#888")
            pc.set_facecolor(color)
            pc.set_alpha(0.55)
        for key in ("cbars", "cmins", "cmaxes", "cmedians"):
            if key in parts:
                parts[key].set_linewidth(1.2)
                parts[key].set_color("black")

        # Overlay mean + 95-CI
        for xi, row in enumerate(ordered):
            m = _f(row.get(f"{metric}_mean", float("nan")))
            clo = _f(row.get(f"{metric}_ci95_lo", m))
            chi = _f(row.get(f"{metric}_ci95_hi", m))
            if not np.isnan(m):
                ax.scatter([xi], [m], color="black", s=35, zorder=5,
                           marker="D")
            if not (np.isnan(clo) or np.isnan(chi)):
                ax.plot([xi, xi], [clo, chi], color="black",
                        linewidth=1.8, zorder=4)

        ax.set_xticks(range(n_cond))
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
        ax.set_title(title, fontweight="bold")
        ax.set_ylabel(title)

    fig.suptitle(
        "Fig. 8 — Seed Distributions Across Ablation Conditions\n"
        "(◆ = mean; vertical bar = 95% CI; violin = per-seed distribution)",
        fontsize=12, fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    p = out / "fig8_violin_distributions.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 9 — Normality diagnostics (Shapiro-Wilk on paired differences)
# ---------------------------------------------------------------------------
def fig9_normality_diagnostics(rows: List[Dict], out: Path) -> None:
    """Heatmap of Shapiro-Wilk p-values on paired differences.

    Justifies using non-parametric Wilcoxon when p < 0.05 (non-normal).
    """
    metrics_shown = [
        "throughput", "near_misses", "mean_flowtime",
        "total_wait_steps", "mean_planning_time_ms",
        "collisions_agent_human", "safety_violations",
        "local_replans", "assignments_broken",
    ]
    conds = [r for r in _build_order(rows) if r["condition"] != CONTROL]
    if not conds:
        print("  Skipping Fig 9 (no ablation conditions)")
        return

    n_cond = len(conds)
    n_met = len(metrics_shown)
    matrix = np.full((n_cond, n_met), float("nan"))

    for ri, row in enumerate(conds):
        for ci, metric in enumerate(metrics_shown):
            p = _f(row.get(f"{metric}_shapiro_p", float("nan")))
            matrix[ri, ci] = p

    fig, ax = plt.subplots(figsize=(n_met * 1.3 + 2, n_cond * 0.5 + 2))
    # Use diverging colormap: red = non-normal (p<0.05), green = normal
    im = ax.imshow(
        matrix, aspect="auto", cmap="RdYlGn",
        vmin=0, vmax=1.0, interpolation="nearest",
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02, shrink=0.8)
    cbar.set_label("Shapiro-Wilk p-value\n(p<0.05 = non-normal)", fontsize=9)

    for ri in range(n_cond):
        for ci in range(n_met):
            v = matrix[ri, ci]
            if np.isnan(v):
                text = "–"
                color = "gray"
            else:
                text = f"{v:.3f}"
                color = "red" if v < 0.05 else "black"
            ax.text(ci, ri, text, ha="center", va="center",
                    fontsize=7, color=color,
                    fontweight="bold" if not np.isnan(v) and v < 0.05 else "normal")

    ax.set_xticks(range(n_met))
    ax.set_xticklabels(metrics_shown, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(n_cond))
    ax.set_yticklabels(
        [r.get("label", r["condition"]) for r in conds], fontsize=8,
    )

    # Highlight threshold
    ax.set_title(
        "Fig. 9 — Normality of Paired Differences (Shapiro-Wilk)\n"
        "Red cells (p<0.05) justify non-parametric Wilcoxon test",
        fontsize=11, fontweight="bold", pad=12,
    )
    fig.tight_layout()
    p = out / "fig9_normality_diagnostics.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Figure 10 — Post-hoc power analysis
# ---------------------------------------------------------------------------
def fig10_power_analysis(rows: List[Dict], out: Path) -> None:
    """Heatmap of post-hoc power (1-β) for each condition × metric."""
    metrics_shown = [
        "throughput", "near_misses", "mean_flowtime",
        "total_wait_steps", "mean_planning_time_ms",
        "collisions_agent_human", "safety_violations",
        "local_replans", "assignments_broken",
    ]
    conds = [r for r in _build_order(rows) if r["condition"] != CONTROL]
    if not conds:
        print("  Skipping Fig 10 (no ablation conditions)")
        return

    n_cond = len(conds)
    n_met = len(metrics_shown)
    matrix = np.full((n_cond, n_met), float("nan"))

    for ri, row in enumerate(conds):
        for ci, metric in enumerate(metrics_shown):
            pwr = _f(row.get(f"{metric}_power", float("nan")))
            matrix[ri, ci] = pwr

    fig, ax = plt.subplots(figsize=(n_met * 1.3 + 2, n_cond * 0.5 + 2))
    im = ax.imshow(
        matrix, aspect="auto", cmap="YlGn",
        vmin=0, vmax=1.0, interpolation="nearest",
    )
    cbar = fig.colorbar(im, ax=ax, pad=0.02, shrink=0.8)
    cbar.set_label("Post-hoc power (1−β)\n(≥0.80 = adequately powered)",
                   fontsize=9)

    for ri in range(n_cond):
        for ci in range(n_met):
            v = matrix[ri, ci]
            if np.isnan(v):
                text = "–"
                color = "gray"
            else:
                text = f"{v:.2f}"
                color = "darkgreen" if v >= 0.80 else (
                    "orange" if v >= 0.50 else "red"
                )
            ax.text(ci, ri, text, ha="center", va="center",
                    fontsize=7, color=color,
                    fontweight="bold" if not np.isnan(v) and v >= 0.80 else "normal")

    ax.set_xticks(range(n_met))
    ax.set_xticklabels(metrics_shown, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(n_cond))
    ax.set_yticklabels(
        [r.get("label", r["condition"]) for r in conds], fontsize=8,
    )

    # Add 0.80 power threshold annotation
    n_seeds = rows[0].get("n_seeds", 30) if rows else 30
    ax.set_title(
        f"Fig. 10 — Post-hoc Power Analysis (n={n_seeds} seeds)\n"
        "Green ≥0.80 (adequate)  Orange 0.50–0.79  Red <0.50 (underpowered)",
        fontsize=11, fontweight="bold", pad=12,
    )
    fig.tight_layout()
    p = out / "fig10_power_analysis.pdf"
    fig.savefig(p)
    fig.savefig(str(p).replace(".pdf", ".png"))
    plt.close(fig)
    print(f"Saved: {p}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate ablation study figures for HA-LMAPF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # All figures
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv

  # With violin plots (requires raw data)
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      --raw logs/ablation/<ts>/results.csv

  # Specific figures only
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      --figures 1 4 5 6

  # Custom output
  python scripts/ablation/plot_ablation.py logs/ablation/<ts>/summary.csv \\
      -o figures/ablation/
""",
    )
    parser.add_argument(
        "summary_csv",
        help="Path to summary.csv from run_ablation_study.py",
    )
    parser.add_argument(
        "--raw", type=str, default=None,
        help="Path to results.csv for violin plots (Fig 8)",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        help="Output directory (default: <summary_dir>/plots/)",
    )
    parser.add_argument(
        "--figures", type=int, nargs="+",
        default=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        help="Which figures to generate (1-10, default: all)",
    )
    args = parser.parse_args()

    summary_path = Path(args.summary_csv)
    if not summary_path.exists():
        print(f"ERROR: {summary_path} not found.")
        sys.exit(1)

    rows = load_csv(str(summary_path))
    if not rows:
        print("ERROR: summary.csv is empty.")
        sys.exit(1)

    out_dir = Path(args.output) if args.output \
        else summary_path.parent / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {out_dir}")

    raw_rows = []
    if args.raw:
        rp = Path(args.raw)
        if rp.exists():
            raw_rows = load_csv(str(rp))
            print(f"Loaded {len(raw_rows)} raw rows from {rp}")
        else:
            print(f"WARNING: --raw file not found: {rp}")

    fig_funcs = {
        1: ("Fig 1 — Throughput by group", lambda: fig1_throughput_by_group(rows, out_dir)),
        2: ("Fig 2 — Safety panel", lambda: fig2_safety_panel(rows, out_dir)),
        3: ("Fig 3 — Efficiency panel", lambda: fig3_efficiency_panel(rows, out_dir)),
        4: ("Fig 4 — Effect size forest", lambda: fig4_effect_size_forest(rows, out_dir)),
        5: ("Fig 5 — Safety-efficiency scatter", lambda: fig5_safety_efficiency_scatter(rows, out_dir)),
        6: ("Fig 6 — Comprehensive heatmap", lambda: fig6_comprehensive_heatmap(rows, out_dir)),
        7: ("Fig 7 — Within-group panels", lambda: fig7_within_group_panels(rows, out_dir)),
        8: ("Fig 8 — Violin distributions", lambda: fig8_violin_distributions(rows, raw_rows, out_dir)),
        9: ("Fig 9 — Normality diagnostics", lambda: fig9_normality_diagnostics(rows, out_dir)),
        10: ("Fig 10 — Power analysis", lambda: fig10_power_analysis(rows, out_dir)),
    }

    for fig_num in sorted(args.figures):
        if fig_num not in fig_funcs:
            print(f"WARNING: Figure {fig_num} unknown (valid: 1-10)")
            continue
        name, fn = fig_funcs[fig_num]
        print(f"\nGenerating {name} ...")
        try:
            fn()
        except Exception as e:
            print(f"  ERROR: {e}")

    print(f"\nAll figures saved to: {out_dir}")
    print("Files: .pdf (vector) + .png (raster) for each figure.")


if __name__ == "__main__":
    main()
