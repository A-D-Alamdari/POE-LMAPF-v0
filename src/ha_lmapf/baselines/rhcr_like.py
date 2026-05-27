# FILE: src/ha_lmapf/baselines/rhcr_like.py
"""
RHCR (Rolling-Horizon Collision Resolution) Baseline.

This module provides both:
1. A Python RHCR-like implementation using existing solvers
2. An optional wrapper for the official RHCR C++ implementation from:
   https://github.com/Jiaoyang-Li/RHCR

To use the official C++ RHCR solver, set use_official=True and ensure
the binary is installed in src/ha_lmapf/global_tier/solvers/rhcr
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional

from ha_lmapf.core.interfaces import SimStateView, GlobalPlanner, TaskAllocator
from ha_lmapf.core.types import PlanBundle, Task
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.task_allocator.task_allocator import GreedyNearestTaskAllocator


def _check_rhcr_binary_available() -> bool:
    """Check if the official RHCR binary is available."""
    try:
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
        solver_dir = os.path.dirname(os.path.abspath(__file__))
        solvers_dir = os.path.join(os.path.dirname(solver_dir), "global_tier", "solvers")
        binary_names = ["rhcr", "rhcr.exe", "lifelong", "lifelong.exe"]
        for name in binary_names:
            if os.path.isfile(os.path.join(solvers_dir, name)):
                return True
        return False
    except ImportError:
        return False


@dataclass
class RHCRPlanner:
    """
    RHCR baseline (Receding Horizon Collision Resolution).

    This implementation supports two modes:
    1. Python simulation: Uses existing MAPF solvers (CBS, LaCAM, etc.) with
       periodic replanning to simulate RHCR behavior.
    2. Official C++ solver: Uses the official RHCR implementation from
       Jiaoyang Li's repository when available.

    Parameters:
        horizon: Planning horizon (H)
        replan_every: Replanning interval (simulation_window in official RHCR)
        solver_name: Backend solver for Python mode ("cbs", "lacam", "pbs", etc.)
        k: Execution window (steps executed before next replan)
        use_official: If True, use official RHCR C++ binary when available
        planning_window: Collision-resolution window (w) for official RHCR
        rhcr_solver: Internal solver algorithm for official RHCR ("WHCA", "ECBS", "PBS")
    """

    horizon: int
    replan_every: int
    solver_name: str = "lacam"
    k: int = 1
    use_official: bool = False
    planning_window: int = 10
    rhcr_solver: str = "PBS"

    # Internal state fields (init=False) to satisfy linters
    solver: GlobalPlanner = field(init=False)
    allocator: TaskAllocator = field(init=False)
    last_planned_step: int = field(default=-10 ** 9, init=False)
    _using_official: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.horizon = int(self.horizon)
        self.replan_every = max(1, int(self.replan_every))
        self.k = max(1, int(self.k))

        # Try to use official RHCR if requested and available
        if self.use_official and _check_rhcr_binary_available():
            from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
            self.solver = RHCRSolver(
                simulation_window=self.replan_every,
                planning_window=self.planning_window,
                solver=self.rhcr_solver,
            )
            self._using_official = True
        else:
            # Fall back to Python implementation
            self.solver = GlobalPlannerFactory.create(self.solver_name)
            self._using_official = False

        self.allocator = GreedyNearestTaskAllocator()

    def step(self, sim_state: SimStateView) -> Optional[PlanBundle]:
        cur_step = int(sim_state.step)

        # RHCR baseline: trigger periodically; if you want strict k=1, set replan_every=1 in config.
        if cur_step % self.replan_every != 0:
            return None

        # Collect open tasks (released but not yet assigned)
        open_tasks = []
        if hasattr(sim_state, "pop_open_tasks"):
            open_tasks = list(getattr(sim_state, "pop_open_tasks")())
        else:
            if hasattr(sim_state, "open_tasks"):
                open_tasks = list(getattr(sim_state, "open_tasks"))

        assignments: Dict[int, Task] = self.allocator.assign(sim_state.agents, open_tasks, cur_step, rng=None)

        # Apply assignments to simulator if hook exists
        if hasattr(sim_state, "mark_task_assigned"):
            for aid, task in assignments.items():
                getattr(sim_state, "mark_task_assigned")(task, aid)

        # Put back leftover tasks not assigned
        assigned_ids = {t.task_id for t in assignments.values()}

        # FIX: Use t.task_id instead of t.id
        leftover = [t for t in open_tasks if t.task_id not in assigned_ids]

        if leftover and hasattr(sim_state, "open_tasks"):
            getattr(sim_state, "open_tasks").extend(leftover)

        # Plan over horizon H
        plan = self.solver.plan(
            env=sim_state.env,
            agents=sim_state.agents,
            assignments=assignments,
            step=cur_step,
            horizon=self.horizon,
            rng=None,
        )

        self.last_planned_step = cur_step
        return plan
