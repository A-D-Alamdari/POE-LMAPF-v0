from __future__ import annotations

from dataclasses import replace

from ha_lmapf.core.types import AgentState, HumanState
from ha_lmapf.local_tier.sensors import build_observation
from ha_lmapf.simulation.environment import Environment


class _SimStub:
    def __init__(self, env, agents, humans, step=0):
        self.env = env
        self.agents = agents
        self.humans = humans
        self.step = step
        self.plans = None


def test_partial_observability_fov() -> None:
    env = Environment(width=10, height=10, blocked=set())

    agents = {0: AgentState(agent_id=0, pos=(0, 0))}
    humans = {0: HumanState(human_id=0, pos=(9, 9), velocity=(0, 0))}

    sim = _SimStub(env, agents, humans, step=0)

    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    assert 0 not in obs.visible_humans  # out of range

    # Move human into range
    sim.humans[0] = replace(sim.humans[0], pos=(2, 1))
    obs2 = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    assert 0 in obs2.visible_humans
