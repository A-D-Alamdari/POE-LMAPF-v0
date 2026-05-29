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
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

# Ensure ``src/`` is on the path even when invoked as a bare script.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))
# Also ensure the repo root is importable so the sibling
# ``scripts.evaluation.validate_paper_claims`` import resolves regardless
# of how this script was invoked (CLI, pytest, etc.).
sys.path.insert(0, str(_REPO_ROOT))

from ha_lmapf.baselines import (  # noqa: E402
    make_lacam_blind_config,
    make_no_buffer_config,
    make_pibt2_fr_config,
    make_rhcr_blind_config,
)

# Phase 2 prompt 5: the runner's per-row validity gate consults the SAME
# predicate the standalone validator uses, so a sweep that passes the
# runner's gate also passes ``validate_paper_claims --manifest`` and vice
# versa.  The probe (audit 14) exposed a divergence between the runner's
# legacy solver-fail-only check and the validator's five-clause strong
# predicate; this import is the alignment.
from scripts.evaluation.validate_paper_claims import (  # noqa: E402
    is_row_invalid,
    INVALID_REASONS,
)
from ha_lmapf.core.types import Metrics, SimConfig  # noqa: E402
from ha_lmapf.simulation.simulator import Simulator  # noqa: E402

# Sibling import: scripts/preflight_solvers.py.  ``scripts/`` has no
# ``__init__.py`` so add it to sys.path directly.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from preflight_solvers import abort_if_any_failed  # noqa: E402

logger = logging.getLogger("paper_harness")


