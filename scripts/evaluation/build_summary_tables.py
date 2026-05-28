#!/usr/bin/env python3
"""
Generate the paper's summary tables.

Two tables are supported:

  * **Table 1 — Tier-1 Solver Substitutability (paper §5.2).**
    Source: ``solver_sensitivity`` results.  Filter to ``H = 20``;
    aggregate per-(solver, map) across ``num_agents`` and seeds.
    Columns: throughput (mean ± 95 % CI), agent-attributable
    violations, exogenous-attributable violations, mean planning time.

  * **Table 2 — Per-Density Baseline Comparison (paper §5.5).**
    Source: ``baseline_comparison`` results filtered to
    ``warehouse-10-20-10-2-2``.  Per ``num_agents`` density bin and
    method, aggregate throughput, agent-attributable, exogenous-
    attributable violations, and wait fraction.

Both tables are emitted as ``.tex`` (booktabs LaTeX) and ``.md``
(GitHub-flavoured Markdown) files for paste-in-place use in the paper
source / supplementary README.
"""
from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger("paper_tables")


SOLVER_DISPLAY = {
    "cbsh2":          "CBSH2-RTC",
    "lacam_official": "LaCAM",
    "lacam3":         "LaCAM*",
    "lns2":           "MAPF-LNS2",
    "pbs":            "PBS",
    "pibt2":          "PIBT2",
}
METHOD_DISPLAY = {
    "ours":      "Ours (POE-LMAPF)",
    "rhcr":      "RHCR",
    "pibt2_fr":  "PIBT2-FR",
    "no_buffer": "No-Buffer",
}


# ---------------------------------------------------------------------------
# Helpers
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


def load_results(results_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with results_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            rows.append({k: _coerce(v) for k, v in raw.items()})
    logger.info("loaded %d rows from %s", len(rows), results_path)
    return rows


def filter_ok(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if (r.get("status") or "").lower() == "ok"]


def map_stem(value: Any) -> str:
    if not isinstance(value, str):
        return str(value)
    base = value.rsplit("/", 1)[-1]
    if base.endswith(".map"):
        base = base[:-4]
    return base


def _bootstrap_ci(values: Sequence[float], n_boot: int = 2000,
                  alpha: float = 0.05) -> Tuple[float, float, float]:
    arr = np.asarray([v for v in values if v is not None and not np.isnan(v)],
                     dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    if arr.size == 1:
        return (float(arr[0]), float(arr[0]), float(arr[0]))
    rng = np.random.default_rng(0)
    boot_means = rng.choice(arr, size=(n_boot, arr.size), replace=True).mean(axis=1)
    lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])
    return (float(arr.mean()), float(lo), float(hi))


def _fmt(mean: float, lo: float, hi: float, digits: int = 3) -> str:
    if any(np.isnan([mean, lo, hi])):
        return "—"
    half = 0.5 * (hi - lo)
    return f"{mean:.{digits}f} ± {half:.{digits}f}"


# ---------------------------------------------------------------------------
# System-health diagnostics (P9 follow-up)
#
# The simulator emits ``deadlock_count`` (per-run agent count whose
# safety-wait streak crossed the threshold) and
# ``global_no_progress_steps`` (per-run tick count where every agent
# with an active assignment failed to advance).  Neither appeared in
# the paper's Table 1 / Table 2 even though both are nonzero in
# every high-density run -- throughput is task-arrival-limited at
# those densities and masks the loss of fleet capacity.  The
# functions below compute three per-cell summaries from the per-run
# values:
#
#   * deadlock_count_mean     -- mean ± CI across seeds (renders
#                                like the existing throughput column).
#   * fraction_with_deadlock  -- fraction of seeds whose
#                                ``deadlock_count`` is strictly
#                                positive.  Renders as percentage.
#   * max_deadlock_count      -- worst-seed deadlock count.  Renders
#                                as integer (no CI).
#
# These are computed per (map, num_agents, method/solver) cell and
# emitted as additional table columns + into the dedicated
# system-health section under ``paper/sections/``.
# ---------------------------------------------------------------------------


def _fraction_with_deadlock(values: Sequence[float]) -> float:
    """Per-cell fraction of seeds with ``deadlock_count > 0``."""
    if not values:
        return float("nan")
    return sum(1 for v in values if v and float(v) > 0) / float(len(values))


def _max_deadlock(values: Sequence[float]) -> int:
    """Per-cell worst-seed deadlock count."""
    if not values:
        return 0
    return int(max(float(v) for v in values))


