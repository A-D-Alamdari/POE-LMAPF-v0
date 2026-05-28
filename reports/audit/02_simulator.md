# Audit step 02 — `simulation/simulator.py`

Scope: `src/ha_lmapf/simulation/simulator.py` (1923 lines).  Focus on
`step_once()` and the helper methods it calls in-tick.  No source
modifications.  All synthetic checks are single-tick, hand-built scenarios
that bypass `Simulator.run()`; the repro script lives at
`scripts/diagnostics/audit_simulator.py` (mirrors `/tmp/audit_simulator.py`
used to generate this report).

---

## 1. Per-tick step order in `step_once()` — **PASS**

Documented inline in `simulator.py:1432`-`1795`.  The numbered list below is
the executed order with the citing line range.

| # | Step | Lines |
|---:|---|---|
| 0 | Reset per-tick wait-kind flags (`last_action_was_physics_revert_wait`, `last_action_was_delay_wait`) | 1458-1460 |
| 1 | **Release tasks** (`_release_tasks`) | 1463 |
| 2 | **Assign tasks** (`assign_tasks`) | 1466 |
| 3 | **Global planning** (`maybe_global_replan`) | 1469 |
| 3.5 | Snapshot `humans_pre_move` (deep copy of `self.humans` BEFORE step 4 mutates them) | 1479-1481 |
| 4 | **Environment dynamics: humans move** (`_update_humans`) | 1484 |
| 4.5 | Snapshot `humans_at_decision = dict(self.humans)` (humans-first ordering: post-step-4 positions are exactly what agents will sense at step 5) | 1491 |
| 5a | **Build per-agent partial observations** (`build_observation`) | 1495-1497 |
| 5b | **Decide actions** (per-agent `decide_action`), bucket safe/yield WAITs into `safe_wait_steps`/`yield_wait_steps`, register decided positions for next-agent conflict detection | 1499-1573 |
| 6 | **Execution-delay injection** (probabilistic override to WAIT, sets `last_action_was_delay_wait`) | 1575-1600 |
| 7a | **Physics: vertex/edge-swap revert loop** — iterative resolver, lower-id wins, reverted agents get `last_action_was_physics_revert_wait = True` | 1602-1660 |
| 7b | **Apply validated actions** (`apply_agent_action` writes `self.agents[aid].pos`) | 1662-1664 |
| 7c | **Post-physics wait-kind bucketing** for delay/physics-revert WAITs | 1666-1693 |
| 7-aux | Tier-1→Tier-2 guidance handoff evaluation (gated on `debug_guidance_trace`) | 1695-1726 |
| 7-deadlock | **Per-agent deadlock streak update + global no-progress accumulator** | 1728-1775 |
| 8 | **Collision detection + Def-1 / WAIT-cf classifiers** (`_detect_collisions_and_near_misses` consumes BOTH `humans_pre_move` and `humans_at_decision`) | 1777-1782 |
| 9 | **Task completion + makespan/SOC** (`_maybe_complete_tasks`) | 1784-1785 |
| 10 | Replay record | 1787-1788 |
| 11 | Per-step decision-time accumulator | 1790-1792 |
| 12 | `self.step += 1` | 1795 |

**Minor cosmetic finding** (not a bug): two consecutive block comments are
labelled `7c` (one at line 1666 for the post-physics wait-kind bucketing,
one at line 1728 for the deadlock detector).  Both run between step 7b and
step 8.  No correctness impact; the labels are documentation-only.

---

## 2. Human-position snapshots: name vs content — **PASS**

