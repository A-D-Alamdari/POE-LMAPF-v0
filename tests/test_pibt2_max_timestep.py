"""Regression tests for the PIBT2 wrapper's ``max_timestep`` formula
(see ``docs/ALLOCATOR_DIAGNOSIS.md``).

Pre-fix, the wrapper wrote ``max_timestep = horizon + 50`` (= 70 with
the default ``horizon=20``), conflating the simulator's per-replan
execution window with PIBT2's full-plan length budget.  PIBT2 is
all-or-nothing: when the longest agent trip exceeds ``max_timestep``,
PIBT2 returns ``solved=0`` even on trivially feasible instances.  On
warehouse-scale maps (63×161), agent trips routinely exceed 70
cells, so every replan failed.

Post-fix: ``max_timestep = max(horizon + 50, 2 * (env.height +
env.width))``.  Two-times the map diameter accommodates any
straight-line trip on a rectangular grid plus detours around
obstacles, while preserving the previous behaviour as a floor for
tiny test maps.

Two distinct PIBT2 ``solved=0`` modes (both produce identical
``error_msg`` text — the wrapper does not yet disambiguate):

* Mode A — ``max_timestep`` budget mismatch.  PRE-FIX dominant on
  warehouse maps; this fix resolves it.
* Mode B — priority-scheme deadlock in confined 1-cell corridors.
  Algorithmic property of PIBT2; not a wrapper bug; cannot be
  fixed by changing ``max_timestep``.

These tests guard against ``max_timestep`` regressing back to the
``horizon + 50`` formula and verify that Mode A no longer fires on
realistic warehouse instances.
"""
from __future__ import annotations

import os
import re
import tempfile
from typing import Tuple

import pytest

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
from ha_lmapf.simulation.environment import Environment


def _binary_runtime_ok(binary_path: str) -> bool:
    """Sanity probe — does the PIBT2 binary launch?"""
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


def _make_open_env(tmp_path, height: int, width: int):
    p = tmp_path / f"open_{height}x{width}.map"
    p.write_text(
        f"type octile\nheight {height}\nwidth {width}\nmap\n"
        + ("." * width + "\n") * height
    )
    return Environment.load_from_map(str(p))


