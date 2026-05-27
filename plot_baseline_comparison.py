#!/usr/bin/env python3
"""
Baseline-comparison figures for POE-LMAPF (§5.5).
Four methods: ours, lacam_blind, pibt2_fr, no_buffer.
Source: logs/paper/baseline_comparison_v2/results.csv (720 runs, steps=2000)
Usage: python plot_baseline_comparison.py [results.csv] [out_dir]
"""
import sys, csv, os
from collections import defaultdict
import statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = sys.argv[1] if len(sys.argv) > 1 else \
      "logs/paper/baseline_comparison_v2/results.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "figures/paper/baselines"
os.makedirs(OUT, exist_ok=True)

# method id -> (display label, color, marker)
METHOD = {
    "ours":         ("POE-Solver (ours)", "#2ca02c", "o"),
    "lacam_blind":  ("LaCAM-Blind",        "#1f77b4", "s"),
    "pibt2_fr":     ("PIBT2-FR",           "#d62728", "^"),
    "no_buffer":    ("No-Buffer",          "#9467bd", "D"),
}
METHOD_ORDER = ["ours", "lacam_blind", "pibt2_fr", "no_buffer"]
MAPS = ["random-64-64-10", "warehouse-10-20-10-2-2"]

def map_key(path):
    for m in MAPS:
        if m in path:
            return m
    return None

# columns to aggregate (names per the verified v2 schema; adjust if needed)
COLS = ["throughput", "completed_tasks", "wait_fraction",
        "violations_agent_attributable",
        "violations_exogenous_attributable",
        "mean_planning_time_ms"]

# ---- load: per (method, map, |M|) -> list of seed values per column ----
data = defaultdict(lambda: defaultdict(list))
with open(CSV) as f:
    reader = csv.DictReader(f)
    header = reader.fieldnames
    for r in reader:
        if r.get("status", "ok") != "ok":
            continue
        mk = map_key(r.get("map_path", ""))
        method = r.get("method", "")
        if mk is None or method not in METHOD:
            continue
        try:
            M = int(r["num_agents"])
        except (KeyError, ValueError):
            continue
        for c in COLS:
            v = r.get(c, "")
            if v not in ("", None):
                try:
                    data[(method, mk, M)][c].append(float(v))
                except ValueError:
                    pass

if not data:
    sys.exit(f"No usable rows in {CSV} — check column names / path.\n"
             f"CSV header was: {header}")

print(f"Loaded baseline data from {CSV}")
print(f"  methods: {sorted({m for (m,_,_) in data})}")
print(f"  maps:    {sorted({mk for (_,mk,_) in data})}")

def series(method, mk, col):
    """returns (sorted_M, means, stds) for one method/map/metric."""
    Ms = sorted({M for (mt, m, M) in data if mt == method and m == mk})
    means, stds = [], []
    for M in Ms:
        vals = data[(method, mk, M)].get(col, [])
        means.append(st.mean(vals) if vals else float("nan"))
        stds.append(st.pstdev(vals) if len(vals) > 1 else 0.0)
    return Ms, means, stds

# ============================================================
# FIGURE 1 — per-map 4-panel comparison
# panels: throughput, N_a, N_x, planning time   (one figure per map)
# ============================================================
def fig_per_map(mk):
    panels = [
        ("throughput",                        "Throughput",                 "linear"),
        ("violations_agent_attributable",     "Agent-attr. violations $N_a$","linear"),
        ("violations_exogenous_attributable", "Ext-attr. violations $N_x$",  "linear"),
        ("mean_planning_time_ms",             "Global planning time (ms)",   "log"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (col, ylabel, yscale) in zip(axes.flat, panels):
        any_data = False
        for method in METHOD_ORDER:
            label, color, mark = METHOD[method]
            Ms, means, stds = series(method, mk, col)
            if not Ms:
                continue
            any_data = True
            ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                        capsize=3, linewidth=1.7, markersize=5, label=label)
        ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel, fontsize=10)
        ax.grid(alpha=.3)
        if yscale == "log" and any_data:
            ax.set_yscale("log")
    axes[0, 0].legend(fontsize=8, framealpha=.95)
    fig.suptitle(f"Baseline comparison — {mk}", fontsize=11)
    fig.tight_layout()
    stem = mk.replace("-", "_")
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/baseline_{stem}.{ext}", dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote baseline_{stem}.{{pdf,png}}")

# ============================================================
# FIGURE 2 — safety headline: N_x, ours vs each baseline, per map
# (single panel per map, side by side)
# ============================================================
def fig_safety():
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, mk in zip(axes, MAPS):
        for method in METHOD_ORDER:
            label, color, mark = METHOD[method]
            Ms, means, stds = series(method, mk,
                                     "violations_exogenous_attributable")
            if not Ms:
                continue
            ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                        capsize=3, linewidth=1.8, markersize=5, label=label)
        ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
        ax.set_ylabel(r"External-attributable violations $N_x$")
        ax.set_title(mk, fontsize=10)
        ax.grid(alpha=.3)
    axes[0].legend(fontsize=8, framealpha=.95)
    fig.suptitle(r"External-attributable violations $N_x$ by method",
                 fontsize=11)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/baseline_safety_Nx.{ext}",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote baseline_safety_Nx.{{pdf,png}}")

# ============================================================
# FIGURE 3 — throughput, both maps side by side
# ============================================================
def fig_throughput():
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, mk in zip(axes, MAPS):
        for method in METHOD_ORDER:
            label, color, mark = METHOD[method]
            Ms, means, stds = series(method, mk, "throughput")
            if not Ms:
                continue
            ax.errorbar(Ms, means, yerr=stds, marker=mark, color=color,
                        capsize=3, linewidth=1.8, markersize=5, label=label)
        ax.set_xlabel(r"Controlled-agent count $|\mathcal{M}|$")
        ax.set_ylabel("Throughput")
        ax.set_title(mk, fontsize=10)
        ax.grid(alpha=.3)
    axes[0].legend(fontsize=8, framealpha=.95)
    fig.suptitle("Throughput by method", fontsize=11)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/baseline_throughput.{ext}",
                    dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote baseline_throughput.{{pdf,png}}")

# ---- generate everything ----
for mk in MAPS:
    fig_per_map(mk)
fig_safety()
fig_throughput()
print(f"Done. Figures in {OUT}/")