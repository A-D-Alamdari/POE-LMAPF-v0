"""Regression test for the auction allocator's ``epsilon`` knob.

``SimConfig.auction_epsilon`` was added so the §5.5 allocator
comparison sweep can encode the auction's bid-increment epsilon
explicitly in YAML.  Previously the simulator used the
``AuctionBasedTaskAllocator`` factory's default of 0.01 with no
config-side override, making the value invisible to YAML configs.

These tests pin:

  T-AE-1  Default (unspecified) ``SimConfig.auction_epsilon`` is
          0.01 — matches the pre-knob factory default and the
          paper-spec value.  Guards against future accidental
          changes to the default.

  T-AE-2  An explicit ``SimConfig(auction_epsilon=0.05)`` produces
          an auction allocator with ``epsilon == 0.05``.  Confirms
          the field is threaded simulator → factory cleanly.

  T-AE-3  An explicit ``SimConfig(auction_epsilon=0.0)`` produces
          an auction allocator with ``epsilon == 0.0``.  Edge-case:
          zero is a legitimate value (no minimum bid increment)
          and must not be silently substituted by the default.

  T-AE-4  Non-auction allocators (``greedy``, ``hungarian``,
          ``congestion_avoidance``) are unaffected by the new
          field — the kwarg is silently ignored by the factory.
          Pre-knob runs that specify these allocators must
          continue to behave identically.

The tests build a real ``Simulator`` on a tiny 5×5 map so they
exercise the full ``_make_allocator`` call site at
simulator.py:261-265, not just the factory in isolation.
"""
from __future__ import annotations

import pytest

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator
from ha_lmapf.task_allocator.task_allocator import (
    AuctionBasedTaskAllocator,
    CongestionAvoidanceTaskAllocator,
    GreedyNearestTaskAllocator,
    HungarianTaskAllocator,
)


@pytest.fixture
def small_map(tmp_path):
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def _sim(map_path: str, allocator: str, **extra) -> Simulator:
    cfg = SimConfig(
        map_path=map_path,
        seed=0, steps=2,
        num_agents=1, num_humans=0,
        fov_radius=4, safety_radius=1,
        global_solver="cbs",
        horizon=20, replan_every=10,
        solver_timeout_s=2.0, hard_safety=True,
        mode="lifelong",
        task_allocator=allocator,
        **extra,
    )
    return Simulator(cfg)


# ---------------------------------------------------------------------------
# T-AE-1 — default is 0.01
# ---------------------------------------------------------------------------


def test_T_AE_1_default_auction_epsilon_is_001():
    """An unspecified ``SimConfig.auction_epsilon`` is 0.01 and
    propagates to the auction allocator unchanged.  This pins the
    backward-compatibility contract: pre-knob YAML behavior is
    preserved."""
    cfg = SimConfig(map_path="data/maps/random-64-64-10.map")
    assert cfg.auction_epsilon == 0.01, (
        f"default auction_epsilon must be 0.01 (matches "
        f"AuctionBasedTaskAllocator factory default and paper §5.5 "
        f"spec); got {cfg.auction_epsilon!r}"
    )


# ---------------------------------------------------------------------------
# T-AE-2 — explicit non-default round-trips
# ---------------------------------------------------------------------------


def test_T_AE_2_explicit_epsilon_reaches_allocator(small_map):
    """SimConfig(auction_epsilon=0.05) → allocator.epsilon == 0.05."""
    sim = _sim(small_map, "auction", auction_epsilon=0.05)
    assert isinstance(sim.task_allocator, AuctionBasedTaskAllocator)
    assert sim.task_allocator.epsilon == 0.05, (
        f"explicit auction_epsilon=0.05 did not round-trip; "
        f"allocator received epsilon={sim.task_allocator.epsilon!r}"
    )


# ---------------------------------------------------------------------------
# T-AE-3 — zero is a legitimate value, not the default
# ---------------------------------------------------------------------------


def test_T_AE_3_zero_epsilon_preserved(small_map):
    """SimConfig(auction_epsilon=0.0) → allocator.epsilon == 0.0.
    Zero is a valid setting (no minimum bid increment); it must NOT
    be silently substituted by the 0.01 default."""
    sim = _sim(small_map, "auction", auction_epsilon=0.0)
    assert isinstance(sim.task_allocator, AuctionBasedTaskAllocator)
    assert sim.task_allocator.epsilon == 0.0, (
        f"auction_epsilon=0.0 must reach the allocator literally; "
        f"got {sim.task_allocator.epsilon!r} (default 0.01 leaking?)"
    )


# ---------------------------------------------------------------------------
# T-AE-4 — non-auction allocators are unaffected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("alloc,expected_cls", [
    ("greedy",                GreedyNearestTaskAllocator),
    ("hungarian",             HungarianTaskAllocator),
    ("congestion_avoidance",  CongestionAvoidanceTaskAllocator),
])
def test_T_AE_4_non_auction_unaffected_by_epsilon(small_map, alloc, expected_cls):
    """Setting ``auction_epsilon`` for a non-auction allocator must
    be a no-op — pre-knob behavior preserved.  The factory's
    ``kwargs.get`` pattern silently drops the unused kwarg."""
    sim = _sim(small_map, alloc, auction_epsilon=99.0)
    assert isinstance(sim.task_allocator, expected_cls), (
        f"expected {expected_cls.__name__} for allocator={alloc!r}, "
        f"got {type(sim.task_allocator).__name__}"
    )
