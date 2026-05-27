# PIBT2 `solved=0` / `solver_errors=100` Diagnosis

**Symptom:** `pytest tests/test_baseline_pibt2_fr.py::test_pibt2_fr_smoke`
fails with `metrics.throughput == 0.0` and `metrics.solver_errors ==
100`. Every replan in the 100-step warehouse simulation logs
`status=error error_msg='no paths parsed from result file'`.

**Verdict:** Two compounding wrapper bugs (NOT a binary bug, NOT a
test infeasibility, NOT a horizon mismatch). The Kei18/pibt2 binary
is functioning correctly when given correctly formatted input.

---

## Reproduction

```bash
git rev-parse HEAD                           # f505a2c (post binary-rebuild)
sha256sum src/ha_lmapf/global_tier/solvers/mapf_pibt2
# c833927b1dc3e0b0d890030af2819c840152cc8043ff43aceef2f8e2ba94d9b8

pytest tests/test_solver_smoke.py -k pibt2 -v        # → PASSED
pytest tests/test_baseline_pibt2_fr.py -v            # → FAILED (throughput=0)
```

The smoke test passes only because it asserts "any agent has > 1
distinct cell" (movement) — see "Why the smoke test gave a false
green" below.

## Captured artifacts

Diagnostic dumps were collected by temporarily instrumenting
`pibt2_wrapper.py::plan_with_metadata` to dump every PIBT2
invocation's command line, instance file, stdout, stderr, return
code, and result file to `/tmp/pibt2_diagnostic/call_<idx>_…/`.
The patch was reverted before this document was written; no
diagnostic code is in the wrapper now.

Captured calls:

| dir | step | n_agents | binary | rc | solved | error |
|---|---|---|---|---|---|---|
| `call_000_step0_n1` | 0 | 1 | `mapf_pibt2` | 0 | 1 | — (probe) |
| `call_001_step0_n20` | 0 | 20 | **`mapd_pibt2`** | 0 | 1 | "no paths parsed from result file" |
| `call_002_step1_n20` | 1 | 20 | **`mapd_pibt2`** | 0 | 1 | "no paths parsed from result file" |
| `call_003_step2_n20` | 2 | 20 | **`mapd_pibt2`** | 0 | 1 | "no paths parsed from result file" |

The simulator's actual replans (calls 001–003) invoke `mapd_pibt2`,
not `mapf_pibt2` — the wrapper's `mode="auto"` + `is_lifelong=True`
(passed from `RollingHorizonPlanner.step` because
`SimConfig.mode="lifelong"`) routes to MAPD.

### Excerpt: instance file the wrapper writes (call_001, simulator's first replan)

```
map_file=/tmp/pibt2_ny5x2qgh/maps/map.map
agents=20
seed=0
random_problem=0
max_timestep=70
max_comp_time=1000
starts=(0,9),(5,6),(0,5),(12,2),(2,3),(3,0),(7,0),(1,0),(9,1),(9,8),...
goals=(2,9),(8,3),(0,0),(11,3),(13,8),(2,0),(8,0),(0,0),(7,0),(12,7),...
```

### Excerpt: result the binary writes back (mapd_pibt2)

```
solved=1
service_time=12.4
makespan=27
comp_time=0
starts=(13,1),(9,8),(10,9),(11,3),(0,4),(5,6),(13,9),(12,1),(6,2),(12,6),...
task=
1:34->89,appear=1,finished=6
4:96->10,appear=4,finished=12
…
solution=
0:(13,1)->(4,6):-1,(9,8)->(4,6):-1,(10,9)->(4,6):-1,…
1:(13,2)->(6,2):-1,(9,7)->(6,2):-1,(9,9)->(13,0):0,…
```

Two things to note:

1. **Result `starts` differ from instance `starts`.** The wrapper sent
   `(0,9),(5,6),(0,5),(12,2),…`; the binary echoed back
   `(13,1),(9,8),(10,9),(11,3),…`. The binary did NOT use the wrapper's
   starts/goals — it generated its own.
