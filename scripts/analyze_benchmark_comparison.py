"""Allocator-bounded-fraction quantification.

Reads two CSVs:

* ``raw_measurements.csv`` — simulator-driven calibration cells from
  ``calibrate_solver_budgets.py``.
* ``raw_measurements_benchmark.csv`` — Stern .scen-driven cells from
  ``calibrate_solver_benchmarks.py``.

Emits ``allocator_bound_quantification.md`` with:

1. Per-cell completion-rate comparison (sim vs bench) for every
   (solver, map, |M|).
2. Allocator-bounded fraction = ``bench_rate - sim_rate`` clamped to
   ``[0, 1]``.  A large positive value means the simulator's task
   allocator is generating instances harder than Stern's canonical
   benchmark — i.e. the simulator-driven failure is *allocator-bound*,
   not solver-bound.
3. Per-solver headline: aggregate sim vs bench across all cells.
4. Sanity-check tables: LaCAM\\* per-cell completion (target ≥95%)
   and per-cell p50 timing (target sub-second on most cells).

This script does NOT modify any wrapper, parser, or solver.  It is an
analysis-only consumer of the two raw_measurements\\* CSVs.
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SimKey = Tuple[str, str, int]  # (solver, map, num_agents)


def _f(s: str, default: float = math.nan) -> float:
    if s == "" or s is None:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _is_complete(status: str) -> bool:
    return status in {"complete", "partial_anytime"}


def _percentile(values: List[float], p: float) -> Optional[float]:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return None
    vals = sorted(vals)
    if len(vals) == 1:
        return vals[0]
    rank = (p / 100.0) * (len(vals) - 1)
    lo, hi = int(math.floor(rank)), int(math.ceil(rank))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (rank - lo)


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[SimKey, Dict[str, Any]]:
    cells: Dict[SimKey, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        try:
            key = (r["solver"], r["map"], int(r["num_agents"]))
        except (KeyError, ValueError):
            continue
        cells[key].append(r)

    out: Dict[SimKey, Dict[str, Any]] = {}
    for key, cell_rows in cells.items():
        n_total = len(cell_rows)
        n_complete = sum(1 for r in cell_rows if _is_complete(r["status"]))
        sw_complete = [
            _f(r["solver_wall_ms"]) for r in cell_rows
            if _is_complete(r["status"])
            and not math.isnan(_f(r["solver_wall_ms"]))
        ]
        status_counter = Counter(r["status"] for r in cell_rows)
        # Bucketed error taxonomy (first 60 chars)
        err_tax: Counter = Counter()
        for r in cell_rows:
            if not _is_complete(r["status"]):
                msg = (r.get("error_msg") or "").strip()
                bucket = msg[:60] if msg else "(empty)"
                err_tax[bucket] += 1

        out[key] = {
            "n_total": n_total,
            "n_complete": n_complete,
            "completion_rate": n_complete / n_total if n_total else 0.0,
            "sw_p50_ms": _percentile(sw_complete, 50),
            "sw_p95_ms": _percentile(sw_complete, 95),
            "status_counter": dict(status_counter),
            "error_taxonomy": dict(err_tax),
        }
    return out


def _fmt_rate(rate: float) -> str:
    return f"{rate:.0%}"


def _fmt_p(v: Optional[float]) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    if v >= 1000.0:
        return f"{v / 1000.0:.2f} s"
    return f"{v:.0f} ms"


def _fmt_delta(d: float) -> str:
    pct = d * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f} pp"


def _build_per_cell_table(
    sim: Dict[SimKey, Dict[str, Any]],
    bench: Dict[SimKey, Dict[str, Any]],
) -> List[str]:
    """Per-cell sim vs bench completion comparison."""
    keys = sorted(set(sim) | set(bench))
    lines: List[str] = []
    lines.append("| Solver | Map | \\|M\\| | sim n | sim rate | bench n | "
                 "bench rate | Δ (bench − sim) | Allocator-bounded |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for key in keys:
        s = sim.get(key)
        b = bench.get(key)
        sim_n = s["n_total"] if s else 0
        sim_rate = s["completion_rate"] if s else float("nan")
        bench_n = b["n_total"] if b else 0
        bench_rate = b["completion_rate"] if b else float("nan")

        if s is None or b is None:
            delta_str = "—"
            verdict = "incomparable (one side missing)"
        else:
            delta = bench_rate - sim_rate
            delta_str = _fmt_delta(delta)
            if delta >= 0.20:
                verdict = "**Yes** — allocator-bound"
            elif delta >= 0.05:
                verdict = "Partial — some allocator drag"
            elif delta > -0.05:
                verdict = "No — solver-bound"
            else:
                verdict = "Inverted — bench harder than sim (?)"

        sim_rate_s = _fmt_rate(sim_rate) if s else "—"
        bench_rate_s = _fmt_rate(bench_rate) if b else "—"
        lines.append(
            f"| {key[0]} | {key[1]} | {key[2]} | {sim_n} | {sim_rate_s} | "
            f"{bench_n} | {bench_rate_s} | {delta_str} | {verdict} |"
        )
    return lines


def _build_per_solver_summary(
    sim: Dict[SimKey, Dict[str, Any]],
    bench: Dict[SimKey, Dict[str, Any]],
) -> List[str]:
    by_solver: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"sim_n": 0, "sim_c": 0, "bench_n": 0, "bench_c": 0,
                 "cells": 0, "allocator_bound_cells": 0}
    )
    keys = sorted(set(sim) | set(bench))
    for key in keys:
        solver = key[0]
        s = sim.get(key)
        b = bench.get(key)
        if s:
            by_solver[solver]["sim_n"] += s["n_total"]
            by_solver[solver]["sim_c"] += s["n_complete"]
        if b:
            by_solver[solver]["bench_n"] += b["n_total"]
            by_solver[solver]["bench_c"] += b["n_complete"]
        if s and b:
            by_solver[solver]["cells"] += 1
            if (b["completion_rate"] - s["completion_rate"]) >= 0.20:
                by_solver[solver]["allocator_bound_cells"] += 1

    lines: List[str] = []
    lines.append("| Solver | sim invocations | sim rate | bench invocations | "
                 "bench rate | Aggregate Δ | Allocator-bound cells |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for solver in sorted(by_solver):
        v = by_solver[solver]
        sim_rate = v["sim_c"] / max(1, v["sim_n"]) if v["sim_n"] else float("nan")
        bench_rate = v["bench_c"] / max(1, v["bench_n"]) if v["bench_n"] else float("nan")
        delta = bench_rate - sim_rate if v["sim_n"] and v["bench_n"] else float("nan")
        sim_rate_s = _fmt_rate(sim_rate) if v["sim_n"] else "—"
        bench_rate_s = _fmt_rate(bench_rate) if v["bench_n"] else "—"
        delta_s = _fmt_delta(delta) if not math.isnan(delta) else "—"
        ab_str = f"{v['allocator_bound_cells']}/{v['cells']}" if v["cells"] else "—"
        lines.append(
            f"| {solver} | {v['sim_n']} | {sim_rate_s} | {v['bench_n']} | "
            f"{bench_rate_s} | {delta_s} | {ab_str} |"
        )
    return lines


def _lacam_star_sanity(
    bench: Dict[SimKey, Dict[str, Any]],
) -> Tuple[List[str], bool]:
    """Per-cell LaCAM\\* (lacam3) completion + p50 timing on benchmark CSV.

    Sanity-check thresholds from the task spec:
    * completion ≥ 95% across all benchmark cells
    * p50 timing sub-second on most cells

    Returns (lines, all_passed).
    """
    keys = sorted(k for k in bench if k[0] == "lacam3")
    lines: List[str] = []
    if not keys:
        lines.append("_No `lacam3` benchmark cells in the input — sanity skipped._")
        return lines, True
    lines.append("| Map | \\|M\\| | n | completion | p50 | p95 | "
                 "≥95% rate? | sub-second p50? |")
    lines.append("|---|---:|---:|---:|---:|---:|---|---|")
    all_passed = True
    for key in keys:
        s = bench[key]
        rate = s["completion_rate"]
        p50 = s["sw_p50_ms"]
        p95 = s["sw_p95_ms"]
        rate_ok = rate >= 0.95
        p50_ok = p50 is not None and p50 < 1000.0
        if not rate_ok:
            all_passed = False
        lines.append(
            f"| {key[1]} | {key[2]} | {s['n_total']} | {_fmt_rate(rate)} | "
            f"{_fmt_p(p50)} | {_fmt_p(p95)} | "
            f"{'yes' if rate_ok else '**NO**'} | "
            f"{'yes' if p50_ok else 'no'} |"
        )
    return lines, all_passed


def _build_doc(
    sim: Dict[SimKey, Dict[str, Any]],
    bench: Dict[SimKey, Dict[str, Any]],
    sim_csv: Path, bench_csv: Path,
) -> str:
    sim_total = sum(s["n_total"] for s in sim.values())
    bench_total = sum(s["n_total"] for s in bench.values())
    sim_complete = sum(s["n_complete"] for s in sim.values())
    bench_complete = sum(s["n_complete"] for s in bench.values())

    lines: List[str] = []
    lines.append("# Allocator-bounded fraction quantification")
    lines.append("")
    lines.append(
        "Per-cell comparison of solver completion under two regimes:"
    )
    lines.append("")
    lines.append(
        f"* **Simulator-driven** ({sim_csv}): {sim_total} `plan_with_metadata` "
        f"invocations from the calibration harness, "
        f"{sim_complete} successful "
        f"({(sim_complete / sim_total) if sim_total else 0:.1%})."
    )
    lines.append(
        f"* **Stern benchmark-driven** ({bench_csv}): {bench_total} "
        f"`plan_with_metadata` invocations from .scen records, "
        f"{bench_complete} successful "
        f"({(bench_complete / bench_total) if bench_total else 0:.1%})."
    )
    lines.append("")
    lines.append(
        "The gap (`bench_rate − sim_rate`) is the **allocator-bounded "
        "fraction** for that cell.  A large positive value means the "
        "task allocator is generating harder-than-Stern instances and the "
        "simulator-driven failure is allocator-bound, not solver-bound."
    )
    lines.append("")
    lines.append("Verdict thresholds:")
    lines.append("")
    lines.append("* Δ ≥ 20 pp: **allocator-bound** (simulator failure not the solver's fault)")
    lines.append("* 5 pp ≤ Δ < 20 pp: partial allocator drag")
    lines.append("* −5 pp < Δ < 5 pp: solver-bound (allocator not at fault)")
    lines.append("* Δ ≤ −5 pp: bench harder than sim (unexpected — investigate)")
    lines.append("")

    # Per-solver headline
    lines.append("## Per-solver headline")
    lines.append("")
    lines.extend(_build_per_solver_summary(sim, bench))
    lines.append("")

    # Per-cell breakdown
    lines.append("## Per-cell breakdown")
    lines.append("")
    lines.extend(_build_per_cell_table(sim, bench))
    lines.append("")

    # LaCAM* sanity
    lines.append("## Sanity check — LaCAM\\* (`lacam3`) on benchmark cells")
    lines.append("")
    lines.append(
        "Stern .scen instances are the canonical comparison cohort for "
        "all current MAPF papers; LaCAM\\* should solve ≥95% of them with "
        "sub-second p50 timing.  A failure on this table means the wrapper "
        "or binary is broken, not the allocator."
    )
    lines.append("")
    sanity_lines, sanity_pass = _lacam_star_sanity(bench)
    lines.extend(sanity_lines)
    lines.append("")
    if sanity_pass:
        lines.append("**Sanity check passed.**  LaCAM\\* meets the ≥95% bar on every "
                     "benchmark cell where it was measured.")
    else:
        lines.append("**Sanity check FAILED.**  At least one cell is below 95% "
                     "completion.  Investigate before relying on the allocator-"
                     "bounded fraction interpretation.")
    lines.append("")

    # Reading guide for §5.4
    lines.append("## Implications for §5.4")
    lines.append("")
    lines.append(
        "If the per-solver headline shows a large positive Δ (bench > sim) "
        "for LaCAM\\* and other non-anytime solvers, the §5.4 \"completion "
        "rate vs density\" curves should be reframed as a measurement of "
        "the *allocator + solver* pipeline, not the solver alone.  The "
        "Stern benchmark cells provide the canonical solver-only baseline; "
        "the gap to the simulator-driven cells is the allocator's "
        "contribution to apparent solver failure."
    )
    lines.append("")
    lines.append(
        "If the headline Δ is small (≤5 pp), the simulator-driven cells "
        "are a faithful proxy for solver completion and §5.4 can stand "
        "as-is."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-in", type=Path, required=True,
                        help="raw_measurements.csv (simulator-driven)")
    parser.add_argument("--bench-in", type=Path, required=True,
                        help="raw_measurements_benchmark.csv (Stern .scen-driven)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory (allocator_bound_quantification.md "
                             "lands here)")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    sim_rows = _read_rows(args.sim_in)
    bench_rows = _read_rows(args.bench_in)
    print(f"loaded {len(sim_rows)} sim rows from {args.sim_in}")
    print(f"loaded {len(bench_rows)} bench rows from {args.bench_in}")

    sim = _aggregate(sim_rows)
    bench = _aggregate(bench_rows)
    print(f"sim cells: {len(sim)}; bench cells: {len(bench)}")

    doc = _build_doc(sim, bench, args.sim_in, args.bench_in)
    out_path = args.out / "allocator_bound_quantification.md"
    out_path.write_text(doc)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
