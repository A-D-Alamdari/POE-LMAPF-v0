# Proposed Approach — POE-LMAPF

> *Footnote on terminology.*  The paper text and this document refer to
> the dynamic non-controlled agents in the environment as **exogenous
> agents**.  The codebase historically used **humans** for the same
> entity (e.g. `HumanState`, `humans/` package, ``human_model`` config
> field) and we kept those names for backward compatibility with the
> SoCS2026 submission.  The two terms are interchangeable.

## A. Problem Formulation

We address **Partially Observable Exogenous-agent Lifelong Multi-Agent
Path Finding (POE-LMAPF)**, defined as follows.

**Definition 1 (POE-LMAPF).** Given:

- A 4-connected grid graph $G = (V, E)$ representing the environment.
- A set of $k$ controlled agents $A = \{a_1, \ldots, a_k\}$ with positions
  $s_i(t) \in V$.
- A set of $m$ exogenous agents $X(t) = \{h_1(t), \ldots, h_m(t)\}$ with
  unpredictable but bounded-step trajectories.
- A continuous lifelong stream of pickup-delivery tasks $T$ released
  online.
- A safety radius $r_{\mathit{safe}}$ defining a buffer around each
  exogenous agent.
- An FoV radius $r_{\mathit{fov}}$ defining each agent's local
  observation set.

Find a sequence of joint actions that maximises task throughput while
satisfying the buffer-aware safety constraint:

$$
s_i(t+1) \notin B_{r_{\mathit{safe}}}\!\bigl(X^{\Phi_i}_t\bigr)
\quad
\forall i, \forall t,
$$

where $X^{\Phi_i}_t = \{ h \in X(t) : \ell_1(s_i(t), h_{\mathrm{pos}}) \le r_{\mathit{fov}} \}$
is the set of exogenous agents observed by $a_i$ at decision time $t$,
and $B_{r}(\cdot)$ is the union of Manhattan balls of radius $r$
truncated to free cells.

The decision-time observation set $X^{\Phi_i}_t$ is the basis for the
**agent-attributable / exogenous-attributable** classification of
violations introduced in §F below.

---

## B. Two-Tier Hierarchical Architecture

We decompose planning into a centralised long-horizon Tier-1 and a
per-agent reactive Tier-2:

| Tier               | Scope         | Cadence       | Responsibility                           |
|--------------------|---------------|---------------|------------------------------------------|
| **Tier-1 (Global)**| Centralised   | Every $R$ steps | Task allocation + collision-free MAPF |
| **Tier-2 (Local)** | Per-agent     | Every step    | Buffer-aware safety + agent-agent conflict resolution |

The global tier optimises multi-agent coordination on the static map
without modelling exogenous-agent behaviour; the local tier provides
real-time reactivity to dynamic obstacles.

---

## C. Tier-1: Rolling Horizon Global Planning  (paper Algorithm 1)

The global planner runs a **rolling horizon** of $H$ time-steps and
re-plans every $R$ steps.  At each replan epoch:

1. **Collect open tasks** released since the last epoch.
2. **Allocate tasks** to idle agents (greedy nearest-by-Manhattan).
3. **Solve MAPF** on the static map for horizon $H$.
4. **Distribute paths** to per-agent controllers.

### Replan triggers

- **Periodic**: $t \bmod R = 0$.
- **Major deviation**: a controller signals it cannot follow its plan.
- **Exhaustion**: too many agents have stale plans (default 40 % of
  agents) — a coordinated plan has effectively collapsed.
- **Safety-Wait fraction $\eta_w$ (paper §4.4)**: when the fraction of
  agents committing **Safe Wait** the previous tick exceeds
  $\eta_w = 0.20$, fire an off-period replan, subject to a
  ``replan_min_gap`` anti-thrash guard (default 3 ticks).  This is the
  emergency trigger described in the paper.

### Task allocation with commitment persistence

Once a task $\tau$ is assigned to agent $a_i$ the assignment is locked
unless

1. the task is completed,
2. the commitment horizon $K_c$ expires, or
3. the actual distance exceeds $\alpha \cdot d_0$ (delay threshold).

This converts the allocator from a memoryless policy into a hysteresis
controller, suppressing assignment thrashing.

