"""End-to-end test: ``hard_safety=False`` relaxes Theorem 1.

Paper §3 states POE-Solver supports a "soft safety" mode in which
buffer cells carry a finite penalty (``BLOCKED_CELL_COST = 50`` in
``local_planner.py:38``) instead of being impassable.  The audit
predicted that soft mode breaks the Theorem-1 zero-agent-attributable
guarantee on scenarios where the only path crosses the buffer: the
hard-mode enforcement at ``agent_controller.py:238`` that forces a
WAIT is bypassed, the local A* commits a buffer-traversing path,
and the per-tick classifier counts the resulting agent-attributable
violation pairs.

This test pins the expected relaxation end-to-end with a forced-
encroachment scenario:

  Map (4×6):
      .@@@@.
      ......       ← human at (1,3) stationary
      ......
      .@@@@.

  Top + bottom rows are walled in the middle, so the agent's only
  thoroughfare is the central rows 1 and 2.  The buffer around the
  human at (1,3) covers (1,2), (1,4), (2,3) and the human cell.
  Any path from the left half (col ≤ 1) to the right half (col ≥ 4)
  must cross the buffer at (1,2), (2,3), or (1,4).

  * In hard mode the controller refuses every such move (line 238)
    → the agent safety-waits → ``agent_attr == 0``.
  * In soft mode the A* finds a buffer-traversing path with the
    +50 penalty applied; the controller commits the move; the
    classifier records the agent-attributable violation pair.
    ``agent_attr`` rises strictly above the hard-mode value.

The test runs both modes with identical seed/scale; the hard run
must show zero agent-attributable violations, the soft run must
show strictly more.  This is the *intended* trade-off documented
in §3, not a bug.
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.types import AgentState, HumanState, SimConfig, Task
from ha_lmapf.simulation.simulator import Simulator


def _identity_human_step(env, humans, rng, agent_positions=None):
    """Human model override that keeps humans stationary across the
    run — same pattern as ``tests/test_rhcr_blind.py``."""
    return dict(humans)


def _build_pinch_map(tmp_path):
    p = tmp_path / "pinch.map"
    p.write_text(
        "type octile\n"
        "height 4\nwidth 6\nmap\n"
        ".@@@@.\n"
        "......\n"
        "......\n"
        ".@@@@.\n"
    )
    return str(p)


def _run(map_path: str, hard: bool, seed: int = 0, steps: int = 60) -> "Metrics":
    """Run the pinch-map scenario in either hard or soft mode."""
    cfg = SimConfig(
        map_path=map_path,
        seed=seed,
        steps=steps,
        num_agents=1, num_humans=1,
        fov_radius=4, safety_radius=1,
        global_solver="cbs",
        horizon=10, replan_every=5,
        solver_timeout_s=2.0,
        hard_safety=hard,
        mode="lifelong",
        task_allocator="greedy",
    )
    sim = Simulator(cfg)

    # Force the agent to (1, 0) with task t0 pointing at (1, 5),
    # bypassing the random allocator placement.  The agent_id key
    # is preserved so the simulator's internal bookkeeping
    # (deadlock streak, etc.) keys correctly.
    sim.agents = {
        0: AgentState(agent_id=0, pos=(1, 0)),
    }

    # Place a single stationary human at (1, 3) and lock the model
    # so it never moves.
    sim.humans = {
        0: HumanState(human_id=0, pos=(1, 3), velocity=(0, 0)),
    }
    sim.human_model.step = _identity_human_step  # type: ignore[assignment]

    return sim.run()


def test_hard_safety_preserves_theorem_1(tmp_path):
    """Hard mode on the pinch scenario: ``violations_agent_attributable``
    must be exactly 0.  Confirms the Theorem-1 invariant the paper
    proves is the *guarantee* that soft mode trades away."""
    map_path = _build_pinch_map(tmp_path)
    metrics = _run(map_path, hard=True)
    assert metrics.violations_agent_attributable == 0, (
        f"hard_safety=True must preserve Theorem 1's zero agent-"
        f"attributable guarantee; got "
        f"violations_agent_attributable={metrics.violations_agent_attributable}. "
        f"This indicates a regression in the controller's hard-safety "
        f"enforcement at agent_controller.py:238."
    )


def test_soft_safety_can_relax_theorem_1(tmp_path):
    """Soft mode on the same pinch scenario: the controller no
    longer enforces the buffer as impassable, so the agent's local
    A* finds a buffer-traversing path and commits it.  We assert
    that soft-mode ``violations_agent_attributable`` is strictly
    greater than the hard-mode value, which pins the *direction* of
    the relaxation without coupling the test to a specific count
    (which would depend on path geometry).

    Documents the intended trade-off in §3, NOT a bug."""
    map_path = _build_pinch_map(tmp_path)
    hard = _run(map_path, hard=True)
    soft = _run(map_path, hard=False)
    assert hard.violations_agent_attributable == 0, (
        "hard control failed; can't isolate soft relaxation"
    )
    assert soft.violations_agent_attributable > hard.violations_agent_attributable, (
        f"soft_safety must produce strictly more agent-attributable "
        f"violations than hard_safety on a scenario where the only "
        f"path crosses the buffer.  Got: hard={hard.violations_agent_attributable}, "
        f"soft={soft.violations_agent_attributable}.  Either the "
        f"BLOCKED_CELL_COST penalty is too large for A* to ever pick "
        f"a buffer path (audit local_planner.py:38), or the scenario "
        f"is no longer forcing encroachment (audit the pinch map)."
    )
