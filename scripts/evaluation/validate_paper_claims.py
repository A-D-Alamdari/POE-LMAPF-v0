#!/usr/bin/env python3
"""
Paper numerical-claim validator + strong-predicate sweep validator.

Two entry points share this module:

1. **Claims mode** (legacy): ``--claims <yaml> --results-root <dir>``.
   Reads a registry of paper claims, pulls the corresponding
   ``results.csv`` from a sweep directory, applies the encoded filter /
   aggregation, and compares against the expected value.  Writes a
   Markdown report grouped by verdict (``Confirmed`` / ``Refuted`` /
   ``Now stronger`` / ``Now weaker`` / ``Skipped`` / ``Invalid``) plus a
   side-by-side LaTeX diff for Tables 1 and 2.  The user reads the
   report and edits the paper accordingly; this tool does **not**
   modify the YAML registry or the paper text.

2. **Manifest mode** (resume-prompt-7): ``--manifest <yaml>``.
   Applies the strong validity predicate (audit 09 + audit 11 +
   Decision 4c) row-by-row to every sweep listed in the manifest,
   produces a per-sweep ``SweepValidityReport``, writes
   ``validity_report.json`` next to the manifest, and exits 3 if any
   sweep's invalid fraction exceeds its declared
   ``max_invalid_fraction``.

Strong validity predicate
-------------------------
A CSV row is INVALID iff any of:

   1. ``status != 'ok'``                            -- reason ``crash``
   2. ``global_replans == 0``                       -- reason ``no-global-replan``
   3. ``solver_fail_fraction > 0.05`` where
      ``solver_fail_fraction =
        (solver_timeouts + solver_errors) / max(1, global_replans)``
                                                    -- reason ``solver-fail-fraction``
   4. ``deadlock_count / num_agents > 0.10``        -- reason ``deadlock-fraction``
   5. ``throughput_utilization >= 0.95`` AND
      ``deadlock_count / num_agents > 0.10``        -- reason ``saturation-hiding-deadlock``

A precondition runs before clauses 1-5: if any of the seven required
columns (``status``, ``global_replans``, ``solver_timeouts``,
``solver_errors``, ``deadlock_count``, ``num_agents``,
``throughput_utilization``) is absent or empty, the row is invalid by
reason ``missing-required-columns`` and no other clause is evaluated.

Reasons ordered by upstream-ness (the predicate names the first clause
that fires; clause 5 is fully subsumed by clause 4 numerically and is
named only when checked in isolation, e.g. by a mutation test):

   - ``crash``                       (clause 1)
   - ``no-global-replan``            (clause 2)
   - ``solver-fail-fraction``        (clause 3)
   - ``deadlock-fraction``           (clause 4)
   - ``saturation-hiding-deadlock``  (clause 5)
   - ``missing-required-columns``    (precondition)

A sweep is REJECTED iff its row-level invalid fraction exceeds the
``max_invalid_fraction`` declared in its manifest entry.

Manifest YAML schema
--------------------
::

    sweeps:
      - name: horizon_replan_full
        csv:  logs/tuning/horizon_replan_full/results.csv
        max_invalid_fraction: 0.0
      - name: fov_safety_sweep
        csv:  logs/tuning/fov_safety_sweep/results.csv
        max_invalid_fraction: 0.0

``validity_report.json`` schema
-------------------------------
::

    {
      "sweeps": {
        "<sweep_name>": {
          "n_rows": int,
          "n_invalid": int,
          "invalid_fraction": float,
          "threshold": float,
          "passed": bool,
          "reasons": {"<reason_name>": int, ...}
        },
        ...
      },
      "overall_passed": bool,
      "n_failed_sweeps": int
    }

The validator complements -- it does not replace -- the run-launch
gate in ``run_paper_experiment.py`` (audit 07).  The runner enforces
per-row validity at sweep launch time; this validator re-applies the
predicate post-hoc on the produced CSV and gates whether any sweep is
fit to feed a §5 table.

Citations: ``reports/audit/09_strong_validity_predicate.md`` (full
five-clause derivation), ``reports/audit/11_solver_fail_hardened.md``
(threshold sensitivity), Decision 4c (subsumption of clause 5 by 4).

Usage::

    # Claims mode
    python scripts/evaluation/validate_paper_claims.py \\
        --claims        docs/PAPER_NUMERICAL_CLAIMS.yaml \\
        --results-root  logs/paper \\
        --out           claim_validation.md \\
        --tables-out    claim_validation_tables.tex \\
        --section       all

    # Manifest mode (resume-prompt-7)
    python scripts/evaluation/validate_paper_claims.py \\
        --manifest      sweeps.yaml
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

logger = logging.getLogger("paper_claims")


REQUIRED_CLAIM_FIELDS = (
    "section", "claim_id", "paper_text", "source", "metric",
    "aggregation", "favorable_direction",
)
ALLOWED_SECTIONS = {"5.2", "5.3", "5.4", "5.5"}
ALLOWED_DIRECTIONS = {"higher", "lower", "neither"}

# Strong validity predicate (audit 09 + audit 11 + Decision 4c) -- LOCKED.
# Do NOT silently revise these thresholds; see the module docstring and
# audit 11 for the threshold-sensitivity analysis.
SOLVER_FAIL_THRESHOLD = 0.05
DEADLOCK_FRACTION_THRESHOLD = 0.10
SATURATION_UTILIZATION_THRESHOLD = 0.95

# Required columns for the strong predicate; absence ⇒ ``missing-required-columns``.
REQUIRED_COLUMNS = (
    "status",
    "global_replans",
    "solver_timeouts",
    "solver_errors",
    "deadlock_count",
    "num_agents",
    "throughput_utilization",
)

# Canonical reason names emitted by ``is_row_invalid``.  Listed in the
# upstream-ness order the predicate uses when several clauses are eligible
# (the predicate returns the FIRST clause that fires).  ``saturation-
# hiding-deadlock`` is in the set for diagnostic completeness; numerically
# it is subsumed by ``deadlock-fraction`` and therefore never named at
# runtime when both apply.
INVALID_REASONS = (
    "crash",
    "no-global-replan",
    "solver-fail-fraction",
    "deadlock-fraction",
    "saturation-hiding-deadlock",
    "missing-required-columns",
)

# Back-compat alias.  The legacy CLI flag ``--validity-threshold`` used to
# parameterise clause 3; under Decision 4c the threshold is locked at 0.05
# and the flag is preserved only for back-compat (no-op + DeprecationWarning).
DEFAULT_VALIDITY_THRESHOLD = SOLVER_FAIL_THRESHOLD


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def _coerce(value: str) -> Any:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def load_results(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append({k: _coerce(v) for k, v in raw.items()})
    return rows


def _missing(row: Dict[str, Any], col: str) -> bool:
    """A column is 'missing' if its key is absent, or its value is None or ''."""
    if col not in row:
        return True
    v = row[col]
    return v is None or v == ""


def is_row_invalid(row: Dict[str, Any]) -> Tuple[bool, str]:
    """Apply the strong validity predicate to a single CSV row.

    Returns ``(is_invalid, reason)``.  ``reason`` is the canonical
    name of the first clause that fires (one of :data:`INVALID_REASONS`)
    or ``""`` if the row is valid.

    Clauses are checked in upstream-ness order so the reason names the
    most upstream failure mode.  The 'missing-required-columns'
    precondition runs before clauses 1-5; if any required column is
    absent or empty the row is invalid by that reason and no other
    clause is evaluated.  Clause 5 (saturation-hiding-deadlock) is
    fully subsumed by clause 4 (deadlock-fraction); it is named only
    when checked in isolation (e.g. by a mutation test).
    """
    # Precondition.
    for col in REQUIRED_COLUMNS:
        if _missing(row, col):
            return True, "missing-required-columns"

    # Clause 1: crash.
    if str(row["status"]) != "ok":
        return True, "crash"

    # Clause 2: no global replan (Tier-1 never ran).
    try:
        gr = int(float(row["global_replans"]))
    except (TypeError, ValueError):
        return True, "missing-required-columns"
    if gr == 0:
        return True, "no-global-replan"

    # Clause 3: solver-fail fraction.
    try:
        st = int(float(row["solver_timeouts"]))
        se = int(float(row["solver_errors"]))
    except (TypeError, ValueError):
        return True, "missing-required-columns"
    sf = (st + se) / float(max(1, gr))
    if sf > SOLVER_FAIL_THRESHOLD:
        return True, "solver-fail-fraction"

    # Clause 4: deadlock fraction.
    try:
        dl = int(float(row["deadlock_count"]))
        n = int(float(row["num_agents"]))
    except (TypeError, ValueError):
        return True, "missing-required-columns"
    dl_frac = dl / float(max(1, n))
    if dl_frac > DEADLOCK_FRACTION_THRESHOLD:
        return True, "deadlock-fraction"

    # Clause 5: saturation-hiding-deadlock (subsumed by clause 4 in
    # practice; reachable only in isolation, kept for diagnostic naming).
    try:
        util = float(row["throughput_utilization"])
    except (TypeError, ValueError):
        return True, "missing-required-columns"
    if util >= SATURATION_UTILIZATION_THRESHOLD and dl_frac > DEADLOCK_FRACTION_THRESHOLD:
        return True, "saturation-hiding-deadlock"

    return False, ""


def classify_row_validity(
    row: Dict[str, Any], threshold: float = SOLVER_FAIL_THRESHOLD,
) -> Optional[str]:
    """Legacy claims-driven adapter around :func:`is_row_invalid`.

    Returns ``None`` if the row passes the strong predicate, otherwise a
    short reason string suitable for the Invalid section of the claim
    report.  The reason is the canonical predicate name plus, where it
    helps the reader, the offending numbers.  The ``threshold`` keyword
    is now a no-op (clause 3's threshold is locked at 0.05 per
    Decision 4c); it is retained for back-compat with the legacy CLI.
    """
    invalid, reason = is_row_invalid(row)
    if not invalid:
        return None
    if reason == "missing-required-columns":
        missing = [c for c in REQUIRED_COLUMNS if _missing(row, c)]
        return f"missing-required-columns: {missing}"
    if reason == "crash":
        return f"crash (status={row.get('status')!r})"
    if reason == "no-global-replan":
        return "no-global-replan (global_replans == 0, Tier-1 never ran)"
    if reason == "solver-fail-fraction":
        gr = int(float(row["global_replans"]))
        st = int(float(row["solver_timeouts"]))
        se = int(float(row["solver_errors"]))
        sf = (st + se) / float(max(1, gr))
        return (
            f"solver-fail-fraction={sf:.4f} > {SOLVER_FAIL_THRESHOLD} "
            f"(solver_errors={se}, solver_timeouts={st}, global_replans={gr})"
        )
    if reason == "deadlock-fraction":
        dl = int(float(row["deadlock_count"]))
        n = int(float(row["num_agents"]))
        return (
            f"deadlock-fraction={dl}/{n}={dl / max(1, n):.4f} "
            f"> {DEADLOCK_FRACTION_THRESHOLD}"
        )
    if reason == "saturation-hiding-deadlock":
        util = float(row["throughput_utilization"])
        dl = int(float(row["deadlock_count"]))
        n = int(float(row["num_agents"]))
        return (
            f"saturation-hiding-deadlock (utilization={util:.3f} >= "
            f"{SATURATION_UTILIZATION_THRESHOLD} AND deadlock={dl}/{n})"
        )
    return reason


def partition_validity(
    rows: Sequence[Dict[str, Any]], threshold: float,
) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """Split rows into (valid, [(invalid_row, reason), ...])."""
    valid: List[Dict[str, Any]] = []
    invalid: List[Tuple[Dict[str, Any], str]] = []
    for r in rows:
        reason = classify_row_validity(r, threshold)
        if reason is None:
            valid.append(r)
        else:
            invalid.append((r, reason))
    return valid, invalid


def annotate_map_stem(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add a ``map_stem`` column to every row (basename minus
    ``.map``) so claim filters can reference the bare stem rather
    than the full path."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        new = dict(r)
        mp = r.get("map_path")
        if isinstance(mp, str):
            base = mp.rsplit("/", 1)[-1]
            if base.endswith(".map"):
                base = base[:-4]
            new["map_stem"] = base
        out.append(new)
    return out


# ---------------------------------------------------------------------------
# Filter language
# ---------------------------------------------------------------------------


def _row_passes(row: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    """A filter spec is a dict whose keys are either bare field names
    (equality) or ``<field>_<op>`` where op ∈ {gte, lte, gt, lt, in, neq}.
    """
    if not spec:
        return True
    for key, want in spec.items():
        if key.endswith("_gte"):
            field = key[:-4]
            v = row.get(field)
            if v is None or float(v) < float(want):
                return False
        elif key.endswith("_lte"):
            field = key[:-4]
            v = row.get(field)
            if v is None or float(v) > float(want):
                return False
        elif key.endswith("_gt"):
            field = key[:-3]
            v = row.get(field)
            if v is None or float(v) <= float(want):
                return False
        elif key.endswith("_lt"):
            field = key[:-3]
            v = row.get(field)
            if v is None or float(v) >= float(want):
                return False
        elif key.endswith("_in"):
            field = key[:-3]
            v = row.get(field)
            if v not in want:
                return False
        elif key.endswith("_neq"):
            field = key[:-4]
            if row.get(field) == want:
                return False
        else:
            if row.get(key) != want:
                return False
    return True


def filter_rows(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [r for r in rows if _row_passes(r, spec)]


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _values(rows: Sequence[Dict[str, Any]], metric: str) -> List[float]:
    out: List[float] = []
    for r in rows:
        v = r.get(metric)
        if v is None:
            continue
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _group_means(rows: Sequence[Dict[str, Any]], group_field: str,
                 metric: str) -> Dict[Any, float]:
    bucket: Dict[Any, List[float]] = {}
    for r in rows:
        v = r.get(metric)
        if v is None:
            continue
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            continue
        bucket.setdefault(r.get(group_field), []).append(v_f)
    return {k: sum(vs) / len(vs) for k, vs in bucket.items() if vs}


def _linear_r_squared(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return float("nan")
    r = sxy / math.sqrt(sxx * syy)
    return r * r


def aggregate(rows: Sequence[Dict[str, Any]], claim: Dict[str, Any]) -> Any:
    metric = claim["metric"]
    agg = claim["aggregation"]
    kind = agg["kind"]
    base_filter: Dict[str, Any] = claim.get("filter", {}) or {}
    filtered = filter_rows(rows, base_filter)

    if kind == "mean":
        vs = _values(filtered, metric)
        return sum(vs) / len(vs) if vs else float("nan")
    if kind == "max":
        vs = _values(filtered, metric)
        return max(vs) if vs else float("nan")
    if kind == "min":
        vs = _values(filtered, metric)
        return min(vs) if vs else float("nan")
    if kind == "sum":
        vs = _values(filtered, metric)
        return sum(vs) if vs else float("nan")
    if kind == "count":
        return float(len(filtered))

    if kind == "max_minus_min_over_field":
        means = _group_means(filtered, agg["field"], metric)
        if not means:
            return float("nan")
        return max(means.values()) - min(means.values())

    if kind == "ratio_of_filters":
        num_rows = filter_rows(filtered, agg["numerator_filter"])
        den_rows = filter_rows(filtered, agg["denominator_filter"])
        num_v = _values(num_rows, metric)
        den_v = _values(den_rows, metric)
        if not num_v or not den_v:
            return float("nan")
        num_mean = sum(num_v) / len(num_v)
        den_mean = sum(den_v) / len(den_v)
        if den_mean == 0:
            return float("inf") if num_mean > 0 else float("nan")
        return num_mean / den_mean

    if kind == "linear_r_squared":
        x_field = agg["x_field"]
        groupby = agg.get("groupby") or []
        # Group rows by groupby keys; within each group fit a line and
        # collect the R^2 values.  Return the mean R^2.
        groups: Dict[Tuple[Any, ...], List[Tuple[float, float]]] = {}
        for r in filtered:
            v = r.get(metric)
            x = r.get(x_field)
            if v is None or x is None:
                continue
            try:
                v_f, x_f = float(v), float(x)
            except (TypeError, ValueError):
                continue
            key = tuple(r.get(g) for g in groupby)
            groups.setdefault(key, []).append((x_f, v_f))
        r2s: List[float] = []
        for pairs in groups.values():
            if len(pairs) < 3:
                continue
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            r2 = _linear_r_squared(xs, ys)
            if not math.isnan(r2):
                r2s.append(r2)
        return sum(r2s) / len(r2s) if r2s else float("nan")

    if kind == "ratio_between_methods":
        method_field = agg["method_field"]
        sub = filter_rows(filtered, agg.get("filter", {}) or {})
        num_v = _values(filter_rows(sub, {method_field: agg["numerator"]}), metric)
        den_v = _values(filter_rows(sub, {method_field: agg["denominator"]}), metric)
        if not num_v or not den_v:
            return float("nan")
        num_mean = sum(num_v) / len(num_v)
        den_mean = sum(den_v) / len(den_v)
        if den_mean == 0:
            return float("inf") if num_mean > 0 else float("nan")
        return num_mean / den_mean

    if kind == "relative_diff_between_methods":
        method_field = agg["method_field"]
        sub = filter_rows(filtered, agg.get("filter", {}) or {})
        ref_v = _values(filter_rows(sub, {method_field: agg["reference"]}), metric)
        oth_v = _values(filter_rows(sub, {method_field: agg["other"]}), metric)
        if not ref_v or not oth_v:
            return float("nan")
        ref_mean = sum(ref_v) / len(ref_v)
        oth_mean = sum(oth_v) / len(oth_v)
        if ref_mean == 0:
            return float("nan")
        return (oth_mean - ref_mean) / abs(ref_mean)

    if kind == "max_relative_diff_between_methods":
        method_field = agg["method_field"]
        sub = filter_rows(filtered, agg.get("filter", {}) or {})
        # Group by every other field but the method field; compute
        # |ref - other| / ref per group; take max.
        ref = agg["reference"]
        oth = agg["other"]
        groups: Dict[Tuple[Any, ...], Dict[str, List[float]]] = {}
        # Keys = all distinguishing fields beyond method_field present in the rows.
        key_fields: List[str] = []
        for r in sub:
            for k in r.keys():
                if k in (method_field, "seed", "run_id", "experiment", "status",
                         "wall_clock_s", "error_msg") or k.startswith("_"):
                    continue
                if k not in key_fields:
                    key_fields.append(k)
        # Actually use only the simple distinguishing fields a user
        # commonly cares about.  Simplify: group by every non-metric
        # numerical field present in the filter spec.
        key_fields = sorted(agg.get("filter", {}).keys()) or [
            "map_stem", "num_agents", "num_humans", "horizon",
        ]
        for r in sub:
            v = r.get(metric)
            if v is None:
                continue
            try:
                v_f = float(v)
            except (TypeError, ValueError):
                continue
            key = tuple(r.get(k) for k in key_fields)
            method = r.get(method_field)
            if method == ref:
                groups.setdefault(key, {}).setdefault("ref", []).append(v_f)
            elif method == oth:
                groups.setdefault(key, {}).setdefault("oth", []).append(v_f)
        diffs: List[float] = []
        for key, m in groups.items():
            if "ref" not in m or "oth" not in m:
                continue
            r_mean = sum(m["ref"]) / len(m["ref"])
            o_mean = sum(m["oth"]) / len(m["oth"])
            if r_mean == 0:
                continue
            diffs.append(abs(o_mean - r_mean) / abs(r_mean))
        return max(diffs) if diffs else float("nan")

    if kind == "best_method_at_density":
        method_field = agg["method_field"]
        sub = filter_rows(filtered, agg.get("filter", {}) or {})
        # For each unique num_agents value, pick the method with the
        # largest mean metric.  Then return the modal best method.
        per_dens: Dict[Any, str] = {}
        densities = sorted({r.get("num_agents") for r in sub
                            if r.get("num_agents") is not None})
        for d in densities:
            cell = filter_rows(sub, {"num_agents": d})
            means = _group_means(cell, method_field, metric)
            if not means:
                continue
            per_dens[d] = max(means, key=lambda m: means[m])
        if not per_dens:
            return ""
        # Modal best method.
        from collections import Counter
        return Counter(per_dens.values()).most_common(1)[0][0]

    if kind == "max_minus_value_at":
        method_field = agg["method_field"]
        method = agg["method"]
        x_field = agg["x_field"]
        ref_x = agg["reference_x"]
        tail_x = agg["tail_x"]
        sub = filter_rows(filtered, {method_field: method})
        ref_v = _values(filter_rows(sub, {x_field: ref_x}), metric)
        tail_v = _values(filter_rows(sub, {x_field: tail_x}), metric)
        if not ref_v or not tail_v:
            return float("nan")
        return (sum(ref_v) / len(ref_v)) - (sum(tail_v) / len(tail_v))

    if kind == "gte_relative_to_max_over":
        # Used for "default cell on the Pareto front" claims.
        # Compute ratio of (mean at default cell) / (max mean over the pseudo-axis).
        # We approximate the pseudo-axis as: max mean over all (fov_radius,
        # safety_radius) cells in the source.
        groups: Dict[Tuple[Any, ...], List[float]] = {}
        for r in filtered:
            v = r.get(metric)
            if v is None:
                continue
            try:
                v_f = float(v)
            except (TypeError, ValueError):
                continue
            key = (r.get("fov_radius"), r.get("safety_radius"))
            groups.setdefault(key, []).append(v_f)
        if not groups:
            return float("nan")
        means = {k: sum(vs) / len(vs) for k, vs in groups.items()}
        cell_value = means.get((claim["filter"].get("fov_radius"),
                                claim["filter"].get("safety_radius")))
        if cell_value is None:
            return float("nan")
        max_value = max(means.values())
        if max_value == 0:
            return float("nan")
        return cell_value / max_value

    if kind == "structural":
        return None  # no numerical aggregation; downstream tabulates

    raise ValueError(f"unknown aggregation kind: {kind!r}")


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    # ``Invalid`` is reserved for claims whose supporting rows failed
    # the degenerate-run guard (see ``classify_row_validity``).  When
    # any matching invalid rows exist the claim is not evaluated --
    # we refuse to emit a Confirmed verdict on top of a tainted
    # input -- and the harness exits non-zero.
    status: str            # Confirmed | Refuted | Now stronger | Now weaker | Skipped | Invalid
    actual: Any
    expected: Any
    paper_text: str
    suggested_replacement: str = ""
    reason: str = ""


def _within_tolerance(actual: float, expected: Any, tol: Dict[str, Any]) -> bool:
    """Check whether actual is within tolerance of expected.

    ``expected`` is a scalar (op = lte / gte / equals / approx) or an
    interval (op = in_range).  ``tol`` is ``{kind: absolute|relative,
    value: float}``.
    """
    kind = tol.get("kind", "absolute")
    val = float(tol.get("value", 0.0))
    if isinstance(expected, (list, tuple)):
        lo, hi = float(expected[0]), float(expected[1])
        if kind == "absolute":
            return (lo - val) <= float(actual) <= (hi + val)
        if kind == "relative":
            return (lo * (1 - val)) <= float(actual) <= (hi * (1 + val))
        return lo <= float(actual) <= hi
    e = float(expected)
    a = float(actual)
    if kind == "absolute":
        return abs(a - e) <= val
    if kind == "relative":
        return abs(a - e) <= val * max(1e-12, abs(e))
    return a == e


def evaluate(claim: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> Verdict:
    expected = claim.get("expected")
    if expected is None or claim["aggregation"]["kind"] == "structural":
        # Pure tabulation — record actual but never refute.
        actual = aggregate(rows, claim) if rows else None
        return Verdict(
            status="Skipped",
            actual=actual,
            expected="(structural)",
            paper_text=claim["paper_text"],
            reason="structural / table claim — see Tables section of report",
        )

    actual = aggregate(rows, claim)
    if isinstance(actual, float) and math.isnan(actual):
        return Verdict(
            status="Skipped", actual=float("nan"),
            expected=expected.get("value"),
            paper_text=claim["paper_text"],
            reason="aggregation returned NaN (insufficient data)",
        )

    op = expected.get("op", "approx")
    exp_val = expected.get("value")
    tol = claim.get("tolerance", {"kind": "absolute", "value": 0.0})
    direction = claim.get("favorable_direction", "neither")

    if isinstance(actual, str) or isinstance(exp_val, str):
        status = "Confirmed" if actual == exp_val else "Refuted"
        return Verdict(
            status=status, actual=actual, expected=exp_val,
            paper_text=claim["paper_text"],
            suggested_replacement=(
                "" if status == "Confirmed"
                else _suggest_replacement(claim["paper_text"], actual, exp_val)
            ),
        )

    confirmed = False
    if op == "lte":
        confirmed = (float(actual) <= float(exp_val) + tol.get("value", 0.0)
                     if tol.get("kind", "absolute") == "absolute"
                     else _within_tolerance(actual, exp_val, tol)
                     or float(actual) <= float(exp_val))
    elif op == "gte":
        confirmed = (float(actual) >= float(exp_val) - tol.get("value", 0.0)
                     if tol.get("kind", "absolute") == "absolute"
                     else _within_tolerance(actual, exp_val, tol)
                     or float(actual) >= float(exp_val))
    elif op == "lt":
        confirmed = float(actual) < float(exp_val) + tol.get("value", 0.0)
    elif op == "gt":
        confirmed = float(actual) > float(exp_val) - tol.get("value", 0.0)
    elif op == "equals":
        confirmed = _within_tolerance(actual, exp_val, tol)
    elif op == "approx":
        confirmed = _within_tolerance(actual, exp_val, tol)
    elif op == "in_range":
        confirmed = _within_tolerance(actual, exp_val, tol)
    else:
        return Verdict(
            status="Skipped", actual=actual, expected=exp_val,
            paper_text=claim["paper_text"], reason=f"unknown op {op!r}",
        )

    if confirmed:
        return Verdict(
            status="Confirmed", actual=actual, expected=exp_val,
            paper_text=claim["paper_text"],
        )

    # Not confirmed — classify direction.
    if direction == "neither":
        status = "Refuted"
    else:
        # Compare actual to expected; for an interval, midpoint.
        ref_val = (float(sum(exp_val)) / 2.0) if isinstance(exp_val, (list, tuple)) else float(exp_val)
        delta = float(actual) - ref_val
        if direction == "higher":
            status = "Now stronger" if delta > 0 else "Now weaker"
        else:
            status = "Now stronger" if delta < 0 else "Now weaker"

    return Verdict(
        status=status, actual=actual, expected=exp_val,
        paper_text=claim["paper_text"],
        suggested_replacement=_suggest_replacement(
            claim["paper_text"], actual, exp_val,
        ),
    )


# ---------------------------------------------------------------------------
# Replacement-sentence synthesis
# ---------------------------------------------------------------------------


def _format_actual(actual: Any) -> str:
    if isinstance(actual, float):
        if abs(actual) >= 1000:
            return f"{actual:,.0f}"
        if abs(actual) >= 10:
            return f"{actual:.1f}"
        if abs(actual) >= 1:
            return f"{actual:.2f}"
        return f"{actual:.3g}"
    return str(actual)


def _suggest_replacement(paper_text: str, actual: Any, expected: Any) -> str:
    """Best-effort heuristic.  Looks for the expected value (or its
    range) in the paper text and substitutes the actual; otherwise
    appends a parenthetical correction."""
    fmt_actual = _format_actual(actual)
    if isinstance(expected, (list, tuple)) and len(expected) == 2:
        # Range claim — substitute the whole "X–Y" interval if it
        # appears verbatim in the paper text; otherwise append.
        candidates = [
            f"{int(expected[0])}–{int(expected[1])}",  # "5–8"
            f"{int(expected[0])}-{int(expected[1])}",         # "5-8"
            f"{expected[0]:.0f}–{expected[1]:.0f}",
            f"{expected[0]:.1f}–{expected[1]:.1f}",
        ]
        for c in candidates:
            if c in paper_text:
                return paper_text.replace(c, fmt_actual)
        return f"{paper_text}  [actual: {fmt_actual}]"
    # Scalar.
    candidates = [
        f"{expected:.0f}",
        f"{expected:.1f}",
        f"{expected:.2f}",
        f"{expected}",
        f"{int(expected) if isinstance(expected, (int, float)) and float(expected).is_integer() else expected}",
    ]
    for c in candidates:
        if str(c) in paper_text:
            return paper_text.replace(str(c), fmt_actual)
    return f"{paper_text}  [actual: {fmt_actual}]"


# ---------------------------------------------------------------------------
# Schema validation (used by tests)
# ---------------------------------------------------------------------------


def validate_schema(claims: Sequence[Dict[str, Any]]) -> List[str]:
    """Return a list of human-readable schema problems.  Empty list
    means the YAML is well-formed."""
    problems: List[str] = []
    seen_ids: set = set()
    for k, c in enumerate(claims):
        for f in REQUIRED_CLAIM_FIELDS:
            if f not in c:
                problems.append(f"claim #{k}: missing required field {f!r}")
        if c.get("section") not in ALLOWED_SECTIONS:
            problems.append(
                f"claim {c.get('claim_id', f'#{k}')}: section {c.get('section')!r} "
                f"not in {sorted(ALLOWED_SECTIONS)}"
            )
        if c.get("favorable_direction") not in ALLOWED_DIRECTIONS:
            problems.append(
                f"claim {c.get('claim_id', f'#{k}')}: favorable_direction "
                f"{c.get('favorable_direction')!r} not in {sorted(ALLOWED_DIRECTIONS)}"
            )
        cid = c.get("claim_id")
        if cid in seen_ids:
            problems.append(f"duplicate claim_id: {cid!r}")
        if cid:
            seen_ids.add(cid)
    return problems


# ---------------------------------------------------------------------------
# Report renderers
# ---------------------------------------------------------------------------


def _md_section(title: str, verdicts: Sequence[Verdict]) -> str:
    if not verdicts:
        return f"## {title} (0)\n\n_None._\n"
    lines = [f"## {title} ({len(verdicts)})\n",
             "| Section | Claim | Paper says | Actual | Verdict |",
             "|---------|-------|------------|--------|---------|"]
    for v in verdicts:
        lines.append(
            "| " + " | ".join([
                getattr(v, "section", "?"),
                v.paper_text[:80] + ("…" if len(v.paper_text) > 80 else ""),
                _fmt_expected(v.expected),
                _format_actual(v.actual),
                v.status,
            ]) + " |"
        )
    if verdicts and verdicts[0].suggested_replacement:
        lines.append("\n### Suggested replacement sentences\n")
        for v in verdicts:
            if v.suggested_replacement:
                lines.append(f"* **{getattr(v, 'claim_id', '?')}** "
                             f"(original):\n  > {v.paper_text}\n"
                             f"  **Suggested:**\n  > {v.suggested_replacement}\n")
    return "\n".join(lines)


def _fmt_expected(expected: Any) -> str:
    if isinstance(expected, (list, tuple)) and len(expected) == 2:
        return f"[{expected[0]}, {expected[1]}]"
    return str(expected)


def render_report(
    verdicts: Sequence[Tuple[Dict[str, Any], Verdict]],
    validity: Optional[ValidityReport] = None,
) -> str:
    by_status: Dict[str, List[Verdict]] = {}
    for claim, v in verdicts:
        v.section = claim.get("section", "?")
        v.claim_id = claim.get("claim_id", "?")
        by_status.setdefault(v.status, []).append(v)

    chunks: List[str] = ["# Paper claim validation report\n"]
    # Top-line input-row summary (P2 follow-up).  Always emitted so
    # the reader can see at a glance whether the underlying CSVs
    # passed the degenerate-run guard before reading any verdicts.
    if validity is not None:
        chunks.append(
            f"**Input rows**: N={validity.total_rows} "
            f"(valid {validity.valid_rows}, invalid {validity.n_invalid})\n"
        )
    summary = " · ".join(
        f"**{k}**: {len(by_status.get(k, []))}"
        for k in ("Confirmed", "Refuted", "Now stronger", "Now weaker",
                  "Skipped", "Invalid")
    )
    chunks.append(summary + "\n")
    # Invalid block FIRST, before any positive verdicts, so a reader
    # cannot scroll past tainted rows on the way to "Confirmed".
    if validity is not None and validity.invalid_rows:
        chunks.append(_md_invalid_section(validity))
        chunks.append("")
    # Refuted before Confirmed for the same scroll-attention reason.
    for status in ("Invalid", "Refuted", "Now weaker", "Now stronger",
                   "Confirmed", "Skipped"):
        chunks.append(_md_section(status, by_status.get(status, [])))
        chunks.append("")
    return "\n".join(chunks)


def _md_invalid_section(validity: ValidityReport) -> str:
    """Render the per-row invalid-input section.  Each invalid row
    is identified by ``(source, claim_id_fields, reason)``; we list
    up to the first 50 to keep the report bounded, with a footer
    summarising the rest."""
    head = (f"## Invalid input rows ({validity.n_invalid} of "
            f"{validity.total_rows})\n"
            f"\nRows below failed the degenerate-run guard "
            f"(run_valid / solver_fail_fraction / global_replans). "
            f"They are excluded from claim evaluation; the harness "
            f"exits non-zero.\n")
    lines = [head, "| # | source | run_id | reason |", "|---|---|---|---|"]
    cap = 50
    for i, (source, row, reason) in enumerate(validity.invalid_rows[:cap], 1):
        rid = str(row.get("run_id", ""))[:12]
        lines.append(f"| {i} | {source} | {rid} | {reason} |")
    extra = max(0, validity.n_invalid - cap)
    if extra:
        lines.append(f"\n_(... and {extra} more not shown)_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Table-level LaTeX diff (Tables 1 and 2)
# ---------------------------------------------------------------------------


def _render_table_diff(
    table_id: str, axes: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
) -> str:
    """Emit a LaTeX tabular with cell colors:

      * green   — value is plausible (always; the tool can't disagree
                  with itself for tabulation-only claims)
      * yellow  — placeholder for the user's manual cross-check
                  against the paper PDF.
    """
    row_axis = axes["rows"]
    col_axis = axes["cols"]
    row_values = sorted({r.get(row_axis) for r in rows
                         if r.get(row_axis) is not None}, key=str)
    col_values = sorted({r.get(col_axis) for r in rows
                         if r.get(col_axis) is not None}, key=str)
    metric = axes.get("metrics", [None])[0] if isinstance(axes.get("metrics"), list) else axes.get("metric")
    if metric is None:
        return f"% {table_id}: no metric specified\n"
    cells: Dict[Tuple[Any, Any], float] = {}
    for r in rows:
        v = r.get(metric)
        if v is None:
            continue
        try:
            v_f = float(v)
        except (TypeError, ValueError):
            continue
        cells.setdefault((r.get(row_axis), r.get(col_axis)), []).append(v_f)
    cell_means = {k: sum(vs) / len(vs) for k, vs in cells.items() if vs}

    chunks: List[str] = [
        rf"% {table_id} — auto-tabulation; user verifies against paper PDF.",
        r"\begin{table}[t]\centering\small",
        r"\begin{tabular}{l" + "r" * len(col_values) + "}",
        r"\toprule",
        " & ".join([f"{row_axis}"] + [str(c) for c in col_values]) + r" \\",
        r"\midrule",
    ]
    for rv in row_values:
        cells_str = []
        for cv in col_values:
            v = cell_means.get((rv, cv))
            if v is None:
                cells_str.append("---")
            else:
                cells_str.append(rf"\cellcolor{{yellow!20}} {_format_actual(v)}")
        chunks.append(" & ".join([str(rv)] + cells_str) + r" \\")
    chunks.append(r"\bottomrule")
    chunks.append(r"\end{tabular}")
    chunks.append(rf"\caption{{Auto-tabulation for {table_id}.  Yellow = "
                  r"verify against paper PDF.}}")
    chunks.append(r"\end{table}")
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _resolve_results(
    results_root: Path,
    source: str,
) -> Optional[Path]:
    """Map the YAML's ``source`` field to ``logs/paper/<source>/results.csv``.

    The special source ``"all"`` returns ``None`` and the validator
    will scan every ``results.csv`` under ``results_root``.
    """
    if source == "all":
        return None
    candidate = results_root / source / "results.csv"
    if candidate.exists():
        return candidate
    return None


def _load_all_under_root(results_root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in sorted(results_root.glob("**/results.csv")):
        try:
            out.extend(load_results(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read %s: %s", path, exc)
    return out


@dataclass
class SweepValidityReport:
    """Per-sweep aggregation of the strong validity predicate.

    Returned by :func:`validate_sweep` and consumed by the manifest CLI
    + ``validity_report.json``.  ``reasons`` keys are drawn from
    :data:`INVALID_REASONS`; the count for any reason absent from a
    sweep is zero (Counter default).
    """
    name: str
    csv_path: str
    n_rows: int
    n_invalid: int
    invalid_fraction: float
    threshold: float
    passed: bool
    reasons: Counter = field(default_factory=Counter)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "csv_path": self.csv_path,
            "n_rows": self.n_rows,
            "n_invalid": self.n_invalid,
            "invalid_fraction": self.invalid_fraction,
            "threshold": self.threshold,
            "passed": self.passed,
            "reasons": dict(self.reasons),
        }


def validate_sweep(
    csv_path: Path,
    max_invalid_fraction: float,
    name: Optional[str] = None,
) -> SweepValidityReport:
    """Apply :func:`is_row_invalid` to every row of ``csv_path`` and
    aggregate.

    A sweep PASSES iff ``invalid_fraction <= max_invalid_fraction``.
    ``max_invalid_fraction = 0.0`` therefore demands every single row
    pass the strong predicate (the contract every committed sweep YAML
    declares -- audit 07).
    """
    csv_path = Path(csv_path)
    rows = load_results(csv_path)
    reasons: Counter = Counter()
    n_invalid = 0
    for r in rows:
        invalid, reason = is_row_invalid(r)
        if invalid:
            n_invalid += 1
            reasons[reason] += 1
    n_rows = len(rows)
    invalid_fraction = n_invalid / float(max(1, n_rows))
    passed = invalid_fraction <= float(max_invalid_fraction)
    return SweepValidityReport(
        name=name if name is not None else csv_path.parent.name,
        csv_path=str(csv_path),
        n_rows=n_rows,
        n_invalid=n_invalid,
        invalid_fraction=invalid_fraction,
        threshold=float(max_invalid_fraction),
        passed=passed,
        reasons=reasons,
    )


@dataclass
class ValidityReport:
    """Per-source / aggregate degenerate-run guard summary.

    Carries two layers of aggregation:

    * **Per-row** (claims-mode path).  ``total_rows`` etc. are
      *unique-row* counts: even if multiple claims reference the same
      source, the source's rows are tallied once.  ``invalid_rows``
      carries enough identifying state to surface in the Invalid
      section of the markdown report.

    * **Per-sweep** (manifest-mode path, optional).  ``per_sweep``
      maps sweep name -> :class:`SweepValidityReport`; populated when
      the validator runs in ``--manifest`` mode.
    """
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: List[Tuple[str, Dict[str, Any], str]] = field(default_factory=list)
    per_sweep: Dict[str, SweepValidityReport] = field(default_factory=dict)

    @property
    def n_invalid(self) -> int:
        return len(self.invalid_rows)

    @property
    def overall_passed(self) -> bool:
        """True iff every sweep in ``per_sweep`` passed.  Empty
        per-sweep dict (claims mode) returns True so callers that
        check this in both modes are not falsely tripped."""
        return all(r.passed for r in self.per_sweep.values())

    @property
    def n_failed_sweeps(self) -> int:
        return sum(1 for r in self.per_sweep.values() if not r.passed)

    def to_dict(self) -> Dict[str, Any]:
        """Schema documented at the top of this module
        (``validity_report.json``)."""
        return {
            "sweeps": {n: r.to_dict() for n, r in self.per_sweep.items()},
            "overall_passed": self.overall_passed,
            "n_failed_sweeps": self.n_failed_sweeps,
        }


def run_validation(
    claims_yaml: Path,
    results_root: Path,
    section_filter: str = "all",
    validity_threshold: float = DEFAULT_VALIDITY_THRESHOLD,
) -> Tuple[List[Tuple[Dict[str, Any], Verdict]], List[Dict[str, Any]], ValidityReport]:
    """Returns ``(verdicts, structural_claims, validity_report)``.

    The validity report aggregates the degenerate-run guard over
    every input row touched by any claim; the caller (``main``)
    uses ``validity_report.n_invalid`` to gate the process exit
    code and the report header line.

    Structural claims are picked out separately for table-level
    rendering.
    """
    spec = yaml.safe_load(claims_yaml.read_text())
    claims = spec.get("claims", [])
    problems = validate_schema(claims)
    if problems:
        for p in problems:
            logger.error("schema: %s", p)
        raise ValueError(f"{len(problems)} schema error(s) in {claims_yaml}")

    verdicts: List[Tuple[Dict[str, Any], Verdict]] = []
    structural: List[Dict[str, Any]] = []
    validity = ValidityReport()

    # Per-source cache so each results.csv is loaded + partitioned
    # exactly once even when many claims share a source, AND so the
    # validity tally counts each on-disk row once.
    source_cache: Dict[str, Tuple[List[Dict[str, Any]],
                                   List[Tuple[Dict[str, Any], str]]]] = {}

    def _load_partitioned(source: str) -> Optional[Tuple[List[Dict[str, Any]],
                                                          List[Tuple[Dict[str, Any], str]]]]:
        if source in source_cache:
            return source_cache[source]
        if source == "all":
            raw = annotate_map_stem(_load_all_under_root(results_root))
        else:
            results_path = _resolve_results(results_root, source)
            if results_path is None:
                return None
            raw = annotate_map_stem(load_results(results_path))
        valid, invalid = partition_validity(raw, validity_threshold)
        # Aggregate into the run-level validity report (once per
        # source).  ``invalid_rows`` carries (source, row, reason)
        # so the report knows which sweep each offender came from.
        validity.total_rows += len(raw)
        validity.valid_rows += len(valid)
        for r, reason in invalid:
            validity.invalid_rows.append((source, r, reason))
        source_cache[source] = (valid, invalid)
        return valid, invalid

    for c in claims:
        if section_filter != "all" and c.get("section") != section_filter:
            continue
        if c.get("aggregation", {}).get("kind") == "structural":
            structural.append(c)
            continue

        source = c.get("source")
        loaded = _load_partitioned(source)
        if loaded is None:
            v = Verdict(
                status="Skipped",
                actual=None,
                expected=c.get("expected", {}).get("value"),
                paper_text=c["paper_text"],
                reason=f"results.csv not found under {results_root / source!r}",
            )
            verdicts.append((c, v))
            continue
        valid_rows, invalid_rows = loaded

        # If any invalid rows match the claim's base filter, refuse
        # to compute a verdict on top of a tainted input -- the
        # spec is explicit: "refuse to print any Confirmed verdict
        # if the supporting rows include invalid runs."  Other
        # invalid rows in the same CSV that fall outside this
        # claim's filter do NOT poison this verdict.
        claim_filter = c.get("filter", {}) or {}
        invalid_for_this_claim = [
            (r, reason) for r, reason in invalid_rows
            if _row_passes(r, claim_filter)
        ]
        if invalid_for_this_claim:
            sample = invalid_for_this_claim[0][1]
            v = Verdict(
                status="Invalid",
                actual=None,
                expected=c.get("expected", {}).get("value"),
                paper_text=c["paper_text"],
                reason=(
                    f"{len(invalid_for_this_claim)} of "
                    f"{len(invalid_for_this_claim) + sum(1 for r in valid_rows if _row_passes(r, claim_filter))} "
                    f"supporting row(s) failed the degenerate-run guard; "
                    f"example: {sample}"
                ),
            )
            verdicts.append((c, v))
            continue

        try:
            v = evaluate(c, valid_rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim %s evaluation failed: %s", c.get("claim_id"), exc)
            v = Verdict(
                status="Skipped", actual=None,
                expected=c.get("expected", {}).get("value"),
                paper_text=c["paper_text"], reason=f"error: {exc}",
            )
        verdicts.append((c, v))
    return verdicts, structural, validity


def run_manifest_validation(manifest_path: Path) -> ValidityReport:
    """Apply :func:`validate_sweep` to every sweep listed in the manifest.

    Returns a :class:`ValidityReport` whose ``per_sweep`` dict carries
    one :class:`SweepValidityReport` per declared sweep.  The per-row
    aggregation fields (``total_rows`` / ``invalid_rows``) stay at
    defaults in manifest mode -- the per-sweep reports already carry the
    row-level counts.
    """
    manifest_path = Path(manifest_path)
    spec = yaml.safe_load(manifest_path.read_text()) or {}
    sweeps = spec.get("sweeps", [])
    if not isinstance(sweeps, list) or not sweeps:
        raise ValueError(
            f"manifest {manifest_path} has no 'sweeps' list "
            f"(got: {type(sweeps).__name__})"
        )
    report = ValidityReport()
    base = manifest_path.parent
    for entry in sweeps:
        if not isinstance(entry, dict):
            raise ValueError(f"sweep entry is not a dict: {entry!r}")
        name = entry.get("name")
        csv_field = entry.get("csv")
        thresh = entry.get("max_invalid_fraction")
        if name is None or csv_field is None or thresh is None:
            raise ValueError(
                f"sweep entry missing required key "
                f"(name / csv / max_invalid_fraction): {entry!r}"
            )
        csv_path = Path(csv_field)
        if not csv_path.is_absolute():
            csv_path = (base / csv_path).resolve()
        sweep_report = validate_sweep(csv_path, float(thresh), name=str(name))
        report.per_sweep[str(name)] = sweep_report
    return report


def _format_sweep_summary(r: SweepValidityReport) -> str:
    """One-line + reason-tail human summary for stderr."""
    pct = r.invalid_fraction * 100.0
    thresh_pct = r.threshold * 100.0
    verdict = "PASS" if r.passed else "FAIL"
    head = (
        f"[sweep:{r.name}] n_rows={r.n_rows} "
        f"invalid={r.n_invalid} ({pct:.1f}%) "
        f"threshold={thresh_pct:.1f}% {verdict}"
    )
    if r.reasons:
        tail = " ".join(f"{k}={v}" for k, v in r.reasons.most_common())
        return f"{head}\n  reasons: {tail}"
    return head


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="POE-LMAPF paper numerical claim validator")
    # Mode is mutually exclusive: --manifest (resume-prompt-7 sweep
    # validator) OR --claims (legacy paper-claims validator).
    p.add_argument("--manifest", type=Path, default=None,
                   help="Sweep manifest YAML (sweeps: [{name, csv, "
                        "max_invalid_fraction}, ...]).  Runs the strong "
                        "validity predicate row-by-row over every sweep "
                        "and writes validity_report.json next to the "
                        "manifest; exits 3 if any sweep fails its "
                        "max_invalid_fraction.")
    p.add_argument("--claims", type=Path, default=None,
                   help="docs/PAPER_NUMERICAL_CLAIMS.yaml (claims mode).")
    p.add_argument("--results-root", type=Path, default=None,
                   help="Claims mode: directory containing per-sweep "
                        "result subdirs (e.g. logs/paper/).")
    p.add_argument("--out", type=Path, default=None,
                   help="Claims mode: Markdown report path.")
    p.add_argument("--tables-out", default=None, type=Path,
                   help="Claims mode: optional LaTeX table diff path "
                        "(default: alongside --out).")
    p.add_argument("--section", default="all",
                   choices=("all", "5.2", "5.3", "5.4", "5.5"))
    p.add_argument("--validity-threshold", type=float,
                   default=DEFAULT_VALIDITY_THRESHOLD,
                   help=("[DEPRECATED, no-op] Solver-fail threshold; locked "
                         f"at {SOLVER_FAIL_THRESHOLD} per Decision 4c."))
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(levelname)s %(name)s | %(message)s")

    # ---- Manifest mode (resume-prompt-7) ----
    if args.manifest is not None:
        if args.claims is not None:
            p.error("--manifest and --claims are mutually exclusive")
        report = run_manifest_validation(args.manifest)
        for sweep in report.per_sweep.values():
            print(_format_sweep_summary(sweep), file=sys.stderr)
        out_json = args.manifest.parent / "validity_report.json"
        out_json.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        logger.info("wrote %s", out_json)
        if not report.overall_passed:
            logger.error(
                "%d of %d sweep(s) failed the validity gate; "
                "exit 3 (audit 07 / Decision 4c).",
                report.n_failed_sweeps, len(report.per_sweep),
            )
            return 3
        return 0

    # ---- Claims mode (legacy) ----
    for required in ("claims", "results_root", "out"):
        if getattr(args, required) is None:
            p.error(
                f"--{required.replace('_', '-')} is required in claims mode "
                f"(use --manifest for sweep-only validation)"
            )
    if args.validity_threshold != DEFAULT_VALIDITY_THRESHOLD:
        logger.warning(
            "--validity-threshold is deprecated and ignored (clause 3 "
            "is locked at %.2f per Decision 4c)",
            SOLVER_FAIL_THRESHOLD,
        )

    verdicts, structural, validity = run_validation(
        args.claims, args.results_root, args.section,
        validity_threshold=float(args.validity_threshold),
    )
    report = render_report(verdicts, validity)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    logger.info("wrote %s", args.out)
    logger.info(
        "input rows: N=%d valid=%d invalid=%d",
        validity.total_rows, validity.valid_rows, validity.n_invalid,
    )
    if validity.invalid_rows:
        logger.error(
            "%d input row(s) failed the degenerate-run guard; "
            "exiting non-zero so the validator is not interpreted as "
            "Confirmed on tainted data.  See the Invalid section in %s.",
            validity.n_invalid, args.out,
        )

    # Tables.
    tex_path = args.tables_out or args.out.with_name(
        args.out.stem + "_tables.tex"
    )
    chunks: List[str] = ["% Auto-generated by validate_paper_claims.py"]
    for c in structural:
        source = c["source"]
        if source == "all":
            rows = annotate_map_stem(_load_all_under_root(args.results_root))
        else:
            rp = _resolve_results(args.results_root, source)
            if rp is None:
                chunks.append(f"% {c['claim_id']}: results not found "
                              f"under {args.results_root / source!r}")
                continue
            rows = annotate_map_stem(load_results(rp))
        chunks.append(
            _render_table_diff(c["claim_id"], c.get("table_axes", {}),
                               filter_rows(rows, c.get("table_axes", {}).get("filter") or {}))
        )
    tex_path.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")
    logger.info("wrote %s", tex_path)
    # P2 follow-up: exit non-zero if ANY input row failed the
    # degenerate-run guard.  This is the gate that distinguishes
    # "no Confirmed verdict was issued on a tainted CSV" from
    # "validator ran clean".  Exit code 3 is reserved for the
    # validity gate so it is distinguishable from a generic
    # SystemExit (1) or argparse failure (2).
    if validity.invalid_rows:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
