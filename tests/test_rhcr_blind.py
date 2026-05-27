"""
RHCR exogenous-blind end-to-end test (paper Section 5.5).

Audit summary (full version in ``docs/REVISION_AUDIT.md`` §12):

  * The RHCR Tier-1 wrapper itself is exogenous-blind: it calls
    ``solver.plan(env=..., agents=..., assignments=..., step=...,
    horizon=..., rng=...)`` where ``env`` is the static map.  No
    exogenous-agent positions are propagated to the solver.
  * The default ``AgentController`` is NOT exogenous-blind: it
    computes the inflated buffer F from visible exogenous agents and
    runs local A* repair around them, which contradicts the paper's
    "no Tier-2" RHCR definition.
  * To match the paper, ``make_rhcr_blind_config`` swaps the
    controller for ``GlobalOnlyController`` via
    ``controller_kind="global_only"``.

This test runs RHCR-blind on a corridor with an exogenous-agent
cluster and asserts at least one ``agent_attributable`` violation
fires — i.e. the rigid follower walks into the buffer of a visible
exogenous agent because it cannot detour.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import replace

import pytest

from ha_lmapf.baselines import make_rhcr_blind_config
from ha_lmapf.core.types import HumanState, SimConfig
from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def corridor_map(tmp_path):
    """Single horizontal corridor with shelves above and below.
    Agents must traverse the corridor; exogenous-agent cluster planted
    in the middle creates unavoidable buffer encounters.
    """
    rows = [
        "..............",
        ".@@@@@@@@@@@@.",
        "..............",
        ".@@@@@@@@@@@@.",
        "..............",
    ]
    p = tmp_path / "corridor.map"
    p.write_text("type octile\nheight 5\nwidth 14\nmap\n" + "\n".join(rows) + "\n")
    return str(p)


def _rhcr_runtime_ok() -> bool:
    """``--help`` parse + a tiny end-to-end probe.

    The RHCR binary on this CI image exits with rc=-11 (SIGSEGV) on
    real planning calls despite having a working ``--help`` page —
    likely a build issue tied to the ``-m`` / scenario interaction.
    A planning probe catches that case so the smoke test skips
    cleanly with a reason.
    """
    import tempfile
    from ha_lmapf.core.types import AgentState, Task
    from ha_lmapf.simulation.environment import Environment

    s = RHCRSolver(time_limit_sec=1.0)
    bp = s.binary_path
    if not os.path.isfile(bp):
        return False
    try:
        r = subprocess.run([bp, "--help"], capture_output=True, text=True, timeout=2)
    except Exception:
        return False
    if r.returncode not in (0, 1) or "shared libraries" in (r.stderr or ""):
        return False
    td = tempfile.mkdtemp()
    mp = os.path.join(td, "probe.map")
    open(mp, "w").write("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    env = Environment.load_from_map(mp)
    plan = s.plan(
        env=env,
        agents={0: AgentState(0, (0, 0)), 1: AgentState(1, (0, 4))},
        assignments={
            0: Task("p0", (0, 0), (4, 4), 0),
            1: Task("p1", (0, 4), (4, 0), 0),
        },
        step=0, horizon=10, rng=None,
    )
    return any(len(set(tp.cells)) > 1 for tp in plan.paths.values() if tp)


def test_rhcr_blind_walks_into_buffer(corridor_map):
    if not _rhcr_runtime_ok():
        pytest.skip("RHCR binary unavailable / non-functional on this host")

    base = SimConfig(
        map_path=corridor_map,
        seed=0,
        steps=50,
        num_agents=4,
        num_humans=5,
        fov_radius=4,
        safety_radius=1,
        solver_timeout_s=1.0,
        replan_every=10,
        horizon=20,
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    cfg = make_rhcr_blind_config(base)
    assert cfg.global_solver == "rhcr"
    assert cfg.controller_kind == "global_only"

    sim = Simulator(cfg)

    # Plant the 5 exogenous agents in a tight cluster mid-corridor so
    # agents traversing the corridor cannot avoid them.
    cluster = [(2, 5), (2, 6), (2, 7), (2, 8), (2, 9)]
    sim.humans = {
        hid: HumanState(human_id=hid, pos=cluster[hid], velocity=(0, 0))
        for hid in range(min(len(cluster), len(sim.humans)))
    }
    # Hold them still by replacing the human model with one that
    # always returns the current state.  Easiest: monkey-patch the
    # ``step`` method to a no-op identity transform.
    def _identity_step(env, humans, rng, agent_positions=None):
        return dict(humans)
    sim.human_model.step = _identity_step  # type: ignore[assignment]

    metrics = sim.run()

    assert metrics.steps == 50
    assert metrics.violations_agent_attributable > 0, (
        f"RHCR-blind produced zero agent-attributable violations on "
        f"a scenario with a 5-cell exogenous-agent cluster blocking "
        f"the only corridor.  Either the GlobalOnlyController is "
        f"accidentally avoiding the buffer (audit) or the simulation "
        f"never reached the cluster.  Final metrics: "
        f"completed={metrics.completed_tasks}, "
        f"agent_attr={metrics.violations_agent_attributable}, "
        f"exo_attr={metrics.violations_exogenous_attributable}, "
        f"a-h_collisions={metrics.collisions_agent_human}."
    )


def test_blind_controller_walks_into_buffer_with_working_solver(corridor_map):
    """Companion to :func:`test_rhcr_blind_walks_into_buffer`.

    The RHCR binary segfaults on this CI image, so the test above
    skips by default.  This sibling test verifies the same end-to-end
    property — *rigid global-plan follower walks into r_safe buffer
    cells around visible exogenous agents* — using a solver that
    does work in CI (CBS via the cbs-mapf Python wrapper).  The
    Tier-1 algorithm is incidental; the audit finding is about the
    Tier-2 (controller) layer, which is what this test pins.
    """
    base = SimConfig(
        map_path=corridor_map,
        seed=0,
        steps=50,
        num_agents=4,
        num_humans=5,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",  # any working solver
        solver_timeout_s=1.0,
        replan_every=10,
        horizon=20,
        communication_mode="priority",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
    )
    cfg = replace(base, controller_kind="global_only")

    sim = Simulator(cfg)
    cluster = [(2, 5), (2, 6), (2, 7), (2, 8), (2, 9)]
    sim.humans = {
        hid: HumanState(human_id=hid, pos=cluster[hid], velocity=(0, 0))
        for hid in range(min(len(cluster), len(sim.humans)))
    }
    def _identity_step(env, humans, rng, agent_positions=None):
        return dict(humans)
    sim.human_model.step = _identity_step  # type: ignore[assignment]

    metrics = sim.run()

    assert metrics.steps == 50
    assert metrics.violations_agent_attributable > 0, (
        f"GlobalOnlyController + CBS produced zero agent-attributable "
        f"violations.  Either the rigid-follower controller is "
        f"accidentally avoiding F (audit failure) or no agents reached "
        f"the corridor cluster.  Final metrics: "
        f"completed={metrics.completed_tasks}, "
        f"agent_attr={metrics.violations_agent_attributable}, "
        f"exo_attr={metrics.violations_exogenous_attributable}."
    )
