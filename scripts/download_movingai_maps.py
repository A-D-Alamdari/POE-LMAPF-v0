# FILE: scripts/download_movingai_maps.py

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Optional helper to download MovingAI maps (or any .map/.zip containing .map files).\n"
            "If you do not provide a URL, this script prints instructions instead."
        )
    )
    p.add_argument(
        "--url",
        default=None,
        help="HTTP(S) URL to a .map file or a .zip containing .map files.",
    )
    p.add_argument(
        "--out",
        default="data/maps",
        help="Output directory to store maps (default: data/maps).",
    )
    return p.parse_args()


def print_instructions() -> None:
    msg = (
        "No URL provided.\n\n"
        "How to use this optional helper:\n"
        "  python scripts/download_movingai_maps.py --url <URL_TO_MAP_OR_ZIP> --out data/maps\n\n"
        "Notes:\n"
        "  - This script can download a single .map file or a .zip archive containing .map files.\n"
        "  - If you are using the official MovingAI benchmark maps, you may prefer to download them\n"
        "    manually from the MovingAI benchmark page and place .map files under data/maps/.\n"
        "  - For research artifacts, it is common to provide a link and instructions instead of bundling maps.\n"
    )
    print(msg)


def download_to_temp(url: str) -> Path:
    with tempfile.TemporaryDirectory() as td:
        # We cannot return a Path inside a context manager; so implement without exiting.
        pass
    raise RuntimeError("Internal error.")


def _safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = os.path.basename(parsed.path)
    if not name:
        name = "downloaded_file"
    # Basic sanitization: keep only safe chars
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "._-")
    return safe or "downloaded_file"


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ha_lmapf-downloader/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(dest, "wb") as f:
        f.write(data)


def extract_zip(zip_path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Only extract .map files
            if not info.filename.lower().endswith(".map"):
                continue
            # Prevent Zip Slip: strip directories
            name = os.path.basename(info.filename)
            if not name:
                continue
            target = out_dir / name
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            extracted += 1
    return extracted


def main() -> None:
    args = parse_args()
    if not args.url:
        print_instructions()
        return

    url = str(args.url).strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        print("Only http(s) URLs are supported.", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename_from_url(url)
    tmp_dir = Path(tempfile.mkdtemp(prefix="halmapf_dl_"))
    try:
        tmp_path = tmp_dir / filename
        print(f"Downloading: {url}")
        fetch(url, tmp_path)

        if tmp_path.suffix.lower() == ".zip":
            n = extract_zip(tmp_path, out_dir)
            if n == 0:
                print("Downloaded ZIP but found no .map files inside.", file=sys.stderr)
                sys.exit(2)
            print(f"Extracted {n} .map file(s) to: {out_dir}")
        elif tmp_path.suffix.lower() == ".map":
            target = out_dir / tmp_path.name
            target.write_bytes(tmp_path.read_bytes())
            print(f"Saved map to: {target}")
        else:
            # Try zipfile detection as a fallback
            try:
                if zipfile.is_zipfile(tmp_path):
                    n = extract_zip(tmp_path, out_dir)
                    if n == 0:
                        print("Downloaded archive but found no .map files inside.", file=sys.stderr)
                        sys.exit(2)
                    print(f"Extracted {n} .map file(s) to: {out_dir}")
                else:
                    print(
                        f"Downloaded file is not a .map or .zip: {tmp_path.name}\n"
                        "Provide a direct URL to a .map file or a ZIP containing .map files.",
                        file=sys.stderr,
                    )
                    sys.exit(2)
            except Exception as e:
                print(f"Could not process downloaded file: {e}", file=sys.stderr)
                sys.exit(2)

    finally:
        # Best-effort cleanup
        try:
            for p in tmp_dir.glob("*"):
                p.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except Exception:
            pass


if __name__ == "__main__":
    main()
