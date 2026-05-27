"""
Baseline implementations for comparative evaluation.

Modules:
  - global_only_replan: Tier-1 guidance only, simply waits for humans (No Tier-2 A*).
  - pibt_only: Greedy local behavior + Conflict Resolution (No Tier-1).
  - rhcr_like: Standard Rolling Horizon Collision Resolution (Periodic, Centralized).
  - whca_star: Windowed Hierarchical Cooperative A* (Prioritized Planning).
  - ignore_humans: Ablation utility to simulate "human-blind" agents.
"""

from .global_only_replan import GlobalOnlyController, make_global_only_controllers
from .pibt_only import PIBTOnlyController
from .rhcr_like import RHCRPlanner
from .whca_star import WHCAStarPlanner
from .ignore_humans import mask_out_humans
from .pibt2_fr import (
    make_pibt2_fr_config,
    make_no_buffer_config,
    make_rhcr_blind_config,
    make_lacam_blind_config,
)

__all__ = [
    "GlobalOnlyController",
    "make_global_only_controllers",
    "PIBTOnlyController",
    "RHCRPlanner",
    "WHCAStarPlanner",
    "mask_out_humans",
    "make_pibt2_fr_config",
    "make_no_buffer_config",
    "make_rhcr_blind_config",
    "make_lacam_blind_config",
]
