"""
Simulation Metrics Tracking.

This module provides the logic for gathering, aggregating, and exporting
performance statistics for Lifelong MAPF experiments. It focuses on:
  - Service Quality: Throughput (tasks/step), Flowtime, Service Time.
  - Safety: Collision types (Agent-Agent vs Agent-Human), near-misses,
    safety buffer violations, and violation rates.
  - Efficiency: Wait times, re-planning frequency, intervention rate.
  - HRI Metrics: Human passive waiting time.
  - Timing: Per-step wall-clock planning and decision latency.
  - Cost: Makespan, sum-of-costs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np

from ha_lmapf.core.types import Metrics


@dataclass
class _TaskRecord:
    """
    Internal bookkeeping structure for a single task's lifecycle.

    Attributes:
        release_step: The simulation step when the task first appeared.
        assigned_step: The step when an agent was first assigned to this task.
        completed_step: The step when the agent arrived at the goal.
        agent_id: The ID of the agent assigned to this task.
    """
    release_step: int
    assigned_step: Optional[int] = None
    completed_step: Optional[int] = None
    agent_id: Optional[int] = None


class MetricsTracker:
    """
    Deterministic metrics tracker for lifelong MAPF experiments.

    Tracks system efficiency, safety, timing, and cost metrics.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, _TaskRecord] = {}
        self._completed_tasks: int = 0
        self.total_tasks: int = 0

        self._coll_rr: int = 0
        self._coll_rh: int = 0
        self._near_misses: int = 0
        self._replans: int = 0
        self._total_wait_steps: int = 0
        # Wait-kind decomposition.  Invariant:
        #   total_wait_steps == safe_wait_steps + yield_wait_steps
        #                       + physics_revert_wait_steps
        #                       + delay_wait_steps   (P11 extension).
        self._safe_wait_steps: int = 0
        self._yield_wait_steps: int = 0
        # P11 wait-kind extension.  Counts ticks where the
        # simulator's step 6 / step 7a forced WAIT after the
        # controller had already decided to move.  Disjoint from
        # safe / yield by construction (the override branches only
        # rewrite non-WAIT actions); see
        # ``simulator.py::step_once`` for the two callsites.
        self._physics_revert_wait_steps: int = 0
        self._delay_wait_steps: int = 0
        # Solver returned None (timeout / crash) — RollingHorizon reused
        # the previous plan bundle.
        self._solver_timeouts: int = 0
        self._solver_partial_returns: int = 0
        self._solver_errors: int = 0
        # Count of replan failures where the rolling-horizon planner
        # re-anchored its last good PlanBundle instead of falling back
        # to all-WAIT.  Independent of (and does NOT decrement) the
        # underlying solver_{timeouts,errors} counts.
        self._solver_fallback_reuses: int = 0

        # Enhanced metrics — agent-tick view (legacy).
        # A "violation pair" (a_i, h) is counted every tick it holds:
        # a human loitering inside the buffer for N consecutive ticks
        # contributes N here.  The P6 audit flagged this as a misleading
        # summary stat; the debounced ``*_events`` counters below count
        # the same hover as a single event (leading-edge only).
        self._safety_violations: int = 0
        # Attribution split (paper Section 3.4): both counters increment per
        # (agent, human) violation pair; their sum equals _safety_violations.
        self._violations_agent_attributable: int = 0
        self._violations_exogenous_attributable: int = 0
        # Definition-1 (paper §3) attribution counters.  Computed by
        # the FOV-gated, pre-move, two-clause classifier in
        # ``simulator.py::_detect_collisions_and_near_misses`` block
        # (A).  These ARE the Theorem 1 invariant; see
        # ``docs/proposed_approach.md`` §F for the construction-level
        # proof.  Independent of the WAIT-counterfactual diagnostic
        # counters above -- the two answer different questions and
        # neither is the other's alias.
        self._violations_def1_agent_attributable: int = 0
        self._violations_def1_exogenous_attributable: int = 0
        # Event-debounced counters (P6 fix).  A "violation event" is a
        # maximal contiguous run of ticks where a specific (agent_id,
        # human_id) pair is inside r_safe; the counter ticks on the
        # transition from not-in-violation to in-violation only.
        # Updated by ``record_violation_pair`` + ``close_violation_tick``;
        # the simulator's per-tick classifier calls those in lockstep
        # with ``add_safety_violation`` / ``add_*_attributable_violation``
        # so the agent-tick and event invariants hold by construction.
        self._safety_violation_events: int = 0
        self._violations_agent_attributable_events: int = 0
        self._violations_exogenous_attributable_events: int = 0
        # Per-tick scratch + carry-over state for the event debounce.
        # ``_active_violation_pairs`` is the set of pairs that were in
        # violation in the PREVIOUS tick, keyed by (aid, hid); value
        # is the bucket ("agent" / "exo") that pair was in last.
        # ``_pending_violation_pairs_this_tick`` accumulates the
        # CURRENT tick's pairs between the per-pair record calls and
        # the closing call.
        self._active_violation_pairs: Dict[Tuple[int, int], Literal["agent", "exo"]] = {}
        self._pending_violation_pairs_this_tick: Dict[Tuple[int, int], Literal["agent", "exo"]] = {}
        self._global_replans: int = 0
        self._local_replans: int = 0
        self._human_passive_wait_steps: int = 0

        # Timing (wall-clock ms)
        self._planning_times_ms: List[float] = []  # per global-replan call
        self._decision_times_ms: List[float] = []  # per step (all agents)
        # Paper §5.8 — per-tick violation timelines.  Populated only when
        # ``Simulator._log_violations_timeline`` is True (knob in SimConfig).
        # The simulator calls ``append_violations_timeline`` once per tick.
        self._violations_agent_timeline: List[int] = []
        self._violations_exogenous_timeline: List[int] = []

        # Tier-1 → Tier-2 guidance handoff instrumentation.  Counted only
        # when ``SimConfig.debug_guidance_trace`` is True; the simulator
        # calls :meth:`add_guidance_observation` once per (agent, tick)
        # for every agent that had an active task on that tick.
        # ``guidance_coverage = covered / eligible`` is the fraction of
        # agent-ticks where the rolling-horizon planner had a non-empty
        # path for the agent at decision time.
        # ``guidance_follow_rate = followed / covered`` is the fraction
        # of those covered agent-ticks where the agent's post-physics
        # position equals the cell the bundle prescribed.  See
        # ``docs/tier_handoff_diagnosis.md``.
        self._guidance_eligible_ticks: int = 0
        self._guidance_covered_ticks: int = 0
        self._guidance_followed_ticks: int = 0

        # Paper §5.6 — global no-progress streak tracking.  The simulator
        # calls ``record_global_no_progress_tick(stalled)`` once per tick
        # AFTER the per-agent deadlock loop with stalled=True iff every
        # agent that has a same-task-as-previous-tick active assignment
        # failed to advance.  ``stalled=None`` (no active agents this
        # tick) breaks any in-flight streak without counting.
        self._global_no_progress_streak_current: int = 0
        self._global_no_progress_streak_max: int = 0
        self._global_no_progress_steps: int = 0

        # Paper §5.5 — realized assignment path-overlap accumulators.
        # Updated once per allocator.assign(...) call by the simulator
        # via record_assignment_overlap_round; finalized into
        # Metrics.sum_assignment_path_overlap and
        # Metrics.mean_assignment_path_overlap.
        self._sum_assignment_path_overlap: float = 0.0
        self._assignment_overlap_rounds: int = 0
        # Paper §5.5 — count of multi-agent (>= 2 agents) allocation
        # rounds, to enable a clean per-round overlap denominator
        # that excludes single-agent unlock-path calls.  Bumped by
        # the simulator via record_multiagent_allocation_round only
        # when the assignment contains >= 2 agents.
        self._n_multiagent_allocation_rounds: int = 0

        # Cost-based
        self._makespan: int = 0  # max steps any agent took to reach goal
        self._sum_of_costs: int = 0  # sum of path lengths for all completed tasks

        # Delay events
        self._delay_events: int = 0

        # Immediate task assignments (assigned on agent completion)
        self._immediate_assignments: int = 0

        # Assignment stability (commitment persistence metrics)
        self._assignments_kept: int = 0
        self._assignments_broken: int = 0

    # Task Lifecycle -------------------------------------

    def on_task_released(self, task_id: str, release_step: int) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].release_step = min(self._tasks[task_id].release_step, release_step)
            return
        self._tasks[task_id] = _TaskRecord(release_step=release_step)

    def on_task_assigned(self, task_id: str, agent_id: int, step: int) -> None:
        record = self._tasks.get(task_id)
        if record is None:
            record = _TaskRecord(release_step=step)
            self._tasks[task_id] = record
        record.assigned_step = step
        # P6 fix: the previous implementation wrote
        # ``record.assigned_agent = agent_id`` to a non-existent field
        # (Python allowed it as an instance attribute, but ``record.
        # agent_id`` -- the only documented field -- stayed ``None``
        # between assignment and completion).  Callers reading
        # ``record.agent_id`` mid-task saw ``None`` and concluded the
        # task was unassigned.  Set the documented field.
        record.agent_id = agent_id

        self.total_tasks = max(self.total_tasks, len(self._tasks))

    def on_task_completed(self, task_id: str, agent_id: int, step: int) -> None:
        record = self._tasks.get(task_id)
        if record is None:
            record = _TaskRecord(release_step=step, assigned_step=step, agent_id=agent_id)
            self._tasks[task_id] = record
        if record.completed_step is None:
            record.completed_step = step
            record.agent_id = agent_id
            self._completed_tasks += 1

        self.total_tasks = max(self.total_tasks, len(self._tasks))

    # Event Counters -------------------------------------

    def add_agent_agent_collision(self, count: int = 1) -> None:
        self._coll_rr += int(count)

    def add_agent_human_collision(self, count: int = 1) -> None:
        self._coll_rh += int(count)

    def add_near_miss(self, count: int = 1) -> None:
        self._near_misses += int(count)

    def add_replan(self, count: int = 1) -> None:
        self._replans += int(count)

    def add_global_replan(self, count: int = 1) -> None:
        self._global_replans += int(count)

    def add_local_replan(self, count: int = 1) -> None:
        self._local_replans += int(count)

    def add_wait_steps(self, count: int = 1) -> None:
        self._total_wait_steps += int(count)

    def add_safe_wait_step(self, count: int = 1) -> None:
        """Record a safety-induced WAIT (no F-respecting action available).
        Caller must also call ``add_wait_steps`` to keep the invariant
        ``total_wait_steps == safe_wait_steps + yield_wait_steps``.
        """
        self._safe_wait_steps += int(count)

    def add_yield_wait_step(self, count: int = 1) -> None:
        """Record a conflict-induced WAIT (resolver yielded after losing).
        Caller must also call ``add_wait_steps``; see invariant on
        :meth:`add_safe_wait_step`.
        """
        self._yield_wait_steps += int(count)

    def add_physics_revert_wait_step(self, count: int = 1) -> None:
        """Record a WAIT forced by the simulator's physics-revert
        step (step 7a in ``step_once``): the controller had decided
        to move but the resolver re-checked for vertex / edge
        conflicts and reverted the move to WAIT.  Caller must also
        call ``add_wait_steps`` to keep the extended invariant
        ``total_wait_steps == safe_wait_steps + yield_wait_steps
        + physics_revert_wait_steps + delay_wait_steps``."""
        self._physics_revert_wait_steps += int(count)

    def add_delay_wait_step(self, count: int = 1) -> None:
        """Record a WAIT forced by execution-delay injection
        (step 6 in ``step_once``, robust-MAPF feature).  Distinct
        from ``delay_events`` -- that counts when delays are
        INJECTED, this counts ticks the agent SPENT under a
        delay-induced WAIT.  See contract on
        :meth:`add_physics_revert_wait_step`."""
        self._delay_wait_steps += int(count)

    def add_solver_timeout(self, count: int = 1) -> None:
        """Count a ``timeout_no_result`` SolverResult — solver hit its
        budget without returning any plan.  Maps to
        ``Metrics.solver_timeouts``.
        """
        self._solver_timeouts += int(count)

    def add_solver_partial_return(self, count: int = 1) -> None:
        """Count a ``partial_anytime`` SolverResult — solver hit budget
        but returned its best-so-far plan.  This is **not** a failure;
        the controller uses the partial plan downstream.  Maps to
        ``Metrics.solver_partial_returns``.
        """
        self._solver_partial_returns += int(count)

    def add_solver_error(self, count: int = 1) -> None:
        """Count an ``error`` or ``binary_not_found`` SolverResult —
        crash, parse failure, segfault, or missing executable.  Maps
        to ``Metrics.solver_errors``.
        """
        self._solver_errors += int(count)

    def add_guidance_observation(
            self, *, eligible: bool, covered: bool, followed: bool,
    ) -> None:
        """Record one (agent, tick) guidance observation.

        ``eligible`` is True iff the agent had an active task this tick
        (i.e. ``agent.goal is not None`` and ``agent.pos != agent.goal``)
        -- the only ticks where the rolling-horizon planner is expected
        to provide guidance.  ``covered`` is True iff the current
        PlanBundle held a non-empty path for that agent at decision
        time.  ``followed`` is True iff the agent's post-physics
        position equals the cell the bundle prescribed for ``step+1``.

        Counters are 0/0 (i.e. NaN ratios) for runs where
        ``SimConfig.debug_guidance_trace`` is False -- the simulator
        is the only caller and gates on the flag.
        """
        if eligible:
            self._guidance_eligible_ticks += 1
        if covered:
            self._guidance_covered_ticks += 1
        if followed:
            self._guidance_followed_ticks += 1

    def add_solver_fallback_reuse(self, count: int = 1) -> None:
        """Count a failed-solve replan that recovered by re-anchoring
        the rolling-horizon planner's last good PlanBundle.  Maps to
        ``Metrics.solver_fallback_reuses``.  Independent of (and does
        not decrement) ``solver_timeouts`` / ``solver_errors``."""
        self._solver_fallback_reuses += int(count)

    def add_safety_violation(self, count: int = 1) -> None:
        self._safety_violations += int(count)

    def add_agent_attributable_violation(self, count: int = 1) -> None:
        """Count (agent, human) safety-buffer violation pairs attributable
        to the agent: an observed h' in X_t^{Phi_i} sits within r_safe of
        the agent's chosen s_i(t+1)."""
        self._violations_agent_attributable += int(count)

    def add_exogenous_attributable_violation(self, count: int = 1) -> None:
        """Count (agent, human) safety-buffer violation pairs attributable
        to the exogenous agent: no h' in X_t^{Phi_i} sits within r_safe of
        s_i(t+1)."""
        self._violations_exogenous_attributable += int(count)

    # ------------------------------------------------------------------
    # Definition-1 attribution (paper §3 / Theorem 1)
    # ------------------------------------------------------------------

    def add_def1_agent_attributable_violation(self, count: int = 1) -> None:
        """Count post-move violation pairs that the FOV-gated, pre-move,
        two-clause Definition-1 classifier in ``simulator.py``
        block (A) labels agent-attributable.  This is the canonical
        Theorem 1 quantity (paper §3); the WAIT-counterfactual
        ``add_agent_attributable_violation`` answers a different
        question.  Theorem 1 (paper §F) is the claim that the count
        this method receives stays zero on every Algorithm-2
        trajectory -- enforced by the forbidden-set construction,
        not by the metric."""
        self._violations_def1_agent_attributable += int(count)

    def add_def1_exogenous_attributable_violation(self, count: int = 1) -> None:
        """Count post-move violation pairs that the Definition-1
        classifier labels exogenous-attributable (the violation
        exists at t+1 but no observed pre-move witness satisfied
        both clauses of Definition 1).  Sum of this and
        ``add_def1_agent_attributable_violation`` equals
        ``violations_def1_safety_violations`` at finalize."""
        self._violations_def1_exogenous_attributable += int(count)

    # ------------------------------------------------------------------
    # Event-debounced violation accounting (P6 fix)
    # ------------------------------------------------------------------

    def record_violation_pair(
            self,
            agent_id: int,
            human_id: int,
            bucket: Literal["agent", "exo"],
    ) -> None:
        """Record one (agent, human) violation pair detected this tick.

        Caller must also bump the per-tick counters via
        ``add_safety_violation`` and ``add_{agent,exogenous}_attributable_violation``
        for the agent-tick view to stay consistent; this method only
        feeds the event-debounce state machine.

        The bucket argument carries the WAIT-counterfactual
        classification (see ``docs/REVISION_AUDIT.md`` §13) so that
        events can be split across the attribution buckets too.
        """
        self._pending_violation_pairs_this_tick[(int(agent_id), int(human_id))] = bucket

    def close_violation_tick(self) -> None:
        """Close out one tick of violation detection.

        Computes the leading-edge diff between the pending tick's
        violation pairs and the previously-active set, bumping the
        event counters for pairs that JUST entered violation this
        tick.  Then rotates the pending set into the active set so
        the next tick can compute its own diff.

        Must be called once per simulator tick after the per-pair
        ``record_violation_pair`` calls -- even on ticks where the
        classifier found no violations, so that dropped-out pairs
        stop being tracked.  The simulator's
        ``_detect_collisions_and_near_misses`` is the only caller.
        """
        prev = self._active_violation_pairs
        curr = self._pending_violation_pairs_this_tick
        for pair, bucket in curr.items():
            if pair not in prev:
                self._safety_violation_events += 1
                if bucket == "agent":
                    self._violations_agent_attributable_events += 1
                else:
                    self._violations_exogenous_attributable_events += 1
        self._active_violation_pairs = curr
        self._pending_violation_pairs_this_tick = {}

    def append_violations_timeline(self, agent_attr: int,
                                   exo_attr: int) -> None:
        """Paper §5.8 — append this tick's violation counts to the
        per-tick timelines.  Called once per tick by the simulator iff
        ``SimConfig.log_violations_timeline`` is True.  Both lists are
        appended in lockstep so they stay index-aligned (length == T)."""
        self._violations_agent_timeline.append(int(agent_attr))
        self._violations_exogenous_timeline.append(int(exo_attr))

    def record_multiagent_allocation_round(self) -> None:
        """Paper §5.5 — bump the multi-agent allocation-round counter.

        The simulator calls this immediately after
        ``record_assignment_overlap_round`` whenever the allocation
        chose 2+ agents simultaneously.  Single-agent unlock-path
        calls do NOT bump this counter, even though they do bump
        the overlap-round counter (with overlap=0).

        Provides a clean denominator for the per-round overlap
        metric at analysis time::

            mean_multiagent_overlap = (
                sum_assignment_path_overlap / n_multiagent_allocation_rounds
            )
        """
        self._n_multiagent_allocation_rounds += 1

    def record_assignment_overlap_round(self, overlap_sum: float) -> None:
        """Paper §5.5 — record one allocation round's total pairwise
        path overlap.  Called by the simulator after each
        ``task_allocator.assign(...)`` invocation with the sum of
        |path_i ∩ path_j| over all assigned-agent pairs (or 0.0 when
        the round assigned 0 or 1 agents — no pairs possible).

        Each call increments the round counter, so a sweep with N
        allocation rounds and zero overlap is distinguishable from
        a sweep with no allocation rounds at all (the latter yields
        mean=0.0 by the divide-by-zero guard in finalize)."""
        self._sum_assignment_path_overlap += float(overlap_sum)
        self._assignment_overlap_rounds += 1

    def record_global_no_progress_tick(self, stalled: Optional[bool]) -> None:
        """Paper §5.6 — record one tick's global no-progress state.

        Called once per simulator tick AFTER the per-agent deadlock loop.

        ``stalled``:
          * ``True``  — at least one agent had an active same-task
                        assignment this tick AND none of them advanced.
                        Counts toward both ``global_no_progress_steps``
                        and the in-flight streak.
          * ``False`` — at least one active agent advanced.  Resets the
                        in-flight streak.
          * ``None``  — no active agents this tick (every agent idle or
                        on a fresh task).  Resets the streak without
                        counting (mirrors per-agent idle handling).

        Maintains ``_global_no_progress_streak_max`` as a running maximum.
        """
        if stalled is True:
            self._global_no_progress_steps += 1
            self._global_no_progress_streak_current += 1
            if self._global_no_progress_streak_current > self._global_no_progress_streak_max:
                self._global_no_progress_streak_max = self._global_no_progress_streak_current
        else:
            # False (someone moved) or None (no active agents) — reset.
            self._global_no_progress_streak_current = 0

    def add_human_passive_wait(self, count: int = 1) -> None:
        self._human_passive_wait_steps += int(count)

    # Timing -------------------------------------------

    def record_planning_time_ms(self, ms: float) -> None:
        """Record wall-clock time for a single global planning call."""
        self._planning_times_ms.append(float(ms))

    def record_decision_time_ms(self, ms: float) -> None:
        """Record wall-clock time for one simulation step (all agents)."""
        self._decision_times_ms.append(float(ms))

    # Cost-based ----------------------------------------

    def add_path_cost(self, cost: int) -> None:
        """Add the path cost (length) for one completed task to sum-of-costs."""
        self._sum_of_costs += int(cost)

    def update_makespan(self, step: int) -> None:
        """Update makespan to be the maximum step at which any task completes."""
        if step > self._makespan:
            self._makespan = step

    # Delay events
    def add_delay_event(self, count: int = 1) -> None:
        self._delay_events += int(count)

    # Immediate assignments
    def add_immediate_assignment(self, count: int = 1) -> None:
        self._immediate_assignments += int(count)

    # Assignment stability (commitment persistence)
    def add_assignment_kept(self, count: int = 1) -> None:
        """Record assignments kept due to commitment persistence."""
        self._assignments_kept += int(count)

    def add_assignment_broken(self, count: int = 1) -> None:
        """Record assignments broken (commitment expired or break condition)."""
        self._assignments_broken += int(count)

    def set_assignment_stability_stats(self, kept: int, broken: int) -> None:
        """Set assignment stability stats from allocator (called once at end)."""
        self._assignments_kept = int(kept)
        self._assignments_broken = int(broken)

    # Outputs --------------------------------------------

    @staticmethod
    def csv_header() -> List[str]:
        # The trailing block ``safety_violation_agent_ticks`` ..
        # ``mean_task_completion_span`` was added in the P6 metric-
        # definitions audit.  Existing legacy columns are preserved
        # (downstream plot scripts read by name).  See
        # ``docs/REVISION_AUDIT.md`` §14 for the new vs deprecated
        # mapping.
        return [
            "throughput",
            "arrival_rate_per_step",       # P10 load-regime
            "throughput_utilization",      # P10 load-regime
            "completed_tasks",
            "total_released_tasks",
            "task_completion",
            "mean_flowtime",
            "median_flowtime",
            "max_flowtime",
            "mean_service_time",
            "collisions_agent_agent",
            "collisions_agent_human",
            "near_misses",
            "safety_violations",                 # deprecated alias of *_agent_ticks
            "safety_violation_rate",             # deprecated: divides by steps only
            "violations_agent_attributable",     # deprecated alias of *_agent_ticks
            "violations_exogenous_attributable", # deprecated alias of *_agent_ticks
            "replans",
            "global_replans",
            "local_replans",
            "intervention_rate",
            "total_wait_steps",
            "human_passive_wait_steps",
            "mean_planning_time_ms",
            "p95_planning_time_ms",
            "max_planning_time_ms",
            "mean_decision_time_ms",
            "p95_decision_time_ms",
            "makespan",                          # deprecated in lifelong mode
            "sum_of_costs",
            "delay_events",
            "immediate_assignments",
            "assignments_kept",
            "assignments_broken",
            "steps",
            # P6 additions ---------------------------------------------
            "safety_violation_agent_ticks",
            "safety_violation_events",
            "safety_violation_rate_per_agent_step",
            "violations_agent_attributable_agent_ticks",
            "violations_agent_attributable_events",
            "violations_exogenous_attributable_agent_ticks",
            "violations_exogenous_attributable_events",
            "mean_task_completion_span",
            # Definition-1 attribution (paper §3 / Theorem 1).  See
            # ``simulator.py::_detect_collisions_and_near_misses``
            # block (A).  Names are alphabetical within this block.
            "violations_def1_agent_attributable",
            "violations_def1_exogenous_attributable",
            "violations_def1_safety_violations",
        ]

    def to_csv_row(self, metrics: Metrics) -> List[str]:
        return [
            f"{metrics.throughput:.6f}",
            f"{metrics.arrival_rate_per_step:.6f}",    # P10
            f"{metrics.throughput_utilization:.6f}",   # P10
            str(metrics.completed_tasks),
            str(metrics.total_released_tasks),
            f"{metrics.task_completion:.4f}",
            f"{metrics.mean_flowtime:.2f}",
            f"{metrics.median_flowtime:.2f}",
            f"{metrics.max_flowtime:.2f}",
            f"{metrics.mean_service_time:.2f}",
            str(metrics.collisions_agent_agent),
            str(metrics.collisions_agent_human),
            str(metrics.near_misses),
            str(metrics.safety_violations),
            f"{metrics.safety_violation_rate:.4f}",
            str(metrics.violations_agent_attributable),
            str(metrics.violations_exogenous_attributable),
            str(metrics.replans),
            str(metrics.global_replans),
            str(metrics.local_replans),
            f"{metrics.intervention_rate:.4f}",
            str(metrics.total_wait_steps),
            str(metrics.human_passive_wait_steps),
            f"{metrics.mean_planning_time_ms:.3f}",
            f"{metrics.p95_planning_time_ms:.3f}",
            f"{metrics.max_planning_time_ms:.3f}",
            f"{metrics.mean_decision_time_ms:.3f}",
            f"{metrics.p95_decision_time_ms:.3f}",
            str(metrics.makespan),
            str(metrics.sum_of_costs),
            str(metrics.delay_events),
            str(metrics.immediate_assignments),
            str(metrics.assignments_kept),
            str(metrics.assignments_broken),
            str(metrics.steps),
            # P6 additions ---------------------------------------------
            str(metrics.safety_violation_agent_ticks),
            str(metrics.safety_violation_events),
            f"{metrics.safety_violation_rate_per_agent_step:.6f}",
            str(metrics.violations_agent_attributable_agent_ticks),
            str(metrics.violations_agent_attributable_events),
            str(metrics.violations_exogenous_attributable_agent_ticks),
            str(metrics.violations_exogenous_attributable_events),
            f"{metrics.mean_task_completion_span:.2f}",
            str(metrics.violations_def1_agent_attributable),
            str(metrics.violations_def1_exogenous_attributable),
            str(metrics.violations_def1_safety_violations),
        ]

    def finalize(
            self,
            total_steps: int,
            num_agents: Optional[int] = None,
            deadlock_count: int = 0,
    ) -> Metrics:
        # Attribution invariant: every safety_violation must land in
        # exactly one of the two attribution buckets.  Asserted here so
        # a future classifier edit that breaks the bookkeeping is
        # caught at run-end rather than silently in downstream
        # aggregation.  See ``docs/REVISION_AUDIT.md`` for the
        # WAIT-counterfactual rule and ``simulator.py::
        # _detect_collisions_and_near_misses`` for the per-pair
        # accounting.
        attr_sum = (
            int(self._violations_agent_attributable)
            + int(self._violations_exogenous_attributable)
        )
        if attr_sum != int(self._safety_violations):
            raise AssertionError(
                f"safety attribution invariant broken: "
                f"safety_violations={self._safety_violations} != "
                f"agent_attributable + exogenous_attributable = "
                f"{self._violations_agent_attributable} + "
                f"{self._violations_exogenous_attributable} = {attr_sum}"
            )

        # Definition-1 invariant: the def1 buckets are computed from
        # the same post-move violation-pair set as bucket (B), so
        # their sum must equal the (B) sum -- i.e. the legacy
        # ``safety_violations`` counter -- whenever Definition 1
        # actually ran.  We compute the def1 sum and expose it as
        # ``violations_def1_safety_violations``.  When the
        # simulator-internal classifier ran (humans_pre_move passed),
        # the two sums are equal by construction; when only legacy
        # paths populated the WAIT counters (unit tests that call
        # ``add_safety_violation`` directly without ``add_def1_*``),
        # the def1 sum stays 0 and the assertion below scopes itself
        # accordingly.
        def1_attr_sum = (
            int(self._violations_def1_agent_attributable)
            + int(self._violations_def1_exogenous_attributable)
        )
        if def1_attr_sum > 0 and def1_attr_sum != int(self._safety_violations):
            raise AssertionError(
                f"Definition-1 attribution invariant broken: "
                f"def1_safety_violations (= def1_agent + def1_exo = "
                f"{self._violations_def1_agent_attributable} + "
                f"{self._violations_def1_exogenous_attributable} = "
                f"{def1_attr_sum}) != safety_violations="
                f"{self._safety_violations}.  Both classifiers iterate "
                f"the same post-move violation-pair set; this drift "
                f"means one classifier saw fewer pairs than the other."
            )

        flowtimes: List[int] = []
        service_times: List[int] = []
        for rec in self._tasks.values():
            if rec.completed_step is not None:
                flowtimes.append(rec.completed_step - rec.release_step)
                if rec.assigned_step is not None:
                    service_times.append(rec.completed_step - rec.assigned_step)

        mean_flow = float(np.mean(flowtimes)) if flowtimes else 0.0
        median_flow = float(np.median(flowtimes)) if flowtimes else 0.0
        max_flow = float(max(flowtimes)) if flowtimes else 0.0
        mean_svc = float(np.mean(service_times)) if service_times else 0.0
        throughput = float(self._completed_tasks) / float(total_steps) if total_steps > 0 else 0.0

        task_completion = float(self._completed_tasks) / float(self.total_tasks) if self.total_tasks > 0 else 0.0

        # Load-regime diagnostics (P10).  The system-wide arrival
        # rate (released_tasks / steps) is what the throughput
        # column is implicitly compared against in a lifelong
        # stream.  ``throughput_utilization`` of 1.0 means the
        # cell is arrival-saturated: throughput equals the arrival
        # rate cap and is no longer measuring planner capacity.
        # Reported in the CSV so paper-table builders can flag
        # arrival-saturated cells visually (see
        # ``scripts/evaluation/build_summary_tables.py``).
        arrival_rate = (
            float(self.total_tasks) / float(total_steps)
            if total_steps > 0 else 0.0
        )
        throughput_util = (
            float(throughput) / arrival_rate
            if arrival_rate > 0.0 else 0.0
        )

        sv_rate = (self._safety_violations / total_steps * 1000.0) if total_steps > 0 else 0.0
        # Agent-normalized rate (P6 fix).  Matches the normalization of
        # ``wait_fraction`` so cross-fleet comparisons in the §5.4
        # scaling sweeps are like-for-like.  Falls back to 0.0 if
        # ``num_agents`` was not provided to finalize.
        denom = float(num_agents * total_steps) if (num_agents and total_steps > 0) else 0.0
        sv_rate_per_agent_step = (
            float(self._safety_violations) / denom if denom > 0.0 else 0.0
        )
        int_rate = (self._global_replans / total_steps * 1000.0) if total_steps > 0 else 0.0

        # Timing stats
        pt = self._planning_times_ms
        mean_pt = float(np.mean(pt)) if pt else 0.0
        p95_pt = float(np.percentile(pt, 95)) if pt else 0.0
        max_pt = float(max(pt)) if pt else 0.0

        dt = self._decision_times_ms
        mean_dt = float(np.mean(dt)) if dt else 0.0
        p95_dt = float(np.percentile(dt, 95)) if dt else 0.0

        # Compute per-step cumulative throughput timeline for
        # convergence analysis.  P6 fix: clamp ``completed_step`` to
        # the last bucket so a task completing exactly at
        # ``total_steps`` is not dropped from the timeline while
        # ``_completed_tasks`` still counts it (the scalar count and
        # the timeline must agree on the same set of tasks).
        completions_per_step = [0] * max(total_steps, 1)
        if total_steps > 0:
            last_idx = total_steps - 1
            for rec in self._tasks.values():
                if rec.completed_step is None or rec.completed_step < 0:
                    continue
                idx = min(int(rec.completed_step), last_idx)
                completions_per_step[idx] += 1
        cumulative = 0
        throughput_timeline: List[float] = []
        for s in range(total_steps):
            cumulative += completions_per_step[s]
            throughput_timeline.append(cumulative / (s + 1))

        m = Metrics(
            throughput=throughput,
            arrival_rate_per_step=arrival_rate,
            throughput_utilization=throughput_util,
            completed_tasks=self._completed_tasks,
            total_released_tasks=self.total_tasks,
            task_completion=task_completion,
            mean_flowtime=mean_flow,
            collisions_agent_agent=self._coll_rr,
            collisions_agent_human=self._coll_rh,
            near_misses=self._near_misses,
            replans=self._replans,
            total_wait_steps=self._total_wait_steps,
            steps=total_steps,
            safety_violations=self._safety_violations,
            safety_violation_agent_ticks=self._safety_violations,
            safety_violation_events=self._safety_violation_events,
            safety_violation_rate=sv_rate,
            safety_violation_rate_per_agent_step=sv_rate_per_agent_step,
            violations_agent_attributable=self._violations_agent_attributable,
            violations_agent_attributable_agent_ticks=self._violations_agent_attributable,
            violations_agent_attributable_events=self._violations_agent_attributable_events,
            violations_exogenous_attributable=self._violations_exogenous_attributable,
            violations_exogenous_attributable_agent_ticks=self._violations_exogenous_attributable,
            violations_exogenous_attributable_events=self._violations_exogenous_attributable_events,
            violations_def1_agent_attributable=self._violations_def1_agent_attributable,
            violations_def1_exogenous_attributable=self._violations_def1_exogenous_attributable,
            violations_def1_safety_violations=def1_attr_sum,
            global_replans=self._global_replans,
            local_replans=self._local_replans,
            intervention_rate=int_rate,
            mean_service_time=mean_svc,
            median_flowtime=median_flow,
            max_flowtime=max_flow,
            human_passive_wait_steps=self._human_passive_wait_steps,
            mean_planning_time_ms=mean_pt,
            p95_planning_time_ms=p95_pt,
            max_planning_time_ms=max_pt,
            mean_decision_time_ms=mean_dt,
            p95_decision_time_ms=p95_dt,
            makespan=self._makespan,
            # P6 fix: paper-aligned per-task completion span.  Numerically
            # identical to ``mean_flowtime`` (release -> completion mean
            # over completed tasks); exposed under the explicit name so
            # downstream plots can switch off the lifelong-meaningless
            # ``makespan`` without column renames.
            mean_task_completion_span=mean_flow,
            sum_of_costs=self._sum_of_costs,
            delay_events=self._delay_events,
            immediate_assignments=self._immediate_assignments,
            assignments_kept=self._assignments_kept,
            assignments_broken=self._assignments_broken,
            throughput_timeline=throughput_timeline,
            safe_wait_steps=self._safe_wait_steps,
            yield_wait_steps=self._yield_wait_steps,
            physics_revert_wait_steps=self._physics_revert_wait_steps,
            delay_wait_steps=self._delay_wait_steps,
            wait_fraction=(
                self._total_wait_steps / float(num_agents * total_steps)
                if (num_agents and total_steps > 0)
                else 0.0
            ),
            # Nomenclature alias — paper text uses "exogenous agents"
            # where the codebase uses "human".  Same value as
            # ``collisions_agent_human``.
            collisions_agent_exogenous=self._coll_rh,
            solver_timeouts=self._solver_timeouts,
            solver_partial_returns=self._solver_partial_returns,
            solver_errors=self._solver_errors,
            solver_fallback_reuses=self._solver_fallback_reuses,
            deadlock_count=deadlock_count,
            max_global_no_progress_streak=int(self._global_no_progress_streak_max),
            global_no_progress_steps=int(self._global_no_progress_steps),
            sum_assignment_path_overlap=float(self._sum_assignment_path_overlap),
            mean_assignment_path_overlap=(
                float(self._sum_assignment_path_overlap)
                / float(self._assignment_overlap_rounds)
                if self._assignment_overlap_rounds > 0 else 0.0
            ),
            n_multiagent_allocation_rounds=int(self._n_multiagent_allocation_rounds),
            # Defensive copies — the returned Metrics must not alias
            # the tracker's internal per-tick buffers.
            violations_agent_timeline=list(self._violations_agent_timeline),
            violations_exogenous_timeline=list(self._violations_exogenous_timeline),
            guidance_eligible_ticks=int(self._guidance_eligible_ticks),
            guidance_covered_ticks=int(self._guidance_covered_ticks),
            guidance_followed_ticks=int(self._guidance_followed_ticks),
            guidance_coverage=(
                float(self._guidance_covered_ticks) / float(self._guidance_eligible_ticks)
                if self._guidance_eligible_ticks > 0 else 0.0
            ),
            guidance_follow_rate=(
                float(self._guidance_followed_ticks) / float(self._guidance_covered_ticks)
                if self._guidance_covered_ticks > 0 else 0.0
            ),
        )

        # Event-vs-agent-ticks contract (P6 follow-up).  The
        # ``*_agent_ticks`` aliases must equal their legacy
        # counterparts because the CSV writer reads both columns
        # from this object; a drift here would surface as columns
        # silently disagreeing in downstream plots.  ``*_events``
        # is the leading-edge debounced count and is bounded above
        # by the per-tick count -- every event consumes at least
        # one tick, so events > agent_ticks would indicate the
        # ``MetricsTracker.close_violation_tick`` state machine
        # double-counted a leading edge.  Asserted here against
        # the MATERIALIZED Metrics fields (the values the CSV
        # writer will actually emit) so a future field rename
        # that decouples the alias from its source fires
        # immediately at run-end.
        assert m.safety_violations == m.safety_violation_agent_ticks, (
            f"safety_violation_agent_ticks alias drift: "
            f"safety_violations={m.safety_violations} != "
            f"safety_violation_agent_ticks={m.safety_violation_agent_ticks}"
        )
        assert m.violations_agent_attributable == m.violations_agent_attributable_agent_ticks, (
            f"violations_agent_attributable_agent_ticks alias drift: "
            f"violations_agent_attributable={m.violations_agent_attributable} != "
            f"violations_agent_attributable_agent_ticks={m.violations_agent_attributable_agent_ticks}"
        )
        assert m.violations_exogenous_attributable == m.violations_exogenous_attributable_agent_ticks, (
            f"violations_exogenous_attributable_agent_ticks alias drift: "
            f"violations_exogenous_attributable={m.violations_exogenous_attributable} != "
            f"violations_exogenous_attributable_agent_ticks={m.violations_exogenous_attributable_agent_ticks}"
        )
        assert m.safety_violations >= m.safety_violation_events, (
            f"events > agent_ticks: "
            f"safety_violation_events={m.safety_violation_events} > "
            f"safety_violations={m.safety_violations}; the debounce "
            f"state machine must have double-counted a leading edge."
        )

        # P11 wait-kind extended invariant.  Every counted wait
        # tick must land in exactly one of the four buckets; a
        # drift here means a new wait-kind callsite was added to
        # the simulator without bumping ``total_wait_steps`` in
        # lockstep, or one of the override branches (step 6 /
        # step 7a) ran on an action the controller had already
        # bucketed as safe / yield.
        wait_kind_sum = (
            int(m.safe_wait_steps)
            + int(m.yield_wait_steps)
            + int(m.physics_revert_wait_steps)
            + int(m.delay_wait_steps)
        )
        assert m.total_wait_steps == wait_kind_sum, (
            f"wait-kind invariant broken: "
            f"total_wait_steps={m.total_wait_steps} != "
            f"safe+yield+physics_revert+delay = "
            f"{m.safe_wait_steps}+{m.yield_wait_steps}+"
            f"{m.physics_revert_wait_steps}+{m.delay_wait_steps} "
            f"= {wait_kind_sum}.  See "
            f"simulator.py::step_once for the wait-bucketing blocks; "
            f"if a new override callsite was added, it must call "
            f"add_wait_steps in lockstep with the appropriate "
            f"add_*_wait_step method."
        )
        return m
