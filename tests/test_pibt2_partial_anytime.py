"""Regression tests for PIBT2's ``solved=0`` -> ``partial_anytime``
handling.

Background: PIBT2's MAPF binary writes ``solved=0`` whenever the full
MAPF instance doesn't terminate within ``max_timestep``, but the
``solution=`` block of agent positions up to the cutoff is still
present in the result file.  For the rolling-horizon framework only
the first ``horizon`` ticks are needed, and those positions are
usually valid progress toward goals.

Pre-fix, the wrapper rejected the result file entirely when it saw
``solved=0``: ``_parse_result_file`` early-returned an empty dict, and
``plan_with_metadata``'s ``parse_fn`` reported an ``error`` status.
This caused PIBT2-FR to register a ``solver_error`` on every replan
at warehouse-10-20-10-2-2 |M|=150 (Mode-B priority-scheme deadlock),
collapsing PIBT2-FR's throughput to ~0 and rendering Section 5.5's
baseline comparison non-comparable.

Post-fix:

* ``_parse_result_file`` no longer early-returns on ``solved=0``; it
  parses the ``solution=`` block in all cases.
* ``parse_fn`` returns a 4-tuple ``(paths, ms, err, status_hint)``;
  when ``solved=0`` AND the solution block parses cleanly, it sets
  ``status_hint = "partial_anytime"``.
* ``_wrap_subprocess`` honors the hint: when the decision tree would
  otherwise pick ``complete`` and the wrapper supplied
  ``partial_anytime``, the result is downgraded to ``partial_anytime``
  so the rolling-horizon planner counts it under
  ``Metrics.solver_partial_returns`` instead of
  ``Metrics.solver_errors``.

These tests exercise both the wrapper-internal parse change and the
end-to-end status routing.  They use a synthetic result file (no
binary dependency) so they run in any environment.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_synthetic_result(
    path: Path, agents: int, horizon: int, *, solved: int,
) -> None:
    """Write a PIBT2-format result file with ``agents`` rows and
    ``horizon + 1`` timesteps in the ``solution=`` block.  Cells are
    chosen so each agent's path is a monotonic walk along the same
    row, which always parses cleanly via the wrapper's regex.

    ``solved`` is written as-is so the test can drive both ``=1``
    (the normal-success branch) and ``=0`` (the partial-anytime
    branch)."""
    lines = [
        "instance=/tmp/dummy",
        f"agents={agents}",
        "map_file=/tmp/dummy.map",
        "solver=PIBT",
        f"solved={solved}",
        "soc=999",
        "lb_soc=100",
        "makespan=508",
        "lb_makespan=10",
        "comp_time=42",
        "preprocessing_comp_time=5",
        f"starts=" + ",".join(f"({a},{a})" for a in range(agents)) + ",",
        f"goals=" + ",".join(f"({a+1},{a})" for a in range(agents)) + ",",
        "solution=",
    ]
    for t in range(horizon + 1):
        cells = ",".join(f"({a + (t > 0)},{a})" for a in range(agents))
        lines.append(f"{t}:{cells},")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Wrapper-internal: _parse_result_file no longer early-returns on solved=0
# ---------------------------------------------------------------------------


def test_parse_result_file_extracts_solution_when_solved_zero(tmp_path):
    """``_parse_result_file`` must parse the ``solution=`` block even
    when the file declares ``solved=0``.  Pre-fix, the function early-
    returned an empty dict and the rolling-horizon framework lost the
    valid prefix entirely."""
    result_path = tmp_path / "result.txt"
    _write_synthetic_result(result_path, agents=3, horizon=5, solved=0)

    solver = PIBT2Solver(time_limit_sec=1.0)
    paths = solver._parse_result_file(
        str(result_path), agent_order=[10, 20, 30],
        start_step=0, horizon=5,
    )
    assert set(paths.keys()) == {10, 20, 30}, (
        "all three active agents must receive a path; pre-fix solved=0 "
        f"caused an empty dict, got: {sorted(paths.keys())!r}"
    )
    for aid, tp in paths.items():
        assert len(tp.cells) == 6, (
            f"agent {aid}: expected horizon+1=6 cells, got {len(tp.cells)}"
        )


def test_parse_result_file_still_parses_solved_one(tmp_path):
    """``solved=1`` continues to parse correctly (regression on the
    happy path)."""
    result_path = tmp_path / "result.txt"
    _write_synthetic_result(result_path, agents=2, horizon=4, solved=1)

    solver = PIBT2Solver(time_limit_sec=1.0)
    paths = solver._parse_result_file(
        str(result_path), agent_order=[7, 8],
        start_step=0, horizon=4,
    )
    assert set(paths.keys()) == {7, 8}
    for tp in paths.values():
        assert len(tp.cells) == 5


# ---------------------------------------------------------------------------
# End-to-end: plan_with_metadata returns partial_anytime on solved=0
# ---------------------------------------------------------------------------


def _binary_runnable(solver: PIBT2Solver) -> bool:
    """``--help`` probe.  Returns True only if the binary loads and
    exits with a usable status."""
    import subprocess
    try:
        r = subprocess.run(
            [solver.mapf_binary, "--help"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if "shared libraries" in (r.stderr or ""):
        return False
    return r.returncode in (0, 1)


def test_plan_with_metadata_returns_partial_anytime_on_solved_zero(tmp_path):
    """Triggers a real PIBT2 invocation on warehouse-10-20-10-2-2 at
    |M|=150, the canonical scale that elicits ``solved=0`` from
    PIBT2's priority scheme.  Asserts the wrapper now surfaces this
    as ``partial_anytime`` with a non-empty plan, instead of
    ``error``.

    Skips when the PIBT2 binary is not loadable (e.g., libboost
    missing on a fresh CI image)."""
    from ha_lmapf.core.types import AgentState, Task
    from ha_lmapf.simulation.environment import Environment

    map_path = "data/maps/warehouse-10-20-10-2-2.map"
    if not os.path.isfile(map_path):
        pytest.skip("warehouse-10-20-10-2-2.map missing")

    solver = PIBT2Solver(time_limit_sec=10.0)
    if not _binary_runnable(solver):
        pytest.skip("PIBT2 binary unavailable on this host")

    env = Environment.load_from_map(map_path)
    import random
    rng = random.Random(0)
    free = [(r, c) for r in range(env.height) for c in range(env.width)
            if not env.is_blocked((r, c))]
    cells = rng.sample(free, 300)
    n = 150
    agents = {i: AgentState(i, cells[i]) for i in range(n)}
    assignments = {
        i: Task(f"p{i}", cells[i], cells[n + i], 0) for i in range(n)
    }
    res = solver.plan_with_metadata(
        env=env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None, is_lifelong=False,
    )
    # The point of the fix: the result is usable.  Either PIBT2
    # happened to solve the random instance (status="complete") or
    # it hit the deadlock and surfaced a partial plan
    # (status="partial_anytime").  Pre-fix, "error" was the only
    # observed outcome at this scale; we forbid it here.
    assert res.status in {"complete", "partial_anytime"}, (
        f"expected complete or partial_anytime, got {res.status!r} "
        f"(error_msg={res.error_msg!r})"
    )
    assert len(res.plan.paths) == n, (
        f"expected {n} agent paths, got {len(res.plan.paths)}"
    )
