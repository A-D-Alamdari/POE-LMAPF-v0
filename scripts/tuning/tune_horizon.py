# !/usr/bin/env python3
"""Step 1 — Tune the global planning *horizon*.

The horizon controls how far ahead the global planner looks.
A longer horizon yields higher-quality paths but increases planning time
exponentially; a shorter horizon is fast but leaves agents with
insufficient lookahead to avoid bottlenecks.

Key insight:  horizon must outlast at least one replan_every interval,
so we couple replan_every = max(1, horizon // 2) here.  The joint sweep
in Step 3 refines both parameters together.

Settings match compare_global_study_agents.py:
  - 3 maps (random, warehouse_small, warehouse_large)
  - Small maps: agents=[25,50,75,100], humans=50
  - Large maps: agents=[100,200,300,400], humans=200
  - 15 seeds, 2000 steps, fov=5, safety_radius=1, budget=5s

Primary metric:   throughput (tasks/step)
Secondary:        mean_flowtime, mean_planning_time_ms, sum_of_costs
Safety metrics:   near_misses, safety_violations

Statistical output:
  - Wilcoxon signed-rank (paired) vs baseline (smallest horizon)
  - BH-corrected FDR q-values
  - Rank-biserial r effect sizes
  - 95% bootstrap confidence intervals

Sweep values: [10, 20, 30, 40, 50, 60, 75, 100]

Incremental durability
----------------------
Each completed run is appended to ``<out>/results.csv`` immediately
(no end-of-sweep buffer), and a ``<out>/.heartbeat`` file is rewritten
atomically every completion with the current progress.  An interrupted
sweep can be resumed via ``--resume --output-dir <out>``; rows already
in ``results.csv`` are skipped via the
``(solver, map_tag, num_agents, horizon, seed)`` identifier tuple.

Usage:
    # Default: lacam solver, all maps, all agent counts
    python scripts/tuning/tune_horizon.py --workers 0

    # Quick sanity check
    python scripts/tuning/tune_horizon.py --sanity --workers 0

    # Per-solver comparison (paper-ready):
    python scripts/tuning/tune_horizon.py --solver lacam lacam3 lns2 --workers 0
    python scripts/tuning/tune_horizon.py --solver all --workers 0

    # Specific maps only
    python scripts/tuning/tune_horizon.py --maps random warehouse_small --workers 0

    # Resume an interrupted sweep (re-uses existing results.csv)
    python scripts/tuning/tune_horizon.py --resume \
        --output-dir logs/tuning/horizon/2026-05-11_14-10-06 \
        --workers 0 --no-latex

    # Monitor progress during a run
    cat logs/tuning/horizon/<dir>/.heartbeat
    watch -n 10 'wc -l logs/tuning/horizon/<dir>/results.csv'
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ha_lmapf.core.types import Metrics

from scripts.tuning.tuning_utils import (
    METRIC_KEYS, STATS_METRICS,
    aggregate_results, compute_pareto_front,
    compute_sensitivity, find_best, make_output_dir,
    print_best, print_statistical_summary, resolve_workers,
    run_single_experiment, save_results, _run_task,
)

SWEEP_VALUES = [10, 20, 30, 40, 50, 60, 75, 100]

# ---------------------------------------------------------------------------
# Map definitions — matching compare_global_study_agents.py
# ---------------------------------------------------------------------------
MAP_DEFS: Dict[str, Dict[str, Any]] = {
    "random": {
        "map_path": "data/maps/random-64-64-10.map",
        "agent_counts": [25, 50, 75, 100],
        "num_humans": 50,
        "size": "small",
    },
    "warehouse_small": {
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "agent_counts": [25, 50, 75, 100],
        "num_humans": 50,
        "size": "small",
    },
    "warehouse_large": {
        "map_path": "data/maps/warehouse-20-40-10-2-2.map",
        "agent_counts": [100, 200, 300, 400],
        "num_humans": 200,
        "size": "large",
    },
}

ALL_MAP_TAGS = list(MAP_DEFS.keys())

# All solvers supported by the framework (label -> SimConfig solver name).
ALL_SOLVERS: Dict[str, str] = {
    "lacam": "lacam",
    "lacam3": "lacam3",
    "pibt2": "pibt2",
    "lns2": "lns2",
    "pbs": "pbs",
    "cbsh2-rtc": "cbsh2",
}

# replan_every is coupled: plan always covers at least one full interval.
_COUPLED_REPLAN = lambda v: max(1, v // 2)


# ---------------------------------------------------------------------------
# Base config — matching compare_global_study_agents.py
# ---------------------------------------------------------------------------
def _make_base_config(
        map_path: str,
        num_agents: int,
        num_humans: int,
        steps: int,
        global_solver: str,
        budget_s: float = 10.0,
) -> Dict[str, Any]:
    """Build a base config matching compare_global_study_agents.py settings.

    ``budget_s`` sets both ``solver_timeout_s`` (the primary, new field)
    and the legacy ``time_budget_ms`` to the same value, so the per-call
    Tier-1 budget is explicit and identical regardless of which field
    the simulator reads.  Default 10.0 s matches paper §5.1.
    """
    budget_ms = float(budget_s) * 1000.0
    return {
        "map_path": map_path,
        "task_stream_path": None,
        "steps": steps,
        "num_agents": num_agents,
        "num_humans": num_humans,
        "fov_radius": 5,
        "safety_radius": 1,
        "hard_safety": True,
        "global_solver": global_solver,
        "horizon": 50,  # will be overridden by sweep
        "replan_every": 25,  # will be overridden by coupled
        "task_allocator": "congestion_avoidance",
        "commit_horizon": 0,
        "delay_threshold": 0.0,
        "task_mode": "immediate",
        "task_arrival_rate": None,
        "task_arrival_percentage": 0.9,
        "communication_mode": "token",
        "local_planner": "astar",
        "human_model": "random_walk",
        "human_model_params": {},
        "execution_delay_prob": 0.0,
        "execution_delay_steps": 1,
        "time_budget_ms": budget_ms,
        "solver_timeout_s": float(budget_s),
        "disable_local_replan": False,
        "disable_conflict_resolution": False,
        "disable_safety": False,
        "seed": 0,
    }


# ---------------------------------------------------------------------------
# Build all experiment tasks
# ---------------------------------------------------------------------------
def _build_tasks(
        solvers: Dict[str, str],
        map_tags: List[str],
        horizon_values: List[int],
        seeds: List[int],
        steps: int,
        budget_s: float = 10.0,
) -> List[Tuple[Dict[str, Any], str, Dict[str, Any]]]:
    """Build (config, name, meta) tuples for every combination."""
    tasks = []
    for solver_label, solver_name in solvers.items():
        for map_tag in map_tags:
            mdef = MAP_DEFS[map_tag]
            for n_agents in mdef["agent_counts"]:
                for horizon in horizon_values:
                    replan = _COUPLED_REPLAN(horizon)
                    for seed in seeds:
                        cfg = _make_base_config(
                            map_path=mdef["map_path"],
                            num_agents=n_agents,
                            num_humans=mdef["num_humans"],
                            steps=steps,
                            global_solver=solver_name,
                            budget_s=budget_s,
                        )
                        cfg["horizon"] = horizon
                        cfg["replan_every"] = replan
                        cfg["seed"] = seed

                        name = (f"{solver_label}__{map_tag}_a{n_agents}"
                                f"_h{horizon}_s{seed}")
                        meta = {
                            "param": "horizon",
                            "value": horizon,
                            "seed": seed,
                            "solver": solver_label,
                            "map_tag": map_tag,
                            "map_path": mdef["map_path"],
                            "num_agents": n_agents,
                            "num_humans": mdef["num_humans"],
                            "replan_every": replan,
                        }
                        tasks.append((cfg, name, meta))
    return tasks


# ---------------------------------------------------------------------------
# Row identifier — single source of truth for the resume skip-set.
#
# Any row dict (whether built from meta+metrics in-memory, or read back
# from results.csv via csv.DictReader) maps to the same 5-tuple via this
# helper.  Used by both the resume scan and the per-task dispatcher; a
# divergence would either re-run completed cells or skip incomplete ones.
# ---------------------------------------------------------------------------
def _row_key(d: Dict[str, Any]) -> Tuple[str, str, int, int, int]:
    """Stable identifier for one (solver, map_tag, num_agents, horizon, seed) cell.

    Reads from either ``value`` (the param-name in the meta dict) or
    ``horizon`` (legacy alias), accepting strings from csv.DictReader
    or ints from in-memory meta.  Returns ``None`` on missing fields
    so callers can ignore malformed rows.
    """
    horizon_raw = d.get("value", d.get("horizon"))
    return (
        str(d["solver"]),
        str(d["map_tag"]),
        int(d["num_agents"]),
        int(horizon_raw),
        int(d["seed"]),
    )


def _read_completed_rows(results_path: Path) -> List[Dict[str, Any]]:
    """Read all rows from an existing ``results.csv`` (returns ``[]`` if
    the file is absent or empty).  Used by ``--resume`` to recover the
    rows the prior process flushed before it was interrupted.
    """
    if not results_path.exists() or results_path.stat().st_size == 0:
        return []
    with results_path.open(newline="") as f:
        return list(csv.DictReader(f))


def _completed_keys(rows: List[Dict[str, Any]]) -> Set[Tuple[str, str, int, int, int]]:
    """Skip-set of row-keys present in an existing results.csv."""
    out: Set[Tuple[str, str, int, int, int]] = set()
    for row in rows:
        try:
            out.add(_row_key(row))
        except (KeyError, ValueError, TypeError):
            # Tolerate malformed rows (partial flush from a crash); they
            # will be re-run rather than mistakenly skipped.
            continue
    return out


def _open_results_writer(
    out_path: Path, sample_row: Dict[str, Any],
) -> Tuple[Any, Any, List[str]]:
    """Open ``results.csv`` for incremental append.  Writes a header iff
    the file is new/empty.  ``sample_row`` provides the fieldname order
    for new files; on resume the existing header is preserved (we keep
    the existing column order via DictReader's fieldnames).

    Returns ``(file_handle, csv.DictWriter, fieldnames)``.  Caller owns
    the file handle and is responsible for closing it.
    """
    write_header = (not out_path.exists()) or out_path.stat().st_size == 0
    if not write_header:
        with out_path.open(newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames or sample_row.keys())
    else:
        fieldnames = list(sample_row.keys())
    f = out_path.open("a", newline="")
    writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if write_header:
        writer.writeheader()
        f.flush()
        os.fsync(f.fileno())
    return f, writer, fieldnames


def _write_heartbeat(hb_path: Path, done: int, total: int,
                     last_label: str = "") -> None:
    """Atomic heartbeat: write to ``.heartbeat.tmp`` then rename.  The
    user's monitor can ``cat`` the file safely at any moment.
    """
    pct = (100.0 * done / total) if total else 0.0
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {done}/{total} rows ({pct:.1f}%)"
    if last_label:
        line += f" — last: {last_label}"
    line += "\n"
    tmp = hb_path.with_suffix(hb_path.suffix + ".tmp")
    tmp.write_text(line)
    tmp.replace(hb_path)


# ---------------------------------------------------------------------------
# Execute all tasks with parallel workers
# ---------------------------------------------------------------------------
def _execute_tasks(
        tasks: List[Tuple[Dict[str, Any], str, Dict[str, Any]]],
        workers: int,
        verbose: bool,
        out: Optional[Path] = None,
        already_done: int = 0,
        original_total: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Run all experiments and return result rows.

    When ``out`` is provided, each completed row is appended to
    ``out/results.csv`` immediately and ``out/.heartbeat`` is rewritten
    atomically per completion.  ``already_done`` and ``original_total``
    let ``--resume`` report progress relative to the *full* sweep,
    not just the remaining slice.
    """
    total = len(tasks)
    grand_total = original_total if original_total is not None else total
    results: List[Dict[str, Any]] = []

    # Incremental-flush writer (lazy-open on first row so we know the
    # full fieldname set including the metrics dict's keys).
    csv_handle = None
    csv_writer = None
    results_path = out / "results.csv" if out is not None else None
    heartbeat_path = out / ".heartbeat" if out is not None else None

    def _persist(row: Dict[str, Any], label: str) -> None:
        nonlocal csv_handle, csv_writer
        results.append(row)
        if results_path is not None:
            if csv_writer is None:
                csv_handle, csv_writer, _ = _open_results_writer(results_path, row)
            csv_writer.writerow(row)
            csv_handle.flush()
            os.fsync(csv_handle.fileno())
        if heartbeat_path is not None:
            _write_heartbeat(heartbeat_path,
                             already_done + len(results), grand_total, label)

    if workers <= 1:
        for n, (cfg, name, meta) in enumerate(tasks, 1):
            print(f"\n[{n}/{total}] {name}")
            metrics, wall = run_single_experiment(cfg, name, verbose)
            _persist({**meta, "wall_time_sec": wall, **asdict(metrics)}, name)
    else:
        print(f"\n  Dispatching {total} jobs across {workers} workers ...")
        worker_args = [(cfg, nm, verbose) for cfg, nm, _ in tasks]
        meta_map = {nm: meta for _, nm, meta in tasks}
        done = 0
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_task, a): a[1] for a in worker_args}
            for fut in as_completed(futs):
                nm = futs[fut]
                done += 1
                meta = meta_map[nm]
                try:
                    r = fut.result()
                    row = {**meta, "wall_time_sec": r["_wall"], **r["_metrics"]}
                except Exception as exc:
                    print(f"  [{done}/{total}] ERROR {nm}: {exc}")
                    row = {**meta, "wall_time_sec": 0.0,
                           **asdict(Metrics(steps=2000))}
                _persist(row, nm)
                if done % 10 == 0 or done == total:
                    elapsed = time.time() - t0
                    overall_done = already_done + done
                    pct = (100.0 * overall_done / grand_total
                           if grand_total else 0.0)
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] "
                          f"Completed {overall_done}/{grand_total} "
                          f"({pct:.1f}%) — last: {nm}  ({elapsed:.0f}s elapsed)")

    if csv_handle is not None:
        csv_handle.close()
    return results


