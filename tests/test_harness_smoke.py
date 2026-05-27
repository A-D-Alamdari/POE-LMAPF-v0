"""
Paper-experiment harness smoke test.

Verifies that:

  1. Every YAML under ``configs/eval/paper/`` parses and expands to a
     non-zero, deterministic number of runs.
  2. The cartesian counts match the paper's documented totals.
  3. A 1-seed / 1-config slice of ``baseline_comparison.yaml`` runs
     end-to-end and writes a well-formed ``results.csv`` with all
     expected columns.

The slice uses ``simulation_steps = 200`` (much shorter than the
2000-step paper default) and the smallest ``num_agents`` density on
the random map, so it completes in a few seconds.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Make ``scripts.evaluation.run_paper_experiment`` importable.
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. Manifest expansion sanity
# ---------------------------------------------------------------------------


EXPECTED_RUN_COUNTS = {
    "solver_sensitivity":      3360,
    "fov_safety":               400,
    "scaling_agents":          1040,
    "scaling_exogenous":        760,
    "baseline_comparison":      720,
    "aux_h_r_decoupling":       110,
    "token_passing_ablation":    60,
}


@pytest.mark.parametrize("yaml_stem,expected", list(EXPECTED_RUN_COUNTS.items()))
def test_yaml_expands_to_documented_run_count(yaml_stem: str, expected: int):
    from scripts.evaluation.run_paper_experiment import expand_manifest

    spec_path = REPO_ROOT / "configs" / "eval" / "paper" / f"{yaml_stem}.yaml"
    assert spec_path.exists(), f"missing config: {spec_path}"
    spec = yaml.safe_load(spec_path.read_text())
    rows = expand_manifest(spec)
    assert len(rows) == expected, (
        f"{yaml_stem}: cartesian product produced {len(rows)} runs, "
        f"expected {expected}"
    )
    # Run IDs must be unique.
    ids = {r["run_id"] for r in rows}
    assert len(ids) == len(rows), "duplicate run_ids in expanded manifest"


# ---------------------------------------------------------------------------
# 2. End-to-end smoke run
# ---------------------------------------------------------------------------


def _build_smoke_spec(base_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Trim ``baseline_comparison.yaml`` down to a 4-run slice:
    1 seed, 1 method per slice if available, 1 ``num_agents`` density,
    1 map.  Reduces ``steps`` to 200 for fast execution.
    """
    spec = {
        "name":        "baseline_comparison_smoke",
        "description": "Smoke slice of baseline_comparison",
        "base":        dict(base_spec.get("base", {})),
        "groups":      [],
        "seeds":       [0],
    }
    spec["base"]["steps"] = 200
    # Use only the random-map group, smallest density, all 4 methods.
    for grp in base_spec["groups"]:
        sweep = grp.get("sweep", {})
        if any("random-64-64-10" in str(p) for p in sweep.get("map_path", [])):
            min_agents = min(sweep.get("num_agents", [10]))
            min_humans = min(sweep.get("num_humans", [10]))
            spec["groups"].append({
                "sweep": {
                    "method":     list(sweep["method"]),
                    "map_path":   [next(p for p in sweep["map_path"]
                                        if "random-64-64-10" in str(p))],
                    "num_agents": [min_agents],
                    "num_humans": [min_humans],
                }
            })
            break
    return spec


def test_baseline_smoke_slice_writes_results_csv(tmp_path: Path):
    from scripts.evaluation.run_paper_experiment import (
        expand_manifest, run_one,
        _append_rows,  # type: ignore[attr-defined]
    )

    spec_path = REPO_ROOT / "configs" / "eval" / "paper" / "baseline_comparison.yaml"
    base_spec = yaml.safe_load(spec_path.read_text())
    spec = _build_smoke_spec(base_spec)
    rows = expand_manifest(spec)
    assert rows, "smoke slice expanded to zero runs"
    assert len(rows) == 4, f"expected 4 method-rows, got {len(rows)}"

    out_dir = tmp_path / "smoke_out"
    out_dir.mkdir()
    results_path = out_dir / "results.csv"

    t0 = time.perf_counter()
    completed: List[Dict[str, Any]] = []
    for row in rows:
        rec = run_one(row)
        completed.append(rec)
    _append_rows(results_path, completed)
    elapsed = time.perf_counter() - t0

    assert results_path.exists(), "results.csv was not written"
    with results_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        out_rows = list(reader)

    # All 4 runs landed.
    assert len(out_rows) == 4

    # Required columns present.
    required = {
        "run_id", "experiment", "method", "map_path",
        "num_agents", "num_humans", "seed", "steps",
        "throughput", "completed_tasks",
        "violations_agent_attributable",
        "violations_exogenous_attributable",
        "safety_violations", "wait_fraction",
        "status", "wall_clock_s",
    }
    missing = required - set(out_rows[0].keys())
    assert not missing, f"results.csv missing columns: {sorted(missing)}"

    # All runs must have status=ok.
    statuses = [r.get("status") for r in out_rows]
    assert all(s == "ok" for s in statuses), (
        f"some runs failed: {statuses}; rows={out_rows}"
    )

    # Smoke slice budget: ought to finish in a few seconds, but allow
    # generous slack for slower CI machines.
    assert elapsed < 30.0, (
        f"smoke slice took {elapsed:.2f}s — too slow for CI; "
        f"per-run mean = {elapsed / 4.0:.2f}s"
    )

    # Print so pytest -v / -s shows the wall-clock for the report.
    print(f"\n[harness smoke] 4 runs in {elapsed:.2f}s "
          f"(mean {elapsed / 4.0:.2f}s/run)")
