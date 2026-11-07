#!/usr/bin/env python3
"""Read the testers' Discord forums, and tell a report's post when its change ships.

Internal tool (the owner, 2026-10-21): testers report bugs, routing issues, road ratings and
feature requests as forum posts, one post per entry. This script, run with a bot token the
owner made, does three things and nothing else:

    python scripts/discord_reports.py check                       # token, forums, status tags
    python scripts/discord_reports.py fetch --out reports.md [--days 14]
    python scripts/discord_reports.py merged POST --version v0.11.0 [--dry-run]
    python scripts/discord_reports.py live v0.11.0 [--dry-run]
    python scripts/discord_reports.py changelog v0.11.0 docs/releases/v0.11.0.md \\
        [--live-date 2026-10-31] [--dry-run]

`fetch` writes the forums' posts to a Markdown file for Claude to read: titles, tags, links
and the messages' words, with no tester's name (a message is "tester", "owner" or "bot").
`merged` is run when the change a post asked for merges into a release branch: the bot
replies "This change is in vX.Y.Z, coming in the next beta release." and sets the post's
"In next release" tag. `live` is run by the beta's release agent after a deploy: every post
tagged "In next release" whose change is in that version or an earlier one gets "vX.Y.Z is
live on beta. Give it a try and let us know how it goes." and the tag "Live on beta". The
owner chose (2026-10-21, decision card) that these two replies post without asking each
time; anything else the bot says waits for his OK on the draft. Discord itself is the
record: the tag says where a post stands and the bot's own reply names the version, so the
beta needs no list of posts.

`changelog` (the owner, 2026-11-07: "I want a bot I have control over") posts a release's
rider notes to the changelog channel as the bot, in place of the old release webhook: the
title "RouteMaker vX.Y.Z is on beta", then the notes, split at line ends to fit, and each image
line of the notes (`![caption](images/v0.22.0/tags.png)`, a path inside docs/releases/) as its
own message: the image attached, the caption as its words and its alt text. The bot reads
its own recent messages in the channel first and posts only the messages not there yet, so a
retried pass never posts twice and one that stopped part-way finishes. The beta's release
agent runs it once per deployed tag.

The settings live outside the repo, in --dir (default ~/.config/routemaker-discord):

    bot-token          the bot's token, one line, mode 600; never printed or logged
    forums             the forum channels' ids, one per line (# starts a comment)
    changelog-channel  the changelog channel's id (only for `changelog`); the bot needs View
                       Channel, Send Messages, Attach Files and Read Message History there

The bot needs View Channels, Read Message History, Send Messages in Threads ("...in Threads
and Posts" in a server's role settings) and Manage Threads (to set the status tags), and the
Message Content intent for `fetch`. Mentions are switched off in everything it posts. A locked
post is skipped. Standard library only, so it runs on the host without the virtualenv (Python
3.11 or later).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/Macrophage87/RouteMaker, 1)"
NEXT_TAG = "In next release"
LIVE_TAG = "Live on beta"
STATUS_TAGS = (NEXT_TAG, LIVE_TAG)
MERGED_TEXT = "This change is in {version}, coming in the next beta release."
LIVE_TEXT = "{version} is live on beta. Give it a try and let us know how it goes."
MERGED_RE = re.compile(r"This change is in (v\d+\.\d+\.\d+)\b")
SEMVER_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MAX_TAGS = 5  # Discord's limit on a forum post's tags
NO_MENTIONS = {"parse": []}


class DiscordError(Exception):
    pass


class Locked(DiscordError):
    """A post the owner locked: skipped, not retried, since only he can open it again."""


def semver(tag: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(tag)
    if not match:
        raise DiscordError(f"not a version like v0.11.0: {tag!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def multipart(payload: dict, files: list[Path]) -> tuple[bytes, str]:
    """A message with attachments, as Discord takes it: payload_json, then files[n]."""
    boundary = "routemaker" + os.urandom(12).hex()
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode()
        + json.dumps(payload).encode()
        + b"\r\n"
    ]
    for n, path in enumerate(files):
        kind = IMAGE_TYPES[path.suffix.lower()]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{n}]"; '
            f'filename="{path.name}"\r\nContent-Type: {kind}\r\n\r\n'.encode()
            + path.read_bytes()
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Discord:
    """The few REST calls the script makes. `send` is the one seam the tests replace."""

    def __init__(self, token: str) -> None:
        self._token = token

    def send(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        files: tuple[Path, ...] | list[Path] = (),
    ):
        content_type = "application/json"
        if files:
            data, content_type = multipart(body or {}, files)
        else:
            data = None if body is None else json.dumps(body).encode()
        for _ in range(5):
            request = urllib.request.Request(API + path, data=data, method=method)
            request.add_header("Authorization", f"Bot {self._token}")
            request.add_header("User-Agent", USER_AGENT)
            if data is not None:
                request.add_header("Content-Type", content_type)
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    raw = response.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as error:
                if error.code == 429:
                    try:
                        wait = float(json.loads(error.read() or b"{}").get("retry_after", 1))
                    except (ValueError, AttributeError):  # Cloudflare's 429 is an HTML page
                        wait = float(error.headers.get("Retry-After") or 1)
                    time.sleep(min(wait, 30))
                    continue
                # The reason only: the response never carries the token, the request might.
                raise DiscordError(f"{method} {path}: HTTP {error.code}") from None
            except urllib.error.URLError as error:
                raise DiscordError(f"{method} {path}: {error.reason}") from None
        raise DiscordError(f"{method} {path}: still rate limited")

    def get(self, path: str):
        return self.send("GET", path)


MAX_CHARS = 2000  # Discord's limit on one message
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # Discord's upload limit for a bot in a server with no boost
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
IMAGE_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
CHANGELOG_TITLE = "**RouteMaker {version} is on beta**"


def changelog_channel(where: Path) -> str:
    path = where / "changelog-channel"
    if not path.is_file():
        raise DiscordError(f"no changelog channel: put its id in {path}")
    lines = [line.split("#", 1)[0].strip() for line in path.read_text().splitlines()]
    ids = [line for line in lines if line]
    if len(ids) != 1 or not ids[0].isdigit():
        raise DiscordError(f"{path}: expected one channel id")
    return ids[0]


def changelog_messages(
    version: str, notes: str, limit: int = MAX_CHARS, live: str | None = None
) -> list[str]:
    """The title, then the notes, cut at line ends into messages of at most `limit` characters."""
    lines = [CHANGELOG_TITLE.format(version=version)]
    if live:
        lines.append(live_line(live))
    if notes.strip():
        body = notes.splitlines()
        # The file's first line repeats the version ("**RouteMaker 0.22.0**"); the title has it.
        if body and body[0].strip().strip("*").strip() == f"RouteMaker {version.lstrip('v')}":
            body = body[1:]
        lines += body
    return split_text(lines, limit)


Image = tuple[Path, str]  # a picture and its caption
Post = tuple[str, tuple[Image, ...]]
MAX_FILES = 10  # Discord's limit on attachments in one message


def undated(text: str) -> str:
    """A post's words without its live-date line, so a retry on another day still matches."""
    lines = text.split("\n")
    if len(lines) > 1 and lines[1].startswith("Live on beta "):
        del lines[1]
    return "\n".join(lines)


