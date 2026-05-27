
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


def _softmax_sample(scores: np.ndarray, rng) -> int:
    """
    Sample from a Boltzmann (softmax) distribution.

    Args:
        scores: Array of logits (unnormalized log-probabilities).
        rng: Numpy random generator.

    Returns:
        Index of the sampled element.
    """
    # Numerical stability: subtract max before exp
    shifted = scores - scores.max()
    exp_scores = np.exp(shifted)
    probs = exp_scores / exp_scores.sum()
    return int(rng.choice(len(scores), p=probs))


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
    ) -> None:
        self.beta_go = float(beta_go)
        self.beta_wait = float(beta_wait)
        self.beta_turn = float(beta_turn)

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        new_humans: Dict[int, HumanState] = {}
        blocked = agent_positions if agent_positions is not None else set()

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos
            vel = h.velocity

            # Compute continuation cell (where same direction leads)
            cont_cell = _continuation_cell(current, vel, env, blocked)

            # Build legal action set A_h(x_h(t))
            successors = _legal_successors(env, current, blocked)

            if len(successors) == 1:
                # Only WAIT is possible (trapped)
                nxt = current
            else:
                # Assign scores per the Boltzmann model
                scores = np.empty(len(successors), dtype=np.float64)
                for i, cell in enumerate(successors):
                    if cell == current:
                        scores[i] = self.beta_wait
                    elif cont_cell is not None and cell == cont_cell:
                        scores[i] = self.beta_go
                    else:
                        scores[i] = self.beta_turn

                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans


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
    ) -> None:
        self.alpha = float(alpha)
        self.beta = float(beta)
        # wait_penalty: additive score bonus for staying at the current cell.
        # Negative values (default -1.0) mirror RandomWalkHumanModel's beta_wait
        # and discourage humans from becoming stationary in narrow aisles,
        # which can otherwise create permanent blockages for agents.
        self.wait_penalty = float(wait_penalty)

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

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        self._ensure_phi(env)
        phi = self._phi

        new_humans: Dict[int, HumanState] = {}
        blocked = agent_positions if agent_positions is not None else set()

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos
            vel = h.velocity

            cont_cell = _continuation_cell(current, vel, env, blocked)
            successors = _legal_successors(env, current, blocked)

            if len(successors) == 1:
                nxt = current
            else:
                # Boltzmann score: alpha * phi(u) + beta * 1[u in cont] + wait_penalty * 1[u == current]
                scores = np.empty(len(successors), dtype=np.float64)
                for i, cell in enumerate(successors):
                    phi_val = phi.get(cell, 0.0)
                    inertia_bonus = self.beta if (cont_cell is not None and cell == cont_cell) else 0.0
                    stay_penalty = self.wait_penalty if cell == current else 0.0
                    scores[i] = self.alpha * phi_val + inertia_bonus + stay_penalty

                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans


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
    ) -> None:
        self.gamma = float(gamma)
        self.lambda_ = float(lambda_)

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

    def step(
            self,
            env,
            humans: Dict[int, HumanState],
            rng,
            agent_positions: Optional[Set[Cell]] = None,
    ) -> Dict[int, HumanState]:
        self._ensure_bottleneck(env)
        bottleneck = self._bottleneck

        blocked = agent_positions if agent_positions is not None else set()

        # Compute agent distance field (changes each step as agents move)
        agent_dist = _compute_agent_distance_field(env, blocked) if blocked else {}

        # Maximum possible distance for cells unreachable from agents
        max_dist = env.width + env.height

        new_humans: Dict[int, HumanState] = {}

        for hid in sorted(humans.keys()):
            h = humans[hid]
            current = h.pos

            successors = _legal_successors(env, current, blocked)

            if len(successors) == 1:
                nxt = current
            else:
                # Compute target field g_t(u) for each successor
                scores = np.empty(len(successors), dtype=np.float64)
                for i, cell in enumerate(successors):
                    b_val = bottleneck.get(cell, 0.0)
                    # Negative distance: closer to agent = higher value
                    d_val = -agent_dist.get(cell, max_dist)
                    g_val = self.lambda_ * b_val + (1.0 - self.lambda_) * d_val
                    scores[i] = self.gamma * g_val

                idx = _softmax_sample(scores, rng)
                nxt = successors[idx]

            new_vel = (nxt[0] - current[0], nxt[1] - current[1])
            new_humans[hid] = replace(h, pos=nxt, velocity=new_vel)

        return new_humans


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
    ) -> None:
        self._models = models
        self._weights = weights
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
    """

    def __init__(
            self,
            trajectories: Dict[int, List[Tuple[int, int]]],
    ) -> None:
        self._trajectories = trajectories
        self._step = 0

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
