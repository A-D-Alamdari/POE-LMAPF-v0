from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from ha_lmapf.core.types import Task
from ha_lmapf.io.task_stream import save_task_stream
from ha_lmapf.simulation.environment import Environment


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate reproducible lifelong MAPF task streams.")
    p.add_argument("--map", required=True, help="Path to MovingAI .map file")
    p.add_argument("--num_tasks", type=int, required=True, help="Number of tasks to generate")
    p.add_argument("--seed", type=int, required=True, help="RNG seed")
    p.add_argument("--out", required=True, help="Output JSON path")
    p.add_argument("--release_rate", type=int, default=10, help="Release a new task every k steps")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(int(args.seed))

    env = Environment.load_from_map(args.map)

    num_tasks = int(args.num_tasks)
    release_rate = max(1, int(args.release_rate))

    tasks = []
    for k in range(num_tasks):
        # Generate distinct start (pickup) and goal (delivery) locations
        start = env.sample_free_cell(rng, exclude=set())
        goal = env.sample_free_cell(rng, exclude={start})  # Ensure goal != start
        tasks.append(Task(
            task_id=f"t{k:07d}",
            start=start,
            goal=goal,
            release_step=k * release_rate
        ))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    save_task_stream(tasks, str(out_path))
    print(f"Wrote {len(tasks)} pickup-delivery tasks to {out_path}")


if __name__ == "__main__":
    main()