def live_line(day: str) -> str:
    try:
        when = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        raise DiscordError(f"a live date is YYYY-MM-DD ({day!r})") from None
    return f"Live on beta {when:%A, %B} {when.day}, {when.year}"


def changelog_posts(
    version: str, notes: str, base: Path | None, live: str | None = None
) -> list[Post]:
    """The changelog's messages in order. The notes' picture lines (`![caption](file.png)`, a
    path inside the notes file's folder) are pulled out, every one checked before anything is
    posted. When the words fit one message and there are at most 10 pictures, it is one post:
    the title, the live date, the notes and every picture attached (the owner, 2026-11-07:
    "One post each"). Otherwise the words are cut to fit and each picture is its own message,
    its caption as its words, where it sits in the notes."""
    text: list[str] = []
    images: list[Image] = []
    blocks: list[tuple[list[str], Image | None]] = []
    for line in notes.splitlines():
        match = IMAGE_RE.match(line)
        if not match:
            text.append(line)
            continue
        image = (image_path(base, match.group(2)), match.group(1).strip())
        images.append(image)
        blocks.append((text, image))
        text = []
    blocks.append((text, None))
    words = changelog_messages(version, "\n".join(sum((b for b, _ in blocks), [])), live=live)
    if len(words) == 1 and len(images) <= MAX_FILES:
        return [(words[0], tuple(images))]
    posts: list[Post] = []
    for n, (lines, image) in enumerate(blocks):
        if n == 0:
            posts.extend((m, ()) for m in changelog_messages(version, "\n".join(lines), live=live))
        elif "\n".join(lines).strip():
            posts.extend((m, ()) for m in split_text(lines))
        if image:
            posts.append((image[1][:MAX_CHARS], (image,)))
    return posts


