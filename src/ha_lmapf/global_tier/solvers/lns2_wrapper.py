"""
MAPF-LNS2 (Large Neighborhood Search 2) Official Wrapper

This module provides a wrapper for the official MAPF-LNS2 solver from:
https://github.com/Jiaoyang-Li/MAPF-LNS2

MAPF-LNS2 is an anytime MAPF solver that uses Large Neighborhood Search
to iteratively improve solutions. It's designed for very large-scale
MAPF problems with hundreds of agents.

Cross-Platform Support:
    - Linux/macOS: Uses binary without extension (e.g., 'lns')
    - Windows: Uses .exe binary (e.g., 'lns.exe')

Usage:
    1. Clone and build MAPF-LNS2:
       # Linux/macOS:
       sudo apt install libboost-all-dev libeigen3-dev
       git clone https://github.com/Jiaoyang-Li/MAPF-LNS2.git && cd MAPF-LNS2
       cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
       cp lns src/ha_lmapf/global_tier/solvers/lns2

       # Windows:
       git clone https://github.com/Jiaoyang-Li/MAPF-LNS2.git && cd MAPF-LNS2
       cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
       copy build\\Release\\lns.exe src\\ha_lmapf\\global_tier\\solvers\\lns2.exe

    2. Use in code:
       from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver
       solver = LNS2Solver()
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


class LNS2Solver(BaseSolverWrapper):
    """
    Wrapper for the official MAPF-LNS2 C++ executable.

    MAPF-LNS2 (Large Neighborhood Search 2) is an anytime MAPF solver
    designed for very large-scale problems with hundreds of agents.
    It iteratively improves solutions using destroy-and-repair operations.

    Cross-platform compatible:
    - Linux/macOS: Looks for 'lns2' or 'lns' binary
    - Windows: Looks for 'lns2.exe' or 'lns.exe' binary
    """

    MIGRATION_DEPTH = "full"  # see BaseSolverWrapper.MIGRATION_DEPTH

    DEFAULT_BINARY_LINUX = "mapf_lns"
    DEFAULT_BINARY_WINDOWS = "lns2.exe"

    def __init__(
            self,
            binary_path: Optional[str] = None,
            time_limit_sec: float = 10.0,
            verbose: int = 0,
    ) -> None:
        """
        Initialize the MAPF-LNS2 solver wrapper.

        Args:
            binary_path: Path to the lns executable. If None, auto-detects.
            time_limit_sec: Time limit for the solver in seconds.
            verbose: Verbosity level (0 = silent, 1+ = verbose).
        """
        self.binary_path = self._find_binary(binary_path)
        self.time_limit_sec = time_limit_sec
        self.verbose = verbose

    @property
    def _default_binary(self) -> str:
        return self.DEFAULT_BINARY_WINDOWS if IS_WINDOWS else self.DEFAULT_BINARY_LINUX

    def _find_binary(self, binary_path: Optional[str]) -> str:
        if binary_path is not None:
            return binary_path

        solver_dir = os.path.dirname(__file__)

        if IS_WINDOWS:
            binary_names = ["lns2.exe", "lns2", "mapf_lns.exe", "mapf_lns", "lns.exe", "lns"]
        else:
            binary_names = ["lns2", "mapf_lns", "lns"]

        search_paths = []
        for name in binary_names:
            search_paths.extend([
                os.path.join(solver_dir, name),
                os.path.join(solver_dir, "MAPF-LNS2", name),
                os.path.join(solver_dir, "MAPF-LNS2", "build", name),
                os.path.join(solver_dir, "MAPF-LNS2", "build", "Release", name),
                os.path.join("build", name),
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
        """SolverResult-returning entry point for MAPF-LNS2.

        Anytime semantics: LNS2's anytime budget is enforced internally
        via ``-t`` (cutoffTime in seconds).  At ``-t`` the binary
        self-terminates with rc=0 and writes the paths file iff it
        found at least the initial solution.  Empirical findings on
        the warehouse-10-20-10-2-2 map (this binary,
        ``-s 0`` non-verbose):

        * If the initial-solution search itself exceeds ``-t``: no
          paths file is written.  rc=0 + no plan → decision tree
          maps to ``error`` (with parse_error indicating the soft
          timeout).
        * If the initial solution is found inside ``-t``: paths file
          is written and the binary may run further iterations to
          improve cost; at the budget it self-terminates with rc=0
          and the best-so-far paths file is on disk.  status ==
          ``complete``.
        * ``partial_anytime`` is only reachable if the wrapper's
          subprocess watchdog fires (``TimeoutExpired``) AFTER the
          initial paths flush — empirically rare for LNS2 because
          the binary writes the paths file only at end-of-run.
        """
        active_agents = self._get_active_agents(agents, assignments)
        if not active_agents:
            return SolverResult(
                plan=PlanBundle(paths={}, created_step=step, horizon=horizon),
                status="complete",
                solver_wall_ms=0.0,
                end_to_end_wall_ms=0.0,
            )

        # Rewrite duplicate-goal agents to ``goal == start`` so the
        # Jiaoyang-Li LNS2 binary does not abort with the rc=255
        # "target conflict" error.  See ``docs/solver_error_diagnosis.md``.
        planned_agents, goal_overrides = self._filter_one_shot_instance(
            agents, assignments, active_agents,
        )

        tmpdir = tempfile.mkdtemp(prefix="lns2_")
        try:
            map_path = os.path.join(tmpdir, "map.map")
            scen_path = os.path.join(tmpdir, "agents.scen")
            output_basename = os.path.join(tmpdir, "output")
            paths_path = os.path.join(tmpdir, "paths.txt")
            map_filename = os.path.basename(map_path)
            self._write_map_file(env, map_path)
            agent_order = self._write_scenario_file(
                env, agents, assignments, planned_agents, scen_path,
                map_filename, goal_overrides=goal_overrides,
            )
            cmd = [
                self.binary_path,
                "-m", map_path,
                "-a", scen_path,
                "-o", output_basename,
                f"--outputPaths={paths_path}",
                "-k", str(len(agent_order)),
                "-t", str(int(self.time_limit_sec)),
            ]

            def parse_fn(stdout: str, stderr: str, returncode: int):
                paths = None
                err = None
                if os.path.exists(paths_path):
                    try:
                        parsed = self._parse_paths_file(
                            paths_path, agent_order, step, horizon,
                        )
                        if parsed and not [a for a in agent_order if a not in parsed]:
                            paths = parsed
                        elif parsed:
                            err = (
                                f"partial parse: {len(parsed)}/{len(agent_order)} "
                                f"active agents got paths"
                            )
                        else:
                            err = "paths file empty / unparseable"
                    except Exception as exc:  # noqa: BLE001
                        err = f"parse error: {exc}"
                else:
                    # When LNS2 fails to find an initial solution
                    # within ``-t`` it exits rc=0 without writing the
                    # paths file.  Surface this so the harness can
                    # distinguish from a real binary fault.
                    if "Failed to find an initial solution" in stdout:
                        err = ("LNS2 reported 'Failed to find an initial "
                               "solution' (-t exhausted before first "
                               "feasible plan)")
                    else:
                        err = "paths file not produced"
                # solver_wall_ms: prefer the CSV ``runtime`` column
                # (LNS2 appends ``-LNS.csv`` to the -o argument).
                # Fall back to the LAST ``runtime = <float>`` line in
                # stdout (LNS2 prints initial + final runtime; we want
                # the latest).  Both report seconds → multiply by
                # 1000 for milliseconds.  NaN if neither is available.
                solver_wall_ms = math.nan
                csv_path = output_basename + "-LNS.csv"
                if os.path.exists(csv_path):
                    try:
                        with open(csv_path, "r") as f:
                            csv_lines = f.readlines()
                        if len(csv_lines) >= 2:
                            header = [h.strip() for h in csv_lines[0].split(",")]
                            row = [v.strip() for v in csv_lines[-1].split(",")]
                            if "runtime" in header:
                                idx = header.index("runtime")
                                if len(row) > idx:
                                    solver_wall_ms = float(row[idx]) * 1000.0
                    except Exception:
                        pass
                if math.isnan(solver_wall_ms) and stdout:
                    matches = re.findall(
                        r"runtime\s*=\s*([0-9.eE+\-]+)", stdout,
                    )
                    if matches:
                        try:
                            solver_wall_ms = float(matches[-1]) * 1000.0
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
        active = []
        for aid, agent in agents.items():
            if agent.goal is not None:
                active.append(aid)
            elif aid in assignments:
                active.append(aid)
        return sorted(active)

    def _write_map_file(self, env, path: str) -> None:
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
            goal_overrides: Optional[Dict[int, Cell]] = None,
    ) -> List[int]:
        """Write the MovingAI .scen file.  ``goal_overrides`` pins
        specific agents' scenario goals (see
        ``BaseSolverWrapper._filter_one_shot_instance``)."""
        agent_order = []
        overrides = goal_overrides or {}
        with open(path, 'w') as f:
            f.write("version 1\n")
            for aid in active_agents:
                agent = agents[aid]
                start = agent.pos
                if aid in overrides:
                    goal = overrides[aid]
                elif agent.goal is not None:
                    goal = agent.goal
                elif aid in assignments:
                    goal = assignments[aid].goal
                else:
                    goal = start
                start_col, start_row = start[1], start[0]
                goal_col, goal_row = goal[1], goal[0]
                f.write(f"0\t{map_filename}\t{env.width}\t{env.height}\t"
                        f"{start_col}\t{start_row}\t{goal_col}\t{goal_row}\t0.0\n")
                agent_order.append(aid)
        return agent_order

    def _run_lns2(
            self,
            map_path: str,
            scen_path: str,
            output_path: str,
            paths_path: str,
            num_agents: int,
    ) -> bool:
        if not os.path.isfile(self.binary_path):
            print(f"[LNS2] ERROR: Binary not found at {self.binary_path}")
            print(f"[LNS2] Please build MAPF-LNS2 from https://github.com/Jiaoyang-Li/MAPF-LNS2")
            if IS_WINDOWS:
                print(f"[LNS2] For Windows: copy build\\Release\\lns.exe to solvers\\lns2.exe")
            else:
                print(f"[LNS2] For Linux/macOS: copy lns to solvers/lns2")
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
                    print(f"[LNS2] Solver returned code {result.returncode}")
                    print(f"[LNS2] stderr: {result.stderr}")
                return False
            return True
        except subprocess.TimeoutExpired:
            print(f"[LNS2] Solver timed out after {self.time_limit_sec}s")
            return False
        except FileNotFoundError:
            print(f"[LNS2] Binary not found: {self.binary_path}")
            return False
        except Exception as e:
            print(f"[LNS2] Execution error: {e}")
            return False

    def _parse_paths_file(
            self,
            paths_path: str,
            agent_order: List[int],
            start_step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        paths: Dict[int, TimedPath] = {}
        try:
            with open(paths_path, 'r') as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
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
            print(f"[LNS2] Error parsing paths file: {e}")
        return paths

    def _parse_path_string(self, path_str: str) -> List[Cell]:
        """Parse a path string like (row,col)->(row,col)->..."""
        cells = []
        # LNS2 (Jiaoyang-Li) outputs (row, col) pairs
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
        paths = {}
        for aid in active_agents:
            paths[aid] = self._create_wait_path(agents[aid].pos, step, horizon)
        return paths

    def _create_wait_path(self, pos: Cell, step: int, horizon: int) -> TimedPath:
        cells = [pos] * (horizon + 1)
        return TimedPath(cells=cells, start_step=step)


# Aliases
MAPFLNS2Solver = LNS2Solver
LargeNeighborhoodSearchSolver = LNS2Solver
