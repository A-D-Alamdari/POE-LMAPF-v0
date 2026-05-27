"""
Initialization invariant regression tests (Theorem 1 base case).

The simulator must not place any exogenous agent within
``r_safe`` of any controlled agent at t=0; otherwise the empirical
``violations_agent_attributable`` counter could be nonzero from the
very first tick due to placement geometry alone, invalidating
Theorem 1's base case.

These tests pin three facets of the invariant:

* **Test A** — happy-path: across 30 random seeds on a paper-sized
  warehouse, the post-init invariant holds and ``Metrics`` start clean.
* **Test B** — degenerate: a 5×5 empty map with |M| = |X| = 10 and
  r_safe = 2 cannot satisfy the invariant; constructor must raise
  :class:`InitializationError` rather than silently relax.
* **Test C** — end-to-end regression: a 50-step run with the
  Theorem-1 stress-test geometry produces
  ``metrics.violations_agent_attributable == 0`` for the entire run
  including step 0.  Future refactors that silently drop the
  invariant will trip this test.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import InitializationError, Simulator


REPO_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_MAP = REPO_ROOT / "data" / "maps" / "warehouse-10-20-10-2-1.map"


# ---------------------------------------------------------------------------
# Test A — happy path across 30 seeds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", list(range(30)))
def test_post_init_invariant_holds_on_warehouse(seed: int):
    cfg = SimConfig(
        map_path=str(WAREHOUSE_MAP),
        seed=seed,
        steps=10,
        num_agents=5,
        num_humans=5,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        solver_timeout_s=1.0,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    sim = Simulator(cfg)

    # Hand-rolled invariant check (independent of the assert we just
    # ran inside ``__init__``).
    r_safe = cfg.safety_radius
    for x in sim.humans.values():
        for a in sim.agents.values():
            d = abs(x.pos[0] - a.pos[0]) + abs(x.pos[1] - a.pos[1])
            assert d > r_safe, (
                f"seed={seed}: exo at {x.pos} within r_safe={r_safe} of "
                f"controlled at {a.pos} (d={d})"
            )

    # No two controlled agents share a vertex.
    positions = [a.pos for a in sim.agents.values()]
    assert len(set(positions)) == len(positions), (
        f"seed={seed}: vertex-colliding controlled agents at t=0"
    )

    # Pre-step metrics: ``finalize`` returns a fresh Metrics with
    # everything zeroed.  We assert the violation counters specifically.
    metrics = sim.metrics.finalize(total_steps=0, num_agents=len(sim.agents))
    assert metrics.violations_agent_attributable == 0
    assert metrics.violations_exogenous_attributable == 0
    assert metrics.safety_violations == 0


# ---------------------------------------------------------------------------
# Test B — degenerate scenario must raise InitializationError
# ---------------------------------------------------------------------------


def test_degenerate_density_raises_initialization_error(tmp_path: Path):
    """5×5 empty grid, |M| = |X| = 10, r_safe = 2.

    With r_safe = 2 the buffer around a single controlled agent
    occupies up to 13 cells (free-truncated Manhattan ball).  Ten
    controlled agents on 25 free cells leave too few cells outside
    the union F_init for any exogenous agent to spawn — the
    constructor must raise :class:`InitializationError`.
    """
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    cfg = SimConfig(
        map_path=str(p),
        seed=0,
        steps=1,
        num_agents=10,
        num_humans=10,
        fov_radius=4,
        safety_radius=2,                # F_init dominates the grid
        global_solver="cbs",
        solver_timeout_s=1.0,
        human_model="random_walk",
        mode="lifelong",
    )
    with pytest.raises(InitializationError) as excinfo:
        Simulator(cfg)

    msg = str(excinfo.value)
    # Error message must mention the knobs the user can turn.
    assert "r_safe" in msg
    assert "|X|" in msg or "exogenous" in msg


# ---------------------------------------------------------------------------
# Test C — end-to-end Theorem-1 regression including step 0
# ---------------------------------------------------------------------------


CORRIDOR_MAP_LINES = [
    "................",
    "..@@..@@..@@..@@",
    "..@@..@@..@@..@@",
    "................",
    "..@@..@@..@@..@@",
    "..@@..@@..@@..@@",
    "................",
    "..@@..@@..@@..@@",
    "..@@..@@..@@..@@",
    "................",
    "..@@..@@..@@..@@",
    "..@@..@@..@@..@@",
    "................",
    "..@@..@@..@@..@@",
    "..@@..@@..@@..@@",
    "................",
]


@pytest.fixture
def corridor_map(tmp_path: Path) -> str:
    p = tmp_path / "corridor16.map"
    body = "\n".join(CORRIDOR_MAP_LINES) + "\n"
    p.write_text(f"type octile\nheight 16\nwidth 16\nmap\n{body}")
    return str(p)


def test_no_agent_attributable_violation_through_step_50(corridor_map: str):
    cfg = SimConfig(
        map_path=corridor_map,
        seed=0,
        steps=50,
        num_agents=8,
        num_humans=6,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        solver_timeout_s=0.5,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    sim = Simulator(cfg)
    metrics = sim.run()
    assert metrics.violations_agent_attributable == 0, (
        f"Theorem 1 base-case regression: {metrics.violations_agent_attributable} "
        f"agent-attributable violations across 50 steps with proper init "
        f"(exo_attr={metrics.violations_exogenous_attributable})."
    )
