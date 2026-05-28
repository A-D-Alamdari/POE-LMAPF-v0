# `physics_revert_wait_steps` reachability audit

## Question

`physics_revert_wait_steps` is incremented in step 7a of
`Simulator.step_once()`, the iterative vertex/edge-swap conflict
resolver that runs *after* the per-agent controllers have chosen
actions.  During P17 work it was claimed that the decentralised
conflict resolver (`AgentController.decide_action` -> Tier-2
`BaseConflictResolver`) catches every imminent vertex/edge conflict
*at decision time* via `detect_imminent_conflict`, so step 7a would
never fire in practice and `physics_revert_wait_steps` would be
dead instrumentation.

This audit answers: can `physics_revert_wait_steps` be nonzero from
`Simulator.run()` in normal operation?

## Verdict: YES — reachable in normal operation

## Mechanism

Step 6 (Execution Delay Injection,
`simulator.py:1575`-`1600`) runs **after** step 5b (decentralised
decision making).  It overrides a previously-chosen MOVE with a
forced WAIT for any agent that draws into a delay.  The conflict
resolver, which ran in step 5b, did **not** see that override and
could not anticipate it.  Concrete pattern:

  - Step 5b: agent A decides MOVE A->B.  The resolver sees B as
    free for next step (because agent B was decided to move
    B->C).
  - Step 5b: agent B decides MOVE B->C.
  - Step 6: a delay fires on agent B.  Its action is forced to
    WAIT; `last_action_was_delay_wait = True`.  Agent B will stay
    at B.
  - Step 7a: agent A still has `intended[A] = B`, but agent B is
    pre-claimed at B (stationary).  Step 7a reverts agent A's
    action to WAIT and sets
    `last_action_was_physics_revert_wait = True`.
  - Step 7c: the post-physics wait-bucketing block adds the tick
    to `physics_revert_wait_steps`.

## Empirical evidence

`scripts/diagnostics/probe_physics_revert.py` runs short episodes
(5x5 open map, 4 agents, 50 steps, `execution_delay_prob = 0.3`,
`execution_delay_steps = 1`, seeds 0-11).  Per-seed output:

```
seed= 0  total_wait= 126  safe=   5  yield=  37  physics_revert=   4  delay=  80  inv_ok=True
seed= 1  total_wait= 129  safe=   5  yield=  32  physics_revert=   4  delay=  88  inv_ok=True
seed= 2  total_wait= 160  safe=  22  yield=  33  physics_revert=   6  delay=  99  inv_ok=True
seed= 3  total_wait= 143  safe=  25  yield=  29  physics_revert=   6  delay=  83  inv_ok=True
seed= 4  total_wait= 129  safe=  10  yield=  32  physics_revert=   9  delay=  78  inv_ok=True
seed= 5  total_wait= 149  safe=  11  yield=  43  physics_revert=   5  delay=  90  inv_ok=True
seed= 6  total_wait= 232  safe=  95  yield=  47  physics_revert=   0  delay=  90  inv_ok=True
seed= 7  total_wait= 125  safe=   8  yield=  28  physics_revert=   3  delay=  86  inv_ok=True
seed= 8  total_wait= 147  safe=  15  yield=  28  physics_revert=  11  delay=  93  inv_ok=True
seed= 9  total_wait= 120  safe=   8  yield=  28  physics_revert=   6  delay=  78  inv_ok=True
seed=10  total_wait= 139  safe=  11  yield=  32  physics_revert=   2  delay=  94  inv_ok=True
seed=11  total_wait= 158  safe=  22  yield=  26  physics_revert=   9  delay= 101  inv_ok=True
```

11 of 12 seeds produced `physics_revert > 0` (range 2..11 per
episode).  The four-bucket invariant
`total_wait == safe + yield + physics_revert + delay`
held on every seed (`inv_ok=True`).

The single zero seed (seed 6) is the seed with the highest
`safe_wait` count (95 out of 232): the run was dominated by
safety waits in front of humans, so few agents reached the
decision-then-delay-then-physics-revert path.

## Test implication

`tests/test_paper_metric_invariants.py::test_wait_fraction_includes_physics_reverts`
asserts `physics_revert_wait_steps > 0` against `Simulator.run()`
output (the public path) -- driven by `execution_delay_prob = 0.5`,
seed 8 (the highest physics_revert count in the probe above).
The test does NOT call step 7a or the post-physics bucketing block
directly; the metric value comes from a complete public run.

If a future edit removes the `add_physics_revert_wait_step(1)`
call at `simulator.py:1690` (or removes the
`last_action_was_physics_revert_wait` tag at `simulator.py:1656`),
the test fails immediately because the four-bucket invariant
breaks and the public counter goes to zero.

## How to reproduce

```bash
python scripts/diagnostics/probe_physics_revert.py
# Exit 0 if any seed produced physics_revert > 0; exit 1 otherwise.
```
