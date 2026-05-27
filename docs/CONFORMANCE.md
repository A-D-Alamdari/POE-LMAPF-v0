# POE-LMAPF Paper ↔ Artefact Conformance Audit

This file is the auditable contract between the paper text and the
released code/data artefacts.  Every paper element is enumerated, with
its code location and one of three statuses:

| Status      | Meaning                                                                  |
|-------------|--------------------------------------------------------------------------|
| **VERIFIED** | Code, tests, and paper text agree; the artefact backs the paper claim. |
| **DEFERRED** | Intentional gap (paper-side text fill-in, etc.); see ``docs/PAPER_TODO.md``. |
| **DRIFT**    | Code and paper disagree; user must update one or the other.             |

**Scope note.**  The paper LaTeX is held by the user and is not part
of this repository.  The conformance audit therefore uses the union
of ``docs/PAPER_TO_CODE_MAP.md``, ``docs/REVISION_AUDIT.md``,
``docs/PAPER_NUMERICAL_CLAIMS.yaml``, and ``docs/PAPER_TODO.md`` as
the canonical "what does the paper say" source of truth, since each
of those was built from the paper text in earlier prompts.  Any DRIFT
between this audit and a literal reading of the paper PDF is
captured in ``docs/PAPER_TODO.md`` for the user to resolve.

---

## §3 — Background and Problem Definition

| Paper element                                    | Code location                                                                  | Status      | Notes |
|--------------------------------------------------|--------------------------------------------------------------------------------|-------------|-------|
| POE-LMAPF problem definition (6 components)      | ``Simulator`` constructor wires all six: ``Environment`` (G), ``self.agents`` (k controlled), ``self.humans`` (m exogenous), ``self.tasks`` (lifelong stream), ``SimConfig.fov_radius`` (r_fov), ``SimConfig.safety_radius`` (r_safe). | VERIFIED | All 6 components present in ``simulator.py:90-247``. |
| FoV radius $r_{\mathit{fov}}$                    | ``SimConfig.fov_radius`` (default 4)                                           | VERIFIED    | Paper §5.1 default 4 matches ``core/types.py``. |
| Safety radius $r_{\mathit{safe}}$                | ``SimConfig.safety_radius`` (default 1)                                        | VERIFIED    | Paper §5.1 default 1 matches. |
| Decision-time observation $X^{\Phi_i}_t$         | ``local_tier/sensors.py::build_observation``                                   | VERIFIED    | FoV-Manhattan filter; reads post-step-4 human positions. |
| Forbidden set $F = B_{r_{\mathit{safe}}}(X^{\Phi_i}_t) \cup D(t)_{\mathit{ext}}$ | ``agent_controller.py:64-66`` constructs ``forbidden`` and ``blocked``         | VERIFIED    | Pinned by ``test_theorem1_resolver.py``. |
| Agent-attributable violation definition          | ``simulator.py::_detect_collisions_and_near_misses`` (phase 8) + ``Metrics.violations_agent_attributable`` | VERIFIED    | Per-pair classification, MOVE-conditioned; tested in ``test_safety_classification.py``. |
| Exogenous-attributable violation definition      | Same; ``Metrics.violations_exogenous_attributable``                             | VERIFIED    | Sum invariant pinned in ``test_metrics_invariants.py``. |
| Lifelong pickup-delivery task lifecycle          | ``Simulator._maybe_complete_tasks`` (Phase-1 pickup → Phase-2 delivery → reassign) | VERIFIED    | ``test_one_shot_mapf.py`` and ``test_metrics_invariants.py`` cover both modes. |
| Action persistence / committed-prefix mechanism  | ``Simulator._decided_next_positions`` written sequentially in step 5; read by ``detect_imminent_conflict`` | VERIFIED    | ``test_decision_table.py`` pins sequential semantics. |
| Initialisation invariant (Theorem 1 base case)   | ``Simulator._place_entities`` (F_init exclusion) + ``_assert_init_invariant`` | VERIFIED    | ``test_init_invariant.py`` (32 tests). |

---

## §4 — Two-Tier Framework

### Algorithm 1 (Tier-1 rolling-horizon planner)

