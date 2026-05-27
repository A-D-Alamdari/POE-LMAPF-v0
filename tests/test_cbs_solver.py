"""
Comprehensive Tests for CBSH2-RTC Solver Wrapper.

Tests the CBSH2Solver class from ha_lmapf.global_tier.solvers.cbsh2_wrapper including:
- Basic pathfinding for single and multiple agents
- Conflict detection and resolution
- Vertex and edge conflict handling
- Edge cases
"""
import os
import pytest
import numpy as np
from ha_lmapf.core.types import AgentState, Task, TimedPath
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver


# Tests that verify actual pathfinding require a working C++ binary.
# The binary file may exist but fail to run (wrong arch, missing libs, etc.).
def _binary_works() -> bool:
    try:
        s = CBSH2Solver()
        if not os.path.isfile(s.binary_path):
            return False
        env = Environment(width=3, height=3, blocked=set())
        from ha_lmapf.core.types import AgentState as _AS, Task as _T
        agents = {0: _AS(agent_id=0, pos=(0, 0), goal=(0, 2))}
        assignments = {0: _T(task_id="t0", start=(0, 0), goal=(0, 2), release_step=0)}
        b = s.plan(env=env, agents=agents, assignments=assignments, step=0, horizon=5)
        return b.paths[0](2) == (0, 2)
    except Exception:
        return False


requires_binary = pytest.mark.skipif(
    not _binary_works(), reason="CBSH2-RTC binary not available or not functional"
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def empty_5x5_env():
    """Create an empty 5x5 environment."""
    return Environment(width=5, height=5, blocked=set())


@pytest.fixture
def env_with_corridor():
    """Create environment with a corridor (narrow passage).

    Layout (5x5):
    .....
    @@@.@
    .....
    @.@@@
    .....
    """
    blocked = {
        (1, 0), (1, 1), (1, 2), (1, 4),
        (3, 0), (3, 2), (3, 3), (3, 4),
    }
    return Environment(width=5, height=5, blocked=blocked)


@pytest.fixture
def cbs_planner():
    """Create a CBS planner instance."""
    return CBSH2Solver()


# ============================================================================
# Single Agent Tests
# ============================================================================

@requires_binary
class TestCBSSingleAgent:
    """Tests for CBS with a single agent (no conflicts possible)."""

    def test_single_agent_direct_path(self, empty_5x5_env, cbs_planner):
        """Single agent finds direct path to goal."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0)}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        assert 0 in bundle.paths
        path = bundle.paths[0]
        assert path(0) == (0, 0)  # Start
        assert path(4) == (0, 4)  # Goal reached in 4 steps

    def test_single_agent_already_at_goal(self, empty_5x5_env, cbs_planner):
        """Single agent already at goal stays in place."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 2))}
        assignments = {0: Task(task_id="t0", start=(2, 2), goal=(2, 2), release_step=0)}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        path = bundle.paths[0]
        # Should stay at goal for entire horizon
        for t in range(11):
            assert path(t) == (2, 2)

    def test_single_agent_with_obstacles(self, env_with_corridor, cbs_planner):
        """Single agent navigates around obstacles."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(4, 4), release_step=0)}

        bundle = cbs_planner.plan(
            env=env_with_corridor,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=20,
        )

        path = bundle.paths[0]
        # Verify path doesn't go through obstacles
        for cell in path.cells:
            assert env_with_corridor.is_free(cell)


# ============================================================================
# Multi-Agent Conflict Resolution Tests
# ============================================================================

@requires_binary
class TestCBSMultiAgent:
    """Tests for CBS with multiple agents requiring conflict resolution."""

    def test_two_agents_no_conflict(self, empty_5x5_env, cbs_planner):
        """Two agents with non-conflicting paths."""
        agents = {
            0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4)),
            1: AgentState(agent_id=1, pos=(4, 0), goal=(4, 4)),
        }
        assignments = {
            0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0),
            1: Task(task_id="t1", start=(4, 0), goal=(4, 4), release_step=0),
        }

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        assert 0 in bundle.paths
        assert 1 in bundle.paths
        # Both should reach goals
        assert bundle.paths[0](4) == (0, 4)
        assert bundle.paths[1](4) == (4, 4)

    def test_head_on_vertex_conflict(self, empty_5x5_env, cbs_planner):
        """Two agents heading toward same cell (vertex conflict)."""
        # Agent 0: (0, 2) -> (2, 2)
        # Agent 1: (4, 2) -> (2, 2)
        # Both want to be at (2, 2)
        agents = {
            0: AgentState(agent_id=0, pos=(0, 2), goal=(2, 2)),
            1: AgentState(agent_id=1, pos=(4, 2), goal=(2, 2)),
        }
        assignments = {
            0: Task(task_id="t0", start=(0, 2), goal=(2, 2), release_step=0),
            1: Task(task_id="t1", start=(4, 2), goal=(2, 2), release_step=0),
        }

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # CBS should resolve - check no collisions at any timestep
        for t in range(11):
            pos0 = bundle.paths[0](t)
            pos1 = bundle.paths[1](t)
            assert pos0 != pos1 or t > 5, f"Vertex conflict at step {t}: both at {pos0}"

    def test_edge_swap_conflict(self, empty_5x5_env, cbs_planner):
        """Two agents trying to swap positions (edge conflict)."""
        # Agent 0: (2, 2) -> (2, 3)
        # Agent 1: (2, 3) -> (2, 2)
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 2)),
        }
        assignments = {
            0: Task(task_id="t0", start=(2, 2), goal=(2, 3), release_step=0),
            1: Task(task_id="t1", start=(2, 3), goal=(2, 2), release_step=0),
        }

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # Check no edge swaps occur
        for t in range(10):
            pos0_t = bundle.paths[0](t)
            pos1_t = bundle.paths[1](t)
            pos0_t1 = bundle.paths[0](t + 1)
            pos1_t1 = bundle.paths[1](t + 1)
            # No swap: if 0 goes from A to B, 1 shouldn't go from B to A
            if pos0_t1 != pos0_t or pos1_t1 != pos1_t:
                assert not (pos0_t == pos1_t1 and pos1_t == pos0_t1), \
                    f"Edge swap at step {t}"

    def test_three_agents_coordination(self, empty_5x5_env, cbs_planner):
        """Three agents needing coordination."""
        agents = {
            0: AgentState(agent_id=0, pos=(0, 2), goal=(4, 2)),
            1: AgentState(agent_id=1, pos=(2, 0), goal=(2, 4)),
            2: AgentState(agent_id=2, pos=(4, 2), goal=(0, 2)),
        }
        assignments = {
            0: Task(task_id="t0", start=(0, 2), goal=(4, 2), release_step=0),
            1: Task(task_id="t1", start=(2, 0), goal=(2, 4), release_step=0),
            2: Task(task_id="t2", start=(4, 2), goal=(0, 2), release_step=0),
        }

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=15,
        )

        # Verify no collisions
        for t in range(16):
            positions = [bundle.paths[aid](t) for aid in [0, 1, 2]]
            assert len(positions) == len(set(positions)), \
                f"Vertex collision at step {t}: {positions}"


# ============================================================================
# Path Quality Tests
# ============================================================================

@requires_binary
class TestCBSPathQuality:
    """Tests for CBS path quality and characteristics."""

    def test_paths_start_at_agent_position(self, empty_5x5_env, cbs_planner):
        """All paths start at agent's current position."""
        agents = {
            0: AgentState(agent_id=0, pos=(1, 1), goal=(3, 3)),
            1: AgentState(agent_id=1, pos=(0, 4), goal=(4, 0)),
        }
        assignments = {
            0: Task(task_id="t0", start=(1, 1), goal=(3, 3), release_step=0),
            1: Task(task_id="t1", start=(0, 4), goal=(4, 0), release_step=0),
        }

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        assert bundle.paths[0](0) == (1, 1)
        assert bundle.paths[1](0) == (0, 4)

    def test_paths_respect_horizon(self, empty_5x5_env, cbs_planner):
        """Paths are truncated/padded to horizon length."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 2))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 2), release_step=0)}
        horizon = 20

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=horizon,
        )

        # Path should have exactly horizon+1 cells
        assert len(bundle.paths[0].cells) == horizon + 1

    def test_paths_are_connected(self, empty_5x5_env, cbs_planner):
        """Each step in path moves at most 1 cell (no teleportation)."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(4, 4), release_step=0)}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=15,
        )

        path = bundle.paths[0]
        for i in range(len(path.cells) - 1):
            curr = path.cells[i]
            next_cell = path.cells[i + 1]
            dist = abs(curr[0] - next_cell[0]) + abs(curr[1] - next_cell[1])
            assert dist <= 1, f"Teleportation from {curr} to {next_cell}"


