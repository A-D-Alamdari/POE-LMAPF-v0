"""Inventory generator for POE-LMAPF audit.

Produces reports/audit/00_inventory.md and reports/audit/00_dependency_map.md.
Inventory-only: does not run code, does not modify anything.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache",
                ".mypy_cache", ".venv", "venv", "build", "dist"}
EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo", ".so", ".o"}


def iter_files(root: Path, *, ext: Tuple[str, ...] | None = None):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in filenames:
            if any(f.endswith(s) for s in EXCLUDE_FILE_SUFFIXES):
                continue
            p = Path(dirpath) / f
            if ext is None or p.suffix in ext:
                yield p


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def directory_tree(root: Path) -> List[Tuple[str, int]]:
    """Return list of (relative_dir_path, depth) for every non-excluded dir."""
    rows: List[Tuple[str, int]] = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        rel_d = "." if dirpath == str(root) else str(Path(dirpath).relative_to(root))
        depth = 0 if rel_d == "." else rel_d.count(os.sep) + 1
        rows.append((rel_d, depth))
    return rows


def first_line_purpose(p: Path) -> str:
    """Heuristic: the directory's purpose, from a README.md in it, else
    a short inferred description."""
    rd = p / "README.md"
    if rd.exists():
        for line in rd.read_text(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:200]
    return ""


def module_docstring(p: Path) -> Tuple[int, str, bool]:
    """Return (line_count, first-line-of-docstring-or-NO_DOCSTRING, parse_ok)."""
    try:
        text = p.read_text(errors="replace")
    except Exception as e:
        return (0, f"READ ERROR: {e}", False)
    lines = text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0
    try:
        tree = ast.parse(text, filename=str(p))
    except SyntaxError as e:
        return (lines, f"SYNTAX ERROR: {e.msg} (line {e.lineno})", False)
    doc = ast.get_docstring(tree)
    if doc is None:
        return (lines, "NO DOCSTRING", True)
    first = doc.strip().splitlines()[0] if doc.strip() else "NO DOCSTRING"
    return (lines, first[:200], True)


def count_tests_in_file(p: Path) -> Tuple[int, str]:
    """Count test_* functions and infer subsystem from filename stem."""
    try:
        tree = ast.parse(p.read_text(errors="replace"), filename=str(p))
    except SyntaxError:
        return (0, "SYNTAX ERROR")
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                n += 1
    stem = p.stem.replace("test_", "")
    return (n, stem)


def gather_imports(p: Path, py_files: Dict[str, Path]) -> Set[str]:
    """Return the set of in-repo modules p imports.

    py_files: mapping module-dotted-name -> path.
    """
    try:
        tree = ast.parse(p.read_text(errors="replace"), filename=str(p))
    except SyntaxError:
        return set()
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                _add_if_inrepo(n.name, py_files, out)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            # Relative imports: resolve against package.
            if node.level > 0:
                # Not commonly used here; skip for simplicity but log.
                pass
            _add_if_inrepo(node.module, py_files, out)
            # also add submodules of the form `from pkg.sub import name`
            for n in node.names:
                _add_if_inrepo(f"{node.module}.{n.name}", py_files, out)
    return out


def _add_if_inrepo(name: str, py_files: Dict[str, Path], out: Set[str]) -> None:
    if name in py_files:
        out.add(name)
        return
    # Try walking back: foo.bar.baz -> foo.bar (if it's a module).
    parts = name.split(".")
    for k in range(len(parts), 0, -1):
        cand = ".".join(parts[:k])
        if cand in py_files:
            out.add(cand)
            return


def module_name_for(p: Path) -> str:
    rp = p.relative_to(ROOT)
    parts = list(rp.parts)
    # Strip src/ prefix.
    if parts[:1] == ["src"]:
        parts = parts[1:]
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # drop .py
    return ".".join(parts)


def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """Return list of simple cycles using Tarjan's SCC."""
    index_counter = [0]
    stack: List[str] = []
    on_stack: Set[str] = set()
    indices: Dict[str, int] = {}
    lowlinks: Dict[str, int] = {}
    sccs: List[List[str]] = []

    def strongconnect(v: str):
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in graph.get(v, ()):
            if w not in indices:
                strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            comp: List[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    # Use iterative to avoid Python recursion depth for large graph.
    sys.setrecursionlimit(50000)
    for v in list(graph.keys()):
        if v not in indices:
            strongconnect(v)
    # Filter to size > 1 or self-loops.
    cycles = []
    for c in sccs:
        if len(c) > 1:
            cycles.append(c)
        elif len(c) == 1 and c[0] in graph.get(c[0], set()):
            cycles.append(c)
    return cycles


def main():
    out_dir = ROOT / "reports" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ----- Collect Python files -----
    py_paths = sorted(iter_files(ROOT, ext=(".py",)))

    py_files: Dict[str, Path] = {}
    broken: List[Tuple[Path, str]] = []
    py_info: List[Tuple[Path, int, str, bool]] = []
    for p in py_paths:
        mod = module_name_for(p)
        py_files[mod] = p
        lines, doc, ok = module_docstring(p)
        py_info.append((p, lines, doc, ok))
        if not ok:
            broken.append((p, doc))

    # ----- Configs (yaml/yml/toml/json/cfg) -----
    cfg_paths = sorted(iter_files(ROOT, ext=(".yaml", ".yml", ".toml",
                                              ".json", ".cfg")))

    # ----- Markdown -----
    md_paths = sorted(iter_files(ROOT, ext=(".md",)))

    # ----- CSVs -----
    csv_paths = sorted(iter_files(ROOT, ext=(".csv",)))

    # ----- Tests subset -----
    test_files = [p for p in py_paths
                  if p.relative_to(ROOT).parts[:1] == ("tests",)]

    # ----- Directory tree -----
    dir_rows = directory_tree(ROOT)

    # ----- Imports / dependencies -----
    deps: Dict[str, Set[str]] = {}
    for p in py_paths:
        mod = module_name_for(p)
        deps[mod] = gather_imports(p, py_files)

    # In-degree count -> "core" / leaves / orphans
    indeg: Dict[str, int] = defaultdict(int)
    for src_mod, targets in deps.items():
        for t in targets:
            indeg[t] += 1
    for m in deps:
        indeg.setdefault(m, 0)

    cycles = find_cycles(deps)

    # Identify scripts (anywhere under scripts/, or top-level plot_*).
    def is_script(mod: str, p: Path) -> bool:
        parts = p.relative_to(ROOT).parts
        if parts[:1] == ("scripts",):
            return True
        if parts[:1] == ("tests",):
            return False
        if len(parts) == 1 and parts[0].startswith("plot_"):
            return True
        return False

    def is_test(p: Path) -> bool:
        return p.relative_to(ROOT).parts[:1] == ("tests",)

    orphans: List[str] = []
    for m, p in py_files.items():
        if indeg[m] > 0:
            continue
        if is_script(m, p):
            continue
        if is_test(p):
            continue
        # __init__.py is imported implicitly via its package.
        if p.name == "__init__.py":
            continue
        orphans.append(m)

    # Top-20 most-imported modules.
    top_cores = sorted(indeg.items(), key=lambda kv: kv[1], reverse=True)[:20]

    # ----- Try importing top-level package + pytest --collect-only -----
    import_log: List[str] = []
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import ha_lmapf; print('ok', ha_lmapf.__file__)"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": f"{ROOT}/src"},
        )
        import_log.append(f"$ PYTHONPATH=src python -c 'import ha_lmapf; ...'")
        import_log.append(f"exit={r.returncode}")
        import_log.append(f"stdout: {r.stdout.strip()}")
        if r.stderr.strip():
            import_log.append("stderr:")
            import_log.extend("  " + l for l in r.stderr.strip().splitlines()[:50])
    except Exception as e:
        import_log.append(f"import-cleanly probe raised: {type(e).__name__}: {e}")

    collect_log: List[str] = []
    try:
        env = {**os.environ, "NO_COLOR": "1", "PY_COLORS": "0",
               "FORCE_COLOR": "0"}
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q",
             "--color=no"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180,
            env=env,
        )
        collect_log.append("$ python -m pytest --collect-only -q --color=no")
        collect_log.append(f"exit={r.returncode}")
        # Capture tail (summary lines) and any errors.  Strip residual ANSI.
        import re as _re
        _ansi = _re.compile(r"\x1b\[[0-9;]*m")
        out_lines = [_ansi.sub("", l) for l in r.stdout.strip().splitlines()]
        err_lines = [_ansi.sub("", l) for l in r.stderr.strip().splitlines()]
        # Last 30 lines of stdout typically contain the summary.
        collect_log.append("stdout (last 40 lines):")
        collect_log.extend("  " + l for l in out_lines[-40:])
        if err_lines:
            collect_log.append("stderr (last 40 lines):")
            collect_log.extend("  " + l for l in err_lines[-40:])
    except Exception as e:
        collect_log.append(f"pytest --collect-only raised: {type(e).__name__}: {e}")

    # ============================================================
    # Write 00_inventory.md
    # ============================================================
    inv_lines: List[str] = []
    inv_lines.append("# Repository inventory")
    inv_lines.append("")
    inv_lines.append(f"Generated by `scripts/diagnostics/build_inventory.py` "
                     f"on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}.")
    inv_lines.append("")
    inv_lines.append("Inventory-only: this file records what exists. No verification, "
                     "no judgments.")
    inv_lines.append("")
    inv_lines.append(f"- Python files: **{len(py_paths)}**")
    inv_lines.append(f"- Test files: **{len(test_files)}**")
    inv_lines.append(f"- Config files (yaml/yml/toml/json/cfg): **{len(cfg_paths)}**")
    inv_lines.append(f"- Markdown docs: **{len(md_paths)}**")
    inv_lines.append(f"- CSV files: **{len(csv_paths)}**")
    inv_lines.append(f"- Directories (after excludes): **{len(dir_rows)}**")
    inv_lines.append(f"- Files with broken AST parse: **{len(broken)}**")
    inv_lines.append("")
    if broken:
        inv_lines.append("## BROKEN FILES")
        inv_lines.append("")
        inv_lines.append("These files did not parse with `ast.parse`.  Listed here so "
                         "downstream consumers know dependency / docstring data is "
                         "missing for them.")
        inv_lines.append("")
        for p, msg in broken:
            inv_lines.append(f"- `{rel(p)}`: {msg}")
        inv_lines.append("")

    # --- Directory tree ---
    inv_lines.append("## Directory tree")
    inv_lines.append("")
    inv_lines.append("Excludes `.git`, `__pycache__`, `node_modules`, "
                     "`.pytest_cache`, `.mypy_cache`, `.venv`, `venv`, "
                     "`build`, `dist`.  One sentence per directory: what it "
                     "holds, inferred from contents or the dir's README.md "
                     "if present.")
    inv_lines.append("")
    # Sentence map per directory — by-hand short labels for the well-known dirs,
    # derived inference for the rest.
    HAND_LABELS: Dict[str, str] = {
        ".": "Repository root: top-level plot scripts, pyproject.toml, README, license, generated figures.",
        "configs": "YAML run configurations for experiment sweeps and evaluation harness.",
        "configs/eval": "Evaluation-time configs (baseline comparison, scaling sweeps).",
        "configs/tuning": "Tuning-time configs (horizon, FOV/safety, allocator sweeps).",
        "data": "Static inputs: maps, scenarios, task streams.",
        "data/maps": ".map files (MovingAI octile grids).",
        "data/random_map": "Generated random benchmark maps.",
        "data/scenarios": ".scen files (start/goal scenarios per map).",
        "data/task_streams": "Pre-generated lifelong task arrival streams.",
        "data/tasks": "Single-task definitions used by one-shot harnesses.",
        "docs": "Project documentation: architecture, reproducibility, audits.",
        "docs/reproducibility": "How to reproduce paper numbers; release manifest.",
        "figures": "Generated figures consumed by the paper.",
        "figures/paper": "Per-section paper figures.",
        "logs": "Per-run artifacts: results.csv, events.csv, manifests, solver dumps.",
        "logs/calibration": "Calibration-run logs (one-shot solver budget tuning).",
        "logs/paper": "Paper-section run artifacts (5.1 / 5.4 / etc.).",
        "logs/regression_smoke": "Regression-smoke harness output (acceptance gate).",
        "logs/solver_debug": "Solver-side debug captures (LaCAM / LNS2 / etc.).",
        "logs/tier_handoff_debug": "Tier-1 -> Tier-2 guidance handoff diagnostics.",
        "logs/tuning": "Tuning-sweep run artifacts.",
        "paper": "Paper text and tables (separate-repo mirror for code-side checks).",
        "paper/sections": "Per-section narrative source / stale-section markers.",
        "paper/tables": "Generated paper tables (.tex + .csv with provenance comments).",
        "reports": "Audit reports and run-status indices.",
        "reports/audit": "Pointed audit reports (this inventory lives here).",
        "results": "Aggregated post-processed results (.csv summaries).",
        "results/paper": "Paper-facing aggregated results.",
        "results/tuning": "Tuning-facing aggregated results.",
        "scripts": "CLI entry points: experiment harness, diagnostics, plotters.",
        "scripts/ablation": "Ablation-sweep drivers.",
        "scripts/diagnostics": "Diagnostic / audit scripts (find_nx_source, probe_*, etc.).",
        "scripts/evaluation": "Evaluation harnesses (run_paper_experiment, build_table_*, ...).",
        "scripts/lifelong": "Lifelong-mode drivers and helpers.",
        "scripts/run_calibration": "Calibration / per-solver budget search drivers.",
        "scripts/run_sweeps": "Sweep drivers (parameter grids, parallel launchers).",
        "scripts/solvers": "Solver-side wrappers and CLIs.",
        "scripts/tuning": "Tuning-sweep drivers (horizon, FOV/safety).",
        "src": "Installable Python package source.",
        "src/ha_lmapf": "Top-level package: core types, metrics, simulation, control, baselines.",
        "tests": "Pytest suite (paper-metric invariants, simulator, controllers, ...).",
    }
    # Auto-fill unknown dirs from README if any.
    for rel_d, depth in dir_rows:
        if rel_d in HAND_LABELS:
            label = HAND_LABELS[rel_d]
        else:
            label = first_line_purpose(ROOT / rel_d) or ""
        indent = "  " * depth
        inv_lines.append(f"{indent}- `{rel_d}` — {label}")
    inv_lines.append("")

    # --- Python files ---
    inv_lines.append("## Python files (path, line count, docstring first-line)")
    inv_lines.append("")
    inv_lines.append(f"Total: {len(py_paths)} files.  Sorted by path.")
    inv_lines.append("")
    inv_lines.append("| Path | Lines | Purpose |")
    inv_lines.append("|---|---:|---|")
    for p, lines, doc, ok in sorted(py_info, key=lambda r: rel(r[0])):
        path = rel(p)
        # Escape pipe in docstrings.
        d = doc.replace("|", "\\|").replace("\n", " ")
        inv_lines.append(f"| `{path}` | {lines} | {d} |")
    inv_lines.append("")

    # --- Config files ---
    inv_lines.append("## Config files")
    inv_lines.append("")
    # Group by directory to keep the table tractable (logs/ alone has thousands).
    cfg_by_dir: Dict[str, List[Path]] = defaultdict(list)
    for c in cfg_paths:
        cfg_by_dir[str(c.parent.relative_to(ROOT))].append(c)
    inv_lines.append(f"Total: {len(cfg_paths)} files across {len(cfg_by_dir)} "
                     "directories.  Grouped by directory; per-file listing for "
                     "non-`logs/` configs (the `logs/` configs are per-run artifacts "
                     "auto-emitted by the harness, summarised as counts).")
    inv_lines.append("")
    inv_lines.append("### Per-directory counts")
    inv_lines.append("")
    inv_lines.append("| Directory | Count |")
    inv_lines.append("|---|---:|")
    for d in sorted(cfg_by_dir):
        inv_lines.append(f"| `{d}` | {len(cfg_by_dir[d])} |")
    inv_lines.append("")

    inv_lines.append("### Non-`logs/` config files (individually listed)")
    inv_lines.append("")
    inv_lines.append("| Path | Purpose |")
    inv_lines.append("|---|---|")
    for d in sorted(cfg_by_dir):
        if d.startswith("logs"):
            continue
        for c in sorted(cfg_by_dir[d]):
            # Heuristic purpose: pull a 'description' or first comment line.
            purpose = ""
            try:
                txt = c.read_text(errors="replace")
                if c.suffix in (".yaml", ".yml"):
                    # First non-blank non-#? line.  Pull description: if any.
                    for line in txt.splitlines():
                        L = line.strip()
                        if L.startswith("description:"):
                            purpose = L.split(":", 1)[1].strip().strip('"\'')
                            break
                    if not purpose:
                        for line in txt.splitlines():
                            L = line.strip()
                            if L.startswith("#"):
                                purpose = L.lstrip("# ").strip()
                                break
                elif c.suffix == ".json":
                    try:
                        obj = json.loads(txt)
                        if isinstance(obj, dict):
                            purpose = str(obj.get("description")
                                          or obj.get("name")
                                          or "<json object>")[:120]
                        elif isinstance(obj, list):
                            purpose = f"<json list, {len(obj)} entries>"
                    except Exception:
                        purpose = "<json unparseable>"
                elif c.suffix == ".toml":
                    for line in txt.splitlines():
                        L = line.strip()
                        if L.startswith("#"):
                            purpose = L.lstrip("# ").strip()
                            break
                        if L.startswith("name") or L.startswith("description"):
                            purpose = L
                            break
            except Exception as e:
                purpose = f"<read failed: {e}>"
            purpose = purpose.replace("|", "\\|")[:200]
            inv_lines.append(f"| `{rel(c)}` | {purpose} |")
    inv_lines.append("")

    # --- Data / log artifact directories ---
    inv_lines.append("## Data / log artifact directories")
    inv_lines.append("")
    inv_lines.append("| Directory | CSV files | Total size | mtime range |")
    inv_lines.append("|---|---:|---:|---|")
    # Walk top-level + immediate subdirs of logs/, results/, data/.
    artifact_roots = ["logs", "results", "data"]
    seen_dirs: Set[str] = set()
    for r in artifact_roots:
        rp = ROOT / r
        if not rp.exists():
            continue
        # The root itself.
        dirs_to_check = [rp]
        for child in sorted(rp.iterdir()):
            if child.is_dir() and child.name not in EXCLUDE_DIRS:
                dirs_to_check.append(child)
        for d in dirs_to_check:
            key = str(d.relative_to(ROOT))
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            csvs = list(d.rglob("*.csv"))
            total_size = 0
            mtimes: List[float] = []
            for f in d.rglob("*"):
                if f.is_file():
                    try:
                        st = f.stat()
                        total_size += st.st_size
                        mtimes.append(st.st_mtime)
                    except OSError:
                        pass
            if mtimes:
                lo = datetime.fromtimestamp(min(mtimes), tz=timezone.utc).strftime("%Y-%m-%d")
                hi = datetime.fromtimestamp(max(mtimes), tz=timezone.utc).strftime("%Y-%m-%d")
                mtime_range = f"{lo} -> {hi}"
            else:
                mtime_range = "(empty)"
            size_h = _human(total_size)
            inv_lines.append(f"| `{key}` | {len(csvs)} | {size_h} | {mtime_range} |")
    inv_lines.append("")

    # --- Test files ---
    inv_lines.append("## Test files (path, test count, subsystem)")
    inv_lines.append("")
    inv_lines.append(f"Total: {len(test_files)} test files.")
    inv_lines.append("")
    inv_lines.append("| Path | Tests | Subsystem |")
    inv_lines.append("|---|---:|---|")
    grand_total = 0
    for t in sorted(test_files):
        n, sub = count_tests_in_file(t)
        grand_total += n
        inv_lines.append(f"| `{rel(t)}` | {n} | {sub} |")
    inv_lines.append("")
    inv_lines.append(f"Aggregate (AST-counted) test functions: **{grand_total}**.  "
                     "Parametrised cases not multiplied.")
    inv_lines.append("")

    # --- Markdown / docs ---
    inv_lines.append("## Markdown docs / reports")
    inv_lines.append("")
    inv_lines.append("| Path | First-line summary |")
    inv_lines.append("|---|---|")
    for m in sorted(md_paths):
        try:
            text = m.read_text(errors="replace")
        except Exception as e:
            inv_lines.append(f"| `{rel(m)}` | <read failed: {e}> |")
            continue
        summary = ""
        for line in text.splitlines():
            L = line.strip()
            if not L:
                continue
            # Strip leading # markers.
            summary = L.lstrip("#").strip()
            break
        summary = summary.replace("|", "\\|")[:200]
        inv_lines.append(f"| `{rel(m)}` | {summary} |")
    inv_lines.append("")

    # --- Cross-check ---
    inv_lines.append("## Acceptance cross-check")
    inv_lines.append("")
    inv_lines.append(
        "Repository-wide Python-file count vs inventory count:\n"
        f"```\n"
        f"$ find . -name '*.py' -not -path '*/.*' | wc -l\n"
        f"{len(py_paths)}\n"
        f"inventory rows: {len(py_paths)}\n"
        f"```")
    inv_lines.append("")

    # --- Import + collect-only logs ---
    inv_lines.append("## Import sanity (verbatim)")
    inv_lines.append("")
    inv_lines.append("```")
    inv_lines.extend(import_log)
    inv_lines.append("```")
    inv_lines.append("")
    inv_lines.append("## `pytest --collect-only` (verbatim, not run)")
    inv_lines.append("")
    inv_lines.append("```")
    inv_lines.extend(collect_log)
    inv_lines.append("```")
    inv_lines.append("")

    (out_dir / "00_inventory.md").write_text("\n".join(inv_lines))

    # ============================================================
    # Write 00_dependency_map.md
    # ============================================================
    dep_lines: List[str] = []
    dep_lines.append("# Repository dependency map")
    dep_lines.append("")
    dep_lines.append("Static AST-based import graph over in-repo Python modules.  "
                     "Generated by `scripts/diagnostics/build_inventory.py`.  "
                     "Inventory-only: nothing executed, no judgments.")
    dep_lines.append("")
    dep_lines.append(f"- Modules indexed: **{len(deps)}**")
    dep_lines.append(f"- Total in-repo edges: **{sum(len(v) for v in deps.values())}**")
    dep_lines.append(f"- SCCs of size > 1 (cycles): **{len([c for c in cycles if len(c) > 1])}**")
    dep_lines.append("")

    # --- Cycles ---
    dep_lines.append("## Import cycles")
    dep_lines.append("")
    nontrivial = [c for c in cycles if len(c) > 1 or (len(c) == 1 and c[0] in deps.get(c[0], set()))]
    if not nontrivial:
        dep_lines.append("None detected.")
    else:
        for i, c in enumerate(nontrivial, 1):
            dep_lines.append(f"### Cycle {i} ({len(c)} modules)")
            dep_lines.append("")
            for m in c:
                dep_lines.append(f"  - `{m}`")
            dep_lines.append("")
    dep_lines.append("")

    # --- Core modules ---
    dep_lines.append("## Core modules (most imported)")
    dep_lines.append("")
    dep_lines.append("Top 20 by in-repo in-degree:")
    dep_lines.append("")
    dep_lines.append("| In-degree | Module |")
    dep_lines.append("|---:|---|")
    for mod, d in top_cores:
        dep_lines.append(f"| {d} | `{mod}` |")
    dep_lines.append("")

    # --- Orphans ---
    dep_lines.append("## Orphan modules (imported by nothing, not a script, not a test)")
    dep_lines.append("")
    dep_lines.append("Candidates for dead code review.  `__init__.py` files are "
                     "excluded; modules under `scripts/`, top-level `plot_*.py`, "
                     "and modules under `tests/` are also excluded.")
    dep_lines.append("")
    if not orphans:
        dep_lines.append("None.")
    else:
        for o in sorted(orphans):
            p = py_files[o]
            dep_lines.append(f"- `{o}` (`{rel(p)}`)")
    dep_lines.append("")

    # --- Full per-module dependency list ---
    dep_lines.append("## Per-module import edges")
    dep_lines.append("")
    dep_lines.append("Each row: `module -> [in-repo modules it imports]`.  "
                     "External / stdlib imports omitted (this graph covers only "
                     "in-repo edges).")
    dep_lines.append("")
    for mod in sorted(deps):
        targets = sorted(deps[mod])
        if not targets:
            dep_lines.append(f"- `{mod}`  (no in-repo imports)")
        else:
            dep_lines.append(f"- `{mod}` -> " + ", ".join(f"`{t}`" for t in targets))
    dep_lines.append("")

    (out_dir / "00_dependency_map.md").write_text("\n".join(dep_lines))

    print(f"wrote {out_dir / '00_inventory.md'}")
    print(f"wrote {out_dir / '00_dependency_map.md'}")
    print(f"py_files={len(py_paths)} cfg={len(cfg_paths)} md={len(md_paths)} "
          f"csv={len(csv_paths)} tests={len(test_files)} broken={len(broken)}")


def _human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.0f}T"


if __name__ == "__main__":
    main()
