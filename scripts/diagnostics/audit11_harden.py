"""Audit step 11 — harden audit 09's verdict.

Three sensitivities:
  - solver-fail clause alone (the YAML-verbatim P2 predicate; no
    deadlock gate at all): the unarguable floor.
  - deadlock-clause alone at thresholds 0.10 / 0.20 / 0.30.
  - 2x cross-tab per sweep at deadlock=0.30 (most conservative):
    solver-only / deadlock-only / either / both.

Plus hand-verify the solver_fail arithmetic on 3 rows.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import yaml

ROOT = Path("/home/user/POE-LMAPF-v0")
SOLVER_FAIL_LIMIT = 0.05


def _i(x) -> Optional[int]:
    if x is None or x == "":
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if abs(f - round(f)) < 1e-6:
        return int(round(f))
    return None


def status_invalid(r) -> bool:
    return str(r.get("status", "")).strip().lower() != "ok"


def solver_invalid(r) -> bool:
    if status_invalid(r):
        return True
    gr = _i(r.get("global_replans"))
    if gr is None or gr == 0:
        return True
    to = _i(r.get("solver_timeouts")) or 0
    er = _i(r.get("solver_errors")) or 0
    return (to + er) / max(1, gr) > SOLVER_FAIL_LIMIT


def deadlock_invalid_at(r, thr: float) -> bool:
    n = _i(r.get("num_agents"))
    dl = _i(r.get("deadlock_count"))
    if n is None or n == 0 or dl is None:
        return False  # cannot evaluate; do not flag
    return dl / n > thr


def find_yaml_threshold(sweep_dir: Path) -> float:
    name = sweep_dir.name
    cands = [
        name,
        re.sub(r"_v\d+(_[0-9a-f]+)?$", "", name),
        re.sub(r"_v\d+$", "", name),
        re.sub(r"_overlap$", "", name),
        re.sub(r"_[0-9a-f]{7}$", "", name),
    ]
    tuning = ROOT / "configs" / "tuning"
    for c in cands:
        yp = tuning / f"{c}.yaml"
        if yp.exists():
            try:
                spec = yaml.safe_load(yp.read_text()) or {}
                t = spec.get("max_invalid_fraction")
                return float(t) if t is not None else float("nan")
            except Exception:
                continue
    return float("nan")


def scan_sweeps() -> List[Dict]:
    out: List[Dict] = []
    sweep_dirs = sorted(
        d for d in (ROOT / "logs" / "tuning").iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )
    for sd in sweep_dirs:
        if "/horizon/" in str(sd):
            continue
        rcsv = sd / "results.csv"
        if not rcsv.exists():
            continue
        rows = list(csv.DictReader(rcsv.open()))
        inv_csv = sd / "results_INVALID.csv"
        if inv_csv.exists():
            rows.extend(csv.DictReader(inv_csv.open()))
        n = len(rows)
        if n == 0:
            continue

        thr = find_yaml_threshold(sd)
        # Solver-only verdict
        n_solver_only = sum(1 for r in rows if solver_invalid(r))
        # Deadlock-only at three thresholds (solver clause disabled,
        # but status check still applies — a crashed run is invalid
        # regardless).
        n_dl = {}
        for t in (0.10, 0.20, 0.30):
            n_dl[t] = sum(1 for r in rows
                          if status_invalid(r) or deadlock_invalid_at(r, t))
        # Cross-tab at deadlock=0.30:
        n_only_solver_dl30 = 0  # solver yes, deadlock@30 no
        n_only_dl_dl30 = 0      # solver no,  deadlock@30 yes
        n_both = 0              # solver yes, deadlock@30 yes
        n_either = 0
        for r in rows:
            sf = solver_invalid(r)
            dl = deadlock_invalid_at(r, 0.30) or status_invalid(r)
            if sf and dl:
                n_both += 1
            if sf and not dl:
                n_only_solver_dl30 += 1
            if dl and not sf:
                n_only_dl_dl30 += 1
            if sf or dl:
                n_either += 1
        out.append({
            "sweep": str(sd.relative_to(ROOT)),
            "rows": n,
            "thresh": thr,
            "n_solver_only": n_solver_only,
            "n_dl10": n_dl[0.10],
            "n_dl20": n_dl[0.20],
            "n_dl30": n_dl[0.30],
            "n_only_solver": n_only_solver_dl30,
            "n_only_dl30": n_only_dl_dl30,
            "n_both": n_both,
            "n_either": n_either,
        })
    return out


def main() -> None:
    rows = scan_sweeps()

    print("== TASK 1: solver-fail clause ONLY (no deadlock gate) ==\n")
    print(f"{'sweep':50s} {'rows':>5} {'thresh':>7} {'solver_inv':>11} "
          f"{'frac':>6}  verdict")
    print("-" * 90)
    n_fail = 0
    for r in rows:
        frac = r["n_solver_only"] / r["rows"]
        verdict = "WOULD FAIL" if frac > r["thresh"] else "would pass"
        if verdict == "WOULD FAIL":
            n_fail += 1
        print(f"{r['sweep']:50s} {r['rows']:5d} {r['thresh']:7.4f} "
              f"{r['n_solver_only']:11d} {frac:6.3f}  {verdict}")
    print(f"\nSweeps failing on SOLVER CLAUSE ALONE: {n_fail} / {len(rows)}")

    print("\n== TASK 2: deadlock clause alone at thresholds 0.10/0.20/0.30 ==\n")
    print(f"{'sweep':50s} {'rows':>5}  {'dl@0.10':>8} {'dl@0.20':>8} {'dl@0.30':>8}  "
          f"{'fail@0.10':>9} {'fail@0.20':>9} {'fail@0.30':>9}")
    print("-" * 110)
    fail10 = fail20 = fail30 = 0
    for r in rows:
        f10 = r["n_dl10"] / r["rows"]
        f20 = r["n_dl20"] / r["rows"]
        f30 = r["n_dl30"] / r["rows"]
        v10 = "FAIL" if f10 > r["thresh"] else "pass"
        v20 = "FAIL" if f20 > r["thresh"] else "pass"
        v30 = "FAIL" if f30 > r["thresh"] else "pass"
        if v10 == "FAIL": fail10 += 1
        if v20 == "FAIL": fail20 += 1
        if v30 == "FAIL": fail30 += 1
        print(f"{r['sweep']:50s} {r['rows']:5d}  "
              f"{f10:8.3f} {f20:8.3f} {f30:8.3f}  "
              f"{v10:>9} {v20:>9} {v30:>9}")
    print(f"\nSweeps failing dl@0.10: {fail10} / {len(rows)}")
    print(f"Sweeps failing dl@0.20: {fail20} / {len(rows)}")
    print(f"Sweeps failing dl@0.30: {fail30} / {len(rows)}")

    print("\n== TASK 3: cross-tab at deadlock=0.30 (most conservative) ==\n")
    print(f"{'sweep':50s} {'rows':>5}  {'solver':>7} {'dl30':>6} {'both':>6} "
          f"{'sOnly':>6} {'dlOnly':>7} {'either':>7}")
    print("-" * 105)
    for r in rows:
        n_solver_total = r["n_solver_only"]
        n_dl30_total = r["n_dl30"]
        print(f"{r['sweep']:50s} {r['rows']:5d}  "
              f"{n_solver_total:7d} {n_dl30_total:6d} {r['n_both']:6d} "
              f"{r['n_only_solver']:6d} {r['n_only_dl30']:7d} {r['n_either']:7d}")


if __name__ == "__main__":
    main()
