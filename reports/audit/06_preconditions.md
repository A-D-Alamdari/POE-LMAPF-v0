# Audit step 06 — enforce documented preconditions

Three preconditions were recorded as "documented but not enforced" in
earlier audit reports.  This step turns the two safety-relevant ones
into executable invariants and pins the third with a regression test
so the audit note can be closed.

| # | Precondition | Prior status | Verdict after this step |
|---|---|---|---|
| 1 | `r_safe < r_fov` (Theorem-1 construction-safety) | documented gap (audit 04 §4) | **ENFORCED** at `SimConfig.__post_init__` |
| 2 | `R = floor(H/2)` (rolling-horizon coupling) | documented gap (audit 04 §1.1) | **DOWNGRADED to "default, not required"** — pinned by a decoupled-run test |
| 3 | `PIBTResolver` ignores `forbidden` when `allow_side_step=True` | documented gap (audit 03 §3) | not addressed in this step (PIBT side-step is not enabled in any committed config; deferred) |

---

## 1. `r_safe < r_fov` — ENFORCED

### Why this matters

The local controller can only enforce a safety buffer on cells it can
observe.  If `safety_radius >= fov_radius`, the forbidden set the
controller computes does not cover every buffer cell the agent could
reach in one step, and the Algorithm-2 invariant "no executed action
enters an observed pre-move buffer" silently fails.  Theorem 1 (paper
§4.5) is then vacuous: the proof relies on `r_safe < r_fov`
(`docs/proposed_approach.md` §F).

Pre-audit code path: the precondition was documented inline at
`src/ha_lmapf/core/types.py:447-449` and
`src/ha_lmapf/simulation/simulator.py:1148-1151` but no executable
check raised when a `SimConfig` violated it.

### Implementation

Added `SimConfig.__post_init__` at `src/ha_lmapf/core/types.py`:

```python
def __post_init__(self) -> None:
    if int(self.safety_radius) >= int(self.fov_radius):
        raise ValueError(
            "SimConfig violates the Theorem-1 precondition "
            "r_safe < r_fov: safety_radius={...} >= fov_radius={...}.  ..."
        )
```

The error message names the precondition, cites paper §4.5 Theorem 1
and `docs/proposed_approach.md` §F, and suggests the canonical
`(fov=4, safe=1)` defaults.

### Pre-fix grep results (committed configs)

Initial scan of every YAML under `configs/` (using the per-cell
cartesian expansion `base × groups[*].sweep`):

```
yamls scanned: 92
cells with explicit (fov, safe) pair: 1316
  satisfy r_safe < r_fov: 1310
  VIOLATIONS (r_safe >= r_fov): 6
    configs/eval/paper/fov_safety.yaml: fov=2, safe=2
    configs/eval/paper/fov_safety.yaml: fov=2, safe=2
    configs/eval/paper/fov_safety.yaml: fov=2, safe=3
    configs/eval/paper/fov_safety.yaml: fov=2, safe=3
    configs/eval/paper/fov_safety.yaml: fov=3, safe=3
    configs/eval/paper/fov_safety.yaml: fov=3, safe=3
```

Six violating cells — three invalid `(fov, safe)` pairs `× 2` maps in
the §5.3 sweep.  Without the new enforcement these cells would have
silently produced runs whose Theorem-1 attribution was undefined; with
enforcement they would crash at `Simulator(cfg)`.

### Config fix

Rewrote `configs/eval/paper/fov_safety.yaml` from a single cartesian
sweep (5 `fov` × 4 `safe` × 2 maps × 10 seeds = 400 runs) to **one
group per fov_radius value**, each pinning only the valid
`safety_radius` subset:

```
fov=2 -> safe in {0, 1}        (2 pairs)
fov=3 -> safe in {0, 1, 2}     (3 pairs)
fov=4 -> safe in {0, 1, 2, 3}  (4 pairs)
fov=5 -> safe in {0, 1, 2, 3}  (4 pairs)
fov=6 -> safe in {0, 1, 2, 3}  (4 pairs)
                  total = 17 pairs
17 × 2 maps × 10 seeds = 340 runs (was 400; 60 invalid runs removed)
```

The expected run count in `tests/test_harness_smoke.py` was updated
from 400 to 340.

### Post-fix grep

```
yamls scanned: 92
cells with explicit (fov, safe) pair: 1310
  satisfy r_safe < r_fov: 1310
  VIOLATIONS (r_safe >= r_fov): 0
```

### Regression tests

