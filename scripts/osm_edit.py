#!/usr/bin/env python3
"""Upload one owner-approved tag change to OpenStreetMap, under the owner's own account.

Internal tool (the owner, 2026-10-21: "if the root cause analysis shows that it's because
OSM data is wrong, we change it"). A drafted edit is a small JSON file naming one node or
way, the tag values the owner was shown ("expect") and the values to write ("set"). Each
upload is one change in one changeset, approved by the owner for that exact file: this is
manual mapping with a helper, never a bot, a queue or an import (OSM's Automated Edits code
of conduct), so there is no batch mode and at most one retry after a conflict.

    python scripts/osm_edit.py login --server dev --client-id <id>   # once, in a terminal
    python scripts/osm_edit.py show edit.json                         # the diff, no upload
    python scripts/osm_edit.py upload edit.json --approved            # dev server
    python scripts/osm_edit.py check edit.json                        # re-run the smoke test
    python scripts/osm_edit.py upload edit.json --approved --live     # live OSM, owner's go

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
import os
import secrets
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


def upload(edit_path: Path, edit: dict, *, live: bool) -> int:
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
    token = _read_token(edit["server"])
    base = api_base(edit["server"])

    element = fetch_element(edit)
    tags = current_tags(element)
    stale = mismatches(edit, tags)
    if stale:
        raise EditError("changed on OSM since it was approved: " + "; ".join(stale))
    if _already_done(edit, tags):
        raise EditError("OSM already says this; nothing to upload")

    status, body = _request(
        "PUT", f"{base}/changeset/create", body=changeset_xml(edit), token=token
    )
    if status != 200:
        raise EditError(f"OSM answered {status} opening a changeset: {body[:200]!r}")
    changeset = int(body.strip())
    try:
        for attempt in range(2):
            url = f"{base}/{edit['element']}/{edit['id']}"
            status, body = _request(
                "PUT", url, body=changed_element(element, edit, changeset), token=token
            )
            if status == 200:
                break
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
        new_version = int(body.strip())
    finally:
        try:
            _request("PUT", f"{base}/changeset/{changeset}/close", token=token)
        except EditError:
            # OSM closes an idle changeset by itself after an hour; say which one it is.
            web = SERVERS[edit["server"]]["web"]
            print(f"Could not close {web}/changeset/{changeset}", file=sys.stderr)

    web = SERVERS[edit["server"]]["web"]
    result = {
        "changeset": changeset,
        "url": f"{web}/changeset/{changeset}",
        "element": edit["element"],
        "id": edit["id"],
        "version": new_version,
        "set": edit["set"],
        "uploaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(json.dumps({"server": edit["server"], **result}) + "\n")
    print(f"Uploaded: {result['url']}")
    return report_check(edit, result)


def check_problems(edit: dict, result: dict) -> list[str]:
    """What OSM says now that does not match the upload recorded in `result`.

    The smoke test after an upload: the element carries the approved tags at the version
    the upload made (or a later one, if someone has edited since), and the changeset is
    closed with exactly one change in it.
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
            if changeset.get("changes_count") not in (None, "1"):
                problems.append(f"changeset holds {changeset.get('changes_count')} changes, not 1")
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
    send = commands.add_parser("upload", help="upload one approved edit")
    send.add_argument("edit", type=Path)
    send.add_argument("--approved", action="store_true", help="the owner approved this file")
    send.add_argument("--live", action="store_true", help="live OSM, on the owner's go")
    args = parser.parse_args(argv)
    try:
        if args.command == "login":
            return login(args.server, args.client_id)
        edit = load_edit(args.edit)
        if args.command == "show":
            return show(edit)
        if args.command == "check":
            return check(args.edit, edit)
        if not args.approved:
            raise EditError("upload needs --approved: the owner approves each edit file")
        return upload(args.edit, edit, live=args.live)
    except EditError as error:
        prefix = "Not uploaded" if args.command == "upload" else "Stopped"
        print(f"{prefix}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
