# Complete Beginner's Guide to HA-LMAPF

## Human-Aware Lifelong Multi-Agent Path Finding under Partial Observability

This guide is written for users with **no prior programming experience**. Follow each step exactly as written.

---

## Developer Quickstart

For experienced developers who want to get started quickly:

```bash
# Clone and setup
git clone <REPO_URL>
cd ha_lmapf
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e ".[dev,gui]"

# Run tests (should all pass)
pytest

# Run a quick demo
python scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 5

# Run evaluation
python scripts/evaluation/run_evaluation.py --group baselines --seeds 0 --out logs/test
```

**Troubleshooting:**
- If imports fail: `pip install -e . --force-reinstall`
- If tests can't find modules: pytest config is in `pyproject.toml`
- For Windows: use `.venv\Scripts\activate` instead

---


## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Before You Start (Prerequisites)](#2-before-you-start-prerequisites)
3. [Step-by-Step Installation](#3-step-by-step-installation)
4. [Verifying Your Installation](#4-verifying-your-installation)
5. [Installing Official MAPF Solvers](#5-installing-official-mapf-solvers)
6. [Your First Experiment](#6-your-first-experiment)
7. [Understanding the Output](#7-understanding-the-output)
8. [Running All Paper Experiments](#8-running-all-paper-experiments)
9. [Running Individual Experiment Groups](#9-running-individual-experiment-groups)
10. [Classical MAPF Experiments (One-Shot)](#10-classical-mapf-experiments-one-shot)
11. [Experiments Without Humans](#11-experiments-without-humans)
12. [GUI Visualization Scripts](#12-gui-visualization-scripts)
13. [Lifelong MAPF GUI (run_gui.py)](#13-lifelong-mapf-gui-run_guipy)
14. [Classical MAPF GUI (run_oneshot_gui.py)](#14-classical-mapf-gui-run_oneshot_guipy)
15. [Human-Aware MAPF GUI (run_oneshot_hamapf_gui.py)](#15-human-aware-mapf-gui-run_oneshot_hamapf_guipy)
16. [Creating Your Own Configuration](#16-creating-your-own-configuration)
17. [Generating Figures and Tables](#17-generating-figures-and-tables)
18. [Running Tests](#18-running-tests)
19. [Configuration Files Explained](#19-configuration-files-explained)
20. [Common Problems and Solutions](#20-common-problems-and-solutions)
21. [Glossary of Terms](#21-glossary-of-terms)
22. [Complete Command Reference](#22-complete-command-reference)

---

## 1. What This Project Does

### In Simple Terms

Imagine a large warehouse with many agents moving packages around. These agents need to:

- Pick up items from one location
- Deliver them to another location
- Avoid crashing into each other
- Avoid bumping into human workers walking through the aisles

This software **simulates** that scenario. It tests different strategies for coordinating the agents and measures how
well they perform.

### Two Types of Experiments

This project supports two main modes:

| Mode              | Description                                                    | Use Case                  |
|-------------------|----------------------------------------------------------------|---------------------------|
| **Lifelong MAPF** | Agents continuously receive new tasks                          | Real warehouse operations |
| **One-Shot MAPF** | Each agent gets one goal, simulation ends when all reach goals | Classical MAPF research   |

### Why This Matters

Traditional agent path planning assumes:

- Agents do one task and stop
- The environment doesn't change
- There are no unpredictable obstacles (like humans)

Real warehouses are different:

- Agents work continuously all day
- New tasks arrive constantly
- Human workers move unpredictably

This project solves the **realistic** version of the problem.

### What the Experiments Measure

| Metric                     | What It Measures                        | Good Values      |
|----------------------------|-----------------------------------------|------------------|
| **Throughput**             | Tasks completed per time step           | Higher is better |
| **Safety Violations**      | Times agents entered human safety zones | Lower is better  |
| **Agent-Agent Collisions** | Times agents hit each other             | 0 is ideal       |
| **Agent-Human Collisions** | Times agents hit humans                 | 0 is ideal       |
| **Mean Flowtime**          | Average time to complete a task         | Lower is better  |
| **Makespan**               | Time until all tasks done               | Lower is better  |
| **Planning Time**          | Time to compute plans                   | Lower is better  |

---

## 2. Before You Start (Prerequisites)

### What You Need

| Requirement      | Minimum                           | Recommended                |
|------------------|-----------------------------------|----------------------------|
| Operating System | Windows 10, macOS 10.15, or Linux | Ubuntu 20.04+ or macOS 12+ |
| Python           | 3.10                              | 3.11                       |
| RAM              | 4 GB                              | 8 GB or more               |
| Disk Space       | 500 MB                            | 1 GB                       |
| GPU              | Not required                      | Not required               |

### Check If Python Is Installed

Open a terminal (or Command Prompt on Windows) and type:

```bash
python3 --version
```

You should see something like:

```
Python 3.11.4
```

If the version is 3.10 or higher, you're good. If you get an error or see a version below 3.10, you need to install
Python.

### How to Open a Terminal

**On macOS:**

1. Press `Cmd + Space` to open Spotlight
2. Type "Terminal" and press Enter

**On Windows:**

1. Press `Win + R` to open Run dialog
2. Type "cmd" and press Enter
3. Or search for "Command Prompt" in the Start menu

**On Linux:**

1. Press `Ctrl + Alt + T`
2. Or search for "Terminal" in your applications

---

## 3. Step-by-Step Installation

### Step 3.1: Download the Project

Open your terminal and run these commands one at a time:

```bash
# Navigate to where you want to store the project
cd ~

# Download the project (replace URL with actual repository URL)
git clone <REPO_URL>

# Enter the project folder
cd ha_lmapf
```

**What this does:**

- `cd ~` moves you to your home folder
- `git clone` downloads the project
- `cd ha_lmapf` enters the project folder

### Step 3.2: Create a Virtual Environment

A virtual environment keeps this project's software separate from other projects.

```bash
# Create a virtual environment named .venv
python3 -m venv .venv
```

### Step 3.3: Activate the Virtual Environment

**On macOS/Linux:**

```bash
source .venv/bin/activate
```

**On Windows (Command Prompt):**

```cmd
.venv\Scripts\activate.bat
```

**On Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**How to know it worked:**
Your terminal prompt should now show `(.venv)` at the beginning, like:

```
(.venv) user@computer:~/ha_lmapf$
```

### Step 3.4: Upgrade pip

pip is the tool that installs Python packages. Make sure it's up to date:

```bash
pip install --upgrade pip
```

### Step 3.5: Install Required Packages

```bash
# Install the main dependencies
pip install -r requirements.txt

# Install the project itself
pip install -e .
```

### Step 3.6: Install Optional Packages (Recommended)

For visualization and plotting:

```bash
# For generating plots and figures
pip install matplotlib

# For the visual GUI (required for visualization)
pip install pygame
```

### Complete Installation Script

Here's everything in one block you can copy-paste:

```bash
cd ~
git clone <REPO_URL>
cd ha_lmapf
python3 -m venv .venv
source .venv/bin/activate  # Use .venv\Scripts\activate on Windows
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pip install matplotlib pygame pytest
```

---

## 4. Verifying Your Installation

Run these three commands to make sure everything is working:

### Test 1: Check Package Import

```bash
python3 -c "import ha_lmapf; print('SUCCESS: Package imports correctly!')"
```

**Expected output:**

```
SUCCESS: Package imports correctly!
```

### Test 2: Check Evaluation Script

```bash
python3 scripts/evaluation/run_evaluation.py --help
```

**Expected output:** A help message showing available options.

### Test 3: Run Automated Tests

```bash
pip install pytest  # Install test framework if not already installed
python3 -m pytest -v tests/
```

**Expected output:**

```
============================= test session starts ==============================
...
tests/test_allocators.py::test_greedy_assigns_nearest PASSED
tests/test_allocators.py::test_hungarian_assigns_optimally PASSED
...
============================== 359 passed in X.XXs =============================
```

**All tests should say PASSED.** If any test fails, see the [Troubleshooting](#20-common-problems-and-solutions)
section.

---

## 5. Installing Official MAPF Solvers

The HA-LMAPF framework includes Python implementations of MAPF solvers, but for best performance you can use the
official C++ implementations. This section explains how to install and use the official solvers from Keisuke Okumura's
research group.

### Available Official Solvers

| Solver     | GitHub                          | Description                                     |
|------------|---------------------------------|-------------------------------------------------|
| **LaCAM3** | https://github.com/Kei18/lacam3 | Latest LaCAM version, very fast                 |
| **LaCAM**  | https://github.com/Kei18/lacam  | Original LaCAM, fast                            |
| **PIBT2**  | https://github.com/Kei18/pibt2  | Priority Inheritance with Backtracking          |

### Solver Comparison

| Solver                 | Type        | Speed         | Path Quality | Best For                       |
|------------------------|-------------|---------------|--------------|--------------------------------|
| `cbs` (Python)         | Optimal     | Slow          | Optimal      | <20 agents, research           |
| `lacam` (Python)       | Approximate | Medium        | Good         | Quick testing                  |
| `lacam3` (C++)         | Official    | **Very Fast** | Near-optimal | **Production use, 50+ agents** |
| `lacam_official` (C++) | Official    | Very Fast     | Near-optimal | Production use                 |
| `pibt2` (C++)          | Real-time   | **Fastest**   | Good         | **Lifelong MAPF, 100+ agents** |

---

### 5.1 LaCAM3 (Recommended)

LaCAM3 (Lazy Constraints Addition for MAPF, version 3) is a **state-of-the-art MAPF solver** developed by Keisuke
Okumura. It is:

- **Fast**: Handles hundreds of agents in seconds
- **High-quality**: Produces near-optimal paths
- **Well-tested**: Used in MAPF research worldwide

GitHub Repository: https://github.com/Kei18/lacam3

### Cross-Platform Support

All solver wrappers support both **Linux/macOS** and **Windows**:

| Platform    | Binary Extension | Example                        |
|-------------|------------------|--------------------------------|
| Linux/macOS | None             | `lacam3`, `mapf_pibt2`         |
| Windows     | `.exe`           | `lacam3.exe`, `mapf_pibt2.exe` |

The wrappers automatically detect your platform and search for the appropriate binary.

### Prerequisites for Building LaCAM3

You need the following tools to compile LaCAM3:

| Tool                 | Check Command     | Install (Ubuntu)         | Install (macOS)          | Install (Windows)         |
|----------------------|-------------------|--------------------------|--------------------------|---------------------------|
| C++ Compiler (C++17) | `g++ --version`   | `sudo apt install g++`   | Xcode Command Line Tools | Visual Studio Build Tools |
| CMake (≥3.16)        | `cmake --version` | `sudo apt install cmake` | `brew install cmake`     | Download from cmake.org   |
| Git                  | `git --version`   | `sudo apt install git`   | `brew install git`       | Git for Windows           |

**Check your system:**

```bash
# All three commands should show version numbers
g++ --version    # or cl.exe on Windows
cmake --version
git --version
```

### Step 5.1: Clone the LaCAM3 Repository

```bash
# Navigate to where you want to clone (outside the HA-LMAPF project)
cd ~

# Clone with submodules (required!)
git clone --recursive https://github.com/Kei18/lacam3.git

# Enter the directory
cd lacam3
```

**Important:** The `--recursive` flag is required to download dependencies.

### Step 5.2: Build LaCAM3

**On Linux/macOS:**

```bash
# Create build directory and configure
cmake -B build

# Compile (use -j to parallelize)
make -C build -j$(nproc)
```

**On Windows (Command Prompt or PowerShell):**

```cmd
# Create build directory and configure
cmake -B build

# Compile using CMake
cmake --build build --config Release
```

**Expected output:**

```
[100%] Built target main
```

**Verify the build:**

```bash
# Linux/macOS
ls -la build/main

# Windows
dir build\Release\main.exe
```

### Step 5.3: Test LaCAM3 (Optional)

Run a quick test to make sure it works:

```bash
# Run with a sample problem
./build/main -m assets/random-32-32-20.map -i assets/random-32-32-20-random-1.scen -N 50 -v 1
```

**Expected output:**

```
solved: true
...
solution=
0:(x1,y1),(x2,y2),...
1:(x1,y1),(x2,y2),...
...
```

### Step 5.4: Install LaCAM3 in HA-LMAPF

Copy the compiled executable to the HA-LMAPF solvers folder:

**On Linux/macOS:**

```bash
# Navigate to HA-LMAPF
cd ~/ha_lmapf

# Copy the LaCAM3 executable
cp ~/lacam3/build/main src/ha_lmapf/global_tier/solvers/lacam3

# Verify it was copied
ls -la src/ha_lmapf/global_tier/solvers/lacam3
```

**On Windows:**

```cmd
# Navigate to HA-LMAPF
cd %USERPROFILE%\ha_lmapf

# Copy the LaCAM3 executable
copy %USERPROFILE%\lacam3\build\Release\main.exe src\ha_lmapf\global_tier\solvers\lacam3.exe

# Verify it was copied
dir src\ha_lmapf\global_tier\solvers\lacam3.exe
```

**Alternative (Linux/macOS): Create a symbolic link (updates automatically when you rebuild):**

```bash
ln -sf ~/lacam3/build/main src/ha_lmapf/global_tier/solvers/lacam3
```

### Step 5.5: Verify Installation

Test that HA-LMAPF can use LaCAM3:

```bash
# Activate your virtual environment if not already active
source .venv/bin/activate

# Quick test
python3 -c "
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
solver = GlobalPlannerFactory.create('lacam3')
print(f'LaCAM3 solver created: {type(solver).__name__}')
print('SUCCESS: LaCAM3 is ready to use!')
"
```

**Expected output:**

```
LaCAM3 solver created: LaCAM3Solver
SUCCESS: LaCAM3 is ready to use!
```

### Using LaCAM3 in Your Experiments

#### Option 1: In Configuration Files

Set the `global_solver` to `lacam3`:

```yaml
# In your config YAML file
global_solver: "lacam3"

# Full example
mode: "lifelong"
map_path: "data/maps/warehouse-10-20-10-2-1.map"
num_agents: 50
num_humans: 10
global_solver: "lacam3"  # Use official LaCAM3
horizon: 60
seed: 42
```

#### Option 2: In GUI Scripts

```bash
# Classical MAPF with LaCAM3
python3 scripts/run_oneshot_gui.py --agents 50 --solver lacam3

# Human-aware MAPF with LaCAM3
python3 scripts/run_oneshot_hamapf_gui.py --agents 50 --humans 10 --solver lacam3
```

#### Option 3: In Python Code

```python
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory
from ha_lmapf.global_tier.solvers import LaCAM3Solver

# Using the factory (recommended)
solver = GlobalPlannerFactory.create("lacam3")

# Or direct instantiation with custom settings
solver = LaCAM3Solver(
    binary_path="/path/to/lacam3",  # Optional if in standard location
    time_limit_sec=30.0,  # Timeout in seconds
    verbose=1,  # Debug output level (0-3)
)

# Use in planning
plan = solver.plan(env, agents, assignments, step, horizon, rng)
```

### Solver Name Aliases

All these names work the same:

| Name         | Description                    |
|--------------|--------------------------------|
| `lacam3`     | Official LaCAM3 C++ executable |
| `lacam3_cpp` | Same as `lacam3`               |
| `lacam_cpp`  | Same as `lacam3`               |

### LaCAM3 Configuration Options

The wrapper supports these options:

| Parameter        | Default     | Description                                         |
|------------------|-------------|-----------------------------------------------------|
| `binary_path`    | Auto-detect | Path to LaCAM3 executable                           |
| `time_limit_sec` | 30.0        | Timeout in seconds                                  |
| `verbose`        | 0           | Debug level (0=silent, 1=basic, 2=detailed, 3=full) |

### Troubleshooting LaCAM3

#### Problem: "Binary not found"

**Cause:** The executable isn't in the expected location.

**Solutions:**

```bash
# Check if the executable exists
ls -la src/ha_lmapf/global_tier/solvers/lacam3

# If missing, copy it again
cp ~/lacam3/build/main src/ha_lmapf/global_tier/solvers/lacam3

# Make sure it's executable
chmod +x src/ha_lmapf/global_tier/solvers/lacam3
```

#### Problem: "cmake not found" or "make not found"

**Cause:** Build tools not installed.

**Solution:**

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install cmake build-essential

# macOS (install Homebrew first if needed)
brew install cmake

# Fedora/RHEL
sudo dnf install cmake gcc-c++ make
```

#### Problem: "fatal error: filesystem" or C++17 errors

**Cause:** Old compiler that doesn't support C++17.

**Solution:**

```bash
# Check your g++ version (need 7+ for C++17)
g++ --version

# Ubuntu: install a newer version
sudo apt install g++-9
export CXX=g++-9
cmake -B build
make -C build
```

#### Problem: LaCAM3 times out on large problems

**Cause:** Too many agents or complex map.

**Solutions:**

1. Increase time limit:

```python
solver = LaCAM3Solver(time_limit_sec=60.0)  # 60 seconds instead of 30
```

2. Reduce planning horizon:

```yaml
horizon: 30  # instead of 60
```

3. Use a smaller map or fewer agents for testing

#### Problem: "Permission denied" when running

**Cause:** Executable doesn't have execute permissions.

**Solution:**

```bash
chmod +x src/ha_lmapf/global_tier/solvers/lacam3
```

### Performance Tips

1. **For 50+ agents**: Always use `lacam3` instead of Python solvers
2. **Large warehouses**: Consider reducing the planning horizon
3. **Fast iteration**: Use symbolic links so rebuilds auto-update
4. **Debugging**: Set `verbose=1` or `verbose=2` to see solver output

### Keeping LaCAM3 Updated

To update to the latest version:

```bash
cd ~/lacam3
git pull origin main
cmake -B build
make -C build -j$(nproc)
# The symbolic link will automatically use the new version
```

---

### 5.2 LaCAM (Original)

LaCAM (Lazy Constraints Addition for MAPF) is the original version of the LaCAM algorithm. While LaCAM3 is recommended
for most use cases, the original LaCAM may be preferred for certain benchmarks.

GitHub Repository: https://github.com/Kei18/lacam

#### Building LaCAM

**On Linux/macOS:**

```bash
# Clone the repository
cd ~
git clone --recursive https://github.com/Kei18/lacam.git
cd lacam

# Build
cmake -B build && make -C build -j$(nproc)
```

**On Windows:**

```cmd
# Clone the repository
cd %USERPROFILE%
git clone --recursive https://github.com/Kei18/lacam.git
cd lacam

# Build
cmake -B build
cmake --build build --config Release
```

#### Installing LaCAM in HA-LMAPF

**On Linux/macOS:**

```bash
# Copy to solvers folder
cd ~/ha_lmapf
cp ~/lacam/build/main src/ha_lmapf/global_tier/solvers/lacam_official

# Or create a symbolic link
ln -sf ~/lacam/build/main src/ha_lmapf/global_tier/solvers/lacam_official
```

**On Windows:**

```cmd
# Copy to solvers folder
cd %USERPROFILE%\ha_lmapf
copy %USERPROFILE%\lacam\build\Release\main.exe src\ha_lmapf\global_tier\solvers\lacam_official.exe
```

#### Using LaCAM

```bash
# In GUI scripts
python3 scripts/run_oneshot_gui.py --agents 50 --solver lacam_official

# In config files
global_solver: "lacam_official"
```

```python
# In Python code
from ha_lmapf.global_tier.planner_interface import GlobalPlannerFactory

solver = GlobalPlannerFactory.create("lacam_official")
```

---

### 5.3 PIBT2 (Priority Inheritance with Backtracking)

PIBT2 is a fast real-time MAPF solver optimized for iterative and lifelong scenarios. It excels at:

- **Real-time planning**: Extremely fast computation
- **Lifelong MAPF**: Designed for continuous task streams
- **Large scale**: Handles 100+ agents efficiently

GitHub Repository: https://github.com/Kei18/pibt2

**PIBT2 provides two executables:**

| Executable | Use Case                | Description                              |
|------------|-------------------------|------------------------------------------|
| `mapf`     | One-shot/Classical MAPF | Each agent has one goal                  |
| `mapd`     | Lifelong MAPF / MAPD    | Continuous task streams, pickup-delivery |

#### Building PIBT2

**On Linux/macOS:**

```bash
# Clone the repository
cd ~
git clone --recursive https://github.com/Kei18/pibt2.git
cd pibt2

# Build (creates both mapf and mapd executables)
mkdir build && cd build
cmake .. && make -j$(nproc)

# Verify both executables were created
ls -la mapf mapd
```

**On Windows:**

```cmd
# Clone the repository
cd %USERPROFILE%
git clone --recursive https://github.com/Kei18/pibt2.git
cd pibt2

# Build (creates both mapf and mapd executables)
mkdir build && cd build
cmake ..
cmake --build . --config Release

# Verify both executables were created
dir Release\mapf.exe Release\mapd.exe
```

#### Installing PIBT2 in HA-LMAPF

Copy **both** executables for full functionality:

**On Linux/macOS:**

```bash
# Navigate to HA-LMAPF
cd ~/ha_lmapf

# Copy the MAPF executable (for one-shot experiments)
cp ~/pibt2/build/mapf src/ha_lmapf/global_tier/solvers/mapf_pibt2

# Copy the MAPD executable (for lifelong experiments)
cp ~/pibt2/build/mapd src/ha_lmapf/global_tier/solvers/mapd_pibt2

# Verify both were copied
ls -la src/ha_lmapf/global_tier/solvers/*pibt2*
```

**On Windows:**

```cmd
# Navigate to HA-LMAPF
cd %USERPROFILE%\ha_lmapf

# Copy the MAPF executable (for one-shot experiments)
copy %USERPROFILE%\pibt2\build\Release\mapf.exe src\ha_lmapf\global_tier\solvers\mapf_pibt2.exe

# Copy the MAPD executable (for lifelong experiments)
copy %USERPROFILE%\pibt2\build\Release\mapd.exe src\ha_lmapf\global_tier\solvers\mapd_pibt2.exe

# Verify both were copied
dir src\ha_lmapf\global_tier\solvers\*pibt2*
```

**Alternative (Linux/macOS): Create symbolic links:**

```bash
ln -sf ~/pibt2/build/mapf src/ha_lmapf/global_tier/solvers/mapf_pibt2
ln -sf ~/pibt2/build/mapd src/ha_lmapf/global_tier/solvers/mapd_pibt2
```

#### Using PIBT2

The wrapper automatically selects the correct executable based on the experiment mode:

```bash
# For one-shot MAPF (uses mapf_pibt2)
python3 scripts/run_oneshot_gui.py --agents 100 --solver pibt2

# For lifelong MAPF (uses mapd_pibt2 via config)
python3 scripts/run_gui.py --config configs/eval/solver_pibt2.yaml
```

**In config files:**

```yaml
global_solver: "pibt2"
mode: "one_shot"   # Uses mapf_pibt2
# OR
mode: "lifelong"   # Uses mapd_pibt2
```

**In Python code with explicit mode:**

```python
from ha_lmapf.global_tier.solvers import PIBT2Solver

# For one-shot MAPF
solver = PIBT2Solver(mode="one_shot")  # Uses mapf_pibt2

# For lifelong MAPF
solver = PIBT2Solver(mode="lifelong")  # Uses mapd_pibt2

# Auto-detect mode (default)
solver = PIBT2Solver(mode="auto")

# Or specify paths explicitly
solver = PIBT2Solver(
    mapf_binary_path="/path/to/mapf_pibt2",
    mapd_binary_path="/path/to/mapd_pibt2",
)
```

#### PIBT2 Solver Variants

PIBT2 includes multiple solver algorithms:

| Solver Name | Description                                      |
|-------------|--------------------------------------------------|
| `PIBT`      | Priority Inheritance with Backtracking (default) |
| `HCA`       | Hierarchical Cooperative A*                      |
| `WHCA`      | Windowed Hierarchical Cooperative A*             |

---

### 5.4 Solver Name Reference

All available solver names and their aliases:

| Name             | Aliases                                | Description          |
|------------------|----------------------------------------|----------------------|
| `cbs`            | `conflict_based_search`                | Python CBS (optimal) |
| `lacam`          | `lacam_like`, `prioritized`, `pylacam` | Python LaCAM-like    |
| `lacam3`         | `lacam3_cpp`                           | Official LaCAM3 C++  |
| `lacam_official` | `lacam_cpp`                            | Official LaCAM C++   |
| `pibt2`          | `pibt2_cpp`, `pibt_cpp`, `pibt`        | Official PIBT2 C++   |

---

## 6. Your First Experiment

Let's run a simple experiment to make sure everything works.

### Option A: Run a Lifelong MAPF Experiment

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group baselines \
    --seeds 0 \
    --out logs/my_first_experiment
```

**What this does:**

- Runs the baseline comparison experiment
- Uses seed 0 for reproducibility
- Saves results to `logs/my_first_experiment`

### Option B: Run a Classical MAPF Experiment

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group classic_mapf \
    --seeds 0 \
    --out logs/my_first_classic_mapf
```

**What this does:**

- Runs one-shot classical MAPF experiments
- Each agent gets one goal, simulation ends when all reach goals

### Watch the Output

You should see output like:

```
HA-LMAPF Evaluation
  Output:     logs/my_first_experiment
  Seeds:      [0]
  Group:      baselines

============================================================
Experiment: warehouse_baselines
============================================================
  [ours] seed=0 agents=15 humans=5 ... done (39.5s) tput=0.1820 sv=100 plan_ms=176.9 done=182
  [global_only] seed=0 agents=15 humans=5 ... done (30.9s) tput=0.0210 sv=296 plan_ms=427.6 done=21
  ...

Results written to logs/my_first_experiment/baselines/results.csv
```

**Congratulations! You just ran your first MAPF experiment!**

---

## 7. Understanding the Output

### The results.csv File

This file contains all measurements from your experiment. Open it in Excel, Google Sheets, or any text editor.

**Key columns explained:**

| Column                   | What It Means                         | Good Values      |
|--------------------------|---------------------------------------|------------------|
| `throughput`             | Tasks completed per time step         | Higher is better |
| `completed_tasks`        | Total tasks finished                  | Higher is better |
| `collisions_agent_agent` | Times agents hit each other           | 0 is ideal       |
| `collisions_agent_human` | Times agents hit humans               | 0 is ideal       |
| `safety_violations`      | Times agents entered unsafe zones     | Lower is better  |
| `mean_flowtime`          | Average time to complete a task       | Lower is better  |
| `makespan`               | Time until all tasks done             | Lower is better  |
| `mean_planning_time_ms`  | Average planning time in milliseconds | Lower is better  |

### Understanding the Baselines

| Baseline        | Description                                    |
|-----------------|------------------------------------------------|
| `ours`          | Our two-tier human-aware approach              |
| `global_only`   | Only global planning, no local human avoidance |
| `pibt_only`     | Priority-based local planning only             |
| `rhcr`          | Rolling Horizon Collision Resolution           |
| `whca_star`     | Windowed Hierarchical Cooperative A*           |
| `ignore_humans` | Our approach but ignoring humans               |

---

## 8. Running All Paper Experiments

To reproduce all experiments from the research paper:

### Full Evaluation (All Groups)

```bash
python3 scripts/evaluation/run_evaluation.py --out logs/paper_experiments
```

**Warning:** This runs many experiments and may take several hours.

### What Gets Run

The evaluation includes **11 experiment groups**:

| Group              | Description                   | Experiments       |
|--------------------|-------------------------------|-------------------|
| `baselines`        | Compare our method to others  | 6 baselines       |
| `scalability`      | Test with 10-500 agents       | 7 configurations  |
| `human_density`    | Test with 0-20 humans         | 4 configurations  |
| `human_models`     | Different human behaviors     | 4 models          |
| `map_types`        | Different warehouse layouts   | 5 maps            |
| `ablations`        | Test with components disabled | 10 configurations |
| `delay_robustness` | Test with execution delays    | 4 delay rates     |
| `arrival_rate`     | Test task arrival speeds      | 4 rates           |
| `robustness`       | Test difficult scenarios      | 3 scenarios       |
| `no_humans`        | Compare without humans        | 9 configurations  |
| `classic_mapf`     | One-shot classical MAPF       | 14 configurations |

### Running with Multiple Seeds (for Statistical Significance)

```bash
python3 scripts/evaluation/run_evaluation.py \
    --seeds 0 1 2 3 4 \
    --out logs/paper_experiments
```

This runs each experiment 5 times with different random seeds for reliable results.

---

## 9. Running Individual Experiment Groups

### Baselines Comparison

Compare our method against other approaches:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group baselines \
    --seeds 0 1 2 3 4 \
    --out logs/baselines_experiment
```

### Scalability Test

See how performance changes with more agents:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group scalability \
    --seeds 0 1 2 \
    --out logs/scalability_experiment
```

**Tests:** 10, 25, 50, 100, 200, 300, 500 agents

### Human Density Test

See how performance changes with more humans:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group human_density \
    --seeds 0 1 2 \
    --out logs/human_density_experiment
```

**Tests:** 0, 5, 10, 20 humans

### Human Behavior Models

Test different human movement patterns:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group human_models \
    --seeds 0 1 2 \
    --out logs/human_models_experiment
```

**Models tested:**

- `random_walk` - Humans move randomly
- `aisle` - Humans follow aisles
- `adversarial` - Humans intentionally block agents
- `mixed` - Combination of behaviors

### Different Map Types

Test on various warehouse layouts:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group map_types \
    --seeds 0 1 2 \
    --out logs/map_types_experiment
```

**Maps tested:** warehouse, random obstacles, rooms, mazes, empty

### Ablation Studies

Test what happens when we disable components:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group ablations \
    --seeds 0 1 2 \
    --out logs/ablations_experiment
```

**Tests:** disable safety, disable local replanning, disable conflict resolution, different solvers, different
allocators

### Execution Delay Robustness

Test with unreliable agent execution:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group delay_robustness \
    --seeds 0 1 2 \
    --out logs/delay_experiment
```

**Delay rates tested:** 0%, 5%, 10%, 20%

### Task Arrival Rate

Test with different task frequencies:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group arrival_rate \
    --seeds 0 1 2 \
    --out logs/arrival_rate_experiment
```

### Robustness Tests

Test in challenging scenarios:

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group robustness \
    --seeds 0 1 2 \
    --out logs/robustness_experiment
```

**Scenarios:** narrow corridors, dense maps, adversarial humans

---

## 10. Classical MAPF Experiments (One-Shot)

Classical MAPF is when each agent has exactly **one goal** and the simulation ends when all agents reach their goals.

### Run All Classical MAPF Experiments

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group classic_mapf \
    --seeds 0 1 2 \
    --out logs/classic_mapf_results
```

### What Gets Tested

| Experiment                    | Description                                                |
|-------------------------------|------------------------------------------------------------|
| `oneshot_cbs_no_humans`       | Classical MAPF with CBS solver, no humans                  |
| `oneshot_lacam_no_humans`     | Classical MAPF with LaCAM solver, no humans                |
| `oneshot_cbs_with_humans`     | Human-aware classical MAPF with CBS                        |
| `oneshot_lacam_with_humans`   | Human-aware classical MAPF with LaCAM                      |
| `oneshot_scale_5/10/20/30/50` | Scalability tests with different agent counts              |
| `oneshot_map_*`               | Different map types (warehouse, random, room, maze, empty) |

### When to Use Classical MAPF

Use classical MAPF when:

- Comparing to traditional MAPF algorithms
- Testing path planning without continuous task streams
- Evaluating makespan and sum-of-costs metrics

---

## 11. Experiments Without Humans

To compare human-aware performance vs. agent-only performance:

### Run All No-Human Experiments

```bash
python3 scripts/evaluation/run_evaluation.py \
    --group no_humans \
    --seeds 0 1 2 \
    --out logs/no_humans_results
```

### What Gets Tested

| Experiment                     | Description                                 |
|--------------------------------|---------------------------------------------|
| `warehouse_no_humans`          | All 6 baselines on warehouse without humans |
| `scale_no_humans_10/25/50/100` | Scalability tests without humans            |
| `map_*_no_humans`              | Different maps without humans               |

### Why Run These?

Running experiments without humans helps you:

- Understand the **overhead** of human-awareness
- Compare **pure MAPF performance** vs human-aware performance
- Establish **upper bounds** on throughput

---

## 12. GUI Visualization Scripts

This project provides **three GUI scripts** for visualizing different types of MAPF experiments:

| Script                      | Purpose                         | Best For                           |
|-----------------------------|---------------------------------|------------------------------------|
| `run_gui.py`                | Lifelong MAPF with config files | Full experiments with all settings |
| `run_oneshot_gui.py`        | Classical one-shot MAPF         | Quick testing without humans       |
| `run_oneshot_hamapf_gui.py` | Human-aware one-shot MAPF       | Demonstrating human avoidance      |

### Common GUI Controls (All Scripts)

| Key     | Action                                                     |
|---------|------------------------------------------------------------|
| `SPACE` | Pause/Resume simulation                                    |
| `N`     | Step forward one time step (when paused)                   |
| `A`     | Toggle auto-stepping mode                                  |
| `P`     | Show/hide global planned paths (blue lines)                |
| `L`     | Show/hide local paths (green lines - human avoidance)      |
| `F`     | Show/hide agent field of view circles                      |
| `B`     | Show/hide forbidden safety zones (red areas around humans) |
| `ESC`   | Quit the simulation                                        |

### Visual Elements

| Element      | Color        | Description                      |
|--------------|--------------|----------------------------------|
| Agents       | Blue circles | The autonomous agents            |
| Humans       | Red circles  | Dynamic obstacles                |
| Walls        | Black cells  | Static obstacles                 |
| Global paths | Blue lines   | Pre-planned collision-free paths |
| Local paths  | Green lines  | Reactive detours around humans   |
| FOV          | Shaded areas | What agents can currently see    |
| Safety zones | Red shaded   | Forbidden areas around humans    |

---

## 13. Lifelong MAPF GUI (run_gui.py)

Use this script for **lifelong MAPF** experiments where agents continuously receive new tasks.

### Basic Usage

```bash
python3 scripts/run_gui.py --config configs/warehouse_small.yaml
```

### Configuration Options

| Option     | Description                                | Example                        |
|------------|--------------------------------------------|--------------------------------|
| `--config` | Path to YAML configuration file (required) | `configs/warehouse_small.yaml` |
| `--seed`   | Override the random seed                   | `--seed 123`                   |

### Example Commands

```bash
# Small warehouse experiment
python3 scripts/run_gui.py --config configs/warehouse_small.yaml

# Large warehouse with specific seed
python3 scripts/run_gui.py --config configs/warehouse_large.yaml --seed 42

# One-shot mode via config
python3 scripts/run_gui.py --config configs/one_shot_mapf.yaml

# Adversarial humans
python3 scripts/run_gui.py --config configs/human_adversarial.yaml

# Mixed human behaviors
python3 scripts/run_gui.py --config configs/human_mixed.yaml
```

### Available Configuration Files

| Config File                              | Description                        |
|------------------------------------------|------------------------------------|
| `configs/warehouse_small.yaml`           | Small warehouse, quick experiments |
| `configs/warehouse_large.yaml`           | Large warehouse, production-like   |
| `configs/one_shot_mapf.yaml`             | Classical MAPF, no humans          |
| `configs/one_shot_mapf_with_humans.yaml` | Classical MAPF with humans         |
| `configs/human_adversarial.yaml`         | Humans that try to block agents    |
| `configs/human_aisle_boltzmann.yaml`     | Humans following aisles            |
| `configs/human_mixed.yaml`               | Mix of human behaviors             |
| `configs/random_20x20.yaml`              | Small random map                   |

---

## 14. Classical MAPF GUI (run_oneshot_gui.py)

Use this script for **classical one-shot MAPF** where each agent has exactly one goal and the simulation ends when all
agents reach their goals.

### Basic Usage

```bash
# Default: 10 agents, no humans
python3 scripts/run_oneshot_gui.py
```

### Configuration Options

| Option     | Short | Description                     | Default                         |
|------------|-------|---------------------------------|---------------------------------|
| `--agents` | `-a`  | Number of agents                | 10                              |
| `--humans` | `-H`  | Number of humans                | 0                               |
| `--map`    | `-m`  | Path to map file                | `data/maps/random-32-32-20.map` |
| `--solver` | `-s`  | MAPF solver (`cbs` or `lacam`)  | `cbs`                           |
| `--seed`   |       | Random seed for reproducibility | 42                              |
| `--steps`  |       | Maximum simulation steps        | 500                             |

### Example Commands

```bash
# Basic classical MAPF
python3 scripts/run_oneshot_gui.py

# More agents
python3 scripts/run_oneshot_gui.py --agents 20

# With humans (human-aware)
python3 scripts/run_oneshot_gui.py --agents 10 -H 5

# Different map
python3 scripts/run_oneshot_gui.py --map data/maps/warehouse-10-20-10-2-1.map

# LaCAM solver (faster for many agents)
python3 scripts/run_oneshot_gui.py --agents 30 --solver lacam

# Maze map with fewer agents
python3 scripts/run_oneshot_gui.py --map data/maps/maze-32-32-4.map --agents 8

# Custom seed for reproducibility
python3 scripts/run_oneshot_gui.py --seed 123
```

### Solver Comparison

```bash
# CBS: Optimal paths, slower computation
python3 scripts/run_oneshot_gui.py --agents 15 --solver cbs

# LaCAM: Fast computation, good quality paths
python3 scripts/run_oneshot_gui.py --agents 15 --solver lacam
```

| Solver  | Speed | Path Quality | Best For             |
|---------|-------|--------------|----------------------|
| `cbs`   | Slow  | Optimal      | <20 agents, research |
| `lacam` | Fast  | Good         | 20+ agents, demos    |

---

## 15. Human-Aware MAPF GUI (run_oneshot_hamapf_gui.py)

Use this script to **demonstrate the proposed two-tier human-aware approach** for classical MAPF. This is the best
script for showing how agents safely navigate around humans.

### Basic Usage

```bash
# Default: 10 agents, 5 humans
python3 scripts/run_oneshot_hamapf_gui.py
```

### Configuration Options

| Option             | Short | Description                               | Default                         |
|--------------------|-------|-------------------------------------------|---------------------------------|
| `--agents`         | `-a`  | Number of agents                          | 10                              |
| `--humans`         | `-H`  | Number of humans                          | 5                               |
| `--map`            | `-m`  | Path to map file                          | `data/maps/random-32-32-20.map` |
| `--fov`            |       | Field of view radius (cells)              | 5                               |
| `--safety`         |       | Safety radius around humans (cells)       | 1                               |
| `--hard-safety`    |       | Agents NEVER enter safety zones           | True (default)                  |
| `--no-hard-safety` |       | Agents avoid but can enter if needed      |                                 |
| `--solver`         | `-s`  | MAPF solver (`cbs` or `lacam`)            | `cbs`                           |
| `--horizon`        |       | Planning horizon (auto-scaled if not set) | Auto                            |
| `--human-model`    |       | Human behavior model                      | `random_walk`                   |
| `--comm-mode`      |       | Conflict resolution mode                  | `token`                         |
| `--seed`           |       | Random seed                               | 42                              |
| `--steps`          |       | Maximum simulation steps                  | 500                             |

### Human Behavior Models

| Model         | Description                         | Use Case              |
|---------------|-------------------------------------|-----------------------|
| `random_walk` | Humans move randomly with inertia   | General testing       |
| `aisle`       | Humans follow warehouse aisles      | Realistic warehouse   |
| `adversarial` | Humans actively try to block agents | Stress testing        |
| `mixed`       | Combination of all behaviors        | Real-world simulation |

### Example Commands

```bash
# Basic human-aware MAPF
python3 scripts/run_oneshot_hamapf_gui.py

# More agents and humans
python3 scripts/run_oneshot_hamapf_gui.py --agents 20 --humans 10

# Custom field of view (limited visibility)
python3 scripts/run_oneshot_hamapf_gui.py --fov 3

# Larger safety buffer around humans
python3 scripts/run_oneshot_hamapf_gui.py --safety 2

# Adversarial humans (challenging scenario)
python3 scripts/run_oneshot_hamapf_gui.py --human-model adversarial --humans 10

# Mixed human behaviors
python3 scripts/run_oneshot_hamapf_gui.py --human-model mixed --humans 15

# Warehouse map with LaCAM
python3 scripts/run_oneshot_hamapf_gui.py \
    --map data/maps/warehouse-10-20-10-2-1.map \
    --solver lacam \
    --agents 15 \
    --humans 8

# Soft safety (agents can enter safety zones if necessary)
python3 scripts/run_oneshot_hamapf_gui.py --no-hard-safety

# Priority-based conflict resolution (no communication)
python3 scripts/run_oneshot_hamapf_gui.py --comm-mode priority
```

### Demonstration Scenarios

#### Scenario 1: Basic Human Avoidance

```bash
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 5
```

Shows agents navigating around randomly moving humans.

#### Scenario 2: High Human Density

```bash
python3 scripts/run_oneshot_hamapf_gui.py --agents 15 --humans 20
```

Shows how the system handles many dynamic obstacles.

#### Scenario 3: Limited Visibility (Partial Observability)

```bash
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 8 --fov 3
```

Agents can only see 3 cells around them, requiring more reactive behavior.

#### Scenario 4: Adversarial Humans

```bash
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 10 --human-model adversarial
```

Humans actively try to block agents - tests robustness.

#### Scenario 5: Large Safety Buffer

```bash
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 5 --safety 3
```

Agents maintain 3-cell distance from humans.

#### Scenario 6: Warehouse Environment

```bash
python3 scripts/run_oneshot_hamapf_gui.py \
    --map data/maps/warehouse-10-20-10-2-1.map \
    --agents 20 \
    --humans 10 \
    --solver lacam \
    --human-model aisle
```

Realistic warehouse with humans following aisles.

### Understanding the Output

After the simulation completes, you'll see statistics:

```
======================================================================
 FINAL STATISTICS
======================================================================
  Total Steps:             156
  Agents Completed:        10/10
  Throughput:              0.0641
  Agent-Agent Collisions:  0
  Agent-Human Collisions:  0
  Safety Violations:       12
  Near Misses:             45
  Mean Planning Time:      89.3ms
  Local Replans:           23
======================================================================
```

| Metric                 | Good Value | Meaning                           |
|------------------------|------------|-----------------------------------|
| Agent-Agent Collisions | 0          | Agents never hit each other       |
| Agent-Human Collisions | 0          | Agents never hit humans           |
| Safety Violations      | Low        | Times agents entered safety zones |
| Local Replans          | Varies     | Human avoidance detours taken     |

---

## 16. Creating Your Own Configuration

### Step-by-Step Guide

#### Step 1: Choose a Base Configuration

Start by copying an existing configuration file:

```bash
# For lifelong MAPF experiments
cp configs/warehouse_small.yaml configs/my_experiment.yaml

# For one-shot MAPF experiments
cp configs/one_shot_mapf.yaml configs/my_oneshot.yaml
```

#### Step 2: Open the File in a Text Editor

```bash
# On Linux/macOS
nano configs/my_experiment.yaml

# Or use any text editor (VS Code, Notepad, etc.)
```

#### Step 3: Modify the Settings

Here's a complete configuration file with all options explained:

```yaml
# ============================================================
# SIMULATION MODE
# ============================================================
# "lifelong" - Agents continuously receive new tasks
# "one_shot" - Each agent gets one goal, ends when all reach goals
mode: "lifelong"

# ============================================================
# MAP CONFIGURATION
# ============================================================
# Path to the map file (.map format)
map_path: "data/maps/warehouse-10-20-10-2-1.map"

# Available maps:
#   data/maps/warehouse-10-20-10-2-1.map  - Standard warehouse
#   data/maps/warehouse-20-40-10-2-1.map  - Large warehouse
#   data/maps/random-32-32-20.map         - Random obstacles
#   data/maps/room-32-32-4.map            - Room layout
#   data/maps/maze-32-32-4.map            - Maze layout
#   data/maps/empty-32-32.map             - Empty space

# ============================================================
# POPULATION
# ============================================================
num_agents: 20    # Number of agents (1-500)
num_humans: 5     # Number of human workers (0-50)

# ============================================================
# SIMULATION LENGTH
# ============================================================
steps: 2000       # Maximum time steps to run

# ============================================================
# TASK CONFIGURATION (for lifelong mode)
# ============================================================
# How often new tasks arrive (every N steps)
# Lower = more frequent tasks = higher workload
task_arrival_rate: 10

# Pre-generated task stream (null = auto-generate)
task_stream_path: null

# ============================================================
# PERCEPTION
# ============================================================
# How far agents can see (in cells)
fov_radius: 5

# ============================================================
# SAFETY
# ============================================================
# Safety buffer distance around humans (in cells)
safety_radius: 1

# If true, agents NEVER enter safety zones (may wait forever)
# If false, agents try to avoid but can enter if necessary
hard_safety: true

# ============================================================
# GLOBAL PLANNER (Tier 1)
# ============================================================
# Solver algorithm:
#   "cbs"   - Conflict-Based Search (optimal, slow)
#   "lacam" - LaCAM (fast, approximate)
global_solver: "lacam"

# How far ahead to plan (time steps)
horizon: 50

# How often to recompute global plans (time steps)
replan_every: 25

# ============================================================
# LOCAL EXECUTION (Tier 2)
# ============================================================
# Communication mode:
#   "token"    - Agents communicate to coordinate
#   "priority" - No communication, use priority rules
communication_mode: "token"

# Local path planning algorithm
local_planner: "astar"

# ============================================================
# TASK ALLOCATION
# ============================================================
# How to assign tasks to agents:
#   "greedy"    - Assign nearest available task
#   "hungarian" - Optimal assignment (slower)
#   "auction"   - Auction-based assignment
task_allocator: "congestion_avoidance"

# ============================================================
# HUMAN BEHAVIOR
# ============================================================
# How humans move in the simulation:
#   "random_walk"  - Random movement with inertia
#   "aisle"        - Follow warehouse aisles
#   "adversarial"  - Try to block agents
#   "mixed"        - Combination of behaviors
#   "replay"       - Replay recorded trajectories
human_model: "random_walk"

# Optional: Parameters for the human model
# human_model_params:
#   beta_go: 2.0      # For random_walk
#   beta_wait: -1.0
#   alpha: 1.0        # For aisle
#   beta: 1.5
#   gamma: 2.0        # For adversarial
#   lambda: 0.5

# ============================================================
# REPRODUCIBILITY
# ============================================================
# Random seed (same seed = same results)
seed: 42

# ============================================================
# ADVANCED OPTIONS
# ============================================================
# Execution delay (simulates agent malfunctions)
# execution_delay_prob: 0.0    # Probability of delay (0-1)
# execution_delay_steps: 2     # Duration of delay

# Disable features (for ablation studies)
# disable_local_replan: false
# disable_conflict_resolution: false
# disable_safety: false
```

#### Step 4: Save and Run

```bash
# Run your custom configuration
python3 scripts/run_gui.py --config configs/my_experiment.yaml

# Or run as evaluation
python3 scripts/evaluation/run_evaluation.py \
    --config configs/my_experiment.yaml \
    --seeds 0 1 2 \
    --out logs/my_custom_experiment
```

### Quick Configuration Examples

#### Example 1: Large Warehouse with Many Agents

```yaml
mode: "lifelong"
map_path: "data/maps/warehouse-20-40-10-2-1.map"
num_agents: 100
num_humans: 20
steps: 3000
global_solver: "lacam"
horizon: 60
replan_every: 30
task_arrival_rate: 5
seed: 42
```

#### Example 2: Classical MAPF (No Humans)

```yaml
mode: "one_shot"
map_path: "data/maps/random-32-32-20.map"
num_agents: 20
num_humans: 0
steps: 500
global_solver: "cbs"
horizon: 200
seed: 42
```

#### Example 3: Adversarial Humans

```yaml
mode: "lifelong"
map_path: "data/maps/warehouse-10-20-10-2-1.map"
num_agents: 15
num_humans: 10
human_model: "adversarial"
human_model_params:
  gamma: 2.0
  lambda: 0.5
hard_safety: true
seed: 42
```

#### Example 4: High Task Frequency

```yaml
mode: "lifelong"
map_path: "data/maps/warehouse-10-20-10-2-1.map"
num_agents: 25
num_humans: 5
task_arrival_rate: 3  # New task every 3 steps
steps: 2000
seed: 42
```

---

## 17. Generating Figures and Tables

After running experiments, create publication-ready figures:

### Generate All Plots

```bash
python3 scripts/evaluation/plot_results.py \
    --results logs/paper_experiments \
    --out figures
```

### What You Get

The `figures/` folder will contain:

- **PNG files** - Images for presentations
- **PDF files** - High-quality figures for papers
- **LaTeX tables** - Ready to paste into your paper
- **summary.txt** - Text summary of key results

### View the Figures

```bash
# List all generated figures
ls figures/

# On macOS, open a figure
open figures/scalability.png

# On Linux with GUI
xdg-open figures/scalability.png

# On Windows
start figures\scalability.png
```

---

## 18. Running Tests

### Why Run Tests?

Tests verify that the code is working correctly. Always run tests:

- After installation
- Before running important experiments
- After making any code changes

### Run All Tests

```bash
python3 -m pytest -v tests/
```

### Run Specific Test Categories

**Map loading tests:**

```bash
python3 -m pytest -v tests/test_map_loading.py
```

**Task allocation tests:**

```bash
python3 -m pytest -v tests/test_allocators.py
```

**Planning tests:**

```bash
python3 -m pytest -v tests/test_one_shot_mapf.py tests/test_receding_horizon_handoff.py
```

**Safety tests:**

```bash
python3 -m pytest -v tests/test_local_safety.py tests/test_token_passing.py
```

### Understanding Test Results

**All passed:**

```
============================== 359 passed in X.XXs =============================
```

Everything is working correctly.

**Some failed:**

```
============================== 2 failed, 15 passed ==============================
```

Some tests failed. See [Troubleshooting](#20-common-problems-and-solutions).

---

## 19. Configuration Files Explained

### Available Configuration Files

```
configs/
├── warehouse_small.yaml           # Small warehouse (quick experiments)
├── warehouse_large.yaml           # Large warehouse (production-like)
├── one_shot_mapf.yaml            # Classical MAPF without humans
├── one_shot_mapf_with_humans.yaml # Classical MAPF with humans
├── random_20x20.yaml              # Small random map
├── human_adversarial.yaml         # Aggressive human behavior
├── human_aisle_boltzmann.yaml     # Humans following aisles
├── human_mixed.yaml               # Mixed human behaviors
├── ablation_no_humans.yaml        # Ablation: no humans
├── ablation_no_comms.yaml         # Ablation: no communication
├── solver_cbs_vs_lacam.yaml       # Compare CBS and LaCAM
└── eval/                          # Paper evaluation configs
    ├── scalability_*.yaml
    ├── human_density_*.yaml
    ├── human_model_*.yaml
    └── ...
```

### Human Model Options

| Model         | Description                    | When to Use            |
|---------------|--------------------------------|------------------------|
| `random_walk` | Humans move randomly           | General testing        |
| `aisle`       | Humans follow warehouse aisles | Realistic warehouse    |
| `adversarial` | Humans try to block agents     | Stress testing         |
| `mixed`       | Combination of behaviors       | Real-world simulation  |
| `replay`      | Replay recorded movements      | Reproducible scenarios |

### Global Solver Options

| Solver  | Speed | Quality | Best For               |
|---------|-------|---------|------------------------|
| `cbs`   | Slow  | Optimal | <30 agents, research   |
| `lacam` | Fast  | Good    | 30+ agents, production |

### Task Allocator Options

| Allocator   | Speed  | Quality | Best For            |
|-------------|--------|---------|---------------------|
| `greedy`    | Fast   | Good    | Large scale         |
| `hungarian` | Medium | Optimal | Research            |
| `auction`   | Medium | Good    | Distributed systems |

---

## 20. Common Problems and Solutions

### Problem: "ModuleNotFoundError: No module named 'ha_lmapf'"

**Cause:** Package not installed or virtual environment not activated.

**Solution:**

```bash
# Make sure you're in the project directory
cd ~/ha_lmapf

# Activate the virtual environment
source .venv/bin/activate  # Linux/macOS
# OR
.venv\Scripts\activate  # Windows

# Reinstall the package
pip install -e .
```

### Problem: "FileNotFoundError: [Errno 2] No such file or directory"

**Cause:** Wrong working directory or missing files.

**Solution:**

```bash
# Make sure you're in the project root
cd ~/ha_lmapf

# Check that the file exists
ls configs/warehouse_small.yaml
ls data/maps/
```

### Problem: Tests fail with import errors

**Cause:** Dependencies not installed correctly.

**Solution:**

```bash
# Reinstall all dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pip install pytest

# Run tests again
python3 -m pytest -v tests/
```

### Problem: "pygame.error: No available video device"

**Cause:** Running on a server without a display.

**Solution:** You can't use the GUI on a headless server. Use the command-line experiment scripts instead:

```bash
python3 scripts/evaluation/run_evaluation.py --group baselines --seeds 0 --out logs/results
```

### Problem: Experiments run very slowly

**Possible causes and solutions:**

1. **Too many agents:** Reduce `num_agents` in the config
2. **Too many steps:** Reduce `steps` in the config
3. **Slow solver:** Change `global_solver` from "cbs" to "lacam"
4. **Too frequent replanning:** Increase `replan_every` value

### Problem: "MemoryError" or computer freezes

**Cause:** Not enough RAM for large experiments.

**Solution:**

- Reduce `num_agents`
- Use smaller maps
- Close other applications
- Run fewer parallel experiments

### Problem: Results differ between runs

**Cause:** Different random seeds.

**Solution:** Always use explicit seeds:

```bash
python3 scripts/evaluation/run_evaluation.py --seeds 42 --group baselines --out logs/results
```

The same seed will always produce the same results.

### Problem: GUI window is too small

**Solution:** Use a map with fewer cells or zoom out (if supported).

---

## 21. Glossary of Terms

| Term                    | Definition                                        |
|-------------------------|---------------------------------------------------|
| **Agent**               | A agent in the simulation                         |
| **CBS**                 | Conflict-Based Search - an optimal MAPF solver    |
| **Cell**                | A single grid square on the map                   |
| **Collision**           | When two entities occupy the same cell            |
| **Configuration file**  | A `.yaml` file that defines experiment settings   |
| **Field of View (FOV)** | How far a agent can see                           |
| **Flowtime**            | Total time for all agents to complete their tasks |
| **Global planner**      | Plans paths for all agents together               |
| **Horizon**             | How far into the future we plan                   |
| **Human model**         | Rules for how humans move in simulation           |
| **LaCAM**               | A fast, approximate MAPF solver                   |
| **Lifelong MAPF**       | Continuous task assignment                        |
| **Local planner**       | Plans short-term detours around obstacles         |
| **Makespan**            | Time until the last task is completed             |
| **MAPF**                | Multi-Agent Path Finding                          |
| **One-shot MAPF**       | Classical MAPF where each agent has one goal      |
| **Replay**              | A recording of a simulation                       |
| **Safety radius**       | Buffer zone around humans                         |
| **Seed**                | A number that controls random generation          |
| **Throughput**          | Tasks completed per unit time                     |
| **Token passing**       | A method for agents to coordinate movements       |
| **Virtual environment** | An isolated Python installation                   |

---

## 22. Complete Command Reference

### Installation Commands

```bash
# Clone repository
git clone <REPO_URL>
cd ha_lmapf

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pip install matplotlib pygame pytest
```

### Verification Commands

```bash
# Check package import
python3 -c "import ha_lmapf; print('OK')"

# Check evaluation script help
python3 scripts/evaluation/run_evaluation.py --help

# Run all tests
python3 -m pytest -v tests/
```

### Evaluation Commands

```bash
# Run all experiments
python3 scripts/evaluation/run_evaluation.py --out logs/all_results

# Run specific experiment group
python3 scripts/evaluation/run_evaluation.py --group baselines --seeds 0 1 2 --out logs/baselines

# Run with custom config
python3 scripts/evaluation/run_evaluation.py --config configs/my_config.yaml --out logs/custom
```

### All Available Experiment Groups

```bash
--group baselines        # Compare against other methods
--group scalability      # Test with varying agent counts
--group human_density    # Test with varying human counts
--group human_models     # Test different human behaviors
--group map_types        # Test different map layouts
--group ablations        # Test with components disabled
--group delay_robustness # Test with execution delays
--group arrival_rate     # Test task arrival speeds
--group robustness       # Test difficult scenarios
--group no_humans        # Compare without humans
--group classic_mapf     # One-shot classical MAPF
```

### Visualization Commands

```bash
# Lifelong MAPF GUI (requires config file)
python3 scripts/run_gui.py --config configs/warehouse_small.yaml --seed 42

# One-shot Classical MAPF GUI (command-line options)
python3 scripts/run_oneshot_gui.py --agents 20 --solver lacam
python3 scripts/run_oneshot_gui.py --agents 10 -H 5  # With humans
python3 scripts/run_oneshot_gui.py --map data/maps/maze-32-32-4.map

# Human-Aware One-Shot MAPF GUI (command-line options)
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 5
python3 scripts/run_oneshot_hamapf_gui.py --agents 15 --humans 10 --human-model adversarial
python3 scripts/run_oneshot_hamapf_gui.py --agents 20 --humans 8 --fov 3 --safety 2

# Generate figures
python3 scripts/evaluation/plot_results.py --results logs/results --out figures
```

### Quick Start Examples

```bash
# 1. Quick baseline test
python3 scripts/evaluation/run_evaluation.py --group baselines --seeds 0 --out logs/quick_test

# 2. Classical MAPF visualization (no humans)
python3 scripts/run_oneshot_gui.py --agents 15 --solver cbs

# 3. Human-aware demonstration (RECOMMENDED for demos)
python3 scripts/run_oneshot_hamapf_gui.py --agents 10 --humans 5

# 4. Lifelong MAPF with config file
python3 scripts/run_gui.py --config configs/warehouse_small.yaml

# 5. Stress test with adversarial humans
python3 scripts/run_oneshot_hamapf_gui.py --agents 15 --humans 10 --human-model adversarial

# 6. Full paper experiments (takes several hours)
python3 scripts/evaluation/run_evaluation.py --seeds 0 1 2 3 4 --out logs/paper_results
```

---

## Repository Folder Guide

Below is what each top-level folder contains and when you need it.

| Folder | Contents | When You Need It |
|--------|----------|------------------|
| `src/` | Main Python package (`ha_lmapf`) with planners, simulator, human models, IO, GUI. | Indirectly, every time you run scripts. Advanced users read it to understand algorithms. |
| `docs/` | User-facing documentation files, including this guide. | Start here if you are new. |
| `tests/` | Automated checks for map loading, allocators, safety, conflicts, one-shot mode, task streams, and replanning logic. | Run these to confirm your installation is healthy before big experiments. |
| `configs/` | YAML experiment settings. General configs and paper-eval variants under `configs/eval/`. | Every time you run a simulation/experiment. |
| `scripts/` | Entry-point scripts for experiments, evaluation suites, plotting, task generation, and GUI. | For all practical usage (run, evaluate, plot). |
| `data/` | Map files (`data/maps/`), task streams (`data/task_streams/`), and scenarios. | Loaded automatically by configs and scripts. |
| `logs/` | Experiment outputs (metrics, replays, plots). | Created when you run experiments. |

---

## FAQ

**Q: I am new. What is the easiest command to start?**
Use the Quick Start section command with `configs/random_20x20.yaml` and one seed.

**Q: Do I need a GPU?**
No. CPU is enough.

**Q: Do I need to understand the source code first?**
No. You can run experiments from scripts/configs directly.

**Q: What is the difference between `run_experiments.py` and `run_evaluation.py`?**
- `run_experiments.py`: run one config for chosen seeds.
- `run_evaluation.py`: run many paper groups automatically.

**Q: How do I compare two settings fairly?**
Use same map, same seeds, and only change one parameter at a time.

**Q: Where do I find final paper-ready figures?**
Run:
```bash
python3 scripts/evaluation/plot_results.py --results logs/eval --out figures
```
Then check `figures/`.

---

## Need More Help?

1. **Check the code documentation:** Well-documented source in `src/ha_lmapf/`
2. **Look at example configs:** `configs/` has many examples
3. **Run tests:** Tests in `tests/` show how components work

---

*This guide was created to help researchers reproduce the experiments.*