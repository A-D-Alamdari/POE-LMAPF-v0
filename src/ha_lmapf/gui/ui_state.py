from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UIState:
    """
    UI toggle state for the visualizer.

    Flags control optional overlays:
      - show_fov: render agent field-of-view
      - show_forbidden: render safety-inflated forbidden cells
      - show_plans: render global planned paths (blue)
      - show_local_plans: render local replanned paths (green)
      - show_tokens: render token ownership (for token-passing resolver)
      - auto_step: automatically step simulation continuously
    """
    show_fov: bool = False
    show_forbidden: bool = False
    show_plans: bool = False
    show_local_plans: bool = True  # Show local replanned paths by default
    show_tokens: bool = False
    auto_step: bool = False  # Auto-step mode (continuous stepping)
    show_events: bool = True  # Print per-step decision events to console

    def toggle(self, name: str) -> None:
        """
        Toggle a UI flag by attribute name.
        Raises AttributeError if the name is invalid.
        """
        if not hasattr(self, name):
            raise AttributeError(f"UIState has no attribute '{name}'")
        current = getattr(self, name)
        if not isinstance(current, bool):
            raise AttributeError(f"UIState attribute '{name}' is not boolean")
        setattr(self, name, not current)
