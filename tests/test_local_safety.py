from __future__ import annotations

from dataclasses import replace

from ha_lmapf.core.types import AgentState, HumanState, Observation, PlanBundle, StepAction, TimedPath
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.local_tier.agent_controller import AgentController
from ha_lmapf.local_tier.conflict_resolution.priority_rules import PriorityRulesResolver
from ha_lmapf.local_tier.local_planner import AStarLocalPlanner
from ha_lmapf.local_tier.sensors import build_observation
from ha_lmapf.simulation.environment import Environment


class _SimStub:
    def __init__(self, env, agents, humans, plans, step=0):
        self.env = env
        self.agents = agents
        self.humans = humans
        self._plans = plans
        self.step = step
        # minimal metrics hook (optional)
        class _M:
            def __init__(self): self.replans = 0
            def add_replan(self, n): self.replans += int(n)
        self.metrics = _M()

    def plans(self):
        return self._plans


def test_agent_controller_respects_human_safety() -> None:
    env = Environment(width=5, height=5, blocked=set())

    # Agent at (2,2) wants to move to (2,3) next
    agents = {
        0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 4), task_id="t0", carrying=True),
    }
    # Human occupies the next planned cell (2,3)
    humans = {
        0: HumanState(human_id=0, pos=(2, 3), velocity=(0, 0)),
    }

    # Global plan: (2,2) -> (2,3) -> (2,4)
    tp = TimedPath(cells=[(2, 2), (2, 3), (2, 4)], start_step=0)
    plans = PlanBundle(paths={0: tp}, created_step=0, horizon=2)

    sim = _SimStub(env, agents, humans, plans, step=0)

    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)

    controller = AgentController(
        agent_id=0,
        local_planner=AStarLocalPlanner(),
        conflict_resolver=PriorityRulesResolver(),
        fov_radius=4,
        safety_radius=1,
    )

    action = controller.decide_action(sim, obs, rng=None)

    # Compute what cell would result from action
    cur = sim.agents[0].pos
    if action == StepAction.UP:
        nxt = (cur[0] - 1, cur[1])
    elif action == StepAction.DOWN:
        nxt = (cur[0] + 1, cur[1])
    elif action == StepAction.LEFT:
        nxt = (cur[0], cur[1] - 1)
    elif action == StepAction.RIGHT:
        nxt = (cur[0], cur[1] + 1)
    else:
        nxt = cur

    forbidden = inflate_cells({humans[0].pos}, radius=1, env=env)

    # With hard safety (default): the agent must not ENTER a new forbidden cell.
    # If it WAITs (staying at current position), that's safe behavior -
    # the agent is not moving into the safety buffer, even if already inside it.
    if action != StepAction.WAIT:
        assert nxt not in forbidden
    # WAIT is always acceptable when a human is nearby (conservative safety)


# Helper used by the T-Esc-* tests below.
def _resulting_cell(cur, action):
    if action == StepAction.UP:
        return (cur[0] - 1, cur[1])
    if action == StepAction.DOWN:
        return (cur[0] + 1, cur[1])
    if action == StepAction.LEFT:
        return (cur[0], cur[1] - 1)
    if action == StepAction.RIGHT:
        return (cur[0], cur[1] + 1)
    return cur


def _make_controller():
    return AgentController(
        agent_id=0,
        local_planner=AStarLocalPlanner(),
        conflict_resolver=PriorityRulesResolver(),
        fov_radius=3,
        safety_radius=1,
    )


# ---------------------------------------------------------------------------
# T-Esc-1 through T-Esc-4 — hard-safety buffer-escape invariant
# (paper Section 4.3).
# ---------------------------------------------------------------------------
#
# These four tests exercise the hard-safety buffer-escape branch added to
# AgentController.decide_action.  When the agent is itself inside the
# forbidden set F and local A* finds no F-respecting path to goal, the
# controller must attempt a one-step F-respecting move via
# _find_escape_move instead of an unconditional Safe Wait.  Safe Wait is
# permitted only in the corridor-trap case where every neighbour of the
# agent is also in F.


