# !/usr/bin/env python3
"""
Human-Count Sweep Study for HA-LMAPF Global Planners.

Compares global planners (4–6 per map) across 4 maps and 3 human-model settings,
with a *fixed* number of agents per map and a *varying* number of humans.
This complements compare_global_study_agents.py (which varies agents and
fixes humans).

Solvers benchmarked
-------------------
  Small maps (random, warehouse_small) — 6 solvers:
    lacam      – LaCAM (official C++ wrapper)
    lacam3     – LaCAM3 anytime (C++ wrapper)
    pibt2      – Priority Inheritance with Backtracking (C++ wrapper)
    lns2       – MAPF-LNS2 large-neighborhood search (C++ wrapper)
    PBS        – Priority-Based Search (C++ wrapper, registered as "pbs")
    cbsh2-rtc  – CBS with heuristics (C++ wrapper, registered as "cbsh2")

  Large maps (warehouse_large) — 4 solvers:
    lacam      – LaCAM (official C++ wrapper)
    lacam3     – LaCAM3 anytime (C++ wrapper)
    pibt2      – Priority Inheritance with Backtracking (C++ wrapper)
    lns2       – MAPF-LNS2 large-neighborhood search (C++ wrapper)

Maps
----
  random           data/maps/random-64-64-10.map           (64×64 random 10% obstacles)  [SMALL]
  warehouse_small  data/maps/warehouse-10-20-10-2-2.map    (63×161 narrow aisles, variant 2)  [SMALL]
  warehouse_large  data/maps/warehouse-20-40-10-2-2.map    (123×321 large warehouse, variant 2)  [LARGE]

Human model settings
--------------------
  random  – random_walk model (default parameters)
  aisle   – aisle-following model (default parameters)
  mixed   – 50% random_walk + 50% aisle

Safety radius
-------------
  warehouse maps: safety_radius = 1
  other maps:     safety_radius = 2

Study matrix
------------
  2 small maps × 3 human models × 6 solvers × variable human counts × 10 seeds
  2 large maps × 3 human models × 4 solvers × variable human counts × 10 seeds

Scaling per map
---------------
  num_agents = floor_to_lower_100(0.02 × free_cells)   [FIXED per map]
  max_humans = floor_to_lower_100(0.02 × free_cells)
  human_counts (tiered by max_humans):
    <= 100: [15, 30, 45, 60, 75, 100]
    <= 200: [25, 50, 75, 100, 125, 150, 175, 200]
    <= 400: [50, 100, 150, 200, 250, 300, 350, 400]

  Override — random map: num_agents=50, human_counts=[15, 30, 45, 60, 75]

Usage
-----
  # Full study (default: 10 seeds, sequential)
  python scripts/solvers/compare_global_study_human.py

  # With parallelism
  python scripts/solvers/compare_global_study_human.py --workers 8

  # Quick smoke-test
  python scripts/solvers/compare_global_study_human.py --sanity

  # Custom seeds
  python scripts/solvers/compare_global_study_human.py --seeds 0 1 2

Output
------
  logs/solvers/human/<unique_run_name>/
  ├── raw/results.csv              per-seed, per-config rows
  ├── aggregated/summary.csv       mean ± std aggregated over seeds
  ├── metadata/config.json         full experiment configuration
  └── figures/                     (empty, populated by plotting script)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import fields as dc_fields
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# t-distribution critical values for 95% CI (two-tailed) by degrees of freedom
# Pre-computed for common seed counts to avoid scipy dependency.
_T_CRIT_95: Dict[int, float] = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
    6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
    11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 19: 2.093,
    24: 2.064, 29: 2.045, 49: 2.010, 99: 1.984,
}


def _t_critical(n: int) -> float:
    """Return the two-tailed t critical value for 95% CI with n-1 df."""
    df = n - 1
    if df in _T_CRIT_95:
        return _T_CRIT_95[df]
    if df >= 100:
        return 1.960
    closest = max(k for k in _T_CRIT_95 if k <= df)
    return _T_CRIT_95[closest]


# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from ha_lmapf.core.types import SimConfig, Metrics
from ha_lmapf.io.movingai_map import load_movingai_map
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Rounding helpers (explicit, matching spec exactly)
# ---------------------------------------------------------------------------

def floor_to_lower_100(x: float) -> int:
    """Round down to nearest multiple of 100.

    Examples: 1182 -> 1100, 1100 -> 1100, 473 -> 400, 99 -> 0
    """
    return int(x // 100) * 100


# ---------------------------------------------------------------------------
# Free cell computation
# ---------------------------------------------------------------------------

def count_free_cells(map_path: str) -> int:
    """Load a MovingAI map and return the number of traversable cells."""
    map_data = load_movingai_map(map_path)
    total = map_data.width * map_data.height
    return total - len(map_data.blocked)


# ---------------------------------------------------------------------------
# Map definitions
# ---------------------------------------------------------------------------
# Same 4 maps as compare_global_study_agents.py.

MAP_DEFS: Dict[str, Dict[str, Any]] = {
    "random": {
        "map_path": "data/maps/random-64-64-10.map",
        "description": "64x64 random 10% obstacles",
        "size": "small",
        "safety_radius": 1,
        # Override: auto-scaling yields 0 for this small map
        "num_agents_override": 50,
        "human_counts_override": [15, 30, 45, 60, 75],
    },
    "warehouse_small": {
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "description": "63x161 narrow aisles (variant 2)",
        "size": "small",
        "safety_radius": 1,
    },
    "warehouse_large": {
        "map_path": "data/maps/warehouse-20-40-10-2-2.map",
        "description": "123x321 large warehouse (variant 2)",
        "size": "large",
        "safety_radius": 1,
    },
}

ALL_MAP_TAGS: List[str] = list(MAP_DEFS)

# ---------------------------------------------------------------------------
# Solver definitions
# ---------------------------------------------------------------------------
# (label, factory_name)
# The factory_name is the key passed to GlobalPlannerFactory.create().

SOLVER_DEFS: List[Tuple[str, str]] = [
    ("lacam", "lacam"),
    ("lacam3", "lacam3"),
    ("pibt2", "pibt2"),
    ("lns2", "lns2"),
    ("PBS", "pbs"),
    ("cbsh2-rtc", "cbsh2"),
]

# Per-map-size solver lists:
#   Small maps (random, warehouse_small): all 6 solvers
#   Large maps (warehouse_large): first 4 only (lacam, lacam3, pibt2, lns2)
SOLVERS_SMALL: List[str] = [
    "lacam", "lacam3", "pibt2", "lns2", "PBS", "cbsh2-rtc",
]
SOLVERS_LARGE: List[str] = [
    "lacam", "lacam3", "pibt2", "lns2",
]

ALL_SOLVER_LABELS: List[str] = [s[0] for s in SOLVER_DEFS]

# ---------------------------------------------------------------------------
# Human model definitions
# ---------------------------------------------------------------------------

HUMAN_MODELS: Dict[str, Dict[str, Any]] = {
    "random": {
        "human_model": "random_walk",
        "human_model_params": {},
    },
    "aisle": {
        "human_model": "aisle",
        "human_model_params": {},
    },
    "mixed": {
        "human_model": "mixed",
        "human_model_params": {
            "weights": {"random_walk": 0.5, "aisle": 0.5},
            "sub_params": {},
        },
    },
}

ALL_HUMAN_TAGS: List[str] = list(HUMAN_MODELS)

# ---------------------------------------------------------------------------
# Base simulation configuration
# ---------------------------------------------------------------------------

BASE_CONFIG: Dict[str, Any] = {
    "task_stream_path": None,
    "steps": 2000,
    "fov_radius": 4,
    "safety_radius": 1,
    "hard_safety": True,
    "global_solver": "lacam",  # overridden per solver entry
    "horizon": 20,
    "replan_every": 10,
    "task_allocator": "congestion_avoidance",
    "commit_horizon": 0,
    "delay_threshold": 0.0,
    "task_mode": "immediate",  # Li et al. 2022: immediate reassignment
    "task_arrival_rate": None,  # unused in immediate mode
    "task_arrival_percentage": 0.9,
    "communication_mode": "token",  # Tier-2 conflict resolution: token-passing
    "local_planner": "astar",
    "human_model": "random_walk",
    "human_model_params": {},
    "execution_delay_prob": 0.0,  # perturbations disabled
    "execution_delay_steps": 1,
    "time_budget_ms": 3000.0,  # 3 seconds planning budget
    "disable_local_replan": False,
    "disable_conflict_resolution": False,
    "disable_safety": False,
    "seed": 0,
}

# ---------------------------------------------------------------------------
# Candidate human counts for the sweep
# ---------------------------------------------------------------------------
# The study tests humans at these counts, filtered to <= max_humans per map.

# Tiered human count candidates — selected based on max_humans per map.
# <= 100: [15, 30, 45, 60, 75, 100]
# <= 200: [25, 50, 75, 100, 125, 150, 175, 200]
# <= 400: [50, 100, 150, 200, 250, 300, 350, 400]
HUMAN_COUNT_TIERS: List[Tuple[int, List[int]]] = [
    (100, [15, 30, 45, 60, 75, 100]),
    (200, [25, 50, 75, 100, 125, 150, 175, 200]),
    (400, [50, 100, 150, 200, 250, 300, 350, 400]),
]

# ---------------------------------------------------------------------------
# Metrics recorded per run
# ---------------------------------------------------------------------------

KEY_METRICS: List[str] = [
    "throughput",
    "task_completion",
    "completed_tasks",
    "total_released_tasks",
    "local_replans",
    "global_replans",
    "mean_planning_time_ms",
    "p95_planning_time_ms",
    "max_planning_time_ms",
    "safety_violations",
    "collisions_agent_agent",
    "collisions_agent_human",
    "near_misses",
    "mean_flowtime",
]

# ---------------------------------------------------------------------------
# CSV columns
# ---------------------------------------------------------------------------

_META_COLUMNS = [
    "map_tag", "map_path", "free_cells",
    "num_agents", "max_humans", "num_humans",
    "human_model_tag", "solver_label",
    "seed", "status", "wall_time_s",
]

_CSV_COLUMNS = _META_COLUMNS + KEY_METRICS


# ---------------------------------------------------------------------------
# Map analysis: compute fixed agent count and human sweep range
# ---------------------------------------------------------------------------

def analyse_map(map_tag: str, map_def: Dict[str, Any]) -> Dict[str, Any]:
    """Compute free cells, fixed agent count, max humans, and human count list.

    Scaling rules (per specification):
      num_agents = floor_to_lower_100(0.02 * free_cells)   — fixed per map
      max_humans = floor_to_lower_100(0.02 * free_cells)

    Per-map overrides (num_agents_override, human_counts_override) take
    precedence over auto-scaling when present in MAP_DEFS.
    """
    map_path = map_def["map_path"]
    free_cells = count_free_cells(map_path)
    raw_value = 0.02 * free_cells
    num_agents = floor_to_lower_100(raw_value)
    max_humans = floor_to_lower_100(raw_value)

    # Apply overrides if present (e.g. random map)
    if "num_agents_override" in map_def:
        num_agents = map_def["num_agents_override"]
        print(f"  [{map_tag}] num_agents override: {num_agents}")

    if "human_counts_override" in map_def:
        human_counts = list(map_def["human_counts_override"])
        max_humans = max(human_counts) if human_counts else 0
        print(f"  [{map_tag}] human_counts override: {human_counts}")
    else:
        # Build human count sweep using tiered ranges based on max_humans
        human_counts: List[int] = []
        if max_humans < 15:
            if max_humans >= 1:
                human_counts = [max_humans]
                print(
                    f"  WARNING [{map_tag}]: free_cells={free_cells}, "
                    f"0.02*free_cells={raw_value:.1f} -> max_humans={max_humans}. "
                    f"max_humans < 15, using fallback human_count=[{max_humans}]."
                )
            else:
                human_counts = []
                print(
                    f"  WARNING [{map_tag}]: free_cells={free_cells}, "
                    f"max_humans=0 — skipping map for human sweep."
                )
        else:
            # Pick the appropriate tier for max_humans
            for threshold, candidates in HUMAN_COUNT_TIERS:
                if max_humans <= threshold:
                    human_counts = [h for h in candidates if h <= max_humans]
                    break
            else:
                # max_humans > 400: use the largest tier
                human_counts = [h for h in HUMAN_COUNT_TIERS[-1][1] if h <= max_humans]

    # Fallback for num_agents too
    if num_agents < 1:
        num_agents = max(1, min(free_cells - 1, 10))
        print(
            f"  WARNING [{map_tag}]: computed num_agents=0, "
            f"using fallback num_agents={num_agents}."
        )

    # Determine solver list based on map size
    size = map_def.get("size", "small")
    solvers = SOLVERS_SMALL if size == "small" else SOLVERS_LARGE

    return {
        "map_tag": map_tag,
        "map_path": map_path,
        "free_cells": free_cells,
        "num_agents": num_agents,
        "max_humans": max_humans,
        "human_counts": human_counts,
        "safety_radius": map_def.get("safety_radius", 2),
        "solvers": solvers,
    }


# ---------------------------------------------------------------------------
# Simulation helpers (following existing repo patterns)
# ---------------------------------------------------------------------------

def _build_sim_config(config_dict: Dict[str, Any]) -> SimConfig:
    """Build SimConfig from dict, filtering to known fields only."""
    known = {f.name for f in dc_fields(SimConfig)}
    filtered = {k: v for k, v in config_dict.items() if k in known}
    return SimConfig(**filtered)


def run_single_experiment(
        config_dict: Dict[str, Any],
        label: str,
        verbose: bool = False,
) -> Tuple[Dict[str, Any], float]:
    """Run one simulation. Returns (metrics_dict, wall_time_seconds).

    Status codes:
      'ok'    — completed successfully
      'skip'  — solver binary not found
      'error' — unexpected exception
    """
    t0 = time.monotonic()
    config = _build_sim_config(config_dict)

    try:
        sim = Simulator(config)
        metrics: Metrics = sim.run()
        wall = time.monotonic() - t0

        m_dict = {k: getattr(metrics, k, 0) for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "ok"
        m_dict["_throughput_timeline"] = getattr(metrics, "throughput_timeline", [])

        if verbose:
            print(
                f"    [{label}] "
                f"thr={metrics.throughput:.4f}  "
                f"cmp={metrics.task_completion:.1%}  "
                f"pt={metrics.mean_planning_time_ms:.1f}ms  "
                f"safety={metrics.safety_violations}  "
                f"wall={wall:.1f}s"
            )
        return m_dict, wall

    except FileNotFoundError as exc:
        wall = time.monotonic() - t0
        print(f"    [{label}] SKIP — binary not found: {exc}")
        m_dict = {k: 0 for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "skip"
        m_dict["_throughput_timeline"] = []
        return m_dict, wall

    except Exception as exc:
        wall = time.monotonic() - t0
        print(f"    [{label}] ERROR: {exc}")
        m_dict = {k: 0 for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "error"
        m_dict["_throughput_timeline"] = []
        return m_dict, wall


# ---------------------------------------------------------------------------
# Picklable worker (required for multiprocessing)
# ---------------------------------------------------------------------------

def _worker_task(args: Tuple) -> Dict[str, Any]:
    config_dict, meta, label, verbose = args
    m_dict, _ = run_single_experiment(config_dict, label, verbose)
    return {**meta, **m_dict}


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

def _write_raw_csv(results: List[Dict[str, Any]], path: Path) -> None:
    """Write per-trial raw results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"  Raw results   -> {path}")


