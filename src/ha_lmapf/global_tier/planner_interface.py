from __future__ import annotations

import os
from typing import Dict

from ha_lmapf.core.interfaces import GlobalPlanner
from ha_lmapf.core.types import AgentState, PlanBundle, Task, TimedPath

from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
from ha_lmapf.global_tier.solvers.lacam_official_real_time import RealTimeLaCAMSolver


class GlobalPlannerFactory:

    @staticmethod
    def create(name: str, **kwargs) -> GlobalPlanner:
        """
        Create a global planner by name.

        Args:
            name: Planner name. Options:
                Primary solvers (C++ wrappers):
                - "lacam_official", "lacam_cpp", "lacam", "lacam_like":
                    LaCAM (Kei18/lacam, Okumura 2023 AAAI) — basic, bounded-suboptimal
                - "lacam3", "lacam3_cpp":
                    LaCAM* (Kei18/lacam3, Okumura 2024) — anytime refinement
                - "cbs", "conflict_based_search": CBSH2-RTC C++ (falls back to Python CBS)
                - "pibt2", "pibt2_cpp", "pibt_cpp", "pibt": PIBT2 C++ executable
                - "rhcr", "rhcr_cpp": RHCR - Rolling-Horizon Collision Resolution
                - "cbsh2", "cbsh2_rtc", "cbsh2_cpp": CBSH2-RTC - CBS with Heuristics
                - "eecbs", "eecbs_cpp": EECBS - Explicit Estimation CBS
                - "pbs", "pbs_cpp": PBS - Priority-Based Search
                - "lns2", "mapf_lns2", "lns2_cpp": MAPF-LNS2 - Large Neighborhood Search

                Real-Time LaCAM (pure Python, persistent DFS + rerooting):
                - "rt_lacam", "lacam_rt", "real_time_lacam": RT-LaCAM

                Aliases (redirect to official C++ wrappers):
                - "pylacam", "lacam_python", "prioritized": LaCAM Official
                - "pycbs", "cbs_python": CBSH2-RTC

            **kwargs: Additional arguments passed to the solver constructor.

        Returns:
            GlobalPlanner instance
        """
        name = (name or "").strip().lower()
        solver_dir = os.path.dirname(os.path.abspath(__file__))

        # Aliases redirecting to official C++ wrappers
        if name in {"pylacam", "lacam_python", "prioritized"}:
            return LaCAMOfficialSolver(**kwargs)

        if name in {"pycbs", "cbs_python"}:
            return CBSH2Solver(**kwargs)

        # LaCAM → C++ LaCAM Official wrapper (primary solver)
        if name in {"lacam", "lacam_like"}:
            return LaCAMOfficialSolver(**kwargs)

        # LaCAM3 → C++ LaCAM3 wrapper (anytime solver with refinement)
        if name in {"lacam3", "lacam3_cpp"}:
            from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver

            return LaCAM3Solver(**kwargs)

        # CBS → C++ CBSH2-RTC wrapper (primary solver)
        if name in {"cbs", "conflict_based_search"}:
            try:
                solver = CBSH2Solver(**kwargs)
                # Verify binary exists
                if os.path.isfile(solver.binary_path):
                    return solver
            except Exception:
                pass
            # Fallback to CBSH2 solver even without binary (will warn at runtime)
            return CBSH2Solver(**kwargs)

        if name in {"lacam_official", "lacam_cpp"}:
            return LaCAMOfficialSolver(**kwargs)

        if name in {"pibt2", "pibt2_cpp", "pibt_cpp", "pibt"}:
            from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
            binary_paths = [
                os.path.join(solver_dir, "solvers", "pibt2"),
                os.path.join(solver_dir, "solvers", "pibt2", "build", "mapf"),
                "pibt2",
                "mapf",
            ]
            for path in binary_paths:
                if os.path.isfile(path):
                    return PIBT2Solver(binary_path=path, **kwargs)
            return PIBT2Solver(**kwargs)

        # C++ wrappers (Jiaoyang-Li)
        if name in {"rhcr", "rhcr_cpp", "lifelong"}:
            from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
            return RHCRSolver(**kwargs)

        if name in {"cbsh2", "cbsh2_rtc", "cbsh2_cpp", "cbs_heuristic"}:
            return CBSH2Solver(**kwargs)

        if name in {"eecbs", "eecbs_cpp", "bounded_cbs"}:
            from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver
            return EECBSSolver(**kwargs)

        if name in {"pbs", "pbs_cpp", "priority_based_search"}:
            from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver
            return PBSSolver(**kwargs)

        if name in {"lns2", "mapf_lns2", "lns2_cpp", "lns"}:
            from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver
            return LNS2Solver(**kwargs)

        # Real-Time LaCAM — persistent DFS with rerooting (pure Python)
        if name in {"rt_lacam", "lacam_rt", "real_time_lacam"}:
            return RealTimeLaCAMSolver(**kwargs)

        raise ValueError(
            f"Unknown global solver '{name}'. "
            f"Available solvers: cbs, lacam, lacam3, lacam_official, pibt2, "
            f"rhcr, cbsh2, eecbs, pbs, lns2, rt_lacam."
        )


def _wait_path(pos, step: int, horizon: int) -> TimedPath:
    # Horizon+1 cells including start cell at time step
    cells = [pos] * (horizon + 1)
    return TimedPath(cells=cells, start_step=step)


def build_wait_plan_for_unassigned(
        agents: Dict[int, AgentState],
        assignments: Dict[int, Task],
        step: int,
        horizon: int,
) -> Dict[int, TimedPath]:
    """
    Create WAIT paths for agents without assignments. Solvers may overwrite these paths.
    """
    paths: Dict[int, TimedPath] = {}
    for aid, a in agents.items():
        if aid not in assignments:
            paths[aid] = _wait_path(a.pos, step, horizon)
    return paths


class PlannerWrapper:
    """
    Optional wrapper to ensure any planner returns a complete PlanBundle:
    - If solver returns partial paths, fill missing agents with WAIT.
    """

    def __init__(self, planner: GlobalPlanner) -> None:
        self.planner = planner

    def plan(
            self,
            env,
            agents: Dict[int, AgentState],
            assignments: Dict[int, Task],
            step: int,
            horizon: int,
            rng,
    ) -> PlanBundle:
        plan = self.planner.plan(env, agents, assignments, step, horizon, rng)
        # Ensure all agents have a path
        for aid, a in agents.items():
            if aid not in plan.paths:
                plan.paths[aid] = _wait_path(a.pos, step, horizon)
        return plan
