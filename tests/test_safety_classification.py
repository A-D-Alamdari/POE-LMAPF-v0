"""
Tests for the agent-attributable / exogenous-attributable safety-violation
split introduced for paper Section 3.4 / Theorem 1.

The three scenarios cover:
  A. Agent moves into the buffer of a human it observed at decision time —
     must be classified as agent-attributable.
  B. Agent and human are far enough apart that no violation occurs — both
     attribution counts must remain zero.
  C. An unobserved human ends up inside the agent's buffer despite the
     agent's chosen action being non-violating under its decision-time
     information — must be classified as exogenous-attributable.

The detector method ``Simulator._detect_collisions_and_near_misses`` is
exercised directly with a manually-constructed ``humans_at_decision``
snapshot.  This isolates the attribution rule from the rest of the
Sense-Plan-Act loop and keeps the tests deterministic without a planner or
human motion model in the loop.

A note on scenario C parameters: with the simulator's human-first ordering
(humans move at step 4, agents sense at step 5), ``humans_at_decision`` is
the post-step-4 snapshot.  An exogenous-attributable violation therefore
requires r_fov < r_safe (so a human can sit in the band r_fov < distance <=
r_safe).  The user-provided sketch used r_fov = r_safe = 1, which is
unreachable in the actual ordering; we instead use r_fov = 1, r_safe = 2,
which preserves the spirit of the scenario.
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.types import AgentState, HumanState, SimConfig
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def map5x5(tmp_path):
    """A 5x5 fully-open MovingAI .map file."""
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _make_sim(map_path: str, fov_radius: int, safety_radius: int) -> Simulator:
    """Build a 0-agent, 0-human Simulator on ``map_path``.

    The caller manually populates ``sim.agents`` / ``sim.humans`` and passes
    explicit ``prev_pos``, ``new_pos``, and ``humans_at_decision`` to the
    detector, bypassing task allocation, planning, and human motion.
    """
    cfg = SimConfig(
        map_path=map_path,
        seed=0,
        steps=1,
        num_agents=0,
        num_humans=0,
        fov_radius=fov_radius,
        safety_radius=safety_radius,
        global_solver="cbs",
        replan_every=1,
        horizon=1,
        human_model="random_walk",
        mode="one_shot",
    )
    return Simulator(cfg)


# ---------------------------------------------------------------------------
# Scenario A — agent-attributable
# ---------------------------------------------------------------------------


def test_scenario_A_agent_attributable(map5x5):
    """Agent at (0,0) observes human at (2,0) within r_fov=4 and then moves
    to (1,0), entering the human's r_safe=1 buffer.  This is squarely the
    case Theorem 1 forbids: the agent had decision-time information that
    its chosen action would violate the buffer.
    """
    sim = _make_sim(map5x5, fov_radius=4, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (1, 0)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 0))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 1
    assert m.violations_exogenous_attributable == 0
    # Legacy invariant: sum of the two attribution counters.
    assert m.safety_violations == 1


# ---------------------------------------------------------------------------
# Scenario B — no violation
# ---------------------------------------------------------------------------


def test_scenario_B_no_violation(map5x5):
    """Agent (0,0) -> (1,0) while human is far away at (4,4).  Human is
    outside the agent's r_fov=2 sensing horizon AND well outside the
    r_safe=1 buffer of the agent's chosen new position, so neither
    attribution counter increments.
    """
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(4, 4))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (1, 0)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(4, 4))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 0
    assert m.safety_violations == 0


# ---------------------------------------------------------------------------
# Scenario C — exogenous-attributable
# ---------------------------------------------------------------------------


def test_scenario_C_exogenous_attributable(map5x5):
    """Agent stays put at (2,2).  Human at decision time is at (4,2):
    Manhattan distance 2, which is OUTSIDE the agent's r_fov=1 (so
    unobserved at decision time) but WITHIN the agent's r_safe=2 buffer of
    its post-move position (still (2,2)).  Theorem 1 attributes this to the
    exogenous agent: under the agent's decision-time information the
    chosen action (WAIT) was non-violating.
    """
    sim = _make_sim(map5x5, fov_radius=1, safety_radius=2)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(4, 2))}

    prev_pos = {0: (2, 2)}
    new_pos = {0: (2, 2)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(4, 2))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 1
    assert m.safety_violations == 1


# ---------------------------------------------------------------------------
# Sanity check on the r_safe = 0 edge case
# ---------------------------------------------------------------------------


def test_r_safe_zero_requires_cell_coincidence(map5x5):
    """When r_safe = 0 the Manhattan check ``<= 0`` reduces to "cells
    coincide".  An adjacent (but non-coincident) human must NOT trigger a
    violation."""
    sim = _make_sim(map5x5, fov_radius=4, safety_radius=0)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (1, 0)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 0))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.safety_violations == 0
    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 0


# ---------------------------------------------------------------------------
# Regression scenarios R1-R4 — lock in revised Definition 1 clauses
# ---------------------------------------------------------------------------
#
# These four tests guard the clause-(a) check introduced by commit b6d77ac
# ("fix(safety): enforce Definition 1 clause (a) in agent-attribution").
# The existing four scenarios (A/B/C/r_safe=0) all pass under both the
# pre-fix and post-fix classifiers because their geometry never exercises
# the discriminating case where the same observed witness h' lies inside
# the buffer of both s_i(t) and s_i(t+1).  R3 below is that case and would
# fail on the pre-fix code.  R1, R2, and R4's coordinates have been
# translated into the existing 5x5 fixture; all relevant L1 invariants
# are preserved.


def test_scenario_R1_move_into_observed_buffer(map5x5):
    """R1 — canonical agent-attributable move into observed buffer.

    Agent at (1,1) observes human at (1,3) (L1 = 2, within r_fov = 3,
    pairwise safe vs r_safe = 1).  Agent moves to (1,2), entering the
    human's r_safe = 1 buffer.  Both Definition 1 clauses hold for the
    sole observed witness:
      (a) L1((1,1), (1,3)) = 2 >  1 = r_safe
      (b) L1((1,2), (1,3)) = 1 <= 1 = r_safe AND (1,1) != (1,2)

    Coordinates translated from the original spec (agent (5,5)->(5,6),
    human (5,7)) into the 5x5 fixture; L1 invariants preserved.
    """
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(1, 3))}

    prev_pos = {0: (1, 1)}
    new_pos = {0: (1, 2)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(1, 3))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 1
    assert m.violations_exogenous_attributable == 0
    assert m.safety_violations == 1


def test_scenario_R2_move_out_of_buffer(map5x5):
    """R2 — agent escapes a pre-existing buffer overlap; no violation at t+1.

    At decision time t the agent at (2,2) is already inside the
    r_safe = 1 buffer of the human at (2,3) (L1 = 1).  The agent moves
    to (2,1) (L1 = 2, OUT of the buffer).  No violation pair (a_i, h)
    is emitted at t+1, so both attribution counters remain zero.

    Coordinates translated from the original spec (agent (5,5)->(5,4),
    human (5,6)) into the 5x5 fixture; L1 invariants preserved.
    """
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 1))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 3))}

    prev_pos = {0: (2, 2)}
    new_pos = {0: (2, 1)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 3))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 0
    assert m.safety_violations == 0


def test_scenario_R3_move_within_buffer_at_rsafe2(map5x5):
    """R3 — DISCRIMINATING case: agent moves between two buffer cells of
    the same observed witness at r_safe = 2.

    Agent at (0,2) observes human at (2,2) (L1 = 2, within r_fov = 3,
    but NOT pairwise safe — L1 = 2 is NOT > r_safe = 2, so clause (a)
    fails).  Agent moves to (1,2) (L1 = 1, still inside the buffer at
    t+1).  Under revised Definition 1, no observed h' satisfies BOTH
    clauses (a) and (b), so the violation is external-attributable.

    This test would FAIL on the pre-fix classifier, which omitted
    clause (a) and treated any moved-into-buffer-with-an-observed-h'
    case as agent-attributable.  See commit b6d77ac
    ("fix(safety): enforce Definition 1 clause (a) in agent-attribution").
    """
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=2)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 2))}

    prev_pos = {0: (0, 2)}
    new_pos = {0: (1, 2)}
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 2))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 1
    assert m.safety_violations == 1


# ---------------------------------------------------------------------------
# Acceptance scenarios for the WAIT-counterfactual classifier
# (replaces the FOV-gated rule that produced agent_attr ≡ 0 by
# construction).  Documented in docs/REVISION_AUDIT.md.
# ---------------------------------------------------------------------------


def test_wait_counterfactual_fov_blind_move_is_agent_attributable(map5x5):
    """A scenario where the agent moves into the buffer of a human it
    did NOT observe at decision time AND where WAIT would have left
    the agent safe vs that human.

    Under the legacy FOV-gated rule this counted as exogenous (the
    witness was outside the observed set).  Under the WAIT
    counterfactual it is agent-attributable: the agent's previous
    cell was outside the buffer, so staying would have avoided this
    pair, and the chosen MOVE put the agent inside.

    This is the scenario that proves the new classifier is not
    tautological -- the old rule never returned a nonzero agent count
    for it, but the WAIT counterfactual does."""
    # r_fov = 1 keeps the human at distance 2 outside the agent's
    # observation set, exercising the old rule's blind spot.
    sim = _make_sim(map5x5, fov_radius=1, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 0))}

    prev_pos = {0: (0, 0)}            # WAIT-safe: L1((0,0),(2,0))=2 > 1
    new_pos  = {0: (1, 0)}            # violates: L1((1,0),(2,0))=1 <= 1
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 0))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 1
    assert m.violations_exogenous_attributable == 0
    assert m.safety_violations == 1


def test_wait_counterfactual_unavoidable_overlap_is_exogenous(map5x5):
    """A scenario where the human's post-step-4 position makes every
    action -- including WAIT -- a buffer violation for the agent.
    The classifier must attribute this to the exogenous bucket and
    leave agent_attributable at zero."""
    # Human ends the human-motion phase at the agent's own cell, so
    # WAIT (a_new == a_prev == (2,2)) is L1=0 from the human, and
    # every neighbour cell is also within r_safe=1.  The agent moves
    # to (2,3); the violation pair is detected at t+1.
    sim = _make_sim(map5x5, fov_radius=4, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 3))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 2))}

    prev_pos = {0: (2, 2)}            # WAIT-unsafe: L1((2,2),(2,2))=0 <= 1
    new_pos  = {0: (2, 3)}            # violates: L1((2,3),(2,2))=1 <= 1
    humans_at_decision = {0: HumanState(human_id=0, pos=(2, 2))}

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 0
    assert m.violations_exogenous_attributable == 1
    assert m.safety_violations == 1


def test_attribution_invariant_holds_across_mixed_pairs(map5x5):
    """One agent generates two violation pairs in the same tick: one
    where WAIT would have been safe (agent-attributable) and one
    where WAIT would also have been unsafe (exogenous-attributable).
    The classifier must split them per-pair and the finalize-time
    invariant ``safety == agent_attr + exo_attr`` must hold."""
    sim = _make_sim(map5x5, fov_radius=4, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {
        # h0 at (2,3) — WAIT was safe (L1((2,1),(2,3))=2>1), agent moves to (2,2) (L1=1) => agent-attributable
        0: HumanState(human_id=0, pos=(2, 3)),
        # h1 at (2,1) — WAIT was already in buffer (L1((2,1),(2,1))=0<=1) => exogenous
        1: HumanState(human_id=1, pos=(2, 1)),
    }
    prev_pos = {0: (2, 1)}            # in h1's buffer at t
    new_pos  = {0: (2, 2)}            # in both h0's and h1's buffer at t+1
    humans_at_decision = {
        0: HumanState(human_id=0, pos=(2, 3)),
        1: HumanState(human_id=1, pos=(2, 1)),
    }

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 1, m
    assert m.violations_exogenous_attributable == 1, m
    assert m.safety_violations == 2, m


def test_scenario_R4_multi_witness_observed_drives_attribution(map5x5):
    """R4 — multi-witness mixed observation; observed witness drives
    attribution.

    Agent at (1,1) observes h1 at (1,3) (L1 = 2 = r_fov, pairwise safe
    vs r_safe = 1).  Human h2 at (4,4) is NOT observed at t
    (L1 = 6 > r_fov = 2).  Agent moves to (1,2).  At t+1, only h1 is
    inside the buffer (L1((1,2), (1,3)) = 1; L1((1,2), (4,4)) = 5),
    so n_pairs == 1.  h1 alone witnesses both Definition 1 clauses,
    yielding an agent-attributable violation.

    Verifies that the per-agent existential correctly identifies an
    observed witness even when other humans sit outside the FoV.
    Coordinates translated from the original spec (agent (5,5)->(5,6),
    h1 (5,7), h2 (10,10)) into the 5x5 fixture; L1 invariants
    preserved.
    """
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 2))}
    sim.humans = {
        0: HumanState(human_id=0, pos=(1, 3)),
        1: HumanState(human_id=1, pos=(4, 4)),
    }

    prev_pos = {0: (1, 1)}
    new_pos = {0: (1, 2)}
    humans_at_decision = {
        0: HumanState(human_id=0, pos=(1, 3)),
        1: HumanState(human_id=1, pos=(4, 4)),
    }

    sim._detect_collisions_and_near_misses(prev_pos, new_pos, humans_at_decision)
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_agent_attributable == 1
    assert m.violations_exogenous_attributable == 0
    assert m.safety_violations == 1
