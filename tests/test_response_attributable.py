"""Resume-prompt-3 acceptance tests: Def-1 response-attributable bucket.

Mixes two test styles:

* Scripted unit tests that drive
  ``Simulator._detect_collisions_and_near_misses`` directly with hand-
  built ``prev_pos`` / ``new_pos`` / ``humans_pre_move`` / ``humans_at_decision``
  snapshots and a pre-seeded ``_encroached_last_tick`` set.  These pin
  the response branch's classifier ordering and the d_new=0 / d_new>0
  uniformity under response (no destination split).

* Real-fixture smoke tests (3 seeds × the audit-10 §3 setup) that
  confirm the bucket stays at 0 under True and populates non-trivially
  under False on emergent encroachments.

A single multi-tick integration test (``test_response_bucket_clears_
after_one_tick``) confirms the one-tick-deep memory by mirroring the
end-of-step_once promotion (the same two lines the simulator runs)
in the test, then re-driving the classifier with the empty memory
state and asserting the next violation routes to agent/exogenous,
not response.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from ha_lmapf.core.types import AgentState, HumanState, SimConfig
from ha_lmapf.simulation.simulator import Simulator


REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_MAP = str(REPO_ROOT / "data" / "maps" / "empty-16-16.map")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def map5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _make_sim(
    map_path: str, fov_radius: int, safety_radius: int,
    humans_block_on_agent_cells: bool = True,
) -> Simulator:
    cfg = SimConfig(
        map_path=map_path, seed=0, steps=1,
        num_agents=0, num_humans=0,
        fov_radius=fov_radius, safety_radius=safety_radius,
        global_solver="cbs", replan_every=1, horizon=1,
        human_model="random_walk", mode="one_shot",
        humans_block_on_agent_cells=humans_block_on_agent_cells,
    )
    return Simulator(cfg)


def _smoke_config(*, humans_block: bool, seed: int = 0) -> SimConfig:
    return SimConfig(
        map_path=SMOKE_MAP,
        seed=seed, steps=300,
        num_agents=4, num_humans=5,
        fov_radius=2, safety_radius=1,
        human_model="random_walk",
        mode="lifelong",
        task_allocator="congestion_avoidance",
        global_solver="cbs",
        hard_safety=True,
        humans_block_on_agent_cells=humans_block,
    )


# ---------------------------------------------------------------------------
# 1. True regime — response bucket stays at zero.
# ---------------------------------------------------------------------------


def test_true_regime_response_bucket_stays_zero():
    """Encroachment is structurally impossible under True (humans
    cannot enter agent cells), so ``_encroached_last_tick`` is empty
    forever and the response branch never fires."""
    for seed in (0, 1, 2):
        cfg = _smoke_config(humans_block=True, seed=seed)
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)
        assert m.violations_def1_response_attributable == 0, (
            f"seed {seed}: True-regime run produced "
            f"{m.violations_def1_response_attributable} response-"
            f"attributable pairs; the bucket must be 0 in True."
        )


# ---------------------------------------------------------------------------
# 2. False regime — response bucket populates.
# ---------------------------------------------------------------------------


def test_false_regime_response_bucket_populates():
    """On the audit-10 §3 fixture every committed seed produces at
    least one encroachment whose follow-up tick lands a violation
    pair on the same agent, routing to response."""
    counts: Dict[int, int] = {}
    for seed in (0, 1, 2):
        cfg = _smoke_config(humans_block=False, seed=seed)
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)
        counts[seed] = int(m.violations_def1_response_attributable)
    assert any(v > 0 for v in counts.values()), (
        f"No response-attributable pairs on any seed: {counts}.  "
        f"Either the memory promotion never fires or the classifier "
        f"branch is not consulting ``_encroached_last_tick``."
    )


# ---------------------------------------------------------------------------
# 3. Response takes priority over agent-attributable.
# ---------------------------------------------------------------------------


def test_response_attribution_takes_priority_over_agent(map5x5):
    """Geometry that the prompt-2 wiring would route to
    ``violations_def1_agent_attributable``, with the same agent
    pre-tagged in ``_encroached_last_tick``, must route to
    response instead.

    Geometry: agent makes a 2-cell hop (legal at this layer --
    ``_detect_collisions_and_near_misses`` does not check
    adjacency), so the audit-06 §5 single-step bound on FoV
    redundancy is sidestepped:

        s_i(t)   = (0, 0)    pre-move human h' = (3, 0)
        s_i(t+1) = (2, 0)
        L1(s_i(t),   h')   = 3 > r_safe=1   ok clause (a)
        L1(s_i(t+1), h')   = 1 <= r_safe=1  ok clause (b)
        L1(s_i(t),   h')   = 3 <= r_fov=3   observed
    """
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (2, 0)}
    pre = {0: HumanState(human_id=0, pos=(3, 0))}
    post = {0: HumanState(human_id=0, pos=(3, 0))}

    # Agent 0 was encroached at the previous tick.
    sim._encroached_last_tick = {0}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_def1_safety_violations == 1
    assert m.violations_def1_response_attributable == 1, (
        f"Encroached agent's violation pair must route to response; "
        f"got response={m.violations_def1_response_attributable}"
    )
    # Agent-attributable would have been the prompt-2 verdict --
    # confirm response took priority.
    assert m.violations_def1_agent_attributable == 0
    assert m.violations_def1_agent_attributable_dgt0 == 0
    assert m.violations_def1_exogenous_attributable == 0


def test_response_attribution_takes_priority_control(map5x5):
    """Control: same geometry without the encroachment memory must
    route to agent-attributable, confirming the takeover test above
    is meaningfully comparing two branches."""
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (2, 0)}
    pre = {0: HumanState(human_id=0, pos=(3, 0))}
    post = {0: HumanState(human_id=0, pos=(3, 0))}

    assert sim._encroached_last_tick == set()  # control: empty memory

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_def1_response_attributable == 0
    assert m.violations_def1_agent_attributable == 1
    # And the d0/dgt0 split per prompt 2 fires for the non-response path.
    assert m.violations_def1_agent_attributable_dgt0 == 1


# ---------------------------------------------------------------------------
# 4. Response persists under continued distance-0.
# ---------------------------------------------------------------------------


def test_response_attribution_persists_under_continued_distance_0(map5x5):
    """Encroached agent stays put (Safe Wait); the original encroacher
    is still inside ``r_safe``.  Without the response branch this
    pair would land in ``exogenous_attributable_d0`` (the agent did
    not move so def1_attr=False, and d_new=0).  With the response
    branch it lands in response -- the continued distance-0 is a
    CONSEQUENCE of the encroachment, not a new exogenous fact."""
    sim = _make_sim(map5x5, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 2))}
    sim.humans = {0: HumanState(human_id=0, pos=(2, 2))}

    prev_pos = {0: (2, 2)}
    new_pos = {0: (2, 2)}                  # Safe Wait, did not move
    pre = {0: HumanState(human_id=0, pos=(2, 2))}
    post = {0: HumanState(human_id=0, pos=(2, 2))}

    sim._encroached_last_tick = {0}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_def1_safety_violations == 1
    assert m.violations_def1_response_attributable == 1
    # NOT exogenous_d0 (the prompt-2 destination would be exo_d0
    # since agent did not move and d_new=0).
    assert m.violations_def1_exogenous_attributable_d0 == 0
    assert m.violations_def1_exogenous_attributable == 0


# ---------------------------------------------------------------------------
# 5. Memory is one tick deep — clears after the promotion.
# ---------------------------------------------------------------------------


def test_response_bucket_clears_after_one_tick(map5x5):
    """Two-stage test mirroring the end-of-step_once promotion in
    the simulator:

    Stage A: encroached agent → one violation routes to response.
    Stage B: promotion (copy then clear) sets last_tick back to
             empty.  A subsequent violation on the same agent with
             ordinary geometry routes to agent or exo, NOT response.

    The promotion code in the test is byte-identical to the two
    lines at the end of ``Simulator.step_once`` -- this test
    therefore proves the promotion gives a one-tick-deep memory,
    not a sticky tag.
    """
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (2, 0)}
    pre = {0: HumanState(human_id=0, pos=(3, 0))}
    post = {0: HumanState(human_id=0, pos=(3, 0))}

    # --- Stage A: encroached memory present, violation goes to response.
    sim._encroached_last_tick = {0}
    sim._encroached_this_tick = set()
    r_before = sim.metrics._violations_def1_response_attributable
    a_before = sim.metrics._violations_def1_agent_attributable
    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    assert (sim.metrics._violations_def1_response_attributable
            - r_before) == 1
    assert (sim.metrics._violations_def1_agent_attributable
            - a_before) == 0

    # --- Promotion: call the simulator's own method so a future
    # mutation to the promotion contract (e.g. making it sticky)
    # surfaces here.  ``_promote_encroachment_memory`` is the same
    # method ``step_once`` invokes at the end of every tick.
    sim._promote_encroachment_memory()
    assert sim._encroached_last_tick == set()

    # --- Stage B: empty memory, same geometry must route to agent.
    r_mid = sim.metrics._violations_def1_response_attributable
    a_mid = sim.metrics._violations_def1_agent_attributable
    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    assert (sim.metrics._violations_def1_response_attributable
            - r_mid) == 0, (
        "Response counter incremented after the memory was cleared; "
        "the promotion is sticky instead of one-tick-deep."
    )
    assert (sim.metrics._violations_def1_agent_attributable
            - a_mid) == 1, (
        "Stage B violation did not land in agent-attributable; "
        "the classifier's else-branch is not firing after memory "
        "cleared."
    )


# ---------------------------------------------------------------------------
# 6. Three-bucket invariant survives the response branch.
# ---------------------------------------------------------------------------


def test_three_bucket_invariant_survives_response_branch():
    """Run a False-regime episode that produces non-zero response;
    the finalize asserts (which include
    safety = agent + exo + response) must all hold."""
    cfg = _smoke_config(humans_block=False, seed=2)
    sim = Simulator(cfg)
    sim.run()
    m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)

    assert m.violations_def1_response_attributable > 0, (
        "Test fixture must produce non-zero response so the "
        "invariant is genuinely exercised."
    )
    assert (m.violations_def1_safety_violations
            == m.violations_def1_agent_attributable
            + m.violations_def1_exogenous_attributable
            + m.violations_def1_response_attributable)
    # Split sums (prompt-2 invariants) still hold on the agent
    # and exogenous buckets even after the response branch
    # siphoned some pairs away.
    assert (m.violations_def1_agent_attributable
            == m.violations_def1_agent_attributable_d0
            + m.violations_def1_agent_attributable_dgt0)
    assert (m.violations_def1_exogenous_attributable
            == m.violations_def1_exogenous_attributable_d0
            + m.violations_def1_exogenous_attributable_dgt0)


# ===========================================================================
# Resume-prompt-5 STAGE 2 — predicted-encroachment memory extension
# ===========================================================================
#
# These tests cover the classifier consuming the new
# ``_predicted_encroached_this_tick`` set (populated by the γ controller
# in stage 3) and the end-of-tick clearing contract.  They bypass the
# controller by writing the predicted set directly.


def test_predicted_encroached_routes_to_response(map5x5):
    """An agent in ``_predicted_encroached_this_tick`` (but NOT in
    ``_encroached_last_tick``) whose move would otherwise be
    agent-attributable must route to response.  Same geometry as the
    prompt-3 realized-takeover test, but driven through the predicted
    memory."""
    sim = _make_sim(map5x5, fov_radius=3, safety_radius=1,
                    humans_block_on_agent_cells=False)
    sim.agents = {0: AgentState(agent_id=0, pos=(2, 0))}
    sim.humans = {0: HumanState(human_id=0, pos=(3, 0))}

    prev_pos = {0: (0, 0)}
    new_pos = {0: (2, 0)}
    pre = {0: HumanState(human_id=0, pos=(3, 0))}
    post = {0: HumanState(human_id=0, pos=(3, 0))}

    # Predicted (not realized) encroachment on agent 0 this tick.
    assert sim._encroached_last_tick == set()
    sim._predicted_encroached_this_tick = {0}

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)

    assert m.violations_def1_safety_violations == 1
    assert m.violations_def1_response_attributable == 1, (
        "Predicted-encroached agent's violation must route to response."
    )
    assert m.violations_def1_agent_attributable == 0
    assert m.violations_def1_exogenous_attributable == 0


def test_both_memories_clear_at_end_of_tick():
    """Populate BOTH realized-this-tick and predicted-this-tick;
    after promotion ``_encroached_last_tick`` reflects the realized
    set (existing behavior) and the predicted set is empty."""
    cfg = SimConfig(
        map_path=SMOKE_MAP, seed=0, steps=1,
        num_agents=0, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs", replan_every=1, horizon=1,
        human_model="random_walk", mode="one_shot",
        humans_block_on_agent_cells=False,
    )
    sim = Simulator(cfg)
    sim._encroached_this_tick = {2}
    sim._predicted_encroached_this_tick = {5}

    sim._promote_encroachment_memory()

    assert sim._encroached_last_tick == {2}, (
        "Realized-this-tick must promote into last_tick."
    )
    assert sim._encroached_this_tick == set()
    assert sim._predicted_encroached_this_tick == set(), (
        "Predicted set must be cleared at end of tick."
    )


def test_predicted_alone_is_not_in_last_tick():
    """The predicted set is a single-tick tag: it must NOT carry over
    into the next tick's ``_encroached_last_tick``."""
    cfg = SimConfig(
        map_path=SMOKE_MAP, seed=0, steps=1,
        num_agents=0, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs", replan_every=1, horizon=1,
        human_model="random_walk", mode="one_shot",
        humans_block_on_agent_cells=False,
    )
    sim = Simulator(cfg)
    sim._encroached_this_tick = set()
    sim._predicted_encroached_this_tick = {3}

    sim._promote_encroachment_memory()

    assert 3 not in sim._encroached_last_tick, (
        "Predicted encroachment must not carry over to next tick's "
        "last_tick; each tick re-derives prediction."
    )
    assert sim._encroached_last_tick == set()
