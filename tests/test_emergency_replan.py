"""
Tests for the paper Section 4.4 emergency replan trigger (eta_w).

The trigger fires an off-period global replan when the fraction of
controlled agents whose committed action the previous tick was a Safe
Wait exceeds ``config.eta_w`` (default 0.20), provided at least
``config.replan_min_gap`` ticks have elapsed since the last replan.

These tests exercise:
  1. The trigger predicate ``RollingHorizonPlanner._eta_w_trigger`` in
     isolation (pure logic; no solver, no humans).
  2. End-to-end: a Simulator with ``replan_every`` set deliberately huge
     so periodic replans cannot fire mid-test, with Safe-Wait flags
     manually pinned between ``step_once`` calls.  The test asserts the
     ``emergency_replans_eta_w`` counter increments off-period.

The Safe-Wait flag is per-tick (``AgentState.last_action_was_safe_wait``)
and is reset by ``AgentController.decide_action`` at the top of every
tick, so each test fixes the flags *between* ``step_once`` invocations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

import pytest

from ha_lmapf.core.types import AgentState, SimConfig
from ha_lmapf.global_tier.rolling_horizon import RollingHorizonPlanner
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def map5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


@dataclass
class _FakeState:
    """Minimal SimStateView surface for ``_eta_w_trigger``."""
    agents: Dict[int, AgentState]
    step: int = 0


def _agents_with_safe_wait(n_total: int, n_safe_wait: int) -> Dict[int, AgentState]:
    out: Dict[int, AgentState] = {}
    for i in range(n_total):
        out[i] = AgentState(
            agent_id=i,
            pos=(0, i),
            last_action_was_safe_wait=(i < n_safe_wait),
        )
    return out


# ---------------------------------------------------------------------------
# Unit tests — the trigger predicate in isolation
# ---------------------------------------------------------------------------


def _make_planner(eta_w: float = 0.20, replan_min_gap: int = 3) -> RollingHorizonPlanner:
    p = RollingHorizonPlanner(
        horizon=10,
        replan_every=100,
        solver_name="cbs",
        eta_w=eta_w,
        replan_min_gap=replan_min_gap,
    )
    # Pretend the previous replan was at step 0 and produced useful paths.
    p.last_replan_step = 0
    p._last_replan_useful = True
    return p


def test_eta_w_fires_when_fraction_exceeds_threshold_and_gap_satisfied():
    planner = _make_planner(eta_w=0.20, replan_min_gap=3)
    state = _FakeState(agents=_agents_with_safe_wait(4, 2), step=5)
    # 2/4 = 50% > 20%; gap = 5 - 0 = 5 >= 3
    assert planner._eta_w_trigger(state, cur_step=5) is True


def test_eta_w_does_not_fire_when_gap_too_small():
    planner = _make_planner(eta_w=0.20, replan_min_gap=3)
    state = _FakeState(agents=_agents_with_safe_wait(4, 4), step=2)
    # Fraction = 100% but gap = 2 < replan_min_gap = 3
    assert planner._eta_w_trigger(state, cur_step=2) is False


def test_eta_w_does_not_fire_when_fraction_at_or_below_threshold():
    planner = _make_planner(eta_w=0.25, replan_min_gap=3)
    # 1/4 = 25%, threshold = 0.25 → strict ">" must be False
    state = _FakeState(agents=_agents_with_safe_wait(4, 1), step=10)
    assert planner._eta_w_trigger(state, cur_step=10) is False


def test_eta_w_does_not_fire_when_no_agents():
    planner = _make_planner()
    state = _FakeState(agents={}, step=10)
    assert planner._eta_w_trigger(state, cur_step=10) is False


def test_eta_w_blocked_when_last_replan_was_useless():
    """Guard: if the previous replan produced all-WAIT paths (e.g. the
    solver binary is missing) we suppress eta_w to avoid feedback loops.
    """
    planner = _make_planner(eta_w=0.20, replan_min_gap=3)
    planner._last_replan_useful = False
    state = _FakeState(agents=_agents_with_safe_wait(4, 4), step=10)
    assert planner._eta_w_trigger(state, cur_step=10) is False


def test_eta_w_zero_disables_trigger():
    planner = _make_planner(eta_w=0.0, replan_min_gap=3)
    state = _FakeState(agents=_agents_with_safe_wait(4, 4), step=10)
    assert planner._eta_w_trigger(state, cur_step=10) is False


# ---------------------------------------------------------------------------
# End-to-end test — emergency_replans_eta_w increments off-period
# ---------------------------------------------------------------------------


def test_eta_w_fires_off_period_in_full_simulator(map5x5):
    """End-to-end: the simulator's RollingHorizonPlanner must fire an
    *off-period* replan when the Safe-Wait fraction exceeds eta_w.

    Setup: ``replan_every = 100`` so periodic replans fire only at t=0
    within a 10-step window.  We pin the Safe-Wait flags on 2 of 4
    agents between every tick (after the controller's per-tick reset).
    The expected timeline is:

        tick 0: periodic replan (last_replan_step=0)
        tick 1, 2: gap < replan_min_gap=3  → eta_w blocked
        tick 3: gap = 3, frac = 0.5 > 0.20 → eta_w FIRES (off-period)
        tick 4, 5: gap < 3 again, blocked
        tick 6: eta_w fires again, etc.

    We assert the counter is at least 1 over 10 ticks.
    """
    cfg = SimConfig(
        map_path=map5x5,
        seed=0,
        steps=10,
        num_agents=4,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=100,
        horizon=20,
        eta_w=0.20,
        replan_min_gap=3,
        mode="lifelong",
        human_model="random_walk",
    )
    sim = Simulator(cfg)

    # tick 0: let the periodic replan fire naturally.
    sim.step_once()
    assert sim.global_planner.last_replan_step == 0
    assert sim.global_planner.emergency_replans_eta_w == 0

    # The CBS Python fallback in this minimal configuration produces
    # all-WAIT paths, which the planner's feedback-loop guard
    # (``_last_replan_useful``) interprets as "solver broken" and uses to
    # suppress the eta_w trigger.  This test is about the trigger logic,
    # not the solver, so we keep ``_last_replan_useful = True`` from here
    # on.  The full-solver path is exercised by tests/test_theorem1_stress.
    for _ in range(9):
        sim.global_planner._last_replan_useful = True
        # Pin 50% of agents to Safe Wait at the start of the next tick.
        # The decide loop will reset these mid-step — that's fine; the
        # planner reads them at step 3 (maybe_global_replan), before the
        # decide loop runs.
        for aid in (0, 1):
            sim.agents[aid].last_action_was_safe_wait = True
        sim.step_once()

    assert sim.global_planner.emergency_replans_eta_w >= 1, (
        f"Expected the eta_w trigger to fire at least once off-period. "
        f"counter={sim.global_planner.emergency_replans_eta_w}, "
        f"last_replan_step={sim.global_planner.last_replan_step}, "
        f"sim.step={sim.step}"
    )

    # Sanity: no spurious periodic replans fired (replan_every=100, only
    # tick 0 is periodic).  So the only legitimate fires beyond t=0 are
    # eta_w (or the pre-existing exhaustion / safety-wait emergency
    # triggers, which need stale-global-plan / safety-wait sets that we
    # are not touching here).  Hence emergency_replans_eta_w must equal
    # the number of off-period fires we observed.
    assert sim.global_planner.last_replan_step >= 3


def test_eta_w_does_not_fire_if_flags_never_set(map5x5):
    """Negative control: with no Safe-Wait flags set anywhere, eta_w
    must never fire (counter stays at 0)."""
    cfg = SimConfig(
        map_path=map5x5,
        seed=0,
        steps=10,
        num_agents=4,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=100,
        horizon=20,
        eta_w=0.20,
        replan_min_gap=3,
        mode="lifelong",
        human_model="random_walk",
    )
    sim = Simulator(cfg)
    for _ in range(10):
        sim.step_once()
    assert sim.global_planner.emergency_replans_eta_w == 0
