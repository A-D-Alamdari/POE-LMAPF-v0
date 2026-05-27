"""
PIBT2-FR baseline smoke test (paper Section 5.5).

PIBT2-FR = PIBT2 with R=1 + GlobalOnlyController (no Tier-2 detour).
We expect:
  * Run completes for all 100 steps without crashing.
  * Throughput is positive (the rigid follower moves agents toward
    goals between exogenous-agent encounters).
  * ``violations_agent_attributable > 0`` because the controller has
    no buffer-aware detour and freely walks into r_safe-buffer cells
    around visible exogenous agents.

We do NOT assert absolute violation counts — that's the experiment's
job; the smoke test only verifies the baseline wires together.
"""
from __future__ import annotations

import pytest

from ha_lmapf.baselines import make_pibt2_fr_config
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def small_warehouse_map(tmp_path):
    # A miniature warehouse-style aisle/shelf layout — the full
    # 161x63 paper map is overkill for a smoke test.
    rows = [
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
        ".@@.@@.@@.@@..",
        ".@@.@@.@@.@@..",
        "..............",
    ]
    p = tmp_path / "mini_warehouse.map"
    p.write_text("type octile\nheight 10\nwidth 14\nmap\n" + "\n".join(rows) + "\n")
    return str(p)


def _check_pibt2_runtime() -> bool:
    """Is the shipped PIBT2 binary actually usable on this host?

    The PIBT2 binary's ``--help`` exits 0 even when it has been
    compiled with a hardcoded map directory that prevents real
    planning, so we additionally do a tiny end-to-end probe: a
    one-agent, one-cell-step instance.  If the wrapper returns only
    WAIT paths, the binary is broken.
    """
    import os
    import tempfile
    from ha_lmapf.core.types import AgentState, Task
    from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
    from ha_lmapf.simulation.environment import Environment

    s = PIBT2Solver(time_limit_sec=0.5)
    if not os.path.isfile(s.binary_path):
        return False
    td = tempfile.mkdtemp()
    mp = os.path.join(td, "probe.map")
    open(mp, "w").write("type octile\nheight 4\nwidth 4\nmap\n" + "....\n" * 4)
    env = Environment.load_from_map(mp)
    plan = s.plan(
        env=env,
        agents={0: AgentState(0, (0, 0))},
        assignments={0: Task("p0", (0, 0), (3, 3), 0)},
        step=0, horizon=10, rng=None,
    )
    if not plan or not plan.paths:
        return False
    return any(len(set(tp.cells)) > 1 for tp in plan.paths.values() if tp)


def test_pibt2_fr_smoke(small_warehouse_map):
    if not _check_pibt2_runtime():
        pytest.skip(
            "PIBT2 binary not functional on this host; smoke test would "
            "exercise only the WAIT-fallback path which is not the "
            "paper's PIBT2-FR baseline."
        )

    base = SimConfig(
        map_path=small_warehouse_map,
        seed=0,
        steps=100,
        num_agents=20,
        num_humans=10,
        fov_radius=4,
        safety_radius=1,
        # PIBT2 sub-second budget keeps the smoke test fast.
        solver_timeout_s=1.0,
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    cfg = make_pibt2_fr_config(base)

    # Sanity: the factory produced the documented overrides.
    assert cfg.global_solver == "pibt2"
    assert cfg.replan_every == 1
    assert cfg.horizon == 20
    assert cfg.controller_kind == "global_only"

    sim = Simulator(cfg)
    metrics = sim.run()

    # Run completed.
    assert metrics.steps == 100
    # The metric fields populate (no crashes / NaNs along the way).
    assert isinstance(metrics.throughput, float)
    assert metrics.throughput > 0.0, (
        "PIBT2-FR throughput=0 — solver may be returning all-WAIT.  "
        "Check PIBT2 binary integration."
    )
    # GlobalOnlyController + non-zero r_safe must produce some
    # agent-attributable violations on a corridor-style map.
    assert metrics.violations_agent_attributable > 0, (
        "PIBT2-FR produced zero agent-attributable violations.  Either "
        "the rigid-follower controller is accidentally avoiding F, or "
        "the test scenario didn't generate any encounters."
    )
