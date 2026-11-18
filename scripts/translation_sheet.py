#!/usr/bin/env python3
"""A sheet per language for a native speaker to fix the app's words, and its way back in.

Every language but English is a Claude draft (frontend/src/i18n/<code>.ts for the app's own
words, src/routemaker/lang_<code>.py for the route's sentences: turns, hazards, work zones,
climbs). A volunteer who reads the language gets one spreadsheet (CSV, opens in Excel or
Google Sheets): the English, the draft, where in the app it shows, and two columns to fill:
"Your fix" for a better phrase and "Checked" (any mark) for one that reads right as it is.
From Excel, save it as "CSV UTF-8"; from Google Sheets, File, Download, CSV.

    python scripts/translation_sheet.py export ko --out sheets/      # sheets/ko.csv
    python scripts/translation_sheet.py export all --out sheets/     # all 20
    python scripts/translation_sheet.py import ko sheets/ko.csv      # fixes into the catalogs
    python scripts/translation_sheet.py sync                         # the app's copy of the
                                                                     # route's sentences

`import` refuses a fix whose {places} differ from the English's (a {street} lost or renamed
would show the brace to a rider), writes the rest into the catalog files, keeps the checked
phrases in frontend/src/i18n/checked/<code>.json (export marks them again) and runs `sync`.
Review the diff (git diff) before committing it.

`sync` writes frontend/src/i18n/server/<code>.ts from the route catalogs: the app reads the
route's sentences back to English with it, for the voice on a phone that has no voice for the
language (lib/i18n.ts englishOf). tests/test_translation_sheet.py fails when it is stale.
"""

from __future__ import annotations

import argparse
import ast
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from routemaker import lang  # noqa: E402

APP = ROOT / "frontend/src/i18n"
SERVER_TS = APP / "server"
CHECKED = APP / "checked"
ROUTE = ROOT / "src/routemaker"
LANGUAGES = [code for code in lang.LANGUAGES if code != "en"]
COLUMNS = ["Where", "English", "Draft", "Your fix", "Checked", "Key"]
_PLACE = re.compile(r"\{(\w+)\}")
# A catalog entry in TypeScript: "English": "draft", the draft maybe on the next line.
_TS_STRING = r'"(?:[^"\\]|\\.)*"'
_TS_ENTRY = re.compile(rf"^\s*({_TS_STRING})\s*:\s*({_TS_STRING})", re.M)
_TS_SECTION = re.compile(r"^\s*// -+\s*(.*?)\s*-*\s*$")
_PY_SECTION = re.compile(r"^\s*# -+\s*(.*?)\s*-*\s*$")


def _ts_literal(text: str) -> str:
    return json.loads(text.replace("\\'", "'"))


def app_path(code: str) -> Path:
    return APP / f"{code}.ts"


def route_path(code: str) -> Path:
    return ROUTE / f"lang_{code}.py"


def app_entries(code: str) -> list[tuple[str, str, str]]:
    """(section, English, draft) of the app's catalog, in file order."""
    text = app_path(code).read_text(encoding="utf-8")
    sections = _sections(text, _TS_SECTION)
    out = []
    for m in _TS_ENTRY.finditer(text):
        line = text.count("\n", 0, m.start(1))
        out.append((sections(line), _ts_literal(m[1]), _ts_literal(m[2])))
    return out


def _sections(text: str, pattern: re.Pattern[str]):
    """The nearest section heading (a "---- Turns ----" comment) above a line."""
    heads = []
    for number, line in enumerate(text.splitlines()):
        m = pattern.match(line)
        if m and m[1]:
            heads.append((number, m[1]))

    def at(line: int) -> str:
        found = ""
        for number, head in heads:
            if number > line:
                break
            found = head
        return found

    return at


def _route_dict(tree: ast.Module) -> ast.Dict:
    for node in tree.body:
        value = node.value if isinstance(node, ast.AnnAssign | ast.Assign) else None
        if isinstance(value, ast.Dict):
            return value
    raise SystemExit("no catalog dict found")


def route_entries(code: str) -> list[tuple[str, str, str]]:
    """(section, English, draft) of the route's catalog, in file order."""
    text = route_path(code).read_text(encoding="utf-8")
    sections = _sections(text, _PY_SECTION)
    table = _route_dict(ast.parse(text))
    return [
        (sections(key.lineno - 1), key.value, value.value)
        for key, value in zip(table.keys, table.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
    ]


def checked(code: str) -> dict[str, list[str]]:
    path = CHECKED / f"{code}.json"
    if not path.exists():
        return {"app": [], "route": []}
    return json.loads(path.read_text(encoding="utf-8"))


def export(code: str, out: Path) -> Path:
    done = checked(code)
    rows = []
    for source, entries in (("app", app_entries(code)), ("route", route_entries(code))):
        ticked = set(done.get(source, []))
        for section, english, draft in entries:
            where = ("Route: " if source == "route" else "") + (section or "Other")
            rows.append([where, english, draft, "", "yes" if english in ticked else "", source])
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{code}.csv"
    # A byte-order mark, so Excel opens it as UTF-8 (Amharic, Arabic and the rest).
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)
    return path


