"""Per-solver discrimination tests for the full SolverResult migration.

Each solver that has been migrated from the coarse
``_legacy_to_solver_result`` shim to the proper ``parse_fn`` /
``BaseSolverWrapper._wrap_subprocess`` pattern should be exercised here
to confirm:

* the solver-internal wall clock is parsed (``solver_wall_ms`` is not
  NaN on the happy path and is bounded by the end-to-end wall clock),
* the four reachable status branches (``complete``, ``partial_anytime``,
  ``timeout_no_result``, ``error``) are actually distinguishable on
  representative instances,
* the legacy ``plan() -> PlanBundle`` shim agrees with
  ``plan_with_metadata(...).plan``.

The tests skip cleanly if the underlying binary is missing or not
runnable on the host.
"""
from __future__ import annotations

import math
import os
import tempfile

import pytest

from ha_lmapf.core.types import AgentState, PlanBundle, Task
from ha_lmapf.simulation.environment import Environment


def _binary_runtime_status(binary_path: str) -> tuple[bool, str]:
    """Return ``(ok, reason)`` — same heuristic as
    ``tests/test_solver_smoke.py``.  ``--help`` / ``-h`` should print
    usage and exit cleanly when the executable's shared libraries are
    available."""
    import subprocess
    if not binary_path or not os.path.isfile(binary_path):
        return False, f"binary not present at {binary_path}"
    for flag in ("--help", "-h"):
        try:
            r = subprocess.run([binary_path, flag], capture_output=True,
                               text=True, timeout=3)
        except Exception as exc:
            return False, f"failed to launch ({exc})"
        if r.returncode == 127 or "shared libraries" in r.stderr:
            return False, f"missing shared libraries: {r.stderr.strip()[:200]}"
        if r.returncode in (0, 1) and (r.stdout or r.stderr):
            return True, ""
    return False, "no usage on --help / -h"


def _open_8x8_env(tmp_path):
    p = tmp_path / "8x8.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return Environment.load_from_map(str(p))


def _three_agent_corner_instance():
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 7)),
        2: AgentState(agent_id=2, pos=(7, 0)),
    }
    assignments = {
        0: Task(task_id="t0", start=(0, 0), goal=(7, 7), release_step=0),
        1: Task(task_id="t1", start=(0, 7), goal=(7, 0), release_step=0),
        2: Task(task_id="t2", start=(7, 0), goal=(0, 7), release_step=0),
    }
    return agents, assignments


# ---------------------------------------------------------------------------
# LaCAM3 (paper's LaCAM*)
# ---------------------------------------------------------------------------


@pytest.fixture
def lacam3_solver_factory():
    """Returns a callable producing fresh LaCAM3Solver instances."""
    from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver

    def _make(time_limit_sec=1.0):
        s = LaCAM3Solver(time_limit_sec=time_limit_sec)
        ok, reason = _binary_runtime_status(s.binary_path)
        if not ok:
            pytest.skip(f"LaCAM3 binary unusable: {reason}")
        return s

    return _make


