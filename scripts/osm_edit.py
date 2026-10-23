#!/usr/bin/env python3
"""Upload one owner-approved tag change to OpenStreetMap, under the owner's own account.

Internal tool (the owner, 2026-10-21: "if the root cause analysis shows that it's because
OSM data is wrong, we change it"). A drafted edit is a small JSON file naming one node or
way, the tag values the owner was shown ("expect") and the values to write ("set"). Each
upload is one change in one changeset, approved by the owner for that exact file: this is
manual mapping with a helper, never a bot, a queue or an import (OSM's Automated Edits code
of conduct), with at most one retry after a conflict. The one exception is
--one-changeset: a set of reviewed edits of one small area, sharing one note, that the
owner chose to put up together.

    python scripts/osm_edit.py login --server dev --client-id <id>   # once, in a terminal
    python scripts/osm_edit.py show edit.json                         # the diff, no upload
    python scripts/osm_edit.py upload edit.json --approved            # dev server
    python scripts/osm_edit.py check edit.json                        # re-run the smoke test
    python scripts/osm_edit.py draft-beacon --name ... --place ... --lat ... --lon ...
        --evidence ... --out DIR
    python scripts/osm_edit.py draft-signal --name ... --place ... --lat ... --lon ... --out DIR
    python scripts/osm_edit.py upload edit.json --approved --live     # live OSM, owner's go
    python scripts/osm_edit.py upload DIR/*.json --approved --live --one-changeset [--dry-run]
    python scripts/osm_edit.py apply DIR --approved --live --actor ID # OSM + our map, one folder
    python scripts/osm_edit.py load FIXTURE --actor ID [--confirm]    # our map only (e.g. beta)

An edit file:

    {"server": "dev", "element": "node", "id": 123, "expect": {"highway": null},
     "set": {"highway": "traffic_signals"}, "comment": "Traffic signal, surveyed",
     "source": "survey"}

A null in "expect" means the tag is absent now; a null in "set" removes the tag.

The OAuth 2.0 token is saved to a file only its owner can read, outside the repo, and is
never printed or logged. Nothing here reads a GPS track: the edit note describes the place,
never who rode it or when. Standard library only, so it runs on the host without the
virtualenv (Python 3.11 or later).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import secrets
import shlex
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

SERVERS = {
    "dev": {
        "web": "https://master.apis.dev.openstreetmap.org",
        "api": "https://master.apis.dev.openstreetmap.org/api/0.6",
    },
    "live": {
        "web": "https://www.openstreetmap.org",
        "api": "https://api.openstreetmap.org/api/0.6",
    },
}
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
SCOPES = "read_prefs write_api"
USER_AGENT = "RouteMaker-osm-edit/1.0 (bike route planner; one reviewed edit at a time)"
CREATED_BY = "RouteMaker osm_edit.py"
REPO = Path(__file__).resolve().parents[1]

# What an edit may touch: lasting facts a rider can see from the road (the proposal's
# "Yes, first" rows). Deliberately not the whole tag space; `highway` on a way would
# change the road's class, so it may only be set on a node, to a junction control.
ALLOWED_KEYS = frozenset(
    {
        "highway",
        "crossing",
        "crossing:signals",
        "traffic_signals",
        "traffic_signals:direction",
        "bicycle",
        "bicycle:forward",
        "bicycle:backward",
        "oneway:bicycle",
        "surface",
        "smoothness",
        "mtb:scale",
        "mtb:scale:imba",
    }
)
NODE_HIGHWAY_VALUES = frozenset({"traffic_signals", "stop", "give_way", "crossing"})
MAX_KEYS = 4


class EditError(Exception):
    """An edit that must not go up, and why, in words for the owner."""


def _state_dir() -> Path:
    override = os.environ.get("ROUTEMAKER_OSM_STATE")
    if override:
        return Path(override)
    return Path.home() / ".config" / "routemaker"


def token_path(server: str) -> Path:
    return _state_dir() / f"osm-{server}.token"


def api_base(server: str) -> str:
    return SERVERS[server]["api"]


def _request(
    method: str, url: str, *, body: bytes | None = None, token: str | None = None
) -> tuple[int, bytes]:
    headers = {"User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "text/xml; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError) as error:
        # The token is in the headers, never the URL, so naming the URL is safe.
        raise EditError(f"could not reach {url}: {error}") from None


# --- the edit file -------------------------------------------------------------------


def load_edit(path: Path) -> dict:
    edit = json.loads(path.read_text())
    problem = edit_problem(edit)
    if problem:
        raise EditError(f"{path}: {problem}")
    return edit


def edit_problem(edit: object) -> str | None:
    """Why `edit` is not one small, allowed tag change, or None if it is."""
    if not isinstance(edit, dict):
        return "an edit is a JSON object"
    if edit.get("server") not in SERVERS:
        return f"server must be one of {sorted(SERVERS)}"
    if edit.get("element") not in ("node", "way"):
        return "element must be node or way"
    if not isinstance(edit.get("id"), int) or isinstance(edit["id"], bool) or edit["id"] <= 0:
        return "id must be a positive OSM id"
    expect, changes = edit.get("expect"), edit.get("set")
    if not isinstance(expect, dict) or not isinstance(changes, dict) or not changes:
        return "expect and set are objects, and set names at least one tag"
    if set(changes) != set(expect):
        return "expect must name exactly the tags set changes, with what the owner was shown"
    if len(changes) > MAX_KEYS:
        return f"at most {MAX_KEYS} tags in one edit"
    for key, value in changes.items():
        if key not in ALLOWED_KEYS:
            return f"tag {key!r} is not one this tool may change"
        if value is not None and (
            not isinstance(value, str) or not value.strip() or value != value.strip()
        ):
            return f"set[{key!r}] must be a non-empty string with no spaces at the ends, or null"
        if value is not None and len(value) > 255:
            return f"set[{key!r}] is longer than OSM's 255 characters"
        if expect[key] is not None and not isinstance(expect[key], str):
            return f"expect[{key!r}] must be a string or null"
    if "highway" in changes:
        if edit["element"] != "node":
            return "highway may only change on a node (a way's highway is its road class)"
        if changes["highway"] is not None and changes["highway"] not in NODE_HIGHWAY_VALUES:
            return f"a node's highway may only be set to one of {sorted(NODE_HIGHWAY_VALUES)}"
    comment = edit.get("comment")
    if not isinstance(comment, str) or not comment.strip() or len(comment) > 255:
        return "comment is the changeset note: 1 to 255 characters"
    if edit.get("source", "survey") not in ("survey", "local_knowledge"):
        return "source is survey or local_knowledge (the owner's own sighting)"
    return None


# --- the element ---------------------------------------------------------------------


def fetch_element(edit: dict) -> ET.Element:
    url = f"{api_base(edit['server'])}/{edit['element']}/{edit['id']}"
    status, body = _request("GET", url)
    if status == 410:
        raise EditError(f"{edit['element']} {edit['id']} has been deleted on OSM")
    if status != 200:
        raise EditError(f"OSM answered {status} reading {edit['element']} {edit['id']}")
    element = ET.fromstring(body).find(edit["element"])
    if element is None:
        raise EditError(f"OSM's answer held no {edit['element']}")
    return element


def current_tags(element: ET.Element) -> dict[str, str]:
    return {tag.get("k"): tag.get("v") for tag in element.findall("tag")}


def mismatches(edit: dict, tags: dict[str, str]) -> list[str]:
    """The tags that no longer say what the owner was shown."""
    return [
        f"{key}: shown {edit['expect'][key]!r}, now {tags.get(key)!r}"
        for key in edit["set"]
        if tags.get(key) != edit["expect"][key]
    ]


def diff_lines(edit: dict, tags: dict[str, str]) -> list[str]:
    lines = []
    for key, new in edit["set"].items():
        old = tags.get(key)
        if old == new:
            lines.append(f"  {key}: {old!r} (already so; nothing to change)")
        else:
            lines.append(f"  {key}: {old!r} -> {new!r}")
    return lines


def changed_element(element: ET.Element, edit: dict, changeset: int) -> bytes:
    """The element as OSM holds it, with only the edit's tags changed."""
    for tag in list(element.findall("tag")):
        if tag.get("k") in edit["set"]:
            element.remove(tag)
    for key, value in edit["set"].items():
        if value is not None:
            ET.SubElement(element, "tag", {"k": key, "v": value})
    element.set("changeset", str(changeset))
    for attribute in ("user", "uid", "timestamp", "visible"):
        element.attrib.pop(attribute, None)
    root = ET.Element("osm", {"version": "0.6", "generator": CREATED_BY})
    root.append(element)
    return ET.tostring(root, encoding="utf-8")


