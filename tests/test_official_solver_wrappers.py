"""
Tests for official MAPF solver wrappers.

These tests verify the wrapper classes for official C++ solvers:
- LaCAM3Solver (from https://github.com/Kei18/lacam3)
- LaCAMOfficialSolver (from https://github.com/Kei18/lacam)
- PIBT2Solver (from https://github.com/Kei18/pibt2)

Tests are skipped if the binaries are not installed.
"""
import importlib
import os
import sys

import pytest
from unittest.mock import Mock, patch

from ha_lmapf.core.types import AgentState, Task, PlanBundle, TimedPath
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def simple_env():
    """Create a simple 5x5 environment for testing."""
    env = Mock()
    env.width = 5
    env.height = 5
    env.is_blocked = lambda cell: False
    env.is_free = lambda cell: True
    return env


@pytest.fixture
def two_agents():
    """Create two agents with goals."""
    return {
        0: AgentState(agent_id=0, pos=(0, 0), goal=(4, 4)),
        1: AgentState(agent_id=1, pos=(0, 4), goal=(4, 0)),
    }


@pytest.fixture
def two_assignments(two_agents):
    """Create task assignments for two agents."""
    return {
        0: Task(task_id="t0", start=(0, 0), goal=(4, 4), release_step=0),
        1: Task(task_id="t1", start=(0, 4), goal=(4, 0), release_step=0),
    }


# ============================================================================
# GlobalPlannerFactory Tests
# ============================================================================

class TestGlobalPlannerFactory:
    """Tests for GlobalPlannerFactory.create() with all solver types."""

    def test_create_cbs(self):
        """Test creating CBS planner."""
        solver = GlobalPlannerFactory.create("cbs")
        assert solver is not None
        assert "CBS" in type(solver).__name__

    def test_create_lacam_python(self):
        """Test creating Python LaCAM planner."""
        solver = GlobalPlannerFactory.create("lacam")
        assert solver is not None
        assert "LaCAM" in type(solver).__name__

    def test_create_lacam3(self):
        """Test creating LaCAM3 wrapper (may not have binary)."""
        solver = GlobalPlannerFactory.create("lacam3")
        assert solver is not None
        assert "LaCAM3" in type(solver).__name__

    def test_create_lacam_official(self):
        """Test creating LaCAM official wrapper (may not have binary)."""
        solver = GlobalPlannerFactory.create("lacam_official")
        assert solver is not None
        assert "LaCAMOfficial" in type(solver).__name__

    def test_create_pibt2(self):
        """Test creating PIBT2 wrapper (may not have binary)."""
        solver = GlobalPlannerFactory.create("pibt2")
        assert solver is not None
        assert "PIBT2" in type(solver).__name__

    def test_create_with_aliases(self):
        """Test that aliases work correctly."""
        # CBS aliases
        assert GlobalPlannerFactory.create("conflict_based_search") is not None

        # LaCAM Python aliases
        assert GlobalPlannerFactory.create("lacam_like") is not None
        assert GlobalPlannerFactory.create("prioritized") is not None

        # LaCAM3 aliases
        assert GlobalPlannerFactory.create("lacam3_cpp") is not None

        # LaCAM Official aliases
        assert GlobalPlannerFactory.create("lacam_cpp") is not None

        # PIBT2 aliases
        assert GlobalPlannerFactory.create("pibt2_cpp") is not None
        assert GlobalPlannerFactory.create("pibt") is not None

    def test_unknown_solver_raises(self):
        """Test that unknown solver names raise ValueError."""
        with pytest.raises(ValueError):
            GlobalPlannerFactory.create("unknown_solver")


# ============================================================================
# LaCAM3Solver Tests
# ============================================================================

