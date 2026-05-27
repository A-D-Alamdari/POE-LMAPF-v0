"""
Comprehensive Tests for Metrics Tracking System.

Tests the MetricsTracker class from ha_lmapf.core.metrics including:
- Task lifecycle tracking
- Event counting (collisions, replans, etc.)
- Timing metrics
- Finalization and aggregation
- CSV output
"""
import pytest
import numpy as np
from ha_lmapf.core.metrics import MetricsTracker


# ============================================================================
# Task Lifecycle Tests
# ============================================================================

class TestTaskLifecycle:
    """Tests for task lifecycle tracking."""

    def test_on_task_released(self):
        """Track task release events."""
        tracker = MetricsTracker()
        tracker.on_task_released("task_001", release_step=10)

        assert "task_001" in tracker._tasks
        assert tracker._tasks["task_001"].release_step == 10

    def test_on_task_assigned(self):
        """Track task assignment events."""
        tracker = MetricsTracker()
        tracker.on_task_released("task_001", release_step=10)
        tracker.on_task_assigned("task_001", agent_id=5, step=15)

        assert tracker._tasks["task_001"].assigned_step == 15

    def test_on_task_completed(self):
        """Track task completion events."""
        tracker = MetricsTracker()
        tracker.on_task_released("task_001", release_step=10)
        tracker.on_task_assigned("task_001", agent_id=5, step=15)
        tracker.on_task_completed("task_001", agent_id=5, step=25)

        assert tracker._tasks["task_001"].completed_step == 25
        assert tracker._completed_tasks == 1

    def test_task_completed_without_release(self):
        """Task completed without prior release creates record."""
        tracker = MetricsTracker()
        tracker.on_task_completed("task_001", agent_id=0, step=50)

        assert "task_001" in tracker._tasks
        assert tracker._completed_tasks == 1

    def test_multiple_tasks(self):
        """Track multiple independent tasks."""
        tracker = MetricsTracker()

        tracker.on_task_released("t1", 0)
        tracker.on_task_released("t2", 5)
        tracker.on_task_released("t3", 10)

        tracker.on_task_completed("t1", 0, 20)
        tracker.on_task_completed("t2", 1, 25)

        assert tracker._completed_tasks == 2
        assert tracker._tasks["t3"].completed_step is None

    def test_double_completion_ignored(self):
        """Second completion of same task is ignored."""
        tracker = MetricsTracker()
        tracker.on_task_released("task_001", 0)
        tracker.on_task_completed("task_001", 0, 10)
        tracker.on_task_completed("task_001", 1, 20)  # Second completion

        assert tracker._completed_tasks == 1
        assert tracker._tasks["task_001"].completed_step == 10


# ============================================================================
# Event Counter Tests
# ============================================================================

class TestEventCounters:
    """Tests for event counting methods."""

    def test_add_agent_agent_collision(self):
        """Track agent-agent collisions."""
        tracker = MetricsTracker()
        tracker.add_agent_agent_collision()
        tracker.add_agent_agent_collision(3)

        assert tracker._coll_rr == 4

    def test_add_agent_human_collision(self):
        """Track agent-human collisions."""
        tracker = MetricsTracker()
        tracker.add_agent_human_collision()
        tracker.add_agent_human_collision(2)

        assert tracker._coll_rh == 3

    def test_add_near_miss(self):
        """Track near miss events."""
        tracker = MetricsTracker()
        tracker.add_near_miss(5)

        assert tracker._near_misses == 5

    def test_add_replan(self):
        """Track replan events."""
        tracker = MetricsTracker()
        tracker.add_replan(10)

        assert tracker._replans == 10

    def test_add_global_replan(self):
        """Track global replan events."""
        tracker = MetricsTracker()
        tracker.add_global_replan(3)

        assert tracker._global_replans == 3

    def test_add_local_replan(self):
        """Track local replan events."""
        tracker = MetricsTracker()
        tracker.add_local_replan(7)

        assert tracker._local_replans == 7

    def test_add_wait_steps(self):
        """Track wait steps."""
        tracker = MetricsTracker()
        tracker.add_wait_steps(100)

        assert tracker._total_wait_steps == 100

    def test_add_safety_violation(self):
        """Track safety violations."""
        tracker = MetricsTracker()
        tracker.add_safety_violation(15)

        assert tracker._safety_violations == 15

    def test_add_human_passive_wait(self):
        """Track human passive waiting."""
        tracker = MetricsTracker()
        tracker.add_human_passive_wait(20)

        assert tracker._human_passive_wait_steps == 20

    def test_add_delay_event(self):
        """Track delay events."""
        tracker = MetricsTracker()
        tracker.add_delay_event(5)

        assert tracker._delay_events == 5


