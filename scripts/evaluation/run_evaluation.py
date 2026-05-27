# !/usr/bin/env python3
"""
Comprehensive Evaluation Runner for HA-LMAPF Paper.

Runs all experiment scenarios across multiple seeds and baselines,
collecting metrics for the evaluation section.

Usage:
    # Run all experiments (default 15 seeds)
    python scripts/evaluation/run_evaluation.py --out logs/eval

    # Run specific experiment group
    python scripts/evaluation/run_evaluation.py --group baselines --out logs/eval

    # Run with custom seeds
    python scripts/evaluation/run_evaluation.py --seeds 0 1 2 3 4 --out logs/eval

Experiment Groups:
    all              - Run everything (default)
    baselines        - Compare our method vs 5 baselines on 4 maps (15 seeds)
    scalability      - Throughput vs number of agents (per-map sweeps)
    human_density    - Performance vs number of humans
    human_models     - Robustness to different human behaviors
    map_types        - Performance across map topologies
    ablations        - Component ablation study
    delay_robustness - Execution delay injection (5%-20%)
    arrival_rate     - Task arrival rate variation
    robustness       - Narrow corridors, dense maps, adversarial
    no_humans        - Mirror configs without humans (for comparison)
    classic_mapf     - One-shot classical MAPF experiments
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

project_root = str(Path(__file__).resolve().parent.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ha_lmapf.core.types import Metrics, SimConfig
from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(path: str) -> SimConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    known_keys = set(SimConfig.__annotations__.keys())
    filtered: Dict[str, Any] = {k: v for k, v in data.items() if k in known_keys}
    return SimConfig(**filtered)


def config_from_dict(base: SimConfig, overrides: Dict[str, Any]) -> SimConfig:
    from dataclasses import asdict
    d = asdict(base)
    d.update(overrides)
    known_keys = set(SimConfig.__annotations__.keys())
    return SimConfig(**{k: v for k, v in d.items() if k in known_keys})


# ---------------------------------------------------------------------------
# Baseline wiring
# ---------------------------------------------------------------------------

def _run_baseline_sim(config: SimConfig, baseline_name: str) -> Tuple[Simulator, float]:
    """
    Create and run a simulator configured for a specific baseline.

    Baselines:
      - "ours": Full two-tier (default behavior)
      - "global_only": Tier-1 only, no local replanning around humans
      - "pibt_only": Decentralized PIBT-like, no global planner
      - "rhcr": Standard RHCR (periodic CBS/LaCAM, no local safety)
      - "whca_star": WHCA* prioritized planning
      - "ignore_humans": Our architecture but human-blind
    """
    t0 = time.time()
    sim = Simulator(config)

    if baseline_name == "global_only":
        from ha_lmapf.baselines.global_only_replan import GlobalOnlyController
        for aid in sorted(sim.agents.keys()):
            sim.controllers[aid] = GlobalOnlyController(  # type: ignore[assignment]
                agent_id=aid,
                conflict_resolver=sim.conflict_solver,
            )

    elif baseline_name == "pibt_only":
        from ha_lmapf.baselines.pibt_only import PIBTOnlyController
        from ha_lmapf.local_tier.conflict_resolution.priority_rules import PriorityRulesResolver
        resolver = PriorityRulesResolver()
        for aid in sorted(sim.agents.keys()):
            sim.controllers[aid] = PIBTOnlyController(  # type: ignore[assignment]
                agent_id=aid,
                resolver=resolver,
            )

    elif baseline_name == "rhcr":
        from ha_lmapf.baselines.rhcr_like import RHCRPlanner
        sim.global_planner = RHCRPlanner(  # type: ignore[assignment]
            horizon=config.horizon,
            replan_every=max(1, config.replan_every // 5),
            solver_name=config.global_solver,
        )
        from ha_lmapf.baselines.global_only_replan import GlobalOnlyController
        for aid in sorted(sim.agents.keys()):
            sim.controllers[aid] = GlobalOnlyController(  # type: ignore[assignment]
                agent_id=aid,
                conflict_resolver=sim.conflict_solver,
            )

    elif baseline_name == "whca_star":
        from ha_lmapf.baselines.whca_star import WHCAStarPlanner
        sim.global_planner = WHCAStarPlanner(  # type: ignore[assignment]
            horizon=config.horizon,
            replan_every=config.replan_every,
            window=min(16, config.horizon),
        )
        from ha_lmapf.baselines.global_only_replan import GlobalOnlyController
        for aid in sorted(sim.agents.keys()):
            sim.controllers[aid] = GlobalOnlyController(  # type: ignore[assignment]
                agent_id=aid,
                conflict_resolver=sim.conflict_solver,
            )

    elif baseline_name == "ignore_humans":
        from ha_lmapf.baselines.ignore_humans import mask_out_humans
        from ha_lmapf.local_tier.agent_controller import AgentController
        original_controllers = dict(sim.controllers)

        class HumanBlindController:
            def __init__(self, inner: AgentController):
                self._inner = inner
                self.agent_id = inner.agent_id

            def decide_action(self, sim_state: Any, observation: Any, rng: Any = None) -> Any:
                masked = mask_out_humans(observation)
                return self._inner.decide_action(sim_state, masked, rng)

        for aid in sorted(sim.agents.keys()):
            sim.controllers[aid] = HumanBlindController(original_controllers[aid])  # type: ignore[assignment]

    metrics = sim.run()
    elapsed = time.time() - t0
    return sim, elapsed


# ---------------------------------------------------------------------------
# Single experiment run
# ---------------------------------------------------------------------------

def run_single(
        config: SimConfig, seed: int, baseline: str, out_dir: Path,
        save_replay: bool = False,
) -> Optional[Metrics]:
    cfg = config_from_dict(config, {"seed": seed})
    label = f"[{baseline}] seed={seed} agents={cfg.num_agents} humans={cfg.num_humans}"
    print(f"  {label} ...", end=" ", flush=True)

    try:
        sim, elapsed = _run_baseline_sim(cfg, baseline)
        metrics = sim.metrics.finalize(total_steps=sim.step)
        print(f"done ({elapsed:.1f}s) "
              f"tput={metrics.throughput:.4f} "
              f"sv={metrics.safety_violations} "
              f"plan_ms={metrics.mean_planning_time_ms:.1f} "
              f"done={metrics.completed_tasks} ({round(metrics.task_completion * 100, 1)}%)")
        if save_replay:
            sim.replay.write(str(out_dir / f"replay_{baseline}_seed{seed}.json"))
        return metrics
    except Exception as e:
        print(f"FAILED: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Experiment definitions
# ---------------------------------------------------------------------------

def _base_warehouse_config() -> SimConfig:
    """
    Base configuration for warehouse experiments.

    Parameters match the paper's Section E defaults exactly:
      H=50, K=25, ρ=4, r=1, arrival_rate=10, commit_horizon=25,
      delay_threshold=2.5, 20 agents, 5 humans, warehouse map.
    """
    return SimConfig(
        map_path="data/maps/warehouse-10-20-10-2-1.map",
        steps=2000,
        num_agents=20,
        num_humans=5,
        fov_radius=4,
        safety_radius=1,
        global_solver="lacam",
        replan_every=25,
        horizon=50,
        communication_mode="token",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="lifelong",
        task_allocator="congestion_avoidance",
        task_arrival_rate=10,
        commit_horizon=25,
        delay_threshold=2.5,
    )


# ---------------------------------------------------------------------------
# Baseline map configurations
# ---------------------------------------------------------------------------
# Same 4 maps used in the global solver comparison study
# (compare_global_study_agents.py), ensuring consistency across studies.
# Agent and human counts are scaled per map topology.

BASELINE_MAP_CONFIGS: Dict[str, Dict[str, Any]] = {
    "warehouse_small": {
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "num_agents": 25,
        "num_humans": 5,
    },
    "warehouse_large": {
        "map_path": "data/maps/warehouse-20-40-10-2-2.map",
        "num_agents": 100,
        "num_humans": 10,
    },
    "random": {
        "map_path": "data/maps/random-64-64-10.map",
        "num_agents": 25,
        "num_humans": 5,
    },
}

# ---------------------------------------------------------------------------
# Scalability map configurations
# ---------------------------------------------------------------------------
# Per-map agent sweep ranges and fixed human counts for scalability study.
# Small maps use fewer agents; large maps scale up to 500.

SCALABILITY_MAP_CONFIGS: Dict[str, Dict[str, Any]] = {
    "random": {
        "map_path": "data/maps/random-64-64-10.map",
        "agent_counts": [25, 50, 75, 100],
        "num_humans": 50,
    },
    "warehouse_small": {
        "map_path": "data/maps/warehouse-10-20-10-2-2.map",
        "agent_counts": [25, 50, 75, 100],
        "num_humans": 50,
    },
    "warehouse_large": {
        "map_path": "data/maps/warehouse-20-40-10-2-2.map",
        "agent_counts": [100, 200, 300, 400, 500],
        "num_humans": 400,
    },
}


def get_experiment_groups() -> Dict[str, List[Tuple[str, SimConfig, List[str]]]]:
    base = _base_warehouse_config()
    groups: Dict[str, List[Tuple[str, SimConfig, List[str]]]] = {}

    # All baselines including WHCA*
    all_baselines = ["ours", "global_only", "pibt_only", "rhcr", "whca_star", "ignore_humans"]

    # ------- 1. BASELINES -------
    # Run all 6 methods across 4 maps (matching the solver comparison study).
    # Each map has its own agent/human counts scaled to map topology.
    baselines_group = []
    for map_tag, map_cfg in BASELINE_MAP_CONFIGS.items():
        cfg = config_from_dict(base, map_cfg)
        baselines_group.append((f"baselines_{map_tag}", cfg, all_baselines))
    groups["baselines"] = baselines_group

    # ------- 2. SCALABILITY (agents sweep per map) -------
    # Each map has its own agent range and fixed human count.
    # Horizon/replan adjusted for high agent counts on large maps.
    scalability = []
    for map_tag, map_cfg in SCALABILITY_MAP_CONFIGS.items():
        for n in map_cfg["agent_counts"]:
            rpe = 25 if n <= 300 else 50
            h = 50 if n <= 300 else 80
            cfg = config_from_dict(base, {
                "map_path": map_cfg["map_path"],
                "num_agents": n,
                "num_humans": map_cfg["num_humans"],
                "steps": 1000,
                "replan_every": rpe,
                "horizon": h,
            })
            scalability.append((f"scale_{map_tag}_{n}", cfg, ["ours"]))
    groups["scalability"] = scalability

    # ------- 3. HUMAN DENSITY -------
    human_density = []
    for h in [0, 5, 10, 20]:
        cfg = config_from_dict(base, {"num_humans": h})
        human_density.append((f"humans_{h}", cfg, ["ours"]))
    groups["human_density"] = human_density

    # ------- 4. HUMAN MODELS -------
    # Paper uses random walk (with inertia) and aisle-following only.
    # Adversarial model is available in code but excluded from paper experiments.
    human_models = []
    for model, params in [
        ("random_walk", {}),
        ("aisle", {"alpha": 1.0, "beta": 1.5}),
    ]:
        cfg = config_from_dict(base, {
            "human_model": model, "human_model_params": params, "num_humans": 10,
        })
        human_models.append((f"hmodel_{model}", cfg, ["ours"]))
    groups["human_models"] = human_models

    # ------- 5. MAP TYPES -------
    map_types = []
    for name, mpath, n_agents in [
        ("warehouse", "data/maps/warehouse-10-20-10-2-1.map", 20),
        ("random", "data/maps/random-32-32-20.map", 20),
        ("room", "data/maps/room-32-32-4.map", 20),
        ("maze", "data/maps/maze-32-32-4.map", 15),
        ("empty", "data/maps/empty-32-32.map", 30),
    ]:
        cfg = config_from_dict(base, {
            "map_path": mpath, "num_agents": n_agents, "steps": 1500,
        })
        map_types.append((f"map_{name}", cfg, ["ours"]))
    groups["map_types"] = map_types

    # ------- 6. ABLATIONS (architectural component study) -------
    ablations = []

    # Hard vs soft safety
    for hard in [True, False]:
        cfg = config_from_dict(base, {"hard_safety": hard, "num_humans": 10})
        ablations.append((f"safety_{'hard' if hard else 'soft'}", cfg, ["ours"]))

    # Solver comparison (Python implementations)
    # CBS is optimal but exponentially slow; LaCAM is fast and scalable
    for solver, na in [
        ("cbs", 15),  # Optimal CBS (exponential complexity)
        ("lacam", 20),  # Fast LaCAM — baseline solver
    ]:
        cfg = config_from_dict(base, {"global_solver": solver, "num_agents": na})
        ablations.append((f"solver_{solver}", cfg, ["ours"]))

    # Official C++ solver comparison - Kei18 (if binaries are installed)
    # Agent counts match configs/eval/solver_*.yaml
    for solver, na, h in [
        ("lacam3", 50, 60),
        ("lacam_official", 50, 60),
        ("pibt2", 100, 60),
    ]:
        cfg = config_from_dict(base, {
            "global_solver": solver, "num_agents": na, "horizon": h,
        })
        ablations.append((f"solver_{solver}", cfg, ["ours"]))

    # Official C++ solver comparison - Jiaoyang-Li (if binaries are installed)
    # rhcr: Rolling-Horizon Collision Resolution (lifelong focused)
    # cbsh2: CBS with Heuristics (optimal, slower)
    # eecbs: Explicit Estimation CBS (bounded-suboptimal)
    # pbs: Priority-Based Search (fast, scalable)
    # lns2: Large Neighborhood Search (anytime, huge scale)
    for solver, na in [
        ("rhcr", 50),  # Lifelong solver, handles many agents
        ("cbsh2", 20),  # Optimal solver, slower - fewer agents
        ("eecbs", 40),  # Bounded-suboptimal, moderate agents
        ("pbs", 60),  # Fast scalable solver
        ("lns2", 100),  # Anytime solver, scales to many agents
    ]:
        cfg = config_from_dict(base, {"global_solver": solver, "num_agents": na})
        ablations.append((f"solver_{solver}", cfg, ["ours"]))

    # Allocator comparison
    for alloc in ["greedy", "hungarian", "auction", "congestion_avoidance"]:
        cfg = config_from_dict(base, {"task_allocator": alloc})
        ablations.append((f"allocator_{alloc}", cfg, ["ours"]))

    # Communication mode
    for comm in ["token", "priority"]:
        cfg = config_from_dict(base, {"communication_mode": comm})
        ablations.append((f"comm_{comm}", cfg, ["ours"]))

    # Disable individual components
    cfg_no_local = config_from_dict(base, {"disable_local_replan": True, "num_humans": 10})
    ablations.append(("no_local_replan", cfg_no_local, ["ours"]))

    cfg_no_cr = config_from_dict(base, {"disable_conflict_resolution": True, "num_humans": 10})
    ablations.append(("no_conflict_res", cfg_no_cr, ["ours"]))

    cfg_no_safety = config_from_dict(base, {"disable_safety": True, "num_humans": 10})
    ablations.append(("no_safety_buffer", cfg_no_safety, ["ours"]))

    groups["ablations"] = ablations

    # ------- 7. DELAY ROBUSTNESS -------
    delay_exps = []
    for prob in [0.0, 0.05, 0.10, 0.20]:
        pct = int(prob * 100)
        cfg = config_from_dict(base, {
            "execution_delay_prob": prob,
            "execution_delay_steps": 2,
            "num_humans": 5,
        })
        delay_exps.append((f"delay_{pct}pct", cfg, ["ours"]))
    groups["delay_robustness"] = delay_exps

    # ------- 8. TASK ARRIVAL RATE -------
    arrival_exps = []
    for rate in [5, 10, 25, 50]:
        cfg = config_from_dict(base, {"task_arrival_rate": rate})
        arrival_exps.append((f"arrival_rate_{rate}", cfg, ["ours"]))
    groups["arrival_rate"] = arrival_exps

    # ------- 9. ROBUSTNESS (narrow, dense) -------
    robustness = []

    # Narrow corridors
    cfg = config_from_dict(base, {
        "map_path": "data/maps/maze-32-32-2.map",
        "num_agents": 15, "num_humans": 5, "steps": 1500,
    })
    robustness.append(("narrow_corridor", cfg, ["ours"]))

    # Dense map (20% obstacle density)
    cfg = config_from_dict(base, {
        "map_path": "data/maps/random-32-32-20.map",
        "num_agents": 20, "num_humans": 5, "steps": 1500,
    })
    robustness.append(("dense_map", cfg, ["ours"]))

    # Note: adversarial human model is available in code but excluded
    # from paper experiments. Use configs/human_adversarial.yaml to
    # run it manually if needed.

    groups["robustness"] = robustness

    # ------- 9b. CITY MAP (large-scale generalization) -------
    cfg = config_from_dict(base, {
        "map_path": "data/maps/Berlin_1_256.map",
        "num_agents": 50,
        "num_humans": 10,
        "steps": 1000,
        "horizon": 80,
        "replan_every": 50,
    })
    robustness.append(("city_berlin", cfg, ["ours"]))

    # ------- 10. NO HUMANS (comparison to human-aware) -------
    # Mirror key experiments but with num_humans=0 for comparison
    no_humans = []

    # Baseline warehouse without humans
    cfg = config_from_dict(base, {"num_humans": 0})
    no_humans.append(("warehouse_no_humans", cfg, all_baselines))

    # Scalability without humans
    for n in [10, 25, 50, 100]:
        cfg = config_from_dict(base, {
            "map_path": "data/maps/warehouse-20-40-10-2-1.map",
            "num_agents": n,
            "num_humans": 0,
            "steps": 1000,
            "replan_every": 25,
        })
        no_humans.append((f"scale_no_humans_{n}", cfg, ["ours"]))

    # Map types without humans
    for name, mpath, n_agents in [
        ("warehouse", "data/maps/warehouse-10-20-10-2-1.map", 20),
        ("random", "data/maps/random-32-32-20.map", 20),
        ("room", "data/maps/room-32-32-4.map", 20),
        ("maze", "data/maps/maze-32-32-4.map", 15),
        ("empty", "data/maps/empty-32-32.map", 30),
    ]:
        cfg = config_from_dict(base, {
            "map_path": mpath,
            "num_agents": n_agents,
            "num_humans": 0,
            "steps": 1500,
        })
        no_humans.append((f"map_{name}_no_humans", cfg, ["ours"]))

    groups["no_humans"] = no_humans

    # ------- 11. CLASSIC MAPF (one-shot, no lifelong tasks) -------
    classic_mapf = []

    # One-shot MAPF without humans (pure classical MAPF)
    cfg_oneshot_base = SimConfig(
        map_path="data/maps/random-32-32-20.map",
        steps=500,
        num_agents=10,
        num_humans=0,
        fov_radius=4,
        safety_radius=1,
        global_solver="cbs",
        replan_every=1,  # Not used in one-shot
        horizon=200,
        communication_mode="token",
        local_planner="astar",
        human_model="random_walk",
        hard_safety=True,
        mode="one_shot",
        task_allocator="congestion_avoidance",
    )
    classic_mapf.append(("oneshot_cbs_no_humans", cfg_oneshot_base, ["ours"]))

    # One-shot with LaCAM solver
    cfg = config_from_dict(cfg_oneshot_base, {"global_solver": "lacam"})
    classic_mapf.append(("oneshot_lacam_no_humans", cfg, ["ours"]))

    # One-shot with humans (human-aware classical MAPF)
    cfg = config_from_dict(cfg_oneshot_base, {"num_humans": 5})
    classic_mapf.append(("oneshot_cbs_with_humans", cfg, ["ours"]))

    cfg = config_from_dict(cfg_oneshot_base, {"global_solver": "lacam", "num_humans": 5})
    classic_mapf.append(("oneshot_lacam_with_humans", cfg, ["ours"]))

    # Scalability for one-shot MAPF
    for n in [5, 10, 20, 30, 50]:
        cfg = config_from_dict(cfg_oneshot_base, {
            "num_agents": n,
            "global_solver": "lacam",  # CBS too slow for large instances
            "horizon": max(200, n * 10),
        })
        classic_mapf.append((f"oneshot_scale_{n}", cfg, ["ours"]))

    # Different maps for one-shot MAPF
    for name, mpath, n_agents in [
        ("warehouse", "data/maps/warehouse-10-20-10-2-1.map", 15),
        ("random", "data/maps/random-32-32-20.map", 15),
        ("room", "data/maps/room-32-32-4.map", 15),
        ("maze", "data/maps/maze-32-32-4.map", 10),
        ("empty", "data/maps/empty-32-32.map", 20),
    ]:
        cfg = config_from_dict(cfg_oneshot_base, {
            "map_path": mpath,
            "num_agents": n_agents,
            "global_solver": "lacam",
        })
        classic_mapf.append((f"oneshot_map_{name}", cfg, ["ours"]))

    groups["classic_mapf"] = classic_mapf

    return groups


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_experiment_group(
        group_name: str,
        experiments: List[Tuple[str, SimConfig, List[str]]],
        seeds: List[int],
        out_dir: Path,
        save_replay: bool = False,
) -> None:
    group_dir = out_dir / group_name
    group_dir.mkdir(parents=True, exist_ok=True)

    csv_path = group_dir / "results.csv"
    header = ["experiment", "baseline", "seed", "num_agents", "num_humans"] + MetricsTracker.csv_header()

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        f.flush()

        for exp_name, config, baselines in experiments:
            print(f"\n{'=' * 60}")
            print(f"Experiment: {exp_name}")
            print(f"{'=' * 60}")

            exp_dir = group_dir / exp_name
            exp_dir.mkdir(parents=True, exist_ok=True)

            for bl in baselines:
                for seed in seeds:
                    metrics = run_single(
                        config, seed, bl, exp_dir,
                        save_replay=(save_replay and seed == seeds[0]),
                    )
                    if metrics is not None:
                        tracker = MetricsTracker()
                        row = [exp_name, bl, str(seed),
                               str(config.num_agents), str(config.num_humans),
                               ] + tracker.to_csv_row(metrics)
                        writer.writerow(row)
                        f.flush()

    print(f"\nResults written to {csv_path}")


def main():
    all_group_names = [
        "all", "baselines", "scalability", "human_density", "human_models",
        "map_types", "ablations", "delay_robustness", "arrival_rate", "robustness",
        "no_humans", "classic_mapf",
    ]

    parser = argparse.ArgumentParser(
        description="HA-LMAPF Comprehensive Evaluation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--group", type=str, default="all", choices=all_group_names)
    parser.add_argument("--seeds", type=int, nargs="+",
                        default=list(range(10)))
    parser.add_argument("--out", type=str, default="logs/eval")
    parser.add_argument("--save-replay", action="store_true")
    parser.add_argument("--config", type=str, default=None,
                        help="Override: run a single config file with all baselines")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = args.seeds

    print(f"HA-LMAPF Evaluation")
    print(f"  Output:     {out_dir}")
    print(f"  Seeds:      {seeds}")
    print(f"  Group:      {args.group}")
    print()

    if args.config:
        cfg = load_config(args.config)
        all_baselines = ["ours", "global_only", "pibt_only", "rhcr", "whca_star", "ignore_humans"]
        experiments = [(Path(args.config).stem, cfg, all_baselines)]
        run_experiment_group("custom", experiments, seeds, out_dir, args.save_replay)
        return

    all_groups = get_experiment_groups()

    if args.group == "all":
        groups_to_run = list(all_groups.keys())
    else:
        groups_to_run = [args.group]

    for gname in groups_to_run:
        if gname not in all_groups:
            print(f"Unknown group: {gname}")
            continue
        run_experiment_group(gname, all_groups[gname], seeds, out_dir, args.save_replay)

    _write_summary(out_dir, groups_to_run)
    print(f"\nAll experiments complete. Results in {out_dir}/")


def _write_summary(out_dir: Path, groups: List[str]) -> None:
    summary_path = out_dir / "summary.csv"
    first = True
    with open(summary_path, "w", newline="") as out_f:
        writer = csv.writer(out_f)
        for gname in groups:
            csv_path = out_dir / gname / "results.csv"
            if not csv_path.exists():
                continue
            with open(csv_path, "r") as in_f:
                reader = csv.reader(in_f)
                header = next(reader)
                if first:
                    writer.writerow(["group"] + header)
                    first = False
                for row in reader:
                    writer.writerow([gname] + row)
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