def _fmt_pct(p: float, digits: int = 0) -> str:
    if p != p:  # NaN
        return "—"
    return f"{p * 100:.{digits}f}%"


# ---------------------------------------------------------------------------
# Table 1 — solver substitutability at H = 20
# ---------------------------------------------------------------------------


# Per-cell health columns appended to every results table (P9).
# Each entry is (field, label, digits, kind) where kind is:
#   "ci"  -> bootstrap mean ± CI across seeds
#   "max" -> worst-seed scalar
#   "pct" -> fraction-of-seeds-with-X * 100
HEALTH_COLS: Tuple[Tuple[str, str, int, str], ...] = (
    ("deadlock_count",          "Deadlock count",        2, "ci"),
    ("deadlock_count",          "Frac. runs with DL",    0, "pct"),
    ("deadlock_count",          "Max DL count",          0, "max"),
    ("global_no_progress_steps", "GNP steps",            1, "ci"),
)


def _render_health_cell(
    field: str, digits: int, kind: str, rs: Sequence[Dict[str, Any]],
) -> str:
    """Render the health-column cell for one (cell, method/solver)
    bucket.  ``rs`` is the list of per-seed rows in that bucket.
    ``kind`` selects the rendering:
      * ``ci``  -> bootstrap mean ± CI;
      * ``max`` -> worst-seed integer;
      * ``pct`` -> percentage of seeds with strictly positive value.
    Returns the cell string ("—" on empty data)."""
    values_raw = [r.get(field) for r in rs if r.get(field) is not None]
    if not values_raw:
        return "—"
    values = [float(v) for v in values_raw]
    if kind == "ci":
        mean, lo, hi = _bootstrap_ci(values)
        return _fmt(mean, lo, hi, digits=digits)
    if kind == "max":
        return str(_max_deadlock(values))
    if kind == "pct":
        return _fmt_pct(_fraction_with_deadlock(values), digits=digits)
    raise ValueError(f"unknown health-column kind: {kind!r}")


COLS_T1 = [
    ("throughput",                       "Throughput",                3),
    # P10 load-regime: throughput_utilization >= 1.0 (within a
    # tolerance) means the cell is arrival-saturated and throughput
    # here measures the task arrival cap, not planner capacity.
    # Visual flagging (asterisk + ARRIVAL-SATURATED legend) is
    # applied by ``_render_utilization_cell``.
    ("throughput_utilization",           "Util.",                     2),
    ("violations_agent_attributable",    "Agent-attr. violations",    1),
    ("violations_exogenous_attributable", "Exo-attr. violations",     1),
    ("mean_planning_time_ms",            "Mean planning time (ms)",   1),
]


# P10 visual-flag threshold.  A cell whose per-seed mean
# throughput_utilization is at or above this value is considered
# arrival-saturated; the renderer appends a trailing asterisk to
# the cell string so the reader can scan the table for the marker
# without recomputing the ratio.  The threshold is 0.95 (not 1.0)
# because per-run utilization can land slightly below 1.0 due to
# the initial task-batch warmup (one task per agent at step 0
# inflates total_released_tasks for the first 100 ticks before
# the exponential arrival catches up).
ARRIVAL_SATURATION_THRESHOLD: float = 0.95


def _render_utilization_cell(values: Sequence[float]) -> str:
    """Render the throughput_utilization column for one cell.
    Bootstrap mean ± CI; append a trailing asterisk when the mean
    crosses ``ARRIVAL_SATURATION_THRESHOLD`` so a reader can scan
    the table for arrival-saturated cells in O(eyeballs)."""
    if not values:
        return "—"
    arr = [float(v) for v in values]
    mean, lo, hi = _bootstrap_ci(arr)
    cell = _fmt(mean, lo, hi, digits=2)
    if mean >= ARRIVAL_SATURATION_THRESHOLD:
        return f"{cell}*"
    return cell


