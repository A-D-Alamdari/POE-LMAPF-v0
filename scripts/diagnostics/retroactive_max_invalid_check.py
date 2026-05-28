"""Retroactive audit: for every committed tuning results.csv, compute
the invalid-cell fraction it WOULD have had under the intended
``max_invalid_fraction`` (as written in each sweep's YAML).

The runner's per-row validity predicate is ``_row_is_valid`` from
``scripts/evaluation/run_paper_experiment.py``: True iff the
``run_valid`` column is True (or missing — legacy rows are treated as
valid by the runner).  We mirror that predicate here.

The runner also separates rows into ``results.csv`` (valid only) and
``results_INVALID.csv`` (invalid only) when the splitting code is on
the path — but several sweep directories carry only ``results.csv``.
We sum from both files when both exist, and from whichever exists when
only one does.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

ROOT = Path("/home/user/POE-LMAPF-v0")


def _row_is_valid(row: Dict[str, str]) -> bool:
    val = row.get("run_valid")
    if val is None or val == "":
        return True
    s = str(val).strip().lower()
    return s in ("true", "1", "yes")


def find_yaml_for_sweep(sweep_dir: Path) -> Tuple[Path, float] | None:
    """Try to map a logs/tuning/<name>/ directory back to a YAML
    config under configs/tuning/.  Returns (yaml_path,
    intended_threshold) or None.  Strip date stamps and -vN / -overlap
    suffixes from the directory name when matching against YAML stems.
    """
    name = sweep_dir.name
    # Strip suffixes like _v1, _v2, _v3, _overlap, _<7-hex-chars>,
    # and the entire trailing "_2026-MM-DD_HH-MM-SS" date stamp.
    candidates: List[str] = []
    candidates.append(name)
    candidates.append(re.sub(r"_v\d+(_[0-9a-f]+)?$", "", name))
    candidates.append(re.sub(r"_v\d+$", "", name))
    candidates.append(re.sub(r"_overlap$", "", name))
    candidates.append(re.sub(r"_[0-9a-f]{7}$", "", name))

    tuning_dir = ROOT / "configs" / "tuning"
    for cand in candidates:
        yp = tuning_dir / f"{cand}.yaml"
        if yp.exists():
            try:
                spec = yaml.safe_load(yp.read_text()) or {}
            except Exception:
                continue
            t = spec.get("max_invalid_fraction")
            if t is None:
                # YAML doesn't set the field — no intended threshold.
                return (yp, float("nan"))
            return (yp, float(t))
    return None


def main() -> None:
    rows_out: List[Dict[str, object]] = []
    sweep_dirs = sorted(
        d for d in (ROOT / "logs" / "tuning").iterdir()
        if d.is_dir() and not d.name.startswith("_")
    )
    print(f"sweep directories scanned: {len(sweep_dirs)}\n")
    for sd in sweep_dirs:
        results = sd / "results.csv"
        invalid_csv = sd / "results_INVALID.csv"
        if not results.exists():
            # Skip date-stamped intermediate dirs.
            continue
        total = 0
        invalid = 0
        for path in (results, invalid_csv):
            if not path.exists():
                continue
            with path.open() as f:
                for row in csv.DictReader(f):
                    total += 1
                    if not _row_is_valid(row):
                        invalid += 1
        frac = invalid / total if total > 0 else 0.0
        ymap = find_yaml_for_sweep(sd)
        if ymap is None:
            yaml_path = "<no YAML mapping>"
            thresh = float("nan")
        else:
            yp, thresh = ymap
            yaml_path = str(yp.relative_to(ROOT))
        # Pass / fail verdict.
        if thresh != thresh:  # NaN
            verdict = "n/a (YAML sets no threshold)"
        elif frac > thresh:
            verdict = "WOULD FAIL"
        else:
            verdict = "would pass"
        rows_out.append({
            "sweep_dir": str(sd.relative_to(ROOT)),
            "yaml": yaml_path,
            "intended": thresh,
            "total": total,
            "invalid": invalid,
            "frac": frac,
            "verdict": verdict,
        })

    # Render.
    print(f"{'sweep_dir':50s} {'yaml':50s} {'thresh':>8s} "
          f"{'total':>7s} {'invalid':>8s} {'frac':>8s}  verdict")
    print("-" * 150)
    for r in rows_out:
        print(f"{r['sweep_dir']:50s} {r['yaml']:50s} "
              f"{r['intended']:8.4f} {r['total']:7d} {r['invalid']:8d} "
              f"{r['frac']:8.4f}  {r['verdict']}")

    any_fail = any(r["verdict"] == "WOULD FAIL" for r in rows_out)
    print()
    print(f"WOULD FAIL: {sum(1 for r in rows_out if r['verdict'] == 'WOULD FAIL')}")
    print(f"would pass: {sum(1 for r in rows_out if r['verdict'] == 'would pass')}")
    print(f"n/a:        {sum(1 for r in rows_out if r['verdict'].startswith('n/a'))}")
    return rows_out, any_fail


if __name__ == "__main__":
    main()