| Snapshot | Capture line | Source | Paper notation | Name vs content |
|---|---|---|---|---|
| `humans_pre_move` | 1479-1481 | `{hid: replace(h) for hid, h in self.humans.items()}` captured **before** `_update_humans` at step 4 | $X_t$ (pre-step-4) | **MATCH** — name says "pre-move", content is pre-step-4 positions |
| `humans_at_decision` | 1491 | `dict(self.humans)` captured **after** `_update_humans` at step 4 | $X_t^{\text{post-step-4}}$ — the positions agents observe at step 5 (humans don't move again until next tick), and therefore the formal decision-time information used by Theorem 1's attribution rule | **MATCH** — name says "at_decision", content is exactly what agents see at decision time |
| `self.humans` (mutable) | mutated at 1484 | live state | — | not a snapshot; the two named snapshots above are derived from it |

Both snapshots are then threaded through `_detect_collisions_and_near_misses`
at step 8 (line 1779-1782).  The Def-1 classifier reads BOTH (FoV gate uses
`humans_pre_move`; violation-pair-at-$t+1$ enumeration uses
`humans_at_decision`).  The WAIT-counterfactual classifier reads only
`humans_at_decision`.

The contract is documented inline:
- `simulator.py:1471-1478` explains why two snapshots exist.
- `simulator.py:1486-1490` explains the humans-first ordering rationale
  ("humans move at step 4 and do not move again until the next tick").
- `simulator.py:1073-1078` repeats the contract in the
  `_detect_collisions_and_near_misses` docstring.

No misnamed snapshot.

---

## 3. The two violation classifiers — **PASS**

### (A) Definition-1 (paper §3, Theorem-1 empirical witness)

Located at `simulator.py:1198-1245`.

- **Inputs**: pre-move humans (FoV filter), post-move humans (violation-pair
  enumeration at $t+1$).
- **FoV gate** (line 1212-1214):
  `observed_pairs = [(hid, h.pos) for hid, h in humans_pre_move.items() if
  |a_prev - h.pos|_1 <= fov_r]`.
- **Two clauses** (line 1235-1241):
  - moved AND
  - $\exists\, h' \in \mathrm{observed\_pairs}$: $|s_i(t) - h'|_1 > r_{\mathrm{safe}}$ AND $|s_i(t+1) - h'|_1 \le r_{\mathrm{safe}}$.
- **Buckets**: `violations_def1_agent_attributable` (clauses satisfied) or
  `violations_def1_exogenous_attributable` (clauses not satisfied).

### (B) WAIT-counterfactual diagnostic

Located at `simulator.py:1247-1275`.

- **Input**: post-move humans only.
- **No FoV gate** — iterates every $(a_i, h)$ pair with $|s_i(t+1) - h_{\mathrm{post}}|_1 \le r_{\mathrm{safe}}$.
- **Single clause** (line 1261): `moved AND |a_prev - h_post|_1 > r_safe` (would WAITing have saved you?).
- **Buckets**: `violations_agent_attributable` / `violations_exogenous_attributable`.
- **Diagnostic label**: docstring at line 1153-1165 explicitly names this
  the "WAIT-counterfactual diagnostic" and notes it is "NOT a Theorem 1
  invariant; on a healthy run it can be nonzero".

### Synthetic ticks (hand-built; `/tmp/audit_simulator.py`)

| Scenario | Agent move | Human pre-move | Human post-move | FoV / safety | Expected | Observed | Verdict |
|---|---|---|---|---|---|---|---|
| A — Def-1 agent-attributable | (3,3) → (3,4) | (3,5) | (3,5) | 2 / 1 | `def1_agent=1, def1_exo=0` | `(1, 0)` | **PASS** |
| B — Def-1 exogenous-attributable | (3,3) → (3,4) | (3,6) (unobserved) | (3,5) | 2 / 1 | `def1_agent=0, def1_exo=1` | `(0, 1)` | **PASS** |
| C — WAIT-cf bucketing on Scenario B's positions | same as B | — | — | — | `agent_attr=1, exo_attr=0` | `(1, 0)` | **PASS** |

Scenario A satisfies clauses (a) and (b) against the OBSERVED pre-move
witness (3,5): $|(3,3)-(3,5)|_1 = 2 > 1$ and $|(3,4)-(3,5)|_1 = 1 \le 1$;
the pre-move witness is in FoV ($2 \le 2$).

Scenario B: the violation pair at $t+1$ exists (agent at (3,4), human
post-move at (3,5), $L_1 = 1 \le 1$).  But the FoV gate rejects the only
human ($|(3,3)-(3,6)|_1 = 3 > 2$); no Def-1 witness ⇒ exogenous-attributable.

Scenario C exercises the WAIT-counterfactual on the same positions: would
the agent have been safe if it WAITed at (3,3)?  $|(3,3)-(3,5)|_1 = 2 > 1$
⇒ yes; the agent moved into the buffer ⇒ agent-attributable under (B).

---

## 4. Physics layer (vertex/edge-swap revert) — **PASS**

Located at `simulator.py:1602-1660`.

- **Vertex conflict**: cell already claimed → revert one of the two agents
  to WAIT (line 1632-1633, 1645-1657).
- **Edge swap**: two agents would swap positions → revert (line 1636-1643,
  1645-1657).
- **Tie-break**: sorted-by-`agent_id` order; lower id wins (the iterative
  loop processes agents in `sorted_aids` order, claiming the destination
  first).
- **Pre-claim for stationary agents** (line 1622-1624): an agent whose
  intended position equals its previous position pre-claims that cell, so
  a lower-id mover cannot displace a stationary higher-id agent.

**Counting (Prompt C / P11)**: the reverted agent gets
`last_action_was_physics_revert_wait = True` (line 1656), and the
post-physics bucketing block at `simulator.py:1684-1693` adds to
`physics_revert_wait_steps`.  The four-bucket invariant
`total_wait == safe + yield + physics_revert + delay` is asserted at
finalize (`metrics.py:980-991`).  Verified in audit step 01 §4 with teeth
tests (raises on broken invariant); and verified end-to-end against
real `Simulator.run()` output in the P17 follow-up
(`reports/audit/physics_revert_reachability.md`).

Prompt C IS applied; physics-revert WAITs are counted.

---

## 5. Task completion + reassignment — **PASS**

Located in `_maybe_complete_tasks` at `simulator.py:1300-1387`.

- **Phase 1 (pickup)**: agent's current position must equal `task.start`
  (line 1322); on match, goal is rewritten to `task.goal` and
  `carrying=True` (line 1333-1337).  `task_id` is NOT cleared yet — the
  task is still active.
- **Phase 2 (delivery)**: agent's position must equal `task.goal` (line
  1324); on match, `on_task_completed` is called once (line 1356).
