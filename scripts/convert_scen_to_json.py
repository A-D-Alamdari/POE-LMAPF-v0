# FILE: scripts/convert_scen_to_json.py
"""
MovingAI Scenario Converter.

Converts a standard .scen file (MovingAI benchmark format) into a
Lifelong MAPF task stream (.json).

Format Reference (.scen):
    version 1
    bucket map width height start_x start_y goal_x goal_y optimal_length

Conversion Logic:
    1. Reads Goal X (col) and Goal Y (row).
    2. Converts to (row, col) for HAL-MAPF.
    3. Assigns a 'release_step' based on a configurable rate.
    4. Ignores 'Start' positions (since Lifelong MAPF tasks are assigned to available agents).

Usage:
    python scripts/convert_scen_to_json.py --scen data/scenarios/warehouse.scen --out data/tasks/warehouse_stream.json --rate 5
"""
import argparse
import json
import sys
from typing import Dict


def parse_scen_line(line: str) -> Dict[str, int]:
    """
    Parse a single line from a .scen file.
    Expected format: bucket map width height start_x start_y goal_x goal_y optimal_length
    """
    parts = line.strip().split()
    if len(parts) < 9:
        raise ValueError(f"Malformed .scen line: {line}")

    # MovingAI uses (x, y) -> (column, row)
    # We strictly need Goal (indices 6 and 7)
    return {
        "goal_c": int(parts[6]),  # goal_x
        "goal_r": int(parts[7]),  # goal_y
    }


def main():
    parser = argparse.ArgumentParser(description="Convert .scen to .json task stream.")
    parser.add_argument("--scen", required=True, help="Input .scen file path")
    parser.add_argument("--out", required=True, help="Output .json file path")
    parser.add_argument("--rate", type=int, default=0, help="Release rate (steps between tasks). 0 = all at once.")
    parser.add_argument("--limit", type=int, default=None, help="Max tasks to convert (optional).")

    args = parser.parse_args()

    tasks = []

    try:
        with open(args.scen, "r") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: File not found {args.scen}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {args.scen}...")

    count = 0
    for line in lines:
        line = line.strip()
        # Skip version header or empty lines
        if not line or line.startswith("version") or line.lower().startswith("bucket"):
            continue

        try:
            data = parse_scen_line(line)
        except ValueError:
            continue

        # Create Task Object (Dictionary for JSON dump)
        # HAL-MAPF uses (row, col) convention
        task = {
            "id": f"t_{count}",
            "goal": [data["goal_r"], data["goal_c"]],
            "release_step": count * args.rate
        }

        tasks.append(task)
        count += 1

        if args.limit and count >= args.limit:
            break

    # Write to JSON
    with open(args.out, "w") as f:
        json.dump(tasks, f, indent=2)

    print(f"Success! Converted {len(tasks)} tasks.")
    print(f"Saved to: {args.out}")


if __name__ == "__main__":
    main()