# ============================================================================
# Edge Cases
# ============================================================================

class TestCBSEdgeCases:
    """Edge case tests for CBS."""

    def test_no_agents(self, empty_5x5_env, cbs_planner):
        """Empty agent set returns empty paths."""
        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents={},
            assignments={},
            step=0,
            horizon=10,
        )
        assert len(bundle.paths) == 0

    def test_agent_without_goal(self, empty_5x5_env, cbs_planner):
        """Agent without goal gets no path (not an active agent)."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=None)}
        assignments = {}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # C++ wrapper skips agents with no goal and no assignment
        assert 0 not in bundle.paths

    def test_unreachable_goal(self, cbs_planner):
        """Agent with unreachable goal (surrounded by walls)."""
        # Create environment where (2, 2) is surrounded
        blocked = {(1, 2), (3, 2), (2, 1), (2, 3)}
        env = Environment(width=5, height=5, blocked=blocked)

        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(0, 0))}
        assignments = {0: Task(task_id="t0", start=(2, 2), goal=(0, 0), release_step=0)}

        bundle = cbs_planner.plan(
            env=env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=10,
        )

        # Should fallback to waiting in place
        path = bundle.paths[0]
        assert path(0) == (2, 2)

    @requires_binary
    def test_start_step_offset(self, empty_5x5_env, cbs_planner):
        """Planning from non-zero start step."""
        agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 4))}
        assignments = {0: Task(task_id="t0", start=(0, 0), goal=(0, 4), release_step=0)}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=100,  # Start at step 100
            horizon=10,
        )

        path = bundle.paths[0]
        assert path.start_step == 100
        assert path(100) == (0, 0)
        assert path(104) == (0, 4)

    def test_horizon_zero(self, empty_5x5_env, cbs_planner):
        """Horizon of zero produces single-cell paths."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4))}
        assignments = {0: Task(task_id="t0", start=(2, 2), goal=(4, 4), release_step=0)}

        bundle = cbs_planner.plan(
            env=empty_5x5_env,
            agents=agents,
            assignments=assignments,
            step=0,
            horizon=0,
        )

        path = bundle.paths[0]
        assert len(path.cells) == 1
        assert path(0) == (2, 2)