def changeset_xml(edit: dict) -> bytes:
    root = ET.Element("osm")
    changeset = ET.SubElement(root, "changeset")
    for key, value in (
        ("comment", edit["comment"].strip()),
        ("source", edit.get("source", "survey")),
        ("created_by", CREATED_BY),
    ):
        ET.SubElement(changeset, "tag", {"k": key, "v": value})
    return ET.tostring(root, encoding="utf-8")


# --- commands ------------------------------------------------------------------------


def show(edit: dict) -> int:
    element = fetch_element(edit)
    tags = current_tags(element)
    print(f"{edit['element']} {edit['id']} on {edit['server']}, version {element.get('version')}")
    print("\n".join(diff_lines(edit, tags)))
    print(f"  note: {edit['comment']}")
    stale = mismatches(edit, tags)
    if stale:
        print("Changed on OSM since it was drafted; draft again before approving:")
        print("\n".join(f"  {line}" for line in stale))
        return 2
    return 0


def _read_token(server: str) -> str:
    path = token_path(server)
    if not path.exists():
        raise EditError(f"not signed in to {server}: run `osm_edit.py login --server {server}`")
    return path.read_text().strip()


def _result_path(edit_path: Path) -> Path:
    return edit_path.with_name(edit_path.stem + ".uploaded.json")


def _log_path() -> Path:
    return _state_dir() / "osm-edits.log"


def _already_logged(edit: dict) -> str | None:
    """The changeset URL of an earlier upload of this same change, from any file."""
    log = _log_path()
    if not log.exists():
        return None
    for line in log.read_text().splitlines():
        entry = json.loads(line)
        if (entry["server"], entry["element"], entry["id"], entry["set"]) == (
            edit["server"],
            edit["element"],
            edit["id"],
            edit["set"],
        ):
            return entry["url"]
    return None


