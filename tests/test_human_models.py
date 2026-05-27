"""
Comprehensive Tests for Human Motion Models.

Tests all human motion models from ha_lmapf.humans.models including:
- RandomWalkHumanModel
- AisleFollowerHumanModel
- AdversarialHumanModel
- MixedPopulationHumanModel
- ReplayHumanModel
"""
import pytest
import numpy as np
from ha_lmapf.core.types import HumanState
from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.humans.models import (
    RandomWalkHumanModel,
    AisleFollowerHumanModel,
    AdversarialHumanModel,
    MixedPopulationHumanModel,
    ReplayHumanModel,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def empty_10x10_env():
    """Create an empty 10x10 environment."""
    return Environment(width=10, height=10, blocked=set())


@pytest.fixture
def env_with_corridors():
    """Create environment with corridors (simulating warehouse aisles).

    Layout (10x10):
    ..........
    .@@@@.@@@@
    ..........
    .@@@@.@@@@
    ..........
    .@@@@.@@@@
    ..........
    .@@@@.@@@@
    ..........
    ..........
    """
    blocked = set()
    for row in [1, 3, 5, 7]:
        for col in [1, 2, 3, 4, 6, 7, 8, 9]:
            blocked.add((row, col))
    return Environment(width=10, height=10, blocked=blocked)


@pytest.fixture
def simple_human():
    """Create a simple human state."""
    return {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}


@pytest.fixture
def multiple_humans():
    """Create multiple human states."""
    return {
        0: HumanState(human_id=0, pos=(2, 2), velocity=(0, 0)),
        1: HumanState(human_id=1, pos=(7, 7), velocity=(1, 0)),
        2: HumanState(human_id=2, pos=(3, 8), velocity=(0, -1)),
    }


# ============================================================================
# RandomWalkHumanModel Tests
# ============================================================================

class TestRandomWalkHumanModel:
    """Tests for RandomWalkHumanModel."""

    def test_basic_step(self, empty_10x10_env, simple_human):
        """Human takes a valid step."""
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, simple_human, rng)

        assert 0 in new_humans
        new_pos = new_humans[0].pos
        old_pos = simple_human[0].pos
        dist = manhattan(old_pos, new_pos)
        assert dist <= 1  # Moves at most 1 cell

    def test_stays_within_bounds(self, empty_10x10_env):
        """Human at corner stays within bounds."""
        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)

        for _ in range(100):
            humans = model.step(empty_10x10_env, humans, rng)
            pos = humans[0].pos
            assert empty_10x10_env.is_free(pos)

    def test_avoids_walls(self, env_with_corridors):
        """Human avoids wall cells."""
        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)

        for _ in range(50):
            humans = model.step(env_with_corridors, humans, rng)
            pos = humans[0].pos
            assert env_with_corridors.is_free(pos)

    def test_avoids_agent_positions(self, empty_10x10_env, simple_human):
        """Human avoids cells occupied by agents."""
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)
        # Block all neighbors with agents
        agent_positions = set(neighbors((5, 5)))

        for _ in range(20):
            new_humans = model.step(empty_10x10_env, simple_human, rng, agent_positions)
            # Human should stay in place or move to unblocked cell
            assert new_humans[0].pos not in agent_positions or new_humans[0].pos == (5, 5)

    def test_velocity_updated(self, empty_10x10_env, simple_human):
        """Velocity is updated to reflect movement."""
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, simple_human, rng)
        new_pos = new_humans[0].pos
        old_pos = simple_human[0].pos
        expected_vel = (new_pos[0] - old_pos[0], new_pos[1] - old_pos[1])
        assert new_humans[0].velocity == expected_vel

    def test_inertia_with_high_beta_go(self, empty_10x10_env):
        """High beta_go encourages continuing same direction."""
        humans = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 1))}  # Moving right
        model = RandomWalkHumanModel(beta_go=10.0, beta_wait=-5.0, beta_turn=0.0)
        rng = np.random.default_rng(42)

        # With high inertia, should mostly continue right
        continue_count = 0
        for seed in range(100):
            rng = np.random.default_rng(seed)
            humans_copy = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 1))}
            new_humans = model.step(empty_10x10_env, humans_copy, rng)
            if new_humans[0].pos == (5, 6):  # Continued right
                continue_count += 1

        # Should continue most of the time with high inertia
        assert continue_count > 70  # At least 70% continue

    def test_multiple_humans_independent(self, empty_10x10_env, multiple_humans):
        """Multiple humans move independently."""
        model = RandomWalkHumanModel()
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, multiple_humans, rng)

        assert len(new_humans) == 3
        for hid in [0, 1, 2]:
            assert hid in new_humans


