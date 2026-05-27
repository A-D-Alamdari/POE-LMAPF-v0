# Paper re-run protocol (P1–P8 acceptance gate)

Authoritative procedure for re-running any large §5.x sweep for the
paper.  Each stage has an expected exit behavior; a failure at any
stage is a hard stop — do **not** advance to the next stage until the
prior one is green.

## Stage 0 — Solver preflight (P0)

```
python scripts/preflight_solvers.py
```

| Outcome | Action |
|---|---|
| All solvers `OK` | Advance. |
| Any solver fails | Fix the binary (rebuild / repath); do not skip. |

The preflight aborts with exit `2` on a missing or non-functional
solver binary; the experiment harness re-invokes it during stage 2
so a host that loses a binary mid-sweep cannot silently substitute
all-WAIT plans.

## Stage 1 — Regression smoke (P1–P6)

```
python scripts/regression_smoke.py
```

Runs the fixed 32-cell matrix + 1 fallback-reuse cell defined in
`scripts/regression_smoke.py` and asserts every P-property:

| Check | Guards |
|---|---|
| `P1_SOLVER_FAIL_FRACTION_ZERO` | P1 / P2: per-row degenerate-run guard works; `solver_fail_fraction == 0` and `run_valid == True` on every cell. |
| `P3_SOLVERS_DISCRIMINATE` | P3: the global tier actually runs.  Across solvers on the same `(map, agents, seed)` triple, at least two solvers produce different throughputs.  Defeats the §2 pathology where every solver returned bitwise-identical results. |
| `P6_ATTRIBUTION_INVARIANT` | P6: `safety_violations == agent_attributable + exogenous_attributable` per row. |
| `P5_AGENT_ATTRIBUTABLE_POSSIBLE` | P5: the attribution split is non-tautological.  At least one row reports `agent_attributable > 0`, OR this doc carries the exemption sentence (see below). |
| `FALLBACK_REUSE_INCREMENTS` | The rolling-horizon planner re-anchors its last good `PlanBundle` when one solver call fails.  `solver_errors >= 1` AND `solver_fallback_reuses >= 1` after injecting one forced error. |

| Outcome | Action |
|---|---|
| Smoke exits `0` | Advance to stage 2. |
| Smoke exits `1` with `P1_*` | Tier-1 errored on at least one easy cell.  Investigate that solver's binary / parameters; do not raise solver budget to mask the failure. |
| Smoke exits `1` with `P3_*` | The global-tier dispatch is broken — every solver is returning the same path / metric.  Bisect against the §2 pathology PR; do not advance. |
| Smoke exits `1` with `P5_*` | Either a real agent-attributable violation occurred and was not detected (planner regression), or this doc no longer carries the exemption sentence and the smoke has no way to confirm the metric isn't tautological.  Fix one or the other. |
| Smoke exits `1` with `P6_*` | The per-pair attribution bookkeeping in the classifier is broken.  See `docs/REVISION_AUDIT.md` §13–§14. |
| Smoke exits `1` with `FALLBACK_REUSE_*` | The rolling-horizon planner is not re-anchoring on solver error.  See `src/ha_lmapf/global_tier/rolling_horizon.py::_reanchor_last_good`. |

A failing smoke is the **correct** outcome on a broken tree.  Do not
weaken any assertion to make the smoke pass; do not skip stage 1 to
"save time" — the smoke runs in roughly five minutes on the dev host.

### Exemption: why the §5.4-default smoke matrix cannot trigger `P5_AGENT_ATTRIBUTABLE_POSSIBLE`

> smoke matrix cannot trigger agent_attributable > 0 under fov > safe

Under the WAIT-counterfactual classifier installed by P5
(`docs/REVISION_AUDIT.md` §13), a violation pair `(a_i, h)` at `t+1`
is agent-attributable iff the agent moved AND `ell_1(s_i(t),
h_pos_at_t+1) > r_safe`, i.e. WAIT would have left the agent safe
vs `h`.  Because the agent can move by at most one Manhattan step
per tick, this requires `ell_1(s_i(t), h_pos_at_t+1) = r_safe + 1`.
For `h` to escape the planner's avoidance logic the agent must
**not** have observed `h` at decision time, i.e.
`ell_1(s_i(t), h_pos_at_t+1) > r_fov`.  Combining: `r_safe + 1 >
r_fov`, i.e. `r_fov <= r_safe`.

The smoke matrix uses `fov_radius=4` and `safety_radius=1` (the
canonical §5.4 operating point), so `r_fov > r_safe` and the
WAIT-counterfactual condition cannot fire on any healthy run.
The classifier is verified non-tautological by
`tests/test_safety_classification.py::test_wait_counterfactual_fov_blind_move_is_agent_attributable`,
which constructs the discriminating `fov=1, safe=1` case
directly.  The acceptance criterion is therefore:

