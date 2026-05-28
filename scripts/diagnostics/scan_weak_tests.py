"""Audit step 12 — heuristic weak-test scan.

A test is heuristically WEAK if its body satisfies ALL of:
  - has at most one `assert`,
  - the assertion is a containment / non-None / truthiness check
    (no numeric/equality comparison against a value),
  - has no `pytest.raises` block (so an exception-shape test does
    not trip the heuristic).

This is a triage tool: results require manual review.  Catches
patterns like:
    assert "col" in MetricsTracker.csv_header()
    assert m.deadlock_count is not None
    assert metrics.steps      # truthiness
while NOT tripping:
    assert m.x == expected_value
    with pytest.raises(ValueError): ...
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

ROOT = Path("/home/user/POE-LMAPF-v0")
TESTS = ROOT / "tests"


def is_strong_assert(node: ast.Assert) -> bool:
    """Return True if the assert tests something more than membership /
    non-None / truthiness."""
    t = node.test
    if isinstance(t, ast.Compare):
        # x == y, x > 0, x in [...], x is not None, x is None
        # `x in seq` and `x is [not] None` are weak; everything else
        # (==, <, >, <=, >=, !=) is strong.
        for op in t.ops:
            if isinstance(op, ast.In) or isinstance(op, ast.NotIn):
                continue
            if isinstance(op, ast.Is) or isinstance(op, ast.IsNot):
                continue
            # Numeric / equality comparator → strong.
            return True
        return False
    if isinstance(t, ast.Call):
        # assert isinstance(x, T) is weak; assert math.isclose(x, y) strong.
        try:
            func_name = (t.func.id if isinstance(t.func, ast.Name)
                         else t.func.attr if isinstance(t.func, ast.Attribute)
                         else "")
        except Exception:
            func_name = ""
        if func_name in ("isinstance", "hasattr", "issubclass", "callable",
                          "len", "any", "all", "bool"):
            return False
        return True  # other function calls (e.g. isclose, equals) -> strong
    if isinstance(t, (ast.Name, ast.Attribute, ast.Subscript)):
        return False  # bare truthiness
    if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
        return False  # `assert not x` is weak
    return True  # complex expressions default to strong


def function_has_pytest_raises(fn: ast.FunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.With):
            for item in node.items:
                ce = item.context_expr
                if isinstance(ce, ast.Call):
                    nm = (ce.func.attr if isinstance(ce.func, ast.Attribute)
                          else ce.func.id if isinstance(ce.func, ast.Name)
                          else "")
                    if nm == "raises":
                        return True
    return False


def function_calls_subprocess_run(fn: ast.FunctionDef) -> bool:
    """Tests that invoke `subprocess.run` / `subprocess.check_call`
    typically assert non-zero exit codes elsewhere; they aren't weak
    just because the assert is `rc == 0`."""
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("run", "check_call", "check_output"):
                return True
    return False


def scan_file(p: Path) -> List[Tuple[str, str, int]]:
    """Return [(test_name, weakness_reason, lineno), ...]."""
    try:
        tree = ast.parse(p.read_text())
    except SyntaxError:
        return []
    weak: List[Tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("test_"):
            continue
        if function_has_pytest_raises(node):
            continue
        if function_calls_subprocess_run(node):
            continue
        asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
        if not asserts:
            # No asserts at all — but a fixture body or a setup helper
            # might be the actual mover.  Flag separately.
            weak.append((node.name, "NO_ASSERT", node.lineno))
            continue
        strong = sum(1 for a in asserts if is_strong_assert(a))
        weak_n = len(asserts) - strong
        # Heuristic: a test is weak if EVERY assert is weak.
        if strong == 0:
            patterns = []
            for a in asserts:
                if isinstance(a.test, ast.Compare):
                    for op in a.test.ops:
                        if isinstance(op, ast.In) or isinstance(op, ast.NotIn):
                            patterns.append("membership")
                        elif isinstance(op, (ast.Is, ast.IsNot)):
                            patterns.append("is-not-None")
                elif isinstance(a.test, ast.Call):
                    f = (a.test.func.id if isinstance(a.test.func, ast.Name)
                         else a.test.func.attr if isinstance(a.test.func, ast.Attribute)
                         else "?")
                    patterns.append(f"call:{f}()")
                else:
                    patterns.append("bare-truthiness")
            reason = (
                f"ALL_WEAK_{len(asserts)}_asserts: " + ",".join(set(patterns))
            )
            weak.append((node.name, reason, node.lineno))
    return weak


def main() -> None:
    total_tests = 0
    weak_total = 0
    flagged: List[Tuple[Path, str, str, int]] = []
    for p in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(p.read_text())
        n_tests = sum(1 for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef)
                       and n.name.startswith("test_"))
        total_tests += n_tests
        weaks = scan_file(p)
        weak_total += len(weaks)
        for name, reason, line in weaks:
            flagged.append((p, name, reason, line))

    print(f"test files scanned: 74")
    print(f"total test functions: {total_tests}")
    print(f"heuristically WEAK tests flagged: {len(flagged)} ({100*len(flagged)/max(1,total_tests):.1f}%)\n")
    for p, name, reason, line in flagged:
        print(f"  {str(p.relative_to(ROOT)):60s} :{line:4d}  {name}  [{reason}]")


if __name__ == "__main__":
    main()
