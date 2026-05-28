"""Audit step 06 — config-precondition enforcement (regression).

Two paper-side preconditions that the original audit recorded as
"documented but not enforced".  This test file moves them from prose
to executable invariants:

  1. Theorem-1 / Algorithm-2 forbidden-set construction-safety
     precondition: r_safe < r_fov.  Enforced in
     ``SimConfig.__post_init__`` (raises ``ValueError`` on violation).
     This test proves the branch fires for the boundary case
     (r_safe == r_fov) and the strict-violation case
     (r_safe > r_fov), and stays quiet for the canonical
     (r_safe < r_fov) configuration.

  2. R = floor(H/2) coupling.  Audit step 04 §1.1 recorded this as a
     paper convention with no code-side dependency.  Audit step 06
     §2 confirmed by grep that no rolling-horizon code path computes
     ``horizon // 2`` or ``2 * replan_every`` or otherwise assumes
     the coupling.  This test pins the decoupling by running a fresh
     ``Simulator`` with non-coupled ``(H=10, R=7)`` (no other value
     pair would prove anything if R simply defaulted to H/2 when
     omitted) and confirms ``Simulator.run()`` finalises with a
     non-degenerate Metrics object.  If a future refactor adds a
     ``R = H / 2`` assert anywhere this test fires.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ha_lmapf.core.types import SimConfig
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# 1. r_safe < r_fov enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def open_5x5_map(tmp_path) -> str:
    p = tmp_path / "5x5.map"
    p.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    return str(p)


def test_r_safe_lt_r_fov_accepted(open_5x5_map):
    """Canonical configuration (r_fov=4, r_safe=1) must construct
    without raising."""
    cfg = SimConfig(
        map_path=open_5x5_map,
        num_agents=1, num_humans=0,
        fov_radius=4, safety_radius=1,
        seed=0, steps=5,
    )
    assert cfg.fov_radius == 4
    assert cfg.safety_radius == 1


def test_r_safe_eq_r_fov_rejected(open_5x5_map):
    """Boundary case: r_fov == r_safe.  The Theorem-1 precondition is
    strict (r_safe < r_fov, not <=); equality must raise so a sweep
    cell like (fov=2, safe=2) — which existed in
    configs/eval/paper/fov_safety.yaml prior to audit step 06 — fails
    loudly instead of silently breaking the safety invariant."""
    with pytest.raises(ValueError) as excinfo:
        SimConfig(
            map_path=open_5x5_map,
            num_agents=1, num_humans=0,
            fov_radius=2, safety_radius=2,
            seed=0, steps=5,
        )
    msg = str(excinfo.value)
    assert "r_safe < r_fov" in msg, (
        f"error message does not name the precondition: {msg!r}")
    assert "Theorem" in msg or "theorem" in msg, (
        f"error message does not cite Theorem 1: {msg!r}")


def test_r_safe_gt_r_fov_rejected(open_5x5_map):
    """Strict violation: r_safe > r_fov.  Must also raise."""
    with pytest.raises(ValueError) as excinfo:
        SimConfig(
            map_path=open_5x5_map,
            num_agents=1, num_humans=0,
            fov_radius=2, safety_radius=3,
            seed=0, steps=5,
        )
    msg = str(excinfo.value)
    assert "safety_radius=3" in msg
    assert "fov_radius=2" in msg


def test_committed_configs_have_zero_violations():
    """Every YAML under ``configs/`` must expand to (fov, safe) cells
    that all satisfy r_safe < r_fov.  This is the file-level
    regression: a future YAML editor who adds an invalid cell breaks
    this test.

    Re-uses the same expansion logic as
    ``scripts/diagnostics/audit_io_runners.py``: walk ``base`` ∪
    every cartesian cell of ``groups[*].sweep``, and check every
    (fov, safe) pair the run would actually instantiate.
    """
    import itertools
    import yaml

    def _as_list(v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]

    def cells(spec):
        base = dict(spec.get("base", {}) or {})
        for g in spec.get("groups", []) or []:
            sweep = (g or {}).get("sweep", {}) or {}
            keys = list(sweep.keys())
            if not keys:
                yield base
                continue
            for combo in itertools.product(*[_as_list(sweep[k]) for k in keys]):
                cell = dict(base)
                cell.update(dict(zip(keys, combo)))
                yield cell

    violations = []
    for yp in sorted((REPO_ROOT / "configs").rglob("*.yaml")):
        try:
            spec = yaml.safe_load(yp.read_text()) or {}
        except Exception as e:
            pytest.fail(f"{yp} failed to parse: {e}")
        for cell in cells(spec):
            fov = cell.get("fov_radius")
            safe = cell.get("safety_radius")
            if fov is None or safe is None:
                continue
            try:
                fovv = int(fov)
                safev = int(safe)
            except Exception:
                continue
            if safev >= fovv:
                violations.append(
                    (str(yp.relative_to(REPO_ROOT)), fovv, safev))

    assert not violations, (
        f"{len(violations)} committed YAML config cell(s) violate the "
        f"Theorem-1 precondition r_safe < r_fov.  Each would crash at "
        f"SimConfig construction (see "
        f"tests/test_config_preconditions.py::test_r_safe_eq_r_fov_rejected). "
        f"Offenders:\n  "
        + "\n  ".join(f"{p}: fov={f}, safe={s}" for p, f, s in violations[:20])
    )


# ---------------------------------------------------------------------------
# 2. R = floor(H/2) is a default, not a code-enforced coupling
# ---------------------------------------------------------------------------


def test_horizon_replan_every_decoupled_run_succeeds(open_5x5_map):
    """Audit step 04 §1.1 + audit step 06 §2 finding: R = floor(H/2)
    is a paper convention; no rolling-horizon code path assumes it.
    The grep that established this checked every occurrence of
    ``horizon`` and ``replan_every`` in
    ``src/ha_lmapf/global_tier/rolling_horizon.py``; the two
    parameters are read independently
    (``periodic = (cur_step % self.replan_every == 0)`` uses only R,
    ``_reanchor_last_good`` uses only H).

    This test pins that decoupling by running a fresh ``Simulator``
    with deliberately-non-coupled ``(horizon=10, replan_every=7)``
    (so a future refactor that adds an ``assert R == H // 2``
    anywhere would fire here).  The run is tiny (2 agents, 30
    steps); the assertion is that ``sim.run()`` returns a finalised
    ``Metrics`` whose four-bucket wait invariant holds — i.e. the
    run did NOT crash and produced coherent output.
    """
    cfg = SimConfig(
        map_path=open_5x5_map,
        num_agents=2, num_humans=0,
        fov_radius=2, safety_radius=1,
        seed=0, steps=30,
        horizon=10, replan_every=7,   # deliberately R != floor(H/2)
    )
    sim = Simulator(cfg)
    metrics = sim.run()
    # The four-bucket wait invariant is asserted inside finalize();
    # if it held the run was internally consistent.  Re-check here
    # explicitly so the test surfaces the field name on failure.
    assert metrics.total_wait_steps == (
        metrics.safe_wait_steps + metrics.yield_wait_steps
        + metrics.physics_revert_wait_steps + metrics.delay_wait_steps
    ), (
        f"decoupled (H={cfg.horizon}, R={cfg.replan_every}) run "
        f"broke the four-bucket wait invariant: {metrics}"
    )
    # Steps actually advanced (not aborted at step 0).
    assert metrics.steps == 30
