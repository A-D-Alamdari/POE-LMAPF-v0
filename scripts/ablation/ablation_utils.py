"""Shared utilities for the HA-LMAPF ablation study.

Ablation groups and what each one justifies
-------------------------------------------
Group A — Tier Architecture
  Claim: "The two-tier (global + local) architecture outperforms a pure
          Tier-1 (RHCR-like) baseline, and each Tier-2 sub-component
          (local replanning, conflict resolution) contributes independently."
  Conditions: full_system, no_local_replan, no_conflict_resolution,
               global_only

Group B — Human-Awareness & Safety System
  Claim: "Hard safety constraints effectively reduce human-robot proximity
          events at an acceptable throughput cost compared to no safety or
          soft safety."
  Conditions: full_system, no_safety, soft_safety

Maps
----
  random           data/maps/random-64-64-10.map        (50 agents, 20 humans)
  warehouse_small  data/maps/warehouse-10-20-10-2-1.map (250 agents, 100 humans)

Statistical methodology
-------------------------------------------------
- Wilcoxon signed-rank test (paired, two-sided) vs full_system.
  Pairing is by seed: the SAME seed is used for the control and each
  ablation condition, giving maximal statistical power.
- Benjamini-Hochberg FDR correction applied within each group.
- Rank-biserial correlation r as standardized effect size.
- 95 % bootstrap confidence interval on the mean difference.
- Friedman test as omnibus within-group test before pairwise comparisons.
- Cohen's d as a familiar parametric effect size alongside rank-biserial r.
- Shapiro-Wilk test on paired differences to justify non-parametric choice.
- Post-hoc power estimate for each pairwise comparison.
- 10 seeds (default).
"""

from __future__ import annotations

import csv
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import types
from typing import Set, Tuple as _Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ha_lmapf.core.types import Metrics, SimConfig
from ha_lmapf.humans.safety import inflate_cells
from ha_lmapf.simulation.simulator import Simulator

Cell = _Tuple[int, int]


# ---------------------------------------------------------------------------
# Human-aware env proxy (used by ablation post-init hooks)
# ---------------------------------------------------------------------------
class _HumanAwareEnvProxy:
    """Thin proxy that makes human-occupied cells appear blocked to the solver.

    Delegates all attribute access to the real env, overriding only
    ``is_blocked`` and ``is_free`` to include human positions.  Agent
    start/goal cells are protected so the solver can still reach them.
    """

    __slots__ = ("_env", "_extra_blocked")

    def __init__(self, env, extra_blocked: frozenset):
        object.__setattr__(self, "_env", env)
        object.__setattr__(self, "_extra_blocked", extra_blocked)

    def is_blocked(self, cell: Cell) -> bool:
        if cell in self._extra_blocked:
            return True
        return self._env.is_blocked(cell)

    def is_free(self, cell: Cell) -> bool:
        if cell in self._extra_blocked:
            return False
        return self._env.is_free(cell)

    def __getattr__(self, name):
        return getattr(self._env, name)


try:
    from scipy.stats import (
        wilcoxon, mannwhitneyu, friedmanchisquare, shapiro,
    )

    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    print("[ablation_utils] WARNING: scipy not found — statistical tests "
          "disabled. Install: pip install scipy")

# ---------------------------------------------------------------------------
# Canonical maps
# ---------------------------------------------------------------------------
PRIMARY_MAP = "data/maps/random-64-64-10.map"
MAPS_ALL: Dict[str, str] = {
    "random": "data/maps/random-64-64-10.map",
    "warehouse_small": "data/maps/warehouse-10-20-10-2-1.map",
}

# Per-map default agent/human counts (matching lifelong agent-sweep study)
MAP_DEFAULTS: Dict[str, Dict[str, int]] = {
    "data/maps/random-64-64-10.map": {"num_agents": 50, "num_humans": 20},
    "data/maps/warehouse-10-20-10-2-1.map": {"num_agents": 250, "num_humans": 100},
}

# ---------------------------------------------------------------------------
# Ablation groups and conditions
# ---------------------------------------------------------------------------
# Each condition: Dict of SimConfig overrides applied on top of base_config.
# "group" key documents which Group A/B/C/D the condition belongs to.
# "label" is the display name for tables and plots.
# "description" is the one-sentence paper-justification.

CONTROL = "full_system"

ABLATION_CONDITIONS: Dict[str, Dict[str, Any]] = {

    # ── Group A: Tier Architecture ─────────────────────────────────────────
    "full_system": {
        "group": "A",
        "label": "Full System",
        "description": "Control: all tiers and safety features enabled.",
        "overrides": {},
    },
    "no_local_replan": {
        "group": "A",
        "label": "No Local Replan",
        "description": (
            "Tier-2 local replanning disabled; agents follow global plan "
            "only and wait when blocked by humans or other agents.  Global "
            "planner receives human positions as temporary obstacles."
        ),
        "overrides": {
            "disable_local_replan": True,
            "human_aware_global": True,
            "min_replan_gap": 5,
            "replan_every": 5,
            "fallback_wait_limit": 2,
        },
    },
    "no_conflict_resolution": {
        "group": "A",
        "label": "No Conflict Res.",
        "description": (
            "Decentralised conflict resolution (token-passing) disabled; "
            "agents wait when a conflict is detected instead of negotiating."
        ),
        "overrides": {"disable_conflict_resolution": True},
    },
    "global_only": {
        "group": "A",
        "label": "Global Only (RHCR)",
        "description": (
            "Both Tier-2 features disabled — closest to a pure RHCR baseline. "
            "Quantifies the total contribution of the local tier.  Global "
            "planner receives human positions as temporary obstacles."
        ),
        "overrides": {
            "disable_local_replan": True,
            "disable_conflict_resolution": True,
            "human_aware_global": True,
            "min_replan_gap": 5,
            "replan_every": 5,
            "fallback_wait_limit": 2,
        },
    },

    # ── Group B: Safety System ─────────────────────────────────────────────
    "no_safety": {
        "group": "B",
        "label": "No Safety",
        "description": (
            "Safety buffer completely disabled (disable_safety=True). "
            "Provides the throughput upper bound and near-miss lower bound "
            "in the absence of human avoidance."
        ),
        "overrides": {"disable_safety": True},
    },
    "soft_safety": {
        "group": "B",
        "label": "Soft Safety",
        "description": (
            "Safety zone treated as a high-cost region rather than a hard "
            "constraint.  Agents may enter the zone when no other move "
            "exists, preventing deadlock at the cost of occasional violations."
        ),
        "overrides": {"hard_safety": False},
    },
    # ── Group C: Task Allocation (disabled) ──────────────────────────────
}

