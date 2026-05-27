"""
Wait-kind decomposition invariant tests.

The metrics tracker exposes three wait counters:
  * ``total_wait_steps`` — every WAIT the controller commits while the
    agent has work to do.
  * ``safe_wait_steps`` — safety-induced WAITs (no F-respecting move
    available).
  * ``yield_wait_steps`` — conflict-induced WAITs (resolver yielded).

The invariant is::

    total_wait_steps == safe_wait_steps + yield_wait_steps

asserted both via direct tracker calls and via a representative
end-to-end run.
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def test_invariant_under_direct_tracker_calls():
    tracker = MetricsTracker()
    tracker.add_wait_steps(1)
    tracker.add_safe_wait_step(1)
    tracker.add_wait_steps(2)
    tracker.add_yield_wait_step(2)
    tracker.add_wait_steps(1)
    tracker.add_safe_wait_step(1)

    m = tracker.finalize(total_steps=10, num_agents=4)
    assert m.total_wait_steps == 4
    assert m.safe_wait_steps == 2
    assert m.yield_wait_steps == 2
    assert m.total_wait_steps == m.safe_wait_steps + m.yield_wait_steps


def test_wait_fraction_is_total_over_agents_times_steps():
    tracker = MetricsTracker()
    for _ in range(7):
        tracker.add_wait_steps(1)
        tracker.add_safe_wait_step(1)

    m = tracker.finalize(total_steps=10, num_agents=2)
    # 7 wait events / (2 agents * 10 steps) = 0.35
    assert m.wait_fraction == pytest.approx(0.35)


def test_wait_fraction_zero_when_total_steps_zero():
    tracker = MetricsTracker()
    m = tracker.finalize(total_steps=0, num_agents=4)
    assert m.wait_fraction == 0.0


def test_collisions_agent_exogenous_alias_mirrors_human():
    tracker = MetricsTracker()
    tracker.add_agent_human_collision(3)
    m = tracker.finalize(total_steps=1, num_agents=1)
    assert m.collisions_agent_human == 3
    assert m.collisions_agent_exogenous == 3
    assert m.collisions_agent_exogenous == m.collisions_agent_human


@pytest.fixture
def map5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def test_invariant_holds_on_end_to_end_run(map5x5):
    """Run a small simulation that produces some yields and some safety
    waits and verify the invariant holds over the full run.
    """
    cfg = SimConfig(
        map_path=map5x5,
        seed=0,
        steps=50,
        num_agents=4,
        num_humans=2,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        # Tight CBS budget keeps this test under a couple of seconds
        # when the CBSH2-RTC binary is installed and surfaces the
        # "two agents same goal" quirk in the simulator's task
        # allocator.  Production runs use 10s per paper Section 5.1.
        solver_timeout_s=1.0,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    sim = Simulator(cfg)
    metrics = sim.run()

    assert metrics.total_wait_steps == metrics.safe_wait_steps + metrics.yield_wait_steps, (
        f"Wait-kind invariant violated: total={metrics.total_wait_steps}, "
        f"safe={metrics.safe_wait_steps}, yield={metrics.yield_wait_steps}"
    )
    # Sanity: wait_fraction is well-defined and within [0, 1].
    assert 0.0 <= metrics.wait_fraction <= 1.0
