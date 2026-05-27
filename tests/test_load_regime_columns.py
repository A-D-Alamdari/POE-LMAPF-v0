"""Acceptance tests for the load-regime columns (P10).

The simulator's lifelong task stream uses a per-agent inter-arrival
mean of $H+W$ steps, so the system-wide arrival rate is
$\\lambda_{\\text{sys}} = |M|/(H+W)$ and throughput cannot exceed
this cap.  ``MetricsTracker.finalize`` now emits
``arrival_rate_per_step`` and ``throughput_utilization`` so the
table builder can flag arrival-saturated cells; the paper text in
``paper/sections/05_1_load_regime.{md,tex}`` warns readers not to
interpret throughput in saturated cells as a planner-quality
metric.

This file pins:

  * ``MetricsTracker.finalize`` returns the two new fields with the
    expected ratio,
  * the CSV header / row writer carry both columns in lockstep,
  * the table builder routes ``throughput_utilization`` through the
    arrival-saturation renderer and asterisks saturated cells,
  * ``paper/sections/05_1_load_regime.{md,tex}`` exist and carry
    the canonical headline numbers + warning sentence,
  * the diagnostic ``check_arrival_saturation.py`` flags the §5.2
    cells as arrival-saturated.
"""
from __future__ import annotations

import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "evaluation"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))

from ha_lmapf.core.metrics import MetricsTracker  # noqa: E402
import build_summary_tables as bst  # noqa: E402
import check_arrival_saturation as cas  # noqa: E402


# ---------------------------------------------------------------------------
# Metrics emission
# ---------------------------------------------------------------------------


def test_finalize_emits_arrival_rate_and_utilization():
    """A tracker fed N releases over T steps and K completions
    must report arrival_rate = N/T and utilization = K/N."""
    tracker = MetricsTracker()
    # Release 10 tasks at steps 0..9, complete 7 of them.
    for i in range(10):
        tracker.on_task_released(f"t{i}", release_step=i)
    for i in range(7):
        tracker.on_task_completed(f"t{i}", agent_id=0, step=i + 5)

    m = tracker.finalize(total_steps=100, num_agents=1)
    # arrival_rate = 10 / 100 = 0.10
    # throughput   = 7 / 100 = 0.07
    # utilization  = throughput / arrival_rate = 0.7
    assert m.arrival_rate_per_step == pytest.approx(0.10)
    assert m.throughput == pytest.approx(0.07)
    assert m.throughput_utilization == pytest.approx(0.70)


def test_finalize_handles_zero_releases():
    """Zero released tasks => arrival_rate = 0 and utilization
    falls back to 0 (no division by zero)."""
    tracker = MetricsTracker()
    m = tracker.finalize(total_steps=100, num_agents=1)
    assert m.arrival_rate_per_step == 0.0
    assert m.throughput_utilization == 0.0


def test_csv_header_carries_arrival_columns():
    header = MetricsTracker.csv_header()
    assert "arrival_rate_per_step" in header, (
        "arrival_rate_per_step missing from CSV header"
    )
    assert "throughput_utilization" in header, (
        "throughput_utilization missing from CSV header"
    )
    # Both must sit next to throughput (the reader expects them
    # together).
    i_thpt = header.index("throughput")
    assert header[i_thpt + 1] == "arrival_rate_per_step"
    assert header[i_thpt + 2] == "throughput_utilization"


def test_csv_row_round_trip_preserves_arrival_columns():
    tracker = MetricsTracker()
    for i in range(10):
        tracker.on_task_released(f"t{i}", release_step=i)
    for i in range(5):
        tracker.on_task_completed(f"t{i}", agent_id=0, step=i + 1)
    metrics = tracker.finalize(total_steps=50, num_agents=1)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(MetricsTracker.csv_header())
    w.writerow(tracker.to_csv_row(metrics))
    buf.seek(0)
    row = next(csv.DictReader(buf))
    assert float(row["arrival_rate_per_step"]) == pytest.approx(0.20)
    assert float(row["throughput_utilization"]) == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Paper-table builder integration
# ---------------------------------------------------------------------------


def test_render_utilization_cell_appends_asterisk_when_saturated():
    """Cells with mean util >= 0.95 must carry a trailing asterisk
    so a reader can scan the table for the marker."""
    # mean = 0.97
    cell = bst._render_utilization_cell([0.95, 0.97, 0.99])
    assert cell.endswith("*"), cell
    # mean = 0.50 -- no asterisk
    cell_low = bst._render_utilization_cell([0.40, 0.50, 0.60])
    assert not cell_low.endswith("*"), cell_low


def test_render_utilization_cell_handles_empty():
    assert bst._render_utilization_cell([]) == "—"


def test_render_utilization_threshold_is_documented():
    """The threshold the diagnostic and the table builder use must
    agree; otherwise a cell flagged in the audit could go un-marked
    in the published table."""
    assert (bst.ARRIVAL_SATURATION_THRESHOLD
            == cas.ARRIVAL_SATURATION_THRESHOLD)