def test_T_esc_1_single_step_escape_exists() -> None:
    """T-Esc-1 — Agent in F, goal unreachable through non-F cells, but a
    one-step F-respecting escape exists.  The controller must take the
    escape, not Safe Wait.

    Geometry: 5x5 open grid, r_safe=1, human at (3,2), agent at (2,2),
    goal at (4,2).  F = {(3,2), (2,2), (4,2), (3,1), (3,3)} — both agent
    and goal are inside F, so A* cannot step into the goal (goal in
    blocked) and returns [].  Neighbours (1,2), (2,1), (2,3) of the agent
    are all outside F; the escape helper picks one of them.
    """
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 2), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(3, 2), velocity=(0, 0))}
    plans = PlanBundle(paths={}, created_step=0, horizon=1)
    sim = _SimStub(env, agents, humans, plans, step=0)
    sim.step_events = []

    forbidden = inflate_cells({humans[0].pos}, radius=1, env=env)
    assert (2, 2) in forbidden, "test geometry: agent must start inside F"
    assert (4, 2) in forbidden, "test geometry: goal must also be in F (forces A* failure)"

    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=3)
    controller = _make_controller()

    action = controller.decide_action(sim, obs, rng=None)
    result = _resulting_cell((2, 2), action)

    assert action != StepAction.WAIT, "agent must escape, not Safe Wait"
    assert result not in forbidden, "escape cell must be outside F"
    assert sim.agents[0].last_action_was_safe_wait is False
    assert any("[BUFFER-ESCAPE]" in e for e in sim.step_events), (
        f"expected [BUFFER-ESCAPE] log line, got: {sim.step_events}"
    )


def test_T_esc_2_goal_reachable_through_non_F() -> None:
    """T-Esc-2 — Agent in F but goal reachable via non-F cells; local A*
    succeeds and the escape branch must NOT fire (regression guard).

    Geometry: 5x5 open grid, r_safe=1, human at (1,2), agent at (2,2),
    goal at (4,4).  F = {(1,2), (0,2), (2,2), (1,1), (1,3)} — agent in F
    but goal outside F.  A* finds a path through (2,3)→(3,3)→(4,3)→(4,4)
    avoiding F entirely, so the controller follows the A* detour rather
    than the new escape branch.
    """
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(1, 2), velocity=(0, 0))}
    plans = PlanBundle(paths={}, created_step=0, horizon=1)
    sim = _SimStub(env, agents, humans, plans, step=0)
    sim.step_events = []

    forbidden = inflate_cells({humans[0].pos}, radius=1, env=env)
    assert (2, 2) in forbidden, "test geometry: agent must start inside F"
    assert (4, 4) not in forbidden, "test geometry: goal must be outside F"

    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=3)
    controller = _make_controller()

    action = controller.decide_action(sim, obs, rng=None)
    result = _resulting_cell((2, 2), action)

    assert action != StepAction.WAIT
    assert result not in forbidden
    assert sim.agents[0].last_action_was_safe_wait is False
    assert not any("[BUFFER-ESCAPE]" in e for e in sim.step_events), (
        f"escape branch should NOT have fired (A* reached goal directly); "
        f"got events: {sim.step_events}"
    )


