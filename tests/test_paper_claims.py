"""
Paper-claim validator tests.

* **Test A** — schema validation: every entry in
  ``docs/PAPER_NUMERICAL_CLAIMS.yaml`` carries the required fields,
  no duplicate ``claim_id``, every section is in {5.2, 5.3, 5.4, 5.5}.
* **Test B** — synthetic dry-run: a fabricated ``results.csv`` with
  exactly the paper's expected values produces all-Confirmed
  verdicts.
* **Test C** — synthetic perturbation: tweak one row by 50 %, the
  affected claim flips to ``Refuted`` and a replacement sentence is
  generated.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    annotate_map_stem,
    evaluate,
    load_results,
    run_validation,
    validate_schema,
)

CLAIMS_YAML = REPO_ROOT / "docs" / "PAPER_NUMERICAL_CLAIMS.yaml"


def _load_claims() -> List[Dict[str, Any]]:
    return yaml.safe_load(CLAIMS_YAML.read_text())["claims"]


# ---------------------------------------------------------------------------
# Test A — schema
# ---------------------------------------------------------------------------


def test_yaml_schema_is_valid():
    claims = _load_claims()
    problems = validate_schema(claims)
    assert problems == [], f"schema problems: {problems}"
    assert claims, "claims list is empty"


def test_no_duplicate_claim_ids():
    claims = _load_claims()
    ids = [c["claim_id"] for c in claims]
    assert len(ids) == len(set(ids)), (
        f"duplicate claim_ids: "
        f"{[i for i in ids if ids.count(i) > 1]}"
    )


def test_every_section_in_allowed_set():
    claims = _load_claims()
    bad = [c for c in claims if c["section"] not in {"5.2", "5.3", "5.4", "5.5"}]
    assert not bad, f"out-of-range sections: {[c['claim_id'] for c in bad]}"


# ---------------------------------------------------------------------------
# Test B — synthetic results that match expected
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# Resume-prompt-7: every test row must carry the strong predicate's
# required columns (audit 09, Decision 4c).  The fixtures in this file
# pre-date that predicate; without these defaults every synth row would
# trip the missing-required-columns precondition and the synthetic
# Confirmed / Refuted assertions below would never reach the
# comparison.  The defaults represent a clean run -- status ok, Tier-1
# fired, no solver failures, no deadlock, sub-saturation utilization --
# so the strong predicate classifies every synth row as VALID.
_STRONG_PREDICATE_CLEAN_DEFAULTS = {
    "status": "ok",
    "global_replans": 100,
    "solver_timeouts": 0,
    "solver_errors": 0,
    "deadlock_count": 0,
    # ``num_agents`` is a sweep axis in most fixtures and overrides this
    # default via setdefault.  The default is here purely so the
    # axis-free fov_safety fixtures (which don't sweep agent count) still
    # satisfy the strong predicate's column-presence check.
    "num_agents": 50,
    "throughput_utilization": 0.5,
}


def _with_strong_predicate_defaults(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Stamp the strong-predicate required columns onto every row.

    The row's own ``status`` (and any other explicit override) wins; this
    only fills gaps.  ``num_agents`` is already supplied by every
    fixture (it's a sweep axis).
    """
    for r in rows:
        for k, v in _STRONG_PREDICATE_CLEAN_DEFAULTS.items():
            r.setdefault(k, v)
    return rows


