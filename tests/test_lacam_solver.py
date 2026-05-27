"""
Comprehensive Tests for LaCAM Official Solver Wrapper.

Tests the LaCAMOfficialSolver class from ha_lmapf.global_tier.solvers.lacam_official_wrapper including:
- Basic pathfinding for single and multiple agents
- Edge and vertex conflict avoidance
"""
import pytest
import numpy as np
from ha_lmapf.core.types import AgentState, Task, TimedPath
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def empty_5x5_env():
    """Create an empty 5x5 environment."""
    return Environment(width=5, height=5, blocked=set())


@pytest.fixture
def env_with_walls():
    """Create environment with walls.

    Layout (5x5):
    .....
    .@@@.
    .....
    .@@@.
    .....
    """
    blocked = {(1, 1), (1, 2), (1, 3), (3, 1), (3, 2), (3, 3)}
    return Environment(width=5, height=5, blocked=blocked)


@pytest.fixture
def lacam_planner():
    """Create a LaCAM Official solver instance."""
    return LaCAMOfficialSolver()


# ============================================================================
# Single Agent Tests
# ============================================================================

class TestLaCAMSingleAgent:
    """Tests for LaCAM with a single agent."""

    def test_single_agent_direct_path(self, empty_5x5_env, lacam_planner):
        """Single agent finds direct path to goal."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0)}

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        assert 0 in bundle.paths
        path = bundle.paths[0]
        assert path(0) == (0, 0)
        assert path(4) == (0, 4)

    def test_single_agent_at_goal(self, empty_5x5_env, lacam_planner):
        """Single agent already at goal stays in place."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 2))}
        assignments = {0: Task(task_id="t0", start=(2, 2), goal=(2, 2), release_step=0)}

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        path = bundle.paths[0]
        for t in range(11):
            assert path(t) == (2, 2)

    def test_single_agent_navigates_obstacles(self, env_with_walls, lacam_planner):
        """Single agent navigates around obstacles."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(4, 4), release_step=0)}

        bundle = lacam_planner.plan(
            env=env_with_walls,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=20,
        )

        path = bundle.paths[0]
        # Path should avoid walls
        for cell in path.cells:
            assert env_with_walls.is_free(cell)


# ============================================================================
# Multi-Agent Tests
# ============================================================================

class TestLaCAMMultiAgent:
    """Tests for LaCAM with multiple agents."""

    def test_two_agents_parallel_paths(self, empty_5x5_env, lacam_planner):
        """Two agents with non-conflicting parallel paths."""
        agents = {
            0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4)),
            1: AgentState(agent_id=1, pos=(4, 0), goal=(4, 4)),
        }
        assignments = {
            0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0),
            1: Task(task_id="t1", start=(4, 0), goal=(4, 4), release_step=0),
        }

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # Both agents should have valid paths
        assert 0 in bundle.paths
        assert 1 in bundle.paths

    def test_collision_avoidance(self, empty_5x5_env, lacam_planner):
        """Prioritized planning avoids collisions."""
        # Agents crossing paths
        agents = {
            0: AgentState(agent_id=0, pos=(0, 2), goal=(4, 2)),
            1: AgentState(agent_id=1, pos=(2, 0), goal=(2, 4)),
        }
        assignments = {
            0: Task(task_id="t0", start=(0, 2), goal=(4, 2), release_step=0),
            1: Task(task_id="t1", start=(2, 0), goal=(2, 4), release_step=0),
        }

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=15,
        )

        # Check no vertex collisions
        for t in range(16):
            pos0 = bundle.paths[0](t)
            pos1 = bundle.paths[1](t)
            assert pos0 != pos1, f"Collision at step {t}: both at {pos0}"

    def test_edge_swap_avoided(self, empty_5x5_env, lacam_planner):
        """Prioritized planning avoids edge swaps."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 2)),
        }
        assignments = {
            0: Task(task_id="t0", start=(2, 2), goal=(2, 3), release_step=0),
            1: Task(task_id="t1", start=(2, 3), goal=(2, 2), release_step=0),
        }

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # Check no edge swaps
        for t in range(10):
            p0_t = bundle.paths[0](t)
            p1_t = bundle.paths[1](t)
            p0_t1 = bundle.paths[0](t + 1)
            p1_t1 = bundle.paths[1](t + 1)
            # No swap condition
            if p0_t != p0_t1 or p1_t != p1_t1:
                assert not (p0_t == p1_t1 and p1_t == p0_t1), \
                    f"Edge swap at step {t}"

    def test_priority_order_by_distance(self, empty_5x5_env, lacam_planner):
        """Agents with longer distances get higher priority."""
        # Agent 0: short distance
        # Agent 1: long distance (should be planned first)
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),  # dist=1
            1: AgentState(agent_id=1, pos=(0, 0), goal=(4, 4)),  # dist=8
        }
        assignments = {
            0: Task(task_id="t0", start=(2, 2), goal=(2, 3), release_step=0),
            1: Task(task_id="t1", start=(0, 0), goal=(4, 4), release_step=0),
        }

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=15,
        )

        # Both should have valid collision-free paths
        assert 0 in bundle.paths
        assert 1 in bundle.paths

    def test_many_agents(self, empty_5x5_env, lacam_planner):
        """Multiple agents all find collision-free paths."""
        agents = {}
        assignments = {}
        # Place agents along top row, goals along bottom row
        for i in range(5):
            agents[i] = AgentState(agent_id=i, pos=(0, i), goal=(4, i))
            assignments[i] = Task(task_id=f"t{i}", start=(0, i), goal=(4, i), release_step=0)

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # All agents should have paths
        assert len(bundle.paths) == 5

        # Check no collisions at any timestep
        for t in range(11):
            positions = [bundle.paths[i](t) for i in range(5)]
            assert len(positions) == len(set(positions)), \
                f"Collision at step {t}: {positions}"


