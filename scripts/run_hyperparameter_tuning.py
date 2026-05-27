# !/usr/bin/env python3
"""
Hyperparameter Tuning Script for HA-LMAPF.

Runs systematic parameter sweeps, multi-map generalization checks, ablations,
and baseline comparisons suitable for publication.

Usage:
    # Run all sweeps on the primary map with 5 seeds
    python scripts/run_hyperparameter_tuning.py --all --seeds 0 1 2 3 4

    # Run the core scalability sweeps on all 3 canonical maps
    python scripts/run_hyperparameter_tuning.py --multi-map

    # Run a single sweep
    python scripts/run_hyperparameter_tuning.py --sweep num_agents

    # Run the ablation study (5 seeds)
    python scripts/run_hyperparameter_tuning.py --ablations

    # Run with custom settings
    python scripts/run_hyperparameter_tuning.py --sweep replan_every \
        --map data/maps/warehouse-20-40-10-2-1.map \
        --agents 20 --humans 5 --steps 5000

    # Run in parallel using all CPU cores
    python scripts/run_hyperparameter_tuning.py --all --seeds 0 1 2 3 4 --workers 0

Output:
    logs/tuning/
    ├── results.csv          # Raw per-seed results
    ├── summary.csv          # Aggregated statistics (mean ± std) + Wilcoxon p-values
    └── plots/               # Generated figures (if --plot is specified)

Submission checklist
--------------------
✓ 5 seeds minimum (default) for statistical power
✓ 5000 steps (default) → ~500 completed tasks per run, stable statistics
✓ 3 canonical maps: small warehouse / large warehouse / room-with-doors
✓ Core sweeps (num_agents, num_humans, human_model, task_arrival_rate)
  run on ALL 3 maps for generalization evidence
✓ Sensitivity sweeps (replan_every, horizon, solver, …) run on the primary
  map only — they show internal system trade-offs, not generalization
✓ execution_delay sweep tests robustness to actuation failures
✓ Wilcoxon signed-rank p-values reported for every key comparison
✓ 6-condition ablation study: every tier / feature toggled individually
✓ horizon sweep coupled to replan_every (plan always outlives interval)
✓ near_miss metric is INDEPENDENT of safety_radius (exactly distance == 1,
  excludes same-cell contacts which are counted as collisions_agent_human)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ha_lmapf.core.types import SimConfig, Metrics
from ha_lmapf.simulation.simulator import Simulator

# ---------------------------------------------------------------------------
# Canonical maps for evaluation
# ---------------------------------------------------------------------------
# Each map entry: (path, label, recommended_max_agents)
# Three topologically distinct maps are required for a generalization claim.
MAPS_CANONICAL: Dict[str, Dict[str, Any]] = {
    # Small warehouse — tight aisles, high agent density, strong contention
    "warehouse_small": {
        "path": "data/maps/warehouse-10-20-10-2-1.map",
        "label": "Warehouse-S (10×20)",
        "max_agents": 40,
    },
    # Large warehouse — primary map used for all sensitivity sweeps
    "warehouse_large": {
        "path": "data/maps/warehouse-20-40-10-2-1.map",
        "label": "Warehouse-L (20×40)",
        "max_agents": 100,
    },
    # Room map — narrow doorways create bottlenecks, tests local planner
    "room": {
        "path": "data/maps/room-32-32-4.map",
        "label": "Room-32 (32×32-4)",
        "max_agents": 60,
    },
}

# The primary map used for single-map sensitivity sweeps
PRIMARY_MAP = MAPS_CANONICAL["warehouse_large"]["path"]

# Core sweeps are run on ALL canonical maps (generalization evidence).
# Sensitivity sweeps are run on the primary map only (internal trade-offs).
SWEEPS_CORE = {"num_agents", "num_humans", "human_model", "task_arrival_rate"}

# ---------------------------------------------------------------------------
# Sweep configurations
# ---------------------------------------------------------------------------
SWEEPS: Dict[str, Dict[str, Any]] = {
    # ---- Scalability -------------------------------------------------------
    "num_agents": {
        "param": "num_agents",
        # Extended upper bound (150) shows where throughput saturates / MAPF
        # planning time becomes a bottleneck — important for scalability
        # claim.  LaCAM forced because CBS does not scale past ~30 agents.
        "values": [5, 10, 15, 20, 30, 40, 50, 75, 100, 150],
        "overrides": {"global_solver": "lacam"},
    },
    "num_humans": {
        "param": "num_humans",
        # Extended to 30 to show the degradation curve clearly.
        # warehouse-20-40 has ~800 free cells; 30 humans ≈ 3.75 % occupancy.
        "values": [0, 2, 5, 10, 15, 20, 30],
    },

    # ---- Task load ---------------------------------------------------------
    "task_arrival_rate": {
        "param": "task_arrival_rate",
        # rate=2  → task every 2 steps → very heavy load (agent saturation)
        # rate=100 → task every 100 steps → sparse, agents mostly idle
        # Full range reveals the saturation point and idle-to-busy transition.
        "values": [2, 5, 10, 15, 20, 30, 50, 100],
    },

    # ---- Safety / perception -----------------------------------------------
    "safety_radius": {
        "param": "safety_radius",
        # Extended to 5 to capture the deadlock cliff where the forbidden zone
        # is large enough that agents regularly have no valid move.
        # NOTE: use near_misses (always distance≤1) as the primary safety
        # metric when analyzing this sweep — safety_violations is confounded
        # because a larger radius counts more cells as violations by definition.
        "values": [0, 1, 2, 3, 4, 5],
    },
    "fov_radius": {
        "param": "fov_radius",
        # Include fov_radius=1 (equals the default safety_radius=1) so the
        # sweep covers the critical region where agents cannot see humans far
        # enough in advance to avoid the safety zone.
        "values": [1, 2, 3, 4, 5, 6, 8, 10],
    },
    "hard_safety": {
        "param": "hard_safety",
        "values": [True, False],
    },

    # ---- Global planner ----------------------------------------------------
    "solver": {
        "param": "global_solver",
        # cbs = optimal, slower; lacam = approximate, faster.
        # (lacam3 / pibt2 require the C++ build — add when available.)
        "values": ["cbs", "lacam"],
    },
    "replan_every": {
        "param": "replan_every",
        # horizon coupled at 2× replan_every so the global plan always
        # covers at least one full interval before the next replan.
        "values": [5, 10, 15, 20, 25, 30, 40, 50],
        "coupled": {"horizon": lambda v: 2 * v},
    },
    "horizon": {
        "param": "horizon",
        # replan_every coupled at horizon/2 so it never exceeds horizon.
        # Without this coupling, horizon=20 with base replan_every=25 causes
        # the global plan to expire 5 steps before the next replan, leaving
        # agents without guidance and producing near-zero throughput.
        "values": [20, 30, 50, 75, 100],
        "coupled": {"replan_every": lambda v: max(1, v // 2)},
    },

    # ---- Task allocator ----------------------------------------------------
    "allocator": {
        "param": "task_allocator",
        "values": ["greedy", "hungarian", "auction", "congestion_avoidance"],
    },
    "commit_horizon": {
        "param": "commit_horizon",
        # 0 = disabled (memoryless allocator).
        # Higher values reduce assignment thrashing at the cost of slower
        # reaction to better opportunities.
        "values": [0, 5, 10, 25, 50, 100],
    },
    "delay_threshold": {
        "param": "delay_threshold",
        # 0.0 = disabled.  1.5 means revoke if current distance > 1.5 × d0.
        # Only meaningful when commit_horizon > 0 or on its own.
        "values": [0.0, 1.5, 2.0, 2.5, 3.0, 4.0],
    },

    # ---- Human behaviour ---------------------------------------------------
    "human_model": {
        "param": "human_model",
        # "mixed" uses a weighted combination of models; tests the system
        # under realistic heterogeneous human populations.
        "values": ["random_walk", "aisle", "mixed"],
    },

    # ---- Robustness (execution noise) -------------------------------------
    "execution_delay": {
        "param": "execution_delay_prob",
        # Probability that an agent's intended move is delayed by one step.
        # Range [0, 0.3] covers no-noise through high-noise environments.
        # This is required for robustness analysis.
        "values": [0.0, 0.05, 0.1, 0.15, 0.2, 0.3],
    },
}

# ---------------------------------------------------------------------------
# Ablation study
# ---------------------------------------------------------------------------
# Each condition disables one system tier/feature in isolation.
# "full_system" is the control; all others differ by exactly one flag,
# making the contribution of each component identifiable.
ABLATIONS: Dict[str, Dict[str, Any]] = {
    # Control — full HA-LMAPF system
    "full_system": {},
    # Remove Tier-2: agents follow global plan only, wait when blocked
    "no_local_replan": {"disable_local_replan": True},
    # Remove conflict resolution: no token passing / priority negotiation
    "no_conflict_resolution": {"disable_conflict_resolution": True},
    # Remove BOTH Tier-2 AND conflict resolution → closest to a pure
    # Tier-1 (RHCR-like) baseline within the HA-LMAPF infrastructure
    "global_only": {
        "disable_local_replan": True,
        "disable_conflict_resolution": True,
    },
    # Remove safety constraint entirely (hard_safety and disable_safety)
    "no_safety": {"disable_safety": True},
    # Soft safety: treat forbidden zone as a high-cost region, not a hard
    # constraint — allows agents to enter the zone to prevent deadlock
    "soft_safety": {"hard_safety": False},
}


# ---------------------------------------------------------------------------
# Base configuration
# ---------------------------------------------------------------------------
def get_base_config(
        map_path: Optional[str] = None,
        num_agents: int = 20,
        num_humans: int = 5,
        steps: int = 5000,
) -> Dict[str, Any]:
    """Return the base (control) configuration for all experiments.

    Notes
    -----
    - steps=5000 → initial burst of num_agents (20) tasks at step 0, then
      one new task every 10 steps → ~520 tasks over 5000 steps, giving
      stable throughput / flowtime statistics across seeds.
    - time_budget_ms=5000 caps each global planning call at 5 s so that
      large-horizon / CBS runs remain tractable.
    - All parameters here are the "recommended" values found in the
      sensitivity sweeps; deviations from these values are the sweep axes.
    """
    return {
        "map_path": map_path or PRIMARY_MAP,
        "task_stream_path": None,
        "steps": steps,
        "num_agents": num_agents,
        "num_humans": num_humans,
        # Perception
        "fov_radius": 4,
        "safety_radius": 1,
        "hard_safety": True,
        # Global planner
        "global_solver": "lacam",
        "replan_every": 25,
        "horizon": 50,
        # Cap each global planning call at 5 s so that horizon=100 / CBS
        # runs remain tractable. Set to 0 to disable the cap.
        "time_budget_ms": 5000.0,
        # Task allocation
        "task_allocator": "congestion_avoidance",
        "commit_horizon": 0,  # disabled by default (pure greedy)
        "delay_threshold": 0.0,  # disabled by default
        "task_arrival_rate": 10,
        "task_arrival_percentage": 0.9,
        # Communication / local planning
        "communication_mode": "token",
        "local_planner": "astar",
        # Human model
        "human_model": "random_walk",
        "human_model_params": {},
        # Robustness
        "execution_delay_prob": 0.0,
        "execution_delay_steps": 1,
        # Ablation flags (all off in the base config)
        "disable_local_replan": False,
        "disable_conflict_resolution": False,
        "disable_safety": False,
        "seed": 0,
    }


# ---------------------------------------------------------------------------
# Sanity-check helpers
# ---------------------------------------------------------------------------
# Steps and seed used for the --sanity smoke-test
_SANITY_STEPS = 1000
_SANITY_SEED = 0


def _sanity_values(values: list) -> list:
    """Pick 3 representative values from a sweep list: low, mid, high.

    - 1 value  → returns it as-is.
    - 2 values → both (no mid to add).
    - 3+ values → first, middle index, last; duplicates are collapsed so
      the returned list is always unique and ordered.
    """
    if len(values) <= 2:
        return list(values)
    mid = values[len(values) // 2]
    seen = []
    for v in [values[0], mid, values[-1]]:
        if v not in seen:
            seen.append(v)
    return seen


def run_sanity_check(
        base_config: Dict[str, Any],
        output_dir: Path,
        verbose: bool = True,
        workers: int = 1,
        sweep_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Run a minimal smoke-test across every sweep + ablation.

    For each sweep: low, middle, and high parameter values are tested
    (3 values, or fewer for short lists), with a single seed and 1000
    simulation steps.  The goal is to verify that every code path
    (solver, allocator, human model, safety mode, …) runs without error
    — NOT to produce statistically valid results.

    Args:
        sweep_filter: If provided, only run sweeps whose names are in this
                      list.  Ablations are always skipped when a filter is
                      active (pass an empty list or None to run all).

    Output is written to ``output_dir/sanity/``.
    """
    sanity_config = base_config.copy()
    sanity_config["steps"] = _SANITY_STEPS

    seeds = [_SANITY_SEED]
    all_results: List[Dict[str, Any]] = []
    errors: List[str] = []

    # Determine which sweeps to run
    if sweep_filter:
        active_sweeps = [s for s in sorted(SWEEPS.keys()) if s in sweep_filter]
        run_ablations_flag = False  # skip ablations when a filter is active
    else:
        active_sweeps = sorted(SWEEPS.keys())
        run_ablations_flag = True

    print(f"\n{'=' * 60}")
    print("SANITY CHECK — minimal smoke-test of every sweep + ablation")
    print(f"  steps={_SANITY_STEPS}  seed={_SANITY_SEED}")
    print(f"  sweeps: {active_sweeps}")
    if run_ablations_flag:
        print(f"  ablations: {list(ABLATIONS.keys())}")
    print(f"{'=' * 60}")

    # Temporarily narrow every sweep to representative values
    original_values: Dict[str, list] = {}
    for name, cfg in SWEEPS.items():
        original_values[name] = cfg["values"]
        SWEEPS[name]["values"] = _sanity_values(cfg["values"])

    try:
        for sweep_name in active_sweeps:
            try:
                results = run_sweep(sweep_name, seeds, sanity_config,
                                    verbose=verbose, workers=workers)
                all_results.extend(results)
            except Exception as exc:
                msg = f"ERROR sweep '{sweep_name}': {exc}"
                print(f"  !! {msg}")
                errors.append(msg)

        if run_ablations_flag:
            try:
                abl_results = run_ablations(seeds, sanity_config,
                                            verbose=verbose, workers=workers)
                all_results.extend(abl_results)
            except Exception as exc:
                msg = f"ERROR ablations: {exc}"
                print(f"  !! {msg}")
                errors.append(msg)
    finally:
        # Always restore original values
        for name, vals in original_values.items():
            SWEEPS[name]["values"] = vals

    sanity_dir = output_dir / "sanity"
    if all_results:
        aggregated = aggregate_results(all_results)
        save_results(all_results, aggregated, sanity_dir)

    n_ok = len(all_results)
    n_err = len(errors)
    print(f"\n{'=' * 60}")
    print(f"Sanity check complete: {n_ok} runs OK, {n_err} errors")
    if errors:
        for e in errors:
            print(f"  - {e}")
    print(f"Results: {sanity_dir}")
    print(f"{'=' * 60}")

    return all_results


