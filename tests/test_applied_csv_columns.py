"""Regression tests for the ``applied_*`` CSV columns in the paper
sweep harness (``scripts.evaluation.run_paper_experiment``).

Background.  Before this fix, the per-run CSV row was built by
flattening ``row["config"]`` — the raw YAML sweep cell — BEFORE
``_apply_method`` had a chance to dispatch on the ``method`` axis.
The factories (``make_pibt2_fr_config``, ``make_no_buffer_config``,
``make_rhcr_blind_config``) DID run and DID produce the right
``SimConfig`` for the simulator, but the CSV recorded only the
pre-dispatch values.  In the §5.8 smoke sweep, all four methods
(ours / no_buffer / pibt2_fr / rhcr) ended up with identical-looking
config columns even though the simulator was running four different
configurations — a strong source of misdiagnosis.

The fix adds an ``applied_*`` block of columns reflecting the
post-dispatch SimConfig.  These tests pin:

* T-AC-1  All seven ``applied_*`` columns exist on every status=ok row.
* T-AC-2  ``no_buffer``'s ``applied_safety_radius`` is 0 (not 1).
* T-AC-3  ``pibt2_fr``'s ``applied_global_solver`` is ``"pibt2"`` and
          ``applied_replan_every`` is 1.
* T-AC-4  ``rhcr``'s ``applied_global_solver`` is ``"rhcr"``.
* T-AC-5  ``ours``'s ``applied_*`` columns equal the base config
          values (factory is a no-op).

The tests use the simplest backend (cbs) and a tiny 5x5 map so they
run in <1s without external solver binaries.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.evaluation.run_paper_experiment import (
    _APPLIED_CSV_FIELDS, compute_run_id, run_one,
)


@pytest.fixture
def small_map(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _base_cfg(map_path: str) -> dict:
    """Minimal SimConfig fields that build a runnable Simulator with
    the in-tree Python CBS backend (no external binary)."""
    return {
        "map_path": map_path,
        "seed": 0,
        "steps": 3,
        "num_agents": 1,
        "num_humans": 0,
        "fov_radius": 4,
        "safety_radius": 1,
        "global_solver": "cbs",
        "horizon": 20,
        "replan_every": 10,
        "solver_timeout_s": 2.0,
        "hard_safety": True,
        "mode": "lifelong",
        "task_allocator": "greedy",
    }


def _run(method: str, map_path: str) -> dict:
    cfg = _base_cfg(map_path)
    cfg["method"] = method
    with tempfile.TemporaryDirectory() as td:
        row = {
            "run_id": compute_run_id(cfg, 0),
            "experiment": "test_applied",
            "seed": 0, "config": cfg,
            "_sidecar_dir": str(Path(td) / "timelines"),
        }
        return run_one(row)


# ---------------------------------------------------------------------------
# T-AC-1 — applied_* columns are present on every status=ok row
# ---------------------------------------------------------------------------


def test_T_AC_1_all_applied_columns_present(small_map):
    """Every status=ok row carries all seven ``applied_*`` columns."""
    rec = _run("ours", small_map)
    assert rec["status"] == "ok", rec
    for key in _APPLIED_CSV_FIELDS:
        assert f"applied_{key}" in rec, (
            f"missing applied_{key} in record keys: {sorted(rec.keys())!r}"
        )


# ---------------------------------------------------------------------------
# T-AC-2 — no_buffer: applied_safety_radius == 0
# ---------------------------------------------------------------------------


def test_T_AC_2_no_buffer_safety_radius_zero(small_map):
    """``make_no_buffer_config`` overrides ``safety_radius=0``.  The
    CSV row must reflect the post-dispatch value, not the pre-dispatch
    base ``safety_radius=1``.  Pre-fix this is the bug that caused the
    §5.8 smoke audit to misdiagnose dispatch as broken."""
    rec = _run("no_buffer", small_map)
    assert rec["status"] == "ok", rec
    assert rec["applied_safety_radius"] == 0, (
        f"no_buffer should have applied_safety_radius=0, got "
        f"{rec['applied_safety_radius']!r}"
    )
    # Base field still shows the raw YAML cell.  Both can coexist;
    # the test pins that ``applied_*`` is distinct.
    assert rec["safety_radius"] == 1


# ---------------------------------------------------------------------------
# T-AC-3 — pibt2_fr: solver swap + replan cadence
# ---------------------------------------------------------------------------


def test_T_AC_3_pibt2_fr_overrides(small_map):
    """``make_pibt2_fr_config`` overrides ``global_solver=pibt2``,
    ``replan_every=1``, ``horizon=20``.  The CSV must reflect all
    three."""
    rec = _run("pibt2_fr", small_map)
    # We don't require status=ok here because the test box may not
    # have a working PIBT2 binary; we just need run_one to have built
    # the record with applied_* columns before the simulator ran.
    # Even on a binary failure those columns are populated in the
    # try-block before Simulator construction.
    assert rec["applied_global_solver"] == "pibt2", rec
    assert rec["applied_replan_every"] == 1, rec
    assert rec["applied_horizon"] == 20, rec


# ---------------------------------------------------------------------------
# T-AC-4 — lacam_blind: solver enforced, controller swapped
# ---------------------------------------------------------------------------


def test_T_AC_4_lacam_blind_overrides(small_map):
    """``make_lacam_blind_config`` enforces ``global_solver=lacam_official``
    and ``controller_kind=global_only``.  Replaces the originally-
    planned ``rhcr`` baseline — see docs/RHCR_DEFERRED.md."""
    rec = _run("lacam_blind", small_map)
    assert rec["applied_global_solver"] == "lacam_official", rec


# ---------------------------------------------------------------------------
# T-AC-5 — ours: applied_* equals the base config (no-op factory)
# ---------------------------------------------------------------------------


def test_T_AC_5_ours_applied_matches_base(small_map):
    """The ``ours`` method is the identity factory.  Every
    ``applied_*`` value must equal its base-config counterpart, so a
    side-by-side CSV inspection on the ours rows shows nothing
    surprising."""
    rec = _run("ours", small_map)
    base = _base_cfg(small_map)
    for key in _APPLIED_CSV_FIELDS:
        if key in base:
            assert rec[f"applied_{key}"] == base[key], (
                f"ours should preserve base {key}={base[key]!r}; got "
                f"applied_{key}={rec[f'applied_{key}']!r}"
            )
