"""
CBSH2-RTC (Conflict-Based Search with Heuristics 2 - Reasoning with Target Conflicts) Wrapper

This module provides a wrapper for the official CBSH2-RTC solver from:
https://github.com/Jiaoyang-Li/CBSH2-RTC

CBSH2-RTC is an optimal MAPF solver that extends CBS with:
- Prioritizing conflicts
- Bypassing conflicts
- WDG heuristics
- Target reasoning
- Generalized rectangle and corridor reasoning

Cross-Platform Support:
    - Linux/macOS: Uses binary without extension (e.g., 'cbsh2')
    - Windows: Uses .exe binary (e.g., 'cbsh2.exe')

Usage:
    1. Clone and build CBSH2-RTC:
       # Linux/macOS:
       sudo apt install libboost-all-dev
       git clone https://github.com/Jiaoyang-Li/CBSH2-RTC.git && cd CBSH2-RTC
       cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
       cp cbs src/ha_lmapf/global_tier/solvers/cbsh2

       # Windows:
       git clone https://github.com/Jiaoyang-Li/CBSH2-RTC.git && cd CBSH2-RTC
       cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
       copy build\\Release\\cbs.exe src\\ha_lmapf\\global_tier\\solvers\\cbsh2.exe

    2. Use in code:
       from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
       solver = CBSH2Solver()
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


class CBSH2Solver(BaseSolverWrapper):
    """
    Wrapper for the official CBSH2-RTC C++ executable.

    CBSH2-RTC (Conflict-Based Search with Heuristics 2) is an optimal MAPF solver
    with advanced conflict resolution techniques.

    Cross-platform compatible:
    - Linux/macOS: Looks for 'cbsh2' or 'cbs' binary
    - Windows: Looks for 'cbsh2.exe' or 'cbs.exe' binary

    Communication protocol:
    1. Write map file in MovingAI .map format
    2. Write scenario file in MovingAI .scen format
    3. Execute CBSH2 binary with appropriate arguments
    4. Parse the output paths file
    """

    MIGRATION_DEPTH = "full"  # see BaseSolverWrapper.MIGRATION_DEPTH

    # Default binary names (platform-specific)
    DEFAULT_BINARY_LINUX = "cbsh2_rtc"
    DEFAULT_BINARY_WINDOWS = "cbsh2_rtc.exe"

    def __init__(
            self,
            binary_path: Optional[str] = None,
            time_limit_sec: float = 10.0,
            verbose: int = 0,
    ) -> None:
        """
        Initialize the CBSH2-RTC solver wrapper.

        Args:
            binary_path: Path to the cbsh2/cbs executable. If None, auto-detects.
            time_limit_sec: Time limit for the solver in seconds.
            verbose: Verbosity level (0 = silent, 1+ = verbose).
        """
        self.binary_path = self._find_binary(binary_path)
        self.time_limit_sec = time_limit_sec
        self.verbose = verbose

    @property
    def _default_binary(self) -> str:
        """Get the default binary name for the current platform."""
        return self.DEFAULT_BINARY_WINDOWS if IS_WINDOWS else self.DEFAULT_BINARY_LINUX

    def _find_binary(self, binary_path: Optional[str]) -> str:
        """Find the CBSH2 executable for the current platform."""
        if binary_path is not None:
            return binary_path

        solver_dir = os.path.dirname(__file__)

        if IS_WINDOWS:
            binary_names = ["cbsh2_rtc.exe", "cbsh2.exe"]
        else:
            binary_names = ["cbsh2_rtc", "cbsh2"]

        search_paths = []
        for name in binary_names:
            search_paths.extend([
                os.path.join(solver_dir, name),
                os.path.join(solver_dir, "CBSH2-RTC", name),
                os.path.join(solver_dir, "CBSH2-RTC", "build", name),
                os.path.join(solver_dir, "CBSH2-RTC", "build", "Release", name),
                os.path.join("build", name),
                os.path.join("build", "Release", name),
                name,
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
    ) -> PlanBundle:
        """Legacy shim — delegates to ``plan_with_metadata`` and returns
        only the ``PlanBundle``."""
        return self.plan_with_metadata(
            env, agents, assignments, step, horizon, rng,
        ).plan

    def plan_with_metadata(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
    ) -> SolverResult:
        """SolverResult-returning entry point for CBSH2-RTC.

        CBSH2-RTC is an **optimal**, non-anytime solver — it returns
        either a fully optimal solution or nothing.  The four
        reachable statuses are therefore::

            complete           rc=0, paths file written, csv solution_cost >= 0
            error  (soft)      rc=0, csv written with solution_cost = -1
                               (binary self-terminated at -t without finding
                               an optimal solution; error_msg surfaces the
                               stdout "Timeout,-1,..." marker)
            timeout_no_result  watchdog killed the subprocess before any
                               file was written
            error  (hard)      rc != 0 (segfault / bad input / etc.)

        ``partial_anytime`` is structurally impossible: the binary
        either writes a complete optimal solution or no paths file at
        all.  This is verified empirically by the
        ``test_no_partial_anytime_for_cbsh2`` discrimination test.
        """
        active_agents = self._get_active_agents(agents, assignments)
        if not active_agents:
            return SolverResult(
                plan=PlanBundle(paths={}, created_step=step, horizon=horizon),
                status="complete",
                solver_wall_ms=0.0,
                end_to_end_wall_ms=0.0,
            )

        tmpdir = tempfile.mkdtemp(prefix="cbsh2_")
        try:
            map_path = os.path.join(tmpdir, "map.map")
            scen_path = os.path.join(tmpdir, "agents.scen")
            output_path = os.path.join(tmpdir, "output.csv")
            paths_path = os.path.join(tmpdir, "paths.txt")
            map_filename = os.path.basename(map_path)
            self._write_map_file(env, map_path)
            agent_order = self._write_scenario_file(
                env, agents, assignments, active_agents, scen_path, map_filename,
            )
            cmd = [
                self.binary_path,
                "-m", map_path,
                "-a", scen_path,
                "-o", output_path,
                f"--outputPaths={paths_path}",
                "-k", str(len(agent_order)),
                "-t", str(int(self.time_limit_sec)),
            ]

            def parse_fn(stdout: str, stderr: str, returncode: int):
                paths = None
                err = None
                # Read the CSV first (always written, even on
                # self-timeout).  ``solution cost = -1`` in the last
                # data row indicates CBSH2 self-terminated at ``-t``
                # without an optimal solution.  This is a soft timeout
                # — paths file will be missing in this case.
                solver_wall_ms = math.nan
                soft_timeout = False
                if os.path.exists(output_path):
                    try:
                        with open(output_path, "r") as f:
                            csv_lines = f.readlines()
                        if len(csv_lines) >= 2:
                            header = [h.strip() for h in csv_lines[0].split(",")]
                            row = [v.strip() for v in csv_lines[-1].split(",")]
                            if "runtime" in header:
                                idx = header.index("runtime")
                                if len(row) > idx:
                                    try:
                                        solver_wall_ms = float(row[idx]) * 1000.0
                                    except ValueError:
                                        pass
                            if "solution cost" in header:
                                idx = header.index("solution cost")
                                if len(row) > idx and row[idx] == "-1":
                                    soft_timeout = True
                    except Exception:
                        pass
                # Stdout "Timeout,-1,..." is the secondary marker.
                if not soft_timeout and "Timeout,-1" in stdout:
                    soft_timeout = True

                if os.path.exists(paths_path):
                    try:
                        parsed = self._parse_paths_file(
                            paths_path, agent_order, step, horizon,
                        )
                        if parsed and not [a for a in agent_order if a not in parsed]:
                            paths = parsed
                        elif parsed:
                            err = (
                                f"partial parse: {len(parsed)}/"
                                f"{len(agent_order)} active agents got paths"
                            )
                        else:
                            err = "paths file empty / unparseable"
                    except Exception as exc:  # noqa: BLE001
                        err = f"parse error: {exc}"
                elif soft_timeout:
                    err = (
                        "CBSH2-RTC self-reported Timeout,-1 (CSV "
                        "solution_cost=-1: -t exhausted before optimal "
                        "solution; non-anytime solver writes no partial "
                        "paths)"
                    )
                else:
                    err = "paths file not produced"
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
        """Write environment to MovingAI .map format."""
        with open(path, 'w') as f:
            f.write("type octile\n")
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

    def _write_scenario_file(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            active_agents: List[int],
            path: str,
            map_filename: str = "map.map",
    ) -> List[int]:
        """Write MovingAI .scen format scenario file."""
        agent_order = []

        with open(path, 'w') as f:
            f.write("version 1\n")

            for aid in active_agents:
                agent = agents[aid]
                start = agent.pos

                if agent.goal is not None:
                    goal = agent.goal
                elif aid in assignments:
                    goal = assignments[aid].goal
                else:
                    goal = start

                # MovingAI format uses (col, row)
                start_col, start_row = start[1], start[0]
                goal_col, goal_row = goal[1], goal[0]

                f.write(f"0\t{map_filename}\t{env.width}\t{env.height}\t"
                        f"{start_col}\t{start_row}\t{goal_col}\t{goal_row}\t0.0\n")

                agent_order.append(aid)

        return agent_order

    def _run_cbsh2(
            self,
            map_path: str,
            scen_path: str,
            output_path: str,
            paths_path: str,
            num_agents: int,
    ) -> bool:
        """Execute the CBSH2-RTC binary."""
        if not os.path.isfile(self.binary_path):
            print(f"[CBSH2] ERROR: Binary not found at {self.binary_path}")
            print(f"[CBSH2] Please build CBSH2-RTC from https://github.com/Jiaoyang-Li/CBSH2-RTC")
            if IS_WINDOWS:
                print(f"[CBSH2] For Windows: copy build\\Release\\cbs.exe to solvers\\cbsh2.exe")
            else:
                print(f"[CBSH2] For Linux/macOS: copy cbs to solvers/cbsh2")
            return False

        cmd = [
            self.binary_path,
            "-m", map_path,
            "-a", scen_path,
            "-o", output_path,
            f"--outputPaths={paths_path}",
            "-k", str(num_agents),
            "-t", str(int(self.time_limit_sec)),
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
                    print(f"[CBSH2] Solver returned code {result.returncode}")
                    print(f"[CBSH2] stderr: {result.stderr}")
                return False

            return True

        except subprocess.TimeoutExpired:
            print(f"[CBSH2] Solver timed out after {self.time_limit_sec}s")
            return False
        except FileNotFoundError:
            print(f"[CBSH2] Binary not found: {self.binary_path}")
            return False
        except Exception as e:
            print(f"[CBSH2] Execution error: {e}")
            return False

    def _parse_paths_file(
            self,
            paths_path: str,
            agent_order: List[int],
            start_step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        """
        Parse CBSH2-RTC paths output file.

        Format (typical):
        Agent 0: (x0,y0)->(x1,y1)->...
        Agent 1: (x0,y0)->(x1,y1)->...
        ...
        """
        paths: Dict[int, TimedPath] = {}

        try:
            with open(paths_path, 'r') as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Try to match "Agent X:" pattern
                match = re.match(r'^Agent\s+(\d+):\s*(.+)$', line, re.IGNORECASE)
                if match:
                    agent_idx = int(match.group(1))
                    path_str = match.group(2)

                    if agent_idx < len(agent_order):
                        aid = agent_order[agent_idx]
                        cells = self._parse_path_string(path_str)

                        if cells:
                            if len(cells) < horizon + 1:
                                cells = cells + [cells[-1]] * (horizon + 1 - len(cells))
                            elif len(cells) > horizon + 1:
                                cells = cells[:horizon + 1]
                            paths[aid] = TimedPath(cells=cells, start_step=start_step)

        except Exception as e:
            print(f"[CBSH2] Error parsing paths file: {e}")

        return paths

    def _parse_path_string(self, path_str: str) -> List[Cell]:
        """Parse a path string like (row,col)->(row,col)->..."""
        cells = []
        # CBSH2-RTC outputs (row, col) pairs — NOT (x, y)
        coords = re.findall(r'\((\d+),(\d+)\)', path_str)
        for row_str, col_str in coords:
            row = int(row_str)
            col = int(col_str)
            cells.append((row, col))
        return cells

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


# Aliases
CBSH2RTCSolver = CBSH2Solver
CBSHeuristicSolver = CBSH2Solver