# Ordered list for consistent output
CONDITION_ORDER = [
    # Group A
    "full_system", "no_local_replan", "no_conflict_resolution", "global_only",
    # Group B
    "no_safety", "soft_safety",
]

GROUP_LABELS = {
    "A": "Tier Architecture",
    "B": "Safety & Perception",
}

GROUP_ORDER = ["A", "B"]

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
METRIC_KEYS: List[str] = [
    "throughput", "completed_tasks", "task_completion",
    "mean_flowtime", "median_flowtime", "max_flowtime", "mean_service_time",
    "collisions_agent_agent", "collisions_agent_human",
    "near_misses", "safety_violations", "safety_violation_rate",
    "replans", "global_replans", "local_replans", "intervention_rate",
    "total_wait_steps", "human_passive_wait_steps",
    "mean_planning_time_ms", "p95_planning_time_ms", "max_planning_time_ms",
    "mean_decision_time_ms", "p95_decision_time_ms",
    "makespan", "sum_of_costs",
    "delay_events", "immediate_assignments",
    "assignments_kept", "assignments_broken",
]

# Metrics for statistical tests
STATS_METRICS: List[str] = [
    "throughput", "mean_flowtime", "near_misses",
    "safety_violations", "total_wait_steps", "mean_planning_time_ms",
    "collisions_agent_human", "local_replans", "assignments_broken",
]

# higher_is_better for each metric
METRIC_DIRECTION: Dict[str, bool] = {
    "throughput": True, "completed_tasks": True, "task_completion": True,
    "mean_flowtime": False, "median_flowtime": False, "max_flowtime": False,
    "mean_service_time": False,
    "collisions_agent_agent": False, "collisions_agent_human": False,
    "near_misses": False, "safety_violations": False,
    "safety_violation_rate": False,
    "replans": False, "global_replans": False, "local_replans": False,
    "intervention_rate": False, "total_wait_steps": False,
    "human_passive_wait_steps": False,
    "mean_planning_time_ms": False, "p95_planning_time_ms": False,
    "max_planning_time_ms": False,
    "mean_decision_time_ms": False, "p95_decision_time_ms": False,
    "makespan": False, "sum_of_costs": False, "delay_events": False,
    "immediate_assignments": True, "assignments_kept": True,
    "assignments_broken": False,
}


