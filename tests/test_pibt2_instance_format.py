"""Regression tests for the PIBT2 wrapper instance-file format and
binary-selection fixes (see ``docs/PIBT2_DIAGNOSIS.md``).

These tests guard against re-introducing two bugs:

* **Bug 1**: writing scenario data as ``starts=(x,y),...`` /
  ``goals=(x,y),...`` lines instead of the per-agent
  ``start_x,start_y,goal_x,goal_y`` records that Kei18/pibt2's parser
  recognises.  Pre-fix, the binary silently fell back to seeded
  random scenario generation.

* **Bug 2**: auto-routing lifelong runs to ``mapd_pibt2``, whose
  output the wrapper's MAPF-format parser cannot read.  Pre-fix,
  every lifelong replan returned ``solver_errors``.

The tests are wrapper-internal: they do not depend on a working
PIBT2 binary except for ``test_pibt2_solves_warehouse_instance_with_real_starts_goals``,
which skips cleanly when the binary is missing or unhealthy.
"""
from __future__ import annotations

import os
import re
import tempfile

import pytest

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
from ha_lmapf.simulation.environment import Environment


def _make_env_8x8(tmp_path):
    p = tmp_path / "8x8_open.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return Environment.load_from_map(str(p))


# ---------------------------------------------------------------------------
# Bug 1: instance-file format
# ---------------------------------------------------------------------------


def test_instance_file_uses_kei18_format(tmp_path):
    """Wrapper must emit per-line ``x_s,y_s,x_g,y_g`` scenario records.

    Verified against Kei18/pibt2's ``Problem.cpp`` regex
    ``(\\d+),(\\d+),(\\d+),(\\d+)``.  Coordinate convention is
    ``(x, y) = (col, row)`` matching MovingAI .map orientation.
    """
    env = _make_env_8x8(tmp_path)
    solver = PIBT2Solver(time_limit_sec=1.0)
    agents = {
        0: AgentState(0, (0, 0)),  # row=0, col=0 → x_s=0, y_s=0
        1: AgentState(1, (5, 5)),  # row=5, col=5 → x_s=5, y_s=5
        2: AgentState(2, (3, 7)),  # row=3, col=7 → x_s=7, y_s=3
    }
    assignments = {
        0: Task("t0", (0, 0), (7, 7), 0),  # goal=(row=7, col=7) → (x_g=7, y_g=7)
        1: Task("t1", (5, 5), (1, 1), 0),  # → (x_g=1, y_g=1)
        2: Task("t2", (3, 7), (6, 2), 0),  # → (x_g=2, y_g=6)
    }

    instance_path = tmp_path / "instance.txt"
    map_path = tmp_path / "map.map"
    map_path.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)

    agent_order = solver._write_instance_file(
        env, agents, assignments, [0, 1, 2],
        str(instance_path), str(map_path), horizon=20,
    )

    assert agent_order == [0, 1, 2]
    contents = instance_path.read_text().splitlines()

    # Header lines (order is not strict per Kei18/pibt2 source, but
    # the wrapper happens to write them first; we just check presence).
    assert any(l.startswith("map_file=") for l in contents)
    assert "agents=3" in contents
    assert "seed=0" in contents
    assert "random_problem=0" in contents
    assert any(l.startswith("max_timestep=") for l in contents)
    assert any(l.startswith("max_comp_time=") for l in contents)

    # Scenario lines: per-agent x_s,y_s,x_g,y_g.  Coordinates in (col, row).
    expected_scenario = ["0,0,7,7", "5,5,1,1", "7,3,2,6"]
    scenario_lines = [
        l for l in contents if re.match(r"^\d+,\d+,\d+,\d+$", l)
    ]
    assert scenario_lines == expected_scenario, (
        f"expected {expected_scenario}, got {scenario_lines}"
    )


def test_instance_file_does_not_use_old_starts_goals_format(tmp_path):
    """Regression check against re-introducing the broken
    ``starts=(...)`` / ``goals=(...)`` syntax.
    """
    env = _make_env_8x8(tmp_path)
    solver = PIBT2Solver(time_limit_sec=1.0)
    agents = {
        0: AgentState(0, (0, 0)),
        1: AgentState(1, (5, 5)),
        2: AgentState(2, (3, 7)),
    }
    assignments = {
        0: Task("t0", (0, 0), (7, 7), 0),
        1: Task("t1", (5, 5), (1, 1), 0),
        2: Task("t2", (3, 7), (6, 2), 0),
    }
    instance_path = tmp_path / "instance.txt"
    map_path = tmp_path / "map.map"
    map_path.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    solver._write_instance_file(
        env, agents, assignments, [0, 1, 2],
        str(instance_path), str(map_path), horizon=20,
    )

    text = instance_path.read_text()
    assert "starts=" not in text, (
        "instance file contains 'starts=' header — Kei18/pibt2 does NOT "
        "parse this; it must be one line per agent: x_s,y_s,x_g,y_g"
    )
    assert "goals=" not in text, (
        "instance file contains 'goals=' header — Kei18/pibt2 does NOT "
        "parse this; it must be one line per agent: x_s,y_s,x_g,y_g"
    )


# ---------------------------------------------------------------------------
# Bug 2: binary selection
# ---------------------------------------------------------------------------


