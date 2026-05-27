"""Three-way completion-rate decomposition: Stern bare → Stern+exo → Sim.

Reads three CSVs from the calibration tier:

* simulator-driven, per-map num_humans (raw_measurements_v2.csv)
* Stern bare, no exogenous (raw_measurements_benchmark.csv)
* Stern + exogenous-as-static-obstacles (raw_measurements_benchmark_with_exo.csv)

Emits ``allocator_vs_exogenous_decomposition.md`` quantifying:

* Per-cell ``exogenous_contribution`` =
  bench_bare_completion − bench_exo_completion
* Per-cell ``allocator_lifelong_contribution`` =
  bench_exo_completion − sim_completion
* Per-cell ``total_gap`` =
  bench_bare_completion − sim_completion

The decomposition isolates the *exogenous-as-obstacles* effect from
the *task-allocator + lifelong-state* effect, both relative to the
canonical Stern solver-only baseline.
"""
from __future__ import annotations

import argparse
import csv
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


CellKey = Tuple[str, str, int]  # (solver, map, num_agents)


def _f(s: str, default: float = math.nan) -> float:
    if s == "" or s is None:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _is_complete(status: str) -> bool:
    return status in {"complete", "partial_anytime"}


def _read_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def _active_allocator_label(sim_csv: Path) -> str:
    """Pick the adjective used in prose to identify the active allocator.

    Reads the ``source_config`` column from the simulator-driven CSV
    and returns ``"congestion_avoidance"`` or ``"greedy"`` when the
    dominant tag plainly contains either token; otherwise returns the
    neutral placeholder ``"the active"`` so the prose remains accurate
    (and grammatical when concatenated with "task allocator" / "task
    allocation") when the CSV pre-dates the source_config convention
    or carries an ambiguous tag.

    Archived calibration CSVs (under ``logs/calibration/``) still use
    the legacy ``"conflict_aware"`` marker; both spellings are
    normalised to ``"congestion_avoidance"`` so the function returns
    one canonical label across pre- and post-rename data.
    """
    rows = _read_rows(sim_csv)
    seen: Dict[str, int] = {}
    for r in rows:
        tag = (r.get("source_config") or "").strip()
        if tag:
            seen[tag] = seen.get(tag, 0) + 1
    if not seen:
        return "the active"
    dominant = max(seen, key=seen.get).lower()
    # Accept the legacy "conflict_aware" tag from archived CSVs and
    # the canonical "congestion_avoidance" tag from new sweeps; both
    # map to the same return value so downstream prose is consistent.
    if "congestion_avoidance" in dominant or "conflict_aware" in dominant:
        return "congestion_avoidance"
    if "greedy" in dominant:
        return "greedy"
    return "the active"


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[CellKey, Dict[str, Any]]:
    cells: Dict[CellKey, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        try:
            key = (r["solver"], r["map"], int(r["num_agents"]))
        except (KeyError, ValueError):
            continue
        cells[key].append(r)

    out: Dict[CellKey, Dict[str, Any]] = {}
    for key, cell_rows in cells.items():
        n_total = len(cell_rows)
        n_complete = sum(1 for r in cell_rows if _is_complete(r["status"]))
        out[key] = {
            "n_total": n_total,
            "n_complete": n_complete,
            "completion_rate": n_complete / n_total if n_total else 0.0,
            # Read num_humans from any row; should be uniform within a cell
            # for v2/exo CSVs (constant per map by construction).
            "num_humans": int(cell_rows[0].get("num_humans", 0))
                if cell_rows and cell_rows[0].get("num_humans", "") != "" else 0,
        }
    return out


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "(git rev-parse failed)"


def _fmt_pp(d: float) -> str:
    if math.isnan(d):
        return "—"
    pct = d * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f} pp"


def _fmt_rate(r: float) -> str:
    if math.isnan(r):
        return "—"
    return f"{r * 100:.0f}%"