def _replace_ts(text: str, english: str, fix: str) -> str | None:
    for m in _TS_ENTRY.finditer(text):
        if _ts_literal(m[1]) == english:
            return text[: m.start(2)] + json.dumps(fix, ensure_ascii=False) + text[m.end(2) :]
    return None


def _replace_py(text: str, english: str, fix: str) -> str | None:
    table = _route_dict(ast.parse(text))
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line.encode("utf-8")))
    raw = text.encode("utf-8")
    for key, value in zip(table.keys, table.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == english:
            assert value.end_lineno is not None and value.end_col_offset is not None
            begin = starts[value.lineno - 1] + value.col_offset
            end = starts[value.end_lineno - 1] + value.end_col_offset
            literal = json.dumps(fix, ensure_ascii=False).encode("utf-8")
            return (raw[:begin] + literal + raw[end:]).decode("utf-8")
    return None


def import_sheet(code: str, sheet: Path) -> list[str]:
    """Writes the sheet's fixes and checks; returns the problems (nothing written if any)."""
    try:
        text = sheet.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return [f"{sheet} is not UTF-8: in Excel, Save As CSV UTF-8 (Comma delimited)"]
    # Excel in some countries saves with semicolons.
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter))
    files = {"app": app_path(code), "route": route_path(code)}
    texts = {source: path.read_text(encoding="utf-8") for source, path in files.items()}
    done = {source: set(keys) for source, keys in checked(code).items()}
    problems = []
    for number, row in enumerate(rows, start=2):
        source, english = (row.get("Key") or "").strip(), row.get("English") or ""
        if source not in files:
            problems.append(f"row {number}: the Key column must say app or route")
            continue
        fix = (row.get("Your fix") or "").strip()
        if fix:
            if sorted(_PLACE.findall(fix)) != sorted(_PLACE.findall(english)):
                problems.append(f"row {number}: keep the {{places}} of {english!r} in {fix!r}")
                continue
            replace = _replace_ts if source == "app" else _replace_py
            changed = replace(texts[source], english, fix)
            if changed is None:
                problems.append(f"row {number}: {english!r} is no longer in the catalog")
                continue
            texts[source] = changed
        if (row.get("Checked") or "").strip() or fix:
            done.setdefault(source, set()).add(english)
    if problems:
        return problems
    for source, path in files.items():
        path.write_text(texts[source], encoding="utf-8")
    CHECKED.mkdir(parents=True, exist_ok=True)
    (CHECKED / f"{code}.json").write_text(
        json.dumps({s: sorted(k) for s, k in sorted(done.items())}, ensure_ascii=False, indent=1)
        + "\n",
        encoding="utf-8",
    )
    sync()
    return []


def server_ts(code: str) -> str:
    """The app's copy of a language's route sentences (frontend/src/i18n/server/<code>.ts)."""
    # Read from the file itself, not lang.catalog: a module imported before an import ran is stale.
    body = "".join(
        f"  {json.dumps(english, ensure_ascii=False)}: {json.dumps(text, ensure_ascii=False)},\n"
        for _, english, text in route_entries(code)
    )
    return (
        "// Generated by scripts/translation_sheet.py sync from src/routemaker/"
        f"lang_{code}.py: do not edit.\n"
        "// The route's sentences, read back to English for the voice (lib/i18n.ts englishOf).\n"
        f"export const SERVER: Readonly<Record<string, string>> = {{\n{body}}};\n"
    )


def sync() -> None:
    SERVER_TS.mkdir(parents=True, exist_ok=True)
    for code in LANGUAGES:
        (SERVER_TS / f"{code}.ts").write_text(server_ts(code), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="write a review sheet (CSV) per language")
    ex.add_argument("code", choices=[*LANGUAGES, "all"])
    ex.add_argument("--out", type=Path, default=Path("translation-sheets"))
    im = sub.add_parser("import", help="write a filled sheet's fixes into the catalogs")
    im.add_argument("code", choices=LANGUAGES)
    im.add_argument("sheet", type=Path)
    sub.add_parser("sync", help="regenerate frontend/src/i18n/server/")
    args = parser.parse_args(argv)
    if args.command == "export":
        for code in LANGUAGES if args.code == "all" else [args.code]:
            print(export(code, args.out))
    elif args.command == "import":
        problems = import_sheet(args.code, args.sheet)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print("Nothing written.", file=sys.stderr)
            return 1
        print(
            f"Written. Review with: git diff -- {app_path(args.code).relative_to(ROOT)} "
            f"{route_path(args.code).relative_to(ROOT)}"
        )
    else:
        sync()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