# ---------------------------------------------------------------------------
# Base configuration
# ---------------------------------------------------------------------------
def get_base_config(
        map_path: Optional[str] = None,
        num_agents: int = 50,
        num_humans: int = 20,
        steps: int = 2000,
        horizon: int = 20,
        replan_every: int = 10,
        fov_radius: int = 4,
        safety_radius: int = 1,
        commit_horizon: int = 0,
        delay_threshold: float = 0.0,
) -> Dict[str, Any]:
    """Base config — uses PBS and tuned defaults.

    All --best-* CLI args from the tuning pipeline should be passed here
    so ablations run on top of the fully-tuned baseline.
    """
    return {
        "map_path": map_path or PRIMARY_MAP,
        "task_stream_path": None,
        "steps": steps,
        "num_agents": num_agents,
        "num_humans": num_humans,
        "fov_radius": fov_radius,
        "safety_radius": safety_radius,
        "hard_safety": True,
        "global_solver": "lacam3",
        "replan_every": replan_every,
        "horizon": horizon,
        "time_budget_ms": 3000.0,
        "task_allocator": "congestion_avoidance",
        "commit_horizon": commit_horizon,
        "delay_threshold": delay_threshold,
        "task_arrival_rate": None,
        "task_arrival_percentage": 0.9,
        "communication_mode": "token",
        "local_planner": "astar",
        "human_model": "random_walk",
        "human_model_params": {},
        "execution_delay_prob": 0.0,
        "execution_delay_steps": 1,
        "disable_local_replan": False,
        "disable_conflict_resolution": False,
        "disable_safety": False,
        "seed": 0,
    }


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------
def make_output_dir(
        run_label: str = "",
        base_dir: str = "logs/ablation",
) -> Path:
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = f"{run_label}_{ts}" if run_label else ts
    out = Path(base_dir) / folder
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------
def _apply_ablation_hooks(sim: Simulator, config_dict: Dict[str, Any]) -> None:
    """Apply post-init ablation hooks that cannot be expressed as SimConfig overrides.

    This keeps all ablation-specific logic in the ablation layer without
    modifying the core simulator, rolling-horizon planner, or solver wrappers.

    Hooks:
      human_aware_global (bool): Monkey-patch the rolling-horizon planner so
          it wraps the environment with a proxy that marks current human
          positions as blocked.  This gives the global solver visibility into
          dynamic human obstacles — critical for ``no_local_replan`` and
          ``global_only`` conditions where the local tier cannot detour.
      min_replan_gap (int): Override the planner's emergency-replan cooldown.
          Prevents excessive global replans when many agents are stuck.
    """
    planner = sim.global_planner

    # --- 0. Prevent controllers from clearing global paths when local replan
    #         is disabled.  Without this, an agent that encounters a human
    #         immediately nulls its global path and can never resume until the
    #         next global replan, causing permanent gridlock. ----------------
    if config_dict.get("disable_local_replan", False):
        from ha_lmapf.core.grid import neighbors as _neighbors
        from ha_lmapf.core.grid import manhattan as _manhattan
        from ha_lmapf.core.types import StepAction as _StepAction
        from ha_lmapf.humans.safety import inflate_cells as _inflate

        disable_cr = config_dict.get("disable_conflict_resolution", False)

        def _make_ablation_decide(controller):
            """Build a simplified decide_action for no-local-replan conditions.

            Key differences from the original:
            1. Position-based plan tracking (not time-indexed) so waits
               don't cause plan drift.
            2. Safety checks on the actual adjacent cell, not a distant
               waypoint.
            3. When no plan cell is reachable, greedily pick the safest
               adjacent cell toward the goal.
            """
            aid = controller.agent_id

            def _decide(sim_state, observation, rng=None):
                agent = sim_state.agents[aid]
                cur = agent.pos
                goal = agent.goal if agent.goal is not None else cur
                if cur == goal:
                    return _StepAction.WAIT

                # Build forbidden set (human safety zones)
                human_cells = {h.pos for h in observation.visible_humans.values()}
                forbidden = _inflate(human_cells, radius=int(controller.safety_radius), env=sim_state.env)

                # Get direction from global plan (position-based)
                waypoint = _plan_next(sim_state, controller, cur)
                if waypoint is None:
                    waypoint = goal  # fallback: head toward goal

                # Compute the actual adjacent cell toward the waypoint
                actual_next = _best_adjacent(cur, waypoint, forbidden, human_cells,
                                             sim_state, controller, observation,
                                             disable_cr)
                if actual_next is None:
                    # No safe adjacent move — wait
                    controller._consecutive_waits += 1
                    if controller._consecutive_waits >= controller.fallback_wait_limit:
                        if hasattr(sim_state, "flag_major_deviation"):
                            sim_state.flag_major_deviation()
                        controller._consecutive_waits = 0
                    if hasattr(sim_state, "mark_safety_wait"):
                        sim_state.mark_safety_wait(aid)
                    return _StepAction.WAIT

                # Clear wait counter — agent is making progress
                controller._consecutive_waits = 0
                if hasattr(sim_state, "clear_safety_wait"):
                    sim_state.clear_safety_wait(aid)

                return controller.conflict_resolver.action_toward(cur, actual_next)

            controller.decide_action = _decide

        def _plan_next(sim_state, ctrl, cur):
            """Position-based plan cell lookup."""
            plans = sim_state.plans()
            if plans is None:
                return None
            path = plans.paths.get(ctrl.agent_id)
            if path is None:
                return None
            # Find current position in the plan and return the next distinct cell
            for i, c in enumerate(path.cells):
                if c == cur:
                    for j in range(i + 1, len(path.cells)):
                        if path.cells[j] != cur:
                            return path.cells[j]
            # Agent not on the plan — use the plan's next time-indexed cell
            nxt = path(sim_state.step + 1)
            return nxt if nxt != cur else None

        def _best_adjacent(cur, target, forbidden, human_cells,
                           sim_state, ctrl, obs, no_cr):
            """Pick the best safe adjacent cell toward target."""
            env = sim_state.env
            candidates = []
            for nb in _neighbors(cur):
                if not env.is_free(nb):
                    continue
                if nb in forbidden:
                    continue
                if nb in human_cells:
                    continue
                # Check agent-agent conflicts via decided positions
                decided = getattr(sim_state, "_decided_next_positions", {})
                if nb in decided.values():
                    if no_cr:
                        continue  # skip — can't resolve conflicts
                candidates.append((nb, _manhattan(nb, target)))

            if not candidates:
                return None
            # Pick the cell closest to the target
            candidates.sort(key=lambda x: x[1])
            return candidates[0][0]

        for ctrl in sim.controllers.values():
            _make_ablation_decide(ctrl)

    # --- 1. Replan cooldown ---------------------------------------------------
    min_gap = config_dict.get("min_replan_gap", 0)
    if min_gap and min_gap > 0:
        planner._min_emergency_gap = int(min_gap)

    human_aware = config_dict.get("human_aware_global", False)
    # Inflate human cells by this radius so the global planner avoids the
    # full safety zone, not just the human's exact cell.
    _safety_radius = int(config_dict.get("safety_radius", 1))

    # We always need to wrap the step method when either feature is active,
    # because the deviation-triggered replans bypass the built-in emergency
    # gap and need explicit throttling.
    if not human_aware and not (min_gap and min_gap > 0):
        return

    _orig_step = planner.step
    _replan_gap = int(min_gap) if (min_gap and min_gap > 0) else 0
    # Mutable state for the closure — tracks last non-periodic replan step
    _last_nonperiodic = {"step": -99999}

    def _patched_step(sim_state, assignments):
        """Wrapper adding human awareness and/or deviation-replan throttling."""
        cur_step = int(sim_state.step)

        # Throttle deviation-triggered replans: if this is NOT a periodic
        # step and the gap hasn't elapsed, suppress the deviation flag so
        # the planner skips this call.
        if _replan_gap > 0:
            periodic = (cur_step % planner.replan_every == 0)
            if not periodic and (cur_step - _last_nonperiodic["step"]) < _replan_gap:
                # Suppress deviation to prevent replan
                if hasattr(sim_state, "_major_deviation_flag"):
                    sim_state._major_deviation_flag = False
                return None

        # Human-aware env proxy
        target_sim_state = sim_state
        if human_aware:
            humans = getattr(sim_state, "humans", None)
            human_cells: Set[Cell] = set()
            if humans:
                human_cells = {h.pos for h in humans.values()}

            if human_cells:
                # Inflate human cells by safety radius so the global plan
                # avoids the full B_r(H_t) zone that agents enforce locally.
                inflated = inflate_cells(
                    human_cells, radius=_safety_radius, env=sim_state.env,
                )
                protected: Set[Cell] = set()
                agents = sim_state.agents
                for aid, agent in agents.items():
                    protected.add(agent.pos)
                    if agent.goal is not None:
                        protected.add(agent.goal)
                    elif aid in assignments:
                        protected.add(assignments[aid].goal)

                extra_blocked = frozenset(inflated - protected)
                if extra_blocked:
                    proxy_env = _HumanAwareEnvProxy(sim_state.env, extra_blocked)

                    class _SimStateShim:
                        """Delegates everything to the real sim_state except env."""

                        def __init__(self, real, proxy):
                            object.__setattr__(self, "_real", real)
                            object.__setattr__(self, "_proxy_env", proxy)

                        @property
                        def env(self):
                            return self._proxy_env

                        def __getattr__(self, name):
                            return getattr(self._real, name)

                    target_sim_state = _SimStateShim(sim_state, proxy_env)

        result = _orig_step(target_sim_state, assignments)

        # Track non-periodic replans for throttling
        if result is not None and _replan_gap > 0:
            periodic = (cur_step % planner.replan_every == 0)
            if not periodic:
                _last_nonperiodic["step"] = cur_step

        return result

    planner.step = _patched_step


