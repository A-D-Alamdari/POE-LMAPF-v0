"""
Agent Dynamics and Physics.

This module defines the state transition logic for agents within the simulation.
It is responsible for:
  1. Calculating the target position based on a discrete action (UP, DOWN, etc.).
  2. Validating the move against the static environment (walls/obstacles).
  3. Updating the agent's internal state (position, wait counters).

Note on Collisions:
    This module only enforces *static* constraints (e.g., "Don't walk into a wall").
    Dynamic constraints (e.g., "Don't walk into another agent or human") are
    checked *after* this step by the main `Simulator` loop to detect and log collisions.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Tuple

from ha_lmapf.core.grid import apply_action as _apply_action_grid
from ha_lmapf.core.types import AgentState, StepAction

Cell = Tuple[int, int]


def apply_action(env, agent_state: AgentState, action: StepAction) -> AgentState:
    """
    Compute the next state of an agent after applying a discrete action.

    Logic:
        - If the action is WAIT, the agent stays in place and `wait_steps` increments.
        - If the action is a move (UP/DOWN/LEFT/RIGHT):
            - Calculate the desired coordinate.
            - Check `env.is_free(desired)` to ensure it's not a static obstacle.
            - If valid, update position.
            - If invalid (blocked by wall), the agent effectively waits (pos stays same).

    Args:
        env: The environment object (must support `.is_free(cell)`).
        agent_state: The current snapshot of the agent.
        action: The discrete step action to attempt.

    Returns:
        A new AgentState object with updated position and counters.
    """
    cur = agent_state.pos

    # Calculate the raw target coordinate based on the direction
    desired = _apply_action_grid(cur, action)

    # Validate against static obstacles
    # We allow the move if:
    # 1. It is NOT a wait action (waiting doesn't change position)
    # 2. The target cell is free of static obstacles
    if action != StepAction.WAIT and env.is_free(desired):
        new_pos = desired
        new_wait = 0  # Reset streak on successful move
    else:
        # Move rejected (hit wall) OR explicit wait
        new_pos = cur
        new_wait = agent_state.wait_steps + (1 if action == StepAction.WAIT else 0)

    return replace(
        agent_state,
        pos=new_pos,
        wait_steps=new_wait,
    )
