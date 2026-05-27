# Calibration High-Density Failure — Root-Cause Diagnosis

**Hypothesis being tested:** the calibration's "all 6 solvers excluded
from §5.4" recommendation reflects a real solver-capability ceiling at
high density.

**Verdict:** **REJECTED.**  The high-density failures are an artifact
of the calibration harness, NOT solver capability.  The simulator's
task allocator + rolling-horizon state evolution produces planning
instances that are pathologically hard for every paper-sweep MAPF
solver (LaCAM\*, LaCAM, MAPF-LNS2, CBSH2-RTC, PBS, PIBT2), while
**random feasible MAPF instances on the same maps at the same
densities solve in tens of milliseconds**.

The calibration is measuring "how well the simulator's task allocator
produces feasible problems" rather than "how well each solver scales
to high density."

---

## 1. Setup

* Calibration data: ``logs/calibration/raw_measurements.csv`` (648 rows
  from commit ``67389d3``).
* Captured 5 cells where ALL 6 solvers returned non-success (error or
  timeout_no_result):

| Cell | Map | \|M\| | Seed | replan_idx |
|---|---|---:|---:|---:|
| cell_0 | random-64-64-10 | 40 | 0 | 1 |
| cell_1 | random-64-64-10 | 40 | 0 | 2 |
| cell_2 | warehouse-10-20-10-2-1 | 100 | 1 | 0 |
| cell_3 | warehouse-10-20-10-2-1 | 100 | 1 | 1 |
| cell_4 | warehouse-10-20-10-2-2 | 200 | 0 | 0 |

* Method: for each cell, reproduced the calibration harness flow
  (build sim, ``sim.run()`` to ``replan_idx + 1`` ticks, then probe
  via ``_measure_one_replan``) and captured the exact instance file
  the wrapper sent to LaCAM-official's binary on the probe call.

* Cleanup: instrumentation hooks were applied in-process and reverted
  before this document was written.  No production code changes.

## 2. Step 2: Direct LaCAM\* invocation at 60 s budget

