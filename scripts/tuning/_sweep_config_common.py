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

from typing import Iterable, Optional


# -- Calibration evidence -----------------------------------------------------
#
# Per-instance solve-time distribution observed in P3 across the two
# calibration runs (``logs/calibration/raw_measurements_v2.csv`` for
# §5.4 cells, ``raw_measurements_v2_5_5.csv`` for §5.5 cells; 107
# successful invocations per solver, ``solver_wall_ms`` column).
# These are NOT model-predicted budgets -- they are the actual
# wall-clock numbers the calibration cohort produced under the
# 10 s budget we ship.  Reviewers should verify them against the
# raw CSVs; the comment block in each YAML carries the same table.
#
# solver           n     p50      p90      p95      p99      max     # ms
# cbsh2          107       6       61      126      764     1500
# lacam3         107   10012    10021    10024    10030    10031     # anytime; uses full budget
# lacam_official 107       2        7        9       17      146
# lns2           107       3        7        9       12       14
# pbs            107       6       22       31       53      167
# pibt2          105       5       15       18       26       27
#
# Reading: every non-anytime solver clears p99 in under one second on
# the calibration cohort.  lacam3 (the anytime backend) deliberately
# uses the full budget as its quality knob.  Setting the per-call
# budget below ~1 s would clip cbsh2's p99 tail; setting it above
# 10 s lets the anytime backend spend more time per call without
# changing completion outcomes for the others.  10 s sits at the
# right inflection point and is also the value the §5.1 paper
# defaults table uses (``docs/experimental_setup.md`` row "Per-call
# solver budget").
SOLVER_BUDGET_S: float = 10.0


def base_solver_budget_yaml(
        budget_s: float = SOLVER_BUDGET_S,
        indent: str = "  ",
) -> str:
    """Return the ``solver_timeout_s: <budget>`` YAML line plus its
    P3-justification comment block.  Caller splices into the
    ``base:`` block.  ``indent`` is the per-line indent used by the
    surrounding YAML (two spaces by default to match the ``base:``
    children)."""
    return (
        f"{indent}# Per-call solver budget — calibrated against the P3\n"
        f"{indent}# cohort (107 successful invocations per solver on\n"
        f"{indent}# ``logs/calibration/raw_measurements_v2*.csv``):\n"
        f"{indent}#\n"
        f"{indent}#   solver           p50   p90   p95   p99    max     # ms\n"
        f"{indent}#   cbsh2              6    61   126   764   1500\n"
        f"{indent}#   lacam3         10012 10021 10024 10030  10031     # anytime; uses full budget\n"
        f"{indent}#   lacam_official     2     7     9    17    146\n"
        f"{indent}#   lns2               3     7     9    12     14\n"
        f"{indent}#   pbs                6    22    31    53    167\n"
        f"{indent}#   pibt2              5    15    18    26     27\n"
        f"{indent}#\n"
        f"{indent}# Every non-anytime solver clears p99 in under one\n"
        f"{indent}# second; lacam3 (anytime) deliberately uses the full\n"
        f"{indent}# budget as its quality knob.  10 s is the §5.1 paper\n"
        f"{indent}# default (docs/experimental_setup.md) and the right\n"
        f"{indent}# trade-off here.\n"
        f"{indent}solver_timeout_s: {float(budget_s)}\n"
    )


def base_validity_guard_yaml(
        max_invalid_fraction: float = 0.0,
        indent: str = "  ",
) -> str:
    """Return the ``max_invalid_fraction: <value>`` YAML line plus
    its P2-tie-in comment block.  ``max_invalid_fraction: 0.0`` is
    the strict default: any run that fails the per-row degenerate-run
    guard (run_valid / solver_fail_fraction / global_replans -- see
    ``scripts/evaluation/validate_paper_claims.py::classify_row_validity``)
    fails the sweep.  Sweeps that legitimately tolerate some loss
    (e.g. stress tests of the resolver fallback path) can raise it
    explicitly with a justification comment."""
    return (
        f"{indent}# Degenerate-run guard — P2 / P7 follow-up.\n"
        f"{indent}# A row is INVALID iff any of:\n"
        f"{indent}#   * run_valid == False,\n"
        f"{indent}#   * solver_fail_fraction > 0.05,\n"
        f"{indent}#   * global_replans == 0 (Tier-1 never ran).\n"
        f"{indent}# This key documents the per-sweep tolerance; the\n"
        f"{indent}# validator (validate_paper_claims.py) exits non-zero\n"
        f"{indent}# if the actual invalid-row fraction exceeds it.\n"
        f"{indent}# 0.0 = strict (zero degenerate runs tolerated).\n"
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
