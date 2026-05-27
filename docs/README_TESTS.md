# Test Suite Documentation

## Human-Aware Lifelong MAPF under Partial Observability — Test Suite

This document provides comprehensive documentation for the HA-LMAPF test suite, covering all test files, their purpose, and how to run them.

---

## Table of Contents

1. [Overview](#overview)
2. [Running Tests](#running-tests)
3. [Test Coverage Summary](#test-coverage-summary)
4. [Test Files Reference](#test-files-reference)
    - [Core Module Tests](#core-module-tests)
    - [Planning Algorithm Tests](#planning-algorithm-tests)
    - [Human-Related Tests](#human-related-tests)
    - [Conflict Resolution Tests](#conflict-resolution-tests)
    - [Simulation Tests](#simulation-tests)
    - [Integration Tests](#integration-tests)
5. [Writing New Tests](#writing-new-tests)
6. [Test Fixtures and Utilities](#test-fixtures-and-utilities)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The test suite contains **359 tests** across **21 test files**, providing approximately **85% code coverage** of the core functionality.

### Test Categories

| Category | Files | Tests | Description |
|----------|-------|-------|-------------|
| Core Modules | 3 | 102 | Data types, grid utilities, environment |
| Planning Algorithms | 3 | 64 | CBS, LaCAM, local A* planner |
| Human-Related | 2 | 57 | Human models, motion prediction |
| Conflict Resolution | 3 | 25 | Token passing, PIBT, priority rules |
| Simulation | 4 | 36 | Metrics, one-shot MAPF, safety |
| Integration | 5 | 24 | Allocators, baselines, end-to-end |

### Test Framework

- **Framework**: pytest
- **Python Version**: 3.10+
- **Configuration**: `pyproject.toml`

---

## Running Tests

### Run All Tests

```bash
# Basic run
python3 -m pytest tests/

# Verbose output
python3 -m pytest tests/ -v

# With short traceback
python3 -m pytest tests/ -v --tb=short
```

### Run Specific Test Files

```bash
# Single file
python3 -m pytest tests/test_cbs_solver.py -v

# Multiple files
python3 -m pytest tests/test_cbs_solver.py tests/test_lacam_solver.py -v
```

### Run Specific Test Classes or Functions

```bash
# Run a specific class
python3 -m pytest tests/test_core_types.py::TestAgentState -v

# Run a specific test function
python3 -m pytest tests/test_allocators.py::test_greedy_assigns_nearest -v
```

### Run Tests by Category

```bash
# Core tests only
python3 -m pytest tests/test_core_*.py tests/test_environment.py -v

# Planning algorithm tests
python3 -m pytest tests/test_cbs_solver.py tests/test_lacam_solver.py tests/test_local_planner.py -v

# Human-related tests
python3 -m pytest tests/test_human_*.py -v

# Conflict resolution tests
python3 -m pytest tests/test_conflict_resolvers.py tests/test_token_passing.py -v
```

### Run Tests with Coverage Report

```bash
# Install coverage tool
pip install pytest-cov

# Run with coverage
python3 -m pytest tests/ --cov=ha_lmapf --cov-report=html

# View report in browser
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Run Tests in Parallel

```bash
# Install pytest-xdist
pip install pytest-xdist

# Run tests in parallel (4 workers)
python3 -m pytest tests/ -n 4
```

---

## Test Coverage Summary

| Module | Coverage | Key Tests |
|--------|----------|-----------|
| `core/types.py` | 95% | AgentState, HumanState, Task, TimedPath, Metrics |
| `core/grid.py` | 100% | Manhattan distance, neighbors, bounds checking |
| `core/metrics.py` | 90% | Task lifecycle, event counters, finalization |
| `simulation/environment.py` | 95% | is_free, is_blocked, sample_free_cell |
| `global_tier/solvers/cbsh2_wrapper.py` | 85% | Vertex/edge conflicts, path planning |
| `global_tier/solvers/lacam_official_wrapper.py` | 80% | Prioritized planning, reservations |
| `global_tier/task_allocator.py` | 90% | Greedy, Hungarian, Auction |
| `local_tier/local_planner.py` | 90% | A* search, hard/soft safety |
| `local_tier/conflict_resolution/` | 85% | Token passing, PIBT, priority rules |
| `humans/models.py` | 80% | RandomWalk, Aisle, Adversarial, Mixed |
| `humans/prediction.py` | 85% | MyopicPredictor, occupancy forecasting |
| `baselines/` | 75% | PIBTOnlyController, baseline properties |

---

## Test Files Reference

### Core Module Tests

#### `test_core_types.py` (44 tests)

Tests all core data types used throughout the system.

**Classes Tested:**
- `TestStepAction` - Movement actions (UP, DOWN, LEFT, RIGHT, WAIT)
- `TestAgentState` - Robot state representation
- `TestHumanState` - Human state representation
- `TestTask` - Task data structure
- `TestTimedPath` - Time-indexed path representation
- `TestPlanBundle` - Collection of agent plans
- `TestObservation` - Agent observation data
- `TestMetrics` - Performance metrics data
- `TestSimConfig` - Simulation configuration

**Key Tests:**
```python
def test_agent_state_creation()      # Basic AgentState creation
    def test_timed_path_call()           # Path indexing by timestep
    def test_metrics_to_dict()           # Metrics serialization
    def test_sim_config_defaults()       # Default configuration values
```

---

#### `test_core_grid.py` (32 tests)

Tests grid utilities for spatial operations.

**Classes Tested:**
- `TestInBounds` - Boundary checking
- `TestManhattan` - Manhattan distance calculation
- `TestNeighbors` - 4-connected neighbor generation
- `TestCoordinateConversion` - Row-column to index conversion
- `TestApplyAction` - Action application to positions
- `TestLineOfSightCircle` - Field of view calculation
- `TestIterManhattanBall` - FOV iteration
- `TestGridIntegration` - Combined functionality

**Key Tests:**
```python
def test_manhattan_distance()        # Distance calculation
    def test_neighbors_4_connected()     # UP, DOWN, LEFT, RIGHT neighbors
    def test_apply_action()              # Movement application
    def test_fov_radius()                # Field of view cells
```

---

#### `test_environment.py` (26 tests)

Tests the simulation environment.

**Classes Tested:**
- `TestEnvironmentInit` - Environment initialization
- `TestIsBlockedIsFree` - Obstacle checking
- `TestSampleFreeCell` - Random cell sampling
- `TestMapLoading` - Map file loading
- `TestEnvironmentEdgeCases` - Edge cases

**Key Tests:**
```python
def test_is_blocked_out_of_bounds()  # Out-of-bounds handling
    def test_sample_free_cell()          # Random free cell selection
    def test_load_from_map_file()        # MovingAI map loading
    def test_all_blocked_raises_error()  # Invalid environment handling
```

---

### Planning Algorithm Tests

#### `test_cbs_solver.py` (18 tests)

Tests the Conflict-Based Search solver.

**Classes Tested:**
- `TestCBSSingleAgent` - Single agent planning
- `TestCBSMultiAgent` - Multi-agent coordination
- `TestCBSPathQuality` - Path optimality
- `TestCBSBudget` - Search budget limits
- `TestCBSEdgeCases` - Edge cases

**Key Tests:**
```python
def test_single_agent_direct_path()  # Basic pathfinding
    def test_head_on_vertex_conflict()   # Vertex conflict resolution
    def test_edge_swap_conflict()        # Edge conflict resolution
    def test_three_agents_coordination() # Multi-agent scenarios
    def test_paths_are_connected()       # Path validity
```

**Example:**
```python
def test_head_on_vertex_conflict(self, empty_5x5_env):
    """Two agents wanting same cell get conflict-free paths."""
    agents = {
        0: AgentState(agent_id=0, pos=(0, 2), goal=(4, 2)),
        1: AgentState(agent_id=1, pos=(4, 2), goal=(0, 2)),
    }
    solver = CBSSolver()
    bundle = solver.plan(agents, empty_5x5_env, start_step=0, horizon=20)

    # Verify no conflicts
    for step in range(20):
        positions = [bundle.paths[aid](step) for aid in agents]
        assert len(positions) == len(set(positions))  # No duplicates
```

---

#### `test_lacam_solver.py` (18 tests)

Tests the LaCAM prioritized planner.

**Classes Tested:**
- `TestLaCAMSingleAgent` - Single agent planning
- `TestLaCAMMultiAgent` - Multi-agent coordination
- `TestLaCAMPathQuality` - Path quality verification
- `TestLaCAMScalability` - Performance with many agents
- `TestLaCAMEdgeCases` - Edge cases

**Key Tests:**
```python
def test_prioritized_planning()      # Priority-based planning
    def test_reservation_table()         # Collision avoidance
    def test_many_agents_scalability()   # 20+ agent scenarios
    def test_narrow_corridor()           # Tight space navigation
```

---

#### `test_local_planner.py` (28 tests)

Tests the local A* planner for reactive navigation.

**Classes Tested:**
- `TestBasicPathfinding` - Basic A* functionality
- `TestStaticObstacleAvoidance` - Wall avoidance
- `TestHardSafetyMode` - Hard safety constraints
- `TestSoftSafetyMode` - Soft safety constraints
- `TestSearchBudget` - Expansion limits
- `TestLocalPlannerEdgeCases` - Edge cases
- `TestLocalPlannerIntegration` - Combined scenarios

**Key Tests:**
```python
def test_hard_safety_blocks()        # Hard safety mode
    def test_soft_safety_allows()        # Soft safety fallback
    def test_obstacle_avoidance()        # Static wall avoidance
    def test_max_expansions_limit()      # Search budget
```

**Hard vs Soft Safety Example:**
```python
def test_hard_vs_soft_different_results(self, empty_5x5_env):
    """Hard and soft modes produce different paths when blocked."""
    hard = AStarLocalPlanner(hard_safety=True)
    soft = AStarLocalPlanner(hard_safety=False)

    blocked = {(2, c) for c in range(5)}  # Complete wall

    hard_path = hard.plan(env, (0, 0), (4, 4), blocked=blocked)
    soft_path = soft.plan(env, (0, 0), (4, 4), blocked=blocked)

    assert hard_path == []      # No path in hard mode
    assert len(soft_path) > 0   # Path exists in soft mode
```

---

### Human-Related Tests

#### `test_human_models.py` (35 tests)

Tests all human motion models.

**Classes Tested:**
- `TestRandomWalkModel` - Random walk behavior
- `TestAisleFollowerModel` - Aisle-following behavior
- `TestAdversarialModel` - Adversarial behavior
- `TestMixedPopulationModel` - Mixed behavior types
- `TestReplayModel` - Trajectory replay
- `TestHumanModelCommon` - Common properties

**Key Tests:**
```python
def test_random_walk_legal_moves()   # Movement validity
    def test_aisle_preference()          # Corridor following
    def test_adversarial_blocking()      # Robot blocking behavior
    def test_mixed_distribution()        # Population type mixing
    def test_replay_deterministic()      # Trajectory playback
```

**Human Model Properties:**
```python
def test_all_models_stay_in_bounds(self, env, rng):
    """All human models produce valid positions."""
    models = [
        RandomWalkHumanModel(),
        AisleFollowerHumanModel(),
        AdversarialHumanModel(),
    ]
    for model in models:
        for _ in range(100):
            human = HumanState(human_id=0, pos=(2, 2))
            next_pos = model.step(human, env, agents={}, rng=rng)
            assert env.is_free(next_pos)
```

---

#### `test_human_prediction.py` (22 tests)

Tests human motion prediction.

**Classes Tested:**
- `TestMyopicPredictor` - Occupancy prediction
- `TestPredictionHorizon` - Multi-step forecasting
- `TestNeighborInclusion` - Neighbor cell expansion
- `TestMultipleHumans` - Multiple human tracking
- `TestPredictorEdgeCases` - Edge cases

**Key Tests:**
```python
def test_current_position_occupied()  # Human at current pos
    def test_horizon_expansion()          # Multi-step prediction
    def test_neighbor_inclusion()         # Conservative expansion
    def test_multiple_humans_tracked()    # Multi-human scenarios
```

---

### Conflict Resolution Tests

#### `test_conflict_resolvers.py` (23 tests)

Tests all conflict resolution strategies.

**Classes Tested:**
- `TestConflictDetection` - Conflict identification
- `TestTokenPassingResolver` - Token-based resolution
- `TestPIBTResolver` - PIBT-style resolution
- `TestPriorityRulesResolver` - Priority-based resolution
- `TestActionCalculation` - Action computation
- `TestConflictResolverEdgeCases` - Edge cases

**Key Tests:**
```python
def test_vertex_conflict_detected()   # Same-cell detection
    def test_edge_conflict_detected()     # Swap detection
    def test_token_holder_proceeds()      # Token priority
    def test_priority_rules_winner()      # Priority ranking
    def test_fairness_rotation()          # Fair priority rotation
```

---

#### `test_token_passing.py` (1 test)

Integration test for token passing with fairness.

```python
def test_token_passing_priority_and_fairness_rotation():
    """Token holder wins conflicts; priority rotates after K conflicts."""
```

---

#### `test_vertex_edge_conflicts.py` (1 test)

Integration test for CBS conflict handling.

```python
def test_cbs_avoids_vertex_and_edge_conflicts():
    """CBS solver produces conflict-free paths."""
```

---

### Simulation Tests

#### `test_metrics.py` (27 tests)

Tests the metrics tracking system.

**Classes Tested:**
- `TestTaskLifecycle` - Task release/assign/complete tracking
- `TestEventCounters` - Collision and replan counting
- `TestTiming` - Timing measurements
- `TestCostMetrics` - Makespan and sum-of-costs
- `TestFinalization` - Metrics aggregation
- `TestCSVOutput` - CSV export
- `TestMetricsIntegration` - Full simulation scenario

**Key Tests:**
```python
def test_throughput_calculation()     # tasks/step
    def test_flowtime_calculation()       # avg completion time
    def test_safety_violation_rate()      # violations/step
    def test_timing_statistics()          # planning time stats
    def test_csv_output()                 # CSV export format
```

---

#### `test_one_shot_mapf.py` (4 tests)

Tests classical (one-shot) MAPF mode.

**Key Tests:**
```python
def test_one_shot_generates_one_task_per_agent()  # Task generation
    def test_one_shot_plans_once()                    # Single planning
    def test_one_shot_terminates_early()              # Early termination
    def test_one_shot_with_allocator_options()        # Allocator support
```

---

#### `test_local_safety.py` (1 test)

Tests local safety enforcement around humans.

```python
def test_agent_controller_respects_human_safety():
    """Agent controller maintains safety buffer around humans."""
```

---

#### `test_partial_observability.py` (1 test)

Tests partial observability (limited FOV).

```python
def test_partial_observability_fov():
    """Agents only observe entities within field of view radius."""
```

---

### Integration Tests

#### `test_allocators.py` (6 tests)

Tests task allocation algorithms.

**Key Tests:**
```python
def test_greedy_assigns_nearest()      # Greedy allocation
    def test_hungarian_assigns_optimally() # Optimal allocation
    def test_auction_assigns_tasks()       # Auction-based allocation
    def test_hungarian_asymmetric()        # Unequal agents/tasks
    def test_allocators_skip_busy_agents() # Busy agent handling
    def test_direct_to_goal_tasks()        # Legacy task format
```

---

#### `test_baseline.py` (17 tests)

Tests baseline controller implementations.

**Classes Tested:**
- `TestPIBTOnlyController` - PIBT baseline
- `TestMultiAgentBaselines` - Multi-agent scenarios
- `TestBaselineProperties` - Determinism, validity
- `TestBaselineEdgeCases` - Edge cases
- `TestBaselineIntegration` - Integration scenarios

**Key Tests:**
```python
def test_moves_toward_goal()          # Greedy movement
    def test_waits_without_goal()         # No-goal handling
    def test_avoids_blocked_cells()       # Obstacle avoidance
    def test_deterministic_action()       # Same state = same action
    def test_ignores_global_plan()        # Local-only behavior
```

---

#### `test_map_loading.py` (1 test)

Tests map file loading.

```python
def test_map_loading_tmp():
    """Load a MovingAI format map file."""
```

---

#### `test_task_stream.py` (1 test)

Tests task stream loading and ordering.

```python
def test_task_stream_ordering_and_release():
    """Tasks are ordered by release_step, then task_id."""
```

---

#### `test_receding_horizon_handoff.py` (1 test)

Tests receding horizon replanning triggers.

```python
def test_receding_horizon_handoff():
    """Replanning triggers at configured intervals."""
```

---

## Writing New Tests

### Test File Template

```python
"""
Tests for [Module Name].

Tests [brief description of what is tested].
"""
import pytest
from ha_lmapf.module import ClassToTest


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_fixture():
    """Create a sample test fixture."""
    return ClassToTest()


# ============================================================================
# Test Classes
# ============================================================================

class TestClassName:
    """Tests for ClassName functionality."""

    def test_basic_functionality(self, sample_fixture):
        """Test basic functionality works."""
        result = sample_fixture.method()
        assert result == expected_value

    def test_edge_case(self, sample_fixture):
        """Test edge case handling."""
        with pytest.raises(ValueError):
            sample_fixture.invalid_operation()
```

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Test files | `test_<module>.py` | `test_cbs_solver.py` |
| Test classes | `Test<ClassName>` | `TestCBSSolver` |
| Test functions | `test_<description>` | `test_single_agent_path` |
| Fixtures | `<descriptive_name>` | `empty_5x5_env` |

### Best Practices

1. **One assertion per test** (when practical)
2. **Descriptive test names** that explain what is tested
3. **Use fixtures** for shared setup
4. **Test edge cases** explicitly
5. **Use parametrize** for multiple similar tests
6. **Mock external dependencies** when needed

---

## Test Fixtures and Utilities

### Common Fixtures

```python
@pytest.fixture
def empty_5x5_env():
    """Create an empty 5x5 environment."""
    return Environment(width=5, height=5, blocked=set())

@pytest.fixture
def env_with_walls():
    """Create environment with wall obstacles."""
    blocked = {(1, 1), (1, 2), (1, 3), (3, 1), (3, 2), (3, 3)}
    return Environment(width=5, height=5, blocked=blocked)

@pytest.fixture
def empty_observation():
    """Create an empty observation."""
    return Observation(visible_humans={}, visible_agents={}, blocked=set())

@pytest.fixture
def rng():
    """Create a seeded random number generator."""
    return np.random.default_rng(42)
```

### MockSimState

A mock implementation of `SimStateView` used in many tests:

```python
@dataclass
class MockSimState:
    """Mock SimStateView for testing."""
    agents: Dict[int, AgentState]
    env: Environment
    step: int = 0
    _plan_bundle: Optional[PlanBundle] = None
    _decided_next_positions: Dict[int, Tuple[int, int]] = None

    def plans(self):
        return self._plan_bundle

    def decided_next_positions(self):
        return self._decided_next_positions or {}
```

---

## Troubleshooting

### Common Issues

#### Import Errors

```bash
# Ensure package is installed
pip install -e .

# Verify installation
python3 -c "import ha_lmapf; print('OK')"
```

#### Missing Dependencies

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-xdist
```

#### Test Discovery Issues

```bash
# Check test collection
python3 -m pytest tests/ --collect-only

# Verify test directory exists
ls tests/
```

#### Slow Tests

```bash
# Run tests in parallel
python3 -m pytest tests/ -n auto

# Skip slow tests (if marked)
python3 -m pytest tests/ -m "not slow"
```

### Debugging Failed Tests

```bash
# Run single failing test with verbose output
python3 -m pytest tests/test_file.py::test_name -v -s

# Show local variables on failure
python3 -m pytest tests/ --tb=long

# Drop into debugger on failure
python3 -m pytest tests/ --pdb
```

---

## Summary

| Metric | Value |
|--------|-------|
| Total Test Files | 21 |
| Total Tests | 359 |
| Estimated Coverage | ~85% |
| Average Test Time | ~5 seconds |

The test suite provides comprehensive coverage of:
- Core data structures and utilities
- Planning algorithms (CBS, LaCAM, A*)
- Human behavior models and prediction
- Conflict resolution strategies
- Simulation engine and metrics
- Task allocation algorithms
- Baseline controller implementations

For questions or issues with tests, please consult the test source files in `tests/`.
