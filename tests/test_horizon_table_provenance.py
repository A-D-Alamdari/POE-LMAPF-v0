"""Provenance lock-in for the rebuilt §5 horizon-tuning table.

The table file ``paper/tables/horizon_tuning.tex`` carries a
``% Column "<label>" <- <csv_field_or_formula>`` line per column
in its preamble.  This test parses those lines and asserts that
every column header appearing inside the ``\\begin{tabular}{...}``
block also appears in the preamble -- the auditable surface of
the rebuild.

If a future edit adds a column to the tabular without also
documenting its CSV provenance in the preamble, this test
fires.  That is the regression that would have re-introduced
the "Local Replanning column shows mean_service_time" mismatch.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEX_PATH = REPO_ROOT / "paper" / "tables" / "horizon_tuning.tex"
CSV_PATH = REPO_ROOT / "paper" / "tables" / "horizon_tuning.csv"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tex_text() -> str:
    assert TEX_PATH.exists(), (
        f"{TEX_PATH} missing -- run "
        f"scripts/evaluation/build_table_horizon.py"
    )
    return TEX_PATH.read_text()


@pytest.fixture(scope="module")
def csv_text() -> str:
    assert CSV_PATH.exists(), (
        f"{CSV_PATH} missing -- run "
        f"scripts/evaluation/build_table_horizon.py"
    )
    return CSV_PATH.read_text()


# ---------------------------------------------------------------------------
# Preamble parser
# ---------------------------------------------------------------------------


def _preamble_columns(tex: str) -> dict:
    """Extract ``label -> source`` mappings from the preamble's
    ``% Column "<label>" <- <source>`` lines.  Stops at the
    \\begin{tabular} line."""
    out: dict = {}
    pat = re.compile(r'%\s*Column\s+"([^"]+)"\s*<-\s*(.+?)\s*$', re.MULTILINE)
    # Limit to the part of the file BEFORE the tabular environment
    # so we don't accidentally pick up table rows that happen to
    # contain quoted labels.
    head = tex.split(r"\begin{tabular}", 1)[0]
    for m in pat.finditer(head):
        out[m.group(1)] = m.group(2).strip()
    return out


def _tabular_headers(tex: str) -> list:
    """Pull the header row of the tabular environment.  The
    header is the line between \\toprule and the next \\\\."""
    inside = tex.split(r"\begin{tabular}", 1)
    assert len(inside) == 2, "tabular environment not found"
    body = inside[1]
    # Match \toprule\s*<header line>\s*\\\\\s*\midrule
    m = re.search(r"\\toprule\s*(.+?)\s*\\\\\s*\\midrule", body, re.DOTALL)
    assert m, "could not find header row between \\toprule and \\midrule"
    line = m.group(1).strip()
    return [cell.strip() for cell in line.split("&")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_provenance_block_documents_every_column(tex_text):
    """Every column header in the tabular must appear in the
    preamble's provenance comment block.  Catches "added a
    column to the table without documenting its CSV source"
    regressions."""
    preamble = _preamble_columns(tex_text)
    headers = _tabular_headers(tex_text)
    # The first two columns ("$H$" and "Map") are row indices,
    # not data columns; the provenance block covers only the
    # data columns.
    INDEX_COLUMNS = {"$H$", "Map"}
    missing = [h for h in headers
               if h not in INDEX_COLUMNS and h not in preamble]
    assert not missing, (
        f"horizon_tuning.tex has tabular column(s) with NO CSV "
        f"provenance in the preamble: {missing}.\n"
        f"Add a `% Column \"{missing[0]}\" <- <csv_field>` line "
        f"above the tabular, or rename the header to match a "
        f"documented one.  Preamble currently documents: "
        f"{sorted(preamble)}"
    )


def test_no_orphaned_provenance_lines(tex_text):
    """Inverse direction: every preamble Column-> line must
    correspond to a header that actually appears in the
    tabular.  Catches "removed a column from the table but
    left a dangling preamble line"."""
    preamble = _preamble_columns(tex_text)
    headers = set(_tabular_headers(tex_text))
    orphans = [lbl for lbl in preamble if lbl not in headers]
    assert not orphans, (
        f"horizon_tuning.tex preamble documents column(s) "
        f"that are not in the tabular: {orphans}.  Either "
        f"add them to the tabular or remove the preamble lines."
    )


def test_local_replans_column_is_not_service_time(tex_text):
    """Direct sanity: the 'Local replans' column must source
    from CSV column ``local_replans``, NOT ``mean_service_time``.
    Catches the original Prompt-B-motivating bug.
    """
    preamble = _preamble_columns(tex_text)
    assert "Local replans" in preamble, (
        "expected 'Local replans' header in the rebuilt table"
    )
    src = preamble["Local replans"]
    assert "local_replans" in src and "mean_service_time" not in src, (
        f"'Local replans' column's CSV provenance is {src!r}; "
        f"must source from `local_replans`, not "
        f"`mean_service_time`."
    )