# ============================================================================
# Timing Tests
# ============================================================================

class TestTiming:
    """Tests for timing metric recording."""

    def test_record_planning_time(self):
        """Record planning time measurements."""
        tracker = MetricsTracker()
        tracker.record_planning_time_ms(100.5)
        tracker.record_planning_time_ms(150.3)
        tracker.record_planning_time_ms(80.0)

        assert len(tracker._planning_times_ms) == 3
        assert tracker._planning_times_ms[0] == 100.5

    def test_record_decision_time(self):
        """Record decision time measurements."""
        tracker = MetricsTracker()
        tracker.record_decision_time_ms(5.5)
        tracker.record_decision_time_ms(8.2)

        assert len(tracker._decision_times_ms) == 2


# ============================================================================
# Cost-Based Metrics Tests
# ============================================================================

class TestCostMetrics:
    """Tests for cost-based metrics."""

    def test_add_path_cost(self):
        """Track sum of costs."""
        tracker = MetricsTracker()
        tracker.add_path_cost(10)
        tracker.add_path_cost(15)
        tracker.add_path_cost(20)

        assert tracker._sum_of_costs == 45

    def test_update_makespan(self):
        """Track makespan (max completion step)."""
        tracker = MetricsTracker()
        tracker.update_makespan(50)
        tracker.update_makespan(30)  # Lower, ignored
        tracker.update_makespan(75)

        assert tracker._makespan == 75


# ============================================================================
# Finalization Tests
# ============================================================================

class TestFinalization:
    """Tests for metrics finalization."""

    def test_finalize_basic(self):
        """Finalize produces valid Metrics object."""
        tracker = MetricsTracker()
        tracker.on_task_released("t1", 0)
        tracker.on_task_completed("t1", 0, 10)
        tracker.add_agent_agent_collision(2)

        metrics = tracker.finalize(total_steps=100)

        assert metrics.completed_tasks == 1
        assert metrics.collisions_agent_agent == 2
        assert metrics.steps == 100

    def test_throughput_calculation(self):
        """Throughput = completed_tasks / steps."""
        tracker = MetricsTracker()
        for i in range(10):
            tracker.on_task_released(f"t{i}", i)
            tracker.on_task_completed(f"t{i}", 0, i + 10)

        metrics = tracker.finalize(total_steps=100)

        assert metrics.throughput == 10 / 100  # 0.1

    def test_flowtime_calculation(self):
        """Mean flowtime = avg(completed_step - release_step)."""
        tracker = MetricsTracker()
        # Task 1: release=0, complete=10, flowtime=10
        tracker.on_task_released("t1", 0)
        tracker.on_task_completed("t1", 0, 10)
        # Task 2: release=5, complete=25, flowtime=20
        tracker.on_task_released("t2", 5)
        tracker.on_task_completed("t2", 1, 25)

        metrics = tracker.finalize(total_steps=50)

        assert metrics.mean_flowtime == 15.0  # (10 + 20) / 2

    def test_safety_violation_rate(self):
        """Safety violation rate = violations / steps * 1000."""
        tracker = MetricsTracker()
        tracker.add_safety_violation(50)

        metrics = tracker.finalize(total_steps=1000)

        assert metrics.safety_violation_rate == 50.0

    def test_intervention_rate(self):
        """Intervention rate = global_replans / steps * 1000."""
        tracker = MetricsTracker()
        tracker.add_global_replan(10)

        metrics = tracker.finalize(total_steps=500)

        assert metrics.intervention_rate == 20.0

    def test_timing_statistics(self):
        """Timing statistics computed correctly."""
        tracker = MetricsTracker()
        for ms in [100, 200, 300, 400, 500]:
            tracker.record_planning_time_ms(ms)

        metrics = tracker.finalize(total_steps=100)

        assert metrics.mean_planning_time_ms == 300.0
        assert metrics.max_planning_time_ms == 500.0
        assert metrics.p95_planning_time_ms > 0

    def test_finalize_empty_tracker(self):
        """Finalize empty tracker doesn't crash."""
        tracker = MetricsTracker()
        metrics = tracker.finalize(total_steps=100)

        assert metrics.completed_tasks == 0
        assert metrics.throughput == 0.0
        assert metrics.mean_flowtime == 0.0

    def test_finalize_zero_steps(self):
        """Finalize with zero steps handles division by zero."""
        tracker = MetricsTracker()
        metrics = tracker.finalize(total_steps=0)

        assert metrics.throughput == 0.0
        assert metrics.safety_violation_rate == 0.0


