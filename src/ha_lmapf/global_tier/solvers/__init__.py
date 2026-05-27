# FILE: src/ha_lmapf/global_tier/solvers/__init__.py
"""
MAPF Solvers Package.

This package contains implementations of multi-agent pathfinding algorithms
adapted for the Rolling Horizon context.

Shared Utilities:
  - common: Shared utilities (A*, Constraints, Conflict Detection)

Official C++ Solver Wrappers (from Keisuke Okumura / Jiaoyang Li):
  - lacam3_wrapper: LaCAM3 - Latest LaCAM version (Kei18/lacam3)
  - lacam_official_wrapper: Original LaCAM (Kei18/lacam)
  - pibt2_wrapper: PIBT2 - Priority Inheritance with Backtracking (Kei18/pibt2)
  - rhcr_wrapper: RHCR - Rolling-Horizon Collision Resolution (Jiaoyang-Li/RHCR)
  - cbsh2_wrapper: CBSH2-RTC - CBS with Heuristics (Jiaoyang-Li/CBSH2-RTC)
  - eecbs_wrapper: EECBS - Explicit Estimation CBS (Jiaoyang-Li/EECBS)
  - pbs_wrapper: PBS - Priority-Based Search (Jiaoyang-Li/PBS)
  - lns2_wrapper: MAPF-LNS2 - Large Neighborhood Search (Jiaoyang-Li/MAPF-LNS2)

To use official C++ solvers, clone and build from their GitHub repositories.
See README_SOLVERS.md for detailed installation instructions.
"""

from .lacam3_wrapper import LaCAM3Solver
from .lacam_official_wrapper import LaCAMOfficialSolver
from .lacam_official_real_time import RealTimeLaCAMSolver
from .pibt2_wrapper import PIBT2Solver
from .rhcr_wrapper import RHCRSolver
from .cbsh2_wrapper import CBSH2Solver
from .eecbs_wrapper import EECBSSolver
from .pbs_wrapper import PBSSolver
from .lns2_wrapper import LNS2Solver
from .common import (
    ConstraintSet,
    VertexConstraint,
    EdgeConstraint,
    Conflict,
    detect_first_conflict,
    a_star_constrained,
)

__all__ = [
    # C++ solver wrappers (Kei18)
    "LaCAM3Solver",
    "LaCAMOfficialSolver",
    "RealTimeLaCAMSolver",
    "PIBT2Solver",
    # C++ solver wrappers (Jiaoyang-Li)
    "RHCRSolver",
    "CBSH2Solver",
    "EECBSSolver",
    "PBSSolver",
    "LNS2Solver",
    # Utilities
    "ConstraintSet",
    "VertexConstraint",
    "EdgeConstraint",
    "Conflict",
    "detect_first_conflict",
    "a_star_constrained",
]
