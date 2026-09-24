"""The stack as compose *renders* it, from the `.env.example` an operator copies.

tests/test_compose.py reads the YAML. That is the right level for the rules
about what is written down - which service holds which secret, which queue each
worker consumes - and it is the wrong level for anything a variable can
override, because every value in that file is a `${...}` string and the file
cannot see the environment file that fills them in.

Which is how the stack shipped unstartable with a green suite. `compose.yaml`
says `PGHOST: ${PGHOST:-postgis}`, and the YAML-level assertion that it is not
"127.0.0.1" passed on the literal `${PGHOST:-postgis}` - while `.env.example`
set `PGHOST=127.0.0.1`, so the rendered configuration gave all four Django
services the loopback address of their own container. `migrate` could not
connect, and `api`, `worker` and `rebuild` all wait on migrate completing, so
what came up was Caddy and three routers serving nothing.

So these tests run `docker compose config` against a copy of `.env.example` and
assert on what comes out. The Docker CLI renders a configuration without a
daemon - no registry, no build, no container - so this needs nothing the
development environment does not have.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

# The services that import Django settings and open a database connection.
DJANGO_SERVICES = ("api", "worker", "migrate", "rebuild")

# The services a default `up` must not start, for two different reasons.
# `bot` and `renderer` have no source in this repository and therefore no image
# anywhere; `photon` has an image and a pin, and what that image does on a
# fresh host is the reason it is here (see the photon tests below).
# docs/DEPLOYMENT.md and handoff.md section 7 carry the same three names.
UNBUILT_PROFILE = "unbuilt"
UNBUILT_SERVICES = {"bot", "renderer", "photon"}
NO_IMAGE_ANYWHERE = {"bot", "renderer"}

# The registry namespace this project's own four images live under: the GitHub
# Container Registry account of this repository's owner. Named once, because
# three tests below are about it being one namespace and a real one.
OURS = "ghcr.io/macrophage87/routemaker-"

# Scheme to the port a browser uses when the URL names none. A redirect URI is
# written without a port on a real deployment, and "no port" is a port.
DEFAULT_PORTS = {"http": 80, "https": 443}


def render(env_file: Path, *profiles: str) -> dict:
    """`docker compose config`, as JSON, with `env_file` standing in for `.env`.

    `--env-file` replaces compose's own default lookup, so a developer's `.env`
    sitting in the repository cannot change what this renders.

    The *shell* still can, and does: compose gives an inherited variable
    precedence over the env file, and this suite runs with `PGDATABASE` set to
    its own test database. So the `PG*` names are dropped from the subprocess
    environment - what these tests ask is what an operator's env file renders,
    which cannot be allowed to depend on who is running them.
    """
    if shutil.which("docker") is None:
        pytest.skip(
            "the docker CLI is not installed, so the compose configuration cannot be "
            "rendered. No daemon is needed - `docker compose config` is offline - but "
            "the CLI is."
        )
    command = ["docker", "compose", "-f", str(REPO / "compose.yaml"), "--env-file", str(env_file)]
    for profile in profiles:
        command += ["--profile", profile]
    command += ["config", "--format", "json"]
    environ = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    finished = subprocess.run(
        command, cwd=REPO, capture_output=True, text=True, timeout=120, env=environ
    )
    if finished.returncode != 0:
        if "compose" in finished.stderr and "is not a docker command" in finished.stderr:
            pytest.skip("the docker CLI has no compose plugin")
        raise AssertionError(
            f"`docker compose config` failed ({finished.returncode}): {finished.stderr[-2000:]}"
        )
    return json.loads(finished.stdout)


@pytest.fixture(scope="module")
def env_file(tmp_path_factory) -> Path:
    """A copy of `.env.example`, which is what a first deployment runs on.

    A copy rather than the file itself, so that a test that needs to mutate a
    value has the same shape to work with and nothing ever writes into the
    repository.
    """
    destination = tmp_path_factory.mktemp("env") / "env"
    destination.write_text(ENV_EXAMPLE.read_text())
    return destination


@pytest.fixture(scope="module")
def rendered(env_file) -> dict:
    return render(env_file)


def environment(rendered: dict, service: str) -> dict:
    return rendered["services"][service]["environment"]


# --- The database host, rendered ---------------------------------------------


def test_every_django_service_is_pointed_at_the_database_service(rendered) -> None:
    """The defect this file exists for.

    `postgis` by name, resolved on the compose network. Anything loopback is
    the container itself, where nothing listens on 5432 - and the failure is
    not localised: migrate exits, and the three services gated on it having
    completed never start.
    """
    postgis = "postgis"
    assert postgis in rendered["services"], "the database service has been renamed"
    for service in DJANGO_SERVICES:
        host = environment(rendered, service)["PGHOST"]
        assert host == postgis, (
            f"rendered from .env.example, {service} would connect to PGHOST={host!r} "
            f"rather than the {postgis!r} service"
        )


def test_the_example_does_not_override_the_compose_default_for_the_database_host(
    tmp_path,
) -> None:
    """The mechanism, stated once so the fix cannot be undone by a different
    wrong value.

    `.env.example` is an environment file, and an environment file wins over
    `${PGHOST:-postgis}`. Any uncommented PGHOST in it is therefore a value
    that reaches all four Django services, which is fine for a database outside
    this stack and wrong for every other reason it might be set.
    """
    mutated = tmp_path / "env"
    mutated.write_text(ENV_EXAMPLE.read_text() + "\nPGHOST=127.0.0.1\n")
    hosts = {
        service: environment(render(mutated), service)["PGHOST"] for service in DJANGO_SERVICES
    }
    assert set(hosts.values()) == {"127.0.0.1"}, (
        "this test's premise is wrong: an env file no longer overrides the compose default"
    )


def test_the_database_service_is_created_with_the_names_django_connects_with(
    tmp_path,
) -> None:
    """The names travel together, or the stack has a database nobody uses.

    `POSTGRES_DB` and `POSTGRES_USER` are what the postgis image's first boot
    calls `initdb` with, and `PGDATABASE`/`PGUSER` are what every Django
    service connects as. They were literals on one side and variables on the
    other, so a deployment that set either name in `.env` got a database and a
    role created under one pair of names and four services asking for another -
    and `migrate` fails on a role that does not exist, taking the three
    services gated on it with it.

    Rendered from an env file that sets both to something other than the
    default, because the default is `routemaker` and `.env.example` sets
    `routemaker`: against that file a hardcoded literal renders identically to
    the substitution and nothing can tell them apart.
    """
    text = ENV_EXAMPLE.read_text()
    text = re.sub(r"^PGDATABASE=.*$", "PGDATABASE=atlas", text, flags=re.M)
    text = re.sub(r"^PGUSER=.*$", "PGUSER=surveyor", text, flags=re.M)
    assert "PGDATABASE=atlas" in text and "PGUSER=surveyor" in text, (
        "this test's premise is wrong: .env.example no longer sets these names"
    )
    mutated = tmp_path / "env"
    mutated.write_text(text)
    rendered = render(mutated)

    postgis = environment(rendered, "postgis")
    assert postgis["POSTGRES_DB"] == "atlas", (
        "the database the image creates does not follow PGDATABASE, so a deployment "
        f"that sets it gets a database nothing connects to: {postgis!r}"
    )
    assert postgis["POSTGRES_USER"] == "surveyor", postgis

    # And the other half of the pairing: what the image creates is what Django
    # asks for. Asserted against the rendered services rather than restated, so
    # the two cannot drift apart under a variable either.
    for service in DJANGO_SERVICES:
        assert environment(rendered, service)["PGDATABASE"] == postgis["POSTGRES_DB"]
        assert environment(rendered, service)["PGUSER"] == postgis["POSTGRES_USER"]

    # The health gate probes the database the application uses, which is the
    # same substitution a third time.
    probe = " ".join(rendered["services"]["postgis"]["healthcheck"]["test"])
    assert "-U surveyor" in probe and "-d atlas" in probe, probe


# --- The two services with no image ------------------------------------------


def test_the_default_up_does_not_reach_for_an_image_that_exists_nowhere(rendered) -> None:
    """`bot` and `renderer` have no source, no `build:` and nothing in any
    registry, so a default `docker compose up -d` - which is what
    docs/DEPLOYMENT.md tells an operator to run - stopped at a pull that cannot
    succeed. Behind a profile they are skipped and the rest of the stack starts.
    """
    present = NO_IMAGE_ANYWHERE & set(rendered["services"])
    assert not present, (
        f"the default configuration still includes {sorted(present)}, which have no image; "
        f"they belong behind `profiles: [{UNBUILT_PROFILE!r}]`"
    )


def test_the_profile_is_how_those_services_come_back(env_file) -> None:
    """A profile that hid them and could not show them again would be a
    deletion with extra steps. Named explicitly, they render in full - so the
    day either one has a source, the stack it rejoins is this one."""
    with_profile = render(env_file, UNBUILT_PROFILE)["services"]
    assert UNBUILT_SERVICES <= set(with_profile), (
        f"`--profile {UNBUILT_PROFILE}` renders {sorted(with_profile)}, "
        f"which is missing {sorted(UNBUILT_SERVICES - set(with_profile))}"
    )
    for service in sorted(UNBUILT_SERVICES):
        limits = with_profile[service]["deploy"]["resources"]["limits"]
        assert {"memory", "cpus"} <= set(limits), (
            f"{service} lost its limits behind the profile; the swap-time sizing counts it"
        )


# --- Photon: what the pinned image does on a fresh host -----------------------


def test_the_default_up_does_not_start_the_planet_downloader(rendered) -> None:
    """The first `up` on every new deployment, which is the whole of this.

    `rtuszik/photon-docker:2.4.0` defaults INITIAL_DOWNLOAD to True
    (`src/utils/config.py:23` in that tag) and this stack sets no REGION, so the
    entrypoint's first act is to fetch the whole-planet index: ~61 GB
    compressed, ~104 GB free needed to unpack. It kept its data at
    `/photon/data` (`config.py:36`) while compose bound `${DATA_ROOT}/photon` at
    the 1.x `/photon/photon_data`, so the mount was inert and the download would
    have landed on the container's writable layer - the *root* volume, which
    PLAN:293 sizes small. Short of the space the entrypoint exits 75, and
    `restart: unless-stopped` makes that a crash loop from the first `up`.

    Nothing in phase 1 calls Photon and PLAN:60's index import is unbuilt, so
    the service is parked rather than repaired into usefulness.
    """
    assert "photon" not in rendered["services"], (
        "a default `docker compose up -d` starts photon again, which on a fresh host is a "
        "61 GB planet download onto the root volume"
    )


def test_enabling_the_profile_gets_an_index_mount_that_the_image_uses(env_file) -> None:
    """The profile has to be safe to turn on, or it is only a deferral.

    Two corrections, both read off the pinned tag's own source: the index lands
    at `/photon/data`, where 2.4.0 keeps it, so it goes on the data volume
    rather than the container's writable layer; and INITIAL_DOWNLOAD is off, so
    enabling the profile starts a geocoder with an empty index instead of a
    61 GB download.
    """
    photon = render(env_file, UNBUILT_PROFILE)["services"]["photon"]

    targets = {volume["target"] for volume in photon["volumes"]}
    assert "/photon/data" in targets, (
        f"photon binds {sorted(targets)}; 2.4.0 reads its index from /photon/data "
        "(src/utils/config.py:36), and a mount anywhere else is inert"
    )
    assert "/photon/photon_data" not in targets, "that is the 1.x path; nothing reads it in 2.4.0"

    initial = str(photon.get("environment", {}).get("INITIAL_DOWNLOAD", "")).lower()
    assert initial in {"false", "0", "no"}, (
        f"photon renders INITIAL_DOWNLOAD={initial!r}; the image defaults it to True "
        "(src/utils/config.py:23) and with REGION unset that is the planet"
    )


# --- The data volume, scoped per service -------------------------------------


def data_root(env_file: Path) -> str:
    values = {}
    for line in env_file.read_text().splitlines():
        if not line.lstrip().startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    return values["DATA_ROOT"]


def mounters(rendered: dict, root: str, directory: str) -> set[str]:
    """Every service binding `${DATA_ROOT}/<directory>`, at any target."""
    prefix = f"{root}/{directory}"
    return {
        name
        for name, service in rendered["services"].items()
        for volume in service.get("volumes", [])
        if volume.get("source") == prefix or str(volume.get("source", "")).startswith(prefix + "/")
    }


def test_the_database_files_and_the_tls_key_reach_one_service_each(env_file) -> None:
    """`${DATA_ROOT}` is one volume and it holds three things no other service
    has any business reading: PGDATA, Caddy's ACME account key and TLS private
    key, and the nightly dumps. The `rebuild` service used to bind the whole of
    it at `/data` - so the container that shells out to six Valhalla binaries
    for six hours could read the edge's private key and the database's files.
    That contradicts this file's own header rule, which scopes secrets per
    service precisely so that what one container can reach is readable at a
    glance.

    Rendered rather than read out of the YAML, and with the profile on, so a
    service that came back from behind a profile is counted too.
    """
    rendered = render(env_file, UNBUILT_PROFILE)
    root = data_root(env_file)

    assert mounters(rendered, root, "postgres") == {"postgis"}, (
        "something other than the database binds PGDATA"
    )
    assert mounters(rendered, root, "caddy") == {"caddy"}, (
        "something other than the edge binds the ACME account key and the TLS private key"
    )
    assert mounters(rendered, root, "backups") == {"worker"}, (
        "something other than the backup worker binds the nightly dumps"
    )
    assert not any(
        volume.get("source") == root
        for service in rendered["services"].values()
        for volume in service.get("volumes", [])
    ), "a service binds the whole data volume again, which is all three of the above at once"


def test_the_rebuild_still_reaches_everything_it_writes(env_file) -> None:
    """The other half of the narrowing: five directories, at the paths
    `settings.DATA_ROOT` derives, or the rebuild fails on a path it cannot see
    rather than on anything it did.
    """
    rendered = render(env_file, UNBUILT_PROFILE)
    targets = {
        volume["target"]
        for volume in rendered["services"]["rebuild"]["volumes"]
        if str(volume["target"]).startswith("/data")
    }
    assert targets == {
        "/data/tiles",
        "/data/elevation",
        "/data/extracts",
        "/data/reference",
        "/data/rebuild",
    }, f"the rebuild binds {sorted(targets)} under /data"
    assert environment(rendered, "rebuild")["DATA_ROOT"] == "/data", (
        "DATA_ROOT moved, so TILES_DIR, REBUILD_SOURCE_PBF, REBUILD_REFERENCE_DIR and "
        "REBUILD_WORK_DIR no longer land in the mounts above"
    )


# --- Start-up ordering, rendered ---------------------------------------------


def test_the_database_declares_a_health_check(rendered) -> None:
    """`service_started` is a container that exists, which for PostgreSQL on a
    fresh volume is initdb and the PostGIS extension scripts still running with
    the port closed. The probe has to be the database answering, and as the
    role and database the application uses - `pg_isready` with no arguments
    would report on whatever the image's defaults are."""
    check = rendered["services"]["postgis"].get("healthcheck")
    assert check, "the postgis service declares no healthcheck"
    probe = " ".join(check["test"])
    assert "pg_isready" in probe, f"the health check is not pg_isready: {check['test']}"
    assert "-h 127.0.0.1" in probe, (
        f"the health check is `{probe}`, which has no host and so probes the unix socket. "
        "That is exactly what the image's init-phase server listens on - its entrypoint "
        "runs initdb and the extension scripts against a temporary server started with "
        "listen_addresses='' - so the probe answers PQPING_OK through the whole first-boot "
        "window this gate exists to cover, while a TCP connect is still refused. migrate "
        "connects over TCP; the gate has to measure the same thing"
    )
    expected = environment(rendered, "migrate")
    assert f"-U {expected['PGUSER']}" in probe, (
        f"the health check probes a different role than migrate connects as: {probe}"
    )
    assert f"-d {expected['PGDATABASE']}" in probe, (
        f"the health check probes a different database than migrate connects to: {probe}"
    )


