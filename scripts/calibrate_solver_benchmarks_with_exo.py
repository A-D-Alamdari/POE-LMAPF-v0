"""Stern .scen-driven sweep with exogenous agents placed as static obstacles.

Sibling of ``scripts/calibrate_solver_benchmarks.py`` (Stern bare).
The bare script measures solver completion on the canonical Stern
instances; this script adds exogenous agents — placed using the
*same* algorithm as ``Simulator._place_entities`` — and freezes them
as static obstacles for each one-shot solver invocation.

Why static obstacles?
---------------------
The Tier-1 solver in the simulator-driven sweep is invoked once per
replan window with a snapshot of the world; it has no human-prediction
model.  Freezing exogenous agents at t=0 in this benchmark sweep
mirrors what the Tier-1 solver sees at the replan instant.  Letting
them move during the planning horizon would give the benchmark sweep
information the simulator's solver does not have, contaminating the
"solver-only baseline" framing.

Per-cell methodology
--------------------
For each (solver, map, |M|, scenario_idx ∈ 1..25):

1. Read ``data/scenarios/<map>-even-<scenario_idx>.scen`` and take the
   first |M| records as starts/goals (same as the bare benchmark).
2. Place ``num_humans[map]`` exogenous cells using the simulator's
   placement algorithm
   (``Simulator._place_entities`` at simulator.py:660-694):
   * ``occupied = starts ∪ goals`` (we additionally exclude goals
     because the one-shot setting knows them at t=0; the lifelong
     simulator does not).
   * ``f_init = inflate_cells(starts, r_safe=1, env)`` — the
     Manhattan-1 buffer around every controlled-agent start.
   * Sample N exogenous cells from
     ``free_cells \ (occupied ∪ f_init)`` using
     ``np.random.default_rng(scenario_idx + 1000)``.  Distinct
     scenario index → distinct deterministic placement.
   * If the pool is exhausted, record a row with
     ``status="error"``,
     ``error_msg="exogenous_placement_pool_exhausted"`` and skip.
3. Build a new ``Environment`` whose ``blocked`` set is the union of
   the map's blocked cells and the exogenous-agent cells.  This makes
   the exogenous cells walls for the one-shot solver call without
   touching any wrapper or solver code.
4. Invoke ``solver.plan_with_metadata(env=env_with_exo, agents=...,
   assignments=..., step=0, horizon=20, is_lifelong=False)``.
5. Record one row, schema:

    solver, map, num_agents, num_humans, scenario_idx, exo_seed,
    status, solver_wall_ms, end_to_end_wall_ms,
    plan_makespan, plan_first_agent_distinct_cells,
    n_records_available, error_msg

Reproducibility
---------------
Exogenous placement uses ``np.random.default_rng(scenario_idx + 1000)``
so a re-run with the same (scenario_idx, map, |M|) produces the same
exogenous layout.  The +1000 offset isolates the placement RNG stream
from any future ``rng=scenario_idx`` use upstream.
"""
from __future__ import annotations

import argparse
import csv
import inspect
import json
import logging
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

logging.getLogger("ha_lmapf.global_tier.rolling_horizon").setLevel(logging.ERROR)

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.simulation.environment import Environment


DEFAULT_NUM_AGENTS_PER_MAP: Dict[str, List[int]] = {
    "random-64-64-10": [20, 40, 60, 80],
    "warehouse-10-20-10-2-1": [50, 100, 150, 200],
    "warehouse-10-20-10-2-2": [100, 200, 300, 450],
}

DEFAULT_NUM_HUMANS_PER_MAP: Dict[str, int] = {
    "random-64-64-10": 20,
    "warehouse-10-20-10-2-1": 40,
    "warehouse-10-20-10-2-2": 60,
}