`tests/test_config_preconditions.py` (4 tests for §1):

| Test | Asserts |
|---|---|
| `test_r_safe_lt_r_fov_accepted` | canonical `(fov=4, safe=1)` constructs without raising |
| `test_r_safe_eq_r_fov_rejected` | boundary case `fov=2, safe=2` raises `ValueError` whose message contains `"r_safe < r_fov"` and `"Theorem"` |
| `test_r_safe_gt_r_fov_rejected` | strict violation `fov=2, safe=3` raises with the actual values in the message |
| `test_committed_configs_have_zero_violations` | walks every committed YAML; fails loudly if any future cell re-introduces a violation |

### Tests that needed adjustment (and why)

Five existing tests built `SimConfig` instances with
`fov_radius=1, safety_radius=1` (or `fov=1, safe=2`) for synthetic
scenarios that pre-dated the precondition enforcement.  All were
exercising the **WAIT-counterfactual classifier** or **physics-revert /
saturation logic** — neither depends on FoV, so bumping `fov` by one
preserves the test semantics.  In one case
(`test_def1_unobserved_witness_is_exogenous`) the human's pre-move
position was pushed out by one cell to keep it FOV-blind under the new
larger FoV.

| Test | Old (fov, safe) | New (fov, safe) | Why semantics preserved |
|---|---|---|---|
| `test_def1_violation_classifier::test_def1_unobserved_witness_is_exogenous` | (1, 1) | (2, 1) + pre→(3,0) | Definition-1 FOV-blindness preserved (`L1=3 > fov=2`) |
| `test_paper_metric_invariants::test_throughput_saturation_warning` | (1, 1) | (2, 1) | Saturation logic is FoV-independent |
| `test_safety_classification::test_scenario_C_exogenous_attributable` | (1, 2) | (3, 2) | WAIT-cf has no FoV gate |
| `test_safety_classification::test_wait_counterfactual_fov_blind_move_is_agent_attributable` | (1, 1) | (2, 1) | WAIT-cf has no FoV gate |
| `test_wait_kind_invariant_extended::test_physics_revert_counted` | (1, 1) | (2, 1) | physics step 7a runs without humans in this scenario |

---

## 2. `R = floor(H/2)` — DOWNGRADED to "default, not required"

### Grep-based dependency check

Searched every `horizon` / `replan_every` reference in the
rolling-horizon planner:

```
$ grep -n "horizon\|replan_every" src/ha_lmapf/global_tier/rolling_horizon.py | grep -v '".*"'
26:            horizon: int,
27:            replan_every: int,
60:        self.horizon = int(horizon)
61:        self.replan_every = max(1, int(replan_every))
86:        self._min_emergency_gap: int = max(3, replan_every // 4)
172:            horizon: int,
206:                    new_cells = list(tail[: horizon + 1])
207:                    if len(new_cells) < horizon + 1:
209:                        new_cells.extend([pad] * (horizon + 1 - len(new_cells)))
214:                    new_cells = [stored_path.cells[-1]] * (horizon + 1)
220:                new_cells = [agent.pos] * (horizon + 1)
223:                          created_step=cur_step, horizon=horizon)
253:        periodic = (cur_step % self.replan_every == 0)
335:                    paths={}, created_step=cur_step, horizon=self.horizon),
366:                horizon=plan.horizon,
388:                    sim_state.agents, cur_step, self.horizon,
```

The two parameters operate independently:

- `horizon` is the **path length** stored in the plan bundle.  Used
  only by `_reanchor_last_good` for tail clipping/padding (L172-223)
  and by the solver's `plan(horizon=…)` kwarg (L290-297, L335, L366).
- `replan_every` is the **periodic-trigger interval**.  Used only at
  L86 (`min_emergency_gap = max(3, replan_every // 4)`) and at L253
  (`periodic = (cur_step % self.replan_every == 0)`).

**No code path computes `horizon // 2`, `2 * replan_every`, or any
relationship between the two**.  `R = floor(H/2)` is purely a paper
convention (replan at half-horizon so the second half of the plan
serves as the commitment buffer); the rolling-horizon planner accepts
any `(H, R)` pair.

### Verdict: downgrade

The audit-04 §1.1 GAP is recharacterized: `R = floor(H/2)` is a
**default convention**, not a code-side invariant.  Adding an assert
would be over-enforcement and would break the `aux_h_r_decoupling`
sweep (`configs/eval/paper/aux_h_r_decoupling.yaml`) which
deliberately varies `(H, R)` independently for the paper's
sensitivity analysis (110 runs in that sweep, per `tests/test_harness_smoke.py`'s
expected count).

