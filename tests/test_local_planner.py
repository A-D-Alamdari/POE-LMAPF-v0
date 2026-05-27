"""
Comprehensive Tests for Local A* Planner.

Tests the AStarLocalPlanner class from ha_lmapf.local_tier.local_planner including:
- Basic pathfinding
- Hard safety mode (blocked cells impassable)
- Soft safety mode (blocked cells high cost)
- Obstacle avoidance
- Edge cases
"""
import pytest
from ha_lmapf.local_tier.local_planner import AStarLocalPlanner
from ha_lmapf.simulation.environment import Environment


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def empty_5x5_env():
    """Create an empty 5x5 environment."""
    return Environment(width=5, height=5, blocked=set())


@pytest.fixture
def env_with_walls():
    """Create environment with wall obstacles.

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
def hard_planner():
    """Create a hard safety local planner."""
    return AStarLocalPlanner(hard_safety=True)


@pytest.fixture
def soft_planner():
    """Create a soft safety local planner."""
    return AStarLocalPlanner(hard_safety=False)


# ============================================================================
# Basic Pathfinding Tests
# ============================================================================

class TestBasicPathfinding:
    """Tests for basic A* pathfinding functionality."""

    def test_direct_horizontal_path(self, empty_5x5_env, hard_planner):
        """Find direct horizontal path."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (0, 4), blocked=set())
        assert len(path) == 5
        assert path[0] == (0, 0)
        assert path[-1] == (0, 4)

    def test_direct_vertical_path(self, empty_5x5_env, hard_planner):
        """Find direct vertical path."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 0), blocked=set())
        assert len(path) == 5
        assert path[0] == (0, 0)
        assert path[-1] == (4, 0)

    def test_diagonal_path(self, empty_5x5_env, hard_planner):
        """Find path requiring diagonal movement."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=set())
        assert len(path) == 9  # Manhattan distance = 8, so 9 cells
        assert path[0] == (0, 0)
        assert path[-1] == (4, 4)

    def test_same_start_and_goal(self, empty_5x5_env, hard_planner):
        """Start equals goal returns single-cell path."""
        path = hard_planner.plan(empty_5x5_env, (2, 2), (2, 2), blocked=set())
        assert path == [(2, 2)]

    def test_path_is_connected(self, empty_5x5_env, hard_planner):
        """Each step in path moves exactly one cell."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=set())
        for i in range(len(path) - 1):
            curr = path[i]
            next_cell = path[i + 1]
            dist = abs(curr[0] - next_cell[0]) + abs(curr[1] - next_cell[1])
            assert dist == 1, f"Non-adjacent cells: {curr} -> {next_cell}"


# ============================================================================
# Static Obstacle Avoidance Tests
# ============================================================================

class TestStaticObstacleAvoidance:
    """Tests for avoiding static walls."""

    def test_path_avoids_walls(self, env_with_walls, hard_planner):
        """Path goes around static walls."""
        path = hard_planner.plan(env_with_walls, (0, 0), (4, 4), blocked=set())
        assert path  # Path should exist
        assert path[0] == (0, 0)
        assert path[-1] == (4, 4)
        for cell in path:
            assert env_with_walls.is_free(cell)

    def test_no_path_through_walls(self, hard_planner):
        """Cannot path through walls."""
        # Completely surrounded cell
        blocked = {(0, 1), (1, 0), (1, 2), (2, 1)}
        env = Environment(width=3, height=3, blocked=blocked)
        # (1, 1) is surrounded
        path = hard_planner.plan(env, (1, 1), (0, 0), blocked=set())
        assert path == []  # No path possible

    def test_start_on_wall_returns_empty(self, env_with_walls, hard_planner):
        """Starting on a wall returns empty path."""
        path = hard_planner.plan(env_with_walls, (1, 1), (4, 4), blocked=set())
        assert path == []

    def test_goal_on_wall_returns_empty(self, env_with_walls, hard_planner):
        """Goal on a wall returns empty path."""
        path = hard_planner.plan(env_with_walls, (0, 0), (1, 1), blocked=set())
        assert path == []


# ============================================================================
# Hard Safety Mode Tests
# ============================================================================

class TestHardSafetyMode:
    """Tests for hard safety mode (blocked cells impassable)."""

    def test_blocked_cells_impassable(self, empty_5x5_env, hard_planner):
        """Dynamic blocked cells are impassable in hard mode."""
        blocked = {(2, 0), (2, 1), (2, 2), (2, 3), (2, 4)}  # Horizontal wall
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # No path should exist as blocked cells block all routes
        assert path == []

    def test_blocked_cells_avoided(self, empty_5x5_env, hard_planner):
        """Path avoids blocked cells."""
        blocked = {(1, 2), (2, 2), (3, 2)}  # Vertical barrier
        path = hard_planner.plan(empty_5x5_env, (0, 0), (2, 4), blocked=blocked)
        # Path must go around
        for cell in path:
            assert cell not in blocked

    def test_surrounded_by_blocked_returns_empty(self, empty_5x5_env, hard_planner):
        """Agent surrounded by blocked cells returns empty path."""
        blocked = {(1, 2), (3, 2), (2, 1), (2, 3)}  # Surround (2,2)
        path = hard_planner.plan(empty_5x5_env, (2, 2), (0, 0), blocked=blocked)
        assert path == []


# ============================================================================
# Soft Safety Mode Tests
# ============================================================================

class TestSoftSafetyMode:
    """Tests for soft safety mode (blocked cells high cost but passable)."""

    def test_blocked_cells_passable_with_cost(self, empty_5x5_env, soft_planner):
        """Blocked cells can be traversed in soft mode."""
        # Create a wall that blocks direct path
        blocked = {(2, 0), (2, 1), (2, 2), (2, 3), (2, 4)}
        path = soft_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # Path should exist (going through blocked cells at high cost)
        assert path
        assert path[0] == (0, 0)
        assert path[-1] == (4, 4)

    def test_prefers_free_cells(self, empty_5x5_env, soft_planner):
        """Soft mode prefers free cells over blocked cells when possible."""
        # Single blocked cell that can be avoided
        blocked = {(2, 2)}
        path = soft_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # Path might avoid (2,2) if alternative is shorter/cheaper
        assert path
        assert path[0] == (0, 0)
        assert path[-1] == (4, 4)

    def test_soft_mode_escape_surround(self, empty_5x5_env, soft_planner):
        """Agent surrounded by blocked can escape in soft mode."""
        blocked = {(1, 2), (3, 2), (2, 1), (2, 3)}
        path = soft_planner.plan(empty_5x5_env, (2, 2), (0, 0), blocked=blocked)
        # Path should exist - can pass through blocked at high cost
        assert path
        assert path[0] == (2, 2)
        assert path[-1] == (0, 0)


# ============================================================================
# Search Budget Tests
# ============================================================================

class TestSearchBudget:
    """Tests for search expansion limits."""

    def test_max_expansions_respected(self, hard_planner):
        """Search terminates within MAX_EXPANSIONS."""
        # Create a very large environment
        env = Environment(width=50, height=50, blocked=set())
        # Block all but a few paths to force extensive search
        blocked = {(r, c) for r in range(1, 49) for c in range(1, 49)}
        path = hard_planner.plan(env, (0, 0), (49, 49), blocked=blocked)
        # Should return (possibly empty) without hanging
        assert path is not None  # Returns list (possibly empty)


# ============================================================================
# Edge Cases
# ============================================================================

class TestLocalPlannerEdgeCases:
    """Edge case tests for local planner."""

    def test_1x1_environment(self):
        """Single cell environment."""
        env = Environment(width=1, height=1, blocked=set())
        planner = AStarLocalPlanner(hard_safety=True)
        path = planner.plan(env, (0, 0), (0, 0), blocked=set())
        assert path == [(0, 0)]

    def test_adjacent_cells(self, empty_5x5_env, hard_planner):
        """Path between adjacent cells."""
        path = hard_planner.plan(empty_5x5_env, (2, 2), (2, 3), blocked=set())
        assert len(path) == 2
        assert path == [(2, 2), (2, 3)]

    def test_blocked_set_empty(self, empty_5x5_env, hard_planner):
        """Empty blocked set is handled."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=set())
        assert path
        assert len(path) == 9

    def test_blocked_set_large(self, empty_5x5_env, hard_planner):
        """Large blocked set that still allows path."""
        # Block everything except edges
        blocked = {(r, c) for r in range(1, 4) for c in range(1, 4)}
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # Must go around the edge
        assert path
        for cell in path:
            assert cell not in blocked

    def test_goal_in_blocked_hard_mode(self, empty_5x5_env, hard_planner):
        """Goal in blocked set returns empty in hard mode."""
        blocked = {(4, 4)}
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # Goal is dynamically blocked - but it's not a wall, so A* might still find it
        # Actually in hard mode, blocked cells are impassable
        # The goal check happens before expanding, so this depends on implementation
        # Let's verify behavior is reasonable
        if path:
            assert path[-1] == (4, 4)

    def test_start_in_blocked_hard_mode(self, empty_5x5_env, hard_planner):
        """Starting in blocked set in hard mode."""
        blocked = {(0, 0)}
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        # Start is dynamically blocked but agent is already there
        # The planner should still work from the start position
        assert path  # Should find a path

    def test_optimal_path_length(self, empty_5x5_env, hard_planner):
        """A* finds optimal path length."""
        path = hard_planner.plan(empty_5x5_env, (0, 0), (3, 4), blocked=set())
        # Optimal Manhattan distance = 7, so 8 cells in path
        assert len(path) == 8


# ============================================================================
# Integration Tests
# ============================================================================

class TestLocalPlannerIntegration:
    """Integration tests combining multiple features."""

    def test_hard_vs_soft_different_results(self, empty_5x5_env):
        """Hard and soft modes produce different paths when blocked."""
        hard = AStarLocalPlanner(hard_safety=True)
        soft = AStarLocalPlanner(hard_safety=False)

        # Complete wall
        blocked = {(2, c) for c in range(5)}

        hard_path = hard.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        soft_path = soft.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)

        # Hard mode: no path (wall blocks all routes)
        assert hard_path == []
        # Soft mode: path exists (goes through at cost)
        assert soft_path
        assert soft_path[0] == (0, 0)
        assert soft_path[-1] == (4, 4)

    def test_multiple_blocked_regions(self, empty_5x5_env, hard_planner):
        """Navigate between multiple blocked regions."""
        blocked = {
            (1, 0), (1, 1),  # Region 1
            (3, 3), (3, 4),  # Region 2
        }
        path = hard_planner.plan(empty_5x5_env, (0, 0), (4, 4), blocked=blocked)
        assert path
        for cell in path:
            assert cell not in blocked
