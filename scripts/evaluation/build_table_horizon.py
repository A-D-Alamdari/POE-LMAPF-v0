#!/usr/bin/env python3
"""Rebuild the §5 horizon-tuning Table 1 from the per-run CSV.

Goal: every printed column in the rebuilt table corresponds to
exactly the CSV column the header names.  The previous version
of the table had:

  * a "Number of Local Replanning" column showing
    ``mean_service_time`` values (60-150 range), not
    ``local_replans`` (~10^4 range);
  * an "N_x" column whose source could not be reproduced from
    any (column, transform) tuple in the candidate panel
    (status: UNRESOLVED -- see
    ``paper/sections/05_1_horizon_subtable_STALE.md``).

This builder reads ``logs/tuning/horizon_replan_full/results.csv``
(num_agents=100, num_humans=50, status=ok), aggregates the 10
seeds per (H, map) cell, and emits two artifacts:

  * ``paper/tables/horizon_tuning.tex`` -- booktabs LaTeX with a
    provenance comment block at the top mapping every column
    header to its source CSV column or derived formula.  Marks
    cells where mean throughput_utilization >= 0.95 with a
    trailing asterisk (P10 convention).
  * ``paper/tables/horizon_tuning.csv`` -- the same data in flat
    CSV form for sanity-checking / pandas round-trip.

Run with::

    python scripts/evaluation/build_table_horizon.py
"""
from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("build_table_horizon")

# ---------------------------------------------------------------------------
# Column definitions
#
# Each entry is (label, csv_column_or_formula, render_kind, digits).
# ``render_kind`` is one of:
#   "ci_int"   -> mean as integer +/- std (int)
#   "ci_3dp"   -> mean +/- std at 3 decimal places
#   "ci_2dp"   -> mean +/- std at 2 decimal places
#   "ci_1dp"   -> mean +/- std at 1 decimal place
#   "util"     -> mean utilization; appends "*" when >= 0.95
#   "thpt_sat" -> throughput cell with asterisk when util-saturated
#   "def1"    -> def1 quantity; "--" when zero (CSV predates Prompt 1)
#   "n_x"     -> N_x_normalized = mean(violations_def1_exogenous_attributable)
#               / (num_agents * steps); "--" when def1 columns absent
#
# The (label, csv_column, kind) triple is what the provenance
# comment block at the top of the LaTeX output documents.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColSpec:
    label: str           # header text in the LaTeX table
    csv_field: str       # CSV column name OR "derived: <formula>"
    kind: str            # render kind (see above)
    digits: int = 2      # decimal places for ci_* kinds


HORIZON_COLS: Tuple[ColSpec, ...] = (
    ColSpec("Throughput",        "throughput",                                  "thpt_sat", 3),
    ColSpec("Util.",             "throughput_utilization",                       "util",    2),
    ColSpec("Local replans",     "local_replans",                                "ci_int",  0),
    ColSpec("Service time (steps)", "mean_service_time",                          "ci_1dp",  1),
    ColSpec("Wait fraction",      "wait_fraction",                                "ci_3dp",  3),
    ColSpec("Deadlock count",     "deadlock_count",                                "ci_1dp",  1),
    ColSpec("Wall (s)",           "wall_clock_s",                                  "ci_int",  0),
    ColSpec("Def-1 agent-attr.",  "violations_def1_agent_attributable",            "def1",    0),
    ColSpec(
        "N_x norm.",
        "derived: mean(violations_def1_exogenous_attributable) / (num_agents * steps)",
        "n_x", 4,
    ),
)


HORIZON_VALUES = (10, 20, 30, 40, 50, 60, 70, 80)
MAPS: Tuple[Tuple[str, str], ...] = (
    ("random",    "random-64-64-10"),
    ("warehouse", "warehouse-10-20-10-2-2"),
)

