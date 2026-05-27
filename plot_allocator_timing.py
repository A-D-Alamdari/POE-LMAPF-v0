#!/usr/bin/env python3
"""
Allocator-study timing & replanning figures for POE-LMAPF (§5.5).
Plots per-replan global planning time, per-tick decision time, and
(if present) global-replan count, per allocator vs |M|.

Usage:
  python plot_allocator_timing.py [results.csv] [out_dir] [op_tag]
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

ALLOC = {
    "greedy":               ("Greedy",               "#888888", "o"),
    "hungarian":            ("Hungarian",             "#1f77b4", "s"),
    "auction":              ("Auction",               "#ff7f0e", "^"),
    "congestion_avoidance": ("Congestion-Avoidance",  "#2ca02c", "D"),
}
ALLOC_ORDER = ["greedy", "hungarian", "auction", "congestion_avoidance"]
WAREHOUSE = "warehouse-10-20-10-2-2"

def map_key(path):
    if "warehouse-10-20-10-2-2" in path: return "warehouse-10-20-10-2-2"
    if "random-64-64-10" in path:        return "random-64-64-10"
    return None

# candidate columns — the script keeps whichever actually exist in the CSV
CANDIDATE_COLS = [
    "mean_planning_time_ms",   # per-replan global-planner time
    "mean_decision_time_ms",   # per-tick Tier-2 + allocator decision time
    "global_replans",          # count of global replans per run
    "local_replans",           # count of local repairs per run
]

# ---- load ----
data = defaultdict(lambda: defaultdict(list))
with open(CSV) as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    present = [c for c in CANDIDATE_COLS if c in header]
    for r in reader:
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
        for c in present:
            v = r.get(c, "")
            if v not in ("", None):
                try:
                    data[(alloc, mk, M)][c].append(float(v))
                except ValueError:
                    pass

if not data:
    sys.exit(f"No usable rows in {CSV}\nCSV header was: {header}")

print(f"Loaded allocator timing data from {CSV}")
print(f"  timing/replan columns present: {present}")

def series(alloc, mk, col):
    Ms = sorted({M for (a, m, M) in data if a == alloc and m == mk})
    means, stds = [], []
    for M in Ms:
        vals = data[(alloc, mk, M)].get(col, [])
        means.append(st.mean(vals) if vals else float("nan"))
        stds.append(st.pstdev(vals) if len(vals) > 1 else 0.0)
    return Ms, means, stds

def has_col(col):
    return any(col in d for d in data.values())

def one_panel(ax, col, ylabel, logy=False):
    drew = False
    for alloc in ALLOC_ORDER:
        label, color, mark = ALLOC[alloc]
        Ms, means, stds = series(alloc, WAREHOUSE, col)
        if not Ms or all(m != m for m in means):  # all-NaN guard
            continue
        drew = True
        ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                    capsize=3, linewidth=1.8, markersize=5, label=label)
    ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
    ax.set_ylabel(ylabel)
    ax.set_title(ylabel, fontsize=10)
    ax.grid(alpha=.3)
    if logy and drew:
        ax.set_yscale("log")
    return drew

# ---- decide which panels to draw based on what exists ----
panels = []
if has_col("mean_planning_time_ms"):
    panels.append(("mean_planning_time_ms",
                    "Global planning time per replan (ms)", False))
if has_col("mean_decision_time_ms"):
    panels.append(("mean_decision_time_ms",
                    "Per-tick decision time (ms)", False))
if has_col("global_replans"):
    panels.append(("global_replans", "Global replans per run", False))
if has_col("local_replans"):
    panels.append(("local_replans", "Local repairs per run", False))

if not panels:
    sys.exit("None of the timing/replan columns were found in the CSV.")

n = len(panels)
ncol = 2 if n > 1 else 1
nrow = (n + ncol - 1) // ncol
fig, axes = plt.subplots(nrow, ncol, figsize=(6.0 * ncol, 4.2 * nrow),
                         squeeze=False)
flat = axes.flat
for ax, (col, ylabel, logy) in zip(flat, panels):
    one_panel(ax, col, ylabel, logy)
for ax in list(flat)[n:]:
    ax.set_visible(False)

flat = axes.flat
next(iter(flat)).legend(fontsize=8, framealpha=.95)

fig.suptitle(f"Allocator timing & replanning — {WAREHOUSE} ({OP_TAG})",
             fontsize=11)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(f"{OUT}/allocator_timing_{OP_TAG}.{ext}",
                dpi=160, bbox_inches="tight")
plt.close(fig)
print(f"  wrote allocator_timing_{OP_TAG}.{{pdf,png}}")
print(f"Done. Figure in {OUT}/")