"""Unit-level negative acceptance tests for ``scripts/regression_smoke.py``.

The full smoke (32 cells + a fallback-reuse cell) runs in ~7 min on
the dev host and is too slow for pytest.  These tests instead verify
that each of the five named ``SmokeFailure`` checks fires on hand-
constructed offending input, so the failure messages stay anchored to
P1-P6 even if the underlying smoke parameters change.

The acceptance criterion from the P8 task spec is:

    "python scripts/regression_smoke.py exits 0 on a healthy tree and
     non-zero, with a specific named failure, when any of P1-P6 is
     reverted."

This file pins the *named failure* half of that contract.  The
exit-0 half is exercised by running ``scripts/regression_smoke.py``
directly (e.g. before launching a paper sweep, per the procedure in
``docs/rerun_protocol.md``); we do not duplicate that here.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from regression_smoke import (  # noqa: E402
    SmokeFailure,
    SmokeRow,
    _EXEMPTION_SENTINEL,
    _assert_fallback_reuse,
    _assert_no_errors,
    _assert_p1_solver_fail_fraction_zero,
    _assert_p3_solvers_discriminate,
    _assert_p5_agent_attributable_possible,
    _assert_p6_attribution_invariant,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ok_row(**overrides):
    metrics = {
        "throughput": 0.10,
        "safety_violations": 0,
        "safety_violation_agent_ticks": 0,
        "safety_violation_events": 0,
        "violations_agent_attributable": 0,
        "violations_exogenous_attributable": 0,
        "solver_errors": 0, "solver_timeouts": 0,
        "solver_fail_fraction": 0.0, "run_valid": True,
        "global_replans": 5,
        "solver_fallback_reuses": 0,
    }
    metrics.update(overrides)
    return SmokeRow(
        map_path="data/maps/warehouse-10-20-10-2-2.map",
        num_agents=25, seed=0, solver="lacam_official",
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Per-check named-failure smoke
# ---------------------------------------------------------------------------


def test_p1_named_failure_on_nonzero_fail_fraction():
    row = _ok_row(solver_fail_fraction=0.2, solver_errors=2, run_valid=False)
    with pytest.raises(SmokeFailure) as exc:
        _assert_p1_solver_fail_fraction_zero([row])
    assert exc.value.check == "P1_SOLVER_FAIL_FRACTION_ZERO"
    assert "solver_fail_fraction" in exc.value.message


def test_p1_named_failure_on_run_valid_false():
    row = _ok_row(run_valid=False)
    with pytest.raises(SmokeFailure) as exc:
        _assert_p1_solver_fail_fraction_zero([row])
    assert exc.value.check == "P1_SOLVER_FAIL_FRACTION_ZERO"


def test_p3_named_failure_on_bitwise_identical_throughputs():
    """Every solver returning the SAME throughput is the §2
    pathology -- the global tier is disabled and every cell collapses
    to the same all-WAIT trajectory."""
    rows = [
        SmokeRow(map_path="m", num_agents=25, seed=0, solver=s,
                 metrics={"throughput": 0.5,
                          "safety_violations": 0,
                          "violations_agent_attributable": 0,
                          "violations_exogenous_attributable": 0,
                          "solver_fail_fraction": 0.0, "run_valid": True})
        for s in ("lacam_official", "lacam3", "lns2", "pibt2")
    ]
    with pytest.raises(SmokeFailure) as exc:
        _assert_p3_solvers_discriminate(rows)
    assert exc.value.check == "P3_SOLVERS_DISCRIMINATE"


def test_p3_passes_when_at_least_one_triple_discriminates():
    """A single triple where 2+ solvers produce different throughputs
    is enough to pass P3 even if other triples are degenerate."""
    rows = [
        SmokeRow(map_path="m", num_agents=25, seed=0, solver="A",
                 metrics={"throughput": 0.5}),
        SmokeRow(map_path="m", num_agents=25, seed=0, solver="B",
                 metrics={"throughput": 0.6}),
    ]
    _assert_p3_solvers_discriminate(rows)  # must not raise


def test_p6_named_failure_when_attribution_doesnt_sum():
    row = _ok_row(safety_violations=5,
                  violations_agent_attributable=1,
                  violations_exogenous_attributable=2)  # 1 + 2 != 5
    with pytest.raises(SmokeFailure) as exc:
        _assert_p6_attribution_invariant([row])
    assert exc.value.check == "P6_ATTRIBUTION_INVARIANT"


def test_p6_passes_on_balanced_attribution():
    row = _ok_row(safety_violations=3,
                  violations_agent_attributable=1,
                  violations_exogenous_attributable=2)
    _assert_p6_attribution_invariant([row])


def test_p5_passes_with_nonzero_agent_attributable():
    rows = [_ok_row(violations_agent_attributable=2)]
    _assert_p5_agent_attributable_possible(
        rows, REPO_ROOT / "docs" / "rerun_protocol.md",
    )


def test_p5_passes_zero_when_protocol_doc_carries_exemption(tmp_path: Path):
    rows = [_ok_row(violations_agent_attributable=0)]
    doc = tmp_path / "rerun_protocol.md"
    doc.write_text(f"header\n\n{_EXEMPTION_SENTINEL}\n\nbody")
    _assert_p5_agent_attributable_possible(rows, doc)


def test_p5_named_failure_when_exemption_sentence_missing(tmp_path: Path):
    rows = [_ok_row(violations_agent_attributable=0)]
    doc = tmp_path / "rerun_protocol.md"
    doc.write_text("a doc that does not carry the canonical sentence")
    with pytest.raises(SmokeFailure) as exc:
        _assert_p5_agent_attributable_possible(rows, doc)
    assert exc.value.check == "P5_AGENT_ATTRIBUTABLE_POSSIBLE"
    assert "exemption" in exc.value.message.lower()


def test_p5_named_failure_when_doc_missing(tmp_path: Path):
    rows = [_ok_row(violations_agent_attributable=0)]
    missing = tmp_path / "no_such_doc.md"
    with pytest.raises(SmokeFailure) as exc:
        _assert_p5_agent_attributable_possible(rows, missing)
    assert exc.value.check == "P5_AGENT_ATTRIBUTABLE_POSSIBLE"


def test_fallback_named_failure_when_no_error_counted():
    row = _ok_row(solver_errors=0, solver_fallback_reuses=0)
    with pytest.raises(SmokeFailure) as exc:
        _assert_fallback_reuse([row])
    assert exc.value.check == "FALLBACK_REUSE_INCREMENTS"
    assert "solver_errors=0" in exc.value.message


def test_fallback_named_failure_when_no_reuse_recorded():
    """Error was counted but the rolling-horizon planner did not
    re-anchor -- catches a regression where the planner stops
    re-anchoring on solver error."""
    row = _ok_row(solver_errors=1, solver_fallback_reuses=0)
    with pytest.raises(SmokeFailure) as exc:
        _assert_fallback_reuse([row])
    assert exc.value.check == "FALLBACK_REUSE_INCREMENTS"
    assert "fallback_reuses=0" in exc.value.message


def test_fallback_passes_when_both_counters_increment():
    row = _ok_row(solver_errors=1, solver_fallback_reuses=1)
    _assert_fallback_reuse([row])


def test_no_errors_propagates_run_exception():
    """A SmokeRow whose ``error`` is populated short-circuits all
    property checks: we cannot reason about metrics if the cell
    raised before producing any."""
    row = SmokeRow(
        map_path="m", num_agents=25, seed=0, solver="x",
        error="ValueError: simulated",
    )
    with pytest.raises(SmokeFailure) as exc:
        _assert_no_errors([row])
    assert exc.value.check == "RUN_EXECUTION"
    assert "simulated" in exc.value.message


# ---------------------------------------------------------------------------
# Matrix-shape regression
# ---------------------------------------------------------------------------


def test_matrix_constants_match_p8_spec():
    """The task spec pins the matrix shape (1 warehouse + 1 random
    map, num_agents {25, 100}, seeds {0, 1}, 4 §5.4 solvers).  This
    test guards against an accidental change that would silently
    shrink the smoke's coverage."""
    from regression_smoke import (
        SMOKE_AGENT_COUNTS,
        SMOKE_MAPS,
        SMOKE_SEEDS,
        SMOKE_SOLVERS,
    )
    assert sorted(SMOKE_AGENT_COUNTS) == [25, 100]
    assert sorted(SMOKE_SEEDS) == [0, 1]
    # Two maps: one warehouse + one random.
    assert len(SMOKE_MAPS) == 2
    stems = [Path(m).stem for m in SMOKE_MAPS]
    assert any("warehouse" in s for s in stems), stems
    assert any("random" in s for s in stems), stems
    # §5.4 solver list.
    assert set(SMOKE_SOLVERS) == {"lacam_official", "lacam3", "lns2", "pibt2"}
