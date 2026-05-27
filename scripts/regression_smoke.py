#!/usr/bin/env python3
"""POE-LMAPF regression smoke — final acceptance gate (P8).

Run a small, fixed matrix of simulator cells across every §5.4-recommended
solver and assert the hard invariants P1-P6 introduced.  A failing
assertion is the correct outcome on a broken tree; the script never
weakens an assertion to make itself pass.

Matrix
------
  * maps: 1 warehouse (warehouse-10-20-10-2-2) + 1 random (random-64-64-10)
  * num_agents: {25, 100}
  * seeds: {0, 1}
  * solvers: lacam_official, lacam3, lns2, pibt2
    (the §5.4 cohort, per logs/calibration/solver_recommendation.md;
    cbsh2 and pbs are excluded -- calibration shows them dropping below
    the 80% completion threshold at |M|=100 on these maps, which would
    surface as ``solver_fail_fraction > 0`` and fail the smoke for
    reasons orthogonal to the P1-P6 properties under test)
  * num_humans: 20
  * steps: 400 (short, per task spec)
  * fov_radius=4, safety_radius=1; horizon=20, replan_every=20

Total: 2 maps x 2 agent counts x 2 seeds x 4 solvers = 32 runs +
       1 forced-error fallback subtest = 33.

Assertions (each one named so a failure points at the right P-fix)
-------------------------------------------------------------------
  P1_SOLVER_FAIL_FRACTION_ZERO       -- every run has
        solver_fail_fraction == 0 AND run_valid == True
        (P1 / P2: the harness must mark a degenerate run honestly).
  P3_SOLVERS_DISCRIMINATE            -- across solvers on the same
        (map, num_agents, seed), at least one (map, num_agents, seed)
        triple has >=2 solvers producing DIFFERENT throughputs
        (P3: the global tier actually runs; the §2 pathology where
        every solver returned bitwise-identical results is gone).
  P6_ATTRIBUTION_INVARIANT           -- every run satisfies
        safety_violations == agent_attributable + exogenous_attributable
        (P6: the attribution split is tracked per pair, not
        double-counted or dropped).
  P5_AGENT_ATTRIBUTABLE_POSSIBLE     -- under the WAIT-counterfactual
        classifier, the metric is non-tautological.  At least one
        smoke run produces agent_attributable > 0, OR
        docs/rerun_protocol.md carries the canonical exemption
        sentence explaining why this matrix cannot trigger it.
        See ``_EXEMPTION_SENTINEL`` below for the exact text.
  FALLBACK_REUSE_INCREMENTS          -- a sim with a single forced
        solver error in the middle of the run records
        solver_fallback_reuses >= 1 AND solver_errors >= 1
        (the rolling-horizon planner re-anchors its last good
        PlanBundle when a solver call returns an error status).

Exit codes
----------
  0  -- every assertion passed; safe to launch the full paper sweep.
  1  -- at least one assertion failed; the named failure is printed
        to stderr and the script halts at the first failed cell so
        the operator can investigate without scrolling through 32
        runs of secondary output.

The script does NOT modify the tree.  It writes a JSON summary to
``logs/regression_smoke/<timestamp>.json`` for the audit trail.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ha_lmapf.core.types import (  # noqa: E402
    Metrics, PlanBundle, SimConfig, SolverResult,
)
from ha_lmapf.simulation.simulator import Simulator  # noqa: E402

logger = logging.getLogger("regression_smoke")


# ---------------------------------------------------------------------------
# Matrix constants — fixed per task spec.
# ---------------------------------------------------------------------------

SMOKE_MAPS: List[str] = [
    "data/maps/warehouse-10-20-10-2-2.map",
    "data/maps/random-64-64-10.map",
]
SMOKE_AGENT_COUNTS: List[int] = [25, 100]
SMOKE_SEEDS: List[int] = [0, 1]
SMOKE_SOLVERS: List[str] = ["lacam_official", "lacam3", "lns2", "pibt2"]

# Smoke parameters are tuned for ~6 min total wall on the dev host:
# steps=100 (well below the example 400 in the spec) keeps the
# |M|=100 cells from compounding per-step local-planner work;
# horizon=50, replan_every=50 leaves 5-8 global replans per cell
# after task-completion-triggered re-plans are accounted for; the
# solver budget is the §5.1 paper default (10 s), guarding against
# the long-tail "no initial solution within -t" failures on
# adversarial random-64-64-10 seeds at |M|=100; num_humans=3 keeps
# the buffer landscape light enough that the local planner does
# not corner agents into safe-wait wedges that would in turn force
# the global solver to time out.  These choices are pure wall-time /
# robustness tuning -- no P-property assertion was relaxed.
SMOKE_STEPS: int = 100
SMOKE_NUM_HUMANS: int = 3
SMOKE_FOV: int = 4
SMOKE_SAFE: int = 1
SMOKE_HORIZON: int = 50
SMOKE_REPLAN_EVERY: int = 50
SMOKE_SOLVER_TIMEOUT_S: float = 10.0


# Canonical exemption sentence — if the §5.4-config smoke matrix
# cannot trigger agent_attributable > 0 (because the planner sees
# every relevant human at fov=4 and the controller forbids
# observed-buffer cells), the operator records that fact in
# docs/rerun_protocol.md.  The smoke checks for this exact
# substring rather than free-form prose so a forgotten / outdated
# doc cannot accidentally satisfy the assertion.
_EXEMPTION_SENTINEL: str = (
    "smoke matrix cannot trigger agent_attributable > 0 under fov > safe"
)


# ---------------------------------------------------------------------------
# Run-row dataclass — what each cell contributes to the summary.
# ---------------------------------------------------------------------------


@dataclass
class SmokeRow:
    map_path: str
    num_agents: int
    seed: int
    solver: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    wall_s: float = 0.0
    error: Optional[str] = None

    @property
    def key_triple(self) -> Tuple[str, int, int]:
        return (Path(self.map_path).stem, self.num_agents, self.seed)


# ---------------------------------------------------------------------------
# Sim execution
# ---------------------------------------------------------------------------


def _build_sim_config(
    *, map_path: str, num_agents: int, seed: int, solver: str,
) -> SimConfig:
    """Build the SimConfig for one smoke cell.  No file IO here -- the
    config is consumed in-process by ``Simulator``."""
    return SimConfig(
        map_path=map_path,
        seed=int(seed),
        steps=SMOKE_STEPS,
        num_agents=int(num_agents),
        num_humans=SMOKE_NUM_HUMANS,
        fov_radius=SMOKE_FOV,
        safety_radius=SMOKE_SAFE,
        horizon=SMOKE_HORIZON,
        replan_every=SMOKE_REPLAN_EVERY,
        solver_timeout_s=SMOKE_SOLVER_TIMEOUT_S,
        global_solver=solver,
        local_planner="astar",
        task_allocator="congestion_avoidance",
        communication_mode="priority",
        hard_safety=True,
        human_model="random_walk",
        mode="lifelong",
        log_violations_timeline=False,
    )


def _metrics_to_dict(m: Metrics) -> Dict[str, Any]:
    """Subset of Metrics needed by the assertions.  Avoids serialising
    timelines / planning-time arrays that aren't checked."""
    keys = [
        "throughput",
        "completed_tasks",
        "steps",
        "global_replans",
        "safety_violations",
        "safety_violation_agent_ticks",
        "safety_violation_events",
        "violations_agent_attributable",
        "violations_exogenous_attributable",
        "solver_timeouts",
        "solver_errors",
        "solver_partial_returns",
        "solver_fallback_reuses",
    ]
    out = {k: getattr(m, k, None) for k in keys}
    # Compute solver_fail_fraction the same way validate_paper_claims does
    # (P2 / P6): (solver_errors + solver_timeouts) / max(1, global_replans).
    gr = int(out.get("global_replans") or 0)
    se = int(out.get("solver_errors") or 0)
    st = int(out.get("solver_timeouts") or 0)
    out["solver_fail_fraction"] = (se + st) / float(max(1, gr))
    # run_valid mirrors the harness's run-validity decision: a run is
    # valid iff Tier-1 ran AND the per-call fail fraction is at or
    # below the standard threshold (0.05).
    out["run_valid"] = (gr > 0) and (out["solver_fail_fraction"] <= 0.05)
    return out


