#!/usr/bin/env python3
"""The phase-1 acceptance checklist, as a program.

Run on the deploy host, from the repository checkout, with Docker and a filled
`.env` beside it:

    python3 scripts/acceptance.py                 # everything automated
    python3 scripts/acceptance.py --dry-run       # print what each item would run
    python3 scripts/acceptance.py --only A1 A2    # a subset
    python3 scripts/acceptance.py --resume acceptance-reports/<earlier>.json

Six items, numbered A1 to A6, each answering PASS, FAIL or SKIP with the
evidence beside it, written to a JSON and a Markdown report. The exit code is
non-zero when anything failed. `docs/ACCEPTANCE.md` says what each item means
and what the operator does by hand in the middle of A3.

Standard library only, on purpose: this runs on a host that has Docker and
Python and nothing of this repository's virtualenv. Nothing here imports
Django; every question about the running stack is asked through
`docker compose exec`, the way the runbooks ask it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# What the stack is called, from `compose.yaml`; `tests/test_acceptance.py`
# holds each of these equal to the rendered configuration so they cannot drift.
ROUTERS = ("valhalla-standard", "valhalla-no-trail", "valhalla-ebike")
VARIANTS = ("standard", "no-trail", "ebike")
ROUTER_URL = {v: f"http://valhalla-{v}:8002" for v in VARIANTS}
DJANGO_SERVICES = ("api", "worker", "rebuild")
HEALTHZ = "/healthz"
LOGIN = "/auth/login"
MIN_FREE_GIB = 20  # the disk gate's floor, `REBUILD_MIN_FREE_BYTES`
# A canary route between two fixed DC points (PLAN.md:292): the Lincoln
# Memorial to Union Station. Any bicycle graph of the District routes it.
CANARY = ((-77.0502, 38.8893), (-77.0063, 38.8973))
REBUILD_POLL_S = 60
REBUILD_TIMEOUT_S = 8 * 3600
RESTORE_DB = "routemaker_acceptance_restore"


class Fail(Exception):
    """An item that did not pass, with the evidence in the message."""


class Skip(Exception):
    """An item that could not be run here, with the reason."""


@dataclass
class Result:
    item: str
    title: str
    status: str
    evidence: list[str] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class Context:
    args: argparse.Namespace
    env: dict[str, str]
    log: list[str] = field(default_factory=list)

    # -- running things ---------------------------------------------------

    def run(
        self,
        argv: list[str],
        *,
        check: bool = True,
        timeout: float | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess:
        self.log.append("$ " + " ".join(argv))
        if self.args.dry_run:
            return subprocess.CompletedProcess(argv, 0, "", "")
        proc = subprocess.run(
            argv, cwd=REPO, text=True, capture_output=True, timeout=timeout, input=input_text
        )
        if check and proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-8:]
            raise Fail(f"`{' '.join(argv[:4])}…` exited {proc.returncode}: " + " | ".join(tail))
        return proc

    def compose(self, *rest: str, **kw) -> subprocess.CompletedProcess:
        return self.run(["docker", "compose", *rest], **kw)

    def exec_in(self, service: str, *cmd: str, **kw) -> subprocess.CompletedProcess:
        return self.compose("exec", "-T", service, *cmd, **kw)

    def django_json(self, service: str, code: str, timeout: float = 120) -> dict:
        """Ask the running stack a question and get JSON back. The snippet
        must `print(json.dumps(...))` exactly once, last."""
        proc = self.exec_in(service, "./manage.py", "shell", "-c", code, timeout=timeout)
        if self.args.dry_run:
            return {}
        line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
        try:
            return json.loads(line)
        except json.JSONDecodeError as error:
            raise Fail(f"{service} answered something that is not JSON: {line[:200]}") from error

    def ps(self) -> dict[str, dict]:
        proc = self.compose("ps", "-a", "--format", "json", check=False)
        if self.args.dry_run:
            return {}
        rows = parse_ps(proc.stdout)
        return {row["Service"]: row for row in rows}

    def http(
        self,
        url: str,
        *,
        host: str | None = None,
        method: str = "GET",
        body: bytes | None = None,
        timeout: float = 20,
    ) -> tuple[int, dict, bytes]:
        """One request from this host, without following redirects."""
        self.log.append(f"> {method} {url}")
        if self.args.dry_run:
            return 0, {}, b""
        headers = {"Host": host} if host else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    # -- facts about the deployment ---------------------------------------

    @property
    def data_root(self) -> Path:
        return Path(self.env.get("DATA_ROOT", ""))

    @property
    def site(self) -> str:
        """The site as Caddy answers it: `:80` means plain http on this host,
        anything else is a hostname over https."""
        address = self.env.get("CADDY_SITE_ADDRESS", ":80").strip()
        if address.startswith(":"):
            return f"http://127.0.0.1{address if address != ':80' else ''}"
        return f"https://{address}"

    @property
    def admin_path(self) -> str:
        return self.env.get("DJANGO_ADMIN_PATH", "internal-8f3a/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib's hook
        return None


# ---------------------------------------------------------------------------
# Pure helpers, tested without a stack.


def read_env_file(path: Path) -> dict[str, str]:
    """The four rules compose's own reader applies, mirrored from
    `scripts/prepare_data_root.sh`: the last assignment wins, a CR is
    stripped, and a matching pair of quotes is removed."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\r")
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def parse_ps(stdout: str) -> list[dict]:
    """`docker compose ps --format json` prints one object per line on
    recent versions and a JSON array on older ones."""
    text = stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def data_root_directories(script: Path) -> list[str]:
    """The directory list `prepare_data_root.sh` creates, read from the
    script so this checklist cannot disagree with it."""
    text = script.read_text(encoding="utf-8")
    match = re.search(r'DIRECTORIES="\n(.*?)"', text, re.S)
    if not match:
        raise Fail("scripts/prepare_data_root.sh no longer declares DIRECTORIES")
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def render_markdown(results: list[Result], meta: dict) -> str:
    lines = [
        "# Phase-1 acceptance run",
        "",
        f"- **When:** {meta['started']}",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Host:** {meta['host']} · Docker Compose {meta['compose_version']}",
        f"- **Site:** {meta['site']} · data root `{meta['data_root']}`",
        "",
        "| Item | Status | Seconds | Evidence |",
        "|---|---|---|---|",
    ]
    for r in results:
        evidence = "<br>".join(e.replace("|", "\\|") for e in r.evidence) or "—"
        lines.append(f"| {r.item} {r.title} | **{r.status}** | {r.seconds:.0f} | {evidence} |")
    failed = [r.item for r in results if r.status == "FAIL"]
    skipped = [r.item for r in results if r.status == "SKIP"]
    lines += [
        "",
        f"**Outcome:** {'FAIL' if failed else 'PASS'}"
        + (f" — failed: {', '.join(failed)}" if failed else "")
        + (f" — skipped: {', '.join(skipped)}" if skipped else ""),
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# The six items.


def a1_preflight(ctx: Context, out: list[str]) -> None:
    """A1 — the host can run the stack: tools, `.env`, the data root, room."""
    for tool in ("docker",):
        if shutil.which(tool) is None:
            raise Fail(f"{tool} is not on PATH")
    version = ctx.compose("version", "--short", check=False).stdout.strip()
    out.append(f"docker compose {version or '(dry run)'}")
    if not ctx.args.dry_run:
        ctx.run(["docker", "info"], timeout=30)  # a reachable daemon
    if not (REPO / ".env").is_file():
        if ctx.args.dry_run:
            out.append(".env is missing; the dry run reads .env.example instead")
        else:
            raise Fail(".env is missing; copy .env.example and fill it in")
    ctx.compose("config", "-q")
    out.append(".env renders")
    for key in ("PGPASSWORD", "DJANGO_SECRET_KEY", "KEY_ENCRYPTION_KEY", "DISCORD_CLIENT_SECRET"):
        if ctx.env.get(key, "").startswith("change-me") or not ctx.env.get(key):
            if ctx.args.dry_run:
                out.append(f"{key} is still the placeholder (would fail)")
                continue
            raise Fail(f"{key} is still the placeholder")
    root = ctx.data_root
    if not root.is_absolute():
        raise Fail(f"DATA_ROOT is not absolute: {root!s}")
    if ctx.args.dry_run:
        return
    missing = [
        d
        for d in data_root_directories(REPO / "scripts/prepare_data_root.sh")
        if not (root / d).is_dir()
    ]
    if missing:
        raise Fail(
            f"data root not prepared, missing: {', '.join(missing)} "
            "(run scripts/prepare_data_root.sh --env-file .env)"
        )
    free_gib = shutil.disk_usage(root).free / 1024**3
    out.append(f"{free_gib:.0f} GiB free on the data volume")
    if free_gib < MIN_FREE_GIB:
        raise Fail(f"{free_gib:.0f} GiB free is under the {MIN_FREE_GIB} GiB rebuild floor")


def a2_build_and_start(ctx: Context, out: list[str]) -> None:
    """A2 — the images build and the stack comes up in order."""
    if not ctx.args.no_build:
        ctx.compose("build", timeout=3600)
        out.append("built api and pipeline images")
    ctx.compose("up", "-d", "--no-build", timeout=900)
    deadline = time.time() + 600
    while True:
        ps = ctx.ps()
        if ctx.args.dry_run:
            return
        postgis = ps.get("postgis", {})
        migrate = ps.get("migrate", {})
        api = ps.get("api", {})
        healthy = "healthy" in postgis.get("Health", "") or "healthy" in postgis.get("Status", "")
        migrated = migrate.get("ExitCode") == 0 and "exited" in migrate.get("State", "")
        api_ok = "healthy" in api.get("Health", "") or "healthy" in api.get("Status", "")
        running = all("running" in ps.get(s, {}).get("State", "") for s in ("worker", "rebuild"))
        if healthy and migrated and api_ok and running:
            break
        if migrate.get("ExitCode") not in (None, 0) and "exited" in migrate.get("State", ""):
            logs = ctx.compose("logs", "--no-color", "--tail", "20", "migrate", check=False).stdout
            raise Fail("migrate exited non-zero: " + " | ".join(logs.strip().splitlines()[-6:]))
        if time.time() > deadline:
            state = {
                s: (ps.get(s, {}).get("State"), ps.get(s, {}).get("Health"))
                for s in ("postgis", "migrate", "api", "worker", "rebuild")
            }
            raise Fail(f"the stack did not settle in 10 minutes: {state}")
        time.sleep(5)
    out.append("postgis healthy, migrate exited 0, api healthy, worker and rebuild running")
    for router in ROUTERS:
        state = ps.get(router, {}).get("State", "absent")
        out.append(f"{router}: {state} (routers cannot serve before the first rebuild)")


def a3_sign_in_and_admin(ctx: Context, out: list[str]) -> None:
    """A3 — the edge answers, sign-in reaches Discord, and the admin flows
    the plan names work — the last part by hand, verified afterwards."""
    site = ctx.site
    host = ctx.env.get("DJANGO_ALLOWED_HOSTS", "").split(",")[0].strip() or None
    status, headers, body = ctx.http(
        site + HEALTHZ, host=None if site.startswith("https") else host
    )
    if not ctx.args.dry_run:
        if status != 200 or body.strip() != b"ok":
            raise Fail(f"{site}{HEALTHZ} answered {status} {body[:60]!r}")
        out.append(f"{HEALTHZ} 200 through the edge")
        if site.startswith("https") and "Strict-Transport-Security" not in headers:
            raise Fail("no Strict-Transport-Security header on the hostname posture")
    status, headers, _ = ctx.http(site + LOGIN, host=None if site.startswith("https") else host)
    if not ctx.args.dry_run:
        location = headers.get("Location", "")
        want = ctx.env.get("DISCORD_REDIRECT_URI", "")
        if status != 302 or "discord.com/oauth2/authorize" not in location:
            raise Fail(f"{LOGIN} answered {status} → {location[:80]!r}, not a Discord redirect")
        if want and urllib.parse.quote(want, safe="") not in location and want not in location:
            raise Fail(f"the Discord redirect does not carry DISCORD_REDIRECT_URI={want}")
        out.append("/auth/login redirects to Discord with the configured redirect_uri")
        status, _, _ = ctx.http(
            site + "/" + ctx.admin_path, host=None if site.startswith("https") else host
        )
        if status != 404:
            raise Fail(f"the admin path answers {status} to an anonymous request, not 404")
        out.append("the admin path is 404 to a stranger")
    if ctx.args.skip_manual:
        out.append("manual steps skipped (--skip-manual)")
        return
    print(MANUAL_A3.format(site=site, admin=ctx.admin_path))
    if ctx.args.dry_run:
        return
    input("Press Enter when the four steps above are done… ")
    facts = ctx.django_json("api", A3_VERIFY)
    problems = []
    if not facts.get("bootstrap_claimed"):
        problems.append("the bootstrap id has not claimed instance admin (BootstrapClaim absent)")
    if facts.get("instance_admins", 0) < 1:
        problems.append("no instance admin exists")
    if facts.get("guild_admin_change", 0) < 1:
        problems.append("no audited own-guild change by a guild admin in the last hour")
    if facts.get("cross_guild_refusal", 0) < 1:
        problems.append("no audited refused cross-guild write in the last hour")
    if problems:
        raise Fail("; ".join(problems))
    out.append(
        f"bootstrap claimed; {facts['instance_admins']} instance admin(s); "
        f"own-guild change and cross-guild refusal both audited"
    )


MANUAL_A3 = """
--- A3, by hand, in a browser -------------------------------------------------
1. Sign in at {site}/auth/login with the Discord account named in
   BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID, then open {site}/{admin} and change
   anything (the first admin action claims instance admin and disables the
   environment path).
2. As that instance admin: add a configured guild and a role mapping that
   makes a second Discord account a guild admin of it, and a second guild.
3. Sign in as the guild admin (a second browser or a private window): edit
   your own guild's name or contact address and save (must succeed).
4. Still as the guild admin, submit a change to the OTHER guild (edit the URL
   to its id, or tick it in a bulk action) — it must be refused.
This script then reads the audit log to confirm steps 1, 3 and 4 happened.
-------------------------------------------------------------------------------"""

A3_VERIFY = """
import json
from datetime import timedelta
from django.utils import timezone
from core.models import AuditLogEntry, BootstrapClaim, User
since = timezone.now() - timedelta(hours=1)
rows = AuditLogEntry.objects.filter(created_at__gte=since)
print(json.dumps({
    "bootstrap_claimed": BootstrapClaim.objects.exists(),
    "instance_admins": User.objects.filter(is_instance_admin=True).count(),
    "guild_admin_change": rows.filter(model="configuredguild", action="change", outcome="allowed",
                                      actor__is_instance_admin=False).count(),
    "cross_guild_refusal": rows.filter(outcome="refused", actor__is_instance_admin=False).count(),
}))
"""


def a4_first_rebuild(ctx: Context, out: list[str], *, second: bool = False) -> None:
    """A4 — a weekly rebuild runs to promotion against the real Valhalla, the
    routers restart onto it, and each variant answers a canary route."""
    before = _latest_rebuild(ctx)
    proc = ctx.exec_in("rebuild", "./manage.py", "run_rebuild_now", check=False, timeout=120)
    if not ctx.args.dry_run:
        text = proc.stdout + proc.stderr
        if proc.returncode != 0 and "already in flight" not in text:
            raise Fail("run_rebuild_now: " + text.strip().splitlines()[-1])
        out.append(
            "queued" if proc.returncode == 0 else "a rebuild was already in flight; waiting on it"
        )
    run = _wait_for_rebuild(ctx, after_id=(before or {}).get("id"))
    if ctx.args.dry_run:
        ctx.compose("restart", *ROUTERS)
        for variant in VARIANTS:
            _canary(ctx, variant)
        ctx.exec_in("worker", "./manage.py", "check_operations", check=False)
        return
    if not run.get("succeeded"):
        raise Fail(f"weekly_rebuild run {run.get('id')} failed: {run.get('detail', '')[:300]}")
    out.append(f"weekly_rebuild run {run['id']} succeeded in {run.get('minutes', '?')} min")
    builds = {}
    for variant in VARIANTS:
        current = ctx.data_root / "tiles" / variant / "current"
        target = current.resolve() if current.exists() else None
        if target is None or not (target / "tiles.tar").is_file():
            raise Fail(f"{current} does not point at a build carrying tiles.tar")
        builds[variant] = target.name
    out.append("current → " + ", ".join(f"{v}={b}" for v, b in builds.items()))
    ctx.compose("restart", *ROUTERS, timeout=300)
    time.sleep(10)
    for variant in VARIANTS:
        _canary(ctx, variant)
    out.append("canary route answered on all three variants")
    ops = ctx.exec_in("worker", "./manage.py", "check_operations", check=False, timeout=120)
    if ops.returncode != 0:
        raise Fail("check_operations after the rebuild: " + ops.stdout.strip().splitlines()[-1])
    out.append("check_operations ok")
    if second:
        out.append("(second rebuild)")


LATEST_RUN = """
import json
from core.models import ScheduledRun
row = ScheduledRun.objects.filter(task="weekly_rebuild").order_by("-started_at").first()
print(json.dumps(None if row is None else {
    "id": row.pk, "finished": row.finished_at is not None, "succeeded": row.succeeded,
    "detail": row.detail[:600],
    "minutes": None if row.finished_at is None
               else round((row.finished_at - row.started_at).total_seconds() / 60),
}))
"""


def _latest_rebuild(ctx: Context) -> dict | None:
    facts = ctx.django_json("api", LATEST_RUN)
    return facts or None


def _wait_for_rebuild(ctx: Context, *, after_id: int | None) -> dict:
    if ctx.args.dry_run:
        return {}
    deadline = time.time() + ctx.args.rebuild_timeout
    while time.time() < deadline:
        run = _latest_rebuild(ctx)
        if run and run.get("finished") and (after_id is None or run["id"] != after_id):
            return run
        time.sleep(REBUILD_POLL_S)
    raise Fail(f"no weekly_rebuild run finished within {ctx.args.rebuild_timeout / 3600:.1f} h")


def _canary(ctx: Context, variant: str) -> None:
    (lon1, lat1), (lon2, lat2) = CANARY
    body = json.dumps(
        {
            "locations": [{"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}],
            "costing": "bicycle",
        }
    )
    code = (
        "import json,sys,urllib.request as u\n"
        f"r=u.urlopen(u.Request({ROUTER_URL[variant]!r}+'/route', data={body!r}.encode(),"
        " headers={'Content-Type':'application/json'}), timeout=60)\n"
        "d=json.load(r); legs=d.get('trip',{}).get('legs',[])\n"
        "print(json.dumps({'status': r.status, 'legs': len(legs),"
        " 'length_km': d.get('trip',{}).get('summary',{}).get('length')}))"
    )
    proc = ctx.exec_in("api", "python", "-c", code, check=False, timeout=90)
    if ctx.args.dry_run:
        return
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        answer = json.loads(line)
    except json.JSONDecodeError as error:
        tail = (proc.stderr or proc.stdout)[-200:]
        raise Fail(f"{variant}: canary route did not answer: {tail}") from error
    if answer.get("status") != 200 or answer.get("legs", 0) < 1:
        raise Fail(f"{variant}: canary route answered {answer}")


def a5_backup_and_restore(ctx: Context, out: list[str]) -> None:
    """A5 — a nightly dump is written and verified, and restores cleanly
    into an empty database beside the live one."""
    facts = ctx.django_json("worker", BACKUP_NOW, timeout=1800)
    if ctx.args.dry_run:
        dump = "/data/backups/routemaker-<instant>.dump"
        ctx.exec_in("worker", "pg_restore", "--list", dump)
        ctx.exec_in("worker", "createdb", RESTORE_DB)
        ctx.exec_in("worker", "pg_restore", "--no-owner", "-d", RESTORE_DB, dump)
        ctx.exec_in("worker", "dropdb", "--if-exists", RESTORE_DB)
        return
    dump = facts.get("path")
    if not dump:
        raise Fail(f"perform_backup did not return a path: {facts}")
    out.append(f"dump written: {Path(dump).name}")
    listing = ctx.exec_in("worker", "pg_restore", "--list", dump, timeout=300).stdout
    if "TABLE DATA" not in listing or "cached_membership" in _data_entries(listing):
        raise Fail(
            "the dump's listing is not the promised one (no data, or the excluded table's data)"
        )
    out.append("pg_restore --list shows table data and no excluded table's rows")
    ctx.exec_in("worker", "dropdb", "--if-exists", RESTORE_DB, check=False, timeout=120)
    ctx.exec_in("worker", "createdb", RESTORE_DB, timeout=120)
    try:
        restore = ctx.exec_in(
            "worker", "pg_restore", "--no-owner", "-d", RESTORE_DB, dump, check=False, timeout=1800
        )
        errors = re.findall(r"errors ignored on restore: (\d+)", restore.stderr)
        if restore.returncode != 0 or errors:
            raise Fail(
                f"pg_restore into an empty database: exit {restore.returncode}, "
                f"errors {errors or 0}: {restore.stderr.strip().splitlines()[-3:]}"
            )
        count = ctx.exec_in(
            "worker",
            "psql",
            "-At",
            "-d",
            RESTORE_DB,
            "-c",
            "select (select count(*) from django_migrations), (select count(*) from live.segment)",
            timeout=300,
        ).stdout.strip()
        out.append(f"restored into an empty database with 0 errors; migrations,segments = {count}")
    finally:
        ctx.exec_in("worker", "dropdb", "--if-exists", RESTORE_DB, check=False, timeout=120)


BACKUP_NOW = """
import json
from config.procrastinate import perform_backup
print(json.dumps({"path": str(perform_backup())}))
"""


def _data_entries(listing: str) -> str:
    return "\n".join(line for line in listing.splitlines() if "TABLE DATA" in line)


def a6_rollback(ctx: Context, out: list[str]) -> None:
    """A6 — with two promoted builds on disk, the rollback rehearses, then
    runs, and the routers serve the older build afterwards."""
    if not ctx.args.second_rebuild:
        if ctx.args.dry_run:  # the plan, even though the item itself is skipped
            ctx.exec_in("rebuild", "./manage.py", "run_rebuild_now", check=False)
            ctx.exec_in("rebuild", "./manage.py", "rollback_rebuild", check=False)
            ctx.exec_in("rebuild", "./manage.py", "rollback_rebuild", "--confirm", check=False)
            ctx.compose("restart", *ROUTERS)
        raise Skip("needs two promoted builds; run with --second-rebuild (another full rebuild)")
    a4_first_rebuild(ctx, out, second=True)
    dry = ctx.exec_in("rebuild", "./manage.py", "rollback_rebuild", check=False, timeout=120)
    if ctx.args.dry_run:
        return
    if dry.returncode != 0 or dry.stdout.count("would go back to build") != len(VARIANTS):
        raise Fail("rollback dry run: " + (dry.stderr or dry.stdout).strip().splitlines()[-1])
    targets = dict(re.findall(r"^(\S+): would go back to build (\S+)", dry.stdout, re.M))
    out.append(
        "dry run names a target for all three variants: "
        + ", ".join(f"{k}={v}" for k, v in targets.items())
    )
    if not ctx.args.confirm_rollback:
        out.append("--confirm-rollback not given; the live rollback was not run")
        return
    ctx.exec_in("rebuild", "./manage.py", "rollback_rebuild", "--confirm", timeout=600)
    ctx.compose("restart", *ROUTERS, timeout=300)
    time.sleep(10)
    for variant in VARIANTS:
        current = (ctx.data_root / "tiles" / variant / "current").resolve().name
        if current != targets.get(variant):
            raise Fail(
                f"{variant}: current is {current}, the rollback target was {targets.get(variant)}"
            )
        _canary(ctx, variant)
    out.append(
        "rolled back; current links match the targets; canary answered on all three variants"
    )


ITEMS = [
    ("A1", "Preflight: host, .env, data root, room", a1_preflight),
    ("A2", "Build and start the stack", a2_build_and_start),
    ("A3", "Edge, sign-in and the admin flows", a3_sign_in_and_admin),
    ("A4", "First rebuild, promotion, routers, canary", a4_first_rebuild),
    ("A5", "Backup and restore into an empty database", a5_backup_and_restore),
    ("A6", "Rollback after a second rebuild", a6_rollback),
]


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--only", nargs="+", metavar="ITEM", help="run only these items (A1..A6)")
    parser.add_argument("--dry-run", action="store_true", help="print what each item would run")
    parser.add_argument("--no-build", action="store_true", help="A2: skip `docker compose build`")
    parser.add_argument("--skip-manual", action="store_true", help="A3: skip the browser steps")
    parser.add_argument(
        "--second-rebuild", action="store_true", help="A6: run a second full rebuild first"
    )
    parser.add_argument(
        "--confirm-rollback",
        action="store_true",
        help="A6: run the live rollback, not only the dry run",
    )
    parser.add_argument(
        "--rebuild-timeout", type=float, default=REBUILD_TIMEOUT_S, metavar="SECONDS"
    )
    parser.add_argument(
        "--resume", metavar="REPORT.json", help="skip items that passed in an earlier report"
    )
    parser.add_argument("--report-dir", default=str(REPO / "acceptance-reports"))
    parser.add_argument("--strict", action="store_true", help="a SKIP counts as a failure")
    args = parser.parse_args(argv)

    env_path = REPO / ".env"
    if not env_path.is_file() and args.dry_run:
        env_path = REPO / ".env.example"
    env = read_env_file(env_path) if env_path.is_file() else {}
    ctx = Context(args=args, env=env)
    passed_before: set[str] = set()
    if args.resume:
        earlier = json.loads(Path(args.resume).read_text())
        passed_before = {r["item"] for r in earlier.get("results", []) if r["status"] == "PASS"}

    # `dt.timezone.utc` rather than `dt.UTC`: this runs on the host's Python, which
    # may be older than the repository's 3.11.
    started = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()  # noqa: UP017
    commit = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO, text=True, capture_output=True
        ).stdout.strip()
        or "unknown"
    )
    results: list[Result] = []
    for item, title, fn in ITEMS:
        if args.only and item not in args.only:
            continue
        if item in passed_before:
            results.append(Result(item, title, "PASS", ["passed in the resumed report"]))
            print(f"[PASS] {item} {title}\n      passed in the resumed report")
            continue
        out: list[str] = []
        t0 = time.time()
        try:
            fn(ctx, out)
            status = "PASS"
        except Skip as skip:
            status, out = "SKIP", out + [str(skip)]
        except Fail as fail:
            status, out = "FAIL", out + [str(fail)]
        except (subprocess.TimeoutExpired, OSError) as error:
            status, out = "FAIL", out + [f"{type(error).__name__}: {error}"]
        results.append(Result(item, title, status, out, time.time() - t0))
        print(f"[{status}] {item} {title}" + ("" if not out else "\n      " + "\n      ".join(out)))
        if status == "FAIL" and not args.dry_run:
            break  # later items depend on this one

    meta = {
        "started": started,
        "commit": commit,
        "host": os.uname().nodename,
        "compose_version": (
            ctx.compose("version", "--short", check=False).stdout.strip()
            if not args.dry_run
            else "dry run"
        ),
        "site": ctx.site,
        "data_root": str(ctx.data_root),
        "dry_run": args.dry_run,
    }
    report_dir = Path(args.report_dir)
    if not args.dry_run:
        report_dir.mkdir(parents=True, exist_ok=True)
        stem = report_dir / started.replace(":", "").replace("+0000", "Z")
        stem.with_suffix(".json").write_text(
            json.dumps(
                {"meta": meta, "results": [r.__dict__ for r in results], "commands": ctx.log},
                indent=2,
            )
        )
        stem.with_suffix(".md").write_text(render_markdown(results, meta))
        print(f"\nreport: {stem.with_suffix('.md')}")
    else:
        print("\n".join(ctx.log))
    failed = any(r.status == "FAIL" for r in results) or (
        args.strict and any(r.status == "SKIP" for r in results)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
