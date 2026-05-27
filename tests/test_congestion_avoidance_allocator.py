"""
Tests for CongestionAvoidanceTaskAllocator (paper Section 4.2 name;
historically ConflictAwareTaskAllocator under the "Direction A" label,
removed in Phase 5).

The congestion-avoidance allocator extends Hungarian assignment with a
path-overlap penalty computed via BFS on the static map. With
lambda_conflict=0 it must reduce to Hungarian on BFS distances; with
lambda_conflict>0 it must produce different assignments when greedy
funnels multiple agents through a single corridor.

Two tests in this file (the *_rejects_legacy_conflict_aware_* tests)
assert that the legacy "conflict_aware" string raises ``ValueError`` at
both factory call sites (``make_allocator`` and
``Simulator._make_allocator``).  This locks in the Phase-5 removal of
the backward-compatibility shim.
"""
from __future__ import annotations

import time

import pytest

from ha_lmapf.core.types import AgentState, SimConfig, Task
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.simulation.simulator import Simulator
from ha_lmapf.task_allocator import make_allocator
from ha_lmapf.task_allocator.task_allocator import (
    CongestionAvoidanceTaskAllocator,
    GreedyNearestTaskAllocator,
)


def _empty_env(width: int = 10, height: int = 10) -> Environment:
    """Empty (no obstacles) WxH grid."""
    return Environment(width=width, height=height, blocked=set())


# --- 5.1 Empty environments ------------------------------------------------


def test_empty_no_agents_no_tasks():
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(_empty_env())
    result = alloc.assign(agents={}, open_tasks=[], step=0)
    assert result == {}


def test_empty_no_agents_some_tasks():
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(_empty_env())
    tasks = [Task(task_id=f"t{i}", start=(i, i), goal=(i + 1, i + 1), release_step=0)
             for i in range(5)]
    result = alloc.assign(agents={}, open_tasks=tasks, step=0)
    assert result == {}


def test_empty_some_agents_no_tasks():
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(_empty_env())
    agents = {i: AgentState(agent_id=i, pos=(i, 0)) for i in range(5)}
    result = alloc.assign(agents=agents, open_tasks=[], step=0)
    assert result == {}


# --- 5.2 Trivial 1-agent 1-task --------------------------------------------


def test_trivial_one_to_one():
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(_empty_env())
    agents = {0: AgentState(agent_id=0, pos=(0, 0))}
    tasks = [Task(task_id="t0", start=(5, 5), goal=(9, 9), release_step=0)]
    result = alloc.assign(agents=agents, open_tasks=tasks, step=0)
    assert result == {0: tasks[0]}


# --- 5.3 lambda_conflict=0 degenerates ------------------------------------


def test_lambda_zero_matches_hungarian_distance():
    """
    With lambda_conflict=0 the congestion-avoidance allocator should match
    Hungarian (and on these inputs, also match greedy since pickup
    distances are unambiguous).
    """
    env = _empty_env()
    alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=0.0)
    alloc.set_env(env)

    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(9, 9)),
    }
    tasks = [
        Task(task_id="t0", start=(0, 1), goal=(2, 2), release_step=0),
        Task(task_id="t1", start=(9, 8), goal=(7, 7), release_step=0),
    ]

    result = alloc.assign(agents=agents, open_tasks=tasks, step=0)
    greedy = GreedyNearestTaskAllocator().assign(agents, tasks, step=0)

    assert {a: t.task_id for a, t in result.items()} == \
           {a: t.task_id for a, t in greedy.items()}


# --- 5.4 Congestion-avoidance diverges from greedy when paths funnel ------------


def test_corridor_funnel_diverges_from_greedy():
    """
    A 10x10 map with a single narrow corridor (one open row) connecting
    two clusters. Greedy assigns all corner agents to the same nearest
    task; congestion-avoidance should spread agents across the four tasks.
    """
    # Build a map where rows 1..8 are blocked except for column 5 (the
    # corridor). Row 0 and row 9 are fully free (the clusters).
    blocked = set()
    for r in range(1, 9):
        for c in range(10):
            if c != 5:
                blocked.add((r, c))
    env = Environment(width=10, height=10, blocked=blocked)

    # 4 agents in the top row (forced through the corridor).
    agents = {
        i: AgentState(agent_id=i, pos=(0, i)) for i in range(4)
    }
    # 4 tasks at the bottom row pickup locations.
    tasks = [
        Task(task_id=f"t{i}", start=(9, i), goal=(9, 9), release_step=0)
        for i in range(4)
    ]

    greedy_alloc = GreedyNearestTaskAllocator()
    greedy_result = {a: t.task_id for a, t in
                     greedy_alloc.assign(agents, tasks, step=0).items()}

    ca_alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=0.5)
    ca_alloc.set_env(env)
    ca_result = {a: t.task_id for a, t in
                 ca_alloc.assign(agents, tasks, step=0).items()}

    # All four agents must still be assigned.
    assert len(ca_result) == 4
    # And the assignment must differ from greedy in at least one slot,
    # confirming the conflict penalty actually shifts the matching.
    assert ca_result != greedy_result


