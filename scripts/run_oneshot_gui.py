#!/usr/bin/env python3
"""
Run One-Shot Classical MAPF with GUI Visualization.

This script provides an easy way to run classical MAPF experiments with
real-time visualization of agent movements. Each agent gets one goal at
step 0 and navigates to it. The simulation ends when all agents reach
their goals.

Usage:
    # Default: 10 agents, no humans, random map
    python scripts/run_oneshot_gui.py

    # Custom number of agents
    python scripts/run_oneshot_gui.py --agents 20

    # With humans (human-aware classical MAPF)
    python scripts/run_oneshot_gui.py --agents 10 -H 5

    # Different map
    python scripts/run_oneshot_gui.py --map data/maps/warehouse-10-20-10-2-1.map

    # Use LaCAM solver (faster for large instances)
    python scripts/run_oneshot_gui.py --agents 30 --solver lacam

    # Use official LaCAM3 C++ solver (fastest, requires build)
    python scripts/run_oneshot_gui.py --agents 50 --solver lacam3

    # Use official PIBT2 solver (best for lifelong, requires build)
    python scripts/run_oneshot_gui.py --agents 100 --solver pibt2

GUI Controls:
    SPACE : Pause / Resume simulation
    N     : Step once (when paused)
    A     : Toggle auto-step mode
    P     : Toggle global plan visualization (blue lines)
    L     : Toggle local plan visualization (green lines)
    F     : Toggle field-of-view circles
    B     : Toggle forbidden zones (safety buffers)
    ESC   : Quit
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Set environment variables before pygame import
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

# Force software rendering to avoid GLX/OpenGL issues
# Try these in order: x11 (without GL), wayland, fbcon, directfb
if 'SDL_VIDEODRIVER' not in os.environ:
    # Don't override if user has set it
    pass  # Let SDL auto-detect, but we'll use SWSURFACE flag

# Disable hardware acceleration which can cause GLX errors
os.environ.setdefault('SDL_RENDER_DRIVER', 'software')

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run One-Shot Classical MAPF with GUI Visualization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--agents", "-a", type=int, default=10,
                        help="Number of agents (default: 10)")
    parser.add_argument("--humans", "-H", type=int, default=0,
                        help="Number of humans (default: 0 for classical MAPF)")
    parser.add_argument("--map", "-m", type=str, default="data/maps/random-32-32-20.map",
                        help="Path to map file (default: random-32-32-20)")
    parser.add_argument("--solver", "-s", type=str, default="cbs",
                        choices=["cbs", "lacam", "lacam3", "lacam_official", "pibt2"],
                        help="MAPF solver: cbs (optimal), lacam (Python), "
                             "lacam3/lacam_official/pibt2 (official C++)")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--steps", type=int, default=500,
                        help="Maximum simulation steps (default: 500)")
    parser.add_argument("--replan_every", type=int, default=25,
                        help="Global Replanning interval (default: 25)")
    parser.add_argument("--horizon", type=int, default=50,
                        help="Global planning horizon (default: 50)")
    return parser.parse_args()


def create_oneshot_config(args: argparse.Namespace) -> SimConfig:
    """Create a SimConfig for one-shot MAPF."""
    return SimConfig(
        map_path=args.map,
        steps=args.steps,
        num_agents=args.agents,
        num_humans=args.humans,
        fov_radius=5,
        safety_radius=1,
        global_solver=args.solver,
        replan_every=args.replan_every,
        horizon=args.horizon,
        communication_mode="token",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="one_shot",  # Key: one-shot mode
        task_allocator="congestion_avoidance",
        seed=args.seed,
    )


def main() -> None:
    args = parse_args()

    # Create config
    cfg = create_oneshot_config(args)

    print("=" * 60)
    print(" ONE-SHOT CLASSICAL MAPF VISUALIZATION")
    print("=" * 60)
    print(f"  Map:      {cfg.map_path}")
    print(f"  Agents:   {cfg.num_agents}")
    print(f"  Humans:   {cfg.num_humans}")
    print(f"  Solver:   {cfg.global_solver}")
    print(f"  Seed:     {cfg.seed}")
    print("=" * 60)

    # Initialize simulation
    print("\nInitializing simulation...")
    sim = Simulator(cfg)

    # Generate initial plan
    # Must release tasks first so allocator can assign them
    print("Computing initial MAPF plan...")
    sim.maybe_global_replan()

    if sim.plans():
        print(f"Plan generated successfully (Horizon: {sim.plans().horizon})")
        # Verify goals were assigned
        agents_with_goals = sum(1 for a in sim.agents.values() if a.goal is not None)
        print(f"Agents with assigned goals: {agents_with_goals}/{cfg.num_agents}")
    else:
        print("WARNING: Initial plan FAILED. Agents will not move.")

    # Try to import GUI
    try:
        import pygame
        from ha_lmapf.gui.visualizer import Visualizer
        from ha_lmapf.gui.ui_state import UIState
    except ImportError as e:
        print(f"\nERROR: Could not import GUI components: {e}")
        print("Make sure pygame is installed: pip install pygame")
        sys.exit(1)

    # Setup GUI
    ui_state = UIState(show_plans=True)
    viz = Visualizer(sim, ui_state)

    print("\n" + "=" * 60)
    print(" GUI CONTROLS")
    print("=" * 60)
    print(" SPACE : Pause / Resume simulation")
    print(" N     : Step once (when paused)")
    print(" A     : Toggle auto-step mode")
    print(" P     : Toggle global plans (blue)")
    print(" L     : Toggle local plans (green)")
    print(" F     : Toggle field-of-view")
    print(" B     : Toggle forbidden zones")
    print(" ESC   : Quit")
    print("=" * 60)
    print("\nSimulation starting PAUSED. Press SPACE to start.")

    paused = True
    completed = False

    while True:
        # Handle events
        cmd = viz.poll()

        if cmd == "quit":
            break
        elif cmd == "toggle_pause":
            paused = not paused
            state = "PAUSED" if paused else "RUNNING"
            print(f"State: {state}")
        elif cmd == "step_once":
            if not completed:
                print(f"Step {sim.step} -> {sim.step + 1}")
                sim.step_once()
        elif cmd == "reset":
            print("Resetting simulation...")
            sim = Simulator(cfg)
            sim.maybe_global_replan()
            viz.attach(sim)
            completed = False
            paused = True

        # Run simulation
        if not paused or ui_state.auto_step:
            if not completed:
                sim.step_once()

                # Check if all agents reached goals (one-shot completion)
                all_done = all(a.goal is None for a in sim.agents.values())
                if all_done:
                    print(f"\n*** ALL AGENTS REACHED GOALS at step {sim.step} ***")
                    completed = True
                    paused = True
                    ui_state.auto_step = False

                # Check max steps
                if sim.step >= cfg.steps:
                    print(f"\nMax steps ({cfg.steps}) reached.")
                    remaining = sum(1 for a in sim.agents.values() if a.goal is not None)
                    print(f"Agents still navigating: {remaining}")
                    completed = True
                    paused = True
                    ui_state.auto_step = False

        viz.render()

    # Print final stats
    metrics = sim.metrics.finalize(total_steps=sim.step)
    print("\n" + "=" * 60)
    print(" FINAL STATISTICS")
    print("=" * 60)
    print(f"  Total Steps:           {sim.step}")
    print(f"  Agents Completed:      {metrics.completed_tasks}/{cfg.num_agents}")
    print(f"  Throughput:            {metrics.throughput:.4f}")
    print(f"  Agent-Agent Collisions: {metrics.collisions_agent_agent}")
    print(f"  Agent-Human Collisions: {metrics.collisions_agent_human}")
    print(f"  Safety Violations:     {metrics.safety_violations}")
    print(f"  Mean Planning Time:    {metrics.mean_planning_time_ms:.1f}ms")
    print("=" * 60)

    viz.close()


if __name__ == "__main__":
    main()
