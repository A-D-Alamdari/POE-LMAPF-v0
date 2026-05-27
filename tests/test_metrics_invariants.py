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


# ---------------------------------------------------------------------------
# P6 acceptance tests — metric definitions audit
# ---------------------------------------------------------------------------


class _MetricsHolder:
    """Lightweight shim that exposes a fresh ``MetricsTracker`` under
    a ``.metrics`` attribute, matching the ``sim.metrics.X`` call
    pattern used elsewhere in this file without standing up a full
    Simulator."""

    def __init__(self) -> None:
        self.metrics = MetricsTracker()


def _basic_metrics_tracker() -> _MetricsHolder:
    return _MetricsHolder()


def test_loitering_human_yields_events_below_agent_ticks(map5x5):
    """An (agent, human) pair that sits inside r_safe for many ticks
    must contribute many agent-tick counts but only one event.  The
    event-debounced counter is the right summary stat for "how often
    did the buffer get breached" while the agent-tick counter remains
    the right summary stat for "how many tick-pairs of overlap"."""
    sim = _basic_metrics_tracker()
    # Drive ten ticks of overlap on the SAME (aid=0, hid=0) pair.
    for _ in range(10):
        sim.metrics.add_safety_violation(1)
        sim.metrics.add_exogenous_attributable_violation(1)
        sim.metrics.record_violation_pair(0, 0, "exo")
        sim.metrics.close_violation_tick()
    m = sim.metrics.finalize(total_steps=10, num_agents=1)

    # Agent-tick count = 10; event count = 1 (the leading edge).
    assert m.safety_violation_agent_ticks == 10
    assert m.safety_violation_events == 1
    assert m.violations_exogenous_attributable_agent_ticks == 10
    assert m.violations_exogenous_attributable_events == 1
    assert m.safety_violations == m.safety_violation_agent_ticks


def test_distinct_events_per_pair_and_per_run(map5x5):
    """Three distinct overlap runs on the same pair count as three
    events; two simultaneous overlap pairs on distinct (aid, hid)
    keys count as two events even within the same tick."""
    sim = _basic_metrics_tracker()
    # Run 1: pair (0,0) for 2 ticks
    for _ in range(2):
        sim.metrics.add_safety_violation(1)
        sim.metrics.add_exogenous_attributable_violation(1)
        sim.metrics.record_violation_pair(0, 0, "exo")
        sim.metrics.close_violation_tick()
    # Quiet tick (pair drops out)
    sim.metrics.close_violation_tick()
    # Run 2: same pair (0,0) re-enters
    sim.metrics.add_safety_violation(1)
    sim.metrics.add_exogenous_attributable_violation(1)
    sim.metrics.record_violation_pair(0, 0, "exo")
    sim.metrics.close_violation_tick()
    # Run 3: two pairs simultaneously, one each bucket
    sim.metrics.add_safety_violation(2)
    sim.metrics.add_agent_attributable_violation(1)
    sim.metrics.add_exogenous_attributable_violation(1)
    sim.metrics.record_violation_pair(0, 0, "exo")    # still active from run 2
    sim.metrics.record_violation_pair(1, 5, "agent")  # new leading edge
    sim.metrics.close_violation_tick()
    m = sim.metrics.finalize(total_steps=5, num_agents=2)

    # Agent-ticks accumulate every tick of overlap:
    # run1 (2 ticks, 1 pair) + run2 (1 tick, 1 pair) +
    # run3 (1 tick, 2 pairs) = 2 + 1 + 2 = 5.
    assert m.safety_violation_agent_ticks == 5
    # Events: run1 leading edge (1) + run2 re-entry (1) + run3 new pair (1) = 3.
    # (Run 3's (0,0) pair was still active from run 2, so it
    # contributes a per-tick overlap but NOT a new event.)
    assert m.safety_violation_events == 3
    # Attribution split mirrors the per-tick bucket assignments.
    assert m.violations_exogenous_attributable_events == 2
    assert m.violations_agent_attributable_events == 1


