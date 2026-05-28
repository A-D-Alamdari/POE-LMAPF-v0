#!/usr/bin/env python3
"""Reverse-engineer the paper Table 1 "N_x" (exo-attr. violations) column.

The paper's Table 1 reports a per-cell mean ± std for the
"Exo-attr. violations" column.  At the time this script was written
the actual CSV columns the paper sweep produced had been audited
upstream (P5 / P6 / Prompt-1 follow-ups), so it was no longer obvious
which column the paper's numbers came from -- they could have been:

  * raw ``violations_exogenous_attributable`` (per-tick agent-tick count),
  * the same per 1000 steps (``safety_violation_rate``),
  * per (M * T), per (X * T), per completed_tasks,
  * an external / deleted dataset,
  * or hand-typed.

This script loads the per-run results.csv that backs the §5.2
solver-sensitivity sweep, filters to the (H, map, solver) cells the
paper's Table 1 carries, and for every numeric CSV column tries a
panel of candidate transforms.  For each (column, transform) pair
it computes the mean across seeds per cell, the L2 residual against
the paper's printed values, and the max per-cell relative error.

The intended output is a sorted Markdown table (best fit first); a
clean match means the column + transform tuple at the top has
near-zero residual and the paper text can keep its numbers.  No
clean match means the column was hand-typed or pulled from a stale
dataset.

Usage::

    python scripts/diagnostics/find_nx_source.py \\
        --results-csv logs/paper/solver_sensitivity/results.csv \\
        --out         reports/nx_source_audit.md

The default --results-csv points at the §5.2 sweep CSV.  The task
description references logs/tuning/horizon_replan_full/ but that
sweep only ran lacam_official (single-solver horizon tuning);
Table 1 is a six-solver comparison, so the correct source is the
§5.2 solver_sensitivity sweep.  The script documents this in the
audit report header.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("find_nx_source")


# ---------------------------------------------------------------------------
# Paper Table 1 cells (H=20, 6 solvers × 2 maps).  Source of truth:
# ``paper/tables/table1_solver_substitutability.{md,tex}``.
# ---------------------------------------------------------------------------

PAPER_TABLE1_H = 20

PAPER_NX: Dict[Tuple[str, str], float] = {
    ("random-64-64-10",        "cbsh2"):           2459.6,
    ("random-64-64-10",        "lacam_official"):  2454.4,
    ("random-64-64-10",        "lacam3"):          2454.4,
    ("random-64-64-10",        "lns2"):            2443.2,
    ("random-64-64-10",        "pbs"):             2533.2,
    ("random-64-64-10",        "pibt2"):           2405.1,
    ("warehouse-10-20-10-2-2", "cbsh2"):            820.3,
    ("warehouse-10-20-10-2-2", "lacam_official"):   760.5,
    ("warehouse-10-20-10-2-2", "lacam3"):           760.5,
    ("warehouse-10-20-10-2-2", "lns2"):             765.1,
    ("warehouse-10-20-10-2-2", "pbs"):              798.6,
    ("warehouse-10-20-10-2-2", "pibt2"):            759.0,
}


# §5.1 horizon-tuning N_x dict.  Cells: H ∈ {10..80} × {random,
# warehouse} at |M|=100, |X|=50.  Values are in [0.029, 0.083]
# and scale roughly with H -- four orders of magnitude away from
# violations_exogenous_attributable in the same CSV (which is in
# the thousands).  No simple transform reproduces these in the
# manual audit; the diagnostic confirms or denies.
PAPER_NX_HORIZON: Dict[Tuple[int, str], float] = {
    (10, "random"):    0.029, (10, "warehouse"): 0.033,
    (20, "random"):    0.040, (20, "warehouse"): 0.044,
    (30, "random"):    0.046, (30, "warehouse"): 0.050,
    (40, "random"):    0.052, (40, "warehouse"): 0.057,
    (50, "random"):    0.061, (50, "warehouse"): 0.058,
    (60, "random"):    0.064, (60, "warehouse"): 0.063,
    (70, "random"):    0.072, (70, "warehouse"): 0.066,
    (80, "random"):    0.083, (80, "warehouse"): 0.067,
}


def _map_short(map_path: str) -> str:
    """Collapse a full map_path to the ``random`` / ``warehouse``
    short name the horizon dict uses."""
    base = Path(map_path).stem
    if base.startswith("random"):
        return "random"
    if base.startswith("warehouse"):
        return "warehouse"
    return base


# ---------------------------------------------------------------------------
# Candidate transforms.  Each transform is a callable
# ``(x, row) -> Optional[float]`` -- if it returns None, the row is
# skipped for that transform (e.g. division by zero).
# ---------------------------------------------------------------------------


def _safe_div(num: float, denom: float) -> Optional[float]:
    return num / denom if denom not in (0, 0.0) else None


def _to_int(row: Dict[str, Any], key: str) -> Optional[int]:
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(row: Dict[str, Any], key: str) -> Optional[float]:
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Panel A — UNARY transforms applied to the iterated column ``x``.
#
# Each entry is (label, fn) where fn must USE the ``x`` argument.
# A function that ignores ``x`` and reads named columns from the
# row instead belongs in Panel B (NAMED_DERIVED) below, not here
# -- otherwise the cross-product over numeric columns collapses to
# identical residuals for every (column, transform) pair (the
# P14 column-dimension-collapse bug).  Enforced by
# ``_assert_no_column_collapse`` in ``main`` -- two columns
# matching to 1e-9 under the same unary transform abort the run.
# ---------------------------------------------------------------------------
UNARY_TRANSFORMS: List[Tuple[str, Callable[[float, Dict[str, Any]], Optional[float]]]] = [
    ("x",                              lambda x, r: x),
    ("x/T",                            lambda x, r: _safe_div(x, _to_int(r, "steps") or 0)),
    ("x/(M*T)",                        lambda x, r: _safe_div(
        x, (_to_int(r, "num_agents") or 0) * (_to_int(r, "steps") or 0)
    )),
    ("x/(X*T)",                        lambda x, r: _safe_div(
        x, (_to_int(r, "num_humans") or 0) * (_to_int(r, "steps") or 0)
    )),
    ("x/completed_tasks",              lambda x, r: _safe_div(
        x, _to_int(r, "completed_tasks") or 0
    )),
    ("x/T * 1000",                     lambda x, r: _safe_div(x * 1000.0, _to_int(r, "steps") or 0)),
    ("x/T * 100",                      lambda x, r: _safe_div(x * 100.0, _to_int(r, "steps") or 0)),
    ("x*T",                            lambda x, r: x * (_to_int(r, "steps") or 0)),
    ("x/M",                            lambda x, r: _safe_div(x, _to_int(r, "num_agents") or 0)),
    ("x/X",                            lambda x, r: _safe_div(x, _to_int(r, "num_humans") or 0)),
    ("x/global_replans",               lambda x, r: _safe_div(
        x, _to_int(r, "global_replans") or 0
    )),
    ("sqrt(x)",                        lambda x, r: math.sqrt(x) if x >= 0 else None),
    ("x/2000",                         lambda x, r: x / 2000.0),  # steps default
    ("x*100",                          lambda x, r: x * 100.0),
    ("x/100",                          lambda x, r: x / 100.0),
]


# Back-compat alias.  Callers that imported ``TRANSFORMS`` from
# this module continue to work; the panel they receive is the
# fixed unary-only one.
TRANSFORMS = UNARY_TRANSFORMS


# ---------------------------------------------------------------------------
# Panel B — NAMED DERIVED quantities, each evaluated ONCE per row
# from explicit source columns.  Each callable returns the per-row
# value of the derived quantity; the fitter then minimises
# ``L2(paper, c * q)`` over the free scalar ``c`` and reports both
# c and the residual after scaling.  A column whose SHAPE matches
# (low residual after free scaling) is more informative than a
# fixed-c guess that misses at the extremes.
# ---------------------------------------------------------------------------
def _MT(r: Dict[str, Any]) -> float:
    return float((_to_int(r, "num_agents") or 0) * (_to_int(r, "steps") or 0))


def _XT(r: Dict[str, Any]) -> float:
    return float((_to_int(r, "num_humans") or 0) * (_to_int(r, "steps") or 0))


def _div_or_none(num: float, denom: float) -> Optional[float]:
    return num / denom if denom > 0 else None


NAMED_DERIVED: List[Tuple[str, Callable[[Dict[str, Any]], Optional[float]]]] = [
    ("safe_wait_steps/(M*T)",
        lambda r: _div_or_none(_to_float(r, "safe_wait_steps") or 0.0, _MT(r))),
    ("yield_wait_steps/(M*T)",
        lambda r: _div_or_none(_to_float(r, "yield_wait_steps") or 0.0, _MT(r))),
    ("(safe_wait_steps + yield_wait_steps)/(2*M*T)",
        lambda r: _div_or_none(
            (_to_float(r, "safe_wait_steps") or 0.0)
            + (_to_float(r, "yield_wait_steps") or 0.0),
            2.0 * _MT(r),
        )),
    ("(safe_wait_steps + 2*yield_wait_steps)/(M*T)",
        lambda r: _div_or_none(
            (_to_float(r, "safe_wait_steps") or 0.0)
            + 2.0 * (_to_float(r, "yield_wait_steps") or 0.0),
            _MT(r),
        )),
    ("(total_wait_steps - safe_wait_steps)/(M*T)",
        lambda r: _div_or_none(
            (_to_float(r, "total_wait_steps") or 0.0)
            - (_to_float(r, "safe_wait_steps") or 0.0),
            _MT(r),
        )),
    ("human_passive_wait_steps/(X*T)",
        lambda r: _div_or_none(
            _to_float(r, "human_passive_wait_steps") or 0.0, _XT(r),
        )),
    ("violations_exogenous_attributable/completed_tasks",
        lambda r: _div_or_none(
            _to_float(r, "violations_exogenous_attributable") or 0.0,
            float(_to_int(r, "completed_tasks") or 0),
        )),
    ("violations_exogenous_attributable/(X*steps)",
        lambda r: _div_or_none(
            _to_float(r, "violations_exogenous_attributable") or 0.0, _XT(r),
        )),
    ("safe_wait_steps/completed_tasks",
        lambda r: _div_or_none(
            _to_float(r, "safe_wait_steps") or 0.0,
            float(_to_int(r, "completed_tasks") or 0),
        )),
    ("global_replans/completed_tasks",
        lambda r: _div_or_none(
            _to_float(r, "global_replans") or 0.0,
            float(_to_int(r, "completed_tasks") or 0),
        )),
    ("wait_fraction",
        lambda r: _to_float(r, "wait_fraction")),
    ("global_replans/1000",
        lambda r: (_to_float(r, "global_replans") or 0.0) / 1000.0),
    ("local_replans/100000",
        lambda r: (_to_float(r, "local_replans") or 0.0) / 100000.0),
]


# ---------------------------------------------------------------------------
# Loader + cell mean computation
# ---------------------------------------------------------------------------


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        return [r for r in csv.DictReader(f)]


def _normalize_map(map_path: str) -> str:
    return map_path.rsplit("/", 1)[-1].removesuffix(".map")


def filter_paper_cells(
    rows: List[Dict[str, Any]],
    horizon: int,
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Group rows by (map_stem, global_solver) for those with the
    paper's H and status=ok.  Returns one bucket per cell.  Used
    for the §5.4 / baseline dataset."""
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("status") not in ("ok", "", None):  # accept legacy CSVs without status
            continue
        try:
            if int(float(r.get("horizon") or 0)) != horizon:
                continue
        except (TypeError, ValueError):
            continue
        cell = (_normalize_map(r.get("map_path", "")), r.get("global_solver", ""))
        out[cell].append(r)
    return out


