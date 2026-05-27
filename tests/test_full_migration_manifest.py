"""Cross-wrapper manifest tests — the integration gate that asserts
every paper-sweep solver is on the **full** SolverResult migration.

These tests are the calibration prompt's prerequisite: if any paper
solver returns ``MIGRATION_DEPTH = "coarse"`` or fails to parse
``solver_wall_ms``, the calibration's
``literature_consistency.md`` / ``anytime_verification.md`` reports
would be missing or NaN-filled and the prompt would have to bail.

Coverage:

* Every ``GlobalPlannerFactory`` paper-sweep wrapper has
  ``MIGRATION_DEPTH == "full"``.
* Every full wrapper returns a ``SolverResult`` with a recognised
  ``status`` from a tiny smoke instance.
* The three anytime solvers (LaCAM3, LNS2, PIBT2) parse a non-NaN
  ``solver_wall_ms`` from their result file / stdout — the parser
  regression check.
* Two consecutive runs of the same instance produce the same status
  (determinism check; ``solver_wall_ms`` is allowed to vary within
  ±50 % to absorb host noise).
"""
from __future__ import annotations

import math
import os
import tempfile
from typing import Dict, List, Tuple, Type

import pytest

from ha_lmapf.core.types import (
    AgentState,
    PlanBundle,
    SolverResult,
    SolverStatus,
    Task,
)
from ha_lmapf.global_tier.solvers._base import BaseSolverWrapper
from ha_lmapf.simulation.environment import Environment


# --- canonical paper-sweep solvers --------------------------------------------
# Map from (factory_string → wrapper_class).  These are the six solvers cited
# in §5.2 Table 1; the migration must be "full" for every one.

PAPER_SOLVERS: List[Tuple[str, str]] = [
    ("lacam_official", "LaCAMOfficialSolver"),
    ("lacam3",         "LaCAM3Solver"),
    ("cbsh2",          "CBSH2Solver"),
    ("lns2",           "LNS2Solver"),
    ("pbs",            "PBSSolver"),
    ("pibt2",          "PIBT2Solver"),
]

# Anytime subset — the parser regression check is mandatory for these.
ANYTIME_SOLVERS = {"lacam_official", "lacam3", "lns2", "pibt2"}


def _make_solver(factory_string: str) -> BaseSolverWrapper:
    from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
    return GlobalPlannerFactory.create(factory_string, time_limit_sec=2.0)