def _write_convergence_csv(results: List[Dict[str, Any]], path: Path) -> None:
    """Write per-step cumulative throughput averaged across seeds for convergence analysis.

    For each (map_tag, human_model_tag, solver_label, num_humans) group, averages
    the throughput_timeline across seeds and writes step-by-step data.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    group_keys = ("map_tag", "human_model_tag", "solver_label", "num_humans")
    grouped: Dict[tuple, List[List[float]]] = defaultdict(list)
    for r in results:
        if r.get("status") != "ok":
            continue
        timeline = r.get("_throughput_timeline", [])
        if not timeline:
            continue
        key = tuple(r.get(k, "") for k in group_keys)
        grouped[key].append(timeline)

    if not grouped:
        print(f"  Convergence   -> (skipped, no timeline data)")
        return

    rows_written = 0
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(list(group_keys) + ["step", "throughput_mean", "throughput_ci95"])

        for key, timelines in sorted(grouped.items()):
            n = len(timelines)
            min_len = min(len(t) for t in timelines)
            t_crit = _t_critical(n) if n >= 2 else 0.0

            for s in range(0, min_len, 10):
                vals = [t[s] for t in timelines]
                mean_v = sum(vals) / n
                if n >= 2:
                    var = sum((v - mean_v) ** 2 for v in vals) / (n - 1)
                    ci95 = t_crit * math.sqrt(var / n)
                else:
                    ci95 = 0.0
                writer.writerow(list(key) + [s, round(mean_v, 6), round(ci95, 6)])
                rows_written += 1

    print(f"  Convergence   -> {path}  ({rows_written} rows)")


def _write_summary_csv(results: List[Dict[str, Any]], path: Path) -> None:
    """Aggregate results: mean +/- std per (map_tag, human_model_tag, solver_label, num_humans).

    Note: unlike the agents study, the grouping key here is num_humans (not
    num_agents), since agents are fixed per map and humans vary.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Group by identifying keys — num_humans is the sweep variable
    group_keys = ("map_tag", "human_model_tag", "solver_label", "num_humans")
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            key = tuple(r.get(k, "") for k in group_keys)
            grouped[key].append(r)

    # Build summary rows
    rows: List[Dict[str, Any]] = []
    for key, recs in sorted(grouped.items()):
        row: Dict[str, Any] = dict(zip(group_keys, key))
        row["free_cells"] = recs[0].get("free_cells", 0)
        row["num_agents"] = recs[0].get("num_agents", 0)
        row["max_humans"] = recs[0].get("max_humans", 0)
        row["map_path"] = recs[0].get("map_path", "")
        row["n_seeds"] = len(recs)
        n = len(recs)
        t_crit = _t_critical(n) if n >= 2 else 0.0
        for m in KEY_METRICS:
            vals = [rec.get(m, 0) for rec in recs]
            mean_v = sum(vals) / len(vals)
            var = sum((v - mean_v) ** 2 for v in vals) / max(n - 1, 1)
            std_v = math.sqrt(var)
            ci95 = t_crit * std_v / math.sqrt(n) if n >= 2 else 0.0
            row[f"{m}_mean"] = round(mean_v, 6)
            row[f"{m}_std"] = round(std_v, 6)
            row[f"{m}_ci95"] = round(ci95, 6)
        row["wall_time_s_mean"] = round(
            sum(r.get("wall_time_s", 0) for r in recs) / max(len(recs), 1), 2
        )
        rows.append(row)

    # Column order
    summary_id_cols = list(group_keys) + [
        "free_cells", "num_agents", "max_humans", "map_path", "n_seeds",
    ]
    metric_cols = [f"{m}_{stat}" for m in KEY_METRICS for stat in ("mean", "std", "ci95")]
    summary_cols = summary_id_cols + metric_cols + ["wall_time_s_mean"]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Summary       -> {path}")


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------

