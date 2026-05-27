"""
Statistical-analysis pipeline tests.

Four scenarios:

* **Test A** — synthetic identical: ref and condition draws are
  identical (paired).  Wilcoxon p ≈ 1.0; Cohen's d ≈ 0; verdict ``ns``.
* **Test B** — synthetic large effect: condition is uniformly +1 SD
  higher than ref across 30 paired seeds.  Wilcoxon p < 0.001;
  Cohen's d > 0.8; verdict at least ``**``.
* **Test C** — FDR correction: 20 conditions × 30 seeds, half truly
  different (large effect), half identical.  After FDR all 10 truly
  different conditions are flagged significant; at most 1 of 10
  identical conditions is a false positive.
* **Test D** — end-to-end smoke: run the CLI on the harness smoke
  output (the 1-seed slice from the harness smoke test), confirm the
  pipeline does not crash and produces non-empty outputs even at
  trivially small n.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Sequence

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.statistical_analysis import (  # noqa: E402
    _bh_fdr,
    compute_descriptive_per_condition,
    compute_friedman_per_metric,
    compute_pair_stats,
    run_analysis,
)


# ---------------------------------------------------------------------------
# Helpers — synthesise a results.csv on disk.
# ---------------------------------------------------------------------------


def _write_results(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _make_paired_table(
    n_seeds: int,
    conditions: Sequence[str],
    ref_value: str,
    metric: str,
    ref_samples: np.ndarray,
    cond_offsets: Dict[str, np.ndarray],
) -> List[Dict[str, Any]]:
    """Build a synthetic results.csv-like list of rows.  ``ref_samples``
    has shape (n_seeds,).  Each cond's column is ``ref_samples +
    cond_offsets[cond]`` (with ``cond_offsets[ref] == 0`` implied).
    """
    out: List[Dict[str, Any]] = []
    for seed in range(n_seeds):
        out.append({
            "method": ref_value,
            "seed": seed,
            "status": "ok",
            metric: float(ref_samples[seed]),
        })
        for cond in conditions:
            if cond == ref_value:
                continue
            offset = cond_offsets.get(cond)
            v = float(ref_samples[seed] + (offset[seed] if offset is not None else 0.0))
            out.append({
                "method": cond,
                "seed": seed,
                "status": "ok",
                metric: v,
            })
    return out


# ---------------------------------------------------------------------------
# Test A — synthetic identical
# ---------------------------------------------------------------------------


def test_synthetic_identical_yields_ns_verdict(tmp_path: Path):
    rng = np.random.default_rng(0)
    samples = rng.normal(loc=1.0, size=30)
    rows = _make_paired_table(
        n_seeds=30,
        conditions=["ref", "alt"],
        ref_value="ref",
        metric="throughput",
        ref_samples=samples,
        cond_offsets={"alt": np.zeros(30)},   # identical
    )
    csv_path = tmp_path / "results.csv"
    _write_results(csv_path, rows)

    out_dir = tmp_path / "stats"
    run_analysis(
        results_path=csv_path,
        out_dir=out_dir,
        groupby=["method"],
        against_field="method",
        against_value="ref",
        metrics=["throughput"],
    )

    pw_rows = list(csv.DictReader((out_dir / "pairwise_comparisons.csv").open()))
    assert len(pw_rows) == 1
    r = pw_rows[0]
    # Wilcoxon on all-zero diffs -> p == 1.0 (our short-circuit).
    assert float(r["wilcoxon_p"]) >= 0.99
    # Cohen's d should be 0 for identical samples (or NaN if std is 0).
    d = r["cohens_d"]
    assert d in ("0.0", "0", "") or float(d) == 0.0
    assert r["verdict"] == "ns"


# ---------------------------------------------------------------------------
# Test B — synthetic large effect
# ---------------------------------------------------------------------------


def test_synthetic_large_effect_flags_significance(tmp_path: Path):
    rng = np.random.default_rng(1)
    n = 30
    samples = rng.normal(loc=0.0, scale=1.0, size=n)
    # Condition is uniformly +1 SD over reference (very large paired effect).
    offset = np.ones(n)
    rows = _make_paired_table(
        n_seeds=n,
        conditions=["ref", "boosted"],
        ref_value="ref",
        metric="throughput",
        ref_samples=samples,
        cond_offsets={"boosted": offset},
    )
    csv_path = tmp_path / "results.csv"
    _write_results(csv_path, rows)

    out_dir = tmp_path / "stats"
    run_analysis(
        results_path=csv_path,
        out_dir=out_dir,
        groupby=["method"],
        against_field="method",
        against_value="ref",
        metrics=["throughput"],
    )
    pw_rows = list(csv.DictReader((out_dir / "pairwise_comparisons.csv").open()))
    r = next(row for row in pw_rows if row["condition"] == "boosted")

    assert float(r["wilcoxon_p"]) < 1e-3
    assert float(r["cohens_d"]) > 0.8
    # FDR-adjusted p with a single comparison equals raw p; verdict
    # must therefore be at least "**".
    assert r["verdict"] in ("**", "***")


# ---------------------------------------------------------------------------
# Test C — FDR correction power vs. false-positive rate
# ---------------------------------------------------------------------------


def test_fdr_flags_true_positives_and_controls_false_positives(tmp_path: Path):
    rng = np.random.default_rng(42)
    n_seeds = 30
    n_true = 10
    n_null = 10
    metric = "throughput"

    samples = rng.normal(loc=0.0, scale=1.0, size=n_seeds)
    cond_offsets: Dict[str, np.ndarray] = {}
    conditions: List[str] = ["ref"]
    # Truly different conditions: condition uniformly +1 SD over ref.
    for k in range(n_true):
        name = f"true_{k}"
        cond_offsets[name] = np.ones(n_seeds)
        conditions.append(name)
    # Null conditions: independent noise around zero (paired, but
    # mean diff = 0).  Use small jitter so Wilcoxon doesn't trivially
    # short-circuit on all-zero diffs.
    for k in range(n_null):
        name = f"null_{k}"
        cond_offsets[name] = rng.normal(loc=0.0, scale=0.05, size=n_seeds)
        conditions.append(name)

    rows = _make_paired_table(
        n_seeds=n_seeds, conditions=conditions, ref_value="ref",
        metric=metric, ref_samples=samples, cond_offsets=cond_offsets,
    )
    csv_path = tmp_path / "results.csv"
    _write_results(csv_path, rows)

    out_dir = tmp_path / "stats"
    run_analysis(
        results_path=csv_path,
        out_dir=out_dir,
        groupby=["method"],
        against_field="method",
        against_value="ref",
        metrics=[metric],
    )
    pw_rows = list(csv.DictReader((out_dir / "pairwise_comparisons.csv").open()))
    by_name = {r["condition"]: r for r in pw_rows}

    # All 10 true conditions are flagged significant.
    true_sig = [by_name[f"true_{k}"]["verdict"] != "ns" for k in range(n_true)]
    assert all(true_sig), (
        f"FDR rejected some true positives: "
        f"{[by_name[f'true_{k}']['verdict'] for k in range(n_true)]}"
    )

    # Among the 10 nulls, BH-FDR at 5 % should keep the false-discovery
    # rate small.  Tolerate up to 1 false positive across 10 nulls.
    false_pos = sum(by_name[f"null_{k}"]["verdict"] != "ns" for k in range(n_null))
    assert false_pos <= 1, (
        f"too many false positives ({false_pos}) among 10 null conditions; "
        f"verdicts={[by_name[f'null_{k}']['verdict'] for k in range(n_null)]}"
    )


# ---------------------------------------------------------------------------
# Test D — end-to-end smoke
# ---------------------------------------------------------------------------


def test_end_to_end_smoke_on_baseline_slice(tmp_path: Path):
    """Reuse the harness smoke fixture: run a 1-seed / 4-method slice
    of baseline_comparison.yaml and confirm the stats pipeline does
    not crash on tiny n."""
    import yaml
    from scripts.evaluation.run_paper_experiment import (
        expand_manifest, run_one, _append_rows,  # type: ignore[attr-defined]
    )

    spec_path = REPO_ROOT / "configs" / "eval" / "paper" / "baseline_comparison.yaml"
    base_spec = yaml.safe_load(spec_path.read_text())
    spec = {
        "name": "baseline_smoke",
        "base": dict(base_spec.get("base", {})),
        "groups": [],
        "seeds": [0],
    }
    spec["base"]["steps"] = 200
    for grp in base_spec["groups"]:
        sweep = grp.get("sweep", {})
        if any("random-64-64-10" in str(p) for p in sweep.get("map_path", [])):
            min_agents = min(sweep.get("num_agents", [10]))
            min_humans = min(sweep.get("num_humans", [10]))
            spec["groups"].append({"sweep": {
                "method":     list(sweep["method"]),
                "map_path":   [next(p for p in sweep["map_path"]
                                    if "random-64-64-10" in str(p))],
                "num_agents": [min_agents],
                "num_humans": [min_humans],
            }})
            break

    rows = expand_manifest(spec)
    out_dir = tmp_path / "smoke"
    out_dir.mkdir()

    completed = [run_one(r) for r in rows]
    _append_rows(out_dir / "results.csv", completed)

    stats_dir = tmp_path / "stats"
    paths = run_analysis(
        results_path=out_dir / "results.csv",
        out_dir=stats_dir,
        groupby=["method", "map_path", "num_agents"],
        against_field="method",
        against_value="ours",
        metrics=["throughput",
                 "violations_agent_attributable",
                 "violations_exogenous_attributable",
                 "wait_fraction"],
    )

    # Outputs exist, are non-empty, and parse as CSV.
    pw = list(csv.DictReader(paths["pairwise"].open()))
    assert pw, "pairwise_comparisons.csv is empty"
    desc = list(csv.DictReader(paths["descriptive"].open()))
    assert desc, "descriptive_stats.csv is empty"
    md_text = paths["report_md"].read_text()
    tex_text = paths["report_tex"].read_text()
    assert "Wilcoxon" in md_text
    assert r"\toprule" in tex_text
    # Friedman omnibus may be empty (we have only 1 seed) but the
    # file must still exist and not raise.
    paths["friedman"].read_text()


# ---------------------------------------------------------------------------
# Direct unit checks on helpers
# ---------------------------------------------------------------------------


def test_bh_fdr_matches_known_values():
    # Three p-values; manual BH adjustment.
    raw = [0.001, 0.04, 0.20]
    adj = _bh_fdr(raw)
    # The largest raw p is unchanged; intermediate is scaled by 3/2;
    # smallest is scaled by 3.
    assert pytest.approx(adj[2], abs=1e-6) == 0.20
    assert pytest.approx(adj[1], abs=1e-3) == 0.06
    assert pytest.approx(adj[0], abs=1e-3) == 0.003


def test_compute_pair_stats_handles_empty_input():
    out = compute_pair_stats([])
    assert out == {"n": 0}