def test_migrate_waits_for_a_database_that_answers(rendered) -> None:
    assert rendered["services"]["migrate"]["depends_on"]["postgis"]["condition"] == (
        "service_healthy"
    ), "migrate would start against a database that is still recovering"


def test_the_three_django_services_wait_for_the_migration_to_finish(rendered) -> None:
    """Unchanged, and asserted on the rendered configuration rather than the
    YAML so that the health gate above cannot be added by weakening these.
    `service_completed_successfully` is strictly later than the database being
    healthy, so these need no health condition of their own."""
    for service in ("api", "worker", "rebuild"):
        conditions = rendered["services"][service]["depends_on"]
        assert conditions["migrate"]["condition"] == "service_completed_successfully", service


# --- The images are pinned ----------------------------------------------------


def test_no_service_runs_a_floating_tag(rendered, env_file) -> None:
    """PLAN:293, "all images pinned". `latest` is whatever a maintainer pushed
    last, so a `docker compose pull` on a bad week is a different component with
    no change in this repository - and the two images this stack builds are
    tagged from `TAG`, which the operator moves deliberately.
    """
    tag_value = [
        line.split("=", 1)[1].strip()
        for line in env_file.read_text().splitlines()
        if line.startswith("TAG=")
    ]
    assert tag_value, ".env.example no longer sets TAG"
    built_locally = {f"routemaker/{name}:{tag_value[0]}" for name in ("api", "pipeline")}
    floating = {
        name: service["image"]
        for name, service in render(env_file, UNBUILT_PROFILE)["services"].items()
        if service["image"] not in built_locally
        and (":" not in service["image"] or service["image"].endswith(":latest"))
    }
    assert not floating, f"services on an unpinned image: {floating}"


