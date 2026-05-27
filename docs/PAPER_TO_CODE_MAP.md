# Paper ↔ Code Map (POE-LMAPF)

A single table mapping every symbol, definition, algorithm, and
theorem in paper Sections 3-5 to its implementing file, class, or
function in this repository.  Use this as the canonical cross-
reference when reading the paper alongside the code.

> *Terminology.*  The paper writes **exogenous agent**; the codebase
> writes ``human`` (e.g. ``HumanState``, ``humans/`` package).  The
> two terms are interchangeable.

## Section 3 — Problem definition

| Paper symbol / concept                              | Code location                                                                 |
|-----------------------------------------------------|-------------------------------------------------------------------------------|
| Grid graph $G = (V, E)$                              | ``simulation/environment.py::Environment``                                    |
| Static obstacle set                                  | ``Environment.blocked``                                                       |
| Controlled agent state $s_i(t)$                      | ``core/types.py::AgentState.pos``                                              |
| Controlled agent set $A$                             | ``Simulator.agents`` (``Dict[int, AgentState]``)                               |
| Exogenous agent state $h_j(t)$                       | ``core/types.py::HumanState`` (``.pos``, ``.velocity``)                        |
| Exogenous agent set $X(t)$                           | ``Simulator.humans``                                                            |
| Pickup-delivery task $\tau$                          | ``core/types.py::Task``                                                        |
| Lifelong task stream $T$                             | ``Simulator._pending_tasks`` / ``Simulator.open_tasks``                        |
| FoV radius $r_{\mathit{fov}}$                        | ``SimConfig.fov_radius``                                                       |
| Safety radius $r_{\mathit{safe}}$                    | ``SimConfig.safety_radius``                                                     |
| Decision-time observation $\Phi_i(t)$                | ``local_tier/sensors.py::build_observation`` (returns ``core/types.py::Observation``) |
| Observed exogenous agents $X^{\Phi_i}_t$             | ``Observation.visible_humans`` filtered by ``manhattan(.,.) ≤ fov_radius``     |
| Manhattan ball $B_{r}(\cdot)$ (free-cell-truncated) | ``humans/safety.py::inflate_cells``                                            |
| Forbidden set $F = B_{r_{\mathit{safe}}}(X^{\Phi_i}_t) \cup D(t)_{\mathit{ext}}$ | constructed in ``local_tier/agent_controller.py::AgentController.decide_action`` (var ``forbidden`` ∪ ``observation.blocked``) |
| Decision table $D(t)$                                | ``Simulator._decided_next_positions``  (read via ``Simulator.decided_next_positions()``) |
| Bounded-step exogenous-agent dynamics                | ``humans/models.py::HumanModel.step`` and subclasses                           |
| Decision-time snapshot of $X(t)$                     | ``Simulator.step_once`` captures ``humans_at_decision = dict(self.humans)`` after phase 4 |

### §3.4 Violation attribution

