#!/usr/bin/env python3
"""
Task-allocator study figures for POE-LMAPF (§5.5, allocator comparison).
Parameterized by operating point — run once per (r_fov, r_safe) sweep.

Usage:
  python plot_allocator_study.py [results.csv] [out_dir] [op_tag]

Examples:
  # (3,1) headline operating point
  python plot_allocator_study.py \
      logs/tuning/allocator_comparison_fov3_safe1_v3/results.csv \
      figures/paper/allocator fov3_safe1_v3

  # (4,2) robustness companion
  python plot_allocator_study.py \
      logs/tuning/allocator_comparison_fov4_safe2_v2/results.csv \
      figures/paper/allocator fov4_safe2_v2
"""
import sys, csv, os
from collections import defaultdict
import statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV    = sys.argv[1] if len(sys.argv) > 1 else \
         "logs/tuning/allocator_comparison_fov3_safe1_v3/results.csv"
OUT    = sys.argv[2] if len(sys.argv) > 2 else "figures/paper/allocator"
OP_TAG = sys.argv[3] if len(sys.argv) > 3 else "fov3_safe1_v3"
os.makedirs(OUT, exist_ok=True)

# allocator id -> (display label, color, marker)
ALLOC = {
    "greedy":               ("Greedy",              "#888888", "o"),
    "hungarian":            ("Hungarian",            "#1f77b4", "s"),
    "auction":              ("Auction",              "#ff7f0e", "^"),
    "congestion_avoidance": ("Congestion-Avoidance", "#2ca02c", "D"),
}
ALLOC_ORDER = ["greedy", "hungarian", "auction", "congestion_avoidance"]
WAREHOUSE = "warehouse-10-20-10-2-2"   # the |M|-swept map

def map_key(path):
    if "warehouse-10-20-10-2-2" in path:
        return "warehouse-10-20-10-2-2"
    if "random-64-64-10" in path:
        return "random-64-64-10"
    return None

# columns to aggregate
COLS = ["throughput", "wait_fraction",
        "violations_exogenous_attributable",
        "violations_agent_attributable",
        "mean_planning_time_ms", "mean_decision_time_ms",
        "sum_assignment_path_overlap"]

# ---- load: per (allocator, map, |M|) -> list of seed values per column ----
data = defaultdict(lambda: defaultdict(list))
with open(CSV) as f:
    for r in csv.DictReader(f):
        if r.get("status", "ok") != "ok":
            continue
        mk = map_key(r.get("map_path", ""))
        alloc = r.get("task_allocator", "")
        if mk is None or alloc not in ALLOC:
            continue
        try:
            M = int(r["num_agents"])
        except (KeyError, ValueError):
            continue
        for c in COLS:
            v = r.get(c, "")
            if v not in ("", None):
                try:
                    data[(alloc, mk, M)][c].append(float(v))
                except ValueError:
                    pass

if not data:
    sys.exit(f"No usable rows in {CSV} — check column names and path.")

def series(alloc, mk, col):
    """returns (sorted_M, means, stds) for one allocator/map/metric."""
    Ms = sorted({M for (a, m, M) in data if a == alloc and m == mk})
    means, stds = [], []
    for M in Ms:
        vals = data[(alloc, mk, M)].get(col, [])
        means.append(st.mean(vals) if vals else float("nan"))
        stds.append(st.pstdev(vals) if len(vals) > 1 else 0.0)
    return Ms, means, stds

# ============================================================
# FIGURE 1 — allocator comparison panel (warehouse, vs |M|)
# 4 panels: throughput, wait fraction, N_x, global planning time
# ============================================================
def fig_comparison():
    panels = [
        ("throughput",                        "Throughput"),
        ("wait_fraction",                     "Wait fraction"),
        ("violations_exogenous_attributable", "External violations $N_x$"),
        ("mean_planning_time_ms",             "Global planning time (ms)"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (col, ylabel) in zip(axes.flat, panels):
        for alloc in ALLOC_ORDER:
            label, color, mark = ALLOC[alloc]
            Ms, means, stds = series(alloc, WAREHOUSE, col)
            if not Ms:
                continue
            ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                        capsize=3, linewidth=1.7, markersize=5, label=label)
        ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel, fontsize=10)
        ax.grid(alpha=.3)
    axes[0, 0].legend(fontsize=8, framealpha=.95)
    fig.suptitle(f"Task-allocator comparison — {WAREHOUSE} ({OP_TAG})",
                 fontsize=11)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/allocator_comparison_{OP_TAG}.{ext}",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote allocator_comparison_{OP_TAG}.{{pdf,png}}")

# ============================================================
# FIGURE 2 — path-overlap mechanism plot (warehouse, vs |M|)
# Mechanistic evidence: CA/Auction low overlap, Greedy highest.
# ============================================================
def fig_overlap():
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    for alloc in ALLOC_ORDER:
        label, color, mark = ALLOC[alloc]
        Ms, means, stds = series(alloc, WAREHOUSE,
                                 "sum_assignment_path_overlap")
        if not Ms:
            continue
        ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                    capsize=3, linewidth=1.8, markersize=6, label=label)
    ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
    ax.set_ylabel("Summed assignment path overlap")
    ax.set_title(f"Assignment path overlap by allocator "
                 f"(lower = easier MAPF instance) — {OP_TAG}")
    ax.grid(alpha=.3)
    ax.legend(fontsize=9, framealpha=.95)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/allocator_overlap_{OP_TAG}.{ext}",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote allocator_overlap_{OP_TAG}.{{pdf,png}}")

print(f"Loaded allocator data from {CSV}")
allocs_found = sorted({a for (a, m, M) in data})
maps_found   = sorted({m for (a, m, M) in data})
print(f"  allocators: {allocs_found}")
print(f"  maps:       {maps_found}")
print(f"  op tag:     {OP_TAG}")
fig_comparison()
fig_overlap()
print(f"Done. Figures in {OUT}/")