### Regression test

`tests/test_config_preconditions.py::test_horizon_replan_every_decoupled_run_succeeds`:

- Builds `SimConfig(horizon=10, replan_every=7)` — a deliberately
  non-coupled pair (`R != floor(H/2) = 5`).
- Runs `Simulator.run()` on a 5×5 open map, 2 agents, 30 steps.
- Asserts the four-bucket wait invariant holds on the returned
  `Metrics` and that `metrics.steps == 30` (the run actually advanced).

If a future refactor adds `assert replan_every == horizon // 2` or
similar coupling check, this test fires immediately.

---

## 3. PIBT `allow_side_step=True` — not addressed in this step

Audit 03 §3 noted that `PIBTResolver._safe_side_step` consults only
`observation.blocked` and not the resolver-plumbed `forbidden` kwarg
when `allow_side_step=True`.  No committed YAML enables this flag
(default is `False`), and PIBTResolver is itself only optionally
selected via `controller_kind` / baseline factories.  Deferred to
a future audit step; the existing audit-03 entry remains as the
record of this known gap.

---

## Summary

| Acceptance criterion | Status | Evidence |
|---|:--:|---|
| A config with `r_safe >= r_fov` fails loudly at load, with a test proving it | **PASS** | `SimConfig.__post_init__`; tests `test_r_safe_eq_r_fov_rejected`, `test_r_safe_gt_r_fov_rejected` |
| R/H coupling either enforced-with-test or downgraded-with-test; no bare "GAP" | **PASS (downgraded)** | grep proves no code dependency; `test_horizon_replan_every_decoupled_run_succeeds` pins decoupling |
| Grep results for both preconditions recorded | **PASS** | §1 pre-fix (6 violations) and post-fix (0 violations) grep blocks above; §2 H/R grep block above |
| `pytest tests/` green | **PASS** | 805 passed, 1 skipped, 8 deselected (3 pre-existing flakes from audit 05 + 6 parameterised lacam3 wall-time flake from audit 00) |

## BUGS FOUND

### BUG (config-data) — `configs/eval/paper/fov_safety.yaml` enumerated 60 Theorem-1-invalid runs

Before this step, the §5.3 sweep produced 60 runs whose `(fov_radius,
safety_radius)` pair violated the Theorem-1 precondition.  Under the
old code these runs would execute with `safety_radius >= fov_radius`,
silently producing the unverified case Theorem 1 explicitly excludes.
Under the new code (after step 1 above) they would crash at
`Simulator(cfg)` construction.

**Fix applied**: rewrote the YAML to enumerate only the 17 valid
`(fov, safe)` pairs per the per-fov breakdown in §1.  The test
`test_committed_configs_have_zero_violations` is the file-level guard
against future re-introduction.

## CLOSED

- Audit 04 §4 GAP "`r_safe < r_fov` is documented but not enforced":
  closed by §1 of this step.
- Audit 04 §1.1 GAP "`RollingHorizonPlanner` does not enforce
  `R = floor(H/2)`": closed by §2 of this step (downgraded to "default,
  not required" with a regression test pinning the decoupling).

---

## 5. Mutation verification — does `test_def1_unobserved_witness_is_exogenous` still exercise the FoV gate?

The §1 work bumped `fov_radius` from 1 to 2 in
`test_def1_unobserved_witness_is_exogenous` (to satisfy the now-
enforced `r_safe < r_fov` precondition) AND pushed the human's
pre-move position out by one cell ((2,0) → (3,0)) to "keep it
FOV-blind".  Two-knob adjustments that keep a test green are the
exact pattern this audit series learned to distrust (cf. the
P17 physics-revert test).  This section re-checks whether the
adjusted test still has teeth.

### Mutation experiment

A detached worktree (`/tmp/scratch-fov` from HEAD `2e60b69`) was
patched to drop the FoV filter from the Definition-1 classifier
in `src/ha_lmapf/simulation/simulator.py`:

```python
# BEFORE (simulator.py:1209-1215)
observed_pairs: List[Tuple[int, Cell]] = [
    (hid, h.pos)
    for hid, h in humans_pre_move.items()
    if abs(a_prev[0] - h.pos[0])
        + abs(a_prev[1] - h.pos[1])
        <= fov_r
]

# AFTER (mutation)
observed_pairs: List[Tuple[int, Cell]] = [
    (hid, h.pos)
    for hid, h in humans_pre_move.items()
]
```

