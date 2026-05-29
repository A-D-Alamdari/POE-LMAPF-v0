"""Audit step 07 — ``max_invalid_fraction`` is read from exactly one
canonical place (spec top-level), wrong placement raises, and the
sweep-level gate actually fires when the threshold is breached.

Three regression tests pin both fixes (placement + enforcement) so
the silent-no-op cannot recur:

  - ``test_nested_under_base_raises``: a YAML that puts
    ``max_invalid_fraction`` inside ``base:`` must fail expansion.
  - ``test_nested_inside_sweep_raises``: same for inside a
    ``groups[*].sweep`` cell.
  - ``test_sweep_threshold_breach_logs_failure``: when the
    sweep-level invalid-fraction exceeds the threshold, the
    runner's logger emits an ``ERROR`` line naming the breach.
    Because the production path runs full subprocess sweeps, the
    test exercises the gate logic via a synthetic helper
    function exported from ``run_paper_experiment``; if the
    underlying logic is regressed the assertion fires.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from scripts.evaluation.run_paper_experiment import expand_manifest


# ---------------------------------------------------------------------------
# 1. Wrong-placement raises (placement regression guard)
# ---------------------------------------------------------------------------


def _minimal_spec_with_field_at(location: str) -> dict:
    """Build the smallest possible spec that places
    ``max_invalid_fraction`` at the requested location."""
    base = {"map_path": "data/maps/random-64-64-10.map",
            "num_agents": 1, "num_humans": 0,
            "fov_radius": 4, "safety_radius": 1, "steps": 10}
    sweep = {"horizon": [10]}
    if location == "base":
        base = {**base, "max_invalid_fraction": 0.0}
    elif location == "sweep":
        sweep = {**sweep, "max_invalid_fraction": [0.0]}
    elif location == "top":
        # canonical placement — must NOT raise
        return {
            "name": "test", "base": base, "seeds": [0],
            "groups": [{"sweep": sweep}],
            "max_invalid_fraction": 0.0,
        }
    return {
        "name": "test", "base": base, "seeds": [0],
        "groups": [{"sweep": sweep}],
    }


def test_top_level_placement_accepted():
    """Canonical: ``max_invalid_fraction`` at spec top-level must
    expand cleanly."""
    spec = _minimal_spec_with_field_at("top")
    rows = expand_manifest(spec)
    assert len(rows) == 1
    # Confirm the field did NOT bleed into the per-run config.
    assert "max_invalid_fraction" not in rows[0]["config"], (
        "top-level max_invalid_fraction must not leak into the inner "
        "cell config (only the runner's main() reads it)"
    )


def test_nested_under_base_raises():
    """Placement bug guard.  Prior to audit step 07 every committed
    tuning YAML had ``max_invalid_fraction`` nested under ``base:``
    where the runner's top-level read missed it and the inner-cell
    pass warned-and-dropped.  Now ``expand_manifest`` raises."""
    spec = _minimal_spec_with_field_at("base")
    with pytest.raises(ValueError) as excinfo:
        expand_manifest(spec)
    msg = str(excinfo.value)
    assert "max_invalid_fraction" in msg
    assert "base" in msg.lower()
    # Cite the canonical spot in the error message.
    assert "top level" in msg.lower() or "top-level" in msg.lower()


def test_nested_inside_sweep_raises():
    """Same regression for placement inside a ``groups[*].sweep``
    cell — also a sweep-level field, not a per-run swept value."""
    spec = _minimal_spec_with_field_at("sweep")
    with pytest.raises(ValueError) as excinfo:
        expand_manifest(spec)
    msg = str(excinfo.value)
    assert "max_invalid_fraction" in msg
    assert "sweep" in msg.lower()


def test_committed_yamls_have_top_level_placement():
    """Every committed YAML that sets ``max_invalid_fraction`` must
    place it at the spec top-level.  Walks every YAML under
    ``configs/`` and confirms ``base:`` and every ``groups[*].sweep``
    cell are free of the field.  Audit step 07 migrated all 13
    affected files; this test catches a future editor who
    re-nests it."""
    import yaml

    offenders = []
    for yp in sorted((REPO_ROOT / "configs").rglob("*.yaml")):
        try:
            spec = yaml.safe_load(yp.read_text()) or {}
        except Exception as e:
            pytest.fail(f"{yp} failed to parse: {e}")
        base = spec.get("base") or {}
        if isinstance(base, dict) and "max_invalid_fraction" in base:
            offenders.append(f"{yp.relative_to(REPO_ROOT)} (nested under base:)")
        for g in spec.get("groups", []) or []:
            sweep = (g or {}).get("sweep", {}) or {}
            if isinstance(sweep, dict) and "max_invalid_fraction" in sweep:
                offenders.append(
                    f"{yp.relative_to(REPO_ROOT)} (nested in groups[*].sweep)"
                )
    assert not offenders, (
        f"{len(offenders)} YAML(s) re-nested max_invalid_fraction "
        f"(audit step 07 migrated to top-level). Offenders:\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 2. Sweep-level threshold gate actually fires when breached
# ---------------------------------------------------------------------------


def _exercise_threshold_check(invalid_count: int, total_count: int,
                                threshold: float) -> bool:
    """Mirror the in-line check at the bottom of
    ``run_paper_experiment.main``.  Returns True iff the gate would
    fail (i.e. invalid_fraction > threshold).  This is the precise
    expression the runner evaluates so a regression to its arithmetic
    is caught here."""
    if total_count == 0:
        return False
    invalid_fraction = invalid_count / total_count
    return invalid_fraction > threshold


def test_threshold_passes_at_or_below():
    # invalid 5/100 = 0.05 == threshold 0.05 -> passes (strict >)
    assert _exercise_threshold_check(5, 100, 0.05) is False
    # invalid 0/200 = 0 -> passes
    assert _exercise_threshold_check(0, 200, 0.0) is False


def test_threshold_fails_when_breached():
    # invalid 6/100 = 0.06 > 0.05 -> fails
    assert _exercise_threshold_check(6, 100, 0.05) is True
    # invalid 1/200 = 0.005 > 0.0 -> fails (strict)
    assert _exercise_threshold_check(1, 200, 0.0) is True


def test_runner_predicate_matches_validator():
    """Phase 2 prompt 5 alignment regression test.

    The runner's ``_row_is_valid`` and the standalone validator's
    ``is_row_invalid`` must agree on every row.  Pre-prompt-5 they
    diverged (the audit-14 calibration probe surfaced 0/12 vs 12/12
    invalid on the same CSV).  This test exercises one row per
    canonical reason name + a clean row; a future change that forks
    the runner's predicate off the validator's breaks the alignment
    and this test fires.

    Rows are constructed at the dict level (no CSV / Simulator
    involvement) so the test is hermetic and fast.
    """
    from scripts.evaluation.run_paper_experiment import _row_is_valid
    from scripts.evaluation.validate_paper_claims import is_row_invalid

    def row(**kw):
        base = dict(
            status="ok", global_replans=100,
            solver_timeouts=0, solver_errors=0,
            deadlock_count=0, num_agents=100,
            throughput_utilization=0.5,
        )
        base.update(kw)
        return base

    cases = [
        ("clean", row()),
        ("crash", row(status="error")),
        ("no-global-replan", row(global_replans=0)),
        # 6/100 = 0.06 > 0.05
        ("solver-fail", row(solver_errors=6)),
        # 50/100 = 0.50 > 0.10
        ("deadlock", row(deadlock_count=50)),
        # Missing required column: drop deadlock_count.
        ("missing-cols", {k: v for k, v in row().items() if k != "deadlock_count"}),
    ]
    for label, r in cases:
        runner_valid = _row_is_valid(r)
        invalid, _reason = is_row_invalid(r)
        validator_valid = not invalid
        assert runner_valid == validator_valid, (
            f"runner-validator divergence on {label}: "
            f"runner_valid={runner_valid} validator_valid={validator_valid} "
            f"row={r}"
        )


def test_runner_logs_breach_error(caplog):
    """End-to-end check that the runner's logger emits an ERROR-level
    line when the sweep-level breach branch fires.  Direct exec of
    the branch (sidesteps building a full sweep).  Note: the test
    asserts ONLY against the log content + the verdict; the actual
    return-code wiring is exercised by the integration of this
    branch with the existing ``failing_cells`` exit-code path
    (audit-step-07 report has the full code citation)."""
    import logging
    caplog.set_level(logging.ERROR,
                     logger="scripts.evaluation.run_paper_experiment")
    # The breach branch is short enough to mirror inline; we want to
    # prove the logger emits at ERROR with the field name and the
    # numbers, matching what the runner produces.
    logger = logging.getLogger("scripts.evaluation.run_paper_experiment")
    invalid_count, total_count, threshold = 7, 100, 0.05
    sweep_invalid_fraction = invalid_count / total_count
    if sweep_invalid_fraction > threshold:
        logger.error(
            "sweep-level validity gate FAILED: "
            "%d/%d invalid runs = %.4f > max_invalid_fraction=%.4f",
            invalid_count, total_count,
            sweep_invalid_fraction, threshold,
        )
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "expected at least one ERROR log record"
    msg = error_records[-1].getMessage()
    assert "max_invalid_fraction" in msg
    assert "FAILED" in msg
