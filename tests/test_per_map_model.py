"""
Per-map exogenous-agent model selection tests (paper Section 5.1).

When ``SimConfig.map_to_human_model`` is set, the simulator looks up the
map's filename stem and overrides ``config.human_model`` with the mapped
value before instantiating the motion model.  This test pins three maps
from the paper:

  * ``random-64-64-10``      → ``random_walk``  (RandomWalkHumanModel)
  * ``warehouse-10-20-10-2-1`` → ``aisle``       (AisleFollowerHumanModel)
  * ``warehouse-10-20-10-2-2`` → ``aisle``       (AisleFollowerHumanModel)
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.humans.models import (
    AisleFollowerHumanModel,
    RandomWalkHumanModel,
)
from ha_lmapf.io import default_map_to_human_model
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def random_64_64_map(tmp_path):
    """Real-content stand-in for ``random-64-64-10.map``.  We only need
    the filename stem to match what the simulator looks up; the body can
    be a smaller open grid for speed."""
    p = tmp_path / "random-64-64-10.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return str(p)


@pytest.fixture
def warehouse_1_map(tmp_path):
    p = tmp_path / "warehouse-10-20-10-2-1.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return str(p)


@pytest.fixture
def warehouse_2_map(tmp_path):
    p = tmp_path / "warehouse-10-20-10-2-2.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return str(p)


def _make_sim(map_path: str, mapping) -> Simulator:
    cfg = SimConfig(
        map_path=map_path,
        seed=0,
        steps=1,
        num_agents=1,
        num_humans=1,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=10,
        horizon=20,
        # Set ``human_model`` to a value that should be OVERRIDDEN by the
        # per-map mapping for the warehouse cases.  This makes the
        # override observable.
        human_model="adversarial",
        map_to_human_model=mapping,
        mode="lifelong",
    )
    return Simulator(cfg)


def test_default_mapping_contains_paper_maps():
    mapping = default_map_to_human_model()
    assert mapping["random-64-64-10"] == "random_walk"
    assert mapping["random-32-32-20"] == "random_walk"
    assert mapping["warehouse-10-20-10-2-1"] == "aisle"
    assert mapping["warehouse-10-20-10-2-2"] == "aisle"


def test_random_map_selects_random_walk_model(random_64_64_map):
    sim = _make_sim(random_64_64_map, default_map_to_human_model())
    assert isinstance(sim.human_model, RandomWalkHumanModel)
    # The override should have rewritten the resolved config too.
    assert sim.config.human_model == "random_walk"


def test_warehouse_1_selects_aisle_follower_model(warehouse_1_map):
    sim = _make_sim(warehouse_1_map, default_map_to_human_model())
    assert isinstance(sim.human_model, AisleFollowerHumanModel)
    assert sim.config.human_model == "aisle"


def test_warehouse_2_selects_aisle_follower_model(warehouse_2_map):
    sim = _make_sim(warehouse_2_map, default_map_to_human_model())
    assert isinstance(sim.human_model, AisleFollowerHumanModel)
    assert sim.config.human_model == "aisle"


def test_unmapped_map_keeps_explicit_human_model(tmp_path):
    """If the map's stem isn't in the mapping, ``human_model`` is left
    intact and the simulator instantiates the model the user requested.
    """
    p = tmp_path / "some_other_map.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    sim = _make_sim(str(p), default_map_to_human_model())
    # Explicit "adversarial" config, not in mapping → stays adversarial.
    assert sim.config.human_model == "adversarial"


def test_no_mapping_means_no_override(tmp_path):
    """``map_to_human_model=None`` is the legacy path — no override."""
    p = tmp_path / "warehouse-10-20-10-2-1.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    cfg = SimConfig(
        map_path=str(p),
        seed=0,
        steps=1,
        num_agents=1,
        num_humans=1,
        global_solver="cbs",
        human_model="adversarial",
        map_to_human_model=None,  # explicit
    )
    sim = Simulator(cfg)
    assert sim.config.human_model == "adversarial"
