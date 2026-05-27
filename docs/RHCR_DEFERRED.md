# RHCR baseline — deferred

**Status:** RHCR is not used as a §5.5 baseline in this paper.  It
has been replaced by **`lacam_blind`** (LaCAM + `controller_kind=
global_only`).  This note records the architectural reason and the
plan for re-introducing RHCR in a future journal extension.

## TL;DR

RHCR's KIVA scenario is a **self-contained lifelong simulator**, not
a callable per-replan MAPF solver.  It cannot be invoked from the
rolling-horizon framework as a one-shot MAPF backend: there is no
CLI for per-replan agent starts, the `--task` flag is parsed but not
consumed in the KIVA branch, and tasks/start positions are generated
internally from map markers.  Fixing the wrapper's input file format
is necessary but not sufficient — the integration would require
either (i) replacing RHCR's KIVA system with a custom MAPF entry
point built from its WHCA*/PBS backend, or (ii) treating RHCR's
end-to-end output as a fixed trajectory and replaying it through the
POE-LMAPF simulator with exogenous-agent injection on top.

For this paper's scope, neither path adds enough comparative value
to justify the implementation cost.  `lacam_blind` preserves the
methodological intent of §5.5 (rigid-follower Tier-2 against a
high-quality Tier-1 planner) without introducing the
task-distribution ambiguity that an RHCR adaptation would.

## Architectural mismatch — source-code evidence

Three loci in the upstream `Jiaoyang-Li/RHCR` repository establish
the mismatch.

### 1. The KIVA branch calls `system.simulate(...)` with no task input

Reference: `src/driver.cpp:178-189`.

```cpp
if (vm["scenario"].as<string>() == "KIVA")
{
    KivaGrid G;
    if (!G.load_map(vm["map"].as<std::string>())) return -1;
    MAPFSolver* solver = set_solver(G, vm);
    KivaSystem system(G, *solver);
    set_parameters(system, vm);
    G.preprocessing(system.consider_rotation);
    system.simulate(vm["simulation_time"].as<int>());   // ← self-contained
    return 0;
}
```

Compare with the BEE branch (`src/driver.cpp:218-260`) which calls
`G.preprocessing(vm["task"].as<std::string>(), ...)` and
`system.load_task_assignments(vm["task"].as<std::string>())` — BEE
consumes the `--task` argument; KIVA does not.

### 2. KIVA agent starts come from map `r` cells, not from any CLI

Reference: `src/KivaSystem.cpp:37-50`.

```cpp
void KivaSystem::initialize_start_locations()
{
    for (int k = 0; k < num_of_drives; k++)
    {
        int orientation = -1;
        if (consider_rotation)
            orientation = rand() % 4;
        starts[k] = State(G.agent_home_locations[k], 0, orientation);
        paths[k].emplace_back(starts[k]);
        finished_tasks[k].emplace_back(G.agent_home_locations[k], 0);
    }
}
```

`G.agent_home_locations` is populated by the map parser from `r`
cell markers and shuffled at load time (`KivaGraph.cpp:175-176`).
The rolling-horizon framework would need to pass _current_ simulator
agent positions on every replan — there is no API path.

### 3. KIVA goals are generated internally from random endpoints

Reference: `src/KivaSystem.cpp::initialize_goal_locations`
(immediately after `initialize_start_locations`).

```cpp
void KivaSystem::initialize_goal_locations()
{
    if (hold_endpoints || useDummyPaths) return;
    // Choose random goal locations
    // Goal locations are not necessarily unique
    ...
}
```

Pickup-delivery tasks are sampled internally over the map's `e`
cells.  The simulator's task allocator's choices have no path to
this code.

### 4. The KIVA map format is well-defined but solves a different problem

Reference: `src/KivaGraph.cpp:92-186` (`load_unweighted_map`).

```
<rows>,<cols>
<num_endpoints>           ← informational; the parser walks the grid
<agent_num>               ← informational
<maxtime>                 ← informational
<rows lines × cols chars, markers: @ e r [anything else=Travel]>
```

Writing a KIVA-format map for `warehouse-10-20-10-2-2` (the §5.5
warehouse) is mechanically straightforward.  But once parsed, the
agents start at the `r` cells **as written in the map file** and
goal cells are sampled randomly from `e` cells **as written in the
map file**.  The wrapper's `tasks.task` file is never read.

## Paths considered

### Path A — Per-replan map encoding

For every replan, write a fresh KIVA map where the simulator's
current 150 agent positions become 150 `r` cells and the assigned
task goals become 150 `e` cells.  Invoke RHCR for `simulation_time`
≈ `H` ticks, parse the first `H` ticks of paths.

**Problems:**

1. RHCR's KIVA mode generates random pickups across all `e` cells.
   Agent _k_'s first goal will not be the `e` cell corresponding to
   simulator-task-_k_'s goal; it will be a uniformly-sampled
   `e` cell.  Wrong goals.
2. RHCR's KIVA mode loops: after agent reaches its first random
   `e`, it samples another, etc.  Only the first segment per agent
   is usable, but the path may be routed through the wrong
   intermediate.
3. Wall-clock: RHCR preprocesses on every map change (84×170 grid,
   ≈ 14 000 free cells).  Estimated 5-30 s per replan, ×200 replans
   per 2000-step run, × 10 seeds, × 4 paper cells → days of cluster
   time per §5.5 sweep.

Effort: ~1-2 days wrapper rewrite.  Outcome: still semantically wrong.
**Not recommended.**

