from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple, Any

# Set SDL to use software rendering as fallback for X11/GLX issues
# This must be done BEFORE importing pygame
if sys.platform.startswith("linux") and os.environ.get("DISPLAY"):
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")

os.environ.setdefault('SDL_RENDER_DRIVER', 'software')

import pygame

# Import UIState to type hint it
from ha_lmapf.gui.ui_state import UIState

Cell = Tuple[int, int]


@dataclass
class Visualizer:
    """
    Minimal pygame visualizer for the Human-Aware Lifelong MAPF simulator.

    Controls:
      - SPACE: Pause/Resume
      - N: Step Once
      - P: Toggle Global Plans (Blue lines)
      - L: Toggle Local Replanned Paths (Green lines)
      - F: Toggle FOV
      - B: Toggle Forbidden Zones (Safety)
      - ESC: Quit
    """

    sim: Any
    # IMPORTANT: ui_state must be the second argument to match run_gui.py
    ui_state: UIState
    cell_size: int = 24
    margin: int = 1
    fps: int = 30

    def __post_init__(self) -> None:
        # Initialize pygame
        pygame.init()

        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 16)

        w_px = self.sim.env.width * self.cell_size
        h_px = self.sim.env.height * self.cell_size + 32  # HUD bar

        # Create display without OpenGL to avoid GLX errors
        # Use pygame.SWSURFACE for software rendering (no hardware acceleration)
        try:
            self.screen = pygame.display.set_mode((w_px, h_px), pygame.SWSURFACE)
        except pygame.error:
            # Fallback: try with no flags
            self.screen = pygame.display.set_mode((w_px, h_px))

        pygame.display.set_caption("HAL-MAPF (Human-Aware Lifelong MAPF)")

        # Colors
        self.bg_color = (235, 235, 235)
        self.blocked_color = (40, 40, 40)
        self.grid_line_color = (210, 210, 210)
        self.agent_color = (30, 120, 220)
        self.human_color = (220, 90, 60)
        self.text_color = (10, 10, 10)

        # Overlay colors
        self.path_color = (100, 100, 255)  # Blue for global plans
        self.local_path_color = (50, 200, 50)  # Green for local replanned paths
        self.fov_color = (200, 200, 50)
        self.forbidden_color = (255, 100, 100)

        self._attached = True

    def attach(self, sim: Any) -> None:
        self.sim = sim

    def poll(self) -> Optional[str]:
        """
        Process events. Returns high-level commands for the runner loop,
        or handles UI toggles internally.
        """
        cmd = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return "quit"
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "quit"
                if event.key == pygame.K_SPACE:
                    cmd = "toggle_pause"
                if event.key == pygame.K_n:
                    cmd = "step_once"
                if event.key == pygame.K_r:
                    cmd = "reset"

                # UI Toggles
                if event.key == pygame.K_p:
                    self.ui_state.toggle("show_plans")
                    print(f"UI: Show Global Plans = {self.ui_state.show_plans}")
                if event.key == pygame.K_l:
                    self.ui_state.toggle("show_local_plans")
                    print(f"UI: Show Local Plans = {self.ui_state.show_local_plans}")
                if event.key == pygame.K_f:
                    self.ui_state.toggle("show_fov")
                if event.key == pygame.K_b:
                    self.ui_state.toggle("show_forbidden")
                if event.key == pygame.K_a:
                    self.ui_state.toggle("auto_step")
                    print(f"UI: Auto-Step = {self.ui_state.auto_step}")
                if event.key == pygame.K_e:
                    self.ui_state.toggle("show_events")
                    print(f"UI: Event Log = {self.ui_state.show_events}")

        return cmd

    def render(self) -> None:
        self.screen.fill(self.bg_color)

        # 1. Draw Grid
        for r in range(self.sim.env.height):
            for c in range(self.sim.env.width):
                rect = self._get_rect(r, c)
                if (r, c) in self.sim.env.blocked:
                    pygame.draw.rect(self.screen, self.blocked_color, rect)
                else:
                    pygame.draw.rect(self.screen, self.bg_color, rect)
                    pygame.draw.rect(self.screen, self.grid_line_color, rect, width=1)

        # 2. Draw Plans (Tier-1) - if enabled
        if self.ui_state.show_plans:
            self._draw_global_plans()

        # 2b. Draw Local Replanned Paths (Tier-2) - if enabled
        if self.ui_state.show_local_plans:
            self._draw_local_plans()

        # 3. Draw Humans
        for hid in sorted(self.sim.humans.keys()):
            h = self.sim.humans[hid]
            self._draw_disc(h.pos, self.human_color, inset=2)
            # Optional: Draw safety radius ring
            if self.ui_state.show_forbidden:
                pass  # Could draw ring here

        # 4. Draw Agents
        for aid in sorted(self.sim.agents.keys()):
            a = self.sim.agents[aid]
            self._draw_disc(a.pos, self.agent_color, inset=2)

            # Draw FOV if enabled
            if self.ui_state.show_fov:
                self._draw_fov_box(a.pos, self.sim.config.fov_radius)

        # 5. HUD
        self._draw_hud()

        pygame.display.flip()
        self.clock.tick(self.fps)

    def _draw_global_plans(self):
        # Access the plans from the simulator
        # Note: In simulator.py we defined plans() as a method
        plans = self.sim.plans()
        if not plans or not plans.paths:
            return

        for aid, timed_path in plans.paths.items():
            if timed_path is None:
                continue

            # Only draw relevant part of path (from current step onwards)
            current_step = self.sim.step
            start_idx = max(0, current_step - timed_path.start_step)

            # Get points
            cells = timed_path.cells
            if start_idx < len(cells):
                future_cells = cells[start_idx:]
                if len(future_cells) > 1:
                    points = [self._get_center(r, c) for r, c in future_cells]
                    pygame.draw.lines(self.screen, self.path_color, False, points, 2)
                    # Draw small dot at goal
                    pygame.draw.circle(self.screen, self.path_color, points[-1], 3)

    def _draw_local_plans(self):
        """Draw local replanned paths (Tier-2) in green."""
        # Access local paths from the simulator
        if not hasattr(self.sim, 'local_paths'):
            return

        local_paths = self.sim.local_paths()
        if not local_paths:
            return

        for aid, path in local_paths.items():
            if path and len(path) >= 2:
                points = [self._get_center(r, c) for r, c in path]
                # Draw thicker line for local plans
                pygame.draw.lines(self.screen, self.local_path_color, False, points, 3)
                # Draw larger dot at intermediate waypoint
                pygame.draw.circle(self.screen, self.local_path_color, points[-1], 4)
                # Draw small circle at start to indicate replanning origin
                pygame.draw.circle(self.screen, self.local_path_color, points[0], 5, 1)

    def _draw_fov_box(self, center: Cell, radius: int):
        r, c = center
        top = (r - radius) * self.cell_size
        left = (c - radius) * self.cell_size
        side = (2 * radius + 1) * self.cell_size
        rect = pygame.Rect(left, top, side, side)
        pygame.draw.rect(self.screen, self.fov_color, rect, width=1)

    def _draw_hud(self):
        hud_y = self.sim.env.height * self.cell_size
        pygame.draw.rect(self.screen, (245, 245, 245),
                         pygame.Rect(0, hud_y, self.screen.get_width(), 32))

        completed = sum(a.done_tasks for a in self.sim.agents.values())
        global_txt = "ON" if self.ui_state.show_plans else "OFF"
        local_txt = "ON" if self.ui_state.show_local_plans else "OFF"
        auto_txt = "ON" if self.ui_state.auto_step else "OFF"

        # Count active local replans
        local_count = 0
        if hasattr(self.sim, 'local_paths'):
            local_count = len(self.sim.local_paths())

        # Count mid-horizon assigned agents
        mid_count = 0
        if hasattr(self.sim, '_mid_horizon_assigned'):
            mid_count = len(self.sim._mid_horizon_assigned)

        mid_txt = f" | MidHz: {mid_count}" if mid_count > 0 else ""
        text = (f"Step: {self.sim.step} | Done: {completed} | "
                f"Auto(A): {auto_txt} | Global(P): {global_txt} | "
                f"Local(L): {local_txt}({local_count}){mid_txt}")

        surf = self.font.render(text, True, self.text_color)
        self.screen.blit(surf, (8, hud_y + 7))

    def _get_rect(self, r: int, c: int) -> pygame.Rect:
        return pygame.Rect(c * self.cell_size, r * self.cell_size,
                           self.cell_size, self.cell_size)

    def _get_center(self, r: int, c: int) -> Tuple[int, int]:
        return (c * self.cell_size + self.cell_size // 2,
                r * self.cell_size + self.cell_size // 2)

    def _draw_disc(self, cell: Cell, color: Tuple[int, int, int], inset: int = 2) -> None:
        rect = self._get_rect(*cell)
        rect.inflate_ip(-inset * 2, -inset * 2)
        pygame.draw.ellipse(self.screen, color, rect)

    def close(self) -> None:
        pygame.quit()
