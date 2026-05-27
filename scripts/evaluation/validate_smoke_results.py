"""
Smoke-test validator for any paper sweep that produces sidecar JSON
timelines (paper §5.8 and successors).

Runs four checks against the harness output of one sweep directory:

  1. Sidecar count vs manifest.
  2. Per-tick timeline sums vs final scalar counters (instrumentation
     consistency).  Verified only for runs whose method is NOT in
     ``--skip-method`` (default: rhcr).
  3. Per-method headline summary: mean ± std of final agent-attributable
     and exogenous-attributable violations.  Theorem-1 sanity check
     ("ours" and "no_buffer" must show zero agent-attributable
     violations across all seeds) is enforced only if those methods
     appear in the manifest.
  4. Figure generation via plot_paper_figures.py.

Concludes with a GO / NO-GO recommendation based on:

  GO   = sidecar count matches manifest AND zero sum-vs-scalar mismatches
         for non-skipped runs AND Theorem-1 invariant holds (if applicable)
         AND figure rendered successfully (or skipped intentionally).

  NO-GO = any of the above fail.

Usage:

  python scripts/evaluation/validate_smoke_results.py \\
      --logs-dir logs/paper/temporal_progression

  # Multiple methods to skip:
  python scripts/evaluation/validate_smoke_results.py \\
      --logs-dir logs/paper/baseline_comparison \\
      --skip-method rhcr --skip-method some_other_broken_baseline

  # Skip the figure step (e.g., results.csv not flushed yet):
  python scripts/evaluation/validate_smoke_results.py \\
      --logs-dir logs/paper/temporal_progression --no-figure

The validator is read-only with respect to the sweep directory.  The
figure is written under ``<logs-dir>/figures/`` by default; override
with ``--figure-out``.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd


# Sentinel return codes — printed and used as the process exit code.
EXIT_GO = 0
EXIT_NO_GO = 1

# Degenerate-run guard (P2 follow-up).  Same threshold the experiment
# runner uses; per-row classifier lives in
# ``scripts.evaluation.validate_paper_claims.classify_row_validity``
# so the two validators reach the same verdict on the same row.
DEFAULT_VALIDITY_THRESHOLD = 0.05


def _load_manifest_methods(manifest_path: Path) -> Dict[str, str]:
    """Return ``{run_id: method}`` from a manifest CSV.  ``method`` is
    pulled from the ``config_json`` column."""
    out: Dict[str, str] = {}
    df = pd.read_csv(manifest_path)
    for _, row in df.iterrows():
        try:
            cfg = json.loads(row["config_json"])
        except (TypeError, ValueError):
            cfg = {}
        out[row["run_id"]] = cfg.get("method", "unknown")
    return out


def _load_results(results_path: Path) -> Optional[pd.DataFrame]:
    if not results_path.exists():
        return None
    df = pd.read_csv(results_path)
    return df


def step_validity_gate(
    logs_dir: Path, threshold: float,
) -> Tuple[bool, int, int, List[str]]:
    """Per-row degenerate-run guard.

    Returns ``(ok, n_total, n_invalid, examples)`` where ``ok`` is
    ``False`` if any row fails the guard (the smoke run is then NO-GO
    regardless of the other steps -- a Confirmed verdict on top of
    100/100 solver-error rows is exactly the failure mode this
    follow-up exists to catch).
    """
    # Import lazily so the smoke validator works even when
    # validate_paper_claims has been moved / renamed; the shared
    # classifier is the canonical implementation.
    try:
        from scripts.evaluation.validate_paper_claims import (
            classify_row_validity,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: validity classifier import failed: {exc}; skipping gate.")
        return False, 0, 0, []

    results_path = logs_dir / "results.csv"
    if not results_path.exists():
        print(f"  WARN: results.csv missing at {results_path}; cannot apply guard.")
        return False, 0, 0, []

    df = pd.read_csv(results_path)
    n_total = len(df)
    invalid: List[Tuple[str, str]] = []
    for _, row in df.iterrows():
        rd = row.to_dict()
        reason = classify_row_validity(rd, threshold)
        if reason is not None:
            rid = str(rd.get("run_id", ""))[:12]
            invalid.append((rid, reason))

    examples: List[str] = []
    print(f"  Rows checked         : {n_total}")
    print(f"  Validity threshold   : {threshold}")
    print(f"  Invalid runs         : {len(invalid)}")
    if invalid:
        print(f"  FAIL: {len(invalid)} row(s) failed the degenerate-run guard:")
        for rid, reason in invalid[:10]:
            examples.append(f"{rid}: {reason}")
            print(f"    - {rid}: {reason}")
        if len(invalid) > 10:
            print(f"    ... and {len(invalid) - 10} more.")
        return False, n_total, len(invalid), examples
    print("  OK   : every row passes run_valid / solver_fail_fraction / "
          "global_replans checks.")
    return True, n_total, 0, examples


def step1_sidecar_count(logs_dir: Path) -> Tuple[bool, int, int]:
    """Returns (ok, n_sidecars, n_manifest_runs)."""
    manifest_path = logs_dir / "manifest.csv"
    timelines_dir = logs_dir / "timelines"
    n_manifest = 0
    if manifest_path.exists():
        n_manifest = len(pd.read_csv(manifest_path))
    n_sidecars = 0
    if timelines_dir.exists():
        n_sidecars = sum(1 for _ in timelines_dir.glob("*.json"))
    print(f"  Manifest rows : {n_manifest}")
    print(f"  Sidecar JSONs : {n_sidecars}")
    if not manifest_path.exists():
        print("  WARN: manifest.csv missing — cannot validate sweep completeness.")
        return False, n_sidecars, n_manifest
    if n_sidecars != n_manifest:
        print(f"  FAIL: sidecar count {n_sidecars} != manifest rows {n_manifest}.")
        return False, n_sidecars, n_manifest
    print("  OK   : every manifest run has a sidecar JSON.")
    return True, n_sidecars, n_manifest


def step2_timeline_consistency(
    logs_dir: Path,
    skip_methods: Set[str],
) -> Tuple[bool, int, int, List[str]]:
    """Returns (ok, n_checked, n_mismatches, mismatch_messages).

    Only checks runs whose method is NOT in ``skip_methods``.  Requires
    results.csv (the scalar counters live there)."""
    results_path = logs_dir / "results.csv"
    timelines_dir = logs_dir / "timelines"
    df = _load_results(results_path)
    if df is None:
        print("  WARN: results.csv missing — cannot validate timeline sums "
              "against scalar counters.  Re-run after the harness flushes.")
        return False, 0, 0, []

    n_checked = 0
    mismatches: List[str] = []
    for _, row in df.iterrows():
        method = str(row.get("method", "unknown"))
        if method in skip_methods:
            continue
        if str(row.get("status", "")) != "ok":
            continue
        run_id = row["run_id"]
        sidecar = timelines_dir / f"{run_id}.json"
        if not sidecar.exists():
            continue
        try:
            with sidecar.open() as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            mismatches.append(f"{run_id} ({method}): sidecar unreadable: {exc}")
            continue
        n_checked += 1
        agent_sum = sum(data.get("violations_agent_timeline", []))
        exo_sum = sum(data.get("violations_exogenous_timeline", []))
        try:
            agent_scalar = int(row["violations_agent_attributable"])
            exo_scalar = int(row["violations_exogenous_attributable"])
        except (KeyError, ValueError):
            continue
        if agent_sum != agent_scalar:
            mismatches.append(
                f"{run_id[:12]} method={method}: agent timeline_sum="
                f"{agent_sum} scalar={agent_scalar}"
            )
        if exo_sum != exo_scalar:
            mismatches.append(
                f"{run_id[:12]} method={method}: exo timeline_sum="
                f"{exo_sum} scalar={exo_scalar}"
            )

    print(f"  Runs checked (non-skipped, status=ok): {n_checked}")
    if skip_methods:
        print(f"  Skipped methods               : {sorted(skip_methods)}")
    if mismatches:
        print(f"  FAIL: {len(mismatches)} sum-vs-scalar mismatch(es):")
        for m in mismatches[:10]:
            print(f"    - {m}")
        if len(mismatches) > 10:
            print(f"    ... and {len(mismatches) - 10} more.")
        return False, n_checked, len(mismatches), mismatches
    if n_checked == 0:
        print("  WARN: no runs to check (all methods skipped or no status=ok rows).")
        return False, 0, 0, []
    print("  OK   : every non-skipped sum matches its scalar counter.")
    return True, n_checked, 0, []


def step3_method_summary(
    logs_dir: Path,
    skip_methods: Set[str],
) -> Tuple[bool, Dict[str, Dict[str, Tuple[float, float, int]]], List[str]]:
    """Returns (theorem1_ok, summary, theorem1_violations).

    ``summary`` is ``{method: {"agent": (mean, std, n), "exo": (mean, std, n)}}``.
    Theorem-1 check: methods named "ours" and "no_buffer" must show
    agent_attr == 0 across all seeds.  Enforced only if those methods
    are present in the manifest."""
    manifest_path = logs_dir / "manifest.csv"
    if not manifest_path.exists():
        print("  WARN: manifest.csv missing.")
        return False, {}, []
    methods = _load_manifest_methods(manifest_path)
    timelines_dir = logs_dir / "timelines"

    by_method_agent: Dict[str, List[int]] = defaultdict(list)
    by_method_exo: Dict[str, List[int]] = defaultdict(list)
    for run_id, method in methods.items():
        sidecar = timelines_dir / f"{run_id}.json"
        if not sidecar.exists():
            continue
        try:
            with sidecar.open() as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        by_method_agent[method].append(
            sum(data.get("violations_agent_timeline", []))
        )
        by_method_exo[method].append(
            sum(data.get("violations_exogenous_timeline", []))
        )

    summary: Dict[str, Dict[str, Tuple[float, float, int]]] = {}
    print(f"  {'method':<14} {'n':>4}  "
          f"{'agent_attr mean ± std':>26}  {'exo_attr mean ± std':>26}")
    print(f"  {'-'*14} {'-'*4}  {'-'*26}  {'-'*26}")
    for method in sorted(by_method_agent.keys()):
        a = by_method_agent[method]
        e = by_method_exo[method]
        a_mean = statistics.mean(a) if a else 0.0
        a_std = statistics.pstdev(a) if len(a) > 1 else 0.0
        e_mean = statistics.mean(e) if e else 0.0
        e_std = statistics.pstdev(e) if len(e) > 1 else 0.0
        summary[method] = {
            "agent": (a_mean, a_std, len(a)),
            "exo":   (e_mean, e_std, len(e)),
        }
        skipped_marker = "  [skipped]" if method in skip_methods else ""
        print(f"  {method:<14} {len(a):>4}  "
              f"{a_mean:>10.2f} ± {a_std:<10.2f}    "
              f"{e_mean:>10.2f} ± {e_std:<10.2f}{skipped_marker}")

    # Theorem-1 invariant: "ours" and "no_buffer" must show 0
    # agent-attributable violations.  Only check if present.
    theorem1_violations: List[str] = []
    for theorem1_method in ("ours", "no_buffer"):
        if theorem1_method not in by_method_agent:
            continue
        if theorem1_method in skip_methods:
            continue
        seeds = by_method_agent[theorem1_method]
        nonzero = [v for v in seeds if v != 0]
        if nonzero:
            theorem1_violations.append(
                f"{theorem1_method}: {len(nonzero)}/{len(seeds)} seeds have "
                f"non-zero agent_attr (values: {nonzero[:5]}"
                f"{'...' if len(nonzero) > 5 else ''}); "
                f"Theorem 1 predicts 0."
            )

    if theorem1_violations:
        print()
        print("  FAIL: Theorem-1 invariant violated:")
        for v in theorem1_violations:
            print(f"    - {v}")
        return False, summary, theorem1_violations

    has_theorem1_methods = any(
        m in by_method_agent and m not in skip_methods
        for m in ("ours", "no_buffer")
    )
    if has_theorem1_methods:
        print()
        print("  OK   : Theorem-1 invariant holds (ours / no_buffer "
              "agent_attr == 0 across all seeds).")
    else:
        print()
        print("  N/A  : neither 'ours' nor 'no_buffer' present in manifest; "
              "Theorem-1 check skipped.")
    return True, summary, []


def step4_figure(
    logs_dir: Path,
    figure_name: str,
    figure_out: Path,
) -> Tuple[bool, Optional[Path]]:
    """Invoke plot_paper_figures.py and verify the PNG appears."""
    results_path = logs_dir / "results.csv"
    if not results_path.exists():
        print("  WARN: results.csv missing — skipping figure step.")
        return False, None
    figure_out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parent.parent.parent
    plotter = repo_root / "scripts" / "evaluation" / "plot_paper_figures.py"
    cmd = [
        sys.executable, str(plotter),
        "--results", str(logs_dir),
        "--out", str(figure_out),
        "--figure", figure_name,
    ]
    print(f"  Invoking: {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        print("  FAIL: plotter timed out (120s).")
        return False, None
    if r.returncode != 0:
        print(f"  FAIL: plotter rc={r.returncode}")
        if r.stderr:
            print(f"    stderr: {r.stderr.strip()[:500]}")
        return False, None
    png = figure_out / f"{figure_name}.png"
    if not png.exists():
        print(f"  FAIL: plotter exited 0 but {png.name} not found in "
              f"{figure_out}.")
        return False, None
    size_kb = png.stat().st_size / 1024.0
    print(f"  OK   : wrote {png} ({size_kb:.1f} KB).")
    return True, png


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Validate the smoke-test artifacts of a paper sweep "
                    "(sidecar count, timeline consistency, per-method "
                    "summary, figure generation).",
    )
    p.add_argument("--logs-dir", required=True, type=Path,
                   help="Sweep output directory (the one containing "
                        "manifest.csv, results.csv, and timelines/).")
    p.add_argument("--skip-method", action="append", default=None,
                   help="Method name to exclude from the consistency check "
                        "and Theorem-1 invariant.  Repeatable.  Default: rhcr.")
    p.add_argument("--figure-name", default="temporal_progression",
                   help="Figure to render via plot_paper_figures.py "
                        "(default: temporal_progression).")
    p.add_argument("--figure-out", type=Path, default=None,
                   help="Where to write the figure (default: "
                        "<logs-dir>/figures/).")
    p.add_argument("--no-figure", action="store_true",
                   help="Skip step 4 (figure generation).  Use when "
                        "results.csv is not yet flushed.")
    p.add_argument("--validity-threshold", type=float,
                   default=DEFAULT_VALIDITY_THRESHOLD,
                   help=("Per-row solver_fail_fraction threshold for "
                         "the degenerate-run guard.  "
                         f"Default {DEFAULT_VALIDITY_THRESHOLD}."))
    args = p.parse_args(argv)

    skip_methods: Set[str] = set(args.skip_method) if args.skip_method else {"rhcr"}
    logs_dir: Path = args.logs_dir.resolve()
    figure_out: Path = args.figure_out or (logs_dir / "figures")

    print(f"Validating sweep at: {logs_dir}")
    print(f"Skipping methods   : {sorted(skip_methods)}")
    print()

    print("STEP 0 — Degenerate-run guard (P2 follow-up)")
    step0_ok, n_rows_total, n_invalid, invalid_examples = step_validity_gate(
        logs_dir, float(args.validity_threshold),
    )
    print()

    print("STEP 1 — Sidecar count")
    step1_ok, n_sidecars, n_manifest = step1_sidecar_count(logs_dir)
    print()

    print("STEP 2 — Timeline-sum vs scalar consistency (non-skipped runs)")
    step2_ok, n_checked, n_mismatches, _ = step2_timeline_consistency(
        logs_dir, skip_methods,
    )
    print()

    print("STEP 3 — Per-method summary (mean ± std of final counts)")
    step3_ok, summary, theorem1_violations = step3_method_summary(
        logs_dir, skip_methods,
    )
    print()

    if args.no_figure:
        print("STEP 4 — Figure generation [skipped via --no-figure]")
        step4_ok = True
        png_path: Optional[Path] = None
    else:
        print(f"STEP 4 — Figure generation ({args.figure_name})")
        step4_ok, png_path = step4_figure(
            logs_dir, args.figure_name, figure_out,
        )
    print()

    # GO / NO-GO
    print("=" * 72)
    # Validity-gate failure is fatal regardless of the other steps:
    # a clean sidecar/timeline check on top of 100/100 solver-error
    # rows is still GO, but those rows are not valid input.  Refuse
    # to recommend GO if any row failed the guard.
    go = step0_ok and step1_ok and step2_ok and step3_ok and step4_ok
    if go:
        print("RECOMMENDATION: GO")
        print(f"  - Validity gate passed ({n_rows_total} rows, 0 invalid).")
        print("  - Sidecar count matches manifest.")
        print("  - Timeline sums match scalar counters for all non-skipped runs.")
        if any(m in summary for m in ("ours", "no_buffer")):
            print("  - Theorem-1 invariant holds (zero agent-attributable "
                  "violations for ours/no_buffer).")
        if png_path:
            print(f"  - Figure rendered: {png_path}")
        print()
        print("  Proceed to the next sweep batch.")
        return EXIT_GO
    print("RECOMMENDATION: NO-GO")
    if not step0_ok:
        print(f"  - Degenerate-run guard failed "
              f"({n_invalid}/{n_rows_total} row(s) invalid); "
              f"a Confirmed verdict on this CSV would be on tainted "
              f"data.  Examples:")
        for example in invalid_examples[:5]:
            print(f"      {example}")
    if not step1_ok:
        print(f"  - Sidecar count mismatch ({n_sidecars} vs {n_manifest}).")
    if not step2_ok:
        if n_mismatches:
            print(f"  - {n_mismatches} timeline-sum vs scalar mismatch(es) "
                  f"in non-skipped runs (instrumentation bug).")
        else:
            print("  - Could not validate timeline consistency "
                  "(results.csv missing or no runs to check).")
    if not step3_ok:
        print("  - Theorem-1 invariant violated:")
        for v in theorem1_violations:
            print(f"      {v}")
    if not step4_ok and not args.no_figure:
        print("  - Figure generation failed.")
    print()
    print("  Investigate the failures above before launching the main batch.")
    return EXIT_NO_GO


if __name__ == "__main__":
    raise SystemExit(main())
