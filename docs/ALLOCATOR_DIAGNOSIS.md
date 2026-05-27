# PIBT2-FR Simulator-Driven Failure — Allocator Diagnosis

**Hypothesis being tested:** the simulator's task allocator generates start/goal
pairs that are PIBT2-pathological even when individually feasible, causing
`test_baseline_pibt2_fr` to fail at every density on
`warehouse-10-20-10-2-1`.

**Verdict:** **Hypothesis is REJECTED.** The allocator is not at fault. The
captured failing instances are fully solvable (LaCAM\* solves them in
`makespan=145` in <1 ms, PIBT2 itself solves them when `max_timestep` is
sufficient). The actual root cause is **a wrapper bug**: PIBT2's
`max_timestep` field is set to `horizon + 50 = 70`, but agents' goals are
often >70 cells from their starts on the 63×161 warehouse map, so PIBT2
deadlocks against the timestep limit before reaching any goal. This is NOT
an allocator-pathology, NOT a PIBT2-incompleteness, and NOT a map-structure
issue.

---

## 1. Setup

Test fixture: `tests/test_baseline_pibt2_fr.py` (post 939b64a wrapper fix).
Repro: `make_pibt2_fr_config` with `map_path=warehouse-10-20-10-2-1.map`,
`seed=0`, `num_agents=5`, `num_humans=20`. Run via `Simulator.run()`.

Failure: every replan reports `error_msg='PIBT2 reported solved=0'`,
`throughput=0`, `completed_tasks=0`. Confirmed on previous turn's empirical
study: 0/5 success across all densities tested
(n_agents = {5, 10, 15, 20, 25}, humans = {0, 5, 10, 20}, steps = {200, 300}).

## 2. Captured failing replans

Three consecutive simulator-driven replans (`step` 0, 1, 2) were dumped via
a temporary `BaseSolverWrapper._wrap_subprocess` hook (the hook was reverted
before this document was written). All three are identical: in step 0 the
simulator's all-WAIT fallback fires when PIBT2 returns `solved=0`, agents
remain stationary, and steps 1–2 see the same starting state. Excerpt of
the captured instance file:

```
map_file=/tmp/pibt2_<...>/maps/map.map
agents=5
seed=0
random_problem=0
max_timestep=70
max_comp_time=1000
139,52,4,46
29,40,19,53
142,31,152,53
152,16,12,11
93,19,113,2
```

