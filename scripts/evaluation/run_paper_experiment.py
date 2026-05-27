#!/usr/bin/env python3
"""
Paper-experiment harness (POE-LMAPF, paper Section 5).

Reads a sweep YAML under ``configs/eval/paper/``, expands the cartesian
product into a manifest of runs, and executes each run sequentially or
through ``multiprocessing.Pool``.  Per-run results are appended to
``<out>/results.csv`` with one row containing the run's ``run_id``,
every config field, every ``Metrics`` field, status (``ok`` /
``timeout`` / ``error``), wall-clock seconds, and any error message.

Key features:

* **Deterministic per seed** — ``run_id`` is the SHA-256 of the
  canonical-form config dict (config + seed), independent of YAML
  ordering.
* **Resumable** — ``--resume`` skips runs whose ``run_id`` already
  appears in the existing ``results.csv`` with status ``ok``.
* **Atomic CSV append** — main process writes; workers return rows
  via ``Pool.imap_unordered`` so partial failures cannot corrupt the
  file.
* **Sharded** — ``--seed-shard i/N`` keeps only seeds whose
  ``seed mod N == i`` for distributed execution across nodes.

YAML schema::

    name:        <str>
    description: <str>
    base:        <dict>            # fields shared by every run
    groups:                        # list of cartesian groups
      - sweep: { field: [values, ...], ... }
      - sweep: { ... }
    seeds: [int, ...]

The optional ``method`` field (used by ``baseline_comparison.yaml``)
is translated by this runner into the appropriate factory call:
``ours`` is the unmodified base; ``rhcr``, ``pibt2_fr``, ``no_buffer``
are routed through their corresponding ``make_*_config`` helpers.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import itertools
import json
import logging
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

# Ensure ``src/`` is on the path even when invoked as a bare script.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from ha_lmapf.baselines import (  # noqa: E402
    make_lacam_blind_config,
    make_no_buffer_config,
    make_pibt2_fr_config,
    make_rhcr_blind_config,
)
from ha_lmapf.core.types import Metrics, SimConfig  # noqa: E402
from ha_lmapf.simulation.simulator import Simulator  # noqa: E402

logger = logging.getLogger("paper_harness")


# ---------------------------------------------------------------------------
# Manifest expansion
# ---------------------------------------------------------------------------


def _canonical(obj: Any) -> Any:
    """Return ``obj`` with dicts sorted by key for stable hashing."""
    if isinstance(obj, dict):
        return {k: _canonical(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, (list, tuple)):
        return [_canonical(x) for x in obj]
    return obj


def compute_run_id(cfg: Dict[str, Any], seed: int) -> str:
    """Deterministic run id = SHA-256 of (canonical config dict, seed)."""
    payload = json.dumps(
        {"config": _canonical(cfg), "seed": int(seed)},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Paper-section ↔ steps consistency
# ---------------------------------------------------------------------------


# Maps the YAML stem to the ``steps`` value the paper specifies for that
# section.  Run-time validation fast-fails if a YAML drifts from the
# paper's choice — burning compute on a misconfigured 3360-run sweep is
# expensive.
PAPER_SECTION_TO_STEPS: Dict[str, int] = {
    "solver_sensitivity":      2000,   # §5.2
    "fov_safety":              2000,   # §5.3
    "scaling_agents":          2000,   # §5.4 part 1
    "scaling_humans":          2000,   # §5.4 part 2 (companion: num_humans sweep at fixed num_agents=200)
    "scaling_exogenous":       2000,   # §5.4 part 2
    "allocator_comparison":    2000,   # §5.5 task-allocator comparison (configs/tuning/) -- DEPRECATED, see *_fov*_safe*
    "allocator_comparison_fov3_safe1":  2000,   # §5.5 allocator comparison @ (fov=3, safe=1) (configs/tuning/)
    "allocator_comparison_fov4_safe2":  2000,   # §5.5 allocator comparison @ (fov=4, safe=2) (configs/tuning/)
    "scaling_agents_fov3_safe1":  2000,   # §5.4 agent-scaling @ (fov=3, safe=1) (configs/tuning/)
    "scaling_agents_fov4_safe2":  2000,   # §5.4 agent-scaling @ (fov=4, safe=2) (configs/tuning/)
    "scaling_humans_fov3_safe1":  2000,   # §5.4 exogenous-scaling @ (fov=3, safe=1) (configs/tuning/)
    "scaling_humans_fov4_safe2":  2000,   # §5.4 exogenous-scaling @ (fov=4, safe=2) (configs/tuning/)
    "baseline_comparison":     2000,   # §5.5 — re-aligned with §5.4 scaling sweeps
    "allocator_alternatives":  2000,   # §5.6
    "temporal_progression":    2000,   # §5.8
    "token_passing_ablation":  1500,   # §4.3 hanging promise — same length as §5.5
    "aux_h_r_decoupling":      2000,   # response-letter material
    "horizon_replan_full":     2000,   # pre-paper tuning sweep (configs/tuning/)
    "fov_safety_sweep":        2000,   # §5.3 fov × safety_radius sensitivity (configs/tuning/)
    "deadlock_wait":           2000,   # §5.6 deadlock + wait-time decomposition (configs/tuning/)
    "soft_safety_ablation":    2000,   # §3 hard-vs-soft safety ablation (configs/tuning/)
}


def validate_config_consistency(config_yaml_path: Path,
                                rows: List[Dict[str, Any]]) -> None:
    """Fast-fail check: every expanded run uses the paper-mandated
    ``steps`` for the YAML's section.

    Raises ``ValueError`` on the first mismatch with a message naming
    the offending YAML, run id, observed value, and expected value.
    """
    stem = config_yaml_path.stem
    expected = PAPER_SECTION_TO_STEPS.get(stem)
    if expected is None:
        # Unknown YAML — no enforced contract; warn so a typo is
        # visible.
        logger.warning(
            "validate_config_consistency: %s is not in PAPER_SECTION_TO_STEPS "
            "— no steps contract enforced.", stem,
        )
        return
    for row in rows:
        run_cfg = row["config"]
        # SimConfig field is ``steps``; the paper text and the user's
        # spec call it ``simulation_steps``.  Accept either.
        observed = run_cfg.get("steps", run_cfg.get("simulation_steps"))
        if observed != expected:
            raise ValueError(
                f"{stem}: run {row['run_id'][:12]} has steps={observed!r} "
                f"but paper specifies {expected} for this section."
            )
    logger.info("validate_config_consistency: %s steps == %d (all %d runs)",
                stem, expected, len(rows))


def expand_manifest(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Expand a YAML spec into the list of runs.

    Each row carries the merged base + sweep-cell config dict plus the
    seed, the run_id, and the experiment name.
    """
    base: Dict[str, Any] = dict(spec.get("base", {}) or {})
    seeds: List[int] = list(spec.get("seeds", [0]))
    name = str(spec.get("name", "experiment"))
    rows: List[Dict[str, Any]] = []
    for group in spec.get("groups", []):
        sweep = group.get("sweep", {}) or {}
        if not sweep:
            continue
        keys = list(sweep.keys())
        value_lists = [list(sweep[k]) for k in keys]
        for values in itertools.product(*value_lists):
            cfg_cell = dict(base)
            cfg_cell.update(dict(zip(keys, values)))
            for seed in seeds:
                run_cfg = dict(cfg_cell)
                run_cfg["seed"] = int(seed)
                run_id = compute_run_id(cfg_cell, int(seed))
                rows.append({
                    "run_id": run_id,
                    "experiment": name,
                    "seed": int(seed),
                    "config": run_cfg,
                })
    return rows