### Path B — End-to-end one-shot + trajectory replay (future work)

The architecturally correct approach.

1. **Once per simulation run:** invoke RHCR's KIVA scenario for the
   full `simulation_time` (e.g., 2000 ticks) at the right scale
   (|M|=150) on a KIVA-format derivative of the warehouse.  Capture
   the 150 agent trajectories × 2000 steps from RHCR's output.
2. **Add a new controller** `controller_kind="trace_replay"` to the
   POE-LMAPF simulator that loads pre-computed trajectories and
   rigidly executes them step by step.
3. **Inject exogenous agents** on top using the existing human-model
   machinery.
4. **Count violations** (agent-attributable and exogenous-attributable)
   against the replayed trajectories.

**Pros:**

* Honors RHCR's actual semantics (it plans its own lifelong loop
  from scratch).
* Wall-clock cost: ~30 s – 2 min per run; fits in the §5.5 budget.
* Methodologically clean: comparison is "POE-LMAPF buffer-aware
  controller" vs "RHCR's task-blind end-to-end planning, rigid
  execution against exogenous agents".

**Cons (the reason it's deferred for this paper):**

* Requires a new controller kind (~150 LoC).
* Wrapper architecture must shift from per-replan solver to one-shot
  trajectory generator — a parallel code path, not a wrapper edit.
* RHCR's randomly-generated tasks ≠ the simulator's task allocator's
  choices.  Throughput will differ from `ours` for reasons unrelated
  to the buffer formulation; a methodology footnote is required.
* Total effort: ~2-3 days dev + sweep retuning.

**Path B plan for the journal extension:**

1. Add `controller_kind = "trace_replay"` to `core/types.py` and a
   `TraceReplayController` in `local_tier/` that reads a path bundle
   and emits `desired_next` per agent per tick.
2. Add a one-shot RHCR baseline runner — separate module from
   `rhcr_wrapper.py`, e.g. `baselines/rhcr_oneshot.py` — that
   invokes RHCR at simulation start and stores the trajectory.
3. Add a new `method = "rhcr_trace"` to `_apply_method` that wires
   the one-shot runner + trace_replay controller into a SimConfig.
4. Acknowledge in the journal §5.5 that RHCR's task semantics differ
   from POE-LMAPF's; report the throughput numbers but emphasize
   safety-violation comparisons (which are well-defined regardless
   of task source).

### Path C — Replace RHCR with `lacam_blind` (this paper's choice)

§5.5's purpose is to demonstrate that buffer-aware Tier-2 improves
safety across different Tier-1 planner qualities.  The 2×2 matrix
intended for §5.5:

| | Tier-2 buffer-aware | Tier-2 rigid |
|---|---|---|
| Optimal Tier-1 | `ours` | `rhcr` (originally), `lacam_blind` (chosen) |
| Suboptimal Tier-1 | (not in paper) | `pibt2_fr` |

`lacam_blind` (LaCAM-Official as Tier-1, `controller_kind=
global_only` as Tier-2) sits in exactly the slot RHCR was intended
to occupy.  Concretely:

* Same Tier-1 quality as `ours` (both use `lacam_official`).
* Tier-2 disabled: no inflated buffer F, no local A* repair, agents
  rigidly follow the global plan.
* Throughput is directly comparable to `ours` because the Tier-1
  plan space is identical; the only experimental difference is
  Tier-2 buffer awareness.

**Effort:** ~1 hour (factory + dispatch wiring + tests).

**Cost vs RHCR:** loses the historical citation but gains
methodological cleanliness.  The §5.5 footnote (below) explains the
substitution.

## §5.5 paper-text footnote draft

> We initially intended to include RHCR (Li et al. 2021) as a
> baseline.  RHCR's KIVA scenario is a self-contained lifelong
> simulator that generates its own tasks and start positions from
> map markers, with no CLI interface for per-replan invocation.
> Integrating it into our rolling-horizon framework would require
> either (i) reimplementing its WHCA\*/PBS backend as a one-shot
> solver, or (ii) treating RHCR's output as fixed trajectories and
> replaying against exogenous agents — both introduce ambiguity in
> the safety-metric attribution.  We instead use LaCAM-blind, LaCAM
> with `controller_kind=global_only`, which preserves the same
> Tier-1 planner quality as our method while disabling Tier-2 buffer
> awareness, isolating buffer-awareness as the experimental
> variable.

## Operational consequences

* `method="rhcr"` in any YAML now raises `NotImplementedError` at
  config-build time, citing this document and naming
  `method="lacam_blind"` as the substitute.  The factory
  `make_rhcr_blind_config` is preserved for import compatibility
  but raises on call.
* All paper sweeps that previously specified `[ours, rhcr,
  pibt2_fr, no_buffer]` (`temporal_progression`,
  `baseline_comparison`, `budget_sensitivity`) now specify
  `[ours, lacam_blind, pibt2_fr, no_buffer]`.
* The 10 §5.8 smoke sidecars from `method=rhcr` (commit `fbb4881`)
  are dropped from `results.csv` and from the `timelines/`
  directory in the same commit that introduces `lacam_blind`.  The
  next sweep run will produce 10 `lacam_blind` cells fresh.
* `validate_smoke_results.py`'s default `--skip-method rhcr` is
  retained for backward compatibility with any out-of-tree CSVs;
  users running new sweeps can drop the flag (no rhcr rows will
  appear).
