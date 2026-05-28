"""Lock-in tests for the two N_x conventions (P13 follow-up).

The paper uses the column name "N_x" in both §5.4 (baseline
comparison) and §5.1 (horizon tuning) but the underlying formula
differs.  This file pins the audit verdicts:

  * §5.4 / baseline_comparison_v2 -- Outcome (i): identity
    transform on ``violations_exogenous_attributable`` reproduces
    every cell within 0.007% (see ``reports/table1_audit.md``).
  * §5.1 / horizon_replan_full    -- Outcome (ii): no candidate
    in the expanded panel reproduces the paper N_x within 5% per
    cell.  The sub-table is held STALE in
    ``paper/sections/05_1_horizon_subtable_STALE.md``.

A future edit to the diagnostic, the candidate panel, or the
schema that quietly changes either verdict fires the matching
test below.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

import find_nx_source as nx  # noqa: E402


def test_baseline_identity_holds():
    """§5.4 / baseline_comparison_v2: the identity transform on
    ``violations_exogenous_attributable`` (or its tied sibling
    ``safety_violations``) must remain the best fit at
    L2 < 0.1 and max rel err < 0.1%.  Locks
    ``reports/table1_audit.md``'s outcome (i) verdict against
    schema drift."""
    csv_path = REPO_ROOT / "logs" / "paper" / "solver_sensitivity" / "results.csv"
    if not csv_path.exists():
        pytest.skip(f"{csv_path} missing")
    rows = nx.load_rows(csv_path)
    cells = dict(nx.filter_paper_cells(rows, nx.PAPER_TABLE1_H))
    fits = []
    for col in nx.numeric_columns(rows):
        for label, fn in nx.TRANSFORMS:
            res = nx.fit_residual(col, label, fn, cells, dict(nx.PAPER_NX))
            if res is None:
                continue
            l2, max_rel, n_cells, _per_cell = res
            fits.append((col, label, l2, max_rel))
    fits.sort(key=lambda t: (t[2], t[3]))
    assert fits, "no fits"
    top_col, top_label, top_l2, top_rel = fits[0]
    assert top_label == "x", (
        f"identity transform should win on the baseline audit; "
        f"got col={top_col!r} label={top_label!r}"
    )
    assert top_col in (
        "violations_exogenous_attributable",
        "safety_violations",
    ), top_col
    assert top_l2 < 0.1, (
        f"baseline outcome (i) regression: top L2 {top_l2:.4f} >= 0.1; "
        f"the §5.4 N_x convention no longer reproduces from "
        f"violations_exogenous_attributable."
    )
    assert top_rel < 1e-3, (
        f"baseline outcome (i) regression: top max rel err "
        f"{top_rel*100:.3f}% >= 0.1%"
    )


def test_horizon_outcome_locked():
    """§5.1 / horizon_replan_full: the diagnostic must continue
    to report outcome (ii) -- no candidate reproduces the paper
    N_x within 5% per cell -- AND the column dimension must not
    collapse (the P13 bug that produced identical residuals
    across every column).  If a future panel addition drops the
    max per-cell rel err below 5%, the responder must update
    ``paper/sections/05_1_horizon_subtable_STALE.md`` and
    ``reports/nx_horizon_audit.md`` to reflect the new (i)
    outcome.
    """
    csv_path = REPO_ROOT / "logs" / "tuning" / "horizon_replan_full" / "results.csv"
    if not csv_path.exists():
        pytest.skip(f"{csv_path} missing")
    rows = nx.load_rows(csv_path)
    cells = dict(nx.filter_horizon_cells(rows))
    paper_dict = dict(nx.PAPER_NX_HORIZON)
    # Sanity: filter should produce all 16 cells (2 maps x 8 H).
    assert len(cells) == 16, (
        f"expected 16 horizon cells, got {len(cells)}; the "
        f"|M|=100, |X|=50 filter may have drifted from the "
        f"sweep config."
    )
    # Panel A -- column x unary-transform grid.  Every transform
    # MUST use its column argument; assert_no_column_collapse
    # raises if two distinct columns share a residual to 1e-9
    # under the same transform (the P14 collapse bug signature).
    panel_a = []
    for col in nx.numeric_columns(rows):
        for label, fn in nx.UNARY_TRANSFORMS:
            res = nx.fit_residual(col, label, fn, cells, paper_dict)
            if res is None:
                continue
            l2, max_rel, n_cells, per_cell = res
            panel_a.append((col, label, l2, max_rel, n_cells, per_cell))
    # **The no-collapse property** -- the test that would have
    # caught the P13 column-binding bug.  ``assert_no_column_collapse``
    # raises RuntimeError if collapse is detected; we wrap it in a
    # try / re-raise here so the failure mode is visible in pytest
    # output as a test failure (not just an uncaught exception).
    try:
        nx.assert_no_column_collapse(panel_a)
    except RuntimeError as exc:
        raise AssertionError(
            f"column dimension collapse detected in Panel A -- the "
            f"P13 bug has regressed.  The diagnostic's unary "
            f"transform panel must use its column argument on EVERY "
            f"entry; reading named columns from the row instead "
            f"belongs in NAMED_DERIVED (Panel B).  Detail: {exc}"
        ) from exc

    # Panel B -- named derived quantities with free scaling.
    panel_b = []
    for label, fn in nx.NAMED_DERIVED:
        res = nx.fit_named_derived(label, fn, cells, paper_dict)
        if res is None:
            continue
        c, l2, max_rel, n_cells, per_cell = res
        panel_b.append((label, c, l2, max_rel, n_cells, per_cell))

    panel_a.sort(key=lambda t: (t[2], t[3]))
    panel_b.sort(key=lambda t: (t[3], t[2]))
    best_max_rel = min(
        (panel_a[0][3] if panel_a else float("inf")),
        (panel_b[0][3] if panel_b else float("inf")),
    )
    # The audit verdict requires max per-cell rel err >= 5%
    # across BOTH panels.
    assert best_max_rel >= nx.OUTCOME_I_THRESHOLD, (
        f"horizon outcome flipped to (i): best max rel err across "
        f"both panels {best_max_rel*100:.3f}% < "
        f"{nx.OUTCOME_I_THRESHOLD*100:.0f}%.  A candidate formula "
        f"now reproduces the paper §5.1 N_x values; update "
        f"paper/sections/05_1_horizon_subtable_STALE.md and "
        f"reports/nx_horizon_audit.md to reflect the new (i) "
        f"verdict."
    )
    # Sanity-check the residual band the post-collapse-fix audit
    # observed (best fit ~20%).  A drift above 50% would mean the
    # |M|=100, |X|=50 slice no longer exists in the CSV.
    assert best_max_rel < 0.50, (
        f"horizon audit residual ({best_max_rel*100:.3f}%) above "
        f"50%; the diagnostic may be reading the wrong slice of "
        f"the horizon CSV.  Expected best-fit rel err ~20% per "
        f"the post-collapse-fix audit."
    )


# Companion tests (STALE-marker existence, audit-doc phrase
# presence) live in tests/test_paper_metric_invariants.py
# alongside the rest of the paper-metric invariants.  Keeping
# this file at exactly two tests per the P13 task spec.
