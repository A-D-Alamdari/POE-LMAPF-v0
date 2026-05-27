"""
Paper §5.8 per-tick violation timeline — regression tests.

The simulator's ``_detect_collisions_and_near_misses`` block tracks
two per-tick counters (``tick_agent_attr``, ``tick_exo_attr``) and,
when ``SimConfig.log_violations_timeline`` is True, appends them once
per tick to ``Metrics.violations_agent_timeline`` and
``Metrics.violations_exogenous_timeline``.  Both lists stay
index-aligned (length == steps) by appending zeros on no-violation
ticks.

The harness (``scripts.evaluation.run_paper_experiment.run_one``)
strips per-tick lists from the CSV row and persists non-empty
timelines to a sidecar JSON at
``<row["_sidecar_dir"]>/<run_id>.json``.

Tests T-VT-1..4 cover, in order:
  1. Knob OFF (default) → timeline lists are empty after a short run.
  2. Knob ON → timeline lists have length == steps; zeros on
     no-violation ticks; defensive copy from the tracker.
  3. Per-tick increments sum to the final scalar counters
     (``violations_agent_attributable`` ==
      sum(violations_agent_timeline), same for exogenous).
  4. Sidecar JSON: harness writes ``<run_id>.json`` to the sidecar
     dir when timelines are non-empty; the CSV row carries
     ``*_timeline_len`` columns instead of the raw lists.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


@pytest.fixture
def small_map(tmp_path):
    """5x5 open map."""
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _cfg(map_path: str, *, steps: int, num_agents: int = 1,
         num_humans: int = 0, log_timeline: bool = False) -> SimConfig:
    return SimConfig(
        map_path=map_path,
        seed=0,
        steps=steps,
        num_agents=num_agents,
        num_humans=num_humans,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=100,
        horizon=20,
        hard_safety=True,
        mode="lifelong",
        human_model="random_walk",
        task_allocator="greedy",
        log_violations_timeline=log_timeline,
    )


# ---------------------------------------------------------------------------
# T-VT-1 — Knob OFF: timelines stay empty
# ---------------------------------------------------------------------------


def test_T_VT_1_knob_off_timelines_empty(small_map):
    """Default knob (False) means the simulator does not call
    ``append_violations_timeline``; the lists remain empty after the
    run.  Verifies the opt-in contract."""
    cfg = _cfg(small_map, steps=20, num_agents=2, num_humans=0,
               log_timeline=False)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert metrics.violations_agent_timeline == []
    assert metrics.violations_exogenous_timeline == []


# ---------------------------------------------------------------------------
# T-VT-2 — Knob ON: timelines length == steps, defensive copy
# ---------------------------------------------------------------------------


def test_T_VT_2_knob_on_timeline_length(small_map):
    """With the knob on, both timelines have exactly ``steps`` entries
    after a clean run; with no humans every entry is 0; the returned
    lists are NOT aliased to the tracker's internal buffers."""
    cfg = _cfg(small_map, steps=15, num_agents=2, num_humans=0,
               log_timeline=True)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert len(metrics.violations_agent_timeline) == 15
    assert len(metrics.violations_exogenous_timeline) == 15
    assert all(v == 0 for v in metrics.violations_agent_timeline)
    assert all(v == 0 for v in metrics.violations_exogenous_timeline)
    # Defensive copy: mutating the returned Metrics does not mutate the
    # tracker's internal buffers.
    metrics.violations_agent_timeline.append(999)
    assert len(sim.metrics._violations_agent_timeline) == 15


# ---------------------------------------------------------------------------
# T-VT-3 — Sum of per-tick counts equals the final scalar counts
# ---------------------------------------------------------------------------


def test_T_VT_3_timeline_sum_matches_scalars(small_map):
    """The invariant that ties the §5.8 timeline to the §5.5/§5.4
    scalar counters: each timeline's sum must equal the final
    Metrics.violations_*_attributable scalar.  Exercised with a small
    population of exogenous agents so the detection block actually
    runs."""
    cfg = _cfg(small_map, steps=30, num_agents=2, num_humans=3,
               log_timeline=True)
    sim = Simulator(cfg)
    metrics = sim.run()
    assert sum(metrics.violations_agent_timeline) == \
        metrics.violations_agent_attributable
    assert sum(metrics.violations_exogenous_timeline) == \
        metrics.violations_exogenous_attributable


# ---------------------------------------------------------------------------
# T-VT-4 — Harness sidecar JSON writeout
# ---------------------------------------------------------------------------


def test_T_VT_4_harness_writes_sidecar(small_map):
    """End-to-end harness path: when ``row["_sidecar_dir"]`` is set
    and the timelines are non-empty, ``run_one`` writes a sidecar
    JSON at ``<sidecar_dir>/<run_id>.json`` and strips the lists
    from the returned CSV row."""
    from scripts.evaluation.run_paper_experiment import run_one, compute_run_id

    with tempfile.TemporaryDirectory() as td:
        sidecar_dir = Path(td) / "timelines"
        cfg_dict = {
            "map_path": small_map,
            "seed": 0,
            "steps": 8,
            "num_agents": 1,
            "num_humans": 2,
            "fov_radius": 4,
            "safety_radius": 1,
            "global_solver": "cbs",
            "replan_every": 100,
            "horizon": 20,
            "hard_safety": True,
            "mode": "lifelong",
            "human_model": "random_walk",
            "task_allocator": "greedy",
            "log_violations_timeline": True,
        }
        run_id = compute_run_id(cfg_dict, 0)
        row = {
            "run_id": run_id,
            "experiment": "test_vt_4",
            "seed": 0,
            "config": cfg_dict,
            "_sidecar_dir": str(sidecar_dir),
        }
        rec = run_one(row)
        assert rec["status"] == "ok", rec
        # CSV row has *_len columns, no raw lists.
        assert "violations_agent_timeline_len" in rec
        assert rec["violations_agent_timeline_len"] == 8
        assert "violations_agent_timeline" not in rec
        assert "violations_exogenous_timeline" not in rec
        # Sidecar JSON exists with the expected keys.
        sidecar = sidecar_dir / f"{run_id}.json"
        assert sidecar.exists()
        data = json.loads(sidecar.read_text())
        assert "violations_agent_timeline" in data
        assert "violations_exogenous_timeline" in data
        assert len(data["violations_agent_timeline"]) == 8
        assert len(data["violations_exogenous_timeline"]) == 8
