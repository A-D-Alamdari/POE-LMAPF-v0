"""Acceptance tests for the event-debounced violation emission path.

P6 added three event-debounced counters
(``safety_violation_events``, ``violations_agent_attributable_events``,
``violations_exogenous_attributable_events``) and three explicit
``*_agent_ticks`` aliases for the legacy per-tick sums.  The CSV
writer must surface all six in ``results.csv`` so downstream
analysis can switch between "how much overlap time" and "how many
breach events" without re-running the experiment.

These tests pin:

  * the CSV header / row writer carry all six columns in lockstep;
  * a contiguous N-tick (agent, human) overlap registers as
    ``safety_violation_events = 1`` and ``safety_violations = N``;
  * the finalize-time invariants
    ``safety_violations == safety_violation_agent_ticks``,
    ``violations_agent_attributable == violations_agent_attributable_agent_ticks``,
    and ``safety_violations >= safety_violation_events`` fire when a
    future regression decouples the alias from its source or the
    debounce state machine double-counts.
"""
from __future__ import annotations

import csv
import io
from typing import Dict

import pytest

from ha_lmapf.core.metrics import MetricsTracker


# ---------------------------------------------------------------------------
# Column-presence test (the "CSV writer emits the six columns" gate)
# ---------------------------------------------------------------------------


REQUIRED_EVENT_COLUMNS = (
    "safety_violation_events",
    "violations_agent_attributable_events",
    "violations_exogenous_attributable_events",
    "safety_violation_agent_ticks",
    "violations_agent_attributable_agent_ticks",
    "violations_exogenous_attributable_agent_ticks",
)


def test_csv_header_carries_event_and_agent_ticks_columns():
    """The six columns from the P6 task spec must all appear in the
    header that ``MetricsTracker.csv_header()`` emits.  A future
    refactor that drops one of them silently re-introduces the
    "events counted internally but never written" regression that
    this fix addresses."""
    header = MetricsTracker.csv_header()
    missing = [c for c in REQUIRED_EVENT_COLUMNS if c not in header]
    assert not missing, (
        f"CSV header is missing the event-debounced columns: {missing}. "
        f"They are computed by MetricsTracker but never written to "
        f"results.csv -- the exact regression this test guards against."
    )


def test_csv_row_writer_emits_event_and_agent_ticks_columns():
    """Run finalize on an empty tracker, render the row, and verify
    the row's value for each of the six columns matches the value
    on the materialized Metrics object.  This catches an edit that
    adds the column to the header but forgets to wire the row
    writer (or vice versa)."""
    tracker = MetricsTracker()
    metrics = tracker.finalize(total_steps=1, num_agents=1)
    header = MetricsTracker.csv_header()
    row = tracker.to_csv_row(metrics)
    assert len(row) == len(header), (
        f"to_csv_row len={len(row)} != csv_header len={len(header)}; "
        f"header and writer are out of sync."
    )
    row_by_name: Dict[str, str] = dict(zip(header, row))
    for col in REQUIRED_EVENT_COLUMNS:
        assert col in row_by_name, f"{col} missing from row"
        # All six are integer counters that start at zero on a
        # fresh tracker; the row should literally be "0".
        assert row_by_name[col] == "0", (
            f"row[{col}] = {row_by_name[col]!r}; expected '0' for "
            f"a fresh tracker"
        )


# ---------------------------------------------------------------------------
# Behavioural test: N-tick loitering -> events=1, agent_ticks=N
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n_consecutive_ticks", [1, 2, 5, 10, 100])
def test_loitering_pair_yields_events_one_and_agent_ticks_n(n_consecutive_ticks: int):
    """A single (agent, human) pair that sits inside the safety
    buffer for ``N`` consecutive ticks must register as exactly one
    debounced event and ``N`` agent-tick increments.  This is the
    P6 task spec's acceptance criterion verbatim, parametrised over
    several N so the relationship ``events = 1`` is locked across
    a range of run lengths."""
    tracker = MetricsTracker()
    for _ in range(n_consecutive_ticks):
        # Mimic the simulator's per-pair recording: bump the
        # legacy counters in lockstep with the debounce state
        # machine, exactly as
        # ``simulator.py::_detect_collisions_and_near_misses``
        # does on every tick where the pair is in violation.
        tracker.add_safety_violation(1)
        tracker.add_exogenous_attributable_violation(1)
        tracker.record_violation_pair(0, 0, "exo")
        tracker.close_violation_tick()
    m = tracker.finalize(total_steps=n_consecutive_ticks, num_agents=1)

    assert m.safety_violations == n_consecutive_ticks, m
    assert m.safety_violation_agent_ticks == n_consecutive_ticks, m
    assert m.safety_violation_events == 1, (
        f"N={n_consecutive_ticks} ticks of overlap on one pair must "
        f"register as ONE debounced event; got "
        f"safety_violation_events={m.safety_violation_events}"
    )
    # The attribution bucket mirrors the recording bucket.
    assert m.violations_exogenous_attributable == n_consecutive_ticks
    assert m.violations_exogenous_attributable_agent_ticks == n_consecutive_ticks
    assert m.violations_exogenous_attributable_events == 1
    # Agent-bucket counters all stay zero -- the pair was recorded
    # under "exo".
    assert m.violations_agent_attributable == 0
    assert m.violations_agent_attributable_agent_ticks == 0
    assert m.violations_agent_attributable_events == 0


