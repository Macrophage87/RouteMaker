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

    def add(self, name, tags, messages, archived=False, locked=False):
        tid = snowflake(len(self.threads) + 1)
        self.threads[tid] = {
            "id": tid,
            "name": name,
            "parent_id": BUGS,
            "applied_tags": list(tags),
            "last_message_id": tid,
            "thread_metadata": {"archived": archived, "locked": locked, "archive_timestamp": "t"},
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
            return {
                "threads": [t for t in self.threads.values() if t["thread_metadata"]["archived"]],
                "has_more": False,
            }
        tid = path.split("/")[2]
        if path.endswith("/messages") and method == "POST":
            self.messages[tid].append(
                {"id": snowflake(999), "author": {"id": BOT}, "content": body["content"]}
            )
            return {}
        if "/messages?" in path:
            return list(reversed(self.messages[tid]))  # Discord gives the newest first
        if method == "PATCH":
            self.threads[tid].update(body)
            return {}
        return self.threads[tid]

    def get(self, path):
        return self.send("GET", path)

    def posted(self):
        return [(p.split("/")[2], b["content"]) for m, p, b in self.calls if m == "POST"]


@pytest.fixture
def settings(tmp_path: Path) -> Path:
    (tmp_path / "bot-token").write_text("secret-token\n")
    (tmp_path / "bot-token").chmod(0o600)
    (tmp_path / "forums").write_text(f"# bug reports\n{BUGS}\n")
    return tmp_path


def run(settings: Path, fake: FakeDiscord, *args: str) -> int:
    return mod.main(["--dir", str(settings), *args], api=fake)


def test_merged_replies_with_the_version_and_sets_the_status_tag(settings, capsys) -> None:
    fake = FakeDiscord()
    post = fake.add("Crash on Plan", ["1", "3"], [(TESTER, "It crashes")])
    assert (
        run(
            settings,
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
    assert "secret-token" not in capsys.readouterr().out


def test_live_tells_only_posts_whose_change_has_shipped(settings) -> None:
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
    assert run(settings, fake, "live", "v0.11.0") == 0
    told = dict(fake.posted())
    assert set(told) == {shipped, earlier}
    assert told[shipped] == "v0.11.0 is live on beta. Give it a try and let us know how it goes."
    assert fake.threads[shipped]["applied_tags"] == ["3"]
    assert fake.threads[earlier]["archived"] is False  # reopened to post
    for post in (later, untagged, impostor):
        assert post not in told
    # A second pass finds nothing left to tell.
    fake.calls.clear()
    assert run(settings, fake, "live", "v0.11.0") == 0
    assert fake.posted() == []


def test_dry_run_posts_nothing(settings, capsys) -> None:
    fake = FakeDiscord()
    fake.add("A", ["2"], [(BOT, "This change is in v0.11.0, coming in the next beta release.")])
    assert run(settings, fake, "live", "v0.11.0", "--dry-run") == 0
    assert not [c for c in fake.calls if c[0] != "GET"]
    assert "would post" in capsys.readouterr().out


def test_a_locked_post_fails_without_stopping_the_rest(settings) -> None:
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
    assert run(settings, fake, "live", "v0.11.0") == 1
    assert [p for p, _ in fake.posted()] == [ok]


def test_fetch_writes_posts_without_tester_names(settings, tmp_path) -> None:
    fake = FakeDiscord()
    fake.add(
        "Crash on Plan",
        ["1"],
        [(TESTER, "It crashes"), (OWNER, "Thanks"), (BOT, "This change is in v0.11.0")],
    )
    out = tmp_path / "reports.md"
    assert run(settings, fake, "fetch", "--out", str(out)) == 0
    text = out.read_text()
    assert "## #bug-reports: Crash on Plan" in text and "tags: Phone app" in text
    assert "**tester**" in text and "**owner**" in text and "**bot**" in text
    assert TESTER not in text.replace(snowflake(1), "")


def test_settings_are_checked(settings, capsys) -> None:
    (settings / "bot-token").chmod(0o644)
    assert run(settings, FakeDiscord(), "check") == 2
    assert "chmod 600" in capsys.readouterr().err
    (settings / "bot-token").chmod(0o600)
    (settings / "forums").write_text("not-an-id\n")
    assert run(settings, FakeDiscord(), "check") == 2


def test_check_names_missing_status_tags(settings, capsys, monkeypatch) -> None:
    monkeypatch.setattr(mod, "STATUS_TAGS", ("In next release", "Live on beta", "Shipped"))
    assert run(settings, FakeDiscord(), "check") == 1
    assert "add the tags Shipped" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["0.11.0", "v0.11", "latest"])
def test_versions_must_be_tags(settings, bad) -> None:
    assert run(settings, FakeDiscord(), "live", bad) == 2


def test_post_links_and_ids() -> None:
    assert mod.post_id("https://discord.com/channels/1/22") == "22"
    assert mod.post_id("https://discord.com/channels/1/22/333") == "22"
    assert mod.post_id(" 44 ") == "44"
    with pytest.raises(mod.DiscordError):
        mod.post_id("https://example.com/channels/1/22")
