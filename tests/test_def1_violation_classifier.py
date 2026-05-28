"""Acceptance tests for the Definition-1 (paper §3) violation classifier.

The P5 follow-up added a WAIT-counterfactual diagnostic alongside the
canonical Theorem 1 classifier; this test pins the canonical one.

Definition 1 (paper §3, agent-attributable buffer violation):
  Violation (a_i, h) at t+1 is agent-attributable iff there exists
  h' in X_t^{Phi_i} (humans observed by a_i within r_fov of s_i(t)
  at decision time t) such that:
    (a) ell_1(s_i(t),   h'_pos_at_t) >  r_safe   (pairwise safe at t)
    (b) ell_1(s_i(t+1), h'_pos_at_t) <= r_safe   (buffer-entered at t+1)
        AND s_i(t) != s_i(t+1)                    (agent moved)

The classifier is driven directly via
``Simulator._detect_collisions_and_near_misses`` with hand-built
``humans_pre_move`` / ``humans_at_decision`` snapshots so the test
isolates the rule from the local controller (which would normally
refuse to step into the buffer).
"""
from __future__ import annotations

from typing import Dict

import pytest

from ha_lmapf.core.types import AgentState, HumanState, SimConfig
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def map5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _make_sim(map_path: str, fov_radius: int, safety_radius: int) -> Simulator:
    cfg = SimConfig(
        map_path=map_path, seed=0, steps=1,
        num_agents=0, num_humans=0,
        fov_radius=fov_radius, safety_radius=safety_radius,
        global_solver="cbs", replan_every=1, horizon=1,
        human_model="random_walk", mode="one_shot",
    )
    return Simulator(cfg)


def test_def1_move_into_observed_buffer_is_agent_attributable(map5x5):
    """Canonical Definition-1 agent-attributable scenario.

    Setup: agent at (2,1) decides to step to (2,2).  Human is at
    (2,2) BOTH pre-step-4 (humans_pre_move) AND post-step-4
    (humans_at_decision) -- the human did not move this tick.
    With r_fov=2, the agent observes the human (L1=1).  With
    r_safe=1, the agent's pre-move position is exactly distance 1
    from the human, which is INSIDE the buffer.  Definition 1
    therefore does NOT classify this as agent-attributable
    (clause (a) requires pre-move safe).

    For a clean agent-attributable case we put the human at (3,2):
        s_i(t)   = (2,1)    h'_pos_pre = (3,2)   L1 = 2  > r_safe=1  ok (a)
        s_i(t+1) = (2,2)                          L1 = 1 <= r_safe=1 ok (b)
        moved: (2,1) != (2,2)                                          ok
        observed: L1((2,1),(3,2)) = 2 <= r_fov=2                       ok

    The post-move human position must produce a violation at t+1
    (so the (a_i, h) pair is in the violation set bucket (A)
    iterates).  We keep the human stationary so pre = post = (3,2)
    and the post-move violation L1((2,2),(3,2))=1 <= r_safe.
    """
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 2))}

    prev_pos: Dict[int, tuple] = {0: (2, 1)}
    new_pos: Dict[int, tuple] = {0: (2, 2)}
    humans_pre_move = {0: HumanState(human_id=0, pos=(3, 2))}
    humans_post = {0: HumanState(human_id=0, pos=(3, 2))}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, humans_post,
        humans_pre_move=humans_pre_move,
    )
    m = sim.metrics.finalize(total_steps=1)

    # The post-move violation IS detected (bucket B + bucket A both
    # iterate the same pair set).
    assert m.violations_def1_safety_violations == 1, m
    assert m.violations_def1_agent_attributable == 1, m
    assert m.violations_def1_exogenous_attributable == 0, m


def test_def1_unobserved_witness_is_exogenous(map5x5):
    """If the violating human is OUTSIDE the agent's FOV at decision
    time, Definition 1 cannot use it as the witness h' and the
    violation is exogenous-attributable.  Compare with the
    WAIT-counterfactual diagnostic, which would still label this
    agent-attributable -- the two answer different questions."""
    # r_fov=2 narrows the observed set so the human pre-move at
    # distance 3 from a_prev=(0,0) is NOT in X_t.  (Audit step 06
    # bumped fov from 1 -> 2 to satisfy the now-enforced
    # construction-safety precondition r_safe < r_fov; the human's
    # pre-move position is pushed out by one cell to keep it
    # FOV-blind.  Post-move the human is at (2,0), creating the
    # same violation pair at t+1 the original scenario exercised.)
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (1, 0)}
    pre = {0: HumanState(human_id=0, pos=(3, 0))}     # unobserved (L1=3 > fov=2)
    post = {0: HumanState(human_id=0, pos=(2, 0))}    # moves in by 1

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)
    assert m.violations_def1_safety_violations == 1, m
    # FOV-blind => Definition 1 exogenous-attributable.
    assert m.violations_def1_agent_attributable == 0, m
    assert m.violations_def1_exogenous_attributable == 1, m
    # The WAIT-counterfactual diagnostic disagrees: WAIT at (0,0)
    # would have been safe (L1=2 > r_safe=1), so bucket (B) labels
    # this agent-attributable.  This is the entire point of having
    # two classifiers -- pin the divergence.
    assert m.violations_agent_attributable == 1, m