def _print_map_summary(map_info: Dict[str, Any]) -> None:
    """Print map analysis summary."""
    print(
        f"  {map_info['map_tag']:<20} "
        f"free={map_info['free_cells']:>6}  "
        f"agents(fixed)={map_info['num_agents']:>5}  "
        f"max_humans={map_info['max_humans']:>5}  "
        f"safety_r={map_info['safety_radius']}  "
        f"solvers={map_info['solvers']}"
    )
    print(
        f"  {'':<20} "
        f"human_counts={map_info['human_counts']}"
    )


def _print_results_table(results: List[Dict[str, Any]]) -> None:
    """Print a summary table per map."""
    grouped: Dict[Tuple[str, str, str, int], List[Dict]] = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            key = (r["map_tag"], r["human_model_tag"], r["solver_label"], r["num_humans"])
            grouped[key].append(r)

    def _mean(recs: List[Dict], key: str) -> float:
        vals = [rec.get(key, 0) for rec in recs]
        return sum(vals) / max(len(vals), 1)

    map_tags_seen = sorted({k[0] for k in grouped})
    for mt in map_tags_seen:
        sep = "=" * 105
        print(f"\n{sep}")
        print(f"Map: {mt}")
        header = (
            f"  {'Solver':<12} {'HumanModel':<10} {'Humans':>6}  {'n':>2}  "
            f"{'Thr':>7}  {'Cmp%':>6}  {'PlanMs':>8}  {'SafeV':>6}  {'FlowT':>7}"
        )
        print(header)
        print("-" * 105)

        entries = sorted(
            [(k, v) for k, v in grouped.items() if k[0] == mt],
            key=lambda kv: (kv[0][3], kv[0][1], kv[0][2]),  # sort by humans, hm, solver
        )
        for (_, hm, solver, n_humans), recs in entries:
            n = len(recs)
            thr = _mean(recs, "throughput")
            cmp = _mean(recs, "task_completion") * 100
            pt = _mean(recs, "mean_planning_time_ms")
            sv = _mean(recs, "safety_violations")
            ft = _mean(recs, "mean_flowtime")
            print(
                f"  {solver:<12} {hm:<10} {n_humans:>6}  {n:>2}  "
                f"{thr:>7.4f}  {cmp:>5.1f}%  {pt:>8.2f}  {sv:>6.0f}  {ft:>7.1f}"
            )
        print(sep)

    # Report skipped/errored
    unavailable = [r for r in results if r.get("status") in ("skip", "error")]
    if unavailable:
        seen: set = set()
        print("\n  Unavailable / errored:")
        for r in unavailable:
            key = (r.get("map_tag"), r.get("solver_label"), r.get("status"))
            if key not in seen:
                seen.add(key)
                print(f"    solver={key[1]:<12}  map={key[0]}  status={key[2]}")