* the smoke matrix produces `agent_attributable == 0` for every
  cell (healthy operation), AND
* this exemption sentence is present in this document, so the
  smoke's `P5_AGENT_ATTRIBUTABLE_POSSIBLE` check has a documented
  reason to accept zero.

If you re-run the smoke matrix at `fov <= safe` (e.g. for a
soft-safety ablation) the smoke will start expecting nonzero
agent-attributable; remove this sentence in that case.

## Stage 2 — Full sweep launch

```
python -m scripts.evaluation.run_paper_experiment \
    --config configs/tuning/<sweep>.yaml \
    --out logs/paper/<sweep>/ \
    --workers 8
```

The harness re-runs P0 preflight and the per-row validity gate
(P2): each run with `solver_fail_fraction > validity_threshold` is
siphoned into `results_INVALID.csv` and excluded from
`results.csv`.  The harness exits non-zero (code `3`) if any
`(solver, map)` cell exceeds the configured
`invalid_cell_fraction_limit`.

`--dry-run` short-circuits after preflight + manifest expansion
without running any sims; use it to verify a new sweep YAML is
well-formed before paying the compute cost.

| Outcome | Action |
|---|---|
| Harness exits `0`, `results.csv` populated, `results_INVALID.csv` empty | Advance. |
| Harness exits `0`, `results_INVALID.csv` non-empty | Inspect the invalid rows — they are debug-only, not used by stage 4.  The harness still considered the sweep healthy under the configured cell-level limit. |
| Harness exits `2` | P0 preflight failed mid-sweep (a binary disappeared).  Restore it and resume with `--resume`. |
| Harness exits `3` | Cell-level invalid-fraction limit exceeded.  Investigate the offending cells; do not advance. |

## Stage 3 — Validity summary

```
python -m scripts.evaluation.validate_smoke_results \
    --logs-dir logs/paper/<sweep>/
```

Runs the five smoke checks (sidecar count, timeline consistency,
per-method summary, validity gate, optional figure render) on the
sweep outputs.  STEP 0 in the output is the degenerate-run guard
introduced by P2/P7 and surfaces the same per-row gate that runs
during the sweep.

| Outcome | Action |
|---|---|
| `RECOMMENDATION: GO` | Advance to stage 4. |
| `RECOMMENDATION: NO-GO` | A property check failed.  The script names the failing step and lists offending rows; investigate. |

## Stage 4 — Claim validation

```
python -m scripts.evaluation.validate_paper_claims \
    --claims        docs/PAPER_NUMERICAL_CLAIMS.yaml \
    --results-root  logs/paper/ \
    --out           claim_validation.md \
    --section       all
```

Compares every paper claim against the sweep's `results.csv` under
the P2 degenerate-run guard (the per-row validity classifier from
`classify_row_validity`).  The report header carries
`**Input rows**: N=… valid … invalid …`; an `## Invalid input
rows` section appears before any positive verdict if any input
rows failed the gate.

| Outcome | Action |
|---|---|
| Validator exits `0` | The paper's numerical claims hold on this re-run.  Edit the paper to match the report's `Refuted` / `Now stronger` / `Now weaker` suggestions. |
| Validator exits `2` | argparse / config error.  Fix the CLI invocation. |
| Validator exits `3` | At least one input row failed the degenerate-run guard.  The validator refused to emit `Confirmed` verdicts on tainted data.  Investigate `## Invalid input rows`; do not edit the paper based on a `3` report. |

## Stage exit-code matrix

| Stage | Tool | `0` | `1` | `2` | `3` |
|---|---|---|---|---|---|
| 0 | `preflight_solvers.py` | all OK | — | binary missing / non-functional | — |
| 1 | `regression_smoke.py` | all checks pass | a named P-check failed | — | — |
| 2 | `run_paper_experiment.py` | sweep ran | generic error / SystemExit | preflight failed | cell-level invalid-fraction exceeded |
| 3 | `validate_smoke_results.py` | GO | NO-GO | — | — |
| 4 | `validate_paper_claims.py` | all claims clean | — | argparse error | input rows failed guard |

The protocol assumes the runner host has a complete solver binary
set.  On a host where one of the §5.4 solvers is unavailable
(e.g. RHCR on the CI image -- segfaults during planning),
quarantine that solver by setting `--skip-method rhcr` on the
validators and removing it from the sweep YAML's solver axis;
do not flip its preflight to "OK".
