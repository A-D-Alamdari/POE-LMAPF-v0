"""Tests for one-shot (classical) MAPF mode."""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def _write_small_map(tmp_path: Path) -> str:
    """Create a small 5x5 open map."""
    map_file = tmp_path / "test_5x5.map"
    lines = [
        "type octile",
        "height 5",
        "width 5",
        "map",
        ".....",
        ".....",
        ".....",
        ".....",
        ".....",
    ]
    map_file.write_text("\n".join(lines) + "\n")
    return str(map_file)


def test_one_shot_generates_one_task_per_agent(tmp_path: Path):
    map_path = _write_small_map(tmp_path)
    config = SimConfig(
        map_path=map_path,
        mode="one_shot",
        num_agents=3,
        num_humans=0,
        steps=200,
        global_solver="cbs",
        horizon=50,
        seed=7,
    )
    sim = Simulator(config)

    # One task per agent, all released at step 0
    assert len(sim.tasks) == 3
    for t in sim.tasks:
        assert t.release_step == 0
        assert t.start == (-1, -1)  # direct-to-goal (no pickup)


def test_one_shot_plans_once(tmp_path: Path):
    map_path = _write_small_map(tmp_path)
    config = SimConfig(
        map_path=map_path,
        mode="one_shot",
        num_agents=2,
        num_humans=0,
        steps=100,
        global_solver="cbs",
        horizon=50,
        seed=42,
    )
    sim = Simulator(config)

    # Before any steps, no plan yet
    assert sim.plans() is None

    sim.step_once()

    # After first step, plan should exist
    plan = sim.plans()
    assert plan is not None

    # Run more steps — plan should not change (one-shot, no replanning)
    sim.step_once()
    sim.step_once()
    assert sim.plans() is plan  # same object, not replanned


def test_one_shot_terminates_early(tmp_path: Path):
    map_path = _write_small_map(tmp_path)
    config = SimConfig(
        map_path=map_path,
        mode="one_shot",
        num_agents=2,
        num_humans=0,
        steps=500,  # large limit
        global_solver="cbs",
        horizon=50,
        seed=42,
    )
    sim = Simulator(config)
    metrics = sim.run()

    # Should terminate well before 500 steps on a 5x5 grid with 2 agents
    assert metrics.steps < 500
    assert metrics.completed_tasks == 2


def test_one_shot_with_allocator_options(tmp_path: Path):
    map_path = _write_small_map(tmp_path)

    for alloc in ["greedy", "hungarian", "auction"]:
        config = SimConfig(
            map_path=map_path,
            mode="one_shot",
            num_agents=2,
            num_humans=0,
            steps=100,
            global_solver="cbs",
            horizon=50,
            seed=42,
            task_allocator=alloc,
        )
        sim = Simulator(config)
        metrics = sim.run()
        assert metrics.completed_tasks == 2, f"Allocator '{alloc}' failed to complete tasks"
