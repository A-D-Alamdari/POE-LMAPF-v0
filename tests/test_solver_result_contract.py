"""
SolverResult contract tests (Prompt 16).

Six test groups:

1. ``test_solver_result_is_frozen`` — the dataclass is immutable.
2. ``test_every_wrapper_returns_solver_result[<name>]`` — parametrised
   over every solver registered in :class:`GlobalPlannerFactory`;
   skips wrappers whose binary is missing on this host.
3. ``test_decision_tree_<status>`` — four mocked-subprocess scenarios
   exercising each non-trivial branch of the decision tree in
   :meth:`BaseSolverWrapper._wrap_subprocess`.
4. ``test_binary_not_found_path`` — missing executable resolves to
   ``status="binary_not_found"`` with a non-empty ``error_msg``.
5. ``test_legacy_plan_shim_returns_same_bundle`` — legacy ``plan()``
   returns a :class:`PlanBundle` whose paths match
   ``plan_with_metadata().plan``.
6. ``test_rolling_horizon_status_dispatch`` — integration test:
   a mock solver with a fixed sequence of statuses correctly
   increments the new ``Metrics`` counters and reuses the previous
   bundle on timeout.
"""
from __future__ import annotations

import dataclasses
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence
from unittest import mock

import pytest

from ha_lmapf.core.types import (
    AgentState, PlanBundle, SolverResult, Task, TimedPath,
)
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.global_tier.solvers._base import BaseSolverWrapper
from ha_lmapf.simulation.environment import Environment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def env_5x5(tmp_path: Path) -> Environment:
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return Environment.load_from_map(str(p))


def _two_agent_instance() -> tuple:
    agents = {0: AgentState(0, (0, 0)), 1: AgentState(1, (0, 4))}
    assignments = {
        0: Task("t0", (0, 0), (4, 4), 0),
        1: Task("t1", (0, 4), (4, 0), 0),
    }
    return agents, assignments


# ---------------------------------------------------------------------------
# Group 1 — dataclass shape
# ---------------------------------------------------------------------------


