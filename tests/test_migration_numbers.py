"""Two branches that each add a migration pick the same number, and the second to merge must
be renamed and repointed (a repeated merge conflict). This fails at once, with the files
named, instead of at `migrate`: every number is used once, and each migration follows the
one numbered before it.

Reads the files only (no Django, no database), so it runs anywhere the suite does."""

from __future__ import annotations

import ast
import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "src" / "core" / "migrations"
NAME = re.compile(r"^(\d{4})_\w+\.py$")


def migrations() -> list[tuple[int, str]]:
    found = []
    for path in sorted(MIGRATIONS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        match = NAME.match(path.name)
        assert match, f"{path.name}: a migration is named NNNN_words.py"
        found.append((int(match.group(1)), path.stem))
    return found


def core_dependencies(stem: str) -> list[str]:
    """The core migrations a migration's `dependencies` names."""
    tree = ast.parse((MIGRATIONS / f"{stem}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [getattr(target, "id", None) for target in getattr(node, "targets", [])]
        if isinstance(node, ast.Assign) and "dependencies" in names:
            pairs = ast.literal_eval(node.value)
            return [name for app, name in pairs if app == "core"]
    return []


def test_every_migration_number_is_used_once() -> None:
    numbers: dict[int, list[str]] = {}
    for number, stem in migrations():
        numbers.setdefault(number, []).append(stem)
    twice = {n: stems for n, stems in numbers.items() if len(stems) > 1}
    assert not twice, f"two migrations share a number; renumber the newer and repoint it: {twice}"


def test_the_numbers_run_without_a_gap() -> None:
    numbers = [number for number, _ in migrations()]
    assert numbers == list(range(1, len(numbers) + 1)), "a migration number is missing or skipped"


def test_each_migration_follows_the_one_before_it() -> None:
    found = migrations()
    for (_, before), (_, stem) in zip(found, found[1:], strict=False):
        assert core_dependencies(stem) == [before], f"{stem} should depend on ('core', '{before}')"
    assert core_dependencies(found[0][1]) == []