def image_path(base: Path | None, name: str) -> Path:
    if base is None:
        raise DiscordError(f"an image ({name}) needs the notes file's folder")
    root = base.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise DiscordError(f"{name}: an image must sit inside {root}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", path.name):
        raise DiscordError(f"{name}: name the file with letters, digits, '.', '_' or '-' only")
    if path.suffix.lower() not in IMAGE_TYPES:
        raise DiscordError(f"{name}: not an image Discord shows ({', '.join(IMAGE_TYPES)})")
    if not path.is_file():
        raise DiscordError(f"{name}: no such image")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise DiscordError(f"{name}: over Discord's 10 MB limit")
    return path


def split_text(lines: list[str], limit: int = MAX_CHARS) -> list[str]:
    """Lines cut at line ends into messages of at most `limit` characters."""
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for line in (line.rstrip() for line in lines):
        for piece in [line[i : i + limit] for i in range(0, len(line), limit)] or [""]:
            add = len(piece) + (1 if cur else 0)
            if cur and size + add > limit:
                chunks.append("\n".join(cur))
                cur, size, add = [], 0, len(piece)
            cur.append(piece)
            size += add
    chunks.append("\n".join(cur))
    return [c.strip("\n") for c in chunks if c.strip()]


def load_token(where: Path) -> str:
    token_file = where / "bot-token"
    if not token_file.is_file():
        raise DiscordError(f"no bot token: save it in {token_file} (mode 600)")
    if token_file.stat().st_mode & 0o077:
        raise DiscordError(f"{token_file} is readable by others: chmod 600 it")
    token = token_file.read_text().strip()
    if not token:
        raise DiscordError(f"{token_file} is empty")
    return token


def load_settings(where: Path) -> tuple[str, list[str]]:
    forums_file = where / "forums"
    token = load_token(where)
    if not forums_file.is_file():
        raise DiscordError(f"no forums listed: put their channel ids in {forums_file}")
    forums = []
    for line in forums_file.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            if not line.isdigit():
                raise DiscordError(f"{forums_file}: not a channel id: {line!r}")
            forums.append(line)
    if not token or not forums:
        raise DiscordError(f"{where}: the token or the forum list is empty")
    return token, forums


def post_id(text: str) -> str:
    """A post's id from its link (https://discord.com/channels/G/P[/M]) or the bare id."""
    text = text.strip()
    if text.isdigit():
        return text
    match = re.match(
        r"^https://(?:\w+\.)?discord(?:app)?\.com/channels/\d+/(\d+)(?:/\d+)?/?$", text
    )
    if not match:
        raise DiscordError(f"not a post link or id: {text!r}")
    return match.group(1)


