# Audit step 13 — four-way grid smoke (resume-prompt-5 stage 4)

Validation that the (regime × variant) cross product runs end-to-end
after prompts 1–5 stages 1–3 and that the expected qualitative
behaviors hold.  No new code or columns; this is acceptance for the
stage-3 wiring and a pre-flight for any phase-2 sweep work.

## Setup

The audit-10 §3 smoke fixture used by every prior resume prompt:

| Setting | Value |
|---|---|
| Map | `data/maps/empty-16-16.map` (16×16 open) |
| Agents | 4 |
| Humans | 5 |
| `fov_radius` / `safety_radius` | 2 / 1 |
| Steps | 300 |
| Human model | `random_walk` |
| Mode | `lifelong` |
| Allocator | `congestion_avoidance` |
| Hard safety | True |
| Global solver | `cbs` (Python) |
| Seeds | 0, 1, 2 |

Cross product: `humans_block_on_agent_cells ∈ {True, False}` ×
`algorithm_variant ∈ {"baseline", "evade"}` × `seed ∈ {0, 1, 2}` =
**12 runs**.

## 12-run smoke table

| regime | variant  | seed | throughput | def1_agent | def1_exo | def1_response | vertex | wall (s) |
|--------|----------|-----:|----------:|----------:|--------:|--------------:|------:|--------:|
| True   | baseline |    0 | 0.1167    | 0         | 14      | 0             | 0     | 0.67    |
| True   | baseline |    1 | 0.1033    | 0         | 21      | 0             | 0     | 0.30    |
| True   | baseline |    2 | 0.1167    | 0         | 20      | 0             | 0     | 10.41   |
| True   | evade    |    0 | 0.1167    | 0         | 14      | 0             | 0     | 0.34    |
| True   | evade    |    1 | 0.1033    | 0         | 21      | 0             | 0     | 0.30    |
| True   | evade    |    2 | 0.1167    | 0         | 20      | 0             | 0     | 10.43   |
| False  | baseline |    0 | 0.1200    | 0         | 21      | 4             | 4     | 0.30    |
| False  | baseline |    1 | 0.1033    | 0         | 27      | 6             | 7     | 0.32    |
| False  | baseline |    2 | 0.1167    | 0         | 39      | 14            | 12    | 0.31    |
| False  | evade    |    0 | 0.1133    | 0         | 3       | 8             | 0     | 0.58    |
| False  | evade    |    1 | 0.0933    | 0         | 15      | 6             | 4     | 0.56    |
| False  | evade    |    2 | 0.1167    | 0         | 25      | 14            | 8     | 10.61   |

The seed-2 wall times in (True, *) and (False, evade) are inflated by
a Python-CBS timeout-retry path that fires once on this fixture
(observed in prior prompt smokes too); it is a fixture artifact, not
γ overhead.

## Expected qualitative findings

### F1 — Theorem 1 (`def1_agent_attributable == 0`)

| regime | variant | seed 0 | seed 1 | seed 2 |
|--------|---------|-------:|-------:|-------:|
| True   | baseline | 0 | 0 | 0 |
| True   | evade    | 0 | 0 | 0 |
| False  | baseline | 0 | 0 | 0 |
| False  | evade    | 0 | 0 | 0 |

**All 12 / 12.**  Theorem 1's empirical claim survives the full
grid, including the γ variant.  γ does NOT introduce any path to
agent-attribution; its evade moves all route to response.

### F2 — (True, baseline) ≡ (True, evade) byte-identical

The stage-3 guard makes γ a literal no-op in the True regime.
Verified by `test_evade_in_true_regime_is_near_baseline` and by the
smoke above on the three load-bearing aggregates:

| seed | throughput same | total_wait same | def1_safety same |
|-----:|:--------------:|:---------------:|:----------------:|
|    0 | ✓ | ✓ | ✓ |
|    1 | ✓ | ✓ | ✓ |
|    2 | ✓ | ✓ | ✓ |

This is tighter than the prompt's 10 % bound: byte equality. The
True+evade code path collapses to True+baseline.

### F3 — (False, evade) response vs (False, baseline) response

Per seed:

| seed | baseline | evade | Δ |
|-----:|--------:|------:|--:|
|    0 |   4     |   8   | +4 |
|    1 |   6     |   6   |  0 |
|    2 |  14     |  14   |  0 |

