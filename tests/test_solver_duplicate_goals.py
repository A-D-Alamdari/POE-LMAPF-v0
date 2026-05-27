"""
Acceptance test for the lacam3 / lacam_official / lns2 error-storm fix.

See ``docs/solver_error_diagnosis.md`` for the root cause: at 200+
agents on the random-64-64-10 map the rolling-horizon planner builds
windowed instances with duplicate effective goal cells (independent
sampling of task endpoints).  All three one-shot MAPF binaries reject
or fail to converge on such instances, producing the
``solver_errors_mean = 100/100`` observed in the §5.4 scaling sweep.

After the fix each wrapper filters duplicate-goal and ``start == goal``
agents out of the scenario it hands the binary and lets
``_build_complete_bundle`` fill in WAIT paths for them.

This test feeds each wrapper a 200-agent windowed instance that
contains BOTH ``start == goal`` agents AND duplicate-goal pairs and
asserts:

* ``status == "complete"``,
* a path per agent in the returned bundle,
* the bundle is pairwise collision-free (no vertex / edge conflicts).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from ha_lmapf.core.types import AgentState, Task  # noqa: E402
from ha_lmapf.io.movingai_map import load_movingai_map  # noqa: E402
from ha_lmapf.simulation.environment import Environment  # noqa: E402

from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver  # noqa: E402
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import (  # noqa: E402
    LaCAMOfficialSolver,
)
from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver  # noqa: E402

Cell = Tuple[int, int]


def _load_env() -> Environment:
    md = load_movingai_map(str(REPO_ROOT / "data/maps/random-64-64-10.map"))
    return Environment(width=md.width, height=md.height, blocked=md.blocked)


def _build_mixed_instance(env: Environment, num_agents: int,
                          seed: int = 0,
                          ) -> Tuple[Dict[int, AgentState], Dict[int, Task]]:
    """200+-agent instance containing both ``start == goal`` agents
    AND duplicate-goal pairs -- the two degeneracies that triggered
    the error storm in the §5.4 scaling sweep."""
    rng = np.random.default_rng(seed)
    free = list(env._free_cells)
    rng.shuffle(free)
    starts = free[:num_agents]
    goals = list(free[num_agents:num_agents * 2])
    agents: Dict[int, AgentState] = {}
    # 20% of agents have start == goal.
    for i in range(num_agents):
        if i % 5 == 0:
            goals[i] = starts[i]
    # Force ~10 pairs of agents to share a goal cell so the instance
    # is well beyond the threshold that triggered solver failure.
    for k in range(10):
        i1 = 4 * k + 1     # not divisible by 5; not on start==goal slot
        i2 = 4 * k + 2
        if i2 < num_agents:
            goals[i2] = goals[i1]
    for i in range(num_agents):
        agents[i] = AgentState(agent_id=i, pos=starts[i], goal=goals[i])
    return agents, {}


def _has_vertex_or_edge_conflict(paths: Dict[int, "object"]) -> List[str]:
    """Return a list of collision descriptions ([] = collision-free)."""
    aids = sorted(paths.keys())
    cells_by_agent = {aid: list(paths[aid].cells) for aid in aids
                      if paths[aid] is not None}
    if not cells_by_agent:
        return []
    T = max(len(c) for c in cells_by_agent.values())
    conflicts: List[str] = []
    # Vertex conflicts at each timestep.
    for t in range(T):
        seen: Dict[Cell, int] = {}
        for aid, cells in cells_by_agent.items():
            cell = cells[t] if t < len(cells) else cells[-1]
            other = seen.get(cell)
            if other is not None and other != aid:
                conflicts.append(
                    f"vertex conflict t={t} cell={cell} "
                    f"agents=({other}, {aid})"
                )
            else:
                seen.setdefault(cell, aid)
    # Edge conflicts (swap) at each transition.
    for t in range(T - 1):
        pos_at_t: Dict[int, Cell] = {}
        pos_at_t1: Dict[int, Cell] = {}
        for aid, cells in cells_by_agent.items():
            a = cells[t] if t < len(cells) else cells[-1]
            b = cells[t + 1] if t + 1 < len(cells) else cells[-1]
            pos_at_t[aid] = a
            pos_at_t1[aid] = b
        # Pairwise edge swap.
        items = list(pos_at_t.items())
        for i, (a1, c1) in enumerate(items):
            for a2, c2 in items[i + 1:]:
                if pos_at_t1[a1] == c2 and pos_at_t1[a2] == c1 and c1 != c2:
                    conflicts.append(
                        f"edge conflict t={t}->{t + 1} "
                        f"agents=({a1}, {a2}) cells=({c1}<->{c2})"
                    )
    return conflicts


SOLVER_CASES = [
    ("lacam3",         lambda: LaCAM3Solver(time_limit_sec=10.0, verbose=0)),
    ("lacam_official", lambda: LaCAMOfficialSolver(time_limit_sec=10.0, verbose=0)),
    ("lns2",           lambda: LNS2Solver(time_limit_sec=10.0, verbose=0)),
]


def _solver_available(solver_name: str) -> bool:
    """Skip if the binary isn't installed in this environment."""
    name_to_bin = {
        "lacam3":         "lacam3",
        "lacam_official": "lacam",
        "lns2":           "mapf_lns",
    }
    solvers_dir = REPO_ROOT / "src/ha_lmapf/global_tier/solvers"
    return (solvers_dir / name_to_bin[solver_name]).is_file()