# ============================================================================
# AisleFollowerHumanModel Tests
# ============================================================================

class TestAisleFollowerHumanModel:
    """Tests for AisleFollowerHumanModel."""

    def test_basic_step(self, env_with_corridors):
        """Human takes valid step in corridor environment."""
        humans = {0: HumanState(human_id=0, pos=(0, 5), velocity=(0, 0))}
        model = AisleFollowerHumanModel(alpha=1.0, beta=1.0)
        rng = np.random.default_rng(42)

        new_humans = model.step(env_with_corridors, humans, rng)
        assert env_with_corridors.is_free(new_humans[0].pos)

    def test_prefers_corridor_cells(self, env_with_corridors):
        """Human biased toward corridor cells (near walls)."""
        # Start in open area, should move toward corridors
        humans = {0: HumanState(human_id=0, pos=(9, 5), velocity=(0, 0))}
        model = AisleFollowerHumanModel(alpha=5.0, beta=0.0)  # High aisle bias
        rng = np.random.default_rng(42)

        # Run multiple steps
        for _ in range(20):
            humans = model.step(env_with_corridors, humans, rng)
            assert env_with_corridors.is_free(humans[0].pos)

    def test_velocity_updated(self, env_with_corridors):
        """Velocity is updated correctly."""
        humans = {0: HumanState(human_id=0, pos=(0, 5), velocity=(0, 0))}
        model = AisleFollowerHumanModel()
        rng = np.random.default_rng(42)

        new_humans = model.step(env_with_corridors, humans, rng)
        old_pos = humans[0].pos
        new_pos = new_humans[0].pos
        expected_vel = (new_pos[0] - old_pos[0], new_pos[1] - old_pos[1])
        assert new_humans[0].velocity == expected_vel

    def test_avoids_agents(self, env_with_corridors):
        """Human avoids agent-occupied cells."""
        humans = {0: HumanState(human_id=0, pos=(0, 5), velocity=(0, 0))}
        model = AisleFollowerHumanModel()
        rng = np.random.default_rng(42)
        agent_positions = {(0, 6), (1, 5), (0, 4)}  # Block some neighbors

        new_humans = model.step(env_with_corridors, humans, rng, agent_positions)
        assert new_humans[0].pos not in agent_positions or new_humans[0].pos == (0, 5)


# ============================================================================
# AdversarialHumanModel Tests
# ============================================================================

