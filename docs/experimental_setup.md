# Experimental Setup — POE-LMAPF (paper §5.1)

> *Footnote on terminology.*  The paper text refers to non-controlled
> moving entities as **exogenous agents**.  The codebase uses
> **humans** for the same concept (e.g. ``HumanState``, ``humans/``
> package, ``human_model`` config field) for backward compatibility
> with the SoCS2026 submission.  The two terms are interchangeable.

## A. Maps

The paper evaluates on three maps from the standard MovingAI MAPF
benchmark [1]:

| Map stem                   | Grid (W × H) | Topology                                              |
|----------------------------|--------------|-------------------------------------------------------|
| ``random-64-64-10``        | 64 × 64      | 10 % random obstacles — open generic-navigation map.  |
| ``warehouse-10-20-10-2-1`` | 161 × 63     | Parallel aisles + shelves; representative of logistics. |
| ``warehouse-10-20-10-2-2`` | 170 × 84     | Larger warehouse variant.                             |

All three are checked into ``data/maps/``; ``scripts/download_maps.sh``
re-fetches them idempotently from the MovingAI repository.
``tests/test_map_loading.py`` asserts the dimensions above on every
CI run.

---

## B. Exogenous-agent motion models (paper-facing)

The paper evaluation uses two stochastic motion models, parametrised
to match the MovingAI benchmark conventions:

### B.1 Random walk with inertia

Boltzmann action selection with a directional-inertia bias:

$$
\Pr(u \mid x_h, a_h) \propto \exp\!\bigl(s(u)\bigr),
\qquad
s(u) =
\begin{cases}
\beta_{\mathrm{go}}   & u \in \mathrm{cont}(x_h, a_h) \\
\beta_{\mathrm{wait}} & u = x_h \\
\beta_{\mathrm{turn}} & \text{otherwise}
\end{cases}
$$

Defaults: $\beta_{\mathrm{go}} = 2.0,\; \beta_{\mathrm{wait}} = -1.0,\; \beta_{\mathrm{turn}} = 0.0$.

### B.2 Aisle-following

Boltzmann action selection biased by an aisle-likelihood field
$\phi(u) = -\mathrm{dist}(u, S)$ where $S$ is the static-obstacle set:

$$
s(u) = \alpha\,\phi(u) + \beta\,\mathbf{1}\bigl[u \in \mathrm{cont}(x_h, a_h)\bigr].
$$

Defaults: $\alpha = 1.0,\; \beta = 1.5$.

### B.3 Per-map model selection (paper §5.1)

To match the paper's setup we wire each map to its motion model via
``SimConfig.map_to_human_model`` (helper:
``ha_lmapf.io.default_map_to_human_model``):

| Map                            | Model       |
|--------------------------------|-------------|
| ``random-64-64-10``            | random_walk |
| ``random-32-32-20``            | random_walk |
| ``warehouse-10-20-10-2-1``     | aisle       |
| ``warehouse-10-20-10-2-2``     | aisle       |

### B.4 Other implemented models (auxiliary, not in the paper sweep)

The codebase also ships ``adversarial`` (congestion-seeking),
``mixed`` (per-human categorical type sampling), and ``replay``
(deterministic JSON trajectory playback).  They are reachable through
``human_model`` in any ``SimConfig`` and are useful for stress tests
and reproducibility runs but are NOT part of the paper's main
evaluation sweep.

---

## C. Baselines (paper §5.5)

