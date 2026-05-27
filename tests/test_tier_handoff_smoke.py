"""
Tier-1 -> Tier-2 guidance handoff smoke test.

Validates two things end-to-end:

1. The ``debug_guidance_trace`` instrumentation is plumbed correctly:
   guidance_coverage / guidance_follow_rate are populated on the
   returned ``Metrics``, and the boundary cases (all-WAIT global tier
   under the rigid-follower controller) have the expected trivial
   values.

2. The acceptance criterion in ``docs/tier_handoff_diagnosis.md``:
   under ``controller_kind="global_only"`` (the paper's rigid-follower
   baseline), the global solver choice produces measurably different
   throughput with an explainable ordering ``all_wait < pibt2 <=
   lacam3``.  Under the default controller throughput is invariant
   for the reasons documented in the doc; the test asserts that
   invariance too, so that any future change that breaks the
   invariant in either direction is surfaced.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ha_lmapf.core.types import SimConfig  # noqa: E402
from ha_lmapf.simulation.simulator import Simulator  # noqa: E402


def _solver_binary_available(name: str) -> bool:
    """Skip when a wrapper's binary isn't shipped in this checkout."""
    if name == "all_wait":
        return True  # pure-Python debug planner
    mapping = {
        "pibt2":  "mapf_pibt2",
        "lacam3": "lacam3",
    }
    solvers_dir = REPO_ROOT / "src/ha_lmapf/global_tier/solvers"
    return (solvers_dir / mapping[name]).is_file()


def _run(solver: str, controller_kind: str) -> Dict[str, float]:
    cfg = SimConfig(
        map_path=str(REPO_ROOT / "data/maps/random-64-64-10.map"),
        seed=0,
        steps=500,
        num_agents=25,
        num_humans=20,
        fov_radius=4,
        safety_radius=1,
        horizon=20,
        replan_every=10,
        global_solver=solver,
        solver_timeout_s=10.0,
        hard_safety=True,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        mode="lifelong",
        task_allocator="congestion_avoidance",
        debug_guidance_trace=True,
        controller_kind=controller_kind,  # type: ignore[arg-type]
    )
    sim = Simulator(cfg)
    m = sim.run()
    return {
        "throughput":       float(m.throughput),
        "completed_tasks":  int(m.completed_tasks),
        "guidance_coverage":   float(m.guidance_coverage),
        "guidance_follow_rate": float(m.guidance_follow_rate),
        "guidance_eligible_ticks": int(m.guidance_eligible_ticks),
        "guidance_covered_ticks":  int(m.guidance_covered_ticks),
        "guidance_followed_ticks": int(m.guidance_followed_ticks),
        "global_replans":   int(m.global_replans),
        "local_replans":    int(m.local_replans),
        "safe_wait_steps":  int(m.safe_wait_steps),
    }


def test_guidance_instrumentation_off_by_default():
    """When ``debug_guidance_trace`` is False (the default) the
    counters stay at zero -- the hot path is gated cleanly so default
    sweeps pay no instrumentation cost."""
    cfg = SimConfig(
        map_path=str(REPO_ROOT / "data/maps/random-64-64-10.map"),
        seed=0,
        steps=100,
        num_agents=10,
        num_humans=5,
        fov_radius=4,
        safety_radius=1,
        horizon=20,
        replan_every=10,
        global_solver="pibt2",
        solver_timeout_s=10.0,
        hard_safety=True,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        mode="lifelong",
        task_allocator="congestion_avoidance",
        # debug_guidance_trace defaults to False
    )
    sim = Simulator(cfg)
    m = sim.run()
    assert m.guidance_eligible_ticks == 0
    assert m.guidance_covered_ticks == 0
    assert m.guidance_followed_ticks == 0
    assert m.guidance_coverage == 0.0
    assert m.guidance_follow_rate == 0.0


def test_all_wait_global_only_yields_no_movement():
    """The trivial boundary: all-WAIT bundle + rigid follower => no
    agent moves, every agent ``follows the bundle`` by waiting, and
    throughput is zero.  Sanity-check the instrumentation."""
    row = _run("all_wait", controller_kind="global_only")
    assert row["throughput"] == 0.0, row
    assert row["completed_tasks"] == 0, row
    # Every (eligible, covered, followed) is True -- agents have a
    # WAIT prescription, the bundle covers them, and they obey by
    # staying in place.
    assert row["guidance_coverage"] == pytest.approx(1.0, abs=1e-6), row
    assert row["guidance_follow_rate"] == pytest.approx(1.0, abs=1e-6), row


@pytest.mark.parametrize("solver", ["pibt2", "lacam3"])
def test_real_solver_default_controller_follow_rate_high(solver: str):
    """The Tier-1 -> Tier-2 plumbing is intact: real solver bundles
    reach the controller, are indexed correctly, and are followed on
    >85% of covered ticks.  This is the test that rules out the
    "bundle isn't reaching agent_controller" failure mode."""
    if not _solver_binary_available(solver):
        pytest.skip(f"{solver} binary unavailable in this checkout")
    row = _run(solver, controller_kind="default")
    assert row["guidance_coverage"] > 0.9, row
    assert row["guidance_follow_rate"] > 0.85, row


def test_global_only_throughput_orders_solvers():
    """Acceptance criterion: with the rigid-follower controller in
    place (no Tier-2 local A* substitution), the global solver choice
    produces measurably different throughput in the expected order:

        all_wait << pibt2  (real coordination)
        all_wait << lacam3 (real coordination)

    The ordering between pibt2 and lacam3 is left flexible -- both
    are real solvers and the noise on a single 500-step seed can
    flip them within a few percent.  What matters for the criterion
    is that the global plan demonstrably matters, which only ``vs
    all_wait`` proves.
    """
    if not (_solver_binary_available("pibt2") and _solver_binary_available("lacam3")):
        pytest.skip("real-solver binaries not present in this checkout")

    pibt2    = _run("pibt2",    controller_kind="global_only")
    lacam3   = _run("lacam3",   controller_kind="global_only")
    all_wait = _run("all_wait", controller_kind="global_only")

    # Trivial check first.
    assert all_wait["throughput"] == 0.0, all_wait

    # Real solvers must do real work.  At 25 agents on
    # random-64-64-10 over 500 steps a healthy run completes ~90+
    # tasks; require well above zero and above the all-WAIT baseline.
    assert pibt2["throughput"] > 0.05, pibt2
    assert lacam3["throughput"] > 0.05, lacam3
    assert pibt2["throughput"] > all_wait["throughput"], (pibt2, all_wait)
    assert lacam3["throughput"] > all_wait["throughput"], (lacam3, all_wait)

    # Follow rate under global_only is essentially the proportion of
    # ticks the rigid controller's prescription cleared the
    # conflict-prevention revert.  Both real solvers should exceed
    # 0.5 -- otherwise the rigid follower isn't actually executing
    # the plan.
    assert pibt2["guidance_follow_rate"] > 0.5, pibt2
    assert lacam3["guidance_follow_rate"] > 0.5, lacam3


def test_default_controller_makes_throughput_solver_invariant():
    """Documents the invariance: under the default Tier-2 controller
    on this map / load, throughput is solver-invariant within a few
    percent (the local-A* substitution effect + auto-tuned task
    supply, see ``docs/tier_handoff_diagnosis.md``).  Any future
    change that breaks this invariant -- in EITHER direction -- is
    a change worth noticing, so the test gates it."""
    if not (_solver_binary_available("pibt2") and _solver_binary_available("lacam3")):
        pytest.skip("real-solver binaries not present in this checkout")

    pibt2    = _run("pibt2",    controller_kind="default")
    lacam3   = _run("lacam3",   controller_kind="default")
    all_wait = _run("all_wait", controller_kind="default")

    # Allow up to 10% spread across the three solvers.
    thpts = [pibt2["throughput"], lacam3["throughput"], all_wait["throughput"]]
    spread = (max(thpts) - min(thpts)) / max(thpts)
    assert spread < 0.10, (
        f"default-controller throughput is no longer solver-invariant; "
        f"spread={spread:.3f}, {pibt2=}, {lacam3=}, {all_wait=}.  "
        f"If this is intentional, re-read docs/tier_handoff_diagnosis.md "
        f"and update the rubric."
    )

    # The diagnostic signal that proves Tier-2 is substituting for
    # the global plan: all_wait runs MORE local replans than the
    # real solvers (because every replan needs Tier-2 to compute
    # something from scratch).
    assert all_wait["local_replans"] > pibt2["local_replans"], (
        pibt2, all_wait,
    )
    assert all_wait["local_replans"] > lacam3["local_replans"], (
        lacam3, all_wait,
    )