class Forums:
    def __init__(self, api: Discord, forum_ids: list[str]) -> None:
        self.api = api
        self.forum_ids = forum_ids
        self._forums: dict[str, dict] = {}
        self._me: str | None = None

    def forum(self, forum_id: str) -> dict:
        if forum_id not in self._forums:
            self._forums[forum_id] = self.api.get(f"/channels/{forum_id}")
        return self._forums[forum_id]

    def tag_ids(self, forum_id: str) -> dict[str, str]:
        return {tag["name"]: tag["id"] for tag in self.forum(forum_id).get("available_tags", [])}

    def me(self) -> str:
        if self._me is None:
            self._me = self.api.get("/users/@me")["id"]
        return self._me

    def posts(self) -> list[dict]:
        """Every post in the listed forums, open or archived, each once."""
        found: dict[str, dict] = {}
        guilds = {self.forum(f)["guild_id"] for f in self.forum_ids}
        for guild in sorted(guilds):
            for thread in self.api.get(f"/guilds/{guild}/threads/active").get("threads", []):
                if thread.get("parent_id") in self.forum_ids:
                    found[thread["id"]] = thread
        for forum_id in self.forum_ids:
            before = None
            while True:
                path = f"/channels/{forum_id}/threads/archived/public?limit=100"
                if before:
                    path += f"&before={before}"
                page = self.api.get(path)
                threads = page.get("threads", [])
                for thread in threads:
                    found.setdefault(thread["id"], thread)
                if not page.get("has_more") or not threads:
                    break
                before = threads[-1]["thread_metadata"]["archive_timestamp"]
        return sorted(found.values(), key=lambda t: int(t["id"]))

    def messages(self, thread_id: str) -> list[dict]:
        """A post's messages, oldest first (the newest 500 at most)."""
        out: list[dict] = []
        before = None
        while len(out) < 500:
            path = f"/channels/{thread_id}/messages?limit=100"
            if before:
                path += f"&before={before}"
            page = self.api.get(path)
            out.extend(page)
            if len(page) < 100:
                break
            before = page[-1]["id"]
        return sorted(out, key=lambda m: int(m["id"]))

    def reply(self, thread: dict, text: str, status: str, dry_run: bool) -> None:
        """Post `text` in the post and make `status` its one status tag."""
        tags = self.tag_ids(thread["parent_id"])
        if status not in tags:
            raise DiscordError(
                f"the forum {self.forum(thread['parent_id']).get('name', thread['parent_id'])} "
                f"has no {status!r} tag: add it in the forum's settings"
            )
        status_ids = {tags[name] for name in STATUS_TAGS if name in tags}
        kept = [t for t in thread.get("applied_tags", []) if t not in status_ids]
        applied = kept[: MAX_TAGS - 1] + [tags[status]]
        if dry_run:
            print(f"would post in {thread['name']!r}: {text}  [tag: {status}]")
            return
        if thread.get("thread_metadata", {}).get("locked"):
            raise Locked(f"{thread['name']!r} is locked; unlock it to post there")
        # The tag first, in the same call that reopens an archived post: if the bot cannot set
        # it, nothing is posted, so a pass that is retried can never post the same reply twice.
        self.api.send(
            "PATCH", f"/channels/{thread['id']}", {"archived": False, "applied_tags": applied}
        )
        self.api.send(
            "POST",
            f"/channels/{thread['id']}/messages",
            {"content": text, "allowed_mentions": NO_MENTIONS},
        )
        print(f"posted in {thread['name']!r}: {text}  [tag: {status}]")


def cmd_check(forums: Forums) -> int:
    bad = 0
    print(f"signed in as bot {forums.me()}")
    for forum_id in forums.forum_ids:
        forum = forums.forum(forum_id)
        if forum.get("type") != 15:  # GUILD_FORUM
            print(f"{forum_id}: {forum.get('name')!r} is not a forum channel")
            bad += 1
            continue
        missing = [name for name in STATUS_TAGS if name not in forums.tag_ids(forum_id)]
        if missing:
            print(f"#{forum['name']}: add the tags {', '.join(missing)}")
            bad += 1
        else:
            print(f"#{forum['name']}: ok")
    return 1 if bad else 0


