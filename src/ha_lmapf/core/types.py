"""
Core Type Definitions for Human-Aware Lifelong MAPF.

This module defines the fundamental data structures used throughout the
simulator and planning tiers. It includes:
  - Enums for agent actions.
  - Dataclasses for entity states (Agent, Human).
  - Structures for tasks, plans, and observations.
  - Metric containers for experiment logging.
  - Configuration schemas.

All types support serialization to dictionaries via `to_dict()` methods
to facilitate JSON logging and replay generation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any, Literal


# Actions --------------------------------------------
class StepAction(Enum):
    """
    Enumeration of valid discrete actions an agent can take in a single time step.

    The grid system assumes a 4-connected graph (Von Neumann neighborhood) plus a wait action.
    """
    UP = "UP"  # Move (row - 1, col)
    DOWN = "DOWN"  # Move (row + 1, col)
    LEFT = "LEFT"  # Move (row, col - 1)
    RIGHT = "RIGHT"  # Move (row, col + 1)
    WAIT = "WAIT"  # Stay at current position (row, col)


# Core State Types ------------------------------------

@dataclass
class AgentState:
    """
    Represents the snapshot of an agent's status at a specific simulation step.

    Attributes:
        agent_id: Unique identifier for the agent.
        pos: Current grid position (row, col).
        goal: Current target position the agent is moving towards, if any.
        carrying: Boolean flag indicating if the agent is currently transporting a load.
        task_id: The ID of the task currently assigned to this agent, if any.
        done_tasks: Cumulative count of tasks completed by this agent so far.
        wait_steps: Cumulative count of steps the agent spent waiting (metrics).
        last_action_was_safe_wait: Single-step boolean flag — True iff
            the controller committed a *safety-induced* WAIT this tick
            (no F-respecting move was available: ``desired_next ∈ F``,
            local A* failed, etc.).  Reset every tick by
            ``AgentController.decide_action``.  Read by
            ``RollingHorizonPlanner`` to compute the eta_w emergency
            replan trigger (paper Section 4.4).  Strictly disjoint from
            ``last_action_was_yield_wait``: the controller sets exactly
            one (or neither) per tick.
        last_action_was_yield_wait: Single-step boolean flag — True iff
            the controller committed a *conflict-induced* WAIT this tick
            (the resolver returned WAIT after losing a vertex/edge
            conflict, or ``disable_conflict_resolution`` forced a yield).
            Distinct bucket from ``last_action_was_safe_wait`` so that
            ``Metrics.safe_wait_steps`` and ``Metrics.yield_wait_steps``
            sum to ``Metrics.total_wait_steps`` exactly.
    """
    agent_id: int
    pos: Tuple[int, int]
    goal: Optional[Tuple[int, int]] = None
    carrying: bool = False
    task_id: Optional[str] = None
    done_tasks: int = 0
    wait_steps: int = 0
    last_action_was_safe_wait: bool = False
    last_action_was_yield_wait: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state to a dictionary for logging/JSON export."""
        return asdict(self)


@dataclass
class HumanState:
    """
    Represents the snapshot of a human's status at a specific simulation step.

    Attributes:
        human_id: Unique identifier for the human.
        pos: Current grid position (row, col).
        velocity: Approximate velocity vector (d_row, d_col) observed.
                  Default is (0,0) if stationary or unknown.
    """
    human_id: int
    pos: Tuple[int, int]
    velocity: Tuple[int, int] = (0, 0)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state to a dictionary for logging/JSON export."""
        return asdict(self)


@dataclass
class Task:
    """
    Represents a pickup-delivery task to be performed by an agent.

    A task involves two phases:
      1. Pickup: Move to the start (pickup) location
      2. Delivery: Move from start to goal (delivery) location

    The task allocator assigns tasks to agents based on their distance
    to the start (pickup) location, not the goal.

    Attributes:
        task_id: Unique string identifier for the task.
        start: The pickup location grid cell (row, col).
        goal: The delivery destination grid cell (row, col).
        release_step: The simulation step when this task became available.
    """
    task_id: str
    start: Tuple[int, int]
    goal: Tuple[int, int]
    release_step: int

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to a dictionary for logging/JSON export."""
        return asdict(self)

    def __hash__(self):
        return hash(self.task_id)


# Planning Structures ---------------------------------