# --- The sign-in posture of the shipped example -------------------------------


def example_values() -> dict[str, str]:
    """`.env.example`'s uncommented assignments. The commented local block is
    deliberately not read: it is an alternative an operator opts into, and the
    thing under test is what the file does as shipped."""
    values = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()
    return values


def published_ports(rendered: dict) -> set[int]:
    """Every host port the stack publishes. Caddy is the only service allowed
    one (PLAN:65), which tests/test_compose.py pins; this reads them all so a
    port that appeared elsewhere would not quietly satisfy the check below."""
    return {
        int(str(port["published"]).rsplit(":", 1)[-1])
        for service in rendered["services"].values()
        for port in service.get("ports", [])
    }


def test_the_shipped_example_can_complete_a_discord_sign_in(rendered) -> None:
    """Four values are one decision and the example had them as four.

    As shipped before this: `CADDY_SITE_ADDRESS=:80` with DJANGO_DEBUG unset,
    so the session and CSRF cookies were Secure and a plain-HTTP browser
    discarded both; `DISCORD_REDIRECT_URI=http://localhost:8000/auth/callback`,
    naming a port nothing in the stack publishes; and
    `DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost` against an http origin. Each
    of those on its own stops a sign-in, and nothing in the suite read the file.

    The redirect URI is the anchor because it is the one value that also has to
    match a registration on the Discord application: whatever it says, the stack
    has to answer to that host, trust that origin for a POST, and publish that
    port.
    """
    values = example_values()
    redirect = urlsplit(values["DISCORD_REDIRECT_URI"])

    hosts = [h.strip() for h in values["DJANGO_ALLOWED_HOSTS"].split(",") if h.strip()]
    assert redirect.hostname in hosts, (
        f"the redirect URI sends the browser to {redirect.hostname!r}, which is not in "
        f"DJANGO_ALLOWED_HOSTS ({hosts}); Django answers that request with a 400"
    )

    origins = [o.strip() for o in values["DJANGO_CSRF_TRUSTED_ORIGINS"].split(",") if o.strip()]
    origin = f"{redirect.scheme}://{redirect.netloc}"
    assert origin in origins, (
        f"the sign-in arrives from {origin}, which is not in DJANGO_CSRF_TRUSTED_ORIGINS "
        f"({origins}); every POST from the site is refused as a CSRF origin failure"
    )

    port = redirect.port or DEFAULT_PORTS[redirect.scheme]
    assert port in published_ports(rendered), (
        f"the redirect URI names port {port}, which no service in the rendered stack "
        f"publishes (published: {sorted(published_ports(rendered))})"
    )