def cmd_fetch(forums: Forums, out: Path, days: int | None) -> int:
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    me = forums.me()
    owners = {}
    lines = [f"# Tester reports, fetched {datetime.now(UTC):%Y-%m-%d %H:%M} UTC", ""]
    count = 0
    for thread in forums.posts():
        posted = discord_time(thread["id"])
        newest = (
            discord_time(thread["last_message_id"]) if thread.get("last_message_id") else posted
        )
        if since and newest < since:
            continue
        forum = forums.forum(thread["parent_id"])
        guild = forum["guild_id"]
        if guild not in owners:
            owners[guild] = forums.api.get(f"/guilds/{guild}")["owner_id"]
        names = {v: k for k, v in forums.tag_ids(thread["parent_id"]).items()}
        tags = ", ".join(names.get(t, t) for t in thread.get("applied_tags", [])) or "none"
        lines += [
            f"## #{forum['name']}: {thread['name']}",
            "",
            f"Link: https://discord.com/channels/{guild}/{thread['id']}  ",
            f"Posted {posted:%Y-%m-%d %H:%M} UTC; tags: {tags}",
            "",
        ]
        for message in forums.messages(thread["id"]):
            author = message.get("author", {}).get("id")
            who = "bot" if author == me else "owner" if author == owners[guild] else "tester"
            text = (message.get("content") or "").strip() or "(no text)"
            lines.append(f"- **{who}**, {discord_time(message['id']):%Y-%m-%d %H:%M}: {text}")
            for attachment in message.get("attachments", []):
                lines.append(f"  - attachment: {attachment.get('url')}")
        lines.append("")
        count += 1
    out.write_text("\n".join(lines))
    print(f"wrote {count} posts to {out}")
    return 0


def discord_time(snowflake: str) -> datetime:
    return datetime.fromtimestamp(((int(snowflake) >> 22) + 1420070400000) / 1000, UTC)


def cmd_merged(forums: Forums, post: str, version: str, dry_run: bool) -> int:
    semver(version)
    thread = forums.api.get(f"/channels/{post_id(post)}")
    if thread.get("parent_id") not in forums.forum_ids:
        raise DiscordError("that post is not in one of the listed forums")
    forums.reply(thread, MERGED_TEXT.format(version=version), NEXT_TAG, dry_run)
    return 0