# ============================================================================
# CSV Output Tests
# ============================================================================

class TestCSVOutput:
    """Tests for CSV output functionality."""

    def test_csv_header(self):
        """CSV header contains expected columns."""
        header = MetricsTracker.csv_header()

        assert "throughput" in header
        assert "completed_tasks" in header
        assert "collisions_agent_agent" in header
        assert "collisions_agent_human" in header
        assert "safety_violations" in header
        assert "mean_planning_time_ms" in header
        assert "makespan" in header

    def test_csv_row(self):
        """CSV row matches header length."""
        tracker = MetricsTracker()
        tracker.on_task_completed("t1", 0, 10)
        metrics = tracker.finalize(total_steps=100)

        header = MetricsTracker.csv_header()
        row = tracker.to_csv_row(metrics)

        assert len(row) == len(header)

    def test_csv_row_format(self):
        """CSV row values are properly formatted strings."""
        tracker = MetricsTracker()
        tracker.on_task_released("t1", 0)
        tracker.on_task_completed("t1", 0, 10)
        tracker.add_agent_agent_collision(5)
        metrics = tracker.finalize(total_steps=100)

        row = tracker.to_csv_row(metrics)

        # All values should be strings
        for val in row:
            assert isinstance(val, str)


# ============================================================================
# Integration Tests
# ============================================================================

class TestMetricsIntegration:
    """Integration tests for MetricsTracker."""

    def test_full_simulation_scenario(self):
        """Simulate a complete simulation run."""
        tracker = MetricsTracker()

        # Release tasks
        for i in range(20):
            tracker.on_task_released(f"task_{i}", release_step=i * 5)

        # Complete some tasks
        for i in range(15):
            tracker.on_task_assigned(f"task_{i}", agent_id=i % 5, step=i * 5 + 2)
            tracker.on_task_completed(f"task_{i}", agent_id=i % 5, step=i * 5 + 20)
            tracker.add_path_cost(15)

        # Add events
        tracker.add_agent_agent_collision(3)
        tracker.add_agent_human_collision(1)
        tracker.add_safety_violation(10)
        tracker.add_global_replan(5)
        tracker.add_local_replan(20)
        tracker.add_wait_steps(150)

        # Record timing
        for _ in range(10):
            tracker.record_planning_time_ms(np.random.uniform(50, 200))
            tracker.record_decision_time_ms(np.random.uniform(1, 10))

        tracker.update_makespan(120)

        # Finalize
        metrics = tracker.finalize(total_steps=200)

        # Verify
        assert metrics.completed_tasks == 15
        assert metrics.collisions_agent_agent == 3
        assert metrics.collisions_agent_human == 1
        assert metrics.safety_violations == 10
        assert metrics.global_replans == 5
        assert metrics.local_replans == 20
        assert metrics.total_wait_steps == 150
        assert metrics.sum_of_costs == 225  # 15 * 15
        assert metrics.makespan == 120
        assert metrics.throughput == 15 / 200
