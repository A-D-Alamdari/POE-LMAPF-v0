"""
Previous-plan reuse contract for ``RollingHorizonPlanner``.

When the global solver returns ``error`` / ``binary_not_found`` /
``timeout_no_result``, the rolling-horizon planner must re-anchor the
last successful ``PlanBundle`` to ``cur_step`` instead of returning the
all-WAIT bundle that ``_base.py::_wrap_subprocess`` packages with the
failure.  These tests exercise that contract directly with a mock
solver — no C++ binary is required.

Also asserts the no-downgrade invariant: a reused plan is still a
solver failure.  ``Metrics.solver_errors`` (or ``solver_timeouts``)
ticks on every failed solve, in addition to
``Metrics.solver_fallback_reuses``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.core.types import (
    AgentState,
    PlanBundle,
    SolverResult,
    SolverStatus,
    Task,
    TimedPath,
)
from ha_lmapf.global_tier.rolling_horizon import RollingHorizonPlanner


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


def _move_path(start: Tuple[int, int], horizon: int,
               step: int, vec: Tuple[int, int] = (0, 1)) -> TimedPath:
    """Build a straight-line path of length ``horizon + 1`` from
    ``start`` along ``vec``."""
    r, c = start
    dr, dc = vec
    cells = [(r + dr * k, c + dc * k) for k in range(horizon + 1)]
    return TimedPath(cells=cells, start_step=step)


class ScriptedSolver:
    """Mock ``GlobalPlanner`` that replays a fixed list of statuses.

    On status ``complete`` / ``partial_anytime`` it returns a
    deterministic "march east" plan rooted at each agent's current
    position so the re-anchor logic has something predictable to
    consume.  On any failure status it returns the all-WAIT bundle the
    real wrappers would build, mimicking
    ``_base.py::_wrap_subprocess`` exactly.
    """

    def __init__(self, statuses: List[SolverStatus]) -> None:
        self._statuses = list(statuses)
        self.calls: int = 0

    def plan_with_metadata(
            self,
            env: Any,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng: Any,
    ) -> SolverResult:
        status = self._statuses[self.calls] if self.calls < len(self._statuses) \
            else "complete"
        self.calls += 1

        if status in ("complete", "partial_anytime"):
            paths = {aid: _move_path(a.pos, horizon, step)
                     for aid, a in agents.items()}
            return SolverResult(
                plan=PlanBundle(paths=paths, created_step=step, horizon=horizon),
                status=status,
                solver_wall_ms=1.0,
                end_to_end_wall_ms=1.0,
            )

        # Failure branch — return the all-WAIT bundle the production
        # solver wrappers also return on failure.  This is the bundle
        # the planner is *supposed* to ignore in favour of the
        # re-anchored last-good bundle.
        wait_paths = {
            aid: TimedPath(cells=[a.pos] * (horizon + 1), start_step=step)
            for aid, a in agents.items()
        }
        return SolverResult(
            plan=PlanBundle(paths=wait_paths, created_step=step,
                            horizon=horizon),
            status=status,
            solver_wall_ms=math.nan,
            end_to_end_wall_ms=0.0,
            error_msg="scripted failure",
        )

    def plan(self, *args, **kwargs):  # pragma: no cover — kept for protocol
        return self.plan_with_metadata(*args, **kwargs).plan


@dataclass
class _MockSimState:
    """Minimal ``SimStateView`` covering only what ``RollingHorizonPlanner.step``
    actually reads."""
    step: int
    agents: Dict[int, AgentState]
    metrics: MetricsTracker
    env: Any = None
    major_deviation: bool = False
    completed_tasks_since_last_plan: int = 0
    _stale: Set[int] = field(default_factory=set)
    _safety_wait: Set[int] = field(default_factory=set)
    humans: Dict[int, Any] = field(default_factory=dict)

    def stale_global_plan_agents(self) -> Set[int]:
        return self._stale

    def safety_wait_agents(self) -> Set[int]:
        return self._safety_wait

    def plans(self) -> Optional[PlanBundle]:  # pragma: no cover
        return None


def _make_agents() -> Dict[int, AgentState]:
    return {
        0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 9)),
        1: AgentState(agent_id=1, pos=(5, 0), goal=(5, 9)),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


REPLAN_EVERY = 5
HORIZON = 10


def _run_step(planner: RollingHorizonPlanner,
              sim_state: _MockSimState) -> Optional[PlanBundle]:
    """Convenience — replan-trigger fires at any step that's a multiple
    of ``REPLAN_EVERY``.  Returns the produced bundle (or ``None`` if
    no trigger fired)."""
    return planner.step(sim_state, assignments={})


def test_reuse_after_complete_then_error() -> None:
    """After N successful solves followed by a failed solve, the
    returned bundle is the re-anchored last good bundle (not the
    all-WAIT bundle the solver wrapper packaged) and the fallback
    counter ticks."""
    statuses: List[SolverStatus] = ["complete", "complete", "error"]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    # First two calls — both "complete".  Plans march east from each
    # agent's start.
    sim.step = 0
    plan0 = _run_step(planner, sim)
    assert plan0 is not None
    assert plan0.created_step == 0
    assert plan0.paths[0].cells[0] == (0, 0)
    assert plan0.paths[0].cells[5] == (0, 5)
    assert planner._last_good_bundle is plan0 or \
        planner._last_good_bundle.paths[0].cells == plan0.paths[0].cells

    sim.step = REPLAN_EVERY
    plan1 = _run_step(planner, sim)
    assert plan1 is not None
    assert plan1.created_step == REPLAN_EVERY
    # plan1's path[0] starts at agent 0's current pos (still (0,0) —
    # the test mock doesn't actually move agents, but the *plan* still
    # marches east).  Important: the stored "last good" snapshot was
    # taken when status was complete, so it should now be plan1.

    # Third call — solver returns "error".  Mock returns an all-WAIT
    # bundle; the planner must REPLACE that with a re-anchored copy
    # of the stored bundle (plan1, shifted by REPLAN_EVERY).
    sim.step = 2 * REPLAN_EVERY
    pre_errors = metrics._solver_errors
    pre_reuses = planner._fallback_reuse_count
    plan2 = _run_step(planner, sim)
    assert plan2 is not None

    # Re-anchor invariants:
    assert plan2.created_step == 2 * REPLAN_EVERY, \
        "re-anchored bundle must report the current step as created_step"
    for aid in (0, 1):
        tp = plan2.paths[aid]
        assert tp is not None
        assert tp.start_step == 2 * REPLAN_EVERY, \
            f"agent {aid} TimedPath must be re-anchored to cur_step"
        assert len(tp.cells) == HORIZON + 1, \
            f"agent {aid} TimedPath must have horizon+1 cells"

    # Re-anchor MUST NOT be the all-WAIT bundle ScriptedSolver
    # returned.  Easiest signature: the first cell of agent 0's
    # re-anchored path is what plan1 prescribed for step 2*REPLAN_EVERY
    # (offset=REPLAN_EVERY into plan1, which marches east).
    expected_first_cell = plan1.paths[0].cells[REPLAN_EVERY]
    assert plan2.paths[0].cells[0] == expected_first_cell, (
        f"expected re-anchored agent 0 cell[0]={expected_first_cell}, "
        f"got {plan2.paths[0].cells[0]} — looks like the all-WAIT bundle "
        f"leaked through instead of the re-anchored last good bundle."
    )

    # The re-anchored bundle must move agents (it is NOT all-WAIT).
    assert len(set(plan2.paths[0].cells)) > 1, \
        "agent 0 re-anchored path collapsed to a single cell (all-WAIT)"

    # Counters.  Reuse counter ticked; error counter ALSO ticked — a
    # reused plan is still a solver failure and must NOT be downgraded.
    assert planner._fallback_reuse_count == pre_reuses + 1
    assert metrics._solver_errors == pre_errors + 1
    assert metrics._solver_fallback_reuses >= 1


def test_reuse_on_timeout_no_result() -> None:
    """``timeout_no_result`` triggers the same reuse path as ``error``
    but ticks ``solver_timeouts`` rather than ``solver_errors``."""
    statuses: List[SolverStatus] = ["complete", "timeout_no_result"]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    sim.step = 0
    plan0 = _run_step(planner, sim)
    assert plan0 is not None

    sim.step = REPLAN_EVERY
    plan1 = _run_step(planner, sim)
    assert plan1 is not None
    assert plan1.paths[0].cells[0] == plan0.paths[0].cells[REPLAN_EVERY], \
        "timeout fallback must reuse the last good bundle, not all-WAIT"
    assert planner._fallback_reuse_count == 1
    assert metrics._solver_timeouts == 1
    assert metrics._solver_errors == 0


def test_first_call_failure_yields_all_wait_with_distinct_warning(
        caplog: pytest.LogCaptureFixture) -> None:
    """If the very first replan fails, there's no prior bundle to
    re-anchor: keep the all-WAIT bundle and emit the
    "no prior bundle; emitting all-WAIT" warning."""
    solver = ScriptedSolver(["error"])
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    with caplog.at_level("WARNING",
                         logger="ha_lmapf.global_tier.rolling_horizon"):
        plan = _run_step(planner, sim)

    assert plan is not None
    # Every agent stationary (all-WAIT bundle preserved).
    for aid, tp in plan.paths.items():
        assert tp is not None
        assert len(set(tp.cells)) == 1, \
            f"agent {aid} should be stationary in all-WAIT bundle"

    assert planner._fallback_reuse_count == 0
    assert metrics._solver_fallback_reuses == 0
    assert metrics._solver_errors == 1

    assert any("no prior bundle" in rec.message for rec in caplog.records), \
        "expected the 'no prior bundle; emitting all-WAIT' warning"


def test_reanchor_per_agent_wait_on_goal_change() -> None:
    """An agent whose goal changed between the stored bundle and the
    failed replan must fall back to WAIT for THAT agent only; agents
    with unchanged goals must still reuse their portion of the plan."""
    statuses: List[SolverStatus] = ["complete", "error"]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    plan0 = _run_step(planner, sim)
    assert plan0 is not None
    expected_agent1_cell = plan0.paths[1].cells[REPLAN_EVERY]

    # Mutate agent 0's goal between the good solve and the failed one.
    agents[0].goal = (9, 9)
    sim.step = REPLAN_EVERY
    plan1 = _run_step(planner, sim)
    assert plan1 is not None

    # Agent 0: goal changed → all-WAIT for this agent (single repeated
    # cell at its current position).
    tp0 = plan1.paths[0]
    assert tp0 is not None
    assert len(set(tp0.cells)) == 1
    assert tp0.cells[0] == agents[0].pos

    # Agent 1: goal unchanged → re-anchored from plan0.
    tp1 = plan1.paths[1]
    assert tp1 is not None
    assert tp1.cells[0] == expected_agent1_cell


def test_reanchor_horizon_length_invariant() -> None:
    """Re-anchored TimedPaths must be exactly ``horizon + 1`` cells —
    same invariant ``_make_all_wait_bundle`` enforces and that
    ``test_receding_horizon_handoff`` implicitly depends on.

    Iteration coverage (HORIZON=10, REPLAN_EVERY=5, stored path has
    11 cells indexed 0..10):

    * k=1 → offset=5  → in-range, tail length 6, **pad** branch.
    * k=2 → offset=10 → in-range, tail length 1, **pad** branch.
    * k=3 → offset=15 → **out-of-range** branch (offset >=
      len(stored.cells)); see
      :func:`test_reanchor_offset_past_stored_path_end` for the
      explicit "parked at final cell" assertion.
    """
    statuses: List[SolverStatus] = ["complete", "error", "error", "error"]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    _run_step(planner, sim)
    for k in (1, 2, 3):
        sim.step = k * REPLAN_EVERY
        plan = _run_step(planner, sim)
        assert plan is not None
        for aid, tp in plan.paths.items():
            assert tp is not None
            assert len(tp.cells) == HORIZON + 1, (
                f"replan {k}: agent {aid} TimedPath length "
                f"{len(tp.cells)} != horizon+1={HORIZON + 1}"
            )
            assert tp.start_step == k * REPLAN_EVERY


def test_reanchor_offset_past_stored_path_end() -> None:
    """When ``cur_step - stored.start_step >= len(stored.cells)`` the
    re-anchored bundle parks every agent at the stored path's final
    cell — NOT at the agent's current position.  Pinning these is
    important: the two look identical only when the agent happens to
    already be at the final cell, and the controllers consume them
    differently downstream.

    Setup: HORIZON=10, REPLAN_EVERY=5, so stored.cells has 11 entries
    (indices 0..10).  On the third failure at cur_step=15 the offset
    is 15 >= 11, exercising the ``elif offset >= len(stored_path.cells)``
    branch in ``_reanchor_last_good``.
    """
    statuses: List[SolverStatus] = ["complete", "error", "error", "error"]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    # Successful first solve at step 0 produces the bundle we'll
    # re-anchor; capture the final cells of every agent's stored path
    # so we can pin the boundary-branch behavior to them specifically
    # (and distinguish from each agent's current pos).
    plan0 = _run_step(planner, sim)
    assert plan0 is not None
    stored_final = {aid: tp.cells[-1] for aid, tp in plan0.paths.items()}
    assert len(plan0.paths[0].cells) == HORIZON + 1
    for aid, agent in agents.items():
        assert stored_final[aid] != agent.pos, (
            f"test setup invariant violated: agent {aid} starts at its "
            f"stored final cell, so 'parked at final' and 'all-WAIT at "
            f"current pos' are indistinguishable."
        )

    # Drive two in-range failure replans first; they exercise the pad
    # branch and are already covered by other tests.
    sim.step = REPLAN_EVERY     # offset = 5
    _run_step(planner, sim)
    sim.step = 2 * REPLAN_EVERY  # offset = 10
    _run_step(planner, sim)

    # The boundary case: offset = 15 > len(stored.cells)=11.
    sim.step = 3 * REPLAN_EVERY
    plan = _run_step(planner, sim)
    assert plan is not None
    assert plan.created_step == 3 * REPLAN_EVERY

    for aid, agent in agents.items():
        tp = plan.paths[aid]
        assert tp is not None
        assert tp.start_step == 3 * REPLAN_EVERY, (
            f"agent {aid} TimedPath must be re-anchored to cur_step"
        )
        assert len(tp.cells) == HORIZON + 1, (
            f"agent {aid} TimedPath length {len(tp.cells)} != "
            f"horizon+1={HORIZON + 1}"
        )
        # The whole path is the agent parked at the stored final cell:
        # exactly one distinct cell, and that cell is stored.cells[-1]
        # (NOT the agent's current pos).
        assert len(set(tp.cells)) == 1, (
            f"agent {aid} should be parked at a single cell at the "
            f"out-of-range boundary; got cells={tp.cells}"
        )
        assert tp.cells[0] == stored_final[aid], (
            f"agent {aid} boundary parking cell {tp.cells[0]} != "
            f"stored final cell {stored_final[aid]} — looks like the "
            f"all-WAIT-at-current-pos fallback engaged instead of the "
            f"'parked at stored final cell' branch."
        )
        assert tp.cells[0] != agent.pos, (
            f"agent {aid} parked at its current pos {agent.pos}, not "
            f"the stored final cell {stored_final[aid]}; the wrong "
            f"branch fired."
        )

    # The reuse counter ticks for all three failures (not just this
    # one).  Errors counter is NOT downgraded — invariant from the
    # parent test.
    assert planner._fallback_reuse_count == 3
    assert metrics._solver_errors == 3
    assert metrics._solver_fallback_reuses == 3


def test_reanchor_no_collision_invariant() -> None:
    """The stored bundle was collision-free at the original step.
    Re-anchoring is a pure slice; the no-collision invariant must
    carry over to the re-anchored bundle for every vertex and edge."""
    solver = ScriptedSolver(["complete", "error"])
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    # Two agents on disjoint rows — the scripted plan is collision-free
    # by construction.  We verify the re-anchored bundle preserves it.
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    _run_step(planner, sim)
    sim.step = REPLAN_EVERY
    plan = _run_step(planner, sim)
    assert plan is not None

    paths = {aid: tp.cells for aid, tp in plan.paths.items() if tp is not None}
    aids = list(paths.keys())
    for t in range(HORIZON + 1):
        positions = {aid: paths[aid][t] for aid in aids}
        # Vertex conflict: two agents at the same cell at the same
        # time.
        assert len(set(positions.values())) == len(positions), (
            f"vertex conflict at t={t}: {positions}"
        )
    for t in range(HORIZON):
        # Edge conflict: agents swapping cells between t and t+1.
        for i, a in enumerate(aids):
            for b in aids[i + 1:]:
                assert not (paths[a][t] == paths[b][t + 1]
                            and paths[b][t] == paths[a][t + 1]), (
                    f"edge conflict between {a} and {b} between t={t} and t={t+1}"
                )


def test_successful_solve_resets_last_good_bundle() -> None:
    """A subsequent ``complete`` after a failure must refresh the
    stored bundle so the next failure re-anchors the *new* plan, not
    the original one."""
    statuses: List[SolverStatus] = [
        "complete", "error", "complete", "error",
    ]
    solver = ScriptedSolver(statuses)
    planner = RollingHorizonPlanner(
        horizon=HORIZON, replan_every=REPLAN_EVERY, solver_impl=solver,
    )
    metrics = MetricsTracker()
    agents = _make_agents()
    sim = _MockSimState(step=0, agents=agents, metrics=metrics)

    sim.step = 0
    _run_step(planner, sim)
    sim.step = REPLAN_EVERY
    _run_step(planner, sim)            # error -> reuse plan@0
    sim.step = 2 * REPLAN_EVERY
    plan2 = _run_step(planner, sim)    # complete -> new last_good
    assert plan2 is not None
    assert planner._last_good_bundle.created_step == 2 * REPLAN_EVERY
    sim.step = 3 * REPLAN_EVERY
    plan3 = _run_step(planner, sim)    # error -> reuse plan@2*REPLAN_EVERY
    assert plan3 is not None
    # Plan3's agent 0 cell[0] should match plan2's offset-REPLAN_EVERY
    # cell, NOT the original plan@0's offset-3*REPLAN_EVERY cell.
    assert plan3.paths[0].cells[0] == plan2.paths[0].cells[REPLAN_EVERY]
    assert planner._fallback_reuse_count == 2
    assert metrics._solver_errors == 2