@dataclass
class TimedPath:
    """
    A sequence of time-indexed positions representing an agent's planned route.

    The path is anchored to a specific `start_step`. This allows the path
    object to answer "Where should I be at step t?" correctly.

    Attributes:
        cells: List of (row, col) tuples. cells[0] is the position at start_step.
        start_step: The global simulation step corresponding to cells[0].
    """
    cells: List[Tuple[int, int]]
    start_step: int

    def __call__(self, step: int) -> Tuple[int, int]:
        """
        Get the planned position at a specific global simulation step.

        Robustness behavior:
          - If step < start_step: Returns the first position (Wait at start).
          - If step > start_step + len(cells): Returns the last position (Stay at goal).

        Args:
            step: The global simulation time step.

        Returns:
            The (row, col) tuple for that step.
        """
        idx = step - self.start_step

        if idx < 0:
            return self.cells[0]

        if idx >= len(self.cells):
            return self.cells[-1]

        return self.cells[idx]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize path to a dictionary."""
        return {
            "cells": list(self.cells),
            "start_step": self.start_step,
        }


@dataclass
class PlanBundle:
    """
    A collection of paths for multiple agents generated by the global planner.

    Attributes:
        paths: Mapping from agent_id to their TimedPath.
        created_step: The simulation step when this plan was generated.
        horizon: The planning horizon used (how far into the future these paths go).
    """
    paths: Dict[int, Optional[TimedPath]]
    created_step: int
    horizon: int

    def to_dict(self) -> Dict[str, Any]:
        """Serialize bundle to a dictionary for logging."""
        return {
            "paths": {aid: path.to_dict() for aid, path in self.paths.items()},
            "created_step": self.created_step,
            "horizon": self.horizon,
        }


# Solver Contract --------------------------------------

# Strict five-way classification of every solver-wrapper return.  The
# decision tree that maps subprocess outcomes to these statuses lives
# in :class:`ha_lmapf.global_tier.solvers._base.BaseSolverWrapper.
# _wrap_subprocess` and MUST be the only authority for setting
# ``SolverResult.status``.
SolverStatus = Literal[
    "complete",            # solver finished and returned a valid plan
    "partial_anytime",     # solver hit time budget; returned best-so-far
    "timeout_no_result",   # solver hit time budget without producing any plan
    "error",               # crash, parse failure, segfault, signal
    "binary_not_found",    # wrapper-level: executable absent or unrunnable
]


@dataclass(frozen=True)
class SolverResult:
    """
    Structured return value of every Tier-1 solver wrapper.

    Replaces the legacy ``PlanBundle``-only contract in which five
    distinct failure modes (binary missing, watchdog kill, anytime
    partial, segfault, parse failure) collapsed into the same
    all-WAIT bundle and the caller could not tell them apart.

    The ``plan`` attribute is **always** a valid ``PlanBundle``: a
    real one for ``complete`` / ``partial_anytime`` and an all-WAIT
    fallback for ``timeout_no_result`` / ``error`` / ``binary_not_found``.
    Callers can use the plan unconditionally; ``status`` tells them
    *why* the plan looks the way it does and whether to count this
    invocation as a success, a soft timeout, or a hard error in the
    metrics.

    Attributes:
        plan: A complete PlanBundle (real paths or all-WAIT fallback).
        status: One of the five SolverStatus values; set by the
            :class:`BaseSolverWrapper._wrap_subprocess` decision tree.
        solver_wall_ms: Solver's self-reported internal wall-clock,
            parsed from the binary's stdout / stderr / result file.
            ``math.nan`` when the format cannot be parsed reliably
            (do NOT silently fall back to ``end_to_end_wall_ms`` —
            they are different quantities).
        end_to_end_wall_ms: Wall-clock measured by the wrapper around
            the entire subprocess invocation, including spawn
            overhead, IO, and result-file parsing.
        error_msg: Diagnostic string; populated only for
            ``status in {"error", "binary_not_found"}``.
    """
    plan: PlanBundle
    status: SolverStatus
    solver_wall_ms: float
    end_to_end_wall_ms: float
    error_msg: str = ""


# Local Observation -----------------------------------

@dataclass
class Observation:
    """
    The sensory input available to a single agent during the execution phase.

    Reflects Partial Observability: only contains entities within the
    agent's Field of View (FOV).

    Attributes:
        visible_humans: Dict of {human_id: HumanState} currently inside FOV.
        visible_agents: Dict of {agent_id: AgentState} currently inside FOV.
        blocked: Set of coordinates considered 'unsafe' or 'occupied'
                 (e.g., inflated static obstacles or dynamic zones).
    """
    visible_humans: Dict[int, HumanState] = field(default_factory=dict)
    visible_agents: Dict[int, AgentState] = field(default_factory=dict)
    blocked: Set[Tuple[int, int]] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize observation to a dictionary."""
        return {
            "visible_humans": {hid: human.to_dict() for hid, human in self.visible_humans.items()},
            "visible_agents": {aid: agent.to_dict() for aid, agent in self.visible_agents.items()},
            "blocked": list(self.blocked),
        }