def build_table1(rows: List[Dict[str, Any]]) -> Dict[str, List[List[str]]]:
    sub = [
        r for r in rows
        if (r.get("horizon") == 20)
    ]
    maps = sorted({map_stem(r.get("map_path")) for r in sub})
    solvers = sorted({r.get("global_solver") for r in sub if r.get("global_solver")})

    out: Dict[str, List[List[str]]] = {}
    for mp in maps:
        rows_mp = [r for r in sub if map_stem(r.get("map_path")) == mp]
        body: List[List[str]] = []
        for solver in solvers:
            rs = [r for r in rows_mp if r.get("global_solver") == solver]
            if not rs:
                continue
            row_cells: List[str] = [SOLVER_DISPLAY.get(solver, solver)]
            for field, _, digits in COLS_T1:
                values = [r.get(field) for r in rs if r.get(field) is not None]
                # P10: route throughput_utilization through the
                # arrival-saturation renderer (appends * to the
                # cell string when mean util >= threshold).
                if field == "throughput_utilization":
                    row_cells.append(_render_utilization_cell(
                        [float(v) for v in values if v is not None]
                    ))
                    continue
                mean, lo, hi = _bootstrap_ci([float(v) for v in values
                                              if v is not None])
                row_cells.append(_fmt(mean, lo, hi, digits=digits))
            # P9 health columns -- appended after the throughput /
            # violations block so column order matches the reader's
            # mental model: "throughput first, safety next, agent-
            # level progress last".
            for field, _, digits, kind in HEALTH_COLS:
                row_cells.append(_render_health_cell(field, digits, kind, rs))
            body.append(row_cells)
        out[mp] = body
    return out


# ---------------------------------------------------------------------------
# Table 2 — baseline comparison on warehouse-10-20-10-2-2
# ---------------------------------------------------------------------------


COLS_T2 = [
    ("throughput",                       "Throughput",                3),
    # P10 load-regime: see comment on COLS_T1.
    ("throughput_utilization",           "Util.",                     2),
    ("violations_agent_attributable",    "Agent-attr.",               1),
    ("violations_exogenous_attributable", "Exo-attr.",                1),
    ("wait_fraction",                    "Wait fraction",             3),
]
TABLE2_MAP = "warehouse-10-20-10-2-2"


def build_table2(rows: List[Dict[str, Any]]) -> Dict[int, List[List[str]]]:
    sub = [r for r in rows if map_stem(r.get("map_path")) == TABLE2_MAP]
    densities = sorted({r.get("num_agents") for r in sub
                        if r.get("num_agents") is not None})
    methods = ["ours", "rhcr", "pibt2_fr", "no_buffer"]

    out: Dict[int, List[List[str]]] = {}
    for d in densities:
        rows_d = [r for r in sub if r.get("num_agents") == d]
        body: List[List[str]] = []
        for method in methods:
            rs = [r for r in rows_d if r.get("method") == method]
            if not rs:
                continue
            row_cells: List[str] = [METHOD_DISPLAY[method]]
            for field, _, digits in COLS_T2:
                values = [r.get(field) for r in rs if r.get(field) is not None]
                # P10: same routing as build_table1 -- see comment there.
                if field == "throughput_utilization":
                    row_cells.append(_render_utilization_cell(
                        [float(v) for v in values if v is not None]
                    ))
                    continue
                mean, lo, hi = _bootstrap_ci([float(v) for v in values
                                              if v is not None])
                row_cells.append(_fmt(mean, lo, hi, digits=digits))
            # P9 health columns -- see comment in build_table1.
            for field, _, digits, kind in HEALTH_COLS:
                row_cells.append(_render_health_cell(field, digits, kind, rs))
            body.append(row_cells)
        out[int(d)] = body
    return out


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _md_table(headers: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    out = [line, sep]
    for row in body:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def _tex_table(headers: Sequence[str], body: Sequence[Sequence[str]],
               caption: str, label: str) -> str:
    n = len(headers)
    col_spec = "l" + "r" * (n - 1)
    lines = [
        r"\begin{table}[t]", r"\centering", r"\small",
        r"\begin{tabular}{" + col_spec + "}",
        r"\toprule",
        " & ".join(_tex_escape(h) for h in headers) + r" \\",
        r"\midrule",
    ]
    for row in body:
        lines.append(" & ".join(_tex_escape(c) for c in row) + r" \\")
    lines += [
        r"\bottomrule", r"\end{tabular}",
        rf"\caption{{{caption}}}", rf"\label{{{label}}}",
        r"\end{table}",
    ]
    return "\n".join(lines)


def _tex_escape(s: str) -> str:
    return (str(s)
            .replace("&", r"\&")
            .replace("%", r"\%")
            .replace("_", r"\_")
            .replace("±", r"$\pm$"))


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def emit_table1(results_path: Path, out_dir: Path) -> None:
    rows = filter_ok(load_results(results_path))
    grouped = build_table1(rows)
    headers = (
        ["Solver"]
        + [c[1] for c in COLS_T1]
        + [c[1] for c in HEALTH_COLS]
    )

    md_chunks = ["# Paper Table 1 — Tier-1 Solver Substitutability ($H = 20$)\n"]
    tex_chunks: List[str] = []
    # P9 footnote: per (H, map) cell, compute the worst-case mean
    # deadlock_count across solvers so the reader sees the
    # agent-level progress signal alongside throughput.  The
    # footnote acknowledges that the §5.2 sweep at H=20 / low
    # density may show zero deadlocks while higher-density sweeps
    # do not -- system_health.{md,tex} carries the cross-density
    # picture.
    rows_all_h20 = [r for r in rows if r.get("horizon") == 20]
    for mp, body in grouped.items():
        md_chunks.append(f"## {mp}\n")
        md_chunks.append(_md_table(headers, body))
        # Per-cell footnote: mean across (seed, solver) of
        # deadlock_count for this (H=20, map) cell.  Locked to the
        # phrasing the P9 task spec calls for so a reviewer can
        # cite it directly.
        cell_rows = [r for r in rows_all_h20
                     if map_stem(r.get("map_path")) == mp]
        cell_dl = [float(r.get("deadlock_count") or 0) for r in cell_rows
                   if r.get("deadlock_count") is not None]
        cell_dl_mean = (sum(cell_dl) / len(cell_dl)) if cell_dl else 0.0
        cell_gnp = [float(r.get("global_no_progress_steps") or 0)
                    for r in cell_rows
                    if r.get("global_no_progress_steps") is not None]
        cell_gnp_mean = (sum(cell_gnp) / len(cell_gnp)) if cell_gnp else 0.0
        md_chunks.append(
            f"_Per-cell health footnote ($H=20$, ${mp}$): mean "
            f"`deadlock_count` across seeds + solvers is "
            f"{cell_dl_mean:.2f}; mean `global_no_progress_steps` is "
            f"{cell_gnp_mean:.1f}.  See `paper/sections/05_4_system_health.md` "
            f"for the full table including high-density (|M| ≥ 100) cells "
            f"where these counters become the dominant signal of "
            f"agent-level progress; under the §5.2 conditions reported "
            f"here both counters may legitimately be zero._"
        )
        md_chunks.append("")
        tex_chunks.append(_tex_table(
            headers, body,
            caption=(
                f"Tier-1 Solver Substitutability at $H = 20$ on {mp}.  "
                f"Per-cell deadlock\\_count mean across seeds + solvers: "
                f"{cell_dl_mean:.2f}; per-cell global\\_no\\_progress\\_steps "
                f"mean: {cell_gnp_mean:.1f}.  See "
                r"\S5.4 (System Health Indicators) for the full table."
            ),
            label=f"tab:solver_subst_{mp}",
        ))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "table1_solver_substitutability.md").write_text(
        "\n".join(md_chunks) + "\n", encoding="utf-8")
    (out_dir / "table1_solver_substitutability.tex").write_text(
        "\n\n".join(tex_chunks) + "\n", encoding="utf-8")
    logger.info("table 1 emitted under %s", out_dir)


