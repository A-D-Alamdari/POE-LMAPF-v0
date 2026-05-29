"""
Integration tests for validate_paper_claims claims-mode runtime under the
strong validity predicate (resume-prompt-7).

History: this file was the P2-follow-up acceptance test for the lenient
classifier that parsed ``run_valid`` / explicit ``solver_fail_fraction``
fields and fell back to a computed fraction for legacy CSVs.
Resume-prompt-7 replaced that classifier with the five-clause strong
predicate of audit 09 + audit 11 + Decision 4c.  The six classifier-detail
unit tests that pinned the OLD predicate (``test_classifier_*`` and
``test_classifier_legacy_row_with_no_signal_passes``) tested behavior
that no longer exists -- the legacy "no signal => valid" path is now
"missing-required-columns => invalid" by design (audit 08).  Their
intent is covered by tests/test_validity_predicate.py, which pins the
new predicate clause by clause.

What remains here is the higher-level integration contract:

* ``partition_validity`` returns split-by-validity lists in input order
  (the new predicate, applied row by row, still produces the same
  partition semantics).
* The CLI exits 0 on a clean CSV, 3 on a CSV with any invalid row.
* The markdown report's Invalid section is correctly populated and the
  per-claim filter logic stays decoupled from sweep-level invalidity.

Every healthy row in this file now carries the seven strong-predicate
required columns (``status``, ``global_replans``, ``solver_timeouts``,
``solver_errors``, ``deadlock_count``, ``num_agents``,
``throughput_utilization``) at clean defaults so the integration tests
exercise the legitimate verdict paths, not the missing-columns
precondition.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    classify_row_validity,
    main as validate_paper_claims_main,
    partition_validity,
)


# Strong-predicate clean defaults stamped onto every fixture row by
# ``_with_strong_defaults``.  Mirrors the helper in test_paper_claims.py.
_STRONG_DEFAULTS = {
    "status": "ok",
    "global_replans": 100,
    "solver_timeouts": 0,
    "solver_errors": 0,
    "deadlock_count": 0,
    "num_agents": 50,
    "throughput_utilization": 0.5,
}


def _with_strong_defaults(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for r in rows:
        for k, v in _STRONG_DEFAULTS.items():
            r.setdefault(k, v)
    return rows


# ---------------------------------------------------------------------------
# partition_validity contract: split + preserve order
# ---------------------------------------------------------------------------
def test_partition_validity_splits_and_preserves_order():
    """Two clean rows interleaved with two clause-failing rows.  The
    valid + invalid lists must split in input order with no reordering.

    Replaces the legacy version of this test (which used
    ``run_valid=False`` / oversized ``solver_errors`` as the failure
    signal).  Under the strong predicate the perturbations that make a
    row invalid are different (clause 1: status, clause 2:
    global_replans, etc.); the partition semantics are unchanged.
    """
    rows: List[Dict[str, Any]] = _with_strong_defaults([
        {"run_id": "ok1"},
        # Clause 1: crash.
        {"run_id": "bad1", "status": "error"},
        {"run_id": "ok2"},
        # Clause 2: no-global-replan.
        {"run_id": "bad2", "global_replans": 0},
    ])
    valid, invalid = partition_validity(rows, 0.05)
    assert [r["run_id"] for r in valid] == ["ok1", "ok2"]
    assert [r["run_id"] for r, _ in invalid] == ["bad1", "bad2"]
    assert all(reason for _, reason in invalid)


def test_classify_row_validity_legacy_threshold_kwarg_is_noop():
    """The legacy ``threshold`` keyword is preserved for back-compat
    (claims-mode CLI used to expose ``--validity-threshold``) but is a
    no-op under the strong predicate -- clause 3's threshold is locked
    at 0.05 per Decision 4c.

    A row whose solver-fail fraction is 0.06 trips clause 3 regardless
    of whether the caller passes the default 0.05 or a permissive 0.50;
    the locked threshold ignores the kwarg.
    """
    row = dict(_STRONG_DEFAULTS, solver_errors=6)  # 6/100 = 0.06
    assert classify_row_validity(row, 0.05) is not None
    # Passing 0.50 would have allowed it under the old behavior; under
    # the locked threshold it is still invalid.
    assert classify_row_validity(row, 0.50) is not None


# ---------------------------------------------------------------------------
# End-to-end: validate_paper_claims main() (claims mode)
# ---------------------------------------------------------------------------
_HEALTHY_RUN = {
    "run_id": "abc", "experiment": "x",
    "method": "ours", "global_solver": "lacam3",
    "horizon": 20, "map_path": "data/maps/random-64-64-10.map",
    "map_stem": "random-64-64-10",
    "num_agents": 50, "num_humans": 20, "seed": 0,
    "throughput": 0.10,
    # Strong-predicate required columns at clean defaults.
    "status": "ok", "global_replans": 100,
    "solver_errors": 0, "solver_timeouts": 0,
    "deadlock_count": 0, "throughput_utilization": 0.5,
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
    """Every row passes the strong predicate -> a normal Confirmed
    verdict and exit code 0."""
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


def test_solver_errors_csv_yields_invalid_and_exit_3(tmp_path: Path):
    """A row whose solver-fail fraction trips clause 3 yields an
    Invalid verdict (not Confirmed) and exit code 3.

    Replaces the legacy ``solver_errors_mean=100`` scenario from the
    original P2 acceptance test; the perturbation is now ``solver_errors
    > 5%`` (the locked clause-3 threshold)."""
    bad_run = dict(_HEALTHY_RUN)
    bad_run.update({
        "run_id": "deg",
        # 6/100 = 0.06 > 0.05 (clause 3 fires).
        "solver_errors": 6,
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
    # The named reason in the report is the canonical clause-3 name.
    assert "solver-fail-fraction" in report


def test_legacy_csv_without_required_columns_is_caught_by_missing_cols(tmp_path: Path):
    """A legacy CSV that predates the strong predicate's required column
    set (e.g. missing ``deadlock_count`` and ``throughput_utilization``)
    trips the missing-required-columns precondition on every row.

    Replaces the legacy "caught by computed solver_fail_fraction" test:
    the strong predicate's precondition fires first, and the named
    reason in the Invalid section is now ``missing-required-columns``."""
    legacy_row = {
        "run_id": "legacy", "experiment": "x",
        "method": "ours", "global_solver": "lacam3",
        "horizon": 20, "map_path": "data/maps/random-64-64-10.map",
        "map_stem": "random-64-64-10",
        "num_agents": 50, "num_humans": 20, "seed": 0,
        "throughput": 0.10, "status": "ok",
        # Has the legacy counters but NOT the new required columns
        # (deadlock_count, throughput_utilization).
        "solver_errors": 50, "solver_timeouts": 50, "global_replans": 100,
        "wall_clock_s": 1.0, "error_msg": "",
    }
    results_root = tmp_path / "logs"
    _make_results_tree(results_root, "solver_sensitivity", [legacy_row])
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
    assert "missing-required-columns" in report


def test_invalid_row_outside_claim_filter_does_not_taint_other_claims(tmp_path: Path):
    """An invalid row that does not match a claim's filter should not
    block that claim's Confirmed verdict.  The harness still exits 3
    overall (invalid rows exist somewhere in the sweep), but per-claim
    verdicts are not falsely demoted."""
    # Healthy: map_stem=random-64-64-10 (matches the claim filter).
    # Invalid: map_stem=warehouse-10-20-10-2-2 (does NOT match), tripped
    # by clause 3.
    other_invalid = dict(_HEALTHY_RUN)
    other_invalid.update({
        "run_id": "warehouse_bad",
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "map_stem": "warehouse-10-20-10-2-2",
        # 99/100 = 0.99 > 0.05 (clause 3).
        "solver_errors": 99,
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
    # excludes the invalid row), so a non-Invalid verdict appears for
    # this claim.
    assert "smoke_throughput_floor" in report
    invalid_block_start = report.find("## Invalid (")
    if invalid_block_start != -1:
        invalid_block_end = report.find("## ", invalid_block_start + 5)
        invalid_block = report[invalid_block_start:invalid_block_end]
        assert "smoke_throughput_floor" not in invalid_block


def test_top_line_summary_format(tmp_path: Path):
    """The markdown header carries 'N=<rows> (valid <m>, invalid <k>)'.
    Three rows in, one tripped by clause 1 (crash): expect N=3, valid 2,
    invalid 1."""
    bad = dict(_HEALTHY_RUN); bad["run_id"] = "b"; bad["status"] = "error"
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