def _already_done(edit: dict, tags: dict[str, str]) -> bool:
    return all(tags.get(key) == value for key, value in edit["set"].items())


def _ready(edit_path: Path, edit: dict, *, live: bool) -> ET.Element:
    """The element as OSM holds it now, once every guard before an upload has passed."""
    if edit["server"] == "live" and not live:
        raise EditError("this edit is for live OSM: that needs --live, on the owner's go")
    if edit["server"] != "live" and live:
        raise EditError("--live given for an edit drafted for the test server")
    result_path = _result_path(edit_path)
    if result_path.exists():
        raise EditError(f"already uploaded (see {result_path}); one approval, one upload")
    if (earlier := _already_logged(edit)) is not None:
        raise EditError(f"this change was already uploaded in {earlier}")
    if REPO in edit_path.resolve().parents:
        raise EditError("keep drafts outside the repo (the scratchpad or the private ride folder)")
    element = fetch_element(edit)
    tags = current_tags(element)
    stale = mismatches(edit, tags)
    if stale:
        raise EditError("changed on OSM since it was approved: " + "; ".join(stale))
    if _already_done(edit, tags):
        raise EditError("OSM already says this; nothing to upload")
    return element


def _open_changeset(edit: dict, token: str) -> int:
    base = api_base(edit["server"])
    status, body = _request(
        "PUT", f"{base}/changeset/create", body=changeset_xml(edit), token=token
    )
    if status != 200:
        raise EditError(f"OSM answered {status} opening a changeset: {body[:200]!r}")
    return int(body.strip())


def _close_changeset(server: str, changeset: int, token: str) -> None:
    try:
        _request("PUT", f"{api_base(server)}/changeset/{changeset}/close", token=token)
    except EditError:
        # OSM closes an idle changeset by itself after an hour; say which one it is.
        print(f"Could not close {SERVERS[server]['web']}/changeset/{changeset}", file=sys.stderr)


def _put_change(element: ET.Element, edit: dict, changeset: int, token: str) -> int:
    """Save one element's change in the open changeset; its new version."""
    url = f"{api_base(edit['server'])}/{edit['element']}/{edit['id']}"
    for attempt in range(2):
        status, body = _request(
            "PUT", url, body=changed_element(element, edit, changeset), token=token
        )
        if status == 200:
            return int(body.strip())
        if status == 409 and attempt == 0:
            # Someone else saved it in between. Try once more on the new version, and
            # only if the tags the owner approved changing still say what they were shown.
            element = fetch_element(edit)
            tags = current_tags(element)
            if _already_done(edit, tags):
                raise EditError("someone else made this same change while uploading")
            stale = mismatches(edit, tags)
            if stale:
                raise EditError("someone else changed it while uploading: " + "; ".join(stale))
            continue
        raise EditError(f"OSM answered {status} saving the change: {body[:200]!r}")
    raise EditError("OSM kept answering 409")