def test_the_shipped_example_does_not_serve_secure_cookies_over_plain_http() -> None:
    """`settings.py` derives `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`
    from `not DEBUG`, so with DJANGO_DEBUG unset every cookie is Secure. A `:80`
    site address is plain HTTP with no certificate at all, and a browser drops a
    Secure cookie on a plain-HTTP response without saying anything: the Discord
    round-trip completes and the next request is anonymous.

    Refused here rather than documented, because the example has to work as
    shipped. The local plain-HTTP arrangement is the commented block in the file
    and it sets DJANGO_DEBUG=1, which is exactly what makes it legal.
    """
    values = example_values()
    address = values.get("CADDY_SITE_ADDRESS", "")
    debug = values.get("DJANGO_DEBUG", "") == "1"
    plain_http = address.startswith(":") or address.startswith("http://")
    assert not (plain_http and not debug), (
        f"CADDY_SITE_ADDRESS={address!r} serves plain HTTP while DJANGO_DEBUG is not 1, so "
        "the session and CSRF cookies are Secure and no browser will keep them. Either ship "
        "a hostname (automatic TLS) or set DJANGO_DEBUG=1 with it."
    )
    origins = values.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")
    assert not (plain_http and "https://" in origins), (
        f"CADDY_SITE_ADDRESS={address!r} is plain HTTP and DJANGO_CSRF_TRUSTED_ORIGINS is "
        f"{origins!r}; the origin a browser sends is the one it used"
    )


# --- The example file's own claims about itself -------------------------------

# The alternative posture at the end of `.env.example`: a commented assignment
# per line, which an operator uncomments in place of the four above it.
LOCAL_BLOCK_HEADER = "--- Local plain-HTTP stack"
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
}


def local_block_assignments() -> list[str]:
    """The commented `NAME=value` lines after the local block's header."""
    _, _, block = ENV_EXAMPLE.read_text().partition(LOCAL_BLOCK_HEADER)
    assert block, f".env.example no longer has a {LOCAL_BLOCK_HEADER!r} section"
    return [
        line.lstrip("# ").partition("=")[0]
        for line in block.splitlines()
        if re.match(r"^#\s*[A-Z][A-Z0-9_]*=", line)
    ]


def redirect_uris() -> dict[str, str]:
    """Every redirect URI an operator can end up running with: the shipped
    value, the local block's commented alternative, and the settings default
    for a process started with neither."""
    from django.conf import settings

    local = [
        line.lstrip("# ").partition("=")[2].strip()
        for line in ENV_EXAMPLE.read_text().partition(LOCAL_BLOCK_HEADER)[2].splitlines()
        if re.match(r"^#\s*DISCORD_REDIRECT_URI=", line)
    ]
    assert len(local) == 1, f"the local block carries {len(local)} redirect URIs"
    return {
        "shipped": example_values()["DISCORD_REDIRECT_URI"],
        "local block": local[0],
        # Read from the module rather than from `settings`, which the test run
        # may have overridden: the default is what a bare process gets.
        "settings default": re.search(
            r'DISCORD_REDIRECT_URI = os\.environ\.get\("DISCORD_REDIRECT_URI", "([^"]+)"\)',
            (REPO / "src" / "config" / "settings.py").read_text(),
        ).group(1),
        "running": settings.DISCORD_REDIRECT_URI,
    }


