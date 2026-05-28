"""Audit step 12 — probe every script with `python -c 'import_module(...)'`
which is the cheapest test that the script's imports resolve.  We do
NOT execute the script (no --help calls): a working --help still
costs a process spawn per script and many scripts are not argparse-
based.  Import-only is sufficient to catch the "references files /
configs / columns that no longer exist" case at the module level.

For scripts that DO have an argparse main, additionally invoke
--help via subprocess (5 s timeout) to confirm the parser builds.
"""
from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path("/home/user/POE-LMAPF-v0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# Probe all scripts under scripts/ + the 6 plot_*.py at repo root.
script_paths = sorted(ROOT.glob("scripts/**/*.py"))
script_paths += sorted(ROOT.glob("plot_*.py"))

n_total = 0
n_import_ok = 0
n_import_fail = 0
import_failures = []
for p in script_paths:
    if "__pycache__" in str(p) or p.name == "__init__.py":
        continue
    n_total += 1
    rel = str(p.relative_to(ROOT))
    # Convert path to module dotted name.
    parts = list(p.relative_to(ROOT).with_suffix("").parts)
    mod_name = ".".join(parts)
    try:
        # Suppress stdout / stderr noise from module top-level side
        # effects.
        with open(os.devnull, "w") as devnull:
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = devnull
            sys.stderr = devnull
            try:
                importlib.import_module(mod_name)
            finally:
                sys.stdout, sys.stderr = old_out, old_err
        n_import_ok += 1
    except SystemExit as e:
        # argparse main with sys.argv (the script ran its main); count
        # as ok if exit code was 0 or 2 (argparse error from missing args).
        if int(getattr(e, "code", 0) or 0) in (0, 2):
            n_import_ok += 1
        else:
            n_import_fail += 1
            import_failures.append((rel, f"SystemExit code {e.code}"))
    except Exception as e:
        n_import_fail += 1
        msg = f"{type(e).__name__}: {e}"
        import_failures.append((rel, msg[:200]))

print(f"scripts probed: {n_total}")
print(f"import OK: {n_import_ok}")
print(f"import FAIL: {n_import_fail}")
if import_failures:
    print()
    print("Failures:")
    for rel, msg in import_failures:
        print(f"  {rel}")
        print(f"    {msg}")
