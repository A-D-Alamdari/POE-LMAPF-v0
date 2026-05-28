"""Acceptance tests for the System Health Indicators columns (P9).

The paper-table builder grew four new columns that surface
agent-level progress signal alongside throughput:

  * Deadlock count        -- per-cell mean ± CI of ``deadlock_count``
  * Frac. runs with DL    -- fraction of seeds with ``deadlock_count > 0``
  * Max DL count          -- worst-seed deadlock count
  * GNP steps             -- per-cell mean ± CI of ``global_no_progress_steps``

This file pins:

  * the new helper functions render the expected strings;
  * ``build_table1`` / ``build_table2`` append the four columns to
    every row;
  * ``emit_table1`` / ``emit_table2`` headers carry the four new
    column names AND match the row width;
  * the per-cell footnote text under Table 1 contains the required
    acceptance sentence ("At |M|=100 on the warehouse map, an
    average of <N> agents per run cross the deadlock threshold;
    this is consistent with the system being task-arrival-limited.");
  * ``paper/sections/05_4_system_health.{md,tex}`` exist and contain
    the canonical claim sentence the task spec mandates.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "evaluation"))

import build_summary_tables as bst  # noqa: E402


# ---------------------------------------------------------------------------
# Helper-function unit tests
# ---------------------------------------------------------------------------


def test_fraction_with_deadlock_handles_empty():
    """Empty input yields NaN, not a div-by-zero."""
    result = bst._fraction_with_deadlock([])
    assert result != result  # NaN check


def test_fraction_with_deadlock_counts_strictly_positive():
    """Only seeds with deadlock_count > 0 count toward the fraction.
    Zero values are NOT counted -- a seed with zero deadlocks did
    NOT cross the threshold."""
    assert bst._fraction_with_deadlock([0, 0, 0]) == 0.0
    assert bst._fraction_with_deadlock([0, 1, 0, 2]) == 0.5
    assert bst._fraction_with_deadlock([1, 2, 3]) == 1.0
    # Strict >0: 0.5 (the 0.5 value... wait actually float values can be 0
    # but if you pass 0.5 that's > 0 so it counts).  Pin the contract.
    assert bst._fraction_with_deadlock([0, 0.5]) == 0.5


def test_max_deadlock_returns_integer_worst_seed():
    """Max is taken across seeds; result is an int (the agent count
    is integral)."""
    assert bst._max_deadlock([0, 5, 2, 10, 1]) == 10
    assert bst._max_deadlock([]) == 0


def test_fmt_pct_renders_percentage():
    assert bst._fmt_pct(0.0) == "0%"
    assert bst._fmt_pct(0.5) == "50%"
    assert bst._fmt_pct(1.0) == "100%"
    assert bst._fmt_pct(float("nan")) == "—"


def test_render_health_cell_dispatches_by_kind():
    rs = [
        {"deadlock_count": 0}, {"deadlock_count": 5},
        {"deadlock_count": 10}, {"deadlock_count": 0},
    ]
    # ci: mean across the four values = 3.75
    ci = bst._render_health_cell("deadlock_count", 2, "ci", rs)
    assert "3.75" in ci and "±" in ci, ci
    # max: 10
    assert bst._render_health_cell("deadlock_count", 0, "max", rs) == "10"
    # pct: 2/4 seeds > 0 = 50%
    assert bst._render_health_cell("deadlock_count", 0, "pct", rs) == "50%"
    # missing column -> em-dash
    rs_missing = [{"throughput": 0.5} for _ in range(3)]
    assert bst._render_health_cell("deadlock_count", 2, "ci", rs_missing) == "—"


def test_render_health_cell_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown health-column kind"):
        bst._render_health_cell("x", 2, "bogus", [{"x": 1}])


# ---------------------------------------------------------------------------
# HEALTH_COLS contract
# ---------------------------------------------------------------------------


def test_HEALTH_COLS_has_required_four_columns():
    """The P9 task spec calls for exactly these four columns,
    appended to every results table; their (field, label, kind)
    contract is pinned here so a future re-ordering doesn't break
    downstream readers."""
    labels = [c[1] for c in bst.HEALTH_COLS]
    assert "Deadlock count" in labels
    assert "Frac. runs with DL" in labels
    assert "Max DL count" in labels
    assert "GNP steps" in labels
    # The deadlock-count "ci" entry MUST come before its sibling
    # pct/max entries so the reader sees the mean first.
    fields_in_order = [(c[0], c[3]) for c in bst.HEALTH_COLS]
    assert fields_in_order.index(("deadlock_count", "ci")) == 0


# ---------------------------------------------------------------------------
# Table builder integration tests against committed CSVs
# ---------------------------------------------------------------------------


@pytest.fixture
def baseline_v2_rows() -> List[Dict[str, Any]]:
    path = REPO_ROOT / "logs" / "paper" / "baseline_comparison_v2" / "results.csv"
    if not path.exists():
        pytest.skip(f"{path} missing")
    with path.open() as f:
        return bst.filter_ok(list(csv.DictReader(f)))


def test_build_table2_appends_health_columns(baseline_v2_rows):
    """Table 2 builder must append four health columns to every row.
    Row width = 1 (method) + len(COLS_T2) + len(HEALTH_COLS)."""
    rows = bst.build_table2([
        {k: bst._coerce(v) for k, v in r.items()} for r in baseline_v2_rows
    ])
    expected_width = 1 + len(bst.COLS_T2) + len(bst.HEALTH_COLS)
    assert rows, "build_table2 produced no rows"
    for density, body in rows.items():
        for row in body:
            assert len(row) == expected_width, (
                f"|M|={density} row width {len(row)} != {expected_width}; "
                f"row={row}"
            )


def test_table2_at_M100_warehouse_carries_nonzero_deadlock(baseline_v2_rows):
    """The headline acceptance datum: at |M|=100 on the warehouse
    map, Ours reports a nonzero deadlock count in the rendered
    table.  This is the cell the P9 task spec cites directly."""
    rows = bst.build_table2([
        {k: bst._coerce(v) for k, v in r.items()} for r in baseline_v2_rows
    ])
    body = rows.get(100)
    assert body, "no |M|=100 cell in build_table2 output"
    # Find the Ours row.
    ours_row = next(
        (row for row in body
         if row[0] == bst.METHOD_DISPLAY.get("ours", "ours")),
        None,
    )
    assert ours_row, "Ours method missing from |M|=100 cell"
    # Health columns are appended after len(COLS_T2)+1 cells.
    health_start = 1 + len(bst.COLS_T2)
    deadlock_cell = ours_row[health_start]   # first HEALTH_COLS entry
    frac_cell = ours_row[health_start + 1]
    max_cell = ours_row[health_start + 2]
    assert deadlock_cell != "—", deadlock_cell
    # Mean is around 16 (per the §5.4 system-health table);
    # tolerate ±5 to absorb seed variation across re-runs.
    mean_value = float(deadlock_cell.split("±")[0].strip())
    assert 10.0 <= mean_value <= 25.0, (
        f"|M|=100 Ours deadlock mean {mean_value} outside expected "
        f"range; CSV may have drifted from baseline_comparison_v2"
    )
    assert frac_cell == "100%", frac_cell
    assert int(max_cell) >= 1, max_cell


# ---------------------------------------------------------------------------
# Document presence + canonical claim sentence
# ---------------------------------------------------------------------------


def test_system_health_section_files_exist():
    """The new §5.4 section files must be committed under
    paper/sections/ in both md and tex form."""
    md = REPO_ROOT / "paper" / "sections" / "05_4_system_health.md"
    tex = REPO_ROOT / "paper" / "sections" / "05_4_system_health.tex"
    assert md.exists(), f"{md} missing"
    assert tex.exists(), f"{tex} missing"


def test_system_health_md_carries_the_canonical_claim():
    """The exact sentence the task spec calls out must be present
    (with no transformation -- a copy-paste from md to paper text
    has to surface it verbatim)."""
    md = (REPO_ROOT / "paper" / "sections" / "05_4_system_health.md").read_text()
    canonical = (
        "In configurations where throughput is task-arrival-limited, "
        "the\nthroughput column does not reflect agent-level progress.  "
        "The\n`deadlock_count` column does."
    )
    assert canonical in md, (
        "canonical claim sentence missing from system_health.md; "
        "tweaks to the doc must preserve it verbatim per the "
        "P9 task spec."
    )


def test_table1_md_carries_the_acceptance_sentence():
    """The text under Table 1 must include the acceptance sentence
    naming |M|=100 warehouse and the deadlock count."""
    md = (REPO_ROOT / "paper" / "tables"
          / "table1_solver_substitutability.md").read_text()
    # The sentence is broken across lines for markdown wrapping; we
    # check the core substrings the reviewer is looking for.
    assert "|M| = 100 on the warehouse map" in md, md
    assert "agents per run\ncross the deadlock threshold" in md, md
    assert "task-arrival-limited" in md, md


def test_table1_tex_carries_the_acceptance_sentence():
    tex = (REPO_ROOT / "paper" / "tables"
           / "table1_solver_substitutability.tex").read_text()
    assert "16.10" in tex, "headline number missing from table1 tex"
    assert "task-arrival-limited" in tex, tex
    assert "deadlock threshold" in tex, tex
