"""
Comprehensive Tests for Simulation Environment.

Tests the Environment class from ha_lmapf.simulation.environment including:
- Initialization with blocked cells
- is_blocked and is_free checks
- sample_free_cell functionality
- Map loading from files
"""
import pytest
import numpy as np
from ha_lmapf.simulation.environment import Environment


# ============================================================================
# Environment Initialization Tests
# ============================================================================

class TestEnvironmentInit:
    """Tests for Environment initialization."""

    def test_basic_creation(self):
        """Create environment with basic parameters."""
        env = Environment(width=10, height=8, blocked=set())
        assert env.width == 10
        assert env.height == 8
        assert len(env.blocked) == 0

    def test_with_blocked_cells(self):
        """Create environment with blocked cells."""
        blocked = {(1, 1), (2, 2), (3, 3)}
        env = Environment(width=10, height=10, blocked=blocked)
        assert len(env.blocked) == 3
        assert (1, 1) in env.blocked
        assert (2, 2) in env.blocked

    def test_free_cells_computed(self):
        """Verify free cells are precomputed."""
        blocked = {(0, 0), (0, 1)}
        env = Environment(width=3, height=3, blocked=blocked)
        # 3x3 = 9 cells, 2 blocked = 7 free
        assert len(env._free_cells) == 7

    def test_all_blocked_raises_error(self):
        """Environment with all cells blocked should raise ValueError."""
        blocked = {(r, c) for r in range(3) for c in range(3)}
        with pytest.raises(ValueError, match="no free cells"):
            Environment(width=3, height=3, blocked=blocked)

    def test_single_free_cell(self):
        """Environment with single free cell is valid."""
        blocked = {(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)}
        env = Environment(width=3, height=3, blocked=blocked)
        assert len(env._free_cells) == 1
        assert (1, 1) in env._free_cells


# ============================================================================
# is_blocked / is_free Tests
# ============================================================================

class TestIsBlockedIsFree:
    """Tests for is_blocked and is_free methods."""

    @pytest.fixture
    def simple_env(self):
        """Create a simple 5x5 environment with some blocked cells."""
        blocked = {(1, 1), (2, 2), (3, 3)}
        return Environment(width=5, height=5, blocked=blocked)

    def test_is_blocked_static_obstacles(self, simple_env):
        """Static obstacles are blocked."""
        assert simple_env.is_blocked((1, 1))
        assert simple_env.is_blocked((2, 2))
        assert simple_env.is_blocked((3, 3))

    def test_is_blocked_free_cells(self, simple_env):
        """Free cells are not blocked."""
        assert not simple_env.is_blocked((0, 0))
        assert not simple_env.is_blocked((4, 4))

    def test_is_blocked_out_of_bounds(self, simple_env):
        """Out of bounds cells are blocked."""
        assert simple_env.is_blocked((-1, 0))
        assert simple_env.is_blocked((0, -1))
        assert simple_env.is_blocked((5, 0))
        assert simple_env.is_blocked((0, 5))
        assert simple_env.is_blocked((100, 100))

    def test_is_free_free_cells(self, simple_env):
        """Free cells return True for is_free."""
        assert simple_env.is_free((0, 0))
        assert simple_env.is_free((4, 4))
        assert simple_env.is_free((0, 4))

    def test_is_free_blocked_cells(self, simple_env):
        """Blocked cells return False for is_free."""
        assert not simple_env.is_free((1, 1))
        assert not simple_env.is_free((2, 2))

    def test_is_free_out_of_bounds(self, simple_env):
        """Out of bounds cells return False for is_free."""
        assert not simple_env.is_free((-1, 0))
        assert not simple_env.is_free((5, 5))

    def test_is_blocked_is_free_inverse(self, simple_env):
        """is_blocked and is_free are inverses for in-bounds cells."""
        for r in range(5):
            for c in range(5):
                cell = (r, c)
                assert simple_env.is_blocked(cell) != simple_env.is_free(cell)


# ============================================================================
# sample_free_cell Tests
# ============================================================================