def test_select_binary_always_returns_mapf_in_auto_mode():
    """``mode="auto"`` must route every replan to ``mapf_pibt2``,
    regardless of ``is_lifelong``.  The simulator's
    RollingHorizonPlanner owns the lifelong loop; each replan is a
    one-shot MAPF problem.  ``mapd_pibt2`` would generate its own
    synthetic tasks and emit incompatible output.
    """
    solver = PIBT2Solver(time_limit_sec=1.0, mode="auto")
    assert solver._select_binary(is_lifelong=False) == solver.mapf_binary
    assert solver._select_binary(is_lifelong=True) == solver.mapf_binary, (
        "mode='auto' + is_lifelong=True still routes to mapd_pibt2 — "
        "Bug 2 has been re-introduced.  See docs/PIBT2_DIAGNOSIS.md."
    )
    assert solver._select_binary(is_lifelong=True) != solver.mapd_binary


def test_select_binary_respects_explicit_mapd_mode():
    """Explicit ``mode="mapd"`` (or ``"lifelong"``) preserves the
    escape hatch for stand-alone MAPD experiments.  The wrapper does
    not actively use this path from the rolling-horizon framework, but
    it remains accessible for future use.
    """
    for mode in ("mapd", "lifelong"):
        solver = PIBT2Solver(time_limit_sec=1.0, mode=mode)
        assert solver._select_binary(is_lifelong=False) == solver.mapd_binary
        assert solver._select_binary(is_lifelong=True) == solver.mapd_binary


def test_select_binary_respects_explicit_mapf_mode():
    """Explicit ``mode="mapf"`` (or ``"one_shot"``) is a no-op given
    the auto fix, but the explicit-mode plumbing should keep working.
    """
    for mode in ("mapf", "one_shot", "oneshot"):
        solver = PIBT2Solver(time_limit_sec=1.0, mode=mode)
        assert solver._select_binary(is_lifelong=False) == solver.mapf_binary
        assert solver._select_binary(is_lifelong=True) == solver.mapf_binary


# ---------------------------------------------------------------------------
# Integration: PIBT2 honours the wrapper's starts / goals
# ---------------------------------------------------------------------------


def _binary_runtime_ok(binary_path: str) -> bool:
    """Sanity probe — does the PIBT2 binary launch?"""
    import subprocess
    if not os.path.isfile(binary_path):
        return False
    try:
        r = subprocess.run(
            [binary_path, "--help"], capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return False
    return r.returncode in (0, 1) and "shared libraries" not in (r.stderr or "")


def test_pibt2_solves_warehouse_instance_with_real_starts_goals(tmp_path):
    """End-to-end: the binary, fed correctly-formatted starts and goals,
    returns a plan whose first cell for each agent equals the input
    start position.  Pre-fix, PIBT2 ignored the wrapper's starts and
    used random ones, so the first cells did NOT match.
    """
    map_path = tmp_path / "warehouse.map"
    map_path.write_text(
        "type octile\nheight 10\nwidth 14\nmap\n"
        "..............\n"
        ".@@.@@.@@.@@..\n"
        "..............\n"
        ".@@.@@.@@.@@..\n"
        "..............\n"
        ".@@.@@.@@.@@..\n"
        "..............\n"
        ".@@.@@.@@.@@..\n"
        "..............\n"
        "..............\n"
    )
    env = Environment.load_from_map(str(map_path))

    # 5 agents — well below PIBT2's structural capacity on this map.
    # Diagonal placement on free cells.
    agents = {
        0: AgentState(0, (0, 0)),
        1: AgentState(1, (0, 13)),
        2: AgentState(2, (4, 0)),
        3: AgentState(3, (4, 13)),
        4: AgentState(4, (8, 7)),
    }
    assignments = {
        0: Task("t0", (0, 0), (9, 13), 0),
        1: Task("t1", (0, 13), (9, 0), 0),
        2: Task("t2", (4, 0), (8, 13), 0),
        3: Task("t3", (4, 13), (8, 0), 0),
        4: Task("t4", (8, 7), (0, 7), 0),
    }

    solver = PIBT2Solver(time_limit_sec=1.0)
    if not _binary_runtime_ok(solver.binary_path):
        pytest.skip(f"PIBT2 binary unavailable at {solver.binary_path}")

    res = solver.plan_with_metadata(
        env, agents, assignments, step=0, horizon=30,
    )

    assert res.status == "complete", (
        f"expected complete at 5 agents on 10x14 mini-warehouse, got "
        f"status={res.status!r} error_msg={res.error_msg!r}"
    )

    # The first cell of every agent's path must equal the input start.
    # If PIBT2 were ignoring the wrapper's starts (Bug 1's symptom), the
    # path's first cell would be a deterministic-random position, not
    # the agent's actual position.
    for aid, agent in agents.items():
        tp = res.plan.paths.get(aid)
        assert tp is not None, f"agent {aid} has no path"
        assert tp.cells[0] == agent.pos, (
            f"agent {aid}: first path cell {tp.cells[0]} does NOT match "
            f"input start {agent.pos} — PIBT2 may be using random starts "
            f"again (Bug 1 regression).  See docs/PIBT2_DIAGNOSIS.md."
        )

    # At least one agent's path must have movement (the binary actually
    # planned something rather than returning all-WAIT).
    has_movement = any(
        len(set(tp.cells)) > 1 for tp in res.plan.paths.values()
        if tp is not None
    )
    assert has_movement, (
        "no agent has movement — wrapper may be silently fabricating "
        "all-WAIT plans"
    )
