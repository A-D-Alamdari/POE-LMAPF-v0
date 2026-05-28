"""Synthetic verification for audit 03: priority tuples, forbidden-set
non-mutation, modularity claim.  No full runs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Set, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT / "src"))

from ha_lmapf.core.types import AgentState, HumanState, SimConfig
from ha_lmapf.simulation.simulator import Simulator
from ha_lmapf.local_tier.conflict_resolution.priority_rules import WaitBasedResolver
from ha_lmapf.local_tier.conflict_resolution.token_passing import TokenBasedResolver


def open_map(p: Path) -> str:
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def fresh_sim(tmp: Path) -> Simulator:
    cfg = SimConfig(
        map_path=open_map(tmp / "m.map"),
        num_agents=2, num_humans=0,
        fov_radius=2, safety_radius=1, seed=0, steps=5,
    )
    sim = Simulator(cfg)
    sim.agents = {
        0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4), task_id="t0"),
        1: AgentState(agent_id=1, pos=(2, 2), goal=(0, 0), task_id="t1",
                       wait_steps=3),
    }
    return sim


# 1. Priority tuple shape: WaitBasedResolver (priority_rules.py)
def test_wait_based_tuple(tmp):
    sim = fresh_sim(tmp)
    r = WaitBasedResolver(starvation_threshold=10, boost=50)
    t0 = r._priority(0, sim)  # dist=8 -> urgency=-8, wait=0, -id=0
    t1 = r._priority(1, sim)  # dist=4 -> urgency=-4, wait=3, -id=-1
    return (t0, t1)


# 2. Priority tuple shape: TokenBasedResolver (token_passing.py)
def test_token_based_tuple(tmp):
    sim = fresh_sim(tmp)
    r = TokenBasedResolver(fairness_k=5)
    t0 = r._priority(0, sim)
    t1 = r._priority(1, sim)
    return (t0, t1)


# 3. Forbidden-set non-mutation: pass a tagged set, call resolve(),
#    confirm the caller's set is unchanged.  Build a vertex conflict
#    so the resolver actually exercises its fallback logic.
def test_forbidden_immutability(tmp, resolver_cls):
    sim = fresh_sim(tmp)
    # Make both agents want cell (1,1) - vertex conflict via decided.
    sim._decided_next_positions = {0: (1, 1)}
    # Build a tiny forbidden set with a sentinel cell.
    forbidden: Set[Tuple[int, int]] = {(99, 99)}
    snapshot = set(forbidden)
    resolver = resolver_cls() if resolver_cls is WaitBasedResolver else resolver_cls(fairness_k=5)
    # Provide a fake observation (no humans).
    from ha_lmapf.core.types import Observation
    obs = Observation(visible_humans={}, visible_agents={}, blocked=set())
    try:
        resolver.resolve(
            agent_id=1, desired_cell=(1, 1),
            sim_state=sim, observation=obs, rng=None,
            forbidden=forbidden, local_planner=None,
        )
    except Exception as e:
        return ("crashed", type(e).__name__, str(e))
    return ("ok", forbidden == snapshot, forbidden)


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "a").mkdir(); (td / "b").mkdir()
        (td / "c").mkdir(); (td / "d").mkdir()
        wb = test_wait_based_tuple(td / "a")
        tk = test_token_based_tuple(td / "b")
        m_wb = test_forbidden_immutability(td / "c", WaitBasedResolver)
        m_tk = test_forbidden_immutability(td / "d", TokenBasedResolver)
    print("WaitBasedResolver._priority:")
    print(f"  agent 0 (dist=8, wait=0): {wb[0]}  expected (-8, 0, 0)")
    print(f"  agent 1 (dist=4, wait=3): {wb[1]}  expected (-4, 3, -1)")
    print(f"  PASS" if wb == ((-8, 0, 0), (-4, 3, -1)) else "  FAIL")
    print()
    print("TokenBasedResolver._priority:")
    print(f"  agent 0 (dist=8, wait=0): {tk[0]}  expected (-8, 0, 0)")
    print(f"  agent 1 (dist=4, wait=3): {tk[1]}  expected (-4, 3, -1)")
    print(f"  PASS" if tk == ((-8, 0, 0), (-4, 3, -1)) else "  FAIL")
    print()
    print(f"WaitBasedResolver forbidden-set immutability: {m_wb}")
    print(f"TokenBasedResolver forbidden-set immutability: {m_tk}")


if __name__ == "__main__":
    main()
