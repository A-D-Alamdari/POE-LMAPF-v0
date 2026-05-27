"""Cross-cohort decomposition summary.

Reads the §5.4 and §5.5 per-cohort decomposition CSVs (or recomputes
from the raw_measurements_* CSVs directly) and emits
``decomposition_summary.md`` — the single artifact paper prose cites.

The summary contains, per cohort:
* most-extreme-cell three-way break-out
* high-density aggregate exo / alloc / total
* allocator-vs-exogenous ratio

Plus a cross-cohort comparison that asks: does the §5.5 cohort
(\\|X\\|=100 on warehouse-2-2) show a larger exogenous-driven
contribution than the §5.4 cohort (\\|X\\|=60)?  If yes, that is
expected — denser exogenous → larger exogenous contribution.  If
no, that is a surprising finding worth flagging.
"""
from __future__ import annotations

import argparse
import math
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Re-use the analysis primitives from the per-cohort script.
import sys
sys.path.insert(0, str(Path(__file__).parent))
from analyze_three_way_comparison import (  # noqa: E402
    _aggregate, _decompose, _read_rows, _high_density_aggregate,
    _extreme_cell_block, _fmt_pp, _fmt_rate,
)


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return "(git rev-parse failed)"


def _cohort_block(
    cohort_label: str, sim_csv: Path, bench_bare_csv: Path,
    bench_exo_csv: Path,
) -> Tuple[List[str], Dict[str, Any]]:
    """Build a per-cohort block + return the high-density summary dict."""
    sim_rows = _read_rows(sim_csv)
    bench_bare_rows = _read_rows(bench_bare_csv)
    bench_exo_rows = _read_rows(bench_exo_csv)

    sim = _aggregate(sim_rows)
    bench_bare = _aggregate(bench_bare_rows)
    bench_exo = _aggregate(bench_exo_rows)
    rows = _decompose(sim, bench_bare, bench_exo)

    lines: List[str] = []
    lines.append(f"## {cohort_label} cohort headline")
    lines.append("")
    lines.append(f"Cells in decomposition (present in all three CSVs): "
                 f"**{len(rows)}**.")
    lines.append("")
    if not rows:
        lines.append("_No comparable cells._")
        lines.append("")
        return lines, {}

    extreme_lines, extreme = _extreme_cell_block(rows)
    lines.append("**Most extreme cell:**")
    lines.append("")
    lines.extend(extreme_lines)
    lines.append("")

    hd_lines, hd_summary = _high_density_aggregate(rows)
    lines.append("**High-density aggregate (warehouse \\|M\\| ≥ 150):**")
    lines.append("")
    lines.extend(hd_lines)
    lines.append("")

    return lines, {"extreme": extreme, "hd": hd_summary, "n_cells": len(rows)}


