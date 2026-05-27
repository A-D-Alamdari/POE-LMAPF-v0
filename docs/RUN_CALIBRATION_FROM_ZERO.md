# Re-running calibration after Direction A activation

Last updated: 2026-05-13
Branch at write time: `claude/conflict-aware-allocator-zfBdw`
Activation commit:    `d802864` (DIRECTION A ACTIVATION)
Active task allocator: `congestion_avoidance`
(was `greedy` prior to `v1.4-pre-direction-a-activation`)

## Why this guide exists

Direction A activation (commit `d802864`) replaced `greedy` with
`congestion_avoidance` as the default task allocator. The v1.4 calibration
data — including the §5.4 24× and §5.5 19× decomposition ratios — was
computed against `greedy` and is no longer the active system's
behavior. This guide re-runs the calibration cohorts that depend on
the allocator, then regenerates the decomposition reports.

A spot check at the contested cell
(`warehouse-10-20-10-2-2`, |M|=200, |X|=100, paired t-CI excludes zero,
+24% relative throughput) supports the expectation that the new ratios
will be smaller, but the exact numbers come from this re-run.

## What gets re-run (and what does not)

| CSV                                              | Status   | Reason                                                                  |
|--------------------------------------------------|----------|-------------------------------------------------------------------------|
| `raw_measurements.csv`                           | RE-RUN   | Simulator-driven; allocator invoked every `replan_every` steps          |
| `raw_measurements_v2.csv` (§5.4)                 | RE-RUN   | Same                                                                    |
| `raw_measurements_v2_5_5.csv` (§5.5)             | RE-RUN   | Same                                                                    |
| `raw_measurements_benchmark.csv` (Stern bare)    | **KEEP** | Bypasses `Simulator`; single-shot solver call; no allocator             |
| `raw_measurements_benchmark_with_exo_5_4.csv`    | **KEEP** | Mirrors the *placement algorithm* `Simulator._place_entities` only; no `Simulator` instance, no `assign()` call, no allocator state |
| `raw_measurements_benchmark_with_exo_5_5.csv`    | **KEEP** | Same                                                                    |

**Stern+exo determination (the non-trivial case).** I verified by
reading `scripts/calibrate_solver_benchmarks_with_exo.py`:

- `_place_exogenous` (line 199) takes `(env, starts, goals, num_humans,
  exo_seed, r_safe)` and samples free cells using
  `np.random.default_rng(exo_seed)` where `exo_seed = scenario_idx +
  1000`. Inputs come from the Stern `.scen` file and the map's
  blocked-cell set.
- `_build_instance` (called at line 305) constructs `AgentState` and
  `Task` objects directly from `.scen` records — each agent gets its
  scen-assigned goal 1-to-1.
- No call to any task-allocator class; no `Simulator(...)`; no
  `assign()` on any allocator. Placement RNG is seeded purely by
  `scenario_idx`.

Therefore the Stern bare and Stern+exo CSVs are allocator-independent
and remain valid under Direction A. No re-run is required for them.

## Estimated wall-clock on a 32-core machine

| Cohort                       | Rows | Est. wall |
|------------------------------|-----:|----------:|
| `calibration_v1`             | 2160 | 5–10 h    |
| `calibration_v2_5_4` (§5.4)  |  648 | 1–3 h     |
| `calibration_v2_5_5` (§5.5)  |  972 | 2–4 h     |
| Decomposition regeneration   |    — | < 5 min   |
| **Total**                    | 3780 | **8–17 h**|

These are estimates derived from `replans_per_cell=3` (each cell
advances the simulator by `replan_idx + 1` ticks; the slowest cells
are |M|=450 on `warehouse-2-2`). The previous v1.4 runs landed in
this band; congestion_avoidance's per-call cost (~130 ms at |M|=200) adds
<1 % to per-cell wall.

## Prerequisites

1. **Activation commit is on your current branch.**

   ```bash
   git log --oneline -10 | grep "DIRECTION A ACTIVATION"
   # Must show: <sha> DIRECTION A ACTIVATION: replace greedy with conflict_aware
   # (Pre-rename commit; the allocator is now called `congestion_avoidance`.)
   ```

2. **Sanity check the active allocator BEFORE launching.** This is
   the most important pre-flight; it catches stale clones, branch
   confusion, and environment issues in one line:

   ```bash
   python -c "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)"
   # Expected output:  congestion_avoidance
   ```

   If anything other than `congestion_avoidance` prints, **stop and fix
   the branch state** before launching the sweep. Every launcher
   script runs this same check and aborts with exit code 2 if it
   does not see `congestion_avoidance`, but it is cheaper to catch it
   before the heartbeat fires.

3. **Archived v1.4 greedy data is in place.**

   ```bash
   ls logs/calibration/_archived_greedy_v1_4_pre_direction_a/
   # Expected: 6 CSVs + 6 MDs + README.txt (created by Prompt 2)
   ```

   If you also maintain an off-`logs/` backup (recommended; `logs/`
   is gitignored), confirm it too — e.g.:

   ```bash
   ls ~/Desktop/EUMAS-POE-LMAPF-archives/v1.4-greedy-calibration/
   ```

