"""Move base_validity_guard_yaml() out of the base: block in each
generator, splicing it as a top-level block before seeds:.

Two source patterns observed (audit step 07 grep):

  pattern_A (12 files):
        + base_solver_budget_yaml()
        + base_validity_guard_yaml()
        +         "  log_violations_timeline: true\n"

  pattern_B (1 file):
        + base_solver_budget_yaml()
        + base_validity_guard_yaml() +
        "  log_violations_timeline: true\n"

Plus the second splice site, two lines later:
        "\n"
        "seeds: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]\n"

which is where the validity-guard block now belongs.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path("/home/user/POE-LMAPF-v0")

GEN_DIR = ROOT / "scripts" / "tuning"

# Two source patterns to recognise and rewrite.
PATTERN_A = (
    "        + base_solver_budget_yaml()\n"
    "        + base_validity_guard_yaml()\n"
    "        +         \"  log_violations_timeline: "
)
PATTERN_B = (
    "        + base_solver_budget_yaml()\n"
    "        + base_validity_guard_yaml() +\n"
    "        \"  log_violations_timeline: "
)


def rewrite_one(p: Path) -> bool:
    text = p.read_text()
    if "base_validity_guard_yaml" not in text:
        return False
    new_text = text
    if PATTERN_A in new_text:
        new_text = new_text.replace(
            PATTERN_A,
            "        + base_solver_budget_yaml()\n"
            "        +         \"  log_violations_timeline: ",
        )
    elif PATTERN_B in new_text:
        new_text = new_text.replace(
            PATTERN_B,
            "        + base_solver_budget_yaml() +\n"
            "        \"  log_violations_timeline: ",
        )
    else:
        return False
    # Insert validity-guard as a top-level block before seeds:.
    seeds_marker = "        \"seeds: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]\\n\""
    if seeds_marker not in new_text:
        # Try alternative seed lists (some sweeps may use different
        # seed counts).  Fall back to the generic seeds-line marker.
        seeds_marker = "        \"seeds: ["
        idx = new_text.find(seeds_marker)
        if idx < 0:
            return False
        # Find the line start (column 0 to first non-blank).  We
        # know the marker is at the start of a Python string literal
        # — back up to the previous "\n" so we can splice before it.
        line_start = new_text.rfind("\n", 0, idx) + 1
        seeds_marker = new_text[line_start:idx + len(seeds_marker)]
    insertion = (
        "        + base_validity_guard_yaml()\n"
        "        \"\\n\"\n"
    )
    # Splice insertion before `"seeds:` ...; the existing "\n" line
    # that precedes seeds is the inter-section blank line — leave it,
    # the insertion adds another blank line after the guard block.
    new_text = new_text.replace(
        seeds_marker,
        insertion + seeds_marker,
        1,
    )
    p.write_text(new_text)
    return True


def main() -> None:
    for p in sorted(GEN_DIR.glob("generate_*_yaml.py")):
        if rewrite_one(p):
            print(f"rewrote: {p.relative_to(ROOT)}")
        else:
            print(f"skipped: {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