Per-agent state (from the captured `state.json`; positions in `(row, col)`
matching the simulator's internal convention):

| Agent | Position (row, col) | Goal (row, col) | Manhattan dist | Carrying | Task |
|---|---|---|---|---|---|
| 0 | (52, 139) | (46, 4) | **141** | False | t0000002 |
| 1 | (40, 29) | (53, 19) | 23 | False | t0000000 |
| 2 | (31, 142) | (53, 152) | 32 | False | t0000004 |
| 3 | (16, 152) | (11, 12) | **145** | False | t0000003 |
| 4 | (19, 93) | (2, 113) | 37 | False | t0000001 |

All starts and goals are on free cells (verified: `env.is_blocked` returns
False for every position).

### Pairwise pathology check

For every (i, j) pair, asked:

| Pattern | Found? |
|---|---|
| Agent i's goal == agent j's current position | **No** |
| Agent i's goal == agent j's goal (target conflict) | **No** |
| Agents i, j on the same 1-cell corridor with goals on opposite ends and no swap room | **No** — this is the open warehouse with 26-cell-wide endcap zones at both flanks |
| Agent i's pickup location coincides with another agent's transit path | Marginal; not the trigger |

The captured instance has **none** of the pathology patterns the prompt
hypothesised. Two agents (0 and 3) have goals >140 Manhattan cells from
their starts; the rest have shorter trips.

## 3. Direct PIBT2 invocation on the captured instance

Same instance (after fixing the `map_file=` path to point to the captured
`map.map`), invoked via `mapf_pibt2` directly. Sweeping `max_timestep` only:

| `max_timestep` | Verdict | Reported `makespan` | `comp_time_ms` |
|---|---|---|---|
| **70 (wrapper default)** | **FAIL** (`solved=0`) | 70 | 0 |
| 100 | FAIL (`solved=0`) | 100 | 0 |
| **145** | **OK** (`solved=1`) | **145** | 0 |
| 150 | OK | 145 | 0 |
| 200 | OK | 145 | 0 |
| 500 | OK | 145 | 0 |

PIBT2 succeeds at `max_timestep ≥ 145`, fails below. The minimum makespan
to reach all 5 goals is 145 (driven by Agent 3's 145-cell trip from
(16, 152) to (11, 12)). PIBT2 cannot return a `solved=1` plan whose
makespan exceeds `max_timestep` — by definition it has no time left to
move agents to their goals.

PIBT2's `solved=0` here is **a self-reported "ran out of allowed timesteps"
condition**, identical in surface form to the genuine deadlocks on the
mini-warehouse but originating from a completely different cause: a
budget mismatch, not a priority-scheme deadlock.

## 4. LaCAM\* comparison on the same instance

Built a MovingAI `.scen` file from the same starts/goals, ran
`lacam_official` with `-t 5.0` (5 s budget):

```
solved=1
makespan=145
comp_time=0    (sub-millisecond)
```

LaCAM\* solves the same instance instantly. **The instance is feasible.**
The allocator is not generating impossible work.

## 5. Allocator code analysis

**Allocator:** `src/ha_lmapf/task_allocator/task_allocator.py::GreedyNearestTaskAllocator.assign`.

```python
# Each released task picks the nearest available agent (Manhattan to pickup):
for task in tasks_ordered:
    if not free_agents:
        break
    pickup_loc = _get_task_pickup_location(task)
    best_aid = min(
        free_agents.keys(),
        key=lambda aid: (manhattan(free_agents[aid].pos, pickup_loc), aid)
    )
    assignments[best_aid] = task
    del free_agents[best_aid]
```

The allocator considers only:

1. Agent's current position (for distance computation)
2. Task's pickup location

It does NOT consider:

* Other agents' goals
* Other agents' current positions
* Conflict potential between assignments
* PIBT2's `max_timestep` budget
* Map geometry (corridors, dead ends)

**Could the allocator generate the pathological patterns the prompt
hypothesised?** In principle yes — there's no constraint that forbids
"agent i's goal == agent j's start". But empirically, on the captured
instance, none of those patterns appear. The allocator's output is
unremarkable: 5 agents, 5 distinct tasks, distinct pickups and deliveries
spread across the map. The only outlier is the pair of long-distance
trips (Agent 0: 141 cells; Agent 3: 145 cells), which is exactly what a
greedy allocator produces when the open task list happens to contain
deliveries on the far side of the map.

The allocator behaves correctly. The wrapper's `max_timestep` is too
small for the trips the allocator is assigning.

## 6. Root-cause analysis

### Where the bug lives

`src/ha_lmapf/global_tier/solvers/pibt2_wrapper.py::_write_instance_file`:

```python
f.write(f"max_timestep={horizon + 50}\n")  # Extra buffer
```

`horizon` here is the **rolling-horizon execution window** — the simulator
will execute only the first `horizon=20` steps of PIBT2's plan before
re-planning. The wrapper translates this to PIBT2's `max_timestep` field
(the maximum length of any solution PIBT2 will return) plus a 50-step
safety cushion. **These are different concepts**:

* `horizon` (simulator semantics) = "execute N steps then replan"
* `max_timestep` (PIBT2 semantics) = "your full plan must reach all goals
  within N steps; otherwise return `solved=0`"

PIBT2 cannot produce a partial plan — it's all-or-nothing per its
internal validator. If goals are 145 cells away and `max_timestep=70`,
PIBT2 returns `solved=0` even though it could trivially produce a
20-step prefix that advances every agent toward its goal.

### Why this masquerades as the allocator's fault

The two surface symptoms are identical:

* `error_msg='PIBT2 reported solved=0'`
* `metrics.solver_errors > 0`
* `throughput == 0`

Both produce identical metrics. The wrapper's parser cannot distinguish
"PIBT2 ran out of `max_timestep`" from "PIBT2 ran out of priorities to
shuffle". Both write `solved=0` to the result file. The only way to tell
them apart is to compare PIBT2's reported `makespan` against
`max_timestep`: if `makespan == max_timestep` exactly, it's the budget
mismatch; if `makespan == max_timestep` AND the agents' positions don't
move much across the trace (priority oscillation), it's a deadlock.

In the captured failing instance, `makespan=70` exactly matches
`max_timestep=70`, identifying it as the budget mismatch.

### Why two prompts back's mini-warehouse failure was *not* the same bug

The previous prompt's diagnosis (mini-warehouse, 10×14, 1-cell aisles)
captured an instance where Manhattan distances were small (5–11 cells)
but PIBT2 still failed at `max_timestep=500`. That was a genuine
priority-scheme deadlock — agents oscillating around shared goal cells
in a confined space with no swap room.

So we have **two distinct failure modes** that produce the same
`error_msg='PIBT2 reported solved=0'`:

| Mode | Trigger | Distinguishable by | Fix scope |
|---|---|---|---|
| **A. `max_timestep` too tight** | Manhattan(start, goal) > horizon + 50 for any agent on a large map | `result.makespan == max_timestep` AND agents move toward goals during the trace | Wrapper-side: change `max_timestep = horizon + 50` to a more generous formula |
| **B. priority-scheme deadlock** | Goals on confined corridors with no swap room (mini-warehouse) | `result.makespan == max_timestep` AND agents oscillate around goals during the trace | Test-side: replace the map; or paper-side: report PIBT2's incompleteness |

The previous prompt addressed mode B but the test was on the
warehouse-10-20-10-2-1 map which triggers mode A. **The
`test_baseline_pibt2_fr` failure is mode A**, not B.

## 7. Ranked-by-evidence root-cause hypothesis

| Rank | Hypothesis | Evidence | Confidence |
|---|---|---|---|
| **1** | **Wrapper's `max_timestep = horizon + 50` is too small** for warehouse-scale agent trips | PIBT2 succeeds at `max_timestep ≥ 145`, fails at ≤ 100. Reported `makespan` exactly equals `max_timestep` on every failing run. LaCAM\* solves the same instance in `makespan=145` in <1 ms. | **HIGH** — direct empirical verification |
| 2 | The allocator generates pathological pickup/delivery pairs | None of the hypothesised patterns appear in the captured instance. Agent 2's goal ≠ Agent 0's start (the previous prompt's hand-traced example was on the mini-warehouse, a different map and a different failure mode). | **REJECTED** |
| 3 | PIBT2's incompleteness on this map | PIBT2 succeeds at `max_timestep ≥ 145`. Direct invocation at n=5/20 agents on this map succeeds in the literature-consistent regime. | **REJECTED** for this map |
| 4 | The simulator passes humans into PIBT2's static map | The wrapper's `_write_map_file` writes only `env.is_blocked()`, which is the static layout. Empirical: `humans=0` produces the same failure pattern. | **REJECTED** |

## 8. Proposed remediation, ranked by scope

| Option | Scope | What it does | Side-effects |
|---|---|---|---|
| **(a) Wrapper-side: change `max_timestep` formula** | 1-line edit in `pibt2_wrapper.py::_write_instance_file` | Compute `max_timestep` from the actual map diameter or a much larger fixed value (e.g., `2 * (env.height + env.width)`). With 63+161=224, that's 448 — sufficient for any agent's trip on warehouse-10-20-10-2-1. | None expected. PIBT2's `comp_time` won't increase materially; it returns within ms regardless of `max_timestep` since it's bounded by `max_comp_time`. The wrapper's `solver_wall_ms` parser already reads `comp_time=` from the result file, not `max_timestep`. |
| (b) Test-side: change the smoke test to use lacam_official | swap `cfg.global_solver = "lacam_official"` in `test_baseline_pibt2_fr.py` | Smoke test passes immediately. | Loses test coverage of PIBT2-FR's actual behaviour; the test name becomes misleading. |
| (c) Allocator-side: add congestion-avoidance constraints | substantial change to `GreedyNearestTaskAllocator.assign` | Avoids the hypothesised allocator pathology that turns out not to exist. | Out of scope; allocator works fine. |
| (d) Wrapper-side: detect & skip pathological instances | new branch in `parse_fn` that distinguishes "budget mismatch" from "deadlock" via `makespan == max_timestep` and the trace pattern | Surfaces the two modes distinctly in `error_msg`. | Doesn't fix the underlying max_timestep problem; only labels it better. |
| (e) Paper-side: report PIBT2 success rate per cell | §5.4 / §5.5 prose change | Treats PIBT2's incompleteness as a measured property. | Doesn't apply here; the test failure is wrapper-side, not PIBT2-side. |

**Recommendation: option (a).** The wrapper writes `max_timestep` from a
1-line formula; replacing `horizon + 50` with something tied to map
dimensions (e.g., `2 * (env.height + env.width)`, or simply a generous
constant like `2000` to match `SimConfig.steps`) resolves the test
failure without touching the allocator, the parser, or the test fixture.

PIBT2's `max_comp_time` (separate field) bounds the wall-clock budget; a
large `max_timestep` does not let PIBT2 run forever — it just gives the
solver enough plan-length to satisfy its all-or-nothing solution
contract. The two fields serve distinct purposes and the wrapper
currently conflates them.

## 9. Concrete one-line fix preview (for the next prompt)

`src/ha_lmapf/global_tier/solvers/pibt2_wrapper.py::_write_instance_file`:

```python
# Before:
f.write(f"max_timestep={horizon + 50}\n")  # Extra buffer

# After:
# `horizon` is the simulator's per-replan execution window (typ. 20 steps),
# NOT PIBT2's full-plan timestep budget.  PIBT2 is all-or-nothing: its
# `max_timestep` must accommodate the longest agent trip on this map.
# 2 × (height + width) is generous enough for any straight-line trip on
# rectangular grids and still stays within PIBT2's millisecond compute time
# (bounded separately by `max_comp_time`).
max_timestep = max(horizon + 50, 2 * (env.height + env.width))
f.write(f"max_timestep={max_timestep}\n")
```

After this change, the captured failing instance's
`max_timestep = max(70, 2 × (63 + 161)) = max(70, 448) = 448`, which is
ample for the 145-cell longest trip. PIBT2 returns `solved=1` and the
wrapper's existing parser reads the plan correctly.

## 10. Verification plan for the fix prompt

1. Apply the 1-line `max_timestep` formula change.
2. Re-run `pytest tests/test_baseline_pibt2_fr.py -v` — expect
   `throughput > 0`, `solver_errors = 0` on warehouse-10-20-10-2-1.
3. Re-run the full manifest tests — expect 23/23 still passing.
4. Spot-check on warehouse-10-20-10-2-2 (paper main map) at high density
   (n_agents = 100) — expect `solved=1` from PIBT2 directly.

If the test still fails on warehouse-10-20-10-2-1 after the fix, that's a
*third* failure mode and warrants its own diagnosis.

## 11. What this diagnosis does NOT do

* Does NOT modify the allocator (works correctly).
* Does NOT modify the wrapper (preserves the diagnosis as evidence).
* Does NOT modify the test (will be updated in the fix prompt).
* Does NOT modify any algorithm (PIBT2 is correctly self-reporting `solved=0`
  given its overly tight `max_timestep`; that's a feature, not a bug).

---

## 12. Resolution

**Wrapper fix landed in this commit.** One-line change in
``src/ha_lmapf/global_tier/solvers/pibt2_wrapper.py::_write_instance_file``:

```python
# Before:
f.write(f"max_timestep={horizon + 50}\n")  # Extra buffer

# After:
max_timestep = max(horizon + 50, 2 * (env.height + env.width))
f.write(f"max_timestep={max_timestep}\n")
```

The ``max(horizon + 50, …)`` floor preserves the previous behaviour
on tiny test maps where the dimension-based formula would be
smaller; on warehouse-scale maps the dimension-based term
dominates.  Concrete values:

| Map                              | Pre-fix | Post-fix |
|----------------------------------|--------:|---------:|
| 5×5 (tiny test)                  | 70      | 70       |
| 10×14 (mini-warehouse)           | 70      | 70       |
| 20×20 (open test)                | 70      | 80       |
| 63×161 (warehouse-10-20-10-2-1)  | 70      | **448**  |
| 84×170 (warehouse-10-20-10-2-2)  | 70      | **508**  |

**Verification (post-fix):**

* The captured failing instance from §2 (Agent 0 trip:
  start=(52,139) → goal=(46,4), 141 cells) now solves cleanly
  through ``plan_with_metadata``.  Status="complete";
  Agent 0 advances 14 cells toward goal in the first 20-step
  rolling-horizon window (135 → 121 Manhattan cells remaining).
* PIBT2 returns ``solved=1`` directly on the same instance with
  the new ``max_timestep=448``.
* New regression tests in
  ``tests/test_pibt2_max_timestep.py`` (4 tests, all PASS):
    - ``test_max_timestep_scales_with_map_dimensions``
    - ``test_max_timestep_floor_preserved_on_tiny_maps``
    - ``test_pibt2_solves_long_distance_trip_on_warehouse``
    - ``test_max_timestep_does_not_mask_mode_b_deadlock``

**What this fix does NOT resolve:**

``test_baseline_pibt2_fr.py::test_pibt2_fr_smoke`` continues to
fail.  That test uses the **mini-warehouse fixture** (a 10×14 map
with 1-cell-wide aisles), not warehouse-10-20-10-2-1.  On the
mini-warehouse, ``max_timestep = max(70, 2*(10+14)) = max(70, 48)
= 70`` — the floor dominates and the value is unchanged from
pre-fix.  The mini-warehouse failure is **Mode B**: priority-scheme
deadlock on confined corridors with no swap room (verified in two
prior empirical studies; the captured pathology has agent goals
sharing transit cells with no parking room).  Mode B is
algorithmic and cannot be fixed by changing ``max_timestep``.
Resolving the smoke test requires either a different fixture map
(warehouse-10-20-10-2-1 or warehouse-10-20-10-2-2 with appropriate
cohort sizes) or accepting PIBT2's incompleteness on that fixture.
That is a separate prompt's scope.