# ---------------------------------------------------------------------------
# Run-validity gating (paper §5 audit trail)
# ---------------------------------------------------------------------------
#
# Background.  When a Tier-1 solver degenerates (binary missing,
# persistent timeouts, persistent errors) the wrapper still returns a
# "result" -- typically an all-WAIT plan -- and the simulator dutifully
# steps through 2000 ticks producing rows that *look* successful.  The
# checked-in CSV
# ``results/paper/scaling/scaling_agents_fov3_safe1_random-64-64-10.csv``
# shows three solvers with ``solver_errors_mean = 100.0`` (every one of
# 100 global replans failed) at 250 agents, yet the runs were written
# to disk as if valid.  The instrumentation below makes that condition
# loud: every per-run row carries ``solver_fail_fraction`` and the
# boolean ``run_valid``; degenerate rows are siphoned to a sibling
# ``*_INVALID.csv``; and a per-(solver,map) summary aborts the sweep
# when any cell exceeds ``INVALID_CELL_FRACTION_LIMIT``.
DEFAULT_VALIDITY_THRESHOLD = 0.05
DEFAULT_INVALID_CELL_FRACTION_LIMIT = 0.20


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
    # Canonical-placement check (audit step 07).  The YAML schema places
    # ``max_invalid_fraction`` at the SPEC TOP LEVEL -- it is a
    # sweep-level threshold consumed by ``main`` after the full sweep
    # completes, not a per-run SimConfig field.  Prior to audit step 07
    # the placement was inconsistent (every committed tuning YAML
    # nested it under ``base:``, where the top-level reader missed it
    # and ``_build_sim_config`` warned "ignoring unknown SimConfig
    # fields: ['max_invalid_fraction']").  The check below makes a
    # wrong placement fail loudly so the silent-no-op cannot recur.
    base_cfg = spec.get("base", {}) or {}
    if isinstance(base_cfg, dict) and "max_invalid_fraction" in base_cfg:
        raise ValueError(
            "spec key ``max_invalid_fraction`` is misplaced under "
            "``base:`` -- it is a sweep-level threshold and must "
            "appear at the SPEC TOP LEVEL.  Dedent the line so it "
            "is a peer of ``base:`` / ``seeds:`` / ``groups:`` "
            "(see audit step 07 / reports/audit/07_max_invalid_fraction.md). "
            "Inside ``base:`` it is silently dropped because "
            "``_build_sim_config`` filters inner keys to SimConfig "
            "fields only."
        )
    for group in spec.get("groups", []) or []:
        sweep = (group or {}).get("sweep", {}) or {}
        if isinstance(sweep, dict) and "max_invalid_fraction" in sweep:
            raise ValueError(
                "spec key ``max_invalid_fraction`` is misplaced inside "
                "a ``groups[*].sweep`` cell -- it is a sweep-level "
                "threshold, not a per-run swept value.  Move it to "
                "the SPEC TOP LEVEL (peer of ``base:``)."
            )

    base: Dict[str, Any] = dict(base_cfg)
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

    # Per-run validity gate.  Phase 2 prompt 5 aligned this stamping
    # path with the standalone validator's strong predicate; pre-prompt-5
    # the runner stamped ``run_valid`` from solver-fail-fraction +
    # status alone, which was the source of the audit-14 runner-vs-
    # validator divergence (the validator's predicate also fires on
    # no-global-replan / deadlock-fraction / saturation / missing
    # columns).  ``run_valid`` is now the strong-predicate verdict and
    # ``validity_reason`` carries the canonical reason name for the
    # first failing clause (one of :data:`INVALID_REASONS`, or "" on
    # passing rows).  ``solver_fail_fraction`` is preserved as a
    # diagnostic CSV column.
    threshold = float(row.get("_validity_threshold", DEFAULT_VALIDITY_THRESHOLD))
    try:
        global_replans = int(record.get("global_replans") or 0)
    except (TypeError, ValueError):
        global_replans = 0
    try:
        solver_errors = int(record.get("solver_errors") or 0)
    except (TypeError, ValueError):
        solver_errors = 0
    try:
        solver_timeouts = int(record.get("solver_timeouts") or 0)
    except (TypeError, ValueError):
        solver_timeouts = 0
    fail_fraction = float(solver_errors + solver_timeouts) / float(max(1, global_replans))
    record["solver_fail_fraction"] = round(fail_fraction, 6)
    record["validity_threshold"] = threshold
    # Strong-predicate verdict (delegates to the validator's canonical
    # predicate, single source of truth).
    invalid, reason = is_row_invalid(record)
    run_valid = not invalid
    record["run_valid"] = bool(run_valid)
    record["validity_reason"] = reason  # canonical reason; "" iff valid
    # Mirror the canonical solver_fallback_reuses field under the
    # spec's preferred audit-trail name without dropping the original.
    if "solver_fallback_reuses" in record and "fallback_reuse_count" not in record:
        record["fallback_reuse_count"] = record["solver_fallback_reuses"]

    if not run_valid:
        # Surface the offending cell so the failure is visible in any
        # log stream.  Read identifying fields from ``record`` rather
        # than ``run_cfg`` so post-dispatch ``applied_*`` overrides
        # show through.
        solver = (
            record.get("applied_global_solver")
            or record.get("global_solver")
            or "<unknown>"
        )
        map_path = record.get("map_path", "<unknown>")
        num_agents = record.get("num_agents", "<unknown>")
        seed = record.get("seed", record.get("config", {}).get("seed") if isinstance(record.get("config"), dict) else "<unknown>")
        logger.error(
            "INVALID run: solver=%s map=%s num_agents=%s seed=%s "
            "reason=%s solver_fail_fraction=%.4f (threshold=%.2f) "
            "global_replans=%d solver_errors=%d solver_timeouts=%d status=%s",
            solver, map_path, num_agents, seed,
            reason, fail_fraction, threshold,
            global_replans, solver_errors, solver_timeouts,
            record.get("status"),
        )
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