@pytest.mark.parametrize("solver_name,solver_factory", SOLVER_CASES)
def test_solver_handles_duplicate_goals_at_scale(solver_name: str,
                                                  solver_factory) -> None:
    if not _solver_available(solver_name):
        pytest.skip(f"{solver_name} binary not present in this environment")

    env = _load_env()
    agents, assignments = _build_mixed_instance(env, num_agents=200, seed=0)

    # Sanity check: the instance must actually have the degeneracies
    # the test purports to exercise, otherwise it would silently
    # pass even on a still-broken wrapper.
    n_start_eq_goal = sum(1 for a in agents.values() if a.goal == a.pos)
    goal_counts: Dict[Cell, int] = {}
    for a in agents.values():
        if a.goal is not None:
            goal_counts[a.goal] = goal_counts.get(a.goal, 0) + 1
    n_duplicate_cells = sum(1 for c in goal_counts.values() if c > 1)
    assert n_start_eq_goal >= 30, (
        f"test instance only has {n_start_eq_goal} start==goal agents; "
        f"expected >= 30 to exercise the degeneracy"
    )
    assert n_duplicate_cells >= 5, (
        f"test instance only has {n_duplicate_cells} duplicate-goal "
        f"cells; expected >= 5 to exercise the degeneracy"
    )

    solver = solver_factory()
    result = solver.plan_with_metadata(
        env=env, agents=agents, assignments=assignments,
        step=0, horizon=40, rng=None,
    )

    assert result.status == "complete", (
        f"{solver_name} returned status={result.status!r} "
        f"error_msg={result.error_msg!r} on a duplicate-goal instance"
    )

    # The bundle must cover every active agent (parsed paths + WAIT
    # fill-in from _build_complete_bundle).
    bundle = result.plan
    assert bundle is not None, f"{solver_name} returned a None plan"
    for aid in agents.keys():
        assert aid in bundle.paths, (
            f"{solver_name} bundle missing agent {aid}"
        )
        assert bundle.paths[aid] is not None, (
            f"{solver_name} bundle has None path for agent {aid}"
        )

    # Collision-free.
    conflicts = _has_vertex_or_edge_conflict(bundle.paths)
    assert not conflicts, (
        f"{solver_name} bundle has {len(conflicts)} collisions; "
        f"first 3: {conflicts[:3]}"
    )
