#!/usr/bin/env python3
"""
Horizon-tuning figures for POE-LMAPF §5.2.
Plots every metric against the planning horizon H to justify H=40.
Source: logs/tuning/horizon_replan_full/results.csv
Usage: python plot_horizon_tuning.py [results.csv] [output_dir]
"""
import sys, csv, os
from collections import defaultdict
import statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV   = sys.argv[1] if len(sys.argv) > 1 else "logs/tuning/horizon_replan_full/results.csv"
OUT   = sys.argv[2] if len(sys.argv) > 2 else "figures/paper/horizon"
SELECTED_H = 40
os.makedirs(OUT, exist_ok=True)

MAPS = {
    "random-64-64-10":        "random-64-64-10",
    "warehouse-10-20-10-2-2": "warehouse-10-20-10-2-2",
}
# (csv column, axis label, filename stem, "higher better"/"lower"/"flat")
METRICS = [
    ("throughput",        "Throughput (tasks/step)",      "throughput",   "flat"),
    ("wall_clock_s",      "Wall-clock (s)",               "wallclock",    "lower"),
    ("mean_service_time", "Mean service time (steps)",    "service_time", "lower"),
    ("mean_flowtime",     "Mean flowtime (steps)",        "flowtime",     "lower"),
    ("wait_fraction",     "Wait fraction",                "wait_fraction","lower"),
    ("yield_wait_steps",  "Yield-wait steps",             "yield_wait",   "lower"),
    ("global_replans",    "Global replans",               "global_replans","info"),
]

def map_key(path):
    for k in MAPS:
        if k in path:
            return k
    return None

# ---- load ----
rows = []
with open(CSV) as f:
    for r in csv.DictReader(f):
        if r.get("status", "ok") != "ok":
            continue
        mk = map_key(r.get("map_path", ""))
        if mk is None:
            continue
        rec = {"map": mk, "H": int(r["horizon"]), "M": int(r["num_agents"])}
        for col, *_ in METRICS:
            v = r.get(col, "")
            rec[col] = float(v) if v not in ("", None) else None
        rows.append(rec)

if not rows:
    sys.exit(f"No usable rows in {CSV}")

Hs = sorted({r["H"] for r in rows})
Ms = sorted({r["M"] for r in rows})
print(f"Loaded {len(rows)} rows | H={Hs} | M={Ms} | maps={list(MAPS)}")

def agg(map_k, col, M=None):
    """mean + sample-std over seeds, per H. M=None -> pooled over all M."""
    means, sds = [], []
    for H in Hs:
        vals = [r[col] for r in rows
                if r["map"] == map_k and r["H"] == H
                and (M is None or r["M"] == M)
                and r[col] is not None]
        means.append(st.mean(vals) if vals else float("nan"))
        sds.append(st.pstdev(vals) if len(vals) > 1 else 0.0)
    return means, sds

# ============================================================
# FIGURE A — metric vs H, one line per |M|, two map panels.
# One figure per metric.
# ============================================================
def fig_metric_vs_H(col, ylabel, stem, sense):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, (mk, mlabel) in zip(axes, MAPS.items()):
        for M in Ms:
            mean, sd = agg(mk, col, M=M)
            ax.errorbar(Hs, mean, yerr=sd, marker="o", capsize=3,
                        label=f"|M|={M}", linewidth=1.6, markersize=4)
        ax.axvline(SELECTED_H, color="crimson", ls="--", lw=1.3, alpha=.8)
        ax.text(SELECTED_H, ax.get_ylim()[1], f" H={SELECTED_H}",
                color="crimson", va="top", fontsize=8)
        ax.set_xlabel(r"Planning horizon $\mathcal{H}$")
        ax.set_ylabel(ylabel)
        ax.set_title(mlabel, fontsize=10)
        ax.grid(alpha=.3)
        ax.set_xticks(Hs)
    axes[0].legend(fontsize=8, framealpha=.9)
    fig.suptitle(f"{ylabel} vs horizon", fontsize=11)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/horizon_{stem}.{ext}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote horizon_{stem}.{{pdf,png}}")

print("Figure A — per-metric vs H (lines = |M|):")
for col, ylabel, stem, sense in METRICS:
    if any(r[col] is not None for r in rows):
        fig_metric_vs_H(col, ylabel, stem, sense)

# ============================================================
# FIGURE B — the decision panel: 4 key metrics pooled over |M|,
# both maps, in one 2x2 grid. THIS is the figure that justifies H=40.
# ============================================================
def fig_decision_panel():
    panel = [
        ("throughput",        "Throughput",            "flat"),
        ("wall_clock_s",      "Wall-clock (s)",        "lower"),
        ("mean_service_time", "Mean service time",     "lower"),
        ("wait_fraction",     "Wait fraction",         "lower"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (col, ylabel, sense) in zip(axes.flat, panel):
        for mk, mlabel in MAPS.items():
            mean, sd = agg(mk, col, M=None)   # pooled over |M|
            ax.errorbar(Hs, mean, yerr=sd, marker="o", capsize=3,
                        label=mlabel, linewidth=1.8, markersize=5)
        ax.axvline(SELECTED_H, color="crimson", ls="--", lw=1.3, alpha=.8)
        ax.set_xlabel(r"Planning horizon $\mathcal{H}$")
        ax.set_ylabel(ylabel)
        ax.set_title(ylabel, fontsize=10)
        ax.grid(alpha=.3); ax.set_xticks(Hs)
    axes[0,0].legend(fontsize=8)
    fig.suptitle(r"Horizon selection: throughput flat, cost falls, "
                 r"responsiveness degrades $\rightarrow$ $\mathcal{H}=40$",
                 fontsize=11)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/horizon_decision_panel.{ext}",
                    dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote horizon_decision_panel.{pdf,png}")

print("Figure B — 4-metric decision panel (pooled over |M|):")
fig_decision_panel()

# ============================================================
# FIGURE C — wall-clock marginal-saving (the 'knee' plot)
# ============================================================
def fig_knee():
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for mk, mlabel in MAPS.items():
        mean, _ = agg(mk, "wall_clock_s", M=None)
        # remaining-gap fraction saved by each +10 step
        base = mean[-1]
        savings = []
        for i in range(len(Hs)-1):
            gap = mean[i] - base
            step = mean[i] - mean[i+1]
            savings.append(100*step/gap if gap > 1e-9 else 0.0)
        ax.plot(Hs[:-1], savings, marker="s", label=mlabel, linewidth=1.8)
    ax.axvline(SELECTED_H, color="crimson", ls="--", lw=1.3)
    ax.set_xlabel(r"Planning horizon $\mathcal{H}$")
    ax.set_ylabel("% of remaining wall-clock gap\nsaved by next +10 step")
    ax.set_title("Diminishing compute returns (knee of the cost curve)")
    ax.grid(alpha=.3); ax.set_xticks(Hs[:-1]); ax.legend(fontsize=9)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{OUT}/horizon_knee.{ext}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("  wrote horizon_knee.{pdf,png}")

print("Figure C — knee analysis:")
fig_knee()

print(f"\nDone. All figures in {OUT}/")