def test_local_replans_values_are_in_thousands(tex_text):
    """The local_replans column values must be in the
    10^3-10^4 range, not 60-150 (which would mean the column
    is sourcing mean_service_time).  Reads the rendered
    \\num{...} cells from the tabular."""
    body = tex_text.split(r"\begin{tabular}", 1)[1]
    # Find the Local replans column by index in the header row.
    headers = _tabular_headers(tex_text)
    idx = headers.index("Local replans")
    # Iterate body rows between \midrule and \bottomrule.
    rows = re.search(r"\\midrule\s*(.+?)\s*\\bottomrule", body, re.DOTALL)
    assert rows, "no data rows found in tabular"
    data = rows.group(1)
    # Extract numeric values from the local_replans column of each row.
    found_thousands = 0
    for line in data.strip().splitlines():
        if r"\\" not in line:
            continue
        cells = line.replace(r"\\", "").split("&")
        if len(cells) <= idx:
            continue
        cell = cells[idx].strip()
        # Pull the first \num{...} value (the mean).
        m = re.search(r"\\num\{([0-9.]+)\}", cell)
        if not m:
            continue
        val = float(m.group(1))
        # local_replans values are in the 10^3-10^4 range
        # (e.g. 4806-19483).  Anything below 1000 is mostly
        # likely mean_service_time bleed-through.
        assert val >= 1000.0, (
            f"local_replans cell renders {val} (< 1000) -- "
            f"likely sourcing mean_service_time instead.  "
            f"Cell: {cell!r}"
        )
        found_thousands += 1
    assert found_thousands > 0, "no local_replans values rendered"


def test_csv_round_trip_loads(csv_text):
    """horizon_tuning.csv must load round-trip via csv.DictReader
    (the spec accepts pandas; csv.DictReader is the same shape)
    and carry the expected per-cell columns."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    assert rows, "horizon_tuning.csv is empty"
    # Must have one row per (H, map) cell: 8 H values x 2 maps = 16.
    assert len(rows) == 16, f"expected 16 rows, got {len(rows)}"
    # Required columns:
    required = {"H", "map", "n_seeds",
                "Local replans__mean", "Local replans__std",
                "Throughput__mean", "Util.__mean", "Util.__saturated"}
    missing = required - set(rows[0].keys())
    assert not missing, f"csv missing columns: {missing}"


def test_saturated_cells_have_asterisk(tex_text):
    """Cells with mean utilization >= 0.95 (per the P10
    convention) must be marked with a trailing asterisk on the
    throughput cell.  Every horizon row in this dataset is
    arrival-saturated (utilization is exactly 1.0 by
    arithmetic), so EVERY throughput cell must carry the *."""
    body = tex_text.split(r"\begin{tabular}", 1)[1]
    data = re.search(r"\\midrule\s*(.+?)\s*\\bottomrule", body, re.DOTALL)
    assert data, "no data rows"
    headers = _tabular_headers(tex_text)
    thpt_idx = headers.index("Throughput")
    n_asterisked = 0
    n_total = 0
    for line in data.group(1).strip().splitlines():
        if r"\\" not in line:
            continue
        cells = line.replace(r"\\", "").split("&")
        if len(cells) <= thpt_idx:
            continue
        n_total += 1
        if "*" in cells[thpt_idx]:
            n_asterisked += 1
    assert n_total == 16, f"expected 16 data rows, got {n_total}"
    assert n_asterisked == 16, (
        f"only {n_asterisked}/{n_total} throughput cells are "
        f"asterisked; every horizon cell at |M|=100 is "
        f"arrival-saturated and must carry the * marker.  "
        f"Per `paper/sections/05_1_load_regime.md`, the marker "
        f"signals throughput in the saturated regime."
    )


def test_builder_round_trip_is_byte_stable(tmp_path):
    """Running the builder twice in a row produces byte-identical
    output.  A new commit that randomises seed order, dict order,
    or drops trailing whitespace would fire."""
    script = REPO_ROOT / "scripts" / "evaluation" / "build_table_horizon.py"
    out_tex = tmp_path / "a.tex"
    out_csv = tmp_path / "a.csv"
    for _ in range(2):
        rc = subprocess.run(
            [sys.executable, str(script),
             "--tex-out", str(out_tex),
             "--csv-out", str(out_csv),
             "--log-level", "WARNING"],
            cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=60,
        )
        assert rc.returncode == 0, rc.stderr
    # Compare against the committed file.
    expected_tex = TEX_PATH.read_bytes()
    expected_csv = CSV_PATH.read_bytes()
    assert out_tex.read_bytes() == expected_tex, (
        "horizon_tuning.tex regenerated content differs from the "
        "committed copy; either run the builder and commit the "
        "diff, or fix the builder to be deterministic."
    )
    assert out_csv.read_bytes() == expected_csv, (
        "horizon_tuning.csv regenerated content differs from the "
        "committed copy."
    )