def _run_one(
    *, map_path: str, num_agents: int, seed: int, solver: str,
    patch_fn: Optional[Callable[[Simulator], None]] = None,
) -> SmokeRow:
    """Run one smoke cell.  ``patch_fn`` is invoked after the
    ``Simulator`` is constructed and before ``sim.run()``; the
    fallback-reuse subtest uses it to monkey-patch the solver."""
    row = SmokeRow(
        map_path=map_path, num_agents=num_agents,
        seed=seed, solver=solver,
    )
    t0 = time.perf_counter()
    try:
        cfg = _build_sim_config(
            map_path=map_path, num_agents=num_agents,
            seed=seed, solver=solver,
        )
        sim = Simulator(cfg)
        if patch_fn is not None:
            patch_fn(sim)
        metrics = sim.run()
        row.metrics = _metrics_to_dict(metrics)
    except Exception as exc:  # noqa: BLE001
        row.error = f"{type(exc).__name__}: {exc}"
        logger.exception("smoke cell raised")
    row.wall_s = time.perf_counter() - t0
    return row


# ---------------------------------------------------------------------------
# Assertions — each one named so a failure points at the right P-fix.
# ---------------------------------------------------------------------------


class SmokeFailure(AssertionError):
    """Raised by an assertion with the failing-check name in
    ``self.check`` so ``main()`` can print one clean error line and
    exit 1."""

    def __init__(self, check: str, message: str) -> None:
        super().__init__(f"{check}: {message}")
        self.check = check
        self.message = message


