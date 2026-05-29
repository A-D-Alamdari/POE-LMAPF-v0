"""Resume-prompt-6 task 7: TokenBased vs WaitBased must differ measurably.

The load-bearing check from the design discussion: the re-implemented
``TokenBasedResolver`` (per-(agent, cell) τ scheme) must produce
*measurably different* behavior from ``WaitBasedResolver`` on dense
contention.  If they don't differ, the re-implementation hasn't actually
changed the mechanism.

The fixture is a 5×5 open grid (constructed inline — ``data/maps`` ships
``empty-8-8`` as its smallest map, no ``empty-5-5``) with 4 agents and no
humans, run for 50 ticks.  Four agents on 25 cells forces repeated
contention for the same cells.  The global solver is ``lacam`` (fast,
approximate) so the local-tier resolver — the thing under test — does the
deconfliction work without the optimal-CBS timeout overhead a 5×5/4-agent
instance would otherwise incur.

Threshold is 5%: large enough to ignore noise, small enough to catch a real
mechanism difference.  Do NOT relax it — if a fixture stops exposing the
difference, make the contention denser (more agents / narrower corridor /
longer run) instead.
"""
from __future__ import annotations

import os
import tempfile

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def _tiny_map(td: str, n: int = 5) -> str:
    p = os.path.join(td, f"empty-{n}.map")
    with open(p, "w") as f:
        f.write(f"type octile\nheight {n}\nwidth {n}\nmap\n" + ("." * n + "\n") * n)
    return p


def _run(mode: str, seed: int, mp: str):
    cfg = SimConfig(
        map_path=mp, seed=seed, steps=50,
        num_agents=4, num_humans=0,
        fov_radius=2, safety_radius=1,
        human_model="random_walk", mode="lifelong",
        task_allocator="congestion_avoidance",
        global_solver="lacam", hard_safety=True,
        humans_block_on_agent_cells=True, algorithm_variant="baseline",
        communication_mode=mode,
    )
    sim = Simulator(cfg)
    sim.run()
    return sim.metrics.finalize(total_steps=50, num_agents=4)


def _pct_diff(a: float, b: float) -> float:
    """Relative difference of a vs b, as a percentage of |b| (0 if both 0)."""
    if a == b:
        return 0.0
    return abs(a - b) / max(1e-9, abs(b)) * 100.0


def test_token_and_wait_differ_on_dense_contention():
    with tempfile.TemporaryDirectory() as td:
        mp = _tiny_map(td, n=5)
        seed = 0
        w = _run("wait_based", seed, mp)
        t = _run("token_based", seed, mp)

        d_wait = _pct_diff(t.total_wait_steps, w.total_wait_steps)
        d_flow = _pct_diff(t.mean_flowtime, w.mean_flowtime)
        d_yield = _pct_diff(t.yield_wait_steps, w.yield_wait_steps)

        # At least one aggregate must differ by >5% — a real mechanism
        # difference, not noise.
        assert max(d_wait, d_flow, d_yield) > 5.0, (
            "TokenBased and WaitBased produced near-identical behavior on dense "
            "contention — the re-implementation did not change the mechanism.\n"
            f"  total_wait: W={w.total_wait_steps} T={t.total_wait_steps} (Δ={d_wait:.1f}%)\n"
            f"  mean_flowtime: W={w.mean_flowtime:.3f} T={t.mean_flowtime:.3f} (Δ={d_flow:.1f}%)\n"
            f"  yield_wait: W={w.yield_wait_steps} T={t.yield_wait_steps} (Δ={d_yield:.1f}%)\n"
            "Do NOT relax the threshold; make the contention denser instead."
        )

        # Both resolvers must still satisfy Theorem 1 on this baseline /
        # True-regime fixture (no humans => no agent-attributable violations
        # possible, but assert the obvious invariant anyway).
        assert w.violations_def1_agent_attributable == 0
        assert t.violations_def1_agent_attributable == 0
