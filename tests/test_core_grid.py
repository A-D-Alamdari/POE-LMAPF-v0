
"""
Comprehensive Tests for Grid Geometry and Graph Utilities.

Tests all functions in ha_lmapf.core.grid including:
- in_bounds: coordinate validity checks
- manhattan: L1 distance calculation
- neighbors: 4-connected neighborhood generation
- rc_to_index / index_to_rc: coordinate conversion
- apply_action: action application
- line_of_sight_circle / iter_manhattan_ball: FOV calculations
"""
import pytest
from ha_lmapf.core.grid import (
    in_bounds,
    manhattan,
    neighbors,
    rc_to_index,
    index_to_rc,
    apply_action,
    line_of_sight_circle,
    iter_manhattan_ball,
)
from ha_lmapf.core.types import StepAction


# ============================================================================
# in_bounds Tests
# ============================================================================

class TestInBounds:
    """Tests for in_bounds function."""

    def test_valid_corner_cells(self):
        """Test all four corners are in bounds."""
        width, height = 10, 8
        assert in_bounds((0, 0), width, height)  # top-left
        assert in_bounds((0, 9), width, height)  # top-right
        assert in_bounds((7, 0), width, height)  # bottom-left
        assert in_bounds((7, 9), width, height)  # bottom-right

    def test_center_cell(self):
        """Test center cell is in bounds."""
        assert in_bounds((5, 5), 10, 10)

    def test_out_of_bounds_negative(self):
        """Test negative coordinates are out of bounds."""
        assert not in_bounds((-1, 0), 10, 10)
        assert not in_bounds((0, -1), 10, 10)
        assert not in_bounds((-1, -1), 10, 10)

    def test_out_of_bounds_too_large(self):
        """Test coordinates at or beyond limits are out of bounds."""
        assert not in_bounds((10, 5), 10, 10)  # row == height
        assert not in_bounds((5, 10), 10, 10)  # col == width
        assert not in_bounds((10, 10), 10, 10)

    def test_single_cell_grid(self):
        """Test 1x1 grid."""
        assert in_bounds((0, 0), 1, 1)
        assert not in_bounds((0, 1), 1, 1)
        assert not in_bounds((1, 0), 1, 1)

    def test_wide_grid(self):
        """Test very wide grid (1 row, many columns)."""
        assert in_bounds((0, 99), 100, 1)
        assert not in_bounds((1, 0), 100, 1)

    def test_tall_grid(self):
        """Test very tall grid (many rows, 1 column)."""
        assert in_bounds((99, 0), 1, 100)
        assert not in_bounds((0, 1), 1, 100)


# ============================================================================
# manhattan Tests
# ============================================================================

class TestManhattan:
    """Tests for manhattan distance function."""

    def test_same_cell(self):
        """Distance to self is zero."""
        assert manhattan((5, 5), (5, 5)) == 0

    def test_horizontal_distance(self):
        """Test pure horizontal distance."""
        assert manhattan((0, 0), (0, 10)) == 10
        assert manhattan((5, 3), (5, 8)) == 5

    def test_vertical_distance(self):
        """Test pure vertical distance."""
        assert manhattan((0, 0), (10, 0)) == 10
        assert manhattan((3, 5), (8, 5)) == 5

    def test_diagonal_distance(self):
        """Test diagonal (combined) distance."""
        assert manhattan((0, 0), (3, 4)) == 7
        assert manhattan((1, 1), (4, 5)) == 7

    def test_symmetry(self):
        """Distance is symmetric."""
        assert manhattan((0, 0), (5, 7)) == manhattan((5, 7), (0, 0))

    def test_negative_coordinates(self):
        """Manhattan distance works with negative coords."""
        assert manhattan((-5, -5), (5, 5)) == 20
        assert manhattan((-3, 2), (3, -2)) == 10


# ============================================================================
# neighbors Tests
# ============================================================================