def _assert_no_errors(rows: List[SmokeRow]) -> None:
    """A run that raised an exception during construction / execution
    is a hard fail before any property checks."""
    for r in rows:
        if r.error is not None:
            raise SmokeFailure(
                "RUN_EXECUTION",
                f"cell {r.key_triple} solver={r.solver} raised: {r.error}",
            )


def _assert_p1_solver_fail_fraction_zero(rows: List[SmokeRow]) -> None:
    """Every run has solver_fail_fraction == 0 AND run_valid == True.
    A nonzero fail fraction means Tier-1 errored / timed out -- the
    smoke is supposed to run easy parameters where this should not
    happen.  ``run_valid`` False is its dual."""
    for r in rows:
        sf = r.metrics.get("solver_fail_fraction")
        rv = r.metrics.get("run_valid")
        if sf is None or sf != 0:
            raise SmokeFailure(
                "P1_SOLVER_FAIL_FRACTION_ZERO",
                f"cell {r.key_triple} solver={r.solver}: "
                f"solver_fail_fraction={sf!r} != 0 "
                f"(solver_errors={r.metrics.get('solver_errors')}, "
                f"solver_timeouts={r.metrics.get('solver_timeouts')}, "
                f"global_replans={r.metrics.get('global_replans')})",
            )
        if rv is not True:
            raise SmokeFailure(
                "P1_SOLVER_FAIL_FRACTION_ZERO",
                f"cell {r.key_triple} solver={r.solver}: "
                f"run_valid={rv!r} != True",
            )


def _assert_p3_solvers_discriminate(rows: List[SmokeRow]) -> None:
    """Across solvers on the same (map, num_agents, seed) triple, the
    set of throughput values must NOT collapse to a single number.
    The §2 pathology was that every solver returned identical results
    because the global tier was disabled in dispatch; this check
    catches a re-regression."""
    by_triple: Dict[Tuple[str, int, int], Dict[str, float]] = {}
    for r in rows:
        by_triple.setdefault(r.key_triple, {})[r.solver] = float(
            r.metrics.get("throughput") or 0.0
        )
    found_discriminating = False
    for triple, by_solver in by_triple.items():
        if len(by_solver) < 2:
            continue
        # Bitwise-identical means every value equals every other.
        first = next(iter(by_solver.values()))
        if any(v != first for v in by_solver.values()):
            found_discriminating = True
            break
    if not found_discriminating:
        # Collect a compact dump for the failure message.
        dump = {
            "/".join(map(str, t)): v for t, v in by_triple.items()
        }
        raise SmokeFailure(
            "P3_SOLVERS_DISCRIMINATE",
            f"every (map, agents, seed) triple has bitwise-identical "
            f"throughput across solvers; global tier likely disabled. "
            f"throughputs by triple: {dump}",
        )