def _record(edit_path: Path, edit: dict, changeset: int, version: int, changes: int) -> dict:
    web = SERVERS[edit["server"]]["web"]
    result = {
        "changeset": changeset,
        "url": f"{web}/changeset/{changeset}",
        "element": edit["element"],
        "id": edit["id"],
        "version": version,
        "set": edit["set"],
        "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if changes != 1:
        result["changes"] = changes
    _result_path(edit_path).write_text(json.dumps(result, indent=2) + "\n")
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(json.dumps({"server": edit["server"], **result}) + "\n")
    return result


def upload(edit_path: Path, edit: dict, *, live: bool) -> int:
    element = _ready(edit_path, edit, live=live)
    token = _read_token(edit["server"])
    changeset = _open_changeset(edit, token)
    try:
        new_version = _put_change(element, edit, changeset, token)
    finally:
        _close_changeset(edit["server"], changeset, token)
    result = _record(edit_path, edit, changeset, new_version, 1)
    print(f"Uploaded: {result['url']}")
    return report_check(edit, result)


# One changeset for a set of edits: the owner, 2026-10-21, chose "One changeset for all 74"
# for the Capitol grounds walks, one tag on many short ways of one small area, all surveyed.
# Every edit is still reviewed, and the set shares one comment and one source.
MAX_TOGETHER = 100


def upload_together(paths: list[Path], *, live: bool, dry_run: bool) -> int:
    edits = [(path, load_edit(path)) for path in paths]
    if len(edits) > MAX_TOGETHER:
        raise EditError(f"at most {MAX_TOGETHER} edits in one changeset")
    first = edits[0][1]
    for path, edit in edits:
        for key in ("server", "comment", "source"):
            if edit.get(key, "survey") != first.get(key, "survey"):
                raise EditError(f"{path.name}: {key} differs; one changeset shares one {key}")
    targets = [(edit["element"], edit["id"]) for _, edit in edits]
    if len(set(targets)) != len(targets):
        raise EditError("the same element appears twice; one change per element")
    ready, problems = [], []
    # A rerun of the same line after a stop picks up where it stopped.
    done = [path for path, _ in edits if _result_path(path).exists()]
    for path in done:
        print(f"{path.name}: already uploaded, skipped")
    edits = [(path, edit) for path, edit in edits if path not in done]
    if not edits:
        raise EditError("every file is already uploaded; one approval, one upload")
    for path, edit in edits:
        try:
            ready.append((path, edit, _ready(path, edit, live=live)))
        except EditError as error:
            problems.append(f"{path.name}: {error}")
    if problems:
        raise EditError("nothing uploaded:\n  " + "\n  ".join(problems))
    for path, edit, element in ready:
        print(f"{path.name}: {edit['element']} {edit['id']} v{element.get('version')}")
        for line in diff_lines(edit, current_tags(element)):
            print(f"  {line}")
    print(f"\nOne changeset, {len(ready)} changes. Note: {first['comment']}")
    if dry_run:
        print("Dry run: nothing uploaded.")
        return 0
    token = _read_token(first["server"])
    changeset = _open_changeset(first, token)
    saved: list[tuple[Path, dict, int]] = []
    failure = None
    results: list[dict] = []
    try:
        for path, edit, element in ready:
            try:
                saved.append((path, edit, _put_change(element, edit, changeset, token)))
            except EditError as error:
                failure = f"{path.name}: {error}"
                break
    finally:
        # Whatever stopped the loop (a refusal, Ctrl-C, an odd answer), what went in is
        # recorded, so it is never uploaded twice and the smoke test can find it.
        _close_changeset(first["server"], changeset, token)
        results = [
            _record(path, edit, changeset, version, len(saved)) for path, edit, version in saved
        ]
        if results:
            print(f"Uploaded {len(results)} changes: {results[0]['url']}")
        rest = [str(path) for path, _, _ in ready[len(saved) :]]
        if rest:
            print(f"Stopped at {failure or 'an interruption'}", file=sys.stderr)
            print(
                "Not uploaded (OSM may still hold the one it stopped on; the check says): "
                + " ".join(rest),
                file=sys.stderr,
            )
    # Once anything went in, a stop is never a plain "not uploaded": 3, as the single upload.
    worst = 3 if failure and saved else 1 if failure else 0
    for (_, edit, _), result in zip(saved, results, strict=True):
        worst = max(worst, report_check(edit, result))
    return worst


def check_problems(edit: dict, result: dict) -> list[str]:
    """What OSM says now that does not match the upload recorded in `result`.

    The smoke test after an upload: the element carries the approved tags at the version
    the upload made (or a later one, if someone has edited since), and the changeset is
    closed holding exactly the changes the upload made (one, or a --one-changeset set).
    """
    problems = []
    element = fetch_element(edit)
    version = int(element.get("version"))
    if version < result["version"]:
        problems.append(f"OSM is at version {version}, older than the upload's {result['version']}")
    elif version == result["version"] and element.get("changeset") != str(result["changeset"]):
        problems.append(f"version {version} belongs to changeset {element.get('changeset')}")
    if version == result["version"]:
        tags = current_tags(element)
        problems += [
            f"{key}: expected {value!r}, OSM has {tags.get(key)!r}"
            for key, value in edit["set"].items()
            if tags.get(key) != value
        ]
    url = f"{api_base(edit['server'])}/changeset/{result['changeset']}"
    status, body = _request("GET", url)
    if status != 200:
        problems.append(f"OSM answered {status} reading changeset {result['changeset']}")
    else:
        changeset = ET.fromstring(body).find("changeset")
        if changeset is None:
            problems.append("OSM's answer held no changeset")
        else:
            if changeset.get("open") != "false":
                problems.append(f"changeset {result['changeset']} is still open")
            expected = str(result.get("changes", 1))
            if changeset.get("changes_count") not in (None, expected):
                problems.append(
                    f"changeset holds {changeset.get('changes_count')} changes, not {expected}"
                )
    return problems


def report_check(edit: dict, result: dict) -> int:
    try:
        problems = check_problems(edit, result)
    except (EditError, ET.ParseError) as error:
        # After an upload this must never read as "Not uploaded": the change may be in.
        problems = [f"could not check: {error}"]
    if problems:
        print("Check FAILED:", file=sys.stderr)
        print("\n".join(f"  {line}" for line in problems), file=sys.stderr)
        return 3
    print(f"Checked: {edit['element']} {edit['id']} has the change, changeset closed")
    return 0


def check(edit_path: Path, edit: dict) -> int:
    result_path = _result_path(edit_path)
    if not result_path.exists():
        raise EditError(f"no upload recorded for {edit_path} ({result_path} is missing)")
    return report_check(edit, json.loads(result_path.read_text()))


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def login(server: str, client_id: str) -> int:
    verifier, challenge = _pkce()
    web = SERVERS[server]["web"]
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    print(f"Open this, sign in and allow access:\n\n  {web}/oauth2/authorize?{query}\n")
    code = input("Paste the code OSM shows: ").strip()
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(
        f"{web}/oauth2/token",
        data=form,
        method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            token = json.loads(response.read())["access_token"]
    except urllib.error.HTTPError as error:
        raise EditError(f"OSM refused the code ({error.code}); run login again") from None
    except (urllib.error.URLError, OSError) as error:
        raise EditError(f"could not reach {web}: {error}") from None
    path = token_path(server)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Owner-only before anything is written: os.open's mode only applies to a new file, so an
    # older, wider file is narrowed first and the token is never readable by anyone else.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    status, body = _request("GET", f"{api_base(server)}/user/details.json", token=token)
    name = json.loads(body)["user"]["display_name"] if status == 200 else "(unknown)"
    print(f"Signed in to {server} as {name}. The token is in {path}, readable only by you.")
    return 0


# --- drafting from a field report ---------------------------------------------------
#
# A rider (the owner or a tester) reports a corner; these find the OSM elements there and
# write the drafts, so a fix is one command, one look at the diffs, one upload. They only
# read OSM. Nothing is uploaded until the owner runs `upload --approved` on the files.

BEACON_REACH_M = 40.0
JUNCTION_REACH_M = 25.0


def _metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = rlat2 - rlat1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def fetch_area(server: str, lat: float, lon: float, reach_m: float) -> ET.Element:
    """Everything OSM has in a small box around (lat, lon)."""
    dlat = reach_m / 111_000 * 1.5
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    box = f"{lon - dlon:.7f},{lat - dlat:.7f},{lon + dlon:.7f},{lat + dlat:.7f}"
    status, body = _request("GET", f"{api_base(server)}/map?bbox={box}")
    if status != 200:
        raise EditError(f"OSM answered {status} reading the area around {lat}, {lon}")
    return ET.fromstring(body)


def _slug(name: str, place: str) -> str:
    words = "".join(c if c.isalnum() else " " for c in f"{name} {place}".lower()).split()
    slug = "-".join(w for w in words if w != "and")[:80].strip("-")
    if not slug:
        raise EditError(
            "--name and --place must name the corner, e.g. 'Connecticut Ave and "
            "Washington St' in 'Kensington'"
        )
    return slug


def _claim(*paths: Path) -> None:
    """Refuse before writing anything if any draft would overwrite a file."""
    taken = [str(path) for path in paths if path.exists()]
    if taken:
        raise EditError(f"already exists: {', '.join(taken)}; draft into a new folder")


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2) + "\n")
    return path


