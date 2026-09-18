"""`pipeline.source` imports the standard library and nothing else.

`config/settings.py` imports it - `from pipeline.source import GEOFABRIK_EXTRACTS`,
so that the list of what is downloaded lives with the code that downloads it
rather than in a second copy that goes stale. That import happens at settings
time, before Django is configured and before any app is loaded, which puts
`pipeline/source.py` in a place ordinary pipeline modules are not: anything it
imports is imported then too.

So `import django` in that file is a circular import (settings importing Django
importing settings), and `from . import tiles` reaches `pipeline/tiles.py`, which
reads `django.conf.settings` - the same cycle one step further out. Either one
breaks every process that loads settings: the API, the workers, the migration
job, `manage.py` itself. The comment in `config/settings.py` states the
condition; nothing held the file to it, and an import added in a later round
would be discovered by a deployment failing to start rather than here.

The check is an AST over the file, not an import of it: importing the module
proves only that it works from a process where Django is already configured,
which is every test process. What matters is the text.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src" / "pipeline" / "source.py"


def non_stdlib_imports(text: str) -> list[str]:
    """Every module `text` imports that is not in the standard library.

    Relative imports are reported as written (`.`, `.tiles`) and are never
    stdlib, which is the point: a relative import from `pipeline/source.py`
    reaches a sibling that may import Django.

    `sys.stdlib_module_names` is the interpreter's own list of the standard
    library's top-level names, so this does not need a list of its own to keep
    up to date - and a name it does not know is treated as third-party, which
    fails in the safe direction.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append("." * node.level + (node.module or ""))
            elif node.module:
                found.append(node.module.split(".")[0])
    return sorted({name for name in found if name not in sys.stdlib_module_names})


def test_pipeline_source_imports_nothing_outside_the_standard_library() -> None:
    assert non_stdlib_imports(SOURCE.read_text()) == [], (
        f"{SOURCE} is imported by config/settings.py at settings time, before Django is "
        "configured. Anything it imports is imported then, and a Django import - or a "
        "pipeline module that imports Django - is a cycle that stops every process that "
        "loads settings from starting."
    )


def test_the_check_notices_the_imports_it_exists_to_forbid() -> None:
    """The mutation, run as a test: the same reader over text that has in it
    each of the three things this file forbids. Without it, a check that had
    stopped looking - a walk over the wrong node type, a name list that quietly
    matched everything - would read as a passing test forever.
    """
    assert non_stdlib_imports("import django\n") == ["django"]
    assert non_stdlib_imports("from django.conf import settings\n") == ["django"]
    assert non_stdlib_imports("from pipeline import tiles\n") == ["pipeline"]
    assert non_stdlib_imports("from . import tiles\n") == ["."]
    assert non_stdlib_imports("from .tiles import CommandOutput\n") == [".tiles"]
    # And it does not cry wolf over what the file really does import.
    assert (
        non_stdlib_imports("import logging\nfrom pathlib import Path\nfrom datetime import UTC\n")
        == []
    )