# ---------------------------------------------------------------------------
# Core study runner
# ---------------------------------------------------------------------------

def run_full_study(
        seeds: List[int],
        map_tags: List[str],
        human_tags: List[str],
        solver_labels: List[str],
        base_config: Dict[str, Any],
        output_dir: Path,
        workers: int = 1,
        verbose: bool = False,
) -> List[Dict[str, Any]]:
    """Run the full factorial human-count sweep study."""

    # Step 1: Analyse maps
    print("\nMap analysis:")
    solver_lookup = {label: factory for label, factory in SOLVER_DEFS}
    map_infos: List[Dict[str, Any]] = []
    for mt in map_tags:
        mdef = MAP_DEFS[mt]
        info = analyse_map(mt, mdef)
        _print_map_summary(info)
        if info["human_counts"]:
            map_infos.append(info)
        else:
            print(f"  SKIPPING map {mt}: no valid human counts.")

    if not map_infos:
        print("ERROR: No maps with valid human counts. Nothing to run.")
        return []

    # Step 2: Build all tasks
    # Outer loop: map → human_model → solver → num_humans → seed
    # Solvers are determined per map (small vs large).
    tasks: List[Tuple[Dict[str, Any], Dict[str, Any], str, bool]] = []
    for minfo in map_infos:
        mt = minfo["map_tag"]
        # Intersect per-map solvers with user-requested solvers
        map_solvers = [s for s in minfo["solvers"] if s in solver_labels]
        for hm_tag in human_tags:
            hm_cfg = HUMAN_MODELS[hm_tag]
            for solver_label in map_solvers:
                factory_name = solver_lookup.get(solver_label)
                if factory_name is None:
                    print(f"  WARNING: solver {solver_label!r} not in SOLVER_DEFS — skipping.")
                    continue
                for n_humans in minfo["human_counts"]:
                    for seed in seeds:
                        cfg = {
                            **base_config,
                            "map_path": minfo["map_path"],
                            "num_agents": minfo["num_agents"],  # fixed per map
                            "num_humans": n_humans,  # sweep variable
                            "safety_radius": minfo["safety_radius"],  # per-map
                            "global_solver": factory_name,
                            "seed": seed,
                            **hm_cfg,
                        }
                        # Metadata for CSV (not part of SimConfig)
                        meta = {
                            "map_tag": mt,
                            "map_path": minfo["map_path"],
                            "free_cells": minfo["free_cells"],
                            "num_agents": minfo["num_agents"],
                            "max_humans": minfo["max_humans"],
                            "num_humans": n_humans,
                            "human_model_tag": hm_tag,
                            "solver_label": solver_label,
                            "seed": seed,
                        }
                        label = f"{mt}__{solver_label}_{hm_tag}_h{n_humans}_s{seed}"
                        tasks.append((cfg, meta, label, verbose))

    total_runs = len(tasks)
    print(f"\nStudy configuration:")
    print(f"  Maps:          {[m['map_tag'] for m in map_infos]}")
    print(f"  Human models:  {human_tags}")
    print(f"  Solvers:       {solver_labels}")
    print(f"  Seeds:         {len(seeds)} ({seeds[0]}..{seeds[-1]})")
    print(f"  Total runs:    {total_runs}")
    print(f"  Workers:       {workers}")
    print(f"  Output:        {output_dir}")

    if total_runs == 0:
        print("No runs to execute.")
        return []

    # Step 3: Execute
    print(f"\nRunning {total_runs} experiments...")
    t_start = time.monotonic()
    results: List[Dict[str, Any]] = []

    if workers <= 1:
        for i, task in enumerate(tasks, 1):
            r = _worker_task(task)
            results.append(r)
            if i % 10 == 0 or i == total_runs:
                elapsed = time.monotonic() - t_start
                print(f"  Progress: {i}/{total_runs}  ({elapsed:.0f}s elapsed)")
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker_task, t): t for t in tasks}
            done_count = 0
            for fut in as_completed(futures):
                done_count += 1
                try:
                    results.append(fut.result())
                except Exception as exc:
                    task = futures[fut]
                    print(f"  Worker error for {task[2]}: {exc}")
                if done_count % 10 == 0 or done_count == total_runs:
                    elapsed = time.monotonic() - t_start
                    print(f"  Progress: {done_count}/{total_runs}  ({elapsed:.0f}s elapsed)")

    total_time = time.monotonic() - t_start
    print(f"\nAll runs finished in {total_time:.1f}s")

    # Step 4: Save results
    raw_dir = output_dir / "raw"
    agg_dir = output_dir / "aggregated"
    meta_dir = output_dir / "metadata"
    fig_dir = output_dir / "figures"
    for d in (raw_dir, agg_dir, meta_dir, fig_dir):
        d.mkdir(parents=True, exist_ok=True)

    _write_raw_csv(results, raw_dir / "results.csv")
    _write_summary_csv(results, agg_dir / "summary.csv")
    _write_convergence_csv(results, agg_dir / "convergence.csv")

    # Save metadata
    metadata = {
        "study_name": "compare_global_planners_human_sweep",
        "timestamp": datetime.now().isoformat(),
        "seeds": seeds,
        "n_seeds": len(seeds),
        "maps": {
            mi["map_tag"]: {
                "map_path": mi["map_path"],
                "free_cells": mi["free_cells"],
                "num_agents": mi["num_agents"],
                "max_humans": mi["max_humans"],
                "human_counts": mi["human_counts"],
            }
            for mi in map_infos
        },
        "human_models": human_tags,
        "solvers": solver_labels,
        "base_config": {k: v for k, v in base_config.items()
                        if not isinstance(v, (type(None),))
                        or v is None},
        "total_runs": total_runs,
        "ok_runs": sum(1 for r in results if r.get("status") == "ok"),
        "skip_runs": sum(1 for r in results if r.get("status") == "skip"),
        "error_runs": sum(1 for r in results if r.get("status") == "error"),
        "total_wall_time_s": round(total_time, 2),
    }
    meta_path = meta_dir / "config.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"  Metadata      -> {meta_path}")

    # Step 5: Print summary
    _print_results_table(results)

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Human-Count Sweep Study for HA-LMAPF Global Planners.\n"
            "Compares global planners (4-6 per map) across 4 maps and 3 human-model settings,\n"
            "with fixed agents per map and varying human counts."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--maps", type=str, nargs="+",
        default=ALL_MAP_TAGS,
        choices=ALL_MAP_TAGS,
        metavar="MAP_TAG",
        help=f"Maps to include (default: all — {ALL_MAP_TAGS})",
    )
    parser.add_argument(
        "--human-models", type=str, nargs="+",
        default=ALL_HUMAN_TAGS,
        choices=ALL_HUMAN_TAGS,
        metavar="HM",
        help=f"Human model settings (default: all — {ALL_HUMAN_TAGS})",
    )
    parser.add_argument(
        "--solvers", type=str, nargs="+",
        default=ALL_SOLVER_LABELS,
        metavar="SOLVER",
        help=f"Solver labels (default: all — {ALL_SOLVER_LABELS})",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+",
        default=list(range(10)),
        metavar="SEED",
        help="Random seeds (default: 0 1 2 ... 9 — ten seeds)",
    )
    parser.add_argument(
        "--steps", type=int, default=None,
        help="Override simulation length (default: 2000)",
    )
    parser.add_argument(
        "--out", type=str, default="logs/solvers/human",
        help="Base output directory (default: logs/solvers/human)",
    )
    parser.add_argument(
        "--run-name", type=str, default=None,
        metavar="NAME",
        help=(
            "Sub-directory name for this run. "
            "Results land in <out>/<run-name>/. "
            "Defaults to a timestamp: human_sweep_YYYYMMDD_HHMMSS"
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Parallel worker processes (0 = all CPU cores)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print per-run metrics to stdout",
    )
    parser.add_argument(
        "--sanity", action="store_true",
        help="Quick smoke-test: 1 seed, 200 steps, first human count only",
    )
    args = parser.parse_args()

    # Build base config
    base_cfg = dict(BASE_CONFIG)
    if args.steps:
        base_cfg["steps"] = args.steps

    n_workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)

    # Unique run directory — timestamp-based, never overwrites prior runs
    run_name = args.run_name or datetime.now().strftime("human_sweep_%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validate solver labels
    valid_solvers = {label for label, _ in SOLVER_DEFS}
    for s in args.solvers:
        if s not in valid_solvers:
            print(
                f"WARNING: solver {s!r} not in SOLVER_DEFS "
                f"(available: {sorted(valid_solvers)}). "
                f"It will be skipped during execution."
            )

    # Header
    print(f"\nHuman-Count Sweep Study for HA-LMAPF Global Planners")
    print(f"  Date          : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Run name      : {run_name}")
    print(f"  Steps         : {base_cfg['steps']}")
    print(f"  Planning budget: {base_cfg['time_budget_ms']}ms")
    print(f"  Seeds         : {args.seeds}  (n={len(args.seeds)})")
    print(f"  Maps          : {args.maps}")
    print(f"  Human models  : {args.human_models}")
    print(f"  Solvers       : {args.solvers}")
    print(f"  Workers       : {n_workers}")
    print(f"  Output        : {out_dir}")

    # Sanity mode overrides
    seeds = args.seeds
    if args.sanity:
        seeds = [0]
        base_cfg["steps"] = 200
        print("\n  ** SANITY MODE: 1 seed, 200 steps **")

    # Run
    results = run_full_study(
        seeds=seeds,
        map_tags=args.maps,
        human_tags=args.human_models,
        solver_labels=args.solvers,
        base_config=base_cfg,
        output_dir=out_dir,
        workers=n_workers,
        verbose=args.verbose,
    )

    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"\nStudy complete. {ok}/{len(results)} runs succeeded.")
    print(f"Results in: {out_dir}")
    print(f"\nTo generate plots, run:")
    print(f"  python scripts/solvers/plot_compare_global_results_human.py --run-dir {out_dir}")


if __name__ == "__main__":
    main()
