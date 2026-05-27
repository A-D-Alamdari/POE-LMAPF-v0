"""Regression tests for the global no-progress metrics (paper §5.6).

``Metrics.max_global_no_progress_streak`` and
``Metrics.global_no_progress_steps`` measure population-level stalls
— ticks where every controlled agent with a same-task active
assignment failed to advance.  Distinct from the per-agent
``Metrics.deadlock_count`` (paper §5.7), which counts distinct
agents whose individual streak crossed
``SimConfig.deadlock_streak_threshold``.

These tests pin:

  T-GNP-1  All-moving run on an open map → both metrics are 0.
           Confirms the metric does not false-positive when agents
           are advancing.

  T-GNP-2  Forced all-stuck stretch via a 1-cell-wide corridor
           swap (canonical Mode-B trigger) → max streak reflects
           the stuck stretch length within tolerance.  Confirms
           the metric counts when no agent advances despite having
           active tasks.

  T-GNP-3  Idle-tick handling matches the per-agent deadlock
           semantics: a tick where every active streak is reset
           (all-idle / fresh-task) breaks the in-flight streak
           WITHOUT incrementing the total count.  Unit-tested via
           ``MetricsTracker.record_global_no_progress_tick`` so the
           contract is pinned independent of simulator behavior.

  T-GNP-4  Defensive: starting from a clean tracker, the
           three-valued contract behaves as documented.  Stuck +
           moved + stuck pattern → streak max == 1 (not 2).
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# T-GNP-1 — All-moving run → both metrics are 0
# ---------------------------------------------------------------------------


@pytest.fixture
def open_5x5(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def test_T_GNP_1_all_moving_yields_zero_metrics(open_5x5):
    """A small open map with one agent and no humans.  Agent is
    assigned tasks immediately and advances every tick.  Both
    no-progress metrics must stay 0."""
    cfg = SimConfig(
        map_path=open_5x5, seed=0, steps=20,
        num_agents=1, num_humans=0,
        fov_radius=4, safety_radius=1,
        global_solver="cbs",
        horizon=20, replan_every=10,
        solver_timeout_s=2.0, hard_safety=True,
        mode="lifelong", task_allocator="greedy",
    )
    metrics = Simulator(cfg).run()
    # With one agent on an open map, the streak might briefly tick
    # up during between-task moments where the agent waits for a
    # new assignment, but those are idle ticks (n_active == 0),
    # which by contract do NOT count.  Assert both metrics are 0.
    assert metrics.max_global_no_progress_streak == 0, (
        f"all-moving run produced a non-zero streak: "
        f"{metrics.max_global_no_progress_streak}"
    )
    assert metrics.global_no_progress_steps == 0, (
        f"all-moving run produced non-zero global_no_progress_steps: "
        f"{metrics.global_no_progress_steps}"
    )


# ---------------------------------------------------------------------------
# T-GNP-2 — Mode-B corridor swap → streak counts the stuck stretch
# ---------------------------------------------------------------------------


def test_T_GNP_2_corridor_swap_records_streak(tmp_path):
    """Two agents on a 1x4 corridor wanting to swap, with
    ``controller_kind=global_only`` (rigid follower — no Tier-2 A*
    detour) and CBS as Tier-1.  CBS finds no plan, the controller
    holds, and the global no-progress streak accumulates.

    Asserts the streak reaches at least half the run length —
    deliberately loose to tolerate any early-tick transient (first
    assignment, etc.).  The point of this test is to confirm the
    metric increments at all when an actual population-level stall
    occurs, not to pin an exact value (which would couple the
    test to solver heuristics)."""
    p = tmp_path / "corridor_1x4.map"
    p.write_text("type octile\nheight 1\nwidth 4\nmap\n....\n")

    cfg = SimConfig(
        map_path=str(p), seed=0, steps=30,
        num_agents=2, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs",
        horizon=10, replan_every=5,
        solver_timeout_s=2.0, hard_safety=True,
        mode="lifelong", task_allocator="greedy",
        controller_kind="global_only",
    )
    metrics = Simulator(cfg).run()
    assert metrics.max_global_no_progress_streak >= metrics.steps // 2, (
        f"expected max_global_no_progress_streak >= {metrics.steps // 2} "
        f"on a 1x4 corridor swap (canonical Mode-B deadlock); got "
        f"{metrics.max_global_no_progress_streak} over {metrics.steps} steps. "
        f"global_no_progress_steps={metrics.global_no_progress_steps}."
    )
    assert metrics.global_no_progress_steps >= metrics.max_global_no_progress_streak, (
        "global_no_progress_steps must be at least the max streak "
        "(it counts the same ticks)."
    )


# ---------------------------------------------------------------------------
# T-GNP-3 — Idle-tick handling (unit test on MetricsTracker)
# ---------------------------------------------------------------------------


def test_T_GNP_3_idle_tick_resets_streak_without_counting():
    """A ``None`` (no active agents) tick must reset the in-flight
    streak WITHOUT contributing to ``global_no_progress_steps``.

    Pattern: stuck, stuck, idle, stuck, stuck, stuck.
      * ticks 1-2: streak grows to 2.
      * tick 3: idle — reset streak to 0; total stays at 2.
      * ticks 4-6: streak grows to 3.
      * Expected: max == 3, total == 5.
    """
    t = MetricsTracker()
    t.record_global_no_progress_tick(True)
    t.record_global_no_progress_tick(True)
    t.record_global_no_progress_tick(None)
    t.record_global_no_progress_tick(True)
    t.record_global_no_progress_tick(True)
    t.record_global_no_progress_tick(True)
    m = t.finalize(total_steps=6, num_agents=1)
    assert m.max_global_no_progress_streak == 3
    assert m.global_no_progress_steps == 5


# ---------------------------------------------------------------------------
# T-GNP-4 — Stuck/moved/stuck pattern: streak max stays at 1
# ---------------------------------------------------------------------------


def test_T_GNP_4_moved_tick_resets_streak_without_counting():
    """A ``False`` (someone moved) tick must reset the in-flight
    streak WITHOUT contributing to ``global_no_progress_steps``.
    Distinguishes ``False`` from ``None`` only in semantics — both
    reset; only ``True`` increments.

    Pattern: stuck, moved, stuck.
      * tick 1: streak = 1, total = 1.
      * tick 2: moved — reset streak; total stays at 1.
      * tick 3: streak = 1, total = 2.
      * Expected: max == 1 (not 2), total == 2.
    """
    t = MetricsTracker()
    t.record_global_no_progress_tick(True)
    t.record_global_no_progress_tick(False)
    t.record_global_no_progress_tick(True)
    m = t.finalize(total_steps=3, num_agents=1)
    assert m.max_global_no_progress_streak == 1
    assert m.global_no_progress_steps == 2