def test_synthetic_matching_results_yield_confirmed(tmp_path: Path):
    """Synthesise per-source CSVs whose aggregated values exactly hit
    the expected_value of every concrete (non-structural) claim."""
    rows_per_source: Dict[str, List[Dict[str, Any]]] = {}

    # Source ``solver_sensitivity``: 6 solvers × 2 maps × 1 horizon × 1
    # density × 10 seeds.  Throughput tuned so range is exactly 0.02
    # on warehouse and 0.025 on random; planning times tuned so PIBT2
    # is at 60 ms, LaCAM/LaCAM* at 400 ms, and LNS2/PBS/CBSH2 at 2900
    # ms (≥ 75 agents).
    solver_throughput = {
        "cbsh2": 0.20, "lacam": 0.21, "lacam_official": 0.215,
        "lns2": 0.205, "pbs": 0.225, "pibt2": 0.22,
    }
    solver_planning = {
        "cbsh2": 2900, "lacam": 400, "lacam_official": 450,
        "lns2": 2900, "pbs": 2900, "pibt2": 60,
    }
    rows_ss: List[Dict[str, Any]] = []
    for solver in solver_throughput:
        for stem, mp in [
            ("random-64-64-10", "data/maps/random-64-64-10.map"),
            ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map"),
        ]:
            base = solver_throughput[solver]
            # Slightly tighter range on warehouse.
            tput = base if stem == "random-64-64-10" else (base - 0.01)
            for seed in range(10):
                for n_agents in (25, 50, 75, 100):
                    rows_ss.append({
                        "status": "ok",
                        "global_solver": solver,
                        "horizon": 20,
                        "num_agents": n_agents,
                        "num_humans": 50,
                        "map_path": mp,
                        "seed": seed,
                        "throughput": tput,
                        "mean_planning_time_ms": solver_planning[solver],
                        "violations_agent_attributable": 0,
                        "violations_exogenous_attributable": 100,
                    })
    rows_per_source["solver_sensitivity"] = rows_ss

    # Source ``fov_safety``: ratio at r_safe=0 / r_safe=1 = 6.5 (in [5,8]).
    rows_fs: List[Dict[str, Any]] = []
    for stem, mp in [
        ("random-64-64-10", "data/maps/random-64-64-10.map"),
        ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map"),
    ]:
        for fov in (2, 3, 4, 5, 6):
            for safety in (0, 1, 2, 3):
                exo = 130 if safety == 0 else 20  # ratio = 6.5
                tput = 0.205 if (fov == 4 and safety == 1) else 0.20
                for seed in range(10):
                    rows_fs.append({
                        "status": "ok",
                        "fov_radius": fov, "safety_radius": safety,
                        "map_path": mp, "seed": seed,
                        "throughput": tput,
                        "violations_exogenous_attributable": exo,
                        "violations_agent_attributable": 0,
                    })
    rows_per_source["fov_safety"] = rows_fs

    # Source ``scaling_agents``: throughput linear in num_agents.
    rows_sa: List[Dict[str, Any]] = []
    for solver in ("lacam_official", "lacam", "lns2", "pibt2"):
        for stem, mp, n_humans, agent_grid in [
            ("random-64-64-10", "data/maps/random-64-64-10.map", 20,
             [10, 20, 30, 40, 50, 60, 70, 80, 90]),
            ("warehouse-10-20-10-2-1", "data/maps/warehouse-10-20-10-2-1.map", 40,
             [50, 100, 150, 200, 250, 300, 350, 400]),
            ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map", 60,
             [50, 100, 150, 200, 250, 300, 350, 400, 450]),
        ]:
            for n_agents in agent_grid:
                # Linear ramp + tiny jitter so R^2 ~ 0.99.
                tput = 0.001 * n_agents
                planning = (
                    60 if solver == "pibt2"
                    else (1000 if n_agents >= 350 else 200)
                )
                if solver == "lns2" and stem == "warehouse-10-20-10-2-2" and n_agents >= 350:
                    planning = 2700
                for seed in range(10):
                    rows_sa.append({
                        "status": "ok",
                        "global_solver": solver,
                        "map_path": mp,
                        "num_agents": n_agents,
                        "num_humans": n_humans,
                        "horizon": 20,
                        "seed": seed,
                        "throughput": tput + 1e-4 * seed,
                        "mean_planning_time_ms": planning,
                        "violations_agent_attributable": 0,
                        "violations_exogenous_attributable": 50,
                    })
    rows_per_source["scaling_agents"] = rows_sa

    # Source ``scaling_exogenous``: violations linear in num_humans on
    # warehouse maps.
    rows_sx: List[Dict[str, Any]] = []
    for solver in ("lacam_official", "lacam", "lns2", "pibt2"):
        for stem, mp, n_agents, hum_grid in [
            ("random-64-64-10", "data/maps/random-64-64-10.map", 50,
             [10, 20, 40, 60, 80, 100]),
            ("warehouse-10-20-10-2-1", "data/maps/warehouse-10-20-10-2-1.map", 100,
             [20, 40, 60, 80, 100, 120]),
            ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map", 150,
             [20, 40, 60, 80, 100, 120, 150]),
        ]:
            for n_h in hum_grid:
                exo = 1.5 * n_h
                for seed in range(10):
                    rows_sx.append({
                        "status": "ok",
                        "global_solver": solver,
                        "map_path": mp,
                        "num_agents": n_agents,
                        "num_humans": n_h,
                        "horizon": 20,
                        "seed": seed,
                        "throughput": 0.2,
                        "violations_agent_attributable": 0,
                        "violations_exogenous_attributable": exo + 0.01 * seed,
                    })
    rows_per_source["scaling_exogenous"] = rows_sx

    # Source ``baseline_comparison``: tuned to hit every §5.5 claim.
    rows_bc: List[Dict[str, Any]] = []
    densities = [10, 20, 30, 40, 50, 60, 70, 80, 90,
                 50, 100, 150, 200, 250, 300, 350, 400, 450]
    for stem, mp, n_humans, dens in [
        ("random-64-64-10", "data/maps/random-64-64-10.map", 20,
         [10, 20, 30, 40, 50, 60, 70, 80, 90]),
        ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map", 100,
         [50, 100, 150, 200, 250, 300, 350, 400, 450]),
    ]:
        for n_agents in dens:
            for method in ("ours", "rhcr", "pibt2_fr", "no_buffer"):
                # Throughput contracts for §5.5.
                if method == "ours":
                    tput = 0.30 if n_agents <= 200 else 0.30
                elif method == "rhcr":
                    # within 5 % of ours up to |M|<=250, then 10% lower
                    if stem == "warehouse-10-20-10-2-2" and n_agents in (350, 450):
                        tput = 0.30 - 0.30 * 0.10
                    else:
                        tput = 0.30 - 0.30 * 0.04
                elif method == "pibt2_fr":
                    if n_agents <= 100:
                        tput = 0.32  # highest at low M
                    elif n_agents == 200:
                        tput = 0.30
                    else:
                        tput = 0.18  # large drop > 0.10 from M=200 to M=450
                else:  # no_buffer
                    tput = 0.30 - 0.30 * 0.02  # within 3 %

                # Violations contracts.
                if method == "ours":
                    exo_v = 100
                elif method == "rhcr":
                    if stem == "warehouse-10-20-10-2-2" and n_agents == 450:
                        exo_v = 12000  # >10^4
                    else:
                        exo_v = 100 * 20  # 20× ours, in [10,30]
                elif method == "pibt2_fr":
                    exo_v = 100 * 4 if "warehouse" in stem else 100
                else:
                    exo_v = 100 * 6  # in [5,8]

                # Planning / per-step compute.
                if method == "ours" or method == "rhcr":
                    plan_ms = 524 if n_agents == 100 else 100
                elif method == "pibt2_fr":
                    plan_ms = 60
                else:
                    plan_ms = 100
                if method == "pibt2_fr":
                    if n_agents <= 100:
                        dec_ms = 65
                    elif n_agents == 450 and stem == "warehouse-10-20-10-2-2":
                        dec_ms = 2200
                    else:
                        dec_ms = 200
                else:
                    dec_ms = 30

                for seed in range(10):
                    rows_bc.append({
                        "status": "ok",
                        "method": method,
                        "map_path": mp,
                        "num_agents": n_agents,
                        "num_humans": n_humans,
                        "horizon": 20,
                        "seed": seed,
                        "throughput": tput,
                        "mean_planning_time_ms": plan_ms,
                        "mean_decision_time_ms": dec_ms,
                        "violations_agent_attributable": 0,
                        "violations_exogenous_attributable": exo_v,
                    })
    rows_per_source["baseline_comparison"] = rows_bc

    # Persist.  Stamp the strong-predicate required columns (audit 09,
    # Decision 4c) onto every row before write so the synth fixtures
    # don't trip the missing-required-columns precondition.
    results_root = tmp_path / "logs" / "paper"
    for source, rows in rows_per_source.items():
        d = results_root / source
        d.mkdir(parents=True, exist_ok=True)
        _write_csv(d / "results.csv", _with_strong_predicate_defaults(rows))

    # run_validation returns (verdicts, structural_claims, validity_report)
    # since 812fc90 added the degenerate-run guard.
    verdicts, _structural, validity_report = run_validation(
        CLAIMS_YAML, results_root, section_filter="all")

    # Synth fixtures carry no failure counters / global_replans, so the
    # degenerate-run guard should classify every row as valid.
    assert validity_report.n_invalid == 0, (
        f"Synth fixture unexpectedly tripped the degenerate-run guard: "
        f"{validity_report.n_invalid}/{validity_report.total_rows} invalid")

    refuted = [(c["claim_id"], v) for c, v in verdicts if v.status == "Refuted"]
    weaker  = [(c["claim_id"], v) for c, v in verdicts if v.status == "Now weaker"]
    confirmed = [(c["claim_id"], v) for c, v in verdicts if v.status == "Confirmed"]

    # All-confirmed is the contract; allow Skipped (e.g. for "summary"
    # claims whose source is 'all' and still resolves) but no Refuted /
    # Now weaker.
    assert not refuted, f"Refuted claims under matching synth: {refuted}"
    assert not weaker,  f"Now-weaker claims under matching synth: {weaker}"
    # Sanity: a non-trivial number of confirmations fired.
    assert len(confirmed) >= 5, (
        f"Only {len(confirmed)} confirmations; check the synth fixture."
    )