def test_solver_result_is_frozen():
    """SolverResult is a frozen dataclass — status / timing fields are
    immutable after construction.  Hashability is implied by frozen=True
    when the field types are themselves hashable (PlanBundle currently
    is not hashable; we only assert the immutability invariant)."""
    assert dataclasses.is_dataclass(SolverResult)
    params = SolverResult.__dataclass_params__
    assert params.frozen is True
    plan = PlanBundle(paths={}, created_step=0, horizon=10)
    r = SolverResult(plan=plan, status="complete",
                     solver_wall_ms=1.0, end_to_end_wall_ms=2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.status = "error"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Group 2 — every wrapper exposes plan_with_metadata
# ---------------------------------------------------------------------------


SOLVER_FACTORY_NAMES = [
    "cbsh2", "lacam_official", "lacam3", "lns2", "pbs", "pibt2",
]


@pytest.mark.parametrize("factory_name", SOLVER_FACTORY_NAMES)
def test_every_wrapper_returns_solver_result(env_5x5, factory_name: str):
    """Each shipped wrapper returns a ``SolverResult`` from
    ``plan_with_metadata``.  Skips wrappers whose binary is missing
    or whose binary fails the canonical smoke test (PIBT2 build issue
    on the CI image)."""
    solver = GlobalPlannerFactory.create(factory_name, time_limit_sec=1.0)
    binary_path = getattr(solver, "binary_path", None)
    if binary_path is None or not os.path.isfile(binary_path):
        pytest.skip(f"{factory_name}: binary not present at {binary_path!r}")
    agents, assignments = _two_agent_instance()
    result = solver.plan_with_metadata(
        env=env_5x5, agents=agents, assignments=assignments,
        step=0, horizon=10, rng=None,
    )
    assert isinstance(result, SolverResult), (
        f"{factory_name}.plan_with_metadata returned {type(result).__name__}"
    )
    assert result.status in {
        "complete", "partial_anytime",
        "timeout_no_result", "error", "binary_not_found",
    }
    assert isinstance(result.plan, PlanBundle)
    assert result.end_to_end_wall_ms >= 0.0


# ---------------------------------------------------------------------------
# Group 3 — decision-tree branches under mocked subprocess
# ---------------------------------------------------------------------------


class _ProbeWrapper(BaseSolverWrapper):
    """Bare wrapper exercising _wrap_subprocess directly."""
    binary_path = "/usr/bin/true"  # always present on Linux CI


def _agents_one() -> Dict[int, AgentState]:
    return {0: AgentState(0, (0, 0))}


def _make_wait_paths_fn(paths_to_return):
    """Return a parse_fn closure that yields the fixed paths."""
    def fn(stdout, stderr, returncode):
        return paths_to_return, math.nan, None
    return fn


def test_decision_tree_complete():
    """rc=0 + parser returned a real plan -> status='complete'."""
    w = _ProbeWrapper()
    real_paths = {0: TimedPath(cells=[(0, 0), (1, 0)], start_step=0)}
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(stdout="", stderr="", returncode=0)
        result = w._wrap_subprocess(
            cmd=["/usr/bin/true"], timeout_s=1.0,
            parse_fn=_make_wait_paths_fn(real_paths),
            agents=_agents_one(), active_agents=[0],
            start_step=0, horizon=2,
        )
    assert result.status == "complete"
    assert result.error_msg == ""


def test_decision_tree_partial_anytime():
    """TimeoutExpired + parser returned partial plan -> 'partial_anytime'."""
    w = _ProbeWrapper()
    real_paths = {0: TimedPath(cells=[(0, 0), (1, 0)], start_step=0)}
    with mock.patch("subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=1.0)
        result = w._wrap_subprocess(
            cmd=["/usr/bin/true"], timeout_s=1.0,
            parse_fn=_make_wait_paths_fn(real_paths),
            agents=_agents_one(), active_agents=[0],
            start_step=0, horizon=2,
        )
    assert result.status == "partial_anytime"


def test_decision_tree_timeout_no_result():
    """TimeoutExpired + parser returned no plan -> 'timeout_no_result'."""
    w = _ProbeWrapper()
    with mock.patch("subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=1.0)
        result = w._wrap_subprocess(
            cmd=["/usr/bin/true"], timeout_s=1.0,
            parse_fn=_make_wait_paths_fn(None),
            agents=_agents_one(), active_agents=[0],
            start_step=0, horizon=2,
        )
    assert result.status == "timeout_no_result"
    # All-WAIT fallback bundle.
    distinct = [len(set(tp.cells)) for tp in result.plan.paths.values() if tp]
    assert all(d == 1 for d in distinct)


def test_decision_tree_segfault_clean_exit_code():
    """rc=139 (SIGSEGV) + no plan -> 'error', error_msg captures rc/stderr."""
    w = _ProbeWrapper()
    with mock.patch("subprocess.run") as run:
        run.return_value = mock.Mock(
            stdout="", stderr="Segmentation fault\n", returncode=139,
        )
        result = w._wrap_subprocess(
            cmd=["/usr/bin/true"], timeout_s=1.0,
            parse_fn=_make_wait_paths_fn(None),
            agents=_agents_one(), active_agents=[0],
            start_step=0, horizon=2,
        )
    assert result.status == "error"
    assert "139" in result.error_msg or "Segmentation" in result.error_msg


# ---------------------------------------------------------------------------
# Group 4 — binary_not_found
# ---------------------------------------------------------------------------


def test_binary_not_found_path():
    """Pre-flight binary-existence check fires with descriptive error."""
    w = _ProbeWrapper()
    fake_binary = "/nonexistent/path/to/solver_binary_xyz"
    result = w._wrap_subprocess(
        cmd=[fake_binary], timeout_s=1.0,
        parse_fn=_make_wait_paths_fn(None),
        agents=_agents_one(), active_agents=[0],
        start_step=0, horizon=2,
        binary_path=fake_binary,
    )
    assert result.status == "binary_not_found"
    assert fake_binary in result.error_msg
    assert math.isnan(result.solver_wall_ms)


# ---------------------------------------------------------------------------
# Group 5 — legacy plan() shim agreement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory_name", SOLVER_FACTORY_NAMES)
def test_legacy_plan_shim_returns_same_bundle(env_5x5, factory_name: str):
    """``solver.plan(...)`` must equal ``solver.plan_with_metadata(...).plan``
    for every wrapper.  Skip when binary is missing — the shim still
    returns the all-WAIT bundle from binary_not_found in both paths,
    so equality holds, but assertion-on-content matters only when the
    binary is functional."""
    solver = GlobalPlannerFactory.create(factory_name, time_limit_sec=1.0)
    binary_path = getattr(solver, "binary_path", None)
    if binary_path is None or not os.path.isfile(binary_path):
        pytest.skip(f"{factory_name}: binary not present at {binary_path!r}")
    agents, assignments = _two_agent_instance()
    bundle_via_shim = solver.plan(
        env=env_5x5, agents=agents, assignments=assignments,
        step=0, horizon=10, rng=None,
    )
    bundle_via_metadata = solver.plan_with_metadata(
        env=env_5x5, agents=agents, assignments=assignments,
        step=0, horizon=10, rng=None,
    ).plan
    assert isinstance(bundle_via_shim, PlanBundle)
    assert isinstance(bundle_via_metadata, PlanBundle)
    # Same agent-id keyset.  We do NOT assert that the path *contents*
    # are identical — solvers with internal randomness (LaCAM, PIBT2)
    # may produce different paths across two independent calls even
    # with the same instance.
    assert set(bundle_via_shim.paths.keys()) == set(bundle_via_metadata.paths.keys())


# ---------------------------------------------------------------------------
# Group 6 — RollingHorizonPlanner integration: status drives Metrics
# ---------------------------------------------------------------------------


class _MockSolver:
    """Solver whose ``plan_with_metadata`` cycles through a fixed
    sequence of statuses across calls.  Enough surface to satisfy
    ``RollingHorizonPlanner.step``."""

    def __init__(self, statuses: Sequence[str], horizon: int = 10):
        self._statuses = list(statuses)
        self._call_idx = 0
        self.horizon = horizon

    def _build_plan(self, agents, status, step) -> PlanBundle:
        # complete / partial_anytime: real movement (1-step delta);
        # otherwise all-WAIT.
        if status in ("complete", "partial_anytime"):
            paths = {
                aid: TimedPath(cells=[a.pos, (a.pos[0] + 1, a.pos[1])] +
                                     [(a.pos[0] + 1, a.pos[1])] * (self.horizon - 1),
                               start_step=step)
                for aid, a in agents.items()
            }
        else:
            paths = {
                aid: TimedPath(cells=[a.pos] * (self.horizon + 1), start_step=step)
                for aid, a in agents.items()
            }
        return PlanBundle(paths=paths, created_step=step, horizon=self.horizon)

    def plan_with_metadata(self, env, agents, assignments, step, horizon, rng=None):
        status = self._statuses[min(self._call_idx, len(self._statuses) - 1)]
        self._call_idx += 1
        plan = self._build_plan(agents, status, step)
        return SolverResult(
            plan=plan, status=status,
            solver_wall_ms=10.0, end_to_end_wall_ms=12.0,
        )

    def plan(self, env, agents, assignments, step, horizon, rng=None):
        return self.plan_with_metadata(env, agents, assignments, step, horizon, rng).plan


def test_rolling_horizon_status_dispatch(tmp_path: Path):
    """5-tick simulation with mock solver returning
    [complete, complete, partial_anytime, timeout_no_result, complete]
    must produce: solver_timeouts == 1, solver_partial_returns == 1,
    solver_errors == 0."""
    from ha_lmapf.core.types import SimConfig
    from ha_lmapf.simulation.simulator import Simulator

    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    cfg = SimConfig(
        map_path=str(p),
        seed=0,
        steps=5,
        num_agents=2,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",   # placeholder; we'll inject the mock below
        solver_timeout_s=1.0,
        replan_every=1,        # replan every tick so all 5 statuses fire
        horizon=10,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    sim = Simulator(cfg)
    mock_solver = _MockSolver(
        statuses=["complete", "complete", "partial_anytime",
                  "timeout_no_result", "complete"],
        horizon=cfg.horizon,
    )
    sim.global_planner.solver = mock_solver
    metrics = sim.run()

    assert metrics.solver_partial_returns == 1, (
        f"expected 1 partial; got {metrics.solver_partial_returns}"
    )
    assert metrics.solver_timeouts == 1, (
        f"expected 1 timeout; got {metrics.solver_timeouts}"
    )
    assert metrics.solver_errors == 0, (
        f"expected 0 errors; got {metrics.solver_errors}"
    )
