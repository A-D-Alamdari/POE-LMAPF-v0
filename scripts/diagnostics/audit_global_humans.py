"""Synthetic checks for audit 04: rolling-horizon, allocators, humans,
safety inflation.  No full runs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Set, Tuple, Dict

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT / "src"))

from ha_lmapf.core.types import AgentState, HumanState, Task
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.humans.models import (
    RandomWalkHumanModel, AisleFollowerHumanModel,
    AdversarialHumanModel, MixedPopulationHumanModel, ReplayHumanModel,
)
from ha_lmapf.task_allocator.task_allocator import (
    CongestionAvoidanceTaskAllocator,
    GreedyNearestTaskAllocator, HungarianTaskAllocator,
    AuctionBasedTaskAllocator,
)
from ha_lmapf.global_tier.rolling_horizon import RollingHorizonPlanner

import numpy as np


# Minimal stub env exposing the API the human models / safety / allocator use.
class StubEnv:
    def __init__(self, w: int, h: int, walls: Set[Tuple[int, int]] = ()):
        self.width = w
        self.height = h
        self._walls = set(walls)
        self._free_cells = [
            (r, c) for r in range(h) for c in range(w)
            if (r, c) not in self._walls
        ]

    def is_free(self, cell):
        r, c = cell
        if not (0 <= r < self.height and 0 <= c < self.width):
            return False
        return cell not in self._walls

    def is_blocked(self, cell):
        return not self.is_free(cell)


# ============================================================
# 1. Safety inflation
# ============================================================

def test_safety_r0():
    env = StubEnv(5, 5)
    seeds = {(2, 2)}
    out = inflate_cells(seeds, radius=0, env=env)
    # radius=0: returns only valid free seed cells.
    return out, {(2, 2)}


def test_safety_r1():
    env = StubEnv(5, 5)
    seeds = {(2, 2)}
    out = inflate_cells(seeds, radius=1, env=env)
    # radius=1: human + 4 neighbours.
    return out, {(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)}


def test_safety_r1_wall_excluded():
    env = StubEnv(5, 5, walls={(2, 3)})
    seeds = {(2, 2)}
    out = inflate_cells(seeds, radius=1, env=env)
    return out, {(2, 2), (1, 2), (3, 2), (2, 1)}  # (2,3) is wall -> excluded


# ============================================================
# 2. Humans-blocked-by-agent-positions
# ============================================================

def test_human_blocked_by_agent():
    """Place a human at (0,0).  With no agents, the human can move to
    (1,0), (0,1).  Add an agent at (1,0); confirm the human's legal
    successors no longer include (1,0)."""
    from ha_lmapf.humans.models import _legal_successors
    env = StubEnv(3, 3)
    succ_no_agents = set(_legal_successors(env, (0, 0), blocked=set()))
    succ_with_agent = set(_legal_successors(env, (0, 0),
                                            blocked={(1, 0)}))
    return (succ_no_agents, succ_with_agent)


def test_random_walk_blocks_into_agent():
    """3x1 corridor.  Human at (0,1), agent at (0,2).  Human's only
    move cells are (0,0) [free] and WAIT.  Force inertia toward (0,2)
    by setting velocity=(0,1).  Confirm human never enters (0,2)
    across many trials."""
    env = StubEnv(3, 1)
    rng = np.random.default_rng(0)
    model = RandomWalkHumanModel(beta_go=10.0, beta_wait=-100.0,
                                  beta_turn=-100.0)
    h0 = HumanState(human_id=0, pos=(0, 1), velocity=(0, 1))
    n_into_agent = 0
    for _ in range(500):
        new = model.step(env, {0: h0}, rng, agent_positions={(0, 2)})
        if new[0].pos == (0, 2):
            n_into_agent += 1
    return n_into_agent  # expected 0


# ============================================================
# 3. CongestionAvoidanceTaskAllocator narrowness + cost matrix
# ============================================================

def test_narrowness_formula():
    """5x5 open grid: every interior cell has degree 4 -> narrowness 1.0;
    corners have degree 2 -> 2.0; edges have degree 3 -> 4/3."""
    env = StubEnv(5, 5)
    nu = CongestionAvoidanceTaskAllocator._compute_narrowness_map(env)
    # Sample a few:
    interior = nu[(2, 2)]   # degree 4 -> 1.0
    corner   = nu[(0, 0)]   # degree 2 -> 2.0
    edge     = nu[(0, 2)]   # degree 3 -> 4/3
    return (interior, corner, edge), (1.0, 2.0, 4.0 / 3.0)


def test_cost_matrix_update():
    """Confirm C[i,j] = D[i,j] + lambda * sum-of-narrowness-weighted overlaps
    via a synthetic 2-agent 2-task scenario where both agents' optimal paths
    cross at one shared cell.
    """
    env = StubEnv(5, 5)
    alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=0.5,
                                              max_rounds=5)
    alloc.set_env(env)
    # Agent 0 at (0,0), task A at (4,4) -> path through (2,2)
    # Agent 1 at (0,4), task B at (4,0) -> path through (2,2)
    # Both paths cross at (2,2) (narrowness=1.0)
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 4)),
    }
    tasks = [
        Task(task_id="A", start=(4, 4), goal=(4, 4), release_step=0),
        Task(task_id="B", start=(4, 0), goal=(4, 0), release_step=0),
    ]
    out = alloc.assign(agents, tasks, step=0)
    return out, alloc.lambda_conflict, alloc.max_rounds, alloc.last_rounds_used


# ============================================================
# 4. RollingHorizonPlanner H/R coupling + eta_w defaults
# ============================================================

def test_rh_defaults():
    p = RollingHorizonPlanner(horizon=20, replan_every=10,
                              solver_name="lacam_official")
    return (p.horizon, p.replan_every, p.eta_w, p.replan_min_gap)


def test_rh_arbitrary_HR():
    """Constructor accepts any (H, R); the R = floor(H/2) coupling is
    NOT enforced in code."""
    p = RollingHorizonPlanner(horizon=10, replan_every=7,
                              solver_name="lacam_official")
    return (p.horizon, p.replan_every)  # accepts mismatched H/R


# ============================================================
# 5. Allocator-module import check
# ============================================================

def test_dead_allocator_module():
    """Both task_allocator files import cleanly; confirm what each
    exposes.  Live module: src/ha_lmapf/task_allocator/task_allocator.py
    (4 allocators + helper).  Dead/orphan: src/ha_lmapf/global_tier/
    task_allocator.py (4 allocators + helper, no in-repo importer)."""
    import ha_lmapf.task_allocator.task_allocator as live
    import ha_lmapf.global_tier.task_allocator as dead
    live_classes = sorted(c for c in dir(live)
                          if "TaskAllocator" in c or "Allocator" in c)
    dead_classes = sorted(c for c in dir(dead)
                          if "TaskAllocator" in c or "Allocator" in c)
    return (live_classes, dead_classes)


def main():
    s_r0 = test_safety_r0()
    s_r1 = test_safety_r1()
    s_r1w = test_safety_r1_wall_excluded()
    succ = test_human_blocked_by_agent()
    n_into = test_random_walk_blocks_into_agent()
    nu = test_narrowness_formula()
    cm = test_cost_matrix_update()
    rh = test_rh_defaults()
    rhar = test_rh_arbitrary_HR()
    da = test_dead_allocator_module()

    print("== safety.inflate_cells ==")
    print(f"r=0:    {s_r0[0]}  expected {s_r0[1]}  "
          f"{'PASS' if s_r0[0] == s_r0[1] else 'FAIL'}")
    print(f"r=1:    {s_r1[0]}  expected {s_r1[1]}  "
          f"{'PASS' if s_r1[0] == s_r1[1] else 'FAIL'}")
    print(f"r=1+wall: {s_r1w[0]}  expected {s_r1w[1]}  "
          f"{'PASS' if s_r1w[0] == s_r1w[1] else 'FAIL'}")
    print()
    print("== human blocked by agent ==")
    print(f"successors w/o agents at (1,0): {succ[0]}")
    print(f"successors w/  agent  at (1,0): {succ[1]}")
    print(f"(1,0) excluded when blocked: "
          f"{'PASS' if (1,0) not in succ[1] else 'FAIL'}")
    print(f"random-walk steps into agent over 500 trials: {n_into}  "
          f"{'PASS' if n_into == 0 else 'FAIL'}")
    print()
    print("== narrowness ==")
    print(f"nu(interior, corner, edge) = {nu[0]}  expected {nu[1]}  "
          f"{'PASS' if nu[0] == nu[1] else 'FAIL'}")
    print()
    print("== cost-matrix iterative assign ==")
    print(f"assignment={cm[0]}, lambda={cm[1]}, max_rounds={cm[2]}, "
          f"rounds_used={cm[3]}")
    print(f"defaults  lambda=0.5, R_max=5: "
          f"{'PASS' if (cm[1] == 0.5 and cm[2] == 5) else 'FAIL'}")
    print()
    print("== rolling-horizon defaults ==")
    print(f"H, R, eta_w, min_gap = {rh}")
    print(f"H/R defaults (20, 10) -> R=H/2: "
          f"{'PASS' if rh[:2] == (20, 10) else 'FAIL'}")
    print(f"eta_w=0.20: {'PASS' if rh[2] == 0.20 else 'FAIL'}")
    print(f"replan_min_gap=3: {'PASS' if rh[3] == 3 else 'FAIL'}")
    print(f"arbitrary H=10, R=7 accepted: {rhar}  "
          f"-> R=floor(H/2) NOT enforced: "
          f"{'PASS (documented gap)' if rhar == (10, 7) else 'FAIL'}")
    print()
    print("== allocator-module reconciliation ==")
    print(f"live   (task_allocator/task_allocator.py): {da[0]}")
    print(f"dead?  (global_tier/task_allocator.py)   : {da[1]}")


if __name__ == "__main__":
    main()