### Global MAPF solvers

Six solvers are wired through ``GlobalPlannerFactory``:

| Solver       | Factory string     | Class                            |
|--------------|--------------------|----------------------------------|
| CBSH2-RTC    | ``cbsh2``          | C++ binary wrapper               |
| **LaCAM** (paper default) | ``lacam_official`` | Kei18/lacam, Okumura 2023 AAAI       |
| LaCAM\*      | ``lacam3``         | Kei18/lacam3, Okumura 2024 — anytime |
| MAPF-LNS2    | ``lns2``           | C++ binary wrapper               |
| PBS          | ``pbs``            | C++ binary wrapper               |
| PIBT2        | ``pibt2``          | C++ binary wrapper               |

Per-call wall-clock budget is set by ``SimConfig.solver_timeout_s``
(paper default $10.0$ s).  See ``docs/SOLVER_STATUS.md`` for the
empirical CI status.

---

## D. Tier-2: Decentralised Local Execution  (paper Algorithm 2)

Each agent runs a **Sense → Plan → Resolve** loop every tick.

### 1) Sense — local observation

Agent $a_i$ at $s_i(t)$ builds

$$
\Phi_i(t) = \bigl(X^{\Phi_i}_t,\; A^{\Phi_i}_t,\; D(t)_{\mathit{ext}}\bigr),
$$

where $X^{\Phi_i}_t$ are exogenous agents within $r_{\mathit{fov}}$,
$A^{\Phi_i}_t$ are visible peer agents, and $D(t)_{\mathit{ext}}$
collects static obstacles, visible-agent occupancy, and decided-next
positions of agents that already committed this tick.

### 2) Plan — buffer-aware safe action selection

The forbidden set used by every action-choice path is

$$
F = B_{r_{\mathit{safe}}}\!\bigl(X^{\Phi_i}_t\bigr) \cup D(t)_{\mathit{ext}}.
$$

The controller picks the next cell $p_i^\ast(t+1)$ from the global
plan if

- $p_i^\ast \neq \emptyset$,
- $p_i^\ast \notin F$,
- $p_i^\ast$ is not stale.

Otherwise it invokes a **local A\*** with $F$ in the blocked set, an
expansion cap $N_{\max} = 10\,000$ (paper $N_{\max} = 500$ is a
safety-net upper bound; the implementation uses a larger ceiling), and
optional path-aligned guidance.  Hard-safety mode treats $F$ as
impassable; soft-safety treats it as a high-cost cell.

### 3) Resolve — agent-agent conflict resolution

If another agent has already committed $p_i^\ast$ (vertex conflict) or
the swap leads to an edge conflict, the resolver runs.  Two
implementations:

- **Priority Rules** (decentralised, no comms): tuple
  $\rho_i = (-d_i + \beta\,\mathbf{1}[w_i > w^\ast],\; w_i,\; -i)$ where
  $d_i = \ell_1(s_i, g_i)$, $w_i$ is wait-streak counter, $w^\ast = 10$
  starvation threshold, $\beta = 50$ urgency boost; lexicographic max
  wins.  Loser's fallback respects $F$ (Theorem 1; see §F).
- **Token Passing** (comms): same priority tuple sans the $\beta$
  boost, plus fairness rotation after $K_{\mathit{fair}} = 5$
  consecutive wins on the same cell.

The **loser's fallback** is critical: it tries a 1-hop side-step
filtered against $F$, then a multi-step local A\* with
``blocked = observation.blocked ∪ F ∪ winner-claimed cell``.  If both
return $\emptyset$ it commits **Safe Wait** at $s_i(t)$ — which is
guaranteed outside $F$ by upstream invariants.  Without the $F$
filter on the fallback, Theorem 1 fails empirically.

---

## E. Decision-Table Semantics

Per-agent decisions are processed in sorted-`agent_id` order within
the tick.  After computing its action, agent $a_i$ writes its intended
$s_i(t+1)$ to the simulator's decision table $D(t)$.  Agent $a_{i+1}$'s
``detect_imminent_conflict`` reads $D(t)$, so vertex- and
edge-conflict detection is up-to-date for the still-undeciding agents.
Tests in ``tests/test_decision_table.py`` pin this property.

