"""
Comprehensive Tests for Human Motion Prediction.

Tests the MyopicPredictor class from ha_lmapf.humans.prediction including:
- Basic occupancy forecasting
- Neighbor inclusion option
- Multiple human handling
- Horizon expansion
"""
import pytest
from ha_lmapf.core.types import HumanState
from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.humans.prediction import MyopicPredictor


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def single_human():
    """Create a single human state."""
    return {0: HumanState(human_id=0, pos=(5, 5), velocity=(1, 0))}


@pytest.fixture
def multiple_humans():
    """Create multiple human states."""
    return {
        0: HumanState(human_id=0, pos=(2, 2), velocity=(0, 1)),
        1: HumanState(human_id=1, pos=(7, 7), velocity=(-1, 0)),
        2: HumanState(human_id=2, pos=(3, 8), velocity=(0, 0)),
    }


# ============================================================================
# Basic Prediction Tests
# ============================================================================

class TestMyopicPredictorBasic:
    """Basic tests for MyopicPredictor."""

    def test_returns_list_of_sets(self, single_human):
        """Predict returns a list of sets for each timestep."""
        predictor = MyopicPredictor()
        horizon = 5

        result = predictor.predict(single_human, horizon)

        assert isinstance(result, list)
        assert len(result) == horizon
        for s in result:
            assert isinstance(s, set)

    def test_horizon_zero_returns_empty(self, single_human):
        """Horizon of 0 returns empty list."""
        predictor = MyopicPredictor()
        result = predictor.predict(single_human, 0)
        assert result == []

    def test_negative_horizon_returns_empty(self, single_human):
        """Negative horizon treated as 0."""
        predictor = MyopicPredictor()
        result = predictor.predict(single_human, -5)
        assert result == []


# ============================================================================
# Occupancy Tests with include_neighbors=True
# ============================================================================

class TestMyopicPredictorWithNeighbors:
    """Tests for MyopicPredictor with include_neighbors=True (default)."""

    def test_includes_current_position(self, single_human):
        """Human's current position is included."""
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(single_human, 5)

        for t in range(5):
            assert (5, 5) in result[t]

    def test_includes_neighbors(self, single_human):
        """Human's neighbors are included."""
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(single_human, 5)

        expected_neighbors = [(4, 5), (6, 5), (5, 4), (5, 6)]
        for t in range(5):
            for nb in expected_neighbors:
                assert nb in result[t]

    def test_five_cells_per_human(self, single_human):
        """Each human contributes 5 cells (center + 4 neighbors)."""
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(single_human, 5)

        for t in range(5):
            assert len(result[t]) == 5

    def test_same_prediction_all_timesteps(self, single_human):
        """Myopic predictor uses same occupancy for all future timesteps."""
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(single_human, 10)

        reference = result[0]
        for t in range(1, 10):
            assert result[t] == reference


# ============================================================================
# Occupancy Tests with include_neighbors=False
# ============================================================================

class TestMyopicPredictorWithoutNeighbors:
    """Tests for MyopicPredictor with include_neighbors=False."""

    def test_only_current_position(self, single_human):
        """Only human's current position is included."""
        predictor = MyopicPredictor(include_neighbors=False)
        result = predictor.predict(single_human, 5)

        for t in range(5):
            assert result[t] == {(5, 5)}

    def test_one_cell_per_human(self, single_human):
        """Each human contributes 1 cell (center only)."""
        predictor = MyopicPredictor(include_neighbors=False)
        result = predictor.predict(single_human, 5)

        for t in range(5):
            assert len(result[t]) == 1


# ============================================================================
# Multiple Humans Tests
# ============================================================================

class TestMyopicPredictorMultipleHumans:
    """Tests for MyopicPredictor with multiple humans."""

    def test_all_humans_included(self, multiple_humans):
        """All human positions are included in prediction."""
        predictor = MyopicPredictor(include_neighbors=False)
        result = predictor.predict(multiple_humans, 5)

        for t in range(5):
            assert (2, 2) in result[t]
            assert (7, 7) in result[t]
            assert (3, 8) in result[t]

    def test_occupancy_union(self, multiple_humans):
        """Predicted set is union of all human occupancies."""
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(multiple_humans, 5)

        # Each human contributes 5 cells (with possible overlap)
        # 3 humans, max 15 cells, possibly fewer due to overlap
        for t in range(5):
            assert len(result[t]) <= 15
            assert len(result[t]) >= 3  # At least the center cells

    def test_overlapping_occupancy(self):
        """Adjacent humans have overlapping occupancy."""
        humans = {
            0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 0)),
            1: HumanState(human_id=1, pos=(5, 6), velocity=(0, 0)),  # Adjacent
        }
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(humans, 5)

        # Overlap at (5, 5) neighbor (5, 6) and (5, 6) center
        for t in range(5):
            assert (5, 5) in result[t]
            assert (5, 6) in result[t]


# ============================================================================
# Edge Cases
# ============================================================================

class TestMyopicPredictorEdgeCases:
    """Edge case tests for MyopicPredictor."""

    def test_empty_humans(self):
        """Empty humans dict returns empty sets."""
        predictor = MyopicPredictor()
        result = predictor.predict({}, 5)

        assert len(result) == 5
        for t in range(5):
            assert result[t] == set()

    def test_human_at_origin(self):
        """Human at (0, 0) produces valid neighbors (some negative)."""
        humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
        predictor = MyopicPredictor(include_neighbors=True)
        result = predictor.predict(humans, 3)

        # Neighbors include negative coords (out of bounds)
        for t in range(3):
            assert (0, 0) in result[t]
            assert (-1, 0) in result[t]  # Out of bounds but included
            assert (0, -1) in result[t]  # Out of bounds but included

    def test_long_horizon(self, single_human):
        """Long horizon produces consistent results."""
        predictor = MyopicPredictor()
        result = predictor.predict(single_human, 1000)

        assert len(result) == 1000
        # All timesteps should have same content
        reference = result[0]
        for t in range(1000):
            assert result[t] == reference

    def test_rng_parameter_unused(self, single_human):
        """RNG parameter is accepted but unused (myopic is deterministic)."""
        import numpy as np
        predictor = MyopicPredictor()

        rng = np.random.default_rng(42)
        result1 = predictor.predict(single_human, 5, rng=rng)

        rng = np.random.default_rng(999)
        result2 = predictor.predict(single_human, 5, rng=rng)

        # Results should be identical (deterministic)
        assert result1 == result2


# ============================================================================
# Interface Compliance Tests
# ============================================================================

class TestMyopicPredictorInterface:
    """Tests for HumanPredictor interface compliance."""

    def test_implements_predict_method(self):
        """MyopicPredictor implements predict method."""
        predictor = MyopicPredictor()
        assert hasattr(predictor, 'predict')
        assert callable(predictor.predict)

    def test_dataclass_attributes(self):
        """MyopicPredictor has expected attributes."""
        predictor = MyopicPredictor()
        assert hasattr(predictor, 'include_neighbors')

    def test_default_include_neighbors(self):
        """Default include_neighbors is True."""
        predictor = MyopicPredictor()
        assert predictor.include_neighbors is True

    def test_custom_include_neighbors(self):
        """Can set include_neighbors to False."""
        predictor = MyopicPredictor(include_neighbors=False)
        assert predictor.include_neighbors is False
