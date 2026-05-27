"""
Core Protocol Interfaces.

This module defines the architectural boundaries of the system using Python Protocols.
It establishes the contracts for:
  - Global Planning (Tier-1): High-level multi-agent pathfinding.
  - Local Planning (Tier-2): Low-level single-agent detours.
  - Task Allocation: Assigning goals to agents.
  - Conflict Resolution: Decentralized agent-agent deconfliction logic.
  - Human Prediction: Forecasting dynamic obstacle positions.

These interfaces ensure that the simulation loop remains decoupled from specific algorithm implementations.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Protocol, Set, Tuple, Any, runtime_checkable, Iterable

from ha_lmapf.core.types import (
    AgentState,
    HumanState,
    Observation,
    PlanBundle,
    StepAction,
    Task,
)

Cell = Tuple[int, int]


@runtime_checkable
class SimStateView(Protocol):
    """
    Lightweight, read-only view of the simulator's internal state.

    This interface is passed to Planners and Resolvers to allow them to query
    global truth (in centralized settings) or debug states, without giving
    them write access to the simulation variables.
    """

    @property
    def step(self) -> int:
        """Current global simulation time step."""
        ...

    @property
    def env(self) -> Any:
        """Mapping of all agent IDs to their current state."""
        ...

    @property
    def agents(self) -> Dict[int, AgentState]:
        """Mapping of all human IDs to their current state."""
        ...

    @property
    def humans(self) -> Dict[int, HumanState]:
        ...

    def plans(self) -> Optional[PlanBundle]:
        """
        Access to the currently active global plan.
        Returns None if no plan has been generated yet.
        """
        ...

    def decided_next_positions(self) -> Dict[int, Tuple[int, int]]:
        """
        Access to positions that agents have already decided to move to this timestep.

        This is used by conflict resolution to prevent collisions during sequential
        decision-making. Returns a mapping of agent_id -> intended_next_cell for
        agents that have already made their decision this timestep.
        """
        ...


class TaskAllocator(Protocol):
    """
    Interface for assigning open tasks to available agents.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: Iterable[Task],
            step: int,
            rng: Any = None,
    ) -> Dict[int, Task]:
        """
        Compute an assignment of tasks to agents.

        Args:
            agents: Dictionary of current agent states.
            open_tasks: List of unassigned tasks available in the backlog.
            step: Current simulation step.
            rng: Random number generator for tie-breaking.

        Returns:
            A dictionary mapping agent_id -> Task.
            Agents not included in the dictionary receive no new task this epoch.
        """

    ...


class GlobalPlanner(Protocol):
    """
    Interface for the Tier-1 Centralized MAPF Planner (e.g., CBS, LaCAM).

    The contract has TWO entry points:

    * ``plan_with_metadata`` — the **canonical** entry point.  Returns
      a ``SolverResult`` (see ``ha_lmapf.core.types``) carrying the
      ``PlanBundle`` plus a ``status`` discriminator, internal solver
      wall-clock, end-to-end wall-clock, and any error message.  The
      ``status`` field is set by the single decision tree in
      :class:`ha_lmapf.global_tier.solvers._base.BaseSolverWrapper`.

    * ``plan`` — legacy shim that returns just the ``PlanBundle``.
      Kept for backward compatibility with callers that don't yet
      consume the metadata.  Implementations may either provide it
      explicitly or inherit the default which delegates to
      ``plan_with_metadata``.
    """

    def plan_with_metadata(
            self,
            env: Any,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng: Any,
    ) -> "SolverResult":  # noqa: F821 — forward ref, imported below for type-checking
        """
        Compute collision-free timed paths and return a structured
        ``SolverResult`` capturing status / timing / error info.

        Returns:
            A SolverResult whose ``plan`` field is always a complete
            ``PlanBundle`` (real paths or all-WAIT fallback).  See
            :class:`ha_lmapf.core.types.SolverResult` for full
            semantics of the five possible ``status`` values.
        """
        ...

    def plan(
            self,
            env: Any,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng: Any
    ) -> PlanBundle:
        """
        Compute collision-free timed paths for all agents over a finite
        horizon.

        Legacy shim.  Default implementation calls
        ``plan_with_metadata`` and returns ``result.plan``.  Wrappers
        that override ``plan`` directly (rather than going through
        ``plan_with_metadata``) bypass the SolverResult contract and
        will not surface ``status`` / timing information to the
        caller — avoid that pattern in new code.
        """
        ...


class LocalPlanner(Protocol):
    """
    Interface for the Tier-2 Single-Agent Path Planner (e.g., A*, D* Lite).

    Used by agents to calculate detours around dynamic obstacles on their local map.
    """

    def plan(
            self,
            env: Any,
            start: Cell,
            goal: Cell,
            blocked: Set[Cell],
            guidance_cells: Optional[Set[Cell]] = None,
    ) -> List[Cell]:
        """
        Find a path from start to goal avoiding specific blocked cells.

        Args:
            env: The static environment/grid context.
            start: The starting cell (row, col).
            goal: The target cell (row, col).
            blocked: A set of cells treated as obstacles (e.g., inflated human positions).
            guidance_cells: Optional remaining cells from the current global path.
                            Implementations may use this to bias search toward
                            path-aligned detours (path-preserving local repair).

        Returns:
            A list of cells representing the path [start, ..., goal].
            Returns an empty list [] if no path exists.
        """
        ...


class ConflictResolver(Protocol):
    """
    Interface for Decentralized Conflict Resolution logic (Algorithm 3).

    Encapsulates the policy for deciding which agent yields when a agent-agent
    collision is imminent during execution.
    """

    def resolve(
            self,
            agent_id: int,
            desired_cell: Cell,
            sim_state: SimStateView,
            observation: Observation,
            rng: Any,
            **kwargs: Any,
    ) -> StepAction:
        """
        Determine the next safe action given a potential conflict.

        Args:
            agent_id: The ID of the agent requesting resolution.
            desired_cell: The cell the agent wants to move into.
            sim_state: Global view (used for privileged baselines or oracle debugging).
                       Real implementation should rely primarily on 'observation'.
            observation: The agent's local observation (visible neighbors).
            rng: Random number generator.
            **kwargs: Optional extension hooks.  In particular the
                ``AgentController`` plumbs ``forbidden`` (the inflated safety
                buffer F = B_{r_safe}(X_t^{Phi_i})) and ``local_planner``
                (an ``AStarLocalPlanner`` instance) so that the loser's
                fallback path can respect Theorem 1's invariant: no executed
                action enters F.  Resolvers that do not need these hooks
                may simply ignore the kwargs.

        Returns:
            A StepAction (e.g., WAIT, or a side-step direction) to resolve the conflict.
        """
        ...


class HumanPredictor(Protocol):
    """
    Interface for predicting dynamic obstacle occupancy (e.g., Human Motion Prediction).
    """

    def predict(
            self,
            humans: Dict[int, HumanState],
            horizon: int,
            rng: Any,
    ) -> List[Set[Cell]]:
        """
        Forecast unsafe cells for a future time horizon.

        Args:
            humans: Current state of humans.
            horizon: Number of steps to predict into the future.
            rng: Random number generator.

        Returns:
            A list of sets of cells. The set at index `t` contains all cells
            predicted to be occupied by humans at time `now + t`.
        """
        ...
