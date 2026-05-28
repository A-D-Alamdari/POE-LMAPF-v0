#!/usr/bin/env python3
"""Audit which cells in a paper-table CSV are arrival-saturated.

A cell is "arrival-saturated" when the per-seed mean
``throughput_utilization`` is at or above 0.95 -- in that regime
throughput equals the system-wide task arrival rate
$\\lambda_{\\text{sys}} = |M|/(H+W)$ and the column cannot
discriminate between planners.  Reading throughput in such cells
as a planner-quality signal is the P10 misreading the paper
text now warns against (see ``paper/sections/05_1_load_regime.md``).

This diagnostic loads a results.csv (default: the §5.2
solver-sensitivity sweep), groups rows by the table's per-cell
factors, and reports:

  * the theoretical $\\lambda_{\\text{sys}}$ for that cell from
    the map's H+W (read from the .map file referenced in
    ``map_path``);
  * the empirical mean ``throughput_utilization`` across seeds;
  * a verdict column: ARRIVAL-SATURATED (>= 0.95),
    NEAR-SATURATED ([0.80, 0.95)), or PLANNER-BOTTLENECKED
    (< 0.80).

Cells flagged ARRIVAL-SATURATED are the ones whose throughput in
paper Tables 1/2 should NOT be read as a planner-discriminating
metric.

Usage::

    python scripts/diagnostics/check_arrival_saturation.py \\
        --results-csv logs/paper/solver_sensitivity/results.csv \\
        --out         reports/arrival_saturation_audit.md
"""
from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("check_arrival_saturation")

# Same threshold the paper-table builder uses for visual flagging.
# See ``scripts/evaluation/build_summary_tables.py::
# ARRIVAL_SATURATION_THRESHOLD``.
ARRIVAL_SATURATION_THRESHOLD: float = 0.95
NEAR_SATURATION_THRESHOLD: float = 0.80


# ---------------------------------------------------------------------------
# Map-dimension cache (reads H + W from the .map file)
# ---------------------------------------------------------------------------


def _map_dimensions(map_path: Path, cache: Dict[Path, Tuple[int, int]]) -> Tuple[int, int]:
    """Return (height, width) parsed from a MovingAI .map header.
    Cached per absolute path."""
    abs_path = map_path.resolve() if map_path.exists() else map_path
    if abs_path in cache:
        return cache[abs_path]
    if not map_path.exists():
        logger.warning("map file missing: %s", map_path)
        cache[abs_path] = (0, 0)
        return 0, 0
    h = w = 0
    with map_path.open() as f:
        for line in f:
            line = line.strip()
            if line.startswith("height "):
                h = int(line.split()[1])
            elif line.startswith("width "):
                w = int(line.split()[1])
            if line == "map":
                break
    cache[abs_path] = (h, w)
    return h, w


# ---------------------------------------------------------------------------
# CSV loader + grouping
# ---------------------------------------------------------------------------


def _coerce(value: str) -> Any:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value


def _map_stem(map_path: str) -> str:
    return Path(map_path).stem


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        rows = [{k: _coerce(v) for k, v in r.items()} for r in csv.DictReader(f)]
    return rows


def cells_grouped_by(
    rows: List[Dict[str, Any]],
    factor_fields: Tuple[str, ...],
) -> Dict[Tuple[Any, ...], List[Dict[str, Any]]]:
    """Group rows by the tuple of values from ``factor_fields``."""
    out: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("status") not in ("ok", "", None):
            continue
        key = tuple(r.get(f) for f in factor_fields)
        out[key].append(r)
    return out


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _verdict(util_mean: float) -> str:
    if util_mean >= ARRIVAL_SATURATION_THRESHOLD:
        return "ARRIVAL-SATURATED"
    if util_mean >= NEAR_SATURATION_THRESHOLD:
        return "NEAR-SATURATED"
    return "PLANNER-BOTTLENECKED"


# ---------------------------------------------------------------------------
# Reporter
# ---------------------------------------------------------------------------


