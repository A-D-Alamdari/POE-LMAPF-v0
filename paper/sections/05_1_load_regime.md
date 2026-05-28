# §5.1  Load regime — what throughput actually measures

In the experimental regime studied here, the system-wide task arrival
rate equals $|M|/(\text{height} + \text{width})$ per step, which is
0.781 on `random-64-64-10` and 0.394 on `warehouse-10-20-10-2-2` at
$|M| = 100$. Throughput in Table 1 saturates at this arrival cap; the
column therefore measures task-arrival-rate compliance, not planner
capacity. Algorithm-discriminating comparisons in §5.4 (System Health
Indicators), §5.5 (baseline comparison), and §5.6 (allocator study)
operate at points where the planner becomes the bottleneck; those are
the comparisons in which throughput is informative.

## Where the arrival cap comes from

The simulator's default lifelong task stream (`Simulator.
_generate_task_stream`) draws inter-arrival times from an exponential
with **per-agent mean $H + W$ steps**, where $H$ and $W$ are the map
height and width. The choice is justified upstream as
"approximately one full task cycle (pickup + delivery) per agent per
$H+W$ ticks" -- the Manhattan-1 average one-way distance on an $H
\times W$ grid is $(H+W)/3$, so a two-leg cycle plus
congestion / safety-wait overhead totals roughly $H+W$. The
system-wide arrival rate is therefore

$$\lambda_{\text{sys}} = \frac{|M|}{H + W}\ \text{tasks/step}.$$

At the headline §5.2 conditions $|M|=100$:

| Map | $H + W$ | $\lambda_{\text{sys}}$ | Paper Table-1 throughput (mean) |
|---|---:|---:|---:|
| random-64-64-10        | $64 + 64 = 128$  | **0.781** | 0.471 (avg across $|M|\in\{25,50,75,100\}$) |
| warehouse-10-20-10-2-2 | $84 + 170 = 254$ | **0.394** | 0.249 (same average)                       |

The Table 1 numbers are averaged across the four $|M|$ values in the
§5.2 sweep, so they sit below the $|M|=100$ ceiling.  At each $|M|$
cell individually the throughput equals
$\lambda(M) = |M|/(H+W)$ within seed variation -- i.e.\ every cell
is arrival-saturated.

## How the table-builder surfaces this

`MetricsTracker.finalize` now emits two CSV columns:

* `arrival_rate_per_step` $= \text{total\_released\_tasks}/\text{steps}$
  -- the system-wide arrival rate the run actually saw (a single
  empirical sample of $\lambda_{\text{sys}}$; under the exponential
  stream and 2000-step horizon the sample is within ±2% of the
  theoretical value).
* `throughput_utilization` $= \text{throughput}/\text{arrival\_rate\_per\_step}$
  -- the fraction of arrived tasks that completed within the run.
  A utilization of $\approx 1.0$ means the planner kept up with the
  arrival stream; the column is saturated and cannot tell two
  planners apart.

The paper-table builder
(`scripts/evaluation/build_summary_tables.py`) appends `Util.` next
to `Throughput` in every table it produces and **flags cells with
mean utilization $\ge 0.95$ with a trailing asterisk**, so the
reader sees at a glance which rows the throughput column cannot
discriminate.

## What to use instead

Throughput is informative when the planner is the bottleneck:

* In §5.3 / §5.4 the FoV / safety-radius sweeps push the local
  controller into safety-wait wedges; arrival-saturation drops and
  throughput becomes a measure of how much capacity the controller
  preserves under conservative parameters.
* In the §5.5 baseline comparison
  (`paper/sections/05_4_system_health.md`), the rigid-follower
  baselines deadlock fractions of the fleet but the throughput
  column stays near the arrival cap because the un-stuck agents
  pick up the slack.  This is the worst-case reading-error from
  treating throughput as a planner-quality metric: LaCAM-blind
  deadlocks 100% of agents in every run but reports throughput
  0.205 vs Ours' 0.396 -- a 1:2 ratio that looks like a
  half-as-good planner rather than a catastrophic one.  The
  Util.\ column **plus** the `deadlock_count` column together
  expose this.
* In the §5.6 allocator study, the comparison is between two
  task-assignment policies under the SAME arrival stream; the
  arrival cap is identical across rows and any throughput
  difference is allocator-attributable.

## Diagnostic

`scripts/diagnostics/check_arrival_saturation.py` loads a results
CSV, computes the per-cell mean utilization across seeds, and
reports which cells are arrival-saturated. Use it on any new
sweep before reading throughput as a planner-discriminating
metric.