# ---------------------------------------------------------------------------
# Method dispatch
# ---------------------------------------------------------------------------


def _apply_method(base: SimConfig, method: str) -> SimConfig:
    """Translate ``method`` axis values to a configured ``SimConfig``.

    The base config is returned unchanged for ``"ours"`` (the paper's
    proposed method).  Baseline factories live in
    ``ha_lmapf.baselines.pibt2_fr``.

    ``method="rhcr"`` is preserved in the dispatch table so stale
    YAMLs fail loudly at config-build time with an actionable error
    rather than silently re-routing.  See ``docs/RHCR_DEFERRED.md``
    for the architectural analysis.  Use ``method="lacam_blind"``
    for the §5.5 rigid-follower baseline.
    """
    method = (method or "ours").lower()
    if method == "ours":
        return base
    if method == "rhcr":
        # Delegated raise — the factory carries the canonical error
        # message so there is a single source of truth.
        return make_rhcr_blind_config(base)
    if method == "lacam_blind":
        return make_lacam_blind_config(base)
    if method == "pibt2_fr":
        return make_pibt2_fr_config(base)
    if method == "no_buffer":
        return make_no_buffer_config(base)
    raise ValueError(f"unknown method {method!r}")


def _build_sim_config(run_cfg: Dict[str, Any]) -> SimConfig:
    """Construct a ``SimConfig`` from a flat sweep-cell dict."""
    cfg = dict(run_cfg)
    method = cfg.pop("method", None)
    # ``map_to_human_model`` is a dict; pass it through as-is.
    sim_cfg_fields = {f.name for f in dataclasses.fields(SimConfig)}
    kwargs = {k: v for k, v in cfg.items() if k in sim_cfg_fields}
    extra = {k: v for k, v in cfg.items() if k not in sim_cfg_fields}
    if extra:
        logger.warning("ignoring unknown SimConfig fields: %s", sorted(extra))
    base = SimConfig(**kwargs)
    return _apply_method(base, method) if method is not None else base