def write_report(
    out_path: Path,
    rows_csv_path: Path,
    factor_fields: Tuple[str, ...],
    rows_by_cell: Dict[Tuple[Any, ...], List[Dict[str, Any]]],
    map_cache: Dict[Path, Tuple[int, int]],
) -> int:
    """Emit the Markdown audit table.  Returns the count of
    arrival-saturated cells (caller may use it as an exit code)."""
    out_lines: List[str] = []
    out_lines.append("# Arrival-saturation audit\n")
    out_lines.append(
        f"Source CSV: `{rows_csv_path}`.  Cells grouped by "
        f"`{factor_fields}`.  Generated by "
        f"`scripts/diagnostics/check_arrival_saturation.py`; rerun "
        f"the script to regenerate.\n"
    )
    out_lines.append(
        f"Thresholds: ARRIVAL-SATURATED if mean util "
        f"$\\ge$ {ARRIVAL_SATURATION_THRESHOLD:.2f}; NEAR-SATURATED "
        f"if $\\ge$ {NEAR_SATURATION_THRESHOLD:.2f}; otherwise "
        f"PLANNER-BOTTLENECKED.  See "
        f"`paper/sections/05_1_load_regime.md` for the load-regime "
        f"discussion.\n"
    )

    n_sat = 0
    n_total = 0

    # Build per-cell summary rows.
    table_rows: List[Tuple[Tuple[Any, ...], int, float, float, float, float, str]] = []
    for key, rs in sorted(rows_by_cell.items(), key=lambda kv: str(kv[0])):
        n_total += 1
        # Pull H + W from the first row's map_path (homogeneous
        # within a cell when ``map_path`` is one of the factor
        # fields).
        map_path_raw = rs[0].get("map_path") or ""
        map_path = Path(map_path_raw) if map_path_raw else Path("")
        h, w = _map_dimensions(map_path, map_cache)
        h_plus_w = h + w
        num_agents = int(rs[0].get("num_agents") or 0)
        theoretical_lambda = (
            float(num_agents) / float(h_plus_w) if h_plus_w > 0 else 0.0
        )
        util_values = [
            float(r["throughput_utilization"]) for r in rs
            if r.get("throughput_utilization") is not None
        ]
        if not util_values:
            # Fall back to throughput / arrival_rate_per_step if
            # the dataset predates the explicit utilisation column.
            util_values = []
            for r in rs:
                t = r.get("throughput")
                a = r.get("arrival_rate_per_step")
                if t is None or a is None or float(a) == 0.0:
                    continue
                util_values.append(float(t) / float(a))
        if not util_values:
            # Last resort: compute from theoretical lambda.
            util_values = []
            for r in rs:
                t = r.get("throughput")
                if t is None or theoretical_lambda == 0.0:
                    continue
                util_values.append(float(t) / theoretical_lambda)
        if not util_values:
            verdict = "MISSING-DATA"
            util_mean = float("nan")
            thpt_mean = float("nan")
        else:
            util_mean = sum(util_values) / len(util_values)
            thpt_mean = sum(
                float(r.get("throughput") or 0.0) for r in rs
            ) / len(rs)
            verdict = _verdict(util_mean)
        if verdict == "ARRIVAL-SATURATED":
            n_sat += 1
        table_rows.append((key, h_plus_w, theoretical_lambda, thpt_mean, util_mean, len(rs), verdict))

    out_lines.append(f"**Cells**: {n_total} total, "
                     f"{n_sat} arrival-saturated.\n")

    # Header
    header_cells = list(factor_fields) + [
        "H+W", "λ_sys", "mean throughput", "mean util.", "n_seeds", "verdict",
    ]
    out_lines.append("| " + " | ".join(header_cells) + " |")
    out_lines.append("|" + "|".join(["---"] * len(header_cells)) + "|")

    for key, h_plus_w, lam, thpt, util, n_seeds, verdict in table_rows:
        key_cells = []
        for f, v in zip(factor_fields, key):
            if f == "map_path" and isinstance(v, str):
                key_cells.append(_map_stem(v))
            else:
                key_cells.append(str(v))
        if util != util:  # NaN
            util_str = "—"
        else:
            util_str = f"{util:.3f}"
            if util >= ARRIVAL_SATURATION_THRESHOLD:
                util_str += " *"
        out_lines.append("| " + " | ".join(
            key_cells + [
                str(h_plus_w),
                f"{lam:.3f}",
                f"{thpt:.3f}" if thpt == thpt else "—",
                util_str,
                str(n_seeds),
                verdict,
            ]
        ) + " |")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    logger.info("wrote %s (%d cells, %d arrival-saturated)", out_path, n_total, n_sat)
    return n_sat


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--results-csv", type=Path,
        default=Path("logs/paper/solver_sensitivity/results.csv"),
        help="Per-run results.csv to audit.",
    )
    p.add_argument(
        "--out", type=Path,
        default=Path("reports/arrival_saturation_audit.md"),
        help="Where to write the audit report.",
    )
    p.add_argument(
        "--group-by", default="map_path,num_agents,horizon,global_solver",
        help=("Comma-separated list of CSV fields to group rows into "
              "cells.  Defaults to (map_path, num_agents, horizon, "
              "global_solver) -- the factor tuple paper Tables 1/2 "
              "use."),
    )
    p.add_argument(
        "--exit-nonzero-on-saturation", action="store_true",
        help=("Exit 2 if any cell is arrival-saturated.  Useful for "
              "CI to refuse to publish a paper table that reads "
              "throughput as a planner-discriminating metric in "
              "saturated cells without flagging them."),
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s | %(message)s",
    )

    if not args.results_csv.exists():
        logger.error("results.csv not found at %s", args.results_csv)
        return 1

    rows = load_rows(args.results_csv)
    factor_fields = tuple(f.strip() for f in args.group_by.split(",") if f.strip())
    by_cell = cells_grouped_by(rows, factor_fields)
    map_cache: Dict[Path, Tuple[int, int]] = {}
    n_sat = write_report(args.out, args.results_csv, factor_fields, by_cell, map_cache)
    if args.exit_nonzero_on_saturation and n_sat > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