---

## F. Theorem 1 (Conditional Safety) and Violation Attribution

Because exogenous agents are partially observable, no algorithm can
guarantee zero buffer violations in general.  We prove instead that
**no executed action is agent-attributable**.

Define a violation pair $(a_i, h)$ at time $t+1$ as
$\ell_1(s_i(t+1), h_{\mathrm{pos\;at\;}t}) \le r_{\mathit{safe}}$.

- The pair is **agent-attributable** iff
  $s_i(t+1) \neq s_i(t)$ AND
  there exists $h' \in X^{\Phi_i}_t$ with
  $\ell_1(s_i(t+1), h'_{\mathrm{pos\;at\;}t}) \le r_{\mathit{safe}}$.
  (The agent moved into the buffer of an exogenous agent it had
  already observed at decision time.)
- Otherwise the pair is **exogenous-attributable**.

**Theorem 1 (Conditional Safety).** Under Algorithm 2 and the
F-respecting loser fallback in the resolver, no executed action is
agent-attributable to a buffer violation; equivalently, the
``violations_def1_agent_attributable`` counter is exactly zero at
all times.

This is a **construction-level invariant**, not an empirical
hypothesis.  Five-line proof, using the simulator's tick ordering
(step 4 = humans move, step 5 = agents sense + decide, step 7 =
agents execute):

1. At decision time $t$ (step 5), agent $i$ has observed every
   exogenous agent within $\ell_1$ distance $r_{\mathit{fov}}$ of
   $s_i(t)$.  The observed set $X^{\Phi_i}_t$ uses pre-step-4
   positions $h'_{\mathrm{pos\;at\;}t}$ (the snapshot the simulator
   takes immediately before $\_$update_humans).
2. Because $r_{\mathit{safe}} < r_{\mathit{fov}}$ (paper §5.1
   default) and agent moves are Manhattan-1, every cell whose
   $r_{\mathit{safe}}$-buffer the agent could enter in one step
   from $s_i(t)$ lies within $\ell_1$ distance
   $r_{\mathit{safe}} + 1 \le r_{\mathit{fov}}$ of $s_i(t)$.
3. The local controller's forbidden set $F$ is exactly the union
   of $r_{\mathit{safe}}$-buffers around every $h' \in
   X^{\Phi_i}_t$.  Step 2 gives $F \supseteq$ every reachable
   buffer cell.
4. With $\mathit{hard\_safety}=\mathit{true}$ (Algorithm 2) the
   controller refuses every cell in $F$ and commits Safe Wait if
   no other action remains; the resolver's loser fallback also
   respects $F$.