# ---------------------------------------------------------------------------
# Single-run execution
# ---------------------------------------------------------------------------


def _flatten_for_csv(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Render nested fields (e.g. ``map_to_human_model``) as JSON
    strings so the row fits in a CSV cell."""
    out: Dict[str, Any] = {}
    for k, v in cfg.items():
        if isinstance(v, (dict, list)):
            out[k] = json.dumps(v, sort_keys=True)
        else:
            out[k] = v
    return out


_TIMELINE_KEYS = (
    "throughput_timeline",
    "violations_agent_timeline",
    "violations_exogenous_timeline",
)

# Paper-relevant SimConfig fields whose post-dispatch values we surface
# under an ``applied_`` prefix in the CSV (paper §5 method-override
# auditing).  Pre-fix, the CSV showed only the raw YAML sweep cell —
# which is identical across all four §5.5 methods because
# ``_apply_method`` runs AFTER ``_flatten_for_csv`` — making it look
# as though every method shared one config.  These columns are the
# actual values that reached ``Simulator.__init__`` for the run.
_APPLIED_CSV_FIELDS = (
    "global_solver",
    "safety_radius",
    "replan_every",
    "horizon",
    "fov_radius",
    "hard_safety",
    "task_allocator",
)


def run_one(row: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one ``Simulator.run`` and return a flat result row.

    Per-tick timelines (``throughput_timeline``,
    ``violations_*_timeline``) are stripped from the CSV row (they'd
    inflate the file by ~10s of MB on full sweeps) and persisted to a
    sidecar JSON at ``<sidecar_dir>/<run_id>.json`` when non-empty.
    The sidecar directory is taken from ``row["_sidecar_dir"]`` if
    present, else no sidecar is written.
    """
    run_cfg = row["config"]
    record: Dict[str, Any] = {
        "run_id": row["run_id"],
        "experiment": row["experiment"],
        **_flatten_for_csv(run_cfg),
    }
    t0 = time.perf_counter()
    try:
        # Build the dispatched SimConfig and record its post-method-
        # dispatch values under ``applied_*`` columns.  Without these,
        # every method in a §5.5-style sweep appears to share one
        # config in the CSV because ``_flatten_for_csv`` above sees
        # only the raw YAML cell (pre-dispatch).  See the
        # ``_APPLIED_CSV_FIELDS`` docstring for the motivating bug.
        sim_cfg = _build_sim_config(run_cfg)
        record.update({
            f"applied_{k}": getattr(sim_cfg, k, None)
            for k in _APPLIED_CSV_FIELDS
        })
        sim = Simulator(sim_cfg)
        metrics: Metrics = sim.run()
        m = asdict(metrics)
        # Per-tick lists: strip from CSV row, capture non-empty ones
        # for sidecar JSON writeout.
        timeline_blob: Dict[str, List[Any]] = {}
        for key in _TIMELINE_KEYS:
            timeline = m.pop(key, None)
            if isinstance(timeline, list):
                m[f"{key}_len"] = len(timeline)
                if timeline:
                    timeline_blob[key] = timeline
        sidecar_dir_str = row.get("_sidecar_dir")
        if timeline_blob and sidecar_dir_str:
            sidecar = Path(sidecar_dir_str) / f"{row['run_id']}.json"
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            with sidecar.open("w") as f:
                json.dump(timeline_blob, f)
        record.update(m)
        record["status"] = "ok"
        record["error_msg"] = ""
    except Exception as exc:  # noqa: BLE001
        record["status"] = "error"
        record["error_msg"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "run %s failed: %s\n%s",
            row["run_id"][:12], exc, traceback.format_exc(),
        )
    record["wall_clock_s"] = round(time.perf_counter() - t0, 4)
    return record


# ---------------------------------------------------------------------------
# CSV I/O — atomic append
# ---------------------------------------------------------------------------


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (write tmp + rename)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_existing_run_ids(results_path: Path) -> set:
    if not results_path.exists():
        return set()
    out: set = set()
    with results_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("status") or "").lower() == "ok":
                rid = row.get("run_id")
                if rid:
                    out.add(rid)
    return out


