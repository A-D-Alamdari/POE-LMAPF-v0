
"""
Human Motion Models.

This module defines the stochastic behaviors for simulated humans,
matching the formulations in the paper's Human Motion Model Framework.

Available Models:
  1. RandomWalkHumanModel: Random Walk with Inertia (Boltzmann/softmax).
  2. AisleFollowerHumanModel: Aisle-Following biased by corridor features (Boltzmann).
  3. AdversarialHumanModel: Congestion-seeking / agent-interfering (soft adversarial).
  4. MixedPopulationHumanModel: Heterogeneous per-human type sampling.
  5. ReplayHumanModel: Deterministic trajectory playback for reproducibility.

All models satisfy:
  - Static feasibility: x_h(t) in V for all t, h.
  - Bounded step: x_h(t+1) in A_h(x_h(t)) for all t, h.

Note:
  Humans treat agent positions as obstacles - they will not move into cells
  occupied by agents.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import replace
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from ha_lmapf.core.grid import manhattan, neighbors
from ha_lmapf.core.types import HumanState

Cell = Tuple[int, int]


class HumanModel:
    """
    Abstract base class for human motion policies.
    """

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        """
        Compute the next state for all humans in the simulation.

        Args:
            env: The simulation environment (must support `.is_free(cell)`).
            humans: A dictionary mapping human_id -> current HumanState.
            rng: A random number generator (e.g., np.random.default_rng()).
            agent_positions: Set of cells occupied by agents. Humans treat these
                           as obstacles and will not move into them.

        Returns:
            A new dictionary mapping human_id -> next HumanState.
        """
        raise NotImplementedError

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        """
        Predict the per-human distribution over next-tick cells WITHOUT
        mutating model state or human positions. Returns a mapping
        ``{human_id: {cell: probability}}``. Probabilities per human
        sum to 1.0. Caller treats any cell with probability > 0 as a
        candidate next-tick location.

        ``agent_positions`` is consulted exactly as in ``step``: under
        ``humans_block_on_agent_cells=True`` it filters candidates;
        under False it does not.  It may be a ``Set[Cell]`` (as
        ``step`` receives) or a ``Dict[int, Cell]`` (as the γ
        controller passes); both are normalized internally.

        This method must be deterministic given (env, humans,
        agent_positions, model state). It does NOT consume RNG; it
        computes the distribution analytically from the model's
        policy. Calling ``predict_next`` must leave the model
        byte-identical to its pre-call state.

        NOTE on the ``humans`` argument: the resume-plan prompt-5
        sketch wrote ``predict_next(env, agent_positions)`` but the
        models in this codebase are stateless w.r.t. human positions
        (``step`` receives ``humans`` per-call).  Predicting per-human
        distributions therefore requires the current human snapshot,
        so ``humans`` is a parameter here.  The γ controller passes
        ``sim_state.simulator.humans`` (the decision-time snapshot).
        """
        raise NotImplementedError


# ============================================================================
# Helper utilities
# ============================================================================

def _legal_successors(
        env, current: Cell, blocked: Set[Cell],
) -> List[Cell]:
    """
    Compute A_h(x_h(t)) = {current} union {free neighbors not in blocked}.

    Returns a list where index 0 is always the WAIT action (current cell),
    followed by valid movement targets.
    """
    successors = [current]  # WAIT is always legal
    for nb in neighbors(current):
        if env.is_free(nb) and nb not in blocked:
            successors.append(nb)
    return successors


def _softmax_probs(scores: np.ndarray) -> np.ndarray:
    """
    Convert a vector of Boltzmann logits to a normalized probability
    vector (no sampling, no RNG).

    Numerically stable (subtract max before exp).  This is the
    analytic core shared by ``_softmax_sample`` (which samples from
    it) and every model's ``predict_next`` (which returns it).
    """
    shifted = scores - scores.max()
    exp_scores = np.exp(shifted)
    return exp_scores / exp_scores.sum()


def _softmax_sample(scores: np.ndarray, rng) -> int:
    """
    Sample from a Boltzmann (softmax) distribution.

    Args:
        scores: Array of logits (unnormalized log-probabilities).
        rng: Numpy random generator.

    Returns:
        Index of the sampled element.
    """
    probs = _softmax_probs(scores)
    return int(rng.choice(len(scores), p=probs))


def _normalize_agent_cells(agent_positions) -> Set[Cell]:
    """
    Resume-prompt-5: normalize the ``agent_positions`` argument to a
    plain ``Set[Cell]``.

    ``step`` historically receives a ``Set[Cell]``; the γ controller
    calls ``predict_next`` with the simulator's ``Dict[int, Cell]``
    (agent_id -> cell).  Both forms (plus ``None``) are accepted so
    the prediction path and the step path consult agent positions
    identically.
    """
    if agent_positions is None:
        return set()
    if isinstance(agent_positions, dict):
        return set(agent_positions.values())
    return set(agent_positions)


def _distribution_from_scores(
        successors: List[Cell], scores: Optional[np.ndarray],
) -> Dict[Cell, float]:
    """
    Build a ``{cell: probability}`` distribution from a successor list
    and its Boltzmann scores.

    When ``scores is None`` the only legal action is WAIT
    (``successors == [current]``), so the distribution is the
    degenerate delta ``{current: 1.0}``.  Otherwise it is the softmax
    over the scored successors, index-aligned with ``successors``.
    """
    if scores is None:
        return {successors[0]: 1.0}
    probs = _softmax_probs(scores)
    return {successors[i]: float(probs[i]) for i in range(len(successors))}



def _continuation_cell(
        current: Cell, velocity: Tuple[int, int], env, blocked: Set[Cell],
) -> Optional[Cell]:
    """
    Compute cont(x_h(t), a_h(t)): the cell reached by continuing the
    previous direction, if feasible.

    Returns the continuation cell if legal, else None.
    """
    dr, dc = velocity
    if dr == 0 and dc == 0:
        return None
    candidate = (current[0] + dr, current[1] + dc)
    if env.is_free(candidate) and candidate not in blocked:
        return candidate
    return None


# ============================================================================
# 1. Random Walk with Inertia (Stochastic, Markov)
# ============================================================================

class RandomWalkHumanModel(HumanModel):
    """
    Random Walk with Inertia using Boltzmann (softmax) distribution.

    Paper formulation:
        pi_h(u | x_h(t), a_h(t)) = exp(score(u)) / sum_v exp(score(v))

    where:
        score(u) = beta_go   if u in cont(x_h(t), a_h(t))   [continue direction]
                   beta_wait if u = x_h(t)                    [stay in place]
                   beta_turn otherwise                         [change direction]

    Parameters:
        beta_go:   Log-weight for continuing in the same direction (inertia).
        beta_wait: Log-weight for remaining stationary.
        beta_turn: Baseline log-weight for changing direction.

    Since softmax is shift-invariant, only relative differences matter:
        - beta_go - beta_turn controls inertia strength
        - beta_wait - beta_turn controls stopping likelihood
        - All equal => uniform random walk
        - beta_go >> beta_turn => near-deterministic straight-line walking
    """

    def __init__(
            self,
            beta_go: float = 2.0,
            beta_wait: float = -1.0,
            beta_turn: float = 0.0,
            humans_block_on_agent_cells: bool = True,
    ) -> None:
        self.beta_go = float(beta_go)
        self.beta_wait = float(beta_wait)
        self.beta_turn = float(beta_turn)
        # Resume-prompt-2: True (default) preserves the vertex-
        # coordinated behavior; False drops the ``agent_positions``
        # filter in ``_legal_successors`` so humans may step into
        # agent-occupied cells (distance-0 vertex collision
        # accounted for by the simulator).
        self._humans_block_on_agent_cells = bool(humans_block_on_agent_cells)

    def _blocked_set(self, agent_positions) -> Set[Cell]:
        cells = _normalize_agent_cells(agent_positions)
        return cells if self._humans_block_on_agent_cells else set()

    def _score_successors(
            self, env, h: HumanState, blocked: Set[Cell],
    ) -> Tuple[List[Cell], Optional[np.ndarray]]:
        """Factor the Boltzmann scoring out of ``step`` so
        ``predict_next`` reuses the identical successor set + logits.
        Returns ``(successors, scores)`` where ``scores is None`` iff
        only WAIT is legal."""
        current = h.pos
        vel = h.velocity
        cont_cell = _continuation_cell(current, vel, env, blocked)
        successors = _legal_successors(env, current, blocked)
        if len(successors) == 1:
            return successors, None
        scores = np.empty(len(successors), dtype=np.float64)
        for i, cell in enumerate(successors):
            if cell == current:
                scores[i] = self.beta_wait
            elif cont_cell is not None and cell == cont_cell:
                scores[i] = self.beta_go
            else:
                scores[i] = self.beta_turn
        return successors, scores

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        new_humans: Dict[int, HumanState] = {}
        blocked = self._blocked_set(agent_positions)

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos

            successors, scores = self._score_successors(env, h, blocked)
            if scores is None:
                nxt = current
            else:
                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        blocked = self._blocked_set(agent_positions)
        out: Dict[int, Dict[Cell, float]] = {}
        for hid in sorted(humans.keys()):
            successors, scores = self._score_successors(env, humans[hid], blocked)
            out[hid] = _distribution_from_scores(successors, scores)
        return out


# ============================================================================
# 2. Aisle-Following Human (Map-Feature Biased)
# ============================================================================

def _compute_obstacle_distance_field(env) -> Dict[Cell, float]:
    """
    Compute the shortest-path distance from each free cell to the nearest
    static obstacle via multi-source BFS.

    Returns:
        Dict mapping free cell -> distance to nearest obstacle.
    """
    dist: Dict[Cell, int] = {}
    queue: deque = deque()

    # Seed BFS from all obstacle cells (distance 0)
    for r in range(env.height):
        for c in range(env.width):
            cell = (r, c)
            if not env.is_free(cell):
                dist[cell] = 0
                queue.append(cell)

    # BFS expansion into free cells
    while queue:
        cell = queue.popleft()
        d = dist[cell]
        for nb in neighbors(cell):
            if env.is_free(nb) and nb not in dist:
                dist[nb] = d + 1
                queue.append(nb)

    # Return only free cells
    return {cell: float(d) for cell, d in dist.items() if env.is_free(cell)}


class AisleFollowerHumanModel(HumanModel):
    """
    Aisle-Following Human using Boltzmann distribution with aisle-likelihood field.

    Paper formulation:
        pi_h(u | x_h(t), a_h(t)) proportional to
            exp(alpha * phi(u) + beta * 1[u in cont(x_h(t), a_h(t))])

    where phi(v) = -dist(v, S) is the aisle-likelihood field.
    S is the set of static obstacles; cells closer to obstacles (corridors
    between shelves) receive higher phi values.

    Typical constructions for phi:
        - phi(v) = -dist(v, S): favoring cells near shelves/corridors
        - phi(v) = 1[v is a corridor cell]: binary corridor indicator
        - A predefined corridor mask

    Parameters:
        alpha: Aisle-bias strength (>= 0). Higher alpha attracts motion
               toward corridor cells. alpha=0 disables aisle bias.
        beta:  Directional inertia strength. Higher beta encourages
               continuing in the previous direction.
    """

    def __init__(
            self,
            alpha: float = 1.0,
            beta: float = 1.5,
            wait_penalty: float = -1.0,
            humans_block_on_agent_cells: bool = True,
    ) -> None:
        self.alpha = float(alpha)
        self.beta = float(beta)
        # wait_penalty: additive score bonus for staying at the current cell.
        # Negative values (default -1.0) mirror RandomWalkHumanModel's beta_wait
        # and discourage humans from becoming stationary in narrow aisles,
        # which can otherwise create permanent blockages for agents.
        self.wait_penalty = float(wait_penalty)
        # Resume-prompt-2: regime toggle (see RandomWalkHumanModel).
        self._humans_block_on_agent_cells = bool(humans_block_on_agent_cells)

        # Cached aisle-likelihood field (computed lazily on first step)
        self._phi: Optional[Dict[Cell, float]] = None
        self._env_id: Optional[int] = None

    def _ensure_phi(self, env) -> None:
        """Lazily compute and cache the aisle-likelihood field phi."""
        env_id = id(env)
        if self._phi is not None and self._env_id == env_id:
            return
        dist_field = _compute_obstacle_distance_field(env)
        # phi(v) = -dist(v, S)
        self._phi = {cell: -d for cell, d in dist_field.items()}
        self._env_id = env_id

    def _blocked_set(self, agent_positions) -> Set[Cell]:
        cells = _normalize_agent_cells(agent_positions)
        return cells if self._humans_block_on_agent_cells else set()

    def _score_successors(
            self, env, h: HumanState, blocked: Set[Cell],
    ) -> Tuple[List[Cell], Optional[np.ndarray]]:
        """Aisle-likelihood Boltzmann scoring, factored for reuse by
        ``predict_next``.  ``scores is None`` iff only WAIT is legal."""
        phi = self._phi
        current = h.pos
        vel = h.velocity
        cont_cell = _continuation_cell(current, vel, env, blocked)
        successors = _legal_successors(env, current, blocked)
        if len(successors) == 1:
            return successors, None
        scores = np.empty(len(successors), dtype=np.float64)
        for i, cell in enumerate(successors):
            phi_val = phi.get(cell, 0.0)
            inertia_bonus = self.beta if (cont_cell is not None and cell == cont_cell) else 0.0
            stay_penalty = self.wait_penalty if cell == current else 0.0
            scores[i] = self.alpha * phi_val + inertia_bonus + stay_penalty
        return successors, scores

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        self._ensure_phi(env)

        new_humans: Dict[int, HumanState] = {}
        blocked = self._blocked_set(agent_positions)

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos

            successors, scores = self._score_successors(env, h, blocked)
            if scores is None:
                nxt = current
            else:
                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        self._ensure_phi(env)
        blocked = self._blocked_set(agent_positions)
        out: Dict[int, Dict[Cell, float]] = {}
        for hid in sorted(humans.keys()):
            successors, scores = self._score_successors(env, humans[hid], blocked)
            out[hid] = _distribution_from_scores(successors, scores)
        return out


# ============================================================================
# 3. Adversarial Human (Congestion-Seeking / Agent-Interfering)
# ============================================================================

def _compute_agent_distance_field(env, agent_positions: Set[Cell]) -> Dict[Cell, int]:
    """
    Multi-source BFS from all agent positions to compute the shortest-path
    distance from each free cell to the nearest agent.

    Returns:
        Dict mapping cell -> min distance to any agent.
    """
    dist: Dict[Cell, int] = {}
    queue: deque = deque()

    for pos in agent_positions:
        if env.is_free(pos):
            dist[pos] = 0
            queue.append(pos)

    while queue:
        cell = queue.popleft()
        d = dist[cell]
        for nb in neighbors(cell):
            if env.is_free(nb) and nb not in dist:
                dist[nb] = d + 1
                queue.append(nb)

    return dist


def _compute_bottleneck_centrality(env) -> Dict[Cell, float]:
    """
    Compute a proxy for vertex bottleneck centrality.

    Uses free-degree inversion: cells with fewer free neighbors
    (corridors, dead-ends) receive higher centrality.

        b(u) = (4 - free_degree(u)) / 4

    Range: [0, 1] where 1 = dead-end, 0.5 = corridor, 0 = open space.
    """
    centrality: Dict[Cell, float] = {}
    for r in range(env.height):
        for c in range(env.width):
            cell = (r, c)
            if not env.is_free(cell):
                continue
            degree = sum(1 for nb in neighbors(cell) if env.is_free(nb))
            centrality[cell] = (4.0 - degree) / 4.0
    return centrality


class AdversarialHumanModel(HumanModel):
    """
    Adversarial (Congestion-Seeking / Agent-Interfering) human model.

    Myopic, bounded-information adversary that biases motion toward agents
    and/or map bottlenecks while remaining one-step lawful.

    Target field:
        g_t(u) = lambda * b(u) - (1 - lambda) * min_i d(u, x_i(t))

    where:
        b(u) = bottleneck centrality (precomputed)
        d(u, x_i(t)) = shortest-path distance from u to nearest agent
        lambda in [0, 1] balances bottleneck vs. proximity attraction

    Policy (soft adversarial):
        pi_h(u | x_h(t), X_R(t)) proportional to
            exp(gamma * g_t(u)) * 1[u in A_h(x_h(t))]

    Parameters:
        gamma:   Aggressiveness factor. Large gamma => near-greedy.
                 Small gamma => more stochastic.
        lambda_: Bottleneck vs proximity factor.
                 0 = purely agent-chasing, 1 = purely bottleneck-seeking.
    """

    def __init__(
            self,
            gamma: float = 2.0,
            lambda_: float = 0.5,
            humans_block_on_agent_cells: bool = True,
    ) -> None:
        self.gamma = float(gamma)
        self.lambda_ = float(lambda_)
        # Resume-prompt-2: regime toggle (see RandomWalkHumanModel).
        self._humans_block_on_agent_cells = bool(humans_block_on_agent_cells)

        # Cached bottleneck centrality (computed lazily)
        self._bottleneck: Optional[Dict[Cell, float]] = None
        self._env_id: Optional[int] = None

    def _ensure_bottleneck(self, env) -> None:
        """Lazily compute and cache bottleneck centrality."""
        env_id = id(env)
        if self._bottleneck is not None and self._env_id == env_id:
            return
        self._bottleneck = _compute_bottleneck_centrality(env)
        self._env_id = env_id

    def _blocked_set(self, agent_positions) -> Set[Cell]:
        cells = _normalize_agent_cells(agent_positions)
        return cells if self._humans_block_on_agent_cells else set()

    def _prepare_fields(self, env, agent_positions):
        """Compute the (bottleneck, agent_dist, max_dist) target-field
        inputs shared by ``step`` and ``predict_next``.  The agent-
        distance field uses the RAW agent positions as sources (regime-
        independent), not the blocked set -- see the step comment from
        resume-prompt-2."""
        self._ensure_bottleneck(env)
        sources = _normalize_agent_cells(agent_positions)
        agent_dist = _compute_agent_distance_field(env, sources) if sources else {}
        max_dist = env.width + env.height
        return self._bottleneck, agent_dist, max_dist

    def _score_successors(
            self, env, h: HumanState, blocked: Set[Cell],
            bottleneck, agent_dist, max_dist,
    ) -> Tuple[List[Cell], Optional[np.ndarray]]:
        """Adversarial target-field scoring, factored for reuse by
        ``predict_next``.  ``scores is None`` iff only WAIT is legal."""
        current = h.pos
        successors = _legal_successors(env, current, blocked)
        if len(successors) == 1:
            return successors, None
        scores = np.empty(len(successors), dtype=np.float64)
        for i, cell in enumerate(successors):
            b_val = bottleneck.get(cell, 0.0)
            d_val = -agent_dist.get(cell, max_dist)
            g_val = self.lambda_ * b_val + (1.0 - self.lambda_) * d_val
            scores[i] = self.gamma * g_val
        return successors, scores

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        bottleneck, agent_dist, max_dist = self._prepare_fields(env, agent_positions)
        blocked = self._blocked_set(agent_positions)

        new_humans: Dict[int, HumanState] = {}

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos

            successors, scores = self._score_successors(
                env, h, blocked, bottleneck, agent_dist, max_dist)
            if scores is None:
                nxt = current
            else:
                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        bottleneck, agent_dist, max_dist = self._prepare_fields(env, agent_positions)
        blocked = self._blocked_set(agent_positions)
        out: Dict[int, Dict[Cell, float]] = {}
        for hid in sorted(humans.keys()):
            successors, scores = self._score_successors(
                env, humans[hid], blocked, bottleneck, agent_dist, max_dist)
            out[hid] = _distribution_from_scores(successors, scores)
        return out


# ============================================================================
# 4. Mixed Human Population Model (Heterogeneous)
# ============================================================================

class MixedPopulationHumanModel(HumanModel):
    """
    Heterogeneous human population with per-human behavior type assignment.

    Each human h is assigned a behavior type z_h sampled once from a
    categorical distribution with weights w:

        Pr(z_h = k) = w_k,   sum_k w_k = 1

    The assignment is fixed for the episode duration, reflecting persistent
    individual walking styles:

        pi_h(.) = pi^(z_h)(.)

    Since each component policy assigns nonzero probability only to legal
    successors, any mixture preserves motion legality and bounded step length.

    Parameters:
        models:  Dict[str, HumanModel] mapping model name -> instance.
        weights: Dict[str, float] mapping model name -> categorical weight.
    """

    def __init__(
            self,
            models: Dict[str, HumanModel],
            weights: Dict[str, float],
            humans_block_on_agent_cells: bool = True,
    ) -> None:
        self._models = models
        self._weights = weights
        # Resume-prompt-2: regime toggle.  Mixed only dispatches to
        # the sub-models, so the toggle takes effect via each
        # sub-model's own ``_humans_block_on_agent_cells`` field --
        # the factory passes the same value through when building
        # each sub-instance.  Stored here so callers can inspect
        # the regime if needed.
        self._humans_block_on_agent_cells = bool(humans_block_on_agent_cells)
        # Per-human type assignments (populated on first step)
        self._assignments: Dict[int, str] = {}
        self._assigned = False

    def _assign_types(self, human_ids, rng) -> None:
        """Assign each human a model type from categorical distribution."""
        if self._assigned:
            return
        names = sorted(self._weights.keys())
        raw_weights = [self._weights[n] for n in names]
        total = sum(raw_weights)
        probs = [w / total for w in raw_weights]

        for hid in sorted(human_ids):
            idx = int(rng.choice(len(names), p=probs))
            self._assignments[hid] = names[idx]
        self._assigned = True

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        self._assign_types(humans.keys(), rng)

        # Group humans by assigned model type
        groups: Dict[str, Dict[int, HumanState]] = {}
        for hid in sorted(humans.keys()):
            model_name = self._assignments[hid]
            groups.setdefault(model_name, {})[hid] = humans[hid]

        # Step each group through its assigned model
        new_humans: Dict[int, HumanState] = {}
        for model_name in sorted(groups.keys()):
            model = self._models[model_name]
            group_result = model.step(env, groups[model_name], rng, agent_positions)
            new_humans.update(group_result)

        return new_humans

    def _predict_assignment(self, human_ids) -> Dict[int, str]:
        """Resolve the per-human sub-model assignment for prediction
        WITHOUT consuming RNG or mutating ``self._assignments``.

        Normal path: ``step`` has already run at least once (the
        simulator advances humans before the controller decides), so
        ``self._assignments`` is populated and is returned as-is.

        Fallback (predict_next called before any step, e.g. an
        isolated unit test): assign each human deterministically to
        the highest-weight sub-model (ties broken by sorted name).
        This is local-only and never written back, preserving the
        no-mutation contract.  Per audit 04 §3 each human belongs to
        exactly one sub-model, which both paths honor."""
        if self._assigned:
            return self._assignments
        names = sorted(self._weights.keys())
        best = max(names, key=lambda n: (self._weights[n], n))
        return {hid: best for hid in human_ids}

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        assignment = self._predict_assignment(sorted(humans.keys()))
        # Group humans by assigned sub-model, then merge each
        # sub-model's prediction.  Each human appears in exactly one
        # group so the merged dict has no key collisions.
        groups: Dict[str, Dict[int, HumanState]] = {}
        for hid in sorted(humans.keys()):
            groups.setdefault(assignment[hid], {})[hid] = humans[hid]
        out: Dict[int, Dict[Cell, float]] = {}
        for model_name in sorted(groups.keys()):
            sub = self._models[model_name].predict_next(
                env, groups[model_name], agent_positions)
            out.update(sub)
        return out


# ============================================================================
# 5. Replay Humans (Deterministic Trajectory Mode)
# ============================================================================

class ReplayHumanModel(HumanModel):
    """
    Deterministic trajectory replay for fairness and reproducibility.

    Each human follows a fixed pre-recorded trajectory:

        x_h(t+1) = trajectory_h[t+1]

    Legality is enforced at generation time:
        - x_h[t] in V for all t
        - x_h[t+1] in A_h(x_h[t]) for all t

    When the trajectory is exhausted, the human remains at its last position.

    Parameters:
        trajectories: Dict mapping human_id -> list of (row, col) positions.

    NOTE on ``humans_block_on_agent_cells`` (resume-prompt-2): this
    model ignores runtime ``agent_positions`` by design (the
    trajectories were fixed at generation time).  The regime toggle
    is accepted for interface uniformity but has no effect: if a
    recorded position happens to coincide with an agent's cell at
    runtime, the human still moves there regardless of the toggle.
    The simulator's distance-0 detection will still count the
    encroachment as a vertex collision under both regimes.
    """

    def __init__(
            self,
            trajectories: Dict[int, List[Tuple[int, int]]],
            humans_block_on_agent_cells: bool = True,
    ) -> None:
        self._trajectories = trajectories
        self._step = 0
        # Stored for interface uniformity; see class docstring note --
        # Replay ignores ``agent_positions`` by design.
        self._humans_block_on_agent_cells = bool(humans_block_on_agent_cells)

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        new_humans: Dict[int, HumanState] = {}
        next_step = self._step + 1

        for hid in sorted(humans.keys()):
            h = humans[hid]
            traj = self._trajectories.get(hid)

            if traj is not None and next_step < len(traj):
                nxt = tuple(traj[next_step])
            else:
                # Trajectory exhausted: remain at last position
                nxt = h.pos

            new_vel = (nxt[0] - h.pos[0], nxt[1] - h.pos[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        self._step += 1
        return new_humans

    def predict_next(
            self,
            env,
            humans: Dict[int, HumanState],
            agent_positions=None,
    ) -> Dict[int, Dict[Cell, float]]:
        """Degenerate delta on the next recorded position.  Mirrors
        ``step``'s lookup (``next_step = self._step + 1``) WITHOUT
        advancing ``self._step``, so the model is byte-identical
        afterward.  When a trajectory is exhausted the human stays
        put: ``{current: 1.0}``.  ``agent_positions`` is ignored by
        design (recorded trajectories are fixed; see class docstring)."""
        next_step = self._step + 1
        out: Dict[int, Dict[Cell, float]] = {}
        for hid in sorted(humans.keys()):
            h = humans[hid]
            traj = self._trajectories.get(hid)
            if traj is not None and next_step < len(traj):
                nxt = tuple(traj[next_step])
            else:
                nxt = h.pos
            out[hid] = {nxt: 1.0}
        return out

    @classmethod
    def from_json(cls, path: str, env=None) -> "ReplayHumanModel":
        """
        Load trajectories from a replay JSON file.

        Expected format (compatible with ReplayWriter output):
            {
              "humans": {
                "0": [[r0, c0], [r1, c1], ...],
                "1": [[r0, c0], [r1, c1], ...],
                ...
              }
            }

        Args:
            path: Path to the JSON file.
            env: Optional environment for legality validation.

        Returns:
            A configured ReplayHumanModel instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw = data.get("humans", {})
        trajectories: Dict[int, List[Tuple[int, int]]] = {}
        for hid_str in sorted(raw.keys(), key=int):
            hid = int(hid_str)
            trajectories[hid] = [tuple(p) for p in raw[hid_str]]

        # Validate legality if environment is provided
        if env is not None:
            for hid, traj in trajectories.items():
                for t, pos in enumerate(traj):
                    if not env.is_free(pos):
                        raise ValueError(
                            f"Replay legality violation: human {hid} at step "
                            f"{t} occupies obstacle cell {pos}"
                        )
                    if t > 0:
                        prev = traj[t - 1]
                        step_dist = abs(pos[0] - prev[0]) + abs(pos[1] - prev[1])
                        if step_dist > 1:
                            raise ValueError(
                                f"Replay legality violation: human {hid} at step "
                                f"{t} has unbounded step {prev} -> {pos} "
                                f"(distance {step_dist})"
                            )

        return cls(trajectories=trajectories)

    @classmethod
    def generate_and_record(
            cls,
            source_model: HumanModel,
            env,
            humans: Dict[int, HumanState],
            rng,
            steps: int,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> "ReplayHumanModel":
        """
        Generate trajectories using a stochastic model and create a replay.

        This is the recommended way to produce replay data: run any stochastic
        model with a fixed seed and record the resulting trajectories.

        Args:
            source_model: The stochastic model to generate from.
            env: The simulation environment.
            humans: Initial human states.
            rng: Seeded random generator for reproducibility.
            steps: Number of steps to generate.
            agent_positions: Optional agent positions (static for generation).

        Returns:
            A ReplayHumanModel with pre-recorded trajectories.
        """
        trajectories: Dict[int, List[Tuple[int, int]]] = {}
        for hid in sorted(humans.keys()):
            trajectories[hid] = [humans[hid].pos]

        current_humans = dict(humans)
        for _ in range(steps):
            current_humans = source_model.step(env, current_humans, rng, agent_positions)
            for hid in sorted(current_humans.keys()):
                trajectories[hid].append(current_humans[hid].pos)

        return cls(trajectories=trajectories)
