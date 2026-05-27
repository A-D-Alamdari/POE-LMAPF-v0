from __future__ import annotations

import os
from pathlib import Path

import pytest

from ha_lmapf.io.movingai_map import load_movingai_map
from ha_lmapf.simulation.environment import Environment


# Paper Section 5.2: the three evaluation maps.  Each entry is
# (filename stem, expected (width, height)).  ``random-64-64-10`` is the
# 10%-obstacle random grid; the warehouse maps follow the
# ``warehouse-<aisle>-<shelf>-<rows>-<cols>-<id>`` MovingAI naming.
PAPER_MAPS = [
    ("random-64-64-10",        (64, 64)),
    ("warehouse-10-20-10-2-1", (161, 63)),
    ("warehouse-10-20-10-2-2", (170, 84)),
]

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_MAPS_DIR = REPO_ROOT / "data" / "maps"


@pytest.mark.parametrize("stem, expected_wh", PAPER_MAPS)
def test_paper_map_loads_with_expected_dimensions(stem: str, expected_wh) -> None:
    """The three paper maps must load via ``Environment.load_from_map``,
    have non-zero free cells, and match the documented dimensions."""
    map_path = DATA_MAPS_DIR / f"{stem}.map"
    assert map_path.exists(), (
        f"Paper map {stem}.map missing from data/maps/. "
        f"See data/maps/README.md and scripts/download_maps.sh."
    )

    env = Environment.load_from_map(str(map_path))
    expected_width, expected_height = expected_wh
    assert env.width == expected_width, f"{stem}: width {env.width} != {expected_width}"
    assert env.height == expected_height, f"{stem}: height {env.height} != {expected_height}"
    assert len(env._free_cells) > 0, f"{stem} has zero free cells"


def test_map_loading_tmp(tmp_path: Path) -> None:
    # 4x3 map: blocked '@' and 'T', free '.' and 'G' and 'S'
    content = "\n".join(
        [
            "type octile",
            "height 3",
            "width 4",
            "map",
            ".@..",
            ".T.G",
            "S...",
            "",
        ]
    )
    p = tmp_path / "toy.map"
    p.write_text(content, encoding="utf-8")

    md = load_movingai_map(str(p))
    assert md.width == 4
    assert md.height == 3

    # blocked at (0,1) '@' and (1,1) 'T'
    assert (0, 1) in md.blocked
    assert (1, 1) in md.blocked
    assert len(md.blocked) == 2