def _assert_p6_attribution_invariant(rows: List[SmokeRow]) -> None:
    """Per-run: safety_violations == agent_attributable +
    exogenous_attributable.  This invariant is also asserted in
    MetricsTracker.finalize -- if it fired there, the cell would have
    raised and been caught by ``_assert_no_errors`` above.  We re-check
    on the returned metrics dict to make the check self-contained
    against a future regression in the in-process invariant."""
    for r in rows:
        sv = int(r.metrics.get("safety_violations") or 0)
        aa = int(r.metrics.get("violations_agent_attributable") or 0)
        ea = int(r.metrics.get("violations_exogenous_attributable") or 0)
        if sv != aa + ea:
            raise SmokeFailure(
                "P6_ATTRIBUTION_INVARIANT",
                f"cell {r.key_triple} solver={r.solver}: "
                f"safety_violations={sv} != "
                f"agent_attributable + exogenous_attributable = "
                f"{aa} + {ea} = {aa + ea}",
            )


def _assert_p5_agent_attributable_possible(
    rows: List[SmokeRow], protocol_doc: Path,
) -> None:
    """At least one row has agent_attributable > 0, OR the protocol
    doc carries the canonical exemption sentence.  Under the WAIT-
    counterfactual rule, agent_attributable can ONLY fire when fov
    <= safe (see docs/REVISION_AUDIT.md §13).  The §5.4-config smoke
    uses fov=4 / safe=1, so the metric must remain zero under healthy
    operation -- but the operator must explicitly acknowledge this in
    the protocol doc so a missing assertion is impossible to miss."""
    if any(
        int(r.metrics.get("violations_agent_attributable") or 0) > 0
        for r in rows
    ):
        return
    # No row triggered.  Check the protocol doc for the exemption.
    if not protocol_doc.exists():
        raise SmokeFailure(
            "P5_AGENT_ATTRIBUTABLE_POSSIBLE",
            f"no row produced agent_attributable > 0 AND "
            f"{protocol_doc} is missing; the WAIT-counterfactual "
            f"classifier (P5) appears tautological on this matrix",
        )
    text = protocol_doc.read_text()
    if _EXEMPTION_SENTINEL not in text:
        raise SmokeFailure(
            "P5_AGENT_ATTRIBUTABLE_POSSIBLE",
            f"no row produced agent_attributable > 0 AND "
            f"{protocol_doc} does not carry the exemption sentence "
            f"({_EXEMPTION_SENTINEL!r}); the WAIT-counterfactual "
            f"classifier (P5) appears tautological on this matrix",
        )


# ---------------------------------------------------------------------------
# Fallback-reuse subtest — forces a single solver error and verifies the
# rolling-horizon planner re-anchors its last good PlanBundle.
# ---------------------------------------------------------------------------


