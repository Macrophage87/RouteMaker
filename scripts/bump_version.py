"""Set the release version everywhere the code carries it, in one step.

    python3 scripts/bump_version.py 0.27.0

The version lives in pyproject.toml (the Android app's versionName reads it there,
mobile/android/app/build.gradle). These files carry a copy, and
tests/test_deploy_docs.py fails when one disagrees:

- src/routemaker/__init__.py `__version__`
- frontend/package.json and package-lock.json (the version riders see by the title)
- mobile/package.json and package-lock.json
- mcp/routemaker_mcp.py `SERVER_VERSION` (the connector's own version, sent to assistant apps)

Prose that names a release (README.md, docs/OPERATIONS.md, docs/releases/) and the generated
help pages are not touched: the release notes and the docs generator own those.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"\d+\.\d+\.\d+")


def _sub(path: Path, pattern: str, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = re.subn(pattern, lambda m: m.group(1) + version + m.group(3), text, count=1, flags=re.M)
    if count != 1:
        raise SystemExit(f"bump_version: no version line found in {path}")
    path.write_text(new, encoding="utf-8")


def _package(path: Path, version: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = version
    root = data.get("packages", {}).get("")
    if root is not None:
        root["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def bump(version: str, root: Path = ROOT) -> None:
    _sub(root / "pyproject.toml", r'^(version = ")([^"]+)(")$', version)
    _sub(root / "src/routemaker/__init__.py", r'^(__version__ = ")([^"]+)(")$', version)
    _sub(root / "mcp/routemaker_mcp.py", r'^(SERVER_VERSION = ")([^"]+)(")$', version)
    for folder in ("frontend", "mobile"):
        for name in ("package.json", "package-lock.json"):
            _package(root / folder / name, version)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not VERSION.fullmatch(argv[0]):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    bump(argv[0])
    print(f"bump_version: {argv[0]} in pyproject.toml, routemaker, frontend, mobile and the connector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
