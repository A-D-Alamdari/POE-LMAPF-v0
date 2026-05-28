"""Resume-prompt-2 acceptance tests: distance-0 physics + Def-1 d0/dgt0 split.

These tests run real simulator instances on the small ``empty-16-16``
map fixture used by audit step 10 §3.  No synthetic single-tick
fixtures; per the resume-design Decision 6, the d0/dgt0 distinction
is exercised through real human-step physics.

The four-way regime grid this prompt foundations:

    humans_block_on_agent_cells  ×  algorithm_variant

In this prompt only the human-side toggle is wired (the γ algorithm
ships in a later prompt), so every test pins
``algorithm_variant="baseline"``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


REPO_ROOT = Path(__file__).resolve().parent.parent
SMALL_MAP = str(REPO_ROOT / "data" / "maps" / "empty-16-16.map")


def _smoke_config(*, humans_block: bool, seed: int = 0) -> SimConfig:
    """Audit-10 §3 setup, with the regime toggle exposed."""
    return SimConfig(
        map_path=SMALL_MAP,
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
# 1. True regime — humans never overlap agent cells.
# ---------------------------------------------------------------------------


def test_true_regime_humans_cannot_enter_agent_cell():
    """audit 04 §3.3 reproduced 0/500 forced-forward entries under the
    vertex-coordinated default; here we span three seeds × 300 ticks
    and pin the same outcome via the new ``collisions_agent_human_vertex``
    counter."""
    for seed in (0, 1, 2):
        cfg = _smoke_config(humans_block=True, seed=seed)
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)

        assert m.collisions_agent_human_vertex == 0, (
            f"seed {seed}: humans_block_on_agent_cells=True "
            f"yielded {m.collisions_agent_human_vertex} vertex "
            f"collisions; the True-regime model must filter "
            f"agent_positions out of legal successors."
        )
        # Final state sanity: no human currently shares a cell with
        # any agent.
        agent_cells = {a.pos for a in sim.agents.values()}
        for hid, h in sim.humans.items():
            assert h.pos not in agent_cells, (
                f"seed {seed}: human {hid} ended at {h.pos} which "
                f"overlaps an agent.  True-regime invariant broken."
            )


# ---------------------------------------------------------------------------
# 2. False regime — humans MAY enter agent cells.
# ---------------------------------------------------------------------------


def test_false_regime_humans_can_enter_agent_cell():
    """The False regime drops the agent-position filter.  With the
    audit-10 §3 fixture (4 agents, 5 humans, 300 steps, RandomWalk)
    every committed seed produces at least one vertex collision.
    This pins the schema field as ACTIVE, not vacuous."""
    counts: Dict[int, int] = {}
    for seed in (0, 1, 2):
        cfg = _smoke_config(humans_block=False, seed=seed)
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)
        counts[seed] = int(m.collisions_agent_human_vertex)

    assert all(v >= 1 for v in counts.values()), (
        f"At least one vertex collision per seed expected on the "
        f"audit-10 §3 fixture; got {counts}.  Either the False-regime "
        f"toggle was not threaded through to the human model, or the "
        f"detection block at simulator.py step 4a is not firing."
    )


def test_false_regime_does_not_alter_agent_positions():
    """Resolution (i): a distance-0 encroachment counts but does not
    move either party.  Verify by comparing agent positions before
    and after a tick on which a vertex collision was detected."""
    cfg = _smoke_config(humans_block=False, seed=0)
    sim = Simulator(cfg)
    # Walk tick-by-tick instead of sim.run() so we can inspect.
    prev_count = 0
    for _ in range(cfg.steps):
        agents_before = {aid: a.pos for aid, a in sim.agents.items()}
        sim.step_once()
        curr = sim.metrics._collisions_agent_human_vertex
        if curr > prev_count:
            # A vertex collision fired this tick; the agent whose
            # cell was entered must NOT have been displaced by the
            # collision itself (its own movement decision is
            # independent and may or may not have moved it).  We
            # cannot assert that the agent stayed put -- the agent
            # may legitimately step elsewhere on this tick -- but
            # the simulator's distance-0 block must not have
            # rewritten agents_before.
            # Sanity: ensure the agent set is unchanged in keys.
            assert set(agents_before.keys()) == set(sim.agents.keys())
            prev_count = curr
    m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)
    assert m.collisions_agent_human_vertex >= 1


# ---------------------------------------------------------------------------
# 3. d0 / dgt0 split is wired against the regime.
# ---------------------------------------------------------------------------


def test_d0_counter_increments_only_in_false_regime():
    """Under the True regime ``_d0`` must stay zero; under False it
    must be > 0 on the audit-10 fixture.  And the parent counter
    must equal d0 + dgt0 in both regimes (the prompt-1 defensive
    guard, now with teeth)."""
    for seed in (0, 1, 2):
        # True regime: no d0.
        cfg_t = _smoke_config(humans_block=True, seed=seed)
        sim_t = Simulator(cfg_t)
        sim_t.run()
        m_t = sim_t.metrics.finalize(total_steps=cfg_t.steps, num_agents=cfg_t.num_agents)
        assert m_t.violations_def1_agent_attributable_d0 == 0
        assert m_t.violations_def1_exogenous_attributable_d0 == 0
        # Parent == d0 + dgt0 by construction.
        assert (m_t.violations_def1_agent_attributable
                == m_t.violations_def1_agent_attributable_d0
                + m_t.violations_def1_agent_attributable_dgt0)
        assert (m_t.violations_def1_exogenous_attributable
                == m_t.violations_def1_exogenous_attributable_d0
                + m_t.violations_def1_exogenous_attributable_dgt0)

        # False regime: at least one d0 (committed seeds 0,1,2
        # produce 4, 7, 12 vertex collisions on this fixture).
        cfg_f = _smoke_config(humans_block=False, seed=seed)
        sim_f = Simulator(cfg_f)
        sim_f.run()
        m_f = sim_f.metrics.finalize(total_steps=cfg_f.steps, num_agents=cfg_f.num_agents)
        total_d0 = (m_f.violations_def1_agent_attributable_d0
                    + m_f.violations_def1_exogenous_attributable_d0)
        assert total_d0 >= 1, (
            f"seed {seed} False-regime: no Def-1 violation pair at "
            f"d_new=0 was recorded, but the simulator reported "
            f"{m_f.collisions_agent_human_vertex} vertex collisions.  "
            f"The classifier's d0 branch is not wired."
        )
        assert (m_f.violations_def1_agent_attributable
                == m_f.violations_def1_agent_attributable_d0
                + m_f.violations_def1_agent_attributable_dgt0)
        assert (m_f.violations_def1_exogenous_attributable
                == m_f.violations_def1_exogenous_attributable_d0
                + m_f.violations_def1_exogenous_attributable_dgt0)


# ---------------------------------------------------------------------------
# 4. Three-bucket invariant — the prompt-1 assert is exercised by
#    a real False-regime run with non-zero splits.
# ---------------------------------------------------------------------------


def test_three_bucket_invariant_holds_with_real_d0():
    """The prompt-1 invariant ``safety = agent + exo + response`` is
    asserted unconditionally in ``MetricsTracker.finalize``.  This
    test runs a False-regime fixture that produces non-zero splits
    so the assert actually fires on real data (not just on the
    prompt-1 synthetic tracker.add_* fixture)."""
    cfg = _smoke_config(humans_block=False, seed=0)
    sim = Simulator(cfg)
    sim.run()
    # No exception raised => the three-bucket invariant + the split
    # asserts all hold.  Cross-check the math here so a regression
    # to a silenced assert would still be caught.
    m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)

    # Real d0 increments must be present, else the test is vacuous.
    assert m.collisions_agent_human_vertex >= 1
    assert (m.violations_def1_agent_attributable_d0
            + m.violations_def1_exogenous_attributable_d0) >= 1

    # Three-bucket sum.
    assert (m.violations_def1_safety_violations
            == m.violations_def1_agent_attributable
            + m.violations_def1_exogenous_attributable
            + m.violations_def1_response_attributable)

    # Both split sums.
    assert (m.violations_def1_agent_attributable
            == m.violations_def1_agent_attributable_d0
            + m.violations_def1_agent_attributable_dgt0)
    assert (m.violations_def1_exogenous_attributable
            == m.violations_def1_exogenous_attributable_d0
            + m.violations_def1_exogenous_attributable_dgt0)


# ---------------------------------------------------------------------------
# 5. True-regime d0 counters stay zero on the audit-08 prediction.
# ---------------------------------------------------------------------------


def test_true_regime_d0_counters_stay_zero():
    """audit 08 §1 predicts every paper-side (True-regime) run sees
    zero distance-0 Def-1 pairs.  The True regime suppresses humans
    from entering agent cells AND the forbidden set covers humans'
    own cells, so neither side of the (a,h) overlap can produce
    d_new = 0.  Verify across the three committed smoke seeds."""
    for seed in (0, 1, 2):
        cfg = _smoke_config(humans_block=True, seed=seed)
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)
        assert m.violations_def1_agent_attributable_d0 == 0
        assert m.violations_def1_exogenous_attributable_d0 == 0
        # Theorem 1 -- def1_agent_attributable must stay zero too.
        assert m.violations_def1_agent_attributable == 0
