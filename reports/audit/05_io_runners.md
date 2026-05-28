# Audit step 05 — io / config loaders / scripts/evaluation runners

Scope: `src/ha_lmapf/io/` (4 modules), the 92 YAML files under
`configs/`, and the experiment-runner stack in
`scripts/evaluation/run_paper_experiment.py`.

Repro script at `scripts/diagnostics/audit_io_runners.py` (mirror of
`/tmp/audit_io_runners.py`).  No source modifications.  One tiny smoke
run (5×5 open map, 2 agents, 20 steps, seed 0) ran end-to-end to
verify CSV alignment.

---

## 1. Config-key coverage — **PASS (with 1 BUG)**

`scripts/evaluation/run_paper_experiment.py` consumes YAMLs in two
layers:

| Layer | Reader | Recognised keys |
|---|---|---|
| Top-level spec | `expand_manifest` (`run_paper_experiment.py:194-223`) | `name`, `base`, `seeds`, `groups`, **`max_invalid_fraction`** (read by `main()` at L689-705) |
| Inner cell (= `base ∪ groups[*].sweep`) | `_build_sim_config` (L260-271) | every `SimConfig` field name + `method` |

`_build_sim_config` at L267-269 **warns** on unknown inner keys:
```python
extra = {k: v for k, v in cfg.items() if k not in sim_cfg_fields}
if extra:
    logger.warning("ignoring unknown SimConfig fields: %s", sorted(extra))
```
So an unknown inner key is not silently dropped — it's logged at
`WARNING` level.  But the value still never reaches the simulator.

### Silent-no-op keys (set in YAML, never read by runner or simulator)

92 YAMLs scanned.  **One** silent-no-op key surfaced.

| Key | YAMLs setting it | Intended consumer | Actual fate |
|---|---|---|---|
| `max_invalid_fraction` | 13 (all under `configs/tuning/`) | runner's top-level `spec["max_invalid_fraction"]` (read at L689-697) | **silently nested under `base:` at indent 2** — runner's top-level lookup misses it; key passes through to inner cell; `_build_sim_config` warns "ignoring unknown SimConfig fields: ['max_invalid_fraction']" |

**This is BUG #1 in the audit (see "BUGS FOUND" at bottom).**

### Untunable `SimConfig` fields (defined but never set by any YAML)

22 of `SimConfig`'s 50+ fields are never set by any YAML in `configs/`.

| Field | Default | Notes |
|---|---|---|
| `seed` | `0` | by design — injected per-row by `expand_manifest` from `seeds: [...]` |
| `controller_kind` | `'default'` | covered by `method` axis instead |
| `task_arrival_rate` | `None` | by design — `None` triggers auto-compute `H+W` (audit §2) |
| `task_mode` | `'poisson'` | poisson is the lifelong default; `'immediate'` is the Li-2022 alt |
| `task_stream_path` | `None` | only used by replay-driven runs |
| `task_arrival_percentage` | `0.9` | unused/legacy; flagged as gap |
| `human_model_params` | `<no default>` | field annotated but with `field(default_factory=dict)`; never set by any YAML |
| `disable_local_replan` | `False` | ablation toggle; never set in configs (would belong under `groups[*].sweep`) |
| `disable_conflict_resolution` | `False` | ablation toggle (note: `configs/ablation_no_comms.yaml` exists but uses a different mechanism) |
| `disable_safety` | `False` | ablation toggle |
| `debug_guidance_trace` | `False` | diagnostic; opt-in via test fixtures |
| `commit_horizon` | `0` | commitment-persistence knob |
| `delay_threshold` | `0.0` | commitment-persistence knob |
| `deviation_threshold` | `1.0` | jaccard threshold for major-deviation flag |
| `execution_delay_prob` | `0.0` | robust-MAPF probability |
| `execution_delay_steps` | `1` | robust-MAPF duration |
| `fallback_wait_limit` | `5` | ablation-only fallback |
| `eta_w` | `0.2` | emergency-replan threshold; un-tunable from YAML — only the rolling-horizon constructor accepts it |
| `replan_min_gap` | `3` | anti-thrash guard for `eta_w` trigger |
| `deadlock_streak_threshold` | `100` | per-agent streak threshold for §5.7 deadlock count |
| `buffer_stuck_warn_threshold` | `20` | warn-only |
| `time_budget_ms` | `0.0` | legacy; prefer `solver_timeout_s` |

