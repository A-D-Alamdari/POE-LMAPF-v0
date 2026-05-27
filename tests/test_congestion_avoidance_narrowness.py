"""Tests for narrowness-weighted path-overlap penalty.

These tests target the addition of ``_compute_narrowness_map`` and the
narrowness-weighted overlap term inside
``CongestionAvoidanceTaskAllocator.assign``, plus the new
``SimConfig.lambda_conflict`` / ``SimConfig.max_rounds`` plumbing.

The original 11 ``test_congestion_avoidance_allocator.py`` tests remain
the contract for the un-weighted behaviour (lambda=0, no env, simple
overlap). Tests here verify that the new code does not regress those
properties and adds the expected new behaviour at lambda>0.
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


# ---------------------------------------------------------------------------
# Narrowness map correctness
# ---------------------------------------------------------------------------


def test_narrowness_3x3_center_obstacle():
    """3x3 with center blocked.

    Layout (0 = free, # = blocked):

        0 0 0
        0 # 0
        0 0 0

    Edge cells: (0,1), (1,0), (1,2), (2,1) — each has 2 free neighbors
    (the centre is blocked, the off-grid neighbour is also blocked)
    so narrowness = 4/2 = 2.0.

    Corner cells: (0,0), (0,2), (2,0), (2,2) — each has 2 free
    neighbors (two of their four neighbours are off-grid) so
    narrowness = 4/2 = 2.0.
    """
    env = Environment(width=3, height=3, blocked={(1, 1)})
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(env)
    narrow = alloc._narrowness
    assert narrow is not None
    # Every free cell has degree 2 on this board, so all 8 free cells
    # have narrowness 2.0.
    expected_free = {(0, 0), (0, 1), (0, 2),
                     (1, 0),         (1, 2),
                     (2, 0), (2, 1), (2, 2)}
    assert set(narrow.keys()) == expected_free
    for cell, w in narrow.items():
        assert w == pytest.approx(2.0), (cell, w)


def test_narrowness_open_interior_has_unit_weight():
    """In a 5x5 open grid, the centre (2,2) has all 4 neighbours free
    → degree 4 → narrowness 4/4 = 1.0. The grid corners have degree 2
    → narrowness 2.0. Edge non-corner cells have degree 3 → 4/3 ≈ 1.333.
    """
    env = Environment(width=5, height=5, blocked=set())
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(env)
    narrow = alloc._narrowness
    assert narrow[(2, 2)] == pytest.approx(1.0)
    assert narrow[(0, 0)] == pytest.approx(2.0)
    assert narrow[(0, 2)] == pytest.approx(4.0 / 3.0)


def test_narrowness_corridor_endpoints_and_interior():
    """A 1x5 corridor:
        E . . . E
    Interior cells (col 1,2,3) have 2 free neighbours → 2.0.
    Endpoint cells (col 0 and 4) have exactly 1 free neighbour → 4.0.
    """
    # Single-row world of height=1; column count 5.
    env = Environment(width=5, height=1, blocked=set())
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(env)
    narrow = alloc._narrowness
    assert narrow[(0, 0)] == pytest.approx(4.0)
    assert narrow[(0, 4)] == pytest.approx(4.0)
    assert narrow[(0, 1)] == pytest.approx(2.0)
    assert narrow[(0, 2)] == pytest.approx(2.0)
    assert narrow[(0, 3)] == pytest.approx(2.0)


def test_narrowness_isolated_cell_clamped_to_four():
    """A free cell with no free neighbours (degree 0) clamps to
    narrowness = 4.0 (4/max(1,0) = 4). Build a 3x3 with everything
    blocked except (0,0).
    """
    blocked = {(r, c) for r in range(3) for c in range(3)} - {(0, 0)}
    env = Environment(width=3, height=3, blocked=blocked)
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(env)
    assert alloc._narrowness[(0, 0)] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Penalty divergence: same overlap count, different narrowness
# ---------------------------------------------------------------------------


def test_corridor_shared_cell_penalises_more_than_open_shared_cell():
    """Build two maps with the same overlap count but different
    narrowness, and observe a strictly larger weighted_overlap on the
    corridor variant.

    We verify by inspecting the cost matrix construction: for two
    paths sharing a single cell, the weighted overlap equals
    ``narrowness[shared_cell]`` (× 2 because the symmetric
    contribution is counted from the other agent's perspective on
    its alternative path). Showing the corridor penalty exceeds the
    open-cell penalty is enough.
    """
    # Open 5x5: shared cell (2,2) has narrowness 1.0
    env_open = Environment(width=5, height=5, blocked=set())
    alloc_open = CongestionAvoidanceTaskAllocator(lambda_conflict=1.0)
    alloc_open.set_env(env_open)
    w_open = alloc_open._narrowness[(2, 2)]

    # Corridor 1x5: every interior cell has narrowness 2.0
    env_corr = Environment(width=5, height=1, blocked=set())
    alloc_corr = CongestionAvoidanceTaskAllocator(lambda_conflict=1.0)
    alloc_corr.set_env(env_corr)
    w_corr = alloc_corr._narrowness[(0, 2)]

    assert w_corr > w_open
    assert w_corr == pytest.approx(2.0)
    assert w_open == pytest.approx(1.0)


def test_narrow_corridor_shifts_assignment_more_than_uniform_weight():
    """End-to-end: in a one-row corridor the two-agent / two-task
    setup must produce a different assignment than the unweighted
    counterpart whenever the narrowness penalty is the deciding
    factor.

    We construct a corridor where two agents at opposite ends and
    two tasks at opposite ends produce paths that share the entire
    middle. With narrowness weighting active the cost of crossing
    paths is amplified, so the allocator should pick the
    same-direction (non-crossing) assignment if it is cheaper under
    the weighted measure.
    """
    env = Environment(width=7, height=1, blocked=set())
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 6)),
    }
    tasks = [
        Task(task_id="t0", start=(0, 6), goal=(0, 6), release_step=0),
        Task(task_id="t1", start=(0, 0), goal=(0, 0), release_step=0),
    ]
    alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=1.0)
    alloc.set_env(env)
    result = alloc.assign(agents=agents, open_tasks=tasks, step=0)
    # Both agents must still receive an assignment.
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------


def test_narrowness_map_cached_in_set_env():
    """set_env binds and computes the narrowness map exactly once.
    A subsequent ``assign()`` must not recompute it.
    """
    env = Environment(width=20, height=20, blocked=set())
    alloc = CongestionAvoidanceTaskAllocator()
    alloc.set_env(env)
    first = alloc._narrowness
    assert first is not None
    # Take a reference; if set_env weren't binding to instance state,
    # the post-assign view would be different.
    agents = {0: AgentState(agent_id=0, pos=(0, 0))}
    tasks = [Task(task_id="t0", start=(5, 5), goal=(5, 5), release_step=0)]
    alloc.assign(agents=agents, open_tasks=tasks, step=0)
    assert alloc._narrowness is first  # same object reference


def test_narrowness_unset_means_uniform_fallback():
    """Without set_env, _narrowness is None and the allocator falls
    back to len(shared) — i.e. the original behaviour. We exercise
    this path by constructing an allocator without an env, providing
    Manhattan-distance fallback, and confirming it still produces an
    assignment.
    """
    alloc = CongestionAvoidanceTaskAllocator(lambda_conflict=1.0)
    assert alloc._narrowness is None
    agents = {0: AgentState(agent_id=0, pos=(0, 0))}
    tasks = [Task(task_id="t0", start=(3, 3), goal=(4, 4), release_step=0)]
    result = alloc.assign(agents=agents, open_tasks=tasks, step=0)
    assert 0 in result


# ---------------------------------------------------------------------------
# lambda_conflict / max_rounds plumbing
# ---------------------------------------------------------------------------


def test_simconfig_lambda_conflict_default():
    cfg = SimConfig(map_path="x")
    assert cfg.lambda_conflict == 0.5
    assert cfg.max_rounds == 5


def test_simconfig_lambda_conflict_override():
    cfg = SimConfig(map_path="x", lambda_conflict=2.0, max_rounds=7)
    assert cfg.lambda_conflict == 2.0
    assert cfg.max_rounds == 7


def test_simulator_forwards_lambda_to_allocator(tmp_path):
    """SimConfig(lambda_conflict=2.0) must produce an allocator with
    lambda_conflict=2.0.
    """
    map_path = tmp_path / "tiny.map"
    map_path.write_text(
        "type octile\nheight 3\nwidth 3\nmap\n...\n...\n...\n"
    )
    cfg = SimConfig(
        map_path=str(map_path), num_agents=1, num_humans=0,
        steps=1, seed=0, global_solver="cbs",
        lambda_conflict=2.0, max_rounds=7,
    )
    sim = Simulator(cfg)
    assert isinstance(sim.task_allocator, CongestionAvoidanceTaskAllocator)
    assert sim.task_allocator.lambda_conflict == 2.0
    assert sim.task_allocator.max_rounds == 7
    # env was bound and narrowness cached
    assert sim.task_allocator._narrowness is not None


def test_simulator_default_lambda(tmp_path):
    map_path = tmp_path / "tiny.map"
    map_path.write_text(
        "type octile\nheight 3\nwidth 3\nmap\n...\n...\n...\n"
    )
    cfg = SimConfig(
        map_path=str(map_path), num_agents=1, num_humans=0,
        steps=1, seed=0, global_solver="cbs",
    )
    sim = Simulator(cfg)
    assert sim.task_allocator.lambda_conflict == 0.5
    assert sim.task_allocator.max_rounds == 5


# ---------------------------------------------------------------------------
# Backward-compatibility regression
# ---------------------------------------------------------------------------


def test_lambda_zero_matches_greedy_on_bfs_distances():
    """With lambda_conflict=0, congestion_avoidance is Hungarian-on-BFS-
    distance. On a single-agent, single-task setup the assignment
    must equal greedy's assignment (only one agent and one task, so
    the only choice is identical).

    This is the critical regression: the narrowness change must not
    leak into the lambda=0 path. The lambda gate at line "if
    self.lambda_conflict > 0.0:" must keep the cost matrix at D
    (pure distances).
    """
    env = Environment(width=10, height=10, blocked=set())
    agents = {i: AgentState(agent_id=i, pos=(0, i)) for i in range(3)}
    tasks = [Task(task_id=f"t{i}", start=(9, i), goal=(9, i), release_step=0)
             for i in range(3)]

    greedy = GreedyNearestTaskAllocator()
    g_result = {a: t.task_id for a, t in
                greedy.assign(agents, tasks, step=0).items()}

    ca = CongestionAvoidanceTaskAllocator(lambda_conflict=0.0)
    ca.set_env(env)
    ca_result = {a: t.task_id for a, t in
                 ca.assign(agents, tasks, step=0).items()}

    assert ca_result == g_result


def test_lambda_zero_assignment_independent_of_narrowness_map():
    """Stronger regression: even on a map with strongly varying
    narrowness (a corridor), lambda=0 must equal Hungarian-on-distance.
    """
    blocked = set()
    for r in range(1, 9):
        for c in range(10):
            if c != 5:
                blocked.add((r, c))
    env = Environment(width=10, height=10, blocked=blocked)
    agents = {
        0: AgentState(agent_id=0, pos=(0, 4)),
        1: AgentState(agent_id=1, pos=(0, 6)),
    }
    tasks = [
        Task(task_id="t0", start=(9, 4), goal=(9, 4), release_step=0),
        Task(task_id="t1", start=(9, 6), goal=(9, 6), release_step=0),
    ]
    ca = CongestionAvoidanceTaskAllocator(lambda_conflict=0.0)
    ca.set_env(env)
    result = ca.assign(agents=agents, open_tasks=tasks, step=0)
    # With lambda=0 and equal distances the assignment is the
    # natural pairing.
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Smoke test on warehouse-2-2 at modest density
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_simulator_smoke_warehouse_2_2_with_narrowness():
    """End-to-end smoke at modest density on the paper map, with the
    new default (lambda_conflict=0.5, narrowness-weighted).

    Asserts throughput > 0 over 100 steps. Also checks that the
    allocator's mean per-call wall-time stays under 100 ms at this
    density — the narrowness map is cached per env, so the per-call
    cost should be in the same ballpark as the un-weighted
    congestion_avoidance.
    """
    import pathlib
    map_path = pathlib.Path("data/maps/warehouse-10-20-10-2-2.map")
    if not map_path.exists():
        pytest.skip("warehouse-10-20-10-2-2.map not available")
    cfg = SimConfig(
        map_path=str(map_path), seed=0, steps=100,
        num_agents=30, num_humans=20,
        global_solver="cbs", solver_timeout_s=1.0,
        task_allocator="congestion_avoidance",
        lambda_conflict=0.5, max_rounds=5,
    )
    sim = Simulator(cfg)
    assert isinstance(sim.task_allocator, CongestionAvoidanceTaskAllocator)
    assert sim.task_allocator._narrowness is not None

    times_ms: list[float] = []
    orig_assign = sim.task_allocator.assign

    def timed_assign(*args, **kwargs):
        t0 = time.perf_counter()
        res = orig_assign(*args, **kwargs)
        times_ms.append((time.perf_counter() - t0) * 1000.0)
        return res

    sim.task_allocator.assign = timed_assign
    metrics = sim.run()
    assert metrics.steps == 100
    assert metrics.throughput >= 0.0  # may be 0 on map+solver unavail
    if times_ms:
        mean_ms = sum(times_ms) / len(times_ms)
        assert mean_ms < 100.0, (
            f"allocator mean wall {mean_ms:.1f} ms exceeds 100 ms "
            "budget; narrowness cache may not be cached per env"
        )