class TestLaCAM3Solver:
    """Tests for LaCAM3Solver wrapper."""

    def test_import(self):
        """Test that LaCAM3Solver can be imported."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
        assert LaCAM3Solver is not None

    def test_instantiation(self):
        """Test that LaCAM3Solver can be instantiated."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
        solver = LaCAM3Solver()
        assert solver is not None

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver

        # Post-Prompt 16, the binary-not-found path is owned by
        # ``BaseSolverWrapper._wrap_subprocess``; we exercise it by
        # pointing the wrapper at an explicit nonexistent path so the
        # check fires regardless of what's installed on the host.
        solver = LaCAM3Solver(binary_path="/nonexistent/path/lacam3")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        # Should return a PlanBundle with WAIT paths
        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2
        for aid, path in result.paths.items():
            assert isinstance(path, TimedPath)
            # WAIT path = all cells are the same (agent's start position)
            assert len(set(path.cells)) == 1

    @pytest.mark.skipif(
        not os.path.exists("src/ha_lmapf/global_tier/solvers/lacam3.exe") and
        not os.path.exists("src/ha_lmapf/global_tier/solvers/lacam3"),
        reason="LaCAM3 binary not installed"
    )
    def test_plan_with_binary(self, simple_env, two_agents, two_assignments):
        """Test planning with actual LaCAM3 binary (skip if not installed)."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
        solver = LaCAM3Solver(binary_path=None)
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=20)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) >= 2


# ============================================================================
# LaCAMOfficialSolver Tests
# ============================================================================

class TestLaCAMOfficialSolver:
    """Tests for LaCAMOfficialSolver wrapper."""

    def test_import(self):
        """Test that LaCAMOfficialSolver can be imported."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
        assert LaCAMOfficialSolver is not None

    def test_instantiation(self):
        """Test that LaCAMOfficialSolver can be instantiated."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
        solver = LaCAMOfficialSolver()
        assert solver is not None

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver

        solver = LaCAMOfficialSolver(binary_path="/nonexistent/path/lacam")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2

    @pytest.mark.skipif(
        not os.path.exists("src/ha_lmapf/global_tier/solvers/lacam.exe") and
        not os.path.exists("src/ha_lmapf/global_tier/solvers/lacam"),
        reason="LaCAM official binary not installed"
    )
    def test_plan_with_binary(self, simple_env, two_agents, two_assignments):
        """Test planning with actual LaCAM binary (skip if not installed)."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
        solver = LaCAMOfficialSolver()
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=20)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) >= 2


# ============================================================================
# PIBT2Solver Tests
# ============================================================================