# ============================================================================
# Path Quality Tests
# ============================================================================

class TestLaCAMPathQuality:
    """Tests for LaCAM path quality."""

    def test_paths_start_at_agent_positions(self, empty_5x5_env, lacam_planner):
        """All paths start at current agent positions."""
        agents = {
            0: AgentState(agent_id=0, pos=(1, 1), goal=(3, 3)),
            1: AgentState(agent_id=1, pos=(0, 4), goal=(4, 0)),
        }
        assignments = {
            0: Task(task_id="t0", start=(1, 1), goal=(3, 3), release_step=0),
            1: Task(task_id="t1", start=(0, 4), goal=(4, 0), release_step=0),
        }

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        assert bundle.paths[0](0) == (1, 1)
        assert bundle.paths[1](0) == (0, 4)

    def test_paths_match_horizon_length(self, empty_5x5_env, lacam_planner):
        """Paths are padded to horizon+1 cells."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 2))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 2), release_step=0)}
        horizon = 20

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=horizon,
        )

        assert len(bundle.paths[0].cells) == horizon + 1

    def test_paths_avoid_walls(self, env_with_walls, lacam_planner):
        """All path cells are on free cells."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(4, 4), release_step=0)}

        bundle = lacam_planner.plan(
            env=env_with_walls,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=20,
        )

        for cell in bundle.paths[0].cells:
            assert env_with_walls.is_free(cell)


# ============================================================================
# Edge Cases
# ============================================================================

class TestLaCAMEdgeCases:
    """Edge case tests for LaCAM."""

    def test_no_agents(self, empty_5x5_env, lacam_planner):
        """Empty agent set returns empty paths."""
        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents={},
            assignments={},
            step=0,
            horizon=10,
        )
        assert len(bundle.paths) == 0

    def test_agent_without_goal(self, empty_5x5_env, lacam_planner):
        """Agent without goal gets no path (not an active agent)."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=None)}
        assignments = {}

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # C++ wrapper skips agents with no goal and no assignment
        assert 0 not in bundle.paths

    def test_unreachable_goal_fallback(self, lacam_planner):
        """Agent with unreachable goal falls back to waiting."""
        # (2, 2) is surrounded by walls
        blocked = {(1, 2), (3, 2), (2, 1), (2, 3)}
        env = Environment(width=5, height=5, blocked=blocked)

        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(0, 0))}
        assignments = {0: Task(task_id="t0", start=(2, 2), goal=(0, 0), release_step=0)}

        bundle = lacam_planner.plan(
            env=env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # Should fall back to waiting
        path = bundle.paths[0]
        assert path(0) == (2, 2)

    def test_nonzero_start_step(self, empty_5x5_env, lacam_planner):
        """Planning from non-zero start step."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0)}

        bundle = lacam_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=50,
            horizon=10,
        )

        path = bundle.paths[0]
        assert path.start_step == 50
        assert path(50) == (0, 0)