def _read_max_timestep(instance_path: str) -> int:
    """Extract the integer max_timestep field from a PIBT2 instance file."""
    text = open(instance_path).read()
    m = re.search(r"^max_timestep\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    assert m is not None, f"max_timestep field not found in instance file: {text}"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# 1. max_timestep formula
# ---------------------------------------------------------------------------


def test_max_timestep_scales_with_map_dimensions(tmp_path):
    """Wrapper's ``max_timestep`` must scale with map size, not be a
    fixed function of ``horizon`` alone.  Pre-fix: always
    ``horizon + 50``; post-fix: ``max(horizon + 50, 2 * (height + width))``.
    """
    small = _make_open_env(tmp_path, height=20, width=20)
    large = _make_open_env(tmp_path, height=200, width=200)

    solver = PIBT2Solver(time_limit_sec=1.0)
    agents = {0: AgentState(0, (0, 0))}
    assignments = {0: Task("t0", (0, 0), (1, 1), 0)}

    small_inst = tmp_path / "small_inst.txt"
    small_map = tmp_path / "small_map.map"
    small_map.write_text("dummy")
    solver._write_instance_file(
        small, agents, assignments, [0],
        str(small_inst), str(small_map), horizon=20,
    )

    large_inst = tmp_path / "large_inst.txt"
    large_map = tmp_path / "large_map.map"
    large_map.write_text("dummy")
    solver._write_instance_file(
        large, agents, assignments, [0],
        str(large_inst), str(large_map), horizon=20,
    )

    small_max = _read_max_timestep(str(small_inst))
    large_max = _read_max_timestep(str(large_inst))

    # Floor: small map's max_timestep is at least horizon+50 = 70.
    # On a 20x20, 2*(20+20) = 80 dominates the floor, so we expect 80.
    assert small_max >= 70, (
        f"small map max_timestep={small_max} < horizon+50 floor of 70"
    )
    # The 80 from 2*(20+20) must dominate the 70 floor on a 20x20.
    assert small_max == 80, (
        f"expected max(70, 2*(20+20)) = 80, got {small_max}"
    )

    # Large map must scale: 2*(200+200) = 800.
    assert large_max == 800, (
        f"expected max(70, 2*(200+200)) = 800, got {large_max}"
    )

    # And large > small — the formula is dimension-sensitive.
    assert large_max > small_max, (
        f"max_timestep did not scale with map size: "
        f"small={small_max}, large={large_max}"
    )


def test_max_timestep_floor_preserved_on_tiny_maps(tmp_path):
    """On tiny maps where ``2 * (height + width) < horizon + 50``,
    the wrapper falls back to the horizon-based floor so PIBT2 still
    has the buffer it had pre-fix.
    """
    tiny = _make_open_env(tmp_path, height=5, width=5)  # 2*(5+5)=20 < 70
    solver = PIBT2Solver(time_limit_sec=1.0)
    agents = {0: AgentState(0, (0, 0))}
    assignments = {0: Task("t0", (0, 0), (4, 4), 0)}

    inst = tmp_path / "tiny_inst.txt"
    map_path = tmp_path / "tiny_map.map"
    map_path.write_text("dummy")
    solver._write_instance_file(
        tiny, agents, assignments, [0],
        str(inst), str(map_path), horizon=20,
    )
    val = _read_max_timestep(str(inst))
    # 5x5 → 2*(5+5)=20; horizon+50=70; max = 70.
    assert val == 70, (
        f"expected horizon+50 floor (70) on 5x5 map, got {val}"
    )


# ---------------------------------------------------------------------------
# 2. End-to-end: long trip on warehouse-10-20-10-2-1
# ---------------------------------------------------------------------------


def test_pibt2_solves_long_distance_trip_on_warehouse():
    """The captured failing instance from
    ``docs/ALLOCATOR_DIAGNOSIS.md``: an agent on
    warehouse-10-20-10-2-1 with start (52, 139) and goal (46, 4) —
    a 141-cell Manhattan trip — failed pre-fix with
    ``max_timestep=70``.  Post-fix, ``max_timestep`` scales with map
    dimensions to 2*(63+161) = 448, which accommodates the trip and
    PIBT2 returns ``solved=1``.
    """
    map_path = "data/maps/warehouse-10-20-10-2-1.map"
    if not os.path.isfile(map_path):
        pytest.skip(f"warehouse map not available at {map_path}")

    env = Environment.load_from_map(map_path)

    solver = PIBT2Solver(time_limit_sec=1.0)
    if not _binary_runtime_ok(solver.binary_path):
        pytest.skip(f"PIBT2 binary unusable at {solver.binary_path}")

    # The exact agent + goal pair from ALLOCATOR_DIAGNOSIS.md.
    # AgentState's pos is (row, col); the diagnosis records (52, 139)
    # which maps to row=52, col=139 (verified against env.is_blocked
    # = False at this position).
    agents = {0: AgentState(0, (52, 139))}
    assignments = {0: Task("t0", (52, 139), (46, 4), 0)}

    res = solver.plan_with_metadata(
        env=env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )

    assert res.status == "complete", (
        f"expected complete on the captured 141-cell trip, got "
        f"status={res.status!r} error_msg={res.error_msg!r}.  "
        f"This is the regression check that Mode-A budget mismatch "
        f"is fixed; see docs/ALLOCATOR_DIAGNOSIS.md."
    )

    # The agent must move toward the goal.  The wrapper truncates
    # PIBT2's full plan (~145 steps) to ``horizon + 1 = 21`` cells, so
    # we don't assert the path REACHES the goal — only that it makes
    # measurable progress toward it.  Pre-fix, PIBT2 returned all-WAIT
    # bundles (no movement at all); post-fix, the agent should advance
    # at least 10 Manhattan cells in 20 steps on the open warehouse.
    tp = res.plan.paths.get(0)
    assert tp is not None and tp.cells, "no path returned for agent 0"
    start = (52, 139)
    goal = (46, 4)
    initial_dist = abs(start[0] - goal[0]) + abs(start[1] - goal[1])
    last_cell = tp.cells[-1]
    final_dist = abs(last_cell[0] - goal[0]) + abs(last_cell[1] - goal[1])
    assert final_dist < initial_dist, (
        f"agent 0 made no progress toward goal: start={start}, "
        f"last_cell={last_cell}, goal={goal}.  Pre-fix symptom of "
        f"all-WAIT fallback when PIBT2 returns solved=0."
    )
    # On a 20-step horizon along a clear corridor, the agent should
    # move at least 10 cells closer to the goal.
    assert (initial_dist - final_dist) >= 10, (
        f"agent 0 advanced only {initial_dist - final_dist} cells in "
        f"20 steps — too slow for an open corridor.  Likely sign that "
        f"PIBT2 is producing degenerate plans even with status=complete."
    )


# ---------------------------------------------------------------------------
# 3. Mode A vs Mode B — confined corridor still triggers Mode B
# ---------------------------------------------------------------------------


def test_max_timestep_does_not_mask_mode_b_deadlock(tmp_path):
    """A confined 1-cell corridor with two agents end-to-end-swapping
    is the canonical Mode-B trigger (priority-scheme deadlock with
    no swap room).  ``max_timestep`` is now 2*(1+6)=14 on a 1x6 grid,
    floor-clamped to horizon+50=70 — both well above the trip
    distance of 5 cells.  Mode A is impossible here.

    PIBT2 still reports ``solved=0`` because the priority scheme
    cannot resolve the swap.  Post-Phase-D-Fix-1, the wrapper
    surfaces this as ``status="partial_anytime"`` (using the
    rolling-horizon prefix PIBT2 wrote out — typically WAIT-in-place
    on a deadlocked instance) with ``error_msg`` that begins with
    ``"PIBT2 solved=0; using rolling-horizon prefix"``.  This
    documents that the Mode-A fix does NOT silently mask Mode-B
    incompleteness: the run is still counted under
    ``Metrics.solver_partial_returns`` (not ``Metrics.replans`` as a
    success), and the error_msg explicitly names the underlying
    solved=0.  ``error`` and ``timeout_no_result`` remain acceptable
    pre-Phase-D (some environments may not produce a parseable
    prefix), but the canonical post-Fix-1 outcome is
    ``partial_anytime``.
    """
    p = tmp_path / "corridor_1x6.map"
    p.write_text("type octile\nheight 1\nwidth 6\nmap\n......\n")
    env = Environment.load_from_map(str(p))

    solver = PIBT2Solver(time_limit_sec=1.0)
    if not _binary_runtime_ok(solver.binary_path):
        pytest.skip(f"PIBT2 binary unusable at {solver.binary_path}")

    # Two agents end-to-end on a 1x6 corridor with no parking → Mode-B
    # deadlock.  The trip is 5 cells; max_timestep is 70+ so Mode A
    # cannot fire.
    agents = {
        0: AgentState(0, (0, 0)),
        1: AgentState(1, (0, 5)),
    }
    assignments = {
        0: Task("t0", (0, 0), (0, 5), 0),
        1: Task("t1", (0, 5), (0, 0), 0),
    }

    res = solver.plan_with_metadata(
        env=env, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )

    # Mode-B deadlock must NOT show up as 'complete' — that would
    # mean the wrapper silently masked PIBT2's solved=0 as success.
    # Acceptable outcomes are:
    #   * "partial_anytime" with an error_msg naming solved=0
    #     (canonical post-Phase-D-Fix-1; the wrapper preserved the
    #     PIBT2 prefix and surfaced the failure status truthfully);
    #   * "error" or "timeout_no_result" (degraded environments
    #     where the prefix wasn't parseable or the binary timed out).
    assert res.status in {"partial_anytime", "error", "timeout_no_result"}, (
        f"expected partial_anytime / error / timeout_no_result on the "
        f"canonical Mode-B deadlock, got status={res.status!r} "
        f"error_msg={res.error_msg!r}.  If status='complete' here, the "
        f"wrapper now silently masks Mode-B failures (regression worth "
        f"investigating)."
    )
    if res.status == "partial_anytime":
        # Post-Fix-1: the error_msg MUST name the underlying solved=0
        # so the diagnostic chain is preserved end-to-end.
        assert "solved=0" in (res.error_msg or ""), (
            f"partial_anytime on Mode-B must surface solved=0 in "
            f"error_msg; got {res.error_msg!r}.  If the wrapper has "
            f"dropped this annotation, the docs/PIBT2_DIAGNOSIS.md "
            f"§\"Residual…\" contract is broken."
        )