class TestPIBT2Solver:
    """Tests for PIBT2Solver wrapper."""

    def test_import(self):
        """Test that PIBT2Solver can be imported."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        assert PIBT2Solver is not None

    def test_instantiation(self):
        """Test that PIBT2Solver can be instantiated."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        solver = PIBT2Solver()
        assert solver is not None

    def test_solver_variants(self):
        """Test that different solver variants can be specified."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        solver_pibt = PIBT2Solver(solver_name="PIBT")
        assert solver_pibt.solver_name == "PIBT"

        solver_hca = PIBT2Solver(solver_name="HCA")
        assert solver_hca.solver_name == "HCA"

        solver_whca = PIBT2Solver(solver_name="WHCA")
        assert solver_whca.solver_name == "WHCA"

    def test_mode_options(self):
        """Test that different mode options can be specified."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        solver_auto = PIBT2Solver(mode="auto")
        assert solver_auto.mode == "auto"

        solver_oneshot = PIBT2Solver(mode="one_shot")
        assert solver_oneshot.mode == "one_shot"

        solver_mapf = PIBT2Solver(mode="mapf")
        assert solver_mapf.mode == "mapf"

        solver_lifelong = PIBT2Solver(mode="lifelong")
        assert solver_lifelong.mode == "lifelong"

        solver_mapd = PIBT2Solver(mode="mapd")
        assert solver_mapd.mode == "mapd"

    def test_dual_binary_paths(self):
        """Test that separate binary paths can be specified for mapf and mapd."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        solver = PIBT2Solver(
            mapf_binary_path="/path/to/mapf_pibt2",
            mapd_binary_path="/path/to/mapd_pibt2"
        )
        assert solver.mapf_binary == "/path/to/mapf_pibt2"
        assert solver.mapd_binary == "/path/to/mapd_pibt2"

    def test_binary_selection_auto_mode(self):
        """Auto mode always returns mapf_pibt2 — see
        ``docs/PIBT2_DIAGNOSIS.md``.  RollingHorizonPlanner owns the
        lifelong loop; each replan is a one-shot MAPF problem.
        ``mapd_pibt2`` would generate its own synthetic tasks and
        emit MAPD-format output the wrapper's parser cannot read."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        solver = PIBT2Solver(
            mapf_binary_path="/path/to/mapf",
            mapd_binary_path="/path/to/mapd",
            mode="auto"
        )
        # Auto mode unconditionally returns mapf, regardless of is_lifelong.
        assert solver._select_binary(is_lifelong=False) == "/path/to/mapf"
        assert solver._select_binary(is_lifelong=True) == "/path/to/mapf"

    def test_binary_selection_forced_mode(self):
        """Test binary selection in forced modes."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        # Force mapf mode - should always use mapf binary
        solver_mapf = PIBT2Solver(
            mapf_binary_path="/path/to/mapf",
            mapd_binary_path="/path/to/mapd",
            mode="one_shot"
        )
        assert solver_mapf._select_binary(is_lifelong=True) == "/path/to/mapf"
        assert solver_mapf._select_binary(is_lifelong=False) == "/path/to/mapf"

        # Force mapd mode - should always use mapd binary
        solver_mapd = PIBT2Solver(
            mapf_binary_path="/path/to/mapf",
            mapd_binary_path="/path/to/mapd",
            mode="lifelong"
        )
        assert solver_mapd._select_binary(is_lifelong=True) == "/path/to/mapd"
        assert solver_mapd._select_binary(is_lifelong=False) == "/path/to/mapd"

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        solver = PIBT2Solver(
            mapf_binary_path="/nonexistent/path/mapf_pibt2",
            mapd_binary_path="/nonexistent/path/mapd_pibt2"
        )
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2

    @pytest.mark.skipif(
        not os.path.isfile("src/ha_lmapf/global_tier/solvers/mapf_pibt2"),
        reason="PIBT2 mapf binary not installed"
    )
    def test_plan_with_mapf_binary(self, simple_env, two_agents, two_assignments):
        """Test planning with PIBT2 mapf binary (for one-shot mode)."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        solver = PIBT2Solver(mode="one_shot")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=20)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) >= 2

    @pytest.mark.skipif(
        not os.path.isfile("src/ha_lmapf/global_tier/solvers/mapd_pibt2"),
        reason="PIBT2 mapd binary not installed"
    )
    def test_plan_with_mapd_binary(self, simple_env, two_agents, two_assignments):
        """Test planning with PIBT2 mapd binary (for lifelong mode)."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        solver = PIBT2Solver(mode="lifelong")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=20)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) >= 2


# ============================================================================
# Integration Tests
# ============================================================================

class TestSolverIntegration:
    """Integration tests for solver wrappers."""

    def test_all_wrappers_have_same_interface(self):
        """Test that all wrappers implement the same interface."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        for SolverClass in [LaCAM3Solver, LaCAMOfficialSolver, PIBT2Solver]:
            solver = SolverClass()
            # Check that plan method exists and has correct signature
            assert hasattr(solver, 'plan')
            assert callable(solver.plan)

    def test_exports_from_init(self):
        """Test that all solver classes are exported from __init__.py."""
        from ha_lmapf.global_tier.solvers import (
            LaCAM3Solver,
            LaCAMOfficialSolver,
            PIBT2Solver,
            CBSH2Solver,
        )
        assert LaCAM3Solver is not None
        assert LaCAMOfficialSolver is not None
        assert PIBT2Solver is not None
        assert CBSH2Solver is not None


