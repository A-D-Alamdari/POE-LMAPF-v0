from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import LocalPlanner, SimStateView
from ha_lmapf.core.types import Observation, StepAction
from ha_lmapf.local_tier.conflict_resolution.base import BaseConflictResolver, detect_imminent_conflict

Cell = Tuple[int, int]


@dataclass
class _TokenState:
    owner: int
    win_streak: int = 0
    last_step: int = -1


class TokenBasedResolver(BaseConflictResolver):
    """
    Communication-based resolver via token ownership per contested cell
    (paper §4.3 "Token-Based").  Renamed from ``TokenPassingResolver``;
    the old class name is retained as a module-level alias at the bottom
    of this file so existing imports continue to work.

    Deterministic given sim state.

    Priority tuple (higher is better):
      urgency = -distance_to_goal (smaller distance => larger priority)
      wait_steps (larger wait => higher priority)
      -agent_id (smaller id => higher priority)

    Fairness:
      if the same owner wins on the same cell for K consecutive conflicts, rotate ownership
      to the next best contender (if any).

    Theorem 1 invariant: when the non-owner cannot take the contested cell,
    its fallback path MUST respect the forbidden set
        F = B_{r_safe}(X_t^{Phi_i}) ∪ D(t)_extended.
    The ``forbidden`` kwarg passed to ``resolve`` carries F.  Both the 1-hop
    side-step and the optional A* fallback (when ``local_planner`` is
    provided) filter against F, and the WAIT fallthrough preserves the
    agent's pre-move position which the controller already guarantees lies
    outside F.
    """

    def __init__(self, fairness_k: int = 5) -> None:
        self.tokens: Dict[Cell, _TokenState] = {}
        self.fairness_k = int(max(1, fairness_k))

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
            # No imminent agent-agent conflict, proceed by mapping desired move to action
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Token is associated with the contested desired cell (vertex conflict) or the "to" cell (edge conflict)
        key_cell = desired_cell if conflict.kind == "vertex" else desired_cell

        contenders = self._contenders_for_cell(key_cell, sim_state)
        if agent_id not in contenders:
            contenders.append(agent_id)
        contenders = sorted(set(contenders))

        # Choose winner by priority tuple
        winner = max(contenders, key=lambda aid: self._priority(aid, sim_state))

        # Fairness rotation
        tok = self.tokens.get(key_cell)
        current_step = sim_state.step
        if tok is None:
            tok = _TokenState(owner=winner, win_streak=1, last_step=current_step)
            self.tokens[key_cell] = tok
        else:
            if tok.owner == winner:
                # Only increment streak once per timestep (resolve is called per-agent)
                if current_step != tok.last_step:
                    tok.win_streak += 1
                    tok.last_step = current_step
            else:
                tok.owner = winner
                tok.win_streak = 1
                tok.last_step = current_step

            if tok.win_streak >= self.fairness_k and len(contenders) > 1:
                # Rotate to next best contender (excluding current owner)
                ordered = sorted(contenders, key=lambda aid: self._priority(aid, sim_state), reverse=True)
                if ordered and ordered[0] == tok.owner:
                    rotated = ordered[1]
                    tok.owner = rotated
                    tok.win_streak = 1
                    winner = rotated

        if winner == agent_id:
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Non-owner: pick the safest fallback that respects F.
        cur = sim_state.agents[agent_id].pos

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
        # urgency: inverse distance -> use negative distance (higher is better)
        if a.goal is None:
            dist = 10 ** 9
        else:
            dist = manhattan(a.pos, a.goal)
        urgency = -dist
        return (urgency, int(a.wait_steps), -int(agent_id))

    def _contenders_for_cell(self, cell: Cell, sim_state: SimStateView) -> List[int]:
        """
        Conservative: consider agents that are adjacent to the contested cell or currently in it.
        """
        cont: List[int] = []
        for aid, a in sim_state.agents.items():
            if a.pos == cell or manhattan(a.pos, cell) == 1:
                cont.append(aid)
        return cont

    def _safe_side_step(
            self,
            agent_id: int,
            sim_state: SimStateView,
            observation: Observation,
            forbidden: Set[Cell],
    ) -> Optional[Cell]:
        """Pick a deterministic 1-hop side-step that is statically free, not
        in ``observation.blocked`` (D(t)_extended), not in ``forbidden`` (F),
        and not an imminent-conflict target.  Preference order: UP, DOWN,
        LEFT, RIGHT (via ``neighbors()``).
        """
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
        """Local A* from the agent's current cell toward its goal with
        ``blocked = observation.blocked ∪ forbidden ∪ {decided next positions
        of others}``.  Returns the next cell of the path or None if no
        F-respecting path exists.
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
        if nxt in forbidden:
            return None
        return nxt


# Backward-compatibility alias.  Old name retained so external imports
# (other modules, tests, archived experiment scripts) keep working.
TokenPassingResolver = TokenBasedResolver