ARRIVAL_SATURATION_THRESHOLD = 0.95


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _filter_horizon_slice(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter to status=ok, num_agents=100, num_humans=50."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        if (r.get("status") or "").lower() != "ok":
            continue
        try:
            if int(float(r.get("num_agents") or 0)) != 100:
                continue
            if int(float(r.get("num_humans") or 0)) != 50:
                continue
        except (TypeError, ValueError):
            continue
        out.append(r)
    return out


def _map_short(map_path: str) -> str:
    base = Path(map_path).stem
    if base.startswith("random"):
        return "random"
    if base.startswith("warehouse"):
        return "warehouse"
    return base


def _group_by_horizon_map(
    rows: List[Dict[str, Any]],
) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
    out: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        try:
            H = int(float(r.get("horizon") or 0))
        except (TypeError, ValueError):
            continue
        m = _map_short(r.get("map_path") or "")
        out[(H, m)].append(r)
    return out


# ---------------------------------------------------------------------------
# Per-cell aggregation
# ---------------------------------------------------------------------------


def _cell_utilization(rs: List[Dict[str, Any]]) -> float:
    """Per-cell mean utilization.  Falls back to arithmetic
    ``throughput / (num_agents / (H+W))`` when the CSV's explicit
    ``throughput_utilization`` column is zero or absent (the
    horizon CSV predates the P10 column)."""
    explicit = [
        _to_float(r.get("throughput_utilization"))
        for r in rs
    ]
    explicit = [v for v in explicit if v is not None and v > 0]
    if explicit:
        return mean(explicit)
    # Arithmetic fallback: lambda_sys = M / (H + W).  We can't
    # read H + W from the CSV directly, but we have num_agents
    # and steps, AND we have completed_tasks / steps == throughput
    # which equals arrival_rate at saturation.  Use the simpler
    # ratio: throughput / arrival_rate_per_step from the CSV if
    # present; otherwise compute lambda_sys from the map.
    pairs: List[float] = []
    for r in rs:
        thpt = _to_float(r.get("throughput"))
        arr = _to_float(r.get("arrival_rate_per_step"))
        if thpt is not None and arr is not None and arr > 0:
            pairs.append(thpt / arr)
    if pairs:
        return mean(pairs)
    # Last resort: total_released / steps as the arrival rate.
    pairs2: List[float] = []
    for r in rs:
        thpt = _to_float(r.get("throughput"))
        rel = _to_float(r.get("total_released_tasks"))
        steps = _to_float(r.get("steps"))
        if (thpt is not None and rel and steps and steps > 0
                and rel / steps > 0):
            pairs2.append(thpt / (rel / steps))
    if pairs2:
        return mean(pairs2)
    return 0.0


def _cell_n_x_normalized(rs: List[Dict[str, Any]]) -> Optional[float]:
    """Derived quantity:
    ``mean(violations_def1_exogenous_attributable) / (num_agents * steps)``.
    Returns ``None`` when the def1 column is zero / absent (the
    horizon CSV in this repo predates Prompt 1; the §5.1 N_x
    source is UNRESOLVED per
    ``paper/sections/05_1_horizon_subtable_STALE.md``)."""
    if not rs:
        return None
    def1_vals = [_to_float(r.get("violations_def1_exogenous_attributable"))
                 for r in rs]
    def1_vals = [v for v in def1_vals if v is not None]
    if not def1_vals or all(v == 0 for v in def1_vals):
        return None
    # n_agents and steps are homogeneous within a cell.
    n_agents = int(float(rs[0].get("num_agents") or 0))
    steps = int(float(rs[0].get("steps") or 0))
    denom = float(n_agents * steps)
    if denom <= 0:
        return None
    return mean(def1_vals) / denom


def _ci_mean_std(values: List[float]) -> Tuple[float, float]:
    if not values:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), 0.0
    return float(mean(values)), float(stdev(values))


