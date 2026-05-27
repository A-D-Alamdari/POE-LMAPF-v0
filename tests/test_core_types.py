"""
Comprehensive Tests for Core Type Definitions.

Tests all data structures in ha_lmapf.core.types including:
- StepAction enum
- AgentState, HumanState dataclasses
- Task dataclass
- TimedPath and PlanBundle structures
- Observation dataclass
- Metrics dataclass
- SimConfig dataclass
"""
import pytest
from ha_lmapf.core.types import (
    StepAction,
    AgentState,
    HumanState,
    Task,
    TimedPath,
    PlanBundle,
    Observation,
    Metrics,
    SimConfig,
)


# ============================================================================
# StepAction Tests
# ============================================================================

class TestStepAction:
    """Tests for the StepAction enumeration."""

    def test_all_actions_exist(self):
        """Verify all 5 actions are defined."""
        assert hasattr(StepAction, "UP")
        assert hasattr(StepAction, "DOWN")
        assert hasattr(StepAction, "LEFT")
        assert hasattr(StepAction, "RIGHT")
        assert hasattr(StepAction, "WAIT")

    def test_action_values(self):
        """Verify action values match expected strings."""
        assert StepAction.UP.value == "UP"
        assert StepAction.DOWN.value == "DOWN"
        assert StepAction.LEFT.value == "LEFT"
        assert StepAction.RIGHT.value == "RIGHT"
        assert StepAction.WAIT.value == "WAIT"

    def test_action_count(self):
        """Verify exactly 5 actions exist."""
        assert len(StepAction) == 5

    def test_action_equality(self):
        """Test enum equality comparisons."""
        assert StepAction.UP == StepAction.UP
        assert StepAction.UP != StepAction.DOWN

    def test_action_iteration(self):
        """Test iterating over all actions."""
        actions = list(StepAction)
        assert len(actions) == 5
        assert StepAction.UP in actions
        assert StepAction.WAIT in actions


# ============================================================================
# AgentState Tests
# ============================================================================

class TestAgentState:
    """Tests for AgentState dataclass."""

    def test_minimal_creation(self):
        """Create agent with only required fields."""
        agent = AgentState(agent_id=0, pos=(5, 10))
        assert agent.agent_id == 0
        assert agent.pos == (5, 10)
        assert agent.goal is None
        assert agent.carrying is False
        assert agent.task_id is None
        assert agent.done_tasks == 0
        assert agent.wait_steps == 0

    def test_full_creation(self):
        """Create agent with all fields specified."""
        agent = AgentState(
            agent_id=42,
            pos=(3, 7),
            goal=(10, 15),
            carrying=True,
            task_id="task_001",
            done_tasks=5,
            wait_steps=3,
        )
        assert agent.agent_id == 42
        assert agent.pos == (3, 7)
        assert agent.goal == (10, 15)
        assert agent.carrying is True
        assert agent.task_id == "task_001"
        assert agent.done_tasks == 5
        assert agent.wait_steps == 3

    def test_to_dict(self):
        """Test serialization to dictionary."""
        agent = AgentState(agent_id=1, pos=(0, 0), goal=(5, 5), carrying=True)
        d = agent.to_dict()
        assert isinstance(d, dict)
        assert d["agent_id"] == 1
        assert d["pos"] == (0, 0)
        assert d["goal"] == (5, 5)
        assert d["carrying"] is True

    def test_to_dict_with_none_goal(self):
        """Test serialization when goal is None."""
        agent = AgentState(agent_id=0, pos=(1, 1))
        d = agent.to_dict()
        assert d["goal"] is None

    def test_agent_equality(self):
        """Test dataclass equality."""
        a1 = AgentState(agent_id=0, pos=(1, 2))
        a2 = AgentState(agent_id=0, pos=(1, 2))
        a3 = AgentState(agent_id=0, pos=(1, 3))
        assert a1 == a2
        assert a1 != a3

    def test_negative_agent_id(self):
        """Negative agent IDs should be allowed (dataclass doesn't validate)."""
        agent = AgentState(agent_id=-1, pos=(0, 0))
        assert agent.agent_id == -1


