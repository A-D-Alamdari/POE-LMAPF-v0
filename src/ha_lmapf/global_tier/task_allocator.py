from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from ha_lmapf.core.grid import manhattan
from ha_lmapf.core.interfaces import TaskAllocator
from ha_lmapf.core.types import AgentState, Task

Cell = Tuple[int, int]


def _get_task_pickup_location(task: Task) -> Cell:
    """
    Get the pickup location for a task.

    For pickup-delivery tasks, this is task.start.
    For legacy delivery-only tasks (start = (-1,-1)), this falls back to task.goal.
    """
    if task.start != (-1, -1):
        return task.start
    return task.goal


class GreedyNearestTaskAllocator(TaskAllocator):
    """
    Greedy task allocator for lifelong pickup-delivery MAPF.

    For each released task (sorted by release_step, then id), assign it to the
    nearest available agent according to Manhattan distance to the task's
    START (pickup) location. Each agent receives at most one task per planning epoch.

    This ensures agents are assigned tasks they can reach quickly for pickup,
    rather than being assigned based on the delivery destination.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: List[Task],
            step: int,
            rng=None,  # Unused; kept for interface compatibility
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents: no current goal or already reached goal
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        # Deterministic ordering of tasks
        tasks_ordered = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        # Track which agents are still free to assign
        free_agents = dict(available_agents)

        for task in tasks_ordered:
            if not free_agents:
                break

            # Get the pickup location for this task
            pickup_loc = _get_task_pickup_location(task)

            # Choose nearest agent by Manhattan distance to PICKUP location (tie-break by agent ID)
            best_aid = min(
                free_agents.keys(),
                key=lambda aid: (manhattan(free_agents[aid].pos, pickup_loc), aid)
            )

            assignments[best_aid] = task

            del free_agents[best_aid]

        return assignments


class HungarianTaskAllocator(TaskAllocator):
    """
    Optimal task allocator using the Hungarian algorithm.

    Computes the globally optimal assignment that minimizes the total
    Manhattan distance from agents to their assigned task pickup locations.

    Falls back to greedy assignment if scipy is not available.
    """

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: List[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents: no current goal or already reached goal
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        agent_ids = sorted(available_agents.keys())
        task_list = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        n_agents = len(agent_ids)
        n_tasks = len(task_list)

        # Build cost matrix
        cost_matrix = np.zeros((n_agents, n_tasks), dtype=np.float64)
        for i, aid in enumerate(agent_ids):
            agent_pos = available_agents[aid].pos
            for j, task in enumerate(task_list):
                pickup_loc = _get_task_pickup_location(task)
                cost_matrix[i, j] = manhattan(agent_pos, pickup_loc)

        try:
            from scipy.optimize import linear_sum_assignment
            row_ind, col_ind = linear_sum_assignment(cost_matrix)

            for i, j in zip(row_ind, col_ind):
                if j < n_tasks:  # Ensure task index is valid
                    assignments[agent_ids[i]] = task_list[j]

        except ImportError:
            # Fallback to greedy if scipy not available
            greedy = GreedyNearestTaskAllocator()
            return greedy.assign(agents, open_tasks, step, rng)

        return assignments


class AuctionBasedTaskAllocator(TaskAllocator):
    """
    Auction-based task allocator using sequential single-item auctions.

    Each task is auctioned off to the highest bidder (lowest distance),
    and agents bid based on their proximity to the task's pickup location.
    This provides a balance between optimality and computational efficiency.
    """

    def __init__(self, max_iterations: int = 100, epsilon: float = 0.01):
        """
        Initialize the auction allocator.

        Args:
            max_iterations: Maximum number of auction iterations.
            epsilon: Price increment for bidding.
        """
        self.max_iterations = max_iterations
        self.epsilon = epsilon

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: List[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        assignments: Dict[int, Task] = {}

        # Determine available agents
        available_agents = {
            aid: a
            for aid, a in agents.items()
            if a.goal is None or a.pos == a.goal
        }

        if not available_agents or not open_tasks:
            return assignments

        agent_ids = sorted(available_agents.keys())
        task_list = sorted(open_tasks, key=lambda t: (t.release_step, t.task_id))

        n_agents = len(agent_ids)
        n_tasks = len(task_list)

        # Compute benefit matrix (negative distance = higher benefit for closer tasks)
        max_dist = 0
        benefit_matrix = np.zeros((n_agents, n_tasks), dtype=np.float64)
        for i, aid in enumerate(agent_ids):
            agent_pos = available_agents[aid].pos
            for j, task in enumerate(task_list):
                pickup_loc = _get_task_pickup_location(task)
                dist = manhattan(agent_pos, pickup_loc)
                max_dist = max(max_dist, dist)
                benefit_matrix[i, j] = -dist

        # Normalize benefits to positive values
        benefit_matrix += max_dist + 1

        # Task prices (start at 0)
        prices = np.zeros(n_tasks, dtype=np.float64)

        # Agent assignments (-1 = unassigned)
        agent_to_task = {aid: -1 for aid in agent_ids}
        task_to_agent: Dict[int, int] = {}

        for _ in range(self.max_iterations):
            # Find unassigned agents
            unassigned = [aid for aid in agent_ids if agent_to_task[aid] == -1]
            if not unassigned:
                break

            for aid in unassigned:
                i = agent_ids.index(aid)

                # Compute net values for each task
                net_values = benefit_matrix[i] - prices
                best_task = int(np.argmax(net_values))
                best_value = net_values[best_task]

                # Find second-best value for price increment
                net_values_copy = net_values.copy()
                net_values_copy[best_task] = -np.inf
                second_best = np.max(net_values_copy)

                # Only bid if beneficial
                if best_value <= 0:
                    continue

                # Compute bid increment
                bid_increment = best_value - second_best + self.epsilon

                # If task is already assigned, unassign previous owner
                if best_task in task_to_agent:
                    prev_owner = task_to_agent[best_task]
                    agent_to_task[prev_owner] = -1

                # Assign task and update price
                agent_to_task[aid] = best_task
                task_to_agent[best_task] = aid
                prices[best_task] += bid_increment

        # Build final assignments
        for aid, task_idx in agent_to_task.items():
            if task_idx >= 0 and task_idx < n_tasks:
                assignments[aid] = task_list[task_idx]

        return assignments


# ---------------------------------------------------------------------------
# Persistent Task Allocator (Commitment Persistence / Anti-Thrashing)
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class _CommittedAssignment:
    """
    Internal record for a committed task assignment.

    Attributes:
        task_id: The assigned task's ID.
        commit_step: Simulation step when the assignment was made.
        initial_eta: Estimated time of arrival at assignment time.
        pickup_pos: The pickup location for this task.
    """
    task_id: str
    commit_step: int
    initial_eta: int
    pickup_pos: Tuple[int, int]


class PersistentTaskAllocator(TaskAllocator):
    """
    Wrapper that adds commitment persistence to any base allocator.

    Commitment persistence prevents "assignment thrashing" where agents
    repeatedly switch tasks due to small changes in distance or task
    availability. This stabilizes the planning system and ensures that
    evaluation measures planner quality, not allocator noise.

    How it works:
    - Once a task is assigned, it remains locked for `commit_horizon` steps.
    - Reassignment is only allowed under specific "break conditions":
      1. The agent completed the task (goal is None).
      2. The commitment horizon expired.
      3. Excessive delay: current ETA > delay_threshold * initial_eta.

    This converts the allocator from a memoryless policy to a hysteresis
    controller, analogous to damping in control systems.

    Paper justification:
        "We use a greedy nearest-task allocator with commitment persistence:
        assignments remain fixed for a finite horizon and are only revised
        when infeasible or excessively delayed, preventing reassignment
        oscillations that could confound execution-level evaluation."
    """

    def __init__(
            self,
            base_allocator: TaskAllocator,
            commit_horizon: int = 25,
            delay_threshold: float = 2.5,
    ):
        """
        Initialize the persistent allocator wrapper.

        Args:
            base_allocator: The underlying allocator (greedy, hungarian, etc.).
            commit_horizon: Number of steps an assignment stays locked (K).
            delay_threshold: Multiplier for allowed delay before reassignment (alpha).
                             If current_eta > alpha * initial_eta, break commitment.
        """
        self.base = base_allocator
        self.commit_horizon = max(1, int(commit_horizon))
        self.delay_threshold = float(delay_threshold)

        # Per-agent commitment state: agent_id -> _CommittedAssignment
        self._commitments: Dict[int, _CommittedAssignment] = {}

        # Statistics for metrics
        self._total_assignments: int = 0
        self._kept_assignments: int = 0
        self._broken_assignments: int = 0

    def assign(
            self,
            agents: Dict[int, AgentState],
            open_tasks: List[Task],
            step: int,
            rng=None,
    ) -> Dict[int, Task]:
        """
        Assign tasks with commitment persistence.

        Agents with valid commitments are skipped (they keep their current task).
        Only truly free agents are passed to the base allocator.
        """
        # 1. Identify agents that should keep their current commitment
        committed_agents: Dict[int, str] = {}  # aid -> task_id (still committed)
        free_agents: Dict[int, AgentState] = {}

        for aid, agent in agents.items():
            keep, reason = self._should_keep_commitment(aid, agent, step)
            if keep:
                committed_agents[aid] = self._commitments[aid].task_id
                self._kept_assignments += 1
            else:
                # Agent is free for reassignment
                if aid in self._commitments:
                    self._broken_assignments += 1
                    del self._commitments[aid]
                free_agents[aid] = agent

        # 2. Run base allocator only on free agents
        new_assignments = self.base.assign(free_agents, open_tasks, step, rng)

        # 3. Lock new assignments with commitment
        for aid, task in new_assignments.items():
            pickup_pos = _get_task_pickup_location(task)
            initial_eta = manhattan(agents[aid].pos, pickup_pos)

            self._commitments[aid] = _CommittedAssignment(
                task_id=task.task_id,
                commit_step=step,
                initial_eta=max(1, initial_eta),  # Avoid division by zero
                pickup_pos=pickup_pos,
            )
            self._total_assignments += 1

        return new_assignments

    def _should_keep_commitment(
            self,
            agent_id: int,
            agent: AgentState,
            step: int,
    ) -> Tuple[bool, str]:
        """
        Determine if an agent should keep its current task commitment.

        Returns:
            Tuple of (should_keep: bool, reason: str)
        """
        if agent_id not in self._commitments:
            return False, "no_commitment"

        commitment = self._commitments[agent_id]

        # Break condition 1: Task completed (agent has no goal)
        if agent.goal is None:
            return False, "task_completed"

        # Break condition 2: Agent's current task doesn't match commitment
        # (This can happen if task was completed and a new one assigned elsewhere)
        if agent.task_id is not None and agent.task_id != commitment.task_id:
            return False, "task_mismatch"

        # Break condition 3: Commitment horizon expired
        elapsed = step - commitment.commit_step
        if elapsed >= self.commit_horizon:
            return False, "horizon_expired"

        # Break condition 4: Excessive delay
        # Current ETA = distance from agent's current position to its goal
        if agent.goal is not None:
            current_eta = manhattan(agent.pos, agent.goal)
            if current_eta > self.delay_threshold * commitment.initial_eta:
                return False, "excessive_delay"

        # No break condition met -> keep commitment
        return True, "committed"

    def get_statistics(self) -> Dict[str, int]:
        """
        Get commitment statistics for metrics tracking.

        Returns:
            Dict with total_assignments, kept_assignments, broken_assignments.
        """
        return {
            "total_assignments": self._total_assignments,
            "kept_assignments": self._kept_assignments,
            "broken_assignments": self._broken_assignments,
        }

    def reset_statistics(self) -> None:
        """Reset commitment statistics (call at start of simulation)."""
        self._total_assignments = 0
        self._kept_assignments = 0
        self._broken_assignments = 0
        self._commitments.clear()


def create_allocator(
        allocator_name: str,
        commit_horizon: int = 0,
        delay_threshold: float = 2.5,
) -> TaskAllocator:
    """
    Factory function to create a task allocator by name.

    Args:
        allocator_name: One of "greedy", "hungarian", "auction".
        commit_horizon: If > 0, wrap with PersistentTaskAllocator.
        delay_threshold: Delay multiplier for persistence (alpha).

    Returns:
        A TaskAllocator instance.
    """
    # Create base allocator
    if allocator_name == "greedy":
        base = GreedyNearestTaskAllocator()
    elif allocator_name == "hungarian":
        base = HungarianTaskAllocator()
    elif allocator_name == "auction":
        base = AuctionBasedTaskAllocator()
    else:
        raise ValueError(f"Unknown allocator: {allocator_name}")

    # Optionally wrap with persistence
    if commit_horizon > 0:
        return PersistentTaskAllocator(
            base_allocator=base,
            commit_horizon=commit_horizon,
            delay_threshold=delay_threshold,
        )

    return base
