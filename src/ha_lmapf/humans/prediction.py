"""
Human Motion Prediction.

This module provides algorithms to forecast the future positions of dynamic obstacles.
These predictions are consumed by the Global Planner (Tier-1) to reserve space
in the time-expanded graph, preventing the planner from routing agents through
areas likely to be occupied by humans.

Strategies:
  - Myopic (Current): Assumes humans block their immediate vicinity for the entire
    horizon. This is a "Safety Shield" approach—highly safe but potentially conservative.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from ha_lmapf.core.grid import neighbors
from ha_lmapf.core.interfaces import HumanPredictor
from ha_lmapf.core.types import HumanState

Cell = Tuple[int, int]


@dataclass
class MyopicPredictor(HumanPredictor):
    """
    A conservative, deterministic predictor for human occupancy.

    Instead of simulating complex future trajectories (which are error-prone),
    this model assumes that the space currently occupied by a human (and optionally
    their immediate neighbors) remains "unsafe" for the entire planning horizon.

    This effectively turns moving humans into static obstacles for the duration
    of the global planning window (e.g., 5-10 seconds). This encourages the
    global planner to find routes that give humans a wide berth.

    Attributes:
        include_neighbors: If True, the predicted unsafe set includes the human's
                           current cell PLUS all 4 adjacent cells. If False, only
                           the current cell is marked.
    """

    include_neighbors: bool = True

    def predict(
            self,
            humans: Dict[int, HumanState],
            horizon: int,
            rng=None,
    ) -> List[Set[Cell]]:
        """
        Generate a forecast of unsafe cells for the given time horizon.

        Args:
            humans: Dictionary of current human states.
            horizon: The number of time steps to predict into the future.
            rng: Random number generator (unused here, kept for interface consistency).

        Returns:
            A list of sets, where list[t] contains the (row, col) coordinates
            predicted to be blocked at time step `now + t`.
        """
        horizon = int(max(0, horizon))

        # Initialize empty sets for each future time step
        # Note: We use built-in set(), not typing.Set
        future: List[Set[Cell]] = [set() for _ in range(horizon)]

        # Determine the "Static Shield" for each human
        for hid in sorted(humans.keys()):
            h = humans[hid]
            cur = h.pos

            # For a myopic predictor, keep same conservative set for all future steps
            # Base occupancy: where the human is right now
            occ: Set[Cell] = {cur}

            # Extended occupancy: where the human *could* step next
            if self.include_neighbors:
                # Note: Since we don't have access to the 'env' object here to check for walls,
                # we blindly add all neighbors. This is safe: blocking a wall is redundant
                # but does not harm the validity of the plan (agents can't go there anyway).
                for nb in neighbors(cur):
                    occ.add(nb)

            # Project this occupancy into the future
            # "Myopic" assumption: The area remains risky for the whole duration.
            for t in range(horizon):
                future[t].update(occ)

        return future
