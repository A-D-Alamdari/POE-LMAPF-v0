"""
Human Simulation and Safety Modules.

This package contains:
  1. Motion Models: How humans move (Random Walk with Inertia, Aisle Following,
     Adversarial, Mixed Population, Replay).
  2. Prediction: Heuristics to guess future human positions.
  3. Safety: Utilities to calculate forbidden zones (inflation) and proximity costs.
"""

from .models import (
    HumanModel,
    RandomWalkHumanModel,
    AisleFollowerHumanModel,
    AdversarialHumanModel,
    MixedPopulationHumanModel,
    ReplayHumanModel,
)

from .prediction import (
    MyopicPredictor,
)

from .safety import (
    inflate_cells,
    proximity_penalty,
    forbidden_mask,
)

__all__ = [
    "HumanModel",
    "RandomWalkHumanModel",
    "AisleFollowerHumanModel",
    "AdversarialHumanModel",
    "MixedPopulationHumanModel",
    "ReplayHumanModel",
    "MyopicPredictor",
    "inflate_cells",
    "proximity_penalty",
    "forbidden_mask",
]
