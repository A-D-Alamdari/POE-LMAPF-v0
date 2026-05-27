from __future__ import annotations

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
from ha_lmapf.global_tier.solvers.common import detect_first_conflict
from ha_lmapf.simulation.environment import Environment


def test_cbs_avoids_vertex_and_edge_conflicts() -> None:
    # 5x5 empty environment
    env = Environment(width=5, height=5, blocked=set())

    # Two agents swapping positions across an edge
    agents = {
        0: AgentState(agent_id=0, pos=(2, 2)),
        1: AgentState(agent_id=1, pos=(2, 3)),
    }
    assignments = {
        0: Task(task_id="t0", start=(2, 2), goal=(2, 3), release_step=0),
        1: Task(task_id="t1", start=(2, 3), goal=(2, 2), release_step=0),
    }

    planner = CBSH2Solver()
    plan = planner.plan(env=env, agents=agents, assignments=assignments, step=0, horizon=2, rng=None)

    p0 = plan.paths[0]
    p1 = plan.paths[1]

    # Ensure no vertex or edge swap conflict exists over the horizon
    conflict = detect_first_conflict(0, p0, 1, p1)
    assert conflict is None
