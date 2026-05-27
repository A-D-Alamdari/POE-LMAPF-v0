#!/usr/bin/env python3
"""
Global Solver Selection Study for HA-LMAPF.

Benchmarks all global solver wrappers (excluding pure-Python fallbacks and
RHCR) across three representative map types to justify selection of the
global planner for publication.

The study is intentionally narrow in scope: every experiment varies only
the global solver while keeping all other HA-LMAPF parameters fixed.
This isolates solver quality from system-level tuning.

Solvers benchmarked
-------------------
  lacam     – LaCAM (official C++ wrapper)
  lacam3    – LaCAM3 anytime (C++ wrapper)
  rt_lacam  – Real-Time LaCAM persistent DFS (C++ wrapper)
  lns2      – MAPF-LNS2 large-neighbourhood search (C++ wrapper)
  pibt2     – PIBT2 (C++ wrapper, one-shot mode)
  pbs       – Priority-Based Search (C++ wrapper)
  cbsh2     – CBS with heuristics 2 (C++ wrapper)

Excluded solvers
----------------
  pylacam   – pure-Python reference; too slow for fleet sizes ≥ 10
  rhcr      – rolling-horizon collision resolution; not available in this build

Map types (three representative environments)
----------------------------------------------
  warehouse  data/maps/warehouse-10-20-10-2-1.map   63×161, narrow aisles
  room       data/maps/room-64-64-8.map              64×64,  room-divided
  random     data/maps/random-64-64-10.map           64×64,  random obstacles

Studies
-------
  1  solver_baseline   All solvers at canonical hyperparameters.
                       Primary table in the paper.

  2  scalability       Fleet-size sweep [5, 10, 15, 20, 30] per solver per map.
                       Shows which solvers remain practical at scale.

  3  time_limit        Per-call planning time budget sweep for anytime solvers
                       (lacam, lacam3, lns2, rt_lacam).
                       Guides the time-limit default used in the final system.

Metrics collected per run
--------------------------
  throughput              tasks / step
  task_completion         fraction of tasks completed
  completed_tasks         raw count
  local_replans           Tier-2 A* fallback triggers
  global_replans          Tier-1 replanning triggers
  mean_planning_time_ms   mean Tier-1 planning latency
  p95_planning_time_ms    95th-percentile planning latency
  max_planning_time_ms    worst-case planning latency
  safety_violations       hard-safety WAITs imposed
  collisions_agent_agent  agent–agent contacts
  collisions_agent_human  agent–human contacts
  near_misses             passes within distance 1 of a human
  mean_flowtime           mean task-completion latency (steps)

Usage
-----
  # Run all three studies on all three maps, 10 seeds, 8 workers
  python scripts/run_solver_study.py --all --seeds $(seq -s' ' 0 9) --workers 8

  # Single study, specific maps
  python scripts/run_solver_study.py --study solver_baseline --maps warehouse room

  # Quick smoke-test (1 seed, 200 steps)
  python scripts/run_solver_study.py --sanity

Output
------
  logs/solver_study/
  ├── results_solver_baseline.csv    raw per-seed, per-map rows
  ├── summary_solver_baseline.csv    mean ± std aggregated over seeds, per map+entry
  ├── results_scalability.csv
  ├── summary_scalability.csv
  ├── results_time_limit.csv
  └── summary_time_limit.csv

python scripts/plot_solver_study.py --log-dir logs/solver_study/run_20260313_143022

"""

from __future__ import annotations

import argparse
import csv
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

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ha_lmapf.core.types import SimConfig, Metrics
from ha_lmapf.simulation.simulator import Simulator

# ---------------------------------------------------------------------------
# Map configurations
# Three map types chosen to represent qualitatively different environments:
#   warehouse – structured, narrow aisles (high contention, directional flow)
#   room      – room-divided topology (choke-point transitions)
#   random    – unstructured random obstacles (general-purpose benchmark)
#
# Agent / human counts are scaled to ~10-15% occupancy of traversable area
# so that solvers are neither trivially easy (empty map) nor permanently
# blocked (over-crowded).
# ---------------------------------------------------------------------------
MAP_CONFIGS: Dict[str, Dict[str, Any]] = {
    "warehouse": {
        "map_path": "data/maps/warehouse-10-20-10-2-1.map",
        "num_agents": 20,
        "num_humans": 4,
        "horizon": 50,
        "replan_every": 25,
    },
    "room": {
        "map_path": "data/maps/room-64-64-8.map",
        "num_agents": 15,
        "num_humans": 3,
        "horizon": 40,
        "replan_every": 20,
    },
    "random": {
        "map_path": "data/maps/random-64-64-10.map",
        "num_agents": 15,
        "num_humans": 3,
        "horizon": 40,
        "replan_every": 20,
    },
}

ALL_MAP_TAGS: List[str] = list(MAP_CONFIGS)

# ---------------------------------------------------------------------------
# Base simulation configuration
# These values are kept constant across all studies so that any performance
# difference is attributable solely to the global solver.
# ---------------------------------------------------------------------------
BASE_CONFIG: Dict[str, Any] = {
    "task_stream_path": None,
    "steps": 2000,  # long enough for stable statistics
    "fov_radius": 4,
    "safety_radius": 1,
    "hard_safety": True,
    "global_solver": "lacam",  # overridden per-study entry
    "task_allocator": "congestion_avoidance",
    "commit_horizon": 0,  # disabled: avoids premature revocation
    "delay_threshold": 0.0,  # disabled: avoids task revocation
    "task_arrival_rate": 5,
    "task_arrival_percentage": 0.9,
    "communication_mode": "token",
    "local_planner": "astar",
    "human_model": "random_walk",
    "human_model_params": {},
    "execution_delay_prob": 0.0,
    "execution_delay_steps": 1,
    "disable_local_replan": False,
    "disable_conflict_resolution": False,
    "disable_safety": False,
    "seed": 0,  # overridden per run
}

# ---------------------------------------------------------------------------
# Metrics recorded for every simulation run
# ---------------------------------------------------------------------------
KEY_METRICS: List[str] = [
    "throughput",
    "task_completion",
    "completed_tasks",
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
# Solver catalogue
# Each entry: (label, solver_name, solver_kwargs)
#   label        – human-readable short name used in CSV rows and table output
#   solver_name  – key passed to GlobalPlannerFactory.create()
#   solver_kwargs – forwarded to the solver constructor
# ---------------------------------------------------------------------------
SOLVER_CATALOGUE: List[Tuple[str, str, Dict[str, Any]]] = [
    ("lacam", "lacam", {}),
    ("lacam3", "lacam3", {}),
    ("rt_lacam", "rt_lacam", {}),
    ("lns2", "lns2", {}),
    ("pibt2", "pibt", {}),
    ("pbs", "pbs", {}),
    ("cbsh2", "cbsh2", {}),
]

# Subset used for scalability / time-limit studies where cbsh2 becomes
# too slow at larger fleet sizes to be practically useful.
_SCALABLE_SOLVERS: List[Tuple[str, str, Dict[str, Any]]] = [
    ("lacam", "lacam", {}),
    ("lacam3", "lacam3", {}),
    ("rt_lacam", "rt_lacam", {}),
    ("lns2", "lns2", {}),
    ("pibt2", "pibt", {}),
    ("pbs", "pbs", {}),
]

# Solvers that expose a per-call time budget (anytime behaviour).
_ANYTIME_SOLVERS: List[Tuple[str, str]] = [
    ("lacam", "lacam"),
    ("lacam3", "lacam3"),
    ("lns2", "lns2"),
]
_ANYTIME_TIME_LIMITS_SEC: List[float] = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0]

# rt_lacam uses time_limit_ms (milliseconds) instead of time_limit_sec.
_RT_LACAM_TIME_LIMITS_MS: List[int] = [50, 100, 250, 500, 1000, 2000]

# Agent counts for the scalability sweep.
# cbsh2 is excluded above fleet ≥ 20 (exponential cost growth).
_SCALE_AGENTS: List[int] = [5, 10, 15, 20, 30]

# ---------------------------------------------------------------------------
# Study 1: Solver baseline
# ---------------------------------------------------------------------------
STUDY_SOLVER_BASELINE: Dict[str, Any] = {
    "description": (
        "All solvers at canonical hyperparameters across all map types. "
        "Primary comparison table for the paper."
    ),
    "solvers": SOLVER_CATALOGUE,
    "config_override": {},
}

