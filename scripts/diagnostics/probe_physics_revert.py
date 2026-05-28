"""Empirical probe: does ``Simulator.run`` ever produce nonzero
``physics_revert_wait_steps`` in a normal episode?

Step 6 (delay injection) overrides a previously-chosen MOVE with a
forced WAIT *after* the decentralised conflict resolver has run.
That makes step 6 the only known source of conflicts the resolver
could not anticipate at decision time:

  - Agent A decided MOVE A->B (resolver saw B as free).
  - Agent B decided MOVE B->C (B's cell will be free).
  - Step 6 fires a delay on agent B, overriding its decision to WAIT.
  - Now agent A still wants B but B is staying at B.
  - Step 7a fires, reverting A to WAIT and incrementing
    ``physics_revert_wait_steps``.

This script runs short episodes across several seeds with
``execution_delay_prob = 0.3`` and reports the observed values.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


def _open_map(tmpdir: Path, w: int, h: int) -> str:
    p = tmpdir / f"{w}x{h}.map"
    p.write_text(f"type octile\nheight {h}\nwidth {w}\nmap\n" + ("." * w + "\n") * h)
    return str(p)


def probe(seed: int, map_path: str, delay_prob: float = 0.3,
          n_agents: int = 6, n_humans: int = 0, steps: int = 60) -> dict:
    cfg = SimConfig(
        map_path=map_path,
        num_agents=n_agents,
        num_humans=n_humans,
        steps=steps,
        fov_radius=2,
        safety_radius=1,
        seed=seed,
        execution_delay_prob=delay_prob,
        execution_delay_steps=1,
    )
    sim = Simulator(cfg)
    m = sim.run()
    return {
        "seed": seed,
        "total_wait": m.total_wait_steps,
        "safe": m.safe_wait_steps,
        "yield": m.yield_wait_steps,
        "physics_revert": m.physics_revert_wait_steps,
        "delay": m.delay_wait_steps,
        "delay_events": getattr(m, "delay_events", 0),
        "invariant_ok": (
            m.total_wait_steps
            == m.safe_wait_steps + m.yield_wait_steps
            + m.physics_revert_wait_steps + m.delay_wait_steps
        ),
    }


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        m = _open_map(td, 5, 5)
        seen_nonzero = False
        rows = []
        for seed in range(0, 12):
            try:
                r = probe(seed=seed, map_path=m, delay_prob=0.3,
                          n_agents=4, steps=50)
            except Exception as e:
                print(f"seed {seed}: ERROR {type(e).__name__}: {e}")
                continue
            rows.append(r)
            if r["physics_revert"] > 0:
                seen_nonzero = True
            print(
                f"seed={r['seed']:2d}  total_wait={r['total_wait']:4d}  "
                f"safe={r['safe']:4d}  yield={r['yield']:4d}  "
                f"physics_revert={r['physics_revert']:4d}  "
                f"delay={r['delay']:4d}  delay_events={r['delay_events']:4d}  "
                f"inv_ok={r['invariant_ok']}"
            )
        print()
        print(f"any physics_revert > 0 ? {seen_nonzero}")
        return 0 if seen_nonzero else 1


if __name__ == "__main__":
    raise SystemExit(main())
