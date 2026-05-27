#!/usr/bin/env python3
"""
Tier-1 -> Tier-2 guidance handoff diagnostic.

Runs three short, single-seed simulations on the same map / task
stream:

* ``pibt2``      — real, conflict-free global plans (the §5.5 control)
* ``lacam3``     — a different real solver to sanity-check that the
                   guidance quality varies independently of the
                   downstream pipeline
* ``all_wait``   — a debug planner that returns an all-WAIT bundle;
                   bounds the contribution of the global tier

The simulator's ``debug_guidance_trace`` flag is forced on, so each
run records ``guidance_coverage`` (the fraction of agent-ticks where a
global path existed for the agent at decision time) and
``guidance_follow_rate`` (the fraction of those covered ticks where
the executed move matched the bundle's prescription).  The script
prints a comparison table and saves the per-run metric dict to
``logs/tier_handoff_debug/``.

Three reasonable outcomes (mapped to the three buckets in
``docs/tier_handoff_diagnosis.md``):

1. ``follow_rate`` high in both pibt2 and all_wait, throughput equal:
   Tier 2 effectively re-plans from scratch.  The global plan is
   cosmetic.  The follow rate is high only because Tier 2's local A*
   happens to align with the bundle, or because both bundles say
   "wait" and the agent does wait.
2. ``follow_rate`` low even with pibt2: the handoff is broken
   (bundle not reaching the controller, or stale / misindexed).
3. ``follow_rate`` high with pibt2, low with all_wait, but
   throughput equal: throughput is task-supply bound, not pathing
   bound.

Run::

    python scripts/debug_tier_handoff.py --num-agents 25 --steps 500
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from ha_lmapf.core.types import SimConfig  # noqa: E402
from ha_lmapf.simulation.simulator import Simulator  # noqa: E402


SOLVERS = ["pibt2", "lacam3", "all_wait"]


def _run_one(solver: str, args: argparse.Namespace,
             controller_kind: str = "default") -> Dict[str, float]:
    cfg = SimConfig(
        map_path=str(args.map),
        seed=int(args.seed),
        task_arrival_rate=(
            float(args.task_arrival_rate) if args.task_arrival_rate is not None else None
        ),
        steps=int(args.steps),
        num_agents=int(args.num_agents),
        num_humans=int(args.num_humans),
        fov_radius=4,
        safety_radius=1,
        horizon=int(args.horizon),
        replan_every=int(args.replan_every),
        global_solver=solver,
        solver_timeout_s=10.0,
        hard_safety=True,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        mode="lifelong",
        task_allocator="congestion_avoidance",
        debug_guidance_trace=True,
        controller_kind=controller_kind,  # type: ignore[arg-type]
    )
    sim = Simulator(cfg)
    metrics = sim.run()
    return {
        "solver":              solver,
        "controller_kind":     controller_kind,
        "throughput":          float(metrics.throughput),
        "completed_tasks":     int(metrics.completed_tasks),
        "safe_wait_steps":     int(metrics.safe_wait_steps),
        "yield_wait_steps":    int(metrics.yield_wait_steps),
        "total_wait_steps":    int(metrics.total_wait_steps),
        "global_replans":      int(metrics.global_replans),
        "local_replans":       int(metrics.local_replans),
        "solver_errors":       int(metrics.solver_errors),
        "solver_timeouts":     int(metrics.solver_timeouts),
        "guidance_eligible_ticks": int(metrics.guidance_eligible_ticks),
        "guidance_covered_ticks":  int(metrics.guidance_covered_ticks),
        "guidance_followed_ticks": int(metrics.guidance_followed_ticks),
        "guidance_coverage":   float(metrics.guidance_coverage),
        "guidance_follow_rate": float(metrics.guidance_follow_rate),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", type=Path,
                   default=_REPO_ROOT / "data/maps/random-64-64-10.map")
    p.add_argument("--num-agents", type=int, default=25)
    p.add_argument("--num-humans", type=int, default=20)
    p.add_argument("--steps", type=int, default=500)
    p.add_argument("--horizon", type=int, default=20)
    p.add_argument("--replan-every", type=int, default=10)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--solvers", nargs="+", default=SOLVERS)
    p.add_argument("--controllers", nargs="+", default=["default"],
                   choices=["default", "global_only"],
                   help="Tier-2 controller variant(s) to compare.  "
                        "``global_only`` is the rigid-follower mode used "
                        "by the paper's PIBT2-FR baseline and disables "
                        "local replan / safety detours -- useful to isolate "
                        "the global-plan contribution.")
    p.add_argument("--task-arrival-rate", type=float, default=None,
                   help="Mean per-agent inter-arrival time (steps).  None = "
                        "simulator default (H + W) which is unit-load by "
                        "construction.  Smaller = oversupplied (backlog "
                        "grows, throughput is path-limited not supply-limited).")
    p.add_argument("--out", type=Path,
                   default=_REPO_ROOT / "logs/tier_handoff_debug")
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, float]] = []
    for ctrl in args.controllers:
        for s in args.solvers:
            print(f"=== solver={s}  controller={ctrl}  steps={args.steps}  "
                  f"num_agents={args.num_agents} ===")
            row = _run_one(s, args, controller_kind=ctrl)
            rows.append(row)
        print(f"  throughput          = {row['throughput']:.5f}  "
              f"({row['completed_tasks']} tasks)")
        print(f"  guidance_coverage   = {row['guidance_coverage']:.4f}  "
              f"({row['guidance_covered_ticks']}/{row['guidance_eligible_ticks']})")
        print(f"  guidance_follow_rate= {row['guidance_follow_rate']:.4f}  "
              f"({row['guidance_followed_ticks']}/{row['guidance_covered_ticks']})")
        print(f"  global_replans      = {row['global_replans']}  "
              f"local_replans={row['local_replans']}")
        print(f"  safe_wait_steps     = {row['safe_wait_steps']}  "
              f"yield_wait_steps={row['yield_wait_steps']}  "
              f"total_wait_steps={row['total_wait_steps']}")
        print(f"  solver_errors       = {row['solver_errors']}  "
              f"solver_timeouts={row['solver_timeouts']}")

    print()
    print("=== summary ===")
    print(f"{'solver':>12s}  {'ctrl':>11s}  {'throughput':>10s}  {'cover':>6s}  "
          f"{'follow':>6s}  {'global':>6s}  {'local':>6s}  {'safe_wait':>10s}")
    for row in rows:
        print(f"{row['solver']:>12s}  {row['controller_kind']:>11s}  "
              f"{row['throughput']:>10.5f}  "
              f"{row['guidance_coverage']:>6.3f}  "
              f"{row['guidance_follow_rate']:>6.3f}  "
              f"{row['global_replans']:>6d}  {row['local_replans']:>6d}  "
              f"{row['safe_wait_steps']:>10d}")

    (args.out / "summary.json").write_text(json.dumps(rows, indent=2))
    print(f"\nartifacts in: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
