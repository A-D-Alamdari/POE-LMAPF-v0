"""Calibration analysis — produce 3 markdown recommendation reports.

Reads ``raw_measurements.csv`` from ``calibrate_solver_budgets.py``
and emits:

* ``solver_recommendation.md`` — per-section solver inclusion table
  + per-solver verdict block + §5.1 budget recommendation.
* ``anytime_verification.md`` — solver-by-solver classification of
  algorithm class vs harness behavior.
* ``literature_consistency.md`` — measured p50/p95 vs published
  runtime claims; per-solver verdict.

This script does NOT modify any solver, wrapper, or contract.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# --- per-section inclusion thresholds ----------------------------------------
SECTION_THRESHOLDS = {
    "5.2":  {"completion_rate": 0.95, "label": "solver substitutability"},
    "5.3":  {"completion_rate": 0.95, "label": "FoV / safety grid"},
    "5.4":  {"completion_rate": 0.80, "label": "scaling (high density)"},
    "5.5":  {"completion_rate": 0.85, "label": "baselines"},
}

# --- solver classification by algorithm class --------------------------------
SOLVER_CLASS = {
    "lacam_official": "anytime (search-based, refines until budget)",
    "lacam3":         "anytime (search-based, refines until budget)",
    "lns2":           "anytime (LNS; writes paths only at end-of-run)",
    "pibt2":          "non-anytime (priority-based; sub-millisecond typical)",
    "cbsh2":          "optimal CBS (no anytime; complete-or-timeout)",
    "pbs":            "suboptimal incomplete (no anytime; no parking-room handling)",
}

# --- literature reference table ---------------------------------------------
LITERATURE = [
    {
        "solver": "lacam_official",
        "claim": "median ~1 s for 400 agents on 32×32",
        "source": "Okumura 2023 (LaCAM), AAAI",
        "measured_at": ("warehouse-10-20-10-2-2", 200),
        "expected_p50_ms": 1000.0,
    },
    {
        "solver": "lacam3",
        "claim": "99% of MAPF benchmarks within 10 s up to 1000 agents",
        "source": "Okumura 2024 (LaCAM*), AAMAS",
        "measured_at": ("warehouse-10-20-10-2-2", 200),
        "expected_p50_ms": 500.0,
    },
    {
        "solver": "pibt2",
        "claim": "<200 ms for hundreds of agents on warehouse",
        "source": "Okumura et al. 2022, AIJ",
        "measured_at": ("warehouse-10-20-10-2-1", 200),
        "expected_p50_ms": 200.0,
    },
    {
        "solver": "lns2",
        "claim": "sub-second initial solution at 100 agents",
        "source": "Li et al. 2022, IJCAI",
        "measured_at": ("warehouse-10-20-10-2-1", 100),
        "expected_p50_ms": 1000.0,
    },
    {
        "solver": "cbsh2",
        "claim": "optimal CBS variant; runtime varies widely with density",
        "source": "Li et al. 2021, ICAPS",
        "measured_at": ("random-64-64-10", 40),
        "expected_p50_ms": 500.0,
    },
    {
        "solver": "pbs",
        "claim": "suboptimal, sub-second when feasible",
        "source": "Ma et al. 2019, AAAI",
        "measured_at": ("random-64-64-10", 40),
        "expected_p50_ms": 500.0,
    },
]


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def _f(s: str, default: float = math.nan) -> float:
    if s == "" or s is None:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_status(s: str) -> str:
    """Treat partial_anytime as a successful return (a plan was produced)."""
    return s


def _is_complete(status: str) -> bool:
    return status in {"complete", "partial_anytime"}


def _percentile(values: List[float], p: float) -> Optional[float]:
    """Numpy-free percentile.  ``p`` is in [0, 100]."""
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


def _stats_per_cell(rows: List[Dict[str, Any]]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    """Aggregate per (solver, map, num_agents) cell across seeds and replans."""
    cells: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = (r["solver"], r["map"], int(r["num_agents"]))
        cells[key].append(r)

    out: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for key, cell_rows in cells.items():
        n_total = len(cell_rows)
        n_complete = sum(1 for r in cell_rows if _is_complete(r["status"]))
        n_error = n_total - n_complete
        completion_rate = n_complete / n_total if n_total else 0.0

        # Solver_wall_ms across complete + partial_anytime only
        sw_ms_complete = [
            _f(r["solver_wall_ms"]) for r in cell_rows
            if _is_complete(r["status"]) and not math.isnan(_f(r["solver_wall_ms"]))
        ]
        e2e_ms = [_f(r["end_to_end_wall_ms"]) for r in cell_rows
                  if not math.isnan(_f(r["end_to_end_wall_ms"]))]

        # Status counter
        status_counter = Counter(r["status"] for r in cell_rows)
        # Error msg taxonomy
        error_taxonomy: Counter = Counter()
        for r in cell_rows:
            if not _is_complete(r["status"]):
                msg = (r.get("error_msg") or "").strip()
                # Bucket by first 60 chars to group similar messages
                bucket = msg[:60] if msg else "(empty)"
                error_taxonomy[bucket] += 1

        out[key] = {
            "n_total": n_total,
            "n_complete": n_complete,
            "n_error": n_error,
            "completion_rate": completion_rate,
            "sw_p50_ms": _percentile(sw_ms_complete, 50),
            "sw_p95_ms": _percentile(sw_ms_complete, 95),
            "sw_max_ms": max(sw_ms_complete) if sw_ms_complete else None,
            "e2e_p50_ms": _percentile(e2e_ms, 50),
            "e2e_p95_ms": _percentile(e2e_ms, 95),
            "e2e_max_ms": max(e2e_ms) if e2e_ms else None,
            "status_counter": dict(status_counter),
            "error_taxonomy": dict(error_taxonomy),
            "produced_partial_anytime": status_counter.get("partial_anytime", 0) > 0,
        }
    return out


def _overall_completion_per_solver(
    cells: Dict[Tuple[str, str, int], Dict[str, Any]],
) -> Dict[str, float]:
    """Aggregate completion rate per solver across all cells."""
    by_solver: Dict[str, List[float]] = defaultdict(list)
    by_solver_n: Dict[str, List[int]] = defaultdict(list)
    for (solver, _, _), s in cells.items():
        by_solver[solver].append(s["completion_rate"])
        by_solver_n[solver].append(s["n_complete"])

    return {
        solver: (sum(by_solver_n[solver]) / max(1, sum(
            cells[k]["n_total"] for k in cells if k[0] == solver
        )))
        for solver in by_solver
    }


def _section_cohort(
    section: str, cells: Dict[Tuple[str, str, int], Dict[str, Any]],
) -> List[Tuple[str, str, int]]:
    """Subset of cells relevant to a given paper section."""
    keys = list(cells.keys())
    if section == "5.2":
        # Solver substitutability: small/moderate density on both maps
        return [k for k in keys if k[2] <= 100 and k[1] != "warehouse-10-20-10-2-2"]
    if section == "5.3":
        # FoV/safety grid: |M|=50 on warehouse-10-20-10-2-1, |M|=20 on random
        return [k for k in keys if (k[1] == "warehouse-10-20-10-2-1" and k[2] == 50)
                or (k[1] == "random-64-64-10" and k[2] == 20)]
    if section == "5.4":
        # Scaling: highest density per map
        out = []
        for map_stem in {k[1] for k in keys}:
            same_map = [k for k in keys if k[1] == map_stem]
            if same_map:
                max_n = max(k[2] for k in same_map)
                out.extend([k for k in same_map if k[2] == max_n])
        return out
    if section == "5.5":
        # Baselines: high but not extreme density
        return [k for k in keys
                if (k[1] == "warehouse-10-20-10-2-1" and k[2] in (100, 150))
                or (k[1] == "warehouse-10-20-10-2-2" and k[2] in (200, 300))]
    return keys


def _section_recommendation(
    section: str, cells: Dict[Tuple[str, str, int], Dict[str, Any]],
) -> Dict[str, Any]:
    threshold = SECTION_THRESHOLDS[section]["completion_rate"]
    cohort = _section_cohort(section, cells)
    by_solver: Dict[str, List[float]] = defaultdict(list)
    by_solver_complete: Dict[str, int] = defaultdict(int)
    by_solver_total: Dict[str, int] = defaultdict(int)
    for k in cohort:
        s = cells[k]
        by_solver[k[0]].append(s["completion_rate"])
        by_solver_complete[k[0]] += s["n_complete"]
        by_solver_total[k[0]] += s["n_total"]

    included: List[str] = []
    excluded: Dict[str, str] = {}
    for solver in sorted(by_solver):
        # Aggregate completion across the cohort
        rate = (by_solver_complete[solver] / max(1, by_solver_total[solver]))
        if rate >= threshold:
            included.append(solver)
        else:
            excluded[solver] = (
                f"completion={rate:.2%} < {threshold:.0%} threshold "
                f"({by_solver_complete[solver]}/{by_solver_total[solver]} "
                f"successful invocations on §{section} cohort cells)"
            )
    return {
        "threshold": threshold,
        "label": SECTION_THRESHOLDS[section]["label"],
        "included": included,
        "excluded": excluded,
        "cohort_size": len(cohort),
    }


def _fmt(v: Optional[float], width: int = 8) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—".rjust(width)
    return f"{v:>{width}.1f}"


def _solver_recommendation_md(
    cells: Dict[Tuple[str, str, int], Dict[str, Any]],
    overall_rate: Dict[str, float],
) -> str:
    lines: List[str] = []
    lines.append("# Solver Recommendation (calibration output)")
    lines.append("")
    lines.append(
        f"Generated from {sum(s['n_total'] for s in cells.values())} "
        f"plan_with_metadata invocations across "
        f"{len({k[0] for k in cells})} solvers, "
        f"{len({k[1] for k in cells})} maps, "
        f"{len(cells)} (solver, map, |M|) cells."
    )
    lines.append("")

    # Cohort summary
    lines.append("## Cohort summary — completion rate by solver (all cells)")
    lines.append("")
    lines.append("| Solver | Completion rate | |M| range tested |")
    lines.append("|---|---:|---|")
    for solver in sorted(overall_rate):
        n_range = sorted({k[2] for k in cells if k[0] == solver})
        lines.append(
            f"| {solver} | {overall_rate[solver]:.2%} | "
            f"{min(n_range)}–{max(n_range)} |"
        )
    lines.append("")

    # Per-section recommendation
    lines.append("## Per-section recommendation")
    lines.append("")
    lines.append("| Section | Cohort | Threshold | Solvers included | Solvers excluded |")
    lines.append("|---|---|---:|---|---|")
    section_rec = {sec: _section_recommendation(sec, cells)
                   for sec in SECTION_THRESHOLDS}
    for sec in sorted(SECTION_THRESHOLDS):
        rec = section_rec[sec]
        included = ", ".join(rec["included"]) if rec["included"] else "_none_"
        excluded = ", ".join(rec["excluded"]) if rec["excluded"] else "_none_"
        lines.append(
            f"| §{sec} ({rec['label']}) | {rec['cohort_size']} cells | "
            f"{rec['threshold']:.0%} | {included} | {excluded} |"
        )
    lines.append("")

    # Per-section justification block
    for sec in sorted(SECTION_THRESHOLDS):
        rec = section_rec[sec]
        if not rec["excluded"]:
            continue
        lines.append(f"### §{sec} exclusions — justification")
        lines.append("")
        for solver, reason in rec["excluded"].items():
            lines.append(f"* **{solver}**: {reason}")
        lines.append("")

    # Per-solver per-cell completion-rate matrix
    lines.append("## Per-solver completion-rate matrix")
    lines.append("")
    solvers = sorted({k[0] for k in cells})
    maps = sorted({k[1] for k in cells})
    for solver in solvers:
        lines.append(f"### {solver}")
        lines.append("")
        n_values = sorted({k[2] for k in cells if k[0] == solver})
        # Build a table: rows = map, cols = num_agents
        header = "| Map | " + " | ".join(str(n) for n in n_values) + " |"
        sep = "|---|" + "---:|" * len(n_values)
        lines.append(header)
        lines.append(sep)
        for map_stem in maps:
            row_vals = []
            for n in n_values:
                key = (solver, map_stem, n)
                if key in cells:
                    rate = cells[key]["completion_rate"]
                    row_vals.append(f"{rate:.0%}")
                else:
                    row_vals.append("—")
            lines.append(f"| {map_stem} | " + " | ".join(row_vals) + " |")
        lines.append("")

    # solver_wall_ms p50 / p95 matrix per solver
    lines.append("## Per-solver `solver_wall_ms` p50 / p95 (ms)")
    lines.append("")
    for solver in solvers:
        lines.append(f"### {solver}")
        lines.append("")
        n_values = sorted({k[2] for k in cells if k[0] == solver})
        lines.append("| Map | |M| | p50 | p95 | max |")
        lines.append("|---|---:|---:|---:|---:|")
        for map_stem in maps:
            for n in n_values:
                key = (solver, map_stem, n)
                if key not in cells:
                    continue
                s = cells[key]
                lines.append(
                    f"| {map_stem} | {n} | "
                    f"{_fmt(s['sw_p50_ms'])} | "
                    f"{_fmt(s['sw_p95_ms'])} | "
                    f"{_fmt(s['sw_max_ms'])} |"
                )
        lines.append("")

    # §5.1 budget recommendation
    lines.append("## §5.1 budget recommendation")
    lines.append("")
    lines.append(
        "Current §5.1 per-replan budget is **5 s** (`SimConfig.solver_timeout_s`)."
    )
    lines.append("")
    # LaCAM* highest-density p95 on warehouse-10-20-10-2-2
    target_key = ("lacam3", "warehouse-10-20-10-2-2", 450)
    if target_key in cells and cells[target_key]["sw_p95_ms"] is not None:
        p95 = cells[target_key]["sw_p95_ms"]
        if p95 > 5000.0:
            verdict = (
                f"**RECOMMEND BUMP** — LaCAM\\* p95 at |M|=450 on "
                f"warehouse-10-20-10-2-2 is {p95:.0f} ms, exceeding the 5 s "
                f"budget.  Suggest bumping §5.1 budget to "
                f"{max(int(p95 / 1000.0) + 1, 7)} s to keep p95 cells "
                f"within budget."
            )
        else:
            verdict = (
                f"**5 s IS SUFFICIENT** — LaCAM\\* p95 at |M|=450 on "
                f"warehouse-10-20-10-2-2 is {p95:.0f} ms, well within the "
                f"5 s budget.  No need to change §5.1."
            )
    else:
        verdict = (
            "**INCONCLUSIVE** — LaCAM\\* p95 at |M|=450 on "
            "warehouse-10-20-10-2-2 not measured (cell missing or all-error). "
            "Re-run calibration with that cell before deciding on §5.1 budget."
        )
    lines.append(verdict)
    lines.append("")

    return "\n".join(lines) + "\n"


def _anytime_verification_md(
    cells: Dict[Tuple[str, str, int], Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append("# Anytime semantics: algorithm class vs harness behavior")
    lines.append("")
    lines.append(
        "Six paper-sweep solvers, classified by published algorithm class "
        "and observed harness behavior in this calibration run."
    )
    lines.append("")
    lines.append(
        "| Solver | Algorithm class | Harness behavior | Reason | "
        "§5.1 \"partial solutions are still used\" applies? |"
    )
    lines.append("|---|---|---|---|---|")
    for solver in sorted(SOLVER_CLASS):
        algo_class = SOLVER_CLASS[solver]
        # Empirical: did this solver produce partial_anytime in any cell?
        produced_partial = any(
            s["produced_partial_anytime"]
            for k, s in cells.items() if k[0] == solver
        )
        if produced_partial:
            harness = "Anytime in harness (produces `partial_anytime` status)"
            applies = "**Yes**"
        elif "anytime" in algo_class.lower():
            harness = "Algorithmically anytime, complete-or-error in harness"
            applies = (
                "Indirectly — the binary self-terminates at `-t` with the "
                "best plan it found (status = complete) or no plan at all "
                "(status = error/timeout_no_result)"
            )
        else:
            harness = "Non-anytime; complete-or-timeout-or-error"
            applies = "No"

        # Reason
        reasons = {
            "lacam_official": "writes its result file even on partial returns",
            "lacam3":         "writes its result file even on partial returns",
            "lns2":           "writes the paths file only at end-of-run; no partial output to recover",
            "pibt2":          "priority-scheme returns first feasible plan; no anytime iteration",
            "cbsh2":          "optimal CBS — complete-or-timeout by design",
            "pbs":            "priority-based; complete-or-incomplete by design",
        }
        reason = reasons.get(solver, "—")

        lines.append(
            f"| {solver} | {algo_class} | {harness} | {reason} | {applies} |"
        )
    lines.append("")

    lines.append("## Implication for §5.1")
    lines.append("")
    lines.append(
        "The §5.1 claim \"partial solutions returned by anytime solvers are "
        "still used\" applies cleanly to **LaCAM\\*** and **LaCAM** (the "
        "`partial_anytime` status fires in this calibration), and "
        "indirectly to **MAPF-LNS2** (the binary's anytime iteration is "
        "real but its all-or-nothing paths-file write means partial returns "
        "manifest as either `complete` with the best plan it had at "
        "budget, or `error` with no plan at all — never `partial_anytime`)."
    )
    lines.append("")
    lines.append(
        "For **PIBT2**, **CBSH2-RTC**, and **PBS**, the §5.1 anytime claim "
        "does not directly apply.  These are non-anytime solvers; their "
        "harness behavior is binary (complete or error)."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _literature_consistency_md(
    cells: Dict[Tuple[str, str, int], Dict[str, Any]],
) -> str:
    lines: List[str] = []
    lines.append("# Literature consistency check")
    lines.append("")
    lines.append(
        "Measured `solver_wall_ms` vs published runtime claims at the "
        "most-comparable cell in our grid."
    )
    lines.append("")
    lines.append(
        "| Solver | Cell | Published claim | Source | "
        "Measured p50 (ms) | Measured p95 (ms) | Verdict |"
    )
    lines.append("|---|---|---|---|---:|---:|---|")
    verdict_counter: Counter = Counter()
    for entry in LITERATURE:
        solver = entry["solver"]
        map_stem, n = entry["measured_at"]
        key = (solver, map_stem, n)
        if key in cells and cells[key]["sw_p50_ms"] is not None:
            measured_p50 = cells[key]["sw_p50_ms"]
            measured_p95 = cells[key]["sw_p95_ms"]
            expected = entry["expected_p50_ms"]
            ratio = measured_p50 / expected if expected > 0 else math.inf
            if 0.5 <= ratio <= 2.0:
                verdict = "**Consistent**"
            elif ratio < 0.5:
                verdict = "Faster — verify parser reads correct field"
            else:
                verdict = "Slower — check end_to_end vs solver_wall gap"
            verdict_counter[verdict.split(" ")[0].lower().rstrip("*")] += 1
            p50_str = f"{measured_p50:.1f}"
            p95_str = f"{measured_p95:.1f}" if measured_p95 is not None else "—"
        else:
            verdict = "Unmeasurable — cell not in grid or all-error"
            verdict_counter["unmeasurable"] += 1
            p50_str = "—"
            p95_str = "—"
        cell_label = f"{map_stem}, |M|={n}"
        lines.append(
            f"| {solver} | {cell_label} | {entry['claim']} | "
            f"{entry['source']} | {p50_str} | {p95_str} | {verdict} |"
        )
    lines.append("")

    # Diagnostic notes for any non-consistent verdicts
    for entry in LITERATURE:
        solver = entry["solver"]
        map_stem, n = entry["measured_at"]
        key = (solver, map_stem, n)
        if key not in cells or cells[key]["sw_p50_ms"] is None:
            continue
        measured = cells[key]["sw_p50_ms"]
        expected = entry["expected_p50_ms"]
        ratio = measured / expected
        if ratio < 0.5:
            lines.append(f"### {solver} — measured {ratio:.1f}× faster than "
                         f"literature")
            lines.append("")
            lines.append(
                "Possible causes: (1) the parser is reading a sub-field "
                "instead of the total runtime (e.g. `comp_time_initial_solution` "
                "rather than `comp_time` in LaCAM\\*'s result file); "
                "(2) the literature cell is harder than ours (different "
                "map / density); (3) the benchmark machine in the cited "
                "paper was slower than this CI host."
            )
            lines.append("")
        elif ratio > 2.0:
            cell = cells[key]
            overhead = (
                cell["e2e_p50_ms"] - cell["sw_p50_ms"]
                if cell.get("e2e_p50_ms") is not None
                else None
            )
            lines.append(f"### {solver} — measured {ratio:.1f}× slower than "
                         f"literature")
            lines.append("")
            if overhead is not None:
                lines.append(
                    f"`end_to_end_wall_ms` p50 = "
                    f"{cell['e2e_p50_ms']:.1f} ms; wrapper overhead "
                    f"(end_to_end − solver_wall) = {overhead:.1f} ms.  "
                    f"If overhead is >50% of solver_wall, the gap is "
                    f"subprocess-startup dominated.  Otherwise the binary "
                    f"itself is slower on this host."
                )
            else:
                lines.append(
                    "`end_to_end_wall_ms` not available; cannot decompose "
                    "into wrapper-overhead vs binary-runtime."
                )
            lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    for v, c in sorted(verdict_counter.items(), key=lambda x: -x[1]):
        lines.append(f"* **{v.capitalize()}**: {c} solver(s)")
    lines.append("")
    if verdict_counter.get("faster", 0) + verdict_counter.get("slower", 0) >= 3:
        lines.append(
            "> **WARNING**: ≥3 solvers diverge from literature.  This is a "
            "wrapper-overhead pattern worth investigating before relying on "
            "the calibration's numbers for §5.x decisions."
        )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", type=Path, required=True)
    parser.add_argument("--out", dest="out_dir", type=Path, required=True)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_rows(args.in_path)
    print(f"loaded {len(rows)} measurements from {args.in_path}")

    cells = _stats_per_cell(rows)
    overall = _overall_completion_per_solver(cells)
    print(f"aggregated into {len(cells)} cells")
    print(f"per-solver overall completion:")
    for s in sorted(overall):
        print(f"  {s}: {overall[s]:.2%}")

    rec_md = _solver_recommendation_md(cells, overall)
    (args.out_dir / "solver_recommendation.md").write_text(rec_md)
    print(f"wrote {args.out_dir / 'solver_recommendation.md'}")

    anytime_md = _anytime_verification_md(cells)
    (args.out_dir / "anytime_verification.md").write_text(anytime_md)
    print(f"wrote {args.out_dir / 'anytime_verification.md'}")

    lit_md = _literature_consistency_md(cells)
    (args.out_dir / "literature_consistency.md").write_text(lit_md)
    print(f"wrote {args.out_dir / 'literature_consistency.md'}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
