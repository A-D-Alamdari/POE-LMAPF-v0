# Solver Error Storm — Diagnosis & Fix

**Status.** Root cause identified, reproduced, and fixed in the wrappers.

## Symptom

In the paper §5.4 scaling sweeps, three one-shot MAPF wrappers — `lacam3`,
`lacam_official`, and `lns2` — produce `solver_errors_mean` that climbs
with agent count, hitting `100.0` (i.e., every one of the 100 global
replans failed) by 250 agents on `random-64-64-10`. The reference
artifact is
[`results/paper/scaling/scaling_agents_fov3_safe1_random-64-64-10.csv`](../results/paper/scaling/scaling_agents_fov3_safe1_random-64-64-10.csv).
The `pibt2` wrapper shows zero errors on the same sweep. The three
binaries are healthy in isolation (`./lacam3 --help` exits 0).

## Reproducer

`scripts/debug_solver_call.py` constructs four synthetic 200-agent
windowed instances and invokes each wrapper through
`plan_with_metadata`, capturing the exact `argv`, both input files, the
raw stdout/stderr, and the binary's result file. The artifacts land
under `logs/solver_debug/<solver>__<scenario>/`.

```
$ python scripts/debug_solver_call.py --num-agents 200 --time-limit-sec 5
```

| scenario              | duplicate goals | lacam3      | lacam_official | lns2                            |
| --------------------- | --------------- | ----------- | -------------- | ------------------------------- |
| `clean`               | 0               | complete    | complete       | complete                        |
| `start_eq_goal` (67)  | 0               | complete    | complete       | complete                        |
| `duplicate_goals` (2) | 2               | error       | error          | error (rc=255)                  |
| `realistic`           | 6               | error       | error          | error (rc=255)                  |

The candidate causes listed in the task spec are ranked here against
the evidence:

* **(a) Degenerate `start == goal` agents.** Ruled out. The
  `start_eq_goal` scenario has 67 of 200 agents with `start == goal`
  and **all three wrappers return `status="complete"`**.
* **(b) Scenario file format mismatch.** Ruled out. The `clean`
  scenario uses the same writer the failing scenarios do and parses
  without issue.
* **(c) Output-format / parser drift.** Ruled out. On the `clean`
  scenario all three parsers produce complete bundles.
* **(d) Wrong result-file path.** Ruled out. `result.txt` /
  `paths.txt` are written exactly where the wrapper expects.

The **actual cause** is none of (a)–(d): it is **duplicate effective
goal cells across agents in the windowed instance**.

## Root cause: duplicate goals

All three binaries are one-shot MAPF solvers expecting an instance
where each agent has a distinct target. When two agents share a goal
cell:

* **Kei18 `lacam` / `lacam3`** exhaust the time budget without ever
  finding an initial feasible solution and write a result file with
  `solved=0` and an empty `solution=` section. The wrapper's parser
  flags it as a parse error, the decision tree sees `rc=0` + no plan
  → `error`.

  ```
  $ ./lacam3 -m m.map -i dup_goal.scen -N 3 -t 5 -v 0
  $ grep -E '^(solved|comp_time)=' result.txt
  solved=0
  comp_time=5006
  ```

* **Jiaoyang-Li `mapf_lns` (LNS2)** detects the target conflict
  during its PP initial-solution phase, prints
  `Find a target conflict where agent X (...) traverses agent Y's
  target location ...`, and **exits with `rc=255`** (a hard abort,
  not a clean budget-exhaustion). The wrapper sees `rc != 0` + no
  paths file → `error`.

  ```
  $ ./mapf_lns -m m.map -a dup_goal.scen --outputPaths=p.txt -k 3 -t 2
  Find a target conflict where agent 0 (of length 14) traverses
    agent 1 (of length 13)'s target location 63 at timestep 14
  $ echo $?
  255
  ```

The error is **catastrophic and instance-wide**: a single pair of
duplicate goals is enough to abort LNS2 and to exhaust LaCAM's full
time budget without producing any agent's path — including the 198
agents whose goals are distinct. That is why the failure rate goes
from 0% at low agent counts to 100% at 250 agents: the scaling sweep
just makes the collision probability cross 1.

## Why duplicate goals exist in rolling-horizon instances

The task stream generator (`scripts/make_task_streams.py:35-36`)
samples each task's `(start, goal)` independently — it enforces
`goal != start` per task but **not** uniqueness of goal cells across
tasks. At 250 agents on a 4096-cell map (3687 free after blocks),
multiple Phase-2 deliveries with the same `task.goal` are likely; one
delivery cell shared by two tasks suffices for the failure.

Other contributors that compound the rate:

* Phase-1 agents whose `goal == task.start` may share a pickup cell
  when a task gets reassigned mid-flight.
* The rolling-horizon planner does no goal-uniqueness check before
  handing the instance to the wrapper.

`pibt2` is unaffected because its prioritized-planning algorithm
treats target cells positionally (an agent at its goal will yield if
contested) rather than as exclusive endpoints.

## Fix

The three offending wrappers now pre-filter the agent set sent to
their binary so the instance always satisfies the one-shot-MAPF
contract:

1. **Drop agents with `start == goal`.** They do not need a plan;
   they already occupy their target and stay put.
2. **Drop agents whose effective goal duplicates an earlier-kept
   agent's goal.** The first agent claiming a cell is planned; later
   claimants are excluded.

Filtered agents are not lost — `BaseSolverWrapper._build_complete_bundle`
already fills `WAIT` paths for every agent absent from the parsed
result, so the returned `PlanBundle` covers the full fleet.

The shared helper lives in `_base.py` as
`BaseSolverWrapper._filter_one_shot_instance` and is called by each
of the three wrappers immediately after `_get_active_agents`. The
helper also short-circuits the empty-kept case (every active agent
filtered → return an all-WAIT bundle with `status="complete"`).

### What this is **not**

* Not a widening of the all-WAIT fallback. The fallback path is
  unchanged; this fix prevents the solver from being called with an
  infeasible instance in the first place.
* Not a timeout bump. `time_limit_sec` is untouched.
* Not silently downgrading the run. Filtered agents still appear in
  the bundle and the simulator is free to plan them again on the next
  replan, by which time the colliding peer will have moved off the
  shared cell (or its task will have completed and been reassigned).

## Verification

`tests/test_solver_duplicate_goals.py` (new) builds the same
`duplicate_goals` and `realistic` instances at 200+ agents, calls each
of the three wrappers' `plan_with_metadata`, and asserts:

* `status == "complete"` for every wrapper / scenario.
* The returned `PlanBundle` has one path per active agent and the
  paths are pairwise collision-free (no vertex/edge conflicts).

Re-running `scripts/debug_solver_call.py` after the fix shows
`status=complete` across all four scenarios for all three wrappers.

## Files touched

* `src/ha_lmapf/global_tier/solvers/_base.py` — new helper
  `_filter_one_shot_instance`.
* `src/ha_lmapf/global_tier/solvers/lacam3_wrapper.py`,
  `lacam_official_wrapper.py`, `lns2_wrapper.py` — invoke the helper
  in `plan_with_metadata` and drop filtered ids from the scenario.
* `scripts/debug_solver_call.py` — diagnostic harness.
* `tests/test_solver_duplicate_goals.py` — acceptance test.