def _binary_runtime_ok(binary_path: str) -> bool:
    """Sanity probe — does the binary launch?"""
    import subprocess
    if not binary_path or not os.path.isfile(binary_path):
        return False
    try:
        r = subprocess.run(
            [binary_path, "--help"], capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return False
    return r.returncode in (0, 1) and "shared libraries" not in (r.stderr or "")


@pytest.fixture
def open_8x8_env(tmp_path):
    p = tmp_path / "8x8.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return Environment.load_from_map(str(p))


def _three_agent_corner_instance() -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    agents = {
        0: AgentState(0, (0, 0)),
        1: AgentState(1, (0, 7)),
        2: AgentState(2, (7, 0)),
    }
    assignments = {
        0: Task("t0", (0, 0), (7, 7), 0),
        1: Task("t1", (0, 7), (7, 0), 0),
        2: Task("t2", (7, 0), (0, 7), 0),
    }
    return agents, assignments


# ---------------------------------------------------------------------------
# 1. Manifest: every paper solver is "full"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory_string,class_name", PAPER_SOLVERS)
def test_all_paper_solvers_are_full_migration(factory_string, class_name):
    """Every paper-sweep solver must declare ``MIGRATION_DEPTH = "full"``.

    The class-level attribute is the source of truth for downstream
    tooling (calibration, claim validation, paper appendix).  A
    ``"coarse"`` here would mean a wrapper has regressed off the
    full-migration contract.
    """
    solver = _make_solver(factory_string)
    assert hasattr(solver, "MIGRATION_DEPTH"), (
        f"{class_name} does not declare MIGRATION_DEPTH; the "
        f"BaseSolverWrapper attribute should be inherited"
    )
    assert solver.MIGRATION_DEPTH == "full", (
        f"{class_name} (factory string {factory_string!r}) has "
        f"MIGRATION_DEPTH = {solver.MIGRATION_DEPTH!r}; paper-sweep "
        f"solvers must be 'full'.  See docs/SOLVER_STATUS.md for the "
        f"per-wrapper migration table."
    )
    assert type(solver).__name__ == class_name, (
        f"factory string {factory_string!r} produced "
        f"{type(solver).__name__}, expected {class_name}"
    )


def test_base_wrapper_default_is_coarse():
    """Ensure the BaseSolverWrapper default remains ``"coarse"`` so a
    new wrapper that forgets to set ``MIGRATION_DEPTH = "full"`` is
    immediately flagged by the manifest tests.
    """
    assert BaseSolverWrapper.MIGRATION_DEPTH == "coarse"


# ---------------------------------------------------------------------------
# 2. Every full wrapper returns a valid SolverResult
# ---------------------------------------------------------------------------


# Pre-defined SolverStatus values — keep in sync with core.types.SolverStatus.
_VALID_STATUSES = {
    "complete",
    "partial_anytime",
    "timeout_no_result",
    "error",
    "binary_not_found",
}


@pytest.mark.parametrize("factory_string,class_name", PAPER_SOLVERS)
def test_all_full_wrappers_return_solver_result(
    factory_string, class_name, open_8x8_env,
):
    """Every full-migration wrapper's ``plan_with_metadata`` returns a
    ``SolverResult`` with one of the five recognised statuses."""
    solver = _make_solver(factory_string)
    if not _binary_runtime_ok(getattr(solver, "binary_path", "")):
        # Wrapper still returns a SolverResult (status=binary_not_found),
        # which is a valid full-migration outcome.  Don't skip — this
        # path is a feature of the contract.
        pass

    agents, assignments = _three_agent_corner_instance()
    res = solver.plan_with_metadata(
        env=open_8x8_env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )
    assert isinstance(res, SolverResult), (
        f"{class_name} returned {type(res).__name__}, expected SolverResult"
    )
    assert res.status in _VALID_STATUSES, (
        f"{class_name} returned unrecognised status {res.status!r}; "
        f"valid: {sorted(_VALID_STATUSES)}"
    )
    assert isinstance(res.plan, PlanBundle), (
        f"{class_name} SolverResult.plan is {type(res.plan).__name__}, "
        f"expected PlanBundle"
    )
    # solver_wall_ms must be a float (NaN allowed for binary-not-found,
    # error, timeout_no_result; checked separately for anytime solvers).
    assert isinstance(res.solver_wall_ms, float)
    assert isinstance(res.end_to_end_wall_ms, float)
    assert res.end_to_end_wall_ms >= 0.0


# ---------------------------------------------------------------------------
# 3. Anytime solvers must parse a non-NaN solver_wall_ms on success
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory_string,class_name", [
    (fs, cn) for fs, cn in PAPER_SOLVERS if fs in ANYTIME_SOLVERS
])
def test_solver_wall_ms_parsed_for_anytime_solvers(
    factory_string, class_name, open_8x8_env,
):
    """Anytime solvers (LaCAM*, LaCAM3, LNS2, PIBT2) must surface their
    binary's self-reported wall clock as ``solver_wall_ms``.  A NaN
    here means the parser silently fell back — exactly the regression
    we want to catch.
    """
    solver = _make_solver(factory_string)
    if not _binary_runtime_ok(getattr(solver, "binary_path", "")):
        pytest.skip(f"{class_name} binary unavailable — cannot test parser")

    agents, assignments = _three_agent_corner_instance()
    res = solver.plan_with_metadata(
        env=open_8x8_env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )

    if res.status not in {"complete", "partial_anytime"}:
        pytest.skip(
            f"{class_name} returned status={res.status!r} on the smoke "
            f"instance; parser-output check requires a successful run"
        )

    assert not math.isnan(res.solver_wall_ms), (
        f"{class_name} returned NaN solver_wall_ms despite "
        f"status={res.status!r} — the per-wrapper parser regressed.  "
        f"See docs/SOLVER_STATUS.md for the expected source per solver."
    )
    # Sanity: the solver's self-reported time must be ≤ end-to-end.
    assert res.solver_wall_ms <= res.end_to_end_wall_ms + 1e-3, (
        f"{class_name} solver_wall_ms={res.solver_wall_ms} exceeds "
        f"end_to_end_wall_ms={res.end_to_end_wall_ms} — likely a unit "
        f"conversion bug (s vs ms)"
    )


# ---------------------------------------------------------------------------
# 4. Round-trip determinism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory_string,class_name", PAPER_SOLVERS)
def test_wrapper_round_trip_consistency(
    factory_string, class_name, open_8x8_env,
):
    """Two back-to-back invocations on the same instance with the same
    seed must produce the same status.  ``solver_wall_ms`` is allowed
    to vary within ±50 % to absorb host noise on sub-millisecond runs.

    Catches non-determinism bugs in the parser (e.g., a path-length
    threshold that flips between calls because of trailing-newline
    handling, or an OrderedDict iteration that depends on insertion).
    """
    solver_a = _make_solver(factory_string)
    if not _binary_runtime_ok(getattr(solver_a, "binary_path", "")):
        pytest.skip(f"{class_name} binary unavailable")

    agents, assignments = _three_agent_corner_instance()
    res_a = solver_a.plan_with_metadata(
        env=open_8x8_env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )

    # Fresh wrapper instance for the second call, to surface any
    # state leakage between instances of the same class.
    solver_b = _make_solver(factory_string)
    res_b = solver_b.plan_with_metadata(
        env=open_8x8_env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )

    assert res_a.status == res_b.status, (
        f"{class_name} status flipped between identical runs: "
        f"{res_a.status!r} vs {res_b.status!r}"
    )

    if (not math.isnan(res_a.solver_wall_ms)
            and not math.isnan(res_b.solver_wall_ms)
            and res_a.solver_wall_ms > 0.0):
        # ±50 % tolerance — host noise dominates at sub-ms scale.
        ratio = res_b.solver_wall_ms / max(res_a.solver_wall_ms, 1e-9)
        assert 0.5 <= ratio <= 1.5 or abs(
            res_b.solver_wall_ms - res_a.solver_wall_ms
        ) < 5.0, (
            f"{class_name} solver_wall_ms drifted between identical "
            f"runs: {res_a.solver_wall_ms:.3f} vs {res_b.solver_wall_ms:.3f} "
            f"(ratio={ratio:.2f}); likely a parser non-determinism"
        )
