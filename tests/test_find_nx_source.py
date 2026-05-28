"""Unit tests for ``scripts/diagnostics/find_nx_source.py``.

The diagnostic that proved the paper Table 1 "N_x" column reproduces
from the per-run CSV needs its own tests so a future refactor of the
candidate-transform panel or the cell-grouping logic doesn't silently
break the audit.

Tests drive the script's fitter against synthetic CSV rows with known
ground truth, then verify:

  * the identity transform on the seed column matches when the paper
    column literally equals one CSV column,
  * a divide-by-N transform matches when the paper column equals
    column/N for known N,
  * cells absent from the CSV are reported as missing (the LaCAM*
    duplication case in the real audit),
  * the panel includes the transforms the spec calls for
    (x, x/T, x/(M*T), x/(X*T), x/completed_tasks).
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import find_nx_source as nx  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic-CSV fixture
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict]) -> Path:
    if not rows:
        path.write_text("seed\n")
        return path
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def _row(seed: int, **overrides) -> dict:
    base = {
        "seed": seed,
        "status": "ok",
        "horizon": 20,
        "map_path": "data/maps/random-64-64-10.map",
        "global_solver": "lacam_official",
        "num_agents": 50,
        "num_humans": 20,
        "steps": 2000,
        "completed_tasks": 47,
        "global_replans": 100,
        "safety_violations": 2454,
        "violations_exogenous_attributable": 2454,
        "violations_agent_attributable": 0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Transform panel coverage
# ---------------------------------------------------------------------------


def test_panel_includes_spec_transforms():
    """The task spec lists a minimum set of candidate transforms;
    each must be in ``nx.TRANSFORMS``."""
    labels = {label for label, _ in nx.TRANSFORMS}
    for required in ("x", "x/T", "x/(M*T)", "x/(X*T)", "x/completed_tasks"):
        assert required in labels, (
            f"transform {required!r} missing from panel; downstream "
            f"audit may overlook the correct fit."
        )


# ---------------------------------------------------------------------------
# Identity-transform fit
# ---------------------------------------------------------------------------


def test_identity_transform_matches_when_paper_equals_csv_column(tmp_path: Path):
    """When the paper column literally equals a CSV column, the
    identity transform ``x`` must produce zero residual and the
    fitter must surface it as the top match."""
    csv_path = tmp_path / "synthetic.csv"
    # Two cells; both have one row each.  Paper value = the CSV
    # column value exactly.
    rows = [
        _row(0,
             map_path="data/maps/random-64-64-10.map",
             violations_exogenous_attributable=1000.0,
             safety_violations=1000.0),
        _row(1,
             map_path="data/maps/warehouse-10-20-10-2-2.map",
             violations_exogenous_attributable=500.0,
             safety_violations=500.0),
    ]
    _write_csv(csv_path, rows)
    paper_nx = {
        ("random-64-64-10",        "lacam_official"): 1000.0,
        ("warehouse-10-20-10-2-2", "lacam_official"): 500.0,
    }

    csv_rows = nx.load_rows(csv_path)
    cells = nx.filter_paper_cells(csv_rows, horizon=20)
    fits = []
    for col in nx.numeric_columns(csv_rows):
        for label, fn in nx.TRANSFORMS:
            res = nx.fit_residual(col, label, fn, cells, paper_nx)
            if res is None:
                continue
            l2, max_rel, n_cells, per_cell = res
            fits.append((col, label, l2, max_rel, n_cells, per_cell))
    fits.sort(key=lambda t: (t[2], t[3]))

    assert fits, "fitter produced no fits"
    top_col, top_label, top_l2, top_rel, top_n, _ = fits[0]
    assert top_label == "x", (
        f"identity transform should win on direct equality; got {top_label!r}"
    )
    # Float-equal up to printing precision.
    assert top_l2 < 1e-9, f"L2 residual {top_l2} should be ~0 on direct equality"
    assert top_rel < 1e-9, f"max rel err {top_rel} should be ~0"
    assert top_n == 2, f"expected 2 cells matched; got {top_n}"


def test_divide_by_steps_transform_matches_when_paper_equals_rate(tmp_path: Path):
    """If the paper column happens to equal x/T, the ``x/T``
    transform should win with zero residual."""
    csv_path = tmp_path / "synthetic.csv"
    # Paper N_x = violations / steps.  At violations=2000, steps=2000,
    # paper = 1.0.
    rows = [
        _row(0, violations_exogenous_attributable=2000.0,
             safety_violations=2000.0, steps=2000),
        _row(1, violations_exogenous_attributable=4000.0,
             safety_violations=4000.0, steps=2000,
             map_path="data/maps/warehouse-10-20-10-2-2.map"),
    ]
    _write_csv(csv_path, rows)
    paper_nx = {
        ("random-64-64-10",        "lacam_official"): 1.0,
        ("warehouse-10-20-10-2-2", "lacam_official"): 2.0,
    }

    csv_rows = nx.load_rows(csv_path)
    cells = nx.filter_paper_cells(csv_rows, horizon=20)
    fits = []
    for col in nx.numeric_columns(csv_rows):
        for label, fn in nx.TRANSFORMS:
            res = nx.fit_residual(col, label, fn, cells, paper_nx)
            if res is None:
                continue
            fits.append((col, label, *res[:2]))
    fits.sort(key=lambda t: (t[2], t[3]))
    # Top fit must be (some violations column, x/T).
    top_col, top_label, top_l2, _ = fits[0]
    assert top_label == "x/T", f"expected x/T to win; got {top_label!r}"
    assert top_l2 < 1e-9
    assert top_col in ("violations_exogenous_attributable", "safety_violations"), top_col


# ---------------------------------------------------------------------------
# Missing-cell handling
# ---------------------------------------------------------------------------


def test_missing_cell_does_not_break_fit(tmp_path: Path):
    """The audit reports cells that exist in the paper but not in
    the CSV (the LaCAM* / lacam3 duplication case in the real
    Table 1).  The fitter must compute the L2 over the cells that
    DO match without exploding on the absent ones."""
    csv_path = tmp_path / "synthetic.csv"
    # Paper has two cells (random + warehouse); CSV has only one.
    rows = [
        _row(0, violations_exogenous_attributable=1000.0,
             safety_violations=1000.0),
    ]
    _write_csv(csv_path, rows)
    paper_nx = {
        ("random-64-64-10",        "lacam_official"): 1000.0,
        ("warehouse-10-20-10-2-2", "lacam_official"): 999.0,  # absent in CSV
    }
    csv_rows = nx.load_rows(csv_path)
    cells = nx.filter_paper_cells(csv_rows, horizon=20)
    res = nx.fit_residual(
        "violations_exogenous_attributable", "x",
        dict(nx.TRANSFORMS)["x"], cells, paper_nx,
    )
    assert res is not None
    l2, max_rel, n_cells, per_cell = res
    assert n_cells == 1, (
        "only one cell exists in the CSV; the missing one must be "
        "skipped, not counted as zero"
    )
    assert l2 < 1e-9


# ---------------------------------------------------------------------------
# Real-audit lock-in (uses the committed CSV; ~10ms)
# ---------------------------------------------------------------------------


def test_real_audit_top_fit_is_identity_on_exo_attributable():
    """Lock the conclusion of ``reports/table1_audit.md`` against the
    committed solver-sensitivity CSV: the top fit must be the
    identity transform on ``violations_exogenous_attributable`` (or
    its tied sibling ``safety_violations``), with L2 residual under
    0.1 -- a regression that broke this would mean either the CSV
    drifted or the fitter is no longer ordering fits correctly."""
    csv_path = REPO_ROOT / "logs" / "paper" / "solver_sensitivity" / "results.csv"
    if not csv_path.exists():
        pytest.skip(f"{csv_path} not present on this checkout")
    csv_rows = nx.load_rows(csv_path)
    cells = nx.filter_paper_cells(csv_rows, horizon=nx.PAPER_TABLE1_H)
    fits = []
    for col in nx.numeric_columns(csv_rows):
        for label, fn in nx.TRANSFORMS:
            res = nx.fit_residual(col, label, fn, cells, nx.PAPER_NX)
            if res is None:
                continue
            fits.append((col, label, res[0], res[1]))
    fits.sort(key=lambda t: (t[2], t[3]))
    assert fits, "no fits computed"
    top_col, top_label, top_l2, top_rel = fits[0]
    assert top_label == "x", (
        f"identity transform must win on the committed audit; "
        f"got top_col={top_col!r} top_label={top_label!r} L2={top_l2:.4f}"
    )
    assert top_col in (
        "violations_exogenous_attributable",
        "safety_violations",
    ), top_col
    assert top_l2 < 0.1, (
        f"top L2 residual {top_l2:.4f} > 0.1 -- the paper's table "
        f"no longer reproduces from the CSV; audit needs rerun"
    )
    assert top_rel < 0.001, (
        f"top max rel err {top_rel*100:.3f}% > 0.1% -- paper / CSV drift"
    )