# ============================================================================
# HumanState Tests
# ============================================================================

class TestHumanState:
    """Tests for HumanState dataclass."""

    def test_minimal_creation(self):
        """Create human with only required fields."""
        human = HumanState(human_id=0, pos=(5, 5))
        assert human.human_id == 0
        assert human.pos == (5, 5)
        assert human.velocity == (0, 0)

    def test_with_velocity(self):
        """Create human with velocity specified."""
        human = HumanState(human_id=1, pos=(3, 4), velocity=(1, 0))
        assert human.velocity == (1, 0)

    def test_negative_velocity(self):
        """Test negative velocity (moving up/left)."""
        human = HumanState(human_id=0, pos=(5, 5), velocity=(-1, -1))
        assert human.velocity == (-1, -1)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        human = HumanState(human_id=2, pos=(7, 8), velocity=(0, 1))
        d = human.to_dict()
        assert d["human_id"] == 2
        assert d["pos"] == (7, 8)
        assert d["velocity"] == (0, 1)

    def test_human_equality(self):
        """Test dataclass equality."""
        h1 = HumanState(human_id=0, pos=(1, 1))
        h2 = HumanState(human_id=0, pos=(1, 1))
        assert h1 == h2


# ============================================================================
# Task Tests
# ============================================================================

class TestTask:
    """Tests for Task dataclass."""

    def test_creation(self):
        """Create a task with all fields."""
        task = Task(
            task_id="task_001",
            start=(1, 2),
            goal=(10, 20),
            release_step=5,
        )
        assert task.task_id == "task_001"
        assert task.start == (1, 2)
        assert task.goal == (10, 20)
        assert task.release_step == 5

    def test_to_dict(self):
        """Test serialization to dictionary."""
        task = Task(task_id="t1", start=(0, 0), goal=(5, 5), release_step=0)
        d = task.to_dict()
        assert d["task_id"] == "t1"
        assert d["start"] == (0, 0)
        assert d["goal"] == (5, 5)
        assert d["release_step"] == 0

    def test_same_start_and_goal(self):
        """Task can have same start and goal (edge case)."""
        task = Task(task_id="t", start=(3, 3), goal=(3, 3), release_step=0)
        assert task.start == task.goal

    def test_direct_to_goal_task(self):
        """Test legacy direct-to-goal task format with start=(-1,-1)."""
        task = Task(task_id="direct", start=(-1, -1), goal=(5, 5), release_step=0)
        assert task.start == (-1, -1)


# ============================================================================
# TimedPath Tests
# ============================================================================

