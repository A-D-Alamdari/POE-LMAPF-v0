# Tuning sweeps

Pre-paper sensitivity sweeps that fix free parameters before the
main §5 paper sweeps run.

| Sweep | YAML | Cells | Purpose |
| --- | --- | --: | --- |
| [Horizon × replan_every](#horizon--replan_every-tuning-sweep) | `configs/tuning/horizon_replan_full.yaml` | 640 | Pick optimal `(horizon, replan_every)` per `(map, num_agents)` |
| [FOV × safety_radius](#fov--safety_radius-sensitivity-sweep) | `configs/tuning/fov_safety_sweep.yaml` | 700 | §5.3 sensitivity to observable region + buffer radius |
| [§5.4 scaling — split into four sweeps](#54-scaling-sweeps-four-way-split) | `configs/tuning/scaling_{agents,humans}_fov{3,4}_safe{1,2}.yaml` | 4 × 560 = 2,240 | §5.4 scaling behavior across 4 Tier-1 backends × 2 fov/safe operating points |
| [§5.5 allocator — split into two sweeps](#55-allocator-comparison-sweeps-two-way-split) | `configs/tuning/allocator_comparison_fov{3,4}_safe{1,2}.yaml` | 2 × 200 = 400 | §5.5 four allocators × two maps × two (fov, safe) operating points |
| [§5.6 deadlock + wait-time](#56-deadlock--wait-time-decomposition-sweep) | `configs/tuning/deadlock_wait.yaml` | 270 | §5.6 three methods × nine M values; global no-progress streak + wait decomposition |
| [§3 soft-safety ablation](#3-soft-safety-ablation-sweep) | `configs/tuning/soft_safety_ablation.yaml` | 180 | §3 hard-vs-soft safety; two arms × nine M values |
| ~~Allocator comparison (old, single-file)~~ | `configs/tuning/allocator_comparison.yaml` | ~~200~~ | **DEPRECATED** — see two-way split |
| ~~Agent scaling (old, 6-solver)~~ | `configs/tuning/scaling_agents.yaml` | ~~840~~ | **DEPRECATED** — see four-sweep split |
| ~~Exogenous scaling (old, 6-solver)~~ | `configs/tuning/scaling_humans.yaml` | ~~840~~ | **DEPRECATED** — see four-sweep split |

§5.6 is a multi-method sweep (`ours`, `pibt2_fr`, `lacam_blind`); the others use `method=ours`.  All active sweeps: `T=2000`, 10 seeds.

---

## Horizon × replan_every tuning sweep

Pre-paper tuning sweep to identify the optimal `(horizon,
replan_every)` configuration per `(map, num_agents)` before the
main §5 paper sweeps.

* **Generator:** `scripts/tuning/generate_horizon_yaml.py`
* **Config:** `configs/tuning/horizon_replan_full.yaml` (640 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["horizon_replan_full"] = 2000`
  (the validator matches by `config_yaml_path.stem`, which is the
  filename without `.yaml`; the YAML's `name:` field is
  `horizon_replan_full_tuning` for human readability but is not
  what the validator keys on).

## Trim history

Initial design was a 1,200-cell sweep covering 3 maps × 10
horizons.  Trimmed for the overnight launch to 640 cells (2 maps
× 8 horizons) by:

* Dropping `warehouse-20-40-10-2-2` — the heaviest map; defers
  the large-warehouse tuning to a separate follow-on sweep.
* Trimming the horizon axis from `[10..100]` to `[10..80]` —
  removes H=90 / H=100 where preliminary §5.x data already
  suggested diminishing returns.

The smaller sweep cuts estimated wall time from ~37-40 h on
16 workers down to ~12-16 h.

## Sweep axes

| Axis | Values |
| --- | --- |
| Map | `random-64-64-10`, `warehouse-10-20-10-2-2` |
| Agent count | 25, 50, 75, 100 |
| Human count | 50 |
| Horizon | 10, 20, 30, 40, 50, 60, 70, 80 |
| `replan_every` | `max(1, horizon // 2)` → 5, 10, 15, 20, 25, 30, 35, 40 |
| Seed | 0..9 |
| Method | ours |
| Steps | 2000 |

**Total cells:** 2 maps × 4 agent_counts × 8 horizons × 10 seeds
= **640 runs**.

## Regenerating the YAML

```bash
python scripts/tuning/generate_horizon_yaml.py
```

Re-running the generator with the same `SWEEP_VALUES` /
`MAP_DEFS` / `SEEDS` constants produces a byte-identical YAML.

## Dry-run (validate harness + YAML before the full launch)

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/horizon_replan_full.yaml \
    --out /tmp/horizon_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

Confirmed working: the dry-run completes the first cell
(random map, |M|=25, H=10) in ~162 seconds and writes
`/tmp/horizon_dryrun/results.csv` with status=ok.

## Full launch (cluster, 16 workers, overnight)

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/horizon_replan_full.yaml \
    --out logs/tuning/horizon_replan_full \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/horizon_replan_full_launch.log 2>&1 &
echo "PID: $!"
```

Resume from a partial run by adding `--resume` (skips runs whose
`run_id` is already in `results.csv` with `status=ok`).

## Wall-time estimate

**Reference point** (from §5.8 smoke): `warehouse-10-20-10-2-2`
at |M|=150, 2000 steps ≈ 22 min/run.  Wall time scales roughly
super-linearly with agent count and is approximately linear in
horizon (longer horizons → longer per-replan planning).

Rough per-cell estimates extrapolating from the reference:

| Map | |M| | Est. per-run wall (range across H=10..80) |
| --- | --: | --- |
| random | 25 | 2–4 min (dry-run = 2.7 min @ H=10) |
| random | 50 | 4–8 min |
| random | 75 | 7–13 min |
| random | 100 | 10–20 min |
| warehouse_small | 25 | 3–6 min |
| warehouse_small | 50 | 6–11 min |
| warehouse_small | 75 | 10–20 min |
| warehouse_small | 100 | 15–30 min |

**Aggregate (serial CPU-hours):**

| Map | Cells | Mean × min/cell | Total CPU-min |
| --- | --: | --- | --: |
| random | 320 | ~7 | 2,240 |
| warehouse_small | 320 | ~12 | 3,840 |
| **Total** | **640** |  | **~6,080 min ≈ 100 CPU-hours** |

**Wall-clock on 16 workers:** ~12-16 hours (overnight).

**Estimate may vary by factor of 2–3** due to scale-dependent
solver behavior (LaCAM-Official sometimes hits the 10s timeout on
warehouse_small at |M|=100 with long horizons, which adds
variance).  Plan for the sweep to take **8-30 hours wall** on
16 workers.

## Post-sweep analysis

After completion, run the validator to check pipeline health:

```bash
.venv/bin/python scripts/evaluation/validate_smoke_results.py \
    --logs-dir logs/tuning/horizon_replan_full \
    --no-figure
```

The Theorem-1 invariant should hold (`ours` with `agent_attr=0`
across all 640 runs).  Sidecar count should equal 640; CSV row
count should equal 640.

The tuning analysis itself (picking the optimal `(horizon,
replan_every)` per cell) is a separate post-sweep step — group
the CSV by `(map_path, num_agents, horizon)` and pick the row
maximizing throughput (or some weighted sum of throughput,
violations, deadlock_count).

---

## FOV × safety_radius sensitivity sweep

§5.3 sensitivity of safety metrics to the observable-region
radius `r_fov` and the buffer radius `r_safe`.

* **Generator:** `scripts/tuning/generate_fov_safety_yaml.py`
* **Config:** `configs/tuning/fov_safety_sweep.yaml` (700 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["fov_safety_sweep"] = 2000`

### Constraint

`r_fov > r_safe` (strict).  An agent cannot enforce a buffer of
radius `r_safe` around exogenous agents it cannot observe.
Pairs with `r_fov ≤ r_safe` are pruned at generation time.

Valid pairs per map: 35.

| `r_fov` | valid `r_safe` values | count |
| ---: | --- | ---: |
| 2 | 1 | 1 |
| 3 | 1, 2 | 2 |
| 4 | 1, 2, 3 | 3 |
| 5 | 1, 2, 3, 4 | 4 |
| 6, 7, 8, 9, 10 | 1, 2, 3, 4, 5 | 5 × 5 = 25 |
| **total** | | **35** |

### Sweep axes

| Axis | Values |
| --- | --- |
| Map | `warehouse-10-20-10-2-1`, `random-64-64-10` |
| `fov_radius` | 2, 3, 4, 5, 6, 7, 8, 9, 10 |
| `safety_radius` | 1, 2, 3, 4, 5 (subject to constraint) |
| `(num_agents, num_humans, horizon, replan_every)` | per-map; see `REFERENCE_SCALE` in the generator |
| Seed | 0..9 |
| Method | ours |
| Steps | 2000 |

**Total cells:** 35 valid pairs × 2 maps × 10 seeds = **700 runs**.

### ⚠️ Provisional reference scale — TODO post-horizon-tuning

The per-map `(num_agents, num_humans, horizon, replan_every)`
values in the generator's `REFERENCE_SCALE` dict are
**PLACEHOLDERS** pending the horizon tuning sweep currently
running.  Once horizon tuning completes:

1. Group the horizon-tuning results by `(map, num_agents)` and
   pick the best-throughput `(horizon, replan_every)` per cell.
2. Update `REFERENCE_SCALE` in
   `scripts/tuning/generate_fov_safety_yaml.py`.
3. Re-run the generator.
4. Diff `configs/tuning/fov_safety_sweep.yaml` to confirm only
   the placeholder fields changed.
5. Launch.

Current placeholders (consistent with §5.8 reference and existing
`tune_fov_safety.py` defaults):

| Map | num_agents | num_humans | horizon | replan_every |
| --- | ---: | ---: | ---: | ---: |
| `warehouse-10-20-10-2-1` | 100 | 50 | 20 | 10 |
| `random-64-64-10` | 50 | 50 | 20 | 10 |

### Regenerating the YAML

```bash
python scripts/tuning/generate_fov_safety_yaml.py
```

Reproducible: re-running with the same `FOV_VALUES` /
`SAFETY_VALUES` / `MAPS` / `REFERENCE_SCALE` / `SEEDS`
produces a byte-identical YAML.

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/fov_safety_sweep.yaml \
    --out /tmp/fov_safety_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

### Full launch (cluster, 16 workers)

**Do NOT launch yet.** The horizon tuning sweep is currently
running on the cluster (~14 h remaining as of the FOV/safety
generator commit).  Launching the FOV/safety sweep concurrently
would cause CPU contention.  Wait for horizon tuning to complete,
then:

1. Update `REFERENCE_SCALE` per the horizon analysis.
2. Re-run the generator.
3. Launch with the same form as the horizon sweep:

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/fov_safety_sweep.yaml \
    --out logs/tuning/fov_safety_sweep \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/fov_safety_sweep_launch.log 2>&1 &
echo "PID: $!"
```

### Wall-time estimate

Each FOV/safety cell runs at the same scale (`num_agents`,
`num_humans`, `horizon`) within its map group, so per-cell wall
time should be roughly constant per map.  Using the §5.8 §-style
reference (`warehouse-10-20-10-2-2 @ |M|=150 ≈ 22 min/run`) and
extrapolating to the lower-scale points in `REFERENCE_SCALE`:

| Map | |M| | Est. per-run wall |
| --- | --: | --- |
| warehouse-10-20-10-2-1 | 100 | ~15-25 min |
| random-64-64-10 | 50 | ~5-10 min |

**Aggregate (serial CPU-hours):**

| Map | Cells | Mean min/cell | Total CPU-min |
| --- | --: | --- | --: |
| warehouse-10-20-10-2-1 | 350 | ~20 | 7,000 |
| random-64-64-10 | 350 | ~8 | 2,800 |
| **Total** | **700** |  | **~9,800 min ≈ 165 CPU-hours** |

**Wall-clock on 16 workers:** ~10-12 hours.

Factor-of-2-to-3 uncertainty applies (same caveat as the horizon
sweep — LaCAM-Official may hit timeouts on the warehouse map at
larger horizons/agent counts).  Plan for **8-25 hours wall** on
16 workers.

### Post-sweep analysis

```bash
.venv/bin/python scripts/evaluation/validate_smoke_results.py \
    --logs-dir logs/tuning/fov_safety_sweep \
    --no-figure
```

The Theorem-1 invariant (`ours` with `agent_attr=0` across all
700 runs) should hold; this sweep is the strongest test of it
under varied `(r_fov, r_safe)` budgets — if any cell breaks the
invariant, that's a bug in the buffer-aware controller's
treatment of the inflated region F at the constraint boundary.

The §5.3 analysis itself (picking the sensitivity-optimal
`(r_fov, r_safe)`) is a separate post-sweep step — group the
CSV by `(map_path, fov_radius, safety_radius)` and report
violations/throughput trade-offs.

---

## Agent scaling × Tier-1 backend sweep

§5.4 controlled-agent scaling across 6 MAPF solvers.  Tests
whether POE-Solver's safety + throughput properties hold across
Tier-1 backends and as agent density grows.

* **Generator:** `scripts/tuning/generate_scaling_agents_yaml.py`
* **Config:** `configs/tuning/scaling_agents.yaml` (840 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["scaling_agents"] = 2000`
  (already present from the original §5.4 paper-section table).

### Sweep axes

| Axis | Values |
| --- | --- |
| Method | `ours` (single — Tier-2 held constant) |
| `global_solver` | `cbsh2`, `lacam_official`, `lacam3`, `lns2`, `pbs`, `pibt2` |
| Map | `warehouse-10-20-10-2-2`, `random-64-64-10` |
| `num_agents` | 25, 50, 75, 100, 150, 200, 250 |
| `num_humans` | 100 (fixed) |
| `horizon` | 40 (fixed — from horizon tuning) |
| `replan_every` | 20 (fixed, paired with H/2) |
| `fov_radius` | **PLACEHOLDER** (from fov/safety sweep) |
| `safety_radius` | **PLACEHOLDER** (from fov/safety sweep) |
| Seed | 0..9 |
| Steps | 2000 |

**Total cells:** 6 solvers × 2 maps × 7 agent counts × 10 seeds
= **840 runs**.

### ⚠️ Provisional fov/safety values — TODO post-fov-sweep

The `PLACEHOLDER_FOV` and `PLACEHOLDER_SAFE` constants at the top
of `scripts/tuning/generate_scaling_agents_yaml.py` are
**TODOs** pending the fov/safety sweep analysis.  Workflow:

1. Run the fov/safety sweep to completion.
2. From the results CSV, pick the (`fov_radius`, `safety_radius`)
   pair that maximizes throughput at the §5.4 reference scale
   (warehouse, M=100 or M=150) subject to `agent_attr == 0`.
3. Edit the two constants at the top of the generator.
4. Re-run the generator.
5. Diff the YAML to confirm only the placeholder fields changed.
6. Launch.

Current placeholders: `fov_radius=4`, `safety_radius=1` (matching
§5.8 baseline; will be overwritten post-analysis).

### Regenerating the YAML

```bash
python scripts/tuning/generate_scaling_agents_yaml.py
```

### Solver registry verification

All six solver names are registered in
`src/ha_lmapf/global_tier/planner_interface.py`:

| Name in YAML | Resolver location |
| --- | --- |
| `cbsh2` | line 101 (alias `cbsh2_rtc`) |
| `lacam_official` | line 80 |
| `lacam3` | line 63 |
| `lns2` | line 112 (alias `mapf_lns2`) |
| `pbs` | line 108 |
| `pibt2` | line 83 (alias `pibt`) |

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/scaling_agents.yaml \
    --out /tmp/scaling_agents_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

### Full launch (cluster, 16 workers)

**Do NOT launch yet.** Update the fov/safety placeholders first.

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/scaling_agents.yaml \
    --out logs/tuning/scaling_agents \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/scaling_agents_launch.log 2>&1 &
echo "PID: $!"
```

### Wall-time estimate

Per-cell wall time varies dramatically with solver × M:

| Map | M | pibt2 / lacam* | cbsh2 / pbs / lns2 |
| --- | --: | --- | --- |
| random | 25 | 1-3 min | 2-5 min |
| random | 100 | 5-10 min | 10-20 min |
| random | 250 | 15-30 min | 30-90 min (timeouts likely) |
| warehouse_small | 25 | 2-4 min | 4-8 min |
| warehouse_small | 100 | 10-20 min | 20-40 min |
| warehouse_small | 250 | 30-60 min | 60-180 min (timeouts likely) |

**Aggregate estimate:** ~3,000-5,000 CPU-minutes serial →
**~24-36 hours on 16 workers**.  Heavily right-skewed by the
M=250 cells on warehouse with the slower solvers (cbsh2 / pbs /
lns2 may hit the 10s `solver_timeout_s` on every replan at this
scale, in which case throughput collapses but wall stays bounded
by the timeout discipline).

The §5.4 sweep is expected to surface solver-specific failure
modes (PBS Mode-B-style deadlocks, CBSH2 timeout cascades) —
these are scientifically interesting and not "broken" per se.

### Post-sweep analysis

```bash
.venv/bin/python scripts/evaluation/validate_smoke_results.py \
    --logs-dir logs/tuning/scaling_agents \
    --no-figure
```

The Theorem-1 invariant should hold across all 840 cells —
strongest evidence yet that buffer-awareness is solver-independent.
Per-solver throughput curves (one line per solver, x=num_agents)
become the §5.4 headline figure.

---

## §5.4 part 2 — Exogenous-density scaling sweep

Companion to the agent-scaling sweep above.  Fixes
`num_agents = 200` and sweeps `num_humans ∈ {25..250}`.  Together
the two §5.4 sweeps form the controlled-density matrix:

| sweep | `num_agents` | `num_humans` |
| --- | --- | --- |
| `scaling_agents.yaml` | {25..250} | 100 |
| `scaling_humans.yaml` | 200 | {25..250} |

* **Generator:** `scripts/tuning/generate_scaling_humans_yaml.py`
* **Config:** `configs/tuning/scaling_humans.yaml` (840 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["scaling_humans"] = 2000`

### Sweep axes

| Axis | Values |
| --- | --- |
| Method | `ours` |
| `global_solver` | `cbsh2`, `lacam_official`, `lacam3`, `lns2`, `pbs`, `pibt2` |
| Map | `warehouse-10-20-10-2-2`, `random-64-64-10` |
| `num_agents` | 200 (fixed) |
| `num_humans` | 25, 50, 75, 100, 150, 200, 250 |
| `horizon` | 40 (fixed) |
| `replan_every` | 20 (fixed) |
| `fov_radius` | **PLACEHOLDER** (from fov/safety sweep) |
| `safety_radius` | **PLACEHOLDER** (from fov/safety sweep) |
| Seed | 0..9 |

**Total cells:** 6 × 2 × 7 × 10 = **840 runs**.

### Pre-launch TODO

Same as `scaling_agents`: update `PLACEHOLDER_FOV` and
`PLACEHOLDER_SAFE` at the top of the generator after the
fov/safety sweep analysis, then re-run.  The two scaling
sweeps should be re-generated **together** so their fov/safety
values stay synchronized.

### Wall-time estimate

Heavier base load than `scaling_agents` because `num_agents = 200`
is fixed at the upper end.  Per-cell wall scales with both
controlled and exogenous density:

| Map | X | pibt2 / lacam* | cbsh2 / pbs / lns2 |
| --- | --: | --- | --- |
| random | 25 | 5-10 min | 10-20 min |
| random | 100 | 10-15 min | 20-40 min |
| random | 250 | 15-25 min | 30-90 min (timeouts likely) |
| warehouse_small | 25 | 10-15 min | 20-40 min |
| warehouse_small | 100 | 15-25 min | 30-60 min |
| warehouse_small | 250 | 25-45 min | 60-180 min (timeouts likely) |

**Aggregate estimate:** ~30-48 hours on 16 workers (heavily
right-skewed by warehouse × cbsh2/pbs/lns2 × X=250 cells where
solver_timeout_s=10s caps wall-clock per replan but error rate
approaches 100%).

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/scaling_humans.yaml \
    --out /tmp/scaling_humans_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

### Full launch

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/scaling_humans.yaml \
    --out logs/tuning/scaling_humans \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/scaling_humans_launch.log 2>&1 &
echo "PID: $!"
```

---

## §5.5 task allocator comparison sweep

§5.5 comparison of four task allocators at fixed Tier-1
(LaCAM-Official) and fixed `(horizon, replan, fov, safe)`.

* **Generator:** `scripts/tuning/generate_allocator_comparison_yaml.py`
* **Config:** `configs/tuning/allocator_comparison.yaml` (200 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["allocator_comparison"] = 2000`

### Allocator → registry-name mapping

| Paper §5.5 name | `SimConfig.task_allocator` | Hyperparameters |
| --- | --- | --- |
| Conflict-Aware (a.k.a. Congestion-Avoidance) | `congestion_avoidance` | `lambda_conflict=0.5`, `max_rounds=5` |
| Greedy | `greedy` | (none) |
| Hungarian | `hungarian` | (none) |
| Auction | `auction` | `auction_epsilon=0.01` |

Note: the legacy alias `conflict_aware` was removed in Phase 5
of the migration (`src/ha_lmapf/task_allocator/__init__.py:24-28`);
all references use `congestion_avoidance` (paper §4.2 terminology).

`auction_epsilon` was added as a SimConfig field in commit
`40673c4` so the spec value (0.01) is explicit in the YAML
rather than relying on the factory's default.

### Sweep axes (per-group)

| Axis | warehouse-10-20-10-2-2 | random-64-64-10 |
| --- | --- | --- |
| `num_agents` | 50, 100, 150, 200 | 50 |
| `num_humans` | 60 | 20 |
| `horizon` | 40 | 40 |
| `replan_every` | 20 | 20 |
| `fov_radius` | **PLACEHOLDER** | **PLACEHOLDER** |
| `safety_radius` | **PLACEHOLDER** | **PLACEHOLDER** |
| Seed | 0..9 | 0..9 |

**Cell count:**

| | groups | cells |
| --- | ---: | ---: |
| warehouse-10-20-10-2-2 | 4 (one per allocator) | 4 × 4 × 10 = 160 |
| random-64-64-10 | 4 (one per allocator) | 4 × 1 × 10 = 40 |
| **total** | **8** | **200** |

### Pre-launch TODO

Same pattern as the other tuning sweeps: update
`PLACEHOLDER_FOV` and `PLACEHOLDER_SAFE` at the top of
`scripts/tuning/generate_allocator_comparison_yaml.py` after the
fov/safety sweep analysis, then re-run the generator.

### Wall-time estimate

Smaller scale than the §5.4 scaling sweeps:

| Map | M | Est. per-cell wall |
| --- | --: | --- |
| random | 50 | 5-10 min |
| warehouse | 50 | 10-20 min |
| warehouse | 100 | 15-25 min |
| warehouse | 150 | 20-35 min |
| warehouse | 200 | 30-50 min (LaCAM may approach timeout) |

**Aggregate:** ~6,000-10,000 CPU-min serial → **~5-10 hours on
16 workers**.

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/allocator_comparison.yaml \
    --out /tmp/allocator_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

The first group (`congestion_avoidance` on warehouse) starts at
M=50 — expected wall ~10-15 min.  For a faster dry-run, use a
single-cell YAML targeting greedy + random + M=50.

### Full launch

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/allocator_comparison.yaml \
    --out logs/tuning/allocator_comparison \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/allocator_comparison_launch.log 2>&1 &
echo "PID: $!"
```

---

## §5.4 scaling sweeps (four-way split)

The §5.4 controlled-density experiments are split into **four
independent sweeps** that cleanly partition across two clusters
for parallel execution:

| Sweep | YAML | Generator | Axis | fov/safe |
| --- | --- | --- | --- | :---: |
| #1 | `scaling_agents_fov3_safe1.yaml` | `generate_scaling_agents_fov3_safe1_yaml.py` | `num_agents ∈ {25..250}`, X=100 | (3, 1) |
| #2 | `scaling_agents_fov4_safe2.yaml` | `generate_scaling_agents_fov4_safe2_yaml.py` | `num_agents ∈ {25..250}`, X=100 | (4, 2) |
| #3 | `scaling_humans_fov3_safe1.yaml` | `generate_scaling_humans_fov3_safe1_yaml.py` | `num_humans ∈ {25..250}`, M=200 | (3, 1) |
| #4 | `scaling_humans_fov4_safe2.yaml` | `generate_scaling_humans_fov4_safe2_yaml.py` | `num_humans ∈ {25..250}`, M=200 | (4, 2) |

Each YAML is **560 cells** (4 solvers × 2 maps × 7 axis-values × 10 seeds).

### Common settings across all four sweeps

| Knob | Value |
| --- | --- |
| `method` | ours |
| `global_solver` | one of `lacam_official`, `lacam3`, `lns2`, `pibt2` (per group) |
| `horizon` | 40 |
| `replan_every` | 20 |
| `steps` | 2000 |
| `task_allocator` | `congestion_avoidance` (`lambda_conflict=0.5`, `max_rounds=5`) |
| `log_violations_timeline` | true |
| `seeds` | 0..9 |
| Maps | `warehouse-10-20-10-2-2`, `random-64-64-10` |

### Differences from the original (deprecated) sweeps

| | Original (deprecated) | New (four-way split) |
| --- | --- | --- |
| Solvers | 6 (incl. cbsh2, pbs) | **4** (cbsh2, pbs dropped after horizon-tuning showed them dominated) |
| fov/safe | 2 PLACEHOLDER constants | **Hardcoded** at (3,1) and (4,2) — no pre-launch edit needed |
| Files per axis | 1 combined | **2 separate** (one per fov/safe setting) |
| Total cells | 840 + 840 = 1,680 | 4 × 560 = **2,240** (more cells, but split across more sweeps for finer scheduling) |

### Cluster scheduling

```
Cluster 1 (run sequentially):
    scaling_agents_fov3_safe1 → scaling_agents_fov4_safe2

Cluster 2 (run sequentially):
    scaling_humans_fov3_safe1 → scaling_humans_fov4_safe2
```

Sequential within a cluster avoids cross-sweep CPU contention.
Cross-cluster runs are fully independent (no shared output dirs,
no shared sidecar paths).

### Launch command (per sweep)

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/scaling_agents_fov3_safe1.yaml \
    --out logs/tuning/scaling_agents_fov3_safe1 \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/scaling_agents_fov3_safe1_launch.log 2>&1 &
echo "PID: $!"
```

Substitute the YAML / output-dir name for the other three sweeps.

---

## §5.5 allocator comparison sweeps (two-way split)

The §5.5 allocator comparison is split into **two independent
sweeps** at the same (r_fov, r_safe) operating points used by
the §5.4 scaling experiments:

| Sweep | YAML | Generator | fov/safe |
| --- | --- | --- | :---: |
| #1 | `allocator_comparison_fov3_safe1.yaml` | `generate_allocator_comparison_fov3_safe1_yaml.py` | (3, 1) |
| #2 | `allocator_comparison_fov4_safe2.yaml` | `generate_allocator_comparison_fov4_safe2_yaml.py` | (4, 2) |

Each YAML is **200 cells** (160 warehouse + 40 random) for a
total of **400 cells** across the two files.

### Common axes (per sweep)

| Axis | warehouse-10-20-10-2-2 | random-64-64-10 |
| --- | --- | --- |
| `num_agents` | 50, 100, 150, 200 | 50 |
| `num_humans` | 60 | 20 |
| `horizon` / `replan_every` | 40 / 20 | 40 / 20 |
| `task_allocator` | `congestion_avoidance`, `greedy`, `hungarian`, `auction` | same |
| Seeds | 0..9 | 0..9 |

### Allocator hyperparameters (explicit in every YAML)

| Allocator | Hyperparameters |
| --- | --- |
| `congestion_avoidance` | `lambda_conflict=0.5`, `max_rounds=5` |
| `greedy` | (none) |
| `hungarian` | (none) |
| `auction` | `auction_epsilon=0.01` |

All hyperparameters match the paper §5.5 spec and the SimConfig
defaults but are emitted explicitly for audit-trail visibility
(consistent with the `auction_epsilon` field added in commit
`40673c4`).

### Cluster scheduling

Both sweeps can run sequentially on a single cluster (no
inter-sweep dependency, no need to parallelize across clusters).
Estimated total wall on 16 workers: **~10-16 h** (~5-8 h per
sweep, matching the per-sweep estimate documented in the
deprecated `allocator_comparison.yaml` section).

If a cluster is available immediately, either sweep can launch
first; the order doesn't matter for downstream analysis.

### Launch command (per sweep)

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/allocator_comparison_fov3_safe1.yaml \
    --out logs/tuning/allocator_comparison_fov3_safe1 \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/allocator_comparison_fov3_safe1_launch.log 2>&1 &
echo "PID: $!"
```

Substitute the YAML / output-dir name for the (4, 2) sweep.

### Why the split

Mirrors the §5.4 four-way scaling split:

* fov/safe values are HARDCODED in each generator (not
  PLACEHOLDERs).  No pre-launch edit required.
* Per-(fov, safe) data lives in separate output directories,
  so post-sweep analysis can read one operating point at a
  time without filtering by column.
* Two clusters (or one cluster running back-to-back) split the
  work cleanly.

---

## §5.6 deadlock + wait-time decomposition sweep

§5.6 measures the population-level deadlock streak and the
wait-time decomposition (safe-wait vs yield-wait vs execution)
across three methods as controlled-agent density grows.  Uses
the new ``Metrics.max_global_no_progress_streak`` and
``Metrics.global_no_progress_steps`` fields (commit `eae3758`)
alongside the existing ``safe_wait_steps`` / ``yield_wait_steps``.

* **Generator:** `scripts/tuning/generate_deadlock_wait_yaml.py`
* **Config:** `configs/tuning/deadlock_wait.yaml` (270 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["deadlock_wait"] = 2000`

### Sweep axes

| Axis | Values |
| --- | --- |
| Map | `warehouse-10-20-10-2-2` (fixed) |
| Method | `ours`, `pibt2_fr`, `lacam_blind` |
| `num_agents` | 50, 100, 150, 200, 250, 300, 350, 400, 450 |
| `num_humans` | 100 (fixed) |
| `horizon` / `replan_every` | 40 / 20 (base — `pibt2_fr` factory overrides to 20/1 at dispatch) |
| `fov_radius` / `safety_radius` | 4 / 1 |
| `global_solver` (base) | `lacam_official` (overridden by `pibt2_fr` / `lacam_blind` factories) |
| `task_allocator` | `congestion_avoidance` (λ=0.5, max_rounds=5) |
| Seeds | 0..9 |
| `log_violations_timeline` | true |

**Cell count:** 3 methods × 9 M-values × 10 seeds = **270 runs**.

### Method handling

The YAML's `base:` section is shared across all three methods.
The harness's `_apply_method` dispatch routes each cell through
the appropriate factory at config-build time:

| Method | Factory | What gets overridden |
| --- | --- | --- |
| `ours` | identity (base unchanged) | (nothing) |
| `pibt2_fr` | `make_pibt2_fr_config` | `global_solver=pibt2`, `replan_every=1`, `horizon=20`, `controller_kind=global_only` |
| `lacam_blind` | `make_lacam_blind_config` | `global_solver=lacam_official`, `controller_kind=global_only` |

The post-dispatch values surface in the CSV under `applied_*`
columns (commit `c685039`); read those rather than the raw YAML
columns when analyzing.

### Why RHCR is not included

RHCR is deferred — see `docs/RHCR_DEFERRED.md`.  `lacam_blind`
is the §5.5 / §5.8 substitute preserving the rigid-follower
comparison at LaCAM Tier-1 quality.

### Wall-time estimate

Per-cell wall scales with `num_agents`.  Reference: §5.8 smoke
at warehouse + M=150 ≈ 22 min/run.  For this sweep:

| M | ours | pibt2_fr | lacam_blind |
| --: | --- | --- | --- |
| 50 | ~5-10 min | ~3-5 min | ~5-10 min |
| 150 | ~20-25 min | ~10-15 min | ~20-25 min |
| 250 | ~30-45 min | ~15-25 min | ~30-45 min |
| 350 | ~45-60 min (LaCAM partial_anytime more often) | ~25-40 min | ~45-60 min |
| 450 | ~60-90 min (LaCAM partial_anytime dominant) | ~35-60 min | ~60-90 min |

**Aggregate (serial CPU-min):** ~14,000-22,000 min → **~15-25
hours on 16 workers**.  M=400/450 cells for `ours` and
`lacam_blind` will produce many LaCAM partial_anytime returns;
this is expected (Phase D Fix 1 handles them cleanly) and is
itself a §5.6 finding worth analyzing.

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/deadlock_wait.yaml \
    --out /tmp/deadlock_wait_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

### Full launch (cluster, 16 workers)

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/deadlock_wait.yaml \
    --out logs/tuning/deadlock_wait \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/deadlock_wait_launch.log 2>&1 &
echo "PID: $!"
```

### Post-sweep analysis

The §5.6 figure groups by `(method, num_agents)` and reports:

* `max_global_no_progress_streak` and `global_no_progress_steps`
  — pick the deadlock threshold post hoc (the metric records the
  full streak distribution rather than a hardcoded boolean).
* `safe_wait_steps`, `yield_wait_steps`, and derived
  `execution_steps = num_agents * steps - total_wait_steps`.
* Invariant check: `total_wait_steps == safe_wait_steps +
  yield_wait_steps` (pinned in `core/types.py:385`).

---

## §3 soft-safety ablation sweep

§3 ablation of the hard-vs-soft safety modes.  POE-Solver's local
A* treats the inflated buffer F either as an impassable region
(``hard_safety=True``, the paper's Theorem-1 setting) or as a
finite-penalty region with ``BLOCKED_CELL_COST=50``
(``hard_safety=False``, soft mode).  The audit confirmed the
predicted Theorem-1 break under soft mode; the end-to-end test
``tests/test_soft_safety_relaxation.py`` pins the relaxation
direction.  No sweep had ever exercised soft mode in production
before this one.

* **Generator:** `scripts/tuning/generate_soft_safety_ablation_yaml.py`
* **Config:** `configs/tuning/soft_safety_ablation.yaml` (180 runs)
* **Harness entry:** `PAPER_SECTION_TO_STEPS["soft_safety_ablation"] = 2000`
* **Companion test:** `tests/test_soft_safety_relaxation.py`

### Sweep axes

| Axis | Values |
| --- | --- |
| Map | `warehouse-10-20-10-2-2` (fixed) |
| Method | `ours` (fixed — only POE-Solver consumes `hard_safety`) |
| `hard_safety` | **true** (hard arm), **false** (soft arm) |
| `num_agents` | 50, 100, 150, 200, 250, 300, 350, 400, 450 |
| `num_humans` | 100 (fixed) |
| `horizon` / `replan_every` | 40 / 20 |
| `fov_radius` / `safety_radius` | 4 / 1 |
| `global_solver` | `lacam_official` |
| `task_allocator` | `congestion_avoidance` (λ=0.5, max_rounds=5) |
| Seeds | 0..9 |
| `log_violations_timeline` | true |

**Cell count:** 2 hard_safety values × 9 M-values × 10 seeds = **180 runs**.

### Why `cost_soft` is not in the sweep

`AStarLocalPlanner.BLOCKED_CELL_COST = 50` is a class constant at
`src/ha_lmapf/local_tier/local_planner.py:38`.  The paper fixes
this value and does not promise a cost sweep.  Exposing it as a
SimConfig field would be a separate change (a ~3-line refactor)
and would only be warranted if a cost-sensitivity sub-ablation
is added to the paper.

### Expected contrast

| | hard arm | soft arm |
| --- | --- | --- |
| `violations_agent_attributable` | **0 across all M** (Theorem 1) | **> 0 at high M** (encroachments forced by congestion) |
| Throughput | collapses under high M (agents safety-wait) | preserved (agents walk through buffer) |
| `safe_wait_steps` | grows with M | low |
| `max_global_no_progress_streak` | long under high M | short |

### Wall-time estimate

Cell load scales with `num_agents`.  Soft mode tends to run faster
per cell (no safety-wait stalls) but the M=400/450 hard-arm cells
will be slow due to LaCAM partial_anytime cascades.  Per the §5.6
estimate at warehouse + M=150 ≈ 22 min:

| M | hard arm | soft arm |
| --: | --- | --- |
| 50 | ~5-10 min | ~5-10 min |
| 150 | ~20-25 min | ~15-20 min |
| 250 | ~30-45 min | ~25-35 min |
| 400 | ~50-70 min (LaCAM partial_anytime dominant) | ~40-55 min |
| 450 | ~60-90 min | ~50-70 min |

**Aggregate:** ~9,000-13,000 CPU-min serial → **~10-14 h on
16 workers**.

### Dry-run

```bash
.venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/soft_safety_ablation.yaml \
    --out /tmp/soft_safety_ablation_dryrun \
    --workers 1 --limit 1 --log-level INFO
```

### Full launch (cluster, 16 workers)

```bash
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config configs/tuning/soft_safety_ablation.yaml \
    --out logs/tuning/soft_safety_ablation \
    --workers 16 \
    --log-level INFO \
    > logs/tuning/soft_safety_ablation_launch.log 2>&1 &
echo "PID: $!"
```

### Post-sweep analysis

The §3 ablation figure groups by `(hard_safety, num_agents)` and
plots:
* `violations_agent_attributable` mean ± std per M
  (hard arm should be a flat 0; soft arm rising with M).
* Throughput per M (hard arm collapsing; soft arm preserved).
* `safe_wait_steps` / `max_global_no_progress_streak` per M.

Theorem-1 invariant check:
```
hard arm: all 90 runs must show violations_agent_attributable == 0.
```
A non-zero value in the hard arm indicates a regression in the
controller's hard-mode enforcement at
``agent_controller.py:238`` and should fail the validator.
