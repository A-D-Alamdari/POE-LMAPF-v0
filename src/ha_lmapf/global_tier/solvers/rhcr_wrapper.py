"""
RHCR (Rolling-Horizon Collision Resolution) Official Wrapper

This module provides a wrapper for the official RHCR solver from:
https://github.com/Jiaoyang-Li/RHCR

RHCR is a lifelong MAPF solver that uses rolling-horizon planning with
collision resolution. It supports multiple windowed MAPF algorithms
including WHCA*, ECBS, and PBS.

Cross-Platform Support:
    - Linux/macOS: Uses binary without extension (e.g., 'rhcr' or 'lifelong')
    - Windows: Uses .exe binary (e.g., 'rhcr.exe' or 'lifelong.exe')

Usage:
    1. Clone and build RHCR:
       # Linux/macOS:
       sudo apt install libboost-all-dev  # Install Boost
       git clone https://github.com/Jiaoyang-Li/RHCR.git && cd RHCR
       cmake . && make
       cp lifelong src/ha_lmapf/global_tier/solvers/rhcr

       # Windows:
       git clone https://github.com/Jiaoyang-Li/RHCR.git && cd RHCR
       cmake -B build && cmake --build build --config Release
       copy build\\Release\\lifelong.exe src\\ha_lmapf\\global_tier\\solvers\\rhcr.exe

    2. Use in code:
       from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
       solver = RHCRSolver()
"""

from __future__ import annotations

import math
import os
import platform
import re
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from ha_lmapf.core.types import (
    AgentState, PlanBundle, SolverResult, Task, TimedPath,
)
from ha_lmapf.global_tier.solvers._base import BaseSolverWrapper

Cell = Tuple[int, int]

# Platform detection
IS_WINDOWS = platform.system() == "Windows"
BINARY_EXT = ".exe" if IS_WINDOWS else ""