4. **`tmux`, `python`, `bc`, and `awk` available**, and the project
   Python environment is active.

5. **System solver-binary dependencies installed.** Calibration v1
   uses LaCAM (``lacam_official``) as its default global solver,
   which is statically linked and requires no system libraries.
   Cohorts that override ``global_solver`` to ``cbsh2``, ``lns2``,
   or ``pbs`` require ``libboost-program-options1.74.0`` and
   ``libboost-filesystem1.74.0`` installed system-wide.  See
   [`docs/REPRODUCING_PAPER.md`](REPRODUCING_PAPER.md#environment-setup)
   for the canonical install command.  If a binary fails with
   ``error while loading shared libraries: libboost_program_options.so.1.74.0``,
   this requirement is unmet.

## Launch sequence

### Step 1 — verify clean state

```bash
git log --oneline -3
# Top commit should be on claude/conflict-aware-allocator-zfBdw (or
# main if merged).

python -c "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)"
# Must print: congestion_avoidance

ls logs/calibration/_archived_greedy_v1_4_pre_direction_a/
# Must show the v1.4 archive.
```

### Step 2 — launch the master sweep in tmux

```bash
tmux new -d -s calibration bash scripts/run_calibration/run_all_calibration.sh
```

This runs the three cohorts sequentially. Each cohort:

1. Deletes its in-place `logs/calibration/*.csv` (the stale v1.4
   greedy data) **unless** the file already contains the matching
   `source_config` tag, in which case `--resume` keeps it.
2. Aborts before launching if `SimConfig().task_allocator !=
   congestion_avoidance`.
3. Writes one row per `(solver, map, |M|, seed, replan_idx)` tuple
   into the in-place CSV, atomically appending.
4. Spawns a background heartbeat writer (60 s cadence) to
   `logs/calibration/.heartbeat_<cohort>`.

If a cohort fails or you kill the tmux session, re-launching the
master script picks up where it left off (the underlying
`scripts/calibrate_solver_budgets.py --resume` skips
already-completed `(solver, map, |M|, seed, replan_idx)` tuples).

### Step 3 — monitor progress

```bash
# Per-cohort heartbeats
for f in logs/calibration/.heartbeat_*; do
    echo "$(basename "$f"): $(cat "$f")"
done

# Live row count
for csv in raw_measurements.csv raw_measurements_v2.csv \
           raw_measurements_v2_5_5.csv; do
    if [ -f logs/calibration/$csv ]; then
        echo "$csv: $(wc -l < logs/calibration/$csv) rows"
    fi
done

# Attach to the tmux session
tmux attach -t calibration
# Detach with Ctrl+B then D
```

### Step 4 — regenerate decomposition reports

After `run_all_calibration.sh` exits successfully:

```bash
bash scripts/run_calibration/regenerate_decomposition_reports.sh
```

This runs `analyze_calibration.py` against the new v1 CSV and
`analyze_three_way_comparison.py` for §5.4 and §5.5 (the Stern bare
and Stern+exo CSVs come from the unchanged archived inputs — they
are not regenerated because they are allocator-independent).

### Step 5 — compare new vs v1.4

```bash
# New (congestion_avoidance)
cat logs/calibration/decomposition_summary.md

# Old (greedy reference)
cat logs/calibration/_archived_greedy_v1_4_pre_direction_a/decomposition_summary.md
```

Record the new ratios in `docs/PAPER_TODO.md` under the
"Direction A activated" entry. The new numbers replace the v1.4
24× / 19× claim in the paper's §5.4 / §5.5 reframing prose.

## Troubleshooting

- **`ABORT: SimConfig().task_allocator = 'greedy'`** — your local
  clone is missing commit `d802864`. `git pull` and re-run.
- **Heartbeat shows stuck row count** — `tmux attach -t calibration`
  to see the active log; common causes are solver binaries missing
  shared libraries (libboost on the sandbox; will not happen on a
  full 32-core box if `data/maps/` and solver binaries are present).
- **Cohort failed mid-run** — re-run the master script.
  `--resume` is the canonical recovery; do not delete the partial
  CSV unless you intend a clean restart.
- **Per-cohort patterns** mirror
  `scripts/run_sweeps/SWEEPS_EXECUTION_GUIDE.md` (heartbeat / resume /
  tmux detach-and-reattach are identical).

## Rollback

If at any point you decide to abort Direction A and restore the v1.4
calibration:

```bash
# 1. Revert the activation commit on the feature branch
git revert d802864

# 2. Restore the archived greedy CSVs as the in-place reference
cp logs/calibration/_archived_greedy_v1_4_pre_direction_a/*.csv logs/calibration/
cp logs/calibration/_archived_greedy_v1_4_pre_direction_a/*.md  logs/calibration/
```

See `docs/PAPER_TODO.md` "Rollback procedure" for the full sequence.
