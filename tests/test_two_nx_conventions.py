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
    """§5.1 / horizon_replan_full: the audit verdict is
    **UNRESOLVED**, not outcome (ii).  An earlier version of
    this test asserted "outcome (ii) holds" against the
    diagnostic's max per-cell rel err threshold; that
    assertion treated the question as closed even though the
    underlying search had a column-binding bug and, even after
    the P14 fix, a finite candidate panel cannot demonstrate
    non-reproducibility.

    The corrected lock-in is: the STALE doc must continue to
    describe the §5.1 source as UNRESOLVED (not "deleted
    source").  A future commit that flips the verdict back to
    "outcome (ii)" without locating the formula, or claims
    "outcome (i)" without documenting the matching formula,
    must update the STALE doc; this test fires when the doc
    no longer carries the UNRESOLVED status string.
    """
    stale = REPO_ROOT / "paper" / "sections" / "05_1_horizon_subtable_STALE.md"
    assert stale.exists(), (
        f"{stale} missing -- the STALE marker has been deleted, "
        f"silently re-opening the verifiability hole the audit "
        f"closed.  Restore it or document the resolution in a "
        f"replacement doc."
    )
    txt = stale.read_text()
    assert "UNRESOLVED" in txt, (
        "STALE doc no longer describes the §5.1 N_x source as "
        "UNRESOLVED.  If the source has been identified, update "
        "this test and the doc to record the new verdict (and "
        "remove the STALE marker).  If the doc was edited to "
        "restore an over-claimed verdict (e.g. 'deleted source' "
        "or 'outcome (ii)'), revert: a finite candidate panel "
        "cannot demonstrate non-reproducibility."
    )
    # The doc must NOT assert the source was deleted as a
    # positive verdict.  We allow the retraction language
    # ("not shown to come from a deleted source") but reject
    # affirmative claims.  The over-claim signature is the
    # original P13 phrasing: "the values came from a deleted /
    # external source" used as a CONCLUSION.
    OVERCLAIM = "came from a deleted / external source"
    assert OVERCLAIM not in txt, (
        f"STALE doc has reintroduced the retracted over-claim "
        f"{OVERCLAIM!r}.  The audit cannot demonstrate "
        f"non-reproducibility; use 'UNRESOLVED' instead."
    )


# Companion tests (STALE-marker existence, audit-doc phrase
# presence) live in tests/test_paper_metric_invariants.py
# alongside the rest of the paper-metric invariants.  Keeping
# this file at exactly two tests per the P13 task spec.
