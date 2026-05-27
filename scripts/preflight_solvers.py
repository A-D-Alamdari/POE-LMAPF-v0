#!/usr/bin/env python3
"""
Preflight check for Tier-1 MAPF solver binaries.

Some of the C++ solvers shipped under
``src/ha_lmapf/global_tier/solvers/`` are dynamically linked against
Boost (``libboost_program_options``, ``libboost_filesystem``).  On a
clean machine without those libraries installed the binaries fail at
``ld.so`` load time, ``BaseSolverWrapper._wrap_subprocess`` catches the
non-zero exit, and the sweep silently degrades to all-WAIT plans.

This script resolves each requested solver's binary path through its
own wrapper (the same logic the factory uses) and probes the binary
with a trivial ``--help`` invocation.  Each solver is classified as:

* ``OK``         — binary present and loaded.  ``--help`` may or may
                   not be supported, but the dynamic linker succeeded.
* ``MISSING``    — wrapper resolved to a path that does not exist on
                   disk.
* ``LOAD_ERROR`` — binary exists but the dynamic linker failed to
                   resolve a shared object (the first stderr line is
                   surfaced as the error message).

Exit status is non-zero iff any requested solver is not ``OK``.

Usage::

    python scripts/preflight_solvers.py
    python scripts/preflight_solvers.py --solvers lacam3,pibt2,cbsh2

The script is also importable from other harnesses::

    from preflight_solvers import preflight, abort_if_any_failed
    abort_if_any_failed(["lacam_official", "lacam3"])
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))


# ---------------------------------------------------------------------------
# Canonical solver list
# ---------------------------------------------------------------------------

# One canonical name per wrapper.  Every alias in
# ``GlobalPlannerFactory.create`` resolves to one of these via
# ``_canonicalize`` below.  The probe runs once per canonical name.
_CANONICAL_SOLVERS: Tuple[str, ...] = (
    "lacam_official",
    "lacam3",
    "cbsh2",
    "pibt2",
    "rhcr",
    "eecbs",
    "pbs",
    "lns2",
    "rt_lacam",
)

# Pure-Python solvers have no binary to probe.
_PYTHON_ONLY: frozenset = frozenset({"rt_lacam"})

# Map every accepted alias to its canonical name.  Mirrors
# ``GlobalPlannerFactory.create`` in
# ``ha_lmapf/global_tier/planner_interface.py``.
_ALIAS_TO_CANONICAL: Dict[str, str] = {
    # LaCAM (Kei18)
    "lacam": "lacam_official",
    "lacam_like": "lacam_official",
    "lacam_official": "lacam_official",
    "lacam_cpp": "lacam_official",
    "pylacam": "lacam_official",
    "lacam_python": "lacam_official",
    "prioritized": "lacam_official",
    # LaCAM3 (Kei18)
    "lacam3": "lacam3",
    "lacam3_cpp": "lacam3",
    # CBSH2-RTC (Jiaoyang-Li)
    "cbs": "cbsh2",
    "conflict_based_search": "cbsh2",
    "cbsh2": "cbsh2",
    "cbsh2_rtc": "cbsh2",
    "cbsh2_cpp": "cbsh2",
    "cbs_heuristic": "cbsh2",
    "pycbs": "cbsh2",
    "cbs_python": "cbsh2",
    # PIBT2 (Kei18)
    "pibt": "pibt2",
    "pibt2": "pibt2",
    "pibt2_cpp": "pibt2",
    "pibt_cpp": "pibt2",
    # RHCR (Jiaoyang-Li)
    "rhcr": "rhcr",
    "rhcr_cpp": "rhcr",
    "lifelong": "rhcr",
    # EECBS (Jiaoyang-Li)
    "eecbs": "eecbs",
    "eecbs_cpp": "eecbs",
    "bounded_cbs": "eecbs",
    # PBS (Jiaoyang-Li)
    "pbs": "pbs",
    "pbs_cpp": "pbs",
    "priority_based_search": "pbs",
    # MAPF-LNS2 (Jiaoyang-Li)
    "lns": "lns2",
    "lns2": "lns2",
    "lns2_cpp": "lns2",
    "mapf_lns2": "lns2",
    # Real-Time LaCAM (pure Python)
    "rt_lacam": "rt_lacam",
    "lacam_rt": "rt_lacam",
    "real_time_lacam": "rt_lacam",
}


def canonicalize(name: str) -> str:
    """Map a factory-accepted alias to its canonical solver name.

    Unknown names are returned unchanged so the probe surfaces the
    same ``Unknown global solver`` error the factory would raise.
    """
    return _ALIAS_TO_CANONICAL.get((name or "").strip().lower(), name)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SolverReport:
    name: str
    status: str            # "OK" | "MISSING" | "LOAD_ERROR" | "UNKNOWN"
    binary_path: Optional[str] = None
    detail: str = ""

    def is_ok(self) -> bool:
        return self.status == "OK"

    def format_line(self) -> str:
        bp = self.binary_path or "-"
        if self.detail:
            return f"{self.name:<18} {self.status:<11} {bp}  ({self.detail})"
        return f"{self.name:<18} {self.status:<11} {bp}"


# ---------------------------------------------------------------------------
# Binary path resolution + probe
# ---------------------------------------------------------------------------


def _resolve_binary_path(canonical: str) -> Optional[str]:
    """Instantiate the wrapper for ``canonical`` and return its
    ``binary_path``.  Returns ``None`` for pure-Python solvers."""
    if canonical in _PYTHON_ONLY:
        return None

    # Import lazily so this script remains usable in environments
    # where unrelated wrappers fail to import (e.g. missing numpy
    # extras).  Each branch mirrors ``GlobalPlannerFactory.create``.
    if canonical == "lacam_official":
        from ha_lmapf.global_tier.solvers.lacam_official_wrapper import LaCAMOfficialSolver
        return LaCAMOfficialSolver().binary_path
    if canonical == "lacam3":
        from ha_lmapf.global_tier.solvers.lacam3_wrapper import LaCAM3Solver
        return LaCAM3Solver().binary_path
    if canonical == "cbsh2":
        from ha_lmapf.global_tier.solvers.cbsh2_wrapper import CBSH2Solver
        return CBSH2Solver().binary_path
    if canonical == "pibt2":
        from ha_lmapf.global_tier.solvers.pibt2_wrapper import PIBT2Solver
        # ``pibt2`` uses the mapf binary in one-shot mode; that's
        # the path stored as ``binary_path`` for compatibility.
        return PIBT2Solver().binary_path
    if canonical == "rhcr":
        from ha_lmapf.global_tier.solvers.rhcr_wrapper import RHCRSolver
        return RHCRSolver().binary_path
    if canonical == "eecbs":
        from ha_lmapf.global_tier.solvers.eecbs_wrapper import EECBSSolver
        return EECBSSolver().binary_path
    if canonical == "pbs":
        from ha_lmapf.global_tier.solvers.pbs_wrapper import PBSSolver
        return PBSSolver().binary_path
    if canonical == "lns2":
        from ha_lmapf.global_tier.solvers.lns2_wrapper import LNS2Solver
        return LNS2Solver().binary_path

    raise KeyError(canonical)


_LOAD_ERROR_MARKERS: Tuple[str, ...] = (
    "error while loading shared libraries",
    "cannot open shared object file",
    "image not found",          # macOS dyld
    "Library not loaded",       # macOS dyld
)


def _probe_binary(binary_path: str, timeout_s: float = 5.0) -> SolverReport:
    """Run the binary with ``--help`` and classify the outcome."""
    if not os.path.isfile(binary_path):
        return SolverReport(
            name="", status="MISSING", binary_path=binary_path,
            detail=f"no file at {binary_path}",
        )

    try:
        completed = subprocess.run(
            [binary_path, "--help"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        # The binary started (so it loaded) but didn't return inside
        # the probe window.  That still proves the dynamic linker is
        # satisfied, which is the property we care about here.
        return SolverReport(
            name="", status="OK", binary_path=binary_path,
            detail="--help timed out; binary loaded",
        )
    except (FileNotFoundError, PermissionError) as exc:
        return SolverReport(
            name="", status="MISSING", binary_path=binary_path,
            detail=f"{type(exc).__name__}: {exc}",
        )
    except OSError as exc:
        return SolverReport(
            name="", status="LOAD_ERROR", binary_path=binary_path,
            detail=f"OSError: {exc}",
        )

    stderr = (completed.stderr or "").strip()
    stdout = (completed.stdout or "").strip()
    combined = f"{stderr}\n{stdout}"
    if any(marker in combined for marker in _LOAD_ERROR_MARKERS):
        first_line = stderr.splitlines()[0] if stderr else stdout.splitlines()[0]
        return SolverReport(
            name="", status="LOAD_ERROR", binary_path=binary_path,
            detail=first_line[:200],
        )

    return SolverReport(
        name="", status="OK", binary_path=binary_path,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def preflight(solvers: Iterable[str]) -> List[SolverReport]:
    """Probe each solver in ``solvers`` and return one report per
    *canonical* name (duplicates collapsed)."""
    reports: List[SolverReport] = []
    seen: Dict[str, SolverReport] = {}

    for raw in solvers:
        canonical = canonicalize(raw)
        if canonical in seen:
            continue
        if canonical not in _ALIAS_TO_CANONICAL.values():
            # Unknown to the factory — flag it instead of crashing.
            rep = SolverReport(
                name=canonical, status="UNKNOWN", binary_path=None,
                detail=f"not registered in GlobalPlannerFactory",
            )
            seen[canonical] = rep
            reports.append(rep)
            continue

        try:
            binary_path = _resolve_binary_path(canonical)
        except Exception as exc:  # noqa: BLE001
            rep = SolverReport(
                name=canonical, status="LOAD_ERROR", binary_path=None,
                detail=f"wrapper import failed: {type(exc).__name__}: {exc}",
            )
            seen[canonical] = rep
            reports.append(rep)
            continue

        if binary_path is None:
            rep = SolverReport(name=canonical, status="OK", binary_path=None,
                               detail="pure-python solver")
        else:
            rep = _probe_binary(binary_path)
            rep.name = canonical
        seen[canonical] = rep
        reports.append(rep)

    return reports


def abort_if_any_failed(solvers: Iterable[str], *,
                        prefix: str = "preflight") -> List[SolverReport]:
    """Convenience wrapper for callers (experiment runners):
    run :func:`preflight`, print one line per solver, and
    ``sys.exit(2)`` if any solver in scope is not ``OK``.

    Returns the report list on success so the caller can log it.
    """
    reports = preflight(solvers)
    print(f"[{prefix}] solver preflight ({len(reports)} solvers):")
    for rep in reports:
        print(f"[{prefix}]   {rep.format_line()}")
    bad = [r for r in reports if not r.is_ok()]
    if bad:
        names = ", ".join(r.name for r in bad)
        print(f"[{prefix}] ABORT: {len(bad)} solver(s) not OK: {names}",
              file=sys.stderr)
        print(f"[{prefix}] See src/ha_lmapf/global_tier/solvers/README_SOLVERS.md "
              f"§ 'Boost runtime dependency'.", file=sys.stderr)
        sys.exit(2)
    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_solver_arg(value: Optional[str]) -> List[str]:
    """Split a comma- or whitespace-separated solver list."""
    if not value:
        return list(_CANONICAL_SOLVERS)
    parts: List[str] = []
    for chunk in value.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return parts


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Preflight Tier-1 solver binaries for load errors.",
    )
    p.add_argument(
        "--solvers", type=str, default=None,
        help="Comma-separated solver names to check (e.g. 'lacam3,pibt2'). "
             "Default: all registered solvers.",
    )
    args = p.parse_args(argv)
    requested = _parse_solver_arg(args.solvers)
    reports = preflight(requested)

    for rep in reports:
        print(rep.format_line())

    bad = [r for r in reports if not r.is_ok()]
    if bad:
        names = ", ".join(r.name for r in bad)
        print(f"\nFAIL: {len(bad)} of {len(reports)} solver(s) not OK: {names}",
              file=sys.stderr)
        print("Remedies — see src/ha_lmapf/global_tier/solvers/README_SOLVERS.md "
              "'Boost runtime dependency':", file=sys.stderr)
        print("  (a) install libboost-program-options and libboost-filesystem", file=sys.stderr)
        print("      matching the binaries' ABI (Ubuntu 22.04 ships 1.74; the", file=sys.stderr)
        print("      bundled binaries link against libboost_program_options.so.1.74.0),", file=sys.stderr)
        print("  (b) rebuild eecbs / cbsh2_rtc / pbs / rhcr / mapf_lns from source", file=sys.stderr)
        print("      with static Boost linkage (-DBoost_USE_STATIC_LIBS=ON).", file=sys.stderr)
        return 1

    print(f"\nOK: all {len(reports)} solver(s) loaded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