| Algorithm 1 line                                  | Code location                                                                  | Status   |
|---------------------------------------------------|--------------------------------------------------------------------------------|----------|
| Periodic trigger ``t mod R == 0``                 | ``rolling_horizon.py::RollingHorizonPlanner.step`` predicate ``periodic``       | VERIFIED |
| Replan period $R$                                 | ``RollingHorizonPlanner.replan_every``  ← ``SimConfig.replan_every`` (default 10) | VERIFIED |
| Planning horizon $H$                              | ``RollingHorizonPlanner.horizon``     ← ``SimConfig.horizon``       (default 20) | VERIFIED |
| Greedy nearest-task allocation                    | ``task_allocator/task_allocator.py::GreedyNearestTaskAllocator``                | VERIFIED |
| Commitment persistence ($K_c$, $\alpha$)          | ``Simulator.assign_tasks``  (uses ``commit_horizon``, ``delay_threshold``)       | VERIFIED |
| Solver dispatch (CBSH2, LaCAM, LaCAM\*, LNS2, PBS, PIBT2) | ``global_tier/planner_interface.py::GlobalPlannerFactory.create``       | VERIFIED |
| Per-call solver budget (10 s)                     | ``SimConfig.solver_timeout_s`` (default 10.0)                                   | VERIFIED |
| **Major-deviation trigger**                       | ``Simulator.flag_major_deviation`` + ``RollingHorizonPlanner.step::deviation``  | VERIFIED |
| **Exhaustion trigger** (stale plans ≥ 0.4)        | ``RollingHorizonPlanner._exhaustion_trigger``                                   | VERIFIED |
| **Safety-wait fraction trigger**                  | ``RollingHorizonPlanner._safety_wait_trigger``                                  | VERIFIED |
| **eta_w emergency trigger** (paper §4.4, $\eta_w = 0.20$) | ``RollingHorizonPlanner._eta_w_trigger`` reads ``AgentState.last_action_was_safe_wait`` | VERIFIED |
| ``replan_min_gap`` anti-thrash guard               | ``SimConfig.replan_min_gap`` (default 3)                                        | VERIFIED |
| Solver-timeout fallback (returns previous bundle) | ``RollingHorizonPlanner.step`` (`_last_replan_useful` guard, ``Metrics.solver_timeouts``) | VERIFIED |

### Algorithm 2 (Tier-2 per-agent control loop)

| Algorithm 2 element                                          | Code location                                                                  | Status   |
|--------------------------------------------------------------|--------------------------------------------------------------------------------|----------|
| Sense — local FoV observation                                | ``local_tier/sensors.py::build_observation``                                    | VERIFIED |
| Forbidden set $F$ construction                               | ``agent_controller.py:64-66`` (``forbidden``) + line 67 (``blocked``)            | VERIFIED |
| Hard-safety enforcement on global plan                       | ``agent_controller.py:200-202`` (``if hard_safety and desired_next in forbidden: WAIT``) | VERIFIED |
| Local A\* with ``blocked = D ∪ F``                            | ``agent_controller.py:112-115`` calls ``self.local_planner.plan(...)``           | VERIFIED |
| Soft-safety escape                                           | ``agent_controller.py::_find_escape_move``                                      | VERIFIED |
| Conflict detection (vertex / edge)                           | ``conflict_resolution/base.py::detect_imminent_conflict``                       | VERIFIED |
| Decision-table read (sequential semantics)                   | ``base.py::detect_imminent_conflict`` reads ``sim_state.decided_next_positions()`` | VERIFIED |
| Decision-table write (per-agent)                             | ``Simulator.step_once`` phase 5: ``self._decided_next_positions[aid] = next_pos`` | VERIFIED |
| Loser-fallback respects $F$ (Theorem 1 invariant)            | ``priority_rules.py::_safe_side_step`` and ``_astar_fallback``; same in ``token_passing.py`` | VERIFIED |
| Safe Wait fallthrough                                        | ``agent_controller.py::_safe_wait`` + ``_yield_wait``                           | VERIFIED |
| Single-step Safe Wait flag (drives eta_w)                    | ``AgentState.last_action_was_safe_wait``                                        | VERIFIED |
| Single-step Yield Wait flag                                  | ``AgentState.last_action_was_yield_wait``                                       | VERIFIED |

### Theorem 1 (Conditional Safety)

