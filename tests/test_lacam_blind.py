"""Regression tests for the §5.5 LaCAM-blind baseline.

LaCAM-blind replaces RHCR-blind in the paper's §5.5 rigid-follower
matrix.  See ``docs/RHCR_DEFERRED.md`` for the architectural reason
RHCR's KIVA scenario cannot be invoked as a per-replan MAPF solver
and why LaCAM-blind is the substitute that isolates Tier-2
buffer-awareness as the experimental variable.

These tests pin:

  T-LB-1  ``make_lacam_blind_config`` returns a SimConfig with
          ``global_solver="lacam_official"`` and
          ``controller_kind="global_only"``; every other field is
          inherited from base.

  T-LB-2  Simulator end-to-end smoke with the lacam_blind config on
          a tiny 5x5 map completes without error and reports a
          well-formed Metrics object.

  T-LB-3  The harness ``_apply_method`` dispatch routes
          ``method="lacam_blind"`` through the factory and exposes
          the post-dispatch fields via the ``applied_*`` CSV columns.

  T-LB-4  The harness ``_apply_method`` dispatch on
          ``method="rhcr"`` raises NotImplementedError pointing at
          docs/RHCR_DEFERRED.md.  Stale YAMLs fail loudly at config-
          build time instead of silently producing garbage runs.
"""
from __future__ import annotations

import tempfile
from dataclasses import fields
from pathlib import Path

import pytest

from ha_lmapf.baselines import make_lacam_blind_config
from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator
from scripts.evaluation.run_paper_experiment import (
    _apply_method, _build_sim_config, compute_run_id, run_one,
)


@pytest.fixture
def small_map(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _base_cfg(map_path: str) -> SimConfig:
    return SimConfig(
        map_path=map_path, seed=0, steps=5,
        num_agents=1, num_humans=0,
        fov_radius=4, safety_radius=1,
        global_solver="cbs",  # base may differ; factory enforces lacam
        horizon=20, replan_every=10,
        solver_timeout_s=2.0, hard_safety=True, mode="lifelong",
        task_allocator="greedy",
    )


# ---------------------------------------------------------------------------
# T-LB-1 — Factory shape
# ---------------------------------------------------------------------------


def test_T_LB_1_factory_overrides(small_map):
    """``make_lacam_blind_config`` MUST override only
    ``global_solver`` and ``controller_kind``.  All other fields are
    inherited unchanged so the baseline is identical to ``ours``
    except for Tier-1 enforcement and Tier-2 disablement."""
    base = _base_cfg(small_map)
    cfg = make_lacam_blind_config(base)
    assert cfg.global_solver == "lacam_official", (
        f"expected global_solver=lacam_official, got {cfg.global_solver!r}"
    )
    assert cfg.controller_kind == "global_only", (
        f"expected controller_kind=global_only, got {cfg.controller_kind!r}"
    )
    # Every other field must equal the base.  Field-by-field check so
    # an accidental extra override is caught immediately.
    for f in fields(SimConfig):
        if f.name in {"global_solver", "controller_kind"}:
            continue
        assert getattr(cfg, f.name) == getattr(base, f.name), (
            f"field {f.name} was modified: base={getattr(base, f.name)!r} "
            f"vs cfg={getattr(cfg, f.name)!r}"
        )


# ---------------------------------------------------------------------------
# T-LB-2 — Simulator smoke
# ---------------------------------------------------------------------------


def test_T_LB_2_simulator_smoke(small_map):
    """A 5-tick simulation with the lacam_blind config completes
    without raising and produces a Metrics object with the expected
    invariants (steps == 5, completed_tasks >= 0)."""
    base = _base_cfg(small_map)
    cfg = make_lacam_blind_config(base)
    metrics = Simulator(cfg).run()
    assert metrics.steps == 5
    assert metrics.completed_tasks >= 0


# ---------------------------------------------------------------------------
# T-LB-3 — Harness dispatch wires lacam_blind through to the SimConfig
# ---------------------------------------------------------------------------


def test_T_LB_3_harness_dispatch_lacam_blind(small_map):
    """``_apply_method(base, 'lacam_blind')`` returns the
    factory-applied SimConfig.  The full ``run_one`` round-trip then
    surfaces these fields under ``applied_*`` CSV columns."""
    base = SimConfig(map_path=small_map, seed=0, steps=2,
                     global_solver="cbs")  # base intentionally differs
    cfg = _apply_method(base, "lacam_blind")
    assert cfg.global_solver == "lacam_official"
    assert cfg.controller_kind == "global_only"

    # End-to-end through run_one.
    run_cfg = {
        "map_path": small_map, "seed": 0, "steps": 2,
        "num_agents": 1, "num_humans": 0,
        "fov_radius": 4, "safety_radius": 1,
        "global_solver": "cbs", "horizon": 20,
        "replan_every": 10, "solver_timeout_s": 2.0,
        "hard_safety": True, "mode": "lifelong",
        "task_allocator": "greedy",
        "method": "lacam_blind",
    }
    with tempfile.TemporaryDirectory() as td:
        row = {
            "run_id": compute_run_id(run_cfg, 0),
            "experiment": "test_lacam_blind",
            "seed": 0, "config": run_cfg,
            "_sidecar_dir": str(Path(td) / "timelines"),
        }
        rec = run_one(row)
    assert rec["applied_global_solver"] == "lacam_official", rec
    # Raw column reflects the YAML's pre-dispatch value.
    assert rec["global_solver"] == "cbs"


# ---------------------------------------------------------------------------
# T-LB-4 — Stale rhcr YAML fails loudly at config build
# ---------------------------------------------------------------------------


def test_T_LB_4_rhcr_method_raises_not_implemented(small_map):
    """``method="rhcr"`` in a stale YAML must raise
    NotImplementedError at config-build time with a message naming
    docs/RHCR_DEFERRED.md and the lacam_blind substitute.  Silent
    re-routing would let stale sweeps pollute the paper's data."""
    run_cfg = {
        "map_path": small_map, "seed": 0, "steps": 2,
        "num_agents": 1, "num_humans": 0,
        "global_solver": "cbs", "horizon": 20, "replan_every": 10,
        "solver_timeout_s": 2.0, "hard_safety": True, "mode": "lifelong",
        "task_allocator": "greedy",
        "method": "rhcr",
    }
    with pytest.raises(NotImplementedError) as exc_info:
        _build_sim_config(run_cfg)
    msg = str(exc_info.value)
    # The error message must be actionable: name the doc and the
    # substitute method.
    assert "RHCR_DEFERRED.md" in msg, (
        f"error message must cite docs/RHCR_DEFERRED.md; got: {msg!r}"
    )
    assert "lacam_blind" in msg, (
        f"error message must name the lacam_blind substitute; got: {msg!r}"
    )