def _report_drafts(paths: list[Path], extra: list[str]) -> int:
    for path in paths:
        print(f"\n{path.name}")
        show(load_edit(path))
    for line in extra:
        print(line)
    folder = paths[0].parent
    owner_row = any(_is_owner_file(path) for path in folder.glob("*.json"))
    print(
        "\nAfter the owner approves, one line does OSM"
        + (" and our map" if owner_row else "")
        + f":\n  python3 {Path(__file__).resolve()} apply {folder} --approved"
        + (" --live" if load_edit(paths[0])["server"] == "live" else "")
        + (" --actor <owner's Discord id>" if owner_row else "")
    )
    return 0


def _fixture_dirs() -> list[Path]:
    # The repo's own when run from a checkout; the PC's checkout when run from the copy
    # outside it (docs/OPERATIONS.md, "Fixing OSM from a ride").
    candidates = [
        REPO / "fixtures" / "flashing-signals",
        Path.home() / "src" / "RouteMaker" / "fixtures" / "flashing-signals",
    ]
    return [path for path in candidates if path.is_dir()]


def _nearby_owner_beacons(lat: float, lon: float) -> list[str] | None:
    """Owner beacon rows already checked in near the point, or None if none could be read."""
    dirs = _fixture_dirs()
    if not dirs:
        return None
    found = []
    for path in sorted(dirs[0].glob("*.json")):
        for row in json.loads(path.read_text()).get("rows", []):
            if _metres(lat, lon, row["lat"], row["lon"]) <= 2 * BEACON_REACH_M:
                found.append(f"{row['id']} ({path.name})")
    return found


def draft_beacon(args: argparse.Namespace) -> int:
    """A signal that runs as a flashing beacon: OSM's signal nodes there become blinkers,
    and an owner flashing-signal row is written for our own map (no rebuild)."""
    root = fetch_area(args.server, args.lat, args.lon, BEACON_REACH_M)
    nodes = [
        node
        for node in root.iter("node")
        if node.find("tag[@k='highway'][@v='traffic_signals']") is not None
        and _metres(args.lat, args.lon, float(node.get("lat")), float(node.get("lon")))
        <= BEACON_REACH_M
    ]
    if not nodes:
        raise EditError(
            f"OSM has no highway=traffic_signals node within {BEACON_REACH_M:.0f} m; "
            "check the point, or this is a missing signal (draft-signal), not a beacon"
        )
    slug = _slug(args.name, args.place)
    label = f"{args.name}, {args.place}"
    today = datetime.now(UTC).date().isoformat()
    nearby = _nearby_owner_beacons(args.lat, args.lon)
    to_edit = [n for n in nodes if current_tags(n).get("traffic_signals") != "blinker"]
    skipped = [n.get("id") for n in nodes if n not in to_edit]
    edits = {
        args.out / f"{slug}-{node.get('id')}.json": {
            "server": args.server,
            "element": "node",
            "id": int(node.get("id")),
            "expect": {"traffic_signals": current_tags(node).get("traffic_signals")},
            "set": {"traffic_signals": "blinker"},
            "comment": f"{label}: signal runs as a flashing beacon (surveyed)",
            "source": "survey",
        }
        for node in to_edit
    }
    for edit in edits.values():
        if problem := edit_problem(edit):
            raise EditError(problem)
    # Named as the checked-in owner files are, so it can be committed as it is.
    fixture = args.out / f"{today}-owner-{slug}.json"
    _claim(fixture, *edits)
    args.out.mkdir(parents=True, exist_ok=True)
    paths = [_write_json(path, edit) for path, edit in edits.items()]
    extra = []
    if nearby:
        # A second owner row at the same corner would be a duplicate: owner loads never
        # withdraw one. The OSM edits still stand on their own.
        extra.append(
            f"\nOur map already has an owner beacon here: {', '.join(nearby)}. No new row written."
        )
    else:
        _write_json(
            fixture,
            {
                "version": 1,
                "source": "owner",
                "decided": today,
                "decided_by": "the deployment owner",
                "status": "Load with load_flashing_signals (dry run first); takes effect at the "
                "next plan, no rebuild.",
                "rows": [
                    {
                        "id": slug,
                        "name": label,
                        "lon": round(args.lon, 7),
                        "lat": round(args.lat, 7),
                        "evidence": args.evidence,
                    }
                ],
            },
        )
        extra.append(
            f"\nOur map: {fixture.name} (load_flashing_signals, then commit it to "
            "fixtures/flashing-signals/)"
        )
        if nearby is None:
            extra.append(
                "Could not read the checked-in beacon files: check for a row here before loading."
            )
    if skipped:
        extra.append(f"Already blinkers on OSM, left alone: {', '.join(skipped)}")
    if not paths:
        print("\n".join(extra))
        print("OSM already has every signal there as a blinker.")
        if not nearby:
            print(
                f"  python3 {Path(__file__).resolve()} load {fixture} --actor <owner's "
                "Discord id> --confirm"
            )
        return 0
    return _report_drafts(paths, extra)


