"""Tests for task allocator strategies: Greedy, Hungarian, Auction."""
from __future__ import annotations

from ha_lmapf.core.types import AgentState, Task
from ha_lmapf.task_allocator.task_allocator import (
    AuctionBasedTaskAllocator,
    GreedyNearestTaskAllocator,
    HungarianTaskAllocator,
)


def _make_agents():
    return {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(4, 4)),
    }


def _make_tasks():
    return [
        Task(task_id="t0", start=(0, 1), goal=(3, 3), release_step=0),
        Task(task_id="t1", start=(4, 3), goal=(1, 1), release_step=0),
    ]


def test_greedy_assigns_nearest():
    agents = _make_agents()
    tasks = _make_tasks()
    alloc = GreedyNearestTaskAllocator()
    result = alloc.assign(agents, tasks, step=0)

    # Agent 0 at (0,0) is closest to task t0 pickup at (0,1) — distance 1
    # Agent 1 at (4,4) is closest to task t1 pickup at (4,3) — distance 1
    assert result[0].task_id == "t0"
    assert result[1].task_id == "t1"


def test_hungarian_assigns_optimally():
    agents = _make_agents()
    tasks = _make_tasks()
    alloc = HungarianTaskAllocator()
    result = alloc.assign(agents, tasks, step=0)

    # Optimal: agent 0 → t0 (dist 1), agent 1 → t1 (dist 1). Total cost = 2.
    # If swapped: agent 0 → t1 (dist 7), agent 1 → t0 (dist 7). Total cost = 14.
    assert result[0].task_id == "t0"
    assert result[1].task_id == "t1"


def test_auction_assigns_tasks():
    agents = _make_agents()
    tasks = _make_tasks()
    alloc = AuctionBasedTaskAllocator()
    result = alloc.assign(agents, tasks, step=0)

    # Auction processes t0 first. Agent 0 bids -1, agent 1 bids -7. Agent 0 wins.
    # Then t1: only agent 1 left, gets t1.
    assert result[0].task_id == "t0"
    assert result[1].task_id == "t1"


def test_hungarian_asymmetric():
    """More agents than tasks — only some get assigned."""
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(0, 4)),
        2: AgentState(agent_id=2, pos=(4, 0)),
    }
    tasks = [
        Task(task_id="t0", start=(0, 3), goal=(2, 2), release_step=0),
    ]
    alloc = HungarianTaskAllocator()
    result = alloc.assign(agents, tasks, step=0)

    # Agent 1 at (0,4) is closest to pickup (0,3) — distance 1.
    assert len(result) == 1
    assert 1 in result
    assert result[1].task_id == "t0"


def test_allocators_skip_busy_agents():
    """Agents with existing goals should not receive new tasks."""
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0), goal=(2, 2)),  # busy
        1: AgentState(agent_id=1, pos=(4, 4)),  # idle
    }
    tasks = [Task(task_id="t0", start=(0, 1), goal=(3, 3), release_step=0)]

    for Alloc in [GreedyNearestTaskAllocator, HungarianTaskAllocator, AuctionBasedTaskAllocator]:
        result = Alloc().assign(agents, tasks, step=0)
        assert 0 not in result, f"{Alloc.__name__} assigned to busy agent"
        assert result[1].task_id == "t0"


def test_direct_to_goal_tasks():
    """Legacy tasks with start=(-1,-1) use goal as pickup location."""
    agents = {
        0: AgentState(agent_id=0, pos=(0, 0)),
        1: AgentState(agent_id=1, pos=(4, 4)),
    }
    tasks = [
        Task(task_id="t0", start=(-1, -1), goal=(0, 1), release_step=0),
        Task(task_id="t1", start=(-1, -1), goal=(4, 3), release_step=0),
    ]

    for Alloc in [GreedyNearestTaskAllocator, HungarianTaskAllocator, AuctionBasedTaskAllocator]:
        result = Alloc().assign(agents, tasks, step=0)
        assert result[0].task_id == "t0", f"{Alloc.__name__} wrong for agent 0"
        assert result[1].task_id == "t1", f"{Alloc.__name__} wrong for agent 1"
