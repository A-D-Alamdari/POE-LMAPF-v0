"""
Real-Time LaCAM — Persistent DFS with Rerooting.

This module implements the Real-Time LaCAM algorithm: instead of restarting
LaCAM from scratch at every control cycle, a single persistent DFS tree is
kept alive across iterations.  At each tick the tree is expanded for a bounded
wall-clock budget, the best partial path from frontier to root is extracted,
only the *first* step is executed, and the tree is *rerooted* at the executed
child configuration.  This is the mechanism that prevents the deadlock /
livelock behaviour of naive "replan-from-scratch" real-time use.

Successor generation uses the **C++ LaCAM binary** (lacam or lacam3) which
internally uses PIBT as its one-step generator.  A single subprocess call
produces a multi-step path that is then inserted as a chain of nodes into
the persistent DFS tree — orders of magnitude faster than pure-Python PIBT.

Algorithm (paper pseudocode):
    initialise persistent tree at start config C0
    root <- start;  frontier <- root
    while root is not goal:
        continue LaCAM DFS from frontier for dt ms
        P <- backtrack from frontier to root
        execute first edge on P:  root -> next
        reroot tree at next

Key data structures
-------------------
RTNode              - one node in the persistent DFS tree (joint configuration).
RTLaCAMState        - mutable state: root, frontier, DFS stack, config->node map.
LaCAMBulkEngine     - C++ LaCAM binary wrapper for multi-step successor generation.
PIBTEngine          - pure-Python PIBT fallback (used when C++ binary unavailable).
RTLaCAMPlanner      - core planner with plan_for_ms / execute_one_step / reroot.
RealTimeLaCAMSolver - GlobalPlanner-protocol wrapper used by the simulator.

References
----------
Keisuke Okumura - "LaCAM: Search-Based Algorithm for Quick Multi-Agent
Pathfinding" (2023) and subsequent real-time extensions.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from ha_lmapf.core.grid import manhattan, in_bounds
from ha_lmapf.core.types import AgentState, PlanBundle, Task, TimedPath
from ha_lmapf.core.types import SolverResult  # noqa: E501
from ha_lmapf.global_tier.solvers._base import BaseSolverWrapper

Cell = Tuple[int, int]
# A joint configuration is an ordered tuple of cells, one per agent.
Config = Tuple[Cell, ...]


# ---------------------------------------------------------------------------
#  DFS tree node
# ---------------------------------------------------------------------------

@dataclass
class RTNode:
    """One node in the persistent Real-Time LaCAM DFS tree."""

    config: Config
    parent: Optional[RTNode] = None
    children: List[RTNode] = field(default_factory=list)

    # Lazy DFS bookkeeping ---------------------------------------------------
    expanded: bool = False
    # How many successor branches have been attempted so far.
    next_branch_index: int = 0
    on_stack: bool = False

    # Configs that were already generated as successors of this node.
    # Used for revisit handling: if PIBT produces a config we already tried
    # we bump the constraint / priority order and regenerate.
    tried_successors: Set[Config] = field(default_factory=set)

    depth: int = 0


# ---------------------------------------------------------------------------
#  Persistent planner state
# ---------------------------------------------------------------------------

class RTLaCAMState:
    """Mutable persistent state for the Real-Time LaCAM DFS."""

    def __init__(self) -> None:
        self.root: Optional[RTNode] = None
        self.frontier: Optional[RTNode] = None
        self.dfs_stack: List[RTNode] = []
        # config -> list of nodes that share it (identity is by *node*, not config)
        self.nodes_by_config: Dict[Config, List[RTNode]] = defaultdict(list)
        # Path from root to frontier (populated by rebuild_current_path)
        self.current_path: List[RTNode] = []
        self.solved: bool = False
        self.total_nodes: int = 0


# ---------------------------------------------------------------------------
#  C++ LaCAM bulk successor generator
# ---------------------------------------------------------------------------

class LaCAMBulkEngine:
    """
    Uses the official C++ LaCAM binary to generate a multi-step path in a
    single subprocess call via the proven .map/.scen protocol.

    LaCAM internally uses PIBT as its one-step configuration generator,
    so running it with a short time limit effectively produces high-quality
    PIBT-backed paths very quickly.  One subprocess call yields a full
    sequence of joint configurations that can then be inserted as a chain
    of nodes into the persistent DFS tree.

    Note: The PIBT2 binary (mapf_pibt2) ignores user-specified starts/goals,
    so we use the LaCAM binary which properly supports custom .scen files.
    """

    def __init__(
            self,
            env,
            agent_ids: List[int],
            binary_path: Optional[str] = None,
            time_limit_sec: float = 1.0,
            verbose: int = 0,
    ):
        self.env = env
        self.agent_ids = agent_ids
        self.n = len(agent_ids)
        self.time_limit_sec = time_limit_sec
        self.verbose = verbose
        self.binary_path = binary_path or self._find_binary()

    def _find_binary(self) -> str:
        """Locate the LaCAM binary (v1 preferred for speed)."""
        solver_dir = os.path.dirname(__file__)
        # Prefer lacam v1 (fast, returns immediately after finding solution)
        # over lacam3 (anytime, spends extra time on refinement)
        candidates = [
            os.path.join(solver_dir, "lacam"),
            os.path.join(solver_dir, "lacam3"),
            os.path.join(solver_dir, "lacam_official"),
            "lacam",
            "lacam3",
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return os.path.join(solver_dir, "lacam3")

    @property
    def available(self) -> bool:
        return os.path.isfile(self.binary_path)

    def generate_path(
            self,
            starts: Config,
            goals: Dict[int, Cell],
            max_timestep: int = 100,
    ) -> List[Config]:
        """
        Run C++ LaCAM once and return the full sequence of joint configs.

        Returns:
            List of Configs [C0, C1, ..., Ct] where C0 = starts.
            Returns [starts] on failure.
        """
        if not self.available:
            return [starts]

        with tempfile.TemporaryDirectory() as tmpdir:
            map_path = os.path.join(tmpdir, "map.map")
            scen_path = os.path.join(tmpdir, "agents.scen")
            result_path = os.path.join(tmpdir, "result.txt")

            self._write_map(map_path)
            self._write_scen(scen_path, starts, goals, "map.map")

            ok = self._run(map_path, scen_path, result_path)
            if ok and os.path.exists(result_path):
                configs = self._parse(result_path)
                if configs:
                    return configs

        return [starts]

    # -- file I/O -----------------------------------------------------------

    def _write_map(self, path: str) -> None:
        with open(path, "w") as f:
            f.write("type octile\n")
            f.write(f"height {self.env.height}\n")
            f.write(f"width {self.env.width}\n")
            f.write("map\n")
            for r in range(self.env.height):
                row = ""
                for c in range(self.env.width):
                    row += "@" if self.env.is_blocked((r, c)) else "."
                f.write(row + "\n")

    def _write_scen(
            self,
            path: str,
            starts: Config,
            goals: Dict[int, Cell],
            map_filename: str,
    ) -> None:
        """Write MovingAI .scen format (same as lacam_official_wrapper)."""
        with open(path, "w") as f:
            f.write("version 1\n")
            for i, aid in enumerate(self.agent_ids):
                sr, sc = starts[i]
                g = goals.get(aid, starts[i])
                gr, gc = g
                # .scen format: bucket map width height start_col start_row goal_col goal_row dist
                f.write(
                    f"0\t{map_filename}\t{self.env.width}\t{self.env.height}\t"
                    f"{sc}\t{sr}\t{gc}\t{gr}\t0.0\n"
                )

    def _run(
            self, map_path: str, scen_path: str, result_path: str
    ) -> bool:
        cmd = [
            self.binary_path,
            "-m", map_path,
            "-i", scen_path,
            "-N", str(self.n),
            "-o", result_path,
            "-t", str(self.time_limit_sec),
            "-v", "0",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.time_limit_sec + 5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            if self.verbose > 0:
                print(f"[RT-LaCAM/cpp] {e}")
            return False

    def _parse(self, result_path: str) -> List[Config]:
        """Parse LaCAM result.txt → list of Configs."""
        try:
            with open(result_path) as f:
                content = f.read()
            if "solution=" not in content:
                return []
            sol_start = content.index("solution=") + len("solution=")
            sol_text = content[sol_start:].strip()

            steps: Dict[int, Config] = {}
            for line in sol_text.split("\n"):
                line = line.strip()
                if not line or ":" not in line:
                    continue
                m = re.match(r"^(\d+):(.+)$", line)
                if not m:
                    continue
                t = int(m.group(1))
                coords = re.findall(r"\((\d+),(\d+)\)", m.group(2))
                if len(coords) != self.n:
                    continue
                # LaCAM output: (col, row) → convert to (row, col)
                cfg = tuple((int(y), int(x)) for x, y in coords)
                steps[t] = cfg

            if not steps:
                return []
            return [steps[t] for t in sorted(steps)]
        except Exception as e:
            if self.verbose > 0:
                print(f"[RT-LaCAM/cpp] parse error: {e}")
            return []


# ---------------------------------------------------------------------------
#  Python PIBT fallback (used when C++ binary unavailable)
# ---------------------------------------------------------------------------

class PIBTEngine:
    """
    Pure-Python PIBT — priority-inheritance with backtracking.

    Used as a fallback when the C++ PIBT2 binary is not available.
    Significantly slower than the C++ version.
    """

    _DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    def __init__(self, env, goals: Dict[int, Cell], agent_ids: List[int]):
        self.env = env
        self.goals = goals
        self.agent_ids = agent_ids
        self.n = len(agent_ids)

    def generate(
            self,
            config: Config,
            order: List[int],
            rng: np.random.Generator,
    ) -> Config:
        """Run PIBT once with the given priority order. Returns successor config."""
        next_pos: List[Optional[Cell]] = [None] * self.n
        claimed: Dict[Cell, int] = {}

        def _neighbours(cell: Cell) -> List[Cell]:
            r, c = cell
            out: List[Cell] = [(r, c)]
            dirs = list(self._DIRS)
            rng.shuffle(dirs)
            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                if in_bounds((nr, nc), self.env.width, self.env.height):
                    if not self.env.is_blocked((nr, nc)):
                        out.append((nr, nc))
            return out

        def _resolve(idx: int, depth: int) -> bool:
            if next_pos[idx] is not None:
                return True
            if depth > self.n:
                return False
            cur = config[idx]
            goal = self.goals.get(self.agent_ids[idx], cur)
            candidates = _neighbours(cur)
            candidates.sort(key=lambda c: manhattan(c, goal))

            for cand in candidates:
                if cand in claimed:
                    continue
                # edge-swap check
                swap = False
                for j in range(self.n):
                    if (j != idx and next_pos[j] is not None
                            and next_pos[j] == cur and config[j] == cand):
                        swap = True
                        break
                if swap:
                    continue
                # push blocker
                blocker = None
                for j in range(self.n):
                    if j != idx and config[j] == cand and next_pos[j] is None:
                        blocker = j
                        break
                if blocker is not None:
                    claimed[cand] = idx
                    ok = _resolve(blocker, depth + 1)
                    if ok and claimed.get(cand) == idx and next_pos[blocker] != cand:
                        next_pos[idx] = cand
                        return True
                    if claimed.get(cand) == idx:
                        del claimed[cand]
                    continue
                next_pos[idx] = cand
                claimed[cand] = idx
                return True

            if cur not in claimed:
                next_pos[idx] = cur
                claimed[cur] = idx
                return True
            return False

        for i in order:
            _resolve(i, 0)
        for i in range(self.n):
            if next_pos[i] is None:
                next_pos[i] = config[i]
        return tuple(next_pos)  # type: ignore[arg-type]

    def generate_with_alternatives(
            self,
            config: Config,
            forbidden: Set[Config],
            rng: np.random.Generator,
            max_attempts: int = 10,
    ) -> Optional[Config]:
        for attempt in range(max_attempts):
            if attempt == 0:
                order = sorted(
                    range(self.n),
                    key=lambda i: -manhattan(
                        config[i],
                        self.goals.get(self.agent_ids[i], config[i]),
                    ),
                )
            else:
                order = list(range(self.n))
                rng.shuffle(order)
            result = self.generate(config, order, rng)
            if result not in forbidden:
                return result
        order = list(range(self.n))
        return self.generate(config, order, rng)


# ---------------------------------------------------------------------------
#  Core Real-Time LaCAM planner (persistent DFS + rerooting)
# ---------------------------------------------------------------------------

class RTLaCAMPlanner:
    """
    Persistent-DFS Real-Time LaCAM.

    Uses C++ PIBT2 for bulk path generation (fast) and falls back to
    pure-Python PIBT only when the binary is unavailable.

    The DFS tree persists across plan() calls.  Each call:
    1.  Generates a multi-step PIBT path via C++ binary.
    2.  Inserts the config sequence as a chain into the tree.
    3.  Extracts the partial path from root to frontier.
    4.  execute_one_step() reroots the tree.
    """

    _MAX_NODES = 100_000

    def __init__(
            self,
            env,
            agent_ids: List[int],
            goals: Dict[int, Cell],
            start_config: Config,
            rng: Optional[np.random.Generator] = None,
            verbose: int = 0,
            lacam_binary: Optional[str] = None,
            lacam_time_limit: float = 1.0,
    ) -> None:
        self.env = env
        self.agent_ids = agent_ids
        self.goals = dict(goals)
        self.n = len(agent_ids)
        self.rng = rng if rng is not None else np.random.default_rng()
        self.verbose = verbose

        # C++ PIBT2 engine (preferred)
        self.lacam_cpp = LaCAMBulkEngine(
            env=env,
            agent_ids=agent_ids,
            binary_path=lacam_binary,
            time_limit_sec=lacam_time_limit,
            verbose=verbose,
        )

        # Python PIBT fallback
        self.pibt_py = PIBTEngine(env, self.goals, agent_ids)

        self._use_cpp = self.lacam_cpp.available
        if self._use_cpp and self.verbose > 0:
            print(f"[RT-LaCAM] Using C++ LaCAM: {self.lacam_cpp.binary_path}")
        elif self.verbose > 0:
            print("[RT-LaCAM] C++ LaCAM not found, using Python PIBT fallback")

        self.S = RTLaCAMState()
        self._initialise(start_config)

    # -- public API ---------------------------------------------------------

    def finished(self) -> bool:
        return self.S.solved

    def current_config(self) -> Config:
        assert self.S.root is not None
        return self.S.root.config

    def plan_for_ms(self, budget_ms: int, max_timestep: int = 100) -> None:
        """
        Continue the persistent DFS for at most *budget_ms* wall-clock ms.

        If C++ LaCAM is available, runs a single subprocess call to get a
        multi-step path, then inserts the entire sequence into the tree.
        Falls back to per-step Python PIBT expansion otherwise.

        Args:
            budget_ms: Wall-clock time budget in milliseconds.
            max_timestep: Maximum path length for C++ LaCAM call.
        """
        if self._use_cpp:
            self._expand_via_cpp(budget_ms, max_timestep=max_timestep)
        else:
            self._expand_via_python(budget_ms)

        self._rebuild_current_path()

    def has_next_move(self) -> bool:
        return len(self.S.current_path) >= 2

    def next_config(self) -> Config:
        if self.has_next_move():
            return self.S.current_path[1].config
        assert self.S.root is not None
        return self.S.root.config

    def execute_one_step(self) -> None:
        """Commit the first step and reroot the tree."""
        if not self.has_next_move():
            return
        child = self.S.current_path[1]
        self._reroot_at(child)
        # solved reflects the ROOT's state, not the tree's exploration.
        self.S.solved = self._is_goal(self.S.root.config)

    # -- goal / config updates (lifelong MAPF) ------------------------------

    def update_goals(self, new_goals: Dict[int, Cell]) -> None:
        old_goals = self.goals
        self.goals = dict(new_goals)
        self.pibt_py.goals = self.goals
        if self.S.root is not None:
            self.S.solved = self._is_goal(self.S.root.config)
        # If goals changed, clear existing children chain so _expand_via_cpp
        # will call C++ fresh with the new goals instead of walking stale paths.
        if old_goals != self.goals and self.S.root is not None:
            self.S.root.children.clear()
            self.S.root.tried_successors.clear()

    def update_config(self, actual: Config) -> None:
        """Handle execution deviation."""
        if self.S.root is not None and self.S.root.config == actual:
            return
        existing = self.S.nodes_by_config.get(actual)
        if existing:
            self._reroot_at(existing[0])
        else:
            self._initialise(actual)

    # -- private: initialisation --------------------------------------------

    def _initialise(self, start_config: Config) -> None:
        root = RTNode(config=start_config, depth=0)
        self.S.root = root
        self.S.frontier = root
        self.S.dfs_stack = [root]
        root.on_stack = True
        self.S.nodes_by_config.clear()
        self.S.nodes_by_config[start_config].append(root)
        self.S.total_nodes = 1
        self.S.current_path = [root]
        self.S.solved = self._is_goal(start_config)

    # -- private: C++ LaCAM bulk expansion ------------------------------------

    def _expand_via_cpp(self, budget_ms: int, max_timestep: int = 100) -> None:
        """
        Use C++ LaCAM to expand the persistent DFS tree.

        Strategy:
        1.  If the tree already has a deep path from root (existing children
            chain) that progresses toward current goals, walk it.
        2.  Otherwise, call C++ LaCAM fresh with current goals.
        """
        assert self.S.root is not None

        # Step 1: Walk existing tree children, but validate they progress
        # toward current goals (not stale from a previous goal set).
        deepest = self._walk_deepest_child_chain(self.S.root)
        if deepest is not self.S.root:
            # Validate: does the chain make progress toward current goals?
            root_dist = self._goal_distance(self.S.root.config)
            deep_dist = self._goal_distance(deepest.config)
            if deep_dist < root_dist:
                self.S.frontier = deepest
                return
            # Chain goes wrong direction — prune it and call C++ fresh
            self.S.root.children.clear()

        # Step 2: Call C++ LaCAM with current goals.
        root_config = self.S.root.config
        configs = self.lacam_cpp.generate_path(
            starts=root_config,
            goals=self.goals,
            max_timestep=max_timestep,
        )

        if len(configs) <= 1:
            self._expand_via_python(budget_ms)
            return

        # Insert the config chain: root → c1 → c2 → ... → cN
        parent_node = self.S.root
        for cfg in configs[1:]:
            parent_node.tried_successors.add(cfg)

            if cfg in self.S.nodes_by_config:
                # Config already explored — stop inserting here
                break

            child = RTNode(
                config=cfg,
                parent=parent_node,
                depth=parent_node.depth + 1,
            )
            parent_node.children.append(child)
            self.S.nodes_by_config[cfg].append(child)
            self.S.total_nodes += 1

            child.on_stack = True
            self.S.dfs_stack.append(child)
            self.S.frontier = child
            parent_node = child

            if self._is_goal(cfg):
                break

        self._maybe_prune()

    def _walk_deepest_child_chain(self, node: RTNode) -> RTNode:
        """
        Walk the first-child chain from *node* to the deepest descendant.
        Used to recover the existing forward path after rerooting.
        """
        cur = node
        visited: Set[int] = {id(cur)}
        while cur.children:
            # Pick the first child that isn't the old root (avoid going backwards).
            # After rerooting, old_root is appended as last child.
            next_child = None
            for c in cur.children:
                cid = id(c)
                if cid not in visited:
                    next_child = c
                    break
            if next_child is None:
                break
            visited.add(id(next_child))
            cur = next_child
        return cur

    # -- private: Python PIBT fallback expansion ----------------------------

    def _expand_via_python(self, budget_ms: int) -> None:
        """Per-step Python PIBT expansion (slow fallback)."""
        deadline = time.monotonic() + budget_ms / 1000.0
        iters = 0
        cap = 50_000

        while time.monotonic() < deadline and not self.S.solved and iters < cap:
            self._expand_one_python()
            iters += 1

        if self.verbose > 0:
            print(
                f"[RT-LaCAM/py] {iters} expansions in {budget_ms}ms  "
                f"tree={self.S.total_nodes}"
            )

    def _expand_one_python(self) -> None:
        """Single lazy-DFS expansion step using Python PIBT."""
        if not self.S.dfs_stack:
            return

        cur = self.S.dfs_stack[-1]
        self.S.frontier = cur

        if self._is_goal(cur.config):
            self.S.solved = True
            return

        forbidden = cur.tried_successors
        succ_config = self.pibt_py.generate_with_alternatives(
            cur.config, forbidden, self.rng, max_attempts=5,
        )

        if succ_config is not None and succ_config not in cur.tried_successors:
            cur.tried_successors.add(succ_config)
            cur.next_branch_index += 1

            if succ_config in self.S.nodes_by_config:
                return

            child = RTNode(
                config=succ_config,
                parent=cur,
                depth=cur.depth + 1,
            )
            cur.children.append(child)
            self.S.nodes_by_config[succ_config].append(child)
            self.S.total_nodes += 1

            child.on_stack = True
            self.S.dfs_stack.append(child)
            self.S.frontier = child

            self._maybe_prune()
        else:
            cur.expanded = True
            cur.on_stack = False
            self.S.dfs_stack.pop()
            if self.S.dfs_stack:
                self.S.frontier = self.S.dfs_stack[-1]

    # -- private: path extraction -------------------------------------------

    def _rebuild_current_path(self) -> None:
        """Backtrack from *frontier* to *root* to obtain the partial path."""
        path: List[RTNode] = []
        node = self.S.frontier
        seen: Set[int] = set()
        while node is not None:
            nid = id(node)
            if nid in seen:
                break
            seen.add(nid)
            path.append(node)
            if node is self.S.root:
                break
            node = node.parent
        path.reverse()
        self.S.current_path = path

    # -- private: rerooting -------------------------------------------------

    def _reroot_at(self, child: RTNode) -> None:
        """Reverse the parent edge so *child* becomes the new tree root."""
        old_root = self.S.root
        assert old_root is not None

        if child in old_root.children:
            old_root.children.remove(child)
        child.parent = None
        old_root.parent = child
        child.children.append(old_root)
        self.S.root = child

        new_stack: List[RTNode] = []
        for node in self.S.dfs_stack:
            if self._is_descendant_of(node, child):
                new_stack.append(node)
        if not new_stack or new_stack[0] is not child:
            new_stack.insert(0, child)
        self.S.dfs_stack = new_stack

    # -- private: helpers ---------------------------------------------------

    def _is_goal(self, config: Config) -> bool:
        for i, aid in enumerate(self.agent_ids):
            goal = self.goals.get(aid)
            if goal is not None and config[i] != goal:
                return False
        return True

    def _goal_distance(self, config: Config) -> int:
        """Sum of Manhattan distances from each agent to its goal."""
        total = 0
        for i, aid in enumerate(self.agent_ids):
            goal = self.goals.get(aid)
            if goal is not None:
                total += manhattan(config[i], goal)
        return total

    def _is_descendant_of(self, node: RTNode, ancestor: RTNode) -> bool:
        cur: Optional[RTNode] = node
        seen: Set[int] = set()
        while cur is not None:
            nid = id(cur)
            if nid in seen:
                return False
            seen.add(nid)
            if cur is ancestor:
                return True
            cur = cur.parent
        return False

    def _maybe_prune(self) -> None:
        if self.S.total_nodes <= self._MAX_NODES:
            return
        keep: Set[int] = set()
        for n in self.S.dfs_stack:
            keep.add(id(n))
            for c in n.children:
                keep.add(id(c))
        new_map: Dict[Config, List[RTNode]] = defaultdict(list)
        kept = 0
        for cfg, nodes in self.S.nodes_by_config.items():
            alive = [n for n in nodes if id(n) in keep]
            if alive:
                new_map[cfg] = alive
                kept += len(alive)
        self.S.nodes_by_config = new_map
        self.S.total_nodes = kept


# ---------------------------------------------------------------------------
#  GlobalPlanner-protocol wrapper
# ---------------------------------------------------------------------------

class RealTimeLaCAMSolver(BaseSolverWrapper):
    """
    ``GlobalPlanner``-compatible wrapper around ``RTLaCAMPlanner``.

    Each ``plan()`` call:
    1.  Re-initialises the planner if the agent set changed.
    2.  Updates goals and the root config (handles execution deviation).
    3.  Runs bounded planning via C++ PIBT2 (or Python fallback).
    4.  Extracts paths of length ``horizon + 1`` by iteratively
        plan-and-step'ing the internal planner.
    5.  Returns a ``PlanBundle``.

    The persistent DFS tree is kept across ``plan()`` invocations, which is
    the whole point: each replan continues the *same* search.
    """

    def __init__(
            self,
            time_limit_ms: int = 10000,
            verbose: int = 0,
            lacam_binary: Optional[str] = None,
    ) -> None:
        """
        Args:
            time_limit_ms: Total wall-clock budget per ``plan()`` call (ms).
                Default 10000 ms = 10.0 s, matching the paper §5.1 uniform
                per-replan budget.  RT-LaCAM is pure-Python; the inner
                C++ LaCAM call still caps at 1.0 s for responsiveness.
            verbose: Verbosity level (0 = silent).
            lacam_binary: Explicit path to the LaCAM C++ binary (lacam3 or lacam).
                If None, auto-detected from the solvers directory.
        """
        self.time_limit_ms = time_limit_ms
        self.verbose = verbose
        self.lacam_binary = lacam_binary

        # Persistent across plan() calls:
        self._planner: Optional[RTLaCAMPlanner] = None
        self._agent_ids: Optional[List[int]] = None

    # -- GlobalPlanner protocol ---------------------------------------------

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

    def _plan_bundle(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
    ) -> PlanBundle:
        agent_ids = sorted(agents.keys())
        goals = self._compute_goals(agents, assignments)
        current_config = tuple(agents[aid].pos for aid in agent_ids)

        # --- (re-)initialise if agent set changed --------------------------
        if self._planner is None or self._agent_ids != agent_ids:
            np_rng = (
                rng
                if isinstance(rng, np.random.Generator)
                else np.random.default_rng()
            )
            self._planner = RTLaCAMPlanner(
                env=env,
                agent_ids=agent_ids,
                goals=goals,
                start_config=current_config,
                rng=np_rng,
                verbose=self.verbose,
                lacam_binary=self.lacam_binary,
                lacam_time_limit=min(1.0, self.time_limit_ms / 1000.0),
            )
            self._agent_ids = agent_ids
        else:
            self._planner.update_config(current_config)
            self._planner.update_goals(goals)

        # --- Use C++ path directly for the full horizon --------------------
        # Instead of the step-by-step plan_for_ms → execute_one_step loop,
        # call C++ LaCAM once for the full horizon and use the result directly.
        # The persistent tree adds overhead but no value when goals change
        # frequently in lifelong MAPF.
        self._planner.plan_for_ms(
            self.time_limit_ms, max_timestep=horizon + 1
        )

        # Extract the full chain from root through frontier
        configs: List[Config] = []
        path_nodes = self._planner.S.current_path
        if path_nodes:
            configs = [n.config for n in path_nodes]
        if not configs:
            configs = [current_config]

        # Don't advance the tree here — the simulator will execute steps and
        # call plan() again with update_config() providing the actual position.
        # This avoids double-advancement and config mismatches.

        # --- convert config sequence -> per-agent TimedPaths ----------------
        paths: Dict[int, TimedPath] = {}
        for idx, aid in enumerate(agent_ids):
            cells = [cfg[idx] for cfg in configs]
            while len(cells) < horizon + 1:
                cells.append(cells[-1])
            if len(cells) > horizon + 1:
                cells = cells[: horizon + 1]
            paths[aid] = TimedPath(cells=cells, start_step=step)

        for aid in agents:
            if aid not in paths:
                paths[aid] = self._wait_path(agents[aid].pos, step, horizon)

        return PlanBundle(paths=paths, created_step=step, horizon=horizon)

    # -- helpers ------------------------------------------------------------

    def plan_with_metadata(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng=None,
    ) -> SolverResult:
        """SolverResult-returning entry point.

        ``RealTimeLaCAMSolver`` is pure-Python: the in-process
        ``RTLaCAMPlanner`` is bounded by a wall-clock budget
        (``time_limit_ms``) and does not produce a separate
        result file.  We therefore time the call here, classify a
        successful return as ``complete`` and an exception as
        ``error``.  ``partial_anytime`` is not distinguishable from
        ``complete`` for this solver (both correspond to "best-known
        plan at budget cutoff") without instrumenting the planner.
        """
        import time as _time
        active_agents = list(agents.keys())
        t0_ns = _time.monotonic_ns()
        try:
            bundle = self._plan_bundle(
                env, agents, assignments, step, horizon, rng,
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                plan=self._make_all_wait_bundle(
                    agents, active_agents, step, horizon,
                ),
                status="error",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=(_time.monotonic_ns() - t0_ns) / 1e6,
                error_msg=f"{type(exc).__name__}: {exc}",
            )
        end_to_end_wall_ms = (_time.monotonic_ns() - t0_ns) / 1e6
        if bundle is None or not bundle.paths:
            return SolverResult(
                plan=self._make_all_wait_bundle(
                    agents, active_agents, step, horizon,
                ),
                status="error",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=end_to_end_wall_ms,
                error_msg="planner returned empty bundle",
            )
        return SolverResult(
            plan=bundle,
            status="complete",
            solver_wall_ms=float(self.time_limit_ms),
            end_to_end_wall_ms=end_to_end_wall_ms,
        )

    @staticmethod
    def _compute_goals(
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
    ) -> Dict[int, Cell]:
        goals: Dict[int, Cell] = {}
        for aid, agent in agents.items():
            if agent.goal is not None:
                goals[aid] = agent.goal
            elif aid in assignments:
                goals[aid] = assignments[aid].goal
            else:
                goals[aid] = agent.pos
        return goals

    @staticmethod
    def _wait_path(pos: Cell, step: int, horizon: int) -> TimedPath:
        return TimedPath(cells=[pos] * (horizon + 1), start_step=step)
