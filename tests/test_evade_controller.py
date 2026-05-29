"""Resume-prompt-5 STAGE 3 acceptance tests: γ in AgentController.

Mixes:

* Single-tick unit tests that drive ``AgentController.decide_action``
  with a ``_SimStub`` (the pattern already used in
  ``tests/test_local_safety.py``) plus a deterministic
  ``ReplayHumanModel`` so the prediction is exact.  These pin the
  forbidden-set construction, the predicted-encroached tag, and the
  Safe-Wait-when-cornered case.

* Real-fixture end-to-end runs covering the two design contracts:
  γ-classified-as-response in the False regime and γ-is-a-no-op in
  the True regime (the latter exact byte equality with baseline,
  per the False-only guard in ``_predicted_forbidden``).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Dict, Set

import numpy as np
import pytest

from ha_lmapf.core.types import (
    AgentState, HumanState, Observation, PlanBundle,
    SimConfig, StepAction, TimedPath,
)
from ha_lmapf.humans.models import ReplayHumanModel
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.local_tier.agent_controller import AgentController
from ha_lmapf.local_tier.conflict_resolution.priority_rules import PriorityRulesResolver
from ha_lmapf.local_tier.local_planner import AStarLocalPlanner
from ha_lmapf.local_tier.sensors import build_observation
from ha_lmapf.simulation.environment import Environment
from ha_lmapf.simulation.simulator import Simulator


REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_MAP = str(REPO_ROOT / "data" / "maps" / "empty-16-16.map")


# ---------------------------------------------------------------------------
# Stub mirroring tests/test_local_safety.py::_SimStub, extended with the
# attributes the γ branch consults: ``config``, ``human_model``,
# ``agent_positions``, ``simulator`` (identity), and the
# ``_predicted_encroached_this_tick`` scratch set.
# ---------------------------------------------------------------------------


class _Cfg:
    def __init__(self, *, algorithm_variant: str, safety_radius: int,
                 humans_block_on_agent_cells: bool = False):
        self.algorithm_variant = algorithm_variant
        self.safety_radius = safety_radius
        self.humans_block_on_agent_cells = humans_block_on_agent_cells


class _SimStub:
    def __init__(self, *, env, agents, humans, plans,
                 cfg: _Cfg, human_model, step: int = 0):
        self.env = env
        self.agents = agents
        self.humans = humans
        self._plans = plans
        self.step = step
        self.config = cfg
        self.human_model = human_model
        self._predicted_encroached_this_tick: Set[int] = set()

        class _M:
            def __init__(self): self.replans = 0
            def add_replan(self, n): self.replans += int(n)
        self.metrics = _M()

    def plans(self):
        return self._plans

    @property
    def agent_positions(self):
        return {aid: a.pos for aid, a in self.agents.items()}

    @property
    def simulator(self):
        return self


def _make_controller(fov: int = 4, safe: int = 1):
    return AgentController(
        agent_id=0,
        local_planner=AStarLocalPlanner(),
        conflict_resolver=PriorityRulesResolver(),
        fov_radius=fov,
        safety_radius=safe,
    )


def _replay(traj_by_hid: Dict[int, list]) -> ReplayHumanModel:
    return ReplayHumanModel(trajectories=traj_by_hid)


def _result_cell(cur, action):
    if action == StepAction.UP:    return (cur[0] - 1, cur[1])
    if action == StepAction.DOWN:  return (cur[0] + 1, cur[1])
    if action == StepAction.LEFT:  return (cur[0], cur[1] - 1)
    if action == StepAction.RIGHT: return (cur[0], cur[1] + 1)
    return cur


# ===========================================================================
# Unit tests — decide_action with deterministic predictions
# ===========================================================================


def test_baseline_ignores_predictions():
    """algorithm_variant='baseline' must NOT consult predict_next: the
    decision is the same as it would be in an alt-world without the
    predicted human, and ``_predicted_encroached_this_tick`` stays
    empty."""
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 4), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
    tp = TimedPath(cells=[(2, 2), (2, 3), (2, 4)], start_step=0)
    plans = PlanBundle(paths={0: tp}, created_step=0, horizon=2)
    # Replay predicts the human steps into (2,3) next -- the cell on
    # the global plan that baseline would otherwise take.
    model = _replay({0: [(0, 0), (2, 3)]})

    cfg = _Cfg(algorithm_variant="baseline", safety_radius=1,
               humans_block_on_agent_cells=False)
    sim = _SimStub(env=env, agents=agents, humans=humans, plans=plans,
                   cfg=cfg, human_model=model)
    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    ctrl = _make_controller()

    action = ctrl.decide_action(sim, obs, rng=None)
    nxt = _result_cell(agents[0].pos, action)
    # Baseline followed the global plan into (2,3) (the prediction is
    # not consulted) and the predicted-encroached tag is untouched.
    assert nxt == (2, 3), f"baseline must follow global plan; got {action} -> {nxt}"
    assert sim._predicted_encroached_this_tick == set(), (
        f"baseline must not touch the predicted set; "
        f"got {sim._predicted_encroached_this_tick}"
    )


def test_evade_avoids_predicted_cells():
    """algorithm_variant='evade': agent at (2,2) with the global plan
    sending it to (2,3); a Replay-deterministic human predicted at
    (2,3) next.  γ must NOT step into (2,3) -- it routes around or
    Safe-Waits.

    The deterministic predictor produces probability 1.0 at (2,3), so
    even the most cautious mutation (β: ``p > 0.5``) still treats it
    as forbidden -- this test pins the geometric avoidance and stays
    insensitive to the probability threshold.  (Mutation β is
    instead caught by ``test_evade_avoids_low_prob_cells`` below.)
    """
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 4), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0))}
    tp = TimedPath(cells=[(2, 2), (2, 3), (2, 4)], start_step=0)
    plans = PlanBundle(paths={0: tp}, created_step=0, horizon=2)
    model = _replay({0: [(0, 0), (2, 3)]})

    cfg = _Cfg(algorithm_variant="evade", safety_radius=1,
               humans_block_on_agent_cells=False)
    sim = _SimStub(env=env, agents=agents, humans=humans, plans=plans,
                   cfg=cfg, human_model=model)
    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    ctrl = _make_controller()

    action = ctrl.decide_action(sim, obs, rng=None)
    nxt = _result_cell(agents[0].pos, action)
    assert nxt != (2, 3), (
        f"γ must avoid the predicted-human cell (2,3); took {action} -> {nxt}"
    )


def test_evade_avoids_low_prob_cells():
    """Mutation β target: a low-but-nonzero predicted probability
    must still be forbidden under the option-II risk-averse rule.

    Critical fixture design: the avoided cell (2,3) must lie OUTSIDE
    the OBSERVED human's r_safe buffer (otherwise the cell is
    already forbidden via the observation path, and the predicted
    contribution is overshadowed -- mutation β would silently slip
    through).  Solution: place the human two cells away so (2,3) is
    only in the PREDICTED-forbidden set, via the inflated buffer
    around the human's predicted next position.

    Layout, r_safe=1, fov=4:
      Agent  (2,2)                     goal (2,4)
      Human  (4,3)                     stationary, velocity (0,0)
      Obs forbidden = inflate({(4,3)}) = {(4,3),(3,3),(5,3),(4,2),(4,4)}
        -> does NOT include (2,3).
      Predict cells with p>0 = {(4,3),(3,3),(5,3),(4,2),(4,4)}
        -> p((3,3)) ~ 0.23.  Inflate({(3,3)}, r=1) includes (2,3).
        -> p((3,3)) is the only contribution to (2,3); β drops it.

    Under the spec (p > 0) γ adds (2,3) and avoids it.  Under
    mutation β (p > 0.5) γ excludes p((3,3)) ~ 0.23 -- (2,3) is no
    longer predicted-forbidden -- and γ takes the global-plan step
    into it."""
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(2, 4), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(4, 3), velocity=(0, 0))}
    tp = TimedPath(cells=[(2, 2), (2, 3), (2, 4)], start_step=0)
    plans = PlanBundle(paths={0: tp}, created_step=0, horizon=2)

    from ha_lmapf.humans.models import RandomWalkHumanModel
    model = RandomWalkHumanModel(humans_block_on_agent_cells=False)

    # Sanity-check the probability of p((3,3)) sits in the band the
    # mutation drops.  This is the single decisive probability for
    # (2,3) being predicted-forbidden under the spec rule.
    dist = model.predict_next(env, humans, agent_positions=None)[0]
    p_33 = dist.get((3, 3), 0.0)
    assert 0.0 < p_33 < 0.5, (
        f"test setup expected p((3,3)) in (0, 0.5); got {p_33}"
    )
    # And (2,3) is NOT in the observation-forbidden set, so the only
    # path to its being forbidden runs through the prediction branch.
    observed_F = inflate_cells({(4, 3)}, radius=1, env=env)
    assert (2, 3) not in observed_F, (
        f"test setup expected (2,3) outside the observed forbidden "
        f"set; got {observed_F}"
    )

    cfg = _Cfg(algorithm_variant="evade", safety_radius=1,
               humans_block_on_agent_cells=False)
    sim = _SimStub(env=env, agents=agents, humans=humans, plans=plans,
                   cfg=cfg, human_model=model)
    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    ctrl = _make_controller()

    action = ctrl.decide_action(sim, obs, rng=None)
    nxt = _result_cell(agents[0].pos, action)
    assert nxt != (2, 3), (
        f"γ must avoid even low-prob predicted cells under option II; "
        f"p((3,3))={p_33:.3f}; action={action} -> {nxt}"
    )


def test_evade_safe_waits_when_all_directions_predicted_blocked():
    """All four neighbours predicted-blocked => γ stays put AND the
    agent is tagged predicted-encroached this tick."""
    env = Environment(width=5, height=5, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(2, 2), goal=(4, 4), task_id="t0")}
    # Four deterministic-Replay humans, one stepping into each of the
    # four neighbours of (2,2).  With r_safe=1 the inflated forbidden
    # set covers (2,2) itself, so the agent is predicted-encroached.
    humans = {
        0: HumanState(human_id=0, pos=(0, 0), velocity=(0, 0)),
        1: HumanState(human_id=1, pos=(0, 4), velocity=(0, 0)),
        2: HumanState(human_id=2, pos=(4, 0), velocity=(0, 0)),
        3: HumanState(human_id=3, pos=(4, 4), velocity=(0, 0)),
    }
    model = _replay({
        0: [(0, 0), (1, 2)],   # -> N neighbour
        1: [(0, 4), (3, 2)],   # -> S neighbour
        2: [(4, 0), (2, 1)],   # -> W neighbour
        3: [(4, 4), (2, 3)],   # -> E neighbour
    })
    plans = PlanBundle(paths={}, created_step=0, horizon=1)
    cfg = _Cfg(algorithm_variant="evade", safety_radius=1,
               humans_block_on_agent_cells=False)
    sim = _SimStub(env=env, agents=agents, humans=humans, plans=plans,
                   cfg=cfg, human_model=model)
    obs = build_observation(agent_id=0, sim_state=sim, fov_radius=4)
    ctrl = _make_controller()

    action = ctrl.decide_action(sim, obs, rng=None)
    assert action == StepAction.WAIT, (
        f"γ must Safe Wait when every neighbour is predicted-blocked; "
        f"got {action}"
    )
    assert 0 in sim._predicted_encroached_this_tick, (
        f"corner-trapped agent must be tagged predicted-encroached; "
        f"got {sim._predicted_encroached_this_tick}"
    )


def test_evade_inflates_predicted_cells_by_r_safe():
    """Geometric symmetry: a predicted human at (3,3) with r_safe=1
    must contribute the Manhattan-1 ball {(3,3),(2,3),(4,3),(3,2),(3,4)}
    to ``_predicted_forbidden``."""
    env = Environment(width=7, height=7, blocked=set())
    agents = {0: AgentState(agent_id=0, pos=(0, 0), goal=(0, 1), task_id="t0")}
    humans = {0: HumanState(human_id=0, pos=(6, 6), velocity=(0, 0))}
    model = _replay({0: [(6, 6), (3, 3)]})

    cfg = _Cfg(algorithm_variant="evade", safety_radius=1,
               humans_block_on_agent_cells=False)
    sim = _SimStub(env=env, agents=agents, humans=humans, plans=None,
                   cfg=cfg, human_model=model)
    ctrl = _make_controller()

    predicted = ctrl._predicted_forbidden(sim)
    expected = inflate_cells({(3, 3)}, radius=1, env=env)
    assert expected == {(3, 3), (2, 3), (4, 3), (3, 2), (3, 4)}, (
        f"sanity: inflate_cells({(3, 3)}, r=1) returned {expected}"
    )
    assert expected.issubset(predicted), (
        f"predicted-forbidden missing inflation cells: "
        f"expected ⊆ {expected}, got {predicted}"
    )


# ===========================================================================
# End-to-end — real fixtures
# ===========================================================================


def _make_tiny_map(td, n=6):
    p = os.path.join(td, f"empty-{n}.map")
    open(p, "w").write(f"type octile\nheight {n}\nwidth {n}\nmap\n" + ("." * n + "\n") * n)
    return p


def test_evade_classified_as_response():
    """End-to-end (False regime): under the audit-10 §3 smoke fixture
    with adversarial humans (which seek agent cells), γ produces
    response-attributable pairs > 0 AND ``def1_agent_attributable == 0``.
    This is the load-bearing test: γ's evade actions do NOT get blamed
    on the agent."""
    with tempfile.TemporaryDirectory() as td:
        mp = _make_tiny_map(td, n=6)
        cfg = SimConfig(
            map_path=mp, seed=0, steps=50,
            num_agents=2, num_humans=6,
            fov_radius=2, safety_radius=1,
            human_model="adversarial",
            mode="lifelong", task_allocator="congestion_avoidance",
            global_solver="cbs", hard_safety=True,
            humans_block_on_agent_cells=False,
            algorithm_variant="evade",
        )
        sim = Simulator(cfg)
        sim.run()
        m = sim.metrics.finalize(total_steps=cfg.steps, num_agents=cfg.num_agents)

        assert m.violations_def1_response_attributable > 0, (
            f"γ must produce some response-attributable pairs on this "
            f"adversarial fixture; got "
            f"{m.violations_def1_response_attributable}"
        )
        assert m.violations_def1_agent_attributable == 0, (
            f"γ evade moves must NOT route to agent-attributable; got "
            f"{m.violations_def1_agent_attributable} "
            f"(response={m.violations_def1_response_attributable})"
        )


def test_evade_in_true_regime_is_near_baseline():
    """γ is a no-op in the True regime by construction (the
    ``_predicted_forbidden`` False-only guard); True+evade and
    True+baseline must execute identical code paths and produce
    identical metrics.  Asserts byte equality on the three load-
    bearing aggregates -- a tighter bar than the prompt's 10%
    bound, made possible by the design guard added during stage 3
    after the qualitative-finding hand-back."""
    for seed in (0, 1, 2):
        common = dict(
            map_path=SMOKE_MAP, seed=seed, steps=300,
            num_agents=4, num_humans=5, fov_radius=2, safety_radius=1,
            human_model="random_walk",
            mode="lifelong", task_allocator="congestion_avoidance",
            global_solver="cbs", hard_safety=True,
            humans_block_on_agent_cells=True,
        )
        sim_b = Simulator(SimConfig(**common, algorithm_variant="baseline"))
        sim_b.run()
        m_b = sim_b.metrics.finalize(total_steps=300, num_agents=4)

        sim_e = Simulator(SimConfig(**common, algorithm_variant="evade"))
        sim_e.run()
        m_e = sim_e.metrics.finalize(total_steps=300, num_agents=4)

        assert m_e.throughput == m_b.throughput, (
            f"seed {seed}: True+evade vs True+baseline throughput "
            f"differ ({m_e.throughput} vs {m_b.throughput}); γ guard "
            f"is not firing."
        )
        assert m_e.total_wait_steps == m_b.total_wait_steps, (
            f"seed {seed}: True+evade vs True+baseline total_wait "
            f"differ ({m_e.total_wait_steps} vs {m_b.total_wait_steps})."
        )
        assert (m_e.violations_def1_safety_violations
                == m_b.violations_def1_safety_violations)
        assert m_e.violations_def1_response_attributable == 0
        assert m_e.violations_def1_agent_attributable == 0
