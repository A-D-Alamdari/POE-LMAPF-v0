# Audit step 04 — global_tier + humans + safety

Scope: `src/ha_lmapf/global_tier/rolling_horizon.py` (423 lines),
the two `task_allocator.py` files (one live, one dead), all five
human models in `src/ha_lmapf/humans/models.py`, and
`src/ha_lmapf/humans/safety.py`.

Read + small synthetic checks (script at
`scripts/diagnostics/audit_global_humans.py`).  No source modifications.

---

## 1. Rolling-horizon planner — **PASS** (with one documented gap)

### 1.1 H / R coupling

`SimConfig` defaults (`core/types.py:738-739`): `replan_every = 10`,
`horizon = 20`.  So $R = \lfloor H/2 \rfloor$ holds at the default
configuration.

**Gap**: `RollingHorizonPlanner.__init__` (`rolling_horizon.py:24-72`)
accepts arbitrary `horizon` and `replan_every` independently; it does
NOT validate or enforce $R = \lfloor H/2 \rfloor$.  Synthetic check:
constructing `RollingHorizonPlanner(horizon=10, replan_every=7)`
succeeds and stores both values verbatim.  The paper's claim therefore
holds **by config convention, not by code invariant**.

**Recommended (not applied) fix**: add a one-line assert in
`__init__`, e.g.
```python
if replan_every != horizon // 2:
    logging.warning("R=%d differs from floor(H/2)=%d", replan_every, horizon // 2)
```

### 1.2 Prefix commitment / action persistence — **PASS**

The simulator advances `self.step` only after `_maybe_complete_tasks`
returns (see audit 02 §1, line 1795).  Every replan call passes
`agents=sim_state.agents` (the **realized** state after step 7b applied
actions) and `step=cur_step` (the current tick) into the solver
(`rolling_horizon.py:290-297`).  The previous plan is overwritten only
from `cur_step` forward; **no past tick's action is retroactively
edited** — committed actions cannot be revoked because they live in
agent positions that are now the starting state of the new plan.

The `_reanchor_last_good` fallback (`rolling_horizon.py:168-223`) reuses
a previous good bundle by *shifting* its index by `cur_step - start_step`
and **clipping** before the current tick.  This explicitly preserves
commitment: the reused tail starts at `offset = cur_step - start_step`,
never before.

### 1.3 Emergency replan trigger — **PASS**

`_eta_w_trigger` at `rolling_horizon.py:133-166`:

| Predicate | Code |
|---|---|
| (i) Safe-Wait fraction > $\eta_w$ | `frac = n_safe_wait / n; return frac > self.eta_w` (L161-166) |
| (ii) `cur_step - last_replan_step ≥ replan_min_gap` | L157-158 |
| (iii) Last replan was useful | L159-160 (`if not self._last_replan_useful: return False`) |
| $\eta_w$ default | `eta_w: float = 0.20` (`rolling_horizon.py:32`) |
| $R_{\text{min\_gap}}$ default | `replan_min_gap: int = 3` (`rolling_horizon.py:33`) |

Synthetic check: defaults verified `(H, R, η_w, min_gap) = (20, 10, 0.20, 3)`.

---

## 2. Task allocators

### 2.1 Module reconciliation — live vs dead

| Path | Status | Classes |
|---|---|---|
| `src/ha_lmapf/task_allocator/task_allocator.py` | **LIVE** (imported by `simulator.py:43`, `baselines/whca_star.py`, `baselines/rhcr_like.py`, 4 test files) | `GreedyNearestTaskAllocator`, `HungarianTaskAllocator`, `AuctionBasedTaskAllocator`, **`CongestionAvoidanceTaskAllocator`**, `TaskAllocator` (re-export) |
| `src/ha_lmapf/global_tier/task_allocator.py` | **DEAD** (audit 00 orphan list — no in-repo importer) | `GreedyNearestTaskAllocator`, `HungarianTaskAllocator`, `AuctionBasedTaskAllocator`, `PersistentTaskAllocator`, `TaskAllocator` |

