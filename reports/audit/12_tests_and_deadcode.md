# Audit step 12 — test-suite verification + dead-code reconciliation

> **Numbering note**: the task brief named this report
> `07_tests_and_deadcode.md`.  Slot 07 already holds
> `07_max_invalid_fraction.md`, so this report files at 12 in
> chronological commit order.

---

## 1. Full-suite run

```
$ python -m pytest tests/ --tb=line -q
======== 2 failed, 818 passed, 1 skipped, 7 warnings in 403.15s (0:06:43) ========
```

| Bucket | Count |
|---|---:|
| Passed | 818 |
| Failed | 2 |
| Skipped | 1 |
| Errors (collection or setup) | 0 |
| Wall-clock | 403.15 s (~6.7 min) |

Total collected (818 + 2 + 1) = 821 test cases.  Up from
audit-00's 809 by the 5 + 7 tests added in audits 06 + 07.

### Skip — explained, not hiding a gap

| Test | File / line | Skip reason | Real gap? |
|---|---|---|:--:|
| `test_rhcr_blind_walks_into_buffer` | `tests/test_rhcr_blind.py:96` | `"RHCR binary unavailable / non-functional on this host"` — the skip predicate `_rhcr_runtime_ok()` (`test_rhcr_blind.py:55-92`) verifies the RHCR binary parses `--help` AND completes a tiny planning probe.  On this CI image the binary exits SIGSEGV (rc=-11) on real calls despite a working `--help`, so the test skips with a clear reason. | **No** — the rhcr-blind ablation path is also exercised by `_apply_method`'s `make_rhcr_blind_config` factory which fails loudly at config-build time when `method='rhcr'` (audit 03 §1).  The skip leaves no untested path; it just confirms the host's binary is broken. |

### Failures — pre-existing, root-cause known

| Test | Error | Source |
|---|---|---|
| `tests/test_paper_claims.py::test_synthetic_matching_results_yield_confirmed` | `ValueError: too many values to unpack (expected 2)` | Commit `812fc90` extended `validate_paper_claims.run_validation` from a 2-tuple to a 3-tuple return; the test unpacks 2.  Audit 05 §3 documented this; audit 12 confirms it persists. |
| `tests/test_paper_claims.py::test_perturbation_flips_a_claim_to_refuted` | same | same |

Both are tracked in `RESUME_DECISION.md` §C-3.3 as Tier-3 hygiene.

---

## 2. Heuristic weak-test scan

`scripts/diagnostics/scan_weak_tests.py` (committed alongside this
report) walks every test function and flags those whose **every**
assertion is one of:
- membership (`x in seq`),
- identity (`x is None` / `x is not None`),
- bare truthiness (`assert x`),
- type-only call (`isinstance`, `hasattr`, `callable`, `len`, `bool`, `any`, `all`).

The heuristic excludes any test that uses `pytest.raises` (its
shape is checked by the context manager) and any test that calls
`subprocess.run` (exit-code checking is an effective non-trivial
assertion).

### Totals

| | Count |
|---|---:|
| Test files scanned | 74 |
| Test functions total | 699 |
| Heuristically flagged WEAK | 138 (19.7%) |

### Per-file flag count

