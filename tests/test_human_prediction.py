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


# ===========================================================================
# Resume-prompt-5 STAGE 1 — HumanModel.predict_next interface
# ===========================================================================
#
# These tests cover the non-mutating one-tick prediction interface added
# to all five human models for the γ (evade) algorithm variant.  They are
# distinct from the MyopicPredictor tests above (a different abstraction).

import copy
import numpy as np
from scipy import stats

from ha_lmapf.simulation.environment import Environment
from ha_lmapf.humans.models import (
    RandomWalkHumanModel,
    AisleFollowerHumanModel,
    AdversarialHumanModel,
    MixedPopulationHumanModel,
    ReplayHumanModel,
)


def _empty_env(n=7):
    return Environment(width=n, height=n, blocked=set())


def _corridor_env():
    # 3x3 with all of human(1,1)'s neighbors blocked except (1,2),
    # forcing a single legal non-current successor.
    return Environment(width=3, height=3, blocked={(0, 1), (2, 1), (1, 0)})


def _all_five_models():
    """One warmed instance of each model (False regime so the blocking
    branch is exercised where relevant).  Replay gets a short trajectory."""
    return {
        "random_walk": RandomWalkHumanModel(humans_block_on_agent_cells=False),
        "aisle": AisleFollowerHumanModel(humans_block_on_agent_cells=False),
        "adversarial": AdversarialHumanModel(humans_block_on_agent_cells=False),
        "mixed": MixedPopulationHumanModel(
            models={
                "random_walk": RandomWalkHumanModel(humans_block_on_agent_cells=False),
                "aisle": AisleFollowerHumanModel(humans_block_on_agent_cells=False),
            },
            weights={"random_walk": 0.5, "aisle": 0.5},
            humans_block_on_agent_cells=False,
        ),
        "replay": ReplayHumanModel(
            trajectories={0: [(5, 5), (5, 6), (6, 6)], 1: [(2, 2), (2, 3), (2, 4)]},
        ),
    }


def _two_humans():
    return {
        0: HumanState(human_id=0, pos=(5, 5), velocity=(0, 1)),
        1: HumanState(human_id=1, pos=(2, 2), velocity=(1, 0)),
    }


def test_predict_next_does_not_mutate_state():
    """For each of the five models: warm any lazy caches, snapshot the
    model state and a companion RNG, call predict_next, and assert
    nothing changed.  This is the test that catches a predict_next
    that secretly calls step() (which would advance _step / assignments
    or consume the RNG)."""
    env = _empty_env()
    humans = _two_humans()
    for name, model in _all_five_models().items():
        # Warm lazy caches (phi / bottleneck) with a first call so the
        # memoization population is not mistaken for a mutation.
        model.predict_next(env, humans, agent_positions=None)

        before = repr(model.__dict__)
        rng = np.random.default_rng(0)
        rng_state_before = rng.bit_generator.state

        model.predict_next(env, humans, agent_positions=None)

        assert repr(model.__dict__) == before, (
            f"{name}: predict_next mutated model state."
        )
        # predict_next takes no rng and must not advance one.
        assert rng.bit_generator.state == rng_state_before, (
            f"{name}: predict_next advanced an RNG."
        )


def test_predict_next_probabilities_sum_to_one():
    """Each per-human distribution sums to 1.0 within 1e-9."""
    env = _empty_env()
    humans = _two_humans()
    for name, model in _all_five_models().items():
        preds = model.predict_next(env, humans, agent_positions=None)
        assert set(preds.keys()) == set(humans.keys()), name
        for hid, dist in preds.items():
            total = sum(dist.values())
            assert abs(total - 1.0) < 1e-9, (
                f"{name} human {hid}: probabilities sum to {total}, not 1.0"
            )