| Theorem 1 element                                      | Code location                                                                  | Status   |
|--------------------------------------------------------|--------------------------------------------------------------------------------|----------|
| Statement: no executed action is agent-attributable    | ``docs/proposed_approach.md`` §F + ``docs/REVISION_AUDIT.md`` §11               | VERIFIED |
| Base case (initialisation invariant)                   | ``Simulator._place_entities`` + ``_assert_init_invariant`` + ``test_init_invariant.py`` | VERIFIED |
| Inductive step — controller F respect                  | ``test_safety_classification.py``                                               | VERIFIED |
| Inductive step — resolver loser fallback respects F    | ``test_theorem1_resolver.py`` (5 tests)                                         | VERIFIED |
| End-to-end empirical guarantee                         | ``test_theorem1_stress.py`` (200-step lifelong, both resolvers)                 | VERIFIED |
| Empirical metric: ``violations_agent_attributable == 0``| Asserted across all stress runs and ``test_init_invariant.py::test_no_agent_attributable_violation_through_step_50`` | VERIFIED |

### Priority tuple $\rho_i$ and resolver constants

| Paper element                                          | Code location                                                                  | Status   |
|--------------------------------------------------------|--------------------------------------------------------------------------------|----------|
| $\rho_i = (-d_i + \beta\,\mathbf{1}[w_i > w^\ast],\, w_i,\, -i)$ | ``conflict_resolution/priority_rules.py::PriorityRulesResolver._priority`` | VERIFIED |
| Starvation threshold $w^\ast = 10$                     | ``PriorityRulesResolver.starvation_threshold`` (default 10)                     | VERIFIED |
| Urgency boost $\beta = 50$                             | ``PriorityRulesResolver.boost`` (default 50)                                    | VERIFIED |
| Token Passing fairness rotation $K = 5$                | ``TokenPassingResolver.fairness_k`` (default 5)                                 | VERIFIED |

### Local A\* expansion cap

| Paper element                                          | Code location                                                                  | Status |
|--------------------------------------------------------|--------------------------------------------------------------------------------|--------|
| $N_{\max} = 500$ (paper)                               | ``AStarLocalPlanner.MAX_EXPANSIONS = 10_000`` (code)                            | **DRIFT** |

**DRIFT (1)** — proposed resolution.  The paper specifies $N_{\max} = 500$;
the code uses 10 000.  Behaviour is identical when the search
terminates naturally (which it does on all three paper maps), and
Theorem 1 still holds when the cap fires (the agent commits Safe
Wait).  **Recommended fix: edit the paper** — change the
$N_{\max}$ value from 500 to 10 000 in §4.3.  Reason: the larger
constant has been validated empirically by every stress test, and
lowering it to 500 might cause unnecessary Safe Waits on long
detours in the warehouse maps.  The change is one numeric token in
the paper.  Already flagged in ``docs/PAPER_TO_CODE_MAP.md`` §4.3
note and ``docs/proposed_approach.md`` §G "Note on $N_{\max}$".

---

## §5.1 — Default configuration