2. **Solution lines are MAPD format**, not MAPF. Each agent's per-step
   entry is `<current_pos>-><task_target>:<task_id>` (or `:-1` for "no
   task"), e.g. `(13,1)->(4,6):-1`. The wrapper's parser expects pure
   `<step>:(x1,y1),(x2,y2),…` (MAPF format).

## Trivial-case parallel test

To prove the binary is healthy, ran `mapf_pibt2` directly on a
hand-crafted 2-agent corridor instance:

```
map_file=/tmp/pibt2_diagnostic/call_001_step0_n20/map.map  (10×14 mini-warehouse)
agents=2
random_problem=0
0,0,13,9
13,9,0,0
```

Result: `solved=1`, returned `starts=(0,0),(13,9)` and `goals=(13,9),(0,0)`
**exactly matching** the instance, with a parseable MAPF-format
solution (e.g. `0:(0,0),(13,9)`). The binary works when fed the
correct format.

## `mapf_pibt2` vs `mapd_pibt2` on the wrapper's instance file

| Diagnostic | Binary | rc | solved | starts in result match wrapper's? | solution format |
|---|---|---|---|---|---|
| current wrapper behavior | `mapd_pibt2` | 0 | 1 | **No** (random) | MAPD `(pos)->(target):task_id` |
| `mapf_pibt2` on the same wrapper instance | `mapf_pibt2` | 0 | 1 | **No** (random) | MAPF `(x,y)` |
| `mapf_pibt2` on **correct format** | `mapf_pibt2` | 0 | 1 | **Yes** | MAPF `(x,y)` |

So **switching to `mapf_pibt2` alone is not sufficient**. Even the
MAPF binary ignores the wrapper's `starts=(...)` / `goals=(...)`
syntax and falls back to seeded random scenario generation.

## Source-code cross-reference (Kei18/pibt2)

`pibt2/src/problem.cpp` parses the instance file with the regex
`r_sg`:

```cpp
std::regex r_sg = std::regex(R"((\d+),(\d+),(\d+),(\d+))");
```

Capture groups: `<x_s>, <y_s>, <x_g>, <y_g>`. The expected format is
**one line per agent**:

```
<start_x>,<start_y>,<goal_x>,<goal_y>
```

There is **no** `r_starts` / `r_goals` regex. The wrapper's
`starts=(...),(...)` and `goals=(...),(...)` lines are silently
ignored. With no scenario lines parsed and `random_problem=0`, the
flow lands in `Problem::Problem`'s fallback that calls
`setRandomStartsGoals(seed)` — which deterministically generates the
same `(13,1)`, `(9,8)`, `(10,9), …` sequence we see in the captured
result.

For `mapd_pibt2`, the same parser logic applies but the binary
additionally generates a synthetic task stream (the `task=` block) and
emits solutions in `<pos>-><task_target>:<task_id>` format because
MAPD agents are continuously assigned new pickup/delivery tasks.

Reference: <https://github.com/Kei18/pibt2/blob/master/pibt2/src/problem.cpp>

## Why the smoke test gave a false green

`tests/test_solver_smoke.py::test_pibt2`'s post-condition is "any
active agent has > 1 distinct cell in its TimedPath" — i.e., **any
movement**. Even with random starts/goals, PIBT2 moves the random
agents around, the wrapper's parser successfully extracts positions
from the MAPF solution, and at least one agent's path has multiple
distinct cells. The test reports `PASSED` despite the plan having
nothing to do with what the simulator asked for.

`test_baseline_pibt2_fr` is sensitive to correctness because it
checks `metrics.throughput > 0`. Throughput requires agents to reach
*their* goals, not random ones. Hence it fails loudly while smoke
silently masks the bug.

## Ranked-by-evidence root cause hypotheses

1. **Wrapper writes the wrong instance-file format** — RANK 1, dominant.
   Evidence: Kei18/pibt2's `r_sg` regex only matches per-line
   `x_s,y_s,x_g,y_g` records; the wrapper emits `starts=(...)` and
   `goals=(...)` lines that don't match. Empirically confirmed by
   feeding the binary the correct format and observing identical
   starts/goals echoed back. **This bug affects EVERY PIBT2
   invocation, including the smoke test (where it's silently masked
   by the "any movement" check).**

2. **Wrapper auto-routes lifelong runs to `mapd_pibt2`** — RANK 2.
   Evidence: `_select_binary(is_lifelong)` in pibt2_wrapper.py
   returns `mapd_binary` when `mode="auto"` and `is_lifelong=True`.
   `RollingHorizonPlanner.step` always passes `is_lifelong=True` for
   lifelong-mode simulations. MAPD ignores the wrapper's
   starts/goals (separate from #1: even fixing #1 would still emit
   the wrong solution format from MAPD), generates synthetic tasks,
   and emits MAPD-format solutions
   (`<pos>-><task_target>:<task_id>`) the wrapper's MAPF-format
   parser cannot decode. Even if #1 is fixed, this bug alone causes
   `solver_errors=100` for every lifelong run.

3. **MAPD-format solution parser missing** — secondary, depends on #2.
   The wrapper's `_parse_result_file` regex `r'\((\d+),(\d+)\)'`
   matches BOTH `(current_pos)` AND `(task_target)` per agent in
   MAPD format, finding 2× the expected coord count per timestep
   line. The check `if len(coords) != len(agent_order)` (e.g.,
   40 != 20) skips every MAPD line. Fixing #2 (route to mapf_pibt2)
   eliminates this concern; otherwise we'd need an MAPD parser too.

Causes (1), (2), (3) from the prompt's hypothesis list:

* Cause (1) "wrapper invokes mapf instead of mapd on instances that
  require lifelong semantics" — **inverted**: the wrapper invokes MAPD
  on instances that should use MAPF. The simulator owns the lifelong
  task-stream loop (`RollingHorizonPlanner` calls the global solver
  per replan with the current snapshot of agent positions and
  assigned goals); each replan is a one-shot MAPF problem, not an
  MAPD problem.
* Cause (2) "instance file format is technically valid but encodes
  infeasible problems" — **rejected**: the instance file is *not*
  valid Kei18/pibt2 format at all (root cause hypothesis #1).
* Cause (3) "PIBT2's planning horizon is mismatched" — **not the
  cause**: the wrapper writes `max_timestep=horizon+50=70` and PIBT2
  reports `makespan=27` well within budget. Horizon is fine.

## Proposed fix (next prompt's scope)

**Wrapper-side, two changes in `pibt2_wrapper.py::_write_instance_file`
and `pibt2_wrapper.py::_select_binary`:**

1. **Change instance-file format** to the per-line records Kei18/pibt2's
   `r_sg` regex requires. Replace
   ```python
   f.write(f"starts={','.join(starts)}\n")
   f.write(f"goals={','.join(goals)}\n")
   ```
   with
   ```python
   for s_xy, g_xy in zip(starts, goals):
       f.write(f"{s_xy[0]},{s_xy[1]},{g_xy[0]},{g_xy[1]}\n")
   ```
   where each `s_xy` / `g_xy` is `(x, y) = (col, row)` in MovingAI
   convention.

2. **Always route lifelong-mode runs to `mapf_pibt2`**, not
   `mapd_pibt2`. The simulator's `RollingHorizonPlanner` owns the
   task-stream loop; each replan is a one-shot MAPF problem on the
   current agent-position / assignment snapshot. Recommended:
   change `_select_binary(is_lifelong)` to ALWAYS return
   `self.mapf_binary` regardless of `is_lifelong` (or remove the
   `mapd_binary` plumbing entirely until/unless a future test
   explicitly needs it). Document this in the wrapper docstring.

After these two changes, the existing MAPF-format result parser
already in the wrapper handles the output correctly — no parser
changes needed.

## Wrapper-side or test-side?

**Both fixes are wrapper-side.** No test should need to know
PIBT2's instance-file format. `test_baseline_pibt2_fr` is correct
as written; it only fails because the wrapper feeds the binary
malformed input.

## Other tests likely affected

* **`test_solver_smoke.py::test_pibt2_pibt2-binary_path`** —
  currently passes via false green (any-movement check). After the
  fix, will still pass and additionally produce a correct plan.
  Worth strengthening the smoke-test post-condition (out of scope).
* **Any §5.4 / §5.5 sweep that uses `pibt2`** as the global solver,
  or `pibt2_fr` as a baseline, will currently produce all-WAIT
  bundles and `throughput=0`, silently corrupting the paper's PIBT2
  numbers (per the prompt's "load-bearing fast solver for §5.4 /
  §5.5" warning). The fix is required for paper reproducibility.
* **`tests/test_official_solver_wrappers.py::TestPIBT2Solver::*`** —
  exercises only the wrapper's API surface (factory creation,
  parameter handling, binary-not-found path); does not run real
  planning, so unaffected.
* **`tests/test_solver_result_contract.py::*[pibt2]`** — same
  category, API-surface only.

## Checklist for the fix prompt

- [ ] Edit `_write_instance_file`: emit `x_s,y_s,x_g,y_g` per line,
      drop the `starts=` and `goals=` lines.
- [ ] Edit `_select_binary` (or `plan_with_metadata`): always route to
      `mapf_binary`. Remove the `is_lifelong` branch or keep it for
      future use but never fire it from the rolling-horizon path.
- [ ] Run `pytest tests/test_solver_smoke.py -k pibt2 -v` — must still
      pass.
- [ ] Run `pytest tests/test_baseline_pibt2_fr.py -v` — must now pass
      with `throughput > 0` and
      `violations_agent_attributable > 0`.
- [ ] Run full `pytest tests/` — no regressions on the other 510
      tests.
- [ ] Manually inspect the result for one warehouse-scale invocation
      (e.g., `agents=200` on warehouse-10-20-10-2-2) to confirm the
      binary's reported `starts`/`goals` match the wrapper's input.
- [ ] Update `docs/SOLVER_STATUS.md` PIBT2 row if it still references
      the broken-binary state.

---

## Resolution

**Wrapper fix landed in commit (this commit).** Two changes in
`src/ha_lmapf/global_tier/solvers/pibt2_wrapper.py`:

1. `_write_instance_file` now emits per-line `x_s,y_s,x_g,y_g`
   scenario records (matching Kei18/pibt2's `Problem.cpp` regex
   `(\d+),(\d+),(\d+),(\d+)`), replacing the unrecognised
   `starts=(...)` / `goals=(...)` syntax.  Source-format check
   (step 2 of the fix prompt) confirmed the diagnosis was accurate;
   no format adjustment was needed beyond what was proposed.
2. `_select_binary` always returns `mapf_binary` in the default
   `mode="auto"`, regardless of `is_lifelong`.  Explicit
   `mode="mapd"` / `"lifelong"` is preserved as an escape hatch.

**Verification (post-fix):**

* PIBT2's reported `starts=` / `goals=` in the result file now
  exactly match the wrapper's input (was: random deterministic
  scenario regardless of input).  Confirmed both at 5-agent and
  20-agent scale on the mini-warehouse.
* Bug 1's symptom (`solver_errors=100` due to "no paths parsed")
  is gone.  `tests/test_solver_smoke.py::test_pibt2` and the new
  `tests/test_pibt2_instance_format.py` (5 deep tests + 1
  end-to-end integration) all PASS.

**Residual `tests/test_baseline_pibt2_fr` failure — separate
concern, out of scope here:**

After the fix, PIBT2 receives correctly-formatted instances on the
mini-warehouse and now reports `solved=0` (was: `solver_errors=100`
with "no paths parsed").  Empirical capacity probe on the mini-
warehouse:

| agents | PIBT2 verdict | makespan |
|---|---|---|
| 2  | solved=1 | 14 |
| 5  | solved=1 | 15 |
| 10 | solved=1 | 25 |
| 15 | solved=1 | 37 |
| **20** (test fixture) | **solved=0** | hits max_timestep |

PIBT2 genuinely cannot find a complete plan for 20 agents on the
1-cell-wide-aisle mini-warehouse.  Increasing `max_timestep` from
70 to 1000 does NOT change the verdict (still `solved=0` at every
budget) — this is a structural deadlock in PIBT2's priority-scheme,
not a budget exhaustion.

The follow-on parser concern hypothesised in the original
diagnosis (the wrapper drops the partial solution PIBT2 produces on
the way to `solved=0`) is the next-prompt scope.  PIBT2 actually
writes 70 timesteps of agent positions to the result file even
when `solved=0`; for the rolling-horizon framework, only the first
`horizon=20` of those timesteps are needed, and they likely
constitute valid agent moves toward goals.  A wrapper change to
parse-and-truncate-on-`solved=0` would resolve `test_baseline_pibt2_fr`
without changing the binary or the test fixture.

`tests/test_official_solver_wrappers.py::TestPIBT2Solver::test_binary_selection_auto_mode`
was updated to reflect the new (correct) behaviour: `mode="auto"`
always returns `mapf_binary` regardless of `is_lifelong`.  The
previous assertion was encoding Bug 2.