def run_single_experiment(
        config_dict: Dict[str, Any],
        name: str,
        verbose: bool = False,
) -> Tuple[Metrics, float]:
    config = SimConfig(**{
        k: v for k, v in config_dict.items()
        if k in SimConfig.__dataclass_fields__
    })
    if verbose:
        print(f"  Running: {name} (seed={config.seed})")
    t0 = time.time()
    try:
        sim = Simulator(config)
        _apply_ablation_hooks(sim, config_dict)
        metrics = sim.run()
        wall = time.time() - t0
        if verbose:
            print(f"    tp={metrics.throughput:.4f}  "
                  f"nm={metrics.near_misses}  "
                  f"ft={metrics.mean_flowtime:.1f}")
        return metrics, wall
    except Exception as e:
        print(f"  ERROR in {name}: {e}")
        return Metrics(steps=config.steps), time.time() - t0


def _worker(args: Tuple[Dict[str, Any], str, bool]) -> Dict[str, Any]:
    cfg, name, verbose = args
    m, w = run_single_experiment(cfg, name, verbose)
    return {"_name": name, "_wall": w, "_metrics": asdict(m)}


# ---------------------------------------------------------------------------
# Ablation runner
# ---------------------------------------------------------------------------
def build_experiment_list(
        conditions: List[str],
        seeds: List[int],
        base_config: Dict[str, Any],
) -> List[Tuple[Dict[str, Any], str, Dict[str, Any]]]:
    """Build the full list of (config, name, meta) tuples."""
    tasks = []
    for cond_name in conditions:
        cond = ABLATION_CONDITIONS[cond_name]
        overrides = dict(cond["overrides"])

        for seed in seeds:
            cfg = base_config.copy()
            cfg.update(overrides)
            cfg["seed"] = seed
            name = f"{cond_name}_seed={seed}"
            tasks.append((cfg, name, {
                "condition": cond_name,
                "group": cond["group"],
                "label": cond["label"],
                "seed": seed,
            }))
    return tasks