def cmd_live(forums: Forums, version: str, dry_run: bool) -> int:
    live = semver(version)
    me = forums.me()
    done = failed = 0
    for thread in forums.posts():
        tags = forums.tag_ids(thread["parent_id"])
        if tags.get(NEXT_TAG) not in thread.get("applied_tags", []):
            continue
        shipped = None
        for message in reversed(forums.messages(thread["id"])):
            match = MERGED_RE.search(message.get("content") or "")
            if message.get("author", {}).get("id") == me and match:
                shipped = match.group(1)
                break
        if shipped is None:
            print(
                f"skipped {thread['name']!r}: tagged {NEXT_TAG!r} but no version reply from the bot"
            )
            continue
        if semver(shipped) > live:
            continue
        try:
            forums.reply(thread, LIVE_TEXT.format(version=version), LIVE_TAG, dry_run)
            done += 1
        except Locked as error:
            print(f"skipped: {error}")
        except DiscordError as error:
            print(f"failed: {error}", file=sys.stderr)
            failed += 1
    print(f"{version}: {done} posts told it is live" + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


def already_posted(api: Discord, channel: str, version: str) -> list[tuple[str, tuple]]:
    """What the bot has posted for this version: its messages from this version's title on, up
    to its next title (the newest 100 messages of the channel)."""
    me = api.get("/users/@me")["id"]
    recent = api.get(f"/channels/{channel}/messages?limit=100") or []
    title = CHANGELOG_TITLE.format(version=version)
    out: list[tuple[str, tuple]] = []
    inside = False
    for m in sorted(recent, key=lambda m: int(m["id"])):
        if m.get("author", {}).get("id") != me:
            continue
        content = m.get("content") or ""
        if content.startswith("**RouteMaker v") and " is on beta**" in content.split("\n", 1)[0]:
            inside = content.startswith(title + "\n") or content == title
        if inside:
            names = tuple(a.get("filename", "") for a in m.get("attachments") or [])
            out.append((undated(content), names))
    return out


def cmd_changelog(
    api: Discord,
    channel: str,
    version: str,
    notes_file: Path | None,
    dry_run: bool,
    live: str | None = None,
) -> int:
    semver(version)
    notes, base = "", None
    if notes_file is not None and notes_file.is_file():
        notes = notes_file.read_text(encoding="utf-8", errors="replace")
        base = notes_file.parent
    posts = changelog_posts(version, notes, base, live)
    # A message the bot already posted for this version is skipped, so a pass that stopped
    # part-way posts only the rest and a repeated pass posts nothing.
    done = already_posted(api, channel, version)
    todo = []
    for text, images in posts:
        key = (undated(text), tuple(path.name for path, _ in images))
        if key in done:
            done.remove(key)
        else:
            todo.append((text, images))
    if not todo:
        print(f"{version}: the changelog already has it")
        return 0
    for n, (text, images) in enumerate(todo):
        if dry_run:
            names = ", ".join(path.name for path, _ in images)
            print(
                f"would post in the changelog:\n{text}" + (f"\n[images: {names}]" if names else "")
            )
            continue
        if n:
            time.sleep(1)
        body: dict = {"content": text, "allowed_mentions": NO_MENTIONS}
        if images:
            body["attachments"] = [
                {"id": i, "filename": path.name, "description": (caption or path.stem)[:1024]}
                for i, (path, caption) in enumerate(images)
            ]
            files = [path for path, _ in images]
            api.send("POST", f"/channels/{channel}/messages", body, files=files)
        else:
            api.send("POST", f"/channels/{channel}/messages", body)
    if not dry_run:
        print(f"{version}: posted to the changelog ({len(todo)} message(s))")
    return 0


def main(argv: list[str] | None = None, api: Discord | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path(
            os.environ.get("ROUTEMAKER_DISCORD_DIR", "~/.config/routemaker-discord")
        ).expanduser(),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--out", type=Path, required=True)
    fetch.add_argument("--days", type=int)
    merged = sub.add_parser("merged")
    merged.add_argument("post")
    merged.add_argument("--version", required=True)
    merged.add_argument("--dry-run", action="store_true")
    live = sub.add_parser("live")
    live.add_argument("version")
    live.add_argument("--dry-run", action="store_true")
    changelog = sub.add_parser("changelog")
    changelog.add_argument("version")
    changelog.add_argument("notes", type=Path, nargs="?")
    changelog.add_argument("--dry-run", action="store_true")
    changelog.add_argument("--live-date", metavar="YYYY-MM-DD", help="the day it went live")
    args = parser.parse_args(argv)
    try:
        if args.command == "changelog":
            token = load_token(args.dir)
            return cmd_changelog(
                api or Discord(token),
                changelog_channel(args.dir),
                args.version,
                args.notes,
                args.dry_run,
                args.live_date,
            )
        token, forum_ids = load_settings(args.dir)
        forums = Forums(api or Discord(token), forum_ids)
        if args.command == "check":
            return cmd_check(forums)
        if args.command == "fetch":
            return cmd_fetch(forums, args.out, args.days)
        if args.command == "merged":
            return cmd_merged(forums, args.post, args.version, args.dry_run)
        return cmd_live(forums, args.version, args.dry_run)
    except DiscordError as error:
        print(f"discord_reports: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