| Paper concept                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Violation pair $(a_i, h)$                            | inner loop of ``Simulator._detect_collisions_and_near_misses`` (phase 8)        |
| Agent-attributable violation                         | ``Metrics.violations_agent_attributable``  (set when ``moved`` AND any observed $h'$ within $r_{\mathit{safe}}$) |
| Exogenous-attributable violation                     | ``Metrics.violations_exogenous_attributable``                                  |
| Legacy ``safety_violations`` = sum of the above      | ``Metrics.safety_violations`` (invariant tested in ``tests/test_metrics_invariants.py``) |
| Wait-fraction $\sum w_i / (k\,T)$                    | ``Metrics.wait_fraction``                                                       |
| Safe-Wait vs. Yield-Wait split                       | ``Metrics.safe_wait_steps`` + ``Metrics.yield_wait_steps`` (invariant: equal to ``total_wait_steps``) |

## Section 4 — Algorithms

### §4.2 Tier-1 (Algorithm 1)

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Algorithm 1 (rolling-horizon planner)                | ``global_tier/rolling_horizon.py::RollingHorizonPlanner``                       |
| Horizon $H$                                          | ``RollingHorizonPlanner.horizon`` ← ``SimConfig.horizon`` (default 20)          |
| Replan period $R$                                    | ``RollingHorizonPlanner.replan_every`` ← ``SimConfig.replan_every`` (default 10) |
| Periodic trigger $t \bmod R = 0$                     | ``RollingHorizonPlanner.step`` predicate ``periodic``                           |
| Major-deviation trigger                              | ``Simulator.flag_major_deviation`` + ``RollingHorizonPlanner.step::deviation``  |
| Exhaustion trigger (stale plans ≥ 0.4)               | ``RollingHorizonPlanner._exhaustion_trigger``                                   |
| Safety-wait fraction trigger                         | ``RollingHorizonPlanner._safety_wait_trigger``                                  |
| **$\eta_w$ emergency trigger** (paper §4.4)          | ``RollingHorizonPlanner._eta_w_trigger`` reads ``AgentState.last_action_was_safe_wait`` |
| $\eta_w$ threshold                                   | ``SimConfig.eta_w`` (default 0.20)                                              |
| Anti-thrash gap                                      | ``SimConfig.replan_min_gap`` (default 3)                                        |
| Per-call solver budget                               | ``SimConfig.solver_timeout_s`` (default 10.0 s)                                 |
| Solver factory (LaCAM\*, CBSH2-RTC, …)               | ``global_tier/planner_interface.py::GlobalPlannerFactory.create``               |
| Greedy nearest-task allocator                        | ``task_allocator/task_allocator.py::GreedyNearestTaskAllocator``                |
| Commitment persistence ($K_c$, $\alpha$)             | ``Simulator.assign_tasks`` (uses ``commit_horizon``, ``delay_threshold``)        |

### §4.3 Tier-2 (Algorithm 2)

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Algorithm 2 (per-agent control loop)                 | ``local_tier/agent_controller.py::AgentController.decide_action``               |
| Sense                                                 | ``local_tier/sensors.py::build_observation``                                   |
| Forbidden set construction                           | lines marked ``# Build human-aware forbidden set`` in ``decide_action``         |
| Hard-safety enforcement                              | ``decide_action`` block at "Hard safety enforcement: never enter the inflated safety buffer" |
| Local A\* with $F$ in blocked                        | ``decide_action`` calls ``self.local_planner.plan(env, start, goal, blocked, guidance_cells)`` |
| Soft-safety escape                                   | ``decide_action::_find_escape_move``                                            |
| Safe-Wait flag (single-step)                         | ``AgentState.last_action_was_safe_wait`` (set by ``AgentController._safe_wait``) |
| Yield-Wait flag (single-step)                        | ``AgentState.last_action_was_yield_wait`` (set by ``AgentController._yield_wait``) |
| Decision-table write                                 | ``Simulator.step_once`` phase 5: ``self._decided_next_positions[aid] = next_pos`` |
| Decision-table read by other agents                  | ``conflict_resolution/base.py::detect_imminent_conflict``                       |

### §4.4 Conflict resolution & priority tuple

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Priority tuple $\rho_i = (-d_i + \beta\,\mathbf{1}[w_i > w^\ast],\, w_i,\, -i)$ | ``conflict_resolution/priority_rules.py::PriorityRulesResolver._priority`` |
| Starvation threshold $w^\ast$                        | ``PriorityRulesResolver.starvation_threshold`` (default 10)                     |
| Urgency boost $\beta$                                | ``PriorityRulesResolver.boost`` (default 50)                                    |
| Token resolver (with comms)                          | ``conflict_resolution/token_passing.py::TokenPassingResolver``                  |
| Fairness rotation period $K_{\mathit{fair}}$         | ``TokenPassingResolver.fairness_k`` (default 5)                                 |
| Loser fallback respects $F$ (Theorem 1 invariant)    | ``PriorityRulesResolver._safe_side_step`` and ``_astar_fallback`` (filter against ``forbidden``); same in ``TokenPassingResolver`` |
| F plumbed through resolver                           | ``AgentController.decide_action`` call to ``conflict_resolver.resolve(..., forbidden=forbidden, local_planner=self.local_planner)`` |

### §4.5 Theorem 1 (Conditional Safety)

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Theorem 1 statement                                  | ``docs/proposed_approach.md`` §F                                                |
| Theorem 1 base case (initialization)                 | ``Simulator._place_entities`` (F_init exclusion) + ``Simulator._assert_init_invariant`` + ``tests/test_init_invariant.py`` |
| Empirical 0-violation invariant                      | ``Metrics.violations_agent_attributable == 0`` post-finalize                    |
| Resolver-fallback invariant tests                    | ``tests/test_theorem1_resolver.py``                                             |
| End-to-end stress test                               | ``tests/test_theorem1_stress.py``                                               |
| Audit trail (pre-/post-fix)                          | ``docs/REVISION_AUDIT.md`` §11                                                  |

### Local A\* parameters

| Paper symbol                                         | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Local A\* expansion cap $N_{\max}$ (paper bound: 500) | ``local_tier/local_planner.py::AStarLocalPlanner.MAX_EXPANSIONS = 10_000`` (see TODO note in §G of ``proposed_approach.md``) |
| Soft-safety blocked-cell cost                        | ``AStarLocalPlanner.BLOCKED_CELL_COST = 50``                                    |
| Path-aligned guidance bias                           | ``AStarLocalPlanner.GUIDANCE_DEVIATION_COST = 1``                               |

## Section 5 — Experiments

### §5.1 Setup

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Default parameter table                              | ``configs/eval/default.yaml`` (canonical), ``core/types.py::SimConfig`` defaults |
| Simulation length $T = 2000$                         | ``SimConfig.steps``                                                             |
| Solver default = LaCAM                               | ``SimConfig.global_solver = "lacam_official"``                                  |
| Per-map exogenous-model wiring                       | ``ha_lmapf.io.default_map_to_human_model`` + ``Simulator._resolve_per_map_human_model`` |
| Maps                                                  | ``data/maps/random-64-64-10.map``, ``data/maps/warehouse-10-20-10-2-1.map``, ``data/maps/warehouse-10-20-10-2-2.map`` |
| Map dimension test                                   | ``tests/test_map_loading.py``                                                   |
| Map download script                                  | ``scripts/download_maps.sh`` + ``data/maps/README.md``                          |

### §5.3 Safety-radius sweep

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| $r_{\mathit{safe}} \in \{0, 1, 2, 3\}$                | ``SimConfig.safety_radius`` per-experiment override                             |
| ``inflate_cells`` correctness at $r = 0$             | ``tests/test_inflate_cells.py``                                                 |

### §5.4 $\eta_w$ sweep                                                                   

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| $\eta_w$ trigger                                     | ``RollingHorizonPlanner._eta_w_trigger``                                        |
| Trigger event counter                                | ``RollingHorizonPlanner.emergency_replans_eta_w``                               |
| Test                                                  | ``tests/test_emergency_replan.py``                                              |

### §5.5 Baselines

| Paper baseline                                       | Code factory                                                                   |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| **Ours (POE-LMAPF)**                                 | direct ``SimConfig`` (paper-aligned defaults)                                   |
| **RHCR** (exogenous-blind end-to-end)                | ``baselines/pibt2_fr.py::make_rhcr_blind_config``                                |
| **PIBT2-FR**                                         | ``baselines/pibt2_fr.py::make_pibt2_fr_config``                                  |
| **No-Buffer**                                        | ``baselines/pibt2_fr.py::make_no_buffer_config``                                 |
| Rigid-follower controller                            | ``SimConfig.controller_kind = "global_only"`` → ``baselines/global_only_replan.py::GlobalOnlyController`` |
| Audit & rationale                                    | ``docs/REVISION_AUDIT.md`` §12                                                  |
| Smoke tests                                           | ``tests/test_baseline_pibt2_fr.py``, ``tests/test_baseline_no_buffer.py``, ``tests/test_rhcr_blind.py`` |

### Solver-status table

| Paper concept                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| Six-solver sweep table                               | ``docs/SOLVER_STATUS.md``                                                       |
| §5.1 "partial solutions returned by anytime solvers are still used" | LaCAM3, LNS2, PIBT2 wrappers' ``partial_anytime`` branch in ``BaseSolverWrapper._wrap_subprocess`` decision tree; consumed by ``RollingHorizonPlanner.step`` |
| §5.2 Table 1 solver-internal runtime ms              | ``SolverResult.solver_wall_ms`` parsed per wrapper; per-source map in ``docs/SOLVER_STATUS.md`` (``comp_time=`` for LaCAM/LaCAM\*/PIBT2; CSV ``runtime`` × 1000 for CBSH2/LNS2/PBS) |
| Calibration's ``solver_recommendation.md`` input     | ``SolverResult.status`` (5-way) + ``SolverResult.end_to_end_wall_ms`` + ``SolverResult.solver_wall_ms`` |
| Cross-wrapper migration manifest                     | ``BaseSolverWrapper.MIGRATION_DEPTH`` + ``tests/test_full_migration_manifest.py`` |
| ``Metrics.solver_timeouts``                          | ``timeout_no_result`` occurrences (``rolling_horizon.py``)                       |
| ``Metrics.solver_partial_returns``                   | ``partial_anytime`` occurrences (``rolling_horizon.py``)                          |
| ``Metrics.solver_errors``                            | ``error`` and ``binary_not_found`` occurrences (``rolling_horizon.py``)           |
| ``SolverResult`` dataclass                           | ``ha_lmapf.core.types.SolverResult`` + ``SolverStatus`` Literal                  |
| Single-source-of-truth status decision tree          | ``solvers/_base.py::BaseSolverWrapper._wrap_subprocess``                         |
| Solver smoke tests                                   | ``tests/test_solver_smoke.py``                                                  |
| Timeout-enforcement test                             | ``tests/test_solver_timeout.py``                                                |
| Solver timeout metric                                | ``Metrics.solver_timeouts``                                                     |

### Statistics

| Paper element                                        | Code location                                                                  |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| 10 seeds (0–9), paired                               | ``scripts/evaluation/run_paper_experiment.py`` ``--seeds`` (default 0–9)         |
| Statistical methodology (paper appendix)             | ``scripts/evaluation/statistical_analysis.py``                                   |
| Friedman omnibus + Kendall's $W$                     | ``statistical_analysis.py::compute_friedman_per_metric``                          |
| Wilcoxon signed-rank + BH-FDR                        | ``statistical_analysis.py::compute_pair_stats`` (Wilcoxon) + ``_bh_fdr``          |
| Bootstrap 95 % CI (BCa)                              | ``statistical_analysis.py::_bca_ci_diff``                                         |
| Cohen's $d$ + rank-biserial $r$                      | ``statistical_analysis.py::compute_pair_stats``                                   |
| Shapiro-Wilk on paired diffs                         | ``statistical_analysis.py::compute_pair_stats`` (``scipy.stats.shapiro``)         |
| Post-hoc power (paired-$t$ proxy)                    | ``statistical_analysis.py::_ttest_paired_power``                                  |
| Descriptive stats (mean / std / median / IQR / skew) | ``statistical_analysis.py::compute_descriptive_per_condition``                     |
| Auto-invocation hook                                 | ``run_paper_experiment.py`` reads ``reference_condition`` / ``statistical_groupby`` from YAML |
| Per-experiment YAMLs                                  | ``configs/eval/``                                                                |

## Open TODOs flagged by the doc-update pass

These are mismatches the documentation pass surfaced; none can be
fixed without a code change, so they are flagged here.

1. **Local A\* expansion cap**: paper §4.3 states $N_{\max} = 500$;
   the implementation at ``local_planner.py:47`` uses
   ``MAX_EXPANSIONS = 10_000``.  Behaviour is identical when the
   search terminates naturally (which it does on the paper's three
   maps), and Theorem 1 still holds when the cap fires (the agent
   commits Safe Wait).  Either (a) lower the constant to 500, or
   (b) update the paper to match.
2. **MyopicPredictor**: the SoCS2026 README and code shipped with an
   explicit *Predict* stage (``humans/prediction.py``).  The paper
   text omits this stage from Algorithm 2.  The code keeps the module
   but the controller no longer invokes it on the main path; this is
   a documentation-only inconsistency that has been called out in
   ``proposed_approach.md`` and ``README_LOCAL_TIER.md``.
3. **Sequential decision-table vs. Observation timing**: phase-5
   observations are built before the decide loop clears
   ``_decided_next_positions``, so each agent's ``Observation.blocked``
   reflects the *previous* tick's decisions.  Current-tick
   sequentiality is achieved through ``detect_imminent_conflict``
   reading ``sim_state.decided_next_positions()`` directly.  Paper
   §4.3 doesn't distinguish the two; documented here and in
   ``simulation/README_SIMULATION.md`` §"Step order".