def filter_horizon_cells(
    rows: List[Dict[str, Any]],
) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
    """Group rows by (horizon, map_short) for the §5.1 horizon-
    tuning dataset, filtering to ``num_agents == 100,
    num_humans == 50, status == 'ok'`` (the slice that backs the
    horizon Table 1 N_x sub-table)."""
    out: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("status") not in ("ok", "", None):
            continue
        try:
            if int(float(r.get("num_agents") or 0)) != 100:
                continue
            if int(float(r.get("num_humans") or 0)) != 50:
                continue
            H = int(float(r.get("horizon") or 0))
        except (TypeError, ValueError):
            continue
        cell = (H, _map_short(r.get("map_path") or ""))
        out[cell].append(r)
    return out


def numeric_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Identify columns whose values parse as floats on at least one row.
    String / categorical columns are skipped."""
    if not rows:
        return []
    cols: List[str] = []
    sample = rows[0]
    for k in sample.keys():
        if k.startswith("_"):
            continue
        # Exclude identifier-like columns that happen to be numeric
        # but are not measurements (seed, num_agents, etc.).  We
        # still try them in case the paper used one as a divisor
        # baseline, but flag them.
        for r in rows[:50]:
            v = r.get(k)
            if v is None or v == "":
                continue
            try:
                float(v)
                cols.append(k)
                break
            except (TypeError, ValueError):
                continue
    return sorted(set(cols))


# ---------------------------------------------------------------------------
# Fit metric
# ---------------------------------------------------------------------------


def fit_residual(
    col: str,
    transform_label: str,
    transform_fn: Callable[[float, Dict[str, Any]], Optional[float]],
    cells: Dict[Tuple[str, str], List[Dict[str, Any]]],
    paper_nx: Dict[Tuple[str, str], float],
) -> Optional[Tuple[float, float, int, Dict[Tuple[str, str], float]]]:
    """Compute the mean transformed value per cell, then the L2
    residual + max per-cell relative error against paper_nx.
    Returns (l2_residual, max_rel_err, n_cells_used, per_cell_means)
    or None if the transform produced no usable values."""
    per_cell: Dict[Tuple[str, str], float] = {}
    for cell, paper_v in paper_nx.items():
        bucket = cells.get(cell, [])
        vals: List[float] = []
        for r in bucket:
            x = _to_float(r, col)
            if x is None:
                continue
            try:
                t = transform_fn(x, r)
            except Exception:
                t = None
            if t is None or not math.isfinite(t):
                continue
            vals.append(float(t))
        if not vals:
            continue
        per_cell[cell] = sum(vals) / len(vals)
    if not per_cell:
        return None
    # Squared error across cells where both paper and actual exist.
    paired = [(paper_nx[c], v) for c, v in per_cell.items() if c in paper_nx]
    if not paired:
        return None
    sq_err = sum((p - v) ** 2 for p, v in paired)
    l2 = math.sqrt(sq_err / len(paired))
    max_rel = max(
        abs(p - v) / max(abs(p), 1e-9)
        for p, v in paired
    )
    return l2, max_rel, len(paired), per_cell


def fit_named_derived(
    label: str,
    fn: Callable[[Dict[str, Any]], Optional[float]],
    cells: Dict[Any, List[Dict[str, Any]]],
    paper_nx: Dict[Any, float],
) -> Optional[Tuple[float, float, float, int, Dict[Any, float]]]:
    """Evaluate a named-derived quantity once per row, take the
    per-cell mean across seeds, then minimise ``L2(paper, c*q)``
    over the free scalar ``c``.

    Closed-form best ``c = sum(p*q) / sum(q*q)``.  Returns
    ``(c, l2_after_scaling, max_rel_err_after_scaling, n_cells,
    per_cell_q_means)`` or None if the quantity has no usable
    values.

    The ``L2`` reported is per-cell RMS after applying the
    free scaling -- the residual a shape match would have if the
    paper's printed value was the free-scaling target.  ``c`` is
    the constant that needs to multiply ``q`` to land on the
    paper value; reporting it separately lets the reader judge
    whether the constant is plausible (e.g. ~1.0 suggests the
    quantity itself IS the formula) or implausible (a fitted c
    like 7.42 suggests the shape isn't really matched, just
    Pearson-correlated)."""
    per_cell: Dict[Any, float] = {}
    for cell in paper_nx:
        bucket = cells.get(cell, [])
        vals: List[float] = []
        for r in bucket:
            try:
                v = fn(r)
            except Exception:
                v = None
            if v is None or not math.isfinite(v):
                continue
            vals.append(float(v))
        if not vals:
            continue
        per_cell[cell] = sum(vals) / len(vals)
    if not per_cell:
        return None
    paired = [(paper_nx[c], v) for c, v in per_cell.items() if c in paper_nx]
    if not paired:
        return None
    # Free-scaling constant c = sum(p*q) / sum(q*q).
    sum_pq = sum(p * q for p, q in paired)
    sum_qq = sum(q * q for _p, q in paired)
    if sum_qq <= 0:
        return None
    c = sum_pq / sum_qq
    # Residual after scaling.
    sq_err = sum((p - c * q) ** 2 for p, q in paired)
    l2 = math.sqrt(sq_err / len(paired))
    max_rel = max(
        abs(p - c * q) / max(abs(p), 1e-9) for p, q in paired
    )
    return c, l2, max_rel, len(paired), per_cell


def assert_no_column_collapse(
    fits_unary: List[Tuple[str, str, float, float, int, Dict[Any, float]]],
    tolerance: float = 1e-9,
) -> None:
    """P14 guard: under the same unary transform, two DISTINCT
    columns must produce different residuals (their data is
    different, the transform uses ``x``, so the post-transform
    means must diverge).  A near-zero L2 difference across many
    columns under the same transform indicates the transform
    ignored its ``x`` argument and read named columns from the
    row instead -- which means the entire column axis of the
    search collapsed.  This was the P13 bug.

    Raise immediately if collapse is detected so the audit
    cannot publish a stale verdict.
    """
    # Group fits by transform label.
    by_transform: Dict[str, List[Tuple[str, float]]] = {}
    for col, label, l2, _max_rel, _n, _per_cell in fits_unary:
        by_transform.setdefault(label, []).append((col, l2))
    for label, entries in by_transform.items():
        if len(entries) < 2:
            continue
        # Sort by L2; check pairs of distinct columns for L2 tie.
        entries.sort(key=lambda e: e[1])
        # Count of column pairs whose L2 differs by less than the
        # tolerance.  We allow at most a tiny number of accidental
        # ties (e.g. integer columns that round identically); a
        # MAJORITY tie across columns is the collapse signature.
        n_tied = 0
        first_l2 = entries[0][1]
        for _col, l2 in entries:
            if abs(l2 - first_l2) < tolerance:
                n_tied += 1
        if n_tied >= max(3, len(entries) // 2):
            # Names of the tied columns -- for the failure msg.
            tied_cols = [
                col for col, l2 in entries
                if abs(l2 - first_l2) < tolerance
            ]
            raise RuntimeError(
                f"column dimension collapsed under transform "
                f"{label!r}: {n_tied}/{len(entries)} columns "
                f"share L2 = {first_l2} to within {tolerance}.  "
                f"Tied columns: {tied_cols[:8]}{'...' if len(tied_cols) > 8 else ''}.  "
                f"The transform is ignoring its column argument "
                f"(probably reading a named column from the row "
                f"directly); move it to NAMED_DERIVED."
            )


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


OUTCOME_I_THRESHOLD = 0.05  # max per-cell relative error for outcome (i)


def _format_cell_key(cell: Any) -> Tuple[str, str]:
    """Render a cell key as (axis1, axis2) strings for the per-cell
    breakdown table.  Handles both the baseline (map_stem, solver)
    and horizon (H, map_short) shapes."""
    a, b = cell
    return (str(a), str(b))


def write_report(
    out_path: Path,
    fits: List[Tuple[str, str, float, float, int, Dict[Any, float]]],
    rows_csv_path: Path,
    n_rows: int,
    paper_nx: Dict[Any, float],
    horizon: int,
    dataset_label: str = "baseline",
    named_fits: Optional[List[Tuple[str, float, float, float, int, Dict[Any, float]]]] = None,
) -> None:
    """Render the sorted audit table + the per-cell breakdown for
    the top THREE candidates + an outcome verdict.

    ``dataset_label`` selects:
      * ``baseline`` -- §5.4 / §5.2 sweep, cell key (map_stem, solver),
        report title carries the H filter.
      * ``horizon``  -- §5.1 horizon-tuning sub-table, cell key
        (H, map_short), report title is dataset-specific.
    """
    fits.sort(key=lambda t: (t[2], t[3]))

    is_horizon = dataset_label == "horizon"
    if is_horizon:
        title = "§5.1 horizon-tuning \"N_x\" sub-table — source audit"
        cells_header = ("H", "map")
        slice_descr = (
            "filtered to ``num_agents == 100, num_humans == 50, "
            "status == 'ok'`` (the slice that backs the §5.1 "
            "horizon-tuning Table 1 N_x sub-table)"
        )
    else:
        title = "Paper Table 1 \"N_x\" column — source audit"
        cells_header = ("Map", "Solver")
        slice_descr = (
            f"filtered to ``horizon == {horizon}, status == 'ok'``"
        )

    lines: List[str] = []
    lines.append(f"# {title}\n")
    lines.append(
        f"Searches every numeric column in `{rows_csv_path}` "
        f"(N={n_rows} rows, {slice_descr}) for the transform whose "
        f"per-cell mean best matches the paper's printed N_x values.  "
        f"Generated by `scripts/diagnostics/find_nx_source.py "
        f"--paper-dataset {dataset_label}`; rerun the script "
        f"to regenerate.  Sorted ascending by L2 residual (best fit "
        f"first); a residual at or near machine epsilon means the "
        f"paper's column reproduces from that (column, transform) "
        f"tuple.\n"
    )
    lines.append(
        f"**Paper cells**: {len(paper_nx)}.\n"
    )

    # Decision: outcome (i) vs (ii).  Considers BOTH panels --
    # whichever gives the lowest max-rel-err post-scaling wins.
    panel_a_top = fits[0][3] if fits else float("inf")
    named_fits = named_fits or []
    # Named fits are tuples (label, c, l2, max_rel, n, per_cell).
    # We use the POST-SCALING max_rel for the verdict.
    named_sorted = sorted(named_fits, key=lambda t: (t[3], t[2]))
    panel_b_top = named_sorted[0][3] if named_sorted else float("inf")
    best_top = min(panel_a_top, panel_b_top)
    if best_top < OUTCOME_I_THRESHOLD:
        outcome_block = (
            f"**Outcome (i)** -- best fit (across both panels) "
            f"reaches max per-cell relative error "
            f"{best_top*100:.3f}% < {OUTCOME_I_THRESHOLD*100:.0f}% "
            f"on the §5.1 N_x cells.  Documented formula reproduces "
            f"the paper N_x column."
        )
    elif math.isinf(best_top):
        outcome_block = "(unable to evaluate -- no candidate fits)"
    else:
        outcome_block = (
            f"**Outcome (ii)** -- best fit across both panels has "
            f"max per-cell relative error {best_top*100:.3f}% >= "
            f"{OUTCOME_I_THRESHOLD*100:.0f}%.  The paper N_x "
            f"values do not reproduce from any (column, transform) "
            f"tuple in Panel A or any named-derived quantity (with "
            f"free scaling) in Panel B."
        )
    lines.append(outcome_block + "\n")

    # --- Panel A: column x unary transform grid ----------------
    lines.append("## Panel A — column × unary transform\n")
    lines.append(
        f"Every numeric column in the CSV ({len(set(t[0] for t in fits))} "
        f"columns) is paired with every unary transform "
        f"({len(set(t[1] for t in fits))} transforms) and the "
        f"per-cell mean across seeds is compared to the paper N_x "
        f"dict.  Sorted ascending by L2 residual; top 50 rows.\n"
    )
    lines.append("| Column | Transform | L2 residual | Max rel err | Cells matched |")
    lines.append("|---|---|---:|---:|---:|")
    for col, label, l2, max_rel, n_cells, _per_cell in fits[:50]:
        lines.append(
            f"| `{col}` | `{label}` | {l2:.4f} | {max_rel*100:.3f}% | "
            f"{n_cells}/{len(paper_nx)} |"
        )

    # Per-cell breakdown for the top THREE Panel A candidates.
    for rank, fit in enumerate(fits[:3], 1):
        top_col, top_lab, top_l2, top_rel, top_n, top_per_cell = fit
        lines.append("")
        lines.append(
            f"### Panel A rank-{rank}: `{top_col}` under `{top_lab}`\n"
        )
        lines.append(
            f"L2 residual = {top_l2:.4f}; max per-cell relative error = "
            f"{top_rel*100:.3f}%; cells matched = "
            f"{top_n}/{len(paper_nx)}.\n"
        )
        lines.append(
            f"| {cells_header[0]} | {cells_header[1]} | Paper N_x | "
            f"Actual mean | Δ (%) |"
        )
        lines.append("|---|---|---:|---:|---:|")
        for cell, paper_v in sorted(paper_nx.items(), key=lambda kv: str(kv[0])):
            a, b = _format_cell_key(cell)
            actual = top_per_cell.get(cell)
            if actual is None:
                lines.append(f"| {a} | {b} | {paper_v} | MISSING | -- |")
            else:
                rel = abs(paper_v - actual) / max(abs(paper_v), 1e-9)
                lines.append(
                    f"| {a} | {b} | {paper_v} | {actual:.4f} | "
                    f"{rel*100:.3f}% |"
                )

    # --- Panel B: named-derived quantities with free scaling ----
    lines.append("")
    lines.append("## Panel B — named derived quantities, free-scaled\n")
    lines.append(
        "Each derived quantity ``q`` is evaluated once per row.  "
        "For each, the script reports the free-scaling constant "
        "``c = argmin_c L2(paper, c*q)`` (closed-form "
        "``c = sum(p*q) / sum(q*q)``) and the residual after "
        "scaling.  A *shape match* (low residual after free "
        "scaling) with c close to a plausible constant suggests a "
        "real formula; a low residual with an implausible c means "
        "the quantity is Pearson-correlated but not the source.\n"
    )
    if named_sorted:
        lines.append(
            "| Quantity | c | L2 (after scaling) | Max rel err | "
            "Cells matched |"
        )
        lines.append("|---|---:|---:|---:|---:|")
        for label, c, l2, max_rel, n_cells, _per_cell in named_sorted:
            lines.append(
                f"| `{label}` | {c:.4f} | {l2:.4f} | "
                f"{max_rel*100:.3f}% | {n_cells}/{len(paper_nx)} |"
            )
        # Per-cell breakdown for the top THREE Panel B fits.
        for rank, fit in enumerate(named_sorted[:3], 1):
            label, c, l2, max_rel, n_cells, per_cell = fit
            lines.append("")
            lines.append(
                f"### Panel B rank-{rank}: `{label}` (c = {c:.6f})\n"
            )
            lines.append(
                f"L2 (after scaling) = {l2:.4f}; max per-cell relative "
                f"error = {max_rel*100:.3f}%; cells matched = "
                f"{n_cells}/{len(paper_nx)}.\n"
            )
            lines.append(
                f"| {cells_header[0]} | {cells_header[1]} | Paper N_x | "
                f"q | c*q | Δ (%) |"
            )
            lines.append("|---|---|---:|---:|---:|---:|")
            for cell, paper_v in sorted(paper_nx.items(),
                                        key=lambda kv: str(kv[0])):
                a, b = _format_cell_key(cell)
                q = per_cell.get(cell)
                if q is None:
                    lines.append(
                        f"| {a} | {b} | {paper_v} | MISSING | -- | -- |"
                    )
                else:
                    pred = c * q
                    rel = abs(paper_v - pred) / max(abs(paper_v), 1e-9)
                    lines.append(
                        f"| {a} | {b} | {paper_v} | {q:.4f} | "
                        f"{pred:.4f} | {rel*100:.3f}% |"
                    )
    else:
        lines.append("_(no named-derived quantities evaluated)_\n")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(
        "wrote %s (%d unary fits, %d named fits)",
        out_path, len(fits), len(named_fits),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--paper-dataset", choices=("baseline", "horizon"),
        default="baseline",
        help=("Which paper dataset to audit.  ``baseline`` -- the "
              "§5.4 / §5.2 sweep (default; cells keyed by "
              "(map_stem, global_solver)).  ``horizon`` -- the §5.1 "
              "horizon-tuning sub-table (cells keyed by "
              "(H, map_short) at |M|=100, |X|=50)."),
    )
    p.add_argument(
        "--results-csv", type=Path,
        default=None,
        help=("Per-run results.csv backing the chosen paper "
              "dataset.  If omitted, defaults to the canonical CSV "
              "for the selected --paper-dataset."),
    )
    p.add_argument(
        "--out", type=Path,
        default=None,
        help=("Where to write the audit report.  If omitted, "
              "defaults to reports/nx_source_audit.md for "
              "--paper-dataset=baseline and reports/"
              "nx_horizon_audit.md for --paper-dataset=horizon."),
    )
    p.add_argument("--horizon", type=int, default=PAPER_TABLE1_H,
                   help=("Horizon filter for --paper-dataset=baseline; "
                         "ignored for horizon mode (which sweeps H)."))
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s | %(message)s",
    )

    # Resolve defaults per dataset.
    if args.paper_dataset == "horizon":
        results_csv = args.results_csv or Path(
            "logs/tuning/horizon_replan_full/results.csv"
        )
        out_path = args.out or Path("reports/nx_horizon_audit.md")
        paper_dict: Dict[Any, float] = dict(PAPER_NX_HORIZON)
    else:
        results_csv = args.results_csv or Path(
            "logs/paper/solver_sensitivity/results.csv"
        )
        out_path = args.out or Path("reports/nx_source_audit.md")
        paper_dict = dict(PAPER_NX)

    if not results_csv.exists():
        logger.error("results.csv not found at %s", results_csv)
        return 2

    rows = load_rows(results_csv)
    if args.paper_dataset == "horizon":
        cells_typed: Dict[Any, List[Dict[str, Any]]] = dict(filter_horizon_cells(rows))
    else:
        cells_typed = dict(filter_paper_cells(rows, args.horizon))
    cols = numeric_columns(rows)
    logger.info(
        "loaded %d rows; %d numeric columns; %d non-empty paper cells "
        "(dataset=%s)",
        len(rows), len(cols),
        sum(1 for c in paper_dict if c in cells_typed),
        args.paper_dataset,
    )

    # Panel A: column x unary transform.
    fits: List[Tuple[str, str, float, float, int, Dict[Any, float]]] = []
    for col in cols:
        for label, fn in UNARY_TRANSFORMS:
            res = fit_residual(col, label, fn, cells_typed, paper_dict)
            if res is None:
                continue
            l2, max_rel, n_cells, per_cell = res
            fits.append((col, label, l2, max_rel, n_cells, per_cell))

    # P14 column-dimension-collapse detector.  A transform that
    # ignores its column argument produces identical L2 across
    # every column under that transform; this raises so the audit
    # cannot publish a verdict resting on a broken search.
    assert_no_column_collapse(fits)
    logger.info("no-collapse check passed (%d unary fits)", len(fits))

    # Panel B: named-derived quantities, evaluated once per row,
    # free-scaling fit.
    named_fits: List[Tuple[str, float, float, float, int, Dict[Any, float]]] = []
    for label, fn in NAMED_DERIVED:
        res = fit_named_derived(label, fn, cells_typed, paper_dict)
        if res is None:
            continue
        c, l2, max_rel, n_cells, per_cell = res
        named_fits.append((label, c, l2, max_rel, n_cells, per_cell))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(
        out_path, fits, results_csv, len(rows), paper_dict,
        args.horizon if args.paper_dataset == "baseline" else 0,
        dataset_label=args.paper_dataset,
        named_fits=named_fits,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