# Per-cohort grids matching the paper §5.4 / §5.5 sweeps.  When --cohort is
# supplied, these defaults override DEFAULT_NUM_AGENTS_PER_MAP /
# DEFAULT_NUM_HUMANS_PER_MAP for that cohort.
COHORT_CONFIGS: Dict[str, Dict[str, Any]] = {
    "5_4": {
        # Mirrors configs/eval/paper/scaling_agents.yaml plus the existing
        # bare benchmark CSV's grid (12 cells).
        "num_agents_per_map": {
            "random-64-64-10": [20, 40, 60, 80],
            "warehouse-10-20-10-2-1": [50, 100, 150, 200],
            "warehouse-10-20-10-2-2": [100, 200, 300, 450],
        },
        "num_humans_per_map": {
            "random-64-64-10": 20,
            "warehouse-10-20-10-2-1": 40,
            "warehouse-10-20-10-2-2": 60,
        },
        "csv_name": "raw_measurements_benchmark_with_exo_5_4.csv",
    },
    "5_5": {
        # Mirrors configs/eval/paper/baseline_comparison.yaml (18 cells,
        # no warehouse-10-20-10-2-1).
        "num_agents_per_map": {
            "random-64-64-10": [10, 20, 30, 40, 50, 60, 70, 80, 90],
            "warehouse-10-20-10-2-2": [50, 100, 150, 200, 250, 300, 350,
                                       400, 450],
        },
        "num_humans_per_map": {
            "random-64-64-10": 20,
            "warehouse-10-20-10-2-2": 100,
        },
        "csv_name": "raw_measurements_benchmark_with_exo_5_5.csv",
    },
}

DEFAULT_SOLVERS = ["lacam_official", "lacam3", "lns2", "pibt2", "cbsh2", "pbs"]
DEFAULT_MAPS = list(DEFAULT_NUM_AGENTS_PER_MAP.keys())
DEFAULT_SCENARIO_IDS = list(range(1, 26))
DEFAULT_TIME_LIMIT = 10.0
DEFAULT_HORIZON = 20
DEFAULT_R_SAFE = 1  # matches paper SimConfig.safety_radius=1

CSV_FIELDS = [
    "solver", "map", "num_agents", "num_humans", "scenario_idx", "exo_seed",
    "cohort",
    "status", "solver_wall_ms", "end_to_end_wall_ms",
    "plan_makespan", "plan_first_agent_distinct_cells",
    "n_records_available", "error_msg",
]


def _map_path(map_stem: str) -> str:
    p = Path("data/maps") / f"{map_stem}.map"
    if not p.exists():
        raise FileNotFoundError(
            f"map not found: {p}.  Run scripts/download_maps.sh first."
        )
    return str(p)


def _scen_path(map_stem: str, scenario_idx: int) -> Path:
    return Path("data/scenarios") / f"{map_stem}-even-{scenario_idx}.scen"