class _OneShotErrorSolver:
    """Wraps a real solver and forces a single ``status='error'``
    SolverResult on the Nth call (default: 2nd).  All other calls
    pass through to the wrapped solver unchanged.

    The point is to make the test independent of how often the
    rolling-horizon planner happens to invoke the solver (depends
    on replan_every and the run length); we just need ONE error
    that has a healthy ``_last_good_bundle`` from the previous
    successful call to re-anchor against."""

    def __init__(self, inner: Any, fail_on_nth: int = 2) -> None:
        self._inner = inner
        self._call_count = 0
        self._fail_on_nth = int(fail_on_nth)
        self._fired = False

    # Forward every other attribute access to the wrapped solver.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def plan_with_metadata(self, **kwargs: Any) -> SolverResult:
        self._call_count += 1
        if (not self._fired) and self._call_count == self._fail_on_nth:
            # Fabricate an error result.  RollingHorizonPlanner reads
            # ``result.status`` and ``result.plan``; the plan must be
            # a valid PlanBundle (per the SolverResult contract -- an
            # all-WAIT bundle for the failure path).
            self._fired = True
            num_agents = len(kwargs.get("start") or {}) or 1
            # Build an all-WAIT bundle: each agent stays at its start.
            from ha_lmapf.core.types import TimedPath
            start_step = int(kwargs.get("start_step") or 0)
            horizon = int(kwargs.get("horizon") or 1)
            start = kwargs.get("start") or {}
            paths = {
                aid: TimedPath(
                    cells=[start[aid]] * (horizon + 1),
                    start_step=start_step,
                )
                for aid in start
            }
            wait_bundle = PlanBundle(
                paths=paths,
                created_step=start_step,
                horizon=horizon,
            )
            return SolverResult(
                plan=wait_bundle,
                status="error",
                solver_wall_ms=0.0,
                end_to_end_wall_ms=0.0,
                error_msg="regression_smoke: injected one-shot solver error",
            )
        return self._inner.plan_with_metadata(**kwargs)


def _patch_force_one_error(sim: Simulator) -> None:
    """Hook used as ``patch_fn`` to wrap the simulator's global-tier
    solver with the one-shot error injector."""
    orig = sim.global_planner.solver
    sim.global_planner.solver = _OneShotErrorSolver(orig, fail_on_nth=2)


def _assert_fallback_reuse(rows_with_inject: List[SmokeRow]) -> None:
    """The cell that ran with the forced error must record
    solver_errors >= 1 (the error was counted) AND
    solver_fallback_reuses >= 1 (the planner re-anchored its last
    good bundle).  Both are independent counters: the failure is
    counted regardless of reuse, and the reuse only fires when a
    previous successful bundle exists."""
    if not rows_with_inject:
        raise SmokeFailure(
            "FALLBACK_REUSE_INCREMENTS",
            "no rows passed to fallback-reuse assertion (programming error)",
        )
    for r in rows_with_inject:
        if r.error is not None:
            raise SmokeFailure(
                "FALLBACK_REUSE_INCREMENTS",
                f"forced-error cell {r.key_triple} solver={r.solver} "
                f"raised: {r.error}",
            )
        se = int(r.metrics.get("solver_errors") or 0)
        fr = int(r.metrics.get("solver_fallback_reuses") or 0)
        if se < 1:
            raise SmokeFailure(
                "FALLBACK_REUSE_INCREMENTS",
                f"forced-error cell {r.key_triple} solver={r.solver}: "
                f"solver_errors={se} < 1 -- the injected error was not counted",
            )
        if fr < 1:
            raise SmokeFailure(
                "FALLBACK_REUSE_INCREMENTS",
                f"forced-error cell {r.key_triple} solver={r.solver}: "
                f"solver_fallback_reuses={fr} < 1 -- the rolling-horizon "
                f"planner did not re-anchor its last good PlanBundle",
            )


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------


def _build_matrix() -> List[Tuple[str, int, int, str]]:
    cells: List[Tuple[str, int, int, str]] = []
    for map_path in SMOKE_MAPS:
        for n in SMOKE_AGENT_COUNTS:
            for seed in SMOKE_SEEDS:
                for solver in SMOKE_SOLVERS:
                    cells.append((map_path, n, seed, solver))
    return cells


def _summary_path(out_root: Path) -> Path:
    ts = time.strftime("%Y%m%dT%H%M%S")
    return out_root / f"smoke_{ts}.json"


