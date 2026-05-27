"""
PIBT-Only Baseline Controller.

This module provides both:
1. A Python PIBT-like controller for decentralized execution
2. An optional wrapper for the official PIBT2 C++ implementation from:
   https://github.com/Kei18/pibt2

The Python implementation is a simplified PIBT-like behavior:
- Ignores global plans entirely
- Chooses greedy moves toward goals
- Uses priority rules for conflict resolution

For the full PIBT2 algorithm, use the official C++ wrapper via:
    from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.interfaces import SimStateView
from ha_lmapf.core.types import Observation, StepAction
from ha_lmapf.local_tier.conflict_resolution.priority_rules import WaitBasedResolver

Cell = Tuple[int, int]


def _check_pibt2_binary_available() -> bool:
    """Check if the official PIBT2 binary is available."""
    try:
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        solver_dir = os.path.dirname(os.path.abspath(__file__))
        solvers_dir = os.path.join(os.path.dirname(solver_dir), "global_tier", "solvers")
        binary_names = ["mapf_pibt2", "mapf_pibt2.exe", "mapf", "mapf.exe"]
        for name in binary_names:
            if os.path.isfile(os.path.join(solvers_dir, name)):
                return True
        return False
    except ImportError:
        return False


@dataclass
class PIBTOnlyController:
    """
    Decentralized baseline controller (PIBT-like behavior at a high level):
      - Ignores global plans entirely.
      - Chooses a greedy move toward its current goal (min Manhattan distance).
      - Uses WaitBasedResolver for robot-robot conflict resolution.

    Note: This is a simplified PIBT-like behavior, not the full PIBT2 algorithm.
    For the full algorithm, use PIBT2Solver from pibt2_wrapper.py.

    To use the official PIBT2 C++ solver instead:
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        solver = PIBT2Solver(mode="one_shot")
    """
    agent_id: int
    resolver: WaitBasedResolver

    def decide_action(self, sim_state: SimStateView, observation: Observation, rng=None) -> StepAction:
        aid = self.agent_id
        agent = sim_state.agents[aid]
        cur = agent.pos

        if agent.goal is None:
            return StepAction.WAIT

        goal = agent.goal

        # Candidate next cells: neighbors + WAIT, filtered by static free and observation blocked
        candidates = [cur] + neighbors(cur)
        feasible = []
        for cell in candidates:
            if not sim_state.env.is_free(cell):
                continue
            if cell in observation.blocked:
                continue
            feasible.append(cell)

        if not feasible:
            return StepAction.WAIT

        # Greedy: minimize Manhattan distance; tie-break deterministically by fixed ordering.
        # Ordering is: WAIT (cur) first, then neighbors() order from grid.neighbors: UP, DOWN, LEFT, RIGHT
        best = min(feasible, key=lambda c: (manhattan(c, goal), 0 if c == cur else 1, c[0], c[1]))

        # Resolve conflicts (priority rules)
        return self.resolver.resolve(
            agent_id=aid,
            desired_cell=best,
            sim_state=sim_state,
            observation=observation,
            rng=rng,
        )
