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
    python scripts/osm_edit.py upload edit.json --approved --live     # live OSM, owner's go

An edit file:

    {"server": "dev", "element": "node", "id": 123, "expect": {"highway": null},
     "set": {"highway": "traffic_signals"}, "comment": "Traffic signal, surveyed",
     "source": "survey"}

A null in "expect" means the tag is absent now; a null in "set" removes the tag.

The OAuth 2.0 token is saved to a file only its owner can read, outside the repo, and is
never printed or logged. Nothing here reads a GPS track: the edit note describes the place,
never who rode it or when. Standard library only, so it runs on the host without the
virtualenv.
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
    # Tests point this at a local stand-in; it is never set on the owner's PC.
    return os.environ.get("ROUTEMAKER_OSM_API") or SERVERS[server]["api"]


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
    if not isinstance(edit.get("id"), int) or edit["id"] <= 0:
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
        if value is not None and (not isinstance(value, str) or not value.strip()):
            return f"set[{key!r}] must be a non-empty string or null"
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


def upload(edit_path: Path, edit: dict, *, live: bool) -> int:
    if edit["server"] == "live" and not live:
        raise EditError("this edit is for live OSM: that needs --live, on the owner's go")
    if edit["server"] != "live" and live:
        raise EditError("--live given for an edit drafted for the test server")
    result_path = _result_path(edit_path)
    if result_path.exists():
        raise EditError(f"already uploaded (see {result_path}); one approval, one upload")
    token = _read_token(edit["server"])
    base = api_base(edit["server"])

    element = fetch_element(edit)
    tags = current_tags(element)
    stale = mismatches(edit, tags)
    if stale:
        raise EditError("changed on OSM since it was approved: " + "; ".join(stale))
    if all(tags.get(key) == value for key, value in edit["set"].items()):
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
                stale = mismatches(edit, current_tags(element))
                if stale:
                    raise EditError("someone else changed it while uploading: " + "; ".join(stale))
                continue
            raise EditError(f"OSM answered {status} saving the change: {body[:200]!r}")
        new_version = int(body.strip())
    finally:
        _request("PUT", f"{base}/changeset/{changeset}/close", token=token)

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
    log = _state_dir() / "osm-edits.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(json.dumps({"server": edit["server"], **result}) + "\n")
    print(f"Uploaded: {result['url']}")
    return 0


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
    path = token_path(server)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Created owner-only before anything is written to it, so the token is never readable
    # by anyone else, even for a moment.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(token)
    os.chmod(path, 0o600)
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
        if not args.approved:
            raise EditError("upload needs --approved: the owner approves each edit file")
        return upload(args.edit, edit, live=args.live)
    except EditError as error:
        print(f"Not uploaded: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