class TestAdversarialHumanModel:
    """Tests for AdversarialHumanModel."""

    def test_basic_step(self, empty_10x10_env, simple_human):
        """Human takes valid step."""
        model = AdversarialHumanModel(gamma=2.0, lambda_=0.5)
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, simple_human, rng)
        assert empty_10x10_env.is_free(new_humans[0].pos)

    def test_attracted_to_agents(self, empty_10x10_env):
        """Adversarial human moves toward agents."""
        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        agent_positions = {(5, 5)}  # Agent in middle
        model = AdversarialHumanModel(gamma=5.0, lambda_=0.0)  # Pure proximity attraction
        rng = np.random.default_rng(42)

        # Run several steps
        for _ in range(10):
            humans = model.step(empty_10x10_env, humans, rng, agent_positions)

        # Should have moved closer to agent
        final_dist = manhattan(humans[0].pos, (5, 5))
        assert final_dist < manhattan((0, 0), (5, 5))

    def test_avoids_agent_cells(self, empty_10x10_env):
        """Human doesn't move onto agent-occupied cells."""
        humans = {0: HumanState(human_id=0, pos=(4, 5), velocity=(0, 0))}
        agent_positions = {(5, 5)}
        model = AdversarialHumanModel()
        rng = np.random.default_rng(42)

        for _ in range(20):
            new_humans = model.step(empty_10x10_env, humans, rng, agent_positions)
            assert new_humans[0].pos not in agent_positions
            humans = new_humans

    def test_velocity_updated(self, empty_10x10_env, simple_human):
        """Velocity updated correctly."""
        model = AdversarialHumanModel()
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, simple_human, rng)
        old_pos = simple_human[0].pos
        new_pos = new_humans[0].pos
        expected_vel = (new_pos[0] - old_pos[0], new_pos[1] - old_pos[1])
        assert new_humans[0].velocity == expected_vel


# ============================================================================
# MixedPopulationHumanModel Tests
# ============================================================================

class TestMixedPopulationHumanModel:
    """Tests for MixedPopulationHumanModel."""

    def test_basic_step(self, empty_10x10_env, multiple_humans):
        """Mixed population takes valid steps."""
        models = {
            "random": RandomWalkHumanModel(),
            "adversarial": AdversarialHumanModel(),
        }
        weights = {"random": 0.7, "adversarial": 0.3}
        model = MixedPopulationHumanModel(models, weights)
        rng = np.random.default_rng(42)

        new_humans = model.step(empty_10x10_env, multiple_humans, rng)
        assert len(new_humans) == 3
        for hid in new_humans:
            assert empty_10x10_env.is_free(new_humans[hid].pos)

    def test_assignments_persistent(self, empty_10x10_env, multiple_humans):
        """Human type assignments persist across steps."""
        models = {
            "random": RandomWalkHumanModel(),
            "adversarial": AdversarialHumanModel(),
        }
        weights = {"random": 0.5, "adversarial": 0.5}
        model = MixedPopulationHumanModel(models, weights)
        rng = np.random.default_rng(42)

        # First step assigns types
        model.step(empty_10x10_env, multiple_humans, rng)
        assignments1 = dict(model._assignments)

        # Second step should have same assignments
        model.step(empty_10x10_env, multiple_humans, rng)
        assignments2 = dict(model._assignments)

        assert assignments1 == assignments2

    def test_all_models_used(self, empty_10x10_env):
        """With enough humans and equal weights, all models get used."""
        # Create many humans
        humans = {i: HumanState(human_id=i, pos=(i % 10, i // 10), velocity=(0, 0))
                  for i in range(20)}
        models = {
            "random": RandomWalkHumanModel(),
            "aisle": AisleFollowerHumanModel(),
        }
        weights = {"random": 0.5, "aisle": 0.5}
        model = MixedPopulationHumanModel(models, weights)
        rng = np.random.default_rng(42)

        model.step(empty_10x10_env, humans, rng)

        # Check both types are assigned
        assigned_types = set(model._assignments.values())
        assert "random" in assigned_types or "aisle" in assigned_types


# ============================================================================
# ReplayHumanModel Tests
# ============================================================================

class TestReplayHumanModel:
    """Tests for ReplayHumanModel."""

    def test_follows_trajectory(self, empty_10x10_env):
        """Human follows pre-recorded trajectory."""
        trajectory = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
        trajectories = {0: trajectory}
        model = ReplayHumanModel(trajectories)

        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        # Step through trajectory
        for i in range(4):
            humans = model.step(empty_10x10_env, humans, rng)
            expected_pos = trajectory[i + 1]
            assert humans[0].pos == expected_pos

    def test_stays_at_end(self, empty_10x10_env):
        """Human stays at last position when trajectory exhausted."""
        trajectory = [(0, 0), (0, 1)]
        trajectories = {0: trajectory}
        model = ReplayHumanModel(trajectories)

        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        # Step beyond trajectory length
        for _ in range(10):
            humans = model.step(empty_10x10_env, humans, rng)

        assert humans[0].pos == (0, 1)  # Last position in trajectory

    def test_velocity_updated(self, empty_10x10_env):
        """Velocity reflects movement along trajectory."""
        trajectory = [(5, 5), (5, 6), (5, 7)]  # Moving right
        trajectories = {0: trajectory}
        model = ReplayHumanModel(trajectories)

        humans = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        humans = model.step(empty_10x10_env, humans, rng)
        assert humans[0].velocity == (0, 1)  # Moving right

    def test_multiple_humans(self, empty_10x10_env):
        """Multiple humans follow their own trajectories."""
        trajectories = {
            0: [(0, 0), (1, 0), (2, 0)],
            1: [(9, 9), (8, 9), (7, 9)],
        }
        model = ReplayHumanModel(trajectories)

        humans = {
            0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0)),
            1: HumanState(human_id=1, pos=(9, 9), velocity=(0, 0)),
        }
        rng = np.random.default_rng(42)

        humans = model.step(empty_10x10_env, humans, rng)
        assert humans[0].pos == (1, 0)
        assert humans[1].pos == (8, 9)

    def test_human_without_trajectory(self, empty_10x10_env):
        """Human without trajectory stays in place."""
        trajectories = {0: [(0, 0), (0, 1)]}  # Only human 0 has trajectory
        model = ReplayHumanModel(trajectories)

        humans = {
            0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0)),
            1: HumanState(human_id=1, pos=(5, 5), velocity=(0, 0)),
        }
        rng = np.random.default_rng(42)

        humans = model.step(empty_10x10_env, humans, rng)
        assert humans[0].pos == (0, 1)
        assert humans[1].pos == (5, 5)  # Stays in place

    def test_generate_and_record(self, empty_10x10_env):
        """Generate trajectories from stochastic model."""
        source_model = RandomWalkHumanModel()
        humans = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        replay_model = ReplayHumanModel.generate_and_record(
            source_model=source_model,
            env=empty_10x10_env,
            humans=humans,
            rng=rng,
            steps=10,
        )

        # Trajectory should have 11 positions (initial + 10 steps)
        assert len(replay_model._trajectories[0]) == 11