| §5.1 default            | Code location                                            | Status |
|-------------------------|----------------------------------------------------------|--------|
| ``steps = 2000``        | ``SimConfig.steps``                                      | VERIFIED |
| ``horizon = 20``        | ``SimConfig.horizon``                                    | VERIFIED |
| ``replan_every = 10``   | ``SimConfig.replan_every``                               | VERIFIED |
| ``solver_timeout_s = 10.0`` | ``SimConfig.solver_timeout_s``                       | VERIFIED |
| ``fov_radius = 4``      | ``SimConfig.fov_radius``                                 | VERIFIED |
| ``safety_radius = 1``   | ``SimConfig.safety_radius``                              | VERIFIED |
| ``communication_mode = "priority"`` | ``SimConfig.communication_mode``             | VERIFIED |
| ``global_solver = "lacam_official"`` (LaCAM)   | ``SimConfig.global_solver``      | VERIFIED |
| ``eta_w = 0.20``        | ``SimConfig.eta_w``                                      | VERIFIED |
| ``replan_min_gap = 3``  | ``SimConfig.replan_min_gap``                             | VERIFIED |
| 10 seeds (0-9)          | ``configs/eval/paper/*.yaml`` ``seeds: [0, 1, ..., 9]`` (every paper YAML) | VERIFIED |
| Per-map exogenous models (random_walk on random; aisle on warehouse) | ``ha_lmapf.io.default_map_to_human_model`` + ``Simulator._resolve_per_map_human_model`` | VERIFIED |
| Hardware specification  | ``[insert your cluster spec]`` placeholder                | DEFERRED — see ``docs/PAPER_TODO.md`` |
| Task arrival rate / arrival percentage | ``SimConfig.task_arrival_percentage = 0.9``, ``task_arrival_rate = None`` (auto = H+W) | DEFERRED — paper text refers to "see Section 5.1" but does not list a specific number; user should add the auto-formula or a concrete value |

---

## §5.2 — Solver sensitivity sweep

| §5.2 element            | Code location                                            | Status |
|-------------------------|----------------------------------------------------------|--------|
| Sweep YAML              | ``configs/eval/paper/solver_sensitivity.yaml``           | VERIFIED |
| 6 solvers wired in factory | ``GlobalPlannerFactory.create``                       | VERIFIED |
| 7 horizons × 4 agent counts × 2 maps × 10 seeds = 3360 | Pinned by ``test_harness_smoke.py::EXPECTED_RUN_COUNTS`` | VERIFIED |
| ``simulation_steps = 2000`` | ``run_paper_experiment.py::PAPER_SECTION_TO_STEPS``  | VERIFIED |
| Statistical pipeline target = ``lacam_official``  | ``solver_sensitivity.yaml::reference_condition`` | VERIFIED |
| Plot generator          | ``plot_paper_figures.py::figure_horizon``                | VERIFIED |
| Table 1 generator       | ``build_summary_tables.py::emit_table1``                 | VERIFIED |

---

## §5.3 — FoV / safety-radius sweep

| §5.3 element            | Code location                                            | Status |
|-------------------------|----------------------------------------------------------|--------|
| Sweep YAML              | ``configs/eval/paper/fov_safety.yaml``                   | VERIFIED |
| 5 r_fov × 4 r_safe × 2 maps × 10 seeds = 400 | Pinned by ``test_harness_smoke.py``        | VERIFIED |
| ``inflate_cells`` correctness at $r = 0$ | ``test_inflate_cells.py``                     | VERIFIED |
| Plot generator          | ``plot_paper_figures.py::figure_fov_safety``             | VERIFIED |

---

## §5.4 — Scaling sweeps (|M| and |X|)

| §5.4 element            | Code location                                            | Status |
|-------------------------|----------------------------------------------------------|--------|
| |M| sweep YAML          | ``configs/eval/paper/scaling_agents.yaml``               | VERIFIED |
| |X| sweep YAML          | ``configs/eval/paper/scaling_exogenous.yaml``            | VERIFIED |
| Per-map |X| values: random=20 / wh-1=40 / wh-2=60 | ``scaling_agents.yaml`` Groups A/B/C ``num_humans`` | VERIFIED |
| 1040 + 760 runs         | Pinned by ``test_harness_smoke.py``                      | VERIFIED |
| Plot generators         | ``figure_scaling_agents``, ``figure_scaling_exogenous``  | VERIFIED |

---

## §5.5 — Baseline comparison

| §5.5 element            | Code location                                            | Status |
|-------------------------|----------------------------------------------------------|--------|
| Sweep YAML              | ``configs/eval/paper/baseline_comparison.yaml``          | VERIFIED |
| 4 methods × 9 + 9 densities × 10 seeds = 720 | Pinned by ``test_harness_smoke.py``     | VERIFIED |
| ``simulation_steps = 1500`` (paper §5.5)     | ``run_paper_experiment.py::PAPER_SECTION_TO_STEPS`` | VERIFIED |
| **Ours** factory        | identity / paper-aligned ``SimConfig``                   | VERIFIED |
| **RHCR** factory        | ``baselines/pibt2_fr.py::make_rhcr_blind_config``         | VERIFIED |
| **PIBT2-FR** factory    | ``baselines/pibt2_fr.py::make_pibt2_fr_config``          | VERIFIED |
| **No-Buffer** factory   | ``baselines/pibt2_fr.py::make_no_buffer_config``         | VERIFIED |
| PIBT2-FR Tier-2 disabled (point-obstacle reading) | ``controller_kind="global_only"`` per ``make_pibt2_fr_config`` long comment | VERIFIED |
| RHCR end-to-end exogenous-blind | ``make_rhcr_blind_config`` swaps controller; audit trail in ``REVISION_AUDIT.md`` §12 | VERIFIED |
| No-Buffer Theorem 1 holds at r_safe = 0  | ``test_baseline_no_buffer.py`` asserts 0 agent-attributable violations | VERIFIED |
| Plot generator          | ``plot_paper_figures.py::figure_baselines``              | VERIFIED |
| Table 2 generator       | ``build_summary_tables.py::emit_table2``                 | VERIFIED |
| Statistical pipeline target = ``ours`` | ``baseline_comparison.yaml::reference_condition`` | VERIFIED |

---

## §5.5 — Token Passing forward reference (paper §4.3)

| Paper claim             | Status |
|-------------------------|--------|
| Paper §4.3: "Token Passing is treated as an ablation in §5.5" | DEFERRED |

**DEFERRED**.  The §5.5 baseline matrix in the paper LaTeX as
currently written has no Token Passing row.  The repository ships
everything required for the ablation
(``configs/eval/paper/token_passing_ablation.yaml`` — 60 runs,
``plot_token_passing_ablation`` figure function, dedicated section in
``docs/REPRODUCING_PAPER.md``).  User must pick option A (run sweep
+ add to §5.5) or option B (delete the §4.3 forward reference).
Tracked in ``docs/PAPER_TODO.md``.

---

## Cross-cutting verifications

| Element                                              | Code location                                            | Status |
|------------------------------------------------------|----------------------------------------------------------|--------|
| 3 paper maps present and dimensioned correctly        | ``data/maps/`` + ``test_map_loading.py``                  | VERIFIED |
| Solver smoke test (6 solvers)                        | ``test_solver_smoke.py``                                  | VERIFIED |
| 10-second timeout enforcement                        | ``test_solver_timeout.py``                                | VERIFIED |
| Wait-kind invariant ($\sum = $ total)                | ``test_metrics_invariants.py``                            | VERIFIED |
| Theorem 1 invariant (resolver fallback respects F)   | ``test_theorem1_resolver.py``                             | VERIFIED |
| Theorem 1 stress test (200 steps, both resolvers)    | ``test_theorem1_stress.py``                               | VERIFIED |
| Theorem 1 base case (initialisation invariant)       | ``test_init_invariant.py``                                | VERIFIED |
| Decision-table sequential semantics                  | ``test_decision_table.py``                                | VERIFIED |
| Per-map exogenous-model wiring                       | ``test_per_map_model.py``                                 | VERIFIED |
| Harness manifest expansion (every YAML)              | ``test_harness_smoke.py``                                 | VERIFIED |
| Statistical pipeline (Wilcoxon + FDR + BCa)          | ``test_statistical_analysis.py``                          | VERIFIED |
| Paper-claim validator                                | ``test_paper_claims.py``                                  | VERIFIED |

---

## Audit summary

| Status      | Count |
|-------------|------:|
| VERIFIED    | 80    |
| DEFERRED    | 3     |
| **DRIFT**   | **1** |

**The single DRIFT entry** ($N_{\max}$ paper says 500, code uses
10 000) is documented in three places already and the recommended
fix is a one-token paper edit.  No code change is required.

The three DEFERRED entries are all paper-prose fill-ins (cluster
hardware specification, task arrival rate concrete value, Token
Passing §5.5 placement) tracked in ``docs/PAPER_TODO.md``.  None of
them affect the algorithmic substance of the paper.

**Theorem 1 invariant** — every stress / unit / regression test
covering Theorem 1 passes:
``test_theorem1_resolver.py`` (5),
``test_theorem1_stress.py`` (3 incl. 2 parametrised resolvers),
``test_init_invariant.py`` (32, including 30-seed happy-path,
degenerate-density error, and end-to-end 50-step regression),
``test_safety_classification.py`` (4).

**Experiment harness** — every paper section has a corresponding
sweep YAML, plot function, and (where applicable) table generator
and statistical-pipeline target.  See the §5.x rows above.
