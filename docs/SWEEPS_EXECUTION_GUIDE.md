# Local execution guide for paper sweeps

**Last updated:** 2026-05-11
**Tested against commit:** `38af32f87c11e198b0d3fb366d833ac3bd945c23`

## Why this guide exists

The seven paper sweeps under `configs/eval/paper/` total roughly **6 450
runs** of the lifelong-MAPD simulator. Each warehouse high-density run
takes 15–30 minutes of wall-clock by itself, so the full set is multi-
day work. The Claude Code VM sandbox cannot host this — it has 4 CPUs
only, Bash timeouts kill long-running commands, and the agent's session
model is not designed for jobs that span days. This guide gives you
everything needed to run the sweeps on your own hardware, where you
control parallelism and there are no timeouts.

## Prerequisites on your local machine

1. **Clone of this repo** at commit `38af32f` or later, with the
   `scripts/run_sweeps/` directory committed.
2. **Python environment** matching what was used during development.
   Recommended:
   ```bash
   pip install -e .
   ```
   from the repo root. Required packages: `numpy`, `scipy`, `pyyaml`,
   `pandas`, `matplotlib`, plus the simulator's internal modules under
   `ha_lmapf/`.
3. **All solver binaries built** at
   `src/ha_lmapf/global_tier/solvers/`. Verify with:
   ```bash
   python -m pytest tests/test_solver_smoke.py -v
   ```
   Expect 5 passing + 1 PIBT2-FR test deselected per
   `docs/PIBT2_DIAGNOSIS.md` (known carry-over Mode B priority deadlock
   on the 10×14 mini-warehouse fixture; documented and not a regression
   for any paper sweep).
4. **`tmux` installed.** `apt install tmux` on Ubuntu/Debian;
   `brew install tmux` on macOS.
5. **`awk` and `bc`** (default on every Unix; used by the heartbeat
   percentage calculation).
6. **Disk space:** ~5–10 GB total for `logs/` after all sweeps. Each
   `results.csv` is small (<10 MB), but the harness writes intermediate
   manifests + per-run logs.

## Hardware recommendations

| CPUs | Recommended workers | Estimated total wall-clock |
|---:|---:|---|
| 4 | 4 | 100–260 hours (~5–11 days) |
| 8 | 8 | 50–130 hours (~2–5 days) |
| 16 | 16 | 25–65 hours (~1–3 days) |
| 32 | 32 | 15–40 hours (overnight) |

The scripts auto-detect `nproc` and use all available cores. To limit
parallelism (e.g., to keep the machine responsive for other work), edit
the `N_CORES=` line in each `run_<sweep>.sh`.

Wall-clock scales near-linearly up to ~16–32 workers; beyond that, the
warehouse-2-2 high-density runs are memory-bound rather than CPU-bound
(each worker holds a simulator + solver instance).

## What gets run

Seven sweeps, listed smallest-first (they run in this order to act as
smoke tests for the larger ones):

| Order | Sweep | EXPECTED_ROWS | Est. wall @ 8 cores | Paper section |
|---:|---|---:|---|---|
| 1 | `token_passing_ablation` | 60 | 2–6 hours | §4.3 ablation |
| 2 | `aux_h_r_decoupling` | 110 | 2–6 hours | reviewer-3 aux |
| 3 | `fov_safety` | 400 | 4–10 hours | §5.3 |
| 4 | `baseline_comparison` | 720 | 12–30 hours | §5.5 |
| 5 | `scaling_exogenous` | 760 | 4–12 hours | §5.4 part 2 |
| 6 | `scaling_agents` | 1040 | 16–40 hours | §5.4 part 1 |
| 7 | `solver_sensitivity` | 3360 | 12–30 hours | §5.2 |

Total: **~6 450 runs**, estimated **50–130 hours** at 8 cores.

## Step-by-step execution

### Step 1: Pull the latest

```bash
cd /path/to/your/clone/EUMAS-POE-LMAPF-test
git fetch
git checkout claude/analyze-repo-structure-37rEb
git pull
```

Verify the new scripts exist:

```bash
ls scripts/run_sweeps/
# Expected: 7 run_*.sh, plus run_all_sequential.sh and generate_artifacts.sh
```

### Step 2: Confirm preconditions