class RHCRSolver(BaseSolverWrapper):
    """
    Wrapper for the official RHCR C++ executable.

    RHCR (Rolling-Horizon Collision Resolution) is a lifelong MAPF solver
    that uses windowed planning with collision resolution.

    Cross-platform compatible:
    - Linux/macOS: Looks for 'rhcr' or 'lifelong' binary
    - Windows: Looks for 'rhcr.exe' or 'lifelong.exe' binary

    Communication protocol:
    1. Write map file in RHCR grid format
    2. Write task file with agent starts and goals
    3. Execute RHCR binary with appropriate arguments
    4. Parse the output paths file

    Key parameters:
    - simulation_window (h): Replanning interval
    - planning_window (w): Collision-resolution horizon
    - solver: Windowed MAPF algorithm (WHCA, ECBS, PBS)
    """

    # Default binary names (platform-specific)
    DEFAULT_BINARY_LINUX = "rhcr"
    DEFAULT_BINARY_WINDOWS = "rhcr.exe"

    def __init__(
            self,
            binary_path: Optional[str] = None,
            time_limit_sec: float = 10.0,
            verbose: int = 0,
            simulation_window: int = 5,
            planning_window: int = 10,
            solver: str = "PBS",
            scenario: str = "KIVA",
    ) -> None:
        """
        Initialize the RHCR solver wrapper.

        Args:
            binary_path: Path to the rhcr/lifelong executable. If None, auto-detects.
            time_limit_sec: Time limit for the solver in seconds.
            verbose: Verbosity level (0 = silent, 1+ = verbose).
            simulation_window: Replanning interval (h parameter).
            planning_window: Collision-resolution horizon (w parameter).
            solver: Windowed MAPF algorithm: "WHCA", "ECBS", or "PBS".
            scenario: Task scenario type: "KIVA" or "SORTING".
        """
        self.binary_path = self._find_binary(binary_path)
        self.time_limit_sec = time_limit_sec
        self.verbose = verbose
        self.simulation_window = simulation_window
        self.planning_window = planning_window
        self.solver = solver.upper()
        self.scenario = scenario.upper()

    @property
    def _default_binary(self) -> str:
        """Get the default binary name for the current platform."""
        return self.DEFAULT_BINARY_WINDOWS if IS_WINDOWS else self.DEFAULT_BINARY_LINUX

    def _find_binary(self, binary_path: Optional[str]) -> str:
        """Find the RHCR executable for the current platform."""
        if binary_path is not None:
            return binary_path

        solver_dir = os.path.dirname(__file__)

        # Platform-specific binary names to search
        if IS_WINDOWS:
            binary_names = ["rhcr.exe", "rhcr", "lifelong.exe", "lifelong"]
        else:
            binary_names = ["rhcr", "lifelong"]

        # Build search paths
        search_paths = []
        for name in binary_names:
            search_paths.extend([
                os.path.join(solver_dir, name),
                os.path.join(solver_dir, "RHCR", name),
                os.path.join(solver_dir, "RHCR", "build", name),
                os.path.join(solver_dir, "RHCR", "build", "Release", name),
                os.path.join("build", name),
                os.path.join("build", "Release", name),
                name,
                os.path.join(".", name),
            ])

        for path in search_paths:
            if os.path.isfile(path):
                return path

        return os.path.join(solver_dir, self._default_binary)

    def plan(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
            is_lifelong: bool = True,
    ) -> PlanBundle:
        """Legacy shim — delegates to ``plan_with_metadata`` and returns
        only the ``PlanBundle``."""
        return self.plan_with_metadata(
            env, agents, assignments, step, horizon, rng,
            is_lifelong=is_lifelong,
        ).plan

    def plan_with_metadata(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
            is_lifelong: bool = True,
    ) -> SolverResult:
        """SolverResult-returning entry point for RHCR."""
        active_agents = self._get_active_agents(agents, assignments)
        if not active_agents:
            return SolverResult(
                plan=PlanBundle(paths={}, created_step=step, horizon=horizon),
                status="complete",
                solver_wall_ms=0.0,
                end_to_end_wall_ms=0.0,
            )

        tmpdir = tempfile.mkdtemp(prefix="rhcr_")
        try:
            map_path = os.path.join(tmpdir, "map.grid")
            task_path = os.path.join(tmpdir, "tasks.task")
            output_path = os.path.join(tmpdir, "output.txt")
            self._write_map_file(env, map_path)
            agent_order = self._write_task_file(
                env, agents, assignments, active_agents, task_path,
            )
            cmd = [
                self.binary_path,
                "-m", map_path,
                "-k", str(len(agent_order)),
                f"--scenario={self.scenario}",
                f"--simulation_window={self.simulation_window}",
                f"--planning_window={self.planning_window}",
                f"--solver={self.solver}",
                "-o", output_path,
            ]

            def parse_fn(stdout: str, stderr: str, returncode: int):
                paths = None
                err = None
                if os.path.exists(output_path):
                    try:
                        parsed = self._parse_output_file(
                            output_path, agent_order, step, horizon,
                        )
                        if parsed and not [a for a in agent_order if a not in parsed]:
                            paths = parsed
                        elif parsed:
                            err = (
                                f"partial parse: {len(parsed)}/{len(agent_order)} "
                                f"active agents got paths"
                            )
                    except Exception as exc:  # noqa: BLE001
                        err = f"parse error: {exc}"
                else:
                    err = "output file not produced"
                # RHCR's stdout typically contains a "runtime: <s>" line.
                solver_wall_ms = math.nan
                m = re.search(
                    r"runtime\s*[:=]\s*([0-9.]+)", stdout or "", re.IGNORECASE,
                )
                if m:
                    try:
                        solver_wall_ms = float(m.group(1)) * 1000.0
                    except ValueError:
                        pass
                return paths, solver_wall_ms, err

            return self._wrap_subprocess(
                cmd=cmd,
                timeout_s=float(self.time_limit_sec),
                parse_fn=parse_fn,
                agents=agents,
                active_agents=active_agents,
                start_step=step,
                horizon=horizon,
                binary_path=self.binary_path,
                watchdog_buffer_s=10.0,
            )
        finally:
            try:
                import shutil
                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception:
                pass

    def _get_active_agents(
            self,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
    ) -> List[int]:
        """Get list of agents that need planning."""
        active = []
        for aid, agent in agents.items():
            if agent.goal is not None:
                active.append(aid)
            elif aid in assignments:
                active.append(aid)
        return sorted(active)

    def _write_map_file(self, env, path: str) -> None:
        """Write environment to RHCR grid format."""
        with open(path, 'w') as f:
            f.write(f"type octile\n")
            f.write(f"height {env.height}\n")
            f.write(f"width {env.width}\n")
            f.write("map\n")

            for r in range(env.height):
                row_str = ""
                for c in range(env.width):
                    if env.is_blocked((r, c)):
                        row_str += "@"
                    else:
                        row_str += "."
                f.write(row_str + "\n")

    def _write_task_file(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            active_agents: List[int],
            path: str,
    ) -> List[int]:
        """
        Write RHCR task file.

        Format depends on scenario type, but typically:
        agent_id start_x start_y goal_x goal_y

        Returns:
            List of agent IDs in order
        """
        agent_order = []

        with open(path, 'w') as f:
            f.write(f"{len(active_agents)}\n")

            for aid in active_agents:
                agent = agents[aid]
                start = agent.pos  # (row, col)

                if agent.goal is not None:
                    goal = agent.goal
                elif aid in assignments:
                    goal = assignments[aid].goal
                else:
                    goal = start

                # RHCR uses (col, row) format (x, y)
                f.write(f"{start[1]} {start[0]} {goal[1]} {goal[0]}\n")
                agent_order.append(aid)

        return agent_order

    def _run_rhcr(
            self,
            map_path: str,
            task_path: str,
            output_path: str,
            num_agents: int,
    ) -> bool:
        """Execute the RHCR binary."""
        if not os.path.isfile(self.binary_path):
            print(f"[RHCR] ERROR: Binary not found at {self.binary_path}")
            print(f"[RHCR] Please build RHCR from https://github.com/Jiaoyang-Li/RHCR")
            if IS_WINDOWS:
                print(f"[RHCR] For Windows: copy build\\Release\\lifelong.exe to solvers\\rhcr.exe")
            else:
                print(f"[RHCR] For Linux/macOS: copy lifelong to solvers/rhcr")
            return False

        cmd = [
            self.binary_path,
            "-m", map_path,
            "-k", str(num_agents),
            f"--scenario={self.scenario}",
            f"--simulation_window={self.simulation_window}",
            f"--planning_window={self.planning_window}",
            f"--solver={self.solver}",
            "-o", output_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.time_limit_sec + 10,
            )

            if result.returncode != 0:
                if self.verbose > 0:
                    print(f"[RHCR] Solver returned code {result.returncode}")
                    print(f"[RHCR] stderr: {result.stderr}")
                return False

            return True

        except subprocess.TimeoutExpired:
            print(f"[RHCR] Solver timed out after {self.time_limit_sec}s")
            return False
        except FileNotFoundError:
            print(f"[RHCR] Binary not found: {self.binary_path}")
            return False
        except Exception as e:
            print(f"[RHCR] Execution error: {e}")
            return False

    def _parse_output_file(
            self,
            output_path: str,
            agent_order: List[int],
            start_step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        """Parse RHCR output file."""
        paths: Dict[int, TimedPath] = {}

        try:
            with open(output_path, 'r') as f:
                content = f.read()

            # RHCR output format may vary; try common patterns
            # Pattern 1: Agent paths line by line
            # Pattern 2: solution= format similar to LaCAM

            if "solution=" in content:
                # LaCAM-like format
                return self._parse_solution_format(content, agent_order, start_step, horizon)

            # Try line-by-line agent paths
            lines = content.strip().split('\n')
            agent_paths: Dict[int, List[Cell]] = {aid: [] for aid in agent_order}

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Try to parse as: agent_id: (x1,y1) (x2,y2) ...
                match = re.match(r'^(\d+):\s*(.+)$', line)
                if match:
                    agent_idx = int(match.group(1))
                    if agent_idx < len(agent_order):
                        aid = agent_order[agent_idx]
                        coords_str = match.group(2)
                        coords = re.findall(r'\((\d+),(\d+)\)', coords_str)
                        for row_str, col_str in coords:
                            row, col = int(row_str), int(col_str)
                            agent_paths[aid].append((row, col))

            for aid, cells in agent_paths.items():
                if cells:
                    if len(cells) < horizon + 1:
                        cells = cells + [cells[-1]] * (horizon + 1 - len(cells))
                    elif len(cells) > horizon + 1:
                        cells = cells[:horizon + 1]
                    paths[aid] = TimedPath(cells=cells, start_step=start_step)

        except Exception as e:
            print(f"[RHCR] Error parsing output file: {e}")

        return paths

    def _parse_solution_format(
            self,
            content: str,
            agent_order: List[int],
            start_step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        """Parse solution= format output."""
        paths: Dict[int, TimedPath] = {}

        solution_start = content.index("solution=") + len("solution=")
        solution_text = content[solution_start:].strip()

        agent_paths: Dict[int, List[Cell]] = {aid: [] for aid in agent_order}

        for line in solution_text.split('\n'):
            line = line.strip()
            if not line or ':' not in line:
                continue

            match = re.match(r'^(\d+):(.+)$', line)
            if not match:
                continue

            coords_str = match.group(2)
            coords = re.findall(r'\((\d+),(\d+)\)', coords_str)

            if len(coords) != len(agent_order):
                continue

            for idx, (row_str, col_str) in enumerate(coords):
                row = int(row_str)
                col = int(col_str)
                cell = (row, col)
                aid = agent_order[idx]
                agent_paths[aid].append(cell)

        for aid, cells in agent_paths.items():
            if cells:
                if len(cells) < horizon + 1:
                    cells = cells + [cells[-1]] * (horizon + 1 - len(cells))
                elif len(cells) > horizon + 1:
                    cells = cells[:horizon + 1]
                paths[aid] = TimedPath(cells=cells, start_step=start_step)

        return paths

    def _create_wait_paths(
            self,
            agents: Dict[int, AgentState],
            active_agents: List[int],
            step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        """Create WAIT paths for all active agents (fallback)."""
        paths = {}
        for aid in active_agents:
            paths[aid] = self._create_wait_path(agents[aid].pos, step, horizon)
        return paths

    def _create_wait_path(self, pos: Cell, step: int, horizon: int) -> TimedPath:
        """Create a WAIT-in-place path."""
        cells = [pos] * (horizon + 1)
        return TimedPath(cells=cells, start_step=step)


# Aliases for compatibility
RHCRCppPlanner = RHCRSolver
LifelongSolver = RHCRSolver
