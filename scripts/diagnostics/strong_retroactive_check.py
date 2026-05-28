"""Audit step 09: re-run the max_invalid_fraction retroactive check
under a stronger validity predicate that catches degenerate runs the
status='ok' check missed.

Predicate (a run is INVALID iff any of):
  - status != 'ok'                                       (crash; baseline)
  - global_replans == 0                                  (Tier-1 never ran)
  - solver_fail_fraction > 0.05                          (Tier-1 mostly failed)
    where solver_fail_fraction = (timeouts + errors) / max(1, global_replans)
  - deadlock_count / num_agents > 0.10                   (fleet stalled)

Justification: in arrival-saturated regimes (common at |M|>=100) the
throughput column is pinned at the arrival cap regardless of how many
agents are stuck.  A row where 30% of the fleet hit the deadlock
threshold contributes biased values for both throughput (capped by
arrival, not planner) and N_x/N_a (stuck agents emit zero
violations), so it cannot be treated as a valid datum for any paper
claim about planner capacity or safety.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

ROOT = Path("/home/user/POE-LMAPF-v0")

DEADLOCK_FRACTION_LIMIT = 0.10  # 10% of fleet stalled
SOLVER_FAIL_FRACTION_LIMIT = 0.05  # P2 origin


def _f(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _i(x: Any) -> Optional[int]:
    f = _f(x)
    if f is None:
        return None
    if abs(f - round(f)) < 1e-6:
        return int(round(f))
    return None


def is_invalid_status_only(row: Dict[str, str]) -> bool:
    return str(row.get("status", "")).strip().lower() != "ok"


def classify_strong(row: Dict[str, str]) -> Tuple[bool, str]:
    """Return (invalid?, reason).  Reason is a short tag for the
    first failing clause; empty if valid."""
    if str(row.get("status", "")).strip().lower() != "ok":
        return True, "status!=ok"
    gr = _i(row.get("global_replans"))
    if gr is None:
        gr = 0
    if gr == 0:
        return True, "no_global_replan"
    timeouts = _i(row.get("solver_timeouts")) or 0
    errors = _i(row.get("solver_errors")) or 0
    sff = (timeouts + errors) / max(1, gr)
    if sff > SOLVER_FAIL_FRACTION_LIMIT:
        return True, f"solver_fail={sff:.3f}>0.05"
    n = _i(row.get("num_agents"))
    dl = _i(row.get("deadlock_count"))
    if n is not None and n > 0 and dl is not None:
        dl_frac = dl / n
        if dl_frac > DEADLOCK_FRACTION_LIMIT:
            return True, f"deadlock={dl_frac:.3f}>0.10"
    return False, ""


def find_yaml_for_sweep(sweep_dir: Path) -> Tuple[Optional[Path], float]:
    name = sweep_dir.name
    candidates = [
        name,
        re.sub(r"_v\d+(_[0-9a-f]+)?$", "", name),
        re.sub(r"_v\d+$", "", name),
        re.sub(r"_overlap$", "", name),
        re.sub(r"_[0-9a-f]{7}$", "", name),
    ]
    tuning_dir = ROOT / "configs" / "tuning"
    for cand in candidates:
        yp = tuning_dir / f"{cand}.yaml"
        if yp.exists():
            try:
                spec = yaml.safe_load(yp.read_text()) or {}
            except Exception:
                continue
            t = spec.get("max_invalid_fraction")
            return (yp, float(t) if t is not None else float("nan"))
    return (None, float("nan"))


def main() -> None:
    rows_out = []
    sweep_dirs = sorted(
        d for d in (ROOT / "logs" / "tuning").iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )
    for sd in sweep_dirs:
        results = sd / "results.csv"
        invalid_csv = sd / "results_INVALID.csv"
        if not results.exists():
            continue
        if "/horizon/" in str(sd):  # the date-stamped early sweep
            continue
        rows_data = []
        for path in (results, invalid_csv):
            if not path.exists():
                continue
            with path.open() as f:
                rows_data.extend(csv.DictReader(f))
        total = len(rows_data)
        if total == 0:
            continue
        n_status_invalid = sum(1 for r in rows_data
                               if is_invalid_status_only(r))
        reasons: Dict[str, int] = {}
        n_strong_invalid = 0
        worst_deadlock_frac = 0.0
        for r in rows_data:
            bad, reason = classify_strong(r)
            if bad:
                n_strong_invalid += 1
                reasons[reason.split("=")[0]] = reasons.get(
                    reason.split("=")[0], 0) + 1
            # Track the worst deadlock fraction even when not invalid.
            n = _i(r.get("num_agents"))
            dl = _i(r.get("deadlock_count"))
            if n and dl is not None and n > 0:
                worst_deadlock_frac = max(worst_deadlock_frac, dl / n)

        ymap, thresh = find_yaml_for_sweep(sd)
        yaml_str = (str(ymap.relative_to(ROOT))
                    if ymap is not None else "<unmapped>")

        strong_frac = n_strong_invalid / total
        status_frac = n_status_invalid / total
        verdict = "n/a"
        if thresh != thresh:  # NaN
            verdict = "n/a (no YAML threshold)"
        elif strong_frac > thresh:
            verdict = "WOULD FAIL"
        else:
            verdict = "would pass"
        rows_out.append({
            "sweep": str(sd.relative_to(ROOT)),
            "yaml": yaml_str,
            "rows": total,
            "thresh": thresh,
            "status_inv": n_status_invalid,
            "status_frac": status_frac,
            "strong_inv": n_strong_invalid,
            "strong_frac": strong_frac,
            "worst_dl_frac": worst_deadlock_frac,
            "reasons": reasons,
            "verdict": verdict,
        })

    # Render.
    print("\nStrong predicate (status!=ok OR global_replans==0 OR "
          "solver_fail>0.05 OR deadlock/n>0.10):")
    print()
    hdr = (f"{'sweep':50s} {'rows':>5s} {'thresh':>7s} "
           f"{'st_inv':>7s} {'strong':>7s} {'worst_dl':>9s}  "
           f"verdict")
    print(hdr)
    print("-" * len(hdr))
    for r in rows_out:
        print(f"{r['sweep']:50s} {r['rows']:5d} {r['thresh']:7.4f} "
              f"{r['status_inv']:7d} {r['strong_inv']:7d} "
              f"{r['worst_dl_frac']:9.3f}  {r['verdict']}")
        if r["reasons"]:
            tags = ", ".join(f"{k}:{v}" for k, v in sorted(r["reasons"].items()))
            print(f"    reasons: {tags}")

    print()
    n_pass_status = sum(1 for r in rows_out
                        if r["status_inv"] / r["rows"] <= r["thresh"])
    n_pass_strong = sum(1 for r in rows_out
                        if r["strong_frac"] <= r["thresh"])
    n_flip = sum(1 for r in rows_out
                 if (r["status_inv"] / r["rows"] <= r["thresh"])
                 and (r["strong_frac"] > r["thresh"]))
    print(f"sweeps tested: {len(rows_out)}")
    print(f"status-only would-pass: {n_pass_status}")
    print(f"strong-pred would-pass: {n_pass_strong}")
    print(f"FLIPPED verdicts (pass→fail): {n_flip}")
    return rows_out


if __name__ == "__main__":
    main()