def run_ablation_group(
        group_id: str,
        seeds: List[int],
        base_config: Dict[str, Any],
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run all conditions in one group, return per-seed result dicts."""
    conditions = [
        k for k in CONDITION_ORDER
        if ABLATION_CONDITIONS[k]["group"] == group_id
    ]
    # Always include full_system as control
    if CONTROL not in conditions:
        conditions = [CONTROL] + conditions

    steps = base_config.get("steps", 2000)
    tasks = build_experiment_list(conditions, seeds, base_config)
    total = len(tasks)
    print(f"\n{'=' * 60}")
    print(f"Group {group_id}: {GROUP_LABELS[group_id]}")
    print(f"  conditions={conditions}")
    print(f"  seeds={seeds}  workers={workers}  total={total} runs")
    print(f"{'=' * 60}")

    return _execute(tasks, steps, verbose, workers)


def run_all_groups(
        seeds: List[int],
        base_config: Dict[str, Any],
        groups: Optional[List[str]] = None,
        verbose: bool = False,
        workers: int = 1,
) -> List[Dict[str, Any]]:
    """Run selected (or all) groups sequentially, return combined results."""
    groups = groups or GROUP_ORDER
    all_results: List[Dict[str, Any]] = []
    for g in groups:
        results = run_ablation_group(
            g, seeds, base_config,
            verbose, workers,
        )
        all_results.extend(results)
    return all_results


def _execute(
        tasks: List[Tuple[Dict, str, Dict]],
        steps: int,
        verbose: bool,
        workers: int,
) -> List[Dict[str, Any]]:
    total = len(tasks)
    results: List[Dict[str, Any]] = []

    if workers <= 1:
        for n, (cfg, name, meta) in enumerate(tasks, 1):
            print(f"\n[{n}/{total}] {name}")
            m, w = run_single_experiment(cfg, name, verbose)
            results.append({**meta, "wall_time_sec": w, **asdict(m)})
    else:
        print(f"  Dispatching {total} jobs to {workers} workers ...")
        args = [(cfg, nm, verbose) for cfg, nm, _ in tasks]
        meta_map = {nm: meta for _, nm, meta in tasks}
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_worker, a): a[1] for a in args}
            for fut in as_completed(futs):
                nm = futs[fut]
                done += 1
                meta = meta_map[nm]
                try:
                    r = fut.result()
                    print(f"  [{done}/{total}] done: {nm}")
                    results.append({
                        **meta, "wall_time_sec": r["_wall"],
                        **r["_metrics"],
                    })
                except Exception as exc:
                    print(f"  [{done}/{total}] ERROR {nm}: {exc}")
                    results.append({
                        **meta, "wall_time_sec": 0.0,
                        **asdict(Metrics(steps=steps)),
                    })
    return results


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def _wilcoxon_p(x: List[float], y: List[float]) -> float:
    if not _HAS_SCIPY or len(x) < 5:
        return float("nan")
    n = min(len(x), len(y))
    try:
        _, p = wilcoxon(x[:n], y[:n], alternative="two-sided")
        return float(p)
    except Exception:
        return float("nan")


def _rank_biserial(x: List[float], y: List[float]) -> float:
    """Rank-biserial r as effect size.  Positive = x > y."""
    if not _HAS_SCIPY or not x or not y:
        return float("nan")
    try:
        stat, _ = mannwhitneyu(x, y, alternative="two-sided")
        r = 1.0 - 2.0 * stat / (len(x) * len(y))
        return float(r)
    except Exception:
        return float("nan")


def _bootstrap_ci(vals: List[float], n_boot: int = 2000) -> Tuple[float, float]:
    a = np.array(vals, dtype=float)
    if len(a) < 2:
        v = float(a[0]) if len(a) else float("nan")
        return v, v
    if len(a) < 10:
        se = np.std(a, ddof=1) / np.sqrt(len(a))
        m = np.mean(a)
        return float(m - 1.96 * se), float(m + 1.96 * se)
    rng = np.random.default_rng(42)
    boot = np.array([
        np.mean(rng.choice(a, size=len(a), replace=True))
        for _ in range(n_boot)
    ])
    return float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def _fdr_bh(pvalues: List[float]) -> List[float]:
    """Benjamini-Hochberg FDR correction; returns adjusted p-values."""
    n = len(pvalues)
    if n == 0:
        return []
    pairs = sorted(
        [(i, p) for i, p in enumerate(pvalues) if not np.isnan(p)],
        key=lambda x: x[1],
    )
    adj = [float("nan")] * n
    cum_min = float("inf")
    for rev_rank, (idx, p) in enumerate(reversed(pairs), 1):
        corr = p * len(pairs) / (len(pairs) - rev_rank + 1)
        cum_min = min(cum_min, corr)
        adj[idx] = min(cum_min, 1.0)
    return adj


def _cohens_d(x: List[float], y: List[float]) -> float:
    """Cohen's d (pooled) — positive means x > y."""
    if len(x) < 2 or len(y) < 2:
        return float("nan")
    mx, my = np.mean(x), np.mean(y)
    sx, sy = np.std(x, ddof=1), np.std(y, ddof=1)
    nx, ny = len(x), len(y)
    pooled = np.sqrt(((nx - 1) * sx ** 2 + (ny - 1) * sy ** 2) / (nx + ny - 2))
    if pooled == 0:
        return float("nan")
    return float((mx - my) / pooled)


def _shapiro_wilk_on_diffs(x: List[float], y: List[float]) -> float:
    """Shapiro-Wilk p on paired differences.  p < 0.05 → non-normal."""
    if not _HAS_SCIPY or len(x) < 5:
        return float("nan")
    n = min(len(x), len(y))
    diffs = np.array(x[:n]) - np.array(y[:n])
    if np.all(diffs == diffs[0]):
        return float("nan")
    try:
        _, p = shapiro(diffs)
        return float(p)
    except Exception:
        return float("nan")


def _friedman_omnibus(
        control_vals: List[float],
        ablation_groups: List[List[float]],
) -> float:
    """Friedman chi-square test across ≥3 related samples (seeds as blocks).

    Returns the p-value.  Requires all groups to have the same length (n_seeds).
    Use as an omnibus test before pairwise Wilcoxon within a group.
    """
    if not _HAS_SCIPY or len(ablation_groups) < 2:
        return float("nan")
    n = len(control_vals)
    # Ensure all groups are the same length
    groups = [control_vals[:n]]
    for g in ablation_groups:
        if len(g) < n:
            return float("nan")
        groups.append(g[:n])
    try:
        _, p = friedmanchisquare(*groups)
        return float(p)
    except Exception:
        return float("nan")


def _post_hoc_power(
        x: List[float], y: List[float], alpha: float = 0.05,
) -> float:
    """Approximate post-hoc power for a two-sided paired Wilcoxon test.

    Uses the normal approximation of the asymptotic relative efficiency
    (ARE = 3/π ≈ 0.955 for Wilcoxon vs t-test).  Provides a rough
    estimate; exact power requires simulation.
    """
    n = min(len(x), len(y))
    if n < 5:
        return float("nan")
    diffs = np.array(x[:n]) - np.array(y[:n])
    sd = np.std(diffs, ddof=1)
    if sd == 0:
        return 1.0 if np.mean(diffs) != 0 else float("nan")
    d = abs(np.mean(diffs)) / sd  # paired Cohen's d
    # ARE adjustment: effective n for Wilcoxon ≈ n * (π/3)
    n_eff = n * (np.pi / 3.0)
    # non-centrality parameter
    ncp = d * np.sqrt(n_eff)
    # power ≈ Φ(ncp - z_{α/2})
    z_alpha = 1.96  # two-sided α=0.05
    from scipy.stats import norm
    power = float(norm.cdf(ncp - z_alpha) + norm.cdf(-ncp - z_alpha))
    return min(max(power, 0.0), 1.0)


def _pct_change(val: float, ref: float) -> float:
    if ref == 0 or np.isnan(ref) or np.isnan(val):
        return float("nan")
    return (val - ref) / abs(ref) * 100.0


# ---------------------------------------------------------------------------
# Aggregation — per condition, vs full_system control
# ---------------------------------------------------------------------------
def aggregate_ablation_results(
        results: List[Dict[str, Any]],
        control_name: str = CONTROL,
) -> List[Dict[str, Any]]:
    """Aggregate per-seed rows; compute stats vs the control condition.

    For each (condition, group) pair:
      - mean, std, 95-CI for every metric
      - percent change from full_system mean
      - Wilcoxon p (paired by seed) vs full_system
      - FDR-corrected q within the group
      - Rank-biserial r effect size
    """
    # Group raw results by condition
    by_cond: Dict[str, List[Dict]] = defaultdict(list)
    for r in results:
        by_cond[r["condition"]].append(r)

    # Sort each condition's results by seed for paired tests
    for cond in by_cond:
        by_cond[cond].sort(key=lambda x: x.get("seed", 0))

    # Get control seed-aligned values
    ctrl_rows = by_cond.get(control_name, [])
    ctrl_by_seed = {r["seed"]: r for r in ctrl_rows}
    ctrl_seeds_sorted = sorted(ctrl_by_seed.keys())

    def _ctrl_vals(metric: str) -> List[float]:
        return [float(ctrl_by_seed[s].get(metric, 0.0))
                for s in ctrl_seeds_sorted]

    agg_rows: List[Dict[str, Any]] = []
    for cond_name in CONDITION_ORDER:
        if cond_name not in by_cond:
            continue
        rows = sorted(by_cond[cond_name], key=lambda x: x.get("seed", 0))
        cond_info = ABLATION_CONDITIONS[cond_name]

        row: Dict[str, Any] = {
            "condition": cond_name,
            "label": cond_info["label"],
            "group": cond_info["group"],
            "group_name": GROUP_LABELS[cond_info["group"]],
            "n_seeds": len(rows),
            "description": cond_info["description"],
        }

        for metric in METRIC_KEYS + ["wall_time_sec"]:
            vals = [float(r.get(metric, 0.0)) for r in rows]
            ctrl_v = _ctrl_vals(metric)

            row[f"{metric}_mean"] = float(np.mean(vals))
            row[f"{metric}_std"] = float(
                np.std(vals, ddof=1) if len(vals) > 1 else 0.0
            )
            ci_lo, ci_hi = _bootstrap_ci(vals)
            row[f"{metric}_ci95_lo"] = ci_lo
            row[f"{metric}_ci95_hi"] = ci_hi

            if ctrl_v:
                row[f"{metric}_pct_change"] = _pct_change(
                    float(np.mean(vals)), float(np.mean(ctrl_v))
                )
            else:
                row[f"{metric}_pct_change"] = float("nan")

        agg_rows.append(row)

    # Wilcoxon + effect sizes + normality + power
    for metric in STATS_METRICS:
        p_col = f"{metric}_wilcoxon_p"
        r_col = f"{metric}_effect_r"
        d_col = f"{metric}_cohens_d"
        sw_col = f"{metric}_shapiro_p"
        pw_col = f"{metric}_power"
        ctrl_v = _ctrl_vals(metric)
        for row in agg_rows:
            cond = row["condition"]
            rows_c = sorted(by_cond[cond], key=lambda x: x.get("seed", 0))
            vals = [float(r.get(metric, 0.0)) for r in rows_c]
            if cond == control_name or not ctrl_v:
                row[p_col] = float("nan")
                row[r_col] = float("nan")
                row[d_col] = float("nan")
                row[sw_col] = float("nan")
                row[pw_col] = float("nan")
                continue
            n = min(len(vals), len(ctrl_v))
            row[p_col] = _wilcoxon_p(vals[:n], ctrl_v[:n])
            row[r_col] = _rank_biserial(vals, ctrl_v)
            row[d_col] = _cohens_d(vals, ctrl_v)
            row[sw_col] = _shapiro_wilk_on_diffs(vals[:n], ctrl_v[:n])
            row[pw_col] = _post_hoc_power(vals[:n], ctrl_v[:n])

    # BH FDR correction per group
    for group in GROUP_ORDER:
        grp_rows = [r for r in agg_rows if r["group"] == group]
        for metric in STATS_METRICS:
            p_col = f"{metric}_wilcoxon_p"
            q_col = f"{metric}_fdr_q"
            ps = [r.get(p_col, float("nan")) for r in grp_rows]
            qs = _fdr_bh(ps)
            for row, q in zip(grp_rows, qs):
                row[q_col] = q

    # Friedman omnibus test per group (across all conditions in the group)
    for group in GROUP_ORDER:
        grp_rows = [r for r in agg_rows if r["group"] == group]
        non_ctrl = [r for r in grp_rows if r["condition"] != control_name]
        if len(non_ctrl) < 2:
            for row in grp_rows:
                for metric in STATS_METRICS:
                    row[f"{metric}_friedman_p"] = float("nan")
            continue

        for metric in STATS_METRICS:
            ctrl_v = _ctrl_vals(metric)
            ablation_groups = []
            for row in non_ctrl:
                cond = row["condition"]
                rows_c = sorted(
                    by_cond[cond], key=lambda x: x.get("seed", 0)
                )
                ablation_groups.append(
                    [float(r.get(metric, 0.0)) for r in rows_c]
                )
            friedman_p = _friedman_omnibus(ctrl_v, ablation_groups)
            for row in grp_rows:
                row[f"{metric}_friedman_p"] = friedman_p

    return agg_rows


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
def save_results(
        results: List[Dict[str, Any]],
        aggregated: List[Dict[str, Any]],
        output_dir: Path,
        latex: bool = True,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    if results:
        p = output_dir / "results.csv"
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print(f"Saved raw results:  {p}")

    if aggregated:
        p = output_dir / "summary.csv"
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=aggregated[0].keys())
            writer.writeheader()
            writer.writerows(aggregated)
        print(f"Saved summary:      {p}")

    if latex and aggregated:
        p = output_dir / "table.tex"
        _write_latex(aggregated, p)
        print(f"Saved LaTeX table:  {p}")


def _sig_stars(p: float) -> str:
    if np.isnan(p):
        return ""
    if p < 0.001:
        return "$^{***}$"
    if p < 0.01:
        return "$^{**}$"
    if p < 0.05:
        return "$^{*}$"
    return "ns"


def _write_latex(aggregated: List[Dict[str, Any]], path: Path) -> None:
    """Write a per-group booktabs LaTeX table with full statistical reporting."""
    table_metrics = [
        ("throughput", r"\textbf{Throughput}$\uparrow$"),
        ("mean_flowtime", r"Flowtime$\downarrow$"),
        ("near_misses", r"Near Misses$\downarrow$"),
        ("collisions_agent_human", r"Collisions$\downarrow$"),
        ("mean_planning_time_ms", r"Plan. Time (ms)$\downarrow$"),
        ("total_wait_steps", r"Wait Steps$\downarrow$"),
    ]

    n_seeds = aggregated[0].get("n_seeds", 30) if aggregated else 30

    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Ablation study results (mean $\pm$ std, "
        f"{n_seeds} seeds). "
        r"Each group compares against \textbf{Full System}. "
        r"Stars: $^{*}p{<}0.05$, $^{**}p{<}0.01$, $^{***}p{<}0.001$ "
        r"(Wilcoxon signed-rank, Benjamini-Hochberg FDR corrected). "
        r"$d$ = Cohen's $d$; $1{-}\beta$ = post-hoc power. "
        r"Friedman omnibus $p$ reported per group when $\geq 3$ conditions. "
        r"\%$\Delta$ = percent change vs Full System.}",
        r"\label{tab:ablation}",
        r"\setlength{\tabcolsep}{2.5pt}",
        r"\footnotesize",
        r"\begin{tabular}{ll" + "r" * len(table_metrics) + "rrrr}",
        r"\toprule",
    ]

    header = r"\textbf{Group} & \textbf{Condition}"
    for _, col_label in table_metrics:
        header += f" & {col_label}"
    header += (
        r" & \textbf{\%$\Delta$ TP} & \textbf{$q$}"
        r" & \textbf{$d$} & \textbf{$1{-}\beta$} \\"
    )
    lines.append(header)

    for group in GROUP_ORDER:
        grp_rows = [r for r in aggregated if r["group"] == group]
        if not grp_rows:
            continue
        lines.append(r"\midrule")

        # Friedman omnibus p for the group
        friedman_p = grp_rows[0].get("throughput_friedman_p", float("nan"))
        friedman_str = ""
        if not np.isnan(friedman_p):
            friedman_str = (
                rf" (Friedman $\chi^2$ $p={friedman_p:.3g}$)"
            )

        lines.append(
            r"\multicolumn{" + str(len(table_metrics) + 6) + r"}{l}{"
                                                             r"\textit{Group " + group + r": " +
            GROUP_LABELS[group] + friedman_str + r"}} \\"
        )

        for row in grp_rows:
            is_ctrl = row["condition"] == CONTROL
            label = row["label"]
            if is_ctrl:
                label = r"\textbf{" + label + "}"
            line = f"{GROUP_LABELS[row['group']][:8]} & {label}"

            for metric, _ in table_metrics:
                mean = row.get(f"{metric}_mean", float("nan"))
                std = row.get(f"{metric}_std", float("nan"))
                cell = f"{mean:.3f}$\\pm${std:.3f}"
                if is_ctrl:
                    cell = r"\textbf{" + cell + "}"
                line += f" & {cell}"

            pct = row.get("throughput_pct_change", float("nan"))
            q = row.get("throughput_fdr_q", float("nan"))
            d = row.get("throughput_cohens_d", float("nan"))
            pwr = row.get("throughput_power", float("nan"))
            pct_str = f"{pct:+.1f}\\%" if not np.isnan(pct) else "--"
            if is_ctrl:
                line += r" & -- & -- & -- & -- \\"
            else:
                d_str = f"{d:.2f}" if not np.isnan(d) else "--"
                pwr_str = f"{pwr:.2f}" if not np.isnan(pwr) else "--"
                line += (
                    f" & {pct_str} & {_sig_stars(q)}"
                    f" & {d_str} & {pwr_str} \\\\"
                )
            lines.append(line)

    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table*}"]
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Console summary
# ---------------------------------------------------------------------------
def print_group_summary(
        aggregated: List[Dict[str, Any]],
        group: str,
        primary: str = "throughput",
        secondary: List[str] = None,
) -> None:
    if secondary is None:
        secondary = ["mean_flowtime", "near_misses", "mean_planning_time_ms"]

    grp_rows = [r for r in aggregated if r["group"] == group]
    if not grp_rows:
        return

    def _fmt(v, is_pct=False):
        if np.isnan(v):
            return "   nan"
        return f"{v:+6.1f}%" if is_pct else f"{v:8.4f}"

    w = 14
    cols = [primary] + secondary
    print(f"\n{'─' * 70}")
    print(f"Group {group}: {GROUP_LABELS[group]}")
    print(f"{'─' * 70}")
    # Print Friedman omnibus p for the group
    friedman_p = grp_rows[0].get(f"{primary}_friedman_p", float("nan"))
    if not np.isnan(friedman_p):
        sig = "***" if friedman_p < 0.001 else "**" if friedman_p < 0.01 \
            else "*" if friedman_p < 0.05 else "ns"
        print(f"  Friedman omnibus: χ² p={friedman_p:.4f} ({sig})")

    hdr = f"{'Condition':<28}"
    for c in cols:
        hdr += f"  {c[:w]:>{w}}"
    hdr += f"  {'%Δ TP':>8}  {'p':>8}  {'q':>8}  {'|r|':>6}  {'d':>6}  {'pwr':>5}"
    print(hdr)
    print("─" * len(hdr))

    for row in grp_rows:
        name = row["label"][:27]
        line = f"{name:<28}"
        for c in cols:
            m = row.get(f"{c}_mean", float("nan"))
            s = row.get(f"{c}_std", float("nan"))
            line += f"  {m:>8.3f}±{s:<5.3f}"
        pct = row.get(f"{primary}_pct_change", float("nan"))
        p = row.get(f"{primary}_wilcoxon_p", float("nan"))
        q = row.get(f"{primary}_fdr_q", float("nan"))
        r = abs(row.get(f"{primary}_effect_r", float("nan")))
        d = row.get(f"{primary}_cohens_d", float("nan"))
        pwr = row.get(f"{primary}_power", float("nan"))
        stars = (
            "***" if not np.isnan(q) and q < 0.001 else
            "**" if not np.isnan(q) and q < 0.01 else
            "*" if not np.isnan(q) and q < 0.05 else "ns"
            if not np.isnan(q) else "—"
        )
        pct_s = f"{pct:+.1f}%" if not np.isnan(pct) else "  —"
        p_s = f"{p:.4f}" if not np.isnan(p) else "  nan"
        q_s = f"{q:.4f}" if not np.isnan(q) else "  nan"
        r_s = f"{r:.3f}" if not np.isnan(r) else " nan"
        d_s = f"{abs(d):.3f}" if not np.isnan(d) else " nan"
        pwr_s = f"{pwr:.2f}" if not np.isnan(pwr) else "  nan"
        line += f"  {pct_s:>8}  {p_s:>8}  {q_s:>8}{stars:>4}  {r_s:>6}  {d_s:>6}  {pwr_s:>5}"
        print(line)

    print("─" * len(hdr))
    print("Stars on q: *** <0.001  ** <0.01  * <0.05  ns not significant")
    print("|r|: 0.1 small · 0.3 medium · 0.5 large")
    print("|d|: 0.2 small · 0.5 medium · 0.8 large")
    print("pwr: post-hoc power (1-β at α=0.05)\n")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------
