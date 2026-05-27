from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def test_receding_horizon_handoff(tmp_path: Path) -> None:
    # Create a tiny .map file (empty 5x5) so Environment.load_from_map works
    map_content = "\n".join(
        [
            "type octile",
            "height 5",
            "width 5",
            "map",
            ".....",
            ".....",
            ".....",
            ".....",
            ".....",
            "",
        ]
    )
    mp = tmp_path / "empty5.map"
    mp.write_text(map_content, encoding="utf-8")

    delta = 3
    cfg = SimConfig(
        map_path=str(mp),
        task_stream_path=None,
        seed=1,
        steps=delta + 1,
        num_agents=2,
        num_humans=0,
        fov_radius=4,
        safety_radius=0,
        global_solver="cbs",
        replan_every=delta,
        horizon=5,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
    )

    sim = Simulator(cfg)

    # At step 0, periodic trigger should create a plan
    assert sim.plans() is None
    sim.step_once()
    assert sim.plans() is not None
    assert sim.plans().created_step == 0

    # Advance to step delta (note: sim.step is incremented at end of step_once)
    while sim.step < delta:
        sim.step_once()

    # Next step triggers replan at step=delta
    sim.step_once()
    assert sim.plans() is not None
    assert sim.plans().created_step == delta