```bash
# Verify Python env imports cleanly
python -c "import ha_lmapf; print(ha_lmapf.__file__)"

# Verify solver binaries — expect 5 passing (one may be skipped on
# hosts without all libboost shared libs)
python -m pytest tests/test_solver_smoke.py -v

# Verify the full test suite — expect 544 passing, 1 skipped (RHCR
# binary unavailable on most hosts), 1 deselected (PIBT2-FR carry-over).
python -m pytest tests/ -q --deselect tests/test_baseline_pibt2_fr.py::test_pibt2_fr_smoke
```

If any unexpected test fails, **stop** and resolve before launching
sweeps.

### Step 3: Launch sweeps

#### Option A: All sweeps sequentially in one tmux session (recommended)

```bash
tmux new -d -s paper_sweeps bash scripts/run_sweeps/run_all_sequential.sh
```

Detach with `Ctrl+B` then `D`. The sweeps continue running in the
background; you can log out of the machine and they will keep going
(as long as the machine itself stays powered on).

Reattach to watch progress:

```bash
tmux attach -t paper_sweeps
```

#### Option B: Each sweep in its own tmux session

Useful if you want to start the larger sweeps before the smaller ones
finish — only on machines with enough cores that simultaneous sweeps
won't oversubscribe (≥ 16 cores). Each sweep uses `N_CORES` workers, so
two parallel sweeps double the load.

```bash
tmux new -d -s sweep_token_passing bash scripts/run_sweeps/run_token_passing_ablation.sh
# Wait for it to finish (check via the heartbeat below) before launching the next.
```

#### Option C: `nohup` background if `tmux` is not available

```bash
nohup bash scripts/run_sweeps/run_all_sequential.sh > sweep_run.log 2>&1 &
echo $! > sweep_run.pid
```

### Step 4: Monitor progress

#### Quick progress check (one-shot)

```bash
for d in logs/paper/*/; do
    sweep=$(basename "$d")
    if [ -f "$d/.heartbeat" ]; then
        echo "[$sweep] $(cat "$d/.heartbeat")"
    fi
done
```

The heartbeat is updated every 60 seconds while a sweep is running.
Each line shows `<timestamp> <data_rows>/<expected_rows> (<percent>%)`.

#### Live monitor of a specific sweep

```bash
watch -n 10 'wc -l logs/paper/<sweep>/results.csv 2>/dev/null; \
             cat logs/paper/<sweep>/.heartbeat 2>/dev/null'
```

#### Tail the full run log

```bash
tail -f logs/paper/<sweep>/run.log
```

#### Detect a stalled sweep

If the heartbeat shows the same row count for 30+ minutes, the sweep
may be wedged (rare, but possible if a solver subprocess hangs):

```bash
ps aux | grep run_paper_experiment | grep -v grep
```

- **Process alive** → it's stuck on a slow run. High-density
  warehouse-2-2 runs with the token communication mode genuinely take
  25–30 minutes each; this is calibrated and expected. Be patient.
  If you must intervene, `kill -9 <pid>`; re-run the sweep script
  (`--resume` skips completed rows).
- **Process dead** → the sweep aborted. Re-run the sweep script
  directly.

### Step 5: After each sweep completes, commit

```bash
git add logs/paper/<sweep>/
git commit -m "paper-data: <sweep> sweep complete ($(($(wc -l < logs/paper/<sweep>/results.csv) - 1)) rows)"
git push
```

Per-sweep commits make partial progress durable across machine reboots,
accidental directory deletions, and disk failures.

### Step 6: Generate artifacts after all sweeps complete

```bash
bash scripts/run_sweeps/generate_artifacts.sh
```

This produces all figures, tables, claim validation, and the
reproducibility lock. Expected wall-clock: 10–30 minutes.

Outputs:

- `figures/paper/<7 subdirs>/<PNGs and PDFs>`
- `paper/tables/table1_*.tex|.md` and `table2_*.tex|.md`
- `logs/paper/token_passing_ablation/stats/significance_report.md`
- `reports/claim_validation.md` (if `docs/PAPER_NUMERICAL_CLAIMS.yaml`
  exists)
- `docs/reproducibility/MANIFEST.md`

### Step 7: Final commit

