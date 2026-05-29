from __future__ import annotations

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


def test_token_passing_winner_proceeds_loser_yields() -> None:
    """Public-contract slice of the former
    ``test_token_passing_priority_and_fairness_rotation`` (resume-prompt-6).

    The K-rotation half of the original test was removed: that mechanism no
    longer exists.  What remains is the resolver's load-bearing contract on
    a single contention — the winner proceeds into the contested cell and
    the loser does not — which holds identically under the new
    per-(agent, cell) token scheme (both agents start at the 5 endowment, so
    the first contention is decided by the rest of the ``(τ, -d, w, -id)``
    tuple and the lower id wins).  Token-mechanism specifics are covered in
    tests/test_token_based_resolver_v2.py.
    """
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

    resolver = TokenPassingResolver()

    # Conflict on (2,2): both at the 5 endowment, equal d (1) and w (0);
    # deterministic winner by the -id tie-break favours agent 0.
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
