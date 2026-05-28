# Audit step 03 — `local_tier/` (controller + conflict resolvers)

Scope: `src/ha_lmapf/local_tier/agent_controller.py` (485 lines),
`local_tier/local_planner.py` (178 lines), and the three resolvers
in `local_tier/conflict_resolution/`.  Read + small synthetic
checks; the repro script is at
`scripts/diagnostics/audit_local_tier.py` (mirrors
`/tmp/audit_local_tier.py`).  No source modifications.

---

## 1. `AgentController.decide_action` flow vs Algorithm 2 — **PASS**

The Sense-Plan-Resolve flow at
`agent_controller.py:48`-`297` (`decide_action`) decomposes as:

| Algorithm-2 step | Code location | Effect |
|---|---|---|
| Reset per-tick wait-kind flags | L60-61 | `last_action_was_safe_wait = False`; `last_action_was_yield_wait = False` |
| At-goal short-circuit (idle WAIT, not safe-wait) | L67-68 | `if cur == goal: return WAIT` |
| Read ablation flags | L70-71 | `disable_local_replan`, `disable_conflict_resolution` |
| **Sense**: build forbidden set $F = B_{r_{\text{safe}}}(X_t^{\Phi_i}) \cup D(t)_{\text{ext}}$ | L73-76 | `human_cells = {h.pos for h in obs.visible_humans.values()}`; `forbidden = inflate_cells(human_cells, safety_radius)`; `blocked = obs.blocked ∪ forbidden` |
| **Plan**: pull desired next from global plan | L79 | `desired_next = self._desired_from_global_plan(sim_state)` |
| Replan trigger conditions | L82-103 | (a) no global plan, (b) `desired_next ∈ forbidden`, (c) global path exhausted (true exhaustion, not coordinated wait), (d) near-future cells of global path pass through `forbidden` |
| Bounded local A* with deviation bias | L122-125 | `self.local_planner.plan(env, cur, goal, blocked, guidance_cells=...)`; A* respects `MAX_EXPANSIONS = 10_000` (local_planner.py:47) and adds `GUIDANCE_DEVIATION_COST = 1` per off-path cell (L42) |
| EscapeMove (buffer escape) | L180-200 | If `cur ∈ forbidden`, try `_find_escape_move`; on success, use the escape cell; on failure, Safe-Wait |
| Safe Wait | L196-207, L233-245, L300-310 | Sets `last_action_was_safe_wait = True`; returns WAIT |
| Hard-safety enforcement (`desired_next ∈ forbidden`) | L238-240 | Returns Safe-Wait BEFORE the resolver runs |
| Reject move into human-occupied cell | L243-245 | Returns Safe-Wait |
| **Resolve**: delegate to conflict resolver | L252-261 | `conflict_resolver.resolve(forbidden=forbidden, local_planner=self.local_planner, ...)` |
| Mark plan stale if resolver rerouted | L263-272 | `set_local_path(aid, [cur])` (one-step staleness; preserves global plan) |
| Yield-WAIT bucketing | L289-290 | If resolver returned WAIT, mark `last_action_was_yield_wait = True` |
| Reset safe-wait latch on movement | L293-295 | `_consecutive_waits = 0`; `clear_safety_wait(aid)` |

