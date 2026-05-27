# MAPF Solvers

Multi-Agent Pathfinding solver implementations for the global tier.

## Overview

### Python Implementations

| Solver              | Algorithm                            | Use Case                   |
|---------------------|--------------------------------------|----------------------------|
| `RealTimeLaCAMSolver` | Real-Time LaCAM with persistent DFS | Streaming / real-time use  |

### Official C++ Implementations - Kei18 (Real-time focused)

| Solver                | Source                                          | Speed     | Use Case                   |
|-----------------------|-------------------------------------------------|-----------|----------------------------|
| `LaCAM3Solver`        | [Kei18/lacam3](https://github.com/Kei18/lacam3) | Very Fast | Production, 50+ agents     |
| `LaCAMOfficialSolver` | [Kei18/lacam](https://github.com/Kei18/lacam)   | Very Fast | Production                 |
| `PIBT2Solver`         | [Kei18/pibt2](https://github.com/Kei18/pibt2)   | Fastest   | Lifelong MAPF, 100+ agents |

### Official C++ Implementations - Jiaoyang-Li (Research-grade)

| Solver        | Source                                                            | Optimality         | Use Case                       |
|---------------|-------------------------------------------------------------------|--------------------|--------------------------------|
| `RHCRSolver`  | [Jiaoyang-Li/RHCR](https://github.com/Jiaoyang-Li/RHCR)           | Suboptimal         | Lifelong MAPF with replanning  |
| `CBSH2Solver` | [Jiaoyang-Li/CBSH2-RTC](https://github.com/Jiaoyang-Li/CBSH2-RTC) | Optimal            | Research, advanced CBS         |
| `EECBSSolver` | [Jiaoyang-Li/EECBS](https://github.com/Jiaoyang-Li/EECBS)         | Bounded-suboptimal | Quality-time tradeoff          |
| `PBSSolver`   | [Jiaoyang-Li/PBS](https://github.com/Jiaoyang-Li/PBS)             | Suboptimal         | Fast, scalable                 |
| `LNS2Solver`  | [Jiaoyang-Li/MAPF-LNS2](https://github.com/Jiaoyang-Li/MAPF-LNS2) | Anytime            | Very large scale (400+ agents) |

## Files

| File                           | Description                                         |
|--------------------------------|-----------------------------------------------------|
| `common.py`                    | Shared utilities (constraints, A*)                  |
| `lacam3_wrapper.py`            | Official LaCAM3 C++ executable wrapper              |
| `lacam_official_wrapper.py`    | Official LaCAM C++ executable wrapper               |
| `lacam_official_real_time.py`  | Real-Time LaCAM with persistent DFS tree            |
| `pibt2_wrapper.py`             | Official PIBT2 C++ executable wrapper               |
| `rhcr_wrapper.py`              | RHCR (Rolling-Horizon Collision Resolution) wrapper |
| `cbsh2_wrapper.py`             | CBSH2-RTC (CBS with Heuristics) wrapper             |
| `eecbs_wrapper.py`             | EECBS (Explicit Estimation CBS) wrapper             |
| `pbs_wrapper.py`               | PBS (Priority-Based Search) wrapper                 |
| `lns2_wrapper.py`              | MAPF-LNS2 (Large Neighborhood Search) wrapper       |

---

## cbsh2_wrapper.py - CBS with Heuristics (Optimal)

Wrapper for the CBSH2-RTC C++ solver. This is the primary optimal solver,
selected via `global_solver: "cbs"` in config files.

### Algorithm Overview

```
CBS Algorithm:
1. Find optimal single-agent paths (ignoring other agents)
2. Check for conflicts between paths
3. If conflict found:
   a. Create two child nodes with constraints
   b. Recurse on children
4. Return first conflict-free solution (optimal by BFS)
```

### Conflict Types

| Type   | Description                          | Resolution                         |
|--------|--------------------------------------|------------------------------------|
| Vertex | Two agents at same cell at same time | Add VertexConstraint to each child |
| Edge   | Two agents swap positions            | Add EdgeConstraint to each child   |

### Usage

```python
from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver

solver = CBSH2Solver(time_limit_sec=2.0)
bundle = solver.plan(env=env, agents=agents, assignments=assignments, step=0, horizon=50)

# Access paths
for agent_id, path in bundle.paths.items():
    print(f"Agent {agent_id}: {path.cells}")
```

---

## lacam_official_wrapper.py - LaCAM Official Solver

Wrapper for the official LaCAM C++ executable from https://github.com/Kei18/lacam.

### Usage

```python
from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver

solver = LaCAMOfficialSolver(time_limit_sec=1.0)
bundle = solver.plan(env=env, agents=agents, assignments=assignments, step=0, horizon=100)
```

---

## common.py - Shared Utilities

### Constraint Types

```python
@dataclass(frozen=True)
class VertexConstraint:
    agent_id: int
    cell: Cell
    time: int  # absolute timestep


@dataclass(frozen=True)
class EdgeConstraint:
    agent_id: int
    from_cell: Cell
    to_cell: Cell
    time: int  # absolute timestep for the transition
```

### Constrained A*

```python
def a_star_constrained(
        env: Environment,
        start: Cell,
        goal: Cell,
        start_step: int,
        horizon: int,
        vertex_constraints: Set[VertexConstraint],
        edge_constraints: Set[EdgeConstraint],
        reservation_table: Optional[Dict] = None
) -> Optional[List[Cell]]:
    """
    A* with time-indexed constraints.

    Returns path respecting all constraints, or None if impossible.
    """
```

### Conflict Detection

```python
def detect_first_conflict(
        paths: Dict[int, TimedPath],
        start_step: int,
        horizon: int
) -> Optional[Conflict]:
    """Find first vertex or edge conflict between paths."""
```

---

## Performance Comparison

| Solver               | 10 agents | 50 agents | 100 agents | 200 agents |
|----------------------|-----------|-----------|------------|------------|
| CBS (Python)         | ~100ms    | ~10s      | Timeout    | Timeout    |
| LaCAM (Python)       | ~10ms     | ~100ms    | ~500ms     | ~2s        |
| LaCAM3 (C++)         | ~5ms      | ~30ms     | ~100ms     | ~300ms     |
| LaCAM Official (C++) | ~5ms      | ~40ms     | ~150ms     | ~400ms     |
| PIBT2 (C++)          | ~2ms      | ~20ms     | ~50ms      | ~150ms     |

---

## Solver Selection Guide

| Scenario                     | Recommended Solver | Config Value            |
|------------------------------|--------------------|-------------------------|
| Research (need optimal)      | CBS or CBSH2       | `"cbs"` or `"cbsh2"`    |
| Small instances (<20 agents) | CBS                | `"cbs"`                 |
| Medium instances (20-50)     | LaCAM (Python)     | `"lacam"`               |
| Large instances (50-100)     | LaCAM3 (C++)       | `"lacam3"`              |
| Very large (100+ agents)     | PIBT2 or LNS2      | `"pibt2"` or `"lns2"`   |
| Huge scale (400+ agents)     | MAPF-LNS2          | `"lns2"`                |
| Lifelong MAPF                | PIBT2 or RHCR      | `"pibt2"` or `"rhcr"`   |
| Real-time requirements       | PIBT2 or LaCAM3    | `"pibt2"` or `"lacam3"` |
| Quality-time tradeoff        | EECBS              | `"eecbs"`               |
| Fast suboptimal              | PBS                | `"pbs"`                 |

---

## Configuration

```yaml
# In config file
global_solver: "lacam3"  # Options below

# Python solvers (no setup required):
#   "cbs"            - Optimal, slow for 20+ agents
#   "lacam"          - Fast approximate

# Official C++ solvers - Kei18 (require build):
#   "lacam3"         - LaCAM3 (fastest LaCAM)
#   "lacam_official" - Original LaCAM
#   "pibt2"          - PIBT2 (best for lifelong/real-time)

# Official C++ solvers - Jiaoyang-Li (require build):
#   "rhcr"           - Rolling-Horizon Collision Resolution (lifelong)
#   "cbsh2"          - CBS with Heuristics 2 (optimal, advanced)
#   "eecbs"          - Explicit Estimation CBS (bounded-suboptimal)
#   "pbs"            - Priority-Based Search (fast, scalable)
#   "lns2"           - Large Neighborhood Search 2 (anytime, huge scale)
```

### Installing Official Solvers

See [GETTING_STARTED.md](../../../docs/GETTING_STARTED.md#5-installing-official-mapf-solvers) for detailed instructions.

**Cross-Platform Support:** All wrappers support Linux, macOS, and Windows.

| Platform    | Binary Extension | Example                        |
|-------------|------------------|--------------------------------|
| Linux/macOS | None             | `lacam3`, `mapf_pibt2`         |
| Windows     | `.exe`           | `lacam3.exe`, `mapf_pibt2.exe` |

**Linux/macOS:**

```bash
# LaCAM3 (recommended)
git clone --recursive https://github.com/Kei18/lacam3.git && cd lacam3
cmake -B build && make -C build
cp build/main path/to/ha_lmapf/global_tier/solvers/lacam3

# LaCAM (original)
git clone --recursive https://github.com/Kei18/lacam.git && cd lacam
cmake -B build && make -C build
cp build/main path/to/ha_lmapf/global_tier/solvers/lacam_official

# PIBT2 (builds two executables: mapf and mapd)
git clone --recursive https://github.com/Kei18/pibt2.git && cd pibt2
mkdir build && cd build && cmake .. && make
cp mapf path/to/ha_lmapf/global_tier/solvers/mapf_pibt2
cp mapd path/to/ha_lmapf/global_tier/solvers/mapd_pibt2
```

**Windows:**

```cmd
# LaCAM3
git clone --recursive https://github.com/Kei18/lacam3.git && cd lacam3
cmake -B build && cmake --build build --config Release
copy build\Release\main.exe path\to\ha_lmapf\global_tier\solvers\lacam3.exe

# LaCAM (original)
git clone --recursive https://github.com/Kei18/lacam.git && cd lacam
cmake -B build && cmake --build build --config Release
copy build\Release\main.exe path\to\ha_lmapf\global_tier\solvers\lacam_official.exe

# PIBT2
git clone --recursive https://github.com/Kei18/pibt2.git && cd pibt2
mkdir build && cd build && cmake .. && cmake --build . --config Release
copy Release\mapf.exe path\to\ha_lmapf\global_tier\solvers\mapf_pibt2.exe
copy Release\mapd.exe path\to\ha_lmapf\global_tier\solvers\mapd_pibt2.exe
```

### Jiaoyang-Li Solvers

All solvers from Jiaoyang Li's repositories require Boost library.

**Prerequisites:**

```bash
# Ubuntu
sudo apt install libboost-all-dev

# For MAPF-LNS2, also need Eigen:
sudo apt install libeigen3-dev
```

**Linux/macOS:**

```bash
# RHCR (Rolling-Horizon Collision Resolution)
git clone https://github.com/Jiaoyang-Li/RHCR.git && cd RHCR
cmake . && make
cp lifelong path/to/ha_lmapf/global_tier/solvers/rhcr

# CBSH2-RTC (CBS with Heuristics)
git clone https://github.com/Jiaoyang-Li/CBSH2-RTC.git && cd CBSH2-RTC
cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
cp cbs path/to/ha_lmapf/global_tier/solvers/cbsh2

# EECBS (Explicit Estimation CBS)
git clone https://github.com/Jiaoyang-Li/EECBS.git && cd EECBS
cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
cp eecbs path/to/ha_lmapf/global_tier/solvers/eecbs

# PBS (Priority-Based Search)
git clone https://github.com/Jiaoyang-Li/PBS.git && cd PBS
cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
cp pbs path/to/ha_lmapf/global_tier/solvers/pbs

# MAPF-LNS2 (Large Neighborhood Search)
git clone https://github.com/Jiaoyang-Li/MAPF-LNS2.git && cd MAPF-LNS2
cmake -DCMAKE_BUILD_TYPE=RELEASE . && make
cp lns path/to/ha_lmapf/global_tier/solvers/lns2
```

**Windows:**

```cmd
# RHCR
git clone https://github.com/Jiaoyang-Li/RHCR.git && cd RHCR
cmake -B build && cmake --build build --config Release
copy build\Release\lifelong.exe path\to\ha_lmapf\global_tier\solvers\rhcr.exe

# CBSH2-RTC
git clone https://github.com/Jiaoyang-Li/CBSH2-RTC.git && cd CBSH2-RTC
cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
copy build\Release\cbs.exe path\to\ha_lmapf\global_tier\solvers\cbsh2.exe

# EECBS
git clone https://github.com/Jiaoyang-Li/EECBS.git && cd EECBS
cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
copy build\Release\eecbs.exe path\to\ha_lmapf\global_tier\solvers\eecbs.exe

# PBS
git clone https://github.com/Jiaoyang-Li/PBS.git && cd PBS
cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
copy build\Release\pbs.exe path\to\ha_lmapf\global_tier\solvers\pbs.exe

# MAPF-LNS2
git clone https://github.com/Jiaoyang-Li/MAPF-LNS2.git && cd MAPF-LNS2
cmake -B build -DCMAKE_BUILD_TYPE=RELEASE && cmake --build build --config Release
copy build\Release\lns.exe path\to\ha_lmapf\global_tier\solvers\lns2.exe
```

---

## Related Modules

- [Global Tier](../README_GLOBAL_TIER.md) - Uses solvers for planning
- [Core](../../core/README_CORE.md) - Type definitions for paths