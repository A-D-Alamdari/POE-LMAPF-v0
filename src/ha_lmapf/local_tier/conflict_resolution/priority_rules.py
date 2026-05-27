from __future__ import annotations

from typing import Optional, Set, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import LocalPlanner, SimStateView
from ha_lmapf.core.types import Observation, StepAction
from ha_lmapf.local_tier.conflict_resolution.base import BaseConflictResolver, detect_imminent_conflict

Cell = Tuple[int, int]


class WaitBasedResolver(BaseConflictResolver):
    """
    Communication-free deterministic resolver (paper §4.3 "Wait-Based").

    Renamed from ``PriorityRulesResolver`` to ``WaitBasedResolver`` to
    emphasize its distinguishing feature — a starvation boost on the
    consecutive Safe-Wait streak.  ``PriorityRulesResolver`` is retained
    as a module-level alias at the bottom of this file so existing
    imports continue to work.

    Priority tuple (higher is better):
      (urgency, wait_steps, -agent_id)
    where urgency = -distance_to_goal, optionally boosted if wait_steps exceeds threshold.

    Theorem 1 invariant: when the agent loses a vertex/edge conflict the
    fallback path MUST respect the forbidden set
        F = B_{r_safe}(X_t^{Phi_i}) ∪ D(t)_extended
    The ``forbidden`` kwarg passed to ``resolve`` carries F.  Both the 1-hop
    side-step and the optional A* fallback (when ``local_planner`` is
    provided) filter against F, and the WAIT fallthrough preserves the
    agent's pre-move position which the controller already guarantees lies
    outside F.
    """

    def __init__(self, starvation_threshold: int = 10, boost: int = 50, allow_side_step: bool = True) -> None:
        self.starvation_threshold = int(max(1, starvation_threshold))
        self.boost = int(boost)
        self.allow_side_step = bool(allow_side_step)

    def resolve(
            self,
            agent_id: int,
            desired_cell: Cell,
            sim_state: SimStateView,
            observation: Observation,
            rng=None,  # unused
            forbidden: Optional[Set[Cell]] = None,
            local_planner: Optional[LocalPlanner] = None,
            **_kwargs,
    ) -> StepAction:
        forbidden_set: Set[Cell] = set(forbidden) if forbidden else set()

        conflict = detect_imminent_conflict(agent_id, desired_cell, sim_state)
        if conflict is None:
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        other_id = conflict.other_agent_id
        p_self = self._priority(agent_id, sim_state)
        p_other = self._priority(other_id, sim_state)

        # Deterministic: higher tuple wins; if tie, lower agent_id wins because -agent_id is higher
        if p_self > p_other:
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Lose: pick the safest fallback that respects F.
        cur = sim_state.agents[agent_id].pos

        if self.allow_side_step:
            side = self._safe_side_step(agent_id, sim_state, observation, forbidden_set)
            if side is not None:
                return self.action_toward(cur, side)

        if local_planner is not None:
            nxt = self._astar_fallback(
                agent_id, sim_state, observation, forbidden_set, local_planner,
            )
            if nxt is not None:
                return self.action_toward(cur, nxt)

        # Safe Wait: cur is invariant-guaranteed to be outside F.
        return StepAction.WAIT

    def _priority(self, agent_id: int, sim_state: SimStateView) -> Tuple[int, int, int]:
        a = sim_state.agents[agent_id]
        if a.goal is None:
            dist = 10 ** 9
        else:
            dist = manhattan(a.pos, a.goal)
        urgency = -dist

        # Starvation prevention: boost urgency once wait exceeds threshold
        if a.wait_steps > self.starvation_threshold:
            urgency += self.boost

        return (urgency, int(a.wait_steps), -int(agent_id))

    def _safe_side_step(
            self,
            agent_id: int,
            sim_state: SimStateView,
            observation: Observation,
            forbidden: Set[Cell],
    ) -> Optional[Cell]:
        """Pick a 1-hop neighbor that is statically free, not in
        ``observation.blocked`` (D(t)_extended), not in ``forbidden`` (F),
        and not a fresh imminent-conflict target."""
        cur = sim_state.agents[agent_id].pos
        for nb in neighbors(cur):
            if not sim_state.env.is_free(nb):
                continue
            if nb in observation.blocked:
                continue
            if nb in forbidden:
                continue
            c = detect_imminent_conflict(agent_id, nb, sim_state)
            if c is None:
                return nb
        return None

    @staticmethod
    def _astar_fallback(
            agent_id: int,
            sim_state: SimStateView,
            observation: Observation,
            forbidden: Set[Cell],
            local_planner: LocalPlanner,
    ) -> Optional[Cell]:
        """Run a local A* from the agent's current cell toward its goal with
        ``blocked = observation.blocked ∪ forbidden ∪ {decided next positions
        of other agents}``.  Returns the first cell of the path (the next
        move) or None if no F-respecting path exists.

        This is the path Theorem 1 relies on: any move it returns is
        guaranteed not to be in F, and the WAIT fallthrough is invoked when
        it returns ``[]``.
        """
        agent = sim_state.agents[agent_id]
        cur = agent.pos
        goal = agent.goal if agent.goal is not None else cur
        if cur == goal:
            return None

        decided: Set[Cell] = set()
        if hasattr(sim_state, "decided_next_positions"):
            for oid, pos in sim_state.decided_next_positions().items():
                if oid != agent_id:
                    decided.add(pos)

        blocked: Set[Cell] = set(observation.blocked) | forbidden | decided
        path = local_planner.plan(sim_state.env, cur, goal, blocked)
        if not path or len(path) < 2:
            return None
        nxt = path[1]
        # Defensive: never return an F cell.
        if nxt in forbidden:
            return None
        return nxt


# Backward-compatibility alias.  Old name retained so external imports
# (other modules, tests, archived experiment scripts) keep working.
PriorityRulesResolver = WaitBasedResolver
