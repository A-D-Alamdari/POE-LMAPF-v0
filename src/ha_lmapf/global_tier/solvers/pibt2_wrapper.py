"""
PIBT2 Official Executable Wrapper

This module provides a wrapper for the official PIBT2 solver from:
https://github.com/Kei18/pibt2

PIBT2 (Priority Inheritance with Backtracking, version 2) is a fast
real-time MAPF solver optimized for iterative/lifelong scenarios.

PIBT2 provides two executables:
- `mapf`: For one-shot/classical MAPF (each agent has one goal)
- `mapd`: For lifelong MAPF / Multi-Agent Pickup and Delivery

Cross-Platform Support:
    - Linux/macOS: Uses binaries without extension (e.g., 'mapf_pibt2', 'mapd_pibt2')
    - Windows: Uses .exe binaries (e.g., 'mapf_pibt2.exe', 'mapd_pibt2.exe')

Usage:
    1. Clone and build PIBT2:
       # Linux/macOS:
       git clone --recursive https://github.com/Kei18/pibt2.git && cd pibt2
       mkdir build && cd build && cmake .. && make
       cp mapf src/ha_lmapf/global_tier/solvers/mapf_pibt2
       cp mapd src/ha_lmapf/global_tier/solvers/mapd_pibt2

       # Windows:
       git clone --recursive https://github.com/Kei18/pibt2.git && cd pibt2
       mkdir build && cd build && cmake .. && cmake --build . --config Release
       copy Release\\mapf.exe src\\ha_lmapf\\global_tier\\solvers\\mapf_pibt2.exe
       copy Release\\mapd.exe src\\ha_lmapf\\global_tier\\solvers\\mapd_pibt2.exe

    2. Use in code:
       from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

       # For one-shot MAPF
       solver = PIBT2Solver(mode="one_shot")

       # For lifelong MAPF
       solver = PIBT2Solver(mode="lifelong")
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


class PIBT2Solver(BaseSolverWrapper):
    """
    Wrapper for the official PIBT2 C++ executables.

    PIBT2 (Priority Inheritance with Backtracking for Iterative MAPF)
    is a fast real-time solver optimized for large-scale scenarios.

    Cross-platform compatible:
    - Linux/macOS: Looks for 'mapf_pibt2' and 'mapd_pibt2' binaries
    - Windows: Looks for 'mapf_pibt2.exe' and 'mapd_pibt2.exe' binaries

    Supports two modes:
    - "one_shot" / "mapf": Uses the `mapf` executable for classical MAPF
    - "lifelong" / "mapd": Uses the `mapd` executable for lifelong MAPF

    Communication protocol:
    1. Write map file in MovingAI .map format (in maps/ subdirectory)
    2. Write instance file with map path, agents, starts, goals
    3. Execute PIBT2 binary with appropriate arguments
    4. Parse the output file

    Output format from PIBT2:
        solution=
        0:(x1,y1),(x2,y2),...
        1:(x1,y1),(x2,y2),...
        ...
    Where (x,y) = (col, row) for each agent at each timestep.
    """

    MIGRATION_DEPTH = "full"  # see BaseSolverWrapper.MIGRATION_DEPTH

    # Default binary names (platform-specific)
    DEFAULT_MAPF_BINARY_LINUX = "mapf_pibt2"
    DEFAULT_MAPF_BINARY_WINDOWS = "mapf_pibt2.exe"
    DEFAULT_MAPD_BINARY_LINUX = "mapd_pibt2"
    DEFAULT_MAPD_BINARY_WINDOWS = "mapd_pibt2.exe"

    @property
    def _default_mapf_binary(self) -> str:
        """Get the default MAPF binary name for the current platform."""
        return self.DEFAULT_MAPF_BINARY_WINDOWS if IS_WINDOWS else self.DEFAULT_MAPF_BINARY_LINUX

    @property
    def _default_mapd_binary(self) -> str:
        """Get the default MAPD binary name for the current platform."""
        return self.DEFAULT_MAPD_BINARY_WINDOWS if IS_WINDOWS else self.DEFAULT_MAPD_BINARY_LINUX

    def __init__(
            self,
            binary_path: Optional[str] = None,
            mapf_binary_path: Optional[str] = None,
            mapd_binary_path: Optional[str] = None,
            time_limit_sec: float = 10.0,
            verbose: int = 0,
            solver_name: str = "PIBT",
            mode: str = "auto",
    ) -> None:
        """
        Initialize the PIBT2 solver wrapper.

        Args:
            binary_path: Legacy path to a single pibt2 executable (for backward compatibility).
                        If provided, used for both modes.
            mapf_binary_path: Path to the mapf executable (for one-shot MAPF).
            mapd_binary_path: Path to the mapd executable (for lifelong MAPF).
            time_limit_sec: Time limit for the solver in seconds.
            verbose: Verbosity level (0 = silent, 1+ = verbose).
            solver_name: Solver algorithm within PIBT2 (e.g., "PIBT", "HCA", "WHCA").
            mode: Operating mode:
                  - "auto": Auto-detect based on experiment type (default)
                  - "one_shot" / "mapf": Use mapf executable
                  - "lifelong" / "mapd": Use mapd executable
        """
        self.time_limit_sec = time_limit_sec
        self.verbose = verbose
        self.solver_name = solver_name
        self.mode = mode.lower()

        # Find binaries
        if binary_path:
            # Legacy: single binary for both modes
            self.mapf_binary = binary_path
            self.mapd_binary = binary_path
        else:
            self.mapf_binary = self._find_mapf_binary(mapf_binary_path)
            self.mapd_binary = self._find_mapd_binary(mapd_binary_path)

        # For backward compatibility
        self.binary_path = self.mapf_binary

    def _find_mapf_binary(self, binary_path: Optional[str]) -> str:
        """Find the PIBT2 mapf executable for one-shot MAPF (cross-platform)."""
        # If a custom path is provided, use it (allows tests to verify path handling)
        if binary_path is not None:
            return binary_path

        solver_dir = os.path.dirname(__file__)

        # Platform-specific binary names to search
        if IS_WINDOWS:
            binary_names = ["mapf_pibt2.exe", "mapf_pibt2", "pibt2.exe", "pibt2_mapf.exe", "mapd_pibt2.exe"]
        else:
            binary_names = ["mapf_pibt2", "pibt2", "pibt2_mapf", "mapd_pibt2"]

        # Build search paths
        search_paths = []
        for name in binary_names:
            search_paths.extend([
                os.path.join(solver_dir, name),
                os.path.join(solver_dir, "pibt2", "build", name),
                os.path.join(solver_dir, "pibt2", "build", "Release", name),
                os.path.join("build", name),
                os.path.join("build", "Release", name),
                name,
                os.path.join(".", name),
            ])

        # Add legacy names
        legacy_names = ["pibt2.exe", "pibt2"] if IS_WINDOWS else ["pibt2"]
        for name in legacy_names:
            search_paths.append(os.path.join(solver_dir, name))

        for path in search_paths:
            if os.path.isfile(path):
                return path

        return os.path.join(solver_dir, self._default_mapf_binary)

    def _find_mapd_binary(self, binary_path: Optional[str]) -> str:
        """Find the PIBT2 mapd executable for lifelong MAPF (cross-platform)."""
        # If a custom path is provided, use it (allows tests to verify path handling)
        if binary_path is not None:
            return binary_path

        solver_dir = os.path.dirname(__file__)

        # Platform-specific binary names to search
        if IS_WINDOWS:
            binary_names = ["mapd_pibt2.exe", "mapd_pibt2", "mapd.exe", "pibt2_mapd.exe"]
        else:
            binary_names = ["mapd_pibt2", "mapd", "pibt2_mapd"]

        # Build search paths
        search_paths = []
        for name in binary_names:
            search_paths.extend([
                os.path.join(solver_dir, name),
                os.path.join(solver_dir, "pibt2", "build", name),
                os.path.join(solver_dir, "pibt2", "build", "Release", name),
                os.path.join("build", name),
                os.path.join("build", "Release", name),
                name,
                os.path.join(".", name),
            ])

        for path in search_paths:
            if os.path.isfile(path):
                return path

        return os.path.join(solver_dir, self._default_mapd_binary)

    def _select_binary(self, is_lifelong: bool) -> str:
        """Select the PIBT2 binary to invoke.

        Always returns ``mapf_pibt2`` in ``"auto"`` mode (the default),
        regardless of ``is_lifelong``.  Each replan from
        :class:`RollingHorizonPlanner` is a one-shot MAPF problem on
        the current snapshot of agent positions and assigned task
        goals; the lifelong loop is owned by the simulator, not by
        the binary.  ``mapd_pibt2`` would generate its own synthetic
        task stream and emit MAPD-format output the wrapper's parser
        cannot read — see ``docs/PIBT2_DIAGNOSIS.md``.

        Explicit ``mode="mapd"`` / ``mode="lifelong"`` is preserved
        as an escape hatch for future stand-alone MAPD experiments
        outside the rolling-horizon framework.
        """
        if self.mode in {"lifelong", "mapd"}:
            return self.mapd_binary
        elif self.mode in {"one_shot", "mapf", "oneshot"}:
            return self.mapf_binary
        else:  # "auto" — always MAPF; see docstring above.
            del is_lifelong  # accepted for API compatibility, intentionally ignored
            return self.mapf_binary

    def plan(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
            is_lifelong: bool = False,
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
            is_lifelong: bool = False,
    ) -> SolverResult:
        """SolverResult-returning entry point for PIBT2.

        Anytime: PIBT2 honours ``max_comp_time`` natively and may
        return its best-so-far solution at the budget cutoff; the
        decision tree records ``partial_anytime`` when this happens.
        """
        active_agents = self._get_active_agents(agents, assignments)
        if not active_agents:
            return SolverResult(
                plan=PlanBundle(paths={}, created_step=step, horizon=horizon),
                status="complete",
                solver_wall_ms=0.0,
                end_to_end_wall_ms=0.0,
            )

        binary = self._select_binary(is_lifelong)

        tmpdir = tempfile.mkdtemp(prefix="pibt2_")
        try:
            maps_dir = os.path.join(tmpdir, "maps")
            os.makedirs(maps_dir, exist_ok=True)
            map_path = os.path.join(maps_dir, "map.map")
            instance_path = os.path.join(tmpdir, "instance.txt")
            result_path = os.path.join(tmpdir, "result.txt")
            self._write_map_file(env, map_path)
            agent_order = self._write_instance_file(
                env, agents, assignments, active_agents,
                instance_path, map_path, horizon,
            )
            cmd = [
                binary,
                "-i", instance_path,
                "-o", result_path,
                "-s", self.solver_name,
            ]
            if self.verbose > 0:
                cmd.append("-v")

            def parse_fn(stdout: str, stderr: str, returncode: int):
                paths = None
                err = None
                # PIBT2 writes ``solved=0`` when the full MAPF instance
                # didn't terminate within ``max_timestep``, but the
                # result file still contains the ``solution=`` block
                # PIBT2 had at the cutoff.  For the rolling-horizon
                # framework only the first ``horizon`` ticks are needed
                # and those are usually valid progress toward goals —
                # see docs/PIBT2_DIAGNOSIS.md §"Residual…" for the
                # root-cause and rolling-horizon-prefix rationale.
                # We therefore always attempt to parse; on
                # ``solved=0`` we surface the resulting plan as
                # ``partial_anytime`` so the rolling-horizon planner
                # counts it under ``solver_partial_returns`` instead of
                # ``solver_errors``.
                status_hint: Optional[str] = None
                solved_zero = False
                if os.path.exists(result_path):
                    try:
                        with open(result_path, "r") as f:
                            content = f.read()
                        solved_zero = "solved=0" in content
                        parsed = self._parse_result_file(
                            result_path, agent_order, step, horizon,
                        )
                        if parsed and not [
                            a for a in agent_order if a not in parsed
                        ]:
                            paths = parsed
                            if solved_zero:
                                status_hint = "partial_anytime"
                                err = (
                                    "PIBT2 solved=0; using rolling-horizon "
                                    f"prefix (H={horizon})"
                                )
                        elif parsed:
                            err = (
                                f"partial parse: {len(parsed)}/"
                                f"{len(agent_order)} active agents got paths"
                            )
                            if solved_zero:
                                err = f"PIBT2 solved=0; {err}"
                        else:
                            err = (
                                "PIBT2 solved=0 and result file unparseable"
                                if solved_zero
                                else "no paths parsed from result file"
                            )
                    except Exception as exc:  # noqa: BLE001
                        err = f"parse error: {exc}"
                else:
                    err = "result file not produced"
                # PIBT2 writes ``comp_time=<ms>`` in the result file
                # (milliseconds, integer) when solved.
                solver_wall_ms = math.nan
                if os.path.exists(result_path):
                    try:
                        with open(result_path, "r") as f:
                            content = f.read(4096)
                        m = re.search(r"comp_time\s*=\s*([0-9.]+)", content)
                        if m:
                            solver_wall_ms = float(m.group(1))
                    except Exception:
                        pass
                return paths, solver_wall_ms, err, status_hint

            return self._wrap_subprocess(
                cmd=cmd,
                timeout_s=float(self.time_limit_sec),
                parse_fn=parse_fn,
                agents=agents,
                active_agents=active_agents,
                start_step=step,
                horizon=horizon,
                binary_path=binary,
                watchdog_buffer_s=5.0,
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
        """Get list of agents that need planning (have goals)."""
        active = []
        for aid, agent in agents.items():
            # Agent has a current goal (from assignment or ongoing task)
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

    def _write_instance_file(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            active_agents: List[int],
            instance_path: str,
            map_path: str,
            horizon: int,
    ) -> List[int]:
        """Write PIBT2 instance file in Kei18/pibt2's expected format.

        Format (verified against Kei18/pibt2 ``Problem.cpp``):

            map_file=<path>
            agents=<count>
            seed=<value>
            random_problem=0
            max_timestep=max(horizon + 50, 2 * (env.height + env.width))
            max_comp_time=<milliseconds>
            <start_x>,<start_y>,<goal_x>,<goal_y>     ← one line per agent
            <start_x>,<start_y>,<goal_x>,<goal_y>
            …

        Coordinates are in PIBT2's ``(x, y) = (col, row)`` convention
        (matching the MovingAI ``.map`` file orientation that the
        binary uses internally).

        The earlier wrapper format wrote ``starts=(x,y),...`` and
        ``goals=(x,y),...`` lines which Kei18/pibt2's parser does
        NOT recognize (its scenario-line regex is
        ``(\\d+),(\\d+),(\\d+),(\\d+)``); the binary silently fell
        back to seeded random scenario generation, producing plans
        that bore no relation to the simulator's actual agents.
        See ``docs/PIBT2_DIAGNOSIS.md`` for the full root-cause
        analysis.

        Returns:
            List of agent IDs in the order they appear in the
            scenario block.  The wrapper's ``_parse_result_file``
            uses this ordering to map PIBT2's positional output
            columns back to the original ``AgentState`` keys.
        """
        agent_order: List[int] = []
        scenario_lines: List[str] = []

        for aid in active_agents:
            agent = agents[aid]
            start = agent.pos  # (row, col)

            # Determine goal
            if agent.goal is not None:
                goal = agent.goal
            elif aid in assignments:
                goal = assignments[aid].goal
            else:
                goal = start  # WAIT

            # PIBT2 uses (x, y) = (col, row); per-line scenario record.
            sx, sy = start[1], start[0]
            gx, gy = goal[1], goal[0]
            scenario_lines.append(f"{sx},{sy},{gx},{gy}")
            agent_order.append(aid)

        with open(instance_path, 'w') as f:
            f.write(f"map_file={map_path}\n")
            f.write(f"agents={len(agent_order)}\n")
            f.write(f"seed=0\n")
            f.write(f"random_problem=0\n")
            # ``horizon`` is the simulator's per-replan execution window
            # (typically 20 steps; the simulator executes that many before
            # the next replan).  PIBT2's ``max_timestep`` is the full-plan
            # length budget — PIBT2 is all-or-nothing and returns
            # ``solved=0`` when any agent's path to its goal exceeds this
            # value, even if the instance is trivially feasible.  The two
            # are distinct concepts; conflating them caused PIBT2 to fail
            # every replan on warehouse-scale maps where agent trips can
            # exceed the rolling-horizon window.  ``2 * (env.height +
            # env.width)`` is a generous upper bound for any straight-line
            # trip on a rectangular grid (twice the diameter, leaving room
            # for detours around obstacles).  The ``max(horizon + 50, ...)``
            # floor preserves the previous behaviour for tiny test maps
            # where the dimension-based formula would be smaller.  See
            # ``docs/ALLOCATOR_DIAGNOSIS.md`` for the empirical analysis
            # that distinguished this Mode-A budget mismatch from the
            # Mode-B priority-scheme deadlock on confined corridors.
            #
            # ``max_comp_time`` (separate field, in ms) bounds wall-clock;
            # a generous ``max_timestep`` does NOT let PIBT2 run forever.
            max_timestep = max(horizon + 50, 2 * (env.height + env.width))
            f.write(f"max_timestep={max_timestep}\n")
            f.write(f"max_comp_time={int(self.time_limit_sec * 1000)}\n")
            for line in scenario_lines:
                f.write(line + "\n")

        return agent_order

    def _run_pibt2(
            self,
            binary: str,
            instance_path: str,
            result_path: str,
    ) -> bool:
        """
        Execute the PIBT2 binary.

        Args:
            binary: Path to the executable (mapf or mapd)
            instance_path: Path to the instance file
            result_path: Path to write results

        Returns:
            True if execution was successful, False otherwise
        """
        if not os.path.isfile(binary):
            binary_type = "mapd" if "mapd" in binary else "mapf"
            print(f"[PIBT2] ERROR: {binary_type} binary not found at {binary}")
            print(f"[PIBT2] Please build PIBT2 from https://github.com/Kei18/pibt2")
            if IS_WINDOWS:
                print(
                    f"[PIBT2] For Windows: copy build\\Release\\{binary_type}.exe to solvers\\{binary_type}_pibt2.exe")
            else:
                print(f"[PIBT2] For Linux/macOS: copy build/{binary_type} to solvers/{binary_type}_pibt2")
            return False

        cmd = [
            binary,
            "-i", instance_path,
            "-o", result_path,
            "-s", self.solver_name,
        ]

        if self.verbose > 0:
            cmd.append("-v")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.time_limit_sec + 5,  # Extra buffer
            )

            if result.returncode != 0:
                if self.verbose > 0:
                    print(f"[PIBT2] Solver returned code {result.returncode}")
                    print(f"[PIBT2] stderr: {result.stderr}")
                return False

            return True

        except subprocess.TimeoutExpired:
            print(f"[PIBT2] Solver timed out after {self.time_limit_sec}s")
            return False
        except FileNotFoundError:
            print(f"[PIBT2] Binary not found: {binary}")
            return False
        except Exception as e:
            print(f"[PIBT2] Execution error: {e}")
            return False

    def _parse_result_file(
            self,
            result_path: str,
            agent_order: List[int],
            start_step: int,
            horizon: int,
    ) -> Dict[int, TimedPath]:
        """
        Parse PIBT2 result output.

        Format:
            instance=...
            agents=...
            solved=1
            ...
            solution=
            0:(x1,y1),(x2,y2),...
            1:(x1,y1),(x2,y2),...
            ...

        Where (x,y) = (col, row) for each agent.
        """
        paths: Dict[int, TimedPath] = {}

        try:
            with open(result_path, 'r') as f:
                content = f.read()

            # NOTE: do NOT early-return on ``solved=0``.  PIBT2 writes a
            # ``solution=`` block of agent positions up to the cutoff
            # even when it couldn't drive every agent to its goal.  For
            # the rolling-horizon framework only the first
            # ``horizon`` ticks are needed, and the caller
            # (``plan_with_metadata``) tags this case as
            # ``status="partial_anytime"`` rather than ``"error"``.
            # See docs/PIBT2_DIAGNOSIS.md §"Residual…" for details.


            # Find solution section
            if "solution=" not in content:
                print("[PIBT2] No solution found in result file")
                return paths

            # Extract solution lines
            solution_start = content.index("solution=") + len("solution=")
            solution_text = content[solution_start:].strip()

            # Parse timestep lines
            # Each line: "t:(x1,y1),(x2,y2),..."
            agent_paths: Dict[int, List[Cell]] = {aid: [] for aid in agent_order}

            for line in solution_text.split('\n'):
                line = line.strip()
                if not line or ':' not in line:
                    continue

                # Parse "t:(x1,y1),(x2,y2),..."
                match = re.match(r'^(\d+):(.+)$', line)
                if not match:
                    continue

                timestep = int(match.group(1))
                coords_str = match.group(2)

                # Extract all (x,y) pairs
                coord_pattern = r'\((\d+),(\d+)\)'
                coords = re.findall(coord_pattern, coords_str)

                if len(coords) != len(agent_order):
                    # Mismatch in agent count
                    continue

                for idx, (x_str, y_str) in enumerate(coords):
                    col = int(x_str)
                    row = int(y_str)
                    cell = (row, col)  # Convert to (row, col) format

                    aid = agent_order[idx]
                    agent_paths[aid].append(cell)

            # Create TimedPath objects
            for aid, cells in agent_paths.items():
                if cells:
                    # Pad or truncate to horizon+1
                    if len(cells) < horizon + 1:
                        # Pad with last position
                        cells = cells + [cells[-1]] * (horizon + 1 - len(cells))
                    elif len(cells) > horizon + 1:
                        cells = cells[:horizon + 1]

                    paths[aid] = TimedPath(cells=cells, start_step=start_step)

        except Exception as e:
            print(f"[PIBT2] Error parsing result file: {e}")

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


# Alias for backward compatibility
PIBTCppPlanner = PIBT2Solver
PIBT2CppPlanner = PIBT2Solver