class TestNeighbors:
    """Tests for neighbors function."""

    def test_basic_neighbors(self):
        """Test neighbors of a center cell."""
        nbs = neighbors((5, 5))
        assert len(nbs) == 4
        assert (4, 5) in nbs  # UP
        assert (6, 5) in nbs  # DOWN
        assert (5, 4) in nbs  # LEFT
        assert (5, 6) in nbs  # RIGHT

    def test_origin_neighbors(self):
        """Test neighbors of origin (includes negative coords)."""
        nbs = neighbors((0, 0))
        assert (-1, 0) in nbs  # UP (out of bounds)
        assert (1, 0) in nbs   # DOWN
        assert (0, -1) in nbs  # LEFT (out of bounds)
        assert (0, 1) in nbs   # RIGHT

    def test_neighbors_order(self):
        """Neighbors are returned in UP, DOWN, LEFT, RIGHT order."""
        nbs = neighbors((2, 3))
        assert nbs[0] == (1, 3)  # UP
        assert nbs[1] == (3, 3)  # DOWN
        assert nbs[2] == (2, 2)  # LEFT
        assert nbs[3] == (2, 4)  # RIGHT

    def test_neighbors_count(self):
        """Always exactly 4 neighbors."""
        assert len(neighbors((100, 100))) == 4
        assert len(neighbors((-5, -5))) == 4


# ============================================================================
# Coordinate Conversion Tests
# ============================================================================

class TestCoordinateConversion:
    """Tests for rc_to_index and index_to_rc functions."""

    def test_rc_to_index_origin(self):
        """Origin maps to index 0."""
        assert rc_to_index((0, 0), width=10) == 0

    def test_rc_to_index_first_row(self):
        """First row indices."""
        assert rc_to_index((0, 5), width=10) == 5
        assert rc_to_index((0, 9), width=10) == 9

    def test_rc_to_index_second_row(self):
        """Second row starts at index=width."""
        assert rc_to_index((1, 0), width=10) == 10
        assert rc_to_index((1, 5), width=10) == 15

    def test_index_to_rc_origin(self):
        """Index 0 maps to origin."""
        assert index_to_rc(0, width=10) == (0, 0)

    def test_index_to_rc_row_boundary(self):
        """Test row boundaries."""
        assert index_to_rc(9, width=10) == (0, 9)
        assert index_to_rc(10, width=10) == (1, 0)

    def test_roundtrip_conversion(self):
        """Test rc_to_index and index_to_rc are inverses."""
        width = 15
        for row in range(10):
            for col in range(15):
                idx = rc_to_index((row, col), width)
                assert index_to_rc(idx, width) == (row, col)

    def test_various_widths(self):
        """Test with different grid widths."""
        assert rc_to_index((3, 4), width=5) == 19
        assert index_to_rc(19, width=5) == (3, 4)

        assert rc_to_index((2, 7), width=8) == 23
        assert index_to_rc(23, width=8) == (2, 7)


# ============================================================================
# apply_action Tests
# ============================================================================

class TestApplyAction:
    """Tests for apply_action function."""

    def test_up(self):
        """UP decreases row by 1."""
        assert apply_action((5, 5), StepAction.UP) == (4, 5)

    def test_down(self):
        """DOWN increases row by 1."""
        assert apply_action((5, 5), StepAction.DOWN) == (6, 5)

    def test_left(self):
        """LEFT decreases column by 1."""
        assert apply_action((5, 5), StepAction.LEFT) == (5, 4)

    def test_right(self):
        """RIGHT increases column by 1."""
        assert apply_action((5, 5), StepAction.RIGHT) == (5, 6)

    def test_wait(self):
        """WAIT keeps position unchanged."""
        assert apply_action((5, 5), StepAction.WAIT) == (5, 5)

    def test_all_actions_from_origin(self):
        """Test all actions from origin."""
        assert apply_action((0, 0), StepAction.UP) == (-1, 0)
        assert apply_action((0, 0), StepAction.DOWN) == (1, 0)
        assert apply_action((0, 0), StepAction.LEFT) == (0, -1)
        assert apply_action((0, 0), StepAction.RIGHT) == (0, 1)
        assert apply_action((0, 0), StepAction.WAIT) == (0, 0)

    def test_action_sequence(self):
        """Test sequence of actions."""
        pos = (0, 0)
        pos = apply_action(pos, StepAction.DOWN)
        pos = apply_action(pos, StepAction.RIGHT)
        pos = apply_action(pos, StepAction.RIGHT)
        pos = apply_action(pos, StepAction.DOWN)
        assert pos == (2, 2)


