"""Shared helpers for the auto-generated sweep YAML producers.

These functions emit the standard ``base:`` block annotations the
§5.4 scaling sweeps + the §5.5 baselines + the §5.6 / §5.7 ablations
all share: the P3-justified ``solver_timeout_s`` comment block, the
``max_invalid_fraction`` guard knob that surfaces P2's degenerate-run
filter in the sweep config itself, and a one-line solver-list
provenance pointer to P0's preflight.

The helpers exist so the dozen-or-so generators in this directory
stay in lockstep without copy-paste drift; touching a budget or
threshold here regenerates every YAML coherently.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Optional

# Single source of truth for the strong-predicate thresholds: import the
# locked constants the validator enforces (Phase 2 prompt 1) so the YAML
# generators and the validator can never drift.  The validator lives under
# scripts/evaluation; ensure the repo root is importable regardless of how
# a generator was invoked (generators only put scripts/tuning on the path).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    SOLVER_FAIL_THRESHOLD as _V_SOLVER_FAIL,
    DEADLOCK_FRACTION_THRESHOLD as _V_DEADLOCK,
    SATURATION_UTILIZATION_THRESHOLD as _V_SATURATION,
)

# Re-exported under the task-specified names; bound to the validator's
# constants so ``test_validity_thresholds_match_validator`` is satisfied by
# identity, not by a duplicated literal that could rot.
SOLVER_FAIL_FRACTION_THRESHOLD = _V_SOLVER_FAIL          # validator clause 3
DEADLOCK_FRACTION_THRESHOLD = _V_DEADLOCK                # validator clauses 4 + 5
UTILIZATION_SATURATION_THRESHOLD = _V_SATURATION         # validator clause 5


# -- Solver budget ------------------------------------------------------------
#
# Solver budget: 30.0s (Phase 2 prompt 2, audit 09 §5 + Decision 1a).
# The previous 10s budget was calibrated against the P3 cohort
# (lacam_official p99 = 17ms) which did not include the operating
# points the §5 sweeps actually use.  Audit 11 confirmed 14/14 sweeps
# would have failed max_invalid_fraction=0.0 on the solver-fail clause
# alone at the 10s budget.  The 30s budget is the locked Phase 3 value;
# the calibration probe (Phase 2 prompt 3) verifies it produces
# solver-fail < 5% at the worst-case operating point before B7 launches.
SOLVER_BUDGET_S: float = 30.0


def base_solver_budget_yaml(
        budget_s: float = SOLVER_BUDGET_S,
        indent: str = "  ",
) -> str:
    """Return just the ``solver_timeout_s: <budget>`` YAML line.

    The per-YAML calibration comment was removed in Phase 2 prompt 3
    (it had become stale next to the locked 30s budget and was always
    redundant).  The canonical calibration rationale lives in the
    module-level comment block at the top of this file.  ``indent`` is
    the per-line indent used by the surrounding YAML (two spaces by
    default to match the ``base:`` children)."""
    return f"{indent}solver_timeout_s: {float(budget_s)}\n"


def base_validity_guard_yaml(
        max_invalid_fraction: float = 0.0,
        indent: str = "",
) -> str:
    """Return the ``max_invalid_fraction: <value>`` YAML line plus its
    strong-predicate comment block.  The block documents the exact
    five-clause predicate the validator now enforces (Phase 2 prompt 1,
    wired into ``scripts/evaluation/validate_paper_claims.py::
    is_row_invalid``); audit 09 §5 / audit 05 BUG #1 was that the old
    three-clause comment described a predicate that was never enforced.

    ``max_invalid_fraction: 0.0`` is the strict default: any single row
    that fails the predicate fails the sweep.

    Audit step 07 moved this field from inside ``base:`` (indent
    "  ") to the SPEC TOP LEVEL (indent "") so the runner's
    top-level reader at ``run_paper_experiment.main`` actually
    consumes it.  Callers splice the result between the closing
    of the ``base:`` block and the ``seeds:`` declaration.  See
    reports/audit/07_max_invalid_fraction.md.
    """
    return (
        f"{indent}# max_invalid_fraction sweep gate (audit 09, audit 11,\n"
        f"{indent}# Decision 4c, Phase 2 prompt 1). A row is INVALID iff any of:\n"
        f"{indent}#   1. status != 'ok'                                  (crash)\n"
        f"{indent}#   2. global_replans == 0                             (no-global-replan)\n"
        f"{indent}#   3. (solver_timeouts + solver_errors) / max(1, global_replans) > 0.05\n"
        f"{indent}#                                                      (solver-fail-fraction)\n"
        f"{indent}#   4. deadlock_count / num_agents > 0.10              (deadlock-fraction)\n"
        f"{indent}#   5. throughput_utilization >= 0.95 AND\n"
        f"{indent}#      deadlock_count / num_agents > 0.10              (saturation-hiding-deadlock)\n"
        f"{indent}# Required columns: status, global_replans, solver_timeouts,\n"
        f"{indent}# solver_errors, deadlock_count, num_agents,\n"
        f"{indent}# throughput_utilization. Rows missing any of these fail with\n"
        f"{indent}# reason 'missing-required-columns'.\n"
        f"{indent}# A sweep is REJECTED if its invalid fraction exceeds\n"
        f"{indent}# max_invalid_fraction (strict-greater-than comparison).\n"
        f"{indent}max_invalid_fraction: {float(max_invalid_fraction)}\n"
    )


def solver_provenance_comment(
        solvers: Iterable[str],
        note: Optional[str] = None,
) -> str:
    """Return a comment block listing the solver set used by this
    sweep and pointing at P0's preflight as the host-availability
    gate.  Placed in the file header so a reviewer can audit the
    solver list at a glance."""
    sorted_solvers = sorted(set(solvers))
    body = (
        "# Solver list (must all pass P0 preflight on the runner host\n"
        "# before the sweep launches):\n"
        f"#   {', '.join(sorted_solvers)}\n"
        "#\n"
        "# Verify with:\n"
        "#   python scripts/preflight_solvers.py --solvers "
        f"{','.join(sorted_solvers)}\n"
    )
    if note:
        body += f"# {note}\n"
    return body