def test_throughput_utilization_in_cols_t1():
    """Util.\\ column must be in COLS_T1 right after throughput so
    the reader sees them side by side."""
    fields = [c[0] for c in bst.COLS_T1]
    i_thpt = fields.index("throughput")
    assert fields[i_thpt + 1] == "throughput_utilization", (
        f"throughput_utilization must follow throughput in COLS_T1; "
        f"got order {fields}"
    )


def test_throughput_utilization_in_cols_t2():
    fields = [c[0] for c in bst.COLS_T2]
    i_thpt = fields.index("throughput")
    assert fields[i_thpt + 1] == "throughput_utilization", (
        f"throughput_utilization must follow throughput in COLS_T2; "
        f"got order {fields}"
    )


# ---------------------------------------------------------------------------
# Diagnostic
# ---------------------------------------------------------------------------


def test_map_dimensions_reads_header():
    """check_arrival_saturation._map_dimensions must parse H and W
    from a MovingAI .map header so the diagnostic's λ_sys column
    is accurate."""
    cache: dict = {}
    h, w = cas._map_dimensions(
        REPO_ROOT / "data" / "maps" / "random-64-64-10.map", cache,
    )
    assert (h, w) == (64, 64)
    h, w = cas._map_dimensions(
        REPO_ROOT / "data" / "maps" / "warehouse-10-20-10-2-2.map", cache,
    )
    assert (h, w) == (84, 170)


def test_diagnostic_flags_5_2_cells_as_arrival_saturated(tmp_path: Path):
    """End-to-end: run the diagnostic on the §5.2 CSV and verify
    every cell is reported as ARRIVAL-SATURATED -- the empirical
    confirmation that the paper Table 1 throughput numbers are the
    arrival cap, not the planner cap."""
    csv_path = REPO_ROOT / "logs" / "paper" / "solver_sensitivity" / "results.csv"
    if not csv_path.exists():
        pytest.skip(f"{csv_path} missing")
    out_md = tmp_path / "audit.md"
    rc = cas.main([
        "--results-csv", str(csv_path),
        "--out", str(out_md),
        "--group-by", "map_path,num_agents",
        "--log-level", "WARNING",
    ])
    assert rc == 0
    text = out_md.read_text()
    # Body verdict check: every cell row must end with
    # ARRIVAL-SATURATED.  The threshold legend that mentions all
    # three verdicts sits outside the table body.
    body_lines = [
        line for line in text.splitlines()
        if line.startswith("|") and "verdict" not in line and "---" not in line
    ]
    assert body_lines, "audit body is empty"
    for line in body_lines:
        assert line.rstrip().endswith("ARRIVAL-SATURATED |"), (
            f"non-saturated cell in §5.2 audit: {line!r}"
        )
    # The expected λ_sys values must appear (random|M|=100 = 0.781,
    # warehouse|M|=100 = 0.394).
    assert "0.781" in text
    assert "0.394" in text


def test_diagnostic_returns_2_when_exit_nonzero_on_saturation(tmp_path: Path):
    csv_path = REPO_ROOT / "logs" / "paper" / "solver_sensitivity" / "results.csv"
    if not csv_path.exists():
        pytest.skip(f"{csv_path} missing")
    rc = cas.main([
        "--results-csv", str(csv_path),
        "--out", str(tmp_path / "a.md"),
        "--group-by", "map_path,num_agents",
        "--exit-nonzero-on-saturation",
        "--log-level", "WARNING",
    ])
    assert rc == 2, (
        f"--exit-nonzero-on-saturation must return 2 when any cell "
        f"is saturated; got rc={rc}"
    )


# ---------------------------------------------------------------------------
# Section files + canonical wording
# ---------------------------------------------------------------------------


def test_load_regime_section_files_exist():
    md = REPO_ROOT / "paper" / "sections" / "05_1_load_regime.md"
    tex = REPO_ROOT / "paper" / "sections" / "05_1_load_regime.tex"
    assert md.exists(), f"{md} missing"
    assert tex.exists(), f"{tex} missing"


def test_load_regime_md_contains_canonical_phrase():
    """The exact phrase the task spec mandates must appear in the
    §5.1 markdown section so a paste into the paper text surfaces
    the warning to readers verbatim."""
    md = (REPO_ROOT / "paper" / "sections" / "05_1_load_regime.md").read_text()
    assert "0.781" in md
    assert "0.394" in md
    # Core phrasing the reader sees.
    assert "task-arrival-rate compliance, not planner\ncapacity." in md, (
        "canonical warning sentence missing from 05_1_load_regime.md"
    )


def test_load_regime_tex_contains_canonical_phrase():
    tex = (REPO_ROOT / "paper" / "sections" / "05_1_load_regime.tex").read_text()
    assert "0.781" in tex
    assert "0.394" in tex
    assert "task-arrival-rate" in tex
    assert "planner" in tex
