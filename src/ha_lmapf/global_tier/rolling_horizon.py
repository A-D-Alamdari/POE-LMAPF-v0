from __future__ import annotations

from typing import Dict, Optional, Tuple

from ha_lmapf.core.interfaces import SimStateView, GlobalPlanner
from ha_lmapf.core.types import AgentState, PlanBundle, Task, TimedPath


# Allocator (Matches your task_allocator.py file name)


# Sentinel used by _reanchor_last_good to distinguish "agent absent
# from the stored goal snapshot" from "agent was tracked with goal
# None".  The former must fall back to WAIT; the latter must still be
# eligible for path reuse when its goal is still None.
_SENTINEL = object()


class RollingHorizonPlanner:
    """
    Tier-1 global planner scheduler for lifelong MAPF.
    """

    def __init__(
            self,
            horizon: int,
            replan_every: int,
            solver_name: str = "cbs",
            solver_impl: Optional[GlobalPlanner] = None,
            exhaustion_fraction: float = 0.4,
            safety_wait_fraction: float = 0.3,
            eta_w: float = 0.20,
            replan_min_gap: int = 3,
    ) -> None:
        """
        Initialize the planner.

        Args:
            horizon: Planning horizon length.
            replan_every: Re-plan interval.
            solver_name: Name of solver to use if solver_impl is None.
                         Options: "cbs", "lacam", "lacam3", "lacam_official", "pibt2"
            solver_impl: (Optional) A specific solver instance.
                         If provided, this OVERRIDES 'solver_name'
            exhaustion_fraction: If this fraction of agents have stale global
                plans (due to path-exhausted or no-global-path local replans),
                trigger an early global replan regardless of the periodic
                schedule. Default 0.4 (40 % of agents).
            safety_wait_fraction: If this fraction of agents are stuck in
                consecutive SAFETY-WAIT (flagged via major_deviation), trigger
                an early global replan. Default 0.3 (30 % of agents).
            eta_w: Paper Section 4.4 emergency replan threshold.  When the
                fraction of controlled agents that committed Safe Wait in
                the previous tick exceeds ``eta_w``, fire an off-period
                replan (subject to ``replan_min_gap``).  Default 0.20.
            replan_min_gap: Anti-thrash guard for the eta_w trigger — the
                minimum number of ticks between two successive replans.
                Default 3.
        """
        self.horizon = int(horizon)
        self.replan_every = max(1, int(replan_every))
        self.exhaustion_fraction = float(exhaustion_fraction)
        self.safety_wait_fraction = float(safety_wait_fraction)
        self.eta_w = float(eta_w)
        self.replan_min_gap = max(1, int(replan_min_gap))
        # ``last_replan_step`` is updated on every actual replan fire
        # (periodic, deviation, exhaustion, safety-wait, or eta_w).  The
        # eta_w trigger uses it to enforce ``replan_min_gap``.
        self.last_replan_step: int = -10 ** 9
        # Event counter: number of off-period replans fired specifically by
        # the eta_w trigger.  Inspected by tests/test_emergency_replan.py.
        self.emergency_replans_eta_w: int = 0

        # Setup Solver (Dependency Injection or Factory)
        if solver_impl is not None:
            self.solver = solver_impl
        else:
            # Use GlobalPlannerFactory for consistent solver creation
            from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
            self.solver = GlobalPlannerFactory.create(solver_name)

        # State tracking
        self.last_planned_step: int = -99999
        self.completed_tasks_seen: int = 0
        # Minimum gap between two consecutive emergency replans (avoid spam)
        self._min_emergency_gap: int = max(3, replan_every // 4)
        self._last_emergency_step: int = -99999
        # Track whether the last global replan produced useful (non-WAIT) paths.
        # If the solver consistently fails (e.g. binary not found), emergency
        # replans would fire every min_gap steps and multiply the waste.
        # We suppress emergency triggers when the last replan was useless.
        self._last_replan_useful: bool = True

        # Previous-plan reuse machinery.  ``_last_good_bundle`` is the
        # most recent PlanBundle whose status was ``complete`` /
        # ``partial_anytime``; ``_last_good_goals`` is the snapshot of
        # ``{aid: goal}`` taken at that step so we can fall back to
        # per-agent WAIT when an agent's goal has since changed.  On a
        # solver failure (``timeout_no_result`` / ``error`` /
        # ``binary_not_found``) the dispatch re-anchors the stored
        # bundle to the current step instead of emitting the all-WAIT
        # plan ``SolverResult.plan`` carries.  ``_fallback_reuse_count``
        # is the cumulative re-anchor counter, mirrored into
        # ``Metrics.solver_fallback_reuses`` via the simulator's
        # tracker.  A reused plan is still a solver failure: the
        # underlying solver_timeouts / solver_errors counter is also
        # incremented on the same replan.
        self._last_good_bundle: Optional[PlanBundle] = None
        self._last_good_goals: Dict[int, Optional[Tuple[int, int]]] = {}
        self._fallback_reuse_count: int = 0

    def _exhaustion_trigger(self, sim_state: SimStateView) -> bool:
        """
        Return True if too many agents have stale global plans.

        A stale plan means the agent already triggered a local A* replan
        (path-exhausted or no-global-path) and the global plan is no longer
        guiding them.  When a large fraction of agents are in this state the
        coordinated plan has effectively collapsed; replanning sooner recovers
        throughput without waiting for the full periodic interval.
        """
        if self.exhaustion_fraction <= 0.0:
            return False
        n_agents = len(getattr(sim_state, "agents", {}))
        if n_agents == 0:
            return False
        stale = getattr(sim_state, "stale_global_plan_agents", None)
        if stale is None or not callable(stale):
            return False
        n_stale = len(stale())
        return (n_stale / n_agents) >= self.exhaustion_fraction

    def _eta_w_trigger(self, sim_state: SimStateView, cur_step: int) -> bool:
        """Paper Section 4.4 emergency replan trigger.

        Returns True iff
            (i)  the fraction of controlled agents whose committed action
                 the previous tick was a Safe Wait exceeds ``self.eta_w``,
            (ii) at least ``self.replan_min_gap`` ticks have elapsed since
                 the last replan fire, and
            (iii) the previous replan was useful (avoid feedback loops when
                  the solver is consistently failing).

        The Safe-Wait flag is the per-tick boolean
        ``AgentState.last_action_was_safe_wait``; it is reset to False at
        the top of every ``AgentController.decide_action`` call and set to
        True at every Safe-Wait return branch in the controller.  Reading
        it here at the *start* of tick t therefore reflects each agent's
        committed action at tick t-1.
        """
        if self.eta_w <= 0.0:
            return False
        agents = getattr(sim_state, "agents", {})
        n = len(agents)
        if n == 0:
            return False
        if (cur_step - self.last_replan_step) < self.replan_min_gap:
            return False
        if not self._last_replan_useful:
            return False
        n_safe_wait = sum(
            1 for a in agents.values()
            if getattr(a, "last_action_was_safe_wait", False)
        )
        frac = n_safe_wait / n
        return frac > self.eta_w

    def _reanchor_last_good(
            self,
            agents: Dict[int, AgentState],
            cur_step: int,
            horizon: int,
    ) -> PlanBundle:
        """Shift / clip ``self._last_good_bundle`` so it is valid for
        ``cur_step`` over ``horizon`` ticks.

        For each agent in ``agents``:

        * If the agent's identity is unchanged and its goal still
          matches the snapshot taken when the bundle was stored, take
          the tail of the stored ``TimedPath`` starting at index
          ``cur_step - start_step``; clip or pad-with-last-cell to
          length ``horizon + 1``.
        * Otherwise (agent absent from the stored bundle, goal
          changed, agent newly added, ``offset < 0``, or stored tail
          empty), emit a WAIT path at the agent's current position
          for that agent only.

        The returned bundle carries ``created_step = cur_step`` so the
        simulator's downstream consumers (``AgentController.global_path
        .__call__``) index it correctly.
        """
        stored = self._last_good_bundle
        assert stored is not None  # callers gate on this
        last_paths = stored.paths
        last_goals = self._last_good_goals
        new_paths: Dict[int, Optional[TimedPath]] = {}
        for aid, agent in agents.items():
            stored_path = last_paths.get(aid)
            goal_matches = last_goals.get(aid, _SENTINEL) == agent.goal
            new_cells: Optional[list] = None
            if stored_path is not None and goal_matches:
                offset = cur_step - stored_path.start_step
                if 0 <= offset < len(stored_path.cells):
                    tail = stored_path.cells[offset:]
                    new_cells = list(tail[: horizon + 1])
                    if len(new_cells) < horizon + 1:
                        pad = new_cells[-1] if new_cells else agent.pos
                        new_cells.extend([pad] * (horizon + 1 - len(new_cells)))
                elif offset >= len(stored_path.cells) and stored_path.cells:
                    # The stored path has already run out — the agent
                    # was expected to be parked at its final cell; keep
                    # it there.
                    new_cells = [stored_path.cells[-1]] * (horizon + 1)
            if new_cells is None:
                # Goal changed, agent unknown, or offset was negative.
                # Falling back per-agent (not globally) avoids dropping
                # the plan-quality benefit for agents whose goals are
                # still valid.
                new_cells = [agent.pos] * (horizon + 1)
            new_paths[aid] = TimedPath(cells=new_cells, start_step=cur_step)
        return PlanBundle(paths=new_paths,
                          created_step=cur_step, horizon=horizon)

    def _safety_wait_trigger(self, sim_state: SimStateView) -> bool:
        """
        Return True if too many agents are stuck in consecutive SAFETY-WAITs.

        When multiple agents are simultaneously frozen by the human safety
        buffer they clog corridors, causing downstream agent-agent conflicts
        and further degrading throughput.  An early global replan redistributes
        agents onto less-congested routes.

        Note: the global planner does not model humans, so it cannot directly
        resolve the blocking.  The benefit is rerouting OTHER agents around
        the congestion that the frozen agents are creating.
        """
        if self.safety_wait_fraction <= 0.0:
            return False
        n_agents = len(getattr(sim_state, "agents", {}))
        if n_agents == 0:
            return False
        waiting = getattr(sim_state, "safety_wait_agents", None)
        if waiting is None or not callable(waiting):
            return False
        n_waiting = len(waiting())
        return (n_waiting / n_agents) >= self.safety_wait_fraction

    def step(self, sim_state: SimStateView, assignments: Dict[int, Task]) -> Optional[PlanBundle]:
        cur_step = int(sim_state.step)

        # --- A. Check Triggers ---
        periodic = (cur_step % self.replan_every == 0)

        # Check completed tasks
        completed_since = 0
        if hasattr(sim_state, "completed_tasks_since_last_plan"):
            completed_since = int(getattr(sim_state, "completed_tasks_since_last_plan"))

        # Check major deviation (set by agent controllers)
        deviation = bool(getattr(sim_state, "major_deviation", False))

        # Emergency: too many agents have exhausted / lost their global paths,
        # or too many agents are stuck in consecutive SAFETY-WAITs.
        # Guard: only fire if the previous global replan was useful (produced
        # non-trivial paths). A consistently failing solver (e.g. binary not
        # found) produces all-WAIT paths that immediately exhaust, which would
        # cause the emergency trigger to fire every min_gap steps and multiply
        # the overhead without any benefit.
        emergency_gap_ok = (cur_step - self._last_emergency_step) >= self._min_emergency_gap
        emergency_allowed = emergency_gap_ok and self._last_replan_useful
        exhaustion = emergency_allowed and self._exhaustion_trigger(sim_state)
        safety_blocked = emergency_allowed and (not exhaustion) and self._safety_wait_trigger(sim_state)
        if exhaustion or safety_blocked:
            self._last_emergency_step = cur_step

        # Paper Section 4.4 eta_w trigger.  Reads the previous tick's
        # ``last_action_was_safe_wait`` flag from each AgentState and fires
        # an off-period replan when the fraction exceeds ``eta_w``.  The
        # ``replan_min_gap`` guard prevents thrash.
        eta_w_trigger = self._eta_w_trigger(sim_state, cur_step)

        if not (periodic or deviation or exhaustion or safety_blocked or eta_w_trigger):
            return None

        # --- B. Global Planning ---

        # Build planning kwargs - always pass is_lifelong=True for rolling horizon
        # (PIBT2 uses this to select MAPD binary instead of MAPF)
        plan_kwargs = {
            "env": sim_state.env,
            "agents": sim_state.agents,
            "assignments": assignments,
            "step": cur_step,
            "horizon": self.horizon,
            "rng": None,
        }

        # Pass is_lifelong=True if the solver supports it (e.g., PIBT2)
        # This ensures PIBT2 uses the MAPD binary for lifelong experiments.
        # Probe the solver's plan_with_metadata signature, since that is
        # the canonical entry point post-Prompt-16.
        import inspect
        plan_signature_source = (
            self.solver.plan_with_metadata
            if hasattr(self.solver, "plan_with_metadata")
            else self.solver.plan
        )
        if "is_lifelong" in inspect.signature(plan_signature_source).parameters:
            plan_kwargs["is_lifelong"] = True

        # SolverResult-aware path.  All shipped wrappers now expose
        # ``plan_with_metadata`` (Prompt 16); the legacy ``plan()`` shim
        # is still available for any third-party planner that hasn't
        # migrated.  We adapt the legacy return on the fly.
        if hasattr(self.solver, "plan_with_metadata"):
            result = self.solver.plan_with_metadata(**plan_kwargs)
            plan = result.plan
            status = result.status
        else:
            from ha_lmapf.core.types import SolverResult  # local import to avoid cycle
            legacy_plan = self.solver.plan(**plan_kwargs)
            plan = legacy_plan
            # Conservative classification of the legacy bundle.
            if legacy_plan is None or not legacy_plan.paths:
                status = "error"
            else:
                has_movement = any(
                    len(set(tp.cells)) > 1
                    for tp in legacy_plan.paths.values() if tp is not None
                )
                status = "complete" if has_movement else "timeout_no_result"
            result = SolverResult(
                plan=plan if plan is not None else PlanBundle(
                    paths={}, created_step=cur_step, horizon=self.horizon),
                status=status,
                solver_wall_ms=float("nan"),
                end_to_end_wall_ms=0.0,
            )

        metrics = getattr(sim_state, "metrics", None)

        # Status-driven dispatch.  This replaces the legacy
        # _last_replan_useful heuristic with an explicit five-way
        # SolverStatus check — see core/types.py::SolverStatus and
        # the decision tree in solvers/_base.py::_wrap_subprocess.
        import logging
        log = logging.getLogger(__name__)
        solver_class = getattr(self.solver, "__class__",
                               type(self.solver)).__name__

        if status in ("complete", "partial_anytime"):
            self._last_replan_useful = True
            # Stash the good plan and a goal snapshot so a subsequent
            # failed solve can re-anchor it.  Defensive copy so that
            # downstream mutation of the path objects can't corrupt
            # what we hand back later.
            self._last_good_bundle = PlanBundle(
                paths={
                    aid: (TimedPath(cells=list(tp.cells),
                                    start_step=tp.start_step)
                          if tp is not None else None)
                    for aid, tp in plan.paths.items()
                },
                created_step=plan.created_step,
                horizon=plan.horizon,
            )
            self._last_good_goals = {
                aid: a.goal for aid, a in sim_state.agents.items()
            }
            if status == "partial_anytime" and metrics is not None and \
                    hasattr(metrics, "add_solver_partial_return"):
                metrics.add_solver_partial_return(1)
        else:
            # ``timeout_no_result`` / ``error`` / ``binary_not_found``.
            # Count the failure first — a reused plan is still a
            # solver failure and the counter must NOT be downgraded.
            self._last_replan_useful = False
            if status == "timeout_no_result":
                if metrics is not None and hasattr(metrics, "add_solver_timeout"):
                    metrics.add_solver_timeout(1)
            else:  # "error" or "binary_not_found"
                if metrics is not None and hasattr(metrics, "add_solver_error"):
                    metrics.add_solver_error(1)

            if self._last_good_bundle is not None:
                reused = self._reanchor_last_good(
                    sim_state.agents, cur_step, self.horizon,
                )
                self._fallback_reuse_count += 1
                if metrics is not None and \
                        hasattr(metrics, "add_solver_fallback_reuse"):
                    metrics.add_solver_fallback_reuse(1)
                log.warning(
                    "[rolling-horizon] solver %r returned status=%s at step %d "
                    "(error_msg=%r); reused last good PlanBundle from step %d.",
                    solver_class, status, cur_step, result.error_msg,
                    self._last_good_bundle.created_step,
                )
                plan = reused
            else:
                # First-replan failure: no prior bundle to re-anchor.
                # Keep the all-WAIT plan SolverResult already built
                # but surface the degenerate-start condition loudly.
                log.warning(
                    "[rolling-horizon] solver %r returned status=%s at step %d "
                    "(error_msg=%r); no prior bundle; emitting all-WAIT. "
                    "This run started with a failed global solver — every "
                    "agent will be stationary until the next successful solve.",
                    solver_class, status, cur_step, result.error_msg,
                )

        self.last_planned_step = cur_step
        self.last_replan_step = cur_step
        # Track eta_w-triggered off-period fires for tests / instrumentation.
        # We count it as eta_w only when no other trigger fired and the
        # eta_w predicate was the reason we replanned.
        if eta_w_trigger and not (periodic or deviation or exhaustion or safety_blocked):
            self.emergency_replans_eta_w += 1
        self.completed_tasks_seen += completed_since

        return plan
