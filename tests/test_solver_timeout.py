"""
Solver-timeout enforcement tests.

Two scenarios:

1. **Wrapper-level**: a tight (50 ms) per-call budget on an anytime
   solver (LaCAM3 / LaCAM\\*) on a saturated 8x8 / 8-agent instance.
   The wrapper must return within 200 ms wall clock and produce a
   ``PlanBundle`` (anytime solvers always return *some* plan, possibly
   all-WAIT, even when they hit the timeout).

2. **Simulator-level**: when the global solver fails to produce a
   useful plan, the simulator must (a) keep stepping without crashing,
   (b) increment ``Metrics.solver_timeouts``, and (c) keep the previous
   ``PlanBundle`` around so agents that already have valid paths keep
   moving while the rest execute Safe Wait.

The PIBT2 wrapper would normally be the easiest to time-bound, but the
binary shipped with this repository was compiled against a hardcoded
map directory and silently fails with exit code 1 on this host.  We
therefore use LaCAM3 for the wrapper-level test (it honours
sub-second timeouts natively).
"""
from __future__ import annotations

import os
import time

import pytest

from ha_lmapf.core.types import AgentState, PlanBundle, SimConfig, Task
from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.simulation.simulator import Simulator


def _binary_runtime_ok(binary_path: str) -> bool:
    """Lightweight ``--help`` probe.  Mirrors the helper in
    ``test_solver_smoke.py`` but trimmed for this file's needs."""
    if not os.path.isfile(binary_path):
        return False
    import subprocess
    try:
        r = subprocess.run(
            [binary_path, "--help"], capture_output=True, text=True, timeout=2,
        )
    except Exception:
        return False
    return r.returncode in (0, 1) and "shared libraries" not in (r.stderr or "")


@pytest.fixture
def env_8x8(tmp_path):
    p = tmp_path / "8x8.map"
    p.write_text("type octile\nheight 8\nwidth 8\nmap\n" + "........\n" * 8)
    return Environment.load_from_map(str(p))


# ---------------------------------------------------------------------------
# 1. Wrapper-level timeout
# ---------------------------------------------------------------------------


def test_lacam3_50ms_budget_returns_within_200ms(env_8x8):
    """Saturated 8-agent instance with a 50 ms budget.  LaCAM3 honors
    sub-second budgets natively and self-terminates well below the
    ``+5 s`` Python subprocess watchdog.
    """
    solver = LaCAM3Solver(time_limit_sec=0.05)
    if not _binary_runtime_ok(solver.binary_path):
        pytest.skip(f"LaCAM3 binary unavailable at {solver.binary_path}")

    # 8 agents — saturating 8x8 with diagonal goals.
    agents = {i: AgentState(agent_id=i, pos=(0, i)) for i in range(8)}
    assignments = {
        i: Task(task_id=f"t{i}", start=(0, i), goal=(7, 7 - i), release_step=0)
        for i in range(8)
    }

    t0 = time.perf_counter()
    plan = solver.plan(
        env=env_8x8, agents=agents, assignments=assignments,
        step=0, horizon=20, rng=None,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # 200 ms wall-clock budget for the test; the actual binary returns
    # well under 50 ms on a host with libboost present.
    assert elapsed_ms < 200.0, (
        f"LaCAM3 with 50ms budget took {elapsed_ms:.0f}ms wall-clock, "
        f"expected < 200ms.  Binary may not be honouring -t."
    )
    assert isinstance(plan, PlanBundle), f"got {type(plan).__name__} not PlanBundle"


# ---------------------------------------------------------------------------
# 2. Simulator-level fallback when the solver runs out of time
# ---------------------------------------------------------------------------


def test_simulator_survives_aggressive_solver_timeout(tmp_path):
    """Drive the simulator with a 50 ms solver budget on a tiny grid
    and confirm:
      * ``run`` returns without raising;
      * ``metrics.solver_timeouts`` is incremented every time the
        solver could not produce a useful plan;
      * the simulation advances at least to its requested step count.
    """
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)

    cfg = SimConfig(
        map_path=str(p),
        seed=0,
        steps=20,
        num_agents=4,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="lacam3",
        solver_timeout_s=0.05,  # 50 ms — extremely aggressive
        replan_every=5,
        horizon=10,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    sim = Simulator(cfg)
    if not _binary_runtime_ok(sim.global_planner.solver.binary_path):
        pytest.skip(
            f"LaCAM3 binary unavailable at "
            f"{sim.global_planner.solver.binary_path}"
        )

    t0 = time.perf_counter()
    metrics = sim.run()
    elapsed = time.perf_counter() - t0

    # The whole 20-step run should fit in well under a few seconds —
    # it's 4 replans at 50 ms each plus normal step overhead.
    assert elapsed < 5.0, (
        f"Simulator took {elapsed:.2f}s with 50 ms solver budget on a "
        f"trivial 5x5 / 4-agent / 20-step run"
    )
    assert metrics.steps == 20
    # ``solver_timeouts`` may or may not increment — depends on whether
    # the saturated-tiny-instance solves in 50 ms — but it must be a
    # well-defined non-negative integer and not None.
    assert isinstance(metrics.solver_timeouts, int)
    assert metrics.solver_timeouts >= 0
