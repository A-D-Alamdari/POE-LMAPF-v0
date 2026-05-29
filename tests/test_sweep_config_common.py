"""Tests for scripts/tuning/_sweep_config_common.py shared sweep knobs.

Resume-prompt Phase 2 prompt 2: locks the 30s solver budget and pins the
strong-predicate threshold constants to the validator's (single source of
truth).  The task brief said "extend the existing file"; the file did not
exist in the tree, so it is created here.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "tuning"))

import _sweep_config_common as common  # noqa: E402
from scripts.evaluation import validate_paper_claims as validator  # noqa: E402


def test_default_solver_timeout_is_30s():
    """The locked Phase 3 solver budget is 30.0s (Decision 1a, audit 09
    §5).  Locks both the module constant and the value the budget-YAML
    helper renders."""
    assert common.SOLVER_BUDGET_S == 30.0
    rendered = common.base_solver_budget_yaml()
    assert "solver_timeout_s: 30.0" in rendered, (
        f"budget helper did not render 30.0:\n{rendered}"
    )


def test_validity_thresholds_match_validator():
    """The threshold constants the YAML generators document must equal
    the ones the validator enforces -- single source of truth (they are
    bound to the validator's constants by import, so this is an identity
    check that also guards against an accidental literal divergence)."""
    assert (common.SOLVER_FAIL_FRACTION_THRESHOLD
            == validator.SOLVER_FAIL_THRESHOLD == 0.05)
    assert (common.DEADLOCK_FRACTION_THRESHOLD
            == validator.DEADLOCK_FRACTION_THRESHOLD == 0.10)
    assert (common.UTILIZATION_SATURATION_THRESHOLD
            == validator.SATURATION_UTILIZATION_THRESHOLD == 0.95)


def test_validity_guard_comment_block_documents_strong_predicate():
    """The validity-guard YAML comment must name all five clauses of the
    strong predicate (audit 09 + Decision 4c, wired in Phase 2 prompt 1),
    so a reviewer reading any sweep YAML sees the exact gate the
    validator enforces."""
    rendered = common.base_validity_guard_yaml()
    for clause_name in (
        "crash",
        "no-global-replan",
        "solver-fail-fraction",
        "deadlock-fraction",
        "saturation-hiding-deadlock",
    ):
        assert clause_name in rendered, (
            f"validity-guard comment block missing clause '{clause_name}':\n"
            f"{rendered}"
        )
    # The strict gate value and the required-columns failure mode are
    # part of the documented contract too.
    assert "max_invalid_fraction: 0.0" in rendered
    assert "missing-required-columns" in rendered
