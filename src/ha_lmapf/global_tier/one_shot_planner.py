
"""
One-Shot Global Planner for Classical MAPF.

Plans once at step 0. After the initial plan, allows replanning when
the simulator signals a major deviation (e.g. agents stuck due to
dynamic human obstacles).
"""
from __future__ import annotations

from typing import Dict, Optional

from ha_lmapf.core.interfaces import GlobalPlanner, SimStateView, TaskAllocator
from ha_lmapf.core.types import PlanBundle, Task


class OneShotPlanner:
    """
    Tier-1 planner for classical one-shot MAPF.

    Behaviour:
      - First call to step(): allocate tasks, compute a single global plan,
        return the PlanBundle.
      - Subsequent calls: return None UNLESS major_deviation is flagged
        (e.g. agents stuck behind humans), in which case replan from
        current positions with existing goal assignments.
    """

    def __init__(
        self,
        horizon: int,
        solver_impl: GlobalPlanner,
        allocator: TaskAllocator,
    ) -> None:
        self.horizon = int(horizon)
        self.solver = solver_impl
        self.allocator = allocator
        self._planned = False

    def step(self, sim_state: SimStateView) -> Optional[PlanBundle]:
        # After initial plan, only replan on deviation (stuck agents)
        if self._planned:
            if not getattr(sim_state, "major_deviation", False):
                return None
            return self._replan_from_current(sim_state)

        cur_step = int(sim_state.step)

        # --- Ensure tasks are released (needed when called before step_once) ---
        if hasattr(sim_state, "_release_tasks"):
            sim_state._release_tasks()

        # --- Task Allocation ---
        open_tasks = []
        if hasattr(sim_state, "pop_open_tasks"):
            open_tasks = list(sim_state.pop_open_tasks())
        elif hasattr(sim_state, "open_tasks"):
            open_tasks = list(sim_state.open_tasks)

        if not open_tasks:
            return None

        assignments: Dict[int, Task] = self.allocator.assign(
            sim_state.agents, open_tasks, cur_step, rng=None,
        )

        if not assignments:
            if hasattr(sim_state, "open_tasks"):
                sim_state.open_tasks.extend(open_tasks)
            return None

        # Register assignments with simulator
        if hasattr(sim_state, "mark_task_assigned"):
            for aid, task in assignments.items():
                sim_state.mark_task_assigned(task, aid)

        # Return unused tasks
        assigned_ids = {t.task_id for t in assignments.values()}
        leftover = [t for t in open_tasks if t.task_id not in assigned_ids]
        if leftover and hasattr(sim_state, "open_tasks"):
            sim_state.open_tasks.extend(leftover)

        # --- Global Planning ---
        all_assignments = dict(assignments)
        for aid, agent in sim_state.agents.items():
            if aid not in all_assignments and agent.goal is not None:
                all_assignments[aid] = Task(
                    task_id=agent.task_id or f"_existing_{aid}",
                    start=agent.pos,
                    goal=agent.goal,
                    release_step=0,
                )

        plan = self.solver.plan(
            env=sim_state.env,
            agents=sim_state.agents,
            assignments=all_assignments,
            step=cur_step,
            horizon=self.horizon,
            rng=None,
        )

        self._planned = True
        return plan

    def _replan_from_current(self, sim_state: SimStateView) -> Optional[PlanBundle]:
        """
        Replan from current agent positions using their existing goal assignments.
        Called when agents are stuck due to dynamic obstacles (humans).
        """
        cur_step = int(sim_state.step)

        # Build assignments from agents that still have goals
        assignments: Dict[int, Task] = {}
        for aid, agent in sim_state.agents.items():
            if agent.goal is not None:
                assignments[aid] = Task(
                    task_id=agent.task_id or f"_replan_{aid}",
                    start=agent.pos,
                    goal=agent.goal,
                    release_step=0,
                )

        if not assignments:
            return None

        plan = self.solver.plan(
            env=sim_state.env,
            agents=sim_state.agents,
            assignments=assignments,
            step=cur_step,
            horizon=self.horizon,
            rng=None,
        )

        return plan
