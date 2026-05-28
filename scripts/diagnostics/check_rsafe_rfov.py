"""Detect any committed YAML config that would produce r_safe >= r_fov."""
from __future__ import annotations

import itertools
from pathlib import Path
import yaml

ROOT = Path("/home/user/POE-LMAPF-v0")


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def cells(spec):
    """Yield each (base+sweep cell) merged dict from the spec."""
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
ok_with_pair = []
yamls = sorted((ROOT / "configs").rglob("*.yaml"))
for yp in yamls:
    try:
        spec = yaml.safe_load(yp.read_text()) or {}
    except Exception as e:
        print(f"PARSE ERROR {yp}: {e}")
        continue
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
            violations.append((str(yp.relative_to(ROOT)), fovv, safev))
        else:
            ok_with_pair.append((str(yp.relative_to(ROOT)), fovv, safev))

print(f"yamls scanned: {len(yamls)}")
print(f"cells with explicit (fov, safe) pair: {len(violations) + len(ok_with_pair)}")
print(f"  satisfy r_safe < r_fov: {len(ok_with_pair)}")
print(f"  VIOLATIONS (r_safe >= r_fov): {len(violations)}")
for f, fov, safe in violations[:20]:
    print(f"  {f}: fov={fov}, safe={safe}")
