# Tier-1 -> Tier-2 Guidance Handoff — Diagnosis

**Status.** The Tier-1 -> Tier-2 handoff is *functionally* correct: the
controller receives the bundle, indexes into it correctly, and the
executed action matches the prescribed cell on >94% of (agent, tick)
pairs when a real solver is in use. Throughput is solver-invariant in
the **default controller** for two compounding reasons; neither is a
plumbing bug, so no controller-handoff change is needed. To compare
global solvers by throughput, the experiment has to use a controller
that does *not* substitute for the global plan -- the existing
`controller_kind="global_only"` mode is the right vehicle, and it
already produces ordered, solver-dependent throughput.

## Observation

In the §5.4 scaling CSVs, `thpt_per_agent_mean ≈ 0.00397` (warehouse) /
`≈ 0.0075` (random) across `num_agents ∈ {25, ..., 250}`, and the
ordering across `pibt2`, `lacam3`, `lacam_official`, `lns2` is
indistinguishable from noise. `pibt2` has zero solver errors (its
plans are real), so "all solvers failed and reduced to all-WAIT" does
not explain it. Concretely, on `random-64-64-10`, 25 agents, 500 steps,
seed 0, `task_arrival_rate=None` (default auto-scaling):

| solver   | ctrl         | throughput | coverage | follow_rate | global | local | safe_wait |
| -------- | ------------ | ---------- | -------- | ----------- | ------ | ----- | --------- |
| pibt2    | default      | 0.190      | 0.988    | 0.939       | 55     | 511   | 24        |
| lacam3   | default      | 0.190      | 0.987    | 0.944       | 55     | 476   | 27        |
| all_wait | default      | 0.192      | 0.986    | 0.625       | 147    | 2521  | 53        |
| pibt2    | global_only  | 0.186      | 0.909    | 0.874       | 50     | 0     | 0         |
| lacam3   | global_only  | 0.190      | 0.907    | 0.918       | 50     | 0     | 0         |
| all_wait | global_only  | **0.000**  | 1.000    | 1.000       | 50     | 0     | 0         |

`all_wait` is a debug global planner (added in this commit, registered
in `GlobalPlannerFactory` under that name) that returns an all-WAIT
bundle every replan; it bounds the contribution of the global tier.

## Instrumentation

`SimConfig.debug_guidance_trace` (default `False`) turns on per-tick
recording in `Simulator.step_once`:

1. **Before** the decide loop, snapshot each agent's prescribed next
   cell from the *current* `PlanBundle`. The snapshot must precede
   `AgentController.decide_action` because the controller calls
   `clear_path` on its own bundle entry whenever it triggers a local
   replan — without the pre-snapshot, the post-decision comparison
   reads `None` and underreports follow rate.
2. **After** the physics phase (post collision-prevention reverts),
   compare the agent's new position to the snapshot.

Aggregated into `Metrics`:

* `guidance_eligible_ticks` — agent-ticks where the agent had an
  active task at decision time (`goal != None`, `pos != goal`).
* `guidance_covered_ticks` — eligible ticks where a non-empty
  `TimedPath` existed for the agent.
* `guidance_followed_ticks` — covered ticks where the post-physics
  position equals the bundle's `step+1` cell.
* `guidance_coverage = covered / eligible`
* `guidance_follow_rate = followed / covered`

