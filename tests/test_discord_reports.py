"""scripts/discord_reports.py: the testers' forums, read and told when a change ships."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "discord_reports.py"
spec = importlib.util.spec_from_file_location("discord_reports", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules["discord_reports"] = mod
spec.loader.exec_module(mod)

BOT, OWNER, TESTER = "900", "800", "700"
GUILD, BUGS = "100", "200"
TAGS = [
    {"id": "1", "name": "Phone app"},
    {"id": "2", "name": "In next release"},
    {"id": "3", "name": "Live on beta"},
]


def snowflake(n: int) -> str:
    return str((1_760_000_000_000 - 1420070400000 + n * 1000) << 22)


class FakeDiscord:
    """Discord as the script sees it: a forum, its posts and their messages."""

    def __init__(self) -> None:
        self.threads: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str, dict | None]] = []
        self.page = 100  # archived posts per page, smaller to make the script page
        self.fail_patch = False

    def add(self, name, tags, messages, archived=False, locked=False):
        tid = snowflake(len(self.threads) + 1)
        self.threads[tid] = {
            "id": tid,
            "name": name,
            "parent_id": BUGS,
            "applied_tags": list(tags),
            "last_message_id": tid,
            "thread_metadata": {
                "archived": archived,
                "locked": locked,
                "archive_timestamp": f"2026-10-{len(self.threads) + 1:02d}T00:00:00+00:00",
            },
        }
        self.messages[tid] = [
            {"id": snowflake(100 + i), "author": {"id": who}, "content": text, "attachments": []}
            for i, (who, text) in enumerate(messages)
        ]
        return tid

    def send(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/users/@me":
            return {"id": BOT}
        if path == f"/channels/{BUGS}":
            return {
                "id": BUGS,
                "guild_id": GUILD,
                "name": "bug-reports",
                "type": 15,
                "available_tags": TAGS,
            }
        if path == f"/guilds/{GUILD}":
            return {"owner_id": OWNER}
        if path == f"/guilds/{GUILD}/threads/active":
            return {
                "threads": [
                    t for t in self.threads.values() if not t["thread_metadata"]["archived"]
                ]
            }
        if path.startswith(f"/channels/{BUGS}/threads/archived/public"):
            query = dict(part.split("=", 1) for part in path.split("?", 1)[1].split("&"))
            older = sorted(
                (t for t in self.threads.values() if t["thread_metadata"]["archived"]),
                key=lambda t: t["thread_metadata"]["archive_timestamp"],
                reverse=True,  # newest archived first, as Discord does
            )
            if "before" in query:
                older = [
                    t for t in older if t["thread_metadata"]["archive_timestamp"] < query["before"]
                ]
            size = min(int(query["limit"]), self.page)
            return {"threads": older[:size], "has_more": len(older) > size}
        tid = path.split("/")[2]
        if path.endswith("/messages") and method == "POST":
            self.messages[tid].append(
                {"id": snowflake(999), "author": {"id": BOT}, "content": body["content"]}
            )
            return {}
        if "/messages?" in path:
            query = dict(part.split("=", 1) for part in path.split("?", 1)[1].split("&"))
            newest = sorted(self.messages[tid], key=lambda m: int(m["id"]), reverse=True)
            if "before" in query:
                newest = [m for m in newest if int(m["id"]) < int(query["before"])]
            return newest[: int(query["limit"])]
        if method == "PATCH":
            if self.fail_patch:
                raise mod.DiscordError(f"PATCH {path}: HTTP 403")
            self.threads[tid].update(body)
            return {}
        return self.threads[tid]

    def get(self, path):
        return self.send("GET", path)

    def posted(self):
        return [(p.split("/")[2], b["content"]) for m, p, b in self.calls if m == "POST"]


@pytest.fixture
def bot_dir(tmp_path: Path) -> Path:
    (tmp_path / "bot-token").write_text("secret-token\n")
    (tmp_path / "bot-token").chmod(0o600)
    (tmp_path / "forums").write_text(f"# bug reports\n{BUGS}\n")
    return tmp_path


def run(bot_dir: Path, fake: FakeDiscord, *args: str) -> int:
    return mod.main(["--dir", str(bot_dir), *args], api=fake)


def test_merged_replies_with_the_version_and_sets_the_status_tag(bot_dir, capsys) -> None:
    fake = FakeDiscord()
    post = fake.add("Crash on Plan", ["1", "3"], [(TESTER, "It crashes")])
    assert (
        run(
            bot_dir,
            fake,
            "merged",
            f"https://discord.com/channels/{GUILD}/{post}",
            "--version",
            "v0.11.0",
        )
        == 0
    )
    assert fake.posted() == [(post, "This change is in v0.11.0, coming in the next beta release.")]
    assert fake.threads[post]["applied_tags"] == ["1", "2"]  # the tester's tag kept, one status tag
    sent = [b for m, p, b in fake.calls if m == "POST"][0]
    assert sent["allowed_mentions"] == {"parse": []}


def test_live_tells_only_posts_whose_change_has_shipped(bot_dir) -> None:
    fake = FakeDiscord()
    shipped = fake.add(
        "A",
        ["2"],
        [(TESTER, "bug"), (BOT, "This change is in v0.11.0, coming in the next beta release.")],
    )
    earlier = fake.add(
        "B",
        ["2"],
        [(BOT, "This change is in v0.10.2, coming in the next beta release.")],
        archived=True,
    )
    later = fake.add(
        "C", ["2"], [(BOT, "This change is in v0.12.0, coming in the next beta release.")]
    )
    untagged = fake.add(
        "D", ["1"], [(BOT, "This change is in v0.11.0, coming in the next beta release.")]
    )
    impostor = fake.add(
        "E", ["2"], [(TESTER, "This change is in v0.11.0, coming in the next beta release.")]
    )
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    told = dict(fake.posted())
    assert set(told) == {shipped, earlier}
    assert told[shipped] == "v0.11.0 is live on beta. Give it a try and let us know how it goes."
    assert fake.threads[shipped]["applied_tags"] == ["3"]
    assert fake.threads[earlier]["archived"] is False  # reopened to post
    for post in (later, untagged, impostor):
        assert post not in told
    # A second pass finds nothing left to tell.
    fake.calls.clear()
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    assert fake.posted() == []


def test_dry_run_posts_nothing(bot_dir, capsys) -> None:
    fake = FakeDiscord()
    fake.add("A", ["2"], [(BOT, "This change is in v0.11.0, coming in the next beta release.")])
    assert run(bot_dir, fake, "live", "v0.11.0", "--dry-run") == 0
    assert not [c for c in fake.calls if c[0] != "GET"]
    assert "would post" in capsys.readouterr().out


def test_a_locked_post_is_skipped_so_it_cannot_fail_every_pass(bot_dir) -> None:
    fake = FakeDiscord()
    fake.add(
        "A",
        ["2"],
        [(BOT, "This change is in v0.11.0, coming in the next beta release.")],
        locked=True,
    )
    ok = fake.add(
        "B", ["2"], [(BOT, "This change is in v0.11.0, coming in the next beta release.")]
    )
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    assert [p for p, _ in fake.posted()] == [ok]


def test_fetch_writes_posts_without_tester_names(bot_dir, tmp_path) -> None:
    fake = FakeDiscord()
    fake.add(
        "Crash on Plan",
        ["1"],
        [(TESTER, "It crashes"), (OWNER, "Thanks"), (BOT, "This change is in v0.11.0")],
    )
    out = tmp_path / "reports.md"
    assert run(bot_dir, fake, "fetch", "--out", str(out)) == 0
    text = out.read_text()
    assert "## #bug-reports: Crash on Plan" in text and "tags: Phone app" in text
    assert "**tester**" in text and "**owner**" in text and "**bot**" in text
    assert TESTER not in text.replace(snowflake(1), "")


def test_settings_are_checked(bot_dir, capsys) -> None:
    (bot_dir / "bot-token").chmod(0o644)
    assert run(bot_dir, FakeDiscord(), "check") == 2
    assert "chmod 600" in capsys.readouterr().err
    (bot_dir / "bot-token").chmod(0o600)
    (bot_dir / "forums").write_text("not-an-id\n")
    assert run(bot_dir, FakeDiscord(), "check") == 2


def test_check_names_missing_status_tags(bot_dir, capsys, monkeypatch) -> None:
    monkeypatch.setattr(mod, "STATUS_TAGS", ("In next release", "Live on beta", "Shipped"))
    assert run(bot_dir, FakeDiscord(), "check") == 1
    assert "add the tags Shipped" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["0.11.0", "v0.11", "latest"])
def test_versions_must_be_tags(bot_dir, bad) -> None:
    assert run(bot_dir, FakeDiscord(), "live", bad) == 2


def test_post_links_and_ids() -> None:
    assert mod.post_id("https://discord.com/channels/1/22") == "22"
    assert mod.post_id("https://discord.com/channels/1/22/333") == "22"
    assert mod.post_id(" 44 ") == "44"
    with pytest.raises(mod.DiscordError):
        mod.post_id("https://example.com/channels/1/22")


NEXT = "This change is in v0.11.0, coming in the next beta release."


def test_a_failed_tag_change_posts_nothing_so_a_retry_cannot_repeat_it(bot_dir) -> None:
    fake = FakeDiscord()
    post = fake.add("A", ["2"], [(BOT, NEXT)])
    fake.fail_patch = True  # e.g. the bot lacks Manage Threads
    for _ in range(3):  # the release agent retries on each pass
        assert run(bot_dir, fake, "live", "v0.11.0") == 1
    assert fake.posted() == []
    fake.fail_patch = False
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    assert [p for p, _ in fake.posted()] == [post]


def test_archived_posts_and_long_posts_are_read_across_pages(bot_dir) -> None:
    fake = FakeDiscord()
    fake.page = 2
    archived = [fake.add(f"old {i}", ["2"], [(BOT, NEXT)], archived=True) for i in range(5)]
    long = fake.add("long", ["2"], [(BOT, NEXT)] + [(TESTER, f"reply {i}") for i in range(250)])
    assert run(bot_dir, fake, "live", "v0.11.0") == 0
    assert sorted(p for p, _ in fake.posted()) == sorted([*archived, long])


def test_send_signs_requests_and_waits_out_an_html_rate_limit(monkeypatch) -> None:
    import io
    import urllib.error

    seen: list = []
    answers = [
        urllib.error.HTTPError(
            "u", 429, "Too Many", {"Retry-After": "2"}, io.BytesIO(b"<html>slow down</html>")
        ),
        io.BytesIO(b'{"id": "1"}'),
    ]

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        seen.append(request)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Response(answer.getvalue())

    slept: list = []
    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(mod.time, "sleep", slept.append)
    assert mod.Discord("tok").get("/users/@me") == {"id": "1"}
    assert slept == [2.0]
    assert seen[0].get_header("Authorization") == "Bot tok"
    assert seen[0].get_header("User-agent").startswith("DiscordBot (")


def test_an_error_names_the_status_and_never_the_token(monkeypatch) -> None:
    import io
    import urllib.error

    def urlopen(request, timeout):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    with pytest.raises(mod.DiscordError) as caught:
        mod.Discord("secret-token").get("/channels/1")
    assert str(caught.value) == "GET /channels/1: HTTP 403"


CHANGELOG = "300"


class FakeChannel:
    def __init__(self, history=None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.files: list[list[str]] = []
        self.history = history or []

    def send(self, method, path, body=None, files=()):
        self.calls.append((method, path, body))
        self.files.append([f.name for f in files])
        if path == "/users/@me":
            return {"id": BOT}
        if path.startswith(f"/channels/{CHANGELOG}/messages?"):
            return self.history
        return {}

    def get(self, path):
        return self.send("GET", path)

    def posted(self):
        return [b["content"] for m, p, b in self.calls if m == "POST"]


@pytest.fixture
def changelog_dir(tmp_path: Path) -> Path:
    (tmp_path / "bot-token").write_text("secret-token\n")
    (tmp_path / "bot-token").chmod(0o600)
    (tmp_path / "changelog-channel").write_text(f"# changelog\n{CHANGELOG}\n")
    return tmp_path


def test_changelog_posts_the_notes_as_the_bot_once(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = changelog_dir / "v0.22.0.md"
    notes.write_text("**RouteMaker 0.22.0**\n- Saved routes take tags\n- A quieter map\n")
    fake = FakeChannel()
    assert run(changelog_dir, fake, "changelog", "v0.22.0", str(notes)) == 0
    assert fake.posted() == [
        "**RouteMaker v0.22.0 is on beta**\n- Saved routes take tags\n- A quieter map"
    ]
    post = [c for c in fake.calls if c[0] == "POST"][0]
    assert post[1] == f"/channels/{CHANGELOG}/messages"
    assert post[2]["allowed_mentions"] == {"parse": []}
    # Already in the channel from the bot: nothing posted again.
    again = FakeChannel([{"id": "1", "author": {"id": BOT}, "content": fake.posted()[0]}])
    assert run(changelog_dir, again, "changelog", "v0.22.0", str(notes)) == 0
    assert again.posted() == []
    # The same title from someone else does not count.
    other = FakeChannel([{"id": "1", "author": {"id": OWNER}, "content": fake.posted()[0]}])
    assert run(changelog_dir, other, "changelog", "v0.22.0", str(notes)) == 0
    assert len(other.posted()) == 1


def test_changelog_splits_long_notes_at_line_ends(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = changelog_dir / "v0.2.0.md"
    notes.write_text("\n".join(f"- line {n} " + "x" * 90 for n in range(40)) + "\n")
    fake = FakeChannel()
    assert run(changelog_dir, fake, "changelog", "v0.2.0", str(notes)) == 0
    sent = fake.posted()
    assert len(sent) > 1 and all(len(m) <= 2000 for m in sent)
    assert "\n".join(sent).count("- line ") == 40


def test_changelog_needs_its_channel(bot_dir, capsys) -> None:
    assert run(bot_dir, FakeChannel(), "changelog", "v0.2.0") == 2
    assert "changelog-channel" in capsys.readouterr().err


def test_changelog_finishes_a_post_that_stopped_part_way(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = changelog_dir / "v0.2.0.md"
    notes.write_text("\n".join(f"- line {n} " + "x" * 90 for n in range(40)) + "\n")
    first = FakeChannel()
    run(changelog_dir, first, "changelog", "v0.2.0", str(notes))
    whole = first.posted()
    done = [{"id": "1", "author": {"id": BOT}, "content": whole[0]}]
    rest = FakeChannel(done)
    assert run(changelog_dir, rest, "changelog", "v0.2.0", str(notes)) == 0
    assert rest.posted() == whole[1:]


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _notes_with_images(where: Path) -> Path:
    (where / "images" / "v0.22.0").mkdir(parents=True)
    (where / "images" / "v0.22.0" / "tags.png").write_bytes(PNG)
    notes = where / "v0.22.0.md"
    notes.write_text(
        "**RouteMaker 0.22.0**\n- Saved routes take tags\n"
        "![Tags in My routes](images/v0.22.0/tags.png)\n- A quieter map\n"
    )
    return notes


def test_changelog_is_one_post_with_the_date_and_every_picture(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = _notes_with_images(changelog_dir)
    fake = FakeChannel()
    args = ("changelog", "v0.22.0", str(notes), "--live-date", "2026-10-31")
    assert run(changelog_dir, fake, *args) == 0
    text = (
        "**RouteMaker v0.22.0 is on beta**\nLive on beta Saturday, October 31, 2026\n"
        "- Saved routes take tags\n- A quieter map"
    )
    assert fake.posted() == [text]
    posts = [(b, f) for (m, _p, b), f in zip(fake.calls, fake.files, strict=True) if m == "POST"]
    assert posts[0][1] == ["tags.png"]
    assert posts[0][0]["attachments"] == [
        {"id": 0, "filename": "tags.png", "description": "Tags in My routes"}
    ]
    history = [
        {
            "id": "1",
            "author": {"id": BOT},
            "content": text,
            "attachments": [{"filename": "tags.png"}],
        }
    ]
    again = FakeChannel(history)
    assert run(changelog_dir, again, *args) == 0
    assert again.posted() == []
    # A retry on another day, or by hand without a date, still finds it.
    later = FakeChannel(history)
    assert (
        run(changelog_dir, later, "changelog", "v0.22.0", str(notes), "--live-date", "2026-11-01")
        == 0
    )
    assert run(changelog_dir, later, "changelog", "v0.22.0", str(notes)) == 0
    assert later.posted() == []


def test_long_notes_put_each_picture_where_it_sits(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = _notes_with_images(changelog_dir)
    long = "\n".join(f"- line {n} " + "x" * 90 for n in range(25))
    notes.write_text(notes.read_text() + long + "\n")
    fake = FakeChannel()
    assert run(changelog_dir, fake, "changelog", "v0.22.0", str(notes)) == 0
    sent = fake.posted()
    assert sent[0] == "**RouteMaker v0.22.0 is on beta**\n- Saved routes take tags"
    assert sent[1] == "Tags in My routes" and fake.files[sent.index(sent[1]) + 2] == ["tags.png"]
    assert all(len(m) <= 2000 for m in sent) and len(sent) > 3
    # Stopped after the first message: the rest follow, the first is not repeated.
    rest = FakeChannel([{"id": "1", "author": {"id": BOT}, "content": sent[0]}])
    assert run(changelog_dir, rest, "changelog", "v0.22.0", str(notes)) == 0
    assert rest.posted() == sent[1:]


def test_another_versions_messages_do_not_count_as_posted(changelog_dir, monkeypatch) -> None:
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    notes = _notes_with_images(changelog_dir)
    history = [
        {"id": "1", "author": {"id": BOT}, "content": "**RouteMaker v0.21.0 is on beta**\n- x"},
        {"id": "2", "author": {"id": BOT}, "content": "- A quieter map"},
    ]
    fake = FakeChannel(history)
    assert run(changelog_dir, fake, "changelog", "v0.22.0", str(notes)) == 0
    assert len(fake.posted()) == 1


def test_a_bad_live_date_is_refused(changelog_dir, capsys) -> None:
    args = ("changelog", "v0.2.0", "--live-date", "Oct 31")
    assert run(changelog_dir, FakeChannel(), *args) == 2
    assert "YYYY-MM-DD" in capsys.readouterr().err


@pytest.mark.parametrize(
    "line, error",
    [
        ("![x](../secret.png)", "inside"),
        ("![x](images/missing.png)", "no such image"),
        ("![x](images/v0.22.0/notes.txt)", "not an image"),
        ("![x](images/v0.22.0/a%20b.png)", "letters, digits"),
    ],
)
def test_bad_images_stop_the_post_before_anything_is_sent(
    changelog_dir, capsys, line, error
) -> None:
    rel = changelog_dir / "rel"
    rel.mkdir()
    notes = _notes_with_images(rel)
    (rel / "images" / "v0.22.0" / "notes.txt").write_text("x")
    (changelog_dir / "secret.png").write_bytes(PNG)
    target = notes
    target.write_text(notes.read_text() + line + "\n")
    fake = FakeChannel()
    assert run(changelog_dir, fake, "changelog", "v0.22.0", str(target)) == 2
    assert error in capsys.readouterr().err
    assert fake.posted() == []


def test_multipart_carries_the_payload_and_the_file(tmp_path) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(PNG)
    data, kind = mod.multipart({"content": "hi"}, [image])
    boundary = kind.split("boundary=", 1)[1]
    assert kind.startswith("multipart/form-data; ")
    assert b'name="payload_json"' in data and b'{"content": "hi"}' in data
    assert b'name="files[0]"; filename="a.png"' in data and PNG in data
    assert data.endswith(f"--{boundary}--\r\n".encode())