def add_common_args(parser) -> None:
    parser.add_argument("--seeds", type=int, nargs="+",
                        default=list(range(10)),
                        help="Random seeds (default: 0–9, i.e. 10 seeds)")
    parser.add_argument("--map", type=str, default=PRIMARY_MAP)
    parser.add_argument("--agents", type=int, default=50)
    parser.add_argument("--humans", type=int, default=20)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--workers", "-j", type=int, default=1,
                        help="Parallel workers (0 = all cores)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--output", type=str, default="logs/ablation")
    parser.add_argument("--label", type=str, default="")
    parser.add_argument("--no-latex", action="store_true")
    # Multi-map and scale sensitivity
    parser.add_argument(
        "--maps", nargs="+", default=None,
        help=(
            "Run ablation across multiple maps (default: primary map only). "
            "Use map aliases: warehouse_large, warehouse_small, room — "
            "or full paths."
        ),
    )
    parser.add_argument(
        "--scale-configs", nargs="+", default=None,
        help=(
            "Scale sensitivity: agents:humans pairs, e.g. '10:2 20:5 40:10'. "
            "Runs the full ablation for each scale config."
        ),
    )
    parser.add_argument(
        "--warmup-steps", type=int, default=0,
        help=(
            "Discard the first N steps as warm-up before computing metrics. "
            "Recommended: 500-1000 for steady-state analysis."
        ),
    )
    # Tuned planning parameters (from tuning pipeline)
    parser.add_argument("--best-horizon", type=int, default=20)
    parser.add_argument("--best-replan-every", type=int, default=10)
    parser.add_argument("--best-fov-radius", type=int, default=4)
    parser.add_argument("--best-safety-radius", type=int, default=1)
    parser.add_argument("--best-commit-horizon", type=int, default=0)
    parser.add_argument("--best-delay-threshold", type=float, default=0.0)


def resolve_workers(n: int) -> int:
    if n <= 0:
        import multiprocessing
        n = multiprocessing.cpu_count()
        print(f"Auto-detected {n} CPU cores.")
    return n
