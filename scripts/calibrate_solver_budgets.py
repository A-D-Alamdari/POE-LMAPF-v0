"""Empirical timing calibration for the six paper-sweep MAPF solvers.

Produces ``logs/calibration/raw_measurements.csv`` with one row per
``plan_with_metadata`` invocation across the (solver × map ×
num_agents × seed × replan_idx) grid.  Downstream
``analyze_calibration.py`` consumes the CSV to produce three
recommendation reports.

This script does NOT change any wrapper, parser, or contract.  It is a
data-collection harness.  Wrapper bugs surfaced by the calibration
should be fixed in their own prompts; the calibration will be
re-run after.

Per-cell methodology
--------------------
For each (solver, map, num_agents, seed, replan_idx):

1.  Construct a fresh ``SimConfig`` + ``Simulator`` with the chosen
    solver and a 10 s ``solver_timeout_s`` (deliberately generous to
    capture the full timing distribution, not just under-budget runs).
2.  Advance the simulator ``replan_idx + 1`` ticks so we measure
    the solver at a non-trivial step (avoids the all-step-0 bias).
3.  Call ``planner.plan_with_metadata(...)`` directly via the
    rolling-horizon planner's ``solver`` attribute, with the current
    agent-state snapshot.
4.  Append one row to the output CSV.

Atomic writes use ``write-tmp + os.replace``.  Per-call timeout is
1.5× the configured ``time_limit_sec`` so a single cell cannot block
the entire sweep.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import os
import sys
import tempfile
import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Suppress noisy warnings from the simulator's `[rolling-horizon]` logger;
# we collect status from SolverResult directly.
logging.getLogger("ha_lmapf.global_tier.rolling_horizon").setLevel(logging.ERROR)

from ha_lmapf.core.types import SimConfig
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.simulation.simulator import Simulator


# Paper §5.4 cohort: covers the densities used in scaling sweeps.
DEFAULT_NUM_AGENTS_PER_MAP: Dict[str, List[int]] = {
    "random-64-64-10": [20, 40, 60, 80],
    "warehouse-10-20-10-2-1": [50, 100, 150, 200],
    "warehouse-10-20-10-2-2": [100, 200, 300, 450],
}

DEFAULT_SOLVERS = ["lacam_official", "lacam3", "lns2", "pibt2", "cbsh2", "pbs"]
DEFAULT_MAPS = list(DEFAULT_NUM_AGENTS_PER_MAP.keys())
DEFAULT_SEEDS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
DEFAULT_REPLANS_PER_CELL = 3
DEFAULT_TIME_LIMIT = 10.0
DEFAULT_NUM_HUMANS = 50  # legacy 50-uniform default; v1 raw_measurements.csv uses this

# Per-map num_humans matching configs/eval/paper/scaling_agents.yaml.
# Used when --num-humans-per-map is supplied without an explicit JSON.
SCALING_AGENTS_NUM_HUMANS: Dict[str, int] = {
    "random-64-64-10": 20,
    "warehouse-10-20-10-2-1": 40,
    "warehouse-10-20-10-2-2": 60,
}

CSV_FIELDS = [
    "solver", "map", "num_agents", "num_humans", "seed", "replan_idx",
    "status", "solver_wall_ms", "end_to_end_wall_ms",
    "plan_makespan", "plan_first_agent_distinct_cells",
    "error_msg", "source_config",
]


def _map_path(map_stem: str) -> str:
    p = Path("data/maps") / f"{map_stem}.map"
    if not p.exists():
        raise FileNotFoundError(
            f"map not found: {p}.  Run scripts/download_maps.sh first."
        )
    return str(p)


def _build_sim(
    solver_name: str, map_stem: str, num_agents: int, num_humans: int,
    seed: int, time_limit_sec: float, steps: int = 1,
) -> Simulator:
    cfg = SimConfig(
        map_path=_map_path(map_stem),
        seed=seed,
        steps=steps,
        num_agents=num_agents,
        num_humans=num_humans,
        fov_radius=4,
        safety_radius=1,
        global_solver=solver_name,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
        solver_timeout_s=time_limit_sec,
    )
    return Simulator(cfg)


def _measure_one_replan(sim: Simulator) -> Dict[str, Any]:
    """Invoke ``plan_with_metadata`` on the simulator's current state.

    The rolling-horizon planner's ``solver`` is the wrapper; we pull
    the current snapshot directly to avoid the simulator's gating
    logic (we want one measurement per call regardless of trigger
    state).
    """
    planner = sim.global_planner
    solver = planner.solver
    assignments = sim.assign_tasks()
    # Mirror RollingHorizonPlanner.step's invocation
    plan_kwargs = {
        "env": sim.env,
        "agents": sim.agents,
        "assignments": assignments,
        "step": sim.step,
        "horizon": planner.horizon,
        "rng": None,
    }
    # Probe is_lifelong support
    import inspect
    sig_source = (
        solver.plan_with_metadata
        if hasattr(solver, "plan_with_metadata")
        else solver.plan
    )
    if "is_lifelong" in inspect.signature(sig_source).parameters:
        plan_kwargs["is_lifelong"] = True

    res = solver.plan_with_metadata(**plan_kwargs)
    # Compute first-agent-distinct-cell count (a proxy for "did the
    # plan actually move someone?")
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


def _run_cell(
    solver_name: str, map_stem: str, num_agents: int, num_humans: int,
    seed: int, replans_per_cell: int, time_limit_sec: float,
    source_config: str = "",
    skip_replans: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Run ``replans_per_cell`` measurements for one (solver, map, |M|, seed)
    cell.  Each subsequent replan advances the simulator by one tick to
    capture solver behavior at non-trivial steps.

    ``skip_replans`` lists replan indices whose rows already exist in the
    output CSV (set by --resume); those indices are not re-run.

    Returns a list of measurement rows.  On simulator-construction
    failure, returns a single error row per replan_idx.
    """
    rows: List[Dict[str, Any]] = []
    skip = set(skip_replans or [])
    # Build a fresh simulator per replan_idx so we can drive it forward
    # via ``sim.run()`` to step ``replan_idx + 1`` (the simulator's task
    # stream releases tasks during run; calling ``assign_tasks`` directly
    # at step 0 yields zero assignments because the stream hasn't ticked).
    for replan_idx in range(replans_per_cell):
        if replan_idx in skip:
            continue
        try:
            sim = _build_sim(
                solver_name, map_stem, num_agents, num_humans, seed,
                time_limit_sec, steps=replan_idx + 1,
            )
            sim.run()  # drive the simulator forward; tasks get released
            measurement = _measure_one_replan(sim)
        except Exception as exc:  # noqa: BLE001
            measurement = {
                "status": "error",
                "solver_wall_ms": math.nan,
                "end_to_end_wall_ms": math.nan,
                "plan_makespan": 0,
                "plan_first_agent_distinct_cells": 0,
                "error_msg": f"{type(exc).__name__}: {exc}"[:500],
            }
        rows.append({
            "solver": solver_name, "map": map_stem,
            "num_agents": num_agents, "num_humans": num_humans,
            "seed": seed, "replan_idx": replan_idx,
            **measurement,
            "source_config": source_config,
        })

    return rows


