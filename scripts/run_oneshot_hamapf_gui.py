#!/usr/bin/env python3
"""
Run Human-Aware One-Shot Classical MAPF with GUI Visualization.

This script demonstrates the proposed two-tier human-aware approach for
classical MAPF scenarios. Each agent gets one goal and must navigate to it
while safely avoiding dynamic human obstacles.

Key Features:
- One-shot MAPF mode (each agent has one goal)
- Human-aware planning with safety buffers
- Configurable field-of-view for partial observability
- Multiple human behavior models
- Real-time visualization of agent movements and human avoidance

Usage:
    # Basic human-aware MAPF with 10 agents and 5 humans
    python scripts/run_oneshot_hamapf_gui.py

    # More agents and humans
    python scripts/run_oneshot_hamapf_gui.py --agents 20 --humans 10

    # Custom field of view and safety radius
    python scripts/run_oneshot_hamapf_gui.py --fov 3 --safety 2

    # Adversarial humans (try to block agents)
    python scripts/run_oneshot_hamapf_gui.py --human-model adversarial

    # Different map
    python scripts/run_oneshot_hamapf_gui.py --map data/maps/warehouse-10-20-10-2-1.map

    # Use LaCAM solver (faster for more agents)
    python scripts/run_oneshot_hamapf_gui.py --agents 30 --solver lacam

    # Use official LaCAM3 C++ solver (fastest, requires build)
    python scripts/run_oneshot_hamapf_gui.py --agents 50 --solver lacam3

    # Use official PIBT2 solver (best for lifelong, requires build)
    python scripts/run_oneshot_hamapf_gui.py --agents 100 --solver pibt2

    # Hard safety mode (agents NEVER enter human safety zones)
    python scripts/run_oneshot_hamapf_gui.py --hard-safety

    # Soft safety mode (agents avoid but can enter if necessary)
    python scripts/run_oneshot_hamapf_gui.py --no-hard-safety

GUI Controls:
    SPACE : Pause / Resume simulation
    N     : Step once (when paused)
    A     : Toggle auto-step mode
    P     : Toggle global plan visualization (blue lines)
    L     : Toggle local plan visualization (green lines)
    F     : Toggle field-of-view circles
    B     : Toggle forbidden zones (safety buffers around humans)
    ESC   : Quit

Visual Elements:
    Blue circles    : Agents
    Red circles     : Humans
    Blue lines      : Global planned paths
    Green lines     : Local detour paths (around humans)
    Shaded areas    : Agent field of view
    Red zones       : Safety buffers around humans
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Set environment variables before pygame import
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
os.environ.setdefault('SDL_RENDER_DRIVER', 'software')

project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Human-Aware One-Shot MAPF with GUI Visualization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Basic configuration
    parser.add_argument("--agents", "-a", type=int, default=10,
                        help="Number of agents (default: 10)")
    parser.add_argument("--humans", "-H", type=int, default=5,
                        help="Number of humans (default: 5)")
    parser.add_argument("--map", "-m", type=str, default="data/maps/random-32-32-20.map",
                        help="Path to map file (default: random-32-32-20)")

    # Perception and safety
    parser.add_argument("--fov", type=int, default=5,
                        help="Field of view radius for agents (default: 5)")
    parser.add_argument("--safety", type=int, default=1,
                        help="Safety radius around humans (default: 1)")
    parser.add_argument("--hard-safety", action="store_true", default=True,
                        help="Hard safety: agents NEVER enter safety zones (default)")
    parser.add_argument("--no-hard-safety", action="store_false", dest="hard_safety",
                        help="Soft safety: agents avoid but can enter if necessary")

    # Solver configuration
    parser.add_argument("--solver", "-s", type=str, default="lacam",
                        choices=["cbs", "lacam", "lacam3", "lacam_official", "pibt2"],
                        help="MAPF solver: cbs (optimal), lacam (Python), "
                             "lacam3/lacam_official/pibt2 (official C++)")
    parser.add_argument("--horizon", type=int, default=None,
                        help="Planning horizon (default: auto-scaled based on agents)")

    # Human behavior
    parser.add_argument("--human-model", type=str, default="random_walk",
                        choices=["random_walk", "aisle", "adversarial", "mixed"],
                        help="Human movement model (default: random_walk)")

    # Conflict resolution (paper §4.3).  Canonical values are "token_based"
    # and "wait_based"; legacy "token" and "priority" continue to be accepted
    # by the simulator's factory alias for backward compatibility with
    # archived configs.
    parser.add_argument("--comm-mode", type=str, default="token_based",
                        choices=["token_based", "wait_based", "token", "priority"],
                        help="Conflict resolution mode (default: token_based; "
                             "legacy 'token'/'priority' accepted)")

    # Reproducibility
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed (default: 42)")
    parser.add_argument("--steps", type=int, default=500,
                        help="Maximum simulation steps (default: 500)")

    return parser.parse_args()


def create_config(args: argparse.Namespace) -> SimConfig:
    """Create a SimConfig for human-aware one-shot MAPF."""

    # Auto-scale horizon based on number of agents if not specified
    horizon = args.horizon
    if horizon is None:
        horizon = max(200, args.agents * 10)

    # Set human model parameters based on model type
    human_model_params = {}
    if args.human_model == "random_walk":
        human_model_params = {"beta_go": 2.0, "beta_wait": -1.0, "beta_turn": 0.0}
    elif args.human_model == "aisle":
        human_model_params = {"alpha": 1.0, "beta": 1.5}
    elif args.human_model == "adversarial":
        human_model_params = {"gamma": 2.0, "lambda": 0.5}
    elif args.human_model == "mixed":
        human_model_params = {
            "weights": {"random_walk": 0.4, "aisle": 0.4, "adversarial": 0.2},
            "sub_params": {
                "random_walk": {"beta_go": 2.0, "beta_wait": -1.0, "beta_turn": 0.0},
                "aisle": {"alpha": 1.0, "beta": 1.5},
                "adversarial": {"gamma": 2.0, "lambda": 0.5},
            }
        }

    return SimConfig(
        map_path=args.map,
        steps=args.steps,
        num_agents=args.agents,
        num_humans=args.humans,
        fov_radius=args.fov,
        safety_radius=args.safety,
        global_solver=args.solver,
        replan_every=1,  # Not used in one-shot mode
        horizon=horizon,
        communication_mode=args.comm_mode,
        local_planner="astar",
        human_model=args.human_model,
        human_model_params=human_model_params,
        hard_safety=args.hard_safety,
        mode="one_shot",  # Key: one-shot mode
        task_allocator="congestion_avoidance",
        seed=args.seed,
    )


def main() -> None:
    args = parse_args()

    # Create config
    cfg = create_config(args)

    print("=" * 70)
    print(" HUMAN-AWARE ONE-SHOT CLASSICAL MAPF VISUALIZATION")
    print("=" * 70)
    print(f"  Map:           {cfg.map_path}")
    print(f"  Agents:        {cfg.num_agents}")
    print(f"  Humans:        {cfg.num_humans}")
    print(f"  Solver:        {cfg.global_solver}")
    print(f"  FOV Radius:    {cfg.fov_radius}")
    print(f"  Safety Radius: {cfg.safety_radius}")
    print(f"  Hard Safety:   {cfg.hard_safety}")
    print(f"  Human Model:   {cfg.human_model}")
    print(f"  Comm Mode:     {cfg.communication_mode}")
    print(f"  Seed:          {cfg.seed}")
    print("=" * 70)

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
    ui_state = UIState(show_plans=True, show_fov=True, show_forbidden=True)
    viz = Visualizer(sim, ui_state)

    print("\n" + "=" * 70)
    print(" GUI CONTROLS")
    print("=" * 70)
    print(" SPACE : Pause / Resume simulation")
    print(" N     : Step once (when paused)")
    print(" A     : Toggle auto-step mode")
    print(" P     : Toggle global plans (blue lines)")
    print(" L     : Toggle local plans (green lines - human avoidance)")
    print(" F     : Toggle field-of-view (partial observability)")
    print(" B     : Toggle forbidden zones (safety buffers)")
    print(" ESC   : Quit")
    print("=" * 70)
    print("\nSimulation starting PAUSED. Press SPACE to start.")
    print("Watch how agents navigate around humans using the two-tier approach!")

    paused = True
    completed = False

    # Debug: track replans
    prev_local_replans = 0
    prev_global_replans = 0

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
                # Debug: print when global replanning is triggered (single step mode)
                current_global_replans = sim.metrics._global_replans
                if current_global_replans > prev_global_replans:
                    print(f"[DEBUG] Step {sim.step}: GLOBAL replanning triggered! "
                          f"(total: {current_global_replans})")
                    prev_global_replans = current_global_replans
                # Debug: print when local replanning is triggered (single step mode)
                current_local_replans = sim.metrics._local_replans
                if current_local_replans > prev_local_replans:
                    new_replans = current_local_replans - prev_local_replans
                    print(f"[DEBUG] Step {sim.step}: Local replanning triggered! "
                          f"({new_replans} replan(s), total: {current_local_replans})")
                    prev_local_replans = current_local_replans
        elif cmd == "reset":
            print("Resetting simulation...")
            sim = Simulator(cfg)
            sim.maybe_global_replan()
            viz.attach(sim)
            completed = False
            paused = True
            prev_local_replans = 0  # Reset debug counters
            prev_global_replans = 0

        # Run simulation
        if not paused or ui_state.auto_step:
            if not completed:
                sim.step_once()

                # Debug: print when global replanning is triggered
                current_global_replans = sim.metrics._global_replans
                if current_global_replans > prev_global_replans:
                    print(f"[DEBUG] Step {sim.step}: GLOBAL replanning triggered! "
                          f"(total: {current_global_replans})")
                    prev_global_replans = current_global_replans

                # Debug: print when local replanning is triggered
                current_local_replans = sim.metrics._local_replans
                if current_local_replans > prev_local_replans:
                    new_replans = current_local_replans - prev_local_replans
                    print(f"[DEBUG] Step {sim.step}: Local replanning triggered! "
                          f"({new_replans} replan(s), total: {current_local_replans})")
                    prev_local_replans = current_local_replans

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
    print("\n" + "=" * 70)
    print(" FINAL STATISTICS")
    print("=" * 70)
    print(f"  Total Steps:             {sim.step}")
    print(f"  Agents Completed:        {metrics.completed_tasks}/{cfg.num_agents}")
    print(f"  Task Completion Percentage:      {round(metrics.task_completion * 100, 2)}%")
    print(f"  Throughput:              {metrics.throughput:.4f}")
    print(f"  Agent-Agent Collisions:  {metrics.collisions_agent_agent}")
    print(f"  Agent-Human Collisions:  {metrics.collisions_agent_human}")
    print(f"  Safety Violations:       {metrics.safety_violations}")
    print(f"  Near Misses:             {metrics.near_misses}")
    print(f"  Mean Planning Time:      {metrics.mean_planning_time_ms:.1f}ms")
    print(f"  Local Replans:           {metrics.local_replans}")
    print("=" * 70)

    # Interpretation
    if metrics.collisions_agent_human == 0:
        print("\nAgent-Human Safety: PERFECT - No collisions with humans!")
    else:
        print(f"\nAgent-Human Safety: {metrics.collisions_agent_human} collisions detected")

    if metrics.safety_violations > 0:
        print(f"Safety Zone Violations: {metrics.safety_violations} "
              "(agents entered human safety buffers)")
    else:
        print("Safety Zone: RESPECTED - Agents maintained safe distance from humans")

    viz.close()


if __name__ == "__main__":
    main()
