# FILE: scripts/run_experiments.py
"""
Headless Experiment Runner.

Executes batch simulations for Human-Aware Lifelong MAPF.
Loads a config, overrides seeds, runs the simulator, and saves metrics.

Usage:
    python scripts/run_experiments.py --config configs/warehouse_small.yaml --seeds 1 2 3 --out logs/experiment_1
"""
import argparse
import copy
import csv
import time
import yaml
from pathlib import Path
from typing import Any, Dict

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def load_config(path: str) -> SimConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    # Filter dict to only known keys to allow extra comments in YAML
    known_keys = SimConfig.__annotations__.keys()
    filtered: Dict[str, Any] = {}
    for k, v in data.items():
        if k in known_keys:
            filtered[k] = v

    return SimConfig(**filtered)


def run_single_seed(base_config: SimConfig, seed: int, output_dir: Path) -> Any:
    # 1. Create a fresh copy of config to avoid mutating the original
    config = copy.deepcopy(base_config)
    config.seed = seed

    print(f"--> Running Seed {seed} | Map: {Path(config.map_path).name} | Agents: {config.num_agents}")

    # 2. Initialize Simulator
    start_time = time.time()
    sim = Simulator(config)

    # 3. Run
    metrics = sim.run()
    elapsed = time.time() - start_time

    print(f"    Done in {elapsed:.2f}s.")
    print(f"    Throughput: {metrics.throughput:.4f} | Safety Violations: {metrics.collisions_agent_human}")

    # 4. Save Replay
    replay_name = f"replay_seed{seed}.json"
    sim.replay.write(str(output_dir / replay_name))

    return metrics


def main():
    parser = argparse.ArgumentParser(description="HAL-MAPF Experiment Runner")
    parser.add_argument("--config", type=str, required=True, help="Path to .yaml config file")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0], help="List of random seeds to run")
    parser.add_argument("--out", type=str, default="logs/default", help="Output directory for logs")

    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    # Prepare CSV Writer
    # Initialize a dummy simulator just to get the header
    dummy_sim = Simulator(config)
    header = ["seed"] + dummy_sim.metrics.csv_header()

    csv_path = out_dir / "metrics.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        f.flush()

        for seed in args.seeds:
            m = run_single_seed(config, seed, out_dir)
            row = [seed] + dummy_sim.metrics.to_csv_row(m)
            writer.writerow(row)
            f.flush()

    print(f"\nAll runs completed. Results in {out_dir}")


if __name__ == "__main__":
    main()