**Differences between the two files**:
- DEAD file lacks `CongestionAvoidanceTaskAllocator` (the paper's §4.2 allocator) — confirming it predates that feature.
- DEAD file ships a `PersistentTaskAllocator` not present in LIVE.  Grep confirms no in-repo caller for the dead `PersistentTaskAllocator`.
- Both files are otherwise structurally similar Greedy/Hungarian/Auction implementations.

**Resolution**: the simulator (`simulator.py:43`) imports the LIVE file
exclusively.  The DEAD file is a stale copy carried under
`global_tier/` from before the package was refactored to
`task_allocator/`.  **Recorded in audit 00 dependency map as orphan**;
no fix applied here.

### 2.2 `CongestionAvoidanceTaskAllocator` — narrowness + cost matrix

#### Narrowness formula

`task_allocator.py:349-381`:

```python
narrowness(c) = 4.0 / max(1, degree(c))
```

where `degree(c)` is the count of free 4-neighbours of `c`.

| Cell category | degree | $\nu$(c) | Code observed |
|---|---|---|---|
| Open interior | 4 | 1.0 | 1.0 ✓ |
| Edge cell | 3 | 4/3 | 1.333... ✓ |
| Corner cell | 2 | 2.0 | 2.0 ✓ |
| Dead-end | 1 | 4.0 | (formula applies) |
| Isolated | 0 | 4.0 (clamped by `max(1, .)`) | (formula applies) |

This matches the paper's §4 narrowness weighting verbatim.

#### Cost matrix update

`task_allocator.py:456-491` (round-by-round refinement):

```python
C[i,j] = D[i,j]
       + lambda_conflict * sum_over(i' != i) (
           sum_over(c in path_ij & path_{prev[i']}) narrowness(c)
       )
```

| Paper element | Code |
|---|---|
| Distance term $D_{ij}$ | `D[i,j] = BFS dist(agent_i.pos, pickup(task_j))` (L430-450) — exact BFS on the 4-connected grid, falls back to Manhattan if no env |
| Path-overlap penalty $\omega_{ij}$ | `sum over shared cells of narrowness(c)` (L477-486) |
| Weighting $\lambda$ | `self.lambda_conflict` (default **0.5**, L316-325) |
| Iteration cap $R_{\max}$ | `self.max_rounds` (default **5**, L316-325) |
| Convergence | `if new_assignment == prev_assignment: break` (L489-490) |

Synthetic check: `lambda_conflict = 0.5`, `max_rounds = 5` confirmed at
defaults.  A 2-agent / 2-task scenario whose greedy paths cross at
(2,2) on a 5×5 grid produced the **anti-crossing assignment** (agent 0
→ task B, agent 1 → task A) and converged in 2 refinement rounds.

### 2.3 Greedy / Hungarian / Auction

| Allocator | Confirmed behaviour | Notes |
|---|---|---|
| `GreedyNearestTaskAllocator` | Sorts tasks by `(release_step, task_id)`; for each task, picks the nearest free agent by Manhattan distance to pickup, removes that agent from the free pool.  Deterministic ✓ | `task_allocator.py:27-81` |
| `HungarianTaskAllocator` | Builds Manhattan cost matrix, runs `scipy.optimize.linear_sum_assignment`; falls back to Greedy if scipy missing | `task_allocator.py:84-140` |
| `AuctionBasedTaskAllocator` | Sequential single-item auction.  `max_iterations` default 100; **`epsilon` default 0.01**.  Termination: `if best_value <= 0: continue`; otherwise `bid_increment = best_value - second_best + epsilon`; loop exits when no unassigned agents remain or `max_iterations` exhausted | `task_allocator.py:143-250` |

`AuctionBasedTaskAllocator.__init__` (L152-161): `epsilon: float = 0.01` confirmed.

---

## 3. Human models

### 3.1 RandomWalk — Boltzmann distribution, three log-weights

`models.py:126-201`.

Distribution:
$$\pi_h(u \mid x_h(t), a_h(t)) \propto \exp(\mathrm{score}(u))$$
where
$$\mathrm{score}(u) = \begin{cases}
\beta_{\text{go}} & u = \mathrm{cont}(x, a)\\
\beta_{\text{wait}} & u = x\\
\beta_{\text{turn}} & \text{otherwise}
\end{cases}$$

Defaults: $\beta_{\text{go}} = 2.0$, $\beta_{\text{wait}} = -1.0$,
$\beta_{\text{turn}} = 0.0$.  Sampling at `_softmax_sample`
(`models.py:86-101`) uses the numerically-stabilised softmax
(`shifted = scores - scores.max()`).  Matches paper formulation.

### 3.2 AisleFollower — aisle-likelihood field $\phi$

`models.py:240-335`.

Distribution:
$$\pi_h(u) \propto \exp\bigl(\alpha\,\phi(u) + \beta\,\mathbf{1}[u = \mathrm{cont}(x, a)]\bigr)$$

`_compute_obstacle_distance_field` (`models.py:208-237`) builds the
multi-source BFS from every static obstacle; $\phi(v) = -\mathrm{dist}(v, S)$
(stored at `models.py:289`).  Defaults: $\alpha = 1.0$, $\beta = 1.5$,
`wait_penalty = -1.0` (the latter is a code-only knob, not in the paper
formula; added to prevent permanent blockages in narrow aisles per the
inline comment at L272-275).

### 3.3 CRITICAL: humans treat agent-occupied cells as obstacles — **CONFIRMED**

**Code path**:

`simulator.py:1046-1054`:
```python
def _update_humans(self) -> None:
    """Humans treat agent positions as obstacles - they will not move into
    cells occupied by agents."""
    agent_positions: Set[Cell] = {a.pos for a in self.agents.values()}
    self.humans = self.human_model.step(self.env, self.humans, self.rng, agent_positions)
```

`models.py:70-83` (`_legal_successors`):
```python
def _legal_successors(env, current, blocked):
    successors = [current]  # WAIT is always legal
    for nb in neighbors(current):
        if env.is_free(nb) and nb not in blocked:
            successors.append(nb)
    return successors
```

In every per-model `step()`:
- `RandomWalkHumanModel.step` (`models.py:168`): `blocked = agent_positions if agent_positions is not None else set()`
- `AisleFollowerHumanModel.step` (`models.py:303`): same
- `AdversarialHumanModel.step` (`models.py:442`): same
- `MixedPopulationHumanModel.step` (`models.py:537-548`): dispatches to the per-type model, which receives the same `agent_positions`
- `ReplayHumanModel.step` (`models.py:584-608`): **IGNORES** `agent_positions` — replays a pre-recorded trajectory; legality is pre-validated at trajectory generation, not at runtime

**Synthetic confirmation** (RandomWalk with `beta_go=10.0`,
`beta_wait=-100.0`, `beta_turn=-100.0`, velocity=(0,1), agent
pre-claiming the only forward cell): **0 / 500 trials moved the human
into the agent's cell**.  Without the agent in `blocked`, the same
config produces forward motion almost every tick.

**Implication for $N_x$ (Definition-1 exogenous-attributable
violations)**: humans cannot collide with agents at the **vertex**
level — they will never share a cell with an agent at $t+1$.  They can
still create a **buffer overlap** (Manhattan distance $\le r_{\text{safe}}$
without sharing a cell), which is what $N_x$ counts.  So:

> $N_x$ measures "exogenous agents approached the safety buffer of an
> agent at $t+1$ despite the agent's decision-time action being
> non-violating per Definition 1", but it does **not** include
> agent-cell co-occupation events — those are blocked at the human
> step boundary.

This is the **"externals are not fully uncoordinated"** finding stated
in the audit brief.  In paper terms: the model is **vertex-coordinated
(humans yield), buffer-uncoordinated (humans do not know about r_safe)**.
Adjacent moves into the buffer are still possible and are precisely
what $N_x$ records.

The `ReplayHumanModel` is the only exception: it can re-enter agent
cells if its pre-recorded trajectory says so.  Its docstring
(`models.py:559-575`) makes the contract explicit ("legality is
enforced at generation time", not runtime), so a replay against a
fresh set of agent positions could in principle produce vertex
co-occupation.  This is a model-author responsibility, not a
simulator bug.

### 3.4 Adversarial / MixedPopulation / Replay — step() contracts

| Model | Signature matches `HumanModel.step` | Uses `agent_positions`? | Behaviour |
|---|:--:|:--:|---|
| `AdversarialHumanModel` | ✓ | ✓ (as `blocked` AND for agent-distance field) | $g_t(u) = \lambda b(u) - (1-\lambda) \min_i d(u, x_i(t))$ via softmax; defaults $\gamma=2.0, \lambda=0.5$ |
| `MixedPopulationHumanModel` | ✓ | ✓ (forwarded to per-type model) | Per-human type assignment from categorical weights, fixed for the episode |
| `ReplayHumanModel` | ✓ | ✗ (intentional) | Deterministic trajectory replay; runtime agent positions ignored |

All five models import cleanly.  Step contracts coherent.

---

## 4. Safety inflation — **PASS**

`humans/safety.py:21-74` (`inflate_cells`).

Formula: $B_{r_{\text{safe}}}(X) = \bigcup_{c \in X} \{ d \in V : \lVert d - c\rVert_1 \le r_{\text{safe}}\}$.

| Case | Code path | Behaviour | Synthetic check |
|---|---|---|---|
| $r_{\text{safe}} = 0$ | L42-44 | Returns the seed cells, filtered for `env.is_free`.  Empty buffer past the human's own cell | `inflate_cells({(2,2)}, 0, env)` → `{(2,2)}` ✓ |
| $r_{\text{safe}} = 1$ | L46-72 | Manhattan ball of size 5 (human + 4 neighbours) | `inflate_cells({(2,2)}, 1, env)` → `{(2,2), (1,2), (3,2), (2,1), (2,3)}` ✓ |
| Wall inside buffer | L70-72 | Excluded (`if env.is_free(cell)`) | With wall at (2,3): result excludes (2,3) ✓ |
| Off-grid cells | L57-66 | Excluded (bounds check) | implicit in the synthetic check |

**$r_{\text{safe}} < r_{\text{fov}}$ enforcement**: NOT enforced.  The
constraint is documented in `types.py:447-449` and
`simulator.py:1148-1151` as the precondition for the Theorem-1
construction-level invariant (Algorithm-2 trajectories produce zero
agent-attributable Definition-1 violations when
`hard_safety` is on AND `r_safe < r_fov`), but no assert / config
validator raises if a user sets `r_safe >= r_fov`.  At the SimConfig
defaults `r_fov = 4`, `r_safe = 1` the precondition trivially holds.

---

## Summary

| Area | Verdict | Evidence |
|---|:--:|---|
| §1.1 H/R coupling | **PASS (defaults)** + documented gap | Defaults `(20, 10)`; constructor accepts arbitrary `(10, 7)` without warning |
| §1.2 Prefix commitment | **PASS** | Replan reads `sim_state.agents` (realized state); `_reanchor_last_good` clips to `offset = cur_step - start_step`, never earlier |
| §1.3 $\eta_w$ trigger | **PASS** | `_eta_w_trigger` consults `last_action_was_safe_wait` flag at L161-166; defaults `eta_w=0.20`, `replan_min_gap=3` |
| §2.1 Allocator module reconciliation | **PASS** | Live: `task_allocator/task_allocator.py` (5 classes incl. CongestionAvoidance); dead: `global_tier/task_allocator.py` (orphan in audit 00) |
| §2.2 Narrowness $\nu(c) = 4/\max(1,\deg(c))$ | **PASS** | Synthetic: interior=1.0, corner=2.0, edge=4/3 |
| §2.2 Cost matrix $C[i,j] = D[i,j] + \lambda \omega$ | **PASS** | $\lambda=0.5$, $R_{\max}=5$ defaults; iterative refinement converged in 2 rounds on synthetic cross-paths |
| §2.3 Greedy / Hungarian / Auction | **PASS** | Auction $\epsilon=0.01$ default confirmed |
| §3.1 RandomWalk Boltzmann | **PASS** | Three log-weights `(β_go=2, β_wait=-1, β_turn=0)`; numerically-stable softmax |
| §3.2 AisleFollower $\phi$ field | **PASS** | $\phi(v) = -\mathrm{dist}(v, S)$ via multi-source BFS |
| §3.3 Humans-block-on-agent-cells | **CONFIRMED** | 0/500 trials of forced-forward random walk entered agent cell |
| §3.4 Adversarial / Mixed / Replay step contracts | **PASS** | Signatures match; Replay intentionally ignores `agent_positions` |
| §4 Safety inflation $r=0, r=1$, walls excluded | **PASS** | Synthetic checks cover all three |
| §4 $r_{\text{safe}} < r_{\text{fov}}$ enforcement | **DOCUMENTED gap** | Not enforced in code; documented as Theorem-1 precondition |

---

## BUGS FOUND

None.

## GAPS (no fix applied; recorded)

1. **`RollingHorizonPlanner` does not enforce $R = \lfloor H/2 \rfloor$.**
   The paper states the coupling; the code treats $H$ and $R$ as
   independent.  Recommended (not applied): add a one-line warning
   when `replan_every != horizon // 2`.

2. **`r_safe < r_fov` is documented but not enforced.**  A user-supplied
   SimConfig with `safety_radius >= fov_radius` would silently violate
   the Theorem-1 precondition.  Recommended (not applied): add a
   one-line assert in `SimConfig.__post_init__` or at simulator
   construction.

3. **Dead module `global_tier/task_allocator.py`.**  Carries a
   `PersistentTaskAllocator` not present in the live module; nothing
   imports it.  Already flagged in audit 00 orphan list; recommended
   (not applied): delete or move to an `_archive/` subtree.

## CLARIFICATIONS (non-bugs that affect interpretation of paper metrics)

1. **Externals are not fully uncoordinated**: agent positions are passed
   to every human model's `step()` as a `blocked` set.  Vertex-level
   coordination (humans yield on agent cells) is enforced; only
   buffer-level coordination is absent (humans don't know $r_{\text{safe}}$).
   This is what $N_x$ actually measures.  The paper's phrasing
   "externals are not coordinated with the planner" should be read as
   "externals are not coordinated with the **planner's path
   reservations or safety buffers**", not as "externals can collide
   with agents at the vertex level" — the latter never happens in this
   simulator (with the documented exception of `ReplayHumanModel`).