These are **not bugs** — most are intentionally pinned to defaults the
paper specifies, or are only exercised by tests / ablation harnesses
that build `SimConfig` programmatically.  Flagged here for awareness:
if any of these need to vary in a future sweep, the YAML schema is
already wired for it (just add the field under `base:` or `sweep:`).

---

## 2. Task-stream generator — **PASS**

### 2.1 Arrival-rate formula (live behaviour)

`simulator.py:_generate_task_stream` (`simulator.py:544-626`):

| Step | Code | Formula |
|---|---|---|
| Initial batch | L562-573 | One task per agent at `release_step=0` (no agent starts idle) |
| Auto-compute `release_rate` | L582-583 | `release_rate = env.height + env.width` per agent (when `task_arrival_rate=None`) |
| Effective per-agent rate | L594 | `effective_rate = release_rate / n_agents` |
| Branch A: exponential | L595-608 | If `effective_rate >= 1.0`: exponential inter-arrivals with scale `effective_rate` |
| Branch B: Poisson batching | L609-624 | If `effective_rate < 1.0` (many agents / low rate): `lam = 1/effective_rate` tasks/step; `n_arrivals = rng.poisson(lam)` per step |

Theoretical system-rate: $\lambda_{\text{sys}} = \mathrm{num\_agents} / (H + W)$ tasks/step.

### 2.2 `arrival_rate_per_step` CSV column (Prompt 6)

`metrics.py:784-787` computes the **empirical** rate from observed releases:

```python
arrival_rate = float(self.total_tasks) / float(total_steps)
```

This is the column that lands in CSV row.  It is the realised system
arrival rate — equal to the theoretical $n/(H+W)$ in expectation but
free to drift on a single run due to Poisson noise plus the initial
batch of `num_agents` tasks at step 0.

**Smoke run** (5×5 open map, 2 agents, 20 steps, seed 0):

| Quantity | Value |
|---|---|
| Theoretical $n/(H+W)$ | $2 / 10 = 0.200$ |
| Empirical `arrival_rate_per_step` | $5 / 20 = 0.250$ |
| Drift explanation | Initial batch contributes 2 tasks at step 0; Poisson sampled 3 more across 20 steps → 5/20 = 0.25 vs expected 0.20 from the steady-state component alone |

This is the documented behaviour, not a bug.  The CSV column reports
the observed rate (the right quantity for arrival-saturation diagnostics);
the theoretical formula governs the *expectation* and is what the load-regime
audit (§5.1) keys off.

### 2.3 Poisson-batching branch (effective_rate < 1)

L609-624 confirmed.  The Poisson branch is the one that fires for the
paper's heavy regimes (e.g. $|M|=100$ on a 64×64 random map →
$\text{effective\_rate} = 128/100 = 1.28 \ge 1$, so this map actually
uses Branch A; but on warehouse `10-20-10-2-2` (66×38) →
$\text{effective\_rate} = 104/100 = 1.04 \ge 1$ — both headline maps stay
in Branch A at `|M|=100`).  Branch B activates when `num_agents > H+W`.

---

## 3. Experiment runner — **PASS**

### 3.1 Spec → run flow

`expand_manifest` (`run_paper_experiment.py:194-223`) crosses
`base × sweep cells × seeds` to produce one row per (config, seed)
pair.  Each row carries `run_id`, `experiment`, `seed`, `config`.
Then `run_one` builds the `SimConfig`, instantiates `Simulator`,
calls `sim.run()`, and emits a flat CSV row.

