"""
Decision-table semantics regression tests.

The simulator processes per-agent decisions sequentially within step 5 of
``Simulator.step_once``: each agent writes its committed next position to
``Simulator._decided_next_positions[aid]`` immediately after deciding,
and the next agent in the sorted iteration order reads that table when
detecting imminent conflicts (``detect_imminent_conflict`` reads
``sim_state.decided_next_positions()`` first; see
``conflict_resolution/base.py``) and when computing its own A* fallback
blocked set (``priority_rules.py::_astar_fallback`` adds
``decided_next_positions`` of others to ``blocked``).

These tests pin two invariants:
  1. End-to-end: when two agents contend for the same cell, exactly one
     ends up at the contested cell after one step.
  2. Probe: when the loser's A* fallback fires, the contested cell
     appears in the ``blocked`` set passed to the local planner.
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from ha_lmapf.core.types import AgentState, SimConfig, Task
from ha_lmapf.local_tier.local_planner import AStarLocalPlanner
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def map5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


@pytest.fixture
def map5x5_with_walls(tmp_path):
    """5x5 grid with walls at (2,4) and (4,4) so an agent at (3,4)
    has only the contested cell (3,3) and out-of-bounds (3,5) as
    geometric neighbors — all side-step candidates fail.
    """
    p = tmp_path / "5x5_walls.map"
    rows = [
        ".....",  # 0
        ".....",  # 1
        "....@",  # 2  wall at (2,4)
        ".....",  # 3
        "....@",  # 4  wall at (4,4)
    ]
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + "\n".join(rows) + "\n")
    return str(p)


def _make_two_agent_sim(map_path: str) -> Simulator:
    """Build a 2-agent simulator with agents pre-positioned and assigned
    goals such that both want to move to ``(3, 3)`` on the next step.
    Uses ``communication_mode='priority'`` to exercise the
    PriorityRulesResolver path.
    """
    cfg = SimConfig(
        map_path=map_path,
        seed=0,
        steps=1,
        num_agents=2,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        # 1s budget so the (intentional) two-agents-want-same-cell
        # contention does not spend the full paper-aligned 10s budget.
        solver_timeout_s=1.0,
        replan_every=100,
        horizon=10,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="one_shot",  # keep tasks static for the single tick
    )
    sim = Simulator(cfg)

    # Override the auto-placed agents and tasks to a deterministic geometry.
    sim.agents = {
        0: AgentState(agent_id=0, pos=(3, 2), goal=(3, 3), task_id="t0"),
        1: AgentState(agent_id=1, pos=(3, 4), goal=(3, 3), task_id="t1"),
    }
    # mark_task_assigned-style bookkeeping
    sim._task_by_id = {
        "t0": Task(task_id="t0", start=(-1, -1), goal=(3, 3), release_step=0),
        "t1": Task(task_id="t1", start=(-1, -1), goal=(3, 3), release_step=0),
    }
    sim.tasks = list(sim._task_by_id.values())
    sim.open_tasks = []
    sim._pending_tasks = []
    # Re-instantiate controllers now that the agent set has changed.
    from ha_lmapf.local_tier.agent_controller import AgentController
    sim.controllers = {
        aid: AgentController(
            agent_id=aid,
            local_planner=sim.local_planner,
            conflict_resolver=sim.conflict_solver,
            fov_radius=int(cfg.fov_radius),
            safety_radius=int(cfg.safety_radius),
            hard_safety=True,
            fallback_wait_limit=int(cfg.fallback_wait_limit),
        )
        for aid in sim.agents
    }
    return sim


# ---------------------------------------------------------------------------
# Scenario 1: open grid, 2 agents contend for (3, 3) — exactly one wins.
# ---------------------------------------------------------------------------


def test_only_one_agent_takes_contested_cell(map5x5):
    sim = _make_two_agent_sim(map5x5)

    sim.step_once()

    new_positions = [a.pos for a in sim.agents.values()]
    contested = [p for p in new_positions if p == (3, 3)]
    assert len(contested) == 1, (
        f"Expected exactly one agent at (3,3) after step_once; "
        f"got positions {new_positions}"
    )
    # The other agent must NOT be at (3, 3) — either it stayed put (Safe
    # Wait) or it side-stepped to a non-contested cell.
    others = [p for p in new_positions if p != (3, 3)]
    assert len(others) == 1


# ---------------------------------------------------------------------------
# Scenario 2: probe — winner's claim is in the loser's decision-table view.
# ---------------------------------------------------------------------------


def test_loser_sees_winner_claim_in_decision_table(map5x5, monkeypatch):
    """Sequential semantics: agents are processed in sorted ``aid`` order.
    Agent 0 (winner — lower id wins the priority tie) decides first and
    writes its next position into ``_decided_next_positions``.  Agent 1
    (loser) decides next; when it asks the resolver to handle the
    imminent conflict, the resolver must see (3, 3) in
    ``sim_state.decided_next_positions()``.  Probe by wrapping the
    resolver's ``resolve`` and capturing what each call sees.
    """
    sim = _make_two_agent_sim(map5x5)

    # Capture (agent_id, snapshot of decided_next_positions, kwargs) per call.
    captured: List[dict] = []
    resolver = sim.conflict_solver
    orig_resolve = resolver.resolve

    def probe(agent_id, desired_cell, sim_state, observation, rng=None,
              forbidden=None, local_planner=None, **kwargs):
        captured.append({
            "agent_id": agent_id,
            "desired_cell": desired_cell,
            "decided_at_call": dict(sim_state.decided_next_positions()),
            "forbidden": set(forbidden) if forbidden else set(),
        })
        return orig_resolve(
            agent_id, desired_cell, sim_state, observation, rng=rng,
            forbidden=forbidden, local_planner=local_planner, **kwargs,
        )

    monkeypatch.setattr(resolver, "resolve", probe)
    sim.step_once()

    # The loser's resolve must have been invoked with (3, 3) already in
    # the decision table — that is the sequential-write invariant we are
    # protecting.
    loser_calls = [c for c in captured if c["agent_id"] == 1]
    assert loser_calls, "PriorityRulesResolver.resolve was never called for the loser"
    assert any(
        (3, 3) in c["decided_at_call"].values()
        for c in loser_calls
    ), (
        f"Loser never observed (3,3) in decided_next_positions during resolve. "
        f"Captured calls: {captured}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: walled-in loser → A* fallback fires; (3,3) in blocked.
# ---------------------------------------------------------------------------


def test_loser_astar_fallback_blocked_set_includes_contested(
    map5x5_with_walls, monkeypatch,
):
    """When the loser is geometrically pinned (walls block UP/DOWN, OOB
    blocks RIGHT, contested cell blocks LEFT), ``_safe_side_step``
    returns ``None`` and ``_astar_fallback`` runs.  The blocked set
    passed to ``AStarLocalPlanner.plan`` must include the contested
    cell (3, 3) via the resolver's ``decided_next_positions`` plumb.
    """
    sim = _make_two_agent_sim(map5x5_with_walls)

    captured: List[Tuple[Tuple[int, int], set]] = []
    orig_plan = AStarLocalPlanner.plan

    def probe_plan(self, env, start, goal, blocked, guidance_cells=None):
        captured.append((start, set(blocked)))
        return orig_plan(self, env, start, goal, blocked, guidance_cells=guidance_cells)

    monkeypatch.setattr(AStarLocalPlanner, "plan", probe_plan)
    sim.step_once()

    # Among all A* calls during this tick, at least one must come from
    # the loser at (3, 4) and include the contested cell (3, 3) in its
    # blocked set.
    loser_calls = [(s, b) for s, b in captured if s == (3, 4)]
    assert loser_calls, (
        f"AStarLocalPlanner.plan was never invoked from the loser's "
        f"position (3, 4); captured starts: {[s for s, _ in captured]}"
    )
    assert any((3, 3) in b for _, b in loser_calls), (
        f"Loser's A* fallback ran but (3, 3) was missing from its blocked "
        f"set.  Captured (start, blocked) pairs from (3,4): {loser_calls}"
    )

    # And the winner must indeed have committed to (3, 3).
    winner_pos = sim.agents[0].pos
    assert winner_pos == (3, 3), (
        f"Winner did not take (3, 3); got {winner_pos}.  Loser geometry "
        f"may be too restrictive."
    )