@pytest.mark.parametrize("which", ["shipped", "local block", "settings default", "running"])
def test_every_redirect_uri_lands_on_the_sign_in_callback(which) -> None:
    """The fourth part of the URI, and the one the sign-in test did not pin.

    Scheme, host, origin and port are checked above against the stack; the
    path was not checked against anything, so a redirect URI naming
    `/auth/callbak` - or a callback route moved without the example following
    it - rendered and started cleanly and failed at the first sign-in, with
    Discord sending the browser back to a 404. Resolved through the URLconf
    rather than compared with a literal, so it follows the route wherever it
    is mounted.
    """
    from django.urls import Resolver404, resolve

    from core import auth_views

    uri = redirect_uris()[which]
    path = urlsplit(uri).path
    try:
        match = resolve(path)
    except Resolver404:
        pytest.fail(f"the {which} redirect URI {uri!r} names {path!r}, which nothing serves")
    assert match.func is auth_views.login_callback, (
        f"the {which} redirect URI {uri!r} lands on {match.view_name}, not the sign-in callback"
    )


def test_the_example_counts_its_own_local_block_correctly() -> None:
    """The file said four and the block is five, and the fifth is the one that
    matters: `DJANGO_DEBUG=1`. It is the only line in the block with no
    counterpart among the uncommented values above, so it is the one an
    operator working from the count drops - and dropping it is round 6's B-5
    exactly, a `:80` stack issuing Secure cookies that no plain-HTTP browser
    keeps, where the Discord round-trip completes and every request after it is
    anonymous.

    Counted rather than restated, and every claim in the file is checked, so
    the count and the prose cannot drift apart again.
    """
    assignments = local_block_assignments()
    assert "DJANGO_DEBUG" in assignments, (
        "the local block no longer sets DJANGO_DEBUG, which is what makes a plain-HTTP "
        "stack able to keep a session cookie at all"
    )

    claimed = [
        NUMBER_WORDS[word]
        for word in re.findall(r"\b([a-z]+) lines\b", ENV_EXAMPLE.read_text())
        if word in NUMBER_WORDS
    ]
    assert claimed, ".env.example no longer states how many lines its local block is"
    assert set(claimed) == {len(assignments)}, (
        f".env.example says its local block is {sorted(set(claimed))} lines and it is "
        f"{len(assignments)}: {assignments}"
    )


def test_the_admin_path_is_offered_in_the_example_and_reaches_the_api(tmp_path) -> None:
    """`settings.ADMIN_PATH` defaults to `internal-8f3a/`, which is in this
    repository and therefore public. The default is fine and the point is that
    an operator should know it is a default: the line is in `.env.example`,
    commented, with what it is for - and it has to be a line compose carries, or
    setting it would change nothing at all.
    """
    body = ENV_EXAMPLE.read_text()
    assert re.search(r"^#\s*DJANGO_ADMIN_PATH=", body, re.M), (
        ".env.example does not offer DJANGO_ADMIN_PATH, so the published default is the "
        "only path anyone knows to set"
    )

    mutated = tmp_path / "env"
    mutated.write_text(body + "\nDJANGO_ADMIN_PATH=somewhere-else/\n")
    assert environment(render(mutated), "api")["DJANGO_ADMIN_PATH"] == "somewhere-else/", (
        "a DJANGO_ADMIN_PATH set in the environment file does not reach the api, so the "
        "admin stays on the path this repository publishes"
    )


# --- Stopping, logging, and the worker count ----------------------------------