# ============================================================================
# Cross-Platform Tests
# ============================================================================

class TestCrossPlatformSupport:
    """Tests for cross-platform binary detection."""

    def test_platform_detection_constants(self):
        """Test that platform detection constants are defined."""
        from ha_lmapf.global_tier.solvers import lacam3_wrapper
        from ha_lmapf.global_tier.solvers import lacam_official_wrapper
        from ha_lmapf.global_tier.solvers import pibt2_wrapper

        # All wrappers should have IS_WINDOWS constant
        assert hasattr(lacam3_wrapper, 'IS_WINDOWS')
        assert hasattr(lacam_official_wrapper, 'IS_WINDOWS')
        assert hasattr(pibt2_wrapper, 'IS_WINDOWS')

        # All should have BINARY_EXT constant
        assert hasattr(lacam3_wrapper, 'BINARY_EXT')
        assert hasattr(lacam_official_wrapper, 'BINARY_EXT')
        assert hasattr(pibt2_wrapper, 'BINARY_EXT')

    def test_lacam3_platform_specific_defaults(self):
        """Test LaCAM3 has platform-specific default binary names."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver

        assert hasattr(LaCAM3Solver, 'DEFAULT_BINARY_LINUX')
        assert hasattr(LaCAM3Solver, 'DEFAULT_BINARY_WINDOWS')
        assert LaCAM3Solver.DEFAULT_BINARY_LINUX == "lacam3"
        assert LaCAM3Solver.DEFAULT_BINARY_WINDOWS == "lacam3.exe"

    def test_lacam_official_platform_specific_defaults(self):
        """Test LaCAM Official has platform-specific default binary names."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver

        assert hasattr(LaCAMOfficialSolver, 'DEFAULT_BINARY_LINUX')
        assert hasattr(LaCAMOfficialSolver, 'DEFAULT_BINARY_WINDOWS')
        assert LaCAMOfficialSolver.DEFAULT_BINARY_LINUX == "lacam_official"
        assert LaCAMOfficialSolver.DEFAULT_BINARY_WINDOWS == "lacam_official.exe"

    def test_pibt2_platform_specific_defaults(self):
        """Test PIBT2 has platform-specific default binary names."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver

        assert hasattr(PIBT2Solver, 'DEFAULT_MAPF_BINARY_LINUX')
        assert hasattr(PIBT2Solver, 'DEFAULT_MAPF_BINARY_WINDOWS')
        assert hasattr(PIBT2Solver, 'DEFAULT_MAPD_BINARY_LINUX')
        assert hasattr(PIBT2Solver, 'DEFAULT_MAPD_BINARY_WINDOWS')

        assert PIBT2Solver.DEFAULT_MAPF_BINARY_LINUX == "mapf_pibt2"
        assert PIBT2Solver.DEFAULT_MAPF_BINARY_WINDOWS == "mapf_pibt2.exe"
        assert PIBT2Solver.DEFAULT_MAPD_BINARY_LINUX == "mapd_pibt2"
        assert PIBT2Solver.DEFAULT_MAPD_BINARY_WINDOWS == "mapd_pibt2.exe"

    def test_lacam3_default_binary_property(self):
        """Test LaCAM3 _default_binary property returns correct value."""
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver, IS_WINDOWS

        solver = LaCAM3Solver()
        expected = "lacam3.exe" if IS_WINDOWS else "lacam3"
        assert solver._default_binary == expected

    def test_lacam_official_default_binary_property(self):
        """Test LaCAM Official _default_binary property returns correct value."""
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver, IS_WINDOWS

        solver = LaCAMOfficialSolver()
        expected = "lacam_official.exe" if IS_WINDOWS else "lacam_official"
        assert solver._default_binary == expected

    def test_pibt2_default_binary_properties(self):
        """Test PIBT2 default binary properties return correct values."""
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver, IS_WINDOWS

        solver = PIBT2Solver()

        expected_mapf = "mapf_pibt2.exe" if IS_WINDOWS else "mapf_pibt2"
        expected_mapd = "mapd_pibt2.exe" if IS_WINDOWS else "mapd_pibt2"

        assert solver._default_mapf_binary == expected_mapf
        assert solver._default_mapd_binary == expected_mapd

    @patch('platform.system')
    def test_windows_binary_extension(self, mock_system):
        """Test that Windows detection works correctly."""
        # This tests the module-level constant, which is set at import time
        # We can't easily test this without reimporting, so we just verify
        # the logic is correct
        import platform
        current_platform = platform.system()

        # Import (or re-import) to get the current value
        if 'ha_lmapf.global_tier.solvers.lacam3_wrapper' in sys.modules:
            import ha_lmapf.global_tier.solvers.lacam3_wrapper as wrapper_module
            importlib.reload(wrapper_module)
        else:
            import ha_lmapf.global_tier.solvers.lacam3_wrapper as wrapper_module

        from ha_lmapf.global_tier.solvers.lacam3_wrapper import BINARY_EXT

        if current_platform == "Windows":
            assert BINARY_EXT == ".exe"
        else:
            assert BINARY_EXT == ""


# ============================================================================
# Jiaoyang-Li Solver Wrapper Tests (RHCR, CBSH2, EECBS, PBS, LNS2)
# ============================================================================

class TestRHCRSolver:
    """Tests for RHCRSolver wrapper."""

    def test_import(self):
        """Test that RHCRSolver can be imported."""
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
        assert RHCRSolver is not None

    def test_instantiation(self):
        """Test that RHCRSolver can be instantiated."""
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
        solver = RHCRSolver()
        assert solver is not None

    def test_parameters(self):
        """Test that solver parameters can be configured."""
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver

        solver = RHCRSolver(
            simulation_window=5,
            planning_window=10,
            solver="PBS"
        )
        assert solver.simulation_window == 5
        assert solver.planning_window == 10
        assert solver.solver == "PBS"

    def test_factory_creation(self):
        """Test creating RHCR solver via factory."""
        solver = GlobalPlannerFactory.create("rhcr")
        assert solver is not None
        assert "RHCR" in type(solver).__name__

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver

        solver = RHCRSolver(binary_path="/nonexistent/path/rhcr")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2


class TestCBSH2Solver:
    """Tests for CBSH2Solver wrapper."""

    def test_import(self):
        """Test that CBSH2Solver can be imported."""
        from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
        assert CBSH2Solver is not None

    def test_instantiation(self):
        """Test that CBSH2Solver can be instantiated."""
        from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
        solver = CBSH2Solver()
        assert solver is not None

    def test_factory_creation(self):
        """Test creating CBSH2 solver via factory."""
        solver = GlobalPlannerFactory.create("cbsh2")
        assert solver is not None
        assert "CBSH2" in type(solver).__name__

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver

        solver = CBSH2Solver(binary_path="/nonexistent/path/cbsh2")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2


class TestEECBSSolver:
    """Tests for EECBSSolver wrapper."""

    def test_import(self):
        """Test that EECBSSolver can be imported."""
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver
        assert EECBSSolver is not None

    def test_instantiation(self):
        """Test that EECBSSolver can be instantiated."""
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver
        solver = EECBSSolver()
        assert solver is not None

    def test_suboptimality_parameter(self):
        """Test that suboptimality parameter can be configured."""
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver

        solver = EECBSSolver(suboptimality=1.5)
        assert solver.suboptimality == 1.5

        # Test that suboptimality < 1.0 is clamped to 1.0
        solver2 = EECBSSolver(suboptimality=0.5)
        assert solver2.suboptimality == 1.0

    def test_factory_creation(self):
        """Test creating EECBS solver via factory."""
        solver = GlobalPlannerFactory.create("eecbs")
        assert solver is not None
        assert "EECBS" in type(solver).__name__

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver

        solver = EECBSSolver(binary_path="/nonexistent/path/eecbs")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2


class TestPBSSolver:
    """Tests for PBSSolver wrapper."""

    def test_import(self):
        """Test that PBSSolver can be imported."""
        from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver
        assert PBSSolver is not None

    def test_instantiation(self):
        """Test that PBSSolver can be instantiated."""
        from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver
        solver = PBSSolver()
        assert solver is not None

    def test_factory_creation(self):
        """Test creating PBS solver via factory."""
        solver = GlobalPlannerFactory.create("pbs")
        assert solver is not None
        assert "PBS" in type(solver).__name__

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver

        solver = PBSSolver(binary_path="/nonexistent/path/pbs")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2


class TestLNS2Solver:
    """Tests for LNS2Solver wrapper."""

    def test_import(self):
        """Test that LNS2Solver can be imported."""
        from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver
        assert LNS2Solver is not None

    def test_instantiation(self):
        """Test that LNS2Solver can be instantiated."""
        from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver
        solver = LNS2Solver()
        assert solver is not None

    def test_factory_creation(self):
        """Test creating LNS2 solver via factory."""
        solver = GlobalPlannerFactory.create("lns2")
        assert solver is not None
        assert "LNS2" in type(solver).__name__

    def test_factory_aliases(self):
        """Test factory aliases for LNS2."""
        solver1 = GlobalPlannerFactory.create("mapf_lns2")
        assert "LNS2" in type(solver1).__name__

        solver2 = GlobalPlannerFactory.create("lns")
        assert "LNS2" in type(solver2).__name__

    def test_plan_without_binary_returns_wait_paths(self, simple_env, two_agents, two_assignments):
        """Test that planning without binary returns fallback WAIT paths."""
        from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver

        solver = LNS2Solver(binary_path="/nonexistent/path/lns2")
        result = solver.plan(simple_env, two_agents, two_assignments, step=0, horizon=10)

        assert isinstance(result, PlanBundle)
        assert len(result.paths) == 2


class TestNewSolverExports:
    """Test that all new solvers are properly exported."""

    def test_exports_from_init(self):
        """Test that all new solver classes are exported from __init__.py."""
        from ha_lmapf.global_tier.solvers import (
            RHCRSolver,
            CBSH2Solver,
            EECBSSolver,
            PBSSolver,
            LNS2Solver,
        )
        assert RHCRSolver is not None
        assert CBSH2Solver is not None
        assert EECBSSolver is not None
        assert PBSSolver is not None
        assert LNS2Solver is not None

    def test_all_new_wrappers_have_same_interface(self):
        """Test that all new wrappers implement the same interface."""
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
        from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver
        from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver
        from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver

        for SolverClass in [RHCRSolver, CBSH2Solver, EECBSSolver, PBSSolver, LNS2Solver]:
            solver = SolverClass()
            assert hasattr(solver, 'plan')
            assert callable(solver.plan)

    def test_all_new_solvers_have_platform_detection(self):
        """Test that all new solvers have cross-platform support."""
        from ha_lmapf.global_tier.solvers import rhcr_wrapper
        from ha_lmapf.global_tier.solvers import cbsh2_wrapper
        from ha_lmapf.global_tier.solvers import eecbs_wrapper
        from ha_lmapf.global_tier.solvers import pbs_wrapper
        from ha_lmapf.global_tier.solvers import lns2_wrapper

        for wrapper in [rhcr_wrapper, cbsh2_wrapper, eecbs_wrapper, pbs_wrapper, lns2_wrapper]:
            assert hasattr(wrapper, 'IS_WINDOWS')
            assert hasattr(wrapper, 'BINARY_EXT')