def test_pair_re_entry_after_quiet_tick_counts_as_new_event():
    """Companion to the loitering test: a pair that DROPS OUT for
    at least one tick and re-enters must register as a NEW
    leading-edge event.  Pins the debounce semantics."""
    tracker = MetricsTracker()
    # Run 1: 3 ticks of overlap.
    for _ in range(3):
        tracker.add_safety_violation(1)
        tracker.add_exogenous_attributable_violation(1)
        tracker.record_violation_pair(0, 0, "exo")
        tracker.close_violation_tick()
    # Quiet tick (pair dropped out).
    tracker.close_violation_tick()
    # Run 2: 2 more ticks of overlap on the same pair.
    for _ in range(2):
        tracker.add_safety_violation(1)
        tracker.add_exogenous_attributable_violation(1)
        tracker.record_violation_pair(0, 0, "exo")
        tracker.close_violation_tick()
    m = tracker.finalize(total_steps=6, num_agents=1)

    assert m.safety_violations == 5
    assert m.safety_violation_agent_ticks == 5
    assert m.safety_violation_events == 2, (
        f"two distinct overlap runs must register as two events; "
        f"got {m.safety_violation_events}"
    )


# ---------------------------------------------------------------------------
# Finalize-time invariant asserts
# ---------------------------------------------------------------------------


def test_finalize_asserts_agent_ticks_alias_equals_legacy(monkeypatch):
    """If a future edit decouples the ``*_agent_ticks`` alias from
    its legacy source (e.g. wires it to a stale internal counter),
    the finalize-time assert must fire before the row writer
    emits the skewed values."""
    tracker = MetricsTracker()
    tracker.add_safety_violation(3)
    tracker.add_exogenous_attributable_violation(3)
    # Patch ``Metrics`` construction to inject a deliberately wrong
    # ``safety_violation_agent_ticks``.  We do this by patching the
    # field assignment via the dataclass replace path.
    import ha_lmapf.core.metrics as metrics_mod
    real_metrics_ctor = metrics_mod.Metrics

    def fake_ctor(*args, **kwargs):
        # Drift the alias by 1 to trigger the assert.
        kwargs["safety_violation_agent_ticks"] = (
            int(kwargs.get("safety_violations", 0)) + 1
        )
        return real_metrics_ctor(*args, **kwargs)

    monkeypatch.setattr(metrics_mod, "Metrics", fake_ctor)
    with pytest.raises(AssertionError, match="safety_violation_agent_ticks alias drift"):
        tracker.finalize(total_steps=1, num_agents=1)


def test_finalize_asserts_events_le_agent_ticks(monkeypatch):
    """A double-counted leading edge would make
    ``safety_violation_events > safety_violations``; the assert
    must catch it before the CSV is written."""
    tracker = MetricsTracker()
    # Drive the events counter directly higher than the per-tick
    # sum via a monkeypatch on the Metrics ctor (the public
    # MetricsTracker API holds the invariant by construction).
    import ha_lmapf.core.metrics as metrics_mod
    real_metrics_ctor = metrics_mod.Metrics

    def fake_ctor(*args, **kwargs):
        # Force events strictly above agent_ticks.
        kwargs["safety_violation_events"] = (
            int(kwargs.get("safety_violations", 0)) + 1
        )
        return real_metrics_ctor(*args, **kwargs)

    monkeypatch.setattr(metrics_mod, "Metrics", fake_ctor)
    with pytest.raises(AssertionError, match="events > agent_ticks"):
        tracker.finalize(total_steps=1, num_agents=1)


# ---------------------------------------------------------------------------
# CSV round-trip on a populated tracker
# ---------------------------------------------------------------------------


def test_csv_round_trip_preserves_event_columns():
    """End-to-end: write a tracker's row to a CSV string, parse it
    back, and verify the six event/agent_ticks columns survive the
    round trip with the values the tracker computed."""
    tracker = MetricsTracker()
    for _ in range(7):
        tracker.add_safety_violation(1)
        tracker.add_agent_attributable_violation(1)
        tracker.record_violation_pair(1, 2, "agent")
        tracker.close_violation_tick()
    metrics = tracker.finalize(total_steps=7, num_agents=1)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(MetricsTracker.csv_header())
    w.writerow(tracker.to_csv_row(metrics))
    buf.seek(0)

    rows = list(csv.DictReader(buf))
    assert len(rows) == 1
    row = rows[0]
    assert int(row["safety_violations"]) == 7
    assert int(row["safety_violation_agent_ticks"]) == 7
    assert int(row["safety_violation_events"]) == 1
    assert int(row["violations_agent_attributable"]) == 7
    assert int(row["violations_agent_attributable_agent_ticks"]) == 7
    assert int(row["violations_agent_attributable_events"]) == 1
    assert int(row["violations_exogenous_attributable_agent_ticks"]) == 0
    assert int(row["violations_exogenous_attributable_events"]) == 0