class TestSampleFreeCell:
    """Tests for sample_free_cell method."""

    @pytest.fixture
    def env(self):
        """Create environment for sampling tests."""
        blocked = {(0, 0), (0, 1), (1, 0)}
        return Environment(width=5, height=5, blocked=blocked)

    def test_sample_returns_free_cell(self, env):
        """Sampled cell is always free."""
        rng = np.random.default_rng(42)
        for _ in range(100):
            cell = env.sample_free_cell(rng)
            assert env.is_free(cell)

    def test_sample_never_returns_blocked(self, env):
        """Sampled cell is never blocked."""
        rng = np.random.default_rng(42)
        for _ in range(100):
            cell = env.sample_free_cell(rng)
            assert not env.is_blocked(cell)

    def test_sample_with_exclusions(self, env):
        """Sample respects exclusion set."""
        rng = np.random.default_rng(42)
        exclude = {(1, 1), (2, 2), (3, 3)}
        for _ in range(100):
            cell = env.sample_free_cell(rng, exclude=exclude)
            assert cell not in exclude
            assert env.is_free(cell)

    def test_sample_all_excluded_raises(self):
        """Sampling when all cells excluded raises RuntimeError."""
        # Create small environment
        env = Environment(width=2, height=2, blocked={(0, 0)})
        rng = np.random.default_rng(42)
        # Exclude all free cells
        exclude = {(0, 1), (1, 0), (1, 1)}
        with pytest.raises(RuntimeError, match="No free cells"):
            env.sample_free_cell(rng, exclude=exclude)

    def test_sample_deterministic_with_seed(self, env):
        """Same seed produces same samples."""
        rng1 = np.random.default_rng(12345)
        rng2 = np.random.default_rng(12345)
        samples1 = [env.sample_free_cell(rng1) for _ in range(10)]
        samples2 = [env.sample_free_cell(rng2) for _ in range(10)]
        assert samples1 == samples2

    def test_sample_single_free_cell(self):
        """Sample from environment with single free cell."""
        blocked = {(r, c) for r in range(3) for c in range(3) if (r, c) != (1, 1)}
        env = Environment(width=3, height=3, blocked=blocked)
        rng = np.random.default_rng(42)
        for _ in range(10):
            assert env.sample_free_cell(rng) == (1, 1)


# ============================================================================
# Map Loading Tests
# ============================================================================

class TestMapLoading:
    """Tests for loading environment from map files."""

    def test_load_from_map_file(self, tmp_path):
        """Load environment from a MovingAI map file."""
        # Create a simple map file
        map_content = """type octile
height 4
width 4
map
....
.@@.
.@@.
....
"""
        map_file = tmp_path / "test.map"
        map_file.write_text(map_content)

        env = Environment.load_from_map(str(map_file))
        assert env.width == 4
        assert env.height == 4
        # @ characters are blocked
        assert env.is_blocked((1, 1))
        assert env.is_blocked((1, 2))
        assert env.is_blocked((2, 1))
        assert env.is_blocked((2, 2))
        # . characters are free
        assert env.is_free((0, 0))
        assert env.is_free((3, 3))


# ============================================================================
# Edge Cases
# ============================================================================

class TestEnvironmentEdgeCases:
    """Edge case tests for Environment."""

    def test_1x1_environment(self):
        """Single cell environment."""
        env = Environment(width=1, height=1, blocked=set())
        assert env.is_free((0, 0))
        assert env.is_blocked((0, 1))
        assert env.is_blocked((1, 0))

    def test_wide_environment(self):
        """Very wide environment (1 row)."""
        env = Environment(width=100, height=1, blocked=set())
        assert env.is_free((0, 0))
        assert env.is_free((0, 99))
        assert not env.is_free((1, 0))

    def test_tall_environment(self):
        """Very tall environment (1 column)."""
        env = Environment(width=1, height=100, blocked=set())
        assert env.is_free((0, 0))
        assert env.is_free((99, 0))
        assert not env.is_free((0, 1))

    def test_large_blocked_set(self):
        """Environment with many blocked cells."""
        # Create checkerboard pattern
        blocked = {(r, c) for r in range(20) for c in range(20) if (r + c) % 2 == 0}
        env = Environment(width=20, height=20, blocked=blocked)
        assert env.is_blocked((0, 0))
        assert env.is_free((0, 1))
        assert env.is_blocked((1, 1))
        assert env.is_free((1, 0))

    def test_blocked_cells_immutable(self):
        """Modifying original blocked set doesn't affect environment."""
        blocked = {(1, 1)}
        env = Environment(width=5, height=5, blocked=blocked)
        blocked.add((2, 2))  # Modify original set
        assert not env.is_blocked((2, 2))  # Environment unaffected
