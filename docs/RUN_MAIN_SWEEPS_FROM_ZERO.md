# Re-launching the main paper sweeps after Direction A activation

Last updated: 2026-05-13
Active branch: `claude/conflict-aware-allocator-zfBdw`
Activation commit: `d802864` (DIRECTION A ACTIVATION)
Active task allocator: `congestion_avoidance` (λ=0.5, max_rounds=5)

## Why this guide exists

Direction A activation (commit `d802864`) replaced `greedy` with
`congestion_avoidance` as the default task allocator in all 8 production
paper YAMLs and the `allocator_alternatives` sweep axis. Any paper
results.csv on disk that was produced under `greedy` (notably the
25 valid rows of `token_passing_ablation` from the VM era) is no
longer comparable to the active codebase. This guide:

1. Archives the pre-Direction-A `logs/paper/` partials (so a record
   exists), then clears them from the live paths.
2. Launches the seven Phase-1 paper sweeps plus the two defensive
   sweeps (E14 `allocator_alternatives`, E17 `budget_sensitivity`)
   sequentially with congestion_avoidance-tagged results.
3. After all sweeps complete, generates the figures, tables, stats,
   and claim-validation artefacts.

## Prerequisites

This guide assumes the operator has already completed the one-time
solver-binary setup documented in
[`docs/REPRODUCING_PAPER.md`](REPRODUCING_PAPER.md#environment-setup):

- Python venv at ``.venv`` with project + dependencies installed
  (``pip install -e .`` plus ``requirements.txt``).
- Solver binaries under ``src/ha_lmapf/global_tier/solvers/`` —
  these ship with the repository; ``download_maps.sh`` is the
  idempotent integrity check.
- ``libboost-program-options1.74.0`` and
  ``libboost-filesystem1.74.0`` installed system-wide (required by
  CBSH2-RTC, MAPF-LNS2, and PBS; **not** by PIBT2, LaCAM, or
  LaCAM*).  On Ubuntu 24.04 LTS:
  ``sudo apt-get install -y libboost-program-options1.74.0 libboost-filesystem1.74.0``.
- Per-solver runtime status: see
  [`docs/SOLVER_STATUS.md`](SOLVER_STATUS.md).  Operators
  troubleshooting solver failures should start from
  [`docs/SWEEPS_EXECUTION_GUIDE.md` § Troubleshooting](SWEEPS_EXECUTION_GUIDE.md#troubleshooting).

If any solver binary fails at runtime with
``error while loading shared libraries: libboost_program_options.so.1.74.0``,
the libboost package above is missing.

## Pre-flight (run before launching)

### 1. Verify the activation commit is on the current branch

```bash
git log --oneline -10 | grep "DIRECTION A ACTIVATION"
# Must print: d802864 DIRECTION A ACTIVATION: replace greedy with conflict_aware
# (Pre-rename commit; the allocator is now called `congestion_avoidance`.)
```

### 2. Verify the active allocator is congestion_avoidance

The launchers in `scripts/run_sweeps/` do **not** have an
allocator-check wrapper (unlike the calibration launchers in
`scripts/run_calibration/`). The one-line probe below is the user's
manual pre-flight; if it does not print `congestion_avoidance`, fix the
branch state before launching:

```bash
python -c "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)"
# Expected: congestion_avoidance
```

This is intentional scope: adding allocator-check wrappers to the
nine sweep launchers is a separate follow-up. The smoke test in
step 4 below catches the misconfiguration cheaply if the pre-flight
is forgotten.

### 3. Verify every paper YAML uses congestion_avoidance

```bash
for f in configs/eval/paper/*.yaml; do
    grep -H "^  task_allocator\|^task_allocator" "$f"
done
```

Every line except `allocator_alternatives.yaml` should show
`task_allocator: congestion_avoidance`. `allocator_alternatives.yaml`
itself uses a sweep axis `[greedy, hungarian, auction, congestion_avoidance]`
— that is correct (E14 is the defensive comparison sweep).

### 4. Verify all nine launcher scripts parse cleanly

```bash
for f in scripts/run_sweeps/*.sh; do bash -n "$f" && echo "OK: $(basename $f)"; done
```

All nine must report OK.

### 5. Verify the run_paper_experiment harness propagates the active allocator

A one-cell smoke run takes ~12 s and confirms the harness emits
`task_allocator=congestion_avoidance` into `results.csv`:

```bash
rm -rf /tmp/integration_smoke
python scripts/evaluation/run_paper_experiment.py \
    --config configs/eval/paper/baseline_comparison.yaml \
    --out /tmp/integration_smoke \
    --workers 1 --limit 1
python3 -c "
import csv
r = next(csv.DictReader(open('/tmp/integration_smoke/results.csv')))
print('status:', r['status'])
print('task_allocator:', r['task_allocator'])
assert r['status'] == 'ok' and r['task_allocator'] == 'congestion_avoidance'
print('OK')
"
rm -rf /tmp/integration_smoke
```

## Archiving the pre-Direction-A `logs/paper/` data

Run **once** before the first sweep launch on a machine that has
pre-Direction-A partials. `logs/` is gitignored, so the archive is
local-disk only.

```bash
mkdir -p logs/paper/_archived_greedy_v1_4_pre_direction_a
if [ -d logs/paper ]; then
    for d in logs/paper/*/; do
        sweep=$(basename "$d")
        if [ "$sweep" != "_archived_greedy_v1_4_pre_direction_a" ] && \
           [ -d "$d" ] && [ "$(ls -A "$d" 2>/dev/null | wc -l)" -gt 0 ]; then
            cp -r "$d" logs/paper/_archived_greedy_v1_4_pre_direction_a/
        fi
    done
fi
cat > logs/paper/_archived_greedy_v1_4_pre_direction_a/README.txt <<'EOF'
All paper-sweep results.csv files here were produced with
task_allocator=greedy (or were partial runs from the VM era).
These are the pre-Direction-A reference data.

The active sweeps will produce congestion_avoidance-tagged results
in the live paths.

Archive created on Direction A activation (post-commit d802864).
logs/ is gitignored, so this archive lives only on the local machine.
EOF
```

Then **delete** live partial results so the new sweeps don't
`--resume` into them:

```bash
for d in logs/paper/*/; do
    sweep=$(basename "$d")
    if [ "$sweep" != "_archived_greedy_v1_4_pre_direction_a" ] && [ -d "$d" ]; then
        rm -f "$d/results.csv" "$d/manifest.csv" "$d/.heartbeat" "$d/run.log"
    fi
done
```

If `logs/paper/` is empty (no prior runs on this machine), both
commands are no-ops — skip them.

## Wall-clock estimate (32-core machine)

These are estimates derived from the v1.4 archived run times plus
the calibration's per-cell timing (warehouse-2-2 |M|≥300 cells take
~5–10 min; random-64 cells ~2 min; warehouse-2-1 mid-density ~3–6
min). The 32-core parallelism efficiency is empirically ~75-85 %
once filesystem and Python GIL contention are accounted for.

| Sweep | Runs | Avg per-run | Total at 32c |
|---|---:|---:|---:|
| `token_passing_ablation` | 60 | 2–5 min | 0.1–0.2 h |
| `aux_h_r_decoupling` | 110 | 2–5 min | 0.2–0.3 h |
| `fov_safety` | 400 | 3–6 min | 0.6–1.3 h |
| `baseline_comparison` | 720 | 3–7 min | 1.1–2.6 h |
| `scaling_exogenous` | 760 | 2–5 min | 0.8–2.0 h |
| `scaling_agents` | 1040 | 4–10 min | 2.2–5.4 h |
| `solver_sensitivity` | 3360 | 3–7 min | 5.3–12.3 h |
| `allocator_alternatives` (E14) | 120 | 4–8 min | 0.3–0.5 h |
| `budget_sensitivity` (E17) | 160 | 4–12 min | 0.3–1.0 h |
| **TOTAL** | **6730** | — | **11–25 h** |

PAPER_TODO's earlier 50–130 h figure was a conservative upper bound
that assumed worst-case solver-timeout density and lower parallel
efficiency. Empirically the 32-core mid-range above is more
representative; budget a full day to be safe and a half-day for the
ideal case.

## Launch sequence

### Step 1 — verify clean state

```bash
git log --oneline -3
python -c "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)"
# Must print: congestion_avoidance
ls logs/paper/_archived_greedy_v1_4_pre_direction_a/  # (if archived)
```

### Step 2 — launch the master in tmux

```bash
tmux new -d -s paper_sweeps bash scripts/run_sweeps/run_all_sequential.sh
```

The master runs the 9 sweeps sequentially in the order:
`token_passing_ablation` → `aux_h_r_decoupling` → `fov_safety` →
`baseline_comparison` → `scaling_exogenous` → `scaling_agents` →
`solver_sensitivity` → `allocator_alternatives` → `budget_sensitivity`.

Each sweep:

1. Skips itself if its `logs/paper/<sweep>/results.csv` already
   contains `EXPECTED + 1` rows (full completion).
2. Otherwise invokes `scripts/run_sweeps/run_<sweep>.sh`, which
   calls `scripts/evaluation/run_paper_experiment.py` with
   `--resume` and the YAML.
3. Spawns a per-sweep heartbeat writer at
   `logs/paper/<sweep>/.heartbeat` (60 s cadence).

On any failure, the master exits non-zero and prints a re-run hint.
Re-launching the same command resumes from the partial CSV.

### Step 3 — monitor progress

```bash
# Per-sweep heartbeats
for f in logs/paper/*/.heartbeat; do
    [ -f "$f" ] && echo "$(dirname "$f" | xargs basename): $(cat "$f")"
done

# Row counts vs expected
for sweep in token_passing_ablation aux_h_r_decoupling fov_safety \
             baseline_comparison scaling_exogenous scaling_agents \
             solver_sensitivity allocator_alternatives \
             budget_sensitivity; do
    csv=logs/paper/${sweep}/results.csv
    if [ -f "$csv" ]; then
        echo "$sweep: $(($(wc -l < "$csv") - 1)) rows"
    fi
done

# Attach to the tmux session
tmux attach -t paper_sweeps
# Detach with Ctrl+B then D
```

### Step 4 — confirm completion before artifacts

Each sweep's `logs/paper/<sweep>/run.log` ends with `DONE: <sweep>`
on success or `FAILED: <sweep> (rows=…)` on failure. The master
script's final stdout reads:

```
All 9 sweeps complete (7 Phase-1 + E14 + E17 defensive).  Proceed to post-processing:
  bash scripts/run_sweeps/generate_artifacts.sh
```

Do not proceed to artifacts until that line appears.

### Step 5 — generate paper artifacts

```bash
bash scripts/run_sweeps/generate_artifacts.sh
```

This:

1. Verifies the total row count across all sweeps is ≥ 6450 (the
   guard against running on partial data).
2. Builds the seven §5 figures into `figures/paper/<fig>/`.
3. Builds Tables 1 and 2 into `paper/tables/`.
4. Runs `statistical_analysis.py` on `token_passing_ablation`
   (reference vs `priority`).
5. Runs `validate_paper_claims.py` against
   `docs/PAPER_NUMERICAL_CLAIMS.yaml` if present.
6. Writes the reproducibility lock into `docs/reproducibility/`.

### Step 6 — commit and push the artefacts

```bash
git add figures/paper/ paper/tables/ reports/ docs/reproducibility/
git commit -m "paper-artifacts: figures, tables, claim validation, lock"
git push origin claude/conflict-aware-allocator-zfBdw
```

## Troubleshooting

- **`ABORT: not all sweeps complete`** from `generate_artifacts.sh`:
  re-launch `run_all_sequential.sh`; it will skip completed sweeps
  and resume the rest.
- **Heartbeat shows stuck row count**: `tmux attach -t paper_sweeps`
  and inspect the live `run.log`. Solver-binary issues (`libboost`,
  missing CBSH2/LNS2 binaries) surface in the
  `[rolling-horizon] solver '...' returned status=error` messages
  with full stderr.
- **One sweep needs a clean re-run**: delete just that sweep's
  results, then re-launch the master:
  ```
  rm -f logs/paper/<sweep>/results.csv logs/paper/<sweep>/manifest.csv
  tmux new -d -s paper_sweeps bash scripts/run_sweeps/run_all_sequential.sh
  ```
- **Mixed-allocator data suspected**: the harness writes
  `task_allocator` into every results.csv row. Filter on
  `task_allocator == "congestion_avoidance"`; any other value indicates a
  config/data drift.

## Rollback (if Direction A is abandoned)

```bash
git revert d802864     # un-flips configs + SimConfig default + scripts
git push origin claude/conflict-aware-allocator-zfBdw
rm -rf logs/paper/*/   # discard congestion_avoidance sweep artefacts
# Restore the archived greedy data:
cp -r logs/paper/_archived_greedy_v1_4_pre_direction_a/*/ logs/paper/
```

See `docs/PAPER_TODO.md` "Rollback procedure" for the full sequence
across calibration + sweeps + tag rollback.

## Known gap: launcher allocator-check wrapper (follow-up)

The calibration launchers under `scripts/run_calibration/` perform
a `SimConfig(map_path='x').task_allocator == "congestion_avoidance"`
check and abort with exit code 2 if the active allocator is not
congestion_avoidance. The sweep launchers under `scripts/run_sweeps/` do
**not** carry this wrapper (they predate the activation). The one-
line pre-flight in step 2 above is the workaround.

A follow-up to add the same allocator-check wrapper to every
`scripts/run_sweeps/run_*.sh` is recommended but **out of scope for
this prompt**. It would prevent the user from accidentally
launching a 25-h sweep against the wrong allocator if a future
config drift slips through.
