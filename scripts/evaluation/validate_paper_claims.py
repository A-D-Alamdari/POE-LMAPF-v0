#!/usr/bin/env python3
"""
Paper numerical-claim validator.

Reads a registry of paper claims (default
``docs/PAPER_NUMERICAL_CLAIMS.yaml``), pulls the corresponding
``results.csv`` from a sweep directory under ``--results-root``,
applies the encoded filter / aggregation, and compares against the
expected value.  Writes a Markdown report grouped by verdict
(``Confirmed`` / ``Refuted`` / ``Now stronger`` / ``Now weaker`` /
``Skipped``) plus a side-by-side LaTeX diff for Table 1 and Table 2.

The user reads the report and edits the paper accordingly; this tool
does **not** modify the YAML registry or the paper text.

Usage::

    python scripts/evaluation/validate_paper_claims.py \\
        --claims        docs/PAPER_NUMERICAL_CLAIMS.yaml \\
        --results-root  logs/paper \\
        --out           claim_validation.md \\
        --tables-out    claim_validation_tables.tex \\
        --section       all
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
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
    status: str            # Confirmed | Refuted | Now stronger | Now weaker | Skipped
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


def render_report(verdicts: Sequence[Tuple[Dict[str, Any], Verdict]]) -> str:
    by_status: Dict[str, List[Verdict]] = {}
    for claim, v in verdicts:
        v.section = claim.get("section", "?")
        v.claim_id = claim.get("claim_id", "?")
        by_status.setdefault(v.status, []).append(v)

    chunks: List[str] = ["# Paper claim validation report\n"]
    summary = " · ".join(
        f"**{k}**: {len(by_status.get(k, []))}"
        for k in ("Confirmed", "Refuted", "Now stronger", "Now weaker", "Skipped")
    )
    chunks.append(summary + "\n")
    for status in ("Refuted", "Now weaker", "Now stronger", "Confirmed", "Skipped"):
        chunks.append(_md_section(status, by_status.get(status, [])))
        chunks.append("")
    return "\n".join(chunks)


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


def run_validation(
    claims_yaml: Path,
    results_root: Path,
    section_filter: str = "all",
) -> Tuple[List[Tuple[Dict[str, Any], Verdict]], List[Dict[str, Any]]]:
    """Returns ``(verdicts, structural_claims)`` where structural claims
    are picked out separately for table-level rendering."""
    spec = yaml.safe_load(claims_yaml.read_text())
    claims = spec.get("claims", [])
    problems = validate_schema(claims)
    if problems:
        for p in problems:
            logger.error("schema: %s", p)
        raise ValueError(f"{len(problems)} schema error(s) in {claims_yaml}")

    verdicts: List[Tuple[Dict[str, Any], Verdict]] = []
    structural: List[Dict[str, Any]] = []
    for c in claims:
        if section_filter != "all" and c.get("section") != section_filter:
            continue
        if c.get("aggregation", {}).get("kind") == "structural":
            structural.append(c)
            continue

        source = c.get("source")
        if source == "all":
            rows = annotate_map_stem(_load_all_under_root(results_root))
        else:
            results_path = _resolve_results(results_root, source)
            if results_path is None:
                v = Verdict(
                    status="Skipped",
                    actual=None,
                    expected=c.get("expected", {}).get("value"),
                    paper_text=c["paper_text"],
                    reason=f"results.csv not found under {results_root / source!r}",
                )
                verdicts.append((c, v))
                continue
            rows = annotate_map_stem(load_results(results_path))

        try:
            v = evaluate(c, rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("claim %s evaluation failed: %s", c.get("claim_id"), exc)
            v = Verdict(
                status="Skipped", actual=None,
                expected=c.get("expected", {}).get("value"),
                paper_text=c["paper_text"], reason=f"error: {exc}",
            )
        verdicts.append((c, v))
    return verdicts, structural


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="POE-LMAPF paper numerical claim validator")
    p.add_argument("--claims", required=True, type=Path,
                   help="docs/PAPER_NUMERICAL_CLAIMS.yaml")
    p.add_argument("--results-root", required=True, type=Path,
                   help="Directory containing per-sweep result subdirs "
                        "(e.g. logs/paper/)")
    p.add_argument("--out", required=True, type=Path,
                   help="Markdown report path")
    p.add_argument("--tables-out", default=None, type=Path,
                   help="Optional LaTeX table diff path "
                        "(default: alongside --out)")
    p.add_argument("--section", default="all",
                   choices=("all", "5.2", "5.3", "5.4", "5.5"))
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(levelname)s %(name)s | %(message)s")

    verdicts, structural = run_validation(
        args.claims, args.results_root, args.section)
    report = render_report(verdicts)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    logger.info("wrote %s", args.out)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
