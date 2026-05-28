"""Audit step 08 — schema-version matrix + in-row invariant check
for every committed results.csv under logs/.

Read-only.  No re-runs, no edits.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")

SCHEMA_PROBES = {
    # (column name) -> nickname for the matrix
    "violations_def1_agent_attributable":         "def1",
    "violations_def1_exogenous_attributable":     "def1_exo",  # redundant; group below
    "deadlock_count":                             "deadlock",
    "arrival_rate_per_step":                      "arrival_rate",
    "throughput_utilization":                     "util",
    # P11 wait-kind columns:
    "physics_revert_wait_steps":                  "p_revert",
    "delay_wait_steps":                           "delay_w",
    "safe_wait_steps":                            "safe_w",
    "yield_wait_steps":                           "yield_w",
    # P6 event-debounce columns:
    "safety_violation_events":                    "sv_events",
    "violations_agent_attributable_events":       "agent_events",
    "violations_exogenous_attributable_events":   "exo_events",
    # P3.4 attribution split:
    "violations_agent_attributable":              "agent_attr",
    "violations_exogenous_attributable":          "exo_attr",
    # Universal columns:
    "total_wait_steps":                           "wait_total",
    "wait_fraction":                              "wait_frac",
    "throughput":                                 "thr",
    "completed_tasks":                            "completed",
    "steps":                                      "steps",
    "num_agents":                                 "num_agents",
    "safety_violations":                          "sv",
}


def _to_float(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _to_int(x: Any) -> Optional[int]:
    f = _to_float(x)
    if f is None:
        return None
    if abs(f - round(f)) < 1e-6:
        return int(round(f))
    return None


def scan_csv(path: Path) -> Dict[str, Any]:
    """Read header + every row; compute schema flags + per-invariant
    pass counts."""
    with path.open() as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows: List[Dict[str, str]] = list(reader)

    fset = set(fields)
    out: Dict[str, Any] = {
        "path": str(path.relative_to(ROOT)),
        "rows": len(rows),
        "cols": len(fields),
        "schema": {
            nick: col in fset
            for col, nick in SCHEMA_PROBES.items()
        },
    }

    # ------------------------------------------------------------
    # Invariant checks (only over rows where the required columns
    # are populated; report counts).
    # ------------------------------------------------------------
    def per_row_check(name: str, predicate, required_cols):
        if not required_cols.issubset(fset):
            out.setdefault("invariants", {})[name] = {
                "tested": 0, "passed": 0, "skipped": len(rows),
                "reason": f"missing column(s): {sorted(required_cols - fset)}",
            }
            return
        tested = 0
        passed = 0
        skipped = 0
        first_failures: List[Dict[str, Any]] = []
        for r in rows:
            try:
                ok = predicate(r)
            except Exception:
                ok = None
            if ok is None:
                skipped += 1
                continue
            tested += 1
            if ok:
                passed += 1
            elif len(first_failures) < 3:
                first_failures.append({
                    k: r.get(k, "") for k in sorted(required_cols)
                })
        out.setdefault("invariants", {})[name] = {
            "tested": tested,
            "passed": passed,
            "skipped": skipped,
            "first_failures": first_failures,
        }

    # 1. four-bucket wait invariant (Prompt C / P11) — only on rows
    #    that have all four wait-kind columns.
    def _four_bucket(r):
        total = _to_int(r.get("total_wait_steps"))
        safe = _to_int(r.get("safe_wait_steps"))
        yld = _to_int(r.get("yield_wait_steps"))
        rev = _to_int(r.get("physics_revert_wait_steps"))
        dly = _to_int(r.get("delay_wait_steps"))
        if None in (total, safe, yld, rev, dly):
            return None
        return total == (safe + yld + rev + dly)

    per_row_check(
        "four-bucket: total == safe+yield+revert+delay",
        _four_bucket,
        {"total_wait_steps", "safe_wait_steps", "yield_wait_steps",
         "physics_revert_wait_steps", "delay_wait_steps"},
    )

    # 1b. two-bucket (pre-P11) — for CSVs that lack the new columns
    #     but have safe/yield.  Identical when revert == delay == 0.
    def _two_bucket(r):
        total = _to_int(r.get("total_wait_steps"))
        safe = _to_int(r.get("safe_wait_steps"))
        yld = _to_int(r.get("yield_wait_steps"))
        if None in (total, safe, yld):
            return None
        return total == (safe + yld)

    per_row_check(
        "two-bucket (legacy): total == safe+yield",
        _two_bucket,
        {"total_wait_steps", "safe_wait_steps", "yield_wait_steps"},
    )

    # 2. attribution: safety_violations == agent_attr + exo_attr
    def _attr_split(r):
        sv = _to_int(r.get("safety_violations"))
        a = _to_int(r.get("violations_agent_attributable"))
        e = _to_int(r.get("violations_exogenous_attributable"))
        if None in (sv, a, e):
            return None
        return sv == (a + e)

    per_row_check(
        "attribution: sv == agent_attr + exo_attr",
        _attr_split,
        {"safety_violations", "violations_agent_attributable",
         "violations_exogenous_attributable"},
    )

    # 3. wait_fraction == total_wait_steps / (num_agents * steps)
    #    Allow a 1e-3 absolute tolerance to absorb the float rounding
    #    the CSV writer applies via the f"{v:.6f}" format.
    def _wait_frac(r):
        wf = _to_float(r.get("wait_fraction"))
        total = _to_float(r.get("total_wait_steps"))
        n = _to_int(r.get("num_agents"))
        s = _to_int(r.get("steps"))
        if wf is None or total is None or n is None or s is None or n*s == 0:
            return None
        expected = total / (n * s)
        return abs(wf - expected) <= 1e-3

    per_row_check(
        "wait_fraction == total_wait / (num_agents * steps)",
        _wait_frac,
        {"wait_fraction", "total_wait_steps", "num_agents", "steps"},
    )

    # 4. throughput == completed_tasks / steps
    def _thr(r):
        thr = _to_float(r.get("throughput"))
        c = _to_int(r.get("completed_tasks"))
        s = _to_int(r.get("steps"))
        if thr is None or c is None or s is None or s == 0:
            return None
        expected = c / s
        return abs(thr - expected) <= 1e-3

    per_row_check(
        "throughput == completed / steps",
        _thr,
        {"throughput", "completed_tasks", "steps"},
    )

    # 5. safety_violation_events <= safety_violations
    def _events_bound(r):
        ev = _to_int(r.get("safety_violation_events"))
        sv = _to_int(r.get("safety_violations"))
        if ev is None or sv is None:
            return None
        return ev <= sv

    per_row_check(
        "events <= agent-ticks (debounce bound)",
        _events_bound,
        {"safety_violation_events", "safety_violations"},
    )

    return out


def main() -> None:
    paths = sorted(ROOT.glob("logs/**/results.csv"))
    results = [scan_csv(p) for p in paths]

    # Schema matrix.
    print("== schema matrix ==")
    nicks = ["def1", "deadlock", "arrival_rate", "util", "p_revert",
             "delay_w", "safe_w", "yield_w", "sv_events"]
    header = f"{'csv':70s}  rows  cols  " + " ".join(f"{n:>7s}" for n in nicks)
    print(header)
    print("-" * len(header))
    for r in results:
        flags = " ".join(
            f"{'Y' if r['schema'][n] else '.':>7s}" for n in nicks
        )
        print(f"{r['path']:70s}  {r['rows']:4d}  {r['cols']:4d}  {flags}")

    # Invariant pass-fraction table.
    print("\n== invariants (passed / tested; skipped) ==")
    inv_names = [
        "four-bucket: total == safe+yield+revert+delay",
        "two-bucket (legacy): total == safe+yield",
        "attribution: sv == agent_attr + exo_attr",
        "wait_fraction == total_wait / (num_agents * steps)",
        "throughput == completed / steps",
        "events <= agent-ticks (debounce bound)",
    ]
    for inv in inv_names:
        print(f"\n--- {inv} ---")
        for r in results:
            i = r.get("invariants", {}).get(inv, {})
            t, p, s = i.get("tested", 0), i.get("passed", 0), i.get("skipped", 0)
            tag = ""
            if t and p == t:
                tag = "PASS"
            elif t == 0:
                tag = f"skipped ({i.get('reason', 'all rows skipped')})"
            else:
                tag = f"FAIL ({t-p}/{t} rows broke)"
            print(f"  {r['path']:65s}  {p}/{t} (skipped {s})  {tag}")

    return results


if __name__ == "__main__":
    main()
