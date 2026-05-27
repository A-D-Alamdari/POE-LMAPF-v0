"""
Lifelong Task Stream I/O.

This module handles the loading and saving of task sequences for Lifelong MAPF experiments.
In a lifelong setting, tasks are "released" over time rather than all being available
at step 0.

File Format (JSON):
    A task stream is stored as a JSON list of objects, each containing:
      - "id": Unique string identifier (e.g., "t_0").
      - "start": [row, col] list of integers (pickup location).
      - "goal": [row, col] list of integers (delivery location).
      - "release_step": Integer simulation step when the task appears.

    Example:
    [
      {"id": "t_0", "start": [3, 5], "goal": [5, 10], "release_step": 0},
      {"id": "t_1", "start": [8, 2], "goal": [12, 12], "release_step": 25}
    ]

Backward Compatibility:
    If a task does not have a 'start' field in the JSON, a default placeholder
    (-1, -1) is used. The simulator will then treat it as a delivery-only task
    where the agent goes directly to the goal.
"""
from __future__ import annotations

import json
from typing import List

from ha_lmapf.core.types import Task


def _sort_tasks(tasks: List[Task]) -> List[Task]:
    """
    Sort tasks deterministically by release time, then by ID.

    Args:
        tasks: The list of tasks to sort.

    Returns:
        A new list of sorted tasks.
    """
    # Sort by tuple (time, string_id) to ensure strict deterministic order
    return sorted(tasks, key=lambda t: (t.release_step, t.task_id))


def load_task_stream(path: str) -> List[Task]:
    """
    Load a lifelong task stream from a JSON file.

    This function parses the JSON list and converts it into `Task` dataclasses.
    Tasks include both a start (pickup) and goal (delivery) location.

    For backward compatibility, if a task does not have a 'start' field,
    it is set to (-1, -1) as a placeholder. The simulator will treat these
    as delivery-only tasks.

    Args:
        path: Path to the .json task file.

    Returns:
        A list of Task objects, sorted by release_step.

    Raises:
        ValueError: If 'goal' or 'start' is not a 2-element list [r, c].
        KeyError: If required fields ('id', 'goal', 'release_step') are missing.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    tasks: List[Task] = []
    for item in raw:
        tid = str(item["id"])

        # Parse goal (required)
        goal = item["goal"]
        if not (isinstance(goal, list) and len(goal) == 2):
            raise ValueError(f"Invalid goal for task {tid}: {goal}")
        goal_r, goal_c = int(goal[0]), int(goal[1])

        # Parse start (optional, for backward compatibility)
        start = item.get("start")
        if start is None:
            # Backward compatibility: no start specified
            start_r, start_c = -1, -1
        else:
            if not (isinstance(start, list) and len(start) == 2):
                raise ValueError(f"Invalid start for task {tid}: {start}")
            start_r, start_c = int(start[0]), int(start[1])

        release_step = int(item["release_step"])
        tasks.append(Task(
            task_id=tid,
            start=(start_r, start_c),
            goal=(goal_r, goal_c),
            release_step=release_step
        ))

    return _sort_tasks(tasks)


def save_task_stream(tasks: List[Task], path: str) -> None:
    """
    Save a list of Task objects to a JSON file.

    Used for generating reproducible benchmarks or saving specific scenario runs.
    Saves both start (pickup) and goal (delivery) locations.

    Args:
        tasks: The list of Task objects to serialize.
        path: Destination file path.
    """
    tasks_sorted = _sort_tasks(list(tasks))
    raw = [
        {
            "id": t.task_id,
            "start": [t.start[0], t.start[1]],
            "goal": [t.goal[0], t.goal[1]],
            "release_step": t.release_step
        }
        for t in tasks_sorted
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, sort_keys=True)


def get_released_tasks(tasks: List[Task], step: int) -> List[Task]:
    """
    Filter tasks that have become available by the given simulation step.

    This is a helper for the simulation loop to fetch "New Tasks" for the
    current epoch.

    Args:
        tasks: The full backlog of pending tasks.
        step: The current simulation time step.

    Returns:
        A list of tasks where task.release_step <= step.
        The returned list is sorted to ensure deterministic assignment order.
    """
    released = [t for t in tasks if t.release_step <= step]
    return _sort_tasks(released)