# ---------------------------------------------------------------------------
# Aggregation by (solver, map_tag, num_agents, horizon)
# ---------------------------------------------------------------------------
def _aggregate_by_group(
        results: List[Dict[str, Any]],
) -> Dict[Tuple[str, str, int], List[Dict[str, Any]]]:
    """Group results by (solver, map_tag, num_agents) and aggregate per horizon.

    Returns {(solver, map, agents): [agg_rows_per_horizon]}.
    """
    groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in results:
        key = (r["solver"], r["map_tag"], r["num_agents"])
        groups[key].append(r)

    agg_groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}
    for key, rows in groups.items():
        agg = aggregate_results(rows)
        # Tag each agg row with group info
        for a in agg:
            a["solver"] = key[0]
            a["map_tag"] = key[1]
            a["num_agents"] = key[2]
        agg_groups[key] = agg
    return agg_groups


# ---------------------------------------------------------------------------
# Grand summary: best horizon per solver (averaged over maps × agents)
# ---------------------------------------------------------------------------
def _compute_grand_summary(
        results: List[Dict[str, Any]],
        horizon_values: List[int],
) -> Dict[str, Dict[str, Any]]:
    """For each solver, find the horizon with best average throughput
    across all maps and agent counts."""
    # Group by (solver, horizon, seed) — average across maps/agents per seed
    solver_horizon_seeds: Dict[Tuple[str, int], Dict[int, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        key = (r["solver"], r["value"])
        solver_horizon_seeds[key][r["seed"]].append(r.get("throughput", 0.0))

    # Average per seed, then aggregate across seeds
    per_solver: Dict[str, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for (solver, horizon), seed_vals in solver_horizon_seeds.items():
        for seed, vals in seed_vals.items():
            per_solver[solver][horizon].append(float(np.mean(vals)))

    best_per_solver: Dict[str, Dict[str, Any]] = {}
    for solver, horizon_data in per_solver.items():
        best_h = None
        best_mean = -1.0
        for h in horizon_values:
            vals = horizon_data.get(h, [])
            if vals:
                m = float(np.mean(vals))
                if m > best_mean:
                    best_mean = m
                    best_h = h
        if best_h is not None:
            vals = horizon_data[best_h]
            best_per_solver[solver] = {
                "value": best_h,
                "throughput_mean": float(np.mean(vals)),
                "throughput_std": float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0,
            }
    return best_per_solver


# ---------------------------------------------------------------------------
# Cross-solver comparison table
# ---------------------------------------------------------------------------
def _print_cross_solver_summary(
        per_solver: Dict[str, Dict[str, Any]],
) -> None:
    """Print a table comparing the best horizon per solver."""
    print(f"\n{'=' * 60}")
    print("Cross-solver horizon comparison (best by throughput)")
    print("(averaged across all maps and agent counts)")
    print(f"{'=' * 60}")
    header = f"{'Solver':<14}{'Best H':>7}{'Throughput':>18}"
    print(header)
    print("-" * len(header))
    for solver, best in per_solver.items():
        h = best["value"]
        tp = best.get("throughput_mean", float("nan"))
        tp_s = best.get("throughput_std", 0)
        print(f"{solver:<14}{h:>7}{tp:>10.4f} +/- {tp_s:<6.4f}")
    print("-" * len(header))

    best_horizons = {s: b["value"] for s, b in per_solver.items()}
    unique = set(best_horizons.values())
    if len(unique) == 1:
        print(f"\nAll solvers agree: best horizon = {unique.pop()}")
        print("-> horizon is solver-agnostic (safe to use a single value)")
    else:
        print(f"\nSolvers disagree on best horizon: {best_horizons}")
        print("-> consider per-solver horizon or use the most common value")


# ---------------------------------------------------------------------------
# LaTeX cross-solver table
# ---------------------------------------------------------------------------
def _write_cross_solver_latex(
        per_solver: Dict[str, Dict[str, Any]],
        path: Path,
) -> None:
    """Write a booktabs LaTeX table comparing best horizon per solver."""
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\caption{Best planning horizon per solver (throughput-optimal), "
        r"averaged across 3~maps and all agent counts. "
        r"Coupled: \texttt{replan\_every} = $\lfloor H/2 \rfloor$. "
        r"15~seeds, 2000~steps.}",
        r"\label{tab:horizon_per_solver}",
        r"\setlength{\tabcolsep}{5pt}",
        r"\begin{tabular}{lcc}",
        r"\toprule",
        r"\textbf{Solver} & \textbf{Best $H$} & \textbf{Throughput} \\",
        r"\midrule",
    ]
    for solver, best in per_solver.items():
        h = best["value"]
        tp_m = best.get("throughput_mean", float("nan"))
        tp_s = best.get("throughput_std", 0)
        lines.append(
            f"{solver} & {h} & {tp_m:.4f}$\\pm${tp_s:.4f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    path.write_text("\n".join(lines) + "\n")
    print(f"Saved cross-solver LaTeX: {path}")


# ---------------------------------------------------------------------------
# Per-group detailed output
# ---------------------------------------------------------------------------
def _save_per_group_results(
        agg_groups: Dict[Tuple[str, str, int], List[Dict[str, Any]]],
        out: Path,
        no_latex: bool,
) -> None:
    """Save results in solver/map_tag/agents_N/ subdirectories."""
    for (solver, map_tag, n_agents), agg in agg_groups.items():
        group_dir = out / solver / map_tag / f"agents_{n_agents}"
        group_dir.mkdir(parents=True, exist_ok=True)
        pareto = compute_pareto_front(agg, obj1="throughput", obj2="near_misses")
        save_results([], agg, group_dir,
                     pareto=pareto if pareto else None,
                     latex=not no_latex)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tune horizon (Step 1) — multi-map, multi-solver, multi-agent-count",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Settings match compare_global_study_agents.py:\n"
            "  Maps:   random, warehouse_small (small), warehouse_large (large)\n"
            "  Small:  agents=[25,50,75,100]  humans=50\n"
            "  Large:  agents=[100,200,300,400]  humans=200\n"
            "  Seeds=15, steps=2000, fov=5, safety_radius=1, budget=10s\n"
            "\n"
            "Output: logs/tuning/horizon/<label>_<timestamp>/\n"
            "  results.csv              — per-seed raw data (all combos)\n"
            "  <solver>/<map>/agents_N/ — per-group summary + pareto + LaTeX\n"
            "  cross_solver_summary.csv — best horizon per solver\n"
            "  table_cross_solver.tex   — paper-ready LaTeX\n"
        ),
    )
    parser.add_argument(
        "--seeds", type=int, nargs="+",
        default=list(range(15)),
        help="Random seeds (default: 0..14 — 15 seeds, matching compare study)",
    )
    parser.add_argument(
        "--steps", type=int, default=2000,
        help="Simulation steps (default: 2000, matching compare study)",
    )
    parser.add_argument(
        "--maps", type=str, nargs="+",
        default=ALL_MAP_TAGS, choices=ALL_MAP_TAGS, metavar="MAP",
        help=f"Maps to include (default: all — {ALL_MAP_TAGS})",
    )
    parser.add_argument(
        "--values", type=int, nargs="+", default=SWEEP_VALUES,
        help=f"Horizon values to sweep (default: {SWEEP_VALUES})",
    )
    parser.add_argument(
        "--solver", type=str, nargs="+", default=None,
        metavar="SOLVER",
        help=(
            "Solver(s) to tune horizon for. "
            f"Available: {list(ALL_SOLVERS.keys())}. "
            "Use 'all' to sweep every solver. "
            "Default: lacam only."
        ),
    )
    parser.add_argument(
        "--workers", "-j", type=int, default=1,
        help="Parallel workers (0 = all cores)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument(
        "--output", type=str, default="logs/tuning",
        help="Base output directory",
    )
    parser.add_argument(
        "--label", type=str, default="",
        help="Run label for the output folder name",
    )
    parser.add_argument("--no-latex", action="store_true",
                        help="Skip LaTeX table generation")
    parser.add_argument(
        "--sanity", action="store_true",
        help="Quick smoke-test: 1 seed, 200 steps, first agent count per map, "
             "horizon=[20,50,75]",
    )
    parser.add_argument(
        "--budget-s", type=float, default=10.0,
        help="Per-call Tier-1 budget in seconds (default: 10.0, matching "
             "paper §5.1).  Sets both solver_timeout_s and the legacy "
             "time_budget_ms.",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Reuse an existing output directory instead of creating a "
             "timestamped one.  Required with --resume.",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip rows already in <output-dir>/results.csv.  The existing "
             "directory is reused; new rows are appended to the same CSV.  "
             "Useful for recovering from an interrupted sweep.",
    )
    args = parser.parse_args()
    args.workers = resolve_workers(args.workers)

    # Resolve solver list
    if args.solver is None:
        solvers = {"lacam": "lacam"}
    elif len(args.solver) == 1 and args.solver[0].lower() == "all":
        solvers = dict(ALL_SOLVERS)
    else:
        solvers = {}
        for s in args.solver:
            if s in ALL_SOLVERS:
                solvers[s] = ALL_SOLVERS[s]
            else:
                print(f"WARNING: unknown solver {s!r} — skipping "
                      f"(available: {list(ALL_SOLVERS.keys())})")

    if not solvers:
        print("ERROR: no valid solvers selected.")
        sys.exit(1)

    # Sanity mode overrides
    seeds = args.seeds
    steps = args.steps
    horizon_values = args.values
    map_tags = args.maps

    if args.sanity:
        seeds = [0]
        steps = 200
        horizon_values = [20, 50, 75]
        print("\n  ** SANITY MODE: 1 seed, 200 steps, horizon=[20,50,75], "
              "first agent count per map **")
        # Temporarily restrict to first agent count per map
        for mt in MAP_DEFS:
            MAP_DEFS[mt]["agent_counts"] = MAP_DEFS[mt]["agent_counts"][:1]

    # Build tasks
    tasks = _build_tasks(solvers, map_tags, horizon_values, seeds, steps,
                         budget_s=args.budget_s)
    original_total = len(tasks)

    # --resume / --output-dir resolution.  When either is provided, we
    # reuse an existing directory and (when --resume) skip the rows
    # already present in its results.csv.
    if args.resume and not args.output_dir:
        parser.error("--resume requires --output-dir <path>")

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
    else:
        out = make_output_dir("horizon", run_label=args.label,
                              base_dir=args.output)

    prior_rows: List[Dict[str, Any]] = []
    skip_keys: Set[Tuple[str, str, int, int, int]] = set()
    if args.resume:
        prior_rows = _read_completed_rows(out / "results.csv")
        skip_keys = _completed_keys(prior_rows)
        before = len(tasks)
        tasks = [t for t in tasks if _row_key(t[2]) not in skip_keys]
        print(f"  Resume         : {before - len(tasks)}/{before} rows "
              f"already in {out}/results.csv; {len(tasks)} remaining")

    # Header
    print(f"\nHorizon Tuning Study")
    print(f"  Date           : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Output         : {out}")
    print(f"  Steps          : {steps}")
    print(f"  Seeds          : {seeds[0]}..{seeds[-1]}  (n={len(seeds)})")
    print(f"  Horizon values : {horizon_values}")
    print(f"  Solvers        : {list(solvers.keys())}")
    print(f"  Maps           : {map_tags}")
    for mt in map_tags:
        mdef = MAP_DEFS[mt]
        print(f"    {mt:<20s} agents={mdef['agent_counts']}  humans={mdef['num_humans']}")
    print(f"  Total runs     : {original_total}"
          + (f"  (remaining: {len(tasks)})" if args.resume else ""))
    print(f"  Workers        : {args.workers}")
    print(f"  Budget         : {args.budget_s:.1f} s per Tier-1 call")

    # Run — incremental flush handled inside _execute_tasks.
    new_rows = _execute_tasks(
        tasks, args.workers, args.verbose,
        out=out, already_done=len(prior_rows), original_total=original_total,
    )

    # The final results.csv on disk is the source of truth (prior + new
    # rows, in the order they were flushed).  Re-read it so aggregation
    # sees both halves on a resumed run.
    results_path = out / "results.csv"
    if args.resume and prior_rows:
        results = _read_completed_rows(results_path)
        # Coerce numeric columns we'll aggregate over (csv reads as str)
        for r in results:
            for k, v in list(r.items()):
                if k in ("num_agents", "num_humans", "seed",
                        "replan_every", "value"):
                    try:
                        r[k] = int(v) if v != "" else 0
                    except (TypeError, ValueError):
                        pass
                else:
                    try:
                        r[k] = float(v)
                    except (TypeError, ValueError):
                        pass
        print(f"\nRe-read {len(results)} rows from {results_path} for aggregation")
    else:
        results = new_rows
        if results:
            print(f"\nSaved raw results: {results_path}")

    # Aggregate by (solver, map, agents) groups
    agg_groups = _aggregate_by_group(results)
    _save_per_group_results(agg_groups, out, args.no_latex)

    # Per-group statistical summaries
    for (solver, map_tag, n_agents), agg in sorted(agg_groups.items()):
        print(f"\n{'#' * 60}")
        print(f"# {solver} / {map_tag} / {n_agents} agents")
        print(f"{'#' * 60}")

        sens = compute_sensitivity(agg, metric="throughput")
        rng = sens.get("global_range", float("nan"))
        rng_str = f"{rng:.4f}" if rng == rng else "?"
        print(f"  Sensitivity — throughput range: {rng_str}")

        print_statistical_summary(
            agg,
            primary_metric="throughput",
            secondary_metrics=["mean_flowtime", "mean_planning_time_ms", "near_misses"],
        )

        best_tp = find_best(agg, metric="throughput")
        print(f"  Best horizon: {best_tp['value']}  "
              f"throughput={best_tp.get('throughput_mean', '?'):.4f}")

    # Per-group best horizon summary (solver × map × agents)
    best_per_group: List[Dict[str, Any]] = []
    for (solver, map_tag, n_agents), agg in sorted(agg_groups.items()):
        best = find_best(agg, metric="throughput")
        best_per_group.append({
            "solver": solver,
            "map": map_tag,
            "num_agents": n_agents,
            "best_horizon": best["value"],
            "throughput_mean": best.get("throughput_mean", float("nan")),
            "throughput_std": best.get("throughput_std", 0.0),
            "throughput_ci95_lo": best.get("throughput_ci95_lo", float("nan")),
            "throughput_ci95_hi": best.get("throughput_ci95_hi", float("nan")),
            "mean_flowtime_mean": best.get("mean_flowtime_mean", float("nan")),
            "near_misses_mean": best.get("near_misses_mean", float("nan")),
        })

    if best_per_group:
        pg_path = out / "best_horizon_per_group.csv"
        with open(pg_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=best_per_group[0].keys())
            writer.writeheader()
            writer.writerows(best_per_group)
        print(f"\nSaved per-group best: {pg_path}")

        # Print per-group table
        print(f"\n{'=' * 80}")
        print("Best horizon per (solver, map, agents)")
        print(f"{'=' * 80}")
        hdr = (f"{'Solver':<14}{'Map':<22}{'Agents':>6}"
               f"{'Best H':>8}{'Throughput':>14}{'Flowtime':>12}{'NearMiss':>10}")
        print(hdr)
        print("-" * len(hdr))
        for row in best_per_group:
            print(f"{row['solver']:<14}{row['map']:<22}{row['num_agents']:>6}"
                  f"{row['best_horizon']:>8}"
                  f"{row['throughput_mean']:>10.4f}±{row['throughput_std']:<4.4f}"
                  f"{row['mean_flowtime_mean']:>12.2f}"
                  f"{row['near_misses_mean']:>10.2f}")
        print("-" * len(hdr))

    # Grand cross-solver summary (averaged over maps × agents)
    grand = _compute_grand_summary(results, horizon_values)
    if grand:
        _print_cross_solver_summary(grand)

        # Save cross-solver summary CSV
        summary_path = out / "cross_solver_summary.csv"
        rows = [{"solver": s, **v} for s, v in grand.items()]
        with open(summary_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"Saved cross-solver summary: {summary_path}")

        if not args.no_latex:
            _write_cross_solver_latex(grand, out / "table_cross_solver.tex")

    # Recommendations
    print(f"\nRecommended next step:")
    for solver, best in grand.items():
        print(f"  {solver}: python scripts/tuning/tune_replan_every.py "
              f"--best-horizon {best['value']}")


if __name__ == "__main__":
    main()