# Metrics ----------------------------------------------

@dataclass
class Metrics:
    """
    Container for aggregate performance statistics of a simulation run.

    Nomenclature: paper text refers to "exogenous agents" where this
    codebase historically used "human"; field names retain "human" for
    backward compatibility but the docstrings below use the paper's
    terminology.  Aliases such as ``collisions_agent_exogenous`` and
    ``violations_exogenous_attributable`` provide a stable surface for
    paper-aligned reporting code.

    Attributes:
        throughput: Rate of tasks completed per time step (completed / steps).
        completed_tasks: Total number of tasks finished.
        task_completion: The percentage of completed tasks completed.
        mean_flowtime: Average time (steps) from task release to completion.
        collisions_agent_agent: Count of agent-agent collisions detected.
        collisions_agent_human: Count of agent-human collisions detected.
        near_misses: Count of dangerous proximity events (e.g., distance <= 1).
        replans: Number of times local or global replanning was triggered.
        total_wait_steps: Sum of steps all agents spent waiting.
        steps: Total duration of the simulation run.
        safety_violations: Legacy total count of (agent, human) safety-buffer
            violation pairs at step t+1.  Equals
            ``violations_agent_attributable + violations_exogenous_attributable``.
        violations_agent_attributable: Count of (agent, human) violation pairs
            that are AGENT-ATTRIBUTABLE per paper Section 3.4: at decision
            time t the agent had at least one observed exogenous agent h' in
            X_t^{Phi_i} with ell_1(s_i(t+1), h'_pos_at_t) <= r_safe.  Theorem 1
            claims this count is exactly zero under our framework.
        violations_exogenous_attributable: Count of (agent, human) violation
            pairs that are EXOGENOUS-ATTRIBUTABLE: an exogenous agent moved
            into the agent's buffer despite the agent selecting a non-violating
            action under its decision-time information (no observed h' was
            within r_safe of s_i(t+1)).
        safety_violation_rate: Legacy safety_violations per 1000 timesteps.
        global_replans: Number of Tier-1 global replanning events.
        local_replans: Number of Tier-2 local replanning events.
        intervention_rate: Global replans per 1000 timesteps (how often
            global planner must intervene due to local deadlocks).
        mean_service_time: Average steps from task assignment to completion.
        median_flowtime: Median flowtime across completed tasks.
        max_flowtime: Maximum flowtime across completed tasks.
        human_passive_wait_steps: Steps humans spent waiting due to agent proximity.
    """
    throughput: float = .0
    completed_tasks: int = 0
    total_released_tasks: int = 0
    task_completion: float = 0.
    # Load-regime diagnostics (P10).  ``arrival_rate_per_step`` is
    # the system-wide task arrival rate (released_tasks /
    # total_steps); under the simulator's default lifelong stream
    # (``Simulator._generate_task_stream``) it equals |M|/(H+W),
    # where H and W are the map height + width.
    # ``throughput_utilization`` is throughput / arrival_rate;
    # >= 1.0 means the cell is arrival-saturated and the throughput
    # column measures the task arrival cap, NOT planner capacity.
    # Used to flag arrival-saturated cells in paper tables; see
    # ``paper/sections/05_1_load_regime.tex`` for the paper-text
    # discussion and ``scripts/diagnostics/check_arrival_saturation.py``
    # for the cross-cell audit.
    arrival_rate_per_step: float = .0
    throughput_utilization: float = .0
    mean_flowtime: float = .0
    collisions_agent_agent: int = 0
    collisions_agent_human: int = 0
    near_misses: int = 0
    replans: int = 0
    total_wait_steps: int = 0
    steps: int = 0
    # Per-tick agent-tick violation count (per (agent, human) pair,
    # per tick).  A human loitering inside an agent's safety buffer
    # for N consecutive ticks contributes N to this counter; the
    # debounced ``safety_violation_events`` counts the same hover
    # as ONE event.  The P6 audit flagged the per-tick form as a
    # misleading summary stat for paper scaling tables; both are
    # exposed so each plot / table can pick the right one.
    # ``safety_violation_agent_ticks`` is an explicit alias for
    # ``safety_violations`` that names the unit honestly; the
    # legacy field is kept for back-compat with existing CSVs.
    safety_violations: int = 0
    safety_violation_agent_ticks: int = 0
    safety_violation_events: int = 0
    # ``safety_violation_rate = safety_violations / total_steps * 1000``
    # (legacy, **deprecated**: divides by steps only, not by agent count,
    # so the rate inflates with fleet size and is not comparable across
    # scaling sweeps).  Use ``safety_violation_rate_per_agent_step``
    # instead.  See ``MetricsTracker.finalize`` for the migration note.
    safety_violation_rate: float = .0
    # Agent-normalized safety-violation rate (P6 fix): per-agent-step
    # incidence of (agent, human) buffer overlaps.  Matches the
    # normalization of ``wait_fraction`` (which divides by
    # ``num_agents * total_steps``) and is therefore comparable across
    # ``num_agents`` values in §5.4 scaling sweeps.
    safety_violation_rate_per_agent_step: float = .0
    # Paper Section 3.4 attribution split (legacy = sum of these two).
    # Per-tick agent-tick counts (one increment per (agent, human)
    # violating pair per tick); ``*_events`` counterparts apply the
    # leading-edge debounce.
    #
    # IMPORTANT.  These are the **WAIT-counterfactual diagnostic**
    # (P5 follow-up), NOT the Theorem 1 invariant from paper §3.
    # The classifier consults post-step-4 human positions and skips
    # the FOV gate; agent-attributable means "the agent moved AND
    # WAIT would have left the agent safe vs this specific h".  This
    # quantity can be nonzero on a healthy run (FOV-blind moves into
    # emergent buffer overlaps) and is kept as an independent
    # measurement so a planner that ignored the forbidden set would
    # surface nonzero values here.
    #
    # The canonical Theorem 1 quantity is the ``violations_def1_*``
    # block below.  Do NOT cite these fields as evidence for or
    # against Theorem 1; they answer a different question.
    violations_agent_attributable: int = 0
    violations_agent_attributable_agent_ticks: int = 0
    violations_agent_attributable_events: int = 0
    violations_exogenous_attributable: int = 0
    violations_exogenous_attributable_agent_ticks: int = 0
    violations_exogenous_attributable_events: int = 0
    # Paper §3 Definition 1 attribution -- the canonical Theorem 1
    # quantity.  Classifier reads pre-step-4 human positions,
    # FOV-gates the witness set X_t^{Phi_i} by r_fov, and applies
    # both clauses (a) ell_1(s_i(t), h_pos_at_t) > r_safe and
    # (b) ell_1(s_i(t+1), h_pos_at_t) <= r_safe AND moved.
    #
    # Theorem 1 (paper §F): on every Algorithm-2 trajectory,
    # ``violations_def1_agent_attributable`` stays zero -- the
    # forbidden set the local controller respects contains every
    # reachable pre-move buffer cell, so no executed action can
    # land inside a buffer the agent observed.  This is a
    # construction-level invariant (hard_safety + r_safe < r_fov +
    # Manhattan-1 moves => the forbidden set covers every reachable
    # buffer cell), proved in ``docs/proposed_approach.md`` §F.
    #
    # ``violations_def1_safety_violations`` is the sum of the two
    # buckets (asserted in ``MetricsTracker.finalize``); it equals
    # the count of post-move violation pairs that pass through
    # classifier (A) in
    # ``simulator.py::_detect_collisions_and_near_misses``.
    violations_def1_agent_attributable: int = 0
    violations_def1_exogenous_attributable: int = 0
    violations_def1_safety_violations: int = 0
    global_replans: int = 0
    local_replans: int = 0
    intervention_rate: float = .0
    mean_service_time: float = .0
    median_flowtime: float = .0
    max_flowtime: float = .0
    human_passive_wait_steps: int = 0
    # Timing metrics (wall-clock, in seconds)
    mean_planning_time_ms: float = .0
    p95_planning_time_ms: float = .0
    max_planning_time_ms: float = .0
    mean_decision_time_ms: float = .0
    p95_decision_time_ms: float = .0
    # Cost-based metrics
    # ``makespan`` is the step at which the last task completed.  In
    # **lifelong** mode it is ~equal to ``total_steps`` (a fresh task
    # almost always finishes near the end of the run), making it
    # near-constant across configurations and useless for cross-run
    # comparison -- the paper P6 audit flagged it as misleading.  Use
    # ``mean_task_completion_span`` (= mean per-task release->completion
    # time) for the lifelong analog.  ``makespan`` is preserved for
    # back-compat (one-shot mode and downstream plot scripts) but is
    # **deprecated** for lifelong reporting.
    makespan: int = 0
    sum_of_costs: int = 0
    # Lifelong-friendly per-task completion span (mirrors
    # ``mean_flowtime`` exactly; exposed under this name so plot
    # scripts can switch off ``makespan`` without renaming columns
    # mid-paper).  See ``MetricsTracker.finalize``.
    mean_task_completion_span: float = 0.0
    # Delay robustness
    delay_events: int = 0
    immediate_assignments: int = 0
    assignments_kept: int = 0
    assignments_broken: int = 0
    # Per-step cumulative throughput timeline (for convergence analysis)
    throughput_timeline: List[float] = field(default_factory=list)
    # Paper §5.8 — per-tick violation timelines.  Each is length-T;
    # index t is the count of violation pairs detected on tick t.
    # Empty if ``SimConfig.log_violations_timeline`` is False (default).
    violations_agent_timeline: List[int] = field(default_factory=list)
    violations_exogenous_timeline: List[int] = field(default_factory=list)
    # Wait-kind decomposition (paper Section 5.x).  Invariant:
    #   total_wait_steps == safe_wait_steps + yield_wait_steps.
    # ``safe_wait_steps`` counts ticks where the controller committed a
    # safety-induced WAIT (no F-respecting action available).
    # ``yield_wait_steps`` counts ticks where the controller committed a
    # conflict-induced WAIT (resolver yielded after losing).
    safe_wait_steps: int = 0
    yield_wait_steps: int = 0
    # Fraction of (agent x step) pairs spent waiting:
    #   wait_fraction = total_wait_steps / (num_agents * steps).
    # Computed in ``MetricsTracker.finalize``.  Reflects "how often does
    # a controlled agent fail to make progress" averaged over the run.
    wait_fraction: float = 0.0
    # Nomenclature alias for ``collisions_agent_human``.  The paper text
    # refers to "exogenous agents" while the implementation uses "human"
    # in module / class names; this alias gives the paper's terminology
    # a stable home in the metrics dataclass without a disruptive rename.
    # Always equal to ``collisions_agent_human`` post-finalize.
    collisions_agent_exogenous: int = 0
    # Solver-wrapper status counters.  These are populated by the
    # SolverResult contract introduced in core/types.py::SolverResult.
    # Invariants:
    #   total_solver_failures = solver_timeouts + solver_errors
    #   solver_partial_returns is NOT a failure — the agent received a
    #     usable (anytime) plan.
    # ``solver_timeouts`` legacy semantics post-contract: counts the
    # ``timeout_no_result`` status only (NOT partial_anytime).
    solver_timeouts: int = 0
    solver_partial_returns: int = 0
    solver_errors: int = 0
    # Count of replans for which the global solver failed
    # (timeout_no_result / error / binary_not_found) AND the
    # RollingHorizonPlanner re-anchored the previous good PlanBundle
    # instead of emitting all-WAIT.  Strictly <= solver_timeouts +
    # solver_errors; the difference equals "failures handled at the
    # start of the run, before any good bundle existed."  A reused
    # plan is still a solver failure — solver_errors / solver_timeouts
    # are NOT downgraded when this counter ticks.
    solver_fallback_reuses: int = 0
    # Paper §5.7 — deadlock count.  Number of distinct controlled
    # agents whose position-unchanged streak exceeded
    # ``SimConfig.deadlock_streak_threshold`` at any point during the
    # run.  Streaks are tracked per-agent with an active task only and
    # reset on movement, fresh task assignment, or becoming idle.
    # Mean over seeds gives the per-cell average count of deadlocked
    # agents the §5.7 figure plots.
    deadlock_count: int = 0
    # Paper §5.6 — global (population-level) no-progress metrics.
    # A "no-progress tick" is one where ZERO controlled agents with
    # an active task advanced their position vs the previous tick.
    # Mirrors the per-agent ``deadlock_count`` idle-handling: agents
    # without a current task, or with a freshly assigned task, do
    # NOT count toward the no-progress condition.  Ticks where no
    # agent has an active task at all are skipped (neither counted
    # nor breaking a streak).
    #
    # ``max_global_no_progress_streak`` is the longest run of
    # consecutive no-progress ticks observed during the run.  Lets
    # the deadlock threshold be chosen at analysis time rather than
    # baked into the sweep.
    #
    # ``global_no_progress_steps`` is the total count of no-progress
    # ticks (not necessarily consecutive).  Useful as a coarse
    # population-level stall rate.
    max_global_no_progress_streak: int = 0
    global_no_progress_steps: int = 0
    # Paper §5.5 — realized inter-agent path overlap of the chosen
    # assignment, computed POST-ALLOCATION uniformly for every
    # allocator.  After each allocator.assign(...) call the simulator
    # runs the same BFS the congestion_avoidance allocator uses
    # internally (task_allocator.py:_bfs / _reconstruct_path) from
    # each assigned agent's current position to its task's pickup
    # location, then sums |path_i ∩ path_j| over all assigned-agent
    # pairs.  Defined identically for greedy / hungarian / auction /
    # congestion_avoidance, so a like-for-like comparison is possible.
    #
    # ``sum_assignment_path_overlap`` accumulates the pairwise-overlap
    # sum across every allocation round in the run.
    # ``mean_assignment_path_overlap`` divides by the number of
    # allocation rounds (calls to allocator.assign with at least one
    # agent), or is 0.0 if no allocation rounds occurred.
    sum_assignment_path_overlap: float = 0.0
    mean_assignment_path_overlap: float = 0.0
    # Paper §5.5 — count of allocation rounds in which 2+ agents were
    # (re)assigned simultaneously.  ``mean_assignment_path_overlap``
    # divides by the total round count (which includes single-agent
    # unlock-path calls that yield 0 overlap by definition) and is
    # therefore diluted.  The clean per-round overlap is
    #     sum_assignment_path_overlap / n_multiagent_allocation_rounds
    # computed at analysis time — numerator and denominator now count
    # the same event.
    n_multiagent_allocation_rounds: int = 0
    # Tier-1 -> Tier-2 guidance handoff instrumentation
    # (``SimConfig.debug_guidance_trace``).  Three raw counters and two
    # derived ratios so downstream tooling can read either form.
    #   guidance_eligible_ticks: agent-ticks where the agent had an
    #     active task (goal != None and pos != goal) -- the only ticks
    #     where guidance is expected.
    #   guidance_covered_ticks: subset of eligible ticks where the
    #     current PlanBundle held a non-empty TimedPath for that agent.
    #   guidance_followed_ticks: subset of covered ticks where the
    #     agent's post-physics position equals the cell the bundle
    #     prescribed for ``step + 1``.
    # Ratios are zero on runs with the flag off (no counters incremented)
    # which is fine -- downstream tooling treats zero/zero as "not
    # measured" rather than a real value.  See
    # ``docs/tier_handoff_diagnosis.md``.
    guidance_eligible_ticks: int = 0
    guidance_covered_ticks: int = 0
    guidance_followed_ticks: int = 0
    guidance_coverage: float = 0.0
    guidance_follow_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize metrics to a dictionary."""
        return asdict(self)


# Simulation Configuration -----------------------------

@dataclass
class SimConfig:
    """
    Configuration parameters defining a complete experiment setup.

    Attributes:
        map_path: Path to the static grid map file (.map format).
        task_stream_path: Path to pre-generated task file (optional).
                          If None, tasks may be generated randomly.
        seed: Random seed for reproducibility.
        steps: Maximum number of simulation steps to run.
        num_agents: Number of agent agents in the fleet.
        num_humans: Number of dynamic human obstacles to simulate.
        fov_radius: Radius (Manhattan distance) of agent's sensor field of view.
        safety_radius: Buffer distance to maintain around detected humans.
        global_solver: Name of the solver for Tier-1.
                       Python: "cbs" (optimal), "lacam" (fast, approximate).
                       Official C++: "lacam3", "lacam_official", "pibt2" (requires build).
        replan_every: Interval (steps) for triggering global re-planning.
        horizon: Time horizon for the global rolling planner.
        deviation_threshold: Min. change ratio between global and local paths to recall global planner
        communication_mode: Protocol for conflict resolution.  Canonical:
            "wait_based" (formerly "priority") or "token_based" (formerly
            "token").  Legacy values continue to be accepted via the
            factory alias in ``simulator.py``.
        local_planner: Algorithm for Tier-2 local pathfinding ("astar").
        human_model: Motion model for humans.
                     Options: "random_walk", "aisle", "adversarial", "mixed", "replay".
        human_model_params: Model-specific parameters passed to the human model constructor.
                            - random_walk: {"beta_go": 2.0, "beta_wait": -1.0, "beta_turn": 0.0}
                            - aisle: {"alpha": 1.0, "beta": 1.5}
                            - adversarial: {"gamma": 2.0, "lambda": 0.5}
                            - mixed: {"weights": {"random_walk": 0.4, "aisle": 0.4,
                                      "adversarial": 0.2}, "sub_params": {...}}
                            - replay: {"trajectory_path": "path/to/replay.json"}
        map_to_human_model: Optional dict mapping map filename stems
            (e.g. ``"warehouse-10-20-10-2-1"``) to exogenous-agent motion
            model names.  When the map's stem is present, the simulator
            uses the mapped model and overrides ``human_model``.  See
            ``ha_lmapf.io.default_map_to_human_model`` for the paper's
            default mapping.
        solver_timeout_s: Per-call wall-clock budget (seconds) for the
            global solver.  Default 10.0 per paper Section 5.1.  Passed as
            ``time_limit_sec`` to solver wrappers.  Takes precedence over
            the legacy ``time_budget_ms`` when both are set.
        hard_safety: If True, agents MUST NOT enter B_r(X_t) (hard
            constraint per the paper, where X_t is the set of exogenous
            agents).  If False, the safety buffer is a high-cost soft
            constraint (prevents deadlock).
        mode: Experiment mode.
              "lifelong" — continuous pickup-delivery task stream with rolling-horizon replanning.
              "one_shot" — classical MAPF: each agent gets one goal at step 0, planned once,
                           task done when goal reached. No pickup phase, no replanning.
        task_allocator: Strategy for assigning tasks to agents.
                        "congestion_avoidance" — iterated Hungarian on
                                            BFS distances with a path-
                                            overlap penalty (default;
                                            paper Section 4.2 name).
                        "greedy" — nearest-task by Manhattan distance.
                        "hungarian" — optimal matching via Hungarian algorithm.
                        "auction" — sequential single-item auction.
        lambda_conflict: Penalty weight in the ``congestion_avoidance``
                         allocator.
                         Higher values make the allocator more willing to
                         take longer paths to avoid conflict. With 0.0 the
                         allocator degenerates to Hungarian-on-BFS-distance.
                         Ignored for other allocators. Default 0.5.
        max_rounds: Hard cap on iterative refinement rounds in
                    ``congestion_avoidance``. Ignored for other
                    allocators. Default 5.
        execution_delay_prob: Probability [0,1] that an agent's move is delayed at each step.
        execution_delay_steps: Duration (in steps) of each injected delay.
        time_budget_ms: Max wall-clock ms per global planning call (0 = unlimited).
        task_arrival_rate: Mean steps between task releases *per agent* (higher = slower arrival).
            System-wide arrival rate = num_agents / task_arrival_rate tasks/step.
            None (default) = auto-compute as height + width, which accounts for the
            two-leg task cycle (pickup + delivery) plus typical congestion overhead,
            giving a balanced ~85% utilization for any fleet size or map dimensions.
        task_arrival_percentage: Fraction (0,1] of steps during which new tasks are released.
        disable_local_replan: Ablation flag — disable Tier-2 local replanning.
        disable_conflict_resolution: Ablation flag — disable decentralized conflict resolution.
        disable_safety: Ablation flag — disable human safety buffer entirely.
    """
    map_path: str
    task_stream_path: Optional[str] = None
    seed: int = 0
    # Paper Section 5.1 defaults: 2000-step lifelong runs.
    steps: int = 2000
    num_agents: int = 1
    num_humans: int = 0
    fov_radius: int = 4
    safety_radius: int = 1
    # Paper Section 5.1 default global solver = LaCAM (Okumura 2023 AAAI,
    # Kei18/lacam).  In ``GlobalPlannerFactory`` the LaCAM wrapper
    # (``LaCAMOfficialSolver``) is registered under ``"lacam_official"``
    # (aliases: ``"lacam_cpp"``, ``"lacam"``).  The anytime variant LaCAM*
    # (Okumura 2024, Kei18/lacam3) is available under ``"lacam3"`` for
    # sweeps that need it.
    global_solver: str = "lacam_official"
    # Paper Section 5.1 schedule: replan every 10 steps, plan 20 steps ahead.
    replan_every: int = 10
    horizon: int = 20
    deviation_threshold: float = 1.0
    # Paper §4.3 conflict-resolution selector.  Canonical names:
    #   "wait_based"   — WaitBasedResolver (formerly "priority")
    #   "token_based"  — TokenBasedResolver (formerly "token")
    # Legacy "priority" / "token" values continue to be accepted by the
    # simulator's factory dispatch (mapped old → new) so archived YAMLs
    # and run manifests keep working without rewrites.
    communication_mode: Literal[
        "wait_based", "token_based", "priority", "token",
    ] = "wait_based"
    local_planner: str = "astar"
    human_model: str = "random_walk"
    human_model_params: Dict[str, Any] = field(default_factory=dict)
    # Optional per-map exogenous-agent model selection.  When set, the
    # simulator looks up the map filename stem (basename without
    # extension) in this dict and uses the mapped model name in place of
    # ``human_model``.  See ``ha_lmapf.io.default_map_to_human_model``
    # for the canonical paper mapping.
    map_to_human_model: Optional[Dict[str, str]] = None
    hard_safety: bool = True
    mode: Literal["lifelong", "one_shot"] = "lifelong"
    task_allocator: Literal[
        "greedy", "hungarian", "auction", "congestion_avoidance",
    ] = "congestion_avoidance"
    # Tuning knobs for the congestion_avoidance allocator. Ignored by
    # greedy / hungarian / auction. Defaults match the class-level
    # defaults so existing configs continue to behave identically.
    lambda_conflict: float = 0.5
    max_rounds: int = 5
    # Tuning knob for the auction allocator (paper §5.5 baseline).
    # Sequential single-item auction's bid-increment epsilon.  Ignored
    # by greedy / hungarian / congestion_avoidance.  Default matches
    # the AuctionBasedTaskAllocator.__init__ default so configs that
    # don't set it behave identically to pre-knob runs.
    auction_epsilon: float = 0.01
    # Delay robustness
    execution_delay_prob: float = 0.0
    execution_delay_steps: int = 1
    # Planning time budget (0 = unlimited).  Legacy field; prefer
    # ``solver_timeout_s`` for new configs.  When both are set,
    # ``solver_timeout_s`` wins.
    time_budget_ms: float = 0.0
    # Paper Section 5.1 default per-call solver timeout (seconds).
    # Passed to LaCAM / LaCAM* / CBS wrappers as ``time_limit_sec``.
    solver_timeout_s: float = 10.0
    # Task generation mode:
    #   "poisson"   — pre-generate stream with Poisson inter-arrivals (original).
    #   "immediate"  — Li et al. (2022) style: one task per agent at step 0,
    #                  new task generated on-demand when agent completes delivery.
    #                  Guarantees every agent always has exactly one task.
    task_mode: Literal["poisson", "immediate"] = "poisson"
    # Task generation rate (mean steps between releases per agent).
    # Only used when task_mode="poisson".
    # None = auto-compute from map geometry: (height + width) / 3.
    task_arrival_rate: Optional[float] = None
    task_arrival_percentage: float = 0.9
    # Commitment persistence for task allocation.
    # commit_horizon: max steps an assignment stays locked (0 = disabled).
    # delay_threshold: revoke if current distance > threshold × d0, where
    #   d0 is the Manhattan distance to the goal at the moment of assignment
    #   (0.0 = disabled).  Both conditions are independent; either can fire.
    commit_horizon: int = 0
    delay_threshold: float = 0.0
    # Ablation flags
    disable_local_replan: bool = False
    disable_conflict_resolution: bool = False
    disable_safety: bool = False
    # When local replan is disabled, after this many consecutive safety-waits
    # the agent requests a global replan (0 = never).
    fallback_wait_limit: int = 5
    # Emergency global-replan trigger (paper Section 4.4).  When the fraction
    # of controlled agents that committed Safe Wait in the previous tick
    # exceeds ``eta_w``, RollingHorizonPlanner fires an off-period replan,
    # subject to ``replan_min_gap`` ticks since the last fire.
    eta_w: float = 0.20
    replan_min_gap: int = 3
    # Observability: when an individual agent's consecutive Safe-Wait
    # streak reaches this threshold, the simulator emits a one-time
    # WARNING log line ([BUFFER-STUCK]).  Set to 0 to disable.  Does
    # NOT trigger replans or change behaviour — purely diagnostic.
    buffer_stuck_warn_threshold: int = 20
    # Paper §5.7 — deadlock detection threshold.  An agent is recorded
    # as "deadlocked" if its position is unchanged for this many
    # consecutive ticks while it has an active task assignment.  An
    # agent that crosses the threshold contributes 1 to the per-run
    # Metrics.deadlock_count (distinct-agent set; re-crossing the
    # threshold for the same agent does not double-count).  Between-
    # task idle RESETS the streak (does not freeze).
    deadlock_streak_threshold: int = 100
    # Paper §5.8 — when True, the simulator appends per-tick violation
    # counts to Metrics.violations_agent_timeline and
    # Metrics.violations_exogenous_timeline.  Default False to avoid
    # per-tick memory cost (2 ints per tick) for sweeps that don't
    # need temporal data.  The §5.8 sweep YAML overrides to True.
    log_violations_timeline: bool = False
    # Tier-2 controller kind.
    #   "default"     — full Sense-Plan-Act controller with hard-safety,
    #                   local A* repair, and conflict resolution.
    #   "global_only" — paper baseline mode: rigidly follow the global
    #                   plan; no local repair, no buffer-aware detour.
    #                   WAITs only at exact occupied cells via the
    #                   observation's ``blocked`` set.  Used by the
    #                   PIBT2-FR baseline (paper Section 5.5) and to
    #                   make RHCR truly exogenous-blind end-to-end.
    controller_kind: Literal["default", "global_only"] = "default"
    # When True the simulator instruments the Tier-1 -> Tier-2 handoff
    # per (agent, tick): whether a global guidance path was available
    # and whether the executed action matched it.  Adds two dict
    # lookups + a comparison per agent per tick (negligible at sweep
    # scale, but off by default).  Used by
    # ``scripts/debug_tier_handoff.py`` and the §5.4 / §5.5 sanity
    # checks; see ``docs/tier_handoff_diagnosis.md``.
    debug_guidance_trace: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config to a dictionary."""
        return asdict(self)
