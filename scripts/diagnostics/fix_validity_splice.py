"""Fix syntax in the migrated generators: the inserted block was
        "\\n"
        + base_validity_guard_yaml()
        "\\n"
        "seeds: ..."

which is invalid (string literal "\\n" without preceding operator
after the function call).  Replace with explicit `+ "\\n"` form.
"""
from pathlib import Path

ROOT = Path("/home/user/POE-LMAPF-v0")
GEN_DIR = ROOT / "scripts" / "tuning"

BAD = (
    "        + base_validity_guard_yaml()\n"
    "        \"\\n\"\n"
)
GOOD = (
    "        + base_validity_guard_yaml()\n"
    "        + \"\\n\"\n"
)

for p in sorted(GEN_DIR.glob("generate_*_yaml.py")):
    txt = p.read_text()
    if BAD in txt:
        p.write_text(txt.replace(BAD, GOOD))
        print(f"fixed: {p.relative_to(ROOT)}")