def _way_tag(way: ET.Element, key: str) -> str:
    tag = way.find(f"tag[@k='{key}']")
    return tag.get("v") if tag is not None else ""


def _junction_nodes(root: ET.Element) -> set[str]:
    """Nodes where streets meet: on three or more highway ways, inside one way and on
    another, or ending two ways of different streets. Two ways that just continue one
    street end to end (a split at a bridge or a tag change) are not a junction."""
    ways: dict[str, list[tuple[bool, str]]] = {}
    for way in root.iter("way"):
        if way.find("tag[@k='highway']") is None:
            continue
        refs = [nd.get("ref") for nd in way.iter("nd")]
        street = _way_tag(way, "name") or _way_tag(way, "ref") or way.get("id")
        closed = len(refs) > 1 and refs[0] == refs[-1]
        for ref in dict.fromkeys(refs):
            at_end = not closed and ref in (refs[0], refs[-1])
            ways.setdefault(ref, []).append((at_end, street))
    junctions = set()
    for ref, uses in ways.items():
        if len(uses) >= 3 or (
            len(uses) == 2 and (not uses[0][0] or not uses[1][0] or uses[0][1] != uses[1][1])
        ):
            junctions.add(ref)
    return junctions


def draft_signal(args: argparse.Namespace) -> int:
    """A working signal OSM lacks: the junction node nearest the point gets
    highway=traffic_signals."""
    root = fetch_area(args.server, args.lat, args.lon, JUNCTION_REACH_M)
    junctions = _junction_nodes(root)
    best, best_m = None, JUNCTION_REACH_M
    for node in root.iter("node"):
        if node.get("id") not in junctions:
            continue
        m = _metres(args.lat, args.lon, float(node.get("lat")), float(node.get("lon")))
        if m <= best_m:
            best, best_m = node, m
    if best is None:
        raise EditError(f"no junction node within {JUNCTION_REACH_M:.0f} m of the point")
    tags = current_tags(best)
    if tags.get("highway") == "traffic_signals":
        raise EditError(f"node {best.get('id')} already has highway=traffic_signals")
    if "highway" in tags:
        raise EditError(
            f"node {best.get('id')} is highway={tags['highway']}; change that by hand in an editor"
        )
    edit = {
        "server": args.server,
        "element": "node",
        "id": int(best.get("id")),
        "expect": {"highway": None},
        "set": {"highway": "traffic_signals"},
        "comment": f"{args.name}, {args.place}: traffic signal (surveyed)",
        "source": "survey",
    }
    if problem := edit_problem(edit):
        raise EditError(problem)
    path = args.out / f"{_slug(args.name, args.place)}-{best.get('id')}.json"
    _claim(path)
    args.out.mkdir(parents=True, exist_ok=True)
    _write_json(path, edit)
    extra = [
        f"\nJunction node {best.get('id')}, {best_m:.0f} m from the point. A dual carriageway "
        "meets a street at two nodes: if so, draft the other one too."
    ]
    return _report_drafts([path], extra)


def upload_all(paths: list[Path], *, live: bool, rerun_ok: bool = False) -> int:
    """Each file its own upload, in turn, stopping at the first failure. A rerun of the same
    line after a failure picks up where it stopped."""
    edits = [(path, load_edit(path)) for path in paths]
    pending = [(path, edit) for path, edit in edits if not _result_path(path).exists()]
    for path, edit in edits:
        if (path, edit) not in pending:
            print(f"{path.name}: already uploaded, skipped")
    if not pending and not rerun_ok:
        raise EditError("every file is already uploaded; one approval, one upload")
    for done, (path, edit) in enumerate(pending):
        print(f"{path.name}:")
        try:
            code = upload(path, edit, live=live)
        except EditError as e:
            print(f"Not uploaded: {e}", file=sys.stderr)
            code = 1
        if code:
            rest = " ".join(str(p) for p, _ in pending[done:])
            print(f"Stopped. Still to upload: {rest}", file=sys.stderr)
            return code
    return 0