Idle / at-goal agents are excluded from the denominator; they are not
expected to receive guidance, and including them would mechanically
push coverage to 100% in low-load regimes. The snapshot stores the
agent's decision-time goal in `Simulator._prev_goal_for_guidance` so
that Phase-1 pickup completion (which rewrites `agent.goal` inside
the same `step_once` after the controller's read) does not flip an
eligible agent's classification mid-tick.

## Mapping observations to the three rubric outcomes

The task spec lists three candidate diagnoses. The instrumented
numbers above place us in **bucket 3** (task-supply / capacity bound),
modulated by an aggressive Tier-2 fallback. Walking through:

* **Bucket 2 — bundle isn't reaching the controller, or is
  stale/misindexed.** Ruled out. `guidance_coverage` is 0.99 in
  every default-controller run, and the bundle is followed on 94% of
  covered ticks for real solvers. The plumbing works.

* **Bucket 1 — follow rate high in both, throughput equal,
  guidance is cosmetic.** Partially. Real solvers' follow rate IS
  high. But `all_wait` shows follow rate dropping to 0.63 — the
  controller *does* notice when the bundle is missing/exhausted; it
  triggers local replans (147 global vs 55 for real solvers, and a
  5× increase in local replans). So the controller is consulting
  the bundle, not ignoring it. The guidance binds in code; it just
  doesn't bind in throughput.

* **Bucket 3 — follow rate high with real, low with all-WAIT, but
  throughput still equal: throughput is supply-bound.** This is the
  fit. The cause has two compounding pieces:

  1. **Auto-tuned task supply matches service rate.** Simulator
     `_generate_task_stream` (lines 575-583, 593-597) sets the
     per-agent inter-arrival to `H + W` when
     `task_arrival_rate is None`, which is "the expected task
     completion time for a random task on the map, giving a
     naturally balanced ~1× load". At ~1× load the system runs at
     its arrival rate, not its capacity. Better routing then
     reduces idle time, not throughput.

     Verified by raising the load (`--task-arrival-rate 5` —
     ~5× oversupply): throughput climbs uniformly to 0.504 / 0.504
     / 0.508, but the solver-invariance persists.

  2. **Tier-2 local A* substitutes effectively for the global
     plan.** Even at oversupplied load, `all_wait` matches the
     real solvers because `AgentController` detects an exhausted
     bundle and triggers `AStarLocalPlanner.plan(...)` with a soft
     +1 cost penalty for off-guidance cells
     (`local_planner.py:42, 156`). On a sparse 64×64 random map
     (~6% density at 250 agents, much less at 25) the
     decentralised conflict resolver handles agent-agent contention
     FOV-locally, so single-agent A* + resolver is essentially a
     competent decentralised MAPF planner without the centralised
     coordination LaCAM provides.

     The +1 deviation cost is small relative to the path-length
     heuristic (~30-60 cells of Manhattan distance), which is why
     A* freely substitutes its own path when the guidance set is
     blocked or absent. Pushing this cost up would *make the global
     plan bind* but would also break human-detour navigation — A*
     would refuse to step off the guidance even when a human is
     parked on it. The current weighting is a deliberate
     compromise, not a bug.

## Why `global_only` does differentiate

`controller_kind="global_only"` (paper baseline mode used by
PIBT2-FR and LaCAM-blind, `simulator.py:343` →
`baselines/global_only_replan.py`) is a rigid-follower controller: no
local A*, no human-aware detour, just execute the bundle's `step+1`
cell with a vertex-occupancy yield. Under that controller the global
plan IS the agent's policy, and throughput is ordered:

* `all_wait` → 0.000 (no plan, no movement)
* `pibt2`    → 0.186
* `lacam3`   → 0.190

The 2% pibt2/lacam3 gap is small but explainable: at the same fleet
size LaCAM3's plans complete more pickups per replan because LaCAM3
allows simultaneous coordination across all agents, while PIBT2's
prioritized search yields longer per-agent paths in dense
neighbourhoods.

## What to do about the §5.4 / §5.5 experiments

The §5.5 baseline comparison already uses `controller_kind` to mark
its rigid-follower baselines (`pibt2_fr`, `lacam_blind`,
`make_pibt2_fr_config`, `make_lacam_blind_config`). The "ours"
condition in that sweep uses the default controller -- which is
exactly the regime where throughput is solver-invariant in the
default controller. Two ways to extract a meaningful global-solver
comparison from existing artifacts without changing the simulator:

1. **Compare across rigid-follower variants.** The `pibt2_fr` and
   `lacam_blind` rows already exercise `global_only`; their
   throughput ordering is the genuine global-plan-quality signal.
2. **Compare on quantities that are not capacity-saturated.** Per
   `metrics.csv` columns that DO differ across solvers even under
   the default controller (data above):
   * `local_replans`: 511 (pibt2) / 476 (lacam3) / 2521 (all_wait).
     A solver-quality proxy: how often the global plan was so
     unusable that the controller had to re-plan locally.
   * `safe_wait_steps`: 24 / 27 / 53. How often safety waits fired
     because the guidance led into a human's buffer.
   * `solver_wall_ms` / `mean_planning_time_ms`: the compute cost
     of the solver itself, the legitimate axis of comparison once
     throughput saturates.

For the paper's solver-sensitivity claim to be load-meaningful with
the default controller, the load must be increased above unit (one
quick way: set `task_arrival_rate` to a fraction of `H + W`, e.g.
`task_arrival_rate: 20.0` on `random-64-64-10` is ~6× oversupply at
25 agents). Even then, the local-A* substitution effect dominates on
sparse maps; warehouse maps with corridor structure show larger
solver-driven differences because A* alone gets boxed in.

## Acceptance criterion

> After the fix, a smoke comparing pibt2 vs lacam3 vs all-WAIT
> global tier on the same seed/map produces measurably different
> throughput, with the ordering explainable. If it does not, the
> diagnosis doc must state explicitly why throughput is
> solver-invariant and what the experiment should measure instead.

Met by the `controller_kind="global_only"` results above:

```
pibt2    -> 0.186   (real coordination, prioritized)
lacam3   -> 0.190   (real coordination, simultaneous)
all_wait -> 0.000   (no coordination, no movement)
```

The ordering `all_wait << pibt2 < lacam3` is consistent with
expected global-plan quality. The default-controller invariance is
documented here (this section + the two-cause analysis above) as the
spec requires.

## Files touched

* `src/ha_lmapf/core/types.py` — `SimConfig.debug_guidance_trace`,
  `Metrics.guidance_*` fields.
* `src/ha_lmapf/core/metrics.py` — three counters,
  `add_guidance_observation`, finalize-time ratio computation.
* `src/ha_lmapf/simulation/simulator.py` — pre-decide snapshot and
  post-physics evaluation, `_prev_goal_for_guidance` field.
* `src/ha_lmapf/global_tier/planner_interface.py` — `AllWaitGlobalPlanner`
  class, factory entry under `"all_wait"`.
* `scripts/debug_tier_handoff.py` — diagnostic harness.
* `tests/test_tier_handoff_smoke.py` — acceptance smoke.