def test_safety_violation_rate_per_agent_step_is_agent_count_invariant(map5x5):
    """A scenario where each agent generates the SAME per-agent
    violation behavior produces the same agent-normalized rate
    regardless of fleet size.  The legacy ``safety_violation_rate``
    scales with agent count -- demonstrably -- so the new field is
    the comparable summary stat."""
    # 1 agent x 100 ticks x 1 violation/tick = 100 violations total.
    # rate / steps              = 100 / 100  = 1.0  -> *1000 = 1000.0
    # rate / (agents * steps)   = 100 / 100  = 1.0
    sim1 = _basic_metrics_tracker()
    for _ in range(100):
        sim1.metrics.add_safety_violation(1)
        sim1.metrics.add_exogenous_attributable_violation(1)
        sim1.metrics.record_violation_pair(0, 0, "exo")
        sim1.metrics.close_violation_tick()
    m1 = sim1.metrics.finalize(total_steps=100, num_agents=1)

    # 4 agents x 100 ticks x 1 violation/agent/tick = 400 violations.
    # rate / steps              = 400 / 100  = 4.0  -> *1000 = 4000.0
    # rate / (agents * steps)   = 400 / 400  = 1.0
    sim4 = _basic_metrics_tracker()
    for t in range(100):
        for aid in range(4):
            sim4.metrics.add_safety_violation(1)
            sim4.metrics.add_exogenous_attributable_violation(1)
            sim4.metrics.record_violation_pair(aid, aid, "exo")
        sim4.metrics.close_violation_tick()
    m4 = sim4.metrics.finalize(total_steps=100, num_agents=4)

    # Legacy rate is NOT comparable (scales with fleet).
    assert m4.safety_violation_rate == pytest.approx(4.0 * m1.safety_violation_rate)
    # Agent-normalized rate IS comparable (invariant when per-agent
    # behavior is held fixed).
    assert m1.safety_violation_rate_per_agent_step == pytest.approx(1.0)
    assert m4.safety_violation_rate_per_agent_step == pytest.approx(1.0)


def test_on_task_assigned_records_agent_id(map5x5):
    """P6 fix: ``on_task_assigned`` previously wrote ``assigned_agent``
    to a non-existent dataclass field, leaving ``record.agent_id`` at
    ``None`` between assignment and completion.  The fix sets the
    documented ``agent_id`` field directly."""
    from ha_lmapf.core.metrics import MetricsTracker

    tracker = MetricsTracker()
    tracker.on_task_released("t_1", release_step=0)
    tracker.on_task_assigned("t_1", agent_id=42, step=5)

    rec = tracker._tasks["t_1"]
    assert rec.agent_id == 42, (
        f"on_task_assigned did not populate record.agent_id; got {rec.agent_id!r}"
    )
    assert rec.assigned_step == 5


def test_throughput_timeline_counts_match_completed_tasks_at_boundary(map5x5):
    """P6 fix: a task completing exactly at ``total_steps`` (boundary
    case, possible when tests / external callers feed
    ``on_task_completed`` directly) must not be silently dropped from
    the throughput timeline while ``completed_tasks`` still counts it.
    The classic symptom was timeline cumulative < completed_tasks."""
    from ha_lmapf.core.metrics import MetricsTracker

    tracker = MetricsTracker()
    tracker.on_task_released("early", release_step=0)
    tracker.on_task_completed("early", agent_id=0, step=5)        # mid-run
    tracker.on_task_released("boundary", release_step=0)
    tracker.on_task_completed("boundary", agent_id=0, step=10)    # exactly at total_steps

    m = tracker.finalize(total_steps=10, num_agents=1)

    # Both tasks must appear in the scalar count AND in the timeline.
    assert m.completed_tasks == 2
    assert len(m.throughput_timeline) == 10
    # The last entry of the cumulative timeline reflects all completed
    # tasks because the boundary task is clamped into the last bucket.
    last_cum = m.throughput_timeline[-1] * 10  # cumulative*step+1 == total
    assert int(round(last_cum)) == 2, (
        f"timeline scalar mismatch: last_cumulative={last_cum}, "
        f"completed_tasks={m.completed_tasks}, timeline={m.throughput_timeline}"
    )


def test_mean_task_completion_span_mirrors_mean_flowtime(map5x5):
    """The lifelong-friendly replacement for ``makespan`` equals
    ``mean_flowtime`` by construction (release -> completion mean
    over completed tasks)."""
    from ha_lmapf.core.metrics import MetricsTracker

    tracker = MetricsTracker()
    tracker.on_task_released("t_1", release_step=0)
    tracker.on_task_completed("t_1", agent_id=0, step=10)         # flowtime 10
    tracker.on_task_released("t_2", release_step=5)
    tracker.on_task_completed("t_2", agent_id=0, step=20)         # flowtime 15
    m = tracker.finalize(total_steps=25, num_agents=1)
    assert m.mean_task_completion_span == pytest.approx(m.mean_flowtime)
    assert m.mean_task_completion_span == pytest.approx(12.5)
