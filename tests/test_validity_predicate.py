"""Resume-prompt-7: strong-predicate validator tests.

Pins the five-clause strong validity predicate from
``reports/audit/09_strong_validity_predicate.md`` + Decision 4c +
audit 11, plus the missing-required-columns precondition.  Also
covers the per-sweep aggregation in :func:`validate_sweep`, the
manifest CLI exit-3 path, and audit 08's prediction that no committed
legacy CSV can pass the new schema.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    INVALID_REASONS,
    REQUIRED_COLUMNS,
    SweepValidityReport,
    is_row_invalid,
    validate_sweep,
)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def _clean_row() -> Dict[str, Any]:
    """Row that passes every clause -- the baseline for clause-specific
    perturbations below."""
    return {
        "status": "ok",
        "global_replans": 100,
        "solver_timeouts": 0,
        "solver_errors": 0,
        "deadlock_count": 0,
        "num_agents": 100,
        "throughput_utilization": 0.5,
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ===========================================================================
# is_row_invalid -- clause-by-clause
# ===========================================================================
def test_is_row_invalid_valid_row():
    """A clean row (status=ok, solver-fail=0, deadlock=0/100, util=0.5)
    satisfies every clause and is reported valid with empty reason."""
    row = _clean_row()
    # Sanity: solver-fail = (0+0)/max(1,100) = 0; deadlock-fraction = 0/100.
    invalid, reason = is_row_invalid(row)
    assert invalid is False
    assert reason == ""


def test_is_row_invalid_clauses_in_order():
    """Construct synthetic rows that fail each clause in turn and verify
    the FIRST failing clause names the row's reason.

    Clauses 1-4 each get a dedicated row that fails ONLY that clause.
    Clause 5 (saturation-hiding-deadlock) is numerically subsumed by
    clause 4 -- any row failing 5 also fails 4 -- so it cannot fire in
    isolation; the order-of-clauses test for the 4-vs-5 ordering lives
    in test_is_row_invalid_saturated_with_deadlock below.

    Also covers the "first failing clause wins" rule by constructing a
    row that fails clauses 3 AND 4 simultaneously: the reason names
    clause 3 (more upstream).
    """
    # Clause 1: crash.
    r1 = _clean_row(); r1["status"] = "error"
    invalid, reason = is_row_invalid(r1)
    assert invalid and reason == "crash", reason

    # Clause 2: no-global-replan.
    r2 = _clean_row(); r2["global_replans"] = 0
    invalid, reason = is_row_invalid(r2)
    assert invalid and reason == "no-global-replan", reason

    # Clause 3: solver-fail-fraction = 6 / 100 = 0.06 > 0.05.
    r3 = _clean_row(); r3["solver_errors"] = 6
    invalid, reason = is_row_invalid(r3)
    assert invalid and reason == "solver-fail-fraction", reason

    # Clause 4: deadlock-fraction = 15 / 100 = 0.15 > 0.10.
    r4 = _clean_row(); r4["deadlock_count"] = 15
    invalid, reason = is_row_invalid(r4)
    assert invalid and reason == "deadlock-fraction", reason

    # First-failing-clause rule: solver-fail (clause 3) AND deadlock
    # (clause 4) both hold; reason must name clause 3 (upstream).
    r34 = _clean_row(); r34["solver_errors"] = 6; r34["deadlock_count"] = 15
    invalid, reason = is_row_invalid(r34)
    assert invalid and reason == "solver-fail-fraction", (
        f"first-failing-clause rule violated: reason={reason} "
        "(should be solver-fail-fraction, not deadlock-fraction)"
    )


def test_is_row_invalid_saturated_with_deadlock():
    """utilization=0.97 AND deadlock=15/100=0.15: both clause 4 AND
    clause 5 fire on this row.  The strong predicate names the
    upstream clause (clause 4 = deadlock-fraction), not clause 5.

    Mutation C (reorder clause 5 before clause 4) would make the reason
    flip to ``saturation-hiding-deadlock`` -- this test is the pin that
    detects that mutation."""
    row = _clean_row()
    row["throughput_utilization"] = 0.97
    row["deadlock_count"] = 15  # 15/100 = 0.15 > 0.10
    invalid, reason = is_row_invalid(row)
    assert invalid is True
    assert reason == "deadlock-fraction", (
        f"clause 4 must be named when both 4 and 5 fire; got reason={reason!r}"
    )


def test_is_row_invalid_saturated_without_deadlock():
    """utilization=0.97 (saturated) but deadlock=2/100=0.02 (below 10%).
    Neither clause 4 nor clause 5 fires; the row is valid."""
    row = _clean_row()
    row["throughput_utilization"] = 0.97
    row["deadlock_count"] = 2
    invalid, reason = is_row_invalid(row)
    assert invalid is False, f"row should be valid; got reason={reason!r}"
    assert reason == ""


def test_is_row_invalid_missing_columns():
    """A row missing any required column trips the precondition before
    any clause is evaluated.  Reason: ``missing-required-columns``."""
    row = _clean_row()
    del row["deadlock_count"]  # legacy schema -- no deadlock_count
    invalid, reason = is_row_invalid(row)
    assert invalid is True
    assert reason == "missing-required-columns", reason

    # An empty-string value is also "missing".
    row2 = _clean_row(); row2["throughput_utilization"] = ""
    invalid, reason = is_row_invalid(row2)
    assert invalid is True
    assert reason == "missing-required-columns"


# ===========================================================================
# validate_sweep -- per-sweep aggregation
# ===========================================================================
def test_validate_sweep_passes_clean_data(tmp_path: Path):
    """100 clean rows, threshold 5%: passed=True, invalid_fraction=0."""
    rows = [_clean_row() for _ in range(100)]
    csv_path = tmp_path / "clean.csv"
    _write_csv(csv_path, rows)
    r = validate_sweep(csv_path, max_invalid_fraction=0.05)
    assert r.passed is True
    assert r.n_rows == 100
    assert r.n_invalid == 0
    assert r.invalid_fraction == 0.0
    assert r.threshold == 0.05
    assert r.reasons == {}


def test_validate_sweep_fails_dirty_data(tmp_path: Path):
    """30% of rows fail clause 3, threshold 5%: passed=False,
    invalid_fraction=0.30, reasons['solver-fail-fraction']=30."""
    rows = [_clean_row() for _ in range(100)]
    for r in rows[:30]:
        r["solver_errors"] = 6  # 6/100 = 0.06 > 0.05
    csv_path = tmp_path / "dirty.csv"
    _write_csv(csv_path, rows)
    r = validate_sweep(csv_path, max_invalid_fraction=0.05)
    assert r.passed is False
    assert r.n_invalid == 30
    assert r.invalid_fraction == pytest.approx(0.30)
    assert r.reasons["solver-fail-fraction"] == 30


def test_validate_sweep_threshold_strict_zero(tmp_path: Path):
    """max_invalid_fraction=0.0: a single invalid row fails the sweep
    (the contract every committed sweep YAML declares -- audit 07).
    """
    rows = [_clean_row() for _ in range(100)]
    rows[0]["status"] = "error"  # exactly one invalid row
    csv_path = tmp_path / "one_bad.csv"
    _write_csv(csv_path, rows)
    r = validate_sweep(csv_path, max_invalid_fraction=0.0)
    assert r.passed is False
    assert r.n_invalid == 1
    assert r.invalid_fraction == pytest.approx(0.01)
    assert r.reasons["crash"] == 1


def test_legacy_csv_universally_fails():
    """Audit 08 / Decision 4c prediction: NO committed legacy CSV has
    all seven required columns simultaneously, so the strong predicate
    flags every row in a representative legacy CSV with reason
    ``missing-required-columns``.

    Picks ``logs/paper/baseline_comparison_v2/results.csv`` (the
    closest legacy CSV: 6/7 required columns, missing only
    ``throughput_utilization``).  Skips cleanly if the CSV isn't on
    disk in this checkout."""
    legacy = REPO_ROOT / "logs" / "paper" / "baseline_comparison_v2" / "results.csv"
    if not legacy.exists():
        pytest.skip(f"legacy CSV not present in checkout: {legacy}")
    # Loose threshold so the .passed verdict isn't what's under test --
    # the load-bearing checks are (a) every row is invalid and (b) the
    # named reason is missing-required-columns on every row.
    r = validate_sweep(legacy, max_invalid_fraction=1.0)
    assert r.n_rows > 0, "legacy CSV must have rows"
    assert r.n_invalid == r.n_rows, (
        f"legacy CSV expected to be 100% invalid under the strong "
        f"predicate (audit 08); got {r.n_invalid}/{r.n_rows}"
    )
    assert r.reasons.get("missing-required-columns") == r.n_rows

    # At any realistic threshold (anything < 1.0) the sweep fails:
    # invalid_fraction=1.0 cannot stay <= a threshold below 1.0.
    r_strict = validate_sweep(legacy, max_invalid_fraction=0.0)
    assert r_strict.passed is False


# ===========================================================================
# Manifest CLI -- exit code 3 on sweep failure
# ===========================================================================
def test_cli_exits_3_on_sweep_failure(tmp_path: Path):
    """Spawn the CLI against a manifest pointing at a dirty CSV.  The
    sweep fails its declared max_invalid_fraction, so the validator
    exits 3 (audit 07 reserved code for the validity gate)."""
    # Dirty CSV: 100 rows, 30 fail clause 3.
    rows = [_clean_row() for _ in range(100)]
    for r in rows[:30]:
        r["solver_errors"] = 6
    csv_path = tmp_path / "dirty.csv"
    _write_csv(csv_path, rows)

    manifest = {
        "sweeps": [
            {"name": "dirty_sweep", "csv": str(csv_path), "max_invalid_fraction": 0.05},
        ],
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest))

    script = REPO_ROOT / "scripts" / "evaluation" / "validate_paper_claims.py"
    result = subprocess.run(
        [sys.executable, str(script), "--manifest", str(manifest_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 3, (
        f"expected exit code 3 on sweep failure; got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    # validity_report.json must be next to the manifest.
    report_json = manifest_path.parent / "validity_report.json"
    assert report_json.exists(), "validity_report.json not written"
    report = json.loads(report_json.read_text())
    assert report["overall_passed"] is False
    assert report["n_failed_sweeps"] == 1
    sweep = report["sweeps"]["dirty_sweep"]
    assert sweep["n_invalid"] == 30
    assert sweep["passed"] is False
    assert sweep["reasons"]["solver-fail-fraction"] == 30

    # Stderr summary should name the failing reason.
    assert "dirty_sweep" in result.stderr
    assert "FAIL" in result.stderr
    assert "solver-fail-fraction" in result.stderr