| Baseline       | Tier-1                       | Tier-2                                | Buffer-aware? |
|----------------|------------------------------|---------------------------------------|---------------|
| **Ours (POE-LMAPF)** | Rolling horizon + LaCAM\*  | Sense-Plan-Resolve, F-respecting     | ✓             |
| **RHCR**       | RHCR (rolling horizon, MAPF) | ``GlobalOnlyController`` (rigid)      | ✗ (Theorem 1 doesn't apply) |
| **PIBT2-FR**   | PIBT2 with $R = 1$, $H = 20$ | ``GlobalOnlyController`` (rigid)      | ✗             |
| **No-Buffer**  | Same as Ours                 | Same as Ours, ``r_safe = 0``           | trivially (buffer = exact cell) |

Helpers in ``ha_lmapf.baselines``:

- ``make_pibt2_fr_config(base)`` — PIBT2 with R=1, H=20, ``controller_kind="global_only"``.
- ``make_no_buffer_config(base)`` — sets ``safety_radius = 0``.
- ``make_rhcr_blind_config(base)`` — ``global_solver = "rhcr"`` and
  ``controller_kind = "global_only"`` (the audit in
  ``docs/REVISION_AUDIT.md §12`` explains why both are needed).

> The codebase also ships ``GlobalOnly``, ``PIBT-Only``,
> ``Ignore-Humans``, and ``WHCA*`` from earlier ablation studies.
> They are not part of the paper's main baseline table but remain
> available for additional analyses.

---

## D. Default parameters (paper §5.1)

| Parameter                  | Symbol               | Default                           | ``SimConfig`` field      |
|----------------------------|----------------------|-----------------------------------|--------------------------|
| Lifelong run length        | —                    | 2000                              | ``steps``                |
| Planning horizon           | $H$                  | 20                                | ``horizon``              |
| Replan interval            | $R$                  | 10                                | ``replan_every``         |
| Per-call solver budget     | —                    | 10.0 s                            | ``solver_timeout_s``     |
| FoV radius                 | $r_{\mathit{fov}}$   | 4                                 | ``fov_radius``           |
| Safety radius              | $r_{\mathit{safe}}$  | 1                                 | ``safety_radius``        |
| Hard-safety mode           | —                    | ``True``                          | ``hard_safety``          |
| Conflict resolution        | —                    | ``priority``                      | ``communication_mode``   |
| Local planner              | —                    | ``astar``                         | ``local_planner``        |
| Eta_w trigger threshold    | $\eta_w$             | 0.20                              | ``eta_w``                |
| Replan-thrash guard        | —                    | 3                                 | ``replan_min_gap``       |
| Solver (paper default)     | —                    | LaCAM                             | ``global_solver = "lacam_official"`` |
| Number of seeds            | —                    | 10 (seeds 0–9)                    | ``--seeds`` CLI flag     |

The canonical YAML sits at ``configs/eval/default.yaml``.

---

## E. Evaluation metrics

### E.1 Service quality

| Metric                  | Definition                                       | Goal      |
|-------------------------|--------------------------------------------------|-----------|
| ``throughput``          | ``completed_tasks / steps``                      | maximise  |
| ``mean_flowtime``       | mean steps from task release to completion       | minimise  |
| ``median_flowtime``     | robust flowtime statistic                        | minimise  |
| ``mean_service_time``   | mean steps from assignment to completion         | minimise  |

### E.2 Safety (paper §3.4 attribution split)

| Metric                                  | Definition                                                                                  | Goal      |
|-----------------------------------------|---------------------------------------------------------------------------------------------|-----------|
| ``violations_agent_attributable``       | (a, h) pairs where agent moved into the buffer of an h' it observed at decision time       | **0** (Theorem 1) |
| ``violations_exogenous_attributable``   | residual violation pairs caused by unobserved encroachment                                  | minimise  |
| ``safety_violations`` (legacy)          | sum of the two attribution counters                                                          | minimise  |
| ``safety_violation_rate``               | ``safety_violations`` per 1000 ticks                                                          | minimise  |
| ``collisions_agent_agent``              | agent-agent vertex/edge conflicts (zero by construction in correct runs)                     | 0         |
| ``collisions_agent_human``              | agent stepped onto an exogenous-agent cell                                                   | 0         |
| ``collisions_agent_exogenous``          | nomenclature alias of the above                                                              | 0         |
| ``near_misses``                         | $\ell_1 \le 1$ proximity events                                                              | minimise  |

### E.3 Wait-kind decomposition

| Metric                  | Definition                                                                          |
|-------------------------|-------------------------------------------------------------------------------------|
| ``total_wait_steps``    | cumulative ticks where an agent committed WAIT with a goal                          |
| ``safe_wait_steps``     | safety-induced WAIT (no F-respecting move available)                                |
| ``yield_wait_steps``    | conflict-induced WAIT (resolver yielded after losing a vertex/edge contention)      |
| ``wait_fraction``       | ``total_wait_steps / (num_agents × steps)``                                         |
| ``human_passive_wait_steps`` | exogenous agents stationary with a controlled agent within ``safety_radius``    |

Invariant (paper §5.x): ``total_wait_steps == safe_wait_steps + yield_wait_steps``,
asserted in ``tests/test_metrics_invariants.py``.

### E.4 Computational cost

| Metric                       | Definition                                            |
|------------------------------|-------------------------------------------------------|
| ``mean_planning_time_ms``    | mean wall-clock per global replan call (ms)            |
| ``p95_planning_time_ms``     | 95-th percentile per call                              |
| ``max_planning_time_ms``     | worst-case per call                                    |
| ``mean_decision_time_ms``    | mean wall-clock per ``step_once`` (all agents)         |
| ``p95_decision_time_ms``     | 95-th percentile per step                              |
| ``solver_timeouts``          | replan attempts that returned no useful plan (None / all-WAIT) |

### E.5 Bookkeeping

| Metric              | Definition                                              |
|---------------------|---------------------------------------------------------|
| ``global_replans``  | Tier-1 replan count                                      |
| ``local_replans``   | Tier-2 local-A\* repair count                            |
| ``intervention_rate`` | ``global_replans / steps × 1000``                       |
| ``assignments_kept`` / ``assignments_broken`` | commitment-persistence telemetry  |

---

## F. Statistical methodology

For paired baseline / ablation comparisons we use the methodology
already wired into ``scripts/evaluation/`` and unchanged from the
SoCS2026 setup:

- **10 seeds** per configuration (seeds 0–9), same seeds across
  baselines for a paired design.
- **Friedman omnibus** $\chi^2$ test within each comparison group
  before pairwise contrasts.
- **Wilcoxon signed-rank** (paired, two-sided) vs. ``Ours``.
- **Benjamini-Hochberg FDR** correction within each comparison group.
- Standardised effect sizes: rank-biserial $r$ AND Cohen's $d$.
- **Shapiro-Wilk** test on paired differences (justifies the
  non-parametric choice).
- **95 % bootstrap CIs (BCa)** on means.  BCa is used when $n \ge 10$,
  which our 10-seed setup satisfies.
- Multi-map generalisation (random + warehouse-1 + warehouse-2) and
  scale sensitivity (varied agent / exogenous-agent counts).

---

## G. Experiment groups

The harness runs the following groups, all driven from
``scripts/evaluation/run_evaluation.py``:

1. **Baselines**: Ours vs. RHCR vs. PIBT2-FR vs. No-Buffer.
2. **Scalability**: agent count $\in \{10, 25, 50, 100, 200, 300, 500\}$.
3. **Exogenous-agent density**: human count $\in \{0, 5, 10, 20\}$.
4. **Map topology**: random / warehouse-1 / warehouse-2.
5. **Safety radius sweep** (paper §5.3): $r_{\mathit{safe}} \in \{0, 1, 2, 3\}$.
6. **Eta_w sweep** (paper §5.4): $\eta_w \in \{0.0, 0.1, 0.2, 0.3, 0.5\}$.
7. **Solver comparison**: ``cbsh2``, ``lacam_official``, ``lacam3``,
   ``lns2``, ``pbs``, ``pibt2`` at moderate agent counts.
8. **Ablations**: ``no_local_replan``, ``no_conflict_resolution``,
   ``soft_safety``, ``no_safety``.

---

## H. Reproducibility

All runs are deterministic given a fixed seed.  Each configuration is
run with 10 seeds (0–9); we report mean ± 95 % BCa bootstrap CI.
Maps come from the MovingAI MAPF benchmark [1] and are checked into
``data/maps/``; the canonical YAML defaults are at
``configs/eval/default.yaml``.

---

## I. Running experiments

```bash
# All experiment groups (10 seeds each)
python scripts/evaluation/run_evaluation.py --out logs/eval

# A specific group
python scripts/evaluation/run_evaluation.py --group baselines --out logs/eval

# Custom seed range
python scripts/evaluation/run_evaluation.py --seeds 0 1 2 3 4 5 6 7 8 9 --out logs/eval

# Generate publication figures
python scripts/evaluation/plot_results.py --results logs/eval --out figures/
```

Output layout:

```
logs/eval/
├── baselines/{results.csv, summary.csv}
├── scalability/{results.csv, summary.csv}
├── human_density/{results.csv, summary.csv}
├── safety_radius_sweep/...
├── eta_w_sweep/...
└── figures/{baselines.pdf, scalability.pdf, ablation.pdf, ...}
```

---

## J. Hardware and software

| Component    | Specification                                                    |
|--------------|------------------------------------------------------------------|
| CPU          | Intel Xeon / AMD EPYC (single-threaded per run)                   |
| Memory       | ≥ 16 GB RAM                                                      |
| Python       | 3.10+                                                            |
| Dependencies | NumPy, SciPy, PyYAML, matplotlib, cbs-mapf                        |
| C++ solvers  | LaCAM, LaCAM3, CBSH2-RTC, PBS, LNS2, PIBT2 — see ``docs/SOLVER_STATUS.md`` |

---

## References

[1] Stern et al., "Multi-Agent Pathfinding: Definitions, Variants, and
Benchmarks," 2019.

[2] Li et al., "Lifelong Multi-Agent Path Finding in Large-Scale
Warehouses," 2021.

[3] Okumura, "LaCAM*: An Anytime Solver for Multi-Agent
Path Finding," 2023.
