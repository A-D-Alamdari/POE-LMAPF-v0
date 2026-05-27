#!/usr/bin/env python3
"""
Heatmaps for the FoV / safety-buffer sweep:
throughput and N_x over the (r_fov, r_safe) grid, per map.
Usage: python plot_fov_safety_heatmap.py [results.csv] [out_dir]
"""
import sys, csv, os
from collections import defaultdict
import statistics as st
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

CSV = sys.argv[1] if len(sys.argv) > 1 else "logs/tuning/fov_safety_sweep/results.csv"
OUT = sys.argv[2] if len(sys.argv) > 2 else "figures/paper"
os.makedirs(OUT, exist_ok=True)

MAPS = ["random-64-64-10", "warehouse-10-20-10-2-2"]

def map_key(path):
    for m in MAPS:
        if m in path:
            return m
    return None

# ---- load & aggregate: mean over seeds per (map, r_fov, r_safe) ----
agg = defaultdict(lambda: {"tp": [], "nx": []})
fovs, safes = set(), set()
n_rows = 0
with open(CSV) as f:
    for r in csv.DictReader(f):
        if r.get("status", "ok") != "ok":
            continue
        mk = map_key(r.get("map_path", ""))
        if mk is None:
            continue
        try:
            rf = int(r["fov_radius"])
            rs = int(r["safety_radius"])
            tp = float(r["throughput"])
            nx = float(r["violations_exogenous_attributable"])
        except (KeyError, ValueError):
            continue
        agg[(mk, rf, rs)]["tp"].append(tp)
        agg[(mk, rf, rs)]["nx"].append(nx)
        fovs.add(rf)
        safes.add(rs)
        n_rows += 1

if n_rows == 0:
    sys.exit(f"No usable rows in {CSV} — check column names and path.")

fovs  = sorted(fovs)     # x-axis
safes = sorted(safes)    # y-axis
print(f"Loaded {n_rows} rows | r_fov={fovs} | r_safe={safes} | maps={MAPS}")

def grid(mk, key):
    """rows = r_safe, cols = r_fov; NaN where no data (r_fov > r_safe constraint)."""
    G = np.full((len(safes), len(fovs)), np.nan)
    for i, rs in enumerate(safes):
        for j, rf in enumerate(fovs):
            d = agg.get((mk, rf, rs))
            if d and d[key]:
                G[i, j] = st.mean(d[key])
    return G

fig, axes = plt.subplots(2, 2, figsize=(13, 8))

for col, mk in enumerate(MAPS):
    for row, (key, label, cmap, better) in enumerate([
        ("tp", "Throughput",                  "viridis", "high"),
        ("nx", r"External violations $N_x$",  "magma_r", "low"),
    ]):
        ax = axes[row, col]
        G = grid(mk, key)
        im = ax.imshow(G, origin="lower", aspect="auto", cmap=cmap)
        ax.set_xticks(range(len(fovs)))
        ax.set_xticklabels(fovs)
        ax.set_yticks(range(len(safes)))
        ax.set_yticklabels(safes)
        ax.set_xlabel(r"FoV radius $r_\mathrm{fov}$")
        ax.set_ylabel(r"Safety radius $r_\mathrm{safe}$")
        ax.set_title(f"{label} — {mk}", fontsize=10)
        # annotate each cell with its value
        for i in range(len(safes)):
            for j in range(len(fovs)):
                v = G[i, j]
                if not np.isnan(v):
                    txt = f"{v:.3f}" if key == "tp" else f"{v:.0f}"
                    ax.text(j, i, txt, ha="center", va="center",
                            fontsize=7,
                            color="white" if key == "nx" else "black")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.set_label(f"{label} ({'higher' if better == 'high' else 'lower'} better)",
                     fontsize=8)

fig.suptitle(r"FoV / safety-buffer sweep: throughput and $N_x$ over the "
             r"$(r_\mathrm{fov}, r_\mathrm{safe})$ grid",
             fontsize=12, y=1.02)
fig.tight_layout()
for ext in ("pdf", "png"):
    fig.savefig(f"{OUT}/fov_safety_heatmap.{ext}", dpi=160, bbox_inches="tight")
    print(f"wrote {OUT}/fov_safety_heatmap.{ext}")