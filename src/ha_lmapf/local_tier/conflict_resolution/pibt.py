from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import SimStateView
from ha_lmapf.core.types import Observation, StepAction
from ha_lmapf.local_tier.conflict_resolution.base import BaseConflictResolver, detect_imminent_conflict

Cell = Tuple[int, int]


@dataclass
class PIBTResolver(BaseConflictResolver):
    """
    Lightweight PIBT-style conflict resolver (depth-2 push, no recursion).

    On a desired move for agent i:
      1) If no imminent conflict -> proceed.
      2) If vertex conflict with blocking agent j at desired cell:
            Try to "push" j to move to its best alternative neighbor (including WAIT)
            that reduces its distance to its own goal (or keeps it minimal), and does not
            immediately conflict with other agents.
         If push feasible -> allow i to proceed (we assume j will yield by moving away).
         Else -> WAIT (or optionally side-step, but kept simple).

    Notes:
      - This resolver does NOT actually command the other agent; it only decides whether
        the current agent should proceed, using a conservative feasibility check.
      - Deterministic: fixed tie-breaks; no RNG.
    """

    allow_side_step: bool = False

    def resolve(
            self,
            agent_id: int,
            desired_cell: Cell,
            sim_state: SimStateView,
            observation: Observation,
            rng=None,  # unused
            **_kwargs,  # accept (and ignore) Theorem-1 plumbing kwargs from AgentController
    ) -> StepAction:
        conflict = detect_imminent_conflict(agent_id, desired_cell, sim_state)
        if conflict is None:
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Only handle vertex conflicts for the push attempt. Otherwise, WAIT conservatively.
        if conflict.kind != "vertex":
            return StepAction.WAIT

        blocker = conflict.other_agent_id

        # Attempt depth-2 push: can blocker move away to a safe alternative next cell?
        if self._can_push_blocker(blocker_id=blocker, sim_state=sim_state, obs_of_blocker=None):
            # If blocker can move away, allow current agent to proceed to desired_cell.
            # We still should ensure current move doesn't conflict with *another* agent (rare here).
            second_conflict = detect_imminent_conflict(agent_id, desired_cell, sim_state)
            if second_conflict is None or second_conflict.other_agent_id == blocker:
                return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Push failed -> WAIT (or optionally side-step)
        if self.allow_side_step:
            side = self._safe_side_step(agent_id, sim_state, observation)
            if side is not None:
                return self.action_toward(sim_state.agents[agent_id].pos, side)

        return StepAction.WAIT

    def _can_push_blocker(self, blocker_id: int, sim_state: SimStateView,
                          obs_of_blocker: Optional[Observation]) -> bool:
        """
        Decide if blocker has at least one feasible alternative move next step that:
          - is statically free
          - is not currently occupied by another agent (except itself)
          - does not create an imminent conflict for blocker (vertex/edge) based on global plan
        This is a conservative feasibility check; it does not require actual execution.
        """
        blocker = sim_state.agents[blocker_id]
        cur = blocker.pos
        goal = blocker.goal

        # Candidate moves: neighbors + WAIT (include WAIT as last option)
        cands = neighbors(cur) + [cur]

        # Deterministic scoring: minimize distance to own goal, then prefer moving (non-WAIT),
        # then lexicographic cell for stability.
        def score(cell: Cell):
            d = manhattan(cell, goal) if goal is not None else 10 ** 9
            is_wait = 1 if cell == cur else 0  # prefer moving => smaller is_wait
            return d, is_wait, cell[0], cell[1]

        # Occupied by other agents (current positions)
        occupied = {aid: a.pos for aid, a in sim_state.agents.items()}
        other_cells = {p for aid, p in occupied.items() if aid != blocker_id}

        for nb in sorted(cands, key=score):
            if not sim_state.env.is_free(nb):
                continue
            if nb in other_cells:
                continue

            # Build a minimal observation-like blocked set if none provided.
            # We do not have the blocker's local FOV here, so use static blocked only.
            # This makes the push test optimistic regarding humans, but still conservative for agents.
            conflict = detect_imminent_conflict(blocker_id, nb, sim_state)
            if conflict is None:
                return True

        return False

    def _safe_side_step(self, agent_id: int, sim_state: SimStateView, observation: Observation) -> Optional[Cell]:
        cur = sim_state.agents[agent_id].pos
        for nb in neighbors(cur):
            if not sim_state.env.is_free(nb):
                continue
            if nb in observation.blocked:
                continue
            if detect_imminent_conflict(agent_id, nb, sim_state) is None:
                return nb
        return None
