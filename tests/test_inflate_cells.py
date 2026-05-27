"""
Regression tests for ``inflate_cells`` correctness.

The paper's r_safe sweep in Section 5.3 covers r_safe ∈ {0, 1, 2, 3} and
the "No-Buffer" ablation in Section 5.5 sets r_safe = 0.  An off-by-one
in ``inflate_cells`` would silently broaden the buffer at radius 0 (e.g.
a cross-of-five instead of a singleton) and quietly break those
configurations.  These tests lock in the correct behaviour at radius 0,
1, and 2, plus the corner-truncation and obstacle-truncation cases.
"""
from __future__ import annotations

from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.simulation.environment import Environment


def _open_5x5() -> Environment:
    return Environment(width=5, height=5, blocked=set())


def test_radius_zero_returns_singleton():
    env = _open_5x5()
    assert inflate_cells({(2, 2)}, radius=0, env=env) == {(2, 2)}


def test_radius_zero_preserves_all_seed_cells():
    env = _open_5x5()
    seeds = {(0, 0), (2, 2), (4, 4)}
    assert inflate_cells(seeds, radius=0, env=env) == seeds


def test_radius_one_is_5_cell_cross():
    env = _open_5x5()
    expected = {(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)}
    assert inflate_cells({(2, 2)}, radius=1, env=env) == expected


def test_radius_two_is_13_cell_diamond():
    env = _open_5x5()
    result = inflate_cells({(2, 2)}, radius=2, env=env)
    expected = {
        (0, 2),
        (1, 1), (1, 2), (1, 3),
        (2, 0), (2, 1), (2, 2), (2, 3), (2, 4),
        (3, 1), (3, 2), (3, 3),
        (4, 2),
    }
    assert result == expected
    assert len(result) == 13


def test_corner_truncates_out_of_bounds_cells():
    env = _open_5x5()
    # At (0, 0) the diamond would cover (-1, 0), (0, -1) — both OOB.
    result = inflate_cells({(0, 0)}, radius=1, env=env)
    assert result == {(0, 0), (1, 0), (0, 1)}


def test_static_obstacle_truncation():
    # Wall at (1, 2) must be excluded from the inflated set.
    env = Environment(width=5, height=5, blocked={(1, 2)})
    result = inflate_cells({(2, 2)}, radius=1, env=env)
    assert (1, 2) not in result
    assert result == {(2, 2), (3, 2), (2, 1), (2, 3)}


def test_radius_zero_filters_obstacle_seed():
    """When the seed cell is itself a wall, radius=0 should drop it
    rather than emit a phantom buffer over the obstacle."""
    env = Environment(width=5, height=5, blocked={(2, 2)})
    assert inflate_cells({(2, 2)}, radius=0, env=env) == set()


def test_empty_seed_set_returns_empty():
    env = _open_5x5()
    assert inflate_cells(set(), radius=0, env=env) == set()
    assert inflate_cells(set(), radius=3, env=env) == set()
