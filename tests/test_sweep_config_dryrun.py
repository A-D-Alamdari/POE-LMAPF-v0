"""Acceptance tests for the P7 scaling/baseline-sweep audit.

Two acceptance criteria from the task spec:

  1. "Each regenerated config round-trips through its generator with
     no diff."  -- the generator output is byte-identical to the
     committed YAML.  A future edit to a YAML by hand without
     touching its producer is caught by the test.

  2. "A dry-run of the runner on each config passes preflight and
     the validity guard wiring without executing full sweeps."  --
     ``scripts/evaluation/run_paper_experiment.py --dry-run`` returns
     0 for each config, exercising manifest expansion + solver
     preflight + config-consistency + the ``max_invalid_fraction`` /
     ``validity_threshold`` wiring.

Tests are parametrised over the same generator -> YAML map the
producers themselves use so a new sweep is automatically covered
the day it's added.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = REPO_ROOT / "scripts" / "tuning"
CONFIG_DIR = REPO_ROOT / "configs" / "tuning"


def _generator_to_yaml(gen_path: Path) -> Path:
    """Discover the OUT_PATH the generator writes to by importing it.

    The convention across these producers is to define a module-level
    ``OUT_PATH = Path(...) / "configs" / "tuning" / "<file>.yaml"``;
    we read that attribute rather than re-parse the filename.
    """
    spec = importlib.util.spec_from_file_location(
        f"_gen_{gen_path.stem}", gen_path,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # ``OUT_PATH`` is set at import time from constants; loading is
    # safe (no side effects, the generator only writes when main() is
    # called).
    spec.loader.exec_module(mod)
    out = getattr(mod, "OUT_PATH", None)
    assert isinstance(out, Path), (
        f"{gen_path.name}: OUT_PATH not a Path attribute "
        f"({type(out).__name__})"
    )
    return out


_GENERATORS: List[Path] = sorted(GEN_DIR.glob("generate_*_yaml.py"))


@pytest.fixture(scope="module")
def gen_yaml_pairs() -> List[Tuple[Path, Path]]:
    pairs: List[Tuple[Path, Path]] = []
    for g in _GENERATORS:
        try:
            y = _generator_to_yaml(g)
            pairs.append((g, y))
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"{g.name}: cannot resolve OUT_PATH: {exc}")
    return pairs


@pytest.mark.parametrize("gen_path", _GENERATORS, ids=lambda p: p.stem)
def test_generator_byte_stable_roundtrip(gen_path: Path):
    """Running the generator produces output byte-identical to the
    committed YAML.  A diff means either the YAML was hand-edited or
    the generator was changed without regenerating."""
    yaml_path = _generator_to_yaml(gen_path)
    assert yaml_path.exists(), f"OUT_PATH {yaml_path} missing"
    before = yaml_path.read_bytes()
    # Run the generator in a fresh subprocess to avoid module-level
    # side effects polluting other tests.
    result = subprocess.run(
        [sys.executable, str(gen_path)],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"{gen_path.name} exited {result.returncode}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    after = yaml_path.read_bytes()
    assert before == after, (
        f"{yaml_path.name} not byte-stable: generator rewrote the file.\n"
        f"  before: {len(before)} bytes\n"
        f"  after : {len(after)} bytes\n"
        "Run the generator and commit the result."
    )


@pytest.mark.parametrize("gen_path", _GENERATORS, ids=lambda p: p.stem)
def test_yaml_has_p7_guard_keys(gen_path: Path):
    """Every auto-generated sweep YAML carries the P3-justified
    ``solver_timeout_s`` and the P2-tied ``max_invalid_fraction``
    keys + their docstring blocks.  Reviewers should be able to see
    the budget justification and the validity-tolerance in the file
    header without spelunking through git history."""
    yaml_path = _generator_to_yaml(gen_path)
    text = yaml_path.read_text()
    assert "solver_timeout_s:" in text, (
        f"{yaml_path.name}: solver_timeout_s key missing"
    )
    assert "max_invalid_fraction:" in text, (
        f"{yaml_path.name}: max_invalid_fraction key missing (P2 guard)"
    )
    # The P3-justification block (calibration table) and the P0-preflight
    # provenance comment must both be present.
    assert "calibrated against the P3" in text, (
        f"{yaml_path.name}: missing P3 solver-budget justification block"
    )
    assert "P0 preflight" in text, (
        f"{yaml_path.name}: missing P0 preflight solver-provenance comment"
    )


# ---------------------------------------------------------------------------
# Dry-run smoke through the paper-experiment harness.
# ---------------------------------------------------------------------------


# Only the configs that the paper-experiment harness actually accepts
# (it requires the "section" key on the spec or an experiment-id field
# on each row).  The generators in scripts/tuning emit configs that
# work with run_paper_experiment.py only when the spec / row schema
# matches; the dry-run test below is opt-in per config.  We discover
# the right configs by checking for the harness-style ``groups``
# structure.
def _is_paper_harness_spec(yaml_path: Path) -> bool:
    """Heuristic: the paper harness reads specs that have either a
    top-level ``groups`` list (sweep style) OR ``runs`` list.  The
    tuning sweep YAMLs all use the groups style."""
    import yaml
    try:
        spec = yaml.safe_load(yaml_path.read_text())
    except Exception:
        return False
    return isinstance(spec, dict) and "groups" in spec


@pytest.mark.parametrize("gen_path", _GENERATORS, ids=lambda p: p.stem)
def test_dry_run_passes_preflight_and_validity_wiring(gen_path: Path, tmp_path: Path):
    """``run_paper_experiment.py --dry-run`` should exit 0 on every
    auto-generated sweep config, meaning:
      * the YAML parses,
      * the manifest expands without errors,
      * every solver listed in the manifest passes P0 preflight,
      * the validity-guard knobs (``validity_threshold`` /
        ``max_invalid_fraction``) are read without error.
    No sims execute.

    Configs that the paper harness cannot accept (different schema)
    are skipped via the ``_is_paper_harness_spec`` predicate."""
    yaml_path = _generator_to_yaml(gen_path)
    if not yaml_path.exists():
        pytest.skip(f"{yaml_path} missing")
    if not _is_paper_harness_spec(yaml_path):
        pytest.skip(f"{yaml_path.name}: not a paper-harness sweep spec")

    out_dir = tmp_path / "out"
    env = os.environ.copy()
    # Keep logs quiet on success and avoid pulling solver binaries
    # from a slow path; the runner does its own logging.
    cmd = [
        sys.executable, "-m", "scripts.evaluation.run_paper_experiment",
        "--config", str(yaml_path),
        "--out", str(out_dir),
        "--dry-run",
        "--log-level", "WARNING",
    ]
    result = subprocess.run(
        cmd, cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"{yaml_path.name}: dry-run failed (rc={result.returncode}).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