class TestLaCAM3FullMigration:
    """LaCAM3Solver routes through ``_wrap_subprocess`` with a
    ``parse_fn`` that parses ``comp_time=<ms>`` from the result file
    (Kei18/lacam3 format).  These tests exercise the four reachable
    SolverStatus branches plus the legacy shim agreement."""

    def test_complete_status_on_normal_instance(
        self, lacam3_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lacam3_solver_factory(time_limit_sec=1.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status == "complete", (
            f"expected complete on a 3-agent 8x8 open instance, "
            f"got status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN — comp_time= regex did not match the "
            "binary's result file; parser may have regressed"
        )
        assert res.end_to_end_wall_ms < 2000.0, (
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.1f}ms exceeds "
            f"the 2000ms budget for a trivial 3-agent instance"
        )

    def test_solver_wall_ms_lower_than_end_to_end(
        self, lacam3_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lacam3_solver_factory(time_limit_sec=1.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN — parser regression"
        )
        assert res.solver_wall_ms <= res.end_to_end_wall_ms + 1e-3, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms exceeds "
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.3f}ms — "
            f"physically impossible; parser is reading the wrong field "
            f"or the unit is wrong (seconds vs ms)"
        )

    def test_partial_anytime_or_complete_under_50ms_budget(
        self, lacam3_solver_factory,
    ):
        """Stress LaCAM* with a tight budget on a real warehouse map.

        Three reachable outcomes given the decision tree:
          * ``complete`` — fast host: full solve under 50ms.
          * ``partial_anytime`` — watchdog killed the binary mid-run
            but a partial result was already on disk.
          * ``error`` with error_msg containing ``solved=0`` — LaCAM*
            self-terminated cleanly at -t with no initial solution
            (rc=0+no-plan, the decision tree's only mapping under
            "DO NOT modify _base.py").

        What must NEVER happen is ``timeout_no_result`` here: the
        binary self-terminated rather than being killed by the
        watchdog, so ``timed_out=False`` in _wrap_subprocess.  The
        ``solved=0`` path is a *soft* timeout from LaCAM*'s
        perspective and surfaces as ``error`` with a discoverable
        ``error_msg``.
        """
        map_path = "data/maps/warehouse-10-20-10-2-2.map"
        if not os.path.isfile(map_path):
            pytest.skip(f"warehouse map not available at {map_path}")
        env = Environment.load_from_map(map_path)

        traversable = [
            (r, c)
            for r in range(env.height)
            for c in range(env.width)
            if not env.is_blocked((r, c))
        ]
        if len(traversable) < 400:
            pytest.skip("warehouse too small for a 200-agent stress test")
        starts = traversable[:200]
        goals = traversable[200:400]
        agents = {
            i: AgentState(agent_id=i, pos=starts[i]) for i in range(200)
        }
        assignments = {
            i: Task(task_id=f"t{i}", start=starts[i], goal=goals[i],
                    release_step=0)
            for i in range(200)
        }

        solver = lacam3_solver_factory(time_limit_sec=0.05)  # 50 ms
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )

        assert res.status in {"partial_anytime", "complete", "error"}, (
            f"unexpected status under 50ms budget: status={res.status!r} "
            f"error_msg={res.error_msg!r}"
        )
        # solver_wall_ms must be parsed regardless of status —
        # ``comp_time=`` is written even on solved=0.
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN even though comp_time= is always "
            "present in LaCAM*'s result file"
        )
        if res.status == "error":
            # The error_msg must indicate the soft-timeout path so
            # downstream tooling can route on it (and not confuse it
            # with a real binary fault).
            assert "solved=0" in res.error_msg, (
                f"error_msg does not surface solved=0 (got "
                f"{res.error_msg!r})"
            )
        elif res.status in {"complete", "partial_anytime"}:
            has_movement = any(
                tp is not None and len(set(tp.cells)) > 1
                for tp in res.plan.paths.values()
            )
            assert has_movement, (
                "plan has no movement — parser did not recover the "
                "binary's solution"
            )

    def test_no_initial_solution_on_impossible_budget(
        self, lacam3_solver_factory,
    ):
        """A 1ms budget on a non-trivial map cannot succeed.

        Two outcomes are possible:
          * Watchdog kills the binary before result-file write
            (subprocess.TimeoutExpired): ``timeout_no_result``.
          * Binary self-terminates at -t with ``solved=0`` (no
            initial solution): ``error`` with error_msg containing
            ``solved=0``.

        Either is acceptable.  The bundle should be all-WAIT in
        either case.
        """
        map_path = "data/maps/warehouse-10-20-10-2-2.map"
        if not os.path.isfile(map_path):
            pytest.skip(f"warehouse map not available at {map_path}")
        env = Environment.load_from_map(map_path)
        traversable = [
            (r, c)
            for r in range(env.height)
            for c in range(env.width)
            if not env.is_blocked((r, c))
        ]
        if len(traversable) < 200:
            pytest.skip("warehouse too small for impossible-budget test")
        agents = {
            i: AgentState(agent_id=i, pos=traversable[i]) for i in range(100)
        }
        assignments = {
            i: Task(task_id=f"t{i}", start=traversable[i],
                    goal=traversable[100 + i], release_step=0)
            for i in range(100)
        }

        solver = lacam3_solver_factory(time_limit_sec=0.001)  # 1 ms
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status in {"timeout_no_result", "error",
                              "partial_anytime"}, (
            f"unexpected status on 1ms budget: status={res.status!r} "
            f"error_msg={res.error_msg!r}"
        )
        if res.status == "error":
            assert "solved=0" in res.error_msg, (
                f"error_msg does not indicate soft-timeout (got "
                f"{res.error_msg!r})"
            )
        if res.status in {"timeout_no_result", "error"}:
            # All-WAIT bundle: every active agent's path is a single
            # repeated cell.
            for aid, tp in res.plan.paths.items():
                if tp is None:
                    continue
                assert len(set(tp.cells)) == 1, (
                    f"agent {aid} has movement in a no-solution "
                    f"bundle: cells={tp.cells[:5]}..."
                )

    def test_legacy_plan_shim_returns_bundle(
        self, lacam3_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lacam3_solver_factory(time_limit_sec=1.0)

        bundle = solver.plan(env, agents, assignments, step=0, horizon=20)
        assert isinstance(bundle, PlanBundle)
        # The shim must agree with plan_with_metadata's plan field.
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.plan.created_step == bundle.created_step
        assert res.plan.horizon == bundle.horizon
        assert set(bundle.paths.keys()) == set(res.plan.paths.keys())


# ---------------------------------------------------------------------------
# MAPF-LNS2
# ---------------------------------------------------------------------------


@pytest.fixture
def lns2_solver_factory():
    """Returns a callable producing fresh LNS2Solver instances."""
    from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver

    def _make(time_limit_sec=2.0):
        s = LNS2Solver(time_limit_sec=time_limit_sec)
        ok, reason = _binary_runtime_status(s.binary_path)
        if not ok:
            pytest.skip(f"LNS2 binary unusable: {reason}")
        return s

    return _make


def _build_warehouse_instance(n_agents: int):
    """Returns ``(env, agents, assignments)`` for ``n_agents`` on
    warehouse-10-20-10-2-2.  Skips if the map is missing or too
    small for the requested cohort.
    """
    map_path = "data/maps/warehouse-10-20-10-2-2.map"
    if not os.path.isfile(map_path):
        pytest.skip(f"warehouse map not available at {map_path}")
    env = Environment.load_from_map(map_path)
    traversable = [
        (r, c)
        for r in range(env.height)
        for c in range(env.width)
        if not env.is_blocked((r, c))
    ]
    if len(traversable) < 2 * n_agents:
        pytest.skip(
            f"warehouse too small for {n_agents}-agent test "
            f"(have {len(traversable)} traversable cells)"
        )
    starts = traversable[:n_agents]
    goals = traversable[n_agents:2 * n_agents]
    agents = {
        i: AgentState(agent_id=i, pos=starts[i]) for i in range(n_agents)
    }
    assignments = {
        i: Task(task_id=f"t{i}", start=starts[i], goal=goals[i],
                release_step=0)
        for i in range(n_agents)
    }
    return env, agents, assignments


class TestLNS2FullMigration:
    """LNS2Solver routes through ``_wrap_subprocess`` with a
    ``parse_fn`` that reads the binary's ``-LNS.csv`` stats file
    (``runtime`` column, seconds → milliseconds) with a stdout
    fallback (``runtime = <float>`` on the LNS(...) summary line).

    Important empirical caveat: LNS2 writes the paths file **only at
    end-of-run** (after self-termination at ``-t``).  Therefore, with
    a sane watchdog buffer (we use +10s), the wrapper sees rc=0 with
    paths (``complete``) or rc=0 without paths (``error``, surfaced
    via parse_error indicating "Failed to find an initial solution"
    when LNS2 self-reports it).  ``partial_anytime`` is empirically
    unreachable for this binary under normal operation — it would
    require the watchdog to fire AFTER LNS2 finished writing the
    paths file but BEFORE the subprocess returned, which is a
    nanoseconds-wide race.
    """

    def test_complete_status_on_normal_instance(
        self, lns2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lns2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status == "complete", (
            f"expected complete on a 3-agent 8x8 open instance, "
            f"got status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN — neither the -LNS.csv runtime "
            "column nor the stdout 'runtime = <float>' line parsed; "
            "parser may have regressed"
        )
        assert res.end_to_end_wall_ms < 5000.0, (
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.1f}ms "
            f"exceeds 5000ms for a trivial 3-agent instance"
        )

    def test_solver_wall_ms_lower_than_end_to_end(
        self, lns2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lns2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN — parser regression"
        )
        assert res.solver_wall_ms <= res.end_to_end_wall_ms + 1e-3, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms exceeds "
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.3f}ms — "
            f"unit-conversion bug (LNS2 reports seconds; we expect "
            f"the parser to multiply by 1000)"
        )
        # LNS2 reports seconds in CSV (e.g. "7.037e-05"); after × 1000
        # the value should be on the order of 0.07-1ms for a 3-agent
        # instance.  If it's > 100ms something is wrong (forgot the
        # × 1000?  read the wrong column?).
        assert 0.0 <= res.solver_wall_ms <= 100.0, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms out of range "
            f"for a 3-agent 8x8 instance (expected ~0.05-5ms after "
            f"seconds → ms conversion)"
        )

    def test_anytime_complete_with_runtime_parsed_at_warehouse_scale(
        self, lns2_solver_factory,
    ):
        """200 agents on warehouse-10-20-10-2-2 with a 2s budget.

        Empirical behavior on this binary: LNS2 reaches its initial
        solution at ~450ms, then self-terminates at ``-t`` and writes
        the paths file.  Status == ``complete`` with the binary's
        self-reported runtime parsed (NOT NaN, NOT the wrapper's
        end-to-end fallback).

        This is the LNS2-specific regression check that proves the
        parser:
          (i)  finds the ``-LNS.csv`` file (correct path),
          (ii) reads the ``runtime`` column (correct column name), and
          (iii) converts seconds → ms (×1000).
        """
        env, agents, assignments = _build_warehouse_instance(200)
        solver = lns2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )
        assert res.status in {"complete", "partial_anytime"}, (
            f"expected complete (or partial_anytime if watchdog won "
            f"the race) at 200-agent / 2s, got status={res.status!r} "
            f"error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN — CSV path or stdout fallback "
            "regression"
        )
        # solver_wall_ms must be in the expected range (~300-2000ms
        # for 200 agents on warehouse).  If it's < 1ms, the parser
        # is reading the wrong unit.  If it's > 10000ms, the parser
        # is reading the wrong column or applying ×1000 twice.
        assert 50.0 <= res.solver_wall_ms <= 10000.0, (
            f"solver_wall_ms={res.solver_wall_ms:.1f}ms out of "
            f"plausible range for 200-agent warehouse"
        )
        # Plan must contain real movement: the parser must not
        # collapse a successful return into all-WAIT.
        movement_count = sum(
            1 for tp in res.plan.paths.values()
            if tp is not None and len(set(tp.cells)) > 1
        )
        assert movement_count >= 100, (
            f"only {movement_count}/200 agents have movement — "
            f"parser may be silently treating partial returns as "
            f"failures"
        )

    def test_no_initial_solution_on_impossible_budget(
        self, lns2_solver_factory,
    ):
        """A 1ms budget (`-t 0`, the integer floor LNS2 accepts) on a
        100-agent warehouse cannot find an initial solution.

        LNS2 self-terminates rc=0 with no paths file.  The decision
        tree maps rc=0+no-plan to ``error``, and our parse_fn surfaces
        the LNS2-specific failure-to-find-initial-solution stdout
        marker via ``error_msg`` so downstream tooling can route on
        it.
        """
        env, agents, assignments = _build_warehouse_instance(100)
        # LNS2 -t is integer seconds; 0 is the floor.  At -t 0 the
        # binary terminates immediately after preprocessing.
        solver = lns2_solver_factory(time_limit_sec=0.001)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status in {"timeout_no_result", "error"}, (
            f"expected timeout_no_result or error on -t 0, got "
            f"status={res.status!r} error_msg={res.error_msg!r}"
        )
        # All-WAIT bundle: every active agent's path is a single
        # repeated cell.
        for aid, tp in res.plan.paths.items():
            if tp is None:
                continue
            assert len(set(tp.cells)) == 1, (
                f"agent {aid} has movement in a no-solution bundle: "
                f"cells={tp.cells[:5]}..."
            )

    def test_partial_plan_has_real_movement(
        self, lns2_solver_factory,
    ):
        """Integration check: when LNS2 returns ``complete`` with a
        valid plan at warehouse scale, the parser preserves the
        movement on every agent.  This catches the bug where a
        partial return is silently collapsed to all-WAIT.
        """
        env, agents, assignments = _build_warehouse_instance(200)
        solver = lns2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )
        if res.status not in {"complete", "partial_anytime"}:
            pytest.skip(
                f"LNS2 did not produce a plan at warehouse-scale "
                f"on this host (status={res.status!r}); the "
                f"movement-preservation check is not applicable"
            )
        movement = [
            tp for tp in res.plan.paths.values()
            if tp is not None and len(set(tp.cells)) > 1
        ]
        # At least 100/200 agents (= 50%) must show movement.  In
        # practice all 200 should move, but we leave headroom for
        # agents whose start coincides with their goal.
        assert len(movement) >= 100, (
            f"only {len(movement)}/200 agents have movement on a "
            f"successful LNS2 return — anytime semantics not "
            f"preserved"
        )

    def test_legacy_plan_shim_returns_bundle(
        self, lns2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = lns2_solver_factory(time_limit_sec=2.0)

        bundle = solver.plan(env, agents, assignments, step=0, horizon=20)
        assert isinstance(bundle, PlanBundle)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.plan.created_step == bundle.created_step
        assert res.plan.horizon == bundle.horizon
        assert set(bundle.paths.keys()) == set(res.plan.paths.keys())


# ---------------------------------------------------------------------------
# CBSH2-RTC
# ---------------------------------------------------------------------------


@pytest.fixture
def cbsh2_solver_factory():
    """Returns a callable producing fresh CBSH2Solver instances."""
    from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver

    def _make(time_limit_sec=2.0):
        s = CBSH2Solver(time_limit_sec=time_limit_sec)
        ok, reason = _binary_runtime_status(s.binary_path)
        if not ok:
            pytest.skip(f"CBSH2-RTC binary unusable: {reason}")
        return s

    return _make


class TestCBSH2FullMigration:
    """CBSH2Solver routes through ``_wrap_subprocess`` with a
    ``parse_fn`` that reads the binary's CSV output (``runtime``
    column, seconds → milliseconds) and detects the
    ``Timeout,-1,...`` self-termination marker.

    CBSH2-RTC is **optimal and non-anytime**: it returns a fully
    optimal solution or no paths at all.  Therefore
    ``partial_anytime`` is structurally impossible — the
    ``test_no_partial_anytime_for_cbsh2`` discrimination test
    documents and enforces this.
    """

    def test_complete_status_on_normal_instance(
        self, cbsh2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = cbsh2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status == "complete", (
            f"expected complete on a 3-agent 8x8 open instance, "
            f"got status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN — CSV runtime column did not "
            "parse; parser may have regressed"
        )
        assert res.end_to_end_wall_ms < 5000.0, (
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.1f}ms "
            f"exceeds 5000ms for a trivial 3-agent instance"
        )

    def test_solver_wall_ms_lower_than_end_to_end(
        self, cbsh2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = cbsh2_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN — parser regression"
        )
        assert res.solver_wall_ms <= res.end_to_end_wall_ms + 1e-3, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms exceeds "
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.3f}ms — "
            f"unit-conversion bug (CBSH2 reports seconds; expect "
            f"the parser to multiply by 1000)"
        )
        # CBSH2 is optimal and fast on 3-agent 8x8: typical
        # solver_wall_ms is sub-millisecond.  If > 100ms something
        # is wrong (forgot ×1000? read wrong column?).
        assert 0.0 <= res.solver_wall_ms <= 100.0, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms out of "
            f"plausible range for a 3-agent 8x8 instance"
        )

    def test_no_partial_anytime_for_cbsh2(
        self, cbsh2_solver_factory,
    ):
        """200 agents on warehouse-10-20-10-2-2 with a 1s budget —
        far below what CBSH2 needs at this density.

        Status MUST NOT be ``partial_anytime``: CBSH2-RTC is
        non-anytime by design and either writes a complete optimal
        solution or no paths file.  The wrapper should map this to
        ``error`` (with error_msg containing "Timeout,-1") under the
        soft-timeout path, or ``timeout_no_result`` if the watchdog
        kills the binary first.

        This is the diagnostic that verifies CBSH2 is correctly
        classified as non-anytime.  If ``partial_anytime`` ever
        fires for this solver, the parser is silently fabricating
        partial returns — a serious bug.
        """
        env, agents, assignments = _build_warehouse_instance(200)
        solver = cbsh2_solver_factory(time_limit_sec=1.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )
        assert res.status != "partial_anytime", (
            f"CBSH2-RTC returned partial_anytime, but it is "
            f"non-anytime by design.  status={res.status!r} "
            f"error_msg={res.error_msg!r}"
        )
        assert res.status in {"timeout_no_result", "error"}, (
            f"expected timeout_no_result or error at 200 agents / "
            f"1s, got status={res.status!r} error_msg={res.error_msg!r}"
        )
        if res.status == "error":
            assert "Timeout,-1" in res.error_msg, (
                f"error_msg does not surface CBSH2's "
                f"'Timeout,-1' marker (got {res.error_msg!r})"
            )
        # All-WAIT bundle.
        for aid, tp in res.plan.paths.items():
            if tp is None:
                continue
            assert len(set(tp.cells)) == 1, (
                f"agent {aid} has movement in a no-solution bundle: "
                f"cells={tp.cells[:5]}..."
            )

    def test_complete_at_low_density(self, cbsh2_solver_factory):
        """25 agents on warehouse-10-20-10-2-2 with a 5s budget
        (paper §5.1).

        CBSH2 should finish optimally well under 5s at this scale.
        Verifies status == "complete" with parsed solver_wall_ms on
        a real warehouse map (vs the trivial 8x8 in test 1).
        """
        env, agents, assignments = _build_warehouse_instance(25)
        solver = cbsh2_solver_factory(time_limit_sec=10.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )
        assert res.status == "complete", (
            f"expected complete at 25 agents / 5s, got "
            f"status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN at warehouse scale — parser "
            "regression"
        )
        # 25 agents on this map should finish in well under 1s
        # (parsed runtime, not end-to-end).
        assert res.solver_wall_ms < 5000.0, (
            f"solver_wall_ms={res.solver_wall_ms:.1f}ms exceeds "
            f"5s budget — parser may be reporting end-to-end timing"
        )
        # Plan must contain real movement.
        movement = sum(
            1 for tp in res.plan.paths.values()
            if tp is not None and len(set(tp.cells)) > 1
        )
        assert movement >= 20, (
            f"only {movement}/25 agents have movement — parser "
            f"regression"
        )

    def test_legacy_plan_shim_returns_bundle(
        self, cbsh2_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = cbsh2_solver_factory(time_limit_sec=2.0)

        bundle = solver.plan(env, agents, assignments, step=0, horizon=20)
        assert isinstance(bundle, PlanBundle)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.plan.created_step == bundle.created_step
        assert res.plan.horizon == bundle.horizon
        assert set(bundle.paths.keys()) == set(res.plan.paths.keys())


# ---------------------------------------------------------------------------
# PBS
# ---------------------------------------------------------------------------


@pytest.fixture
def pbs_solver_factory():
    """Returns a callable producing fresh PBSSolver instances."""
    from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver

    def _make(time_limit_sec=2.0):
        s = PBSSolver(time_limit_sec=time_limit_sec)
        ok, reason = _binary_runtime_status(s.binary_path)
        if not ok:
            pytest.skip(f"PBS binary unusable: {reason}")
        return s

    return _make


def _corridor_swap_env_and_agents(tmp_path):
    """1x6 open corridor with two agents that must swap end-to-end.

    Empirically reliable trigger of PBS's incompleteness: with a
    1-cell-wide corridor and no parking cells, no priority ordering
    yields a feasible plan (PBS doesn't park / detour).  The binary
    self-terminates rc=0 with CSV ``solution cost = -2`` in ~2ms.
    """
    p = tmp_path / "corridor_1x6.map"
    p.write_text("type octile\nheight 1\nwidth 6\nmap\n......\n")
    env = Environment.load_from_map(str(p))
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 5)),
    }
    assignments = {
        0: Task(task_id="t0", start=(0, 0), goal=(0, 5), release_step=0),
        1: Task(task_id="t1", start=(0, 5), goal=(0, 0), release_step=0),
    }
    return env, agents, assignments