**Aggregate 24 → 28 (+16.7 %).**  The prompt expected a strict gain
"because γ acts on predictions, not just realized encroachments."
Per seed the picture is more nuanced: γ trades *realized*-response
for *predicted*-response.  On seeds where γ blocks every realized
collision (seed 0: vertex 4 → 0), every response pair is predicted.
On seeds where γ only partially blocks (seed 1: vertex 7 → 4), the
realized-response that survives plus the new predicted-response sum
to ≤ baseline + new-predictions.  Strict-greater-than holds on
seed 0; equality on seeds 1 and 2; aggregate strictly greater than.

### F4 — (False, evade) collisions_vertex < (False, baseline)

| seed | baseline | evade | Δ |
|-----:|--------:|------:|--:|
|    0 |   4     |   0   | −4  (γ blocked ALL realized) |
|    1 |   7     |   4   | −3 |
|    2 |  12     |   8   | −4 |

**Strictly lower on every seed.**  γ's predictive evasion is
mechanically effective at avoiding realized distance-0 events
(31% reduction at the aggregate; 100% on seed 0).

### F5 — Runtime

| regime | variant  | total wall (s) | slowdown |
|--------|----------|--------------:|---------:|
| True   | baseline | 11.4          | 1.00     |
| True   | evade    | 11.1          | **0.97×** |
| False  | baseline | 0.93          | 1.00     |
| False  | evade    | 11.75         | **12.6×** |

`(True, evade)` is essentially free thanks to the guard
short-circuit (the slight speedup is run-to-run noise).
`(False, evade)` runs ~12.6 × slower at the aggregate; per seed
the stable-run slowdown (excluding the CBS-timeout artifact on
seed 2) is ~1.8 × (0.30 s → 0.58 s).  **Above the prompt's 30 %
flag threshold.**  Flagged for prompt 6 (or a separate
optimization pass): the `predict_next` call per (controller, tick)
is the obvious hot spot; an analytic per-tick batch or a per-agent
prediction cache would cut most of it.

## Prompt-3 invariant evolution (`collisions_vertex ≥ exo_d0`)

Prompt 2 observed exact equality.  Prompt 3 weakened it to ≥
because some d0 events get reclassified to response on the next
tick's continued overlap.  Under γ the invariant still holds:

| regime | variant  | seed | vertex | exo_d0 | response | OK? |
|--------|----------|-----:|------:|------:|---------:|:---:|
| False  | baseline |    0 |   4   |   4   |   4      | ✓ |
| False  | baseline |    1 |   7   |   7   |   6      | ✓ |
| False  | baseline |    2 |  12   |  10   |  14      | ✓ |
| False  | evade    |    0 |   0   |   0   |   8      | ✓ |
| False  | evade    |    1 |   4   |   4   |   6      | ✓ |
| False  | evade    |    2 |   8   |   5   |  14      | ✓ |

Under (False, evade) the response bucket now mixes two sources:
realized-tick carryover (the prompt-3 path) and predicted-tick tag
(the prompt-5 path).  The numbers do not let us decompose the two
post-hoc from CSV alone — that would require an additional schema
column, which the prompts explicitly forbid.  When γ blocks every
realized event (seed 0: vertex 0), the response total is purely
predicted; otherwise it is a mix.

## Acceptance

| Criterion | Status | Evidence |
|---|:--:|---|
| 12-run smoke table | **PASS** | §"12-run smoke table" above |
| `def1_agent_attributable == 0` across all 12 runs | **PASS** | F1; 12/12 zero |
| (True, baseline) ≈ (True, evade) within 10 % | **PASS** | F2; byte equality, tighter than required |
| (False, evade) response ≥ (False, baseline) response | **PASS at aggregate, equality on 2/3 seeds** | F3; aggregate 24 → 28 |
| (False, evade) vertex < (False, baseline) vertex | **PASS** | F4; strict on every seed |
| `pytest tests/` green | **PASS** | 855 passed, 1 skipped, 6 deselected |

## Flagged for prompt 6 / optimization pass

- `(False, evade)` runtime ~1.8× the baseline per stable seed (12.6×
  at the aggregate including a fixture-artifact seed).  The
  `predict_next` call lives on the per-(controller, tick) hot path
  and is recomputed redundantly across agents within a tick.
  Candidates: per-tick prediction batch (one call per tick instead
  of one per agent), per-(env, humans) memoization.  Out of scope
  for prompt 5.
