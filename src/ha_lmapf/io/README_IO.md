# I/O Module

The I/O module handles file input/output operations for the HA-LMAPF system, including map loading, task stream management, and simulation replay recording.

## Module Overview

```
io/
├── __init__.py
├── movingai_map.py   # MovingAI format map parser
├── task_stream.py    # Lifelong task stream I/O
└── replay.py         # Simulation state recorder
```

## Components

### MovingAI Map Loader (`movingai_map.py`)

Parses map files in the standard MovingAI benchmark format (`.map`).

#### Map File Format

```
type octile
height <int>
width <int>
map
<grid rows...>
```

#### Character Interpretation

| Character | Meaning |
|-----------|---------|
| `@` | Static wall/obstacle (Blocked) |
| `T` | Tree/obstacle (Blocked) |
| `.` | Open ground (Free) |
| `G`, `S` | Swamp/water (Treated as Free) |

#### Data Structure

```python
@dataclass(frozen=True)
class MapData:
    grid: List[str]      # ASCII grid for visualization
    width: int           # Number of columns
    height: int          # Number of rows
    blocked: Set[Cell]   # Blocked coordinates (O(1) lookup)
```

#### Usage

```python
from ha_lmapf.io.movingai_map import load_movingai_map

map_data = load_movingai_map("data/maps/warehouse.map")

# Check if cell is blocked
if (5, 10) in map_data.blocked:
    print("Cell (5, 10) is a wall")

# Access dimensions
print(f"Map size: {map_data.width}x{map_data.height}")
```

### Task Stream I/O (`task_stream.py`)

Manages lifelong task sequences with release timing for Lifelong MAPF experiments.

#### Task Stream Format (JSON)

```json
[
  {
    "id": "t_0",
    "start": [3, 5],
    "goal": [5, 10],
    "release_step": 0
  },
  {
    "id": "t_1",
    "start": [8, 2],
    "goal": [12, 12],
    "release_step": 25
  }
]
```

#### Task Fields

| Field | Description |
|-------|-------------|
| `id` | Unique string identifier |
| `start` | `[row, col]` pickup location |
| `goal` | `[row, col]` delivery location |
| `release_step` | Simulation step when task appears |

#### Backward Compatibility

Tasks without a `start` field are treated as delivery-only:
- `start` defaults to `(-1, -1)`
- Agent goes directly to goal (no pickup phase)

#### Functions

```python
def load_task_stream(path: str) -> List[Task]:
    """
    Load task stream from JSON file.
    Returns sorted list by release_step.
    """

def save_task_stream(tasks: List[Task], path: str) -> None:
    """
    Save task list to JSON file.
    Used for generating reproducible benchmarks.
    """

def get_released_tasks(tasks: List[Task], step: int) -> List[Task]:
    """
    Filter tasks available at current simulation step.
    Returns tasks where release_step <= step.
    """
```

#### Usage

```python
from ha_lmapf.io.task_stream import load_task_stream, save_task_stream

# Load existing task stream
tasks = load_task_stream("scenarios/warehouse_tasks.json")

# Generate and save new stream
from ha_lmapf.core.types import Task

new_tasks = [
    Task(task_id="t0", start=(1, 1), goal=(5, 5), release_step=0),
    Task(task_id="t1", start=(2, 2), goal=(8, 8), release_step=10),
]
save_task_stream(new_tasks, "output/tasks.json")
```

### Replay Writer (`replay.py`)

Captures simulation state at every timestep for post-hoc visualization and debugging.

#### Replay Format (JSON)

```json
{
  "meta": {
    "map_path": "path/to/map.map",
    "seed": 12345,
    "steps": 100,
    "config": { ... },
    "task_stream": [
      {"id": "t1", "goal": [5, 10], "release_step": 0}
    ]
  },
  "agents": {
    "0": [[r0, c0], [r1, c1], ...],
    "1": [[r0, c0], [r1, c1], ...]
  },
  "humans": {
    "0": [[r0, c0], ...],
    "1": [[r0, c0], ...]
  }
}
```

#### ReplayWriter Class

```python
@dataclass
class ReplayWriter:
    map_path: str
    seed: int
    config: Dict[str, Any]
    task_stream: List[Dict[str, Any]]

    @classmethod
    def from_config(cls, map_path, seed, config, tasks) -> "ReplayWriter":
        """Factory method from SimConfig objects."""

    def record(self, agents: Dict[int, AgentState],
               humans: Dict[int, HumanState]) -> None:
        """Snapshot current entity positions. Call once per step."""

    def write(self, path: str) -> None:
        """Serialize recorded history to JSON file."""
```

#### Usage

```python
from ha_lmapf.io.replay import ReplayWriter

# Create writer from simulation config
writer = ReplayWriter.from_config(
    map_path="maps/warehouse.map",
    seed=42,
    config=sim_config,
    tasks=task_list,
)

# During simulation loop
for step in range(num_steps):
    sim.step_once()
    writer.record(sim.agents, sim.humans)

# Save replay file
writer.write("logs/replay_001.json")
```

## Use Cases

### 1. Visualization

Replay files enable the GUI visualizer to render simulations post-hoc:

```bash
python scripts/run_gui.py --replay logs/replay_001.json
```

### 2. Debugging

Analyze specific failure cases by examining exact trajectories:

```python
import json

with open("logs/replay.json") as f:
    data = json.load(f)

# Find when agent 0 reached position (5, 10)
for step, pos in enumerate(data["agents"]["0"]):
    if pos == [5, 10]:
        print(f"Agent 0 at (5,10) on step {step}")
```

### 3. Reproducible Benchmarks

Save and load exact task configurations:

```python
# Save scenario
save_task_stream(generated_tasks, "benchmarks/scenario_A.json")

# Reload for experiments
tasks = load_task_stream("benchmarks/scenario_A.json")
```

### 4. Experiment Auditability

Replay metadata captures full experimental configuration:

```python
replay_data = json.load(open("logs/replay.json"))
config = replay_data["meta"]["config"]

print(f"Solver: {config['global_solver']}")
print(f"Seed: {replay_data['meta']['seed']}")
```

## File Locations

| File Type | Default Location | Extension |
|-----------|------------------|-----------|
| Maps | `data/maps/` | `.map` |
| Task Streams | `scenarios/` | `.json` |
| Replays | `logs/` | `.json` |

## Related Modules

- [Simulation](../simulation/README_SIMULATION.md) - Uses I/O for initialization
- [GUI](../gui/README_GUI.md) - Consumes replay files
- [Core Types](../core/README_CORE.md) - Task and config definitions