```bash
git add figures/paper/ paper/tables/ reports/ docs/reproducibility/
git commit -m "paper-artifacts: figures, tables, claim validation, lock"
git push
```

## Troubleshooting

### Sweep died but I want to resume

Just re-run the script. `--resume` skips runs already in `results.csv`.
No data is lost — the harness's atomic-append flushes every 25 completed
runs, so at most the last <25 in-flight runs need to be re-executed.

```bash
bash scripts/run_sweeps/run_<sweep>.sh
```

### Sweep is slower than expected

Check the `.heartbeat` file. If rows are growing — even slowly — it is
just slow. The warehouse-2-2 |M|=250 lifelong cells genuinely take
15–30 minutes each in the allocator-bound regime (see
`logs/calibration/decomposition_summary.md`). If rows are *not* growing
for 30+ minutes, see "Detect a stalled sweep" above.

### Disk space running low

Each sweep's `results.csv` is small (<10 MB), but the harness writes
intermediate manifest files and per-run logs:

```bash
du -sh logs/paper/
```

If usage exceeds ~20 GB, archive completed sweeps to a different
filesystem:

```bash
tar czf token_passing_ablation_complete.tar.gz logs/paper/token_passing_ablation/
# After verifying the archive, you can re-symlink or move logs/paper/<sweep>/
# to free up space.
```

### Want to use a subset of CPU cores

Edit `N_CORES=` line in the specific `run_<sweep>.sh`:

```bash
# Default (uses all cores):
N_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

# Override (use exactly 8 cores even if more are available):
N_CORES=8
```

### Want to abort everything

```bash
tmux kill-session -t paper_sweeps    # if using Option A
# Or kill individual python processes:
pkill -f run_paper_experiment.py
```

Resume any time with the same script — `--resume` recovers cleanly.

### A test fails on my machine that didn't fail in CI

Most likely causes:

- **Missing solver binary.** Verify with `pytest tests/test_solver_smoke.py
  -v`. Build instructions for each solver are in
  `src/ha_lmapf/global_tier/solvers/`.
- **libboost mismatch.** Some solvers need libboost 1.74. On Ubuntu
  22.04: `apt install libboost-all-dev`.
- **Python module not found.** `pip install -e .` from the repo root
  re-installs the package in editable mode.

If a test fails in a way that affects a specific solver's behavior, the
corresponding paper sweep will show that solver at lower completion
than expected. Investigate before the long sweeps commit hours of
compute.

## What "complete" looks like

When everything is done, your repo should have:

- `logs/paper/<sweep>/results.csv` for each of 7 sweeps, with the
  expected row count (header + N).
- `logs/paper/<sweep>/run.log` showing the full sweep history.
- `logs/paper/<sweep>/stats/` for sweeps whose YAML defines
  `reference_condition` (`solver_sensitivity`, `baseline_comparison`),
  plus `token_passing_ablation` which `generate_artifacts.sh` invokes
  manually.
- `figures/paper/<7 subdirectories>/<PNGs and PDFs>`.
- `paper/tables/table1_solver_substitutability.tex|.md` and
  `table2_baseline_comparison.tex|.md`.
- `reports/claim_validation.md` if `docs/PAPER_NUMERICAL_CLAIMS.yaml`
  exists in your tree.
- `docs/reproducibility/MANIFEST.md` plus environment/config/result
  hashes.

## Resume from the partial token_passing_ablation state

There are currently **25 valid rows** in
`logs/paper/token_passing_ablation/results.csv` from a prior
sandbox-VM attempt. The run script will resume from row 26
automatically; you do not need to delete or re-run those 25 rows. The
harness's `--resume` reads existing rows by `run_id` and skips any whose
ID is already present with `status=ok`.

## Estimated time on common hardware configurations

- **Modest laptop (4 cores, 8 GB RAM):** 5–11 days. Possible but slow;
  consider a desktop or cluster.
- **Workstation (8–16 cores, 32 GB RAM):** 2–5 days. Realistic for most
  academic hardware.
- **Server (32+ cores, 64+ GB RAM):** ~1 day, often overnight.
  Recommended if available via cluster access at Özyeğin or PUCRS.

The disk footprint and per-run memory are modest; the bottleneck is
purely CPU.
