#!/usr/bin/env python3
"""
Conventional Pareto plot for the FoV / safety-buffer sweep.
Throughput (maximize) vs N_x (minimize) -> N_x axis flipped so the
Pareto frontier is the conventional upper-right staircase.
Usage: python plot_pareto_fov_safety.py [results.csv] [out_dir]
"""
import sys, csv, os
from collections import defaultdict
import statistics as st
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = sys.argv[1] if len(sys.argv) > 1 else "logs/tuning/fov_safety_sweep/results.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "figures/paper"
os.makedirs(OUT, exist_ok=True)

MAPS = ["random-64-64-10", "warehouse-10-20-10-2-2"]
RSAFE_COLOR = {1:"#1f77b4", 2:"#ff7f0e", 3:"#2ca02c", 4:"#d62728", 5:"#9467bd"}
RSAFE_MARK  = {1:"o", 2:"s", 3:"^", 4:"D", 5:"v"}

def map_key(path):
    for m in MAPS:
        if m in path: return m
    return None

# ---- load & aggregate: mean over seeds per (map, r_fov, r_safe) ----
agg = defaultdict(lambda: {"tp": [], "nx": []})
with open(CSV) as f:
    for r in csv.DictReader(f):
        if r.get("status", "ok") != "ok":
            continue
        mk = map_key(r.get("map_path", ""))
        if mk is None:
            continue
        try:
            rf = int(r["fov_radius"]); rs = int(r["safety_radius"])
            tp = float(r["throughput"])
            nx = float(r["violations_exogenous_attributable"])
        except (KeyError, ValueError):
            continue
        agg[(mk, rf, rs)]["tp"].append(tp)
        agg[(mk, rf, rs)]["nx"].append(nx)

# per-map list of points: (r_fov, r_safe, mean_tp, mean_nx)
points = defaultdict(list)
for (mk, rf, rs), d in agg.items():
    if d["tp"]:
        points[mk].append((rf, rs,
                            st.mean(d["tp"]), st.mean(d["nx"])))

def pareto_front(pts):
    """pts: list of (rf, rs, tp, nx). maximize tp, minimize nx.
       returns indices of non-dominated points."""
    front = []
    for i, (_, _, tp_i, nx_i) in enumerate(pts):
        dominated = False
        for j, (_, _, tp_j, nx_j) in enumerate(pts):
            if j == i:
                continue
            # j dominates i if j is >= on tp and <= on nx, strictly better on one
            if tp_j >= tp_i and nx_j <= nx_i and (tp_j > tp_i or nx_j < nx_i):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

for ax, mk in zip(axes, MAPS):
    pts = points.get(mk, [])
    if not pts:
        ax.set_title(f"{mk} (no data)")
        continue
    front_idx = set(pareto_front(pts))

    # plot dominated points: faded
    for i, (rf, rs, tp, nx) in enumerate(pts):
        if i in front_idx:
            continue
        ax.scatter(nx, tp, c="lightgrey", marker=RSAFE_MARK[rs],
                   s=35, edgecolors="grey", linewidths=0.4, zorder=2)

    # plot frontier points: emphasized, colored by r_safe
    fp = sorted((pts[i] for i in front_idx), key=lambda p: p[3])  # by nx
    for rf, rs, tp, nx in fp:
        ax.scatter(nx, tp, c=RSAFE_COLOR[rs], marker=RSAFE_MARK[rs],
                   s=130, edgecolors="black", linewidths=1.0, zorder=4)
        ax.annotate(f"({rf},{rs})", (nx, tp),
                    textcoords="offset points", xytext=(6, 5),
                    fontsize=8, zorder=5)
    # frontier step-line
    if len(fp) > 1:
        ax.plot([p[3] for p in fp], [p[2] for p in fp],
                color="crimson", lw=1.8, ls="-", zorder=3,
                label="Pareto frontier")

    ax.invert_xaxis()                       # <-- key: low N_x to the RIGHT
    ax.set_xscale("log")
    ax.set_xlabel(r"External-attributable violations $N_x$  "
                  r"($\leftarrow$ fewer / better)")
    ax.set_ylabel("Throughput  (better $\\uparrow$)")
    ax.set_title(mk, fontsize=11)
    ax.grid(alpha=.3, which="both")
    ax.legend(loc="lower left", fontsize=9, framealpha=.95)

# shared r_safe legend
handles = [plt.Line2D([0],[0], marker=RSAFE_MARK[rs], color="w",
           markerfacecolor=RSAFE_COLOR[rs], markeredgecolor="black",
           markersize=9, label=f"$r_{{safe}}={rs}$")
           for rs in sorted(RSAFE_COLOR)]
fig.legend(handles=handles, loc="upper center", ncol=5,
           fontsize=9, bbox_to_anchor=(0.5, 1.04))

fig.suptitle("Throughput vs $N_x$ Pareto frontier across "
             r"$(r_\mathrm{fov}, r_\mathrm{safe})$", y=1.10, fontsize=12)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(f"{OUT}/fov_safety_pareto.{ext}", dpi=160, bbox_inches="tight")
print(f"wrote {OUT}/fov_safety_pareto.{{pdf,png}}")