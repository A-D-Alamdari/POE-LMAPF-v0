# Conflict Resolution

Agent-agent conflict resolution strategies for the local tier.

## Naming (paper §4.3)

Canonical class / config names:

| Canonical (paper §4.3) | Class | `communication_mode` value | Legacy alias |
| --- | --- | --- | --- |
| Wait-Based | `WaitBasedResolver` | `"wait_based"` | `PriorityRulesResolver`, `"priority"` |
| Token-Based | `TokenBasedResolver` | `"token_based"` | `TokenPassingResolver`, `"token"` |

Old names are retained as module-level aliases (in `priority_rules.py`
and `token_passing.py`) and as factory-dispatch aliases (in
`simulator.py`) so existing imports, YAML configs, and archived run
manifests continue to work unchanged.  New code should use the
canonical names.


## Theorem 1 invariant (paper §4.5)

When agent $a_i$ loses a vertex- or edge-conflict, its fallback path
**must respect the forbidden set**

$$
F = B_{r_{\mathit{safe}}}\!\bigl(X^{\Phi_i}_t\bigr) \cup D(t)_{\mathit{ext}}.
$$

The controller plumbs $F$ (and a local-planner reference) into the
resolver via the ``forbidden`` and ``local_planner`` kwargs.  Concrete
resolvers (``PriorityRulesResolver``, ``TokenPassingResolver``)
filter the 1-hop side-step against $F$ and, on failure, run a local
A\* with ``blocked = observation.blocked ∪ F ∪ {winner-claimed
cell}``.  If A\* returns no path, the resolver commits **Safe Wait** at
$s_i(t)$ (which the upstream controller invariant guarantees lies
outside $F$).  Without the $F$ filter on this fallback, Theorem 1
fails empirically — the loser would side-step into a buffer cell.
The contract is locked in by ``tests/test_theorem1_resolver.py``.

> *Terminology.*  The paper text refers to dynamic non-controlled
> entities as **exogenous agents**.  This file uses ``human``
> (matching the codebase) for the same concept.

## Priority tuple (paper-form)

$$
\rho_i \;=\; \bigl(\, -d_i + \beta\,\mathbf{1}\!\left[w_i > w^\ast\right],\;\; w_i,\;\; -i\,\bigr)
$$

with $d_i = \ell_1(s_i, g_i)$, $w_i$ the wait-streak counter,
$w^\ast = 10$ the starvation threshold, $\beta = 50$ the urgency
boost, and $i$ the controlled-agent ID.  The lexicographic maximum
wins; ties favour the lower $i$.  Implementation:
``priority_rules.py::PriorityRulesResolver._priority``.
``TokenBasedResolver`` instead uses the paper's $(\tau, -d, w, -i)$
tuple, where $\tau$ is the per-(agent, cell) token count (0 tokens ⇒
$\tau = +\infty$, an automatic win); see
``token_passing.py::TokenBasedResolver`` and the re-implementation note
in that file's section below.

## Overview

When two agents want to occupy the same cell, a conflict resolver
determines which agent proceeds and which yields.  The loser's
fallback respects $F$ (Theorem 1 invariant above).

```
┌───────────────────────────────────────────────────────────┐
│                    CONFLICT RESOLUTION                    │
├───────────────────────────────────────────────────────────┤
│                                                           │
│    Agent A wants cell X    Agent B wants cell X           │
│           │                       │                       │
│           └───────────┬───────────┘                       │
│                       ▼                                   │
│              ┌─────────────────┐                          │
│              │    RESOLVER     │                          │
│              │  (Token/PIBT/   │                          │
│              │   Priority)     │                          │
│              └─────────────────┘                          │
│                       │                                   │
│           ┌───────────┴───────────┐                       │
│           ▼                       ▼                       │
│    Agent A: PROCEED        Agent B: WAIT/YIELD            │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

## Files

| File                | Description                       |
|---------------------|-----------------------------------|
| `base.py`           | Conflict detection and base class |
| `token_passing.py`  | Communication-based resolver      |
| `priority_rules.py` | Communication-free resolver       |
| `pibt.py`           | Push-based resolver               |

---

## Conflict Types

### Vertex Conflict

Two agents want to be at the same cell at the same timestep.

```
Time t:     Agent A at (2,2)    Agent B at (2,3)
Time t+1:   Agent A wants (2,3) Agent B wants (2,3)  ← CONFLICT
```

### Edge Conflict (Swap)

Two agents want to swap positions.

```
Time t:     Agent A at (2,2)    Agent B at (2,3)
Time t+1:   Agent A wants (2,3) Agent B wants (2,2)  ← SWAP CONFLICT
```

---

## base.py - Conflict Detection

### detect_imminent_conflict Function

```python
def detect_imminent_conflict(
        agent_id: int,
        desired_cell: Cell,
        sim_state: SimStateView
) -> Optional[ImminentConflict]:
    """
    Detect conflicts for the next step only.

    Checks:
        1. Vertex conflict: another agent at desired_cell
        2. Edge conflict: agents swapping positions
        3. Decided positions: cells already claimed this timestep

    Returns:
        ImminentConflict with conflict details, or None
    """