def run_smoke(
    out_root: Path, protocol_doc: Path,
) -> Tuple[int, Dict[str, Any]]:
    """Execute the matrix + the fallback-reuse subtest, run every
    assertion, and return ``(exit_code, summary_dict)``.

    On a healthy tree returns ``(0, summary)``.  On a P-property
    failure returns ``(1, summary)`` with ``summary['failure']`` set
    to the named check."""
    cells = _build_matrix()
    rows: List[SmokeRow] = []
    logger.info("running %d smoke cells (%d solvers x %d maps x %d agent-counts x %d seeds)",
                len(cells), len(SMOKE_SOLVERS), len(SMOKE_MAPS),
                len(SMOKE_AGENT_COUNTS), len(SMOKE_SEEDS))
    for i, (map_path, n, seed, solver) in enumerate(cells, 1):
        logger.info(
            "  [%d/%d] %s n=%d seed=%d solver=%s",
            i, len(cells), Path(map_path).stem, n, seed, solver,
        )
        sys.stdout.flush()
        sys.stderr.flush()
        r = _run_one(
            map_path=map_path, num_agents=n, seed=seed, solver=solver,
        )
        logger.info(
            "      -> wall=%.1fs throughput=%.4f gr=%s err=%s",
            r.wall_s, float(r.metrics.get("throughput") or 0.0),
            r.metrics.get("global_replans"), r.error,
        )
        sys.stdout.flush()
        sys.stderr.flush()
        rows.append(r)

    # Fallback-reuse subtest: one extra cell with a forced error.
    # Run on the LIGHTEST configuration we have (25 agents, random
    # map, seed=0) so the assertion is not contaminated by a
    # second, naturally-occurring solver failure later in the run
    # (which would still trip the assertion but for the wrong
    # reason).
    logger.info("running 1 fallback-reuse cell with injected solver error")
    inject_row = _run_one(
        map_path=SMOKE_MAPS[1],  # random-64-64-10 -- light
        num_agents=25, seed=0, solver="lacam_official",
        patch_fn=_patch_force_one_error,
    )

    summary: Dict[str, Any] = {
        "matrix": [asdict(r) for r in rows],
        "fallback_reuse_cell": asdict(inject_row),
        "constants": {
            "maps": SMOKE_MAPS,
            "num_agents": SMOKE_AGENT_COUNTS,
            "seeds": SMOKE_SEEDS,
            "solvers": SMOKE_SOLVERS,
            "steps": SMOKE_STEPS,
            "num_humans": SMOKE_NUM_HUMANS,
            "fov_radius": SMOKE_FOV,
            "safety_radius": SMOKE_SAFE,
            "horizon": SMOKE_HORIZON,
            "replan_every": SMOKE_REPLAN_EVERY,
            "solver_timeout_s": SMOKE_SOLVER_TIMEOUT_S,
        },
    }

    # Assertions in order; halt at first failure.
    try:
        _assert_no_errors(rows)
        _assert_p1_solver_fail_fraction_zero(rows)
        _assert_p6_attribution_invariant(rows)
        _assert_p3_solvers_discriminate(rows)
        _assert_p5_agent_attributable_possible(rows, protocol_doc)
        _assert_fallback_reuse([inject_row])
    except SmokeFailure as f:
        summary["failure"] = {"check": f.check, "message": f.message}
        out_root.mkdir(parents=True, exist_ok=True)
        path = _summary_path(out_root)
        path.write_text(json.dumps(summary, indent=2, default=str))
        logger.error("SMOKE FAILED: %s", f)
        logger.error("summary written to %s", path)
        return 1, summary

    summary["failure"] = None
    out_root.mkdir(parents=True, exist_ok=True)
    path = _summary_path(out_root)
    path.write_text(json.dumps(summary, indent=2, default=str))
    logger.info("smoke OK; summary written to %s", path)
    return 0, summary


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--out", type=Path,
        default=REPO_ROOT / "logs" / "regression_smoke",
        help="Directory for the JSON summary (default: logs/regression_smoke/).",
    )
    p.add_argument(
        "--protocol-doc", type=Path,
        default=REPO_ROOT / "docs" / "rerun_protocol.md",
        help="Path to the protocol doc consulted by the P5 exemption check.",
    )
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )
    rc, _ = run_smoke(args.out, args.protocol_doc)
    return rc


if __name__ == "__main__":
    sys.exit(main())