def _read_scen_records(path: Path) -> List[Tuple[int, int, int, int]]:
    """Same parser as calibrate_solver_benchmarks.py."""
    records: List[Tuple[int, int, int, int]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("version"):
                continue
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                start_x = int(parts[4])
                start_y = int(parts[5])
                goal_x = int(parts[6])
                goal_y = int(parts[7])
            except ValueError:
                continue
            records.append((start_y, start_x, goal_y, goal_x))
    return records


def _build_instance(
    records: List[Tuple[int, int, int, int]], num_agents: int,
) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    agents: Dict[int, AgentState] = {}
    assignments: Dict[int, Task] = {}
    for aid, (sr, sc, gr, gc) in enumerate(records[:num_agents]):
        task_id = f"t{aid}"
        agents[aid] = AgentState(
            agent_id=aid, pos=(sr, sc), goal=(gr, gc), task_id=task_id,
        )
        assignments[aid] = Task(
            task_id=task_id, start=(sr, sc), goal=(gr, gc), release_step=0,
        )
    return agents, assignments


def _place_exogenous(
    env: Environment, starts: Set[Tuple[int, int]],
    goals: Set[Tuple[int, int]], num_humans: int, exo_seed: int,
    r_safe: int = DEFAULT_R_SAFE,
) -> Tuple[Set[Tuple[int, int]], Optional[str]]:
    """Mirror ``Simulator._place_entities`` for the one-shot setting.

    Returns ``(exo_cells, error_or_none)``.  ``error_or_none`` is None
    on success, or a short explanation on pool exhaustion.
    """
    f_init = inflate_cells(starts, radius=r_safe, env=env)
    forbidden = starts | goals | f_init
    rng = np.random.default_rng(exo_seed)
    exo_cells: Set[Tuple[int, int]] = set()
    occupied = set(forbidden)
    for _ in range(num_humans):
        try:
            cell = env.sample_free_cell(rng, exclude=occupied)
        except RuntimeError:
            return exo_cells, "exogenous_placement_pool_exhausted"
        exo_cells.add(cell)
        occupied.add(cell)
    return exo_cells, None


def _env_with_blocked(env: Environment,
                      extra_blocked: Set[Tuple[int, int]]) -> Environment:
    """Return a new ``Environment`` with the original blocked cells
    plus ``extra_blocked``.  The original env is left untouched.
    """
    return Environment(
        width=env.width, height=env.height,
        blocked=env.blocked | extra_blocked,
    )


def _plan_call(
    solver, env, agents, assignments, horizon: int,
) -> Dict[str, Any]:
    """Mirror calibrate_solver_benchmarks.py._plan_call."""
    plan_kwargs: Dict[str, Any] = {
        "env": env,
        "agents": agents,
        "assignments": assignments,
        "step": 0,
        "horizon": horizon,
        "rng": None,
    }
    sig = inspect.signature(solver.plan_with_metadata)
    if "is_lifelong" in sig.parameters:
        plan_kwargs["is_lifelong"] = False

    res = solver.plan_with_metadata(**plan_kwargs)

    first_distinct = 0
    plan_makespan = 0
    if res.plan and res.plan.paths:
        for tp in res.plan.paths.values():
            if tp is None:
                continue
            distinct = len(set(tp.cells))
            if distinct > first_distinct:
                first_distinct = distinct
            plan_makespan = max(plan_makespan, len(tp.cells))
    return {
        "status": res.status,
        "solver_wall_ms": res.solver_wall_ms,
        "end_to_end_wall_ms": res.end_to_end_wall_ms,
        "plan_makespan": plan_makespan,
        "plan_first_agent_distinct_cells": first_distinct,
        "error_msg": (res.error_msg or "")[:500],
    }


def _run_one(
    solver_name: str, map_stem: str, num_agents: int, num_humans: int,
    scenario_idx: int, time_limit_sec: float, horizon: int,
    r_safe: int = DEFAULT_R_SAFE, cohort: str = "",
) -> Dict[str, Any]:
    exo_seed = scenario_idx + 1000
    base_row = {
        "solver": solver_name, "map": map_stem,
        "num_agents": num_agents, "num_humans": num_humans,
        "scenario_idx": scenario_idx, "exo_seed": exo_seed,
        "cohort": cohort,
        "n_records_available": 0,
    }
    error_row = lambda msg: {
        **base_row,
        "status": "error",
        "solver_wall_ms": math.nan,
        "end_to_end_wall_ms": math.nan,
        "plan_makespan": 0,
        "plan_first_agent_distinct_cells": 0,
        "error_msg": msg[:500],
    }
    try:
        scen = _scen_path(map_stem, scenario_idx)
        records = _read_scen_records(scen)
        base_row["n_records_available"] = len(records)
        if len(records) < num_agents:
            return error_row(
                f"insufficient records: scen has {len(records)} but |M|={num_agents}",
            )

        env = Environment.load_from_map(_map_path(map_stem))
        agents, assignments = _build_instance(records, num_agents)
        starts = {a.pos for a in agents.values()}
        goals = {t.goal for t in assignments.values()}

        exo_cells, exo_err = _place_exogenous(
            env, starts, goals, num_humans, exo_seed, r_safe=r_safe,
        )
        if exo_err:
            return error_row(exo_err)

        env_with_exo = _env_with_blocked(env, exo_cells)
        solver = GlobalPlannerFactory.create(
            solver_name, time_limit_sec=time_limit_sec,
        )
        m = _plan_call(solver, env_with_exo, agents, assignments, horizon)
        return {**base_row, **m}
    except Exception as exc:  # noqa: BLE001
        return error_row(f"{type(exc).__name__}: {exc}")


def _run_one_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _run_one(**kwargs)


def _build_grid(
    solvers: List[str], maps: List[str],
    num_agents_per_map: Dict[str, List[int]],
    num_humans_per_map: Dict[str, int],
    scenario_ids: List[int],
) -> List[Dict[str, Any]]:
    grid: List[Dict[str, Any]] = []
    for solver_name in solvers:
        for map_stem in maps:
            n_humans = num_humans_per_map.get(map_stem, 0)
            for n in num_agents_per_map.get(map_stem, []):
                for sidx in scenario_ids:
                    grid.append({
                        "solver_name": solver_name, "map_stem": map_stem,
                        "num_agents": n, "num_humans": n_humans,
                        "scenario_idx": sidx,
                    })
    return grid


def _read_completed(out_csv: Path) -> Set[Tuple[str, str, int, int, int]]:
    if not out_csv.exists():
        return set()
    done: Set[Tuple[str, str, int, int, int]] = set()
    with out_csv.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                done.add((
                    r["solver"], r["map"],
                    int(r["num_agents"]), int(r["num_humans"]),
                    int(r["scenario_idx"]),
                ))
            except (KeyError, ValueError):
                continue
    return done


def _write_rows(out_path: Path, rows: List[Dict[str, Any]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists()
    if write_header:
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
        os.replace(tmp, out_path)
    else:
        with out_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=str, default="",
                        choices=["", "5_4", "5_5"],
                        help="When set, applies the cohort's per-map "
                             "num_agents and num_humans defaults from "
                             "COHORT_CONFIGS and writes to the cohort's "
                             "default CSV name.  Explicit "
                             "--num-agents-per-map / --num-humans-per-map / "
                             "--csv-name still override.")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory")
    parser.add_argument("--solvers", type=str, default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--maps", type=str, default="",
                        help="Comma-separated map stems; empty = use the "
                             "cohort default (or DEFAULT_MAPS when no cohort).")
    parser.add_argument("--num-agents-per-map", type=str, default="",
                        help="JSON dict; default = cohort grid (or §5.4 grid "
                             "when no cohort).")
    parser.add_argument("--num-humans-per-map", type=str, default="",
                        help="JSON dict; default = cohort grid.")
    parser.add_argument("--scenarios", type=str,
                        default=",".join(str(s) for s in DEFAULT_SCENARIO_IDS))
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--r-safe", type=int, default=DEFAULT_R_SAFE,
                        help="safety_radius mirroring SimConfig (default 1).")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true",
                        help="Skip (solver, map, |M|, |X|, scenario_idx) "
                             "tuples already present in the output CSV.")
    parser.add_argument("--csv-name", type=str, default="",
                        help="Output CSV filename inside --out.  Empty = "
                             "use cohort default, falling back to "
                             "raw_measurements_benchmark_with_exo.csv.")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("calibrate_bench_exo")

    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    scenario_ids = [int(s.strip()) for s in args.scenarios.split(",") if s.strip()]

    cohort_cfg = COHORT_CONFIGS.get(args.cohort, {}) if args.cohort else {}

    # maps: cohort default, then explicit, then DEFAULT_MAPS
    if args.maps:
        maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    elif cohort_cfg:
        maps = list(cohort_cfg["num_agents_per_map"].keys())
    else:
        maps = list(DEFAULT_MAPS)

    if args.num_agents_per_map:
        num_agents_per_map = json.loads(args.num_agents_per_map)
    elif cohort_cfg:
        num_agents_per_map = {m: cohort_cfg["num_agents_per_map"][m]
                              for m in maps
                              if m in cohort_cfg["num_agents_per_map"]}
    else:
        num_agents_per_map = {m: DEFAULT_NUM_AGENTS_PER_MAP[m]
                              for m in maps if m in DEFAULT_NUM_AGENTS_PER_MAP}

    if args.num_humans_per_map:
        num_humans_per_map = json.loads(args.num_humans_per_map)
    elif cohort_cfg:
        num_humans_per_map = {m: cohort_cfg["num_humans_per_map"][m]
                              for m in maps
                              if m in cohort_cfg["num_humans_per_map"]}
    else:
        num_humans_per_map = {m: DEFAULT_NUM_HUMANS_PER_MAP[m]
                              for m in maps if m in DEFAULT_NUM_HUMANS_PER_MAP}

    csv_name = (
        args.csv_name
        or (cohort_cfg.get("csv_name") if cohort_cfg else "")
        or "raw_measurements_benchmark_with_exo.csv"
    )

    grid = _build_grid(solvers, maps, num_agents_per_map,
                       num_humans_per_map, scenario_ids)
    if args.limit is not None:
        grid = grid[:args.limit]

    out_csv = args.out / csv_name

    if args.resume:
        done = _read_completed(out_csv)
        before = len(grid)
        grid = [
            g for g in grid
            if (g["solver_name"], g["map_stem"], g["num_agents"],
                g["num_humans"], g["scenario_idx"]) not in done
        ]
        log.info("--resume: %d/%d already done; %d remaining",
                 len(done), before, len(grid))
    else:
        if out_csv.exists():
            log.warning("removing existing %s", out_csv)
            out_csv.unlink()

    total = len(grid)
    log.info(
        "benchmark+exo grid: %d invocations across %d solvers × %d maps × "
        "varying |M| × %d scenarios; num_humans_per_map=%s; r_safe=%d",
        total, len(solvers), len(maps), len(scenario_ids),
        num_humans_per_map, args.r_safe,
    )
    if total == 0:
        log.info("nothing to do; exiting")
        return 0

    t0 = time.monotonic()
    completed = 0

    if args.workers <= 1:
        for kw in grid:
            row = _run_one_kwargs(dict(
                kw, time_limit_sec=args.time_limit, horizon=args.horizon,
                r_safe=args.r_safe, cohort=args.cohort,
            ))
            _write_rows(out_csv, [row])
            completed += 1
            if completed % 25 == 0 or completed == total:
                elapsed = time.monotonic() - t0
                log.info("progress: %d/%d (%.1f%%, elapsed %.1fs)",
                         completed, total,
                         100.0 * completed / total, elapsed)
    else:
        log.info("running with %d workers", args.workers)
        cell_kwargs = [
            dict(kw, time_limit_sec=args.time_limit, horizon=args.horizon,
                 r_safe=args.r_safe, cohort=args.cohort)
            for kw in grid
        ]
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_run_one_kwargs, ck): ck
                       for ck in cell_kwargs}
            for fut in as_completed(futures):
                try:
                    row = fut.result()
                    _write_rows(out_csv, [row])
                except Exception as exc:  # noqa: BLE001
                    log.error("invocation failed: %s — %s",
                              futures[fut], exc)
                    continue
                completed += 1
                if completed % 25 == 0 or completed == total:
                    elapsed = time.monotonic() - t0
                    log.info("progress: %d/%d (%.1f%%, elapsed %.1fs)",
                             completed, total,
                             100.0 * completed / total, elapsed)

    elapsed = time.monotonic() - t0
    log.info("benchmark+exo sweep done: %d/%d invocations, %.1fs wall",
             completed, total, elapsed)
    log.info("rows written to %s", out_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