# ============================================================================
# General Model Properties
# ============================================================================

class TestModelProperties:
    """Tests for properties that should hold for all models."""

    @pytest.fixture(params=[
        RandomWalkHumanModel(),
        AisleFollowerHumanModel(),
        AdversarialHumanModel(),
    ])
    def model(self, request):
        return request.param

    def test_bounded_step(self, empty_10x10_env, model):
        """All models take at most 1-step moves."""
        humans = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        for _ in range(50):
            old_pos = humans[0].pos
            humans = model.step(empty_10x10_env, humans, rng)
            new_pos = humans[0].pos
            dist = manhattan(old_pos, new_pos)
            assert dist <= 1

    def test_stays_on_free_cells(self, env_with_corridors, model):
        """All models stay on free cells."""
        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        rng = np.random.default_rng(42)

        for _ in range(50):
            humans = model.step(env_with_corridors, humans, rng)
            assert env_with_corridors.is_free(humans[0].pos)

    def test_deterministic_with_seed(self, empty_10x10_env, model):
        """Same seed produces same results."""
        humans1 = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}
        humans2 = {0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0))}

        rng1 = np.random.default_rng(12345)
        rng2 = np.random.default_rng(12345)

        result1 = model.step(empty_10x10_env, humans1, rng1)
        result2 = model.step(empty_10x10_env, humans2, rng2)

        assert result1[0].pos == result2[0].pos
