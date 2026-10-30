"""The code cites in docs/stress, held to the tree they cite.

The 2026-10-29 review found `file:line` cites there pointing at blank lines and moved
constants. A line number cannot be checked for meaning here, so the pages now name symbols
where it matters (docs/stress/README.md); this checks what can be: every cited file exists,
a bare name (`run.py`) is one file under src/, lua/, frontend/src/ or scripts/, and a cited
line is inside its file.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CITE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|lua|ts|tsx|mjs))(?::(\d+)(?:-(\d+))?)?`")
ROOTS = ("src", "lua", "frontend/src", "scripts")
SUFFIXES = {".py", ".lua", ".ts", ".tsx", ".mjs"}


@cache
def by_name() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for root in ROOTS:
        for path in (REPO / root).rglob("*"):
            if path.suffix in SUFFIXES and "node_modules" not in path.parts:
                found.setdefault(path.name, []).append(path)
    return found


def resolve(cited: str) -> Path | None:
    if (REPO / cited).is_file():
        return REPO / cited
    matches = [p for p in by_name().get(Path(cited).name, []) if p.as_posix().endswith("/" + cited)]
    src = [p for p in matches if (REPO / "src") in p.parents]
    if len(matches) == 1:
        return matches[0]
    return src[0] if len(src) == 1 else None


def test_every_cited_file_exists_and_every_cited_line_is_inside_it():
    problems = []
    for doc in sorted((REPO / "docs" / "stress").glob("*.md")):
        for number, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            for match in CITE.finditer(line):
                cited, first, last = match.groups()
                path = resolve(cited)
                where = f"{doc.name}:{number} {match.group(0)}"
                if path is None:
                    problems.append(f"{where}: no such file")
                    continue
                if first is not None:
                    length = len(path.read_text(encoding="utf-8").split("\n"))
                    if int(last or first) > length:
                        problems.append(f"{where}: the file has {length} lines")
    assert not problems, "\n".join(problems)
