"""Audit step 02: simulator tick ordering, human-snapshot naming,
violation-classifier correctness on hand-built ticks, physics layer,
task completion, deadlock detector.

Inventory-only: no source files modified.  Single-tick synthetic checks
only (no Simulator.run, no episodes).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT / "src"))

from ha_lmapf.core.types import AgentState, HumanState, SimConfig, Metrics
from ha_lmapf.simulation.simulator import Simulator


def open_map(path: Path, w: int, h: int) -> str:
    path.write_text(f"type octile\nheight {h}\nwidth {w}\nmap\n" + ("." * w + "\n") * h)
    return str(path)


def fresh_sim(tmp: Path, fov: int = 2, safety: int = 1) -> Simulator:
    """Build a minimal Simulator wrapping the helper used by Audit 02
    synthetic ticks; agents/humans are then rewritten in place to set
    up specific scenarios."""
    m = open_map(tmp / "map.map", 7, 7)
    cfg = SimConfig(
        map_path=m, num_agents=1, num_humans=1,
        fov_radius=fov, safety_radius=safety, seed=0, steps=10,
    )
    return Simulator(cfg)


# ============================================================
# Scenario A: Def-1 AGENT-attributable.
#   Agent at (3,3) at t, moves to (3,4) at t+1.
#   One human pre-move at (3,5), still at (3,5) post-move.
#   FoV r_fov=2; safety r=1.
#   d_pre(a_prev, h_pre) = |3-3| + |3-5| = 2 > 1 (clause a)
#   d_new(a_new, h_pre)  = |3-3| + |4-5| = 1 <= 1 (clause b)
#   moved = True
#   FoV: |3-3| + |3-5| = 2 <= 2 (observed)
#   d_new(a_new, h_post) = |3-3| + |4-5| = 1 <= 1 (violation pair at t+1)
#   Expected: violations_def1_agent_attributable += 1
#             violations_def1_exogenous_attributable += 0
# ============================================================

def scenario_A(tmp: Path) -> Tuple[int, int]:
    sim = fresh_sim(tmp, fov=2, safety=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(3, 3),
                                goal=(3, 4), task_id="t0")}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 5))}
    prev_pos = {0: (3, 3)}
    new_pos = {0: (3, 4)}
    h_pre = {0: HumanState(human_id=0, pos=(3, 5))}
    h_post = {0: HumanState(human_id=0, pos=(3, 5))}
    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, h_post, humans_pre_move=h_pre,
    )
    m = sim.metrics.finalize(total_steps=1, num_agents=1)
    return (m.violations_def1_agent_attributable,
            m.violations_def1_exogenous_attributable)


# ============================================================
# Scenario B: Def-1 EXOGENOUS-attributable.
#   Same agent move (3,3) -> (3,4).
#   Human pre-move at (3,6) (unobserved at FoV=2 from (3,3)).
#   Human post-move at (3,5).
#   d_new(a_new, h_post) = |3-3| + |4-5| = 1 <= 1 (violation pair at t+1)
#   FoV: |3-3| + |3-6| = 3 > 2  → unobserved → no Def-1 witness.
#   Expected: violations_def1_agent_attributable += 0
#             violations_def1_exogenous_attributable += 1
# ============================================================

def scenario_B(tmp: Path) -> Tuple[int, int]:
    sim = fresh_sim(tmp, fov=2, safety=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(3, 3),
                                goal=(3, 4), task_id="t0")}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 5))}
    prev_pos = {0: (3, 3)}
    new_pos = {0: (3, 4)}
    h_pre = {0: HumanState(human_id=0, pos=(3, 6))}     # unobserved
    h_post = {0: HumanState(human_id=0, pos=(3, 5))}    # moves into buffer
    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, h_post, humans_pre_move=h_pre,
    )
    m = sim.metrics.finalize(total_steps=1, num_agents=1)
    return (m.violations_def1_agent_attributable,
            m.violations_def1_exogenous_attributable)


# ============================================================
# Scenario C: WAIT-counterfactual buckets on the same ticks.
#   Uses Scenario B's positions; the WAIT-classifier reads h_post (3,5)
#   and asks: "moved AND would WAIT at a_prev have avoided this?".
#   d_wait(a_prev, h_post) = |3-3| + |3-5| = 2 > 1  → yes, WAIT was safe.
#   moved=True → agent-attributable under (B).
#   Expected: violations_agent_attributable += 1
#             violations_exogenous_attributable += 0
# ============================================================

def scenario_C(tmp: Path) -> Tuple[int, int]:
    sim = fresh_sim(tmp, fov=2, safety=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(3, 3),
                                goal=(3, 4), task_id="t0")}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 5))}
    prev_pos = {0: (3, 3)}
    new_pos = {0: (3, 4)}
    h_pre = {0: HumanState(human_id=0, pos=(3, 6))}
    h_post = {0: HumanState(human_id=0, pos=(3, 5))}
    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, h_post, humans_pre_move=h_pre,
    )
    m = sim.metrics.finalize(total_steps=1, num_agents=1)
    return (m.violations_agent_attributable,
            m.violations_exogenous_attributable)


# ============================================================
# Task-completion idempotence.  Call on_task_completed twice for the
# same task_id and confirm _completed_tasks increments exactly once.
# ============================================================

def task_completion_idempotence() -> int:
    from ha_lmapf.core.metrics import MetricsTracker
    t = MetricsTracker()
    t.on_task_released("t0", release_step=0)
    t.on_task_assigned("t0", agent_id=0, step=0)
    t.on_task_completed("t0", agent_id=0, step=3)
    t.on_task_completed("t0", agent_id=0, step=4)  # spurious second call
    return t._completed_tasks


# ============================================================
# Deadlock detector: distinct-agent count.  Add the same aid twice
# to _deadlocked_agents, confirm len() == 1.
# ============================================================

def deadlock_set_distinctness(tmp: Path) -> int:
    sim = fresh_sim(tmp)
    sim._deadlocked_agents.add(7)
    sim._deadlocked_agents.add(7)
    sim._deadlocked_agents.add(7)
    return len(sim._deadlocked_agents)


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "a").mkdir()
        (td / "b").mkdir()
        (td / "c").mkdir()
        (td / "d").mkdir()
        A = scenario_A(td / "a")
        B = scenario_B(td / "b")
        C = scenario_C(td / "c")
        comp = task_completion_idempotence()
        dl = deadlock_set_distinctness(td / "d")

    print("Scenario A (Def-1 agent-attr):", A,
          "expected (1, 0); ",
          "PASS" if A == (1, 0) else "FAIL")
    print("Scenario B (Def-1 exo-attr):  ", B,
          "expected (0, 1); ",
          "PASS" if B == (0, 1) else "FAIL")
    print("Scenario C (WAIT-cf agent):   ", C,
          "expected (1, 0); ",
          "PASS" if C == (1, 0) else "FAIL")
    print("Task-completion idempotence:  ", comp,
          "expected 1; ",
          "PASS" if comp == 1 else "FAIL")
    print("Deadlock set distinctness:    ", dl,
          "expected 1; ",
          "PASS" if dl == 1 else "FAIL")


if __name__ == "__main__":
    main()
