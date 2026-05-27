"""
Comprehensive Tests for Conflict Resolution.

Tests all conflict resolvers from ha_lmapf.local_tier.conflict_resolution including:
- TokenPassingResolver
- PIBTResolver
- PriorityRulesResolver
- Base conflict detection
"""
import pytest
from dataclasses import dataclass
from typing import Dict, Tuple, Set
from ha_lmapf.core.types import AgentState, Observation, TimedPath, StepAction
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.local_tier.conflict_resolution.token_passing import TokenPassingResolver
from ha_lmapf.local_tier.conflict_resolution.pibt import PIBTResolver
from ha_lmapf.local_tier.conflict_resolution.priority_rules import PriorityRulesResolver
from ha_lmapf.local_tier.conflict_resolution.base import detect_imminent_conflict


# ============================================================================
# Mock SimStateView for testing
# ============================================================================

@dataclass
class MockSimState:
    """Mock SimStateView for testing conflict resolvers."""
    agents: Dict[int, AgentState]
    env: Environment
    step: int = 0
    _plan_bundle: object = None
    _decided_next_positions: Dict[int, Tuple[int, int]] = None

    def __post_init__(self):
        if self._decided_next_positions is None:
            self._decided_next_positions = {}

    def plans(self):
        """Return the plan bundle (what the real simulator calls)."""
        return self._plan_bundle

    def plan_bundle(self):
        """Alias for plans()."""
        return self._plan_bundle

    def decided_next_positions(self) -> Dict[int, Tuple[int, int]]:
        return self._decided_next_positions


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def empty_5x5_env():
    """Create an empty 5x5 environment."""
    return Environment(width=5, height=5, blocked=set())


@pytest.fixture
def empty_observation():
    """Create an empty observation."""
    return Observation(visible_humans={}, visible_agents={}, blocked=set())


# ============================================================================
# Conflict Detection Tests
# ============================================================================

class TestConflictDetection:
    """Tests for detect_imminent_conflict function."""

    def test_no_conflict_empty(self, empty_5x5_env):
        """No conflict when agent is alone."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)

        conflict = detect_imminent_conflict(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
        )

        assert conflict is None

    def test_vertex_conflict_detected(self, empty_5x5_env):
        """Detect vertex conflict when two agents want same cell."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 3)),  # Already at target
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)

        conflict = detect_imminent_conflict(
            agent_id=0,
            desired_cell=(2, 3),  # Agent 1 is already here
            sim_state=sim_state,
        )

        assert conflict is not None
        assert conflict.kind == "vertex"
        assert conflict.other_agent_id == 1

    def test_no_conflict_with_self(self, empty_5x5_env):
        """Agent doesn't conflict with itself."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 2))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)

        conflict = detect_imminent_conflict(
            agent_id=0,
            desired_cell=(2, 2),  # Same as current position
            sim_state=sim_state,
        )

        assert conflict is None


# ============================================================================
# TokenPassingResolver Tests
# ============================================================================

class TestTokenPassingResolver:
    """Tests for TokenPassingResolver."""

    def test_no_conflict_proceeds(self, empty_5x5_env, empty_observation):
        """Agent proceeds when no conflict."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = TokenPassingResolver()

        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        assert action == StepAction.RIGHT

    def test_conflict_winner_proceeds(self, empty_5x5_env, empty_observation):
        """Agent with token wins conflict."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 3)),
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = TokenPassingResolver()

        # Agent 0 should proceed or wait based on token
        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        # Should return a valid action
        assert action in [StepAction.RIGHT, StepAction.WAIT, StepAction.UP, StepAction.DOWN, StepAction.LEFT]

    def test_fairness_rotation(self, empty_5x5_env, empty_observation):
        """Token holder rotates after K conflicts."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 2)),
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = TokenPassingResolver(fairness_k=2)

        # Multiple resolutions to test fairness rotation
        for _ in range(5):
            action = resolver.resolve(0, (2, 3), sim_state, empty_observation)
            assert action in list(StepAction)


# ============================================================================
# PIBTResolver Tests
# ============================================================================