**Precedence of fallbacks** (paper's stated order):
1. Follow global plan → 2. Local A* detour → 3. EscapeMove (if `cur ∈ F`) → 4. Safe-Wait.  Conflict resolver only runs once a valid `desired_next` survives the hard-safety filter.  This matches the Algorithm 2 narrative in `docs/proposed_approach.md` §F.

**Forbidden-set construction** matches paper §4:
- Vertex forbidden $F^{\text{vtx}}$ = `inflate_cells(human_cells, safety_radius)`
  at `agent_controller.py:75`, where `inflate_cells` (in
  `humans/safety.py`) returns the Manhattan-ball $B_{r_{\text{safe}}}$
  around each observed human.
- The "cells claimed by other agents" component $D(t)_{\text{ext}}$
  is supplied via `Observation.blocked` (built by `sensors.py`) and
  consulted in the resolver's loser-fallback (`priority_rules.py:107`,
  `token_passing.py:156`, `_astar_fallback`'s `decided` set).
- Edge forbidden $F^{\text{edg}}$ is enforced by step 7a in
  `simulator.py:1635-1643` (the edge-swap detection / revert path,
  audit 02 §4).

---

## 2. Resolver priority tuples — paper vs code

### `WaitBasedResolver` (formerly `PriorityRulesResolver`, paper §4.3 "Wait-Based")

`priority_rules.py:85`-`97`:

```python
def _priority(self, agent_id, sim_state):
    a = sim_state.agents[agent_id]
    dist = manhattan(a.pos, a.goal) if a.goal is not None else 10**9
    urgency = -dist
    if a.wait_steps > self.starvation_threshold:
        urgency += self.boost
    return (urgency, int(a.wait_steps), -int(agent_id))
```

| Slot | Paper ($\rho_i$) | Code | Match? |
|---|---|---|:--:|
| 1 (primary) | $-d_i + \beta \cdot \mathbf{1}[w_i > w^*]$ | `urgency = -dist + boost·(wait_steps > threshold)` | **YES** ($\beta = 50$, $w^* = 10$ defaults match `docs/CONFORMANCE.md`) |
| 2 (secondary) | $w_i$ | `int(a.wait_steps)` | **YES** |
| 3 (tertiary, tie-break) | $-i$ | `-int(agent_id)` | **YES** |

**Synthetic check** (`/tmp/audit_local_tier.py`):
- Agent 0 at (0,0) goal (4,4) wait=0 → `_priority(0) = (-8, 0, 0)` — expected `(-8, 0, 0)`.  PASS.
- Agent 1 at (2,2) goal (0,0) wait=3 → `_priority(1) = (-4, 3, -1)` — expected `(-4, 3, -1)`.  PASS.

### `PIBTResolver` (paper §4.3 "PIBT-style")

`pibt.py` has **no `_priority` method**.  Instead it implements a depth-2
push: on a vertex conflict, ask whether the blocker has any feasible
alternative move that reduces its distance to its own goal.  If yes,
current agent proceeds; else WAIT.  Scoring of blocker candidates
(`_can_push_blocker` L89-92):

```python
def score(cell):
    d = manhattan(cell, blocker.goal) if blocker.goal else 10**9
    is_wait = 1 if cell == cur else 0
    return d, is_wait, cell[0], cell[1]
```

| Slot | Paper PIBT tuple | Code blocker-scoring tuple | Match? |
|---|---|---|:--:|
| 1 | priority by goal-distance | `d = manhattan(cell, blocker.goal)` | **YES** in spirit (minimised, not maximised) |
| 2 | move > wait | `is_wait` (0 if move, 1 if WAIT; minimised) | **YES** |
| 3 | lexicographic tie | `cell[0], cell[1]` | **YES** |

Note: this is the score on the *blocker's candidate cells*, not a global
agent-priority tuple in the sense the wait-based resolver uses.  PIBT in
this codebase is a **depth-2 push feasibility check**, not the full
recursive PIBT-PP procedure.  See "Modularity" §3 below for the
implication on Theorem 1 plumbing.

### `TokenBasedResolver` (formerly `TokenPassingResolver`, paper §4.3 "Token-Based")

`token_passing.py:128`-`136`:

```python
def _priority(self, agent_id, sim_state):
    a = sim_state.agents[agent_id]
    dist = manhattan(a.pos, a.goal) if a.goal is not None else 10**9
    urgency = -dist
    return (urgency, int(a.wait_steps), -int(agent_id))
```

| Slot | Paper $\rho$ (per task brief: `(τ, -d, w)`) | Code | Match? |
|---|---|---|:--:|
| 1 | **token count $\tau_i$** (per-agent per-cell) | `urgency = -manhattan(pos, goal)` | **NO** |
| 2 | $-d_i$ | `int(a.wait_steps)` | **NO** |
| 3 | $w_i$ | `-int(agent_id)` | **NO** |

**The code does not implement a token-count term in the priority tuple at
all.**  Instead the tuple is the same `(-d, w, -id)` shape used by the
wait-based resolver (minus the starvation boost), and the "token"
concept is realised differently — as **per-cell single-owner state with
$K$-streak rotation**, captured in `_TokenState`:

```python
@dataclass
class _TokenState:
    owner: int
    win_streak: int = 0
    last_step: int = -1
```

`token_passing.py:82`-`106` shows the mechanism:
- On the first conflict for a cell, the highest-priority contender (by
  the `(-d, w, -id)` tuple) becomes the owner; `win_streak = 1`.
- If the same owner wins again on a later tick, `win_streak += 1`.
- If `win_streak >= fairness_k` (default 5) and there are other
  contenders, rotate ownership to the next-best contender.

**Synthetic check**:
- Agent 0 at (0,0) goal (4,4) wait=0 → `_priority(0) = (-8, 0, 0)` (no τ term, same as WaitBased).  PASS.
- Agent 1 at (2,2) goal (0,0) wait=3 → `_priority(1) = (-4, 3, -1)`.  PASS.

### Exact characterization of the token_passing divergence

The paper's $\rho = (\tau, -d, w)$ tuple specifies that the primary
tie-break is the count of tokens a contender holds at the contested cell,
making fairness an emergent property of accumulated token credit (token
inflation as a side-effect of repeated losses, eventually flipping
ownership).

The code instead implements **single-owner-with-K-rotation**:
1. Priority tuple has **no τ term**; it is `(-d, w, -id)`.
2. "Token" is a per-cell `_TokenState(owner, win_streak, last_step)`, not
   a per-(agent, cell) count.
3. Fairness comes from the explicit `if win_streak >= K: rotate` rule,
   not from accumulated count comparisons.

The effective tie-break order in code is:
$\rho_{\text{code}}^{\text{token}} = (-d_i, w_i, -i)$, with a tick-rate
governor that flips the owner after $K$ consecutive wins.

**Verdict for §2.token: DIVERGENCE confirmed and characterized**.  Code
implements single-owner + $K$-rotation, paper specifies per-cell token
count in the priority tuple.

---

## 3. Modularity: resolver does not alter the forbidden set — **PASS** (with one caveat)

**Claim**: the safety result is independent of resolver choice because
the resolver only ranks contenders; it never mutates the forbidden set
$F$ that the controller hands it.

**Construction-level evidence**:

- `agent_controller.py:75` builds `forbidden` once per tick from the
  observed humans plus safety radius.  This is a fresh `set` each tick
  (`inflate_cells` returns a new set).
- `agent_controller.py:253-261` passes `forbidden=forbidden` into
  `resolve()` as a kwarg.
- `priority_rules.py:53` and `token_passing.py:64` start their resolve
  with `forbidden_set = set(forbidden)` — a **defensive copy**.  After
  that, the only operations on `forbidden_set` are membership tests
  (`nb in forbidden_set` at `priority_rules.py:115`, `token_passing.py:166`,
  and inside `_astar_fallback`); no mutation.
- `pibt.py:43` accepts and silently ignores `forbidden` via `**_kwargs`.

**Synthetic check** (`/tmp/audit_local_tier.py`): pass a tagged
forbidden set `{(99,99)}` into a `resolve()` call, then assert the
caller's set is unchanged:

```
WaitBasedResolver  forbidden-set immutability: ('ok', True, {(99, 99)})
TokenBasedResolver forbidden-set immutability: ('ok', True, {(99, 99)})
```

PASS for both.

**Caveat (PIBT)**: `PIBTResolver` accepts `**_kwargs` and discards
`forbidden`.  This is safe for its default behaviour:
- When the depth-2 push succeeds, the agent moves to `desired_next`,
  which has already been hard-safety-filtered at
  `agent_controller.py:238` BEFORE the resolver call.  No $F$ violation
  possible.
- When push fails, PIBT defaults to `WAIT` (`pibt.py:69`), which holds
  the agent's pre-move position — invariant-guaranteed outside $F$.
- HOWEVER if `allow_side_step=True` is enabled (default False),
  `_safe_side_step` at `pibt.py:113-122` consults only
  `observation.blocked`, NOT `forbidden`.  In that mode PIBT could
  side-step into an $F$ cell that's not in `observation.blocked` (e.g.
  if `safety_radius > 0` produced an inflation around a cell the
  observation didn't list).  **This is a documented gap, not a bug at
  the default configuration**; reported here for completeness.

---

## 4. Bounded local A* respects $N_{\max}$, deviation bias, F — **PASS**

`local_planner.py:47`-`168`:

| Paper element | Code | Match? |
|---|---|:--:|
| $N_{\max}$ expansion cap | `MAX_EXPANSIONS = 10_000` at L47; checked at L125 (`if expansions > MAX_EXPANSIONS: break`) | **YES** |
| Deviation bias | `GUIDANCE_DEVIATION_COST = 1` at L42; applied at L156-157 (`step_cost += 1` if cell not in `guidance_cells`) | **YES** |
| Static-obstacle avoidance | `env.is_free(nb)` filter at L140 | **YES** |
| Forbidden-set avoidance (hard) | L143-146: `if nb in blocked: if hard_safety: continue` | **YES** |
| Forbidden-set avoidance (soft) | L143-149: `step_cost = BLOCKED_CELL_COST = 50` | **YES** |
| Start-in-buffer corner case | L109-112: start cost penalty in soft mode; no special case in hard mode (the caller's EscapeMove handles it) | **YES** |

---

## Summary

| Area | Verdict | Evidence |
|---|:--:|---|
| §1 Sense-Plan-Resolve flow vs Algorithm 2 | **PASS** | Line-by-line mapping table at top of this report |
| §1 Forbidden-set construction ($F^{\text{vtx}}$, $F^{\text{edg}}$) | **PASS** | `agent_controller.py:75`; `simulator.py:1635-1643` |
| §1 Bounded A* (N_max, deviation, F) | **PASS** | `local_planner.py:47, 42, 140, 143` |
| §1 EscapeMove + Safe-Wait precedence | **PASS** | `agent_controller.py:180-207, 233-245`; matches §4.3 |
| §2 WaitBased priority tuple | **PASS** | `(urgency, w, -id)` with $\beta·\mathbf{1}[w > w^*]$ boost; synthetic = `(-8,0,0)`, `(-4,3,-1)` |
| §2 PIBT (depth-2 push, not full PIBT-PP) | **partial** | No global priority tuple; per-blocker scoring `(d, is_wait, r, c)` matches push-heuristic intent |
| §2 TokenBased priority tuple | **FAIL** (divergence) | Code: `(-d, w, -id)` + single-owner K-rotation.  Paper: $(\tau, -d, w)$ with per-cell token count.  Characterized in §2.token. |
| §3 Resolver does not mutate F (modularity) | **PASS** | Defensive `set(forbidden)` copy in priority_rules / token_passing; synthetic verifies no mutation.  PIBT ignores F but is safe at default `allow_side_step=False` |

---

## BUGS FOUND

None as bugs that break correctness at default configurations.

## DIVERGENCES FROM PAPER (no fix proposed; recorded for paper authors)

- **`token_passing.py` priority tuple**: code is `(-d, w, -id)` with
  per-cell single-owner $K$-rotation; paper §4.3 (per the task brief)
  specifies $(\tau, -d, w)$ with per-(agent, cell) token count.  This
  was a known issue and is now precisely characterized above.  Resolution
  options: (a) update the paper to describe the single-owner + K-rotation
  semantics actually implemented, (b) re-implement the resolver with a
  $\tau$-first tuple and per-(agent,cell) counters.

## GAPS (config-dependent, not active at defaults)

- **`PIBTResolver` with `allow_side_step=True`**: `_safe_side_step`
  filters `observation.blocked` but not the resolver-plumbed `forbidden`
  kwarg.  Default `allow_side_step=False` avoids this path; if a future
  config enables it, the resolver could side-step into $F$.  Proposed
  fix (not applied): plumb `forbidden` through `_safe_side_step` and add
  the membership test, matching the analogous filter in
  `priority_rules.py::_safe_side_step:115`.
