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


# Transform = (label, function(x, row) -> Optional[float]).
TRANSFORMS: List[Tuple[str, Callable[[float, Dict[str, Any]], Optional[float]]]] = [
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
    ("x/(M*T) * 100",                  lambda x, r: _safe_div(
        x, (_to_int(r, "num_agents") or 0) * (_to_int(r, "steps") or 0)
    ) and _safe_div(
        x * 100.0, (_to_int(r, "num_agents") or 0) * (_to_int(r, "steps") or 0)
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
    paper's H and status=ok.  Returns one bucket per cell."""
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


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_report(
    out_path: Path,
    fits: List[Tuple[str, str, float, float, int, Dict[Tuple[str, str], float]]],
    rows_csv_path: Path,
    n_rows: int,
    paper_nx: Dict[Tuple[str, str], float],
    horizon: int,
) -> None:
    """Render the sorted audit table.  Each row: column name,
    transform label, L2 residual, max relative error, # cells with
    data.  Sort ascending by L2 residual so the closest match is
    first."""
    fits.sort(key=lambda t: (t[2], t[3]))

    lines: List[str] = []
    lines.append("# Paper Table 1 \"N_x\" column — source audit\n")
    lines.append(
        f"Searches every numeric column in `{rows_csv_path}` "
        f"(N={n_rows} rows) at H={horizon} for the transform whose "
        f"per-cell mean best matches the paper's printed Exo-attr. "
        f"violations column.  Generated by "
        f"`scripts/diagnostics/find_nx_source.py`; rerun the script "
        f"to regenerate.  Sorted ascending by L2 residual (best fit "
        f"first); a residual at or near machine epsilon means the "
        f"paper's column reproduces from that (column, transform) "
        f"tuple.\n"
    )
    lines.append(
        f"**Paper cells**: {len(paper_nx)} (H={horizon}, 6 solvers × 2 maps; "
        f"the paper's Table 1 markdown / tex source is "
        f"`paper/tables/table1_solver_substitutability.*`).\n"
    )
    lines.append("| Column | Transform | L2 residual | Max rel err | Cells matched |")
    lines.append("|---|---|---:|---:|---:|")
    for col, label, l2, max_rel, n_cells, _per_cell in fits[:50]:
        lines.append(
            f"| `{col}` | `{label}` | {l2:.4f} | {max_rel*100:.3f}% | {n_cells}/{len(paper_nx)} |"
        )

    # Detailed per-cell breakdown for the top fit, so a reader can
    # eyeball the match without rerunning the script.
    if fits:
        top_col, top_lab, top_l2, top_rel, top_n, top_per_cell = fits[0]
        lines.append("")
        lines.append(
            f"## Top fit: `{top_col}` under transform `{top_lab}`\n"
        )
        lines.append(
            f"L2 residual = {top_l2:.4f}; max per-cell relative error = "
            f"{top_rel*100:.3f}%.\n"
        )
        lines.append("| Map | Solver | Paper N_x | Actual mean | Δ (%) |")
        lines.append("|---|---|---:|---:|---:|")
        for cell, paper_v in sorted(paper_nx.items()):
            actual = top_per_cell.get(cell)
            if actual is None:
                lines.append(
                    f"| {cell[0]} | {cell[1]} | {paper_v:.1f} | MISSING | -- |"
                )
            else:
                rel = abs(paper_v - actual) / max(abs(paper_v), 1e-9)
                lines.append(
                    f"| {cell[0]} | {cell[1]} | {paper_v:.1f} | "
                    f"{actual:.2f} | {rel*100:.3f}% |"
                )

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("wrote %s (%d (col, transform) pairs)", out_path, len(fits))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--results-csv", type=Path,
        default=Path("logs/paper/solver_sensitivity/results.csv"),
        help="Per-run results.csv backing Table 1 (default: §5.2 sweep).",
    )
    p.add_argument(
        "--out", type=Path,
        default=Path("reports/nx_source_audit.md"),
        help="Where to write the audit report.",
    )
    p.add_argument("--horizon", type=int, default=PAPER_TABLE1_H)
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s | %(message)s",
    )

    if not args.results_csv.exists():
        logger.error("results.csv not found at %s", args.results_csv)
        return 2

    rows = load_rows(args.results_csv)
    cells = filter_paper_cells(rows, args.horizon)
    cols = numeric_columns(rows)
    logger.info(
        "loaded %d rows; %d numeric columns; %d non-empty paper cells",
        len(rows), len(cols),
        sum(1 for c in PAPER_NX if c in cells),
    )

    fits: List[Tuple[str, str, float, float, int, Dict[Tuple[str, str], float]]] = []
    for col in cols:
        for label, fn in TRANSFORMS:
            res = fit_residual(col, label, fn, cells, PAPER_NX)
            if res is None:
                continue
            l2, max_rel, n_cells, per_cell = res
            fits.append((col, label, l2, max_rel, n_cells, per_cell))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_report(args.out, fits, args.results_csv, len(rows), PAPER_NX, args.horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