def test_def1_pre_move_human_position_matters(map5x5):
    """Definition 1 reads the PRE-step-4 human position; the post-
    step-4 position is only used to enumerate the violation set.

    Scenario: human at (4,2) pre-step-4 (well outside the agent's
    r_fov=2 from s_i(t)=(2,1) -- L1=4 > 2).  At step 4 the human
    moves to (3,2) -- now L1=1 from a_new=(2,2) so a post-move
    violation pair exists.  Definition 1 must use the PRE-step-4
    position (4,2) which fails the FOV gate, so the violation is
    exogenous-attributable.  A buggy implementation that used the
    post-move position would observe the human at (3,2) post-step-4
    (L1=2 from a_prev), pass clauses (a) and (b), and incorrectly
    label this agent-attributable."""
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 2))}

    prev_pos = {0: (2, 1)}
    new_pos = {0: (2, 2)}
    pre = {0: HumanState(human_id=0, pos=(4, 2))}     # unobserved at t
    post = {0: HumanState(human_id=0, pos=(3, 2))}    # adjacent at t+1

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)
    assert m.violations_def1_safety_violations == 1, m
    assert m.violations_def1_agent_attributable == 0, (
        "Definition 1 must consult the PRE-step-4 human position; this "
        "test fails on a classifier that mistakenly reads post-step-4. "
        f"metrics={m}"
    )
    assert m.violations_def1_exogenous_attributable == 1, m


def test_def1_safe_wait_is_exogenous(map5x5):
    """An agent that stays put (safe-wait, s_i(t+1) == s_i(t)) can
    never be Definition-1 agent-attributable, regardless of which
    humans surround it -- clause (b) explicitly requires the agent
    to have moved."""
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 3))}

    prev_pos = {0: (2, 2)}
    new_pos = {0: (2, 2)}                              # safe-wait
    pre = {0: HumanState(human_id=0, pos=(2, 3))}
    post = {0: HumanState(human_id=0, pos=(2, 3))}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)
    assert m.violations_def1_safety_violations == 1, m
    assert m.violations_def1_agent_attributable == 0, m
    assert m.violations_def1_exogenous_attributable == 1, m


def test_def1_invariant_matches_safety_violations(map5x5):
    """``violations_def1_safety_violations`` must equal the legacy
    ``safety_violations`` whenever the def1 classifier ran -- the
    two iterate the same post-move violation-pair set.  Locked in
    by the assertion in ``MetricsTracker.finalize``."""
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {
        0: AgentState(agent_id=0, pos=(2, 2)),
        1: AgentState(agent_id=1, pos=(1, 1)),
    }
    sim.humans = {
        0: HumanState(human_id=0, pos=(3, 2)),
        1: HumanState(human_id=1, pos=(0, 1)),
    }
    prev = {0: (2, 1), 1: (1, 0)}
    new = {0: (2, 2), 1: (1, 1)}
    pre = {
        0: HumanState(human_id=0, pos=(3, 2)),
        1: HumanState(human_id=1, pos=(0, 1)),
    }
    post = dict(pre)

    sim._detect_collisions_and_near_misses(
        prev, new, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)
    assert m.violations_def1_safety_violations == m.safety_violations, m
    assert m.violations_def1_safety_violations == (
        m.violations_def1_agent_attributable
        + m.violations_def1_exogenous_attributable
    )


def test_csv_carries_def1_columns(map5x5):
    """The new fields must appear in ``MetricsTracker.csv_header()``
    and ``to_csv_row()`` in lockstep so downstream tooling sees the
    columns immediately after re-running run_paper_experiment.py."""
    from ha_lmapf.core.metrics import MetricsTracker

    tracker = MetricsTracker()
    header = tracker.csv_header()
    assert "violations_def1_agent_attributable" in header
    assert "violations_def1_exogenous_attributable" in header
    assert "violations_def1_safety_violations" in header
    # Row writer must produce a value for each header column.
    metrics = tracker.finalize(total_steps=1, num_agents=1)
    row = tracker.to_csv_row(metrics)
    assert len(row) == len(header), (
        f"to_csv_row len={len(row)} != csv_header len={len(header)}; "
        f"the two are out of sync."
    )


def test_legacy_classifier_path_skips_def1(map5x5):
    """When the caller omits ``humans_pre_move`` (legacy test-harness
    path that bypasses step_once()), the def1 block is skipped and
    only the WAIT-counterfactual diagnostic runs.  Verifies that
    existing unit tests in test_safety_classification.py keep
    working unchanged."""
    sim = _make_sim(map5x5, fov_radius=4, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(1, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (1, 0)}
    post = {0: HumanState(human_id=0, pos=(2, 0))}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post,   # humans_pre_move omitted
    )
    m = sim.metrics.finalize(total_steps=1)
    # Legacy WAIT-counterfactual classifier still runs.
    assert m.safety_violations == 1
    assert m.violations_agent_attributable == 1
    # Definition 1 stays at zero -- the block did not execute.
    assert m.violations_def1_agent_attributable == 0
    assert m.violations_def1_exogenous_attributable == 0
    assert m.violations_def1_safety_violations == 0
