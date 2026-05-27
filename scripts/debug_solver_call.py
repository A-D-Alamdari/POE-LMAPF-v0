#!/usr/bin/env python3
"""
Diagnostic harness for the lacam3 / lacam_official / lns2 error storm
observed in scaling sweeps at 250+ agents.

The scaling CSVs show ``solver_errors_mean = 100.0`` (every replan
failed) for these three wrappers, while pibt2 shows zero errors on the
same configuration.  This script constructs realistic rolling-horizon
windowed instances, invokes each wrapper through ``plan_with_metadata``,
and dumps every artifact the binary saw / produced -- the only way to
distinguish format drift, parser drift, and instance-rejection.

Run::

    python scripts/debug_solver_call.py                       # all three
    python scripts/debug_solver_call.py --solvers lacam3      # just one
    python scripts/debug_solver_call.py --inject-duplicate-goals 0
    python scripts/debug_solver_call.py --num-agents 250

The output directory (``logs/solver_debug/`` by default) collects, per
solver and scenario:

    <solver>__<scenario>/cmd.txt           the exact argv handed to subprocess
    <solver>__<scenario>/map.map           the map file the binary read
    <solver>__<scenario>/scenario.scen     the scenario file the binary read
    <solver>__<scenario>/stdout.txt        captured stdout
    <solver>__<scenario>/stderr.txt        captured stderr
    <solver>__<scenario>/result.txt        raw result file the binary wrote
    <solver>__<scenario>/verdict.json      {status, error_msg, num_paths, ...}

Scenarios:

    clean              200 agents, no duplicate goals, no start==goal
    start_eq_goal      200 agents, ~1/3 have start == goal
    duplicate_goals    200 agents, ~2 pairs of agents share a goal cell
    realistic          250 agents on random-64-64-10 with random pickup-
                       delivery tasks (no uniqueness guarantee, mimics
                       the live runner's distribution).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from ha_lmapf.core.types import AgentState, Task  # noqa: E402
from ha_lmapf.io.movingai_map import load_movingai_map  # noqa: E402
from ha_lmapf.simulation.environment import Environment  # noqa: E402

# Solver wrappers.
from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver  # noqa: E402
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import (  # noqa: E402
    LaCAMOfficialSolver,
)
from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver  # noqa: E402

Cell = Tuple[int, int]


# ---------------------------------------------------------------------------
# Synthetic windowed instance generation
# ---------------------------------------------------------------------------


def _load_env(map_path: Path) -> Environment:
    md = load_movingai_map(str(map_path))
    return Environment(width=md.width, height=md.height, blocked=md.blocked)


def _sample_distinct_free_cells(env: Environment, n: int,
                                rng: np.random.Generator) -> List[Cell]:
    free = list(env._free_cells)
    rng.shuffle(free)
    if len(free) < n:
        raise RuntimeError(
            f"need {n} free cells, map only has {len(free)}"
        )
    return free[:n]


def build_clean_instance(env: Environment, num_agents: int,
                         rng: np.random.Generator,
                         ) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    """All agents have unique start and a unique goal cell, no overlaps."""
    cells = _sample_distinct_free_cells(env, num_agents * 2, rng)
    starts = cells[:num_agents]
    goals = cells[num_agents:]
    agents = {
        i: AgentState(agent_id=i, pos=starts[i], goal=goals[i])
        for i in range(num_agents)
    }
    return agents, {}


def build_start_eq_goal_instance(env: Environment, num_agents: int,
                                 rng: np.random.Generator,
                                 ) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    """A third of agents have ``start == goal`` (already at their target)."""
    cells = _sample_distinct_free_cells(env, num_agents * 2, rng)
    starts = cells[:num_agents]
    goals = cells[num_agents:]
    agents: Dict[int, AgentState] = {}
    for i in range(num_agents):
        if i % 3 == 0:
            agents[i] = AgentState(agent_id=i, pos=starts[i], goal=starts[i])
        else:
            agents[i] = AgentState(agent_id=i, pos=starts[i], goal=goals[i])
    return agents, {}


def build_duplicate_goals_instance(env: Environment, num_agents: int,
                                   num_duplicates: int,
                                   rng: np.random.Generator,
                                   ) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    """Most agents are clean; ``num_duplicates`` pairs share a goal cell."""
    cells = _sample_distinct_free_cells(env, num_agents * 2, rng)
    starts = cells[:num_agents]
    goals = list(cells[num_agents:])
    # Force ``num_duplicates`` pairs to collide: agent (2k+1)'s goal = (2k)'s goal.
    for k in range(num_duplicates):
        i1 = 2 * k
        i2 = 2 * k + 1
        if i2 < num_agents:
            goals[i2] = goals[i1]
    agents = {
        i: AgentState(agent_id=i, pos=starts[i], goal=goals[i])
        for i in range(num_agents)
    }
    return agents, {}


def build_realistic_instance(env: Environment, num_agents: int,
                             rng: np.random.Generator,
                             ) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    """Mimics the rolling-horizon distribution at a mid-run replan:

    * Each agent has a unique start (simulator invariant).
    * Each agent is in ONE of: (i) Phase-2 delivery to a random goal
      (60%), (ii) Phase-1 pickup to a random pickup cell (20%), (iii)
      idle: ``goal=None`` with no task (10%), (iv) just-arrived:
      ``goal == pos`` (10%).  Per-task goal cells are sampled
      independently -- no uniqueness guarantee, mirroring
      ``scripts/make_task_streams.py``.
    """
    starts = _sample_distinct_free_cells(env, num_agents, rng)
    free_pool = list(env._free_cells)
    agents: Dict[int, AgentState] = {}
    assignments: Dict[int, Task] = {}
    for i, start in enumerate(starts):
        roll = rng.random()
        if roll < 0.60:  # Phase-2 delivery: agent.goal set
            g = free_pool[int(rng.integers(0, len(free_pool)))]
            agents[i] = AgentState(agent_id=i, pos=start, goal=g,
                                   task_id=f"t_{i}", carrying=True)
        elif roll < 0.80:  # Phase-1 pickup: agent.goal == pickup
            g = free_pool[int(rng.integers(0, len(free_pool)))]
            agents[i] = AgentState(agent_id=i, pos=start, goal=g,
                                   task_id=f"t_{i}", carrying=False)
            assignments[i] = Task(task_id=f"t_{i}", start=g, goal=g,
                                  release_step=0)
        elif roll < 0.90:  # idle, no task: included via assignments fallback
            agents[i] = AgentState(agent_id=i, pos=start, goal=None)
            # Inject a random task for some idle agents (mimics
            # mid-tick allocator handoff).
            if rng.random() < 0.5:
                g = free_pool[int(rng.integers(0, len(free_pool)))]
                assignments[i] = Task(task_id=f"t_{i}", start=g, goal=g,
                                      release_step=0)
        else:  # just-arrived: start == goal
            agents[i] = AgentState(agent_id=i, pos=start, goal=start)
    return agents, assignments


def count_goal_duplicates(agents: Dict[int, AgentState],
                          assignments: Dict[int, Task]) -> Dict[str, int]:
    """Count how many active agents share a goal cell with at least
    one other active agent, and how many have ``start == goal``."""
    from collections import Counter
    effective_goals: List[Cell] = []
    start_eq_goal = 0
    for aid, ag in agents.items():
        if ag.goal is not None:
            g = ag.goal
        elif aid in assignments:
            g = assignments[aid].goal
        else:
            continue
        if g == ag.pos:
            start_eq_goal += 1
        effective_goals.append(g)
    counts = Counter(effective_goals)
    dup_cells = sum(1 for c, n in counts.items() if n > 1)
    dup_agents = sum(n for n in counts.values() if n > 1)
    return {
        "active_with_goal": len(effective_goals),
        "unique_goal_cells": len(counts),
        "duplicate_goal_cells": dup_cells,
        "agents_with_duplicated_goal": dup_agents,
        "start_eq_goal_agents": start_eq_goal,
    }


# ---------------------------------------------------------------------------
# Per-solver invocation: hook into plan_with_metadata, capture artifacts
# ---------------------------------------------------------------------------


def _make_solver(name: str, time_limit_sec: float):
    if name == "lacam3":
        return LaCAM3Solver(time_limit_sec=time_limit_sec, verbose=0)
    if name == "lacam_official":
        return LaCAMOfficialSolver(time_limit_sec=time_limit_sec, verbose=0)
    if name == "lns2":
        return LNS2Solver(time_limit_sec=time_limit_sec, verbose=0)
    raise ValueError(f"unknown solver {name!r}")


def _capture_subprocess_invocation(solver, env: Environment,
                                   agents: Dict[int, AgentState],
                                   assignments: Dict[int, Task],
                                   capture_dir: Path):
    """Intercept the wrapper's ``subprocess.run`` to capture the exact
    cmdline + (map, scenario) files and the raw stdout/stderr/result
    that the binary emits.  Returns ``(SolverResult, info_dict)``."""
    capture_dir.mkdir(parents=True, exist_ok=True)

    # Monkey-patch subprocess.run for this one invocation so we
    # capture the cmdline and copy the input/output artifacts off the
    # ephemeral tempdir before it is removed.
    import subprocess as _sp
    real_run = _sp.run
    captured: Dict[str, object] = {}

    def patched_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        # Pull paths from the cmd: every wrapper here uses ``-m`` for
        # the map and ``-i`` (lacam/lacam3) or ``-a`` (lns2) for the
        # scenario, plus ``-o`` for the result/output.
        argv = list(cmd)
        for flag in ("-m", "-i", "-a", "-o"):
            if flag in argv:
                idx = argv.index(flag)
                if idx + 1 < len(argv):
                    captured[flag] = argv[idx + 1]
        # Capture the --outputPaths form for LNS2.
        for arg in argv:
            if arg.startswith("--outputPaths="):
                captured["--outputPaths"] = arg.split("=", 1)[1]
        # Copy input files BEFORE the binary runs so we have them
        # even if the wrapper's finally-block wipes the tempdir.
        for key in ("-m", "-i", "-a"):
            src = captured.get(key)
            if isinstance(src, str) and os.path.isfile(src):
                shutil.copy2(
                    src,
                    capture_dir / (
                        "map.map" if key == "-m" else "scenario.scen"
                    ),
                )
        result = real_run(cmd, *args, **kwargs)
        captured["returncode"] = result.returncode
        captured["stdout"] = result.stdout or ""
        captured["stderr"] = result.stderr or ""
        # Copy output files now that they exist.
        for key in ("-o", "--outputPaths"):
            src = captured.get(key)
            if isinstance(src, str) and os.path.isfile(src):
                dst_name = "result.txt" if key == "-o" else "paths.txt"
                shutil.copy2(src, capture_dir / dst_name)
        return result

    try:
        _sp.run = patched_run
        # _wrap_subprocess imports subprocess at module load time; the
        # binding inside _base.py needs patching too.
        import ha_lmapf.global_tier.solvers._base as base_mod
        real_base_run = base_mod.subprocess.run
        base_mod.subprocess.run = patched_run
        try:
            result = solver.plan_with_metadata(
                env=env, agents=agents, assignments=assignments,
                step=0, horizon=40, rng=None,
            )
        finally:
            base_mod.subprocess.run = real_base_run
    finally:
        _sp.run = real_run

    # Persist captured stdio + cmd to files.
    (capture_dir / "cmd.txt").write_text(
        " ".join(str(c) for c in captured.get("cmd", []))
    )
    (capture_dir / "stdout.txt").write_text(str(captured.get("stdout", "")))
    (capture_dir / "stderr.txt").write_text(str(captured.get("stderr", "")))
    info = {
        "cmd": captured.get("cmd"),
        "returncode": captured.get("returncode"),
        "stdout_tail": str(captured.get("stdout", ""))[-2000:],
        "stderr_tail": str(captured.get("stderr", ""))[-2000:],
        "status": result.status,
        "error_msg": result.error_msg,
        "solver_wall_ms": result.solver_wall_ms,
        "end_to_end_wall_ms": result.end_to_end_wall_ms,
        "num_paths": len(result.plan.paths) if result.plan and result.plan.paths else 0,
        "horizon": result.plan.horizon if result.plan else None,
    }
    return result, info


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


SCENARIO_BUILDERS = {
    "clean":           lambda env, n, rng: build_clean_instance(env, n, rng),
    "start_eq_goal":   lambda env, n, rng: build_start_eq_goal_instance(env, n, rng),
    "duplicate_goals": lambda env, n, rng: build_duplicate_goals_instance(env, n, 2, rng),
    "realistic":       lambda env, n, rng: build_realistic_instance(env, n, rng),
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", type=Path,
                   default=_REPO_ROOT / "data/maps/random-64-64-10.map")
    p.add_argument("--num-agents", type=int, default=200)
    p.add_argument("--solvers", nargs="+",
                   default=["lacam3", "lacam_official", "lns2"],
                   help="Which wrappers to exercise.")
    p.add_argument("--scenarios", nargs="+",
                   default=list(SCENARIO_BUILDERS.keys()),
                   help=f"Which instance shapes to exercise. "
                        f"Choices: {sorted(SCENARIO_BUILDERS.keys())}.")
    p.add_argument("--time-limit-sec", type=float, default=5.0)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path,
                   default=_REPO_ROOT / "logs/solver_debug")
    args = p.parse_args()

    if not args.map.exists():
        print(f"ERROR: map not found at {args.map}", file=sys.stderr)
        return 1

    env = _load_env(args.map)
    print(f"map: {args.map.name} ({env.width}x{env.height}, "
          f"{len(env._free_cells)} free)")

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    summary: List[Dict[str, object]] = []

    for scenario in args.scenarios:
        if scenario not in SCENARIO_BUILDERS:
            print(f"WARN: unknown scenario {scenario!r}; skipping",
                  file=sys.stderr)
            continue
        rng = np.random.default_rng(args.seed)
        agents, assignments = SCENARIO_BUILDERS[scenario](
            env, args.num_agents, rng,
        )
        dup_stats = count_goal_duplicates(agents, assignments)
        print(f"\n=== scenario={scenario} num_agents={args.num_agents} ===")
        print(f"    duplicate-goal stats: {dup_stats}")

        for solver_name in args.solvers:
            solver = _make_solver(solver_name, args.time_limit_sec)
            capture_dir = out_root / f"{solver_name}__{scenario}"
            print(f"  -> {solver_name} ... ", end="", flush=True)
            try:
                result, info = _capture_subprocess_invocation(
                    solver, env, agents, assignments, capture_dir,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"EXCEPTION: {type(exc).__name__}: {exc}")
                (capture_dir / "verdict.json").write_text(json.dumps({
                    "scenario": scenario, "solver": solver_name,
                    "exception": f"{type(exc).__name__}: {exc}",
                }, indent=2))
                summary.append({
                    "scenario": scenario, "solver": solver_name,
                    "status": "exception",
                    "error_msg": f"{type(exc).__name__}: {exc}",
                })
                continue
            verdict = {
                "scenario": scenario,
                "solver": solver_name,
                "num_agents": args.num_agents,
                "duplicate_stats": dup_stats,
                **info,
            }
            (capture_dir / "verdict.json").write_text(json.dumps(verdict, indent=2))
            print(f"status={info['status']:18s} "
                  f"rc={info['returncode']!s:>4} "
                  f"err={info['error_msg']!r}")
            summary.append({
                "scenario":  scenario,
                "solver":    solver_name,
                "status":    info["status"],
                "error_msg": info["error_msg"],
                "returncode": info["returncode"],
                "num_paths": info["num_paths"],
            })

    summary_path = out_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nartifacts in: {out_root}")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