| Spec field | Read in code | Reaches simulator? |
|---|---|---|
| `name` | `expand_manifest:202` | logged only |
| `base` | `expand_manifest:200` | merged into each cell |
| `seeds` | `expand_manifest:201` | passed as `run_cfg["seed"]` |
| `groups[*].sweep` | `expand_manifest:205-212` | crossed into per-cell `run_cfg` |
| `max_invalid_fraction` | `main():689-705` | logged; downstream validator was intended to consume it (currently not implemented) |
| Inner cell `method` | `_build_sim_config:263, _apply_method:231-257` | dispatches via `_apply_method` |
| Inner cell `<SimConfig field>` | `_build_sim_config:266` | passed via kwargs |
| Inner cell other | `_build_sim_config:267-269` | **warned and dropped** |

### 3.2 `status == 'ok'` semantics

`run_one` (`run_paper_experiment.py:315-372`):

```python
t0 = time.perf_counter()
try:
    sim_cfg = _build_sim_config(run_cfg)        # could raise
    sim = Simulator(sim_cfg)                    # could raise
    metrics: Metrics = sim.run()                # could raise
    m = asdict(metrics)                         # could raise
    # ... timeline sidecar write (could raise) ...
    record.update(m)
    record["status"] = "ok"          # ← only reached on full success
    record["error_msg"] = ""
except Exception as exc:
    record["status"] = "error"
    record["error_msg"] = f"{type(exc).__name__}: {exc}"
    logger.warning(...)
record["wall_clock_s"] = round(time.perf_counter() - t0, 4)
```

**`status = 'ok'` is assigned only after**:
1. `_build_sim_config` returned (no unknown-field exception),
2. `Simulator.__init__` returned (placement + planner init succeeded),
3. `sim.run()` returned (the four `finalize()` invariants asserted in audit 01 §4 all held — any AssertionError there routes to the except),
4. `asdict(metrics)` and the timeline-sidecar block completed.

**No crash-writes-ok path** exists in the code reviewed.  Confirmed by
inspection.

### 3.3 CSV alignment — end-to-end

| Layer | Length | Match |
|---|---:|:--:|
| `MetricsTracker.csv_header()` | 67 | — |
| `tracker.to_csv_row(metrics)` (smoke run) | 67 | ✓ |
| `csv.DictReader` parse of written row | 67 fields | ✓ |
| Sample fields parsed correctly | `steps=20`, `total_released_tasks=5`, `throughput=0.250000`, `arrival_rate_per_step=0.250000`, `throughput_utilization=1.000000` | ✓ |

End-to-end alignment **PASS**.  The Prompt-1 / audit-01 in-process
length check (67 == 67) is reproduced here against a real CSV byte
stream — `csv.writer` + `csv.DictReader` round-trip preserves column
order and count.

---

## Summary

| Area | Verdict | Evidence |
|---|:--:|---|
| §1 YAML key coverage | **PASS (1 bug)** | 92 YAMLs scanned; 1 silent-no-op key (`max_invalid_fraction`) surfaced as BUG #1 |
| §1 Untunable SimConfig fields | informational | 22 fields never set by any YAML — most by design |
| §2.1 Arrival-rate formula `n / (H+W)` | **PASS** | `simulator.py:582-594` confirmed live |
| §2.2 `arrival_rate_per_step` CSV column | **PASS** | computed at `metrics.py:784-787` as `total_tasks / total_steps` (empirical) |
| §2.3 Poisson-batching branch | **PASS** | `simulator.py:609-624`; activates when `effective_rate < 1` (i.e. `n_agents > H+W`) |
| §3.1 Spec → simulator flow | **PASS** | `expand_manifest` × `_build_sim_config` × `_apply_method` |
| §3.2 `status == 'ok'` ⇒ run completed | **PASS** | `status='ok'` assigned only inside the try block AFTER `sim.run()` returns; any exception routes to except |
| §3.3 CSV header == row length end-to-end | **PASS** | 67 == 67 == 67 (in-process, byte-stream, parsed-back) |