def _decompose(
    sim: Dict[CellKey, Dict[str, Any]],
    bench_bare: Dict[CellKey, Dict[str, Any]],
    bench_exo: Dict[CellKey, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """For every key present in all three, compute the decomposition."""
    keys = sorted(set(sim) & set(bench_bare) & set(bench_exo))
    out: List[Dict[str, Any]] = []
    for k in keys:
        s = sim[k]["completion_rate"]
        bb = bench_bare[k]["completion_rate"]
        be = bench_exo[k]["completion_rate"]
        out.append({
            "key": k,
            "solver": k[0], "map": k[1], "num_agents": k[2],
            "num_humans": bench_exo[k]["num_humans"],
            "sim_rate": s,
            "bench_bare_rate": bb,
            "bench_exo_rate": be,
            "exo_contribution": bb - be,
            "alloc_lifelong_contribution": be - s,
            "total_gap": bb - s,
            "sim_n": sim[k]["n_total"],
            "bench_bare_n": bench_bare[k]["n_total"],
            "bench_exo_n": bench_exo[k]["n_total"],
        })
    return out


def _build_headline_table(rows: List[Dict[str, Any]]) -> List[str]:
    """Per-cell × per-solver headline table, sorted by total_gap DESC."""
    lines: List[str] = []
    lines.append("| Solver | Map | \\|M\\| | \\|X\\| | Bare | +Exo | Sim | "
                 "Exo Δ | Alloc Δ | Total Δ |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    sorted_rows = sorted(rows, key=lambda r: -r["total_gap"])
    for r in sorted_rows:
        lines.append(
            f"| {r['solver']} | {r['map']} | {r['num_agents']} | "
            f"{r['num_humans']} | "
            f"{_fmt_rate(r['bench_bare_rate'])} | "
            f"{_fmt_rate(r['bench_exo_rate'])} | "
            f"{_fmt_rate(r['sim_rate'])} | "
            f"{_fmt_pp(r['exo_contribution'])} | "
            f"{_fmt_pp(r['alloc_lifelong_contribution'])} | "
            f"{_fmt_pp(r['total_gap'])} |"
        )
    return lines


def _solver_aggregate(rows: List[Dict[str, Any]]) -> List[str]:
    """Per-solver aggregate over all cells."""
    by_solver: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_solver[r["solver"]].append(r)
    lines: List[str] = []
    lines.append("| Solver | Cells | Mean Bare | Mean +Exo | Mean Sim | "
                 "Mean Exo Δ | Mean Alloc Δ | Mean Total Δ | Alloc/Exo ratio |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for solver in sorted(by_solver):
        srows = by_solver[solver]
        n = len(srows)
        m_bare = sum(r["bench_bare_rate"] for r in srows) / n
        m_exo = sum(r["bench_exo_rate"] for r in srows) / n
        m_sim = sum(r["sim_rate"] for r in srows) / n
        m_exo_d = sum(r["exo_contribution"] for r in srows) / n
        m_alloc_d = sum(r["alloc_lifelong_contribution"] for r in srows) / n
        m_total_d = sum(r["total_gap"] for r in srows) / n
        # Ratio guarded against tiny denominators
        if abs(m_exo_d) > 1e-6:
            ratio_str = f"{m_alloc_d / m_exo_d:.1f}×"
        else:
            ratio_str = "∞ (exo ≈ 0)"
        lines.append(
            f"| {solver} | {n} | "
            f"{_fmt_rate(m_bare)} | {_fmt_rate(m_exo)} | "
            f"{_fmt_rate(m_sim)} | "
            f"{_fmt_pp(m_exo_d)} | {_fmt_pp(m_alloc_d)} | "
            f"{_fmt_pp(m_total_d)} | {ratio_str} |"
        )
    return lines


def _high_density_aggregate(
    rows: List[Dict[str, Any]],
) -> Tuple[List[str], Dict[str, float]]:
    """Aggregate over (warehouse, |M|≥150) cells.  Returns table + summary
    dict for the implication paragraph.
    """
    high = [r for r in rows
            if r["map"].startswith("warehouse") and r["num_agents"] >= 150]
    lines: List[str] = []
    summary: Dict[str, float] = {}
    if not high:
        lines.append("_No high-density warehouse cells in the input._")
        return lines, summary
    n = len(high)
    m_bare = sum(r["bench_bare_rate"] for r in high) / n
    m_exo = sum(r["bench_exo_rate"] for r in high) / n
    m_sim = sum(r["sim_rate"] for r in high) / n
    m_exo_d = sum(r["exo_contribution"] for r in high) / n
    m_alloc_d = sum(r["alloc_lifelong_contribution"] for r in high) / n
    m_total_d = sum(r["total_gap"] for r in high) / n
    summary = {
        "n_cells": n,
        "mean_bare": m_bare, "mean_exo": m_exo, "mean_sim": m_sim,
        "mean_exo_d": m_exo_d, "mean_alloc_d": m_alloc_d,
        "mean_total_d": m_total_d,
    }
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Cells aggregated | {n} (warehouse maps, \\|M\\| ≥ 150) |")
    lines.append(f"| Mean Stern bare completion | {_fmt_rate(m_bare)} |")
    lines.append(f"| Mean Stern + exogenous completion | {_fmt_rate(m_exo)} |")
    lines.append(f"| Mean simulator-driven completion | {_fmt_rate(m_sim)} |")
    lines.append(f"| Mean exogenous-only contribution | {_fmt_pp(m_exo_d)} |")
    lines.append(
        f"| Mean allocator + lifelong-state contribution | {_fmt_pp(m_alloc_d)} |"
    )
    lines.append(f"| Mean total gap | {_fmt_pp(m_total_d)} |")
    if abs(m_exo_d) > 1e-6:
        ratio = m_alloc_d / m_exo_d
        lines.append(f"| Allocator-vs-exogenous ratio | {ratio:.1f}× |")
        summary["ratio"] = ratio
    else:
        lines.append(f"| Allocator-vs-exogenous ratio | ∞ (exo ≈ 0) |")
        summary["ratio"] = float("inf")
    return lines, summary


def _extreme_cell_block(rows: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any]]:
    """The cell with the largest total_gap; report the three-way break-out."""
    if not rows:
        return ["_No cells in input._"], {}
    extreme = max(rows, key=lambda r: r["total_gap"])
    lines: List[str] = []
    lines.append(
        f"Most extreme cell (largest total gap): "
        f"**{extreme['solver']}** on **{extreme['map']}** at "
        f"\\|M\\|={extreme['num_agents']}, \\|X\\|={extreme['num_humans']}."
    )
    lines.append("")
    lines.append("| Regime | Completion |")
    lines.append("|---|---:|")
    lines.append(f"| Stern bare (no exogenous) | {_fmt_rate(extreme['bench_bare_rate'])} |")
    lines.append(f"| Stern + {extreme['num_humans']} exogenous obstacles | "
                 f"{_fmt_rate(extreme['bench_exo_rate'])} |")
    lines.append(f"| Simulator-driven (lifelong) | {_fmt_rate(extreme['sim_rate'])} |")
    lines.append(f"| **Exogenous-only contribution** | "
                 f"{_fmt_pp(extreme['exo_contribution'])} |")
    lines.append(f"| **Allocator + lifelong contribution** | "
                 f"{_fmt_pp(extreme['alloc_lifelong_contribution'])} |")
    lines.append(f"| Total gap | {_fmt_pp(extreme['total_gap'])} |")
    return lines, extreme


def _anomalies(rows: List[Dict[str, Any]]) -> List[str]:
    """Cells that fail the decomposition's invariants."""
    lines: List[str] = []
    sum_anomaly: List[Dict[str, Any]] = []
    neg_exo: List[Dict[str, Any]] = []
    neg_alloc: List[Dict[str, Any]] = []
    for r in rows:
        s = r["exo_contribution"] + r["alloc_lifelong_contribution"]
        if abs(s - r["total_gap"]) > 0.05:
            sum_anomaly.append(r)
        if r["exo_contribution"] < -0.05:
            neg_exo.append(r)
        if r["alloc_lifelong_contribution"] < -0.05:
            neg_alloc.append(r)

    if not (sum_anomaly or neg_exo or neg_alloc):
        lines.append("None.  Decomposition sums cleanly on all cells; "
                     "no negative contributions.")
        return lines

    if sum_anomaly:
        lines.append(
            f"### Decomposition does not sum cleanly "
            f"(\\|exo + alloc − total\\| > 5 pp): {len(sum_anomaly)} cells"
        )
        lines.append("")
        for r in sum_anomaly[:12]:
            lines.append(
                f"* {r['solver']} / {r['map']} / |M|={r['num_agents']}: "
                f"exo={_fmt_pp(r['exo_contribution'])}, "
                f"alloc={_fmt_pp(r['alloc_lifelong_contribution'])}, "
                f"total={_fmt_pp(r['total_gap'])}"
            )
        lines.append("")

    if neg_exo:
        lines.append(
            f"### Negative exogenous contribution "
            f"(Stern + obstacles OUTPERFORMS Stern bare): {len(neg_exo)} cells"
        )
        lines.append("")
        for r in neg_exo[:12]:
            lines.append(
                f"* {r['solver']} / {r['map']} / |M|={r['num_agents']}: "
                f"bare={_fmt_rate(r['bench_bare_rate'])}, "
                f"+exo={_fmt_rate(r['bench_exo_rate'])} "
                f"({_fmt_pp(r['exo_contribution'])})"
            )
        lines.append("")

    if neg_alloc:
        lines.append(
            f"### Negative allocator contribution "
            f"(simulator OUTPERFORMS Stern + obstacles): {len(neg_alloc)} cells"
        )
        lines.append("")
        for r in neg_alloc[:12]:
            lines.append(
                f"* {r['solver']} / {r['map']} / |M|={r['num_agents']}: "
                f"+exo={_fmt_rate(r['bench_exo_rate'])}, "
                f"sim={_fmt_rate(r['sim_rate'])} "
                f"({_fmt_pp(r['alloc_lifelong_contribution'])})"
            )
        lines.append("")

    return lines


def _build_doc(
    rows: List[Dict[str, Any]],
    sim_csv: Path, bench_bare_csv: Path, bench_exo_csv: Path,
    sim: Dict[CellKey, Dict[str, Any]],
    bench_bare: Dict[CellKey, Dict[str, Any]],
    bench_exo: Dict[CellKey, Dict[str, Any]],
    cohort: str = "",
    alloc_label: str = "the active",
) -> str:
    cohort_label = (
        {"5_4": "§5.4", "5_5": "§5.5"}.get(cohort, "§5.4")
        if cohort else "§5.4"
    )
    lines: List[str] = []
    lines.append(f"# Allocator-vs-exogenous decomposition ({cohort_label} evidence)")
    lines.append("")
    lines.append(f"Generated against commit: `{_git_head()}`")
    lines.append("")
    lines.append("Sources:")
    lines.append("")
    lines.append(f"* simulator-driven (per-map num_humans): `{sim_csv}` "
                 f"({sum(s['n_total'] for s in sim.values())} rows, "
                 f"{len(sim)} cells)")
    lines.append(f"* Stern bare: `{bench_bare_csv}` "
                 f"({sum(s['n_total'] for s in bench_bare.values())} rows, "
                 f"{len(bench_bare)} cells)")
    lines.append(f"* Stern + exogenous obstacles: `{bench_exo_csv}` "
                 f"({sum(s['n_total'] for s in bench_exo.values())} rows, "
                 f"{len(bench_exo)} cells)")
    lines.append("")
    lines.append(
        "**Decomposition definition.**  For every (solver, map, \\|M\\|) "
        "cell present in all three CSVs:"
    )
    lines.append("")
    lines.append("* `exogenous_contribution = bench_bare − bench_exo` — "
                 "the drop from adding \\|X\\| static obstacles drawn from "
                 "the simulator's t=0 placement distribution.")
    lines.append("* `allocator_lifelong_contribution = bench_exo − sim` — "
                 "the additional drop from running the lifelong-MAPD "
                 f"pipeline ({alloc_label} task allocator releasing tasks "
                 "over time + exogenous agents moving + Tier-2 safety "
                 "reactions).")
    lines.append("* `total_gap = bench_bare − sim`. By construction "
                 "`total_gap = exogenous_contribution + allocator_lifelong_contribution`.")
    lines.append("")
    lines.append(f"Cells aggregated: **{len(rows)}** "
                 f"((solver, map, \\|M\\|) keys present in all three CSVs).")
    lines.append("")

    # Headline table
    lines.append("## Headline three-way completion-rate table")
    lines.append("")
    lines.append("Per-cell × per-solver, sorted by total gap descending.")
    lines.append("")
    lines.extend(_build_headline_table(rows))
    lines.append("")

    # Per-solver aggregate
    lines.append("## Per-solver aggregate")
    lines.append("")
    lines.extend(_solver_aggregate(rows))
    lines.append("")

    # Most extreme cell
    lines.append("## Most extreme cell")
    lines.append("")
    extreme_lines, extreme = _extreme_cell_block(rows)
    lines.extend(extreme_lines)
    lines.append("")

    # High-density aggregate
    lines.append("## High-density aggregate (warehouse \\|M\\| ≥ 150)")
    lines.append("")
    hd_lines, hd_summary = _high_density_aggregate(rows)
    lines.extend(hd_lines)
    lines.append("")

    # Implication paragraph
    lines.append("## Implication for §5.4 prose")
    lines.append("")
    if extreme and hd_summary:
        bare_pct = extreme["bench_bare_rate"] * 100
        sim_pct = extreme["sim_rate"] * 100
        exo_pp = extreme["exo_contribution"] * 100
        alloc_pp = extreme["alloc_lifelong_contribution"] * 100
        total_pp = extreme["total_gap"] * 100
        hd_exo_pp = hd_summary["mean_exo_d"] * 100
        hd_alloc_pp = hd_summary["mean_alloc_d"] * 100
        hd_ratio = hd_summary.get("ratio", float("inf"))
        if hd_ratio == float("inf") or hd_ratio > 100:
            ratio_phrase = "vastly larger than"
        elif hd_ratio >= 2.0:
            ratio_phrase = f"{hd_ratio:.1f}× larger than"
        elif hd_ratio >= 0.5:
            ratio_phrase = (
                f"comparable in magnitude to "
                f"({hd_ratio:.1f}× the size of)"
            )
        elif hd_ratio > 0:
            ratio_phrase = (
                f"smaller than "
                f"({hd_ratio:.1f}× the size of)"
            )
        else:
            ratio_phrase = (
                f"opposite-signed from "
                f"({hd_ratio:.1f}× the size of)"
            )
        if hd_alloc_pp >= hd_exo_pp:
            dominance = "**task allocation under rolling-horizon execution**"
        else:
            dominance = "**exogenous-agent obstacles**"
        lines.append(
            f"Of the {total_pp:.0f}-pp gap between Stern benchmark "
            f"completion ({bare_pct:.0f}%) and simulator-driven "
            f"completion ({sim_pct:.0f}%) at the most extreme cell "
            f"({extreme['solver']} on {extreme['map']}, \\|M\\|="
            f"{extreme['num_agents']}, \\|X\\|={extreme['num_humans']}), "
            f"{exo_pp:.0f} pp is attributable to exogenous-agent "
            f"obstacles and {alloc_pp:.0f} pp to {alloc_label} task "
            f"allocation under rolling-horizon execution.  Across all "
            f"{int(hd_summary['n_cells'])} high-density warehouse cells "
            f"(\\|M\\| ≥ 150), the mean allocator-driven contribution "
            f"({hd_alloc_pp:.0f} pp) is {ratio_phrase} the mean "
            f"exogenous-driven contribution ({hd_exo_pp:.0f} pp), "
            f"identifying {dominance} as the dominant source of "
            f"difficulty in our lifelong-MAPD setting."
        )
    else:
        lines.append("_(No comparable cells; cannot synthesize an implication.)_")
    lines.append("")

    # Anomalies
    lines.append("## Anomalies and caveats")
    lines.append("")
    lines.extend(_anomalies(rows))
    lines.append("")

    return "\n".join(lines) + "\n"


COHORT_DEFAULTS: Dict[str, Dict[str, Path]] = {
    "5_4": {
        "simulator_csv": Path("logs/calibration/raw_measurements_v2.csv"),
        "benchmark_exo_csv": Path(
            "logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv"),
        "out_filename": "allocator_vs_exogenous_decomposition_5_4.md",
    },
    "5_5": {
        "simulator_csv": Path("logs/calibration/raw_measurements_v2_5_5.csv"),
        "benchmark_exo_csv": Path(
            "logs/calibration/raw_measurements_benchmark_with_exo_5_5.csv"),
        "out_filename": "allocator_vs_exogenous_decomposition_5_5.md",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=str, default="",
                        choices=["", "5_4", "5_5"],
                        help="When set, defaults --simulator-csv, "
                             "--benchmark-exo-csv, and the output filename "
                             "from COHORT_DEFAULTS.  Explicit flags still "
                             "override.")
    parser.add_argument(
        "--simulator-csv", type=Path, default=None,
    )
    parser.add_argument(
        "--benchmark-bare-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_benchmark.csv"),
    )
    parser.add_argument(
        "--benchmark-exo-csv", type=Path, default=None,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--out-filename", type=str, default="",
                        help="Output .md filename inside --out.  Empty = "
                             "use cohort default, or "
                             "allocator_vs_exogenous_decomposition.md.")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    cohort_defaults = COHORT_DEFAULTS.get(args.cohort, {}) if args.cohort else {}
    sim_csv = args.simulator_csv or cohort_defaults.get(
        "simulator_csv",
        Path("logs/calibration/raw_measurements_v2.csv"),
    )
    bench_exo_csv = args.benchmark_exo_csv or cohort_defaults.get(
        "benchmark_exo_csv",
        Path("logs/calibration/raw_measurements_benchmark_with_exo.csv"),
    )
    out_filename = (
        args.out_filename
        or cohort_defaults.get("out_filename", "")
        or "allocator_vs_exogenous_decomposition.md"
    )

    sim_rows = _read_rows(sim_csv)
    bench_bare_rows = _read_rows(args.benchmark_bare_csv)
    bench_exo_rows = _read_rows(bench_exo_csv)
    print(f"cohort: {args.cohort or '(none)'}")
    print(f"sim:        {len(sim_rows)} rows from {sim_csv}")
    print(f"bench_bare: {len(bench_bare_rows)} rows from {args.benchmark_bare_csv}")
    print(f"bench_exo:  {len(bench_exo_rows)} rows from {bench_exo_csv}")

    sim = _aggregate(sim_rows)
    bench_bare = _aggregate(bench_bare_rows)
    bench_exo = _aggregate(bench_exo_rows)
    print(f"cells: sim={len(sim)} bench_bare={len(bench_bare)} "
          f"bench_exo={len(bench_exo)}")

    rows = _decompose(sim, bench_bare, bench_exo)
    print(f"decomposition: {len(rows)} cells with all three measurements")

    alloc_label = _active_allocator_label(sim_csv)
    print(f"alloc_label: {alloc_label}")
    doc = _build_doc(
        rows, sim_csv, args.benchmark_bare_csv, bench_exo_csv,
        sim, bench_bare, bench_exo, cohort=args.cohort,
        alloc_label=alloc_label,
    )
    out_path = args.out / out_filename
    out_path.write_text(doc)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
