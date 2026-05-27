# FILE: scripts/generate_random_map.py
"""
Random Map Generator with Connectivity Check.
Generates a MovingAI .map file.
"""
import argparse
import random
from collections import deque
from pathlib import Path
from typing import List


def is_fully_connected(grid: List[List[str]], width: int, height: int) -> bool:
    """
    Returns True if all free cells ('.') are reachable from the first free cell found.
    """
    free_cells = []
    for r in range(height):
        for c in range(width):
            if grid[r][c] == '.':
                free_cells.append((r, c))

    if not free_cells:
        return False  # No free space at all

    start = free_cells[0]
    queue = deque([start])
    visited = {start}

    count = 0
    while queue:
        r, c = queue.popleft()
        count += 1

        # Check 4 neighbors
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < height and 0 <= nc < width:
                if grid[nr][nc] == '.' and (nr, nc) not in visited:
                    visited.add((nr, nc))
                    queue.append((nr, nc))

    return count == len(free_cells)


def generate_map(width: int, height: int, density: float) -> List[List[str]]:
    grid = [['.' for _ in range(width)] for _ in range(height)]
    for r in range(height):
        for c in range(width):
            if random.random() < density:
                grid[r][c] = '@'  # Obstacle
    return grid


def save_map(grid: List[List[str]], width: int, height: int, path: str):
    with open(path, "w") as f:
        f.write("type octile\n")
        f.write(f"height {height}\n")
        f.write(f"width {width}\n")
        f.write("map\n")
        for row in grid:
            f.write("".join(row) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Output .map file path")
    parser.add_argument("--width", type=int, default=20)
    parser.add_argument("--height", type=int, default=20)
    parser.add_argument("--density", type=float, default=0.2, help="Obstacle density (0.0 to 1.0)")
    args = parser.parse_args()

    attempts = 0
    while True:
        attempts += 1
        grid = generate_map(args.width, args.height, args.density)
        if is_fully_connected(grid, args.width, args.height):
            break
        if attempts % 100 == 0:
            print(f"Attempt {attempts}: Map not connected, retrying...")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_map(grid, args.width, args.height, str(out_path))
    print(f"Success! Connected map saved to {args.out} (Attempts: {attempts})")


if __name__ == "__main__":
    main()