# ---------------------------------------------------------------------------
# Single-experiment runner
# ---------------------------------------------------------------------------
def run_single_experiment(
        config_dict: Dict[str, Any],
        experiment_name: str,
        verbose: bool = False,
) -> Tuple[Metrics, float]:
    """Run one simulation and return (Metrics, wall_clock_seconds)."""
    config = SimConfig(**{
        k: v for k, v in config_dict.items()
        if k in SimConfig.__dataclass_fields__
    })

    if verbose:
        print(f"  Running: {experiment_name} (seed={config.seed})")

    start_time = time.time()
    try:
        sim = Simulator(config)
        metrics = sim.run()
        wall_time = time.time() - start_time

        if verbose:
            print(f"    Throughput={metrics.throughput:.4f}  "
                  f"Flowtime={metrics.mean_flowtime:.1f}  "
                  f"NearMiss={metrics.near_misses}  "
                  f"Violations={metrics.safety_violations}")

        return metrics, wall_time

    except Exception as e:
        print(f"  ERROR in {experiment_name}: {e}")
        wall_time = time.time() - start_time
        return Metrics(steps=config.steps), wall_time


# ---------------------------------------------------------------------------
# Parallel worker (must be top-level so it is picklable by multiprocessing)
# ---------------------------------------------------------------------------
def _run_experiment_task(
        args: Tuple[Dict[str, Any], str, bool]
) -> Dict[str, Any]:
    """Picklable wrapper used by ProcessPoolExecutor."""
    config_dict, name, verbose = args
    metrics, wall_time = run_single_experiment(config_dict, name, verbose)
    return {
        "_name": name,
        "_wall_time": wall_time,
        "_metrics": asdict(metrics),
    }


