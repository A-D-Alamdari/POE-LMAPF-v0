from __future__ import annotations

from typing import Dict, Optional

from ha_lmapf.core.interfaces import SimStateView, GlobalPlanner
from ha_lmapf.core.types import PlanBundle, Task


# Allocator (Matches your task_allocator.py file name)


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
        if status in ("complete", "partial_anytime"):
            self._last_replan_useful = True
            if status == "partial_anytime" and metrics is not None and \
                    hasattr(metrics, "add_solver_partial_return"):
                metrics.add_solver_partial_return(1)
        elif status == "timeout_no_result":
            self._last_replan_useful = False
            if metrics is not None and hasattr(metrics, "add_solver_timeout"):
                metrics.add_solver_timeout(1)
        else:  # "error" or "binary_not_found"
            self._last_replan_useful = False
            if metrics is not None and hasattr(metrics, "add_solver_error"):
                metrics.add_solver_error(1)
            import logging
            logging.getLogger(__name__).warning(
                "[rolling-horizon] solver %r returned status=%s at step %d "
                "(error_msg=%r); reusing previous PlanBundle.",
                getattr(self.solver, "__class__", type(self.solver)).__name__,
                status, cur_step, result.error_msg,
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