class TestTimedPath:
    """Tests for TimedPath dataclass."""

    def test_creation(self):
        """Create a basic timed path."""
        cells = [(0, 0), (0, 1), (0, 2)]
        path = TimedPath(cells=cells, start_step=10)
        assert path.cells == cells
        assert path.start_step == 10

    def test_call_exact_index(self):
        """Test __call__ at exact indices."""
        path = TimedPath(cells=[(0, 0), (1, 0), (2, 0)], start_step=5)
        assert path(5) == (0, 0)  # First cell
        assert path(6) == (1, 0)  # Second cell
        assert path(7) == (2, 0)  # Third cell

    def test_call_before_start(self):
        """Test __call__ before start_step returns first cell."""
        path = TimedPath(cells=[(5, 5), (5, 6)], start_step=10)
        assert path(0) == (5, 5)
        assert path(9) == (5, 5)

    def test_call_after_end(self):
        """Test __call__ after path ends returns last cell."""
        path = TimedPath(cells=[(0, 0), (1, 1), (2, 2)], start_step=0)
        assert path(3) == (2, 2)
        assert path(100) == (2, 2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        path = TimedPath(cells=[(0, 0), (1, 1)], start_step=5)
        d = path.to_dict()
        assert d["cells"] == [(0, 0), (1, 1)]
        assert d["start_step"] == 5

    def test_single_cell_path(self):
        """Test path with single cell (WAIT in place)."""
        path = TimedPath(cells=[(3, 3)], start_step=0)
        assert path(0) == (3, 3)
        assert path(10) == (3, 3)

    def test_empty_path_access(self):
        """Empty path should raise IndexError when accessed."""
        path = TimedPath(cells=[], start_step=0)
        with pytest.raises(IndexError):
            _ = path(0)


# ============================================================================
# PlanBundle Tests
# ============================================================================

class TestPlanBundle:
    """Tests for PlanBundle dataclass."""

    def test_creation(self):
        """Create a plan bundle with multiple agents."""
        path1 = TimedPath(cells=[(0, 0), (0, 1)], start_step=0)
        path2 = TimedPath(cells=[(5, 5), (5, 4)], start_step=0)
        bundle = PlanBundle(
            paths={0: path1, 1: path2},
            created_step=0,
            horizon=10,
        )
        assert len(bundle.paths) == 2
        assert 0 in bundle.paths
        assert 1 in bundle.paths
        assert bundle.created_step == 0
        assert bundle.horizon == 10

    def test_to_dict(self):
        """Test serialization to dictionary."""
        path = TimedPath(cells=[(1, 1)], start_step=5)
        bundle = PlanBundle(paths={0: path}, created_step=5, horizon=20)
        d = bundle.to_dict()
        assert "paths" in d
        assert "0" in d["paths"] or 0 in d["paths"]
        assert d["created_step"] == 5
        assert d["horizon"] == 20

    def test_empty_bundle(self):
        """Empty plan bundle (no agents)."""
        bundle = PlanBundle(paths={}, created_step=0, horizon=10)
        assert len(bundle.paths) == 0


# ============================================================================
# Observation Tests
# ============================================================================

class TestObservation:
    """Tests for Observation dataclass."""

    def test_default_creation(self):
        """Create observation with defaults."""
        obs = Observation()
        assert obs.visible_humans == {}
        assert obs.visible_agents == {}
        assert obs.blocked == set()

    def test_with_visible_entities(self):
        """Create observation with visible humans and agents."""
        human = HumanState(human_id=0, pos=(5, 5))
        agent = AgentState(agent_id=1, pos=(3, 3))
        obs = Observation(
            visible_humans={0: human},
            visible_agents={1: agent},
            blocked={(10, 10), (11, 11)},
        )
        assert 0 in obs.visible_humans
        assert 1 in obs.visible_agents
        assert (10, 10) in obs.blocked

    def test_to_dict(self):
        """Test serialization to dictionary."""
        human = HumanState(human_id=0, pos=(1, 1))
        obs = Observation(visible_humans={0: human}, blocked={(2, 2)})
        d = obs.to_dict()
        assert "visible_humans" in d
        assert "blocked" in d
        assert (2, 2) in d["blocked"] or [2, 2] in d["blocked"]


# ============================================================================
# Metrics Tests
# ============================================================================

class TestMetrics:
    """Tests for Metrics dataclass."""

    def test_default_values(self):
        """Test all default values are zero or appropriate."""
        m = Metrics()
        assert m.throughput == 0.0
        assert m.completed_tasks == 0
        assert m.mean_flowtime == 0.0
        assert m.collisions_agent_agent == 0
        assert m.collisions_agent_human == 0
        assert m.near_misses == 0
        assert m.replans == 0
        assert m.total_wait_steps == 0
        assert m.steps == 0
        assert m.safety_violations == 0
        assert m.makespan == 0
        assert m.sum_of_costs == 0

    def test_custom_values(self):
        """Test metrics with custom values."""
        m = Metrics(
            throughput=0.5,
            completed_tasks=100,
            collisions_agent_agent=2,
            collisions_agent_human=1,
            steps=1000,
        )
        assert m.throughput == 0.5
        assert m.completed_tasks == 100
        assert m.collisions_agent_agent == 2

    def test_to_dict(self):
        """Test serialization to dictionary."""
        m = Metrics(throughput=0.25, completed_tasks=50)
        d = m.to_dict()
        assert d["throughput"] == 0.25
        assert d["completed_tasks"] == 50

    def test_all_metric_fields_present(self):
        """Verify all expected metric fields exist."""
        m = Metrics()
        d = m.to_dict()
        expected_fields = [
            "throughput", "completed_tasks", "mean_flowtime",
            "collisions_agent_agent", "collisions_agent_human",
            "near_misses", "replans", "total_wait_steps", "steps",
            "safety_violations", "safety_violation_rate",
            "global_replans", "local_replans", "intervention_rate",
            "mean_service_time", "median_flowtime", "max_flowtime",
            "human_passive_wait_steps", "mean_planning_time_ms",
            "p95_planning_time_ms", "max_planning_time_ms",
            "mean_decision_time_ms", "p95_decision_time_ms",
            "makespan", "sum_of_costs", "delay_events",
        ]
        for field in expected_fields:
            assert field in d, f"Missing field: {field}"


# ============================================================================
# SimConfig Tests
# ============================================================================

class TestSimConfig:
    """Tests for SimConfig dataclass."""

    def test_minimal_creation(self):
        """Create config with only required field.  Defaults updated to
        paper Section 5.1: 2000-step lifelong runs."""
        cfg = SimConfig(map_path="data/maps/test.map")
        assert cfg.map_path == "data/maps/test.map"
        assert cfg.seed == 0
        assert cfg.steps == 2000
        assert cfg.num_agents == 1
        assert cfg.num_humans == 0

    def test_full_creation(self):
        """Create config with all fields specified."""
        cfg = SimConfig(
            map_path="data/maps/warehouse.map",
            task_stream_path="tasks.json",
            seed=42,
            steps=2000,
            num_agents=20,
            num_humans=5,
            fov_radius=5,
            safety_radius=2,
            global_solver="lacam",
            replan_every=30,
            horizon=60,
            communication_mode="priority",
            local_planner="astar",
            human_model="adversarial",
            hard_safety=False,
            mode="one_shot",
            task_allocator="hungarian",
        )
        assert cfg.num_agents == 20
        assert cfg.num_humans == 5
        assert cfg.global_solver == "lacam"
        assert cfg.mode == "one_shot"
        assert cfg.task_allocator == "hungarian"
        assert cfg.hard_safety is False

    def test_to_dict(self):
        """Test serialization to dictionary."""
        cfg = SimConfig(map_path="test.map", num_agents=10)
        d = cfg.to_dict()
        assert d["map_path"] == "test.map"
        assert d["num_agents"] == 10

    def test_default_modes(self):
        """Test default mode values.  Defaults updated to paper
        Section 5.1: LaCAM* (registered as ``lacam_official`` in the
        factory) and Wait-Based conflict resolution (formerly
        ``"priority"``, renamed to ``"wait_based"`` per paper §4.3
        terminology — the legacy value is still accepted via the
        factory alias in ``simulator.py``)."""
        cfg = SimConfig(map_path="test.map")
        assert cfg.mode == "lifelong"
        assert cfg.global_solver == "lacam_official"
        assert cfg.communication_mode == "wait_based"
        assert cfg.task_allocator == "congestion_avoidance"

    def test_ablation_flags_default_false(self):
        """Test ablation flags default to False."""
        cfg = SimConfig(map_path="test.map")
        assert cfg.disable_local_replan is False
        assert cfg.disable_conflict_resolution is False
        assert cfg.disable_safety is False

    def test_delay_robustness_params(self):
        """Test execution delay parameters."""
        cfg = SimConfig(
            map_path="test.map",
            execution_delay_prob=0.1,
            execution_delay_steps=3,
        )
        assert cfg.execution_delay_prob == 0.1
        assert cfg.execution_delay_steps == 3

    def test_human_model_params(self):
        """Test human model parameters dict."""
        params = {"beta_go": 3.0, "beta_wait": -2.0}
        cfg = SimConfig(
            map_path="test.map",
            human_model="random_walk",
            human_model_params=params,
        )
        assert cfg.human_model_params["beta_go"] == 3.0
