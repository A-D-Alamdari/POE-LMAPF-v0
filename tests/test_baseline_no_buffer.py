"""
No-Buffer baseline smoke test (paper Section 5.3 / 5.5).

The No-Buffer ablation runs the *full* POE-LMAPF architecture with
``safety_radius = 0``.  At r_safe=0 the inflated buffer F collapses to
the exogenous agents' exact cells (``inflate_cells({pos}, 0, env) ==
{pos}``).  The hard-safety controller still rejects the exogenous
agents' exact cells, and the formal Theorem 1 attribution rule
``ell_1(s_i(t+1), h.pos) <= 0`` simplifies to "cells coincide" — a
case the controller already prevents.

We therefore assert ``violations_agent_attributable == 0`` even with
the buffer disabled.  This is the paper's central observation that
the architecture's correctness comes from the controller's
F-respecting fallback path, not from the buffer width.

If this assertion fails, that is a notable finding and the test
output preserves the metric values for diagnosis.
"""
from __future__ import annotations

import pytest

from ha_lmapf.baselines import make_no_buffer_config
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def small_warehouse_map(tmp_path):
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


def test_no_buffer_smoke(small_warehouse_map):
    base = SimConfig(
        map_path=small_warehouse_map,
        seed=0,
        steps=100,
        num_agents=20,
        num_humans=10,
        fov_radius=4,
        safety_radius=1,                 # overridden to 0 by the factory
        global_solver="cbs",             # pure-Python fallback works on CI
        solver_timeout_s=1.0,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    cfg = make_no_buffer_config(base)
    assert cfg.safety_radius == 0
    # All other defaults preserved
    assert cfg.global_solver == "cbs"
    assert cfg.controller_kind == "default"

    sim = Simulator(cfg)
    metrics = sim.run()

    assert metrics.steps == 100
    assert isinstance(metrics.violations_agent_attributable, int)

    # Theorem 1 still holds at r_safe=0: the controller's hard-safety
    # branch and the resolver's F-respecting fallback both bottom out
    # in "agent never moves into a cell within r_safe of an observed
    # exogenous agent", which at r_safe=0 means "agent never moves
    # onto the same cell as a visible exogenous agent" — exactly what
    # the controller already enforces.
    assert metrics.violations_agent_attributable == 0, (
        f"No-Buffer: agent_attributable={metrics.violations_agent_attributable} "
        f"(expected 0 even with r_safe=0).  exogenous_attributable="
        f"{metrics.violations_exogenous_attributable}, "
        f"safety_violations={metrics.safety_violations}.  This is a "
        f"finding worth investigating: either the controller's "
        f"r_safe=0 path is mis-counting agent-moves into exogenous "
        f"cells, or the metric definition has a corner case at "
        f"r_safe=0."
    )
