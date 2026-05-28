"""Audit step 05: config-key coverage, arrival-rate formula vs CSV,
runner status semantics, end-to-end CSV alignment smoke.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts" / "evaluation"))

from ha_lmapf.core.types import SimConfig
from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.simulation.simulator import Simulator


SIMCONFIG_FIELDS: Set[str] = {f.name for f in dataclasses.fields(SimConfig)}
SIMCONFIG_DEFAULTS: Dict[str, Any] = {
    f.name: (f.default if f.default is not dataclasses.MISSING
             else "<no default>")
    for f in dataclasses.fields(SimConfig)
}

# Schema keys recognised at the manifest top-level (read by expand_manifest).
MANIFEST_KEYS = {
    "name", "base", "seeds", "groups",
}
GROUP_KEYS = {"sweep", "method"}
# `method` may also appear inside a sweep cell; expand_manifest only knows
# `sweep`, but the inner cell can carry `method` which is consumed by
# `_apply_method` after _build_sim_config pops it.
INNER_RECOGNISED = SIMCONFIG_FIELDS | {"method"}


def collect_yaml_keys(p: Path) -> Tuple[Set[str], Set[str]]:
    """Return (top_level_keys, inner_cell_keys) used by p."""
    spec = yaml.safe_load(p.read_text()) or {}
    top = set(spec.keys())
    inner: Set[str] = set()
    if "base" in spec and isinstance(spec["base"], dict):
        inner.update(spec["base"].keys())
    for g in spec.get("groups", []) or []:
        if isinstance(g, dict) and isinstance(g.get("sweep"), dict):
            inner.update(g["sweep"].keys())
    return top, inner


def audit_all_configs(cfg_dir: Path) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    key_use_count: Counter = Counter()
    silent_noop_total: Counter = Counter()
    paper_yamls = sorted(cfg_dir.rglob("*.yaml"))
    for p in paper_yamls:
        try:
            top, inner = collect_yaml_keys(p)
        except Exception as e:
            rows.append({"path": str(p.relative_to(ROOT)),
                          "error": str(e)[:80]})
            continue
        # Classify each top key.
        unrecognised_top = top - MANIFEST_KEYS
        # Inner keys: each must be a SimConfig field or "method".
        silent = inner - INNER_RECOGNISED
        for k in inner:
            key_use_count[k] += 1
        for k in silent:
            silent_noop_total[k] += 1
        rows.append({
            "path": str(p.relative_to(ROOT)),
            "top_keys": sorted(top),
            "inner_keys": sorted(inner),
            "unrecognised_top": sorted(unrecognised_top),
            "silent_inner": sorted(silent),
        })
    return {
        "rows": rows,
        "key_use_count": key_use_count,
        "silent_noop_total": silent_noop_total,
    }


def untunable_simconfig_fields(key_use_count: Counter) -> Set[str]:
    """SimConfig fields never set by any YAML."""
    return SIMCONFIG_FIELDS - set(key_use_count)


# ============================================================
# 2. arrival_rate formula vs CSV column
# ============================================================

def smoke_run_csv():
    """Smallest possible end-to-end smoke: 5x5 open map, 2 agents, 20 steps."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        m = td / "5x5.map"
        m.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
        cfg = SimConfig(
            map_path=str(m),
            num_agents=2, num_humans=0,
            fov_radius=2, safety_radius=1, seed=0, steps=20,
        )
        sim = Simulator(cfg)
        metrics = sim.run()
        tracker = sim.metrics
        header = tracker.csv_header()
        row = tracker.to_csv_row(metrics)
        # Build a single-row CSV with the header, parse it back.
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerow(row)
        buf.seek(0)
        parsed = list(csv.DictReader(buf))
        return header, row, parsed, metrics


def main():
    print("== Config-key coverage ==")
    cfg_dir = ROOT / "configs"
    audit = audit_all_configs(cfg_dir)
    n_yamls = len(audit["rows"])
    n_with_silent = sum(1 for r in audit["rows"] if r.get("silent_inner"))
    print(f"YAMLs scanned: {n_yamls}")
    print(f"YAMLs with at least one silent-no-op inner key: {n_with_silent}")
    print(f"Silent-no-op key totals (key, count of YAMLs using it):")
    for k, n in sorted(audit["silent_noop_total"].items(),
                       key=lambda kv: (-kv[1], kv[0])):
        print(f"  {k!r}: {n}")
    untunable = untunable_simconfig_fields(audit["key_use_count"])
    print(f"\nUntunable SimConfig fields (defined but never set by any YAML): {len(untunable)}")
    for f in sorted(untunable):
        default = SIMCONFIG_DEFAULTS.get(f, "?")
        print(f"  {f!r}  default={default!r}")

    print("\n== arrival-rate formula vs CSV ==")
    print("Formula (simulator.py:582-594):")
    print("  release_rate = H + W (per agent) when task_arrival_rate=None")
    print("  effective_rate = release_rate / num_agents")
    print("  -> system rate = num_agents / (H+W) tasks/step")
    print("CSV column: arrival_rate_per_step = total_tasks / total_steps (empirical)")
    header, row, parsed, m = smoke_run_csv()
    print(f"  smoke run: 5x5 map, 2 agents, 20 steps, seed 0")
    print(f"    metrics.arrival_rate_per_step = {m.arrival_rate_per_step:.6f}")
    theoretical = 2.0 / (5.0 + 5.0)
    print(f"    theoretical (n/(H+W)) = {theoretical:.6f}")
    # Tasks are stochastic + initial-batch (2 tasks at step 0); empirical can drift.

    print("\n== runner status semantics ==")
    print("run_paper_experiment.run_one:")
    print("  try: ... record['status']='ok'; record['error_msg']=''")
    print("  except: record['status']='error'; record['error_msg']=type+str")
    print("  'ok' is assigned AFTER sim.run() and timeline writeout succeed.")
    print("  Any exception in the try block routes to except (status='error').")

    print("\n== CSV alignment (header == row) ==")
    print(f"  len(csv_header()) = {len(header)}")
    print(f"  len(to_csv_row()) = {len(row)}")
    print(f"  len(parsed[0])    = {len(parsed[0])}")
    print(f"  alignment: {'PASS' if len(header) == len(row) == len(parsed[0]) else 'FAIL'}")
    print(f"  parsed sample fields:")
    for k in ("steps", "total_released_tasks", "throughput",
              "arrival_rate_per_step", "throughput_utilization"):
        print(f"    {k!r}: {parsed[0].get(k)!r}")

    return audit


if __name__ == "__main__":
    main()