Result: `pytest tests/test_def1_violation_classifier.py -k
"test_def1_unobserved_witness_is_exogenous"` — **1 passed** under
the mutation.  Running the whole file: **7 passed**.  No test in
the Definition-1 classifier file detects the dropped FoV gate.

### Why the test does not exercise the FoV gate

Trace the adjusted scenario by hand:

| symbol | value |
|---|---|
| `a_prev` | `(0,0)` |
| `a_new`  | `(1,0)` |
| `pre`    | `(3,0)` |
| `post`   | `(2,0)` |
| `r_fov`  | `2` |
| `r_safe` | `1` |

Without the FoV filter, `observed_pairs == [(0, (3,0))]`.  Walk
clauses (a) and (b) against the witness `h'_pre = (3,0)`:

- clause (a): `|a_prev - h'_pre|₁ = 3 > r_safe=1`  ✓
- clause (b): `|a_new  - h'_pre|₁ = 3 ≤ r_safe=1` ✗

Clause (b) fails on the pre-move position, so `def1_attr=False`
regardless of FoV gating.  The test passes whether or not the
gate is applied.  **Outcome (b) per the task spec: the adjusted
test does NOT exercise the FoV boundary.**

### Why a single-step move cannot exercise the FoV gate under `r_safe < r_fov`

This is structural, not an accident of fixture choice.  Definition
1's witness `h'` contributes both clauses against its pre-move
position `hp`.  For the FoV gate to make any difference, there
must exist `hp` such that:

1. `|a_prev - hp|₁ > r_fov`                       (FoV-blind ⇒ filtered out)
2. `|a_prev - hp|₁ > r_safe`                      (clause a)
3. `|a_new  - hp|₁ ≤ r_safe`                      (clause b)
4. `a_prev ≠ a_new`                                (moved)

The new precondition `r_safe < r_fov` enforced in §1 means
`r_fov ≥ r_safe + 1` on integers.  Triangle inequality on the
`ℓ¹` metric gives

```
|a_prev - hp|₁  ≤  |a_prev - a_new|₁ + |a_new - hp|₁
                ≤  |a_prev - a_new|₁ + r_safe        (from (3))
```

For a single-step agent move `|a_prev - a_new|₁ = 1`, so
`|a_prev - hp|₁ ≤ r_safe + 1 ≤ r_fov`, which directly contradicts
(1).  No witness can be simultaneously FoV-blind from `a_prev`
and inside `r_safe` of `a_new` when the agent moves only one
cell.  The original audit-02 fixture worked because `r_fov = 1`
made `r_safe + 1 = 2 > r_fov`; the new precondition closes that
window.

### Proposed adjustment that restores FoV sensitivity

The simplest construction that escapes the bound is to make the
agent hop **two cells** in one tick.  `_detect_collisions_and_near_misses`
is driven directly with synthetic `prev_pos` / `new_pos` dicts in
this unit test, so non-physical hops are legal here:

```python
prev_pos = {0: (0, 0)}
new_pos  = {0: (2, 0)}                            # 2-cell hop
pre  = {0: HumanState(human_id=0, pos=(3, 0))}    # L1((0,0),(3,0))=3 > fov=2
post = {0: HumanState(human_id=0, pos=(2, 0))}    # L1((2,0),(2,0))=0 ≤ safe=1
```

Under this fixture:

- clause (a): `|(0,0) - (3,0)|₁ = 3 > 1`  ✓
- clause (b): `|(2,0) - (3,0)|₁ = 1 ≤ 1`  ✓
- FoV gate:   `|(0,0) - (3,0)|₁ = 3 > 2`  ⇒ witness filtered out

Pristine source: `safety=1, agent=0, exo=1` (exogenous, as
expected).  Mutation (FoV filter removed): `safety=1, agent=1,
exo=0` — the FoV filter is the **only** thing keeping this case
out of the agent-attributable bucket.  The test would have teeth
under the proposed construction.

### Disposition

The adjusted test is harmless (it still pins exogenous-vs-agent
divergence between Definition-1 and the WAIT-counterfactual
diagnostic) but it no longer probes the FoV boundary it claims
to.  A follow-up is added to `RESUME_DECISION.md` Tier 3 to
either rewrite the fixture using the 2-cell-hop construction
above or split it into a separate test that does.  No source
change in this audit step; the only artifact is this §5.