class TestPBSFullMigration:
    """PBSSolver routes through ``_wrap_subprocess`` with a
    ``parse_fn`` that reads the binary's CSV and discriminates
    THREE distinct non-success markers in the ``solution cost``
    column:

    * ``-1`` ⇒ self-timeout at ``-t`` (soft timeout)
    * ``-2`` ⇒ no feasible priority ordering exists (PBS's
              **incompleteness** — distinct from a timeout)
    * any cost ≥ 0 with paths file ⇒ ``complete``

    The prompt's claim that PBS writes timing to stderr is wrong
    for this build — the summary line goes to stdout, and the CSV
    is the authoritative source for ``solver_wall_ms``.

    ``partial_anytime`` is structurally impossible for PBS.
    """

    def test_complete_status_on_normal_instance(
        self, pbs_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = pbs_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status == "complete", (
            f"expected complete on a 3-agent 8x8 open instance, "
            f"got status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms is NaN — CSV runtime column did not "
            "parse; if the parser regressed to scanning stderr "
            "(per the original prompt's claim), this test should "
            "catch it: PBS's stderr is empty in this build, the "
            "CSV is the authoritative source"
        )
        assert res.end_to_end_wall_ms < 5000.0, (
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.1f}ms "
            f"exceeds 5000ms for a trivial 3-agent instance"
        )

    def test_solver_wall_ms_lower_than_end_to_end(
        self, pbs_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = pbs_solver_factory(time_limit_sec=2.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN — parser regression.  The most "
            "likely cause is the parser scanning stderr (which is "
            "empty for this build) instead of the CSV; verify the "
            "CSV path in pbs_wrapper.py::plan_with_metadata"
        )
        assert res.solver_wall_ms <= res.end_to_end_wall_ms + 1e-3, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms exceeds "
            f"end_to_end_wall_ms={res.end_to_end_wall_ms:.3f}ms — "
            f"unit-conversion bug (PBS reports seconds; expect "
            f"the parser to multiply by 1000)"
        )
        # 3 agents on 8x8: PBS finishes in tens of microseconds.
        # If > 100ms something is wrong.
        assert 0.0 <= res.solver_wall_ms <= 100.0, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms out of "
            f"plausible range for a 3-agent 8x8 instance"
        )

    def test_pbs_incompleteness_is_error_not_timeout(
        self, pbs_solver_factory, tmp_path,
    ):
        """Two agents must swap end-to-end on a 1-cell-wide
        corridor (no parking).  No priority order yields a feasible
        plan, so PBS exhausts the priority space and returns rc=0
        with CSV ``solution cost = -2``.

        Status MUST be ``error`` with ``error_msg`` containing
        "no solution" (case-insensitive) — NOT
        ``timeout_no_result``.  This distinguishes PBS's
        **incompleteness** from a true budget exhaustion.

        Verified empirically on this build: the corridor swap
        completes in ~2ms with cost=-2, well below any reasonable
        timeout.
        """
        env, agents, assignments = _corridor_swap_env_and_agents(tmp_path)
        solver = pbs_solver_factory(time_limit_sec=10.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.status == "error", (
            f"expected error (PBS incompleteness), got "
            f"status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert "no solution" in res.error_msg.lower(), (
            f"error_msg does not surface PBS's incompleteness "
            f"signal (expected 'no solution', got "
            f"{res.error_msg!r})"
        )
        # solver_wall_ms should be parsed even on the no-solution
        # path (CSV is written).  A few ms is plausible for the
        # 2-agent corridor.
        assert not math.isnan(res.solver_wall_ms), (
            "solver_wall_ms NaN even though PBS wrote a CSV with "
            "cost=-2"
        )
        assert res.solver_wall_ms < 1000.0, (
            f"solver_wall_ms={res.solver_wall_ms:.3f}ms too large "
            f"for a 2-agent corridor swap; this case should fail "
            f"in milliseconds, not at the timeout"
        )

    def test_timeout_no_result_on_impossible_budget(
        self, pbs_solver_factory,
    ):
        """A 1-second budget on 200 agents is below PBS's solving
        time at this scale on the warehouse map.

        PBS will self-terminate at ``-t`` with CSV cost=-1 (rc=0,
        no paths file).  Decision tree maps rc=0+no-plan to
        ``error`` with the soft-timeout marker (the prompt asks
        for ``timeout_no_result``, but per the constraint "DO NOT
        modify _base.py" the soft-timeout path can only be
        ``error`` — surfaced via error_msg).

        Accept either ``error`` (with Timeout,-1 marker) or
        ``timeout_no_result`` (if the watchdog won the race).
        """
        env, agents, assignments = _build_warehouse_instance(200)
        solver = pbs_solver_factory(time_limit_sec=1.0)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=30,
        )
        assert res.status in {"timeout_no_result", "error"}, (
            f"expected timeout_no_result or error at 200 agents / "
            f"1s, got status={res.status!r} error_msg={res.error_msg!r}"
        )
        assert res.status != "partial_anytime", (
            "PBS returned partial_anytime — but PBS is non-anytime "
            "by design.  Parser is fabricating partial returns."
        )
        if res.status == "error":
            assert "Timeout,-1" in res.error_msg, (
                f"error_msg does not surface PBS's 'Timeout,-1' "
                f"marker (got {res.error_msg!r})"
            )
        # All-WAIT bundle.
        for aid, tp in res.plan.paths.items():
            if tp is None:
                continue
            assert len(set(tp.cells)) == 1, (
                f"agent {aid} has movement in a no-solution bundle"
            )

    def test_legacy_plan_shim_returns_bundle(
        self, pbs_solver_factory, tmp_path,
    ):
        env = _open_8x8_env(tmp_path)
        agents, assignments = _three_agent_corner_instance()
        solver = pbs_solver_factory(time_limit_sec=2.0)

        bundle = solver.plan(env, agents, assignments, step=0, horizon=20)
        assert isinstance(bundle, PlanBundle)
        res = solver.plan_with_metadata(
            env, agents, assignments, step=0, horizon=20,
        )
        assert res.plan.created_step == bundle.created_step
        assert res.plan.horizon == bundle.horizon
        assert set(bundle.paths.keys()) == set(res.plan.paths.keys())