---

## BUGS FOUND

### BUG #1 — `max_invalid_fraction` silently ignored in all 13 tuning YAMLs

**File**: every YAML in the table below (and the runner's read site).

**Symptom**: 13 tuning YAMLs declare `max_invalid_fraction: 0.0` at indent
level 2 (nested under `base:`).  The runner at
`run_paper_experiment.py:690` reads `spec["max_invalid_fraction"]` —
the **top-level** spec.  Because the key is nested, the top-level
lookup misses it; `spec_max_invalid_fraction` stays `None`; the log
line at L698-705 prints `sweep-level max_invalid_fraction=<unset>`.

The value also propagates into the inner cell when `expand_manifest`
copies `base` into each per-cell config; `_build_sim_config` then emits
the warning `"ignoring unknown SimConfig fields: ['max_invalid_fraction']"`.

**Affected YAMLs** (all 13 confirmed by grep on `max_invalid_fraction`,
all at indent 2 inside `base:`):

```
configs/tuning/horizon_replan_full.yaml          line 70
configs/tuning/soft_safety_ablation.yaml          line 75
configs/tuning/scaling_agents_fov4_safe2.yaml     line 69
configs/tuning/scaling_humans_fov4_safe2.yaml     line 67
configs/tuning/scaling_humans.yaml                line 76
configs/tuning/scaling_agents_fov3_safe1.yaml     line 69
configs/tuning/deadlock_wait.yaml                 line 80
configs/tuning/allocator_comparison_fov3_safe1.yaml line 73
configs/tuning/scaling_agents.yaml                line 72
configs/tuning/scaling_humans_fov3_safe1.yaml     line 67
configs/tuning/allocator_comparison_fov4_safe2.yaml line 73
configs/tuning/fov_safety_sweep.yaml              line 72
configs/tuning/allocator_comparison.yaml          line 75
```

**Impact**: the runner's `max_invalid_fraction` log line is the only
surface mention of the per-sweep validity threshold.  Even if it were
read correctly, an additional gap exists: `validate_paper_claims.py`
does NOT reference `max_invalid_fraction` (grepped — zero hits), so no
downstream code actually enforces the threshold against the produced
CSV either.  The intent (P7 follow-up: per-sweep "tolerate at most X%
invalid rows") is partially wired (the field is read, logged) and
partially not (the gate isn't actually checked anywhere).

**Proposed fix (NOT applied)** — two options:

  - **Option A: move the line in each YAML to top-level.**  In each
    of the 13 files, dedent
    `  max_invalid_fraction: 0.0` to
    `max_invalid_fraction: 0.0`
    (and verify the runner now logs the value instead of `<unset>`).
    This fixes the silent-drop and the spurious "unknown SimConfig
    field" warning.
  - **Option B: also accept the nested form.**  In
    `run_paper_experiment.py:690`, fall back to
    `spec.get("base", {}).get("max_invalid_fraction")` when the
    top-level lookup misses.  Less invasive but masks the YAML schema
    error.

  Either way, a separate follow-up is needed to make
  `validate_paper_claims.py` actually consume the value if the field is
  intended to govern sweep-level acceptance.

---

## GAPS (no fix proposed)

1. **22 SimConfig fields are not tunable from any committed YAML.**
   Most by design (see §1 table).  A few (`eta_w`, `replan_min_gap`,
   `deadlock_streak_threshold`, `execution_delay_prob`,
   `execution_delay_steps`) are arguably worth a top-level knob for
   the next paper revision but no current sweep needs them.

2. **`task_arrival_percentage` is defined (`SimConfig.task_arrival_percentage = 0.9`)
   but unused** (grep for the field name returns only its definition
   in `types.py`).  Candidate for deletion.

3. **`validate_paper_claims.py` does not reference `max_invalid_fraction`.**
   Even with BUG #1 fixed, the gate would be enforced only by manual
   inspection of the runner's log line.  Worth wiring into the
   validator if the threshold is meant to be a hard gate.