# ---------------------------------------------------------------------------
# Study 2: Fleet-size scalability
# ---------------------------------------------------------------------------
STUDY_SCALABILITY: Dict[str, Any] = {
    "description": (
        "Throughput and planning latency vs fleet size for practical solvers. "
        "Demonstrates which solver remains viable at the target deployment scale."
    ),
    "entries": [
        (f"{name}_a{n}", solver_name, kwargs, {"num_agents": n, "num_humans": max(1, n // 5)})
        for (name, solver_name, kwargs) in _SCALABLE_SOLVERS
        for n in _SCALE_AGENTS
    ],
    "config_override": {},
}

# ---------------------------------------------------------------------------
# Study 3: Planning time budget
# ---------------------------------------------------------------------------
STUDY_TIME_LIMIT: Dict[str, Any] = {
    "description": (
        "Effect of per-call planning time budget on solution quality for "
        "anytime solvers. Guides the choice of time-limit in the final system."
    ),
    "entries": (
        # Standard anytime solvers using time_limit_sec
            [
                (f"{name}_t{t}s", solver_name, {"time_limit_sec": t})
                for (name, solver_name) in _ANYTIME_SOLVERS
                for t in _ANYTIME_TIME_LIMITS_SEC
            ]
            +
            # rt_lacam uses time_limit_ms
            [
                (f"rt_lacam_t{ms}ms", "rt_lacam", {"time_limit_ms": ms})
                for ms in _RT_LACAM_TIME_LIMITS_MS
            ]
    ),
    "config_override": {},
}

# ---------------------------------------------------------------------------
# Study registry
# ---------------------------------------------------------------------------
STUDIES: Dict[str, Dict[str, Any]] = {
    "solver_baseline": STUDY_SOLVER_BASELINE,
    "scalability": STUDY_SCALABILITY,
    "time_limit": STUDY_TIME_LIMIT,
}


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _build_sim_config(config_dict: Dict[str, Any]) -> SimConfig:
    known = {f.name for f in dc_fields(SimConfig)}
    filtered = {k: v for k, v in config_dict.items() if k in known}
    return SimConfig(**filtered)


def _inject_solver(
        sim: "Simulator",
        solver_name: str,
        solver_kwargs: Dict[str, Any],
) -> None:
    """
    Replace the solver inside a pre-built Simulator's RollingHorizonPlanner
    with a custom instance carrying solver-specific kwargs (e.g. time_limit_sec).
    """
    if not solver_kwargs:
        return
    from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
    try:
        custom_solver = GlobalPlannerFactory.create(solver_name, **solver_kwargs)
        sim.global_planner.solver = custom_solver
    except Exception as exc:
        print(
            f"  [solver_study] WARNING: could not inject solver {solver_name!r} "
            f"with kwargs {solver_kwargs}: {exc}"
        )


def run_single_experiment(
        config_dict: Dict[str, Any],
        solver_kwargs: Dict[str, Any],
        label: str,
        verbose: bool = False,
) -> Tuple[Dict[str, Any], float]:
    """
    Run one simulation and return (metrics_dict, wall_clock_seconds).

    The returned dict has a 'status' key:
      'ok'    – simulation completed successfully
      'skip'  – solver binary not found (solver unavailable on this machine)
      'error' – unexpected exception; metrics are zero-filled
    """
    t0 = time.monotonic()
    config = _build_sim_config(config_dict)

    try:
        sim = Simulator(config)
        _inject_solver(sim, config_dict["global_solver"], solver_kwargs)
        metrics: Metrics = sim.run()
        wall = time.monotonic() - t0

        m_dict = {k: getattr(metrics, k, 0) for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "ok"

        if verbose:
            print(
                f"    [{label}] "
                f"thr={metrics.throughput:.4f}  "
                f"cmp={metrics.task_completion:.1%}  "
                f"lreplan={metrics.local_replans}  "
                f"pt={metrics.mean_planning_time_ms:.1f}ms  "
                f"wall={wall:.1f}s"
            )
        return m_dict, wall

    except FileNotFoundError as exc:
        wall = time.monotonic() - t0
        print(f"    [{label}] SKIP — binary not found: {exc}")
        m_dict = {k: 0 for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "skip"
        return m_dict, wall

    except Exception as exc:
        wall = time.monotonic() - t0
        print(f"    [{label}] ERROR: {exc}")
        m_dict = {k: 0 for k in KEY_METRICS}
        m_dict["wall_time_s"] = round(wall, 3)
        m_dict["status"] = "error"
        return m_dict, wall


# ---------------------------------------------------------------------------
# Picklable worker (required for multiprocessing)
# ---------------------------------------------------------------------------

def _worker_task(args: Tuple) -> Dict[str, Any]:
    config_dict, solver_kwargs, label, verbose = args
    m_dict, _ = run_single_experiment(config_dict, solver_kwargs, label, verbose)
    return {"_label": label, **m_dict}


# ---------------------------------------------------------------------------
# Study entry normalisation
# ---------------------------------------------------------------------------

def _entries_from_study(
        study: Dict[str, Any],
) -> List[Tuple[str, str, Dict[str, Any], Dict[str, Any]]]:
    """
    Return a uniform list of (label, solver_name, solver_kwargs, config_override)
    tuples from any study definition format.
    """
    entries: List[Tuple[str, str, Dict[str, Any], Dict[str, Any]]] = []
    global_override = study.get("config_override", {})

    if "solvers" in study:
        for item in study["solvers"]:
            label, solver_name, solver_kwargs = item
            entries.append((label, solver_name, solver_kwargs, global_override))

    elif "entries" in study:
        for item in study["entries"]:
            if len(item) == 3:
                label, solver_name, solver_kwargs = item
                cfg_ovr = global_override.copy()
            else:
                label, solver_name, solver_kwargs, item_ovr = item
                cfg_ovr = {**global_override, **item_ovr}
            entries.append((label, solver_name, solver_kwargs, cfg_ovr))

    return entries


# ---------------------------------------------------------------------------
# Core study runner
# ---------------------------------------------------------------------------

def run_study(
        study_name: str,
        seeds: List[int],
        base_config: Dict[str, Any],
        map_tags: List[str],
        output_dir: Path,
        workers: int = 1,
        verbose: bool = False,
) -> List[Dict[str, Any]]:
    """
    Run one study across the specified map types.

    For each map_tag, the map's config overrides (map_path, num_agents,
    num_humans, horizon, replan_every) are merged into base_config before
    building simulation configs.  The map_tag is stored in every result row
    so results from all maps land in a single CSV file.

    Returns all result dicts.
    """
    if study_name not in STUDIES:
        raise ValueError(
            f"Unknown study: {study_name!r}. Available: {sorted(STUDIES)}"
        )

    study = STUDIES[study_name]
    entries = _entries_from_study(study)

    total_runs = len(entries) * len(seeds) * len(map_tags)
    print(f"\n{'=' * 72}")
    print(f"Study : {study_name}")
    print(f"Desc  : {study.get('description', '')}")
    print(f"Maps  : {map_tags}")
    print(f"Entries: {len(entries)}  Seeds: {len(seeds)}  "
          f"Maps: {len(map_tags)}  Total runs: {total_runs}  Workers: {workers}")
    print(f"{'=' * 72}")

    # Build all tasks
    tasks: List[Tuple[Dict[str, Any], Dict[str, Any], str, bool]] = []
    for map_tag in map_tags:
        map_cfg = MAP_CONFIGS.get(map_tag, {})
        for seed in seeds:
            for (label, solver_name, solver_kwargs, cfg_ovr) in entries:
                cfg = {
                    **base_config,
                    **map_cfg,  # map-specific overrides first
                    **cfg_ovr,  # study-specific overrides (may override agents)
                    "global_solver": solver_name,
                    "seed": seed,
                }
                full_label = f"{map_tag}__{label}_s{seed}"
                tasks.append((cfg, solver_kwargs, full_label, verbose))

    # Execute
    results: List[Dict[str, Any]] = []
    if workers <= 1:
        for task in tasks:
            r = _worker_task(task)
            results.append(r)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker_task, t): t for t in tasks}
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as exc:
                    task = futures[fut]
                    print(f"  Worker error for {task[2]}: {exc}")

    # Attach metadata (map_tag, entry, seed) by parsing _label
    for r in results:
        label_raw = r["_label"]  # e.g. "warehouse__lacam_s3"
        r["study"] = study_name
        r["map_tag"] = "unknown"
        r["entry"] = label_raw
        r["seed"] = -1

        for mt in map_tags:
            prefix = f"{mt}__"
            if label_raw.startswith(prefix):
                remainder = label_raw[len(prefix):]  # e.g. "lacam_s3"
                r["map_tag"] = mt
                for seed in seeds:
                    suffix = f"_s{seed}"
                    if remainder.endswith(suffix):
                        r["entry"] = remainder[: -len(suffix)]
                        r["seed"] = seed
                        break
                else:
                    r["entry"] = remainder
                break

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = output_dir / f"results_{study_name}.csv"
    _write_raw_csv(results, raw_csv)

    summary_csv = output_dir / f"summary_{study_name}.csv"
    _write_summary_csv(results, summary_csv, study_name)

    return results


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ["study", "map_tag", "entry", "seed", "status", "wall_time_s"] + KEY_METRICS


def _write_raw_csv(results: List[Dict[str, Any]], path: Path) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"  Raw results  → {path}")


def _write_summary_csv(
        results: List[Dict[str, Any]],
        path: Path,
        study_name: str,
) -> None:
    """Aggregate results: mean ± std per (map_tag, entry) across seeds."""
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            grouped[(r["map_tag"], r["entry"])].append(r)

    rows: List[Dict[str, Any]] = []
    for (map_tag, entry), recs in sorted(grouped.items()):
        row: Dict[str, Any] = {
            "study": study_name,
            "map_tag": map_tag,
            "entry": entry,
            "n_seeds": len(recs),
        }
        for m in KEY_METRICS:
            vals = [rec.get(m, 0) for rec in recs]
            mean_v = sum(vals) / len(vals)
            var = sum((v - mean_v) ** 2 for v in vals) / max(len(vals) - 1, 1)
            row[f"{m}_mean"] = round(mean_v, 4)
            row[f"{m}_std"] = round(math.sqrt(var), 4)
        row["wall_time_s_mean"] = round(
            sum(r.get("wall_time_s", 0) for r in recs) / max(len(recs), 1), 2
        )
        rows.append(row)

    summary_cols = (
            ["study", "map_tag", "entry", "n_seeds"]
            + [f"{m}_{stat}" for m in KEY_METRICS for stat in ("mean", "std")]
            + ["wall_time_s_mean"]
    )
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  Summary      → {path}")


# ---------------------------------------------------------------------------
# Console summary table
# ---------------------------------------------------------------------------

def _print_summary_table(results: List[Dict[str, Any]], study_name: str) -> None:
    """Print a per-map-type ranking table sorted by mean throughput."""
    from collections import defaultdict

    # Group by (map_tag, entry)
    grouped: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            grouped[(r["map_tag"], r["entry"])].append(r)

    def _mean(recs: List[Dict], key: str) -> float:
        vals = [rec.get(key, 0) for rec in recs]
        return sum(vals) / max(len(vals), 1)

    # Print one table per map_tag
    map_tags_seen = sorted({k[0] for k in grouped})
    for mt in map_tags_seen:
        entries_for_map = {
            entry: recs
            for (m, entry), recs in grouped.items()
            if m == mt
        }
        ranked = sorted(
            entries_for_map.items(),
            key=lambda kv: _mean(kv[1], "throughput"),
            reverse=True,
        )

        header = (
            f"  {'Entry':<28} {'n':>2}  "
            f"{'Thr':>7}  {'Cmp%':>6}  "
            f"{'PlanMs':>8}  {'P95Ms':>7}  "
            f"{'SafeV':>6}  {'NearMs':>6}  {'FlowT':>7}"
        )
        sep = "=" * (len(header) - 2)
        print(f"\n{sep}")
        print(f"Study: {study_name}   Map: {mt}")
        print(header)
        print("-" * (len(header) - 2))
        for entry, recs in ranked:
            n = len(recs)
            thr = _mean(recs, "throughput")
            cmp = _mean(recs, "task_completion") * 100
            pt = _mean(recs, "mean_planning_time_ms")
            p95 = _mean(recs, "p95_planning_time_ms")
            sv = _mean(recs, "safety_violations")
            nm = _mean(recs, "near_misses")
            ft = _mean(recs, "mean_flowtime")
            print(
                f"  {entry:<28} {n:>2}  "
                f"{thr:>7.4f}  {cmp:>5.1f}%  "
                f"{pt:>8.2f}  {p95:>7.2f}  "
                f"{sv:>6.0f}  {nm:>6.0f}  {ft:>7.1f}"
            )
        print(sep)

    # Skipped / errored
    unavailable = [r for r in results if r.get("status") in ("skip", "error")]
    if unavailable:
        seen: set = set()
        print("\n  Unavailable / errored:")
        for r in unavailable:
            key = (r.get("map_tag", "?"), r.get("entry", r.get("_label", "?")))
            if key not in seen:
                seen.add(key)
                print(f"    {key[1]:<35}  map={key[0]}  status={r.get('status')}")


# ---------------------------------------------------------------------------
# Sanity check
# ---------------------------------------------------------------------------

def run_sanity_check(
        base_config: Dict[str, Any],
        map_tags: List[str],
        output_dir: Path,
) -> None:
    """Smoke-test: run every solver for 200 steps on each requested map."""
    print(f"\n{'=' * 60}")
    print("SOLVER SANITY CHECK — 200 steps, seed 0")
    print(f"{'=' * 60}")
    cfg = {**base_config, "steps": 200}
    results = run_study(
        "solver_baseline",
        seeds=[0],
        base_config=cfg,
        map_tags=map_tags,
        output_dir=output_dir,
        workers=1,
        verbose=True,
    )
    _print_summary_table(results, "solver_baseline [sanity]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Global Solver Selection Study for HA-LMAPF.\n"
            "Produces paper-quality CSV data to justify global planner choice."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--study", type=str, default=None,
        choices=list(STUDIES),
        help="Run a single named study",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all three studies (solver_baseline, scalability, time_limit)",
    )
    parser.add_argument(
        "--sanity", action="store_true",
        help="Quick smoke-test: all solvers, 200 steps, seed 0",
    )
    parser.add_argument(
        "--maps", type=str, nargs="+",
        default=ALL_MAP_TAGS,
        choices=ALL_MAP_TAGS,
        metavar="MAP_TAG",
        help=f"Map types to include (default: all — {ALL_MAP_TAGS})",
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+",
        default=list(range(10)),
        metavar="SEED",
        help="Random seeds (default: 0 1 2 … 9 — ten seeds for paper)",
    )
    parser.add_argument(
        "--steps", type=int, default=None,
        help="Override simulation length (default: 2000)",
    )
    parser.add_argument(
        "--out", type=str, default="logs/solver_study",
        help="Base output directory (default: logs/solver_study)",
    )
    parser.add_argument(
        "--run-name", type=str, default=None,
        metavar="NAME",
        help=(
            "Sub-directory name for this run.  "
            "Results land in <out>/<run-name>/.  "
            "Defaults to a timestamp: run_YYYYMMDD_HHMMSS"
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
    args = parser.parse_args()

    # Build base config
    base_cfg = dict(BASE_CONFIG)
    if args.steps:
        base_cfg["steps"] = args.steps

    n_workers = args.workers if args.workers > 0 else (os.cpu_count() or 1)

    run_name = args.run_name or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Header
    print(f"\nGlobal Solver Selection Study")
    print(f"  Date     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Run name : {run_name}")
    print(f"  Steps    : {base_cfg['steps']}")
    print(f"  Seeds    : {args.seeds}  (n={len(args.seeds)})")
    print(f"  Maps     : {args.maps}")
    print(f"  Workers  : {n_workers}")
    print(f"  Output   : {out_dir}")

    # Sanity check
    if args.sanity:
        run_sanity_check(base_cfg, args.maps, out_dir / "sanity")
        return

    # Determine studies to run
    if args.all:
        study_names = list(STUDIES)
    elif args.study:
        study_names = [args.study]
    else:
        parser.print_help()
        print("\nSpecify --study <name>, --all, or --sanity")
        sys.exit(1)

    # Run
    for study_name in study_names:
        results = run_study(
            study_name,
            seeds=args.seeds,
            base_config=base_cfg,
            map_tags=args.maps,
            output_dir=out_dir,
            workers=n_workers,
            verbose=args.verbose,
        )
        _print_summary_table(results, study_name)

    print(f"\nAll studies complete.  Results in: {out_dir}")


if __name__ == "__main__":
    main()
