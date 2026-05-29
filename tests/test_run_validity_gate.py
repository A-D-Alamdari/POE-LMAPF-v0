"""
Run-validity gate tests for ``scripts.evaluation.run_paper_experiment``.

Covers the instrumentation that makes degenerate solver runs loud:

* The runner's per-row gate delegates to the standalone validator's
  strong predicate (Phase 2 prompt 5).  Invalid rows are siphoned to
  ``results_INVALID.csv`` and excluded from the main ``results.csv``
  -- they are NOT deleted.
* ``run_validity_summary.csv`` is written per (solver, map) cell and
  flags cells whose invalid fraction exceeds the limit.
* ``write_run_validity_summary`` returns ``(summary_rows,
  failing_cells, sweep_invalid_reasons)`` (Phase 2 prompt 5 added the
  reason Counter as the third element so the post-sweep log can
  surface budget-vs-deadlock-vs-schema breakdown).
* A healthy smoke slice writes the summary with all runs valid.

The pre-prompt-5 test ``test_row_is_valid_handles_string_and_missing``
pinned a contract the strong predicate intentionally inverts (legacy
row with no signal now FAILS missing-required-columns by design,
audit 08).  That test's intent is now covered by
``test_runner_predicate_matches_validator`` in
tests/test_max_invalid_fraction.py and has been removed here.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.run_paper_experiment import (  # noqa: E402
    DEFAULT_VALIDITY_THRESHOLD,
    _append_rows_split,
    _row_is_valid,
    _split_valid_invalid,
    write_run_validity_summary,
)


# Strong-predicate required columns at clean defaults (Phase 2 prompt 5).
# Fixtures stamp these onto every row so the partition / aggregation
# tests exercise the legitimate verdict paths, not the missing-cols
# precondition.  The pre-prompt-5 ``_mk_row`` only set ``run_valid`` +
# ``solver_fail_fraction``; under the strong predicate that row would
# trip missing-required-columns before any clause fires.
_STRONG_CLEAN = dict(
    status="ok", global_replans=100,
    solver_timeouts=0, solver_errors=0,
    deadlock_count=0, num_agents=100,
    throughput_utilization=0.5,
)


def _mk_row(run_id: str, solver: str, map_path: str, run_valid: bool,
            status: str = "ok") -> dict:
    """Build a synthetic CSV row.

    ``run_valid=False`` is realised by perturbing a clause-3 input
    (solver_errors above the 5 % gate) under a status=ok base, so the
    row's strong-predicate verdict matches the requested ``run_valid``.
    The ``run_valid`` field itself is still stamped for back-compat
    with any CSV reader that reads it back as text -- it is NOT what
    ``_row_is_valid`` consults under the strong predicate.
    """
    row = {
        "run_id": run_id,
        "experiment": "test",
        "applied_global_solver": solver,
        "global_solver": solver,
        "map_path": map_path,
        "seed": 0,
        "run_valid": run_valid,
    }
    row.update(_STRONG_CLEAN)
    row["status"] = status
    if not run_valid:
        # Trip clause 3 (solver-fail-fraction): 6/100 = 0.06 > 0.05.
        row["solver_errors"] = 6
        row["solver_fail_fraction"] = 0.06
    else:
        row["solver_fail_fraction"] = 0.0
    # Honor an explicit non-ok status as a clause-1 (crash) perturbation.
    if status != "ok":
        row["status"] = status
    return row


def test_split_valid_invalid_partitions_rows():
    rows = [
        _mk_row("a", "lacam3", "m1", True),
        _mk_row("b", "lacam3", "m1", False),
        _mk_row("c", "lacam3", "m2", True),
    ]
    valid, invalid = _split_valid_invalid(rows)
    assert [r["run_id"] for r in valid] == ["a", "c"]
    assert [r["run_id"] for r in invalid] == ["b"]


def test_append_rows_split_routes_to_separate_files(tmp_path: Path):
    main_path = tmp_path / "results.csv"
    invalid_path = tmp_path / "results_INVALID.csv"
    rows = [
        _mk_row("ok-1", "lacam3", "m1", True),
        _mk_row("bad-1", "lacam3", "m1", False),
        _mk_row("ok-2", "pibt2", "m1", True),
    ]
    _append_rows_split(main_path, invalid_path, rows)

    with main_path.open() as f:
        main_rows = list(csv.DictReader(f))
    with invalid_path.open() as f:
        bad_rows = list(csv.DictReader(f))

    assert {r["run_id"] for r in main_rows} == {"ok-1", "ok-2"}
    assert [r["run_id"] for r in bad_rows] == ["bad-1"]
    # Audit-trail columns must survive the round trip.
    assert "run_valid" in main_rows[0]
    assert "solver_fail_fraction" in main_rows[0]


def test_summary_flags_cells_over_limit(tmp_path: Path):
    main_path = tmp_path / "results.csv"
    invalid_path = tmp_path / "results_INVALID.csv"
    summary_path = tmp_path / "run_validity_summary.csv"

    # 5 runs on (lacam3, m1): 4 invalid (80%) -> exceeds 20% limit.
    # 5 runs on (pibt2,  m1): all valid -> ok.
    rows = (
        [_mk_row(f"a{i}", "lacam3", "m1", False) for i in range(4)]
        + [_mk_row("a4", "lacam3", "m1", True)]
        + [_mk_row(f"b{i}", "pibt2", "m1", True) for i in range(5)]
    )
    _append_rows_split(main_path, invalid_path, rows)
    summary_rows, failing, reasons = write_run_validity_summary(
        main_path, invalid_path, summary_path, cell_fraction_limit=0.20,
    )

    assert summary_path.exists()
    keys = {(r["global_solver"], r["map_path"]): r for r in summary_rows}
    bad = keys[("lacam3", "m1")]
    good = keys[("pibt2", "m1")]
    assert int(bad["invalid_runs"]) == 4
    assert int(bad["total_runs"]) == 5
    assert float(bad["invalid_fraction"]) == 0.8
    assert bad["cell_exceeds_limit"] is True
    assert int(good["invalid_runs"]) == 0
    assert good["cell_exceeds_limit"] is False
    assert failing == [("lacam3", "m1")]
    # Phase 2 prompt 5: the third return element is a reason Counter.
    # The 4 invalid rows here trip clause 3 (solver-fail-fraction).
    assert reasons["solver-fail-fraction"] == 4


def test_summary_all_valid_returns_empty_failing(tmp_path: Path):
    main_path = tmp_path / "results.csv"
    invalid_path = tmp_path / "results_INVALID.csv"
    summary_path = tmp_path / "run_validity_summary.csv"
    rows = [_mk_row(f"r{i}", "lacam3", "m1", True) for i in range(3)]
    _append_rows_split(main_path, invalid_path, rows)
    _, failing, reasons = write_run_validity_summary(
        main_path, invalid_path, summary_path, cell_fraction_limit=0.20,
    )
    assert not invalid_path.exists()  # nothing invalid -> file not created
    assert summary_path.exists()
    assert failing == []
    # Phase 2 prompt 5: clean sweep -> empty reason Counter.
    assert not reasons
    with summary_path.open() as f:
        rows_out = list(csv.DictReader(f))
    assert len(rows_out) == 1
    assert int(rows_out[0]["invalid_runs"]) == 0


def test_run_one_tags_validity_columns(tmp_path: Path):
    """End-to-end: a healthy smoke run lands in results.csv with
    run_valid=True, solver_fail_fraction=0.0, and the audit-trail
    columns surfaced by the metrics dataclass."""
    from scripts.evaluation.run_paper_experiment import (
        _append_rows_split,
        expand_manifest,
        run_one,
        write_run_validity_summary,
    )

    spec_path = REPO_ROOT / "configs" / "eval" / "paper" / "baseline_comparison.yaml"
    base_spec = yaml.safe_load(spec_path.read_text())
    # Trim to one method/density/map; 200 steps for speed.
    spec = {
        "name":  "validity_gate_smoke",
        "base":  dict(base_spec.get("base", {})),
        "groups": [],
        "seeds": [0],
    }
    spec["base"]["steps"] = 200
    for grp in base_spec["groups"]:
        sweep = grp.get("sweep", {})
        if any("random-64-64-10" in str(p) for p in sweep.get("map_path", [])):
            spec["groups"].append({
                "sweep": {
                    "method":     [sweep["method"][0]],
                    "map_path":   [next(p for p in sweep["map_path"]
                                        if "random-64-64-10" in str(p))],
                    "num_agents": [min(sweep.get("num_agents", [10]))],
                    "num_humans": [min(sweep.get("num_humans", [10]))],
                }
            })
            break

    rows = expand_manifest(spec)
    assert rows, "smoke spec expanded to zero runs"
    for r in rows:
        r["_validity_threshold"] = DEFAULT_VALIDITY_THRESHOLD

    recs = [run_one(r) for r in rows]
    for rec in recs:
        # Required audit-trail columns must all be present in the row.
        for k in (
            "global_replans", "solver_errors", "solver_timeouts",
            "solver_partial_returns", "solver_fallback_reuses",
            "solver_fail_fraction", "run_valid",
        ):
            assert k in rec, f"missing audit column: {k}"
        assert rec["status"] == "ok"
        assert rec["run_valid"] is True, rec
        assert float(rec["solver_fail_fraction"]) == 0.0

    main_path = tmp_path / "results.csv"
    invalid_path = tmp_path / "results_INVALID.csv"
    summary_path = tmp_path / "run_validity_summary.csv"
    _append_rows_split(main_path, invalid_path, recs)
    summary_rows, failing, _reasons = write_run_validity_summary(
        main_path, invalid_path, summary_path, cell_fraction_limit=0.20,
    )

    assert main_path.exists()
    assert not invalid_path.exists(), "invalid CSV must NOT be created when all runs valid"
    assert summary_path.exists()
    assert failing == []
    # Summary must report all-valid for the single (solver, map) cell.
    assert len(summary_rows) == 1
    assert int(summary_rows[0]["invalid_runs"]) == 0
    assert int(summary_rows[0]["valid_runs"]) == len(recs)


def test_invalid_runs_preserved_in_invalid_csv(tmp_path: Path):
    """Spec contract: do NOT delete invalid runs; keep them in
    ``*_INVALID.csv`` for debugging."""
    main_path = tmp_path / "results.csv"
    invalid_path = tmp_path / "results_INVALID.csv"
    rows = [
        _mk_row("bad-1", "lacam3", "m1", False),
        _mk_row("bad-2", "lacam3", "m1", False),
    ]
    _append_rows_split(main_path, invalid_path, rows)
    assert not main_path.exists()
    assert invalid_path.exists()
    with invalid_path.open() as f:
        preserved = list(csv.DictReader(f))
    assert {r["run_id"] for r in preserved} == {"bad-1", "bad-2"}