def _append_rows(results_path: Path, rows: List[Dict[str, Any]]) -> None:
    """Append ``rows`` to ``results.csv``, replacing the file
    atomically.  Adds any new columns introduced by ``rows`` to the
    existing schema (CSV header is sorted lexicographically for
    stability)."""
    existing: List[Dict[str, Any]] = []
    if results_path.exists():
        with results_path.open("r", newline="") as f:
            existing = list(csv.DictReader(f))
    all_rows = existing + rows
    fieldnames = sorted({k for row in all_rows for k in row.keys()})
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for row in all_rows:
        w.writerow({k: row.get(k, "") for k in fieldnames})
    _atomic_write_text(results_path, buf.getvalue())


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _filter_by_shard(rows: List[Dict[str, Any]], shard: Optional[Tuple[int, int]]) -> List[Dict[str, Any]]:
    if shard is None:
        return rows
    i, n = shard
    if n <= 0 or i < 0 or i >= n:
        raise ValueError(f"invalid --seed-shard {i}/{n}")
    return [r for r in rows if (r["seed"] % n) == i]


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="POE-LMAPF paper experiment harness")
    p.add_argument("--config", required=True, type=Path,
                   help="Path to a sweep YAML under configs/eval/paper/")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory; results.csv and manifest.csv land here")
    p.add_argument("--workers", type=int, default=1,
                   help="Process-pool size (default 1 = sequential).")
    p.add_argument("--seed-shard", type=str, default=None,
                   metavar="i/N",
                   help="Distribute seeds across N shards; this process runs shard i.")
    p.add_argument("--resume", action="store_true",
                   help="Skip runs whose run_id already appears with status=ok.")
    p.add_argument("--limit", type=int, default=None,
                   help="Run at most this many configs (for smoke / debugging).")
    p.add_argument("--log-level", type=str, default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    args.out.mkdir(parents=True, exist_ok=True)

    spec = yaml.safe_load(args.config.read_text())
    rows = expand_manifest(spec)
    logger.info("manifest expanded: %d runs (config=%s)", len(rows), args.config.name)

    # Inject sidecar-JSON directory for per-tick timelines (paper §5.8).
    # Workers consult ``row["_sidecar_dir"]`` to write
    # ``<dir>/<run_id>.json`` when timelines are non-empty.
    sidecar_dir = args.out / "timelines"
    for row in rows:
        row["_sidecar_dir"] = str(sidecar_dir)

    # Fast-fail before any compute is spent: enforce paper-specified
    # ``steps`` per section.
    validate_config_consistency(args.config, rows)

    # Apply optional shard.
    shard: Optional[Tuple[int, int]] = None
    if args.seed_shard:
        i_str, n_str = args.seed_shard.split("/")
        shard = (int(i_str), int(n_str))
        rows = _filter_by_shard(rows, shard)
        logger.info("shard %s -> %d runs", args.seed_shard, len(rows))

    # Persist the manifest (full list, including completed runs — useful
    # for debugging and for downstream tooling that wants to verify
    # coverage).
    manifest_path = args.out / "manifest.csv"
    with manifest_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "experiment", "seed", "config_json"])
        for row in rows:
            w.writerow([row["run_id"], row["experiment"], row["seed"],
                        json.dumps(_canonical(row["config"]), sort_keys=True)])

    results_path = args.out / "results.csv"
    if args.resume:
        done = _read_existing_run_ids(results_path)
        rows = [r for r in rows if r["run_id"] not in done]
        logger.info("resume: %d runs remaining (%d already complete)",
                    len(rows), len(done))

    if args.limit is not None:
        rows = rows[: args.limit]
        logger.info("limit applied: running first %d runs only", len(rows))

    if not rows:
        logger.info("nothing to do")
        return 0

    # Execute.
    new_rows: List[Dict[str, Any]] = []
    flush_every = 25  # write to disk every N completed runs
    t_start = time.perf_counter()

    if args.workers and args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(run_one, row): row for row in rows}
            for fut in as_completed(futures):
                rec = fut.result()
                new_rows.append(rec)
                logger.info(
                    "[%d/%d] %s status=%s wall=%.2fs",
                    len(new_rows), len(rows),
                    rec["run_id"][:12], rec["status"], rec.get("wall_clock_s", -1),
                )
                if len(new_rows) % flush_every == 0:
                    _append_rows(results_path, new_rows)
                    new_rows.clear()
    else:
        for k, row in enumerate(rows, 1):
            rec = run_one(row)
            new_rows.append(rec)
            logger.info(
                "[%d/%d] %s status=%s wall=%.2fs",
                k, len(rows),
                rec["run_id"][:12], rec["status"], rec.get("wall_clock_s", -1),
            )
            if len(new_rows) % flush_every == 0:
                _append_rows(results_path, new_rows)
                new_rows.clear()

    if new_rows:
        _append_rows(results_path, new_rows)

    logger.info(
        "done: %d runs in %.1fs (results=%s)",
        len(rows), time.perf_counter() - t_start, results_path,
    )

    # Auto-invocation hook (paper appendix material).  When the YAML
    # ships ``reference_condition`` and ``statistical_groupby`` fields,
    # run the appendix-grade pairwise pipeline at the end of the
    # sweep.  See ``scripts/evaluation/statistical_analysis.py``.
    ref_cond = spec.get("reference_condition")
    if ref_cond is not None:
        try:
            from scripts.evaluation.statistical_analysis import run_analysis
        except Exception as exc:  # noqa: BLE001
            logger.warning("statistical_analysis import failed (%s); skipping", exc)
            return 0
        groupby_str = spec.get("statistical_groupby")
        if isinstance(groupby_str, str):
            groupby = [s.strip() for s in groupby_str.split(",") if s.strip()]
        elif isinstance(groupby_str, list):
            groupby = list(groupby_str)
        else:
            groupby = []
        metrics = spec.get(
            "statistical_metrics",
            ["throughput", "violations_exogenous_attributable", "wait_fraction"],
        )
        # The reference field is the first groupby entry that contains
        # the reference value among its observed levels.
        reference_field = spec.get("reference_field")
        if reference_field is None:
            # Look in each row for the field; pick the first one whose
            # set of values includes ``ref_cond``.  Fall back to the
            # first groupby entry.
            try:
                rows_for_scan = []
                with results_path.open("r", newline="") as f:
                    rows_for_scan = list(csv.DictReader(f))
                for f in groupby:
                    if any(r.get(f) == str(ref_cond) for r in rows_for_scan):
                        reference_field = f
                        break
            except Exception:
                pass
            if reference_field is None and groupby:
                reference_field = groupby[0]
        try:
            run_analysis(
                results_path=results_path,
                out_dir=args.out / "stats",
                groupby=groupby,
                against_field=str(reference_field),
                against_value=ref_cond,
                metrics=metrics,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-stats failed (%s); inspect manually", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