def emit_table2(results_path: Path, out_dir: Path) -> None:
    rows = filter_ok(load_results(results_path))
    grouped = build_table2(rows)
    headers = (
        ["Method"]
        + [c[1] for c in COLS_T2]
        + [c[1] for c in HEALTH_COLS]
    )

    md_chunks = [f"# Paper Table 2 — Baseline comparison on {TABLE2_MAP}\n"]
    tex_chunks: List[str] = []
    for density, body in grouped.items():
        md_chunks.append(f"## $|M| = {density}$\n")
        md_chunks.append(_md_table(headers, body))
        md_chunks.append("")
        tex_chunks.append(_tex_table(
            headers, body,
            caption=(f"Baseline comparison at $|M|={density}$ on "
                     rf"{TABLE2_MAP}."),
            label=f"tab:baselines_{density}",
        ))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "table2_baseline_comparison.md").write_text(
        "\n".join(md_chunks) + "\n", encoding="utf-8")
    (out_dir / "table2_baseline_comparison.tex").write_text(
        "\n\n".join(tex_chunks) + "\n", encoding="utf-8")
    logger.info("table 2 emitted under %s", out_dir)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="POE-LMAPF paper summary tables")
    p.add_argument("--results", required=True, type=Path,
                   help="Directory containing results.csv")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory for table .tex / .md files")
    p.add_argument("--table", choices=["1", "2", "all"], default="all")
    p.add_argument("--log-level", type=str, default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(levelname)s %(name)s | %(message)s")

    results_path = args.results / "results.csv" if args.results.is_dir() else args.results
    if not results_path.exists():
        logger.error("results.csv not found at %s", results_path)
        return 2

    if args.table in ("1", "all"):
        emit_table1(results_path, args.out)
    if args.table in ("2", "all"):
        emit_table2(results_path, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