def duration_seconds(value: str) -> float:
    """A Go duration as compose renders it ("60s", "1m0s", "1h30m0s")."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", str(value).strip())
    assert match and any(match.groups()), f"not a duration compose would render: {value!r}"
    hours, minutes, secs = match.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(secs or 0)


def test_the_rebuild_is_given_time_to_stop_rather_than_being_killed(rendered) -> None:
    """Compose's default is ten seconds between the SIGTERM and the SIGKILL.

    This is the one service whose shutdown competes with its own build for the
    database: procrastinate cancels its side tasks and then calls
    `unregister_worker`, which is a round trip to the PostgreSQL the rebuild has
    had four cores' worth of load on. A grace period is what makes a clean stop
    the ordinary outcome of `down`, `up -d` and `restart`.

    It is bounded on both sides and the upper bound is the point: no value here
    saves a build that is running, because procrastinate 3.9.0 leaves
    `shutdown_graceful_timeout` unset and therefore waits for the running job
    without limit, and `weekly_rebuild` is a synchronous task that polls
    `should_abort` nowhere. A stop mid-build ends at the SIGKILL whatever this
    says, with the job row left `doing` for `unwedge_job`. A grace period long
    enough to pretend otherwise would only make `docker compose down` hang.
    """
    grace = rendered["services"]["rebuild"].get("stop_grace_period")
    assert grace, (
        "the rebuild service declares no stop_grace_period, so compose kills its worker "
        "ten seconds after the SIGTERM and the shutdown that unregisters it from the "
        "database is a race"
    )
    seconds = duration_seconds(grace)
    assert 30 <= seconds <= 300, (
        f"stop_grace_period is {grace}; under 30s is the race this exists to remove, and "
        "over 300s is a `docker compose down` that appears to hang while no value here "
        "can outlast a six-hour build anyway"
    )


def test_every_service_rotates_its_logs(env_file) -> None:
    """Docker's default `json-file` driver has no rotation at all, and the file
    it writes is on the root volume, which PLAN:293 sizes small and nothing in
    this stack binds. gunicorn logs a line per request, three valhalla
    containers log per request, and the rebuild prints its way through six
    hours; a full root volume stops the daemon rather than one container.

    Every service, with the profile on, because a service parked behind a
    profile still writes logs the day it is turned on.
    """
    services = render(env_file, UNBUILT_PROFILE)["services"]
    missing = sorted(name for name, service in services.items() if not service.get("logging"))
    assert not missing, f"services with no logging configuration: {missing}"
    for name, service in sorted(services.items()):
        logging = service["logging"]
        assert logging.get("driver") == "json-file", (
            f"{name} logs through {logging.get('driver')!r}; the rotation options below are "
            "json-file's and mean nothing to another driver"
        )
        options = logging.get("options") or {}
        assert {"max-size", "max-file"} <= set(options), (
            f"{name} sets {sorted(options)}; both are needed - a max-size with no max-file "
            f"keeps every rotated file, and a max-file with no max-size never rotates"
        )
        assert re.fullmatch(r"\d+[kmg]", str(options["max-size"]), re.I), options
        assert int(options["max-file"]) >= 2, (
            f"{name} keeps {options['max-file']} file(s); one file is a truncation, not a "
            "rotation, and the last thing before an incident is what gets dropped"
        )


def test_the_api_worker_count_is_the_one_its_cpu_limit_can_pay_for(rendered) -> None:
    """`docker/api-entrypoint.sh` derives a count when compose hands it none,
    and what it had to derive it from was `nproc` - which reports the *host*,
    because a compose `cpus:` limit is a cgroup quota and does not change it.
    On PLAN:293's 8-vCPU host that was 17 sync gunicorn workers, each a full
    Django process, inside this service's 2 GB limit.

    So compose delivers the value, and the assertion is against the service's
    own cpu limit rather than a number written twice: `2 * cpus + 1`, the same
    formula, read off the right figure.
    """
    api = rendered["services"]["api"]
    workers = api["environment"].get("WEB_CONCURRENCY")
    assert workers, (
        "compose hands the api no WEB_CONCURRENCY, so the entrypoint falls back to "
        "deriving one inside the container"
    )
    cpus = float(api["deploy"]["resources"]["limits"]["cpus"])
    assert int(workers) == int(2 * cpus + 1), (
        f"the api renders WEB_CONCURRENCY={workers} against a {cpus:g}-cpu limit; "
        f"gunicorn's own arithmetic on that limit is {int(2 * cpus + 1)}"
    )


def test_the_health_gate_has_a_start_period_as_well_as_retries(rendered) -> None:
    """Two windows, not one budget spent twice.

    `retries x interval` is the ordinary restart: a server that is already
    initialised and answers in seconds. The start period is the *first* boot on
    an empty volume - initdb, the PostGIS extension scripts, the first start -
    during which a failing probe does not count against the retries at all.
    Without it those two are the same sixty seconds, and a slow host doing
    first-boot work is a `postgis` marked unhealthy, a `migrate` whose
    dependency never opens, and `api`, `worker` and `rebuild` - all held on
    `service_completed_successfully` - that never start.
    """
    check = rendered["services"]["postgis"]["healthcheck"]
    assert "start_period" in check, (
        "the database health check has no start period, so the first boot on an empty "
        "volume spends the restart budget on initdb"
    )
    restart_window = duration_seconds(check["interval"]) * int(check["retries"])
    assert duration_seconds(check["start_period"]) >= restart_window, (
        f"the start period is {check['start_period']} against a restart budget of "
        f"{restart_window:g}s; first boot on an empty volume is the longer of the two"
    )


# --- the four constants these tests are written against -----------------------
#
# A canary, in the manner of tests/test_compose.py's derivation checks. Each of
# these sets is typed out by hand at the top of this file and stands between
# every test below and the stack, so each can be narrowed with the suite still
# green and nothing anywhere would say so: drop `rebuild` from DJANGO_SERVICES
# and the service that runs the six-hour rebuild stops being asked whether it
# can reach the database at all; drop `photon` from UNBUILT_SERVICES and the
# heaviest image in the stack quietly goes back to starting on a default `up`;
# drop `http` from DEFAULT_PORTS and a redirect URI written without a port is
# checked against nothing; drop `renderer` from NO_IMAGE_ANYWHERE and the test
# that a default `up` reaches for no image that exists nowhere goes on passing
# with the renderer back in the default stack.
#
# So each is asserted equal to a derivation from the rendered configuration.
# The lists stay hand-written - they are what this file claims the stack is,
# and a test that only ever asked the stack about itself would pass on any
# stack at all - and these three say when the claim and the stack part company.


def test_the_django_services_are_the_ones_compose_hands_a_database_to(rendered) -> None:
    """`DJANGO_SERVICES`, derived.

    A Django service here is one compose gives the libpq variables to: PGHOST
    and PGDATABASE are how `settings.DATABASES` is filled in, so a service that
    carries them is a service that opens a connection, and one that does not
    cannot. `postgis` is the server and carries `POSTGRES_*` instead.
    """
    connect = {
        name
        for name, service in rendered["services"].items()
        if {"PGHOST", "PGDATABASE", "PGUSER"} <= set(service.get("environment") or {})
    }
    assert set(DJANGO_SERVICES) == connect, (
        f"DJANGO_SERVICES names {sorted(DJANGO_SERVICES)} and the rendered stack "
        f"connects from {sorted(connect)}"
    )
    # And they are this repository's own images rather than anything pulled,
    # which is the other half of what makes them Django services.
    assert all(rendered["services"][name].get("build") for name in DJANGO_SERVICES)


def test_the_unbuilt_services_are_the_ones_behind_a_profile(env_file) -> None:
    """`UNBUILT_SERVICES`, derived.

    A service behind a profile is a service a default `up` does not start,
    which is the whole property the name records. Read from the render that
    names the profile, because the ones under test are absent from the other.
    """
    with_profile = render(env_file, UNBUILT_PROFILE)["services"]
    profiled = {name for name, service in with_profile.items() if service.get("profiles")}
    assert UNBUILT_SERVICES == profiled, (
        f"UNBUILT_SERVICES names {sorted(UNBUILT_SERVICES)} and the stack parks "
        f"{sorted(profiled)} behind a profile"
    )
    for name in sorted(profiled):
        assert with_profile[name]["profiles"] == [UNBUILT_PROFILE], (
            f"{name} is behind {with_profile[name]['profiles']}, and the tests above "
            f"only ever ask for --profile {UNBUILT_PROFILE}"
        )


def test_the_default_ports_are_the_ports_the_stack_publishes(rendered) -> None:
    """`DEFAULT_PORTS`, derived.

    The two schemes are only worth mapping because the edge proxy publishes
    exactly the two ports a browser assumes when a URL names none: that is what
    makes "no port" answerable at all. A scheme dropped from the mapping raises
    KeyError in the sign-in check rather than passing it - but a *port* changed
    to one nothing publishes would make that check assert against a number the
    stack never listens on, and the mapping is where it would come from.
    """
    assert set(DEFAULT_PORTS.values()) == published_ports(rendered), (
        f"the stack publishes {sorted(published_ports(rendered))} and the browser "
        f"defaults are {sorted(DEFAULT_PORTS.values())}"
    )
    assert set(DEFAULT_PORTS) == {"http", "https"}


def test_the_imageless_services_are_the_ones_nothing_builds(env_file) -> None:
    """`NO_IMAGE_ANYWHERE`, derived.

    An image under `OURS` is one this repository is the source of, and nothing
    pushes one anywhere: the tag exists on a host because that host built it.
    So a service whose image is in that namespace and which declares no
    `build:` is a service whose image exists nowhere at all - `api`, `worker`,
    `migrate` and `rebuild` name the same namespace and each carries a
    `build:` stanza, and `photon`, `caddy` and the three routers are pulled
    from real registries under their own names.

    Read with the profile on, because the services this names are absent from
    the default render - which is the property the tests above check.
    """
    services = render(env_file, UNBUILT_PROFILE)["services"]
    imageless = {
        name
        for name, service in services.items()
        if str(service.get("image", "")).startswith(OURS) and not service.get("build")
    }
    assert NO_IMAGE_ANYWHERE == imageless, (
        f"NO_IMAGE_ANYWHERE names {sorted(NO_IMAGE_ANYWHERE)} and the stack declares "
        f"{sorted(imageless)} with an image nothing builds and no registry holds"
    )
    assert NO_IMAGE_ANYWHERE < UNBUILT_SERVICES, (
        "every service with no image anywhere has to be behind the profile, and there "
        "has to be something else behind it too - photon, which has an image and is "
        "parked for a different reason"
    )


# --- Every image names a registry ---------------------------------------------


def test_no_image_in_the_rendered_stack_is_an_unqualified_reference(env_file) -> None:
    """An image name with no registry in it is a Docker Hub name, and Hub is a
    default rather than a decision.

    The four images of this project's own were `routemaker/api:${TAG}` and so
    on, which is `docker.io/routemaker/api:dev`: a namespace this project does
    not own, empty on Hub at the time of writing and registrable by anybody. A
    host without the locally built tag - after a prune, or on a `TAG` it never
    built - would have pulled whatever was there and started it with
    `PGPASSWORD`, `KEY_ENCRYPTION_KEY` and `DJANGO_SECRET_KEY` in its
    environment.

    The rule is the reference grammar's own: the first path component is the
    registry when it contains a `.` or a `:`, and otherwise the whole name is a
    Hub path. So this asks of every rendered image that its first component be
    a host, which `docker.io/postgis/postgis:16-3.4` satisfies as much as
    `ghcr.io/...` does - what is refused is the reference that leaves it out.

    Rendered rather than read from the YAML, because `${TAG}` is not the part
    that matters and a reference is what the daemon is handed.
    """
    services = render(env_file, UNBUILT_PROFILE)["services"]
    unqualified = {}
    for name, service in sorted(services.items()):
        image = str(service.get("image", ""))
        assert image, f"the {name} service renders with no image at all"
        head = image.split("/")[0]
        if "/" not in image or ("." not in head and ":" not in head):
            unqualified[name] = image
    assert not unqualified, (
        f"these images name no registry, so they resolve to Docker Hub by default: {unqualified}"
    )


def test_our_own_images_are_under_a_namespace_this_project_controls(env_file) -> None:
    """And the same one, so there is a single place a release would be pushed
    to and a single place a rollback would pull from."""
    services = render(env_file, UNBUILT_PROFILE)["services"]
    ours = {
        name: service["image"]
        for name, service in services.items()
        if service.get("build") or name in NO_IMAGE_ANYWHERE
    }
    assert set(ours) == {"api", "worker", "migrate", "rebuild"} | NO_IMAGE_ANYWHERE
    for name, image in sorted(ours.items()):
        assert image.startswith(OURS), (
            f"the {name} service's image is {image!r}, which is outside {OURS!r} - the "
            "namespace of this repository's own owner"
        )


def test_the_services_that_build_never_pull(env_file) -> None:
    """`pull_policy: never`, on each of the four.

    Compose's default policy for a service that declares both `image:` and
    `build:` is `missing`, which is a pull attempt first and a build only if
    that fails. These four are built from this working tree and pushed nowhere,
    so a pull of one of them can only fetch somebody else's image under a name
    that looks like ours. `if_not_present` is `missing` under another name and
    `always` pulls on every `up`. `build` pulls nothing but rebuilds the working
    tree on every `up`, present tag or not, so a `TAG` rollback would run the
    current code under the previous tag. `never` is the one value that neither
    pulls nor replaces an image the local store already holds (measured under
    Compose v5.3.1; compose.yaml's `api` service carries the table).
    """
    services = render(env_file, UNBUILT_PROFILE)["services"]
    building = {name for name, service in services.items() if service.get("build")}
    assert building == {"api", "worker", "migrate", "rebuild"}
    for name in sorted(building):
        assert services[name].get("pull_policy") == "never", (
            f"the {name} service builds its image but renders pull_policy="
            f"{services[name].get('pull_policy')!r}: anything but `never` either "
            "pulls a missing tag or rebuilds a present one on `up`"
        )


# --- A `$` in a password, through the parser that actually reads it ----------

# The form `.env.example` tells an operator to use for a value containing a `$`,
# and the literal that form has to deliver. Single quotes, because compose's
# dotenv reader strips a matching pair and expands nothing inside them - which
# is one rule rather than one decision per character.
DOLLAR_PASSWORD = "pa$w0rd"
DOLLAR_LINE = "PGPASSWORD='pa$w0rd'"


# `docker compose config` renders a configuration that is itself a compose file,
# so a literal `$` comes back out of it doubled. Proved without any env-file
# parsing in the way: a value handed to compose through the process environment,
# where nothing unescapes anything, renders with its `$` doubled too. Undo it
# before comparing, or this asserts about the renderer rather than the value.
def unescape(rendered: str) -> str:
    return rendered.replace("$$", "$")


def render_password(tmp_path, line: str) -> str:
    """The `POSTGRES_PASSWORD` the postgis container would be started with, from
    an otherwise untouched copy of `.env.example` with its PGPASSWORD replaced."""
    body = [
        line if original.startswith("PGPASSWORD=") else original
        for original in ENV_EXAMPLE.read_text().splitlines()
    ]
    assert line in body, "no PGPASSWORD line in .env.example to replace"
    destination = tmp_path / "env"
    destination.write_text("\n".join(body) + "\n")
    return unescape(render(destination)["services"]["postgis"]["environment"]["POSTGRES_PASSWORD"])


def test_the_quoting_this_file_prescribes_delivers_the_password_it_was_given(
    tmp_path,
) -> None:
    """The defect: `.env.example` described a rule for `$` that nobody had run.

    A password is the one value in that file where being off by a character is
    not a warning. `POSTGRES_PASSWORD` initialises PGDATA on the first `up`, and
    every later start ignores it - so a value that reached the container
    mangled, once, is the password the role now has, and the disagreement shows
    up as `pg_isready` green, migrate failing authentication, and api, worker
    and rebuild never starting.
    """
    assert render_password(tmp_path, DOLLAR_LINE) == DOLLAR_PASSWORD


def test_the_forms_that_file_warns_against_really_do_lose_the_dollar(
    tmp_path,
) -> None:
    """The other half, so the warning is not folklore.

    A bare `$` introduces a name compose expands - to nothing, with a warning
    nobody reads on a `docker compose up -d` - and double quotes do not stop
    it. If either of these ever started delivering the literal, the guidance
    above would be over-cautious rather than wrong, and this is where that
    would be noticed.
    """
    assert render_password(tmp_path, "PGPASSWORD=pa$w0rd") == "pa"
    assert render_password(tmp_path, 'PGPASSWORD="pa$w0rd"') == "pa"


def test_the_example_recommends_the_form_it_was_measured_to_need(tmp_path) -> None:
    """And says so in the file an operator is reading while they paste the
    value, rather than only in a test."""
    body = ENV_EXAMPLE.read_text()
    assert DOLLAR_LINE.replace("PGPASSWORD=", "") in body, (
        f"`.env.example` no longer shows {DOLLAR_LINE!r} as the form to use for a value "
        "containing a dollar sign"
    )
    assert "single quotes" in body
    assert "strips a matching pair" in " ".join(body.split()), (
        "`.env.example` no longer says compose's dotenv reader strips the quotes, which "
        "is what makes the single-quoted form above work - it used to claim the "
        "opposite, and the single-quoted form would be meaningless under that claim"
    )


def test_the_shipped_secrets_reach_the_containers_unaltered(rendered) -> None:
    """The example's own four `change-me` values, end to end.

    They are placeholders, and that is the point: whatever an operator replaces
    them with has to arrive the way it was written, and the way to notice that
    it does not is to check that the shipped ones do. A `$` slipped into any of
    them - by an editor, by a paste, by somebody making the placeholders look
    more like passwords - is a silent change to the value, and for PGPASSWORD a
    silent change to the password PGDATA is initialised with.
    """
    expected = dict(
        line.split("=", 1) for line in ENV_EXAMPLE.read_text().splitlines() if "=" in line
    )
    checked = 0
    for service, name, source in (
        ("postgis", "POSTGRES_PASSWORD", "PGPASSWORD"),
        ("api", "DJANGO_SECRET_KEY", "DJANGO_SECRET_KEY"),
        ("api", "KEY_ENCRYPTION_KEY", "KEY_ENCRYPTION_KEY"),
        ("api", "DISCORD_CLIENT_SECRET", "DISCORD_CLIENT_SECRET"),
    ):
        # An inherited variable beats the env file, and this suite runs with
        # `KEY_ENCRYPTION_KEY` set - `config.test_settings` refuses to import
        # without one. `render()` drops the `PG*` names for the same reason;
        # the rest are skipped here rather than made to depend on who is
        # running the tests. PGPASSWORD is the one this test is really about
        # and it is always checked.
        if source in os.environ and not source.startswith("PG"):
            continue
        assert unescape(environment(rendered, service)[name]) == expected[source], (
            f"{service}'s {name} is not the {source} line of .env.example verbatim"
        )
        checked += 1
    assert checked, "every secret was skipped; the environment this ran in set all of them"