# Our map's side. Each site's api container runs the loader; the fixture goes in on standard
# input because the api image has no fixtures/ (load_flashing_signals docstring). The PC's
# live stack is a compose folder here; beta is reached over ssh and runs it from its own
# checkout through beta-compose.sh (docs/BETA-RUNBOOK.md, sections 0 and 1). The ssh host
# name stays out of the repo: it comes from ROUTEMAKER_BETA_SSH or --beta-host. The PC's
# stack folder can move: ROUTEMAKER_LIVE_DIR or --stack.
DEFAULT_STACK = Path(os.environ.get("ROUTEMAKER_LIVE_DIR", Path.home() / "src" / "wt" / "t9"))
SITES = ("pc", "beta")
BETA_CD = '. "$HOME/routemaker-beta-state/vars.sh" && cd "$RM_SRC" && scripts/beta/beta-compose.sh'
NOT_YET = ("create:", "update:", "restore:", "withdrawn:")


def _site_command(
    args: argparse.Namespace, site: str, loader: list[str]
) -> tuple[list[str], Path | None]:
    if site == "pc":
        return [*shlex.split(args.compose), *loader], args.stack
    host = args.beta_host or os.environ.get("ROUTEMAKER_BETA_SSH")
    if not host:
        raise EditError("beta needs its ssh host: --beta-host, or ROUTEMAKER_BETA_SSH")
    return ["ssh", host, " ".join([BETA_CD, *map(shlex.quote, loader)])], None


def _loader(args: argparse.Namespace, site: str, fixture: Path, confirm: bool) -> str:
    loader = ["exec", "-T", "api", "python", "manage.py", "load_flashing_signals", "-"]
    loader += ["--actor", str(args.actor)] + (["--confirm"] if confirm else [])
    command, cwd = _site_command(args, site, loader)
    try:
        with fixture.open("rb") as stdin:
            done = subprocess.run(
                command, cwd=cwd, stdin=stdin, capture_output=True, text=True, check=False
            )
    except OSError as e:
        raise EditError(f"could not run the loader for {site}: {e}") from e
    print(done.stdout, end="")
    if done.returncode:
        raise EditError(f"the {site} loader stopped: {done.stderr.strip() or done.returncode}")
    return done.stdout


def _is_owner_file(path: Path) -> bool:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(document, dict) and document.get("source") == "owner" and "rows" in document


def _owner_rows(fixture: Path) -> list[dict]:
    if not _is_owner_file(fixture):
        raise EditError(f"{fixture.name} is not an owner flashing-signal file")
    rows = json.loads(fixture.read_text())["rows"]
    if not rows:
        raise EditError(f"{fixture.name} has no rows")
    return rows


def _all_present(output: str, rows: list[dict]) -> bool:
    """The loader's dry run finds every row active and unchanged: its summary line is
    '<stdin>: owner, N present' and nothing else (load_flashing_signals, handle)."""
    lines = output.splitlines()
    return not any(line.startswith(NOT_YET) for line in lines) and any(
        line.endswith(f": owner, {len(rows)} present") for line in lines
    )


def _preflight(args: argparse.Namespace, fixture: Path) -> None:
    """A dry run at every site, before anything is written anywhere: a wrong actor, a missing
    ssh host or an unreachable site stops here, not after the OSM upload."""
    for site in args.to:
        print(f"Our map on {site}, dry run:")
        _loader(args, site, fixture, confirm=False)


def load(args: argparse.Namespace, fixture: Path, *, confirm: bool, checked: bool = False) -> int:
    """For each site: a dry run (unless done already); with confirm, the write and then a dry
    run again that must find every row there (the read-back for our side). A site that
    fails does not stop the next one."""
    rows = _owner_rows(fixture)
    if not checked:
        _preflight(args, fixture)
    if not confirm:
        print("Nothing written; add --confirm to load it.")
        return 0
    done, failed = [], []
    for site in args.to:
        try:
            print(f"Loading on {site}:")
            _loader(args, site, fixture, confirm=True)
            if not _all_present(_loader(args, site, fixture, confirm=False), rows):
                raise EditError("the row is not active after the load")
            done.append(site)
        except EditError as e:
            failed.append(f"{site}: {e}")
    if done:
        print(f"Checked: {len(rows)} row(s) active on {', '.join(done)}, from the next plan")
    if failed:
        print("Check FAILED: " + "; ".join(failed), file=sys.stderr)
        again = " ".join(f"--to {f.split(':')[0]}" for f in failed)
        print(
            f"Rerun for the rest: load {fixture} --actor {args.actor} {again} --confirm",
            file=sys.stderr,
        )
        return 3
    return 0