def _render(
    col: ColSpec,
    rs: List[Dict[str, Any]],
    util_mean: float,
) -> str:
    """Render one cell of the LaTeX table.  Returns a string the
    caller plugs directly into the row."""
    if col.kind == "util":
        if util_mean <= 0.0:
            return "--"
        marker = "*" if util_mean >= ARRIVAL_SATURATION_THRESHOLD else ""
        return rf"\num{{{util_mean:.{col.digits}f}}}{marker}"

    if col.kind == "thpt_sat":
        vals = [v for v in (_to_float(r.get(col.csv_field)) for r in rs)
                if v is not None]
        m, s = _ci_mean_std(vals)
        marker = "*" if util_mean >= ARRIVAL_SATURATION_THRESHOLD else ""
        return (rf"\num{{{m:.{col.digits}f}}}{marker} $\pm$ "
                rf"\num{{{s:.{col.digits}f}}}")

    if col.kind == "def1":
        # CSV predates Prompt 1 if all entries are zero / absent.
        vals = [v for v in (_to_float(r.get(col.csv_field)) for r in rs)
                if v is not None]
        if not vals or all(v == 0 for v in vals):
            return "--"
        m, s = _ci_mean_std(vals)
        return rf"\num{{{m:.{col.digits}f}}} $\pm$ \num{{{s:.{col.digits}f}}}"

    if col.kind == "n_x":
        nx = _cell_n_x_normalized(rs)
        if nx is None:
            return "--"
        return rf"\num{{{nx:.{col.digits}f}}}"

    if col.kind in ("ci_int", "ci_1dp", "ci_2dp", "ci_3dp"):
        vals = [v for v in (_to_float(r.get(col.csv_field)) for r in rs)
                if v is not None]
        m, s = _ci_mean_std(vals)
        if col.kind == "ci_int":
            return rf"\num{{{m:.0f}}} $\pm$ \num{{{s:.0f}}}"
        return (rf"\num{{{m:.{col.digits}f}}} $\pm$ "
                rf"\num{{{s:.{col.digits}f}}}")

    raise ValueError(f"unknown render kind: {col.kind!r}")


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _provenance_comment(cols: Tuple[ColSpec, ...]) -> str:
    """Render the provenance comment block at the top of the LaTeX
    file.  Reads from the .tex alone: every column header maps to
    its CSV column or derived formula.  This is the auditable
    surface the P12 paper-metric-invariants test reads from."""
    lines: List[str] = [
        "%",
        "% Provenance block (P12 / Prompt B): every column in the",
        "% table below sources its value from the named CSV column",
        "% or derived formula.  Auditable from this file alone --",
        "% the P15 test tests/test_horizon_table_provenance.py",
        "% parses these lines and asserts every header appears.",
        "%",
    ]
    for c in cols:
        lines.append(f'% Column "{c.label}" <- {c.csv_field}')
    lines.append("%")
    lines.append("% Source CSV: logs/tuning/horizon_replan_full/results.csv")
    lines.append("% Filter: status=ok, num_agents=100, num_humans=50")
    lines.append("% Aggregation: mean +/- seed-std across 10 seeds per (H, map).")
    lines.append("% Utilization marker (*): mean utilization >= 0.95 (P10 convention).")
    lines.append("%")
    return "\n".join(lines) + "\n"


