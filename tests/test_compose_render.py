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

# Scheme to the port a browser uses when the URL names none. A redirect URI is
# written without a port on a real deployment, and "no port" is a port.
DEFAULT_PORTS = {"http": 80, "https": 443}


def render(env_file: Path, *profiles: str) -> dict:
    """`docker compose config`, as JSON, with `env_file` standing in for `.env`.

    `--env-file` replaces compose's own default lookup, so a developer's `.env`
    sitting in the repository cannot change what this renders.
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
    finished = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=120)
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