def _run_cell_kwargs(kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Top-level wrapper for ProcessPoolExecutor.  ``kwargs`` is
    pickleable (only Python primitives)."""
    return _run_cell(**kwargs)


def _build_grid(
    solvers: List[str], maps: List[str],
    num_agents_per_map: Dict[str, List[int]],
    seeds: List[int], replans_per_cell: int,
) -> List[Dict[str, Any]]:
    """Cartesian grid of (solver, map, |M|, seed) cells."""
    grid = []
    for solver_name in solvers:
        for map_stem in maps:
            n_list = num_agents_per_map.get(map_stem, [])
            for n in n_list:
                for seed in seeds:
                    grid.append({
                        "solver": solver_name, "map": map_stem,
                        "num_agents": n, "seed": seed,
                    })
    return grid


def _write_rows(out_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Atomic append: write to a sibling .tmp and rename."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not out_path.exists()
    # Use a sibling tmp file for atomic rename of new content
    if write_header:
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
        os.replace(tmp, out_path)
    else:
        # Append: read-modify-write to keep atomicity simple
        with out_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory (raw_measurements.csv lands here)")
    parser.add_argument("--solvers", type=str,
                        default=",".join(DEFAULT_SOLVERS))
    parser.add_argument("--maps", type=str, default=",".join(DEFAULT_MAPS))
    parser.add_argument("--num-agents-per-map", type=str, default="",
                        help="JSON dict; keys=map stem, values=list of ints. "
                             "Empty = use builtin default grid.")
    parser.add_argument("--num-humans", type=int, default=DEFAULT_NUM_HUMANS,
                        help="Uniform exogenous-agent count (legacy 50-uniform "
                             "matches v1 raw_measurements.csv). Ignored when "
                             "--num-humans-per-map is provided.")
    parser.add_argument("--num-humans-per-map", type=str, default="",
                        help="JSON dict {map_stem: int} matching paper §5.4 "
                             "scaling_agents.yaml (random=20, warehouse-2-1=40, "
                             "warehouse-2-2=60). When set, overrides --num-humans.")
    parser.add_argument("--csv-name", type=str, default="raw_measurements.csv",
                        help="Output CSV filename inside --out (default keeps "
                             "v1 raw_measurements.csv; use raw_measurements_v2.csv "
                             "for the per-map-num_humans run).")
    parser.add_argument("--source-config", type=str, default="",
                        help="String written to source_config column "
                             "(e.g. 'scaling_agents_v2').")
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT)
    parser.add_argument("--seeds", type=str,
                        default=",".join(str(s) for s in DEFAULT_SEEDS))
    parser.add_argument("--replans-per-cell", type=int,
                        default=DEFAULT_REPLANS_PER_CELL)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true",
                        help="Skip (solver, map, num_agents, seed, replan_idx) "
                             "tuples already present in the output CSV.  "
                             "When unset, an existing CSV is unlinked.")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap total cells (debugging only)")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("calibrate")

    solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    maps = [m.strip() for m in args.maps.split(",") if m.strip()]
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    if args.num_agents_per_map:
        num_agents_per_map = json.loads(args.num_agents_per_map)
    else:
        num_agents_per_map = {m: DEFAULT_NUM_AGENTS_PER_MAP[m]
                              for m in maps if m in DEFAULT_NUM_AGENTS_PER_MAP}

    if args.num_humans_per_map:
        num_humans_per_map: Dict[str, int] = json.loads(args.num_humans_per_map)
    else:
        num_humans_per_map = {}

    grid = _build_grid(solvers, maps, num_agents_per_map, seeds,
                       args.replans_per_cell)
    if args.limit is not None:
        grid = grid[:args.limit]
    total_cells = len(grid)
    total_calls = total_cells * args.replans_per_cell
    log.info(
        "calibration grid: %d cells × %d replans/cell = %d invocations "
        "(time_limit=%.1fs each)",
        total_cells, args.replans_per_cell, total_calls, args.time_limit,
    )
    if num_humans_per_map:
        log.info("num_humans per map: %s", num_humans_per_map)

    out_csv = args.out / args.csv_name

    # --resume: read existing rows to build skip-set; otherwise, unlink.
    done_replans_by_cell: Dict[Tuple[str, str, int, int], List[int]] = {}
    if out_csv.exists():
        if args.resume:
            with out_csv.open() as f:
                reader = csv.DictReader(f)
                for r in reader:
                    try:
                        key = (r["solver"], r["map"], int(r["num_agents"]),
                               int(r["seed"]))
                        done_replans_by_cell.setdefault(
                            key, []).append(int(r["replan_idx"]))
                    except (KeyError, ValueError):
                        continue
            n_done = sum(len(v) for v in done_replans_by_cell.values())
            log.info("--resume: %d existing rows across %d cells in %s",
                     n_done, len(done_replans_by_cell), out_csv)
        else:
            log.warning("removing existing %s (use --resume to keep)",
                        out_csv)
            out_csv.unlink()

    # Filter the grid: drop cells whose replans are all done.
    if done_replans_by_cell:
        before = len(grid)
        kept: List[Dict[str, Any]] = []
        for cell in grid:
            key = (cell["solver"], cell["map"],
                   cell["num_agents"], cell["seed"])
            already = set(done_replans_by_cell.get(key, []))
            if len(already) >= args.replans_per_cell:
                continue  # fully done
            kept.append(dict(cell, _skip_replans=sorted(already)))
        grid = kept
        log.info("--resume: %d/%d cells already complete; %d remaining",
                 before - len(grid), before, len(grid))
        total_cells = len(grid)
        total_calls = total_cells * args.replans_per_cell  # upper bound

    t0 = time.monotonic()
    completed = 0
    failed_cells = 0

    def _humans_for(map_stem: str) -> int:
        return int(num_humans_per_map.get(map_stem, args.num_humans))

    if args.workers <= 1:
        for cell in grid:
            try:
                rows = _run_cell(
                    cell["solver"], cell["map"], cell["num_agents"],
                    _humans_for(cell["map"]), cell["seed"],
                    args.replans_per_cell, args.time_limit,
                    source_config=args.source_config,
                    skip_replans=cell.get("_skip_replans"),
                )
                _write_rows(out_csv, rows)
            except Exception as exc:  # noqa: BLE001
                log.error("cell failed: %s — %s", cell, exc)
                failed_cells += 1
                continue
            completed += 1
            if completed % 5 == 0 or completed == total_cells:
                elapsed = time.monotonic() - t0
                log.info(
                    "progress: %d/%d cells (%.1f%%, elapsed %.1fs)",
                    completed, total_cells, 100.0 * completed / total_cells,
                    elapsed,
                )
    else:
        # Parallel execution via ProcessPoolExecutor.  Use a top-level
        # picklable function (`_run_cell_kwargs`) since closures defined
        # inside main can't be pickled.
        from concurrent.futures import ProcessPoolExecutor, as_completed
        log.info("running with %d workers", args.workers)

        cell_kwargs = [{
            "solver_name": c["solver"],
            "map_stem": c["map"],
            "num_agents": c["num_agents"],
            "num_humans": _humans_for(c["map"]),
            "seed": c["seed"],
            "replans_per_cell": args.replans_per_cell,
            "time_limit_sec": args.time_limit,
            "source_config": args.source_config,
            "skip_replans": c.get("_skip_replans"),
        } for c in grid]

        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_run_cell_kwargs, ck): grid[i]
                       for i, ck in enumerate(cell_kwargs)}
            for fut in as_completed(futures):
                cell = futures[fut]
                try:
                    rows = fut.result()
                    _write_rows(out_csv, rows)
                except Exception as exc:  # noqa: BLE001
                    log.error("cell failed: %s — %s", cell, exc)
                    failed_cells += 1
                    continue
                completed += 1
                if completed % 5 == 0 or completed == total_cells:
                    elapsed = time.monotonic() - t0
                    log.info(
                        "progress: %d/%d cells (%.1f%%, elapsed %.1fs)",
                        completed, total_cells,
                        100.0 * completed / total_cells, elapsed,
                    )

    elapsed = time.monotonic() - t0
    log.info(
        "calibration done: %d/%d cells succeeded (%d failed), %.1fs wall",
        completed, total_cells, failed_cells, elapsed,
    )
    log.info("rows written to %s", out_csv)
    return 0 if failed_cells == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
