#!/usr/bin/env python3
"""
Reproducibility lock for the POE-LMAPF release.

Captures every artefact that defines a run's environment and inputs
into ``docs/reproducibility/``:

  * ``environment.txt``    — git commit, Python version, ``pip freeze``.
  * ``config_hashes.txt``  — SHA-256 of every YAML under ``configs/``.
  * ``results_hashes.txt`` — SHA-256 of every ``results.csv`` under
                             ``logs/`` (skipped when no logs exist).
  * ``MANIFEST.md``        — top-level summary linking all of the above.

Future researchers can verify they're reproducing the exact same
release by re-running ``--check-only`` and comparing the recorded
hashes.

Usage::

    # Refresh the locked artefacts (default).
    python scripts/lock_reproducibility.py

    # Verify hashes haven't drifted (used by CI).
    python scripts/lock_reproducibility.py --check-only

    # Custom output directory.
    python scripts/lock_reproducibility.py --out docs/reproducibility
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

logger = logging.getLogger("repro_lock")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "reproducibility"


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _sha256_file(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(block_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk_files(root: Path, glob: str) -> List[Path]:
    return sorted(p for p in root.glob(glob) if p.is_file())


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "(unavailable)"


def _git_status_clean() -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        ).decode()
        return out.strip() == ""
    except Exception:
        return False


def _pip_freeze() -> str:
    try:
        return subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze"],
            stderr=subprocess.DEVNULL,
        ).decode()
    except Exception as exc:
        return f"(pip freeze failed: {exc})\n"


def write_environment(out_dir: Path) -> Path:
    path = out_dir / "environment.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append(f"# POE-LMAPF reproducibility environment lock")
    lines.append(f"# generated: {dt.datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append(f"git_commit:        {_git_commit()}")
    lines.append(f"git_clean:         {_git_status_clean()}")
    lines.append(f"python_version:    {sys.version.split()[0]}")
    lines.append(f"python_executable: {sys.executable}")
    lines.append(f"platform:          {platform.platform()}")
    lines.append(f"machine:           {platform.machine()}")
    lines.append(f"processor:         {platform.processor() or '(unknown)'}")
    lines.append("")
    lines.append("# pip freeze")
    lines.append("")
    lines.append(_pip_freeze())
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("wrote %s", path)
    return path


# ---------------------------------------------------------------------------
# YAML / CSV hashing
# ---------------------------------------------------------------------------


def _hash_table(rel_paths_and_hashes: Iterable[Tuple[Path, str]],
                title: str) -> str:
    body = ["# " + title,
            f"# generated: {dt.datetime.utcnow().isoformat()}Z",
            "# format:    sha256  relpath",
            ""]
    for path, h in rel_paths_and_hashes:
        body.append(f"{h}  {path}")
    body.append("")
    return "\n".join(body)


def write_config_hashes(out_dir: Path) -> Path:
    path = out_dir / "config_hashes.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs: List[Tuple[Path, str]] = []
    for f in _walk_files(REPO_ROOT / "configs", "**/*.yaml"):
        rel = f.relative_to(REPO_ROOT)
        pairs.append((rel, _sha256_file(f)))
    path.write_text(_hash_table(pairs, "Config YAML SHA-256"), encoding="utf-8")
    logger.info("wrote %s (%d configs)", path, len(pairs))
    return path


def write_results_hashes(out_dir: Path,
                         logs_root: Path = REPO_ROOT / "logs") -> Path:
    path = out_dir / "results_hashes.txt"
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs: List[Tuple[Path, str]] = []
    if logs_root.exists():
        for f in _walk_files(logs_root, "**/results.csv"):
            rel = f.relative_to(REPO_ROOT)
            pairs.append((rel, _sha256_file(f)))
    body = _hash_table(pairs, "Per-sweep results.csv SHA-256")
    if not pairs:
        body += "\n# No results.csv found under logs/.  Run scripts/evaluation/run_paper_experiment.py first.\n"
    path.write_text(body, encoding="utf-8")
    logger.info("wrote %s (%d results)", path, len(pairs))
    return path


# ---------------------------------------------------------------------------
# MANIFEST
# ---------------------------------------------------------------------------


def write_manifest(out_dir: Path,
                   environment_path: Path,
                   config_hashes_path: Path,
                   results_hashes_path: Path) -> Path:
    path = out_dir / "MANIFEST.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: List[str] = [
        "# POE-LMAPF Reproducibility Manifest",
        "",
        "Snapshots the artefacts a third party needs to verify they "
        "are reproducing **the same release** as the paper-attached "
        "supplementary material.  Re-run "
        "``scripts/lock_reproducibility.py --check-only`` to verify "
        "no hashes have drifted since this manifest was generated.",
        "",
        f"- generated: ``{dt.datetime.utcnow().isoformat()}Z``",
        f"- git commit: ``{_git_commit()}``",
        f"- working tree clean: ``{_git_status_clean()}``",
        f"- Python: ``{sys.version.split()[0]}``",
        f"- platform: ``{platform.platform()}``",
        "",
        "## Artefact files",
        "",
        f"- [`environment.txt`](environment.txt) — git commit, Python version, ``pip freeze``.",
        f"- [`config_hashes.txt`](config_hashes.txt) — SHA-256 of every YAML under ``configs/``.",
        f"- [`results_hashes.txt`](results_hashes.txt) — SHA-256 of every ``logs/**/results.csv``.",
        "",
        "## Verification recipe",
        "",
        "```bash",
        "git checkout " + _git_commit(),
        "pip install -r requirements.txt",
        "pip install -e .",
        "python scripts/lock_reproducibility.py --check-only",
        "```",
        "",
        "If ``--check-only`` exits ``0``, the artefacts on disk match "
        "the snapshot recorded here.  Any non-zero exit indicates "
        "drift between the recorded hashes and the current files; "
        "the script prints the diverging paths.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("wrote %s", path)
    return path


# ---------------------------------------------------------------------------
# Check-only mode
# ---------------------------------------------------------------------------


def _parse_hash_file(path: Path) -> List[Tuple[str, Path]]:
    """Return a list of ``(sha256, relpath)`` pairs from a hash table file."""
    out: List[Tuple[str, Path]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        out.append((parts[0], Path(parts[1])))
    return out


def check(out_dir: Path) -> int:
    """Return 0 if all hashes match the live files; non-zero otherwise."""
    bad: List[str] = []

    config_pairs = _parse_hash_file(out_dir / "config_hashes.txt")
    for h, rel in config_pairs:
        f = REPO_ROOT / rel
        if not f.exists():
            bad.append(f"missing: {rel}")
            continue
        live = _sha256_file(f)
        if live != h:
            bad.append(f"drift:   {rel} (recorded {h[:12]}, live {live[:12]})")

    results_pairs = _parse_hash_file(out_dir / "results_hashes.txt")
    for h, rel in results_pairs:
        f = REPO_ROOT / rel
        if not f.exists():
            # Results may not exist on a fresh checkout — skip rather than fail.
            continue
        live = _sha256_file(f)
        if live != h:
            bad.append(f"drift:   {rel} (recorded {h[:12]}, live {live[:12]})")

    if bad:
        for line in bad:
            print(line, file=sys.stderr)
        return 1
    print(
        f"OK — {len(config_pairs)} configs and {len(results_pairs)} results "
        f"hashes verified against live files.",
    )
    return 0


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="POE-LMAPF reproducibility lock")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="Output directory (default: docs/reproducibility/).")
    p.add_argument("--check-only", action="store_true",
                   help="Verify recorded hashes match live files; do not rewrite.")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(name)s | %(message)s",
    )

    if args.check_only:
        return check(args.out)

    env_path     = write_environment(args.out)
    cfg_path     = write_config_hashes(args.out)
    results_path = write_results_hashes(args.out)
    write_manifest(args.out, env_path, cfg_path, results_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
