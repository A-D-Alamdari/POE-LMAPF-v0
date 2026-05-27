"""
Simulation Event Definitions.

This module defines the immutable data structures used to record discrete events
during the simulation. These events serve multiple purposes:
  1. Logging: A structured history of "what happened" (assignments, collisions).
  2. Debugging: Tracing the cause of specific behaviors (e.g., why did Agent 5 stop?).
  3. Metrics: The `MetricsTracker` aggregates these events to calculate statistics.

All events are frozen dataclasses to ensure they remain immutable once created.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

Cell = Tuple[int, int]


@dataclass(frozen=True)
class TaskAssigned:
    """
    Event recorded when an agent is assigned a new task.

    Attributes:
        step: Simulation tick when the assignment occurred.
        agent_id: The ID of the assignee.
        task_id: The unique string ID of the task.
        goal: The target coordinates (row, col).
    """
    step: int
    agent_id: int
    task_id: str
    goal: Cell


@dataclass(frozen=True)
class TaskCompleted:
    """
    Event recorded when an agent successfully reaches its goal.

    Attributes:
        step: Simulation tick when completion occurred.
        agent_id: The ID of the agent.
        task_id: The ID of the completed task.
        goal: The location where the task was finished.
    """
    step: int
    agent_id: int
    task_id: str
    goal: Cell


@dataclass(frozen=True)
class HumanDetected:
    """
    Event recorded when an agent senses a human in its field of view.

    Attributes:
        step: Simulation tick.
        agent_id: The observing agent.
        human_id: The detected human.
        cell: The location of the human at that moment.
    """
    step: int
    agent_id: int
    human_id: int
    cell: Cell


@dataclass(frozen=True)
class ReplanTriggered:
    """
    Event recorded when a path re-calculation is initiated.

    Attributes:
        step: Simulation tick.
        agent_id: The specific agent triggering the replan, or None if it's
                  a system-wide Global Replan (e.g., periodic rolling horizon).
        reason: Description of the cause (e.g., "blocked_by_human", "rolling_horizon").
    """
    step: int
    agent_id: Optional[int]  # None if global replan
    reason: str


@dataclass(frozen=True)
class Collision:
    """
    Event recorded when a safety violation occurs (entities overlapping).

    Attributes:
        step: Simulation tick.
        entity_a: Identifier string (e.g., "agent:1").
        entity_b: Identifier string (e.g., "agent:2" or "human:0").
        cell: The grid location where the collision occurred.
    """
    step: int
    entity_a: str  # e.g., "agent:1"
    entity_b: str  # e.g., "agent:2" or "human:0"
    cell: Cell


@dataclass(frozen=True)
class NearMiss:
    """
    Event recorded when entities come dangerously close (e.g., dist <= 1) but do not collide.

    Attributes:
        step: Simulation tick.
        agent_id: The agent involved.
        other_entity: Identifier string of the other party (e.g., "human:1").
        cell: The location of the agent during the near miss.
    """
    step: int
    agent_id: int
    other_entity: str  # e.g., "agent:2" or "human:1"
    cell: Cell
