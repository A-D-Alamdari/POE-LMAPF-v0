# HA-LMAPF Simulation Metrics Reference

This document describes every metric recorded by the simulator, how it is
computed from raw simulation events, and why it matters for evaluating
Human-Aware Lifelong Multi-Agent Path Finding under Partial Observability (HA-LMAPF) systems.

---

## Table of Contents

1. [Service Quality](#1-service-quality)
2. [Safety](#2-safety)
3. [Efficiency and Planning](#3-efficiency-and-planning)
4. [Human-Robot Interaction (HRI)](#4-human-robot-interaction-hri)
5. [Timing (Wall-Clock)](#5-timing-wall-clock)
6. [Cost-Based](#6-cost-based)
7. [Delay and Assignment Stability](#7-delay-and-assignment-stability)
8. [Statistical Aggregation in Tuning](#8-statistical-aggregation-in-tuning)
9. [Metric Relationships and Interpretation Guide](#9-metric-relationships-and-interpretation-guide)
10. [Recommended Metric Hierarchy for Reporting](#10-recommended-metric-hierarchy-for-reporting)

---

## 1. Service Quality

These metrics measure how well the fleet delivers tasks.

---

### `throughput`

**Formula:**

```
throughput = completed_tasks / total_steps
```

**When it is updated:** Computed once at the end of the simulation in
`MetricsTracker.finalize()`.

**What it measures:** The empirical average task delivery rate over the
executed simulation horizon — tasks completed per simulation step. This is
the primary performance indicator for lifelong MAPF. A value of `0.05`
means the fleet delivers one task every 20 steps on average.

> **Note:** This is a finite-horizon average, not a guaranteed steady-state
> estimate. It approximates steady-state throughput when the run is long
> enough that startup transients and end-of-horizon truncation are small
> relative to the total horizon.

**Importance:** Throughput directly captures the productive output of the
fleet. It is the single most important metric for comparing configurations
because it integrates the effects of task allocation, planning quality,
congestion, and safety constraints into one number. All other metrics
explain *why* throughput is high or low.

**Sensitivity notes:**

- Increases with `num_agents` until congestion saturates the map.
- `task_arrival_rate` in the implementation is an **inter-arrival interval
  in steps** (not a rate): larger values mean sparser arrivals. Throughput
  drops when `task_arrival_rate` is very large (rare arrivals → agents idle)
  or very small (dense arrivals → queue backlog, agents permanently busy).
- Hard safety constraints (`hard_safety=True`) may reduce throughput if
  agents are frequently blocked by human safety zones.

---

### `completed_tasks`

**Formula:** Raw integer count. Incremented by `on_task_completed()` each
time an agent reaches the delivery cell (Phase 2 completion).

**What it measures:** The total number of full pickup-delivery cycles
finished in the simulation run.

**Importance:** The unnormalized counterpart to throughput. Useful for
sanity-checking that `throughput = completed_tasks / steps`.

---

### `mean_flowtime`

**Formula:**

```
flowtime_i = completed_step_i - release_step_i
mean_flowtime = mean(flowtime_i)  for all completed tasks i
```

**When it is updated:** Computed in `finalize()` by iterating over all
task records that have a non-None `completed_step`.

**What it measures:** On average, how many steps elapse from the moment a
task appears in the system until an agent delivers it. This includes:

- Time waiting in the open task queue (not yet assigned).
- Time for the agent to travel to the pickup location.
- Time for the agent to travel from pickup to delivery.

**Importance:** Flowtime is the end-to-end latency experienced by each
task. High mean flowtime indicates the system is falling behind: either
tasks are queuing for a long time before assignment, or agents take
indirect routes. It is a standard benchmark metric in lifelong MAPF.

**Sensitivity notes:**

- Increases with `num_humans` because agents must detour around humans.
- Increases when `task_arrival_rate` is low relative to fleet size (agents
  must travel far between tasks, increasing release-to-pickup gap).
- Decreases with more agents (shorter queue wait) up to the congestion
  point.

---

### `median_flowtime`

**Formula:** `median(completed_step_i - release_step_i)`

**What it measures:** The 50th percentile flowtime, robust to outliers
caused by tasks that were accidentally delayed or re-queued.

**Importance:** Use alongside `mean_flowtime`. A large gap between mean and
median indicates that a small number of tasks experience extreme delays
(long tail), which may signal a deadlock-prone configuration.

---

### `max_flowtime`

**Formula:** `max(completed_step_i - release_step_i)`

**What it measures:** The worst-case end-to-end latency observed in the
run. A single task that was never completed is excluded (only completed
tasks are counted).

**Importance:** Flags extreme outliers. In a well-functioning system, max
flowtime should be bounded. A very large max flowtime relative to mean
flowtime suggests occasional severe congestion or near-deadlock events.

> **Stability note:** `max_flowtime` is highly seed-sensitive and not
> recommended as a primary publication metric. Prefer `p90_flowtime` and
> `p95_flowtime` for more stable tail characterisation.

---

### `p90_flowtime`, `p95_flowtime`, `p99_flowtime`

**Formula:**

```
p90_flowtime = percentile(flowtime_i, 90)
p95_flowtime = percentile(flowtime_i, 95)
p99_flowtime = percentile(flowtime_i, 99)
```

**What it measures:** Upper-tail end-to-end latency. These complement
`median_flowtime` and `mean_flowtime` by characterising how the worst
fraction of tasks are served.

**Importance:** Percentile latency is substantially more stable across
seeds than `max_flowtime` and is the standard tail-latency reporting
convention in systems research. A large gap between `p95_flowtime` and
`median_flowtime` indicates a heavy-tailed latency distribution — a small
fraction of tasks experience disproportionate delays. Reporting `p95`
alongside mean and median is the minimum recommended set for a paper.

---

### `task_completion_ratio`

**Formula:**

```
task_completion_ratio = completed_tasks / released_tasks
```

**What it measures:** The fraction of all tasks that entered the system
(were released into the queue) and were subsequently completed within the
simulation horizon.

**Importance:** `throughput` can be misleadingly high if the arrival rate
is low. `task_completion_ratio` reveals whether the fleet is keeping up
with demand. A ratio below 1.0 means the system is accumulating backlog;
a ratio at or near 1.0 confirms the fleet is not overloaded at the tested
arrival rate.

---

### `mean_service_time`

**Formula:**

```
service_time_i = completed_step_i - assigned_step_i
mean_service_time = mean(service_time_i)
```

**When it is updated:** Computed in `finalize()`. Only tasks with both
`assigned_step` and `completed_step` recorded are included.

**What it measures:** The average time from when a task was *assigned to a
specific agent* until that agent delivered it. Unlike flowtime, this
excludes queue wait time and isolates the agent execution quality.

**Importance:** A large `mean_service_time` relative to the Manhattan
distance from pickup to delivery means agents are taking many detours or
waiting frequently during execution. This metric isolates planner quality
from allocator quality. If `mean_flowtime` is high but `mean_service_time`
is low, the bottleneck is in the task queue (allocator or arrival rate),
not in agent navigation.

> **Requeue caveat:** If a task is returned to the queue and later
> reassigned, `assigned_step` is overwritten with the new assignment time.
> Therefore `mean_service_time` reflects the final successful assignment
> episode only — not the cumulative service burden across failed attempts.
> For full assignment history, see `mean_assignments_per_task` in
> Section 7.

---

## 2. Safety

These metrics measure how safely agents operate around humans.

---

### `collisions_agent_agent`

**Formula:** Incremented in `_detect_collisions_and_near_misses()`:

- **Vertex collision:** `+= (n - 1)` for each cell occupied by `n > 1`
  agents simultaneously (conservative: counts excess agents per cell).
- **Edge (swap) collision:** `+= 1` for each pair `(a, b)` where
  `prev[a] == new[b]` and `prev[b] == new[a]` and agents actually moved
  (not both waiting in place).

**What it measures:** Physical conflicts between two robots. In a correct
MAPF solution, this should be zero. A nonzero value indicates the global
or local planner produced conflicting paths.

**Importance:** Agent-agent collisions are a hard correctness criterion.
They represent hardware damage risk in a real deployment. Any nonzero count
signals a planner bug or a configuration where the local replanner produces
paths that conflict with other agents' movements.

**Sensitivity notes:**

- Increases with `num_agents` (more agents, higher collision probability
  in narrow corridors).
- Increases when `disable_conflict_resolution=True` (ablation).

---

### `collisions_agent_human`

**Formula:** `+= 1` for each agent that ends a step on the same cell as
any human.

**What it measures:** Physical contact events between a robot and a person.
These are the most serious safety events in the simulation.

**Importance:** Agent-human collisions represent the failure of the entire
safety layer. In a properly configured system with `hard_safety=True` and
adequate `fov_radius`, this should be zero or near-zero. A nonzero value
indicates either:

- The `fov_radius` is too small (agent cannot see the human in time).
- The `safety_radius` is zero (no forbidden zone).
- A deadlock forced the agent through the human position.

---

### `near_misses`

**Formula:**

```
+= 1 for each agent a where:
  min over all humans h of: |a.row - h.row| + |a.col - h.col| == 1
```

Checked at the end of each step in `_detect_collisions_and_near_misses()`.
Each agent contributes at most **1** near miss per step (the `break` after
the first human within distance 1 prevents double-counting). Distance 0
(same cell) is counted as `collisions_agent_human`, not a near miss.

**Key property:** Near miss is **independent of `safety_radius`**. It is
always defined as exactly Manhattan distance = 1 to any human. This makes
it a comparable safety indicator across the `safety_radius` sweep, where
`safety_violations` is confounded by the changing forbidden zone size.

**What it measures:** How frequently agents come dangerously close to
humans. A near miss at distance 1 means one more step in the same direction
would have caused a collision.

**Importance:** Near misses are the primary human safety metric for
hyperparameter analysis. Unlike `collisions_agent_human` (which should
ideally be zero and thus gives little gradient for optimization),
`near_misses` provides a continuous safety signal that reflects how tight
the margins are. High near-miss rates signal that the safety buffer
(`safety_radius`) or perception range (`fov_radius`) is insufficient.

---

### `safety_violations`

**Formula:**

```
forbidden = inflate_cells(human_positions, radius=safety_radius, env)
+= 1 for each agent that ends a step inside `forbidden`
```

Checked every step. Skipped entirely when `disable_safety=True`.

**What it measures:** How often an agent enters the forbidden zone
`B_r(H_t)` that surrounds each human at the configured `safety_radius`.
This is the formal safety constraint defined in the paper.

**Importance:** Safety violations count formal constraint breaches. Unlike
near misses, this metric *is* confounded by `safety_radius` — a larger
radius defines a larger forbidden zone so violations are counted for cells
that would not be violations at a smaller radius. Therefore:

- Use `near_misses` as the primary safety metric when sweeping
  `safety_radius`.
- Use `safety_violations` as the primary safety metric when comparing
  configurations at the same `safety_radius`.

---

### `safety_violation_rate`

**Formula:**

```
safety_violation_rate = safety_violations / total_steps * 1000
```

**What it measures:** Safety violations normalized per 1000 simulation
steps. Makes long-run and short-run results comparable.

**Importance:** A rate metric is essential for comparing runs of different
lengths or with different task arrival rates. Use this instead of the raw
count when comparing across sweeps.

---

## 3. Efficiency and Planning

These metrics diagnose *why* throughput is what it is, by decomposing
waiting and replanning behavior.

---

### `total_wait_steps`

**Formula:** `+= 1` for each agent each step where:

- The agent's action is `WAIT`, AND
- The agent **has a task assigned** (`goal is not None`).

**What it measures:** The total number of agent-steps spent blocked during
task execution. This includes:

- Waiting for another agent to clear a corridor (congestion).
- Waiting because the human safety zone blocks the path (`hard_safety`).
- Waiting due to an injected execution delay (`execution_delay_prob`).

**Critical distinction:** Idle waits (no task assigned) are **not**
counted here. They are recorded separately in `idle_wait_steps`. This
separation ensures that `total_wait_steps` is a clean measure of
*execution friction* — delays caused by the environment and other agents,
not by task availability.

**Importance:** High `total_wait_steps` while throughput is acceptable
means the system wastes motion budget on detours and blockages. High
`total_wait_steps` while throughput is low confirms the system is gridlocked.
This is a primary metric for the Wilcoxon significance tests in tuning.

---

### `idle_wait_steps`

**Formula:** `+= 1` for each agent each step where:

- The agent's action is `WAIT`, AND
- The agent **has no task assigned** (`goal is None`).

**What it measures:** Steps agents spend idle, waiting for a new task to
arrive. This is determined entirely by `task_arrival_rate` and fleet size
relative to task load — not by planner quality.

**Importance:** A high `idle_wait_steps` count indicates the task arrival
rate is too low for the fleet size (agents finish tasks faster than new
ones arrive). It is kept separate from `total_wait_steps` so that
task-arrival gaps do not inflate the execution wait statistics and mislead
the hyperparameter tuning analysis.

**Interpretation:**

```
total_wait_steps  → planner / congestion quality
idle_wait_steps   → task load balance (arrival rate vs fleet size)
```

---

### `global_replans`

**Formula:** `+= 1` each time the Tier-1 Rolling Horizon Planner runs a
new planning call (`maybe_global_replan()` triggers the solver).

**What it measures:** How many times the global planner was invoked during
the simulation.

**Importance:** Reflects computational load on the global planner.
With default settings, global replanning occurs every `replan_every` steps
plus on task completion events. More replans mean more up-to-date paths
but higher CPU cost.

---

### `local_replans`

**Formula:** `+= 1` each time a Tier-2 local A* replan is triggered for
any agent.

**What it measures:** How many Tier-2 interventions were required. Local
replans occur when an agent is blocked by another agent or by a human and
the local controller reroutes independently without invoking the global
planner.

**Importance:** Local replans are cheap (single-agent A*) but indicate that
the global plan has become invalid or that agents are frequently blocked.
A high `local_replans / global_replans` ratio indicates the local tier is
doing heavy lifting — the global plans are frequently stale or invalid.

---

### `replans`

**Formula:** `+= 1` at the same time as every `global_replan`. Currently
equivalent to `global_replans`.

**Note:** Provided for backward compatibility. Use `global_replans` and
`local_replans` for detailed analysis.

---

### `intervention_rate`

**Formula:**

```
intervention_rate = global_replans / total_steps * 1000
```

**What it measures:** How frequently the global planner must intervene,
per 1000 steps.

**Importance:** A high intervention rate means the system is frequently
invalidating its own plans (e.g., due to human movements or agent
deviations). This is a measure of plan stability. Excessive intervention
rate can hurt throughput because each global replan incurs solver latency.

> **Normalisation note:** Raw `global_replans` and `local_replans` counts
> are hard to compare across runs with different horizons or task loads.
> Prefer derived ratios such as:
> - `replans_per_completed_task = global_replans / completed_tasks`
> - `local_per_global_ratio = local_replans / global_replans`
> - `planning_ms_per_task = sum(planning_times_ms) / completed_tasks`

---

### `mean_open_queue`, `max_open_queue`

**Formula:**

```
mean_open_queue = (1/T) * sum over t of |open_tasks_t|
max_open_queue  = max over t of |open_tasks_t|
```

Sampled every step.

**What it measures:** The size of the unassigned task backlog over time.
`mean_open_queue` is the time-averaged queue depth;
`max_open_queue` is the peak backlog seen during the run.

**Importance:** These metrics expose the operating regime of the system:

| Regime      | Typical signature                                             |
|-------------|---------------------------------------------------------------|
| Underloaded | `mean_open_queue ≈ 0`, high `idle_wait_steps`                 |
| Balanced    | `mean_open_queue` small and stable                            |
| Overloaded  | `mean_open_queue` grows steadily, `task_completion_ratio < 1` |

Without a backlog metric, low throughput and high flowtime are ambiguous —
the cause could be either empty queues (underload) or swelling queues
(overload). `mean_open_queue` resolves this ambiguity.

---

### `mean_agent_utilization`

**Formula:**

```
utilization_i      = steps_with_assigned_task_i / T
mean_agent_utilization = mean(utilization_i)  over all agents i
```

**What it measures:** The fraction of simulation time the average agent
spent working on an assigned task (as opposed to being idle).

**Importance:** Utilization is the standard link between fleet load and
throughput:

- Low throughput + low utilization → underloaded; add tasks or reduce agents.
- Low throughput + high utilization → congestion; the fleet is busy but
  not productive.
- High throughput + high utilization → efficient, high-load operation.

This metric is essential for interpreting throughput changes across
`num_agents` or `task_arrival_rate` sweeps.

---

### `utilization_gini`

**Formula:**

```
utilization_gini = Gini coefficient of (utilization_i) over all agents
```

**What it measures:** Fairness of task load distribution across agents.
A value of 0 means all agents are equally loaded; 1 means one agent does
all the work.

**Importance:** A system can achieve good aggregate throughput while
heavily overloading a subset of agents (e.g., those near hotspot task
locations). High `utilization_gini` signals spatial or allocator-induced
unfairness that would accelerate wear on a real fleet. This should be
monitored alongside `mean_agent_utilization`.

---

### `service_wait_ratio`

**Formula:**

```
service_wait_ratio = total_wait_steps / total_assigned_agent_steps
```

where `total_assigned_agent_steps` is the sum of all steps across all
agents while they held an assigned task.

**What it measures:** The fraction of time-under-assignment that was spent
waiting rather than moving. A value of 0.0 means every assigned step was a
move; a value of 0.5 means agents waited half the time they were carrying
an assignment.

**Importance:** This is a cleaner measure of execution friction than raw
`total_wait_steps`, because it normalises by how much time agents actually
spent working. High `service_wait_ratio` indicates the planner frequently
stalls agents during service — due to congestion, safety zones, or stale
global plans.

---

## 4. Human-Robot Interaction (HRI)

---

### `human_passive_wait_steps`

**Formula:**

```
for each stationary human h (velocity == (0,0)):
    if any agent is within safety_radius of h:
        += 1
```

Checked every step in `_detect_collisions_and_near_misses()`.

**What it measures:** A model-dependent proxy for robot-induced human
disruption. A stationary human (`velocity == (0,0)`) with an agent within
`safety_radius` is assumed to be waiting for the robot to pass. This is an
inference, not a direct observation — the human may also be stationary due
to its own trajectory policy or a pause in its planned route unrelated to
any agent.

**Importance:** This is the primary HRI quality metric from the human's
perspective. It measures the *disruption cost* imposed on human workers by
the robot fleet. A system that is efficient for the robots but constantly
forces humans to stop is not acceptable in a real warehouse.

High `human_passive_wait_steps` can indicate:

- Too many agents operating in human-dense areas.
- The safety radius is too large, creating wide forbidden zones that push
  humans into waiting positions.
- Human model behavior causes humans to linger near agent paths.

---

## 5. Timing (Wall-Clock)

These metrics record real computation time, not simulation steps. They are
critical for assessing whether a configuration is deployable in real time.

---

### `mean_planning_time_ms`, `p95_planning_time_ms`, `max_planning_time_ms`

**Formula:**

```
planning_times = list of wall-clock durations (ms) for each global replan call
mean_planning_time_ms = mean(planning_times)
p95_planning_time_ms  = percentile(planning_times, 95)
max_planning_time_ms  = max(planning_times)
```

**What it measures:** Wall-clock time consumed by the Tier-1 global solver
(CBS or LaCAM) for each planning invocation.

**Importance:**

- `mean_planning_time_ms`: Average planning overhead per replan interval.
- `p95_planning_time_ms`: The 95th-percentile worst case — what the system
  experiences 5% of the time. This is the operational latency bound.
- `max_planning_time_ms`: The absolute worst case. If this exceeds the
  `time_budget_ms` cap, the solver was cut off and returned an incomplete
  plan.

**Sensitivity notes:**

- CBS scales exponentially with `num_agents` and is impractical above ~30
  agents.
- LaCAM scales gracefully to 150+ agents but produces suboptimal paths.
- Long `horizon` values increase planning time for both solvers.

---

### `mean_decision_time_ms`, `p95_decision_time_ms`

**Formula:**

```
decision_times = list of wall-clock durations (ms) for each full simulation step
mean_decision_time_ms = mean(decision_times)
p95_decision_time_ms  = percentile(decision_times, 95)
```

**What it measures:** Total wall-clock time to execute one simulation step
(all agents making decisions, local replanning, collision detection, task
completion logic).

**Importance:** For real-time deployment, each step must complete within
the physical time budget (e.g., 1 second per step in a real warehouse).
High `p95_decision_time_ms` flags configurations that occasionally stall
the control loop. Large agent counts and frequent local replanning are the
main drivers.

---

## 6. Cost-Based

These metrics are standard MAPF cost measures, adapted for the lifelong
pickup-delivery setting.

---

### `makespan`

**Formula:**

```
makespan = max(completed_step_i)  over all completed tasks i
```

Updated incrementally: each time a task completes, `update_makespan(step)`
checks whether the current step is a new maximum.

**What it measures:** The simulation step at which the last task was
delivered. In one-shot MAPF, makespan is the primary objective.

> **Lifelong MAPF note:** In a lifelong setting with a fixed simulation
> horizon, makespan is an **auxiliary** metric only. Because tasks arrive
> continuously, makespan mostly reflects the horizon length and the
> completion time of the final task, not fleet efficiency. Use `throughput`
> and `mean_flowtime` as primary objectives. Makespan is useful as a
> sanity-check bound — confirming all arriving tasks were eventually
> cleared — but should not be used for cross-configuration comparisons.

---

### `sum_of_costs`

**Formula:**

```
cost_i = completed_step_i - assigned_step_i
sum_of_costs = sum(cost_i)  over all completed tasks
```

**What it measures:** The cumulative execution-time cost from assignment to
delivery, summed across all completed tasks. This counts every step
(movement *and* waiting) that elapsed between assignment and delivery.
It is analogous to the classical MAPF sum-of-costs objective but includes
waiting time, safety-induced pauses, and stochastic delays — not just
geometric path length.

**Importance:** A lower sum-of-costs means agents are taking more direct
routes. High sum-of-costs relative to the sum of Manhattan distances from
pickup to delivery indicates detour overhead imposed by congestion or
human avoidance.

---

## 7. Delay and Assignment Stability

These metrics track robustness to execution noise and the stability of
task-agent assignments over time.

---

### `delay_events`

**Formula:** `+= 1` each time an agent's intended move is stochastically
delayed (controlled by `execution_delay_prob`).

**What it measures:** The number of times an execution delay was injected.
With `execution_delay_prob=0.1` and 20 agents over 5000 steps, the
expected count is `0.1 × 20 × 5000 = 10000` delay events.

**Importance:** In the execution delay sweep, `delay_events` confirms the
noise model is working as expected. The effect of delays on `throughput`
and `total_wait_steps` measures the system's robustness to execution
uncertainty.

---

### `immediate_assignments`

**Formula:** `+= 1` each time a task is assigned to an agent at the
instant that agent completes its previous task (no queue wait).

**What it measures:** How often the allocator can immediately chain a new
task onto a just-freed agent. High immediate assignments indicate the task
queue always has work available for agents.

**Importance:** The raw count scales with run length and fleet output, so
prefer the derived ratio for cross-run comparisons:

```
immediate_assignment_ratio = immediate_assignments / completed_tasks
```

A high ratio means the fleet is fully loaded and agents rarely go idle
between tasks. A low ratio means the task arrival rate is too slow for the
fleet size.

---

### `assignments_kept`

**Formula:** `+= 1` each time an existing task-agent assignment is
retained because the `commit_horizon` lock has not yet expired.

**What it measures:** How often the task allocator's commitment mechanism
prevents re-optimization of existing assignments.

**Importance:** At `commit_horizon > 0`, the allocator suppresses
reassignment for a fixed number of steps after issuing a plan. A high
`assignments_kept` count with good throughput validates that commitment
reduces plan thrashing without hurting performance.

---

### `assignments_broken`

**Formula:** `+= 1` each time a committed assignment is overridden
(commitment expired or a break condition was triggered).

**What it measures:** How often the system decides to abandon a committed
assignment despite the lock.

**Importance:** Together with `assignments_kept`, this characterizes the
stability of the task allocation over time. A very high `assignments_broken`
relative to `assignments_kept` suggests the `commit_horizon` is too short
or the `delay_threshold` is too aggressive in reclaiming tasks.

---

### `tasks_requeued`

**Formula:** `+= 1` each time a task is returned to the open queue after
having previously been assigned to an agent.

**What it measures:** The count of failed service episodes — how often the
system decided (or was forced) to give up on a task mid-execution and put
it back into the pool.

**Importance:** Frequent requeueing indicates the execution-aware
commitment mechanism is unstable or that execution delays and safety
blockages are causing widespread plan abandonment. High `tasks_requeued`
combined with good throughput is acceptable; high `tasks_requeued` with
low throughput indicates the fleet is churning on the same tasks
repeatedly.

---

### `mean_assignments_per_task`

**Formula:**

```
mean_assignments_per_task = total_assignment_events / completed_tasks
```

where `total_assignment_events` counts every assignment (including
reassignments after requeue).

**What it measures:** On average, how many times a task was assigned
before it was finally delivered. A value of 1.0 means every task was
completed on its first assignment. Values above 1.0 indicate requeueing.

**Importance:** This is the most interpretable summary of assignment
stability. It complements `tasks_requeued` by normalizing the requeue
count against productive output. It directly measures the overhead cost of
the commitment and requeue mechanism relative to actual task delivery.

---

## 8. Statistical Aggregation in Tuning

When running hyperparameter tuning (`run_hyperparameter_tuning.py`), every
metric is recorded per seed. The aggregation step (`aggregate_results()`)
computes the following for **all** metrics:

```
{metric}_mean   = mean across seeds
{metric}_std    = sample standard deviation across seeds (ddof=1)
```

For the **six primary metrics** listed below, a Wilcoxon signed-rank test
is also computed:

```
{metric}_wilcoxon_p
```

This p-value tests whether the distribution of values across seeds differs
significantly from the baseline (the group with the lowest parameter value
in the same sweep, or `full_system` for ablations).

**Primary metrics (get Wilcoxon p-values):**

| Metric              | Why it is primary                                    |
|---------------------|------------------------------------------------------|
| `throughput`        | Main performance objective                           |
| `mean_flowtime`     | End-to-end latency                                   |
| `near_misses`       | Comparable safety indicator (radius-independent)     |
| `safety_violations` | Formal safety constraint breaches                    |
| `total_wait_steps`  | Execution friction (blocked waits during tasks only) |
| `idle_wait_steps`   | Task load balance indicator                          |

A Wilcoxon p-value < 0.05 indicates that the parameter value produces a
statistically significant difference from the sweep baseline, justifying
the conclusion that this parameter materially affects system behavior.

**Multiple-comparison note:** When testing many parameter values against
the same baseline across multiple metrics in a single sweep, consider
applying a Holm–Bonferroni correction to control the family-wise error
rate. Without correction, the probability of at least one spurious
significant result grows with the number of comparisons.

**Confidence intervals:** In addition to mean and sample standard
deviation, consider reporting 95% confidence intervals for primary
metrics:

```
CI_95 = mean ± (1.96 * std / sqrt(num_seeds))
```

or bootstrap confidence intervals if the seed count is small (< 10).
Confidence intervals communicate variability more directly than standard
deviation alone and are preferred in publication tables.

---

## 9. Metric Relationships and Interpretation Guide

```
throughput ──────── primary output (tasks / step)
    │
    ├─ LOW throughput causes:
    │       ├── high total_wait_steps   → congestion or safety blocking
    │       ├── high mean_flowtime      → long routes or queue backlog
    │       └── high idle_wait_steps    → task arrival rate too low
    │
    └─ HIGH throughput with:
            ├── high near_misses        → unsafe (reduce safety_radius or fov)
            ├── high collisions         → planner correctness failure
            └── high human_passive_wait → disruptive to human workers
```

**Key rule:** `total_wait_steps` and `idle_wait_steps` are mutually
exclusive:

```
total_wait_steps  = waits WHILE agent has a task (blocked/safety)
idle_wait_steps   = waits WHILE agent has NO task (queue empty)
```

The sum of both represents every WAIT action taken in the simulation:

```
all_waits = total_wait_steps + idle_wait_steps
```

**Near misses vs safety violations:**

- Sweep `safety_radius` → use `near_misses` (independent of radius).
- Compare configurations at fixed `safety_radius` → use `safety_violations`.

These two metrics are **not substitutes**. They answer different questions:

- `near_misses`: geometry-based proximity risk, comparable across radii.
- `safety_violations`: policy-based formal constraint breaches, comparable
  only at the same radius.

**Planning time vs decision time:**

- `mean_planning_time_ms` is per global-replan call (periodic, expensive).
- `mean_decision_time_ms` is per simulation step (continuous, lower bound
  on control loop latency).

**High throughput is not sufficient on its own.** A configuration can rank
first on throughput and still be unacceptable if it also exhibits:

- high `near_misses` (safety margin too tight),
- high `human_passive_wait_steps` (unacceptable disruption to workers),
- high `p95_decision_time_ms` (control loop not real-time feasible),
- high `mean_assignments_per_task` (assignment thrashing).

Throughput is the primary *efficiency* objective; it is not the sole
decision criterion in HA-LMAPF.

**Diagnosing low throughput with the new backlog/utilization metrics:**

```
low throughput + low mean_open_queue + high idle_wait_steps
    → underloaded (reduce fleet or increase arrival rate)

low throughput + high mean_open_queue + high mean_agent_utilization
    → overloaded / congested (increase fleet or reduce arrival rate)

low throughput + high service_wait_ratio + moderate mean_open_queue
    → planner producing excessive waits during execution
```

**`delay_events` is a disturbance-model sanity check, not an outcome.**
Its primary use is to confirm that the injected noise level matches the
configured `execution_delay_prob`. Interpret it alongside `throughput`,
`total_wait_steps`, and `global_replans` to measure robustness to
execution uncertainty.

---

## 10. Recommended Metric Hierarchy for Reporting

The following classification is recommended for structuring paper results
tables and discussion.

### Primary outcome metrics

These decide whether a configuration is good. Report them in every
experiment table.

| Metric                     | What it decides         |
|----------------------------|-------------------------|
| `throughput`               | Fleet productive output |
| `mean_flowtime`            | End-to-end task latency |
| `near_misses`              | Human safety margin     |
| `human_passive_wait_steps` | HRI disruption          |
| `p95_decision_time_ms`     | Real-time feasibility   |

### Secondary diagnostic metrics

These explain *why* the primary metrics moved. Include in supplementary
tables or when a primary metric changes unexpectedly.

| Metric                                          | What it diagnoses                         |
|-------------------------------------------------|-------------------------------------------|
| `mean_service_time`                             | Execution quality vs allocation quality   |
| `total_wait_steps`                              | Execution friction (congestion / safety)  |
| `idle_wait_steps`                               | Task load balance                         |
| `mean_open_queue`                               | Backlog / operating regime                |
| `mean_agent_utilization`                        | Fleet load level                          |
| `service_wait_ratio`                            | Wait fraction during service              |
| `global_replans`, `local_replans`               | Planning burden                           |
| `task_completion_ratio`                         | Whether fleet keeps up with demand        |
| `mean_assignments_per_task`                     | Assignment stability                      |
| `p95_flowtime`                                  | Tail latency                              |
| `safety_violations`                             | Formal constraint breaches (fixed radius) |
| `mean_planning_time_ms`, `p95_planning_time_ms` | Solver scalability                        |

### Sanity / accounting metrics

These validate the run and aid debugging. Not recommended for primary
comparisons.

| Metric                                   | Use                                            |
|------------------------------------------|------------------------------------------------|
| `completed_tasks`                        | Cross-check `throughput`                       |
| `delay_events`                           | Confirm noise model is active                  |
| `makespan`                               | Bound on last task completion (auxiliary)      |
| `assignments_kept`, `assignments_broken` | Commitment mechanism activity                  |
| `immediate_assignments` (raw count)      | Raw chaining count (use ratio)                 |
| `replans`                                | Backward-compatible alias for `global_replans` |