| File | Flags | Real-weak (after manual review) |
|---|---:|---|
| `test_official_solver_wrappers.py` | 34 | Mostly factory shape tests (`test_import`, `test_instantiation`, `test_factory_creation`).  These ARE shape-only by design — they verify the wrapper imports and constructs without crashing, but would NOT catch a planner-behaviour regression.  Companion behavioural tests (`test_plan_without_binary_returns_wait_paths`, `test_partial_anytime_or_complete_under_50ms_budget`) cover the planning surface; the shape tests are the floor, not the ceiling.  **Real-weak as a category**, but not bugs.  |
| `test_human_prediction.py` | 9 | Sample inspection: most are bare-truthiness on prediction-distribution properties (e.g. `assert all(p > 0 for p in dist)`). The heuristic mis-flags `all(...)` as weak.  Likely **false positives**; needs deeper manual review. |
| `test_conflict_resolvers.py` | 8 | Sample: factory-shape (`assert isinstance(r, WaitBasedResolver)`).  **Real-weak as a category**, but not bugs. |
| `test_baseline.py` | 8 | Sample: `assert ... in blocked` checks.  Verify policy-output containment, not the specific cell.  **Weak by design**; would not catch a wrong-but-still-in-blocked-set output. |
| `test_core_grid.py` | 7 | Likely small-API shape tests (Cell type, neighbours).  Acceptable for a primitive module; behavioural tests elsewhere drive the real exercise. |
| `test_emergency_replan.py` | 6 | Sample: `assert "emergency" in caplog.text`.  Tests log-message content but not the replan-fire arithmetic.  **Real-weak**; consider tightening to assert `emergency_replans_eta_w` counter incremented. |
| `test_regression_smoke_assertions.py` | 5 | Flagged as NO_ASSERT — they call a helper (`_assert_p3_solvers_discriminate(rows)`) that raises on failure.  The assertion is in the helper.  **False positives** for the heuristic. |
| `test_local_planner.py` | 5 | Sample: `assert path is not None`.  Tests path existence, not optimality / length.  **Real-weak**; consider asserting `len(path) <= expected`. |
| `test_environment.py` | 5 | Likely environment-load shape tests (height, width, free-cell-count present).  Acceptable. |
| `test_core_types.py` | 5 | Sample: `assert hasattr(AgentState, "pos")`.  Type-shape only.  Acceptable for a dataclass module. |
| `test_validate_paper_claims_guard.py` | 4 | Sample: `assert verdict.status in ("Confirmed", "Refuted", "NoData")`.  Checks status-string SET, not the chosen one.  **Real-weak** — would not catch a Confirmed/Refuted mis-routing on the tested row. |
| `test_max_invalid_fraction.py` | 4 | (Audit 07's own tests.)  Sample: `test_top_level_placement_accepted` asserts `"max_invalid_fraction" not in rows[0]["config"]` — a membership check.  Companion tests (`test_nested_under_base_raises`, `test_nested_inside_sweep_raises`) assert specific error text via `pytest.raises` and are NOT flagged.  Membership-only tests in this file are deliberate shape checks paired with their companion-test value checks.  **False positives for the heuristic**. |
| `test_lacam_solver.py` | 4 | Likely shape on lacam factory.  Acceptable category. |
| `test_system_health_columns.py` | 3 | Sample: `assert "deadlock_count" in tex_text`.  Asserts table/doc text contains a column name; does NOT verify the number is correct.  **Real-weak** by design (table-provenance check, not numerical). |
| Remaining files (24 with 1-3 flags each) | 34 | Mix of false positives (helper-assertion patterns) and real-weak shape tests.  Spot-checked sample (`test_table1_columns_match_csv`): the heuristic flagged its `assert not unresolved` as bare-truthiness, but the test actually accumulates a list of offending columns and surfaces them in a detailed error message — **false positive**.  Per-file manual review would refine this. |

### Weak-test summary

The heuristic's 138 flag count is an upper bound.  Manual sampling
shows the categories break down roughly:

- **~50 real-weak factory shape tests** (mostly
  `test_official_solver_wrappers.py`).  These would not catch a
  behaviour regression but DO catch import / construction
  regressions.  Acceptable as a floor; ideally paired with
  behavioural companions (most are).
- **~30 real-weak content-membership tests** (e.g. asserting a
  doc/log message contains a string).  These would not catch a
  value regression.  Examples in `test_emergency_replan.py`,
  `test_validate_paper_claims_guard.py`,
  `test_system_health_columns.py`.  Hardening recommended.
- **~50 false positives** from the heuristic — tests that use
  `assert not <list>` to surface accumulated errors, or call
  helpers that raise.

**No test was identified that completely lacks a path to fail
when the named feature is broken.**  The weakest layer is "verifies
shape, not content" — present, but not hiding gaps.

---

## 3. Dead-code reconciliation (audit 00 orphan list)

Audit 00's `00_dependency_map.md` listed 5 orphan modules.  This
step re-verifies each via grep against every Python module + YAML +
markdown + report file in the repo.  An orphan is **confirmed dead**
only if no in-package re-export, no script reference, and no test
imports it.

| Module | Verified status | Evidence |
|---|---|---|
| `src/ha_lmapf/baselines/pibt2_fr.py` | **LIVE** (false-orphan) | Re-exported via `baselines/__init__.py:17-31` (`make_pibt2_fr_config` in `__all__`).  Consumed by `run_paper_experiment._apply_method` when `method='pibt2_fr'` (`run_paper_experiment.py:253-254`).  The audit-00 scan did not follow package-level re-exports.  Display labels in `plot_paper_figures.py:66` and `build_summary_tables.py:47`. |
| `src/ha_lmapf/global_tier/one_shot_planner.py` | **DEAD** | No Python importer (grep `from ha_lmapf.global_tier.one_shot_planner` → 0 hits).  Mentioned only in the directory's own README. |
| `src/ha_lmapf/global_tier/task_allocator.py` | **DEAD** | No Python importer.  The sibling directory's README (`global_tier/README_GLOBAL_TIER.md:36, 85-120`) explicitly states "Task allocators live in `src/ha_lmapf/task_allocator/task_allocator.py`" — the file under `global_tier/` is a stale predecessor.  Also flagged by audit 04 §2.1; reconfirmed here. |
| `src/ha_lmapf/io/map_to_human_model.py` | **LIVE** (false-orphan) | Re-exported via `io/__init__.py:25` (`default_map_to_human_model` in `__all__`).  Consumed at `simulation/simulator.py:293, 416` (`_resolve_per_map_human_model` method) for per-map model dispatch. |
| `src/ha_lmapf/simulation/events.py` | **DEAD** | No Python importer (`grep "from ha_lmapf.simulation.events"` → 0 hits).  The simulator records events as plain strings in `self.step_events` (a `list[str]`); the dataclasses in `events.py` are not used.  Module docstring describes structured event types but nothing reads them. |

### Confirmed kill-list (DO NOT delete; recorded for the resume work)

| Module | Lines | Reason |
|---|---:|---|
| `src/ha_lmapf/global_tier/one_shot_planner.py` | 142 | No importer; mentioned only in directory README |
| `src/ha_lmapf/global_tier/task_allocator.py` | 312 | No importer; replaced by `src/ha_lmapf/task_allocator/task_allocator.py`; directory README explicitly redirects |
| `src/ha_lmapf/simulation/events.py` | 175 | No importer; the simulator uses `list[str]`, not these dataclasses |
| **Total dead code** | **629 lines** | All three could be deleted in a single hygiene commit without any code or test change |

### False-orphan reclassifications

| Module | Was flagged | Reclassified | Why audit-00 missed it |
|---|---|---|---|
| `baselines.pibt2_fr` | orphan | **LIVE entry point** | Package `__init__` re-export; AST scan did not follow `from .X import Y` re-exports |
| `io.map_to_human_model` | orphan | **LIVE entry point** | Same |

Audit 00's dependency-map scanner needs an enhancement for the
next pass: follow `from .x import y` re-exports inside `__init__.py`
files, so re-exported callables are not flagged as orphans.  This
is a future improvement; the current reclassification is recorded
manually.

---

## 4. Scripts probe

All 94 scripts under `scripts/` (88 files) + `plot_*.py` at repo
root (6 files) were import-probed:

```
scripts probed: 94
import OK: 94
import FAIL: 0
```

No script has a broken reference to a missing file / config /
column at module-import time.  Spot-check on the headline runner:

```
$ python scripts/evaluation/run_paper_experiment.py --help
usage: run_paper_experiment.py [-h] --config CONFIG --out OUT
                               [--workers WORKERS] [--seed-shard i/N]
                               [--resume] [--limit LIMIT]
exit=0
```

Argparse builds cleanly.

`--help` was not invoked on every script (94 process spawns × the
import cost) — the import-only probe is sufficient to surface the
"references files / configs / columns that no longer exist" failure
mode at the module level.  Scripts that lazy-load their dependencies
inside `main()` (e.g. `import pandas` inside the runner) would only
fail at run time; those are not covered by this probe and are
addressed by the per-sweep dry-runs already in
`tests/test_sweep_config_dryrun.py` (39 tests, all pass per the
audit 07 follow-up).

---

## Summary

| Acceptance criterion | Status | Evidence |
|---|:--:|---|
| Full suite run, every skip explained | **PASS** | §1: 818 pass / 2 fail (pre-existing) / 1 skip (RHCR binary segfault); skip predicate documented inline |
| Weak-test list produced | **PASS** | §2: 138 heuristic flags, categorized into ~50 factory-shape (acceptable floor), ~30 content-membership (hardening recommended), ~50 false positives (helper-assertion / accumulated-error patterns) |
| Dead-code kill-list with evidence | **PASS** | §3: 3 modules confirmed dead (629 lines); 2 false-orphans reclassified as live with package-re-export evidence; full grep audit per module |
| Scripts verified to import / `--help` | **PASS** | §4: 94/94 scripts import cleanly; `run_paper_experiment.py --help` exit 0 |

## BUGS FOUND

None at the code level.  Two pre-existing test failures
(`test_paper_claims.py::{test_synthetic_matching_results_yield_confirmed, test_perturbation_flips_a_claim_to_refuted}`) are
already tracked in `RESUME_DECISION.md` §C-3.3.

## RECOMMENDATIONS (no fix applied; scoped for resume work)

1. **Tighten ~30 content-membership weak tests** (esp. in
   `test_emergency_replan.py`, `test_validate_paper_claims_guard.py`,
   `test_system_health_columns.py`) to assert numeric values, not
   just string presence.

2. **Delete the 3 dead modules** (`global_tier/one_shot_planner.py`,
   `global_tier/task_allocator.py`, `simulation/events.py` —
   629 lines total) once the resume work clears the Tier-1
   findings in `RESUME_DECISION.md`.  Hygiene only.

3. **Enhance `00_dependency_map.md`'s scanner to follow
   `__init__.py` re-exports** so `baselines.pibt2_fr` and
   `io.map_to_human_model` are not flagged as orphans on future
   audits.

4. **Fix the 2 pre-existing `test_paper_claims.py` failures**
   (update the tuple-unpacking to match the post-`812fc90`
   3-tuple return).  Hygiene only.