# ============================================================================
# FOV / Manhattan Ball Tests
# ============================================================================

class TestLineOfSightCircle:
    """Tests for line_of_sight_circle function."""

    def test_radius_zero(self):
        """Radius 0 returns only center."""
        cells = line_of_sight_circle((5, 5), 0)
        assert len(cells) == 1
        assert (5, 5) in cells

    def test_radius_one(self):
        """Radius 1 returns center + 4 neighbors (5 cells)."""
        cells = line_of_sight_circle((5, 5), 1)
        assert len(cells) == 5
        assert (5, 5) in cells  # center
        assert (4, 5) in cells  # up
        assert (6, 5) in cells  # down
        assert (5, 4) in cells  # left
        assert (5, 6) in cells  # right

    def test_radius_two(self):
        """Radius 2 returns 13 cells (diamond shape)."""
        cells = line_of_sight_circle((5, 5), 2)
        # Formula: 2*r^2 + 2*r + 1 = 2*4 + 4 + 1 = 13
        assert len(cells) == 13
        assert (5, 5) in cells
        assert (3, 5) in cells  # 2 up
        assert (7, 5) in cells  # 2 down
        assert (5, 3) in cells  # 2 left
        assert (5, 7) in cells  # 2 right

    def test_center_at_origin(self):
        """Test with center at origin (includes negative coords)."""
        cells = line_of_sight_circle((0, 0), 1)
        assert (0, 0) in cells
        assert (-1, 0) in cells
        assert (0, -1) in cells

    def test_all_cells_within_manhattan_distance(self):
        """Verify all returned cells are within manhattan distance."""
        center = (10, 10)
        radius = 3
        cells = line_of_sight_circle(center, radius)
        for cell in cells:
            assert manhattan(center, cell) <= radius


class TestIterManhattanBall:
    """Tests for iter_manhattan_ball generator."""

    def test_same_as_line_of_sight(self):
        """Generator produces same cells as list function."""
        center = (5, 5)
        radius = 3
        from_list = set(line_of_sight_circle(center, radius))
        from_gen = set(iter_manhattan_ball(center, radius))
        assert from_list == from_gen

    def test_is_generator(self):
        """Verify it returns a generator/iterator."""
        gen = iter_manhattan_ball((0, 0), 2)
        assert hasattr(gen, '__next__')

    def test_can_early_exit(self):
        """Can stop iteration early."""
        gen = iter_manhattan_ball((0, 0), 100)
        first = next(gen)
        assert first is not None
        # No exception, successfully got one element


# ============================================================================
# Integration Tests
# ============================================================================

class TestGridIntegration:
    """Integration tests combining multiple grid functions."""

    def test_neighbors_within_bounds(self):
        """Filter neighbors to only those in bounds."""
        width, height = 5, 5
        center = (0, 0)  # corner
        nbs = neighbors(center)
        valid = [n for n in nbs if in_bounds(n, width, height)]
        assert len(valid) == 2  # only DOWN and RIGHT
        assert (1, 0) in valid
        assert (0, 1) in valid

    def test_action_produces_neighbor(self):
        """Non-WAIT actions produce a neighbor cell."""
        center = (5, 5)
        nbs = set(neighbors(center))
        for action in [StepAction.UP, StepAction.DOWN, StepAction.LEFT, StepAction.RIGHT]:
            result = apply_action(center, action)
            assert result in nbs

    def test_fov_corner_filtering(self):
        """Filter FOV cells to only those in bounds."""
        width, height = 10, 10
        center = (0, 0)
        radius = 2
        cells = line_of_sight_circle(center, radius)
        valid = [c for c in cells if in_bounds(c, width, height)]
        # At corner with radius 2, only cells in first quadrant are valid
        assert len(valid) < len(cells)
        assert all(in_bounds(c, width, height) for c in valid)
