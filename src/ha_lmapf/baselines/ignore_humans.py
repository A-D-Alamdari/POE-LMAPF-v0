from __future__ import annotations

from typing import Set, Tuple

from ha_lmapf.core.types import Observation

Cell = Tuple[int, int]


def mask_out_humans(observation: Observation) -> Observation:
    """
    Ablation helper: ignore humans entirely.

    Returns a modified Observation where:
      - visible_humans is empty
      - blocked does NOT include cells occupied by humans
      - visible_agents is unchanged

    This simulates planners/controllers that are unaware of humans.
    Deterministic and dependency-free.
    """
    # Remove human-occupied cells from blocked set
    human_cells: Set[Cell] = {h.pos for h in observation.visible_humans.values()}
    new_blocked = set(observation.blocked) - human_cells

    return Observation(
        visible_humans={},
        visible_agents=dict(observation.visible_agents),
        blocked=new_blocked,
    )