def test_T_esc_3_corridor_surround_no_escape() -> None:
    """T-Esc-3 — Agent in F with every immediate neighbour also in F
    (corridor-surround).  The controller must Safe Wait and emit
    [BUFFER-TRAPPED] (not [SAFETY-WAIT]).

    Geometry: 5x5 open grid, r_safe=1, four humans at the four cells
    adjacent to (2,2) — (1,2), (3,2), (2,1), (2,3).  Each human's r_safe=1
    diamond covers itself plus (2,2), so all of {(1,2),(3,2),(2,1),(2,3)}
    are in F and (2,2) is too.  _find_escape_move filters out every
    neighbour and returns None → BUFFER-TRAPPED → Safe Wait.
    """
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4), task_id="t0")}
    humans = {
        0: HumanState(human_id=0, pos=(1, 2), velocity=(0, 0)),
        1: HumanState(human_id=1, pos=(3, 2), velocity=(0, 0)),
        2: HumanState(human_id=2, pos=(2, 1), velocity=(0, 0)),
        3: HumanState(human_id=3, pos=(2, 3), velocity=(0, 0)),
    }
    plans = PlanBundle(paths={}, created_step=0, horizon=1)
    sim = _SimStub(env, agents, humans, plans, step=0)
    sim.step_events = []

    forbidden = inflate_cells({h.pos for h in humans.values()}, radius=1, env=env)
    assert (2, 2) in forbidden
    for nb in [(1, 2), (3, 2), (2, 1), (2, 3)]:
        assert nb in forbidden, f"corridor-surround precondition: {nb} must be in F"

    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=3)
    controller = _make_controller()

    action = controller.decide_action(sim, obs, rng=None)

    assert action == StepAction.WAIT
    assert sim.agents[0].last_action_was_safe_wait is True
    assert any("[BUFFER-TRAPPED]" in e for e in sim.step_events), (
        f"expected [BUFFER-TRAPPED] log line, got: {sim.step_events}"
    )
    assert not any("[SAFETY-WAIT]" in e for e in sim.step_events), (
        f"expected [BUFFER-TRAPPED], not [SAFETY-WAIT], for corridor-surround; "
        f"got events: {sim.step_events}"
    )


def test_T_esc_4_multi_tick_stuck_then_escape() -> None:
    """T-Esc-4 — Agent surrounded at tick t (Safe Wait); at tick t+1 one
    neighbour opens because a human moves away.  The agent must escape on
    the next decide_action call.  Locks in the "agent cannot stay in F
    for more than 2 consecutive ticks unless trapped" invariant.

    Geometry at tick t: identical to T-Esc-3 (four humans around (2,2)).
    Between ticks: human 0 moves from (1,2) to (0,1).  At tick t+1, (1,2)
    is no longer in F, but (2,2) still is (because of the three remaining
    humans), so the escape branch fires and the agent steps to (1,2).
    """
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(0, 0), task_id="t0")}
    humans = {
        0: HumanState(human_id=0, pos=(1, 2), velocity=(0, 0)),
        1: HumanState(human_id=1, pos=(3, 2), velocity=(0, 0)),
        2: HumanState(human_id=2, pos=(2, 1), velocity=(0, 0)),
        3: HumanState(human_id=3, pos=(2, 3), velocity=(0, 0)),
    }
    plans = PlanBundle(paths={}, created_step=0, horizon=1)
    sim = _SimStub(env, agents, humans, plans, step=0)
    sim.step_events = []

    controller = _make_controller()

    # Tick t: agent surrounded — must Safe Wait.
    obs_t = build_observation(agent_id=0, sim_state=sim, fov_radius=3)
    action_t = controller.decide_action(sim, obs_t, rng=None)
    assert action_t == StepAction.WAIT
    assert sim.agents[0].last_action_was_safe_wait is True
    assert any("[BUFFER-TRAPPED]" in e for e in sim.step_events)

    # Between ticks: human 0 leaves the immediate neighbourhood,
    # vacating cell (1,2) and opening an F-respecting escape.
    sim.humans[0] = replace(sim.humans[0], pos=(0, 1))
    sim.step += 1
    sim.step_events = []  # fresh per-tick log buffer

    forbidden_tp1 = inflate_cells({h.pos for h in sim.humans.values()}, radius=1, env=env)
    assert (1, 2) not in forbidden_tp1, "test geometry: (1,2) must be outside F at t+1"
    assert (2, 2) in forbidden_tp1, "test geometry: agent still in F at t+1"

    obs_tp1 = build_observation(agent_id=0, sim_state=sim, fov_radius=3)
    action_tp1 = controller.decide_action(sim, obs_tp1, rng=None)
    result_tp1 = _resulting_cell((2, 2), action_tp1)

    assert action_tp1 != StepAction.WAIT, (
        f"agent must escape at tick t+1, not Safe Wait again; "
        f"got {action_tp1}, events: {sim.step_events}"
    )
    assert result_tp1 not in forbidden_tp1
    assert sim.agents[0].last_action_was_safe_wait is False
    assert any("[BUFFER-ESCAPE]" in e for e in sim.step_events), (
        f"expected [BUFFER-ESCAPE] log line at t+1, got: {sim.step_events}"
    )