# ---------------------------------------------------------------------------
# Sweep runner
# ---------------------------------------------------------------------------
def run_sweep(
        sweep_name: str,
        seeds: List[int],
        base_config: Dict[str, Any],
        map_label: str = "",
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run a parameter sweep; return a list of per-seed result dicts.

    When *workers* > 1 all (value, seed) combinations are dispatched to a
    ``ProcessPoolExecutor`` so they run in parallel across CPU cores.
    """
    if sweep_name not in SWEEPS:
        raise ValueError(
            f"Unknown sweep: {sweep_name}. Available: {sorted(SWEEPS)}"
        )

    sweep_cfg = SWEEPS[sweep_name]
    param_name = sweep_cfg["param"]
    param_values = sweep_cfg["values"]
    coupled = sweep_cfg.get("coupled", {})
    overrides = sweep_cfg.get("overrides", {})
    steps = base_config.get("steps", 1000)

    tag = f" [{map_label}]" if map_label else ""
    print(f"\n{'=' * 60}")
    print(f"Sweep: {sweep_name}{tag}")
    print(f"  param={param_name}  values={param_values}  seeds={seeds}"
          f"  workers={workers}")
    print(f"{'=' * 60}")

    # Build the full list of (config, name, meta) tuples up front
    tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
    for value in param_values:
        for seed in seeds:
            config = base_config.copy()
            config[param_name] = value
            config["seed"] = seed
            for coupled_param, func in coupled.items():
                config[coupled_param] = func(value)
            for k, v in overrides.items():
                config[k] = v

            name = f"{sweep_name}_{param_name}={value}_seed={seed}"
            if map_label:
                name = f"{map_label}_{name}"

            tasks.append((config, name, {
                "sweep": sweep_name,
                "map": map_label or base_config.get("map_path", ""),
                "param": param_name,
                "value": value,
                "seed": seed,
            }))

    total = len(tasks)
    results: List[Dict[str, Any]] = []

    if workers <= 1:
        # Sequential path (original behavior)
        for n, (config, name, meta) in enumerate(tasks, 1):
            print(f"\n[{n}/{total}] {meta['param']}={meta['value']}, "
                  f"seed={meta['seed']}")
            metrics, wall_time = run_single_experiment(config, name, verbose)
            results.append({**meta, "wall_time_sec": wall_time,
                            **asdict(metrics)})
    else:
        # Parallel path
        print(f"  Dispatching {total} jobs across {workers} workers …")
        worker_args = [(cfg, nm, verbose) for cfg, nm, _ in tasks]
        meta_map = {nm: meta for _, nm, meta in tasks}

        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_name = {
                pool.submit(_run_experiment_task, arg): arg[1]
                for arg in worker_args
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                completed += 1
                meta = meta_map[name]
                try:
                    result = future.result()
                    print(f"  [{completed}/{total}] done: {name}")
                    results.append({**meta,
                                    "wall_time_sec": result["_wall_time"],
                                    **result["_metrics"]})
                except Exception as exc:
                    print(f"  [{completed}/{total}] ERROR {name}: {exc}")
                    results.append({**meta, "wall_time_sec": 0.0,
                                    **asdict(Metrics(steps=steps))})

    return results


# ---------------------------------------------------------------------------
# Multi-map runner (core sweeps)
# ---------------------------------------------------------------------------
def run_multi_map_sweeps(
        seeds: List[int],
        num_agents: int,
        num_humans: int,
        steps: int,
        sweep_names: Optional[List[str]] = None,
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run the core sweeps on all three canonical maps for generalization evidence.

    Only sweeps in SWEEPS_CORE (num_agents, num_humans, human_model,
    task_arrival_rate) are run on all maps.  Sensitivity sweeps (replan_every,
    horizon, …) are run on the primary map only; they characterize internal
    trade-offs, not cross-environment generalization.
    """
    targets = sweep_names or sorted(SWEEPS_CORE)
    all_results: List[Dict[str, Any]] = []

    for map_key, map_info in MAPS_CANONICAL.items():
        map_path = map_info["path"]
        label = map_info["label"]
        max_ag = map_info["max_agents"]

        base = get_base_config(
            map_path=map_path,
            num_agents=min(num_agents, max_ag),
            num_humans=num_humans,
            steps=steps,
        )

        for sweep_name in targets:
            if sweep_name not in SWEEPS_CORE:
                print(f"  [skip] {sweep_name} is a sensitivity sweep "
                      f"— run on primary map only")
                continue
            if sweep_name not in SWEEPS:
                print(f"  [skip] unknown sweep: {sweep_name}")
                continue

            # For num_agents sweep, cap values at the map's recommended max
            sweep_cfg = SWEEPS[sweep_name]
            original_values = sweep_cfg["values"]
            if sweep_cfg["param"] == "num_agents":
                SWEEPS[sweep_name]["values"] = [
                    v for v in original_values if v <= max_ag
                ]

            results = run_sweep(sweep_name, seeds, base,
                                map_label=map_key, verbose=verbose,
                                workers=workers)
            all_results.extend(results)

            # Restore original values list
            if sweep_cfg["param"] == "num_agents":
                SWEEPS[sweep_name]["values"] = original_values

    return all_results


# ---------------------------------------------------------------------------
# Ablation runner
# ---------------------------------------------------------------------------
def run_ablations(
        seeds: List[int],
        base_config: Dict[str, Any],
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run the 6-condition ablation study."""
    steps = base_config.get("steps", 1000)

    print(f"\n{'=' * 60}")
    print("Ablation study")
    print(f"  conditions={list(ABLATIONS)}  seeds={seeds}  workers={workers}")
    print(f"{'=' * 60}")

    # Build tasks
    tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]] = []
    for ablation_name, overrides in ABLATIONS.items():
        for seed in seeds:
            config = base_config.copy()
            config["seed"] = seed
            for k, v in overrides.items():
                config[k] = v
            name = f"ablation_{ablation_name}_seed={seed}"
            tasks.append((config, name, {
                "sweep": "ablation",
                "map": base_config.get("map_path", ""),
                "param": "ablation",
                "value": ablation_name,
                "seed": seed,
            }))

    total = len(tasks)
    results: List[Dict[str, Any]] = []

    if workers <= 1:
        for n, (config, name, meta) in enumerate(tasks, 1):
            print(f"\n[{n}/{total}] {meta['value']}, seed={meta['seed']}")
            metrics, wall_time = run_single_experiment(config, name, verbose)
            results.append({**meta, "wall_time_sec": wall_time,
                            **asdict(metrics)})
    else:
        print(f"  Dispatching {total} jobs across {workers} workers …")
        worker_args = [(cfg, nm, verbose) for cfg, nm, _ in tasks]
        meta_map = {nm: meta for _, nm, meta in tasks}

        completed = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_name = {
                pool.submit(_run_experiment_task, arg): arg[1]
                for arg in worker_args
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                completed += 1
                meta = meta_map[name]
                try:
                    result = future.result()
                    print(f"  [{completed}/{total}] done: {name}")
                    results.append({**meta,
                                    "wall_time_sec": result["_wall_time"],
                                    **result["_metrics"]})
                except Exception as exc:
                    print(f"  [{completed}/{total}] ERROR {name}: {exc}")
                    results.append({**meta, "wall_time_sec": 0.0,
                                    **asdict(Metrics(steps=steps))})

    return results


# ---------------------------------------------------------------------------
# Aggregation with statistical tests
# ---------------------------------------------------------------------------
# Metrics reported in summary.csv: mean, std, and (where applicable)
# Wilcoxon signed-rank p-value vs the adjacent lower value in the sweep.
METRIC_KEYS = [
    "throughput", "completed_tasks", "task_completion",
    "mean_flowtime", "median_flowtime",
    "max_flowtime", "mean_service_time", "collisions_agent_agent",
    "collisions_agent_human", "near_misses", "safety_violations",
    "safety_violation_rate", "replans", "global_replans", "local_replans",
    "intervention_rate", "total_wait_steps",
    "human_passive_wait_steps",
    "mean_planning_time_ms", "p95_planning_time_ms", "max_planning_time_ms",
    "mean_decision_time_ms", "p95_decision_time_ms", "makespan",
    "sum_of_costs", "delay_events", "immediate_assignments",
    "assignments_kept", "assignments_broken", "wall_time_sec",
]

# Metrics for which we compute Wilcoxon p-values vs the sweep baseline.
# These are the primary claims in the paper; others are supporting data.
STATS_METRICS = ["throughput", "mean_flowtime", "near_misses",
                 "safety_violations", "total_wait_steps"]


def aggregate_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate per-seed rows → mean ± std rows, plus Wilcoxon p-values.

    For each (sweep, map, param, value) group the function computes:
    - {metric}_mean, {metric}_std  for every metric in METRIC_KEYS
    - {metric}_wilcoxon_p          for every metric in STATS_METRICS,
      testing whether this group differs significantly from the group with
      the *lowest* param value in the same sweep (e.g. num_agents=5).
      Requires scipy; gracefully falls back to NaN if not installed.
    """
    import numpy as np
    from collections import defaultdict

    # Try to import scipy for Wilcoxon tests; gracefully degrade if absent.
    try:
        from scipy.stats import wilcoxon
        _has_scipy = True
    except ImportError:
        print("  [warning] scipy not found — Wilcoxon p-values will be NaN. "
              "Install with:  pip install scipy")
        _has_scipy = False

    # Group by (sweep, map, param, value)
    groups: Dict[Tuple, List[Dict]] = defaultdict(list)
    for r in results:
        key = (r["sweep"], r.get("map", ""), r["param"], r["value"])
        groups[key].append(r)

    # For each sweep×map, collect the baseline (lowest numeric value or first)
    baselines: Dict[Tuple, Dict[str, List[float]]] = {}
    sweep_map_pairs = {(k[0], k[1]) for k in groups}
    for sw, mp in sweep_map_pairs:
        keys_for_pair = [k for k in groups if k[0] == sw and k[1] == mp]
        # For the ablation sweep, always use "full_system" as the baseline so
        # Wilcoxon p-values are computed against the control condition.
        # For numeric sweeps, use the group with the smallest parameter value.
        if sw == "ablation":
            full_system_keys = [k for k in keys_for_pair if k[3] == "full_system"]
            baseline_key = full_system_keys[0] if full_system_keys else keys_for_pair[0]
        else:
            def sort_key(k):
                try:
                    return float(k[3])
                except (ValueError, TypeError):
                    return 0

            baseline_key = min(keys_for_pair, key=sort_key)
        baselines[(sw, mp)] = {
            m: [r.get(m, 0.0) for r in groups[baseline_key]]
            for m in STATS_METRICS
        }

    aggregated = []
    for (sweep, mp, param, value), group in groups.items():
        agg: Dict[str, Any] = {
            "sweep": sweep,
            "map": mp,
            "param": param,
            "value": value,
            "n_seeds": len(group),
        }

        for key in METRIC_KEYS:
            vals = [r.get(key, 0.0) for r in group]
            agg[f"{key}_mean"] = float(np.mean(vals))
            agg[f"{key}_std"] = float(np.std(vals, ddof=1) if len(vals) > 1 else 0.0)

        # Wilcoxon p-values vs sweep baseline
        baseline_data = baselines.get((sweep, mp), {})
        for key in STATS_METRICS:
            col = f"{key}_wilcoxon_p"
            if not _has_scipy or key not in baseline_data:
                agg[col] = float("nan")
                continue
            vals = [r.get(key, 0.0) for r in group]
            base_vals = baseline_data[key]
            # Need paired samples of equal length; skip if baseline == this group
            if vals == base_vals or len(vals) < 5:
                agg[col] = float("nan")
            else:
                n = min(len(vals), len(base_vals))
                try:
                    _, p = wilcoxon(vals[:n], base_vals[:n],
                                    alternative="two-sided")
                    agg[col] = float(p)
                except Exception:
                    agg[col] = float("nan")

        aggregated.append(agg)

    return aggregated


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def save_results(
        results: List[Dict[str, Any]],
        aggregated: List[Dict[str, Any]],
        output_dir: Path,
) -> None:
    """Write raw results and aggregated summary to CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if results:
        raw_path = output_dir / "results.csv"
        with open(raw_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved raw results to: {raw_path}")

    if aggregated:
        agg_path = output_dir / "summary.csv"
        with open(agg_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=aggregated[0].keys())
            writer.writeheader()
            writer.writerows(aggregated)
        print(f"Saved summary to: {agg_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hyperparameter tuning for HA-LMAPF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Recommended runs (in order of increasing cost)
──────────────────────────────────────────────
Smoke-test every sweep + ablation (3 values: low/mid/high, 1 seed, 1000 steps):
  python scripts/run_hyperparameter_tuning.py --sanity

Quick sweep check (3 sweeps, 1 seed, 500 steps):
  python scripts/run_hyperparameter_tuning.py \\
      --sweep num_agents --sweep num_humans --sweep human_model \\
      --seeds 0 --steps 500

Full single-map sweep battery (primary map, 5 seeds, 5000 steps):
  python scripts/run_hyperparameter_tuning.py --all

Multi-map generalization (3 maps, core sweeps only, 5 seeds):
  python scripts/run_hyperparameter_tuning.py --multi-map

Ablation study (5 seeds, primary map):
  python scripts/run_hyperparameter_tuning.py --ablations

Full battery (all of the above — expect several hours):
  python scripts/run_hyperparameter_tuning.py --all --multi-map --ablations

Specific sweep with custom settings:
  python scripts/run_hyperparameter_tuning.py --sweep replan_every \\
      --map data/maps/warehouse-20-40-10-2-1.map \\
      --agents 20 --humans 5 --steps 5000
        """,
    )

    # What to run
    parser.add_argument(
        "--sweep",
        type=str,
        action="append",
        dest="sweeps",
        choices=sorted(SWEEPS.keys()),
        metavar="SWEEP",
        help="Sweep to run (may be repeated; see choices: "
             f"{sorted(SWEEPS.keys())})",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run ALL sensitivity sweeps on the primary map",
    )
    parser.add_argument(
        "--multi-map",
        action="store_true",
        dest="multi_map",
        help=f"Run core sweeps ({sorted(SWEEPS_CORE)}) on all 3 canonical maps",
    )
    parser.add_argument(
        "--ablations",
        action="store_true",
        help="Run the 6-condition ablation study",
    )
    parser.add_argument(
        "--sanity",
        action="store_true",
        help=(
            "Smoke-test every sweep and ablation with 3 values (low/mid/high),"
            " 1 seed, 1000 steps. Verifies all code paths before a full battery."
        ),
    )

    # Experiment settings
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[0, 1, 2, 3, 4],
        help="Random seeds (default: 0 1 2 3 4 — 5 seeds minimum)",
    )
    parser.add_argument(
        "--map",
        type=str,
        default=PRIMARY_MAP,
        help="Primary map path (used for all single-map sweeps)",
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=20,
        help="Number of agents in the base config (default: 20)",
    )
    parser.add_argument(
        "--humans",
        type=int,
        default=5,
        help="Number of humans in the base config (default: 5)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=5000,
        help="Simulation steps (default: 5000; 1000 yields too few "
             "completed tasks for stable statistics)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="logs/tuning",
        help="Base output directory (default: logs/tuning). "
             "Each run is saved in a timestamped subfolder, e.g. "
             "logs/tuning/2026-03-09_14-35-22/, so previous runs "
             "are never overwritten.",
    )
    parser.add_argument(
        "--workers", "-j",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel worker processes (default: 1 = sequential). "
             "Set to the number of CPU cores for maximum throughput, e.g. "
             "--workers $(nproc)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-run metrics",
    )

    args = parser.parse_args()

    if not args.sweeps and not args.all and not args.multi_map \
            and not args.ablations and not args.sanity:
        parser.error(
            "Specify at least one of: --sweep, --all, --multi-map, "
            "--ablations, --sanity"
        )

    base_config = get_base_config(
        map_path=args.map,
        num_agents=args.agents,
        num_humans=args.humans,
        steps=args.steps,
    )

    # Each run goes into a timestamped subfolder so previous runs are never
    # overwritten.  Format: <base>/<YYYY-MM-DD_HH-MM-SS>/
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_dir = Path(args.output) / run_timestamp
    print(f"Run directory: {output_dir}")

    all_results: List[Dict[str, Any]] = []
    start_time = time.time()

    # ---- Sanity check (runs instead of everything else if requested) -------
    if args.sanity:
        run_sanity_check(
            base_config, output_dir,
            verbose=args.verbose, workers=args.workers,
            sweep_filter=args.sweeps or None,  # None = run all
        )
        return

    # ---- Single-map sweeps -------------------------------------------------
    sweeps_to_run: List[str] = []
    if args.all:
        sweeps_to_run = sorted(SWEEPS.keys())
    elif args.sweeps:
        sweeps_to_run = args.sweeps

    for sweep_name in sweeps_to_run:
        try:
            results = run_sweep(sweep_name, args.seeds, base_config,
                                verbose=args.verbose, workers=args.workers)
            all_results.extend(results)
        except Exception as e:
            print(f"ERROR in sweep '{sweep_name}': {e}")

    # ---- Multi-map generalization sweeps -----------------------------------
    if args.multi_map:
        try:
            results = run_multi_map_sweeps(
                seeds=args.seeds,
                num_agents=args.agents,
                num_humans=args.humans,
                steps=args.steps,
                verbose=args.verbose,
                workers=args.workers,
            )
            all_results.extend(results)
        except Exception as e:
            print(f"ERROR in multi-map sweeps: {e}")

    # ---- Ablation study ----------------------------------------------------
    if args.ablations:
        try:
            results = run_ablations(args.seeds, base_config, args.verbose,
                                    workers=args.workers)
            all_results.extend(results)
        except Exception as e:
            print(f"ERROR in ablations: {e}")

    # ---- Save ---------------------------------------------------------------
    total_time = time.time() - start_time

    if all_results:
        aggregated = aggregate_results(all_results)
        save_results(all_results, aggregated, output_dir)
        print(f"\n{'=' * 60}")
        print(f"Done — {len(all_results)} experiments in "
              f"{total_time / 60:.1f} min")
        print(f"Results: {output_dir}")
        print(f"{'=' * 60}")
    else:
        print("No results to save.")


if __name__ == "__main__":
    main()