```

### ImminentConflict Dataclass

```python
@dataclass(frozen=True)
class ImminentConflict:
    kind: str  # "vertex" or "edge"
    other_agent_id: int  # Conflicting agent
    cell: Optional[Cell]  # For vertex conflicts
    edge: Optional[Tuple]  # For edge conflicts
```

---

## token_passing.py - Token-Based Resolver

Communication-based conflict resolution via per-(agent, cell) token counts
(paper §4.3 "Token-Based").  Canonical class `TokenBasedResolver`;
`TokenPassingResolver` is retained as a back-compat alias.

> **Re-implemented in resume-prompt-6.**  The previous version used a
> single-owner token with K-conflict rotation and *no* τ term in its
> priority tuple — the divergence from the paper characterised in
> audit 03 §2.  Per Decision 2b the paper is defended, so the resolver now
> implements the priority tuple the paper claims, `(τ, -d, w)`, with a
> per-(agent, cell) token count `τ` as the primary key.  The `fairness_k`
> constructor parameter is retained for backward compatibility but is
> **deprecated and inert** (it warns and does nothing).

### Mechanism

```
Per-(agent, cell) token counts, lazily endowed with 5 on first contention.

Priority tuple (higher wins, lexicographic):  (τ, -d, w, -id)
    τ  = +∞ if token_count == 0 else token_count   (0 tokens => auto-win)
    d  = Manhattan distance from current pos to goal
    w  = consecutive wait count
    id = agent id

Win-loss transfer, one per contention:
    winner's count at the contested cell -= 1   (floored at 0)
    every loser's count at the cell      += 1   (never capped)
    winner pays 1 total regardless of the number of losers
        (per-(winner, loser) pair conservation; not whole-contention
         conservation when there is more than one loser)

State scope: token counts live for the lifetime of one resolver instance
(one Simulator run); the simulator builds a fresh resolver per run.
```

### Public API

`resolve(agent_id, desired_cell, sim_state, observation, rng=None,
forbidden=None, local_planner=None) -> StepAction` is the live per-agent
contract (unchanged shape; consumed by `AgentController`).  Internally it
runs the contested cell's contention exactly once per tick and maps the
outcome to an action.  The contention primitive `contend(cell, contenders,
sim_state) -> winner_id` (pick winner by priority + apply the token
transfer) is exposed for direct testing.

### Theorem 1 / modularity

When the calling agent loses, its fallback (1-hop side-step, then optional
local A*, then Safe-WAIT) filters against the forbidden set `F` so no
executed action enters `F`.  The resolver reads `forbidden` by membership
only and never mutates any caller-supplied collection (audit 03 §3); the
sole mutable state is the internal `_tokens` dict.

### Usage

```python
from ha_lmapf.local_tier.conflict_resolution import TokenBasedResolver

resolver = TokenBasedResolver()
action = resolver.resolve(agent_id, desired_cell, sim_state, observation)
```

---

## priority_rules.py - Priority Rules Resolver

Communication-free deterministic resolution.

### PriorityRulesResolver Class

```python
class PriorityRulesResolver(ConflictResolver):
    """
    Deterministic priority-based resolution.
    No communication required - same rules on all agents.

    Priority Tuple (higher = higher priority):
        1. urgency = -distance_to_goal, optionally boosted by `boost`
           when agent's consecutive wait_steps exceed starvation_threshold
        2. wait_steps: current consecutive wait streak since last move
        3. -agent_id: lower agent ID wins ties

    Parameters:
        starvation_threshold: int - Consecutive wait steps before boost (default: 10)
        boost: int - Urgency boost for starving agents (default: 50)
    """

    def resolve(
            self,
            agent_id: int,
            desired_cell: Cell,
            sim_state: SimStateView,
            observation: Observation,
            rng=None
    ) -> StepAction:
        """
        Resolve conflict using priority rules.

        Winner: agent with higher priority tuple (uses max())
        Loser: yields (WAIT or side-step)
        """
