from __future__ import annotations

from dataclasses import replace

from ha_lmapf.core.types import AgentState, Observation, PlanBundle, StepAction, TimedPath
from ha_lmapf.local_tier.conflict_resolution.token_passing import TokenPassingResolver
from ha_lmapf.simulation.environment import Environment


class _SimStub:
    def __init__(self, env, agents, step=0, plans=None):
        self.env = env
        self.agents = agents
        self.humans = {}
        self.step = step
        self._plans = plans

    def plans(self):
        return self._plans


def test_token_passing_priority_and_fairness_rotation() -> None:
    env = Environment(width=5, height=5, blocked=set())

    # Two agents adjacent, both want the same contested cell (2,2)
    agents = {
        0: AgentState(agent_id=0, pos=(2, 1), goal=(2, 2), wait_steps=0),
        1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 2), wait_steps=0),
    }

    # Provide minimal plans so edge checks work (not needed for vertex conflict)
    plans = PlanBundle(
        paths={
            0: TimedPath(cells=[(2, 1), (2, 2)], start_step=0),
            1: TimedPath(cells=[(2, 3), (2, 2)], start_step=0),
        },
        created_step=0,
        horizon=1,
    )
    sim = _SimStub(env, agents, step=0, plans=plans)

    obs0 = Observation(visible_humans={}, visible_agents={1: agents[1]}, blocked=set(env.blocked))
    obs1 = Observation(visible_humans={}, visible_agents={0: agents[0]}, blocked=set(env.blocked))

    resolver = TokenPassingResolver(fairness_k=2)

    # First conflict on (2,2): deterministic winner by priority tie-break (-agent_id favors 0)
    a0 = resolver.resolve(0, (2, 2), sim, obs0, rng=None)
    a1 = resolver.resolve(1, (2, 2), sim, obs1, rng=None)

    assert a0 != StepAction.WAIT
    # Loser must yield: either WAIT or side-step away from the contested cell
    assert a1 != a0 or a1 == StepAction.WAIT  # loser does not proceed same as winner
    # Verify the loser does not move into the contested cell (2,2)
    cur1 = sim.agents[1].pos
    from ha_lmapf.core.grid import apply_action
    nxt1 = apply_action(cur1, a1)
    assert nxt1 != (2, 2), "Loser should not move into contested cell"

    # Simulate repeated conflicts where agent 0 keeps winning; after fairness_k, should rotate to agent 1
    # Increase wait_steps for agent 1 to ensure it becomes next-best contender clearly
    sim.agents[1] = replace(sim.agents[1], wait_steps=5)

    # Second win by agent 0 triggers rotation (fairness_k=2)
    _ = resolver.resolve(0, (2, 2), sim, obs0, rng=None)

    # Now agent 1 should be favored as token owner on next conflict
    a1_next = resolver.resolve(1, (2, 2), sim, obs1, rng=None)
    assert a1_next != StepAction.WAIT
