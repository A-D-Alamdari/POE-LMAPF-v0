"""Tests for tune_horizon.py incremental flush + --resume semantics.

The interesting invariants here are:

1. ``_row_key`` produces the same 5-tuple whether the input is the
   in-memory ``meta`` dict (built by ``_build_tasks``) or a row read
   back from ``results.csv`` via ``csv.DictReader`` (strings).
   A divergence would either re-run completed cells or skip incomplete
   ones — both silent failures.

2. ``_completed_keys`` builds a skip-set from an existing
   ``results.csv``, tolerating malformed rows.

3. ``_open_results_writer`` opens the file in append mode and writes a
   header only when the file is new/empty.

4. ``_write_heartbeat`` is atomic: a reader that races the writer
   never sees a half-written file.

5. End-to-end: filtering the task list against the skip-set produces
   exactly the rows missing from a partially-completed CSV.

The tests intentionally do not launch real workers — those are
multi-second simulator runs that belong in a slower test tier.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from scripts.tuning.tune_horizon import (
    _build_tasks, _completed_keys, _open_results_writer,
    _read_completed_rows, _row_key, _write_heartbeat,
)


def test_row_key_matches_meta_and_csv_string_row(tmp_path):
    """A row built from meta+metrics and the same row read back from
    CSV must produce identical keys.  This is the contract the
    skip-set logic depends on.
    """
    meta = {
        "param": "horizon", "value": 20, "seed": 0,
        "solver": "lacam", "map_tag": "random",
        "map_path": "data/maps/random-64-64-10.map",
        "num_agents": 25, "num_humans": 50, "replan_every": 10,
    }
    key_inmem = _row_key(meta)

    # Round-trip via csv.DictReader (all values become strings)
    csv_path = tmp_path / "rt.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(meta.keys()))
        w.writeheader()
        w.writerow(meta)
    rows = list(csv.DictReader(csv_path.open()))
    key_disk = _row_key(rows[0])

    assert key_inmem == key_disk
    assert key_inmem == ("lacam", "random", 25, 20, 0)


def test_row_key_falls_back_to_horizon_field():
    """Older CSVs / sibling scripts may use ``horizon`` instead of
    ``value`` as the param column.  ``_row_key`` accepts either.
    """
    d = {"solver": "lacam3", "map_tag": "warehouse_small",
         "num_agents": 50, "horizon": 75, "seed": 3}
    assert _row_key(d) == ("lacam3", "warehouse_small", 50, 75, 3)


def test_completed_keys_tolerates_malformed_rows(tmp_path):
    """A partial flush from a crash may leave a row missing fields.
    The skip-set should silently drop it (so the task is re-run)
    rather than crashing the resume.
    """
    csv_path = tmp_path / "results.csv"
    with csv_path.open("w", newline="") as f:
        f.write("param,value,seed,solver,map_tag,num_agents,num_humans\n")
        f.write("horizon,20,0,lacam,random,25,50\n")
        # Malformed: no seed
        f.write("horizon,20,,lacam,random,25,50\n")
        # Valid
        f.write("horizon,50,1,lacam3,warehouse_small,75,50\n")

    rows = _read_completed_rows(csv_path)
    assert len(rows) == 3
    keys = _completed_keys(rows)
    # Two valid rows kept, one malformed dropped
    assert ("lacam", "random", 25, 20, 0) in keys
    assert ("lacam3", "warehouse_small", 75, 50, 1) in keys
    assert len(keys) == 2


def test_read_completed_rows_empty_file(tmp_path):
    """Empty/missing CSV must return [] — not raise."""
    p = tmp_path / "missing.csv"
    assert _read_completed_rows(p) == []
    p.write_text("")
    assert _read_completed_rows(p) == []


def test_open_results_writer_header_only_when_new(tmp_path):
    """Writer must NOT prepend a header on append-to-existing-file."""
    p = tmp_path / "results.csv"
    sample = {"solver": "lacam", "map_tag": "random",
              "num_agents": 25, "value": 20, "seed": 0,
              "throughput": 0.5}

    fh, w, fields = _open_results_writer(p, sample)
    w.writerow(sample)
    fh.close()

    # Second open: must reuse existing header / fieldnames
    fh2, w2, fields2 = _open_results_writer(p, sample)
    w2.writerow(sample)
    fh2.close()

    assert fields2 == fields  # header preserved
    contents = p.read_text().splitlines()
    # Exactly one header line + two data rows
    assert len(contents) == 3
    assert contents[0] == ",".join(fields)


def test_write_heartbeat_atomic_via_replace(tmp_path):
    """Heartbeat writes go through a .tmp + replace so a reader never
    sees a partial line.  Sanity-check: file exists after each write
    and contains the expected progress string.
    """
    hb = tmp_path / ".heartbeat"
    _write_heartbeat(hb, 0, 100)
    line1 = hb.read_text()
    assert "0/100" in line1 and "0.0%" in line1

    _write_heartbeat(hb, 25, 100, "lacam__random_a25_h20_s0")
    line2 = hb.read_text()
    assert "25/100" in line2 and "25.0%" in line2
    assert "lacam__random_a25_h20_s0" in line2

    # The tmp sidecar must be cleaned up by replace()
    assert not (tmp_path / ".heartbeat.tmp").exists()


def test_build_tasks_key_matches_csv_row_key(tmp_path):
    """End-to-end: a task's meta and a CSV row produced from completing
    that task share the same ``_row_key``.  This is the contract that
    makes skip-filtering work for ``--resume``.
    """
    tasks = _build_tasks(
        solvers={"lacam": "lacam"},
        map_tags=["random"],
        horizon_values=[20],
        seeds=[0, 1],
        steps=100,
    )
    # 1 solver × 1 map × 4 default agent counts × 1 horizon × 2 seeds
    assert len(tasks) == 8

    # Simulate writing those tasks' meta as completed rows
    csv_path = tmp_path / "results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(tasks[0][2].keys()))
        w.writeheader()
        for _, _, meta in tasks:
            w.writerow(meta)

    # Read back and confirm every task's meta-key is in the skip-set
    skip = _completed_keys(_read_completed_rows(csv_path))
    for _, _, meta in tasks:
        assert _row_key(meta) in skip
    assert len(skip) == 8


def test_resume_filter_keeps_only_missing_tasks(tmp_path):
    """If half the tasks' keys are in the skip-set, filtering must
    leave exactly the other half.
    """
    tasks = _build_tasks(
        solvers={"lacam": "lacam"},
        map_tags=["random"],
        horizon_values=[20, 50],
        seeds=[0, 1],
        steps=100,
    )
    # 1 × 1 × 4 × 2 × 2 = 16 tasks
    assert len(tasks) == 16

    # Mark every horizon=20 task complete
    completed_rows = []
    for cfg, name, meta in tasks:
        if meta["value"] == 20:
            completed_rows.append(meta)

    csv_path = tmp_path / "results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(completed_rows[0].keys()))
        w.writeheader()
        for r in completed_rows:
            w.writerow(r)

    skip = _completed_keys(_read_completed_rows(csv_path))
    remaining = [t for t in tasks if _row_key(t[2]) not in skip]

    # Exactly the horizon=50 tasks remain
    assert len(remaining) == 8
    for _, _, meta in remaining:
        assert meta["value"] == 50
