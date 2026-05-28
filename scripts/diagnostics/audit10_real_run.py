"""Audit step 10 — produce ONE small real run on head with the
def1 columns populated, then test the identity claim row-for-row
on real data.

The claim under test (from reports/table1_audit.md and the
classifier docstring in simulator.py:1192-1245):

  "When the agent bucket is empty (def1_agent_attributable == 0),
   violations_def1_exogenous_attributable equals
   violations_exogenous_attributable -- the two classifiers
   iterate the same post-move pair set and disagree only on which
   pairs are agent-attributable."

This script:
  - constructs a small SimConfig (empty-16-16, 4 agents, 5 humans,
    300 steps, 3 seeds);
  - runs Simulator.run() on head;
  - extracts (legacy WAIT-cf, def1) buckets per run;
  - reports row-for-row whether they match;
  - confirms def1_agent_attributable == 0 on every run.
"""
from __future__ import annotations

import csv
import dataclasses
import sys
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT / "src"))

from ha_lmapf.core.types import SimConfig, Metrics
from ha_lmapf.simulation.simulator import Simulator


CONFIG_BASE = dict(
    map_path=str(ROOT / "data/maps/empty-16-16.map"),
    num_agents=4,
    num_humans=5,
    fov_radius=2,
    safety_radius=1,
    steps=300,
    human_model="random_walk",
    mode="lifelong",
    task_allocator="congestion_avoidance",
    hard_safety=True,
)


def run_one(seed: int) -> Dict[str, object]:
    cfg = SimConfig(seed=seed, **CONFIG_BASE)
    t0 = time.perf_counter()
    sim = Simulator(cfg)
    m: Metrics = sim.run()
    wall = time.perf_counter() - t0
    return {
        "seed": seed,
        "wall_s": wall,
        "sv": m.safety_violations,
        "legacy_agent": m.violations_agent_attributable,
        "legacy_exo":   m.violations_exogenous_attributable,
        "def1_agent":   m.violations_def1_agent_attributable,
        "def1_exo":     m.violations_def1_exogenous_attributable,
        "def1_sum":     m.violations_def1_safety_violations,
        "completed":    m.completed_tasks,
        "steps":        m.steps,
        "wait_total":   m.total_wait_steps,
        "safe":         m.safe_wait_steps,
        "yield":        m.yield_wait_steps,
        "p_revert":     m.physics_revert_wait_steps,
        "delay":        m.delay_wait_steps,
        "deadlock":     m.deadlock_count,
        "arrival_rate": m.arrival_rate_per_step,
        "util":         m.throughput_utilization,
        "sv_events":    m.safety_violation_events,
    }


def main() -> int:
    rows: List[Dict[str, object]] = []
    for seed in (0, 1, 2):
        print(f"running seed {seed} ...", flush=True)
        rows.append(run_one(seed))

    print("\n== per-seed columns ==")
    print(f"{'seed':>4} {'wall':>7} {'sv':>4} {'legacy_a':>10} "
          f"{'legacy_x':>10} {'def1_a':>8} {'def1_x':>8} {'def1_sum':>8}  "
          f"identity? agent_zero?")
    print("-" * 110)
    all_identity = True
    all_agent_zero = True
    for r in rows:
        identity = (r["def1_exo"] == r["legacy_exo"])
        agent_zero = (r["def1_agent"] == 0)
        all_identity &= identity
        all_agent_zero &= agent_zero
        print(f"{r['seed']:4d} {r['wall_s']:7.2f} {r['sv']:4d} "
              f"{r['legacy_agent']:10d} {r['legacy_exo']:10d} "
              f"{r['def1_agent']:8d} {r['def1_exo']:8d} {r['def1_sum']:8d}  "
              f"{'Y' if identity else 'N':>9}  "
              f"{'Y' if agent_zero else 'N'}")

    print()
    print(f"identity claim (def1_exo == legacy_exo): "
          f"{'PASS' if all_identity else 'FAIL'}")
    print(f"construction claim (def1_agent == 0):     "
          f"{'PASS' if all_agent_zero else 'FAIL'}")

    # Spot-check a few other columns the audit cares about.
    print("\n== schema columns present in the live run ==")
    sample = rows[0]
    for k in ("arrival_rate", "util", "p_revert", "delay", "deadlock",
              "sv_events"):
        print(f"  {k:14s} = {sample[k]!r}")

    # Write a small CSV so downstream auditors can compare directly.
    out_csv = ROOT / "logs/audit/audit10_smoke.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\nwrote {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