- **Becomes idle**: line 1372-1378 sets `goal=None`, `carrying=False`,
  `task_id=None`, `done_tasks += 1`.
- **Reassignment**: mid-horizon assignment via `_try_mid_horizon_assign`
  fires immediately after (line 1387), so the agent can pick up a new
  task in the same tick.

**`completed_tasks` increments exactly once per task** — guarded inside
`MetricsTracker.on_task_completed` at `metrics.py:220-223`:

```
if record.completed_step is None:
    record.completed_step = step
    record.agent_id = agent_id
    self._completed_tasks += 1
```

The `is None` guard makes the increment idempotent under repeated calls.
**Synthetic verification** (call twice on the same task_id): observed
`_completed_tasks == 1` (expected 1) ⇒ PASS.

---

## 6. Deadlock detector — **PASS**

Located at `simulator.py:1728-1775`.

- **Threshold**: `_deadlock_streak_threshold` initialised from
  `SimConfig.deadlock_streak_threshold` (default 100) at `simulator.py:
  221-222`.
- **Increment**: a streak ticks up only when the agent has an active task
  (`cur_task is not None and a.goal is not None`), the task did not just
  change (`cur_task == prev_task`), and position did not advance
  (`a.pos == prev_pos[aid]`) — `simulator.py:1748-1763`.
- **Reset triggers** (each clears the streak to 0):
  - idle / between-task (`cur_task is None or a.goal is None`) — line 1750
  - new task assignment (`cur_task != prev_task`) — line 1754
  - movement (`a.pos != prev_pos[aid]`) — line 1759
- **Bookkeeping**: agents crossing the threshold are added to
  `_deadlocked_agents: Set[int]` — line 1765.
- **Reported as**: `Metrics.deadlock_count = len(self._deadlocked_agents)`
  in `Simulator.run` finalize (line 1818) → **per-run distinct-agent count**
  by construction (`set` semantics).

**Synthetic verification** (add aid=7 to `_deadlocked_agents` three times):
observed `len == 1` (expected 1) ⇒ PASS.

---

## Summary

| Area | Verdict | Evidence |
|---|:--:|---|
| §1 Per-tick ordering | **PASS** | Lines 1432-1795; numbered table above with exact line ranges |
| §2 Human-snapshot name vs content | **PASS** | `humans_pre_move` captured at L1479-1481 pre-step-4; `humans_at_decision` captured at L1491 post-step-4; both names match content |
| §3 Def-1 / WAIT-cf classifiers | **PASS** | 3 synthetic ticks (`/tmp/audit_simulator.py`); A=(1,0), B=(0,1), C=(1,0); diagnostic label at L1153 |
| §4 Physics revert + counting | **PASS** | L1602-1693; P11 applied; verified in audit 01 + P17 reachability audit |
| §5 Task completion | **PASS** | `on_task_completed` idempotent at metrics.py:220-223; synthetic double-call observed `_completed_tasks=1` |
| §6 Deadlock detector | **PASS** | `_deadlocked_agents: Set` → `Metrics.deadlock_count = len(_)`; resets on idle / new-task / movement |

## BUGS FOUND

None.

## Cosmetic findings (no correctness impact)

- `simulator.py:1666` and `simulator.py:1728` are both labelled "step 7c"
  in their block comments.  The labels are documentation-only; both blocks
  run between step 7b (apply) and step 8 (collision detection).  Consider
  renumbering one of them on a future cleanup pass.