def _cross_cohort_block(
    s54: Dict[str, Any], s55: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("## Cross-cohort comparison")
    lines.append("")
    if not (s54.get("hd") and s55.get("hd")):
        lines.append("_Insufficient high-density cells in one or both cohorts "
                     "to compare._")
        return lines

    h54 = s54["hd"]
    h55 = s55["hd"]
    lines.append("| Metric | §5.4 (\\|X\\|=20/40/60) | §5.5 (\\|X\\|=20/100) | "
                 "Δ (5.5 − 5.4) |")
    lines.append("|---|---:|---:|---:|")
    lines.append(
        f"| Mean exogenous-only Δ | "
        f"{_fmt_pp(h54['mean_exo_d'])} | "
        f"{_fmt_pp(h55['mean_exo_d'])} | "
        f"{_fmt_pp(h55['mean_exo_d'] - h54['mean_exo_d'])} |"
    )
    lines.append(
        f"| Mean allocator + lifelong Δ | "
        f"{_fmt_pp(h54['mean_alloc_d'])} | "
        f"{_fmt_pp(h55['mean_alloc_d'])} | "
        f"{_fmt_pp(h55['mean_alloc_d'] - h54['mean_alloc_d'])} |"
    )
    lines.append(
        f"| Mean total Δ | "
        f"{_fmt_pp(h54['mean_total_d'])} | "
        f"{_fmt_pp(h55['mean_total_d'])} | "
        f"{_fmt_pp(h55['mean_total_d'] - h54['mean_total_d'])} |"
    )
    lines.append(
        f"| Allocator-vs-exogenous ratio | "
        f"{h54.get('ratio', float('inf')):.1f}× | "
        f"{h55.get('ratio', float('inf')):.1f}× | — |"
    )
    lines.append("")

    # Direction-of-effect prose
    exo_delta = h55["mean_exo_d"] - h54["mean_exo_d"]
    if exo_delta > 0.05:
        verdict = (
            "**Expected.**  The §5.5 cohort's higher exogenous density "
            f"({_fmt_pp(exo_delta)} larger exogenous contribution at "
            "high density) reflects the denser \\|X\\|=100 on "
            "warehouse-2-2 vs §5.4's \\|X\\|=60.  The denser the "
            "exogenous occupancy, the more the bare-Stern → +exo gap "
            "widens.  This is the direction one would expect from the "
            "physics of the placement."
        )
    elif exo_delta < -0.05:
        verdict = (
            "**Unexpected.**  The §5.5 cohort's higher exogenous "
            f"density ({_fmt_pp(-exo_delta)} smaller exogenous "
            "contribution at high density) inverts the physical "
            "intuition that denser \\|X\\| should harden the instance "
            "more.  Either the §5.5 cells in the high-density bucket "
            "are saturated (both Stern bare and Stern + obstacles at "
            "0% completion, so the gap collapses) or there is a "
            "matching bug in the analysis.  Inspect the extreme cell "
            "above before quoting these numbers in the paper."
        )
    else:
        verdict = (
            "**Roughly equal.**  The §5.5 cohort's exogenous "
            "contribution matches §5.4's within "
            f"{_fmt_pp(abs(exo_delta))}.  Either both cohorts are "
            "saturated at high density (everything at 0% completion) or "
            "the |X| difference (100 vs 60) is not large enough on "
            "warehouse-2-2 to materially change the obstacle-induced "
            "drop."
        )
    lines.append(verdict)
    lines.append("")
    return lines


def _implications_block(
    s54: Dict[str, Any], s55: Dict[str, Any],
) -> List[str]:
    lines: List[str] = []
    lines.append("## Single-sentence implications for paper prose")
    lines.append("")

    def _one_sentence(label: str, summary: Dict[str, Any]) -> str:
        if not summary.get("hd"):
            return f"* **{label}:** _no high-density cells comparable; cannot quote a ratio._"
        h = summary["hd"]
        ratio = h.get("ratio", float("inf"))
        if h["mean_alloc_d"] >= h["mean_exo_d"]:
            dom = "task allocation under rolling-horizon execution"
        else:
            dom = "exogenous-agent obstacles"
        if ratio == float("inf") or ratio > 100:
            ratio_str = "vastly larger than"
        elif ratio >= 2.0:
            ratio_str = f"{ratio:.1f}× larger than"
        elif ratio >= 0.5:
            ratio_str = f"comparable in magnitude to ({ratio:.1f}×)"
        elif ratio > 0:
            ratio_str = f"smaller than ({ratio:.1f}×)"
        else:
            ratio_str = f"opposite-signed from ({ratio:.1f}×)"
        return (
            f"* **{label}:** at high density the allocator + lifelong "
            f"contribution ({_fmt_pp(h['mean_alloc_d'])}) is "
            f"{ratio_str} the exogenous-as-obstacles contribution "
            f"({_fmt_pp(h['mean_exo_d'])}), identifying **{dom}** as "
            f"the dominant source of difficulty in the cohort."
        )

    lines.append(_one_sentence("§5.4", s54))
    lines.append(_one_sentence("§5.5", s55))
    lines.append("")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sim-5-4-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_v2.csv"),
    )
    parser.add_argument(
        "--sim-5-5-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_v2_5_5.csv"),
    )
    parser.add_argument(
        "--bare-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_benchmark.csv"),
    )
    parser.add_argument(
        "--exo-5-4-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_benchmark_with_exo_5_4.csv"),
    )
    parser.add_argument(
        "--exo-5-5-csv", type=Path,
        default=Path("logs/calibration/raw_measurements_benchmark_with_exo_5_5.csv"),
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("# Three-way decomposition summary (§5.4 + §5.5)")
    lines.append("")
    lines.append(f"Generated against commit: `{_git_head()}`")
    lines.append("")
    lines.append("Sources:")
    lines.append("")
    lines.append(f"* §5.4 simulator: `{args.sim_5_4_csv}`")
    lines.append(f"* §5.5 simulator: `{args.sim_5_5_csv}`")
    lines.append(f"* Stern bare (shared):    `{args.bare_csv}`")
    lines.append(f"* §5.4 Stern + exogenous: `{args.exo_5_4_csv}`")
    lines.append(f"* §5.5 Stern + exogenous: `{args.exo_5_5_csv}`")
    lines.append("")
    lines.append("Per-cohort detailed tables: see "
                 "`allocator_vs_exogenous_decomposition_5_4.md` and "
                 "`allocator_vs_exogenous_decomposition_5_5.md`.")
    lines.append("")

    s54_lines, s54 = _cohort_block(
        "§5.4", args.sim_5_4_csv, args.bare_csv, args.exo_5_4_csv,
    )
    s55_lines, s55 = _cohort_block(
        "§5.5", args.sim_5_5_csv, args.bare_csv, args.exo_5_5_csv,
    )
    lines.extend(s54_lines)
    lines.extend(s55_lines)
    lines.extend(_cross_cohort_block(s54, s55))
    lines.extend(_implications_block(s54, s55))

    out_path = args.out / "decomposition_summary.md"
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
