from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict

from ha_lmapf.core.grid import neighbors
from ha_lmapf.core.interfaces import LocalPlanner, SimStateView
from ha_lmapf.core.types import Observation, StepAction, TimedPath
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.local_tier.conflict_resolution import BaseConflictResolver

Cell = Tuple[int, int]


@dataclass
class AgentController:
    """
    Tier-2 per-agent controller implementing a Sense-Plan-Act loop:

    1) Follow next step from global timed plan (Tier-1) as a guidance policy.
    2) Human-aware safety: inflate visible human cells by safety_radius to create forbidden set.
       If desired move enters forbidden set, IMMEDIATELY trigger local replanning.
    3) If no global plan exists, use local planner to navigate to goal.
    4) Resolve imminent agent-agent conflicts via ConflictResolver (token / priority rules).

    Safety Modes:
    - hard_safety=True (default): Agents MUST NOT enter B_r(H_t).
      The inflated safety buffer is an absolute barrier per the paper's constraint:
          s_i(t) not in B_r(H_t)  for all i in {1, ..., k}
      If no path exists avoiding the buffer, the agent WAITs.
    - hard_safety=False: Safety buffer is a high-cost soft constraint.
      Agents can path through human zones when no alternative exists
      (prevents permanent deadlock at the cost of safety violations).
    """

    agent_id: int
    local_planner: LocalPlanner
    conflict_resolver: BaseConflictResolver
    fov_radius: int
    safety_radius: int
    hard_safety: bool = True
    global_path: Optional[TimedPath] = None
    # Fallback for ablation: after this many consecutive safety-waits
    # (when local replan is disabled), request a global replan.
    fallback_wait_limit: int = 5
    _consecutive_waits: int = 0

    def _predicted_forbidden(self, sim_state: SimStateView) -> set:
        """γ (evade) predicted-forbidden cell set — resume-prompt-5.

        Returns the set of cells where humans are predicted to be at
        t+1, each inflated by ``r_safe`` into a Manhattan ball so
        predicted humans get the SAME buffer treatment as observed
        ones (geometric symmetry with the observation-forbidden set).

        Empty set (=γ no-op) in three cases:
          * ``algorithm_variant != "evade"`` (baseline).
          * ``humans_block_on_agent_cells == True`` (γ defends the
            False regime; True has nothing to defend against -- the
            human-step physics already filters agent-occupied cells
            out of every legal-successor set, so a predicted-
            forbidden inflation would only deflate throughput
            without ever preventing a real encroachment).  γ is a
            literal no-op here, by construction; the True+evade and
            True+baseline runs execute identical code paths.
          * No human model is reachable on ``sim_state``.

        RISK-AVERSE semantics (Decision 3, option II): in the False
        regime a cell is forbidden iff its predicted probability is
        > 0 -- γ would rather detour around a 1%-likely human than
        risk a distance-0 encroachment.  The probability-weighted
        soft-penalty alternative (option I) was explicitly rejected.
        """
        cfg = getattr(sim_state, "config", None)
        if cfg is None or getattr(cfg, "algorithm_variant", "baseline") != "evade":
            return set()
        if bool(getattr(cfg, "humans_block_on_agent_cells", True)):
            return set()
        human_model = getattr(sim_state, "human_model", None)
        if human_model is None:
            return set()
        predictions = human_model.predict_next(
            sim_state.env,
            sim_state.humans,
            getattr(sim_state, "agent_positions", None),
        )
        predicted_cells: set = set()
        for _hid, dist in predictions.items():
            for cell, p in dist.items():
                if p > 0:
                    predicted_cells |= inflate_cells(
                        {cell}, radius=int(self.safety_radius),
                        env=sim_state.env,
                    )
        return predicted_cells

    def decide_action(self, sim_state: SimStateView, observation: Observation, rng=None) -> StepAction:
        aid = self.agent_id
        agent = sim_state.agents[aid]
        cur = agent.pos

        # Reset the per-tick wait-kind flags.  The controller sets at most
        # one of these true: ``last_action_was_safe_wait`` for safety /
        # no-path WAITs (read by ``RollingHorizonPlanner`` for the eta_w
        # emergency replan trigger, paper Section 4.4), and
        # ``last_action_was_yield_wait`` for conflict-resolution yields.
        # Disjoint by construction so the wait-kind metrics keep their
        # invariant ``total_wait_steps == safe_wait_steps + yield_wait_steps``.
        agent.last_action_was_safe_wait = False
        agent.last_action_was_yield_wait = False

        # Determine goal (from agent state if assigned; otherwise use current pos)
        goal = agent.goal if agent.goal is not None else cur

        # If we're already at the goal, just WAIT (idle, NOT a Safe Wait).
        if cur == goal:
            return StepAction.WAIT

        disable_local_replan = getattr(sim_state, "disable_local_replan", False)
        disable_conflict_resolution = getattr(sim_state, "disable_conflict_resolution", False)

        # Build human-aware forbidden set (inflate visible humans)
        human_cells = {h.pos for h in observation.visible_humans.values()}
        forbidden = inflate_cells(human_cells, radius=int(self.safety_radius), env=sim_state.env)
        blocked = set(observation.blocked) | set(forbidden)

        # ---- γ (evade) variant — resume-prompt-5, stage 3 -----------
        # When algorithm_variant == "evade", extend the forbidden set
        # with cells where humans are PREDICTED to be at t+1 (each
        # inflated by r_safe, see ``_predicted_forbidden``).  If the
        # agent's CURRENT cell is in that set, the agent is
        # predicted-encroached: it evades if it can, Safe-Waits if it
        # cannot, and either way its action is classified
        # response-attributable (the simulator's Def-1 classifier
        # reads the predicted-encroached tag written here).  The
        # branch is a no-op for baseline, leaving baseline behavior
        # byte-identical.
        predicted_cells = self._predicted_forbidden(sim_state)
        if predicted_cells:
            forbidden = forbidden | predicted_cells
            blocked = blocked | predicted_cells
            if cur in predicted_cells:
                simulator = getattr(sim_state, "simulator", None)
                pred_set = getattr(
                    simulator, "_predicted_encroached_this_tick", None)
                if pred_set is not None:
                    pred_set.add(aid)

        # Get desired next cell from global plan
        desired_next = self._desired_from_global_plan(sim_state)

        # Determine if we need local replanning
        needs_replan = False
        if desired_next is None:
            # No global plan available - must use local planning
            needs_replan = True
        elif desired_next in forbidden:
            # Global plan leads into human safety zone - replan
            needs_replan = True
        elif desired_next == cur and self._global_path_truly_exhausted(sim_state):
            # Global plan is exhausted (no meaningful moves remain) but goal
            # not reached.  A simple desired_next==cur is NOT sufficient —
            # the global planner (LaCAM) explicitly schedules waits to
            # coordinate agents.  Triggering a replan on a planned wait
            # destroys the coordinated plan and cascades into conflicts.
            needs_replan = True
        elif self._global_path_blocked(sim_state, forbidden):
            # Future steps of global path pass through human safety zones -
            # replan proactively to route around humans before we arrive.
            # NOTE: We intentionally do NOT replan here for agent-occupied cells.
            # Transient agent positions cause false-positive replans (agents move
            # every step). Agent-agent conflicts are resolved by the conflict
            # resolver (cheap wait/sidestep), not by expensive local A*.
            needs_replan = True

        if needs_replan and not disable_local_replan:
            # Determine reason for local replan
            if desired_next is None:
                replan_reason = "no-global-path"
            elif desired_next in forbidden:
                replan_reason = "human-safety-conflict"
            else:
                replan_reason = "path-exhausted"

            # Extract remaining global path cells to bias local A* toward
            # path-aligned detours (path-preserving local repair).
            guidance_cells = None
            if self.global_path is not None:
                idx = max(0, sim_state.step - self.global_path.start_step)
                guidance_cells = set(self.global_path.cells[idx:])

            # IMMEDIATELY trigger local replanning to find alternate path
            detour = self.local_planner.plan(
                sim_state.env, start=cur, goal=goal, blocked=blocked,
                guidance_cells=guidance_cells,
            )

            # Call global planner if deviation is large-enough
            deviation_ratio = self._deviation_ratio(sim_state, detour)

            if hasattr(sim_state, "flag_major_deviation") and hasattr(sim_state, "deviation_threshold"):
                if deviation_ratio > sim_state.deviation_threshold:
                    sim_state.flag_major_deviation()
                    self._log_event(sim_state,
                                    f"[MAJOR-DEVIATION] Agent {aid}: deviation={deviation_ratio:.2f} "
                                    f"> threshold={sim_state.deviation_threshold} → requesting global replan"
                                    )

            self.clear_path(sim_state)  # Clean current path

            if detour and len(detour) >= 2:
                desired_next = detour[1]
                self._count_replan(sim_state)
                # Store the local path for visualization
                self._store_local_path(sim_state, detour)
                self._log_event(sim_state,
                                f"[LOCAL-REPLAN] Agent {aid}: {replan_reason} at {cur} → "
                                f"A* detour ({len(detour)} steps) toward {goal}"
                                )
            else:
                # NOTE: Do NOT flag major_deviation here. A* failure means the
                # agent is surrounded by human safety zones — a local issue the
                # global planner cannot resolve (it doesn't model humans).
                # Flagging it causes global replan spam every step while the
                # agent is safety-waiting, wasting compute without benefit.

                if not self.hard_safety:
                    # Soft safety mode: try any safe neighbor as escape
                    escape = self._find_escape_move(cur, goal, blocked, sim_state.env)
                    if escape is not None:
                        desired_next = escape
                        self._count_replan(sim_state)
                        self._store_local_path(sim_state, [cur, escape])
                        self._log_event(sim_state,
                                        f"[ESCAPE] Agent {aid}: soft-safety escape {cur}→{escape}"
                                        )
                    else:
                        # Truly stuck - WAIT
                        self._log_event(sim_state,
                                        f"[SAFETY-WAIT] Agent {aid}: no safe move at {cur} (soft-safety, stuck)"
                                        )
                        return self._safe_wait(agent)
                else:
                    # Hard safety mode: cannot violate B_r(H_t).
                    # Per the paper's Section 4.3 buffer-escape invariant,
                    # if the agent is itself inside F at the start of the
                    # tick it must still attempt a one-step F-respecting
                    # move before falling back to WAIT.  WAIT fires only
                    # in the corridor-trap case where every immediate
                    # neighbor is also in F.
                    if cur in forbidden:
                        escape = self._find_escape_move(cur, goal, blocked, sim_state.env)
                        if escape is not None:
                            desired_next = escape
                            self._count_replan(sim_state)
                            self._store_local_path(sim_state, [cur, escape])
                            self._log_event(sim_state,
                                            f"[BUFFER-ESCAPE] Agent {aid}: {cur}→{escape} "
                                            f"(F-respecting one-step escape; A* to goal infeasible)"
                                            )
                            # Fall through to the post-replan code path so
                            # the conflict resolver still arbitrates against
                            # other agents' intended cells.
                        else:
                            self._log_event(sim_state,
                                            f"[BUFFER-TRAPPED] Agent {aid}: cur {cur} in F and "
                                            f"every neighbor also in F → waiting (hard-safety)"
                                            )
                            if hasattr(sim_state, "mark_safety_wait"):
                                sim_state.mark_safety_wait(aid)
                            return self._safe_wait(agent)
                    else:
                        self._log_event(sim_state,
                                        f"[SAFETY-WAIT] Agent {aid}: no safe detour at {cur} → waiting (hard-safety)"
                                        )
                        if hasattr(sim_state, "mark_safety_wait"):
                            sim_state.mark_safety_wait(aid)
                        return self._safe_wait(agent)
        elif needs_replan and disable_local_replan:
            # Local replanning is disabled (ablation).  The agent cannot
            # detour around the human, so it must wait.  After
            # `fallback_wait_limit` consecutive waits we ask Tier-1 for a
            # fresh global plan that hopefully routes around the obstacle.
            self._consecutive_waits += 1
            if hasattr(sim_state, "mark_safety_wait"):
                sim_state.mark_safety_wait(aid)
            if self._consecutive_waits >= self.fallback_wait_limit:
                if hasattr(sim_state, "flag_major_deviation"):
                    sim_state.flag_major_deviation()
                self._log_event(
                    sim_state,
                    f"[FALLBACK-REQUERY] Agent {aid}: {self._consecutive_waits} "
                    f"consecutive waits (local replan disabled) → requesting global replan",
                )
                self._consecutive_waits = 0
            self._clear_local_path(sim_state)
            self.clear_path(sim_state)
            return self._safe_wait(agent)
        else:
            # Following global plan - clear any stored local path
            self._clear_local_path(sim_state)

        # Safety check: ensure desired cell is valid
        if desired_next is None or not sim_state.env.is_free(desired_next):
            self.clear_path(sim_state)
            return self._safe_wait(agent)

        # Hard safety enforcement: never enter the inflated safety buffer
        if self.hard_safety and desired_next in forbidden:
            self.clear_path(sim_state)
            return self._safe_wait(agent)

        # Final safety check: don't move into human-occupied cells
        if desired_next in human_cells:
            self.clear_path(sim_state)
            return self._safe_wait(agent)

        # Delegate agent-agent conflict avoidance.  Plumb the forbidden set
        # F = B_{r_safe}(X_t^{Phi_i}) and a local planner reference so that
        # the resolver's loser-fallback path can respect Theorem 1's
        # invariant: no executed action enters F.  See the resolver
        # implementations and tests/test_theorem1_resolver.py.
        action = self.conflict_resolver.action_toward(sim_state.agents[self.agent_id].pos, desired_next)
        resolved_action = self.conflict_resolver.resolve(
            agent_id=aid,
            desired_cell=desired_next,
            sim_state=sim_state,
            observation=observation,
            rng=rng,
            forbidden=forbidden,
            local_planner=self.local_planner,
        )

        if action != resolved_action:
            # Do NOT clear the global path here.  The conflict resolver reroutes
            # the agent for this single step; the global plan remains the best
            # guidance for all subsequent steps.  Nulling it causes a cascade:
            #   conflict → no global path → local A* → shorter detour path →
            #   path-exhausted next step → local A* again → oscillation.
            # Instead we mark the plan as stale (agent deviated for one step)
            # so the rolling horizon knows to replan sooner if many agents diverge.
            if hasattr(sim_state, "set_local_path"):
                sim_state.set_local_path(aid, [cur])  # registers stale, no detour stored

            self._log_event(sim_state,
                            f"[CONFLICT] Agent {aid}: agent-agent conflict at {cur} → "
                            f"{action.name}→{resolved_action.name}"
                            )

            if disable_conflict_resolution:
                # Conflict-induced WAIT under the ablation flag — this is
                # a yield, not a safety wait.
                return self._yield_wait(agent)

        # If the resolver yielded the agent (WAIT due to conflict-loss),
        # mark this as a yield-WAIT.  Yields are a normal cost of
        # decentralised conflict resolution and are tracked separately
        # from safety-induced WAITs (which dominate the eta_w emergency
        # replan signal).
        if resolved_action == StepAction.WAIT:
            return self._yield_wait(agent)

        # Agent is moving (not safety-waiting) — clear any stale safety-wait flag
        self._consecutive_waits = 0
        if hasattr(sim_state, "clear_safety_wait"):
            sim_state.clear_safety_wait(aid)

        return resolved_action

    @staticmethod
    def _safe_wait(agent) -> StepAction:
        """Set ``agent.last_action_was_safe_wait = True`` and return WAIT.

        Used at safety-induced WAIT branches in :meth:`decide_action`
        (no F-respecting move available, ``desired_next ∈ F``, A* failed,
        etc.).  Read by :class:`RollingHorizonPlanner` for the eta_w
        emergency replan trigger, and accounted as ``safe_wait_steps``
        in the metrics tracker.  Disjoint from :meth:`_yield_wait`.
        """
        agent.last_action_was_safe_wait = True
        return StepAction.WAIT

    @staticmethod
    def _yield_wait(agent) -> StepAction:
        """Set ``agent.last_action_was_yield_wait = True`` and return WAIT.

        Used when the resolver yielded the agent after losing a vertex /
        edge conflict, or when ``disable_conflict_resolution`` forces a
        yield.  Counted as ``yield_wait_steps`` in the metrics tracker.
        Disjoint from :meth:`_safe_wait`.
        """
        agent.last_action_was_yield_wait = True
        return StepAction.WAIT

    def _global_path_truly_exhausted(self, sim_state: SimStateView) -> bool:
        """
        Check whether the global path is truly exhausted (all remaining cells
        equal the agent's current position), as opposed to a planned wait
        where the global planner scheduled the agent to stay for one or more
        steps before continuing.

        LaCAM/CBS explicitly plan waits to coordinate agents. If the next cell
        is cur but later cells are different, the agent should follow the plan
        and WAIT, not trigger an expensive local A* replan that destroys the
        coordinated global plan.
        """
        plans = sim_state.plans()
        if plans is None:
            return True
        path = plans.paths.get(self.agent_id)
        if path is None:
            return True

        cur = sim_state.agents[self.agent_id].pos
        idx = max(0, sim_state.step - path.start_step)
        remaining = path.cells[idx:]

        # Path is truly exhausted only if ALL remaining cells == cur
        return all(c == cur for c in remaining)

    def _global_path_blocked(self, sim_state: SimStateView, blocked: set) -> bool:
        """
        Check if the near-future path passes through any blocked cell
        (e.g., an idle agent). If so, replanning now avoids walking up to
        the obstacle and stopping.

        Only checks the next `fov_radius` steps — agents further ahead
        will likely move before we reach them, so checking the entire
        remaining path causes excessive false-positive replanning.
        """
        plans = sim_state.plans()
        if plans is None:
            return False
        path = plans.paths.get(self.agent_id)
        if path is None:
            return False
        idx = max(0, sim_state.step - path.start_step)
        # Lookahead limited to FOV radius: only check cells we can
        # actually observe. Agents beyond this horizon are invisible
        # and will likely move before we arrive.
        lookahead = self.fov_radius
        remaining = path.cells[idx: idx + lookahead]
        for cell in remaining:
            if cell in blocked:
                return True
        return False

    def _find_escape_move(self, cur: Cell, goal: Cell, blocked, env) -> Optional[Cell]:
        """
        Find a safe neighbor cell to move to when stuck.
        Prefers cells that move closer to the goal.

        Called from two paths: soft-safety A*-failure, and hard-safety
        buffer-escape (paper Section 4.3) when cur is in F.  The body
        filters out cells in ``blocked`` either way, so it never returns
        a cell that violates the hard-safety constraint.
        """
        from ha_lmapf.core.grid import manhattan

        best_cell = None
        best_dist = float('inf')

        for nb in neighbors(cur):
            if not env.is_free(nb):
                continue
            if nb in blocked:
                continue

            dist = manhattan(nb, goal)
            if dist < best_dist:
                best_dist = dist
                best_cell = nb

        return best_cell

    def _desired_from_global_plan(self, sim_state: SimStateView) -> Optional[Cell]:
        plans = sim_state.plans()
        if plans is None:
            return None

        path = plans.paths.get(self.agent_id)
        if path is None:
            return None

        nxt = path(sim_state.step + 1)
        return nxt

    def _deviation_ratio(self, sim_state: SimStateView, detour: List[Tuple[int, int]]) -> float:
        """
        Deviation Ratio = 1. - Jaccard Coefficient(Global Path, New Path)
        """
        if detour is None or len(detour) < 2:
            return 0.

        if self.global_path is None:
            return 0.

        org_path_start_idx = sim_state.step - self.global_path.start_step

        org_path_cells = set(self.global_path.cells[org_path_start_idx:])
        detour_cells = set(detour)

        common_cells = org_path_cells & detour_cells
        total_cells = org_path_cells | detour_cells

        if len(total_cells) > 0:
            return 1. - (len(common_cells) / len(total_cells))

        return 0.

    @staticmethod
    def _log_event(sim_state: SimStateView, msg: str) -> None:
        """Append a structured event message to the simulator's per-step log."""
        if hasattr(sim_state, "step_events"):
            sim_state.step_events.append(msg)

    def _count_replan(self, sim_state: SimStateView) -> None:
        """
        Increment replans counter via sim_state hook when available.
        """
        if hasattr(sim_state, "metrics"):
            m = sim_state.metrics
            if hasattr(m, "add_local_replan"):
                m.add_local_replan(1)
            if hasattr(m, "add_replan"):
                m.add_replan(1)
            return
        if hasattr(sim_state, "on_local_replan"):
            getattr(sim_state, "on_local_replan")()
            return

    def _store_local_path(self, sim_state: SimStateView, path: list) -> None:
        """
        Store the local replanned path for visualization.
        """
        if hasattr(sim_state, "set_local_path"):
            sim_state.set_local_path(self.agent_id, path)
            # Use new plan
            sim_state.plans().paths[self.agent_id] = TimedPath(path, sim_state.step)

    def clear_path(self, sim_state: SimStateView):
        """
        Clear the path since it is revised
        """
        if sim_state.plans() is not None:
            sim_state.plans().paths[self.agent_id] = None

        self._clear_local_path(sim_state)

    def _clear_local_path(self, sim_state: SimStateView) -> None:
        """
        Clear the stored local path when following global plan.
        """
        if hasattr(sim_state, "clear_local_path"):
            sim_state.clear_local_path(self.agent_id)
