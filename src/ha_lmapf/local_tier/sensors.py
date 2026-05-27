from __future__ import annotations

from typing import Dict, Set, Tuple

from ha_lmapf.core.grid import manhattan
from ha_lmapf.core.types import AgentState, HumanState, Observation

Cell = Tuple[int, int]


def build_observation(agent_id: int, sim_state, fov_radius: int) -> Observation:
    """
    Build a local Observation for an agent under partial observability.

    - Visible humans: within Manhattan distance <= fov_radius
    - Visible agents (other agents): within Manhattan distance <= fov_radius (exclude self)
    - blocked: static blocked cells + cells occupied by visible humans (NOT inflated)

    Deterministic given deterministic sim_state.
    """
    fov_radius = int(fov_radius)
    agent = sim_state.agents[agent_id]
    apos = agent.pos

    visible_humans: Dict[int, HumanState] = {}
    for hid in sorted(sim_state.humans.keys()):
        h = sim_state.humans[hid]
        if manhattan(apos, h.pos) <= fov_radius:
            visible_humans[hid] = h

    visible_agents: Dict[int, AgentState] = {}
    for aid in sorted(sim_state.agents.keys()):
        if aid == agent_id:
            continue
        a = sim_state.agents[aid]
        if manhattan(apos, a.pos) <= fov_radius:
            visible_agents[aid] = a

    blocked: Set[Cell] = set(sim_state.env.blocked)
    for h in visible_humans.values():
        blocked.add(h.pos)
    # Block cells occupied by visible agents so local A* avoids them
    for a in visible_agents.values():
        blocked.add(a.pos)
    # Also block cells already committed by earlier agents this timestep
    if hasattr(sim_state, 'decided_next_positions'):
        for oid, decided_pos in sim_state.decided_next_positions().items():
            if oid != agent_id:
                blocked.add(decided_pos)

    return Observation(
        visible_humans=visible_humans,
        visible_agents=visible_agents,
        blocked=blocked,
    )
