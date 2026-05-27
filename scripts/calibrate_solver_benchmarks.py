"""Stern et al. 2019 benchmark-driven solver timing measurements.

Sibling of ``scripts/calibrate_solver_budgets.py``.  The simulator-driven
calibration captures end-to-end behavior (allocator + solver + replan
gating); this script bypasses ``Simulator`` and ``assign_tasks``
entirely and feeds each solver wrapper Stern .scen records directly.

The gap between the two CSVs **is** the allocator-bounded fraction —
i.e. the share of simulator-driven failures attributable to allocator
artifacts (clustered goals, infeasible adjacency, etc.) rather than
solver shortcomings.  This measurement is needed to support the §5.4
reframing documented in ``docs/CALIBRATION_DIAGNOSIS.md``.

Per-cell methodology
--------------------
For each (solver, map, num_agents, scenario_idx ∈ 1..25):

1.  Read ``data/scenarios/<map>-even-<idx>.scen`` and take the first
    ``num_agents`` records.  Each record's (start, goal) is converted
    from MovingAI ``(x, y) = (col, row)`` to our ``(row, col)``.
2.  Construct ``AgentState`` (with ``goal=goal``, ``task_id``) and
    ``Task`` (release_step=0) dicts.
3.  Call ``solver.plan_with_metadata(env, agents, assignments, step=0,
    horizon=20, is_lifelong=False)`` — one-shot MAPF.
4.  Append one row to the output CSV.

Atomic CSV writes via ``write-tmp + os.replace``.  ``--resume`` reads
the existing CSV, computes the (solver, map, num_agents, scenario_idx)
set, and skips already-completed runs.
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

logging.getLogger("ha_lmapf.global_tier.rolling_horizon").setLevel(logging.ERROR)

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.simulation.environment import Environment


DEFAULT_NUM_AGENTS_PER_MAP: Dict[str, List[int]] = {
    "random-64-64-10": [20, 40, 60, 80],
    "warehouse-10-20-10-2-1": [50, 100, 150, 200],
    "warehouse-10-20-10-2-2": [100, 200, 300, 450],
}

DEFAULT_SOLVERS = ["lacam_official", "lacam3", "lns2", "pibt2", "cbsh2", "pbs"]
DEFAULT_MAPS = list(DEFAULT_NUM_AGENTS_PER_MAP.keys())
DEFAULT_SCENARIO_IDS = list(range(1, 26))
DEFAULT_TIME_LIMIT = 10.0
DEFAULT_HORIZON = 20

CSV_FIELDS = [
    "solver", "map", "num_agents", "scenario_idx",
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
    """Parse a MovingAI .scen file into (start_row, start_col, goal_row,
    goal_col) tuples.

    The .scen layout is documented in
    ``docs/STERN_BENCHMARK_COMPATIBILITY.md`` §2.  Per-line fields::

        bucket  map_filename  width  height
        start_x  start_y  goal_x  goal_y  opt_length

    where (x, y) = (col, row).  We swap to (row, col) to match our
    AgentState convention.  Lines starting with ``version`` or empty
    are skipped.
    """
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


def _plan_call(
    solver, env, agents, assignments, horizon: int,
) -> Dict[str, Any]:
    """Invoke ``plan_with_metadata`` with ``is_lifelong=False`` when the
    wrapper supports it; fall back gracefully otherwise.
    """
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
    solver_name: str, map_stem: str, num_agents: int, scenario_idx: int,
    time_limit_sec: float, horizon: int,
) -> Dict[str, Any]:
    """Single (solver, map, |M|, scenario_idx) measurement."""
    base_row = {
        "solver": solver_name, "map": map_stem,
        "num_agents": num_agents, "scenario_idx": scenario_idx,
        "n_records_available": 0,
    }
    try:
        scen = _scen_path(map_stem, scenario_idx)
        records = _read_scen_records(scen)
        base_row["n_records_available"] = len(records)
        if len(records) < num_agents:
            return {
                **base_row,
                "status": "error",
                "solver_wall_ms": math.nan,
                "end_to_end_wall_ms": math.nan,
                "plan_makespan": 0,
                "plan_first_agent_distinct_cells": 0,
                "error_msg": (
                    f"insufficient records: scen has {len(records)} "
                    f"but |M|={num_agents}"
                ),
            }

        env = Environment.load_from_map(_map_path(map_stem))
        solver = GlobalPlannerFactory.create(
            solver_name, time_limit_sec=time_limit_sec,
        )
        agents, assignments = _build_instance(records, num_agents)
        m = _plan_call(solver, env, agents, assignments, horizon)
        return {**base_row, **m}
    except Exception as exc:  # noqa: BLE001
        return {
            **base_row,
            "status": "error",
            "solver_wall_ms": math.nan,
            "end_to_end_wall_ms": math.nan,
            "plan_makespan": 0,
            "plan_first_agent_distinct_cells": 0,
            "error_msg": f"{type(exc).__name__}: {exc}"[:500],
        }


def _run_one_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _run_one(**kwargs)


def _build_grid(
    solvers: List[str], maps: List[str],
    num_agents_per_map: Dict[str, List[int]],
    scenario_ids: List[int],
) -> List[Dict[str, Any]]:
    grid: List[Dict[str, Any]] = []
    for solver_name in solvers:
        for map_stem in maps:
            for n in num_agents_per_map.get(map_stem, []):
                for sidx in scenario_ids:
                    grid.append({
                        "solver_name": solver_name, "map_stem": map_stem,
                        "num_agents": n, "scenario_idx": sidx,
                    })
    return grid


def _read_completed(out_csv: Path) -> Set[Tuple[str, str, int, int]]:
    if not out_csv.exists():
        return set()
    done: Set[Tuple[str, str, int, int]] = set()
    with out_csv.open() as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                done.add((
                    r["solver"], r["map"],
                    int(r["num_agents"]), int(r["scenario_idx"]),
                ))
            except (KeyError, ValueError):
                continue
    return done


def _write_rows(out_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Atomic-on-create / append-on-extend.  Mirrors
    ``calibrate_solver_budgets.py``: header write goes via .tmp +
    os.replace, subsequent appends use buffered append (acceptable
    because each append is a single short flush; in the worst case a
    crash mid-append truncates a single row, which --resume detects).
    """
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
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory (raw_measurements_benchmark.csv lands here)")
    parser.add_argument("--solvers", type=str,
                        default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--maps", type=str, default=",".join(DEFAULT_MAPS))
    parser.add_argument("--num-agents-per-map", type=str, default="",
                        help="JSON dict; keys=map stem, values=list of ints. "
                             "Empty = use builtin default grid.")
    parser.add_argument("--scenarios", type=str,
                        default=",".join(str(s) for s in DEFAULT_SCENARIO_IDS))
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true",
                        help="Skip (solver, map, |M|, scenario_idx) tuples "
                             "already present in the output CSV.")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total rows (debugging only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("calibrate_bench")

    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    scenario_ids = [int(s.strip()) for s in args.scenarios.split(",") if s.strip()]

    if args.num_agents_per_map:
        num_agents_per_map = json.loads(args.num_agents_per_map)
    else:
        num_agents_per_map = {m: DEFAULT_NUM_AGENTS_PER_MAP[m]
                              for m in maps if m in DEFAULT_NUM_AGENTS_PER_MAP}

    grid = _build_grid(solvers, maps, num_agents_per_map, scenario_ids)
    if args.limit is not None:
        grid = grid[:args.limit]

    out_csv = args.out / "raw_measurements_benchmark.csv"

    if args.resume:
        done = _read_completed(out_csv)
        before = len(grid)
        grid = [
            g for g in grid
            if (g["solver_name"], g["map_stem"], g["num_agents"],
                g["scenario_idx"]) not in done
        ]
        log.info("--resume: %d/%d already done; %d remaining",
                 len(done), before, len(grid))
    else:
        if out_csv.exists():
            log.warning("removing existing %s", out_csv)
            out_csv.unlink()

    total = len(grid)
    log.info(
        "benchmark grid: %d invocations across %d solvers × %d maps × "
        "varying |M| × %d scenarios (time_limit=%.1fs each)",
        total, len(solvers), len(maps), len(scenario_ids), args.time_limit,
    )
    if total == 0:
        log.info("nothing to do; exiting")
        return 0

    t0 = time.monotonic()
    completed = 0

    if args.workers <= 1:
        for kw in grid:
            row = _run_one_kwargs(dict(kw, time_limit_sec=args.time_limit,
                                       horizon=args.horizon))
            _write_rows(out_csv, [row])
            completed += 1
            if completed % 25 == 0 or completed == total:
                elapsed = time.monotonic() - t0
                log.info(
                    "progress: %d/%d (%.1f%%, elapsed %.1fs)",
                    completed, total, 100.0 * completed / total, elapsed,
                )
    else:
        log.info("running with %d workers", args.workers)
        cell_kwargs = [
            dict(kw, time_limit_sec=args.time_limit, horizon=args.horizon)
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
                    log.info(
                        "progress: %d/%d (%.1f%%, elapsed %.1fs)",
                        completed, total, 100.0 * completed / total, elapsed,
                    )

    elapsed = time.monotonic() - t0
    log.info("benchmark sweep done: %d/%d invocations, %.1fs wall",
             completed, total, elapsed)
    log.info("rows written to %s", out_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
