# GUI Module

The GUI module provides real-time and replay-based visualization for HA-LMAPF simulations using Pygame. It renders the grid environment, agent/human positions, planned paths, and provides interactive controls.

## Module Overview

```
gui/
├── __init__.py
├── visualizer.py    # Pygame-based renderer
└── ui_state.py      # UI toggle state management
```

## Components

### Visualizer (`visualizer.py`)

The `Visualizer` class provides real-time rendering of the simulation:

```python
@dataclass
class Visualizer:
    sim: Any              # Simulator instance
    ui_state: UIState     # Toggle states
    cell_size: int = 14   # Pixels per grid cell
    margin: int = 1       # Cell margin
    fps: int = 30         # Target frame rate
```

#### Rendering Layers

1. **Grid** - Static obstacles (dark) and free cells (light)
2. **Global Plans** - Blue lines showing Tier-1 paths
3. **Local Plans** - Green lines showing Tier-2 detours
4. **Humans** - Red discs for dynamic obstacles
5. **Agents** - Blue discs for agents
6. **FOV** - Yellow boxes for field-of-view (optional)
7. **HUD** - Status bar with metrics

#### Color Scheme

| Element | Color |
|---------|-------|
| Background | Light gray `(235, 235, 235)` |
| Obstacles | Dark gray `(40, 40, 40)` |
| Agents | Blue `(30, 120, 220)` |
| Humans | Red-orange `(220, 90, 60)` |
| Global paths | Blue `(100, 100, 255)` |
| Local paths | Green `(50, 200, 50)` |
| FOV box | Yellow `(200, 200, 50)` |

#### Key Methods

```python
def poll(self) -> Optional[str]:
    """
    Process pygame events.
    Returns: "quit", "toggle_pause", "step_once", "reset", or None
    """

def render(self) -> None:
    """Draw current simulation state to screen."""

def close(self) -> None:
    """Clean up pygame resources."""
```

### UI State (`ui_state.py`)

The `UIState` dataclass manages visualization toggle flags:

```python
@dataclass
class UIState:
    show_fov: bool = False         # Agent field-of-view boxes
    show_forbidden: bool = False    # Safety-inflated zones
    show_plans: bool = False        # Global planned paths (blue)
    show_local_plans: bool = True   # Local replanned paths (green)
    show_tokens: bool = False       # Token ownership (token-passing)
    auto_step: bool = False         # Continuous simulation

    def toggle(self, name: str) -> None:
        """Toggle a boolean attribute by name."""
```

## Keyboard Controls

| Key | Action |
|-----|--------|
| `SPACE` | Pause/Resume simulation |
| `N` | Step once (when paused) |
| `R` | Reset simulation |
| `P` | Toggle global plans (blue) |
| `L` | Toggle local plans (green) |
| `F` | Toggle FOV visualization |
| `B` | Toggle forbidden zones |
| `A` | Toggle auto-step mode |
| `ESC` | Quit |

## HUD Display

The status bar shows:
- **Step**: Current simulation timestep
- **Done**: Tasks completed
- **Auto(A)**: Auto-step mode ON/OFF
- **Global(P)**: Global path display ON/OFF
- **Local(L)**: Local path display ON/OFF with active count

## Usage Examples

### Live Simulation

```python
from ha_lmapf.simulation.simulator import Simulator
from ha_lmapf.gui.visualizer import Visualizer
from ha_lmapf.gui.ui_state import UIState

# Create simulation
sim = Simulator(config)
ui_state = UIState(show_plans=True)
viz = Visualizer(sim=sim, ui_state=ui_state)

# Main loop
running = True
paused = True
while running:
    cmd = viz.poll()
    if cmd == "quit":
        running = False
    elif cmd == "toggle_pause":
        paused = not paused
    elif cmd == "step_once":
        sim.step_once()

    if not paused or ui_state.auto_step:
        sim.step_once()

    viz.render()

viz.close()
```

### Using Runner Scripts

```bash
# Lifelong MAPF with GUI
python scripts/run_gui.py --config configs/warehouse.yaml

# One-shot MAPF with GUI
python scripts/run_oneshot_gui.py --map maps/small.map --agents 5

# Human-aware one-shot MAPF
python scripts/run_oneshot_hamapf_gui.py --map maps/small.map --agents 5 --humans 3
```

## Display Configuration

### Software Rendering

The visualizer uses software rendering by default to avoid OpenGL/GLX issues on headless systems:

```python
os.environ.setdefault('SDL_VIDEODRIVER', 'x11')
os.environ.setdefault('SDL_RENDER_DRIVER', 'software')
```

### Window Size

Automatically calculated from map dimensions:
- Width: `map.width * cell_size` pixels
- Height: `map.height * cell_size + 32` pixels (includes HUD)

### Cell Size

Default is 14 pixels. Adjust for different map scales:

```python
viz = Visualizer(sim=sim, ui_state=ui_state, cell_size=20)
```

## Path Visualization

### Global Plans (Blue)

Shows remaining path from current step:
- Thin blue lines connecting waypoints
- Small dot at goal location
- Updates as plan is executed

### Local Plans (Green)

Shows reactive detour paths:
- Thicker green lines for visibility
- Circle at origin indicating replan start
- Larger dot at intermediate waypoint

## Integration with Simulator

The visualizer accesses simulator state via:

```python
# Agent and human positions
sim.agents[aid].pos
sim.humans[hid].pos

# Configuration
sim.config.fov_radius

# Path data
sim.plans()        # Returns PlanBundle
sim.local_paths()  # Returns Dict[int, List[Cell]]
```

## Troubleshooting

### Display Issues

1. **No display found**: Set `DISPLAY` environment variable
2. **GLX errors**: Uses software rendering by default
3. **Slow rendering**: Reduce `cell_size` or `fps`

### Performance

For large maps:
- Disable unnecessary overlays (FOV, forbidden zones)
- Use auto-step sparingly on complex scenarios
- Consider reducing FPS for computation-heavy simulations

## Related Modules

- [Simulation](../simulation/README_SIMULATION.md) - Provides state to visualize
- [I/O](../io/README_IO.md) - Replay file format
- [Local Tier](../local_tier/README_LOCAL_TIER.md) - Local path source
- [Global Tier](../global_tier/README_GLOBAL_TIER.md) - Global plan source