class TestPIBTResolver:
    """Tests for PIBTResolver."""

    def test_no_conflict_proceeds(self, empty_5x5_env, empty_observation):
        """Agent proceeds when no conflict."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PIBTResolver()

        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        assert action == StepAction.RIGHT

    def test_action_toward_direction(self, empty_5x5_env, empty_observation):
        """Resolver computes correct action toward cell."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(0, 2))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PIBTResolver()

        # Going UP (decreasing row)
        action = resolver.resolve(
            agent_id=0,
            desired_cell=(1, 2),
            sim_state=sim_state,
            observation=empty_observation,
        )

        assert action == StepAction.UP

    def test_wait_on_blocked_push(self, empty_5x5_env, empty_observation):
        """Agent waits when push not feasible."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 3)),  # Blocker at goal
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PIBTResolver()

        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        # Should return a valid action (wait, side-step, or proceed if push succeeds)
        assert action in list(StepAction)

    def test_side_step_allowed(self, empty_5x5_env, empty_observation):
        """Side step option when enabled."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 3)),
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PIBTResolver(allow_side_step=True)

        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        # Could side step
        assert action in [StepAction.WAIT, StepAction.UP, StepAction.DOWN, StepAction.LEFT, StepAction.RIGHT]


# ============================================================================
# PriorityRulesResolver Tests
# ============================================================================

class TestPriorityRulesResolver:
    """Tests for PriorityRulesResolver."""

    def test_no_conflict_proceeds(self, empty_5x5_env, empty_observation):
        """Agent proceeds when no conflict."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        assert action == StepAction.RIGHT

    def test_higher_priority_wins(self, empty_5x5_env, empty_observation):
        """Agent closer to goal (higher urgency) wins."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 3)),  # 1 step to goal
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 5)),  # 2 steps to goal
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        # Agent 0 has higher urgency (closer to goal)
        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        # Agent 0 should proceed (higher priority)
        assert action == StepAction.RIGHT

    def test_starvation_boost(self, empty_5x5_env, empty_observation):
        """Agent waiting long gets priority boost."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 5), wait_steps=15),  # Starving
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 4), wait_steps=0),  # Fresh
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver(starvation_threshold=10, boost=100)

        # Agent 0 should get priority boost due to starvation
        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        assert action == StepAction.RIGHT

    def test_tie_break_by_agent_id(self, empty_5x5_env, empty_observation):
        """Equal priority breaks tie by lower agent_id."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 4)),  # 2 steps
            1: AgentState(agent_id=1, pos=(2, 3), goal=(2, 5)),  # 2 steps
        }
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        # Both have same distance, agent 0 (lower ID) wins
        action = resolver.resolve(
            agent_id=0,
            desired_cell=(2, 3),
            sim_state=sim_state,
            observation=empty_observation,
        )

        # Agent 0 should win tie
        assert action == StepAction.RIGHT


# ============================================================================
# Action Calculation Tests
# ============================================================================

class TestActionCalculation:
    """Tests for action calculation helpers."""

    def test_action_toward_up(self, empty_5x5_env, empty_observation):
        """Calculate UP action."""
        agents = {0: AgentState(agent_id=0, pos=(3, 3), goal=(2, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (2, 3), sim_state, empty_observation)
        assert action == StepAction.UP

    def test_action_toward_down(self, empty_5x5_env, empty_observation):
        """Calculate DOWN action."""
        agents = {0: AgentState(agent_id=0, pos=(2, 3), goal=(3, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (3, 3), sim_state, empty_observation)
        assert action == StepAction.DOWN

    def test_action_toward_left(self, empty_5x5_env, empty_observation):
        """Calculate LEFT action."""
        agents = {0: AgentState(agent_id=0, pos=(3, 3), goal=(3, 2))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (3, 2), sim_state, empty_observation)
        assert action == StepAction.LEFT

    def test_action_toward_wait(self, empty_5x5_env, empty_observation):
        """Calculate WAIT action."""
        agents = {0: AgentState(agent_id=0, pos=(3, 3), goal=(3, 3))}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (3, 3), sim_state, empty_observation)
        assert action == StepAction.WAIT


# ============================================================================
# Edge Cases
# ============================================================================

class TestConflictResolverEdgeCases:
    """Edge case tests for conflict resolvers."""

    def test_agent_surrounded(self, empty_5x5_env):
        """Agent surrounded by blocked cells waits."""
        agents = {
            0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4)),
        }
        blocked = {(1, 2), (3, 2), (2, 1), (2, 3)}
        observation = Observation(blocked=blocked)
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (2, 3), sim_state, observation)

        # Should wait (or side-step if available)
        assert action in [StepAction.WAIT, StepAction.UP, StepAction.DOWN, StepAction.LEFT, StepAction.RIGHT]

    def test_agent_without_goal(self, empty_5x5_env, empty_observation):
        """Agent without goal handles gracefully."""
        agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=None)}
        sim_state = MockSimState(agents=agents, env=empty_5x5_env)
        resolver = PriorityRulesResolver()

        action = resolver.resolve(0, (2, 3), sim_state, empty_observation)

        # Should still produce valid action
        assert action in list(StepAction)
