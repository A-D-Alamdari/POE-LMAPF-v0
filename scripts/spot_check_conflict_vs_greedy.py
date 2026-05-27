"""Diagnostic spot check: congestion_avoidance vs. greedy at warehouse-2-2 |M|=200.

Sibling diagnostic to ``scripts/calibrate_solver_budgets.py``; does NOT
mutate any production script.  Runs the contested cell
(warehouse-10-20-10-2-2.map, |M|=200, |X|=100, lacam_official, H=20,
R=10, 10 s budget) for 500 steps under both allocators across three
seeds, writes one CSV row per run atomically as it completes, and
prints a verdict comparing the two allocators on raw throughput.

The verdict is the headline artifact: the user decides from it
whether to commit hours of compute to the Direction A calibration
re-run.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import statistics
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.getLogger("ha_lmapf.global_tier.rolling_horizon").setLevel(logging.ERROR)
logging.getLogger("ha_lmapf.simulation.simulator").setLevel(logging.ERROR)

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


MAP_STEM = "warehouse-10-20-10-2-2"
NUM_AGENTS = 200
NUM_HUMANS = 100
GLOBAL_SOLVER = "lacam_official"
HORIZON = 20
REPLAN_EVERY = 10
SOLVER_TIMEOUT_S = 10.0
DEFAULT_STEPS = 500

ALLOCATORS = ["greedy", "congestion_avoidance"]
DEFAULT_SEEDS = [0, 1, 2]

CSV_FIELDS = [
    "allocator", "seed", "status",
    "throughput", "completed_tasks", "total_released_tasks",
    "task_completion", "solver_errors", "solver_timeouts",
    "solver_partial_returns",
    "mean_planning_time_ms", "p95_planning_time_ms",
    "assignments_kept", "assignments_broken",
    "wall_time_sec", "mean_allocator_time_ms",
    "replans", "error_msg",
]


def _map_path() -> str:
    p = Path("data/maps") / f"{MAP_STEM}.map"
    if not p.exists():
        raise FileNotFoundError(f"map not found: {p}")
    return str(p)


def _run_one(allocator: str, seed: int, steps: int,
             lambda_conflict: float = 0.5) -> Dict[str, Any]:
    """Run a single simulation and return one CSV row.

    Wraps the simulator's allocator instance to record wall-time per
    ``allocate`` call, then summarises across all calls.
    """
    t0 = time.monotonic()
    try:
        cfg = SimConfig(
            map_path=_map_path(),
            seed=seed,
            steps=steps,
            num_agents=NUM_AGENTS,
            num_humans=NUM_HUMANS,
            fov_radius=4,
            safety_radius=1,
            global_solver=GLOBAL_SOLVER,
            replan_every=REPLAN_EVERY,
            horizon=HORIZON,
            communication_mode="priority",
            local_planner="astar",
            human_model="random_walk",
            hard_safety=True,
            mode="lifelong",
            solver_timeout_s=SOLVER_TIMEOUT_S,
            task_allocator=allocator,
            lambda_conflict=lambda_conflict,
        )
        sim = Simulator(cfg)

        # Wrap assign() to record per-call wall-time
        alloc_times_ms: List[float] = []
        orig_assign = sim.task_allocator.assign

        def timed_assign(*args, **kwargs):
            t_a0 = time.perf_counter()
            res = orig_assign(*args, **kwargs)
            alloc_times_ms.append((time.perf_counter() - t_a0) * 1000.0)
            return res

        sim.task_allocator.assign = timed_assign

        metrics = sim.run()
        wall = time.monotonic() - t0

        completed = int(metrics.completed_tasks)
        released = int(metrics.total_released_tasks)
        task_completion = (completed / released) if released > 0 else 0.0
        mean_alloc_ms = (
            statistics.fmean(alloc_times_ms) if alloc_times_ms else math.nan
        )

        return {
            "allocator": allocator,
            "seed": seed,
            "status": "ok",
            "throughput": float(metrics.throughput),
            "completed_tasks": completed,
            "total_released_tasks": released,
            "task_completion": task_completion,
            "solver_errors": int(metrics.solver_errors),
            "solver_timeouts": int(metrics.solver_timeouts),
            "solver_partial_returns": int(metrics.solver_partial_returns),
            "mean_planning_time_ms": float(metrics.mean_planning_time_ms),
            "p95_planning_time_ms": float(metrics.p95_planning_time_ms),
            "assignments_kept": int(metrics.assignments_kept),
            "assignments_broken": int(metrics.assignments_broken),
            "wall_time_sec": wall,
            "mean_allocator_time_ms": mean_alloc_ms,
            "replans": int(getattr(metrics, "replans", 0)),
            "error_msg": "",
        }
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        wall = time.monotonic() - t0
        return {
            "allocator": allocator,
            "seed": seed,
            "status": "error",
            "throughput": math.nan,
            "completed_tasks": 0,
            "total_released_tasks": 0,
            "task_completion": math.nan,
            "solver_errors": 0,
            "solver_timeouts": 0,
            "solver_partial_returns": 0,
            "mean_planning_time_ms": math.nan,
            "p95_planning_time_ms": math.nan,
            "assignments_kept": 0,
            "assignments_broken": 0,
            "wall_time_sec": wall,
            "mean_allocator_time_ms": math.nan,
            "replans": 0,
            "error_msg": f"{type(exc).__name__}: {exc}\n{tb}"[:1500],
        }


def _write_row(out_path: Path, row: Dict[str, Any]) -> None:
    """Atomic per-row append.  First write creates header via tmp+rename;
    subsequent rows append in-place (append is atomic for single
    lines on POSIX)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists():
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
        os.replace(tmp, out_path)
    else:
        with out_path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def _run_one_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _run_one(**kwargs)


