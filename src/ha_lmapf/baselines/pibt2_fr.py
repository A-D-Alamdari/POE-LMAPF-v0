"""
PIBT2-FR baseline (paper Section 5.5).

PIBT2-FR = "PIBT2 with Full Replanning every step":

  * Tier-1 solver: PIBT2 (fast, partial-result anytime suboptimal MAPF).
  * Replanning cadence: every step (R = 1).
  * Horizon: 20 steps (paper default for the rolling horizon).
  * Tier-2: DISABLED.  Agents follow the PIBT2 plan rigidly.  No local
    A* repair around exogenous agents, no buffer-aware detour.  When
    the next planned cell is occupied by a visible exogenous agent the
    agent WAITs; otherwise it commits the planned move regardless of
    whether the destination lies inside the safety buffer F.

The "rigid follower" Tier-2 behaviour is provided by the existing
``GlobalOnlyController`` in :mod:`ha_lmapf.baselines.global_only_replan`,
selected by setting ``SimConfig.controller_kind = "global_only"``.

Rationale.  We considered defining a dedicated ``PIBT2FRController`` but
``GlobalOnlyController`` already implements every property required by
the paper baseline:
    * reads ``desired_next`` from the global plan;
    * does NOT call the local A* planner;
    * does NOT compute the inflated buffer F;
    * routes through the configured conflict resolver for agent-agent
      yields.
A second class would just duplicate this code.

Other baselines reuse the same configuration helper (``No-Buffer``,
``RHCR-blind``); see :func:`make_no_buffer_config` and
:func:`make_rhcr_blind_config` below.
"""
from __future__ import annotations

from dataclasses import replace

from ha_lmapf.core.types import SimConfig


def make_pibt2_fr_config(base_config: SimConfig) -> SimConfig:
    """Return a copy of ``base_config`` configured as the paper's
    PIBT2-FR baseline.

    Overrides:
        * ``global_solver``    = ``"pibt2"``
        * ``replan_every``     = ``1``           (R = 1 → full replan every tick)
        * ``horizon``          = ``20``
        * ``controller_kind``  = ``"global_only"`` (rigid follower)

    All other fields — map, agent count, exogenous count, seed, safety
    radius, etc. — are inherited unchanged from ``base_config``.

    Disambiguation note (paper §5.5).  The paper text says

        "PIBT2-FR plans against exogenous agents only as point obstacles,
         not as buffer-inflated regions."

    This rules out the alternative reading where Tier-2 stays enabled
    and merely runs on top of PIBT2's plan: a Tier-2-enabled variant
    would inflate observed exogenous agents into the safety buffer F,
    which the paper sentence explicitly forbids.  Our implementation
    therefore wires Tier-2 OFF (``controller_kind="global_only"``):

        * Tier-1 (PIBT2)            — receives only the static map; no
                                      exogenous-agent positions enter
                                      the MAPF input at all.
        * Tier-2 (GlobalOnlyController) — reads the PIBT2 plan, WAITs
                                      only at exact exogenous-agent
                                      CELLS via ``observation.blocked``
                                      (no buffer inflation, no local
                                      A* repair).

    The combined runtime behaviour is precisely "exogenous agents are
    point obstacles" — the paper's stated intent.
    """
    return replace(
        base_config,
        global_solver="pibt2",
        replan_every=1,
        horizon=20,
        controller_kind="global_only",
    )


def make_no_buffer_config(base_config: SimConfig) -> SimConfig:
    """Return a copy of ``base_config`` configured as the paper's
    No-Buffer ablation (Section 5.5 / Section 5.3 sweep at r_safe=0).

    Overrides:
        * ``safety_radius`` = ``0``

    The full POE-LMAPF architecture is otherwise preserved — Tier-1
    rolling-horizon planner, hard-safety controller, conflict
    resolution.  At r_safe=0 the buffer collapses to the exogenous
    agents' exact cells, so ``inflate_cells({pos}, 0, env) == {pos}``;
    the controller still avoids stepping onto an exogenous agent (it
    is in ``observation.blocked``) but every adjacent cell is
    permitted.  Theorem 1 still holds because the rule
    ``ell_1(s_i(t+1), h.pos) <= 0`` simply requires cell coincidence,
    and the controller's hard-safety check rejects exactly that.
    """
    return replace(base_config, safety_radius=0)


def make_rhcr_blind_config(base_config: SimConfig) -> SimConfig:
    """**DEPRECATED — raises NotImplementedError.**

    Originally intended as the §5.5 RHCR-blind baseline.  Source-code
    audit (RHCR ``driver.cpp:178-189`` + ``KivaSystem.cpp:37-50`` +
    ``KivaGraph.cpp:92-186``) revealed that RHCR's KIVA scenario is a
    self-contained lifelong simulator that generates its own tasks
    and reads agent starts from map ``r`` markers — no CLI for
    per-replan invocation.  Integrating it into our rolling-horizon
    framework requires either reimplementing its WHCA*/PBS backend
    as a one-shot solver, or treating its output as fixed
    trajectories and replaying against exogenous agents.  Both
    introduce ambiguity in the safety-metric attribution.

    See ``docs/RHCR_DEFERRED.md`` for the full architectural analysis
    and the future-work plan for Path B (trajectory-replay
    integration).  Use ``method=lacam_blind`` for the §5.5
    rigid-follower baseline — same Tier-1 quality as our method,
    Tier-2 disabled.
    """
    raise NotImplementedError(
        "RHCR's KIVA scenario is a self-contained lifelong simulator, "
        "not a callable per-replan solver. See docs/RHCR_DEFERRED.md "
        "for the full architectural analysis. Use method=lacam_blind "
        "for the §5.5 rigid-follower baseline."
    )


def make_lacam_blind_config(base_config: SimConfig) -> SimConfig:
    """Return a copy of ``base_config`` configured as the paper's
    §5.5 LaCAM-blind baseline.

    Replaces the originally-planned RHCR-blind baseline (see
    :func:`make_rhcr_blind_config` and ``docs/RHCR_DEFERRED.md`` for
    why).  LaCAM-blind preserves the same Tier-1 planner quality as
    ``ours`` (optimal LaCAM rolling-horizon planning against the
    static map) while disabling Tier-2 buffer awareness, isolating
    buffer-awareness as the experimental variable in §5.5's
    2×2 {Tier-1 quality} × {Tier-2 rigid/buffer-aware} matrix.

    Overrides:
        * ``global_solver``   = ``"lacam_official"`` (unchanged from
          base when base already uses it, but enforced for safety)
        * ``controller_kind`` = ``"global_only"`` (rigid follower)

    The RHCR Tier-1 wrapper is not invoked; only the global-only
    controller path is exercised.
    """
    return replace(
        base_config,
        global_solver="lacam_official",
        controller_kind="global_only",
    )