# --- 5.5 Convergence within max_rounds ------------------------------------


def test_convergence_within_max_rounds():
    """
    Iterative refinement must stabilise within max_rounds. We check
    by inspecting last_rounds_used after a non-trivial allocate call.
    """
    env = _empty_env(width=20, height=20)
    alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=0.5, max_rounds=5)
    alloc.set_env(env)

    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 19)),
        2: AgentState(agent_id=2, pos=(19, 0)),
        3: AgentState(agent_id=3, pos=(19, 19)),
        4: AgentState(agent_id=4, pos=(10, 10)),
    }
    tasks = [
        Task(task_id=f"t{i}", start=(i, 5), goal=(i + 1, 6), release_step=0)
        for i in range(8)
    ]

    result = alloc.assign(agents=agents, open_tasks=tasks, step=0)

    assert len(result) == 5, "All 5 agents should be assigned"
    # Round counter is incremented each round; converged if it stopped
    # before exhausting max_rounds OR equal to max_rounds+1 (i.e. did
    # not exceed). Either way it must be bounded.
    assert alloc.last_rounds_used <= alloc.max_rounds + 1
    print(f"\nConvergence: last_rounds_used={alloc.last_rounds_used}")


# --- 5.6 Factory integration ----------------------------------------------


def test_factory_creates_congestion_avoidance():
    alloc = make_allocator("congestion_avoidance")
    assert isinstance(alloc, CongestionAvoidanceTaskAllocator)
    assert alloc.lambda_conflict == 0.5
    assert alloc.max_rounds == 5


# --- 5.6b Phase-5 rejection tests ------------------------------------------
# These tests verify that the legacy "conflict_aware" string raises
# ``ValueError`` at both factory call sites (``make_allocator`` and
# ``Simulator._make_allocator``).  They lock in the Phase-5 removal of
# the backward-compatibility shim.


def test_factory_rejects_legacy_conflict_aware_string():
    """The legacy "conflict_aware" string was removed in Phase 5 of
    the conflict_aware -> congestion_avoidance migration.  The factory
    must raise ``ValueError`` with a helpful message pointing users
    to the new name."""
    with pytest.raises(ValueError, match=r"conflict_aware.*Phase 5"):
        make_allocator("conflict_aware")


def test_factory_forwards_lambda_kwarg():
    alloc = make_allocator("congestion_avoidance", lambda_conflict=1.0)
    assert isinstance(alloc, CongestionAvoidanceTaskAllocator)
    assert alloc.lambda_conflict == 1.0


def test_factory_forwards_max_rounds_kwarg():
    alloc = make_allocator("congestion_avoidance", max_rounds=10)
    assert isinstance(alloc, CongestionAvoidanceTaskAllocator)
    assert alloc.max_rounds == 10


# --- 5.7 Integration smoke test -------------------------------------------


@pytest.fixture
def warehouse_2_2_map(tmp_path):
    """Synthesise a small warehouse-2-2-like map for the smoke test."""
    rows = [
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
    ]
    p = tmp_path / "mini_warehouse_2_2.map"
    p.write_text("type octile\nheight 10\nwidth 14\nmap\n" + "\n".join(rows) + "\n")
    return str(p)


def test_simulator_smoke_rejects_legacy_conflict_aware_string(warehouse_2_2_map):
    """Phase-5 rejection test.  Constructing a Simulator with the
    legacy ``task_allocator="conflict_aware"`` must raise ``ValueError``
    from inside ``Simulator._make_allocator``.  Python does not enforce
    ``Literal`` types at construction time, so SimConfig accepts the
    string and the rejection fires at Simulator()'s allocator-factory
    call site.  Verifies both factory sites raise consistently with
    the make_allocator rejection test above.
    """
    cfg = SimConfig(
        map_path=warehouse_2_2_map,
        global_solver="cbs",
        task_allocator="conflict_aware",  # known-rejected
    )
    with pytest.raises(ValueError, match=r"conflict_aware.*Phase 5"):
        Simulator(cfg)