# Paired t-critical at alpha=0.05 (two-sided) for df = n-1
_T_CRIT_TWO_SIDED_0_05 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571}


def _paired_ci(diffs: List[float]) -> tuple:
    """Paired-difference 95% CI via t-distribution.  Returns
    (mean, ci_low, ci_high).  When n<2 or sd==0, returns (mean, mean, mean)."""
    n = len(diffs)
    if n == 0:
        return (math.nan, math.nan, math.nan)
    mean = statistics.fmean(diffs)
    if n < 2:
        return (mean, mean, mean)
    sd = statistics.stdev(diffs)
    if sd == 0.0:
        return (mean, mean, mean)
    t_crit = _T_CRIT_TWO_SIDED_0_05.get(n - 1, 1.96)
    half = t_crit * sd / math.sqrt(n)
    return (mean, mean - half, mean + half)


def _summarise(rows: List[Dict[str, Any]], steps: int) -> str:
    """Produce the human-readable verdict per spec §3.6."""
    by_alloc: Dict[str, List[Dict[str, Any]]] = {a: [] for a in ALLOCATORS}
    for r in rows:
        if r["status"] == "ok" and r["allocator"] in by_alloc:
            by_alloc[r["allocator"]].append(r)

    def _agg(allocator: str) -> Dict[str, float]:
        rs = by_alloc[allocator]
        if not rs:
            return {k: math.nan for k in
                    ("throughput_mean", "throughput_sd",
                     "completed_mean", "completed_sd",
                     "task_completion_mean", "solver_err_sum",
                     "mean_plan_ms_mean")}
        tput = [r["throughput"] for r in rs]
        comp = [r["completed_tasks"] for r in rs]
        tcomp = [r["task_completion"] for r in rs]
        serr = sum(r["solver_errors"] for r in rs)
        plan = [r["mean_planning_time_ms"] for r in rs]
        return {
            "throughput_mean": statistics.fmean(tput),
            "throughput_sd": statistics.stdev(tput) if len(tput) > 1 else 0.0,
            "completed_mean": statistics.fmean(comp),
            "completed_sd": statistics.stdev(comp) if len(comp) > 1 else 0.0,
            "task_completion_mean": statistics.fmean(tcomp) * 100.0,
            "solver_err_sum": serr,
            "mean_plan_ms_mean": statistics.fmean(plan),
        }

    g = _agg("greedy")
    c = _agg("congestion_avoidance")

    # Paired difference (only seeds where BOTH allocators succeeded)
    paired_diffs: List[float] = []
    paired_tcomp_diffs: List[float] = []
    seeds_seen = sorted({r["seed"] for r in rows
                         if r["status"] == "ok"
                         and r["allocator"] in ALLOCATORS})
    for s in seeds_seen:
        gr = next((r for r in by_alloc["greedy"] if r["seed"] == s), None)
        cr = next((r for r in by_alloc["congestion_avoidance"]
                   if r["seed"] == s), None)
        if gr and cr:
            paired_diffs.append(cr["throughput"] - gr["throughput"])
            paired_tcomp_diffs.append(
                cr["task_completion"] - gr["task_completion"])
    d_mean, d_lo, d_hi = _paired_ci(paired_diffs)
    tc_mean, _, _ = _paired_ci(paired_tcomp_diffs)
    err_delta_raw = c["solver_err_sum"] - g["solver_err_sum"]
    err_delta_str = (
        f"{int(err_delta_raw):+d}"
        if not (isinstance(err_delta_raw, float) and math.isnan(err_delta_raw))
        else "nan"
    )

    # Verdict
    if (d_mean > 0.05) and (d_lo > 0.0):
        verdict = (
            "MEANINGFUL POSITIVE EFFECT — congestion_avoidance reduces Tier-1 "
            "failure regime at this cell. Decomposition re-run expected "
            "to show smaller ratios. Proceed to Prompt 3 (calibration "
            "re-run)."
        )
    elif (d_mean < -0.05):
        verdict = (
            "NEGATIVE EFFECT — congestion_avoidance is producing worse outcomes "
            "than greedy. This is a regression in the allocator. STOP and "
            "investigate before proceeding to any further compute. "
            "Possible causes: bug in iterative refinement, λ too "
            "aggressive causing degenerate assignments, or interaction "
            "between congestion_avoidance and the SPR fallback. Rollback "
            "recommended: git reset --hard v1.4-pre-direction-a-activation"
        )
    else:
        verdict = (
            "NEGLIGIBLE EFFECT — congestion_avoidance does not meaningfully "
            "change throughput at this cell. Decomposition ratios will "
            "be similar to v1.4 (24× and 19×). Two options: (a) proceed "
            "to Prompt 3 anyway (the paper's reframing strengthens "
            "because the gap is robust to allocator design), or (b) "
            "tweak λ in CongestionAvoidanceTaskAllocator before re-running."
        )

    lines = []
    lines.append("=== Spot Check Report ===")
    lines.append(
        f"Cell: {MAP_STEM}, |M|={NUM_AGENTS}, |X|={NUM_HUMANS}, "
        f"solver={GLOBAL_SOLVER}, H={HORIZON}, R={REPLAN_EVERY}, "
        f"budget={SOLVER_TIMEOUT_S}s, steps={steps}"
    )
    lines.append("")
    lines.append(
        "ALLOCATOR        | THROUGHPUT      | COMPLETED       | TASK_COMPL | SOLVER_ERR | MEAN_PLAN_MS"
    )
    lines.append(
        f"greedy           | {g['throughput_mean']:.4f} ± {g['throughput_sd']:.4f} | "
        f"{g['completed_mean']:5.1f} ± {g['completed_sd']:4.1f} | "
        f"{g['task_completion_mean']:5.1f}%     | "
        f"{int(g['solver_err_sum']) if not math.isnan(g['solver_err_sum']) else 'nan':>10} | "
        f"{g['mean_plan_ms_mean']:.1f}"
    )
    lines.append(
        f"congestion_avoidance   | {c['throughput_mean']:.4f} ± {c['throughput_sd']:.4f} | "
        f"{c['completed_mean']:5.1f} ± {c['completed_sd']:4.1f} | "
        f"{c['task_completion_mean']:5.1f}%     | "
        f"{int(c['solver_err_sum']) if not math.isnan(c['solver_err_sum']) else 'nan':>10} | "
        f"{c['mean_plan_ms_mean']:.1f}"
    )
    lines.append("")
    if math.isnan(d_mean):
        lines.append("Δ throughput (congestion_avoidance − greedy): n/a (no paired seeds)")
    else:
        lines.append(
            f"Δ throughput (congestion_avoidance − greedy): {d_mean:+.4f} "
            f"([{d_lo:+.4f}, {d_hi:+.4f}], paired n={len(paired_diffs)})"
        )
    if not math.isnan(tc_mean):
        lines.append(
            f"Δ task completion (congestion_avoidance − greedy): {tc_mean*100.0:+.1f} pp"
        )
    lines.append(
        f"Δ solver errors (congestion_avoidance − greedy): {err_delta_str} "
        f"(negative = fewer errors = better)"
    )
    lines.append("")
    lines.append(f"Interpretation: {verdict}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=str, default=",".join(
        str(s) for s in DEFAULT_SEEDS))
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--lambda-conflict", type=float, default=0.5,
        help="lambda_conflict for the congestion_avoidance allocator. "
             "Ignored for greedy.")
    parser.add_argument(
        "--out", type=Path,
        default=Path("logs/calibration/spot_check_conflict_vs_greedy.csv"))
    args = parser.parse_args()

    workers = max(1, min(args.workers, 4))  # cap per spec
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    # Reset output (no --resume)
    if args.out.exists():
        args.out.unlink()

    jobs = [{"allocator": a, "seed": s, "steps": args.steps,
             "lambda_conflict": args.lambda_conflict}
            for a in ALLOCATORS for s in seeds]
    print(f"[spot-check] {len(jobs)} runs "
          f"({len(ALLOCATORS)} allocators × {len(seeds)} seeds) "
          f"on {workers} worker(s); steps={args.steps}", flush=True)
    print(f"[spot-check] map={MAP_STEM} |M|={NUM_AGENTS} |X|={NUM_HUMANS} "
          f"solver={GLOBAL_SOLVER} budget={SOLVER_TIMEOUT_S}s", flush=True)
    print(f"[spot-check] writing rows incrementally to {args.out}",
          flush=True)

    rows: List[Dict[str, Any]] = []
    t0 = time.monotonic()
    completed = 0

    if workers <= 1:
        for j in jobs:
            r = _run_one_kwargs(j)
            _write_row(args.out, r)
            rows.append(r)
            completed += 1
            print(f"[spot-check] done {completed}/{len(jobs)}: "
                  f"allocator={r['allocator']} seed={r['seed']} "
                  f"status={r['status']} "
                  f"throughput={r['throughput']:.4f} "
                  f"wall={r['wall_time_sec']:.1f}s",
                  flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one_kwargs, j): j for j in jobs}
            for fut in as_completed(futs):
                j = futs[fut]
                try:
                    r = fut.result()
                except Exception as exc:  # noqa: BLE001
                    r = {
                        "allocator": j["allocator"], "seed": j["seed"],
                        "status": "error",
                        "throughput": math.nan, "completed_tasks": 0,
                        "total_released_tasks": 0,
                        "task_completion": math.nan,
                        "solver_errors": 0, "solver_timeouts": 0,
                        "solver_partial_returns": 0,
                        "mean_planning_time_ms": math.nan,
                        "p95_planning_time_ms": math.nan,
                        "assignments_kept": 0, "assignments_broken": 0,
                        "wall_time_sec": math.nan,
                        "mean_allocator_time_ms": math.nan,
                        "replans": 0,
                        "error_msg": f"future failure: {type(exc).__name__}: {exc}",
                    }
                _write_row(args.out, r)
                rows.append(r)
                completed += 1
                tput = r['throughput']
                tput_s = f"{tput:.4f}" if isinstance(tput, float) and not math.isnan(tput) else "nan"
                print(f"[spot-check] done {completed}/{len(jobs)}: "
                      f"allocator={r['allocator']} seed={r['seed']} "
                      f"status={r['status']} "
                      f"throughput={tput_s} "
                      f"wall={r['wall_time_sec']:.1f}s",
                      flush=True)

    elapsed = time.monotonic() - t0
    print(f"\n[spot-check] all runs complete in {elapsed:.1f}s "
          f"({elapsed/60:.1f} min); CSV at {args.out}", flush=True)

    print()
    print(_summarise(rows, steps=args.steps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
