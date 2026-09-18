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
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

# The services that import Django settings and open a database connection.
DJANGO_SERVICES = ("api", "worker", "migrate", "rebuild")

# The services with no source in this repository, which therefore have no image
# anywhere and must not be in a default `up`. docs/DEPLOYMENT.md and
# handoff.md section 7 carry the same two names.
UNBUILT_PROFILE = "unbuilt"
UNBUILT_SERVICES = {"bot", "renderer"}

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
    present = UNBUILT_SERVICES & set(rendered["services"])
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
