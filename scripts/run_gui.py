# FILE: scripts/run_gui.py
"""
Run Lifelong Human-Aware MAPF with GUI Visualization.

Usage:
    # Basic: use a YAML config
    python scripts/run_gui.py --config configs/random_20x20.yaml

    # Override agent/human counts
    python scripts/run_gui.py --config configs/random_20x20.yaml --agents 15 --humans 5

    # Override solver and planning parameters
    python scripts/run_gui.py --config configs/random_20x20.yaml --solver cbs --horizon 30

    # Custom seed
    python scripts/run_gui.py --config configs/random_20x20.yaml --seed 123
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from typing import Any, Dict

# Set SDL environment variables BEFORE importing pygame (via visualizer)
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

# Force software rendering to avoid GLX/OpenGL issues
if 'SDL_VIDEODRIVER' not in os.environ:
    pass  # Let SDL auto-detect, but we'll use SWSURFACE flag
os.environ.setdefault('SDL_RENDER_DRIVER', 'software')

import yaml

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator
from ha_lmapf.gui.ui_state import UIState


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run Lifelong HA-LMAPF with GUI Visualization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", required=True, help="Path to YAML config")

    # CLI overrides (applied on top of YAML config)
    p.add_argument("--agents", "-a", type=int, default=None,
                   help="Override number of agents")
    p.add_argument("--humans", "-H", type=int, default=None,
                   help="Override number of humans")
    p.add_argument("--seed", type=int, default=None,
                   help="Override random seed")
    p.add_argument("--solver", "-s", type=str, default=None,
                   choices=["cbs", "lacam", "lacam3", "lacam_official", "pibt2"],
                   help="Override MAPF solver")
    p.add_argument("--horizon", type=int, default=None,
                   help="Override planning horizon")
    p.add_argument("--replan-every", type=int, default=None,
                   help="Override replanning interval (Delta)")
    p.add_argument("--fov", type=int, default=None,
                   help="Override field-of-view radius")
    p.add_argument("--safety", type=int, default=None,
                   help="Override safety radius")
    p.add_argument("--human-model", type=str, default=None,
                   choices=["random_walk", "aisle", "adversarial", "mixed"],
                   help="Override human movement model")
    p.add_argument("--steps", type=int, default=None,
                   help="Override max simulation steps")
    return p.parse_args()


def load_config(path: str) -> SimConfig:
    with open(path, "r", encoding="utf-8") as f:
        cfg: Dict[str, Any] = yaml.safe_load(f)
    valid_keys = SimConfig.__annotations__.keys()
    filtered = {k: v for k, v in cfg.items() if k in valid_keys}
    return SimConfig(**filtered)


def main() -> None:
    args = parse_args()

    # 1. Load Config from YAML
    cfg = load_config(args.config)

    # 2. Apply CLI overrides
    overrides = {}
    if args.agents is not None:
        overrides["num_agents"] = args.agents
    if args.humans is not None:
        overrides["num_humans"] = args.humans
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.solver is not None:
        overrides["global_solver"] = args.solver
    if args.horizon is not None:
        overrides["horizon"] = args.horizon
    if args.replan_every is not None:
        overrides["replan_every"] = args.replan_every
    if args.fov is not None:
        overrides["fov_radius"] = args.fov
    if args.safety is not None:
        overrides["safety_radius"] = args.safety
    if args.human_model is not None:
        overrides["human_model"] = args.human_model
    if args.steps is not None:
        overrides["steps"] = args.steps
    if overrides:
        cfg = replace(cfg, **overrides)

    # 3. Print config summary
    print("=" * 60)
    print(" HA-LMAPF LIFELONG SIMULATION")
    print("=" * 60)
    print(f"  Map:            {cfg.map_path}")
    print(f"  Agents:         {cfg.num_agents}")
    print(f"  Humans:         {cfg.num_humans}")
    print(f"  Solver:         {cfg.global_solver}")
    print(f"  Horizon:        {cfg.horizon}")
    print(f"  Replan Every:   {cfg.replan_every}")
    print(f"  FOV Radius:     {cfg.fov_radius}")
    print(f"  Safety Radius:  {cfg.safety_radius}")
    print(f"  Human Model:    {cfg.human_model}")
    print(f"  Seed:           {cfg.seed}")
    print(f"  Max Steps:      {cfg.steps}")
    print("=" * 60)

    sim = Simulator(cfg)

    # 4. Force Initial Plan
    print("Computing initial global plan...")
    sim.maybe_global_replan()
    if sim.plans():
        print(f"Initial plan generated (Horizon: {sim.plans().horizon})")
    else:
        print("WARNING: Initial global plan FAILED. Agents will not move.")

    # Print initial assignment events
    if sim.step_events:
        print(f"── initial setup {'─' * 50}")
        for ev in sim.step_events:
            print(f"  {ev}")

    # 5. Setup GUI
    try:
        import pygame  # noqa: F401
        from ha_lmapf.gui.visualizer import Visualizer
    except ImportError:
        print("CRITICAL: pygame or visualizer not found.")
        sys.exit(1)

    ui_state = UIState(show_plans=True)
    viz = Visualizer(sim, ui_state)

    print("\n" + "=" * 60)
    print(" CONTROLS")
    print("=" * 60)
    print(" SPACE : Pause / Resume")
    print(" N     : Step Once")
    print(" A     : Toggle Auto-Step (continuous)")
    print(" P     : Toggle Global Plans (Blue)")
    print(" L     : Toggle Local Plans (Green)")
    print(" F     : Toggle FOV")
    print(" B     : Toggle Forbidden Zones")
    print(" E     : Toggle Event Log (console)")
    print(" R     : Reset Simulation")
    print(" ESC   : Quit")
    print("=" * 60)
    print("\nSimulation starting PAUSED. Press SPACE or N to begin.\n")

    paused = True

    def _print_step_events() -> None:
        """Print simulator decision events for the current step."""
        if not ui_state.show_events or not sim.step_events:
            return
        print(f"── step {sim.step - 1} {'─' * 50}")
        for ev in sim.step_events:
            print(f"  {ev}")

    while True:
        # Handle Events
        cmd = viz.poll()

        if cmd == "quit":
            break
        elif cmd == "toggle_pause":
            paused = not paused
            print(f"State: {'PAUSED' if paused else 'RUNNING'}")
        elif cmd == "step_once":
            sim.step_once()
            _print_step_events()
        elif cmd == "reset":
            print("Resetting Simulation...")
            sim = Simulator(cfg)
            sim.maybe_global_replan()
            viz.attach(sim)
            paused = True

        # Continuous Run (either via SPACE unpause or Auto-Step mode)
        if not paused or ui_state.auto_step:
            sim.step_once()
            _print_step_events()
            if sim.step >= cfg.steps:
                print("Max steps reached. Pausing.")
                paused = True
                ui_state.auto_step = False

        viz.render()

    # Final statistics
    metrics = sim.metrics.finalize(total_steps=sim.step)
    print("\n" + "=" * 60)
    print(" FINAL STATISTICS")
    print("=" * 60)
    print(f"  Total Steps:            {sim.step}")
    print(f"  Tasks Completed:        {metrics.completed_tasks}")
    print(f"  Task Completion:        {round(metrics.task_completion * 100, 2)}%")
    print(f"  Throughput:             {metrics.throughput:.4f}")
    print(f"  Agent-Agent Collisions: {metrics.collisions_agent_agent}")
    print(f"  Agent-Human Collisions: {metrics.collisions_agent_human}")
    print(f"  Safety Violations:      {metrics.safety_violations}")
    print(f"  Near Misses:            {metrics.near_misses}")
    print(f"  Local Replans:          {metrics.local_replans}")
    print(f"  Mean Planning Time:     {metrics.mean_planning_time_ms:.1f}ms")
    print("=" * 60)

    viz.close()


if __name__ == "__main__":
    main()