# ---------------------------------------------------------------------------
# Test C — synthetic perturbation
# ---------------------------------------------------------------------------


def test_perturbation_flips_a_claim_to_refuted(tmp_path: Path):
    """Perturb a single claim's source CSV by 50 % and confirm the
    affected claim is flipped to Refuted (or Now weaker if the
    direction makes that the right verdict) and a replacement
    sentence is generated."""
    # Use the smallest possible source: fov_safety, 50% perturbation
    # on the r_safe=0 violations (which controls the 5–8× ratio claim).
    rows: List[Dict[str, Any]] = []
    for stem, mp in [
        ("random-64-64-10", "data/maps/random-64-64-10.map"),
        ("warehouse-10-20-10-2-2", "data/maps/warehouse-10-20-10-2-2.map"),
    ]:
        for fov in (2, 3, 4, 5, 6):
            for safety in (0, 1, 2, 3):
                # Perturb: drop the r_safe=0 / r_safe=1 ratio to ~3×.
                if safety == 0:
                    exo = 60      # was 130
                elif safety == 1:
                    exo = 20
                else:
                    exo = 5
                for seed in range(10):
                    rows.append({
                        "status": "ok",
                        "fov_radius": fov, "safety_radius": safety,
                        "map_path": mp, "seed": seed,
                        "throughput": 0.20,
                        "violations_exogenous_attributable": exo,
                        "violations_agent_attributable": 0,
                    })
    results_root = tmp_path / "logs" / "paper"
    d = results_root / "fov_safety"
    d.mkdir(parents=True, exist_ok=True)
    _write_csv(d / "results.csv", _with_strong_predicate_defaults(rows))

    # Run only the §5.3 section so we don't depend on other sources.
    # run_validation returns (verdicts, structural_claims, validity_report)
    # since 812fc90; this test only inspects the verdicts list.
    verdicts, _structural, validity_report = run_validation(
        CLAIMS_YAML, results_root, section_filter="5.3")

    # The perturbation alters values but does not introduce failure
    # counters, so the degenerate-run guard should still pass everything.
    assert validity_report.n_invalid == 0, (
        f"Perturbed fixture unexpectedly tripped the degenerate-run guard: "
        f"{validity_report.n_invalid}/{validity_report.total_rows} invalid")

    refuted = [(c, v) for c, v in verdicts if v.status == "Refuted"]
    refuted_ids = {c["claim_id"] for c, v in refuted}
    assert "viol_ratio_rsafe0_vs_rsafe1_random" in refuted_ids, (
        f"Expected the random-map ratio claim to flip to Refuted; "
        f"refuted_ids={refuted_ids}"
    )
    matching = next(v for c, v in verdicts
                    if c["claim_id"] == "viol_ratio_rsafe0_vs_rsafe1_random")
    assert matching.suggested_replacement, (
        "Refuted claim must carry a suggested replacement sentence"
    )
    # The replacement should mention the new actual value (3× ish).
    assert "3" in matching.suggested_replacement