```

### Priority Calculation

```python
def priority_tuple(agent):
    dist = manhattan(agent.pos, agent.goal)
    urgency = -dist  # negative distance: closer goal → less negative → higher
    if agent.wait_steps > starvation_threshold:
        urgency += boost  # starvation boost for currently-blocked agents
    return (urgency, agent.wait_steps, -agent.agent_id)

# Higher tuple = higher priority (resolver uses max())
# Example: (-3, 8, -1) beats (-5, 2, 0) because -3 > -5
# wait_steps is a consecutive-wait streak reset on each successful move
```

### Usage

```python
from ha_lmapf.local_tier.conflict_resolution import PriorityRulesResolver

resolver = PriorityRulesResolver(starvation_threshold=10, boost=50)
action = resolver.resolve(agent_id, desired_cell, sim_state, observation)
```

---

## pibt.py - PIBT Resolver

Priority Inheritance with Backtracking (simplified).

### PIBTResolver Class

```python
class PIBTResolver(ConflictResolver):
    """
    PIBT-style push-based conflict resolution.

    Mechanism:
        - Higher priority agent can "push" lower priority agent
        - Pushed agent must move to a feasible cell
        - If push not feasible, pusher waits

    Parameters:
        allow_side_step: bool - Allow side-stepping when blocked
    """

    def resolve(
            self,
            agent_id: int,
            desired_cell: Cell,
            sim_state: SimStateView,
            observation: Observation,
            rng=None
    ) -> StepAction:
        """
        Resolve conflict using push mechanism.

        Process:
            1. Detect conflict with other agent
            2. If higher priority: attempt to push
            3. If push feasible: proceed
            4. If push not feasible: wait or side-step
        """
```

### Push Feasibility

```
Push is feasible if:
    - Pushed agent has adjacent free cell to move to
    - Pushed agent's movement doesn't cause new conflict
```

### Usage

```python
from ha_lmapf.local_tier.conflict_resolution import PIBTResolver

resolver = PIBTResolver(allow_side_step=True)
action = resolver.resolve(agent_id, desired_cell, sim_state, observation)
```

---

## Comparison

| Resolver       | Communication | Complexity | Fairness         | Use Case            |
|----------------|---------------|------------|------------------|---------------------|
| Token Passing  | Required      | O(1)       | Rotation         | Coordinated systems |
| Priority Rules | None          | O(1)       | Starvation boost | Independent agents  |
| PIBT           | None          | O(n)       | Implicit         | Dense environments  |

---

## Configuration

```yaml
# In config file
communication_mode: "token_based"  # Options: "token_based" / "wait_based"
                                   # (legacy "token" / "priority" accepted)

# Token-based: no tunable parameters (per-(agent, cell) token counts are
# internal; the endowment is fixed at 5).  The legacy `fairness_k` knob is
# deprecated and ignored.

# Priority rules specific
starvation_threshold: 10
boost: 50
```

> **Note:** `pibt` is not a valid `communication_mode` in `SimConfig`. The `PIBTResolver`
> exists in `pibt.py` but must be wired manually; it is not selectable via config.

---

## Sequential Decision-Making

To prevent race conditions during sequential agent decisions:

```python
# In simulator
for agent_id in sorted(agents.keys()):
    action = controllers[agent_id].decide_action(sim_state, obs)
    next_pos = compute_next_position(agents[agent_id].pos, action)
    decided_next_positions[agent_id] = next_pos  # Track for later agents
```

The `decided_next_positions` dict is checked by conflict detection to avoid collisions with already-committed moves.

---

## Related Modules

- [Local Tier](../README_LOCAL_TIER.md) - Uses resolvers in agent controller
- [Core](../../core/README_CORE.md) - Protocol definitions