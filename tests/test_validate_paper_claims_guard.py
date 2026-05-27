"""
Acceptance tests for the degenerate-run guard added to the paper-claim
and smoke validators (P2 follow-up).

The guard reads ``run_valid`` / ``solver_fail_fraction`` / ``global_replans``
on every input row and refuses to emit a Confirmed verdict when any
supporting row failed the check.  Both validators must:

* exit non-zero when any input row fails the guard,
* keep cleanly validating data that passes the guard,
* expose the per-row reasons in the report / GO-NO-GO output.
"""
from __future__ import annotations

import csv
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    DEFAULT_VALIDITY_THRESHOLD,
    ValidityReport,
    classify_row_validity,
    main as validate_paper_claims_main,
    partition_validity,
    run_validation,
)


# ---------------------------------------------------------------------------
# Classifier unit cases
# ---------------------------------------------------------------------------


def test_classifier_passes_healthy_row():
    """Healthy row -- non-degenerate solver, all P2 columns absent --
    returns ``None`` (i.e. valid).  This is the legacy-CSV path."""
    row = {"solver_errors": 0, "solver_timeouts": 0, "global_replans": 100}
    assert classify_row_validity(row, 0.05) is None


def test_classifier_trips_on_explicit_run_valid_false():
    reason = classify_row_validity({"run_valid": "False"}, 0.05)
    assert reason is not None and "run_valid" in reason


def test_classifier_trips_on_explicit_solver_fail_fraction():
    reason = classify_row_validity({"solver_fail_fraction": 0.5}, 0.05)
    assert reason is not None and "solver_fail_fraction=0.5" in reason


def test_classifier_trips_on_computed_solver_fail_fraction():
    """Legacy CSVs lack ``solver_fail_fraction`` but carry the raw
    counters; the classifier must compute the ratio and trip on it."""
    row = {"solver_errors": 100, "solver_timeouts": 0, "global_replans": 100}
    reason = classify_row_validity(row, 0.05)
    assert reason is not None
    assert "computed solver_fail_fraction=1.0000" in reason


def test_classifier_trips_on_zero_global_replans():
    reason = classify_row_validity({"global_replans": 0}, 0.05)
    assert reason is not None and "global_replans=0" in reason


def test_classifier_legacy_row_with_no_signal_passes():
    """A row with none of the validity columns present should not
    be classified as invalid -- we have no signal."""
    assert classify_row_validity({"throughput": 0.5}, 0.05) is None


def test_partition_validity_splits_and_preserves_order():
    rows: List[Dict[str, Any]] = [
        {"run_id": "ok1", "global_replans": 100, "solver_errors": 1},
        {"run_id": "bad1", "global_replans": 100, "solver_errors": 100},
        {"run_id": "ok2", "global_replans": 50, "solver_errors": 2},
        {"run_id": "bad2", "global_replans": 0},
    ]
    valid, invalid = partition_validity(rows, 0.05)
    assert [r["run_id"] for r in valid] == ["ok1", "ok2"]
    assert [r["run_id"] for r, _ in invalid] == ["bad1", "bad2"]
    assert all(reason for _, reason in invalid)


# ---------------------------------------------------------------------------
# End-to-end: validate_paper_claims main()
# ---------------------------------------------------------------------------


_HEALTHY_RUN = {
    "run_id": "abc", "experiment": "x",
    "method": "ours", "global_solver": "lacam3",
    "horizon": 20, "map_path": "data/maps/random-64-64-10.map",
    "map_stem": "random-64-64-10",
    "num_agents": 50, "num_humans": 20, "seed": 0,
    "throughput": 0.10, "status": "ok",
    # Validity columns
    "run_valid": True, "solver_fail_fraction": 0.0,
    "global_replans": 100, "solver_errors": 0, "solver_timeouts": 0,
    "wall_clock_s": 1.0, "error_msg": "",
}


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("run_id\n")
        return
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_claims_yaml(path: Path) -> None:
    spec = {
        "schema_version": 1,
        "claims": [
            {
                "section": "5.2",
                "claim_id": "smoke_throughput_floor",
                "paper_text": "Throughput is at least 0.05 on this slice.",
                "source": "solver_sensitivity",
                "metric": "throughput",
                "filter": {"map_stem": "random-64-64-10"},
                "aggregation": {"kind": "mean"},
                "expected": {"kind": "at_least", "value": 0.05},
                "favorable_direction": "higher",
            },
        ],
    }
    path.write_text(yaml.safe_dump(spec))


def _make_results_tree(root: Path, source: str, rows: List[Dict[str, Any]]) -> None:
    sub = root / source
    sub.mkdir(parents=True, exist_ok=True)
    _write_csv(sub / "results.csv", rows)


def test_clean_csv_runs_validator_with_exit_zero(tmp_path: Path):
    """Healthy input -- every row passes the guard -- gives a normal
    Confirmed verdict and the harness exits 0."""
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity", [_HEALTHY_RUN])
    claims_path = tmp_path / "claims.yaml"
    _write_claims_yaml(claims_path)
    out = tmp_path / "report.md"

    rc = validate_paper_claims_main([
        "--claims", str(claims_path),
        "--results-root", str(results_root),
        "--out", str(out),
        "--section", "5.2",
        "--log-level", "WARNING",
    ])
    assert rc == 0
    report = out.read_text()
    assert "**Invalid**: 0" in report
    assert "N=1" in report and "valid 1" in report and "invalid 0" in report
    # The Invalid header line is suppressed when there are no invalid rows.
    assert "## Invalid input rows" not in report


def test_solver_errors_100_csv_yields_invalid_and_exit_3(tmp_path: Path):
    """The acceptance scenario from the task spec: feeding the
    harness rows that look like the existing ``solver_errors_mean = 100``
    artifacts (per-run rows with solver_errors = global_replans) yields
    an Invalid verdict and exit code 3, NOT Confirmed."""
    bad_run = dict(_HEALTHY_RUN)
    bad_run.update({
        "run_id": "deg",
        "run_valid": False,
        "solver_fail_fraction": 1.0,
        "solver_errors": 100,
        "global_replans": 100,
    })
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity",
                       [_HEALTHY_RUN, bad_run])
    claims_path = tmp_path / "claims.yaml"
    _write_claims_yaml(claims_path)
    out = tmp_path / "report.md"

    rc = validate_paper_claims_main([
        "--claims", str(claims_path),
        "--results-root", str(results_root),
        "--out", str(out),
        "--section", "5.2",
        "--log-level", "WARNING",
    ])
    assert rc == 3, f"validator returned {rc}, expected 3 (Invalid exit code)"
    report = out.read_text()
    assert "## Invalid input rows" in report
    assert "**Invalid**: 1" in report
    # No Confirmed verdict for the claim whose supporting row was tainted.
    assert "## Confirmed (1)" not in report
    # Run id of the tainted row appears in the Invalid section.
    assert "deg" in report


def test_legacy_csv_without_validity_columns_is_caught_by_computed_fraction(tmp_path: Path):
    """A legacy CSV that predates ``run_valid`` / ``solver_fail_fraction``
    but still carries ``solver_errors`` + ``global_replans`` must
    trip the guard via the computed fraction."""
    legacy_bad = {
        "run_id": "legacy", "experiment": "x",
        "method": "ours", "global_solver": "lacam3",
        "horizon": 20, "map_path": "data/maps/random-64-64-10.map",
        "map_stem": "random-64-64-10",
        "num_agents": 50, "num_humans": 20, "seed": 0,
        "throughput": 0.10, "status": "ok",
        # NO run_valid / solver_fail_fraction columns
        "solver_errors": 50, "solver_timeouts": 50, "global_replans": 100,
        "wall_clock_s": 1.0, "error_msg": "",
    }
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity", [legacy_bad])
    claims_path = tmp_path / "claims.yaml"
    _write_claims_yaml(claims_path)
    out = tmp_path / "report.md"

    rc = validate_paper_claims_main([
        "--claims", str(claims_path),
        "--results-root", str(results_root),
        "--out", str(out),
        "--section", "5.2",
        "--log-level", "WARNING",
    ])
    assert rc == 3
    report = out.read_text()
    assert "computed solver_fail_fraction" in report


def test_invalid_row_outside_claim_filter_does_not_taint_other_claims(tmp_path: Path):
    """An invalid row that does not match a claim's filter should not
    block that claim's Confirmed verdict.  The harness still exits
    non-zero overall because invalid rows exist somewhere in the
    sweep, but per-claim verdicts are not falsely demoted."""
    # Healthy: map_stem=random-64-64-10 (matches the claim filter).
    # Invalid: map_stem=warehouse-10-20-10-2-2 (does NOT match).
    other_invalid = dict(_HEALTHY_RUN)
    other_invalid.update({
        "run_id": "warehouse_bad",
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "map_stem": "warehouse-10-20-10-2-2",
        "run_valid": False,
        "solver_fail_fraction": 0.99,
    })
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity",
                       [_HEALTHY_RUN, other_invalid])
    claims_path = tmp_path / "claims.yaml"
    _write_claims_yaml(claims_path)
    out = tmp_path / "report.md"

    rc = validate_paper_claims_main([
        "--claims", str(claims_path),
        "--results-root", str(results_root),
        "--out", str(out),
        "--section", "5.2",
        "--log-level", "WARNING",
    ])
    # Invalid rows exist -> exit non-zero overall.
    assert rc == 3
    report = out.read_text()
    # ... but the claim itself can still be evaluated (its filter
    # excludes the invalid row), so a non-Invalid verdict should
    # appear for this claim.
    assert "smoke_throughput_floor" in report
    # The Invalid section must NOT mention this claim as Invalid.
    invalid_block_start = report.find("## Invalid (")
    if invalid_block_start != -1:
        invalid_block_end = report.find("## ", invalid_block_start + 5)
        invalid_block = report[invalid_block_start:invalid_block_end]
        assert "smoke_throughput_floor" not in invalid_block


def test_top_line_summary_format(tmp_path: Path):
    """Spec: 'Add a top-line summary: N rows, M valid, K invalid'.
    Verify it appears in the markdown header."""
    bad = dict(_HEALTHY_RUN); bad["run_id"] = "b"
    bad["run_valid"] = False; bad["solver_fail_fraction"] = 1.0
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity",
                       [_HEALTHY_RUN, dict(_HEALTHY_RUN, run_id="g2"), bad])
    claims_path = tmp_path / "claims.yaml"
    _write_claims_yaml(claims_path)
    out = tmp_path / "report.md"

    validate_paper_claims_main([
        "--claims", str(claims_path),
        "--results-root", str(results_root),
        "--out", str(out),
        "--section", "5.2",
        "--log-level", "WARNING",
    ])
    report = out.read_text()
    assert "N=3" in report
    assert "valid 2" in report
    assert "invalid 1" in report