def _row_is_valid(row: Dict[str, Any]) -> bool:
    """True iff the row passes the strong validity predicate.

    Phase 2 prompt 5 alignment.  Delegates to
    :func:`scripts.evaluation.validate_paper_claims.is_row_invalid` --
    the SAME canonical predicate the standalone validator's manifest
    mode uses -- so runner and validator can never disagree about which
    rows are invalid.  The runner's per-row stamping path
    (:func:`_classify_run_validity`) writes ``run_valid`` to each
    record using the same delegate; this function works on either a
    freshly-classified record or a row read back from CSV
    (``is_row_invalid`` reads the raw columns; the stamped column is
    ignored).

    Pre-prompt-5 behavior: read the stamped boolean ``run_valid``
    column and treat missing as valid.  That was the source of the
    audit-14 runner-vs-validator divergence (the runner stamped the
    column from solver-fail alone; the standalone validator's
    predicate also checks no-global-replan / deadlock-fraction /
    saturation / required-columns).  The new body bypasses the stamped
    column entirely and re-evaluates the strong predicate.
    """
    invalid, _reason = is_row_invalid(row)
    return not invalid


def _split_valid_invalid(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partition rows into (valid, invalid) by the ``run_valid`` flag."""
    valid: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    for r in rows:
        (valid if _row_is_valid(r) else invalid).append(r)
    return valid, invalid


def _append_rows_split(
    results_path: Path,
    invalid_path: Path,
    rows: List[Dict[str, Any]],
) -> None:
    """Sort ``rows`` by ``run_valid`` and append each half to the
    appropriate CSV via :func:`_append_rows`.  Valid rows land in the
    main ``results.csv`` so downstream aggregation skips the
    instrumentation column entirely; invalid rows land in
    ``results_INVALID.csv`` for debugging and are NOT deleted."""
    valid, invalid = _split_valid_invalid(rows)
    if valid:
        _append_rows(results_path, valid)
    if invalid:
        _append_rows(invalid_path, invalid)


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


def _read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    """Read all rows from a CSV file, returning [] if it does not exist."""
    if not path.exists():
        return []
    with path.open("r", newline="") as f:
        return list(csv.DictReader(f))


def _summary_key(row: Dict[str, Any]) -> Tuple[str, str]:
    """Return the (solver, map) bucket for the run-validity summary.
    Prefer post-dispatch ``applied_global_solver`` so method-override
    sweeps (e.g. ``method=lacam_blind``) report against the solver
    that actually ran rather than the YAML's raw cell."""
    solver = (
        row.get("applied_global_solver")
        or row.get("global_solver")
        or "<unknown>"
    )
    map_path = row.get("map_path") or "<unknown>"
    return (str(solver), str(map_path))


def write_run_validity_summary(
    results_path: Path,
    invalid_path: Path,
    summary_path: Path,
    cell_fraction_limit: float,
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], Counter]:
    """Aggregate (solver, map) run counts across both result CSVs and
    write ``run_validity_summary.csv``.  Returns
    ``(summary_rows, failing_cells, sweep_invalid_reasons)`` where:

    * ``summary_rows`` is the per-cell summary table.
    * ``failing_cells`` lists cells with invalid fraction strictly
      greater than ``cell_fraction_limit``.
    * ``sweep_invalid_reasons`` is a Counter mapping the canonical
      reason name (one of :data:`INVALID_REASONS`) to the number of
      sweep-wide invalid rows attributed to it.  Phase 2 prompt 5
      addition; the runner's post-sweep log surfaces it so an operator
      can see at a glance whether the failure was budget-related,
      deadlock-related, schema-related, etc.

    Always writes the summary file (with a header row only) so the
    artifact exists even for empty sweeps -- downstream tooling can
    rely on its presence."""
    all_rows = _read_csv_rows(results_path) + _read_csv_rows(invalid_path)
    # Aggregate by (solver, map).
    buckets: Dict[Tuple[str, str], Dict[str, int]] = {}
    sweep_invalid_reasons: Counter = Counter()
    for r in all_rows:
        key = _summary_key(r)
        b = buckets.setdefault(
            key, {"valid": 0, "invalid": 0, "errored": 0, "total": 0},
        )
        b["total"] += 1
        invalid, reason = is_row_invalid(r)
        if invalid:
            b["invalid"] += 1
            sweep_invalid_reasons[reason] += 1
        else:
            b["valid"] += 1
        if str(r.get("status", "")).lower() not in ("ok", ""):
            b["errored"] += 1

    summary_rows: List[Dict[str, Any]] = []
    failing_cells: List[Tuple[str, str]] = []
    for (solver, map_path), b in sorted(buckets.items()):
        total = b["total"]
        invalid_fraction = (b["invalid"] / total) if total > 0 else 0.0
        row = {
            "global_solver":    solver,
            "map_path":         map_path,
            "total_runs":       total,
            "valid_runs":       b["valid"],
            "invalid_runs":     b["invalid"],
            "errored_runs":     b["errored"],
            "invalid_fraction": round(invalid_fraction, 6),
            "cell_fraction_limit": cell_fraction_limit,
            "cell_exceeds_limit":  invalid_fraction > cell_fraction_limit,
        }
        summary_rows.append(row)
        if invalid_fraction > cell_fraction_limit:
            failing_cells.append((solver, map_path))

    fieldnames = [
        "global_solver", "map_path", "total_runs",
        "valid_runs", "invalid_runs", "errored_runs",
        "invalid_fraction", "cell_fraction_limit", "cell_exceeds_limit",
    ]
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in summary_rows:
        w.writerow({k: r.get(k, "") for k in fieldnames})
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(summary_path, buf.getvalue())
    return summary_rows, failing_cells, sweep_invalid_reasons


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
    p.add_argument("--validity-threshold", type=float,
                   default=DEFAULT_VALIDITY_THRESHOLD,
                   help=("Per-run solver_fail_fraction above which the run is "
                         "marked invalid and siphoned to results_INVALID.csv. "
                         f"Default: {DEFAULT_VALIDITY_THRESHOLD}."))
    p.add_argument("--invalid-cell-fraction-limit", type=float,
                   default=DEFAULT_INVALID_CELL_FRACTION_LIMIT,
                   help=("Exit non-zero if any (solver, map) cell has a "
                         "strictly greater invalid-run fraction than this. "
                         f"Default: {DEFAULT_INVALID_CELL_FRACTION_LIMIT}."))
    p.add_argument("--dry-run", action="store_true",
                   help=("Expand the manifest, run solver preflight + "
                         "config-consistency checks + the validity-guard "
                         "wiring (read ``max_invalid_fraction`` /"
                         " ``validity_threshold`` from the spec, log them), "
                         "then exit 0 without running any sims.  Used by "
                         "tests/test_sweep_config_dryrun.py to keep the "
                         "scaling/baseline configs honest."))
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

    # Validity threshold: an explicit CLI flag wins; otherwise the
    # spec's ``validity_threshold`` key takes effect; otherwise the
    # module default.  A spec key is useful for pinning the threshold
    # alongside the rest of the sweep so reruns share the contract.
    if args.validity_threshold != DEFAULT_VALIDITY_THRESHOLD:
        validity_threshold = float(args.validity_threshold)
    elif "validity_threshold" in spec:
        validity_threshold = float(spec["validity_threshold"])
    else:
        validity_threshold = float(args.validity_threshold)
    invalid_cell_limit = float(args.invalid_cell_fraction_limit)
    # P7 follow-up: the YAML may also declare a sweep-level
    # ``max_invalid_fraction`` (the post-sweep invalid-row fraction
    # ceiling).  We only read + log it here; downstream tooling
    # (the validator) is what enforces it on the produced CSV.
    # Logging it makes the contract visible at run launch so a
    # mismatch between YAML and CLI flags is obvious in the log.
    spec_max_invalid_fraction: Optional[float] = None
    if "max_invalid_fraction" in spec:
        try:
            spec_max_invalid_fraction = float(spec["max_invalid_fraction"])
        except (TypeError, ValueError):
            logger.warning(
                "spec key ``max_invalid_fraction`` is not numeric: %r",
                spec.get("max_invalid_fraction"),
            )
    logger.info(
        "run-validity gate: solver_fail_fraction <= %.4f per run; "
        "(solver, map) cell limit %.2f%% invalid; "
        "sweep-level max_invalid_fraction=%s",
        validity_threshold, invalid_cell_limit * 100.0,
        "<unset>" if spec_max_invalid_fraction is None
        else f"{spec_max_invalid_fraction:.4f}",
    )

    # Inject sidecar-JSON directory for per-tick timelines (paper §5.8).
    # Workers consult ``row["_sidecar_dir"]`` to write
    # ``<dir>/<run_id>.json`` when timelines are non-empty.
    sidecar_dir = args.out / "timelines"
    for row in rows:
        row["_sidecar_dir"] = str(sidecar_dir)
        row["_validity_threshold"] = validity_threshold

    # Fast-fail before any compute is spent: enforce paper-specified
    # ``steps`` per section.
    validate_config_consistency(args.config, rows)

    # Fast-fail before any compute is spent: every solver the sweep
    # will invoke must actually load.  Resolving the post-method
    # dispatch ``global_solver`` per row matches what ``run_one``
    # ultimately calls -- a method axis can swap solvers
    # (e.g. ``method=pibt2_fr`` forces ``global_solver=pibt2``).
    sweep_solvers: List[str] = []
    seen_solvers: set = set()
    for row in rows:
        try:
            sim_cfg = _build_sim_config(row["config"])
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"config build failed for run {row['run_id'][:12]}: "
                f"{type(exc).__name__}: {exc}"
            )
        s = getattr(sim_cfg, "global_solver", None)
        if s and s not in seen_solvers:
            seen_solvers.add(s)
            sweep_solvers.append(s)
    if sweep_solvers:
        abort_if_any_failed(sweep_solvers, prefix="paper_harness")

    if args.dry_run:
        # Reached after manifest expansion + config consistency +
        # preflight + validity-guard wiring -- the exact "plumbing"
        # gate the P7 acceptance criterion asks for.  Exit 0 without
        # executing any sims.
        logger.info(
            "dry-run: %d runs would execute; preflight + "
            "consistency + validity guard wiring OK; exiting.",
            len(rows),
        )
        return 0

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
    invalid_path = args.out / "results_INVALID.csv"
    summary_path = args.out / "run_validity_summary.csv"
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
        # Still publish a summary so downstream tooling sees the
        # current state of disk.
        _, failing_cells = write_run_validity_summary(
            results_path, invalid_path, summary_path, invalid_cell_limit,
        )
        if failing_cells:
            logger.error(
                "run-validity gate FAILED on resume/no-op for %d (solver, map) "
                "cell(s): %s",
                len(failing_cells),
                ", ".join(f"{s}@{m}" for s, m in failing_cells),
            )
            return 3
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
                    _append_rows_split(results_path, invalid_path, new_rows)
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
                _append_rows_split(results_path, invalid_path, new_rows)
                new_rows.clear()

    if new_rows:
        _append_rows_split(results_path, invalid_path, new_rows)

    logger.info(
        "done: %d runs in %.1fs (results=%s)",
        len(rows), time.perf_counter() - t_start, results_path,
    )

    # Post-sweep run-validity summary.  Aggregates over both the main
    # CSV and the invalid CSV so the totals reflect every run on disk
    # (including those carried in from earlier sharded / resumed
    # invocations).  Exits non-zero -- without skipping the auto-stats
    # block below -- if any (solver, map) cell exceeds the limit; the
    # caller can then decide whether to retry or accept the partial
    # sweep.
    summary_rows, failing_cells, sweep_invalid_reasons = write_run_validity_summary(
        results_path, invalid_path, summary_path, invalid_cell_limit,
    )
    total_runs = sum(int(r["total_runs"]) for r in summary_rows)
    total_invalid = sum(int(r["invalid_runs"]) for r in summary_rows)
    logger.info(
        "run-validity summary written: %s (%d cells, %d/%d runs invalid)",
        summary_path, len(summary_rows), total_invalid, total_runs,
    )
    # Phase 2 prompt 5: surface the canonical reason breakdown so an
    # operator can tell budget-pressure failures from deadlock failures
    # without diffing the CSV.  Empty Counter on a clean sweep -> no
    # tail line.
    if sweep_invalid_reasons:
        reason_tail = " ".join(
            f"{name}={sweep_invalid_reasons[name]}"
            for name in INVALID_REASONS
            if sweep_invalid_reasons[name] > 0
        )
        logger.info("  reasons: %s", reason_tail)
    for r in summary_rows:
        if int(r["invalid_runs"]) > 0:
            marker = "EXCEEDS LIMIT" if r["cell_exceeds_limit"] else "ok"
            logger.warning(
                "  cell solver=%s map=%s -- %d/%d invalid (%.2f%%) [%s]",
                r["global_solver"], r["map_path"],
                r["invalid_runs"], r["total_runs"],
                100.0 * float(r["invalid_fraction"]), marker,
            )
    if failing_cells:
        logger.error(
            "run-validity gate FAILED: %d (solver, map) cell(s) "
            "exceed %.2f%% invalid runs: %s",
            len(failing_cells), invalid_cell_limit * 100.0,
            ", ".join(f"{s}@{m}" for s, m in failing_cells),
        )
        # Continue to write auto-stats artifacts (if configured)
        # before returning -- the operator may still want them for
        # the partial valid subset -- but flag the failure with a
        # non-zero exit at the end.

    # Sweep-level threshold (audit step 07).  ``spec_max_invalid_fraction``
    # is the YAML's per-sweep ceiling on the OVERALL invalid-row
    # fraction (one number across all (solver, map) cells together,
    # distinct from ``invalid_cell_limit`` which gates each cell
    # individually).  Prior to audit 07 this value was read into
    # ``spec_max_invalid_fraction`` but NEVER consumed; the check below
    # closes that loop.  Both gates can fire independently — the final
    # exit code reflects either failure.
    sweep_threshold_breached = False
    if spec_max_invalid_fraction is not None and total_runs > 0:
        sweep_invalid_fraction = total_invalid / total_runs
        # Format the reason tail once (Phase 2 prompt 5): "" if no
        # invalid runs, otherwise space-separated "reason=count" pairs
        # in the upstream-ness order :data:`INVALID_REASONS` declares.
        reason_tail = " ".join(
            f"{name}={sweep_invalid_reasons[name]}"
            for name in INVALID_REASONS
            if sweep_invalid_reasons[name] > 0
        )
        reason_suffix = f"  reasons: {reason_tail}" if reason_tail else ""
        if sweep_invalid_fraction > spec_max_invalid_fraction:
            sweep_threshold_breached = True
            logger.error(
                "sweep-level validity gate FAILED: "
                "%d/%d invalid runs = %.4f > max_invalid_fraction=%.4f "
                "(from spec top-level).  See audit step 07 / "
                "reports/audit/07_max_invalid_fraction.md.%s",
                total_invalid, total_runs,
                sweep_invalid_fraction, spec_max_invalid_fraction,
                reason_suffix,
            )
        else:
            logger.info(
                "sweep-level validity gate PASSED: "
                "%d/%d invalid runs = %.4f <= max_invalid_fraction=%.4f%s",
                total_invalid, total_runs,
                sweep_invalid_fraction, spec_max_invalid_fraction,
                reason_suffix,
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
            return 3 if (failing_cells or sweep_threshold_breached) else 0
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

    # Final exit code reflects the run-validity gate.  Exit code 3 is
    # reserved for "sweep completed but failed the validity contract"
    # so it is distinguishable from preflight failure (2) and from
    # generic SystemExit / unhandled exceptions (1).  Both the
    # per-(solver, map) cell gate AND the sweep-level
    # ``max_invalid_fraction`` gate (audit step 07) feed into the
    # same exit code.
    if failing_cells or sweep_threshold_breached:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
