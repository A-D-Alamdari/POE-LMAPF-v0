from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Set, Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import LocalPlanner, SimStateView
from ha_lmapf.core.types import Observation, StepAction
from ha_lmapf.local_tier.conflict_resolution.base import BaseConflictResolver, detect_imminent_conflict

Cell = Tuple[int, int]

# Initial token endowment per (agent, cell), materialized lazily the first
# time the pair appears in a contention (locked semantics, resume-prompt-6).
INITIAL_ENDOWMENT = 5

# Belt-and-suspenders (locked semantics, task 2): the zero-token "+∞
# priority" rule is implemented by mapping a 0 count to float('inf') in the
# τ slot of the priority tuple, so the ordinary lexicographic tuple compare
# does the auto-win without any special-case branch.  Confirm at import that
# float('inf') really does dominate any finite τ in a tuple comparison.
assert (float("inf"), -1, 0, 0) > (5.0, 0, 99, 0), (
    "float('inf') must compare greater than finite τ in lexicographic tuple order"
)


class TokenBasedResolver(BaseConflictResolver):
    """
    Communication-based resolver (paper §4.3 "Token-Based").

    This is the resume-prompt-6 re-implementation that makes the code match
    the priority tuple the paper *claims*: ``ρ = (τ, -d, w)`` with a
    per-(agent, cell) token count ``τ`` as the primary key.  Per Decision 2b
    the paper is being defended, so the divergence characterised in
    audit 03 §2 (old code: ``(-d, w, -id)`` + single-owner K-rotation, no τ
    term) is resolved in favour of the paper.

    Mechanism (locked semantics):

    * **Per-(agent, cell) state.**  Each agent keeps an independent token
      counter for every cell it has ever contended for, stored in
      ``self._tokens[(agent_id, cell)]``.

    * **Initial endowment = 5, lazily materialized.**  ``_token`` returns 5
      for any pair not yet in the dict; the entry is written the first time
      that (agent, cell) pair takes part in a contention, so a
      first-contention winner goes 5 → 4 (not "nothing" → -1).

    * **Win-loss transfer.**  When agents contend for cell ``c`` and one
      wins, the winner's count at ``c`` decreases by 1 and *every* loser's
      count at ``c`` increases by 1.  The winner pays 1 **total** per
      contention regardless of how many losers there were.  This conserves
      tokens within each (winner, loser) pair but is **not** strict
      conservation across the whole contention when there is more than one
      loser — the cleanest reading of "win lose 1, lose gain 1".

    * **Floor at 0.**  A count never drops below 0: a decrement that would
      go negative is suppressed (Decision D1).  Increments are never
      suppressed.

    * **Zero-token rule.**  An agent at 0 tokens for the contested cell is
      automatically eligible to win: 0 is treated as τ = +∞.  Among several
      0-token contenders the rest of the tuple breaks the tie.

    * **Priority tuple (higher wins, lexicographic):** ``(τ, -d, w, -id)``
      where ``τ = +∞`` if the count is 0 else the count, ``d`` is the
      Manhattan distance from the agent's current cell to its goal, ``w`` is
      the agent's consecutive wait count, and ``id`` is the agent id.  So:
      higher τ wins; ties on τ go to smaller ``d`` (closer to goal); ties on
      τ and ``d`` go to larger ``w`` (waited longer); ties on everything go
      to smaller ``id``.

    * **State scope.**  Token counts live for the lifetime of one
      ``TokenBasedResolver`` instance — i.e. one ``Simulator`` run.  The
      simulator constructs a fresh resolver per run, so counts never cross
      runs.

    Theorem 1 invariant (unchanged from the previous implementation and from
    ``WaitBasedResolver``): when the calling agent loses the contention its
    fallback path MUST respect the forbidden set
        F = B_{r_safe}(X_t^{Phi_i}) ∪ D(t)_extended.
    The ``forbidden`` kwarg carries F; the 1-hop side-step and the optional
    A* fallback both filter against F, and the WAIT fallthrough preserves the
    agent's pre-move position which the controller guarantees lies outside F.
    The resolver reads ``forbidden`` via membership only and never mutates
    any caller-supplied collection (audit 03 §3 modularity property): the
    sole mutable state is ``self._tokens``, owned by the resolver.

    Note on the public ``resolve`` signature.  The resume-prompt-6 brief
    sketched a ``resolve(agent_id, desired_next, contenders, ...) ->
    ResolveOutcome`` shape, but the live contract — fixed by
    ``AgentController.decide_action`` and the ``ConflictResolver`` protocol,
    both explicitly out of scope for this change — is
    ``resolve(agent_id, desired_cell, sim_state, observation, rng,
    forbidden=, local_planner=) -> StepAction``.  The contention primitive
    the brief describes lives here as :meth:`contend` (which *does* take an
    explicit contender list and runs one token transfer); ``resolve`` is the
    thin per-agent adapter that gathers contenders, runs the contention once
    per tick, and maps the outcome to a ``StepAction``.
    """

    def __init__(self, fairness_k: Optional[int] = None) -> None:
        # Per-(agent, cell) token counts.  Absent key => INITIAL_ENDOWMENT.
        self._tokens: Dict[Tuple[int, Cell], int] = {}
        # Per-(step, cell) memo of the settled winner.  ``resolve`` is called
        # once per agent, but a contention's token transfer must be applied
        # exactly once; the memo lets later agents in the same tick reuse the
        # already-settled winner instead of re-running (and re-charging) the
        # contention.  Cleared whenever the simulation step advances so it
        # never holds more than one tick's worth of entries.
        self._contention_winner: Dict[Tuple[int, Cell], int] = {}
        self._memo_step: Optional[int] = None

        if fairness_k is not None:
            # K-rotation is gone (replaced by the per-(agent, cell) token
            # scheme).  The parameter is retained for backward compatibility
            # with archived configs/scripts but is inert.
            warnings.warn(
                "TokenBasedResolver(fairness_k=...) is deprecated and ignored: "
                "the single-owner K-rotation mechanism was replaced by the "
                "per-(agent, cell) token-count scheme (resume-prompt-6).",
                DeprecationWarning,
                stacklevel=2,
            )

    # ------------------------------------------------------------------
    # Token state
    # ------------------------------------------------------------------
    def _token(self, agent_id: int, cell: Cell) -> int:
        """Current token count for (agent_id, cell), defaulting to 5."""
        return self._tokens.get((agent_id, cell), INITIAL_ENDOWMENT)

    def _priority(self, agent_id: int, cell: Cell, sim_state: SimStateView) -> tuple:
        """Priority tuple for (agent_id, cell). Higher wins lexicographically."""
        t = self._token(agent_id, cell)
        a = sim_state.agents[agent_id]
        d = manhattan(a.pos, a.goal) if a.goal is not None else 10 ** 9
        w = int(a.wait_steps)
        # 0 tokens => "+∞ priority"; float('inf') keeps the lex compare branchless.
        tau = float("inf") if t == 0 else float(t)
        return (tau, -d, w, -int(agent_id))

    # ------------------------------------------------------------------
    # Contention primitive
    # ------------------------------------------------------------------
    def _settle(self, cell: Cell, winner: int, contenders: List[int]) -> None:
        """Apply the token transfer for a settled contention.

        Materializes the 5-token endowment for every contender at ``cell``
        first (so a first-contention winner goes 5 → 4 and a loser 5 → 6),
        then decrements the winner by 1 (floored at 0) and increments every
        other contender by 1 (never floored).
        """
        ids = set(contenders) | {winner}
        for aid in ids:
            self._tokens.setdefault((aid, cell), INITIAL_ENDOWMENT)
        # Winner pays exactly 1, floored at 0.
        self._tokens[(winner, cell)] = max(0, self._tokens[(winner, cell)] - 1)
        # Each loser gains 1, no ceiling.
        for aid in ids:
            if aid != winner:
                self._tokens[(aid, cell)] = self._tokens[(aid, cell)] + 1

    def _pick_winner(self, cell: Cell, contenders: List[int], sim_state: SimStateView) -> int:
        """Winner of a contention for ``cell`` by lexicographic-max priority."""
        return max(contenders, key=lambda aid: self._priority(aid, cell, sim_state))

    def contend(self, cell: Cell, contenders: List[int], sim_state: SimStateView) -> int:
        """Run ONE contention for ``cell`` among ``contenders``; return the winner.

        Picks the winner by the ``(τ, -d, w, -id)`` priority tuple, then
        applies the one-per-contention token transfer (winner -1 floored,
        each loser +1).  A degenerate "contention" with 0 or 1 contender
        touches no token state and just returns the lone id (or -1).
        """
        ids = sorted(set(contenders))
        if len(ids) <= 1:
            return ids[0] if ids else -1
        winner = self._pick_winner(cell, ids, sim_state)
        self._settle(cell, winner, ids)
        return winner

    # ------------------------------------------------------------------
    # Public resolve() — per-agent adapter (live contract)
    # ------------------------------------------------------------------
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
            # No imminent agent-agent conflict: follow the desired move.
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Token is associated with the contested cell (the desired "to" cell
        # for both vertex and edge conflicts, matching the prior resolver).
        key_cell = desired_cell

        winner = self._resolve_winner_once(agent_id, key_cell, sim_state)

        if winner == agent_id:
            return self.action_toward(sim_state.agents[agent_id].pos, desired_cell)

        # Loser: pick the safest fallback that respects F (Theorem 1).
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

    def _resolve_winner_once(self, agent_id: int, cell: Cell, sim_state: SimStateView) -> int:
        """Winner of the contention for ``cell`` this tick, settling tokens
        exactly once.

        ``resolve`` runs once per agent, so several agents may ask about the
        same contested ``cell`` within one tick.  The first call gathers the
        contenders, picks the winner, applies the token transfer, and
        memoizes the result keyed by ``(step, cell)``; later calls in the
        same tick reuse the memoized winner without re-charging tokens.  The
        memo is reset whenever the step advances.
        """
        step = getattr(sim_state, "step", 0)
        if step != self._memo_step:
            self._contention_winner.clear()
            self._memo_step = step

        memo_key = (step, cell)
        cached = self._contention_winner.get(memo_key)
        if cached is not None:
            return cached

        contenders = self._contenders_for_cell(cell, sim_state)
        if agent_id not in contenders:
            contenders.append(agent_id)
        winner = self.contend(cell, contenders, sim_state)
        self._contention_winner[memo_key] = winner
        return winner

    def _contenders_for_cell(self, cell: Cell, sim_state: SimStateView) -> List[int]:
        """Agents currently at the contested cell or one step away from it.

        Conservative neighbourhood, unchanged from the prior implementation:
        the τ re-implementation changed *who wins and how tokens move*, not
        *which agents are considered to be contending*.
        """
        cont: List[int] = []
        for aid, a in sim_state.agents.items():
            if a.pos == cell or manhattan(a.pos, cell) == 1:
                cont.append(aid)
        return cont

    # ------------------------------------------------------------------
    # Loser fallbacks (F-respecting) — identical policy to WaitBasedResolver
    # ------------------------------------------------------------------
    def _safe_side_step(
            self,
            agent_id: int,
            sim_state: SimStateView,
            observation: Observation,
            forbidden: Set[Cell],
    ) -> Optional[Cell]:
        """Pick a deterministic 1-hop side-step that is statically free, not
        in ``observation.blocked`` (D(t)_extended), not in ``forbidden`` (F),
        and not an imminent-conflict target.  Preference order via
        ``neighbors()``."""
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
        F-respecting path exists."""
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
