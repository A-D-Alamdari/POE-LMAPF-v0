"""Build the cross-cohort decomposition summary at
``logs/calibration/decomposition_summary.md``.

Reads both §5.4 and §5.5 three-way decomposition inputs (the same CSVs
``scripts/analyze_three_way_comparison.py`` consumes for each cohort)
and synthesises the two-cohort headline file.  The per-cohort detail
files are produced by ``analyze_three_way_comparison.py`` directly;
this script regenerates only the cross-cohort summary that was
previously committed by hand.

Run after both cohorts have been re-decomposed:

    bash scripts/run_calibration/regenerate_decomposition_reports.sh

(which calls ``analyze_three_way_comparison.py`` for each cohort, then
this script as the final step).
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any, Dict


SCRIPTS_DIR = Path(__file__).resolve().parent


def _load_atwc():
    """Import ``analyze_three_way_comparison.py`` as a module."""
    spec = importlib.util.spec_from_file_location(
        "atwc", SCRIPTS_DIR / "analyze_three_way_comparison.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _cohort_block(atwc, label: str, sim_csv: Path, bench_bare_csv: Path,
                  bench_exo_csv: Path) -> Dict[str, Any]:
    """Aggregate one cohort and return the fields the summary needs."""
    sim = atwc._aggregate(atwc._read_rows(sim_csv))
    bb = atwc._aggregate(atwc._read_rows(bench_bare_csv))
    be = atwc._aggregate(atwc._read_rows(bench_exo_csv))
    rows = atwc._decompose(sim, bb, be)
    _, hd = atwc._high_density_aggregate(rows)
    if not rows:
        extreme: Dict[str, Any] = {}
    else:
        extreme = max(rows, key=lambda r: r["total_gap"])
    return {
        "label": label,
        "rows": rows,
        "extreme": extreme,
        "hd": hd,
        "sim_csv": sim_csv,
        "bench_bare_csv": bench_bare_csv,
        "bench_exo_csv": bench_exo_csv,
        "alloc_label": atwc._active_allocator_label(sim_csv),
    }


def _fmt_pct(r: float) -> str:
    return f"{r * 100:.0f}%"


def _fmt_pp(d: float) -> str:
    return f"{'+' if d >= 0 else ''}{d * 100:.0f} pp"


def _ratio_phrase(hd: Dict[str, float]) -> str:
    r = hd.get("ratio", float("inf"))
    if r == float("inf"):
        return "∞ (exo ≈ 0)"
    return f"{r:.1f}×"


def _extreme_block(label: str, extreme: Dict[str, Any]) -> str:
    if not extreme:
        return f"_(No extreme cell for {label}.)_\n"
    return (
        f"Most extreme cell (largest total gap): "
        f"**{extreme['solver']}** on **{extreme['map']}** at "
        f"\\|M\\|={extreme['num_agents']}, "
        f"\\|X\\|={extreme['num_humans']}.\n\n"
        f"| Regime | Completion |\n"
        f"|---|---:|\n"
        f"| Stern bare (no exogenous) | "
        f"{_fmt_pct(extreme['bench_bare_rate'])} |\n"
        f"| Stern + {extreme['num_humans']} exogenous obstacles | "
        f"{_fmt_pct(extreme['bench_exo_rate'])} |\n"
        f"| Simulator-driven (lifelong) | "
        f"{_fmt_pct(extreme['sim_rate'])} |\n"
        f"| **Exogenous-only contribution** | "
        f"{_fmt_pp(extreme['exo_contribution'])} |\n"
        f"| **Allocator + lifelong contribution** | "
        f"{_fmt_pp(extreme['alloc_lifelong_contribution'])} |\n"
        f"| Total gap | {_fmt_pp(extreme['total_gap'])} |\n"
    )


def _hd_block(hd: Dict[str, float]) -> str:
    if not hd:
        return "_No high-density warehouse cells in input._\n"
    return (
        f"| Metric | Value |\n"
        f"|---|---:|\n"
        f"| Cells aggregated | {int(hd['n_cells'])} "
        f"(warehouse maps, \\|M\\| ≥ 150) |\n"
        f"| Mean Stern bare completion | "
        f"{_fmt_pct(hd['mean_bare'])} |\n"
        f"| Mean Stern + exogenous completion | "
        f"{_fmt_pct(hd['mean_exo'])} |\n"
        f"| Mean simulator-driven completion | "
        f"{_fmt_pct(hd['mean_sim'])} |\n"
        f"| Mean exogenous-only contribution | "
        f"{_fmt_pp(hd['mean_exo_d'])} |\n"
        f"| Mean allocator + lifelong-state contribution | "
        f"{_fmt_pp(hd['mean_alloc_d'])} |\n"
        f"| Mean total gap | {_fmt_pp(hd['mean_total_d'])} |\n"
        f"| Allocator-vs-exogenous ratio | {_ratio_phrase(hd)} |\n"
    )


def _cross_cohort_table(c4: Dict[str, Any], c5: Dict[str, Any]) -> str:
    """The cross-cohort comparison table."""
    hd4 = c4["hd"]; hd5 = c5["hd"]
    def _delta_pp(a: float, b: float) -> str:
        return _fmt_pp(b - a)
    return (
        f"| Metric | §5.4 (\\|X\\|=20/40/60) | §5.5 (\\|X\\|=20/100) | "
        f"Δ (5.5 − 5.4) |\n"
        f"|---|---:|---:|---:|\n"
        f"| Mean exogenous-only Δ | {_fmt_pp(hd4['mean_exo_d'])} | "
        f"{_fmt_pp(hd5['mean_exo_d'])} | "
        f"{_delta_pp(hd4['mean_exo_d'], hd5['mean_exo_d'])} |\n"
        f"| Mean allocator + lifelong Δ | {_fmt_pp(hd4['mean_alloc_d'])} | "
        f"{_fmt_pp(hd5['mean_alloc_d'])} | "
        f"{_delta_pp(hd4['mean_alloc_d'], hd5['mean_alloc_d'])} |\n"
        f"| Mean total Δ | {_fmt_pp(hd4['mean_total_d'])} | "
        f"{_fmt_pp(hd5['mean_total_d'])} | "
        f"{_delta_pp(hd4['mean_total_d'], hd5['mean_total_d'])} |\n"
        f"| Allocator-vs-exogenous ratio | {_ratio_phrase(hd4)} | "
        f"{_ratio_phrase(hd5)} | — |\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_dir", type=Path,
                        default=Path("logs/calibration"))
    parser.add_argument("--out", type=Path,
                        default=Path("logs/calibration/decomposition_summary.md"))
    args = parser.parse_args()

    atwc = _load_atwc()

    bench_bare = args.in_dir / "raw_measurements_benchmark.csv"
    c4 = _cohort_block(
        atwc, "5_4",
        args.in_dir / "raw_measurements_v2.csv",
        bench_bare,
        args.in_dir / "raw_measurements_benchmark_with_exo_5_4.csv",
    )
    c5 = _cohort_block(
        atwc, "5_5",
        args.in_dir / "raw_measurements_v2_5_5.csv",
        bench_bare,
        args.in_dir / "raw_measurements_benchmark_with_exo_5_5.csv",
    )

    alloc_labels = {c4["alloc_label"], c5["alloc_label"]}
    if len(alloc_labels) == 1:
        alloc = next(iter(alloc_labels))
    else:
        alloc = "the active"

    lines = []
    lines.append("# Three-way decomposition summary (§5.4 + §5.5)")
    lines.append("")
    lines.append(f"Generated against commit: `{atwc._git_head()}`")
    lines.append("")
    lines.append("Sources:")
    lines.append("")
    lines.append(f"* §5.4 simulator: `{c4['sim_csv']}`")
    lines.append(f"* §5.5 simulator: `{c5['sim_csv']}`")
    lines.append(f"* Stern bare (shared):    `{bench_bare}`")
    lines.append(f"* §5.4 Stern + exogenous: `{c4['bench_exo_csv']}`")
    lines.append(f"* §5.5 Stern + exogenous: `{c5['bench_exo_csv']}`")
    lines.append("")
    lines.append("Per-cohort detailed tables: see "
                 "`allocator_vs_exogenous_decomposition_5_4.md` and "
                 "`allocator_vs_exogenous_decomposition_5_5.md`.")
    lines.append("")

    # §5.4 cohort headline
    lines.append("## §5.4 cohort headline")
    lines.append("")
    lines.append(f"Cells in decomposition (present in all three CSVs): "
                 f"**{len(c4['rows'])}**.")
    lines.append("")
    lines.append("**Most extreme cell:**")
    lines.append("")
    lines.append(_extreme_block("§5.4", c4["extreme"]))
    lines.append("**High-density aggregate (warehouse \\|M\\| ≥ 150):**")
    lines.append("")
    lines.append(_hd_block(c4["hd"]))

    # §5.5 cohort headline
    lines.append("## §5.5 cohort headline")
    lines.append("")
    lines.append(f"Cells in decomposition (present in all three CSVs): "
                 f"**{len(c5['rows'])}**.")
    lines.append("")
    lines.append("**Most extreme cell:**")
    lines.append("")
    lines.append(_extreme_block("§5.5", c5["extreme"]))
    lines.append("**High-density aggregate (warehouse \\|M\\| ≥ 150):**")
    lines.append("")
    lines.append(_hd_block(c5["hd"]))

    # Cross-cohort comparison
    lines.append("## Cross-cohort comparison")
    lines.append("")
    lines.append(_cross_cohort_table(c4, c5))

    # Single-sentence implications — uses alloc label, not hardcoded "greedy"
    lines.append("## Single-sentence implications for paper prose")
    lines.append("")
    if c4["hd"]:
        lines.append(
            f"* **§5.4:** at high density the allocator + lifelong "
            f"contribution ({_fmt_pp(c4['hd']['mean_alloc_d'])}) is "
            f"{_ratio_phrase(c4['hd'])} larger than the "
            f"exogenous-as-obstacles contribution "
            f"({_fmt_pp(c4['hd']['mean_exo_d'])}), identifying "
            f"**{alloc} task allocation under rolling-horizon execution** "
            f"as the dominant source of difficulty in the cohort."
        )
    if c5["hd"]:
        lines.append(
            f"* **§5.5:** at high density the allocator + lifelong "
            f"contribution ({_fmt_pp(c5['hd']['mean_alloc_d'])}) is "
            f"{_ratio_phrase(c5['hd'])} larger than the "
            f"exogenous-as-obstacles contribution "
            f"({_fmt_pp(c5['hd']['mean_exo_d'])}), identifying "
            f"**{alloc} task allocation under rolling-horizon execution** "
            f"as the dominant source of difficulty in the cohort."
        )
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"wrote {args.out}")
    print(f"alloc_label: §5.4={c4['alloc_label']} §5.5={c5['alloc_label']}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
