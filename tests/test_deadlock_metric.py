"""
Paper §5.7 deadlock metric — regression tests.

The simulator tracks a per-agent ``_deadlock_streak`` counter that
increments on any tick where ``pos_t == pos_{t-1}`` while the agent has
an active task assignment.  Streaks reset on movement, on fresh task
assignment, AND on becoming idle (between-task gap clears the counter).
Any agent that crosses ``SimConfig.deadlock_streak_threshold`` is
added to ``_deadlocked_agents`` (a per-run distinct-agent set); the
final ``Metrics.deadlock_count = len(_deadlocked_agents)`` ∈
[0, num_agents].

Tests T-DL-1..5 cover, in order:
  1. Normal run: no deadlock.
  2. Forced deadlock: one agent monkey-patched to never move.
  3. Between-task idle: streak is cleared on idle, agent does not
     accumulate phantom no-movement ticks during a task gap.
  4. Task transition: streak resets on fresh assignment.
  5. Multiple deadlocked agents: distinct-count increments correctly.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation import simulator as simulator_module
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def small_map(tmp_path):
    """5x5 open map (all passable cells)."""
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _cfg(map_path: str, *, threshold: int, steps: int, num_agents: int = 1) -> SimConfig:
    return SimConfig(
        map_path=map_path,
        seed=0,
        steps=steps,
        num_agents=num_agents,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=100,
        horizon=20,
        hard_safety=True,
        mode="lifelong",
        human_model="random_walk",
        task_allocator="greedy",
        deadlock_streak_threshold=threshold,
    )


def _freeze_movement(monkeypatch):
    """Monkeypatch apply_agent_action so no agent ever changes position."""
    def no_move(env, agent_state, action):
        return agent_state
    monkeypatch.setattr(simulator_module, "apply_agent_action", no_move)


# ---------------------------------------------------------------------------
# T-DL-1 — Normal run: no deadlock
# ---------------------------------------------------------------------------


def test_T_DL_1_normal_run_no_deadlock(small_map):
    """A short run that completes without any agent freezing: streak
    never accumulates past the threshold; ``deadlock_count == 0``."""
    cfg = _cfg(small_map, threshold=100, steps=20, num_agents=2)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert metrics.deadlock_count == 0


# ---------------------------------------------------------------------------
# T-DL-2 — Forced deadlock: single non-moving agent
# ---------------------------------------------------------------------------


def test_T_DL_2_forced_deadlock_single_agent(small_map, monkeypatch):
    """With ``apply_agent_action`` monkey-patched to no-op, the agent
    gets a task assignment on tick 0 (transition: streak reset to 0),
    then stalls indefinitely.  At ``threshold=3`` the streak crosses
    after enough ticks and the agent is added to ``_deadlocked_agents``,
    so the distinct-agent ``deadlock_count == 1``."""
    _freeze_movement(monkeypatch)
    cfg = _cfg(small_map, threshold=3, steps=10, num_agents=1)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert metrics.deadlock_count == 1


# ---------------------------------------------------------------------------
# T-DL-3 — Between-task idle does not count toward deadlock
# ---------------------------------------------------------------------------


def test_T_DL_3_idle_does_not_trigger_deadlock(small_map, monkeypatch):
    """An agent that sits idle (no task, no goal) for far longer than
    ``threshold`` ticks must NOT register as deadlocked.  Under
    reset-on-idle semantics the streak is cleared each tick the agent
    is idle, so the threshold can never be crossed by idle time alone.
    """
    _freeze_movement(monkeypatch)
    cfg = _cfg(small_map, threshold=5, steps=30, num_agents=1)
    sim = Simulator(cfg)
    sim.step_once()  # let task / replay buffers initialize.
    aid = next(iter(sim.agents))
    # Drain the task pool so the agent has no available reassignment.
    sim.open_tasks.clear()
    sim._pending_tasks.clear()
    # Pre-load a streak just below threshold to demonstrate the reset
    # effect; under reset-on-idle the first idle tick zeroes it.
    sim._deadlock_streak[aid] = 4
    # Force the agent idle (no task, no goal) for 20 ticks > threshold.
    for _ in range(20):
        sim.agents[aid] = replace(sim.agents[aid], task_id=None, goal=None,
                                  carrying=False)
        sim.step_once()
    # Streak must be 0 (reset on idle) and no agent should have been
    # added to the deadlocked set (no threshold crossing).
    assert sim._deadlock_streak[aid] == 0
    assert aid not in sim._deadlocked_agents
    metrics = sim.metrics.finalize(
        total_steps=sim.step,
        num_agents=len(sim.agents),
        deadlock_count=len(sim._deadlocked_agents),
    )
    assert metrics.deadlock_count == 0


# ---------------------------------------------------------------------------
# T-DL-4 — Task transition resets the streak
# ---------------------------------------------------------------------------


def test_T_DL_4_task_transition_resets_streak(small_map, monkeypatch):
    """Pre-load a streak just below threshold, then flip the agent's
    task_id to a NEW value while keeping position unchanged: the
    transition branch fires and resets streak to 0.  The agent does
    NOT cross the threshold from the prior streak's near-threshold
    accumulation."""
    _freeze_movement(monkeypatch)
    cfg = _cfg(small_map, threshold=5, steps=20, num_agents=1)
    sim = Simulator(cfg)
    sim.step_once()  # natural task assignment (streak reset by transition).
    aid = next(iter(sim.agents))
    # Pre-load streak just below threshold.
    sim._deadlock_streak[aid] = 4
    # Flip task_id to a new (non-None) value; goal kept non-None.
    new_goal = sim.agents[aid].goal if sim.agents[aid].goal is not None else (0, 0)
    sim.agents[aid] = replace(sim.agents[aid], task_id="t_forced_new", goal=new_goal)
    sim.step_once()
    # Transition branch: streak resets to 0; deadlocked set stays empty.
    assert sim._deadlock_streak[aid] == 0
    assert aid not in sim._deadlocked_agents


# ---------------------------------------------------------------------------
# T-DL-5 — Multiple deadlocked agents: distinct count increments
# ---------------------------------------------------------------------------


def test_T_DL_5_multiple_deadlocked_distinct_count(small_map, monkeypatch):
    """Two agents both stalled by monkey-patched no-movement; both
    cross the threshold; the distinct-agent ``deadlock_count == 2``."""
    _freeze_movement(monkeypatch)
    cfg = _cfg(small_map, threshold=3, steps=10, num_agents=2)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert metrics.deadlock_count == 2
