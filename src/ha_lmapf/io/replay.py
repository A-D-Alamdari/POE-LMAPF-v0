"""
Simulation Replay Recorder.

This module provides the `ReplayWriter` class, which captures the state of the
simulation at every time step and serializes it to a JSON file.

Replay files are essential for:
  1. Visualization: Rendering the simulation post-hoc using the GUI.
  2. Debugging: analyzing specific failure cases (collisions, deadlocks).
  3. Auditability: Providing a permanent record of an experiment run.

Output JSON Schema:
    {
      "meta": {
         "map_path": "path/to/map.map",
         "seed": 12345,
         "steps": 100,
         "config": { ... },
         "task_stream": [
            {"id": "t1", "goal": [5, 10], "release_step": 0},
            ...
         ]
      },
      "agents": {
         "0": [[r0, c0], [r1, c1], ...],
         "1": [[r0, c0], [r1, c1], ...]
      },
      "humans": {
         "0": [[r0, c0], ...],
         ...
      }
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ha_lmapf.core.types import AgentState, HumanState, SimConfig, Task

Cell = Tuple[int, int]


@dataclass
class ReplayWriter:
    """
    Stateful recorder that collects agent and human trajectories during simulation.

    Attributes:
        map_path: Path to the static map file used in this run.
        seed: Random seed used for the experiment.
        config: Dictionary representation of the full SimConfig.
        task_stream: List of task definitions active in this run (for reference).
    """
    map_path: str
    seed: int
    config: Dict[str, Any]
    task_stream: List[Dict[str, Any]] = field(default_factory=list)

    # Internal storage for trajectories.
    # Key: Entity ID, Value: List of [row, col] coordinates for each step.
    _agent_traj: Dict[int, List[List[int]]] = field(default_factory=dict, init=False)
    _human_traj: Dict[int, List[List[int]]] = field(default_factory=dict, init=False)
    _steps: int = field(default=0, init=False)

    @classmethod
    def from_config(
            cls,
            map_path: str,
            seed: int,
            config: SimConfig,
            tasks: Optional[List[Task]] = None,
    ) -> "ReplayWriter":
        """
        Factory method to initialize a writer from simulation configuration objects.

        Args:
            map_path: Path to the map file.
            seed: Random seed.
            config: The SimConfig object.
            tasks: Optional list of Task objects to include in the replay metadata.

        Returns:
            A configured ReplayWriter instance.
        """
        task_stream = []
        if tasks is not None:
            task_stream = [{"id": t.task_id, "goal": [t.goal[0], t.goal[1]], "release_step": t.release_step} for t in
                           tasks]
        return cls(
            map_path=map_path,
            seed=seed,
            config=config.to_dict(),
            task_stream=task_stream,
        )

    def record(self, agents: Dict[int, AgentState], humans: Dict[int, HumanState]) -> None:
        """
        Snapshot the current positions of all entities.

        This method must be called exactly once per simulation step to ensure
        that the trajectory lists remain synchronized with the time steps.

        Args:
            agents: Dictionary of {agent_id: AgentState}.
            humans: Dictionary of {human_id: HumanState}.
        """
        # Ensure stable ordering by iterating over sorted ids to handle non-deterministic dicts
        for aid in sorted(agents.keys()):
            a = agents[aid]
            self._agent_traj.setdefault(aid, []).append([int(a.pos[0]), int(a.pos[1])])

        for hid in sorted(humans.keys()):
            h = humans[hid]
            self._human_traj.setdefault(hid, []).append([int(h.pos[0]), int(h.pos[1])])

        self._steps += 1

    def write(self, path: str) -> None:
        """
        Serialize the recorded history to a JSON file.

        Args:
            path: Destination file path (e.g., "logs/replay_001.json").
        """
        payload = {
            "meta": {
                "map_path": self.map_path,
                "seed": self.seed,
                "config": self.config,
                "task_stream": self.task_stream,
                "steps": self._steps,
            },
            # Convert integer keys to strings for valid JSON
            "agents": {str(aid): traj for aid, traj in self._agent_traj.items()},
            "humans": {str(hid): traj for hid, traj in self._human_traj.items()},
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