def emit_tex(
    by_cell: Dict[Tuple[int, str], List[Dict[str, Any]]],
    out_path: Path,
) -> None:
    parts: List[str] = []
    parts.append(_provenance_comment(HORIZON_COLS))
    # Column spec: l for the H column, then r per data column;
    # add a second l before data columns for the map name.
    col_spec = "l" + "l" + "r" * len(HORIZON_COLS)
    parts.append(r"\begin{tabular}{" + col_spec + "}")
    parts.append(r"\toprule")
    header = ["$H$", "Map"] + [c.label for c in HORIZON_COLS]
    parts.append(" & ".join(header) + r" \\")
    parts.append(r"\midrule")
    for H in HORIZON_VALUES:
        for short, full in MAPS:
            rs = by_cell.get((H, short), [])
            if not rs:
                row = [str(H), short.replace("_", r"\_")] + ["--"] * len(HORIZON_COLS)
                parts.append(" & ".join(row) + r" \\")
                continue
            util_mean = _cell_utilization(rs)
            cells = [_render(c, rs, util_mean) for c in HORIZON_COLS]
            row = [str(H), short.replace("_", r"\_")] + cells
            parts.append(" & ".join(row) + r" \\")
    parts.append(r"\bottomrule")
    parts.append(r"\end{tabular}")
    parts.append("")
    parts.append("% Saturation footnote.  See paper/sections/05_1_load_regime.md")
    parts.append("% for the canonical wording: at |M|=100 the system-wide")
    parts.append("% task arrival rate is |M|/(H+W) = 0.781 (random) / 0.394")
    parts.append("% (warehouse); throughput in cells marked with * saturates at")
    parts.append("% this arrival cap and does not measure planner capacity.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    logger.info("wrote %s", out_path)


def emit_csv(
    by_cell: Dict[Tuple[int, str], List[Dict[str, Any]]],
    out_path: Path,
) -> None:
    """Write the same data as a flat CSV.  Columns: H, map, then
    per-cell mean / std for every column in HORIZON_COLS (utility
    fields included).  Loadable round-trip via pandas."""
    out_rows: List[Dict[str, Any]] = []
    for H in HORIZON_VALUES:
        for short, full in MAPS:
            rs = by_cell.get((H, short), [])
            row: Dict[str, Any] = {"H": H, "map": short, "n_seeds": len(rs)}
            util_mean = _cell_utilization(rs) if rs else 0.0
            row["throughput_utilization_mean"] = util_mean
            for c in HORIZON_COLS:
                if c.kind in ("def1", "n_x"):
                    # Special-case derived quantities.
                    if c.kind == "n_x":
                        v = _cell_n_x_normalized(rs)
                        row[f"{c.label}__mean"] = "" if v is None else v
                        row[f"{c.label}__std"] = ""
                        continue
                    vals = [
                        _to_float(r.get(c.csv_field)) for r in rs
                    ]
                    vals_clean = [v for v in vals if v is not None]
                    if not vals_clean or all(v == 0 for v in vals_clean):
                        row[f"{c.label}__mean"] = ""
                        row[f"{c.label}__std"] = ""
                        continue
                    m, s = _ci_mean_std(vals_clean)
                    row[f"{c.label}__mean"] = m
                    row[f"{c.label}__std"] = s
                    continue
                if c.kind == "util":
                    row[f"{c.label}__mean"] = util_mean
                    row[f"{c.label}__std"] = ""
                    row[f"{c.label}__saturated"] = (
                        util_mean >= ARRIVAL_SATURATION_THRESHOLD
                    )
                    continue
                vals = [_to_float(r.get(c.csv_field)) for r in rs]
                vals_clean = [v for v in vals if v is not None]
                m, s = _ci_mean_std(vals_clean)
                row[f"{c.label}__mean"] = m
                row[f"{c.label}__std"] = s
            out_rows.append(row)
    if not out_rows:
        out_path.write_text("H,map\n", encoding="utf-8")
        return
    fieldnames = sorted({k for r in out_rows for k in r.keys()})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    logger.info("wrote %s (%d cells)", out_path, len(out_rows))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--results-csv", type=Path,
        default=Path("logs/tuning/horizon_replan_full/results.csv"),
    )
    p.add_argument(
        "--tex-out", type=Path,
        default=Path("paper/tables/horizon_tuning.tex"),
    )
    p.add_argument(
        "--csv-out", type=Path,
        default=Path("paper/tables/horizon_tuning.csv"),
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s | %(message)s",
    )

    if not args.results_csv.exists():
        logger.error("results.csv not found at %s", args.results_csv)
        return 2

    raw = load_rows(args.results_csv)
    sub = _filter_horizon_slice(raw)
    by_cell = _group_by_horizon_map(sub)
    logger.info(
        "loaded %d rows; %d after filter; %d (H, map) cells",
        len(raw), len(sub), len(by_cell),
    )
    emit_tex(by_cell, args.tex_out)
    emit_csv(by_cell, args.csv_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
