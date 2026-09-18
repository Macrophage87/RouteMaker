"""Compose stack rules.

Asserted here as well as in CI so that a change to the stack fails in the same
suite as everything else, rather than only on push.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]


def limits(name: str) -> dict:
    return SERVICES[name].get("deploy", {}).get("resources", {}).get("limits", {})


def test_every_service_declares_both_limits() -> None:
    """A service with no memory limit can take PostGIS down with it, and a
    six-hour rebuild with no CPU limit saturates every core and destroys the
    preview latency target and the canary health check along with it.

    One test reporting every offending service, rather than three parametrised
    over thirteen services each. Twenty-six near-identical cases said nothing
    that this does not, and a stack that lost limits on four services reported
    four failures where one naming all four is what an operator needs.
    """
    missing = {
        name: sorted({"memory", "cpus"} - set(limits(name)))
        for name in sorted(SERVICES)
        if not {"memory", "cpus"} <= set(limits(name))
    }
    assert not missing, f"services missing limits: {missing}"


def test_only_the_edge_proxy_publishes_ports() -> None:
    """Photon, Valhalla, the renderer and the bot are reachable only from inside.
    The bot is the source of authorization truth and must never be addressable
    from outside the host."""
    published = sorted(
        name for name, service in SERVICES.items() if name != "caddy" and service.get("ports")
    )
    assert not published, f"services publishing ports: {published}"


def test_the_bot_alone_holds_the_bot_token() -> None:
    """A shared env_file would hand it to every container, which is exactly what
    the per-service scoping exists to prevent."""
    holders = [
        name
        for name, service in SERVICES.items()
        if "DISCORD_BOT_TOKEN" in (service.get("environment") or {})
    ]
    assert holders == ["bot"]


def key_encryption_key_holders() -> list[str]:
    return sorted(
        name
        for name, service in SERVICES.items()
        if "KEY_ENCRYPTION_KEY" in (service.get("environment") or {})
    )


def test_the_key_encryption_key_reaches_the_api_and_the_worker() -> None:
    """Both of them, and the pin matters: the ban tombstone's HMAC key is
    derived from this one, so a service that lost it would refuse to start
    rather than key tombstones with something else."""
    assert {"api", "worker"} <= set(key_encryption_key_holders())


def test_the_key_encryption_key_reaches_only_the_services_that_run_django() -> None:
    """Which is a wider set than it was, on purpose.

    `settings.TOMBSTONE_KEY` is derived from this key and has no default at all,
    so every process that imports Django settings needs it or fails at import -
    including `migrate` and the rebuild worker, neither of which computes a
    tombstone. That is the intended direction: a container that cannot key a
    tombstone should stop, not carry on with a key from the repository.

    What the scoping rule is actually protecting is asserted here rather than
    implied by an equality against two names: the bot, the edge proxy, the
    database and the routing containers never see it. The bot is the one that
    matters - it is the source of authorization truth and holds the token that
    reads every guild's roster.
    """
    assert key_encryption_key_holders() == ["api", "migrate", "rebuild", "worker"]
    for name in ("bot", "caddy", "postgis", "photon", "valhalla-standard"):
        assert "KEY_ENCRYPTION_KEY" not in (SERVICES[name].get("environment") or {}), name


def test_the_bootstrap_instance_admin_id_reaches_the_api_alone() -> None:
    """The admin is the only surface that reads it, and it is inert once the
    instance-admin list is non-empty."""
    holders = sorted(
        name
        for name, service in SERVICES.items()
        if "BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID" in (service.get("environment") or {})
    )
    assert holders == ["api"]


def test_no_service_uses_a_shared_env_file() -> None:
    """env_file hands the same secrets to every service that declares it, which
    is the failure mode the scoping rule exists for."""
    assert [name for name, s in SERVICES.items() if s.get("env_file")] == []


def test_one_valhalla_process_per_tile_variant() -> None:
    variants = sorted(n for n in SERVICES if n.startswith("valhalla-"))
    assert variants == ["valhalla-ebike", "valhalla-no-trail", "valhalla-standard"]


def _load_check_compose_limits():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_compose_limits", REPO / "scripts" / "check_compose_limits.py"
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


def test_the_swap_time_peak_fits_in_the_host() -> None:
    """The one rule the script adds that this file does not: the sum of the
    limits, including the duplicate Valhalla containers resident during a swap,
    has to stay under host RAM.

    Run in-process rather than as a subprocess. The script used to be shelled out
    to here, which re-ran the two limit checks above a fourth time and reported
    whatever it found as a single opaque return code.

    The path is passed explicitly (NIT 7): main()'s old default,
    `"compose.yaml"`, resolved against pytest's own working directory rather
    than the repository root, so a run from any other directory silently
    parsed a different file - or none - from the one this test's other
    assertions were written against.
    """
    script = _load_check_compose_limits()
    assert script.main(str(REPO / "compose.yaml")) == 0


def test_valhalla_worker_count_is_checked_against_its_own_limit(tmp_path) -> None:
    """PLAN: "the CI compose check asserts the worker count against the limit
    rather than merely asserting that a limit exists." A worker count raised
    from 2 to 64 at the same 2 GB limit is exactly the mutation that survived
    the round-3 panel, and it must fail here, not just the weak `>= 2` floor
    tests/test_valhalla_config.py used to carry alone.
    """
    script = _load_check_compose_limits()

    mutated = yaml.safe_load((REPO / "compose.yaml").read_text())
    mutated["services"]["valhalla-standard"]["command"][2] = "64"
    mutated_path = tmp_path / "compose.yaml"
    mutated_path.write_text(yaml.safe_dump(mutated))

    assert script.main(str(mutated_path)) == 1, "64 workers at a 2 GB, 2-cpu limit must be refused"


def test_the_worker_starts_through_django() -> None:
    """`procrastinate --app=... worker` never set Django up: it died on the
    missing schema, and past that every task raised AppRegistryNotReady. The
    process has to be the management command, whose schema comes from the same
    migrate one-shot as every other table."""
    for name in ("worker", "rebuild"):
        command = SERVICES[name]["command"]
        assert command[:3] == ["./manage.py", "procrastinate", "worker"], name
        assert SERVICES[name]["depends_on"]["migrate"] == {
            "condition": "service_completed_successfully"
        }, f"{name} must not start before the schema exists"
    assert SERVICES["api"]["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }


def test_the_rebuild_queue_is_consumed_only_by_the_container_with_the_binaries() -> None:
    """The queue split is load-bearing: the rebuild service is the one with the
    Valhalla and GDAL binaries, the data mounts and the 8G limit, so it is the
    only worker on the rebuild queue - and the api-image worker, which has
    none of those, never picks a rebuild up."""

    def queues(name: str) -> set[str]:
        for argument in SERVICES[name]["command"]:
            if argument.startswith("--queues="):
                return set(argument.removeprefix("--queues=").split(","))
        raise AssertionError(f"{name} listens on every queue")

    assert queues("rebuild") == {"rebuild"}
    assert "rebuild" not in queues("worker")
    assert "maintenance" in queues("worker")
    assert SERVICES["rebuild"]["image"] != SERVICES["worker"]["image"]
    assert SERVICES["rebuild"]["restart"] == "unless-stopped", "a resident worker, not a one-shot"


def test_the_maintenance_worker_has_more_than_one_slot() -> None:
    """Every periodic task except the rebuild queues on the maintenance worker,
    and Procrastinate drops a periodic tick whose predecessor is still running
    rather than delaying it. With the default of one slot a nightly dump held
    the queue, and the 5-minute degraded sweep and the 10-minute worker
    heartbeat silently missed their ticks - the bound docs/OPERATIONS.md
    describes could not be met by any change inside the tasks."""
    assert "--concurrency=4" in SERVICES["worker"]["command"]
    assert "--concurrency=1" in SERVICES["rebuild"]["command"], (
        "the rebuild stays single-slot: two rebuilds at once would share a data volume"
    )


def test_the_rebuild_sees_the_whole_data_volume_at_the_path_its_settings_assume() -> None:
    volumes = SERVICES["rebuild"]["volumes"]
    assert "${DATA_ROOT}:/data" in volumes
    assert SERVICES["rebuild"]["environment"]["DATA_ROOT"] == "/data"
    assert "./lua:/conf/lua:ro" in volumes and "./valhalla:/conf:ro" in volumes


def test_the_backup_lands_on_the_data_volume() -> None:
    assert "${DATA_ROOT}/backups:/data/backups" in SERVICES["worker"]["volumes"]


# --- What settings.py reads, against what compose delivers -----------------------------

SETTINGS_SOURCE = REPO / "src" / "config" / "settings.py"

# Every environment lookup in the settings module, derived from the source
# rather than restated here. A list written out by hand is a list that stops
# matching the module the day somebody adds a lookup, which is exactly how six
# declared variables came to stand against twenty-four read ones.
#
# Parsed rather than matched. The regex this replaces required a literal `(`
# after `os.environ`, so it saw `os.environ.get("X")` and nothing else:
# `os.environ["X"]` - the bracket form, which is the one with no default and so
# the one that hard-fails a container that is missing the variable - was
# invisible to it, as were `os.getenv("X")` and every `from os import environ`
# form. Two undeclared reads in those shapes left this file passing, which made
# the claim below false in exactly the direction that matters.
# The attribute names, which an alias cannot change: `os.environ` is
# `os.environ` however `os` itself was imported, so `import os as operating_system`
# needs nothing special here.
ENVIRON_ATTRIBUTES = frozenset({"environ"})
GETENV_ATTRIBUTES = frozenset({"getenv"})


def bare_os_names(tree: ast.AST) -> tuple[frozenset[str], frozenset[str]]:
    """The local names this module binds `os.environ` and `os.getenv` to.

    Resolved from the module's own imports rather than assumed. The version this
    replaces hard-coded `frozenset({"environ"})`, which reads
    `from os import environ` and nothing else: `from os import environ as E`
    binds the same object to a different name, `E["DJANGO_SECRET_KEY"]` is the
    same undeclared read as `os.environ["DJANGO_SECRET_KEY"]`, and this file saw
    none of it. The whole point of deriving the list from the source is that it
    keeps holding when somebody writes the lookup a way nobody predicted, so a
    derivation that only understands one spelling of the import is the same
    defect the regex was.

    A bare name with no import behind it binds nothing and is not collected: a
    module-level `environ = {...}` is a dictionary, not the environment.
    """
    environ: set[str] = set()
    getenv: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "os" and not node.level:
            for alias in node.names:
                bound = alias.asname or alias.name
                if alias.name in ENVIRON_ATTRIBUTES:
                    environ.add(bound)
                elif alias.name in GETENV_ATTRIBUTES:
                    getenv.add(bound)
    return frozenset(environ), frozenset(getenv)


def _is_environ(node: ast.AST, bare: frozenset[str]) -> bool:
    """`<os>.environ`, or whatever name `from os import environ [as ...]` bound."""
    if isinstance(node, ast.Attribute):
        return node.attr in ENVIRON_ATTRIBUTES
    return isinstance(node, ast.Name) and node.id in bare


def _is_getenv(node: ast.AST, bare: frozenset[str]) -> bool:
    """`<os>.getenv`, or whatever name `from os import getenv [as ...]` bound."""
    if isinstance(node, ast.Attribute):
        return node.attr in GETENV_ATTRIBUTES
    return isinstance(node, ast.Name) and node.id in bare


def _literal_key(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def environment_names_in(source: str) -> set[str]:
    """The string key of every environment read in `source`.

    Covered: `environ["X"]`, `environ.get("X")`, `environ.setdefault("X", ...)`
    and `getenv("X")`, each whether reached through `os.`, through an alias of
    `os`, or imported bare under its own name or an alias of it. A lookup whose
    key is not a literal string is not collected - there is none in settings.py,
    and one would have to be declared by hand anyway.
    """
    tree = ast.parse(source)
    bare_environ, bare_getenv = bare_os_names(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_environ(node.value, bare_environ):
            if (key := _literal_key(node.slice)) is not None:
                names.add(key)
        elif isinstance(node, ast.Call) and node.args:
            function = node.func
            reads_environment = _is_getenv(function, bare_getenv) or (
                isinstance(function, ast.Attribute)
                and function.attr in ("get", "setdefault")
                and _is_environ(function.value, bare_environ)
            )
            if reads_environment and (key := _literal_key(node.args[0])) is not None:
                names.add(key)
    return names


# The names settings.py reads that the `api` service deliberately does not
# declare, each with the services that do - or None where nothing in the stack
# delivers it, because nothing in the stack should.
#
# This is the one escape hatch, and it is deliberately narrow: anything not
# named here must reach the api, so a new `os.environ.get("NEW_THING")` in
# settings.py fails this file until compose carries it or until somebody writes
# down here why it should not.
NOT_DELIVERED_TO_THE_API: dict[str, tuple[str, ...] | None] = {
    # Test isolation only. Two concurrent runs on one host would otherwise reach
    # into each other's `live` and `staging`; a deployment uses the defaults and
    # the swap renames them, so a container that could override them would be a
    # way to point one deployment's API at another's tables.
    "ROUTEMAKER_LIVE_SCHEMA": None,
    "ROUTEMAKER_STAGING_SCHEMA": None,
    # The data volume, inside the containers that mount it. The api mounts none:
    # it serves requests and writes nothing durable, and a DATA_ROOT on it would
    # name a path that does not exist in that container. Note that the
    # `${DATA_ROOT}` in every volume mapping is the *host* path, read from the
    # deployment's environment file by compose itself, not by a container.
    "DATA_ROOT": ("rebuild", "worker"),
    # The rebuild's disk gate, read by the rebuild alone.
    "REBUILD_MIN_FREE_BYTES": ("rebuild",),
    # The source extract the rebuild downloads, merges and clips for itself
    # (pipeline.source). Read at FETCH_EXTRACT and nowhere the api runs.
    "SOURCE_EXTRACT_URLS": ("rebuild",),
    "SOURCE_EXTRACT_MAX_AGE_DAYS": ("rebuild",),
    "SOURCE_EXTRACT_FORCE_REFRESH": ("rebuild",),
    "COVERAGE_POLYGON": ("rebuild",),
    # The admin map widget's optional tile template. Read by the api - the admin
    # is the only surface that renders a map - and delivered by nothing, because
    # phase 1 has nothing to deliver: the PMTiles extract and the renderer are
    # unbuilt, so there is no self-hosted basemap to point it at and no public
    # one it is allowed to point at (PLAN:15). Unset, the widget draws the
    # polygon over a plain background and requests no tiles, which is the
    # shipped configuration rather than a degraded one.
    #
    # It is parked here rather than declared on the api because a declared
    # `${ADMIN_BASEMAP_TILE_URL}` with no compose-side default would make
    # .env.example owe it a value, and the value it owes does not exist yet.
    # When the renderer lands, this entry comes out and the api declares it with
    # an empty default - and until then a deployment that has its own tiles
    # reaches the container the same way any other unlisted variable does.
    "ADMIN_BASEMAP_TILE_URL": None,
}


def environment_names_read_by_settings() -> set[str]:
    return environment_names_in(SETTINGS_SOURCE.read_text())


def declared_by(service: str) -> set[str]:
    return set(SERVICES[service].get("environment") or {})


def test_the_derivation_finds_the_lookups_settings_actually_has() -> None:
    """The derivation is the load-bearing part of the test below, so it is
    checked against a handful of names that are certainly in the module - one
    from each shape of lookup, including the bracket form that has no default.
    A derivation that silently found nothing would make the next test vacuous."""
    names = environment_names_read_by_settings()
    assert {
        "DJANGO_SECRET_KEY",  # os.environ.get with a string default
        "DATA_ROOT",  # os.environ.get with a non-string default
        "BOOTSTRAP_INSTANCE_ADMIN_DISCORD_ID",  # os.environ[...] and os.environ.get
        "DISCORD_CLIENT_ID",
        "KEY_ENCRYPTION_KEY",
    } <= names
    assert len(names) >= 20, f"the lookups stopped being found: {sorted(names)}"


@pytest.mark.parametrize(
    "source",
    [
        'X = os.environ["SHAPE_UNDER_TEST"]',
        'X = os.environ.get("SHAPE_UNDER_TEST", "")',
        'X = os.getenv("SHAPE_UNDER_TEST")',
        'from os import environ\nX = environ["SHAPE_UNDER_TEST"]',
        'from os import environ\nX = environ.get("SHAPE_UNDER_TEST", "")',
        'from os import getenv\nX = getenv("SHAPE_UNDER_TEST", "")',
        # The aliased shapes. `from os import environ as E` binds the same
        # object to a name the hard-coded list could not know, and the lookup
        # through it is the same undeclared read.
        'from os import environ as E\nX = E["SHAPE_UNDER_TEST"]',
        'from os import environ as E\nX = E.get("SHAPE_UNDER_TEST", "")',
        'from os import environ as E\nX = E.setdefault("SHAPE_UNDER_TEST", "")',
        'from os import getenv as read_env\nX = read_env("SHAPE_UNDER_TEST")',
        # And an alias of the module, which needs nothing special because the
        # attribute is still spelled `environ` - asserted so that a future
        # rewrite that starts resolving module names keeps covering it.
        'import os as operating_system\nX = operating_system.environ["SHAPE_UNDER_TEST"]',
        'X = int(os.environ.get("SHAPE_UNDER_TEST", "1"))',
        'X = [h for h in os.getenv("SHAPE_UNDER_TEST", "").split(",") if h]',
    ],
)
def test_every_shape_of_lookup_is_seen(source: str) -> None:
    """The shapes the regex missed, each on its own, so a derivation that
    regresses to matching one syntax says which one it stopped seeing. The
    bracket form is the important one: it has no default, so a container missing
    that variable does not start at all."""
    assert "SHAPE_UNDER_TEST" in environment_names_in(source)


def test_the_api_declares_every_setting_it_reads_from_the_environment() -> None:
    """The stack has to deliver the settings the running code reads.

    It did not, and the sign-in path is where that showed. Six variables were
    declared against the twenty-four settings.py reads, so under the stack as
    written ALLOWED_HOSTS was the module's `["localhost"]` default and every
    request arriving through Caddy was a DisallowedHost 400; the authorize URL
    carried `client_id=` empty and a `localhost:8000` redirect; and the database
    host was 127.0.0.1, which inside that container is that container. PLAN:299
    puts "Discord login with the identify scope" in phase 1, and none of it
    could work.

    Derived from the module's source, so this keeps holding: a lookup added to
    settings.py fails here until compose carries it.
    """
    undeclared = sorted(
        name
        for name in environment_names_read_by_settings() - declared_by("api")
        if name not in NOT_DELIVERED_TO_THE_API
    )
    assert not undeclared, (
        f"settings.py reads these and the api service declares none of them: {undeclared}"
    )


def test_the_names_the_api_skips_reach_the_services_that_do_read_them() -> None:
    """The allow-list above is an exemption from the api, not from the stack. A
    name parked in it and delivered nowhere would be the same defect one
    dictionary further away."""
    missing = {
        name: [s for s in services if name not in declared_by(s)]
        for name, services in NOT_DELIVERED_TO_THE_API.items()
        if services
    }
    assert not any(missing.values()), f"allow-listed but not delivered either: {missing}"


def test_every_django_service_can_reach_the_database() -> None:
    """The four services that import Django settings all open a connection, and
    settings.py's own defaults for the host are wrong inside a container:
    127.0.0.1 is the container itself, not the postgis service."""
    for name in ("api", "worker", "migrate", "rebuild"):
        declared = declared_by(name)
        assert {"PGHOST", "PGUSER", "PGDATABASE", "PGPASSWORD"} <= declared, name
        assert SERVICES[name]["environment"]["PGHOST"] != "127.0.0.1", name


def test_the_discord_client_id_and_redirect_reach_the_api() -> None:
    """Neither is a secret - both are in the authorize URL the browser follows -
    and neither has a usable default: the client id defaults to the empty string
    and the redirect to localhost, so a stack without them has a login button
    that goes to an application Discord does not know."""
    environment = SERVICES["api"]["environment"]
    assert environment["DISCORD_CLIENT_ID"] == "${DISCORD_CLIENT_ID}"
    assert environment["DISCORD_REDIRECT_URI"] == "${DISCORD_REDIRECT_URI}"
    assert "localhost" not in environment["DISCORD_REDIRECT_URI"], (
        "a compose default here would ship a redirect to the developer's own machine"
    )


def test_the_client_secret_still_reaches_the_api_alone() -> None:
    """The scoping rule survives the widening: the id and the redirect are
    public, the secret is not, and only the service that exchanges an
    authorization code sees it."""
    holders = sorted(
        name
        for name, service in SERVICES.items()
        if "DISCORD_CLIENT_SECRET" in (service.get("environment") or {})
    )
    assert holders == ["api"]


def test_the_env_example_lists_every_name_the_stack_expects_from_it() -> None:
    """`.env.example` is what an operator fills in, so a variable compose
    interpolates and the example never names is one the first deployment leaves
    empty. Only the names with no compose-side default are required here - the
    rest fall back to a value that works."""
    example = {
        line.split("=", 1)[0].strip()
        for line in (REPO / ".env.example").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    required = set()
    for service in SERVICES.values():
        for value in (service.get("environment") or {}).values():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                inner = value[2:-1]
                if ":-" not in inner and ":?" not in inner:
                    required.add(inner)
    assert required <= example, (
        f"compose requires these and .env.example omits them: {sorted(required - example)}"
    )