5. Therefore the executed cell $s_i(t+1)$ is either $s_i(t)$
   (Safe Wait, clause (b) of Definition 1 fails on moved) or a
   cell outside $F$ (and therefore outside every buffer of any
   $h' \in X^{\Phi_i}_t$, so clause (b) fails on
   $\ell_1(s_i(t+1), h'_{\mathrm{pos\;at\;}t}) > r_{\mathit{safe}}$).
   No (a_i, h') pair satisfies Definition 1 clauses (a) and (b)
   simultaneously, so $\mathit{violations\_def1\_agent\_attributable} = 0$.

The empirical witness counter is locked in by

- ``tests/test_safety_classification.py`` (WAIT-counterfactual diagnostic);
- ``tests/test_def1_violation_classifier.py`` (Definition-1 classifier);
- ``tests/test_theorem1_resolver.py`` (loser fallback respects $F$);
- ``tests/test_theorem1_stress.py`` (200-step end-to-end).

A note on the WAIT-counterfactual diagnostic
``violations_agent_attributable`` (P5 follow-up): that counter
implements a different rule -- no FOV gate, post-step-4 human
positions, single clause "WAIT would have been safe vs this
specific $h$".  It is NOT a Theorem 1 invariant and CAN be nonzero
on a healthy run (FOV-blind moves into emergent buffer overlaps).
Do not cite it as evidence for or against Theorem 1.  See
``docs/REVISION_AUDIT.md`` §13 for the migration note and
``simulator.py::_detect_collisions_and_near_misses`` for the
side-by-side classifier code.

---

## G. System Parameters (paper §5.1 defaults)

| Parameter                     | Symbol                  | Default | SimConfig field         |
|-------------------------------|-------------------------|---------|-------------------------|
| Planning horizon              | $H$                     | 20      | ``horizon``             |
| Replan interval               | $R$                     | 10      | ``replan_every``        |
| FoV radius                    | $r_{\mathit{fov}}$      | 4       | ``fov_radius``          |
| Safety radius                 | $r_{\mathit{safe}}$     | 1       | ``safety_radius``       |
| Lifelong run length           | —                       | 2000    | ``steps``               |
| Per-call solver budget        | —                       | 10.0 s  | ``solver_timeout_s``    |
| Eta_w trigger threshold       | $\eta_w$                | 0.20    | ``eta_w``               |
| Replan-thrash guard           | —                       | 3       | ``replan_min_gap``      |
| Local A\* expansion cap       | $N_{\max}$              | 10 000  | ``AStarLocalPlanner.MAX_EXPANSIONS`` (paper bound: 500) |
| Starvation threshold          | $w^\ast$                | 10      | ``PriorityRulesResolver.starvation_threshold`` |
| Urgency boost                 | $\beta$                 | 50      | ``PriorityRulesResolver.boost`` |
| Token-rotation period         | $K_{\mathit{fair}}$     | 5       | ``TokenPassingResolver.fairness_k`` |

> **Note on $N_{\max}$.**  The paper bounds the local A\* search at
> 500 expansions.  The shipped value is 10 000 because our
> 64×64 / 161×63 / 170×84 evaluation maps occasionally need more
> expansions for genuinely long detours; behaviour is identical when
> the search terminates naturally (under either bound) and Theorem 1
> still holds when the cap fires (the agent commits Safe Wait).
> See ``docs/PAPER_TO_CODE_MAP.md``.

---

## H. End-to-End Algorithm (paper Algorithm 2)

```
Input: env G, agents A, exogenous-agent dynamics, lifelong task stream T
Output: continuous task execution with conditional safety

for each tick t do
    # Tier-1 (paper Algorithm 1)
    if t mod R = 0  or  any emergency trigger fires:
        tasks       ← collect_open_tasks(T)
        assignments ← allocate(A, tasks)                         # greedy + commitment
        plans       ← solve_MAPF(G, A, assignments, H)           # LaCAM*  (10 s budget)
        distribute(plans)

    # exogenous dynamics (sampled by chosen motion model)
    X(t) ← step_exogenous(X(t-1))

    # Tier-2 (paper Algorithm 2) — sequential within tick
    for each a_i in sorted(A) do
        Φ_i ← sense(a_i, r_fov)
        F   ← inflate(X^{Φ_i}, r_safe) ∪ D(t)_extended
        p*  ← global_plan_next(a_i)
        if p* = ∅ or p* ∈ F or stale(p*):
            p* ← local_A*(s_i, g_i, blocked = F ∪ obs.blocked)
            if p* = ∅:
                commit Safe Wait
                continue
        if conflict(a_i, p*) and a_i loses by ρ:
            p* ← side_step(s_i, F)  or  fallback_A*(s_i, g_i, F ∪ winner-claim)
            if no F-respecting move: commit Safe Wait
        execute(a_i, p*); D(t)[i] ← p*
```

---

## I. Why Two Tiers?

| Architecture        | Limitation                                                  |
|---------------------|-------------------------------------------------------------|
| Global-only (RHCR)  | Cannot react to unobserved exogenous-agent encroachment.    |
| Local-only (PIBTOnly) | No coordination; deadlocks and head-on contention.         |
| Replan-on-conflict  | Planning latency dominates; thrashes under exogenous noise. |

The two-tier design combines centralised optimisation
(coordination, collision-free MAPF on the static map) with
decentralised reactivity ($F$-respecting local repair, Theorem 1
guarantees at the executed-action level).

> "We use a greedy nearest-task allocator with commitment persistence:
> assignments remain fixed for a finite horizon and are only revised
> when infeasible or excessively delayed, preventing reassignment
> oscillations that could confound execution-level evaluation."
