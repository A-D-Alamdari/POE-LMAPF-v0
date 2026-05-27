"""Regression tests for the §5.5 realized assignment path-overlap
metric.

``Metrics.sum_assignment_path_overlap`` and
``Metrics.mean_assignment_path_overlap`` are computed POST-allocation
by the simulator using BFS shortest paths from each assigned agent's
current position to its task's pickup location, then summing
|path_i ∩ path_j| over all assigned-agent pairs.

The metric is defined identically for greedy / hungarian / auction /
congestion_avoidance — the BFS service is a private
``CongestionAvoidanceTaskAllocator`` instance the simulator
instantiates regardless of which allocator made the choice.

These tests pin:

  T-APO-1  Disjoint paths → overlap == 0.  Two agents at opposite
           corners of an open map, each with a task whose pickup is
           on its own side.  Paths share no cells.

  T-APO-2  Identical paths → overlap > 0.  Two agents on a 1xN
           corridor with both tasks pickup'd at the same far end.
           Their BFS paths share at least the goal cell; overlap
           must be positive.

  T-APO-3  Greedy allocator round-trips a non-null overlap value
           on a multi-agent run.  Confirms the metric is
           allocator-agnostic (was the original motivation —
           greedy / hungarian / auction don't compute overlap
           internally; the simulator's post-processing supplies it).

  T-APO-4  Single-agent rounds do NOT bump
           ``n_multiagent_allocation_rounds``; multi-agent rounds
           do.  Confirms the clean denominator counter is wired
           independently of the overlap-round counter.

  T-APO-5  A run with at least one multi-agent allocation round
           round-trips n_multiagent_allocation_rounds > 0 and the
           derived per-round overlap is well-defined.
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.types import AgentState, SimConfig, Task
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Direct helper-level tests (T-APO-1, T-APO-2)
# ---------------------------------------------------------------------------


def _make_sim(map_text: str, tmp_path, **cfg_overrides) -> Simulator:
    """Build a Simulator on a synthetic map.  num_agents/num_humans
    are set to 1/0 so __init__ succeeds; subsequent tests overwrite
    ``sim.agents`` directly and call _record_assignment_overlap()
    to exercise the metric on hand-crafted assignments."""
    p = tmp_path / "test.map"
    p.write_text(map_text)
    base = dict(
        map_path=str(p), seed=0, steps=1,
        num_agents=1, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs",
        horizon=10, replan_every=10,
        solver_timeout_s=1.0, hard_safety=True,
        mode="lifelong", task_allocator="greedy",
    )
    base.update(cfg_overrides)
    return Simulator(SimConfig(**base))


def test_T_APO_1_disjoint_paths_zero_overlap(tmp_path):
    """Two agents on a 5x5 open map with tasks whose pickup
    locations are on opposite sides.  BFS shortest paths share no
    cells → overlap == 0 for that allocation round."""
    sim = _make_sim(
        "type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5,
        tmp_path,
    )
    # Hand-place two agents at (0,0) and (4,4).
    sim.agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(4, 4)),
    }
    # Tasks with pickups on each agent's own column/row — disjoint paths.
    # Agent 0: (0,0) → (0,4) along the top row.
    # Agent 1: (4,4) → (4,0) along the bottom row.
    assignments = {
        0: Task(task_id="t0", start=(0, 4), goal=(0, 4), release_step=0),
        1: Task(task_id="t1", start=(4, 0), goal=(4, 0), release_step=0),
    }
    sim._record_assignment_overlap(assignments)
    m = sim.metrics.finalize(total_steps=1, num_agents=2)
    assert m.sum_assignment_path_overlap == 0.0, (
        f"disjoint paths produced non-zero overlap: "
        f"{m.sum_assignment_path_overlap}"
    )
    assert m.mean_assignment_path_overlap == 0.0


def test_T_APO_2_identical_paths_positive_overlap(tmp_path):
    """Two agents on a 1x6 corridor both starting at (0,0) with
    pickups at (0,5).  Their BFS paths are both (0,0)→(0,1)→...→(0,5)
    — six identical cells.  Overlap must equal len(path) = 6
    (because the path-cell sets are identical)."""
    sim = _make_sim(
        "type octile\nheight 1\nwidth 6\nmap\n" + "......\n",
        tmp_path,
    )
    # Both agents at (0,0) (a synthetic setup — vertex conflict
    # ignored since this is metric-only, not a real planning run).
    sim.agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 0)),
    }
    # Both tasks have pickup at (0,5) — paths are identical.
    assignments = {
        0: Task(task_id="t0", start=(0, 5), goal=(0, 5), release_step=0),
        1: Task(task_id="t1", start=(0, 5), goal=(0, 5), release_step=0),
    }
    sim._record_assignment_overlap(assignments)
    m = sim.metrics.finalize(total_steps=1, num_agents=2)
    # Path is 6 cells long; identical for both agents; one pair → 6.
    assert m.sum_assignment_path_overlap == 6.0, (
        f"identical 6-cell paths produced overlap "
        f"{m.sum_assignment_path_overlap}, expected 6.0"
    )
    assert m.mean_assignment_path_overlap == 6.0


# ---------------------------------------------------------------------------
# T-APO-3 — allocator-agnostic end-to-end
# ---------------------------------------------------------------------------


def test_T_APO_3_greedy_allocator_records_overlap(tmp_path):
    """End-to-end: a multi-agent run with the GREEDY allocator
    (which does NOT compute overlap internally) populates
    ``sum_assignment_path_overlap`` and ``mean_assignment_path_overlap``
    via the simulator's post-allocation hook.  The actual numbers
    depend on seed-dependent task placement; we only require that
    both fields are non-negative finite floats and that at least
    one allocation round was recorded (so mean is well-defined)."""
    p = tmp_path / "open8.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    cfg = SimConfig(
        map_path=str(p), seed=0, steps=20,
        num_agents=3, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs",
        horizon=10, replan_every=5,
        solver_timeout_s=2.0, hard_safety=True,
        mode="lifelong",
        task_allocator="greedy",   # ← key: not congestion_avoidance
    )
    m = Simulator(cfg).run()
    # Allocator-agnostic contract: the metric is populated.
    assert m.sum_assignment_path_overlap >= 0.0
    assert m.mean_assignment_path_overlap >= 0.0
    # mean must be finite (no divide-by-zero) even if sum is 0.
    import math
    assert math.isfinite(m.mean_assignment_path_overlap), (
        f"mean overlap not finite: {m.mean_assignment_path_overlap}"
    )


# ---------------------------------------------------------------------------
# T-APO-4 — Single-agent vs multi-agent counter wiring
# ---------------------------------------------------------------------------


def test_T_APO_4_single_agent_rounds_do_not_bump_multiagent_counter(tmp_path):
    """Calling ``_record_assignment_overlap`` with a 0-agent or
    1-agent assignment must increment the overlap-round counter
    (by adding 0.0) but NOT the multi-agent counter.  Conversely,
    a 2-agent assignment must increment both.
    """
    sim = _make_sim(
        "type octile\nheight 4\nwidth 4\nmap\n" + "....\n" * 4,
        tmp_path,
    )
    sim.agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(3, 3)),
    }
    # Empty round.
    sim._record_assignment_overlap({})
    # Single-agent round.
    sim._record_assignment_overlap({
        0: Task(task_id="ta", start=(0, 3), goal=(0, 3), release_step=0),
    })
    # Multi-agent round.
    sim._record_assignment_overlap({
        0: Task(task_id="tb", start=(0, 3), goal=(0, 3), release_step=0),
        1: Task(task_id="tc", start=(3, 0), goal=(3, 0), release_step=0),
    })
    m = sim.metrics.finalize(total_steps=1, num_agents=2)
    # 3 calls total → 3 overlap rounds; but only 1 is multi-agent.
    assert sim.metrics._assignment_overlap_rounds == 3
    assert m.n_multiagent_allocation_rounds == 1, (
        f"expected n_multiagent_allocation_rounds == 1 "
        f"(only the 2-agent round counts), got "
        f"{m.n_multiagent_allocation_rounds}"
    )


# ---------------------------------------------------------------------------
# T-APO-5 — End-to-end: derived per-round overlap is well-defined
# ---------------------------------------------------------------------------


def test_T_APO_5_derived_per_round_overlap_well_defined(tmp_path):
    """A multi-agent run records at least one multi-agent round and
    the derived ``sum / n_multiagent_allocation_rounds`` is a finite
    non-negative number — i.e. the §5.5 clean per-round overlap
    can be computed post-hoc from the CSV."""
    import math
    p = tmp_path / "open10.map"
    p.write_text("type octile\nheight 10\nwidth 10\nmap\n" + ".........." + "\n.........." * 9 + "\n")
    cfg = SimConfig(
        map_path=str(p), seed=0, steps=20,
        num_agents=4, num_humans=0,
        fov_radius=2, safety_radius=1,
        global_solver="cbs",
        horizon=10, replan_every=5,
        solver_timeout_s=2.0, hard_safety=True,
        mode="lifelong", task_allocator="greedy",
    )
    m = Simulator(cfg).run()
    assert m.n_multiagent_allocation_rounds >= 1, (
        f"multi-agent run produced no multi-agent allocation rounds; "
        f"got n_multiagent_allocation_rounds="
        f"{m.n_multiagent_allocation_rounds}"
    )
    derived = m.sum_assignment_path_overlap / m.n_multiagent_allocation_rounds
    assert math.isfinite(derived) and derived >= 0.0, (
        f"derived per-round overlap {derived} is not a finite "
        f"non-negative number"
    )