def apply(args: argparse.Namespace) -> int:
    """One approved draft folder: every OSM edit in it, then our map's owner row if any."""
    folder = args.folder
    if not folder.is_dir():
        raise EditError(f"{folder} is not a draft folder")
    files = sorted(p for p in folder.glob("*.json") if not p.name.endswith(".uploaded.json"))
    fixtures = [p for p in files if _is_owner_file(p)]
    edits = [p for p in files if p not in fixtures]
    if len(fixtures) > 1:
        raise EditError(f"more than one owner file in {folder}: one corner per folder")
    if fixtures and args.actor is None:
        raise EditError("loading our row needs --actor (the owner's Discord id)")
    if not edits and not fixtures:
        raise EditError(f"nothing to apply in {folder}")
    for path in edits:
        if problem := edit_problem(load_edit(path)):
            raise EditError(f"{path.name}: {problem}")
    if fixtures:
        _owner_rows(fixtures[0])
        _preflight(args, fixtures[0])
    if edits and (code := upload_all(edits, live=args.live, rerun_ok=True)):
        print("Our map not loaded: the OSM side stopped first.", file=sys.stderr)
        return code
    if fixtures:
        return load(args, fixtures[0], confirm=True, checked=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    sign_in = commands.add_parser("login", help="sign in once and keep the token on this PC")
    sign_in.add_argument("--server", choices=sorted(SERVERS), required=True)
    sign_in.add_argument("--client-id", required=True)
    look = commands.add_parser("show", help="print the change against OSM as it is now")
    look.add_argument("edit", type=Path)
    again = commands.add_parser("check", help="re-check an uploaded edit against OSM now")
    again.add_argument("edit", type=Path)
    for kind, helptext in (
        ("draft-beacon", "a signal that runs as a flashing beacon: blinker edits + our row"),
        ("draft-signal", "a working signal OSM lacks: highway=traffic_signals on the junction"),
    ):
        draft = commands.add_parser(kind, help=helptext)
        draft.add_argument("--name", required=True, help="e.g. 'Connecticut Ave and Washington St'")
        draft.add_argument("--place", required=True, help="the town or area, e.g. 'Kensington'")
        draft.add_argument("--lat", type=float, required=True)
        draft.add_argument("--lon", type=float, required=True)
        draft.add_argument("--server", choices=sorted(SERVERS), default="live")
        draft.add_argument("--out", type=Path, required=True, help="a new folder outside the repo")
        if kind == "draft-beacon":
            draft.add_argument(
                "--evidence", required=True, help="what was seen, in the reporter's words"
            )
    send = commands.add_parser("upload", help="upload approved edits, one changeset each")
    send.add_argument("edit", type=Path, nargs="+")
    send.add_argument("--approved", action="store_true", help="the owner approved this file")
    send.add_argument("--live", action="store_true", help="live OSM, on the owner's go")
    send.add_argument(
        "--one-changeset",
        action="store_true",
        help="all the files in one changeset (one area, one tag, one note)",
    )
    send.add_argument(
        "--dry-run",
        action="store_true",
        help="with --one-changeset: every check and diff, nothing uploaded",
    )
    for kind, helptext in (
        ("apply", "an approved draft folder: upload its OSM edits, then load our row"),
        ("load", "load an owner flashing-signal file into our map (dry run unless --confirm)"),
    ):
        step = commands.add_parser(kind, help=helptext)
        step.add_argument("folder" if kind == "apply" else "fixture", type=Path)
        step.add_argument(
            "--actor",
            type=int,
            required=kind == "load",
            help="the owner's Discord id, as load_flashing_signals takes it",
        )
        step.add_argument(
            "--to",
            choices=SITES,
            action="append",
            help="where our row goes; repeat for both (default: pc and beta)",
        )
        step.add_argument(
            "--stack",
            type=Path,
            default=DEFAULT_STACK,
            help="the PC's compose folder (default: the live stack)",
        )
        step.add_argument("--compose", default="docker compose", help=argparse.SUPPRESS)
        step.add_argument("--beta-host", help="beta's ssh host (or ROUTEMAKER_BETA_SSH)")
        if kind == "apply":
            step.add_argument(
                "--approved", action="store_true", help="the owner approved this folder"
            )
            step.add_argument("--live", action="store_true", help="live OSM, on the owner's go")
        else:
            step.add_argument("--confirm", action="store_true", help="write (dry run without it)")
    args = parser.parse_args(argv)
    if args.command in ("apply", "load"):
        args.to = list(dict.fromkeys(args.to or SITES))
    try:
        if args.command == "login":
            return login(args.server, args.client_id)
        if args.command in ("draft-beacon", "draft-signal"):
            if REPO in args.out.resolve().parents or args.out.resolve() == REPO:
                raise EditError("draft outside the repo (the scratchpad or the private folder)")
            return (draft_beacon if args.command == "draft-beacon" else draft_signal)(args)
        if args.command == "apply":
            if not args.approved:
                raise EditError("apply needs --approved: the owner approved this folder")
            return apply(args)
        if args.command == "load":
            return load(args, args.fixture, confirm=args.confirm)
        if args.command == "upload":
            if args.dry_run and not args.one_changeset:
                raise EditError("--dry-run goes with --one-changeset; use show for one file")
            if not args.approved and not args.dry_run:
                raise EditError("upload needs --approved: the owner approves each edit file")
            # A rerun with the same DIR/*.json also matches the result files; skip them.
            edits = [p for p in args.edit if not p.name.endswith(".uploaded.json")]
            if args.one_changeset:
                return upload_together(edits, live=args.live, dry_run=args.dry_run)
            return upload_all(edits, live=args.live)
        edit = load_edit(args.edit)
        if args.command == "show":
            return show(edit)
        return check(args.edit, edit)
    except EditError as error:
        prefix = "Not uploaded" if args.command == "upload" else "Stopped"
        print(f"{prefix}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
