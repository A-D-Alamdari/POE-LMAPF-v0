"""Move `max_invalid_fraction` from inside `base:` to spec top-level
in every committed YAML where the line is nested under `base:`.

Preserves the surrounding comments by detecting the contiguous
preceding `#` comment block, moving comment block + line together to
the YAML top level (between the last existing top-level field and
`seeds:` / `groups:` if present, else appended).

Idempotent: if the line is already at indent 0, leaves the file alone.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")


def process(path: Path) -> str:
    text = path.read_text()
    lines = text.splitlines(keepends=False)

    # Find the line that defines max_invalid_fraction.
    idx_line = None
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)max_invalid_fraction\s*:", line)
        if m:
            idx_line = i
            indent = len(m.group(1))
            break
    if idx_line is None:
        return "no_field"
    if indent == 0:
        return "already_top_level"

    # Walk back to capture contiguous preceding comment lines that
    # belong to this field.  Stop on a blank line or a non-comment
    # line that's at a different indent.
    block_start = idx_line
    cur_indent_str = " " * indent
    while block_start > 0:
        prev = lines[block_start - 1]
        if prev.strip().startswith("#") and prev.startswith(cur_indent_str):
            block_start -= 1
            continue
        break

    block = lines[block_start:idx_line + 1]
    # Dedent every line in the block by `indent` spaces.
    dedented = [l[indent:] if l.startswith(cur_indent_str) else l
                for l in block]

    # Remove the block from its original location.
    remaining = lines[:block_start] + lines[idx_line + 1:]

    # Insert the dedented block at the top level: right BEFORE the
    # first occurrence of a top-level (indent 0) key that comes
    # after `base:` (e.g. `seeds:` or `groups:`).
    insert_at = len(remaining)  # default: append at EOF
    in_base = False
    for j, line in enumerate(remaining):
        # Detect entry into `base:` block (top-level).
        if re.match(r"^base\s*:\s*$", line):
            in_base = True
            continue
        if in_base:
            # A top-level key terminates the base: block.
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:", line):
                insert_at = j
                break

    new_lines = remaining[:insert_at] + dedented + [""] + remaining[insert_at:]
    new_text = "\n".join(new_lines)
    # Preserve trailing newline.
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text)
    return f"moved (block size {len(block)}; indent was {indent})"


def main() -> None:
    yamls = sorted((ROOT / "configs").rglob("*.yaml"))
    for yp in yamls:
        out = process(yp)
        if out != "no_field":
            print(f"{yp.relative_to(ROOT)}: {out}")


if __name__ == "__main__":
    main()