def test_predict_next_respects_blocking_regime():
    """3x3 corridor: human at (1,1) has a single legal non-current
    successor (1,2); an agent sits there.  Under True that cell has
    probability 0; under False it has probability > 0."""
    env = _corridor_env()
    humans = {0: HumanState(human_id=0, pos=(1, 1), velocity=(0, 0))}
    agent_positions = {99: (1, 2)}

    blocking_models = {
        "random_walk": RandomWalkHumanModel,
        "aisle": AisleFollowerHumanModel,
        "adversarial": AdversarialHumanModel,
    }
    for name, cls in blocking_models.items():
        m_true = cls(humans_block_on_agent_cells=True)
        m_false = cls(humans_block_on_agent_cells=False)
        d_true = m_true.predict_next(env, humans, agent_positions)[0]
        d_false = m_false.predict_next(env, humans, agent_positions)[0]
        assert d_true.get((1, 2), 0.0) == 0.0, (
            f"{name}: True regime gave (1,2) prob {d_true.get((1, 2))}; "
            f"should be 0 (agent blocks it)."
        )
        assert d_false.get((1, 2), 0.0) > 0.0, (
            f"{name}: False regime gave (1,2) prob 0; should be > 0."
        )

    # Mixed delegates to its sub-models; same expectation.
    m_true = MixedPopulationHumanModel(
        models={"random_walk": RandomWalkHumanModel(humans_block_on_agent_cells=True)},
        weights={"random_walk": 1.0},
        humans_block_on_agent_cells=True,
    )
    m_false = MixedPopulationHumanModel(
        models={"random_walk": RandomWalkHumanModel(humans_block_on_agent_cells=False)},
        weights={"random_walk": 1.0},
        humans_block_on_agent_cells=False,
    )
    assert m_true.predict_next(env, humans, agent_positions)[0].get((1, 2), 0.0) == 0.0
    assert m_false.predict_next(env, humans, agent_positions)[0].get((1, 2), 0.0) > 0.0


def test_replay_predict_next_is_delta_on_next_recorded():
    """ReplayHumanModel.predict_next returns a single-cell delta on the
    next recorded position at each step, and a delta on the current
    position once the trajectory is exhausted."""
    env = _empty_env()
    traj = {0: [(1, 1), (1, 2), (1, 3)]}
    model = ReplayHumanModel(trajectories=traj)
    humans = {0: HumanState(human_id=0, pos=(1, 1), velocity=(0, 0))}

    # step 0 -> predict next recorded (1,2)
    d = model.predict_next(env, humans)[0]
    assert d == {(1, 2): 1.0}, d
    humans = model.step(env, humans, np.random.default_rng(0))

    # step 1 -> predict next recorded (1,3)
    d = model.predict_next(env, humans)[0]
    assert d == {(1, 3): 1.0}, d
    humans = model.step(env, humans, np.random.default_rng(0))

    # trajectory exhausted -> delta on current position
    d = model.predict_next(env, humans)[0]
    assert d == {humans[0].pos: 1.0}, d


def _chisquare_predict_vs_step(model_factory, env, human, n=2000, seed0=0):
    """Sample step() n times (fresh RNG each) and chi-square the
    empirical distribution against predict_next's analytic one."""
    humans = {0: human}
    analytic = model_factory().predict_next(env, humans)[0]
    cells = sorted(analytic.keys())
    idx = {c: i for i, c in enumerate(cells)}
    obs = np.zeros(len(cells))
    for k in range(n):
        m = model_factory()
        rng = np.random.default_rng(seed0 + k)
        nxt = m.step(env, humans, rng)[0].pos
        # step may produce a cell only if it's a legal successor; the
        # analytic dist covers exactly those, so this never KeyErrors.
        obs[idx[nxt]] += 1
    exp = np.array([analytic[c] * n for c in cells])
    # Drop cells with tiny expected counts to keep the chi-square valid.
    keep = exp >= 5
    chi2, p = stats.chisquare(obs[keep], exp[keep])
    return p, dict(zip(cells, obs.astype(int)))


def test_predict_next_agrees_with_step_marginally():
    """The analytic prediction must match the process step() samples.
    Verified on three (model, env) fixtures; each must clear p > 0.01."""
    fixtures = [
        ("random_walk/empty",
         lambda: RandomWalkHumanModel(),
         _empty_env(),
         HumanState(human_id=0, pos=(3, 3), velocity=(0, 1))),
        ("aisle/empty",
         lambda: AisleFollowerHumanModel(),
         _empty_env(),
         HumanState(human_id=0, pos=(3, 3), velocity=(1, 0))),
        ("adversarial/empty",
         lambda: AdversarialHumanModel(),
         _empty_env(),
         HumanState(human_id=0, pos=(3, 3), velocity=(0, 1))),
    ]
    results = {}
    for name, factory, env, human in fixtures:
        p, counts = _chisquare_predict_vs_step(factory, env, human)
        results[name] = p
        assert p > 0.01, (
            f"{name}: chi-square p={p:.4f} <= 0.01; predict_next does "
            f"not match the step() process.  counts={counts}"
        )
    # Surface the p-values for the commit-message record.
    print("STAGE1 chi-square p-values:", {k: round(v, 4) for k, v in results.items()})