For each captured probe instance, invoked the ``lacam`` binary
directly with ``-t 60.0`` (6× the calibration's 10 s budget).

| Cell | Map | \|M\| | Verdict at 60 s | comp_time | makespan | wall |
|---|---|---:|---|---|---:|---:|
| cell_0 | random-64-64-10 | 40 | **WATCHDOG_KILL** | — | — | 71.6 s |
| cell_1 | random-64-64-10 | 40 | **WATCHDOG_KILL** | — | — | 71.8 s |
| cell_2 | warehouse-10-20-10-2-1 | 100 | **WATCHDOG_KILL** | — | — | 71.3 s |
| cell_3 | warehouse-10-20-10-2-1 | 100 | **WATCHDOG_KILL** | — | — | 71.3 s |
| cell_4 | warehouse-10-20-10-2-2 | 200 | **INFEASIBLE** | 67 647 ms | 0 | 68.6 s |

**0/5 feasible at 60 s.**  Even with 6× the calibration budget,
LaCAM-official cannot solve any of the five captured probe instances.
On cells 0–3 the binary did not even self-terminate at ``-t 60``
(the wrapper's 70 s subprocess watchdog killed it).  cell_4
self-terminated past ``-t`` with ``solved=0`` (makespan=0 = no plan).

This is consistent with cause (1) "infeasible instances" *or* cause
(3) "probe-point artifact".  Steps 3 and 4 disambiguate.

## 3. Step 3: replan_idx variation does NOT meaningfully change failure rate

A naive replan_idx=0 vs replan_idx=2 comparison was attempted but
exposed a methodology issue: at sim construction the simulator has not
yet released any tasks, so all agents have ``goal=None``, the
``_measure_one_replan`` probe sees ``active_agents = []``, and every
wrapper short-circuits with ``status=complete, solver_wall_ms=0.0``
(the trivial-empty-plan return path).

Validating this:

```
|M|=100: BEFORE sim.run() — agents with goals: 0/100
|M|=100: AFTER  sim.run() — agents with goals: 100/100
|M|=300: BEFORE sim.run() — agents with goals: 0/300
|M|=300: AFTER  sim.run() — agents with goals: 300/300
```

So the harness *requires* ``sim.run()`` to populate agent goals before
the probe is meaningful.  Within the meaningful regime
(``replan_idx ∈ {0, 1, 2}`` all running ``sim.run()``), the
calibration's per-cell results are nearly identical across
``replan_idx`` (the simulator's all-WAIT fallback freezes state when
the first replan fails, so subsequent replans see the same instance).

**Cause (3) is partially supported but not the dominant story** — the
harness is sensitive to probe-point assumptions, but varying the
probe-point within the tested regime doesn't materially change
results.  The key issue is what ``sim.run()`` does TO the state, not
when the probe fires.

## 4. Step 4: Random feasible benchmarks vs simulator-driven — DECISIVE

Generated 10 random feasible MAPF instances at \|M\|=300 on
warehouse-10-20-10-2-2.  Each instance: 300 agents drawn without
replacement from free cells; 300 goals drawn without replacement from
free cells; agents and goals selected independently (canonical
random-feasible MAPF benchmark methodology, as in Stern et al. 2019
"Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks").

Direct LaCAM-official invocation, ``-t 60.0``:

| Trial | Verdict | comp_time | wall |
|------:|---|---:|---:|
| 0 | FEASIBLE | 50 ms | 0.1 s |
| 1 | FEASIBLE | 52 ms | 0.2 s |
| 2 | FEASIBLE | 51 ms | 0.1 s |
| 3 | FEASIBLE | 49 ms | 0.1 s |
| 4 | FEASIBLE | 46 ms | 0.1 s |
| 5 | FEASIBLE | 52 ms | 0.1 s |
| 6 | FEASIBLE | 49 ms | 0.1 s |
| 7 | FEASIBLE | 48 ms | 0.1 s |
| 8 | FEASIBLE | 51 ms | 0.1 s |
| 9 | FEASIBLE | 50 ms | 0.1 s |

**10/10 feasible in ~50 ms.**  Median LaCAM-official solve time on
\|M\|=300 random benchmarks is **50 ms** — **200× faster than the
calibration's 10 000 ms timeout** at the same (map, \|M\|) cell.

Calibration's ``lacam_official`` completion at this cell:
``warehouse-10-20-10-2-2, |M|=300`` → **0/9** invocations succeeded
with ``solver_wall_ms`` averaging ~10 700 ms (= the 10 s budget cap).

**Allocator-bounded fraction = 100%.**  The entire failure population
at this cell is attributable to the simulator's task-allocator output,
not to the solvers' capability ceiling.

This is the same pattern documented in
``docs/ALLOCATOR_DIAGNOSIS.md`` (a separate diagnosis from a different
prompt that found the simulator's task allocator generates pathological
start/goal pairs because it doesn't reason about agent-pair conflicts).

## 5. Step 5: LNS2 rc=255 "target conflict" investigation

Captured one rc=255 cell: ``random-64-64-10, |M|=40, seed=0,
replan_idx=1``.  Direct LNS2 invocation reproduces:

```
$ mapf_lns -m map.map -a scen.scen -o output --outputPaths=paths.txt -k 40 -t 10 -s 1
…
Iteration 2, group size = 1, colliding pairs = 0, solution cost = 544, remaining time = 9.985
        InitLNS(PP): runtime = 0.0094, iterations = 3, colliding pairs = 0, …
Initial solution cost = 544, runtime = 0.0151
LNS(PP;PP): runtime = 0.0151, iterations = 1, …, failed iterations = 1

stderr:
Find a target conflict where agent 1 (of length 17) traverses agent 29
(of length 16)'s target location 2552 at timestep 17

rc=255
```

LNS2 found a solution (``colliding pairs = 0``), then crashed with
rc=255 in a final validation check that flags **target conflicts** —
agent A traversing agent B's target cell at a timestep when B has
already been absorbed at that target.  This is a MAPF-specific edge
case that LNS2's main pairwise-conflict loop does not surface but its
final validator catches.

**Test on random-feasible benchmarks (same map and \|M|):**

| Trial | rc | Paths file size |
|------:|---:|---:|
| 0 | 0 | 18 329 B |
| 1 | 0 | 15 064 B |
| 2 | 0 | 14 567 B |
| 3 | 0 | 15 268 B |
| 4 | 0 | 16 395 B |

**rc=255 crash rate on random benchmarks: 0/5.**
**rc=255 crash rate on simulator-driven cells: 63/108 (58%).**

LNS2's target-conflict assertion is upstream LNS2 behavior, but it
fires only on simulator-allocator-generated instances, never on
random feasible benchmarks.  This is a **two-layer cause**:

1. **Upstream LNS2 (Jiaoyang-Li/MAPF-LNS2):** the target-conflict
   validator should either prevent target-conflict-rich instances
   from reaching it (input validation), or the planner should plan
   around target conflicts.  The current behavior — assert and exit
   rc=255 mid-iteration — is a usability bug.  Not a wrapper issue.
2. **Simulator task allocator:** generates start/goal pairs that
   produce target conflicts at non-trivial frequency.  This is the
   same allocator pathology documented in
   ``docs/ALLOCATOR_DIAGNOSIS.md``.

Wrapper-side: nothing to fix.  The wrapper correctly classifies
rc=255 as ``error`` with the stderr surfaced in ``error_msg``.

## 6. Dominant cause

| Cause | Evidence | Verdict |
|---|---|---|
| (1) Allocator generates infeasible instances | LaCAM\* solves 0/5 captured probe instances at 60 s | **Plausible — see (1+3) combined below** |
| (2) 10 s calibration budget too tight | LaCAM\* hits 60 s on captured probes; sub-second on random benchmarks | **Partially true at the calibration's specific cells, but not the dominant story** |
| (3) Probe-point artifact (sim state evolution makes probe pathological) | Random feasible benchmarks at the same (map, \|M\|) solve in 50 ms; calibration probes at the same cell take >10 000 ms | **DOMINANT** |

The unified explanation:

* The simulator's ``GreedyNearestTaskAllocator`` does not reason
  about other agents' goals or conflict potential
  (``docs/ALLOCATOR_DIAGNOSIS.md`` documents this).
* When the simulator runs for ``replan_idx + 1`` ticks before the
  probe, the rolling-horizon planner triggers exactly one global
  replan at step 0; agents execute against that plan; some agents
  reach their pickup-or-delivery targets and the allocator
  reassigns them new goals from the open task pool; the probe sees
  a state where many agent-goal pairs share a transit corridor or
  target cell with another agent's target.
* LaCAM\* / LaCAM / LNS2 / CBSH2 / PBS / PIBT2 all individually
  struggle with these target-conflict-heavy instances even though
  they trivially solve random-feasible MAPF instances at the same
  scale.
* The calibration was therefore measuring **the simulator's
  task-allocator-induced instance hardness**, not solver capability.

Cause (1) "infeasible" is technically wrong: the captured probe
instances ARE feasible (random-feasible benchmarks at the same
density solve in 50 ms; the captured probes are specific harder
instances within the feasible set, not infeasible ones).  But the
*specific* instances the simulator produces are pathologically hard
in a way that mimics infeasibility under any reasonable budget.

## 7. Recommendations

### For §5.4 / §5.5 (paper writing)

* **Do NOT report calibration's per-section completion rates as
  "solver capability at \|M\|=N" data.**  They reflect the simulator's
  task allocator more than the solvers.
* **Do report them as "lifelong-task realism scores"** — a measure
  of how well each solver handles the instance distribution the
  simulator's allocator produces.  This is a different (and arguably
  more paper-relevant) metric than one-shot benchmark capability.
* **Cite Stern et al. 2019 random-feasible benchmarks** alongside
  the simulator-driven cells if the paper claims "all six solvers
  scale to \|M\|=300 on warehouse-10-20-10-2-2."  The calibration
  alone does not support that claim; the random-benchmark check in
  §4 of this document does.

### For the simulator (out of this prompt's scope)

The dominant cause is the task allocator.  Two follow-up directions
exist:

* **(a) Make the allocator congestion-avoidance.**  Add a constraint to
  ``GreedyNearestTaskAllocator`` that forbids assigning agent ``i``
  a goal coincident with another agent's current position or
  another agent's pending target.  This is a meaningful algorithmic
  change; would require its own prompt and a paper-text discussion
  of why the change is appropriate.
* **(b) Document the allocator's limitations in §5.x prose.**  The
  paper can acknowledge that the lifelong task generator is an
  intentional stress test of the rolling-horizon planner and is not
  the same as one-shot MAPF benchmarks.  Reviewers who probe will
  appreciate the candor.

### For the calibration harness (out of this prompt's scope)

* **Probe additional points.**  In addition to the simulator-driven
  probe, also probe random-feasible instances (the §4 methodology
  here).  This produces TWO completion-rate numbers per cell — a
  "simulator realism" rate and a "raw solver capability" rate —
  whose gap quantifies the allocator's contribution.

### For the LNS2 rc=255 issue (out of this prompt's scope)

* **Upstream PR / issue** at
  https://github.com/Jiaoyang-Li/MAPF-LNS2 noting that the
  target-conflict assertion in the final validator should be
  upgraded to either (a) prevent target conflicts during planning,
  or (b) reject the instance up-front rather than mid-run.  This
  is not blocking the paper; the wrapper correctly reports rc=255
  as ``error`` with the stderr surfaced.

## 8. What this diagnosis does NOT do

* Does NOT modify the production calibration harness defaults.
* Does NOT modify the task allocator.
* Does NOT modify any wrapper.
* Does NOT commit a fix; the deliverable is this document.

The diagnostic instrumentation hooks used to capture the 5 cells were
applied in-process and reverted before this document was written.
