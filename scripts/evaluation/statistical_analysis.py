#!/usr/bin/env python3
"""
Paired statistical-analysis pipeline for POE-LMAPF appendix tables.

Reads a sweep ``results.csv`` produced by ``run_paper_experiment.py``
and emits four files into ``--out``:

  * ``pairwise_comparisons.csv`` — one row per (condition, metric)
    pair against the reference condition; columns include n,
    means, mean diff, BCa 95 % CI, Shapiro-Wilk p, Wilcoxon
    statistic + p, sign-test p, Cohen's d, rank-biserial r,
    Wilcoxon power at α=0.05, raw p, BH-FDR-adjusted p, and a
    "*" / "**" / "***" / "ns" verdict.
  * ``friedman_omnibus.csv`` — one row per metric; columns include
    χ², df, p-value, and Kendall's W.
  * ``descriptive_stats.csv`` — one row per (condition, metric)
    pair; columns include n, mean, std, median, IQR low / high,
    min, max, skewness, kurtosis.
  * ``significance_report.tex`` and ``.md`` — booktabs LaTeX and
    GitHub-flavoured Markdown summaries built from
    ``pairwise_comparisons.csv``.

Usage::

    python scripts/evaluation/statistical_analysis.py \\
        --results logs/paper/baseline_comparison \\
        --out     stats/paper/baseline_comparison \\
        --groupby method \\
        --against ours \\
        --metrics throughput,violations_exogenous_attributable,wait_fraction
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats as sps

logger = logging.getLogger("paper_stats")


# ---------------------------------------------------------------------------
# Optional deps with graceful fallbacks
# ---------------------------------------------------------------------------


def _bh_fdr(pvalues: Sequence[float]) -> List[float]:
    """Benjamini-Hochberg FDR.  Uses ``statsmodels`` if available;
    otherwise falls back to a NaN-safe manual implementation."""
    try:
        from statsmodels.stats.multitest import multipletests
        valid_mask = np.isfinite(pvalues)
        out = np.full(len(pvalues), float("nan"))
        if valid_mask.any():
            valid = np.asarray(pvalues, dtype=float)[valid_mask]
            _, adj, *_ = multipletests(valid, method="fdr_bh")
            out[valid_mask] = adj
        return out.tolist()
    except Exception:
        # Manual BH on NaN-safe subset.
        ps = np.asarray(pvalues, dtype=float)
        idx = np.where(np.isfinite(ps))[0]
        out = np.full(ps.shape, float("nan"))
        if idx.size == 0:
            return out.tolist()
        sub = ps[idx]
        order = np.argsort(sub)
        ranked = sub[order]
        m = len(ranked)
        adj = np.minimum.accumulate(
            (ranked * m / np.arange(1, m + 1))[::-1]
        )[::-1]
        adj = np.clip(adj, 0.0, 1.0)
        out_sub = np.empty_like(adj)
        out_sub[order] = adj
        out[idx] = out_sub
        return out.tolist()


def _ttest_paired_power(d_eff: float, n: int, alpha: float = 0.05) -> float:
    """Post-hoc power of a two-sided paired test at effect size
    ``d_eff`` and sample size ``n``.  Uses statsmodels' analytical
    paired-t power if available; otherwise computes a Monte-Carlo
    approximation under normality (1000 trials).

    Wilcoxon's asymptotic relative efficiency vs. paired t under
    normality is ~95 %, so this is a tight upper bound on Wilcoxon
    power and is the standard rebuttal-grade approximation.
    """
    if not np.isfinite(d_eff) or n < 2:
        return float("nan")
    try:
        from statsmodels.stats.power import TTestPower
        return float(TTestPower().solve_power(
            effect_size=abs(d_eff), nobs=n, alpha=alpha,
            power=None, alternative="two-sided",
        ))
    except Exception:
        rng = np.random.default_rng(0)
        rejected = 0
        trials = 1000
        for _ in range(trials):
            sample = rng.normal(loc=d_eff, size=n)
            t, p = sps.ttest_1samp(sample, 0.0)
            if np.isfinite(p) and p < alpha:
                rejected += 1
        return rejected / trials


def _bca_ci_diff(diffs: np.ndarray, alpha: float = 0.05,
                 n_resamples: int = 4000) -> Tuple[float, float]:
    """BCa bootstrap CI for the mean of paired differences.  Uses
    ``scipy.stats.bootstrap(method="BCa")`` when ``n >= 10`` and a
    percentile bootstrap otherwise (BCa is unreliable for very small
    n)."""
    if diffs.size < 2:
        return (float("nan"), float("nan"))
    if diffs.size >= 10:
        method = "BCa"
    else:
        method = "percentile"
    try:
        rng = np.random.default_rng(0)
        res = sps.bootstrap(
            (diffs,), np.mean, confidence_level=1 - alpha,
            n_resamples=n_resamples, method=method,
            random_state=rng,
        )
        return (float(res.confidence_interval.low),
                float(res.confidence_interval.high))
    except Exception as exc:
        logger.warning("BCa bootstrap failed (%s); using percentile.", exc)
        rng = np.random.default_rng(0)
        idx = rng.integers(0, diffs.size, size=(n_resamples, diffs.size))
        boot_means = diffs[idx].mean(axis=1)
        lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])
        return (float(lo), float(hi))


# ---------------------------------------------------------------------------
# IO
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


def _resolve_results_path(arg: Path) -> Path:
    return arg / "results.csv" if arg.is_dir() else arg


# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


def _key(row: Dict[str, Any], fields: Sequence[str]) -> Tuple[Any, ...]:
    return tuple(row.get(f) for f in fields)


def _pair_seeds(
    rows: List[Dict[str, Any]],
    groupby: Sequence[str],
    against_field: str,
    against_value: Any,
    metric: str,
    seed_field: str = "seed",
) -> Dict[Tuple[Any, ...], List[Tuple[float, float]]]:
    """For each group of ``groupby \\ {against_field}`` values, return
    a list of (reference_value, condition_value) pairs across seeds.

    Pairs are formed by matching seeds within the same group.
    """
    other_fields = [f for f in groupby if f != against_field]
    # group by (other_fields, against_field) -> {seed: metric}
    table: Dict[Tuple[Any, ...], Dict[Any, Dict[Any, float]]] = {}
    for r in rows:
        key_other = tuple(r.get(f) for f in other_fields)
        cond = r.get(against_field)
        seed = r.get(seed_field)
        m = r.get(metric)
        if m is None:
            continue
        try:
            m = float(m)
        except (TypeError, ValueError):
            continue
        table.setdefault(key_other, {}).setdefault(cond, {})[seed] = m

    out: Dict[Tuple[Any, ...], List[Tuple[float, float]]] = {}
    for key_other, conds in table.items():
        ref_map = conds.get(against_value, {})
        if not ref_map:
            continue
        for cond, seeds_to_v in conds.items():
            if cond == against_value:
                continue
            paired: List[Tuple[float, float]] = []
            for seed, v_ref in ref_map.items():
                v_cond = seeds_to_v.get(seed)
                if v_cond is None or not np.isfinite(v_cond) or not np.isfinite(v_ref):
                    continue
                paired.append((v_ref, v_cond))
            if paired:
                out[key_other + (cond,)] = paired
    return out


# ---------------------------------------------------------------------------
# Per-(condition, metric) statistics
# ---------------------------------------------------------------------------


def _verdict(adj_p: float) -> str:
    if not np.isfinite(adj_p):
        return "ns"
    if adj_p < 0.001:
        return "***"
    if adj_p < 0.01:
        return "**"
    if adj_p < 0.05:
        return "*"
    return "ns"


def compute_pair_stats(pairs: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
    """Run every paired test on a (reference, condition) sample.

    Returns a partial row missing ``adj_p_value`` and ``verdict``,
    which are filled in after FDR is applied across all conditions
    for that metric.
    """
    arr = np.asarray(pairs, dtype=float)
    if arr.size == 0:
        return {"n": 0}
    refs = arr[:, 0]
    cnds = arr[:, 1]
    diffs = cnds - refs
    n = diffs.size

    out: Dict[str, Any] = {
        "n": n,
        "reference_mean": float(refs.mean()),
        "condition_mean": float(cnds.mean()),
        "mean_diff": float(diffs.mean()),
    }

    # BCa 95 % CI on mean diff.
    ci_lo, ci_hi = _bca_ci_diff(diffs)
    out["ci95_lo"] = ci_lo
    out["ci95_hi"] = ci_hi

    # Shapiro-Wilk on differences.
    if n >= 3 and np.std(diffs) > 0:
        try:
            sw = sps.shapiro(diffs)
            out["shapiro_p"] = float(sw.pvalue)
        except Exception:
            out["shapiro_p"] = float("nan")
    else:
        out["shapiro_p"] = float("nan")

    # Wilcoxon signed-rank.
    if n >= 1 and np.any(diffs != 0):
        try:
            w = sps.wilcoxon(diffs, zero_method="wilcox", alternative="two-sided")
            out["wilcoxon_stat"] = float(w.statistic)
            out["wilcoxon_p"] = float(w.pvalue)
        except Exception:
            out["wilcoxon_stat"] = float("nan")
            out["wilcoxon_p"] = float("nan")
    else:
        # All differences zero — perfectly equal samples.
        out["wilcoxon_stat"] = 0.0
        out["wilcoxon_p"] = 1.0

    # Sign test (binomial on positives among nonzero diffs).
    nonzero = diffs[diffs != 0]
    if nonzero.size > 0:
        n_pos = int((nonzero > 0).sum())
        try:
            bt = sps.binomtest(n_pos, nonzero.size, p=0.5, alternative="two-sided")
            out["sign_test_p"] = float(bt.pvalue)
        except Exception:
            out["sign_test_p"] = float("nan")
    else:
        out["sign_test_p"] = 1.0

    # Cohen's d for paired differences.
    if n >= 2 and np.std(diffs, ddof=1) > 0:
        out["cohens_d"] = float(diffs.mean() / np.std(diffs, ddof=1))
    else:
        out["cohens_d"] = 0.0 if diffs.mean() == 0 else float("nan")

    # Rank-biserial r derived from Wilcoxon W on |diffs|.
    if n >= 1 and np.any(diffs != 0):
        ranks = sps.rankdata(np.abs(diffs))
        rsum_pos = ranks[diffs > 0].sum()
        rsum_neg = ranks[diffs < 0].sum()
        rsum_total = ranks.sum()
        if rsum_total > 0:
            out["rank_biserial_r"] = float((rsum_pos - rsum_neg) / rsum_total)
        else:
            out["rank_biserial_r"] = 0.0
    else:
        out["rank_biserial_r"] = 0.0

    # Post-hoc Wilcoxon power (paired-t proxy).
    out["power"] = _ttest_paired_power(out["cohens_d"], n)

    out["raw_p_value"] = out["wilcoxon_p"]
    return out


# ---------------------------------------------------------------------------
# Friedman omnibus
# ---------------------------------------------------------------------------


def compute_friedman_per_metric(
    rows: List[Dict[str, Any]],
    against_field: str,
    metric: str,
    seed_field: str = "seed",
) -> Optional[Dict[str, Any]]:
    """Return Friedman χ², df, p, Kendall's W for the seed-paired
    matrix of conditions × seeds.  Returns ``None`` when fewer than 3
    conditions or fewer than 3 seeds are available (Friedman degenerate)."""
    table: Dict[Any, Dict[Any, float]] = {}
    for r in rows:
        cond = r.get(against_field)
        seed = r.get(seed_field)
        m = r.get(metric)
        if m is None:
            continue
        try:
            m = float(m)
        except (TypeError, ValueError):
            continue
        table.setdefault(cond, {})[seed] = m

    if len(table) < 3:
        return None
    common_seeds = set.intersection(*(set(d.keys()) for d in table.values()))
    if len(common_seeds) < 3:
        return None

    seed_list = sorted(common_seeds)
    cond_list = sorted(table.keys(), key=str)
    matrix = np.array(
        [[table[c][s] for s in seed_list] for c in cond_list],
        dtype=float,
    )
    try:
        chi2, p = sps.friedmanchisquare(*matrix)
    except Exception as exc:
        logger.warning("Friedman failed for %s: %s", metric, exc)
        return None
    df = matrix.shape[0] - 1
    n = matrix.shape[1]
    k = matrix.shape[0]
    kendall_w = float(chi2) / (n * (k - 1)) if (n * (k - 1)) > 0 else float("nan")
    return {
        "metric": metric,
        "n_conditions": int(k),
        "n_seeds": int(n),
        "df": int(df),
        "chi_squared": float(chi2),
        "p_value": float(p),
        "kendall_w": float(kendall_w),
    }


# ---------------------------------------------------------------------------
# Descriptive stats
# ---------------------------------------------------------------------------


def compute_descriptive_per_condition(
    rows: List[Dict[str, Any]],
    against_field: str,
    metric: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    table: Dict[Any, List[float]] = {}
    for r in rows:
        cond = r.get(against_field)
        m = r.get(metric)
        if m is None:
            continue
        try:
            m = float(m)
        except (TypeError, ValueError):
            continue
        table.setdefault(cond, []).append(m)
    for cond, values in sorted(table.items(), key=lambda kv: str(kv[0])):
        v = np.asarray(values, dtype=float)
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        q1, q3 = np.quantile(v, [0.25, 0.75])
        out.append({
            "condition": cond,
            "metric": metric,
            "n": int(v.size),
            "mean": float(v.mean()),
            "std": float(v.std(ddof=1)) if v.size > 1 else 0.0,
            "median": float(np.median(v)),
            "iqr_lo": float(q1),
            "iqr_hi": float(q3),
            "min": float(v.min()),
            "max": float(v.max()),
            "skew": float(sps.skew(v)) if v.size > 2 else float("nan"),
            "kurtosis": float(sps.kurtosis(v)) if v.size > 3 else float("nan"),
        })
    return out


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _md_significance_report(
    rows_per_metric: Dict[str, List[Dict[str, Any]]],
    against_value: Any,
) -> str:
    headers = [
        "Condition", "n", "mean diff [95% CI]",
        "Wilcoxon p (FDR)", "Cohen's d", "rank-biserial r", "verdict",
    ]
    lines: List[str] = []
    for metric, rows in rows_per_metric.items():
        lines.append(f"## Metric: `{metric}`  vs. `{against_value}`\n")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in rows:
            ci = (f"[{r['ci95_lo']:.2g}, {r['ci95_hi']:.2g}]"
                  if np.isfinite(r["ci95_lo"]) and np.isfinite(r["ci95_hi"])
                  else "[—, —]")
            mean_diff = (f"{r['mean_diff']:.3g} {ci}"
                         if np.isfinite(r["mean_diff"]) else "—")
            wilc = (f"{r['raw_p_value']:.3f} ({r['adj_p_value']:.3f})"
                    if np.isfinite(r["raw_p_value"]) else "—")
            d = (f"{r['cohens_d']:.2f}" if np.isfinite(r["cohens_d"]) else "—")
            rr = (f"{r['rank_biserial_r']:.2f}"
                  if np.isfinite(r["rank_biserial_r"]) else "—")
            cond_label = " / ".join(str(x) for x in r["condition_key"])
            lines.append("| " + " | ".join([
                cond_label, str(r["n"]), mean_diff, wilc, d, rr, r["verdict"],
            ]) + " |")
        lines.append("")
    return "\n".join(lines)


def _tex_escape(s: str) -> str:
    return (str(s)
            .replace("&", r"\&")
            .replace("%", r"\%")
            .replace("_", r"\_")
            .replace("±", r"$\pm$"))


def _tex_significance_report(
    rows_per_metric: Dict[str, List[Dict[str, Any]]],
    against_value: Any,
) -> str:
    chunks: List[str] = [
        r"% Auto-generated by statistical_analysis.py — do not edit by hand.",
        r"% Requires booktabs and (optionally) siunitx.",
    ]
    for metric, rows in rows_per_metric.items():
        chunks.append(r"\begin{table}[t]")
        chunks.append(r"\centering")
        chunks.append(r"\small")
        chunks.append(r"\begin{tabular}{lrrrrrl}")
        chunks.append(r"\toprule")
        chunks.append(
            r"Condition vs.\ " + _tex_escape(str(against_value)) +
            r" & $n$ & mean diff [95\% CI] & Wilcoxon $p$ (FDR) "
            r"& Cohen's $d$ & rank-biserial $r$ & verdict \\"
        )
        chunks.append(r"\midrule")
        for r in rows:
            ci = (f"[{r['ci95_lo']:.2g}, {r['ci95_hi']:.2g}]"
                  if np.isfinite(r["ci95_lo"]) and np.isfinite(r["ci95_hi"])
                  else "—")
            mean_diff = (f"{r['mean_diff']:.3g} {ci}"
                         if np.isfinite(r["mean_diff"]) else "—")
            wilc = (f"{r['raw_p_value']:.3f} ({r['adj_p_value']:.3f})"
                    if np.isfinite(r["raw_p_value"]) else "—")
            d = (f"{r['cohens_d']:.2f}" if np.isfinite(r["cohens_d"]) else "—")
            rr = (f"{r['rank_biserial_r']:.2f}"
                  if np.isfinite(r["rank_biserial_r"]) else "—")
            cond_label = " / ".join(str(x) for x in r["condition_key"])
            cells = [
                _tex_escape(cond_label),
                str(r["n"]),
                _tex_escape(mean_diff),
                _tex_escape(wilc),
                d, rr,
                _tex_escape(r["verdict"]),
            ]
            chunks.append(" & ".join(cells) + r" \\")
        chunks.append(r"\bottomrule")
        chunks.append(r"\end{tabular}")
        chunks.append(rf"\caption{{Paired comparisons against {_tex_escape(str(against_value))} on metric \texttt{{{_tex_escape(metric)}}}.  $p$-values use the Wilcoxon signed-rank test, paired across seeds; FDR-adjusted via Benjamini--Hochberg.}}")
        chunks.append(rf"\label{{tab:stats_{_tex_escape(metric)}}}")
        chunks.append(r"\end{table}")
        chunks.append("")
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# CSV writers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({k for row in rows for k in row.keys()})
    # Put a stable subset first for readability.
    front = [
        "metric", "condition_key", "condition", "n",
        "reference_mean", "condition_mean", "mean_diff",
        "ci95_lo", "ci95_hi", "shapiro_p",
        "wilcoxon_stat", "wilcoxon_p", "sign_test_p",
        "cohens_d", "rank_biserial_r", "power",
        "raw_p_value", "adj_p_value", "verdict",
    ]
    head = [f for f in front if f in fieldnames]
    rest = [f for f in fieldnames if f not in head]
    fieldnames = head + rest
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            row_out = {k: row.get(k, "") for k in fieldnames}
            for k, v in row_out.items():
                if isinstance(v, tuple):
                    row_out[k] = "/".join(str(x) for x in v)
            w.writerow(row_out)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_analysis(
    results_path: Path,
    out_dir: Path,
    groupby: Sequence[str],
    against_field: str,
    against_value: Any,
    metrics: Sequence[str],
    seed_field: str = "seed",
) -> Dict[str, Path]:
    """Top-level analysis routine — used by both the CLI and the
    automatic invocation hook from ``run_paper_experiment.py``.
    Returns a dict of output paths.
    """
    rows = filter_ok(load_results(results_path))
    out_dir.mkdir(parents=True, exist_ok=True)

    if against_field not in groupby:
        groupby = list(groupby) + [against_field]

    pairwise_rows: List[Dict[str, Any]] = []
    by_metric: Dict[str, List[Dict[str, Any]]] = {}
    for metric in metrics:
        groups = _pair_seeds(rows, groupby, against_field, against_value,
                             metric, seed_field=seed_field)
        per_metric: List[Dict[str, Any]] = []
        for cond_key, pairs in sorted(groups.items(), key=lambda kv: str(kv[0])):
            stats_row = compute_pair_stats(pairs)
            stats_row["metric"] = metric
            stats_row["condition_key"] = cond_key
            stats_row["condition"] = cond_key[-1]
            per_metric.append(stats_row)

        # Apply FDR within metric.
        raw = [r.get("raw_p_value", float("nan")) for r in per_metric]
        adj = _bh_fdr(raw)
        for r, a in zip(per_metric, adj):
            r["adj_p_value"] = a
            r["verdict"] = _verdict(a)

        pairwise_rows.extend(per_metric)
        by_metric[metric] = per_metric

    pairwise_path = out_dir / "pairwise_comparisons.csv"
    _write_csv(pairwise_path, pairwise_rows)

    # Friedman omnibus.
    friedman_rows: List[Dict[str, Any]] = []
    for metric in metrics:
        f = compute_friedman_per_metric(rows, against_field, metric,
                                        seed_field=seed_field)
        if f is not None:
            friedman_rows.append(f)
    friedman_path = out_dir / "friedman_omnibus.csv"
    _write_csv(friedman_path, friedman_rows)

    # Descriptive stats.
    desc_rows: List[Dict[str, Any]] = []
    for metric in metrics:
        desc_rows.extend(compute_descriptive_per_condition(rows, against_field, metric))
    desc_path = out_dir / "descriptive_stats.csv"
    _write_csv(desc_path, desc_rows)

    # Reports.
    md = _md_significance_report(by_metric, against_value)
    md_path = out_dir / "significance_report.md"
    md_path.write_text(md, encoding="utf-8")

    tex = _tex_significance_report(by_metric, against_value)
    tex_path = out_dir / "significance_report.tex"
    tex_path.write_text(tex, encoding="utf-8")

    logger.info("statistical analysis written to %s", out_dir)
    return {
        "pairwise": pairwise_path,
        "friedman": friedman_path,
        "descriptive": desc_path,
        "report_md": md_path,
        "report_tex": tex_path,
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="POE-LMAPF appendix-grade paired-stats pipeline")
    p.add_argument("--results", required=True, type=Path,
                   help="Directory containing results.csv (or path to the file)")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory for stats artefacts")
    p.add_argument("--groupby", required=True,
                   help="Comma-separated list of fields used to form paired groups; "
                        "the field carrying the condition labels MUST be one of them.")
    p.add_argument("--against", required=True,
                   help="Reference condition value (e.g. 'ours', 'lacam_official').")
    p.add_argument("--against-field", default=None,
                   help="Field whose value matches --against.  Default: the first "
                        "--groupby entry whose values include --against.")
    p.add_argument("--metrics", required=True,
                   help="Comma-separated metric column names.")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(levelname)s %(name)s | %(message)s")

    results_path = _resolve_results_path(args.results)
    if not results_path.exists():
        logger.error("results.csv not found at %s", results_path)
        return 2

    groupby = [s.strip() for s in args.groupby.split(",") if s.strip()]
    metrics = [s.strip() for s in args.metrics.split(",") if s.strip()]

    against_field = args.against_field
    if against_field is None:
        # Auto-detect: the first groupby column containing --against as a value.
        rows = load_results(results_path)
        for f in groupby:
            vals = {r.get(f) for r in rows}
            if args.against in vals or _coerce(args.against) in vals:
                against_field = f
                break
        if against_field is None:
            logger.error(
                "Cannot find a --groupby field containing the reference value %r. "
                "Pass --against-field explicitly.",
                args.against,
            )
            return 2

    # Coerce 'ours' / 'lacam_official' / etc. to the same type the CSV
    # parser produced (string).  Numeric reference values are coerced
    # via _coerce.
    against_value: Any = _coerce(args.against) if args.against.replace(".", "", 1).isdigit() else args.against

    run_analysis(
        results_path=results_path,
        out_dir=args.out,
        groupby=groupby,
        against_field=against_field,
        against_value=against_value,
        metrics=metrics,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
