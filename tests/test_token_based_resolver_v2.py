"""Resume-prompt-6: per-(agent, cell) token-count TokenBasedResolver.

These tests pin the re-implemented mechanism (audit 03 §2 divergence
resolved in favour of the paper, Decision 2b):

  * lazy 5-token endowment per (agent, cell),
  * one-per-contention transfer (winner -1 floored, each loser +1),
  * floor at 0 on decrement, no ceiling on increment,
  * zero-token "+∞ priority" auto-win,
  * the (τ, -d, w, -id) lexicographic priority tuple,
  * per-(agent, cell) (not per-agent) state scope,
  * within-run persistence and fresh-per-instance state,
  * audit 03 §3 modularity (no mutation of the caller's forbidden set).

The token transfer and the winner selection are exercised through the
resolver's own primitives — :meth:`_settle` (transfer with an explicit
winner) and :meth:`contend` / :meth:`_pick_winner` (winner by priority).
This is deliberate white-box testing: a transfer test like
``test_winner_decrements_loser_increments`` needs the SAME agent to win
five times in a row, which the natural priority mechanism forbids (after
one win the winner's τ drops below the loser's), so the arithmetic is
verified via the explicit-winner primitive while the selection rules are
verified separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import pytest

from ha_lmapf.core.types import AgentState, Observation, StepAction
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.local_tier.conflict_resolution.token_passing import (
    INITIAL_ENDOWMENT,
    TokenBasedResolver,
)


Cell = Tuple[int, int]


# ---------------------------------------------------------------------------
# Minimal SimStateView stub (mirrors tests/test_conflict_resolvers.py)
# ---------------------------------------------------------------------------
@dataclass
class MockSimState:
    agents: Dict[int, AgentState]
    env: Environment
    step: int = 0
    _plan_bundle: object = None
    _decided: Dict[int, Cell] = None

    def __post_init__(self):
        if self._decided is None:
            self._decided = {}

    def plans(self):
        return self._plan_bundle

    def decided_next_positions(self) -> Dict[int, Cell]:
        return self._decided


def _env() -> Environment:
    return Environment(width=7, height=7, blocked=set())


def _agent(aid: int, pos: Cell, goal: Cell, wait: int = 0) -> AgentState:
    return AgentState(agent_id=aid, pos=pos, goal=goal, wait_steps=wait)


# ===========================================================================
# Endowment + transfer arithmetic
# ===========================================================================
def test_initial_endowment_is_5():
    """A single contention between two agents at cell c: the winner's count
    at c goes to 4 and the loser's to 6, both materialized from the 5
    default (neither had a prior entry)."""
    env = _env()
    c = (3, 3)
    # A at (3,2) and B at (3,4) both want c; equal d (1) and w (0) -> A (id 0)
    # wins by the -id tie-break.
    agents = {0: _agent(0, (3, 2), c), 1: _agent(1, (3, 4), c)}
    sim = MockSimState(agents=agents, env=env)
    r = TokenBasedResolver()

    # Pre-state: nothing materialized.
    assert (0, c) not in r._tokens and (1, c) not in r._tokens
    assert r._token(0, c) == 5 and r._token(1, c) == 5

    winner = r.contend(c, [0, 1], sim)
    assert winner == 0
    assert r._tokens[(0, c)] == 4, "winner 5 -> 4"
    assert r._tokens[(1, c)] == 6, "loser 5 -> 6 (materialized from the 5 default)"


def test_winner_decrements_loser_increments():
    """Five consecutive contentions at cell c where agent A wins every time
    against agent B.  After five wins: A == 0, B == 10 (one token per
    contention).

    A is forced to win each round via the explicit-winner transfer
    primitive ``_settle`` — the natural priority mechanism would flip the
    winner to B after the first transfer (B's τ would exceed A's), so the
    one-per-contention arithmetic can only be exercised with a fixed
    winner."""
    c = (3, 3)
    r = TokenBasedResolver()
    for _ in range(5):
        r._settle(c, winner=0, contenders=[0, 1])
    assert r._tokens[(0, c)] == 0, "A: 5 -> 0 after five -1 transfers"
    assert r._tokens[(1, c)] == 10, "B: 5 -> 10 after five +1 transfers"


def test_floor_at_zero():
    """After A reaches 0 at c (five wins), a sixth win against a fresh agent
    C (count 5) leaves A at 0 (decrement floored) and C at 6 (incremented).

    Increment is never floored; only the decrement is suppressed below 0."""
    c = (3, 3)
    r = TokenBasedResolver()
    for _ in range(5):
        r._settle(c, winner=0, contenders=[0, 1])
    assert r._tokens[(0, c)] == 0
    # Sixth contention: A wins again, now against fresh C.
    r._settle(c, winner=0, contenders=[0, 2])
    assert r._tokens[(0, c)] == 0, "winner floored at 0, not -1"
    assert r._tokens[(2, c)] == 6, "fresh loser C: 5 -> 6"


# ===========================================================================
# Zero-token "+∞ priority" rule and the priority tuple
# ===========================================================================
def test_zero_token_auto_wins():
    """An agent at 0 tokens for c auto-wins via τ = +∞, even when the other
    contender has a strictly better (-d, w, -id) tail.

    Fixture: A is at 0 tokens, far from goal, high id; B is at 5 tokens,
    adjacent to goal, low id, long wait.  If τ were the finite count, B's
    tuple would dominate on every remaining slot — so a pass proves the
    +∞ rule, not the tail."""
    env = _env()
    c = (3, 3)
    # A: id 9, pos (3,2), goal far at (6,6) -> d large; B: id 0, pos (3,4),
    # goal (3,5) -> d small, big wait.
    agents = {
        9: _agent(9, (3, 2), (6, 6), wait=0),
        0: _agent(0, (3, 4), (3, 5), wait=50),
    }
    sim = MockSimState(agents=agents, env=env)
    r = TokenBasedResolver()
    r._tokens[(9, c)] = 0   # A at zero -> +∞
    r._tokens[(0, c)] = 5   # B finite

    # Sanity: under finite τ, B would win on the tail.
    assert r._priority(0, c, sim)[1:] > r._priority(9, c, sim)[1:]
    assert r._pick_winner(c, [9, 0], sim) == 9, "zero-token A auto-wins on τ=+∞"


def test_two_zero_agents_tie_break_by_id():
    """Two agents both at 0 tokens for c: both auto-win on τ=+∞, so the
    ``(-d, w, -id)`` tail decides.

    The locked tuple is (τ, -d, w, -id) — ``-d`` and ``w`` are MORE
    significant than ``-id``.  (The brief's prose example "B has the better
    (-d, w) but A wins on id" contradicts that ordering; the locked tuple is
    authoritative, so this test pins the *final* ``-id`` tiebreak the only
    way consistent with it: equal d and equal w, decided by id.)  With
    everything else equal the smaller id wins; swapping which agent holds
    the smaller id flips the winner."""
    env = _env()
    c = (3, 3)
    # Equal d (both 1 from their goals) and equal w; differ only by id.
    agents = {
        0: _agent(0, (3, 2), (3, 1), wait=3),
        1: _agent(1, (3, 4), (3, 5), wait=3),
    }
    sim = MockSimState(agents=agents, env=env)
    r = TokenBasedResolver()
    r._tokens[(0, c)] = 0
    r._tokens[(1, c)] = 0
    # Confirm the tails are identical except for -id.
    assert r._priority(0, c, sim)[:3] == r._priority(1, c, sim)[:3]
    assert r._pick_winner(c, [0, 1], sim) == 0, "smaller id wins the final tiebreak"

    # Swap which agent has the smaller id by relabeling: now agent 5 vs 7,
    # identical tails, smaller id (5) wins.
    agents2 = {
        7: _agent(7, (3, 2), (3, 1), wait=3),
        5: _agent(5, (3, 4), (3, 5), wait=3),
    }
    sim2 = MockSimState(agents=agents2, env=env)
    r2 = TokenBasedResolver()
    r2._tokens[(7, c)] = 0
    r2._tokens[(5, c)] = 0
    assert r2._pick_winner(c, [7, 5], sim2) == 5, "smaller id (5) wins"


def test_priority_tuple_lex_order_with_finite_taus():
    """Finite-τ lexicographic ordering across the full tuple.

    A (τ=5, far from goal), B (τ=3, near goal), C (τ=3, far from goal).
    A wins outright on τ.  Remove A and B beats C on -d (B is nearer)."""
    env = _env()
    c = (3, 3)
    agents = {
        0: _agent(0, (3, 2), (6, 6)),   # A: far  -> large d
        1: _agent(1, (3, 4), (3, 5)),   # B: near -> small d
        2: _agent(2, (2, 3), (6, 0)),   # C: far  -> large d
    }
    sim = MockSimState(agents=agents, env=env)
    r = TokenBasedResolver()
    r._tokens[(0, c)] = 5
    r._tokens[(1, c)] = 3
    r._tokens[(2, c)] = 3

    assert r._pick_winner(c, [0, 1, 2], sim) == 0, "A wins on highest τ"
    # Among the τ=3 pair, B wins by -d (nearer goal).
    assert r._pick_winner(c, [1, 2], sim) == 1, "B beats C on -d at equal τ"


# ===========================================================================
# Modularity (audit 03 §3)
# ===========================================================================
def test_forbidden_set_not_mutated():
    """resolve() may read the caller's forbidden set but must never mutate
    it (audit 03 §3).  After a real contention the passed set is
    byte-identical."""
    env = _env()
    c = (3, 3)
    agents = {0: _agent(0, (3, 2), c), 1: _agent(1, c, c)}  # B sits on c
    sim = MockSimState(agents=agents, env=env)
    obs = Observation(visible_humans={}, visible_agents={}, blocked=set())
    r = TokenBasedResolver()

    sentinel = {(99, 99)}
    before = set(sentinel)
    _ = r.resolve(0, c, sim, obs, rng=None, forbidden=sentinel)
    assert sentinel == before == {(99, 99)}, "resolver must not mutate caller's forbidden set"


# ===========================================================================
# State scope
# ===========================================================================
def test_separate_cells_have_separate_token_state():
    """Token state is per-(agent, cell): draining A at c1 to 0 leaves A's
    count at an untouched c2 at the 5 default."""
    c1, c2 = (3, 3), (1, 1)
    r = TokenBasedResolver()
    for _ in range(5):
        r._settle(c1, winner=0, contenders=[0, 1])
    assert r._tokens[(0, c1)] == 0
    assert (0, c2) not in r._tokens, "no entry for an un-contended cell"
    assert r._token(0, c2) == 5, "fresh 5 endowment at a different cell"


def test_token_state_persists_within_run():
    """Two contentions in sequence on the same resolver: the second sees the
    token state left by the first."""
    c = (3, 3)
    r = TokenBasedResolver()
    r._settle(c, winner=0, contenders=[0, 1])
    assert r._tokens[(0, c)] == 4 and r._tokens[(1, c)] == 6
    # Second contention reads the carried state, not the 5 default.
    r._settle(c, winner=0, contenders=[0, 1])
    assert r._tokens[(0, c)] == 3 and r._tokens[(1, c)] == 7


def test_token_state_does_not_cross_resolver_instances():
    """A fresh resolver starts with empty token state; the first contention
    materializes the 5 default (fresh-per-run semantics)."""
    c = (3, 3)
    r1 = TokenBasedResolver()
    for _ in range(5):
        r1._settle(c, winner=0, contenders=[0, 1])
    assert r1._tokens[(0, c)] == 0

    r2 = TokenBasedResolver()
    assert r2._tokens == {}, "new instance has no token state"
    assert r2._token(0, c) == INITIAL_ENDOWMENT
    r2._settle(c, winner=0, contenders=[0, 1])
    assert r2._tokens[(0, c)] == 4, "fresh instance starts the winner at 5 -> 4"
