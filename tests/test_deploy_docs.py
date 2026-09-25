"""The runbook, held to the stack it describes.

Cheap tests, and the round-6 review is the argument for them: the two defects
below were both a document that had drifted from `compose.yaml` in a way no
reader could see, and a wrong runbook is not a documentation problem when it is
the only description of a procedure nobody has executed.

- `docs/OPERATIONS.md` told an operator to roll a rebuild back with
  `docker compose exec -T api`. The `api` service then mounted no part of the
  data volume, so `rollback_rebuild` there found no `previous` link and
  refused as if the deployment had never rebuilt. Since wave 8 it binds the
  tiles read-only, and the command refuses there on a write probe instead
  (round 10) - either way, `rebuild` is where it runs.
- The `chown -R` in `docs/DEPLOYMENT.md` ran before the first `up`, and Docker
  creates a missing bind-mount source as a root-owned directory, so it chowned
  a tree that did not yet contain the directories the problem is about. The fix
  is a script, and the thing worth testing about a list of directories is that
  it has not fallen behind the mounts it was derived from - so the list is
  checked against `compose.yaml`'s own mappings rather than restated here.

What these tests may assert about a document, since round 10 found two of
them defending sentences the code had made false: a command's argv (which
service it runs in, which flags it passes, the order the commands come in), a
value the document quotes that is read here from where it is configured, a
path or a route that has to exist, and that a section is there at all. Never a
phrase. A test that pins wording holds the guide to the state it was in when
the test was written; when the code moves, it fails the correction rather than
the defect.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]

OPERATIONS = (REPO / "docs" / "OPERATIONS.md").read_text()
DEPLOYMENT = (REPO / "docs" / "DEPLOYMENT.md").read_text()
DEVELOPMENT = (REPO / "docs" / "DEVELOPMENT.md").read_text()
DOCUMENTS = {
    "docs/OPERATIONS.md": OPERATIONS,
    "docs/DEPLOYMENT.md": DEPLOYMENT,
    "docs/DEVELOPMENT.md": DEVELOPMENT,
}
# Every guide, for the checks that hold for any command an operator is shown:
# the playbook and the acceptance notes run the same commands as the three above.
ALL_DOCUMENTS = {
    f"docs/{path.name}": path.read_text() for path in sorted((REPO / "docs").glob("*.md"))
}
PREPARE = REPO / "scripts" / "prepare_data_root.sh"

# `docker compose exec [-flags] <service> ...`, which is the shape every
# invocation in these documents takes.
EXEC = re.compile(r"docker compose exec\s+((?:-\S+\s+)*)(\S+)\s+([^\n`]*)")

# The services that can run a management command against the data volume at all:
# `rebuild` binds the five directories it writes under /data, `worker` binds the
# backups directory there. The api binds `static` and, read-only, `tiles`, and
# is not one of them.
DATA_SERVICES = {"rebuild", "worker"}


def documented_exec_invocations(text: str) -> list[tuple[str, str]]:
    """(service, command line) for every `docker compose exec` in a document."""
    return [(match.group(2), match.group(3).strip()) for match in EXEC.finditer(text)]


def test_the_services_this_file_reasons_about_still_mount_what_it_says() -> None:
    """The premise of everything below, asserted rather than assumed.

    `rebuild` writes the five directories under `/data`. `api` holds two of
    them and neither makes it a place to run a data command: `static`, which is
    the `collectstatic` target, and `tiles` **read-only**, which exists for the
    operations page's `statvfs`. A stack that gave the api `extracts` or
    `reference` would make the table of which command runs where wrong rather
    than failing.
    """
    rebuild_volumes = SERVICES["rebuild"]["volumes"]
    assert "${DATA_ROOT}/tiles:/data/tiles" in rebuild_volumes
    assert "${DATA_ROOT}/reference:/data/reference" in rebuild_volumes
    assert SERVICES["rebuild"]["environment"]["DATA_ROOT"] == "/data"
    api_volumes = set(SERVICES["api"].get("volumes") or [])
    assert api_volumes == {
        "${DATA_ROOT}/static:/data/static",
        "${DATA_ROOT}/tiles:/data/tiles:ro",
    }, (
        f"the api mounts {sorted(api_volumes)}; docs/DEPLOYMENT.md's table of what it "
        "binds, and the rule about where data commands run, both follow from this set"
    )
    assert SERVICES["api"]["environment"]["DATA_ROOT"] == "/data", (
        "the api binds /data/static and /data/tiles but does not set DATA_ROOT, so "
        "settings.STATIC_ROOT and settings.TILES_DIR are under /app/data and neither "
        "mount is reached by anything"
    )


@pytest.mark.parametrize("service", ["api", "worker"])
def test_the_tiles_are_bound_read_only_into_the_services_that_only_measure_them(
    service: str,
) -> None:
    """The free-space figure, on both surfaces that carry it.

    `core.operations` reports the room left for the next rebuild as a `statvfs`
    on `settings.TILES_DIR`. The operations page runs that in `api`; the
    `check_operations` cron entry runs it in `worker`. Neither mounted the
    tiles, so both resolved `/data/tiles` (or `/app/data/tiles`) to a path that
    does not exist, `statvfs` walked up to the nearest one that does, and the
    figure reported was the container's own writable layer - a positive
    statement about a filesystem the process could not see.

    Read-only, because measuring is all either of them does: the build
    directories and the `current` symlinks under it belong to `rebuild`.
    """
    volumes = SERVICES[service]["volumes"]
    assert "${DATA_ROOT}/tiles:/data/tiles:ro" in volumes, (
        f"the {service} service binds {volumes}; without the tiles it reports the room "
        "left on its own layer as the room left for a rebuild"
    )
    assert SERVICES[service]["environment"]["DATA_ROOT"] == "/data", (
        f"the {service} service mounts the tiles at /data/tiles but DATA_ROOT does not "
        "point there, so settings.TILES_DIR is somewhere else"
    )


def test_the_free_space_check_is_documented_against_the_container_that_runs_it() -> None:
    """The cron entry, `docs/DEPLOYMENT.md`'s table and the mount are three
    statements of one decision, and the review before this one found them two
    versions apart."""
    rows = [line for line in DEPLOYMENT.splitlines() if line.startswith("| `check_operations`")]
    assert len(rows) == 1, f"expected one check_operations row, found {len(rows)}"
    documented = rows[0].split("|")[2].strip().strip("`")
    cron = [
        line
        for line in OPERATIONS.splitlines()
        if "check_operations" in line and "docker compose exec" in line
    ]
    assert cron, "docs/OPERATIONS.md no longer shows check_operations as a compose exec"
    for line in cron:
        service = documented_exec_invocations(line)[0][0]
        assert service == documented, (
            f"docs/DEPLOYMENT.md says check_operations runs in {documented!r} and "
            f"docs/OPERATIONS.md runs it in {service!r}"
        )
    assert "${DATA_ROOT}/tiles:/data/tiles:ro" in SERVICES[documented]["volumes"], (
        f"check_operations is documented against {documented!r}, which does not mount "
        "the tiles its free-space check measures"
    )


@pytest.mark.parametrize("service", ["rebuild", "worker"])
def test_both_procrastinate_workers_get_longer_than_the_ten_second_default(
    service: str,
) -> None:
    """A SIGKILLed worker leaves whatever it was running `doing` for ever, and
    the repair is a hand-run `unwedge_job`.

    Compose's default is ten seconds between the SIGTERM and the SIGKILL, and
    what a Procrastinate worker owes the database on the way out is a real
    shutdown: it cancels its side tasks and then calls `unregister_worker`,
    which is a round trip. Neither value saves a *running* job - nothing does,
    since `shutdown_graceful_timeout` is unset and the wait is unbounded - so
    what the grace period buys is that the idle case, which is almost every
    `down` and `up -d`, is a clean unregister rather than a race.

    `rebuild` had one and `worker` did not, and the difference was never a
    decision: a nightly dump or a sweep killed at second ten leaves exactly the
    same wedged row a killed rebuild does.
    """
    grace = SERVICES[service].get("stop_grace_period")
    assert grace, (
        f"the {service} service declares no stop_grace_period, so compose kills its "
        "Procrastinate worker ten seconds after the SIGTERM"
    )
    assert grace == "60s", f"the {service} service's grace period is {grace!r}, not 60s"


def test_the_api_declares_a_healthcheck_the_image_can_actually_run() -> None:
    """`/healthz`, probed with the interpreter gunicorn already runs under.

    Two things make this more than a line of YAML. The runtime stage of
    `docker/api.Dockerfile` installs no `curl` in the image that runs, so a
    `CMD curl ...` healthcheck is a check that reports unhealthy on a healthy
    container. And Django refuses a request whose `Host` is not in
    `ALLOWED_HOSTS` with a 400, so a probe of `http://127.0.0.1:8000/` on a
    deployment whose `DJANGO_ALLOWED_HOSTS` is its public name is red for ever
    - which is why the check sends the first name out of that variable.
    """
    check = SERVICES["api"].get("healthcheck")
    assert check, "the api service declares no healthcheck"
    test = check["test"]
    assert test[0] == "CMD", f"the healthcheck is {test!r}; CMD runs it without a shell"
    assert test[1] == "python", (
        f"the healthcheck runs {test[1]!r}; the api image's runtime stage installs no "
        "curl, and python is the interpreter gunicorn is already running under"
    )
    body = test[-1]
    assert "/healthz" in body, f"the healthcheck does not probe /healthz: {body!r}"
    assert "DJANGO_ALLOWED_HOSTS" in body, (
        "the healthcheck sends no Host header derived from DJANGO_ALLOWED_HOSTS, so on "
        "a deployment with a real hostname every probe is a DisallowedHost 400"
    )
    assert "urllib" in body, f"the healthcheck does not use urllib: {body!r}"
    port = re.search(r"127\.0\.0\.1:(\d+)", body)
    assert port, f"the healthcheck names no loopback port: {body!r}"
    entrypoint = (REPO / "docker" / "api-entrypoint.sh").read_text()
    assert f"0.0.0.0:{port.group(1)}" in entrypoint, (
        f"the healthcheck probes port {port.group(1)} and the entrypoint binds gunicorn "
        "somewhere else"
    )
    # `depends_on` is either a mapping of conditions or a plain list of names.
    gated = [
        name
        for name, service in SERVICES.items()
        if isinstance(service.get("depends_on"), dict)
        and service["depends_on"].get("api", {}).get("condition") == "service_healthy"
    ]
    assert not gated, (
        f"{gated} now wait on the api being healthy; this check is a `docker compose ps` "
        "an operator reads, not a condition the stack refuses to come up without - and "
        "a /healthz that 404s on a release that has not added the view yet would then "
        "hold the whole stack down"
    )


@pytest.mark.parametrize("command", ["rollback_rebuild", "run_rebuild_now"])
def test_the_data_volume_commands_are_documented_against_a_container_that_has_one(
    command: str,
) -> None:
    """Both of these resolve paths under `settings.DATA_ROOT`, so the container
    is part of the instruction and not an incidental detail of how it was
    written down."""
    invocations = [
        (service, line)
        for service, line in documented_exec_invocations(OPERATIONS)
        if command in line
    ]
    assert invocations, f"docs/OPERATIONS.md no longer documents how to run {command}"
    wrong = [(service, line) for service, line in invocations if service not in DATA_SERVICES]
    assert not wrong, (
        f"{command} is documented against a service with no data mount: {wrong}. "
        f"It has to run in one of {sorted(DATA_SERVICES)}"
    )


def test_the_rollback_procedure_shows_the_dry_run_and_the_confirm_where_they_can_run() -> None:
    """The command an operator reaches for at three in the morning after a bad
    promotion, and the dry run and the `--confirm` are two separate commands
    that both have to be right: both shown, and both in a service whose tiles
    bind is read-write in the rendered configuration. That service used to be
    written into this test by name."""
    invocations = [
        (service, line.split())
        for service, line in documented_exec_invocations(
            section(OPERATIONS, "## Rolling back a rebuild")
        )
        if "rollback_rebuild" in line.split()
    ]
    confirms = [argv for _service, argv in invocations if "--confirm" in argv]
    dry_runs = [argv for _service, argv in invocations if "--confirm" not in argv]
    assert confirms and dry_runs, (
        f"the rollback section does not show both the dry run and the --confirm: {invocations}"
    )
    binds = rendered_tiles_binds()
    wrong = [(service, argv) for service, argv in invocations if binds.get(service) is not False]
    assert not wrong, (
        f"the rollback is documented in a service that cannot write the tile links it moves: "
        f"{wrong}; the tiles binds are {binds}"
    )


def rendered_tiles_binds() -> dict[str, bool]:
    """Service -> read-only, for every service whose `settings.TILES_DIR` is a
    bind of `${DATA_ROOT}/tiles`, in the configuration compose renders from the
    shipped `.env.example`.

    `TILES_DIR` is `DATA_ROOT / "tiles"`, so the target is derived from each
    service's own rendered `DATA_ROOT` rather than written out here.
    """
    import tempfile

    from test_compose_render import ENV_EXAMPLE, data_root, render

    with tempfile.TemporaryDirectory() as tmp:
        env_file = Path(tmp) / "env"
        env_file.write_text(ENV_EXAMPLE.read_text())
        rendered = render(env_file)
        source = f"{data_root(env_file)}/tiles"
    binds: dict[str, bool] = {}
    for name, service in rendered["services"].items():
        root = (service.get("environment") or {}).get("DATA_ROOT")
        if not root:
            continue
        for volume in service.get("volumes", []):
            if volume.get("source") == source and volume.get("target") == f"{root}/tiles":
                binds[name] = bool(volume.get("read_only"))
    return binds


def test_rollback_rebuild_is_documented_where_the_tiles_are_writable() -> None:
    """The rollback rewrites the promotion links under `TILES_DIR`, so the
    container both guides name for it has to bind that directory read-write -
    read off the rendered configuration, not off a sentence about it. This
    replaces a test that pinned "mounts no part of the data volume", which
    wave 8 made false and which went on defending the sentence for two rounds.

    And the other half of the property: a service that binds the tiles
    read-only exists (`api`, for its free-space line), which is why the
    command's write probe is what an operator meets there rather than a
    rollback that stops halfway.
    """
    binds = rendered_tiles_binds()
    writable = {name for name, read_only in binds.items() if not read_only}
    assert writable, f"no service binds the tiles read-write: {binds}"
    assert binds.get("api") is True, f"the api's tiles bind is not read-only: {binds}"

    documented = {
        service
        for document in (OPERATIONS, DEPLOYMENT)
        for service, line in documented_exec_invocations(document)
        if "rollback_rebuild" in line
    }
    assert documented, "neither guide shows how to run rollback_rebuild"
    rows = [line for line in DEPLOYMENT.splitlines() if line.startswith("| `rollback_rebuild`")]
    assert len(rows) == 1, f"expected one rollback_rebuild row in the table, found {len(rows)}"
    documented.add(rows[0].split("|")[2].strip().strip("`"))
    assert documented <= writable, (
        f"rollback_rebuild is documented in {sorted(documented - writable)}, which cannot "
        f"write the tiles; the services that can are {sorted(writable)}"
    )


def where_commands_run() -> dict[str, str]:
    """docs/DEPLOYMENT.md's table of which command runs in which container, as
    command -> service."""
    lines = DEPLOYMENT.splitlines()
    header = next(
        (i for i, line in enumerate(lines) if line.startswith("| Command | Container |")), None
    )
    assert header is not None, "docs/DEPLOYMENT.md has no table of where each command runs"
    rows = {}
    for line in lines[header + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip().strip("`") for cell in line.split("|")[1:3]]
        rows[cells[0]] = cells[1]
    return rows


def test_the_table_of_where_commands_run_names_real_commands_and_real_services() -> None:
    """Each row is a command an operator will type and a container they will
    type it into, so both halves have to exist: a management command Django
    loads or a script in the repository, and a service in `compose.yaml` that
    runs this project's own code. This replaces a check that three command
    names appeared somewhere in the document."""
    from django.core.management import get_commands

    rows = where_commands_run()
    assert rows, "the table of where each command runs is empty"
    commands = get_commands()
    ours = {name for name, service in SERVICES.items() if "build" in service}
    for command, service in rows.items():
        assert command in commands or (REPO / "scripts" / command).is_file(), (
            f"the table names {command!r}, which is neither a management command nor a "
            "script in scripts/"
        )
        assert service in ours, (
            f"the table runs {command} in {service!r}, which is not one of the services "
            f"built from this repository: {sorted(ours)}"
        )


def test_a_half_restored_swap_has_a_repair_run_where_the_tiles_are_writable() -> None:
    """`SwapUndoIncomplete` is terminal and `rollback_rebuild` refuses on the
    state it leaves, so the runbook's section for it is the only repair there
    is. Its presence, and that every command in it runs in a container that
    can write the tile links it puts back."""
    sections = [
        chunk
        for chunk in OPERATIONS.split("\n## ")[1:]
        if "SwapUndoIncomplete" in chunk.splitlines()[0]
    ]
    assert len(sections) == 1, "docs/OPERATIONS.md has no section for a SwapUndoIncomplete alert"
    invocations = documented_exec_invocations(sections[0])
    assert invocations, "the section names no command to run"
    binds = rendered_tiles_binds()
    wrong = [(service, line) for service, line in invocations if binds.get(service) is not False]
    assert not wrong, f"these run where the tiles cannot be written: {wrong}"
    # The swap's own undo deletes a row the swap created, so the hand repair
    # has both halves too: an update for a row that existed, a delete for one
    # that did not.
    row_repairs = [line for _service, line in invocations if "ValhallaUpstream" in line]
    for operation in (".update(", ".delete()"):
        assert any(operation in line for line in row_repairs), (
            f"no command in the section repairs a settings row with {operation}: {row_repairs}"
        )


# --- The data-root directories, derived from the mounts ----------------------


def data_root_mount_paths() -> set[str]:
    """Every host path under `${DATA_ROOT}` that a compose service binds,
    relative to `${DATA_ROOT}` - which is exactly the set Docker would otherwise
    create as root on the first `up`.

    The bare `${DATA_ROOT}` mapping on the rebuild is excluded: it is the volume
    itself, which the script creates first and chowns whole.
    """
    prefix = "${DATA_ROOT}"
    paths = set()
    for service in SERVICES.values():
        for volume in service.get("volumes") or []:
            source = volume.split(":", 1)[0]
            if source.startswith(prefix + "/"):
                paths.add(source[len(prefix) + 1 :])
    return paths


def prepared_directories() -> set[str]:
    """The DIRECTORIES list in scripts/prepare_data_root.sh."""
    body = PREPARE.read_text()
    listed = re.search(r'DIRECTORIES="\n(.*?)\n"', body, re.DOTALL)
    assert listed, "scripts/prepare_data_root.sh no longer declares a DIRECTORIES list"
    return {line.strip() for line in listed.group(1).splitlines() if line.strip()}


def test_the_premise_is_not_vacuous() -> None:
    """A derivation that found nothing would make the test below pass on an
    empty script. Three of these are the ones that actually broke."""
    paths = data_root_mount_paths()
    assert {"backups", "static", "elevation", "tiles/standard/current"} <= paths, (
        f"the mappings stopped being found: {sorted(paths)}"
    )


def test_the_prepare_script_creates_every_directory_compose_binds() -> None:
    """Derived from `compose.yaml`, so a mount added to the stack fails here
    until the script covers it. That is the whole point of not writing the list
    out twice: the defect was a directory nobody thought about until a container
    could not write it."""
    missing = sorted(data_root_mount_paths() - prepared_directories())
    assert not missing, (
        f"compose binds these under ${{DATA_ROOT}} and scripts/prepare_data_root.sh does "
        f"not create them, so Docker will create them as root on the first up: {missing}"
    )


def test_the_script_also_creates_what_the_rebuild_writes() -> None:
    """Named in settings - REBUILD_SOURCE_PBF, REBUILD_REFERENCE_DIR and
    REBUILD_WORK_DIR - and bound by the rebuild service, so the derivation above
    sees them too. Stated separately anyway: they are the three the script
    carried before the rebuild's mount was narrowed to name them, and a mount
    list that lost one would otherwise take this list with it."""
    assert {"extracts", "reference", "rebuild"} <= prepared_directories()


# --- Who owns what under ${DATA_ROOT} -----------------------------------------

# The services that run this project's own images, which run as uid 10001.
OUR_SERVICES = {"api", "worker", "migrate", "rebuild"}

# ...and the one directory they write that no such service binds: `static` is
# bound read-only into Caddy, and written by the `collectstatic` deploy step,
# which runs the api image with that directory mounted (docs/DEPLOYMENT.md).
ALSO_OURS = {"static"}


def owned_directories() -> set[str]:
    """The OWNED list in scripts/prepare_data_root.sh - what it chowns."""
    body = PREPARE.read_text()
    listed = re.search(r'OWNED="\n(.*?)\n"', body, re.DOTALL)
    assert listed, "scripts/prepare_data_root.sh no longer declares an OWNED list"
    return {line.strip() for line in listed.group(1).splitlines() if line.strip()}


def ours_by_mount() -> set[str]:
    """Every `${DATA_ROOT}` path bound by a service running as uid 10001."""
    prefix = "${DATA_ROOT}"
    paths = set()
    for name in OUR_SERVICES:
        for volume in SERVICES[name].get("volumes") or []:
            source = volume.split(":", 1)[0]
            if source.startswith(prefix + "/"):
                paths.add(source[len(prefix) + 1 :])
    return paths


def test_the_script_chowns_what_our_own_images_write_and_nothing_else() -> None:
    """Derived from the mounts, in both directions, because both directions have
    been wrong.

    The script used to end in `chown -R 10001:10001 "$DATA_ROOT"`, and the
    documented remedy for a stack already started was the same command. On a
    live host that hands `caddy/` - the ACME account key and the deployment's
    TLS private key - and `postgres/` and the nightly dumps in `backups/` to the
    uid every container of ours runs as, which is the opposite of what
    compose.yaml's header says this stack does with secrets. So: every
    directory a 10001 service binds must be chowned, and the three nobody of
    ours writes must not be.
    """
    owned = owned_directories()
    expected = ours_by_mount() | ALSO_OURS

    uncovered = sorted(
        path
        for path in expected
        if path not in owned and not any(path.startswith(o + "/") for o in owned)
    )
    assert not uncovered, (
        f"a service running as uid 10001 binds these and the script does not chown them, "
        f"so the daemon's root-owned directory is what the container finds: {uncovered}"
    )

    foreign = {"postgres", "caddy", "photon"}
    assert not (owned & foreign), (
        f"the script chowns {sorted(owned & foreign)}. postgres is PGDATA, caddy holds the "
        "ACME account key and the TLS private key, and photon belongs to an image that is "
        "not ours; none of the three is written by anything running as 10001"
    )
    assert foreign <= prepared_directories(), (
        "the script must still create them - a bind-mount source that does not exist is "
        "manufactured by the daemon as root, which is the defect this script is about"
    )


def test_nothing_runs_a_recursive_chown_over_the_whole_data_root() -> None:
    """The command, wherever it would actually be executed: a shell block in a
    document an operator copies from, or a line in the script itself.

    Mentioning it in prose is fine and two paragraphs do - that is how the
    hazard gets explained. Running it is the thing: `${DATA_ROOT}` holds
    `caddy/`, and `caddy/` holds the deployment's TLS private key.
    """
    recursive = re.compile(r"chown\s+-R\s+\S+\s+\"?\$(?:DATA_ROOT|\{DATA_ROOT\})\"?\s*$")

    for name, body in DOCUMENTS.items():
        for block in re.findall(r"```sh\n(.*?)```", body, re.DOTALL):
            for line in block.replace("\\\n", " ").splitlines():
                assert not recursive.search(line), (
                    f"{name} tells an operator to run `{line.strip()}`, which chowns the TLS "
                    "private key and PGDATA along with everything else"
                )

    for line in PREPARE.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert not recursive.match(line.strip()), (
            f"scripts/prepare_data_root.sh runs `{line.strip()}`: one recursive chown over "
            "the root of the volume, PGDATA and the ACME account key included"
        )


# Sourcing `.env` into a shell, in any of the spellings that do it. Prose is
# allowed to name them - both documents explain at length why not to - so this
# is matched against the shell snippets only.
SOURCES_ENV = re.compile(r"(?:^|\s)(?:set -a\b|\.\s+\S*\.env\b|source\s+\S*\.env\b)")


def shell_snippets(text: str) -> list[str]:
    return re.findall(r"```sh\n(.*?)```", text, re.DOTALL)


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_no_documented_command_sources_the_environment_file(name: str) -> None:
    """`.env` is compose's input and it must not reach a shell.

    Every snippet in these documents used to open with
    `set -a; . ./.env; set +a` and then run `docker compose` in the same shell,
    which put every value in the file through `sh` on the way: `$$` is a
    literal-`$` escape to compose's parser and the shell's pid to `sh`,
    backticks and `$(...)` in a value are commands, and an exported variable
    beats the env file when compose reads it. So the first `up` initialised
    PGDATA with `hunter47112`, the next `up -d` from a different shell sent
    `hunter81330`, `pg_isready` went green on both, `migrate` failed
    authentication and the three services gated on it never started - an outage
    with the shape of a rotated password that nobody had rotated.

    The two snippets that genuinely needed `$DATA_ROOT` get it another way now:
    `scripts/prepare_data_root.sh --env-file ./.env` reads the one line it
    wants without evaluating the file, and `collectstatic` runs under
    `docker compose run`, which gives the container the service's own
    environment.
    """
    offenders = [block for block in shell_snippets(DOCUMENTS[name]) if SOURCES_ENV.search(block)]
    assert not offenders, (
        f"{name} has shell snippets that source the environment file:\n" + "\n---\n".join(offenders)
    )


def test_every_documented_run_of_the_prepare_script_names_the_env_file() -> None:
    """The option that let the guides stop sourcing `.env`, on every command
    that runs the script, read as argv. That the script reads the file without
    evaluating it is run, not read, in tests/test_prepare_data_root.py; this
    used to grep the script for `sed -n`."""
    runs = [
        (name, tokens)
        for name, body in ALL_DOCUMENTS.items()
        for tokens in snippet_commands(body) + inline_commands(body)
        if tokens[0] in {"sudo", "sh"}
        and any(token.endswith("prepare_data_root.sh") for token in tokens)
    ]
    assert runs, "no guide runs scripts/prepare_data_root.sh any more"
    for name, tokens in runs:
        script = next(i for i, token in enumerate(tokens) if token.endswith("prepare_data_root.sh"))
        arguments = tokens[script + 1 :]
        named = (arguments[:1] == ["--env-file"] and len(arguments) >= 2) or (
            bool(arguments) and arguments[0].startswith("--env-file=")
        )
        assert named, (
            f"{name} runs the script without naming an env file: {' '.join(tokens)}; with "
            "DATA_ROOT unset it refuses, and the way round that is sourcing .env"
        )


def test_every_documented_data_root_snippet_has_the_value_from_somewhere() -> None:
    """`$DATA_ROOT` is not exported by anything, so a snippet that uses it
    without setting it runs with it empty. In the `chown -R` case that is a
    chown of `/`; in the `install -d` case it is a directory at the host's root
    that the rebuild container cannot see.

    The permitted source is now an explicit `export DATA_ROOT=<path>` - one
    variable, typed out, a path and not a secret - rather than the whole file.
    """
    used = 0
    for name, body in DOCUMENTS.items():
        using = [block for block in shell_snippets(body) if "$DATA_ROOT" in block]
        used += len(using)
        unguarded = [
            block for block in using if not re.search(r"^\s*export DATA_ROOT=", block, re.M)
        ]
        assert not unguarded, (
            f"these {name} snippets use $DATA_ROOT without setting it first: "
            + "\n---\n".join(unguarded)
        )
    assert used, "no snippet uses $DATA_ROOT any more, so this test is vacuous"


# --- The figures the host is sized from --------------------------------------


def load_script(name: str):
    """A module out of scripts/, which is not a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_host_requirements_quote_the_figures_the_repository_enforces() -> None:
    """Two numbers in the host requirements are enforced by something here, and
    both are read from where they are enforced: the RAM figure
    `scripts/check_compose_limits.py` fails against, and the free-space gate
    compose gives the rebuild. The plan's vCPU and volume figures are the
    plan's and are not checked by anything, so this no longer pins them as
    strings."""
    body = section(DEPLOYMENT, "## Host requirements")
    ram = load_script("check_compose_limits").HOST_RAM_GB
    assert f"HOST_RAM_GB = {ram}" in body, (
        f"scripts/check_compose_limits.py fails a stack above {ram} GB and the host "
        "requirements quote a different figure, or none"
    )
    assert f"{ram} GB" in body, f"the host requirements do not state {ram} GB of RAM"

    default = SERVICES["rebuild"]["environment"]["REBUILD_MIN_FREE_BYTES"]
    documented = default.removeprefix("${REBUILD_MIN_FREE_BYTES:-").removesuffix("}")
    assert documented.isdigit(), f"compose's REBUILD_MIN_FREE_BYTES is not a default: {default}"
    assert documented in body, (
        f"compose defaults REBUILD_MIN_FREE_BYTES to {documented} and the host requirements "
        "section names a different number"
    )


def test_the_photon_pin_and_what_it_is_serving_are_both_written_down() -> None:
    """A pinned image and an empty index. PLAN:60's population step is unbuilt,
    nothing in phase 1 calls this service, and a reader who finds it in the
    stack should find that out here rather than by querying it."""
    image = SERVICES["photon"]["image"]
    assert not image.endswith(":latest"), "the photon image is unpinned again"
    assert image in section(DEPLOYMENT, "## Photon"), (
        f"docs/DEPLOYMENT.md's Photon section does not record the pin {image}"
    )
    # The citation, resolved: the plan line it names has to be the geocoder's.
    cited = {int(n) for n in re.findall(r"PLAN(?:\.md)?:(\d+)\b", section(DEPLOYMENT, "## Photon"))}
    plan = (REPO / "PLAN.md").read_text().splitlines()
    assert cited, "the Photon section cites no plan line for the unbuilt index"
    for line in cited:
        assert "Photon" in plan[line - 1], (
            f"the Photon section cites PLAN.md:{line}, which is not about Photon: "
            f"{plan[line - 1][:120]!r}"
        )


def test_the_root_path_is_a_404_as_the_entry_points_section_says() -> None:
    """`config/urls.py` routes the admin, the health check and three auth paths
    and nothing else, so a first deployment that checks `/` sees a 404 on a
    stack that is working, and docs/DEPLOYMENT.md says where to look instead.
    Resolved through the URLconf, which is the thing that would change; the
    paths the section sends a reader to are resolved by
    `test_every_path_the_guides_send_an_operator_to_is_routed`."""
    from django.urls import Resolver404, resolve

    with pytest.raises(Resolver404):
        resolve("/")
    section(DEPLOYMENT, "## What the deployment serves")


# --- The osmium commands, as the documents print them ------------------------


def documented_osmium_commands(documents=None) -> list[tuple[str, list[str]]]:
    """(document, argv) for every osmium command line in docs/*.md.

    Shell blocks only, with the eighty-column continuations folded back in, so
    what is checked is what an operator would paste.

    `documents` is for the test below that hands it a block of its own: this
    collector stands between every flag assertion here and the runbook, so what
    it does *not* match has to be stated against an input that has one, rather
    than against whatever the documents happen to look like today.
    """
    found = []
    for name, body in (documents if documents is not None else DOCUMENTS).items():
        for block in re.findall(r"```sh\n(.*?)```", body, re.DOTALL):
            for line in block.replace("\\\n", " ").splitlines():
                if line.strip().startswith("osmium "):
                    found.append((name, line.split()))
    return found


def osmium_line_count() -> int:
    """How many osmium lines the documents' shell blocks hold, counted a
    different way from the collector above.

    The collector is the thing between every flag assertion and the runbook,
    and narrowing it - `startswith("osmium merge")` in place of
    `startswith("osmium ")` - leaves every remaining assertion passing while
    the `osmium extract` line, which carries `-s smart -S types=any` and the
    bounding box, is checked by nothing. So the count is taken again here with
    a regular expression rather than the same predicate.
    """
    total = 0
    for body in DOCUMENTS.values():
        for block in re.findall(r"```sh\n(.*?)```", body, re.DOTALL):
            total += len(re.findall(r"(?m)^[ \t]*osmium\b", block.replace("\\\n", " ")))
    return total


def test_the_osmium_collector_reads_an_indented_command_line() -> None:
    """Indentation is not part of a command.

    A shell block nests: a command under a numbered step, inside a `for` loop,
    or under a heading an author indented for readability, is still a line an
    operator pastes. Matched at column zero only, such a line is invisible to
    every flag assertion above - and invisibly so, because the documents today
    happen to carry none, which is exactly why this is asserted against a block
    written here rather than against `docs/`.

    The sibling count in `osmium_line_count` is deliberately written with a
    different predicate and compared against this collector's output, so an
    indented line appearing in a real document is caught there too.
    """
    indented = {
        "synthetic.md": (
            "Under a step:\n\n```sh\n"
            "  osmium merge dc.osm.pbf md.osm.pbf --overwrite -f pbf -o merged.osm.pbf\n"
            "\tosmium extract -s smart -S types=any --overwrite -f pbf \\\n"
            "    -b -78.0,38.2,-76.02,39.72 merged.osm.pbf -o source.osm.pbf\n"
            "```\n"
        )
    }

    assert osmium_line_count.__doc__, "the sibling count is the other half of this"
    found = documented_osmium_commands(indented)
    assert [argv[1] for _, argv in found] == ["merge", "extract"], (
        f"the collector saw {found} in a block holding two indented osmium lines; a line "
        "it does not see is a command in a runbook that nothing checks"
    )
    assert all(argv[0] == "osmium" for _, argv in found), found


def test_every_osmium_command_in_the_documents_is_one_osmium_would_accept() -> None:
    """The flags are not decoration and one of them was missing from a document
    while the code had it right.

    `-f pbf` is what makes the `.part` staging scheme work at all: osmium takes
    the output format from the output file's suffix, `merged.osm.pbf.part` has
    the wrong one, and without the flag osmium exits during argument setup. A
    runbook that prints the command without it prints a command that cannot
    run, which costs an operator an afternoon rather than costing the code a
    bug. `--overwrite` is the weekly re-run into the same directory, and
    `-s smart -S types=any` is PLAN:13's clip strategy - without the `-S` half
    the administrative boundaries are exactly the relations the clip cuts.

    Derived from `pipeline.source`, so the code is the authority and a document
    that restates it cannot quietly disagree.
    """
    from django.conf import settings

    from pipeline import source

    commands = documented_osmium_commands()
    assert commands, "no osmium command lines in docs/*.md any more"
    assert len(commands) == osmium_line_count(), (
        f"the collector found {len(commands)} osmium lines and the documents' shell "
        f"blocks hold {osmium_line_count()}; a line it does not see is a command in a "
        "runbook that nothing checks"
    )

    produced = {
        "merge": source.merge_command([Path("dc.osm.pbf")], Path("merged.osm.pbf.part")),
        "extract": source.clip_command(
            Path("merged.osm.pbf"), Path("source.osm.pbf.part"), settings.COVERAGE_BBOX
        ),
    }
    # Read back out of the real commands rather than restated, so this cannot
    # outlive a change to either one.
    required = {
        name: [
            flag
            for flag in ("--overwrite", "-f", "pbf", "-s", "smart", "-S", "types=any")
            if flag in argv
        ]
        for name, argv in produced.items()
    }
    assert required["merge"] == ["--overwrite", "-f", "pbf"], f"merge_command: {produced['merge']}"
    assert required["extract"] == ["--overwrite", "-f", "pbf", "-s", "smart", "-S", "types=any"], (
        f"clip_command: {produced['extract']}"
    )

    assert {argv[1] for _, argv in commands} == set(produced), (
        f"the documents print {sorted({argv[1] for _, argv in commands})} and the "
        f"pipeline produces {sorted(produced)}; the extract line carries the clip "
        "strategy and the bounding box and is the one worth checking"
    )

    for document, argv in commands:
        subcommand = argv[1]
        missing = [flag for flag in required[subcommand] if flag not in argv]
        assert not missing, (
            f"{document} prints `{' '.join(argv)}`, which is missing {missing}; "
            f"pipeline.source.{subcommand}_command produces them"
        )
        assert argv[argv.index("-f") + 1] == "pbf", (
            f"{document} names an output format that is not pbf: {' '.join(argv)}"
        )
        # The box too, where a line prints one: a runbook clipping to last
        # season's region is a map that silently stops short of the plan's.
        for flag in ("--bbox", "-b"):
            if flag in argv:
                printed = tuple(float(v) for v in argv[argv.index(flag) + 1].split(","))
                assert printed == tuple(settings.COVERAGE_BBOX), (
                    f"{document} clips to {printed}; settings.COVERAGE_BBOX is "
                    f"{settings.COVERAGE_BBOX}"
                )


# --- Rolling a release back ---------------------------------------------------


def test_every_documented_tag_change_is_applied_with_up() -> None:
    """`docker compose restart` restarts the containers that exist, on the
    image they were created from. A rollback moves `TAG`, which changes which
    image the service should run, and only `up -d` acts on that: it re-reads
    `.env`, sees the image has changed and recreates the container. Documented
    as a restart, the rollback is a stack that reports success and goes on
    serving the release it was rolling back from.

    Read off the commands rather than the sentences around them: every command
    in a guide that sets `TAG` is an `up -d`. This used to split the prose into
    sentences and look for the words "TAG", "rollback" and "restart" together.
    """
    tagged = [
        (name, tokens)
        for name, body in ALL_DOCUMENTS.items()
        for tokens in snippet_commands(body) + inline_commands(body)
        if tokens[0].startswith("TAG=") and len(tokens) > 1
    ]
    assert tagged, "no guide shows a command that sets TAG, so this checks nothing"
    for name, tokens in tagged:
        command = [token for token in tokens if not re.match(r"^[A-Z_]+=", token)]
        assert command[:4] == ["docker", "compose", "up", "-d"], (
            f"{name} applies a TAG change with `{' '.join(tokens)}`; only `docker compose "
            "up -d` recreates a container on the image the new tag names"
        )


def test_every_documented_restart_is_of_the_routers_that_load_tiles_at_start() -> None:
    """A restart is right for exactly one thing in this stack: the three
    `valhalla_service` containers open the promoted tiles once, at start, so
    after a rebuild or a rollback they have to be restarted to see the new
    build - all three, or one variant keeps serving the old graph. For anything
    that reads `.env`, a restart keeps the environment the container was
    created with, which is the mistake the guides warn about in prose.

    Derived from `compose.yaml`: the services that bind a promoted `current`
    tile directory are the ones a restart is for, and every documented
    `docker compose restart` names exactly that set."""
    routers = {
        name
        for name, service in SERVICES.items()
        for volume in service.get("volumes") or []
        if re.match(r"^\$\{DATA_ROOT\}/tiles/[^/]+/current:", volume)
    }
    assert routers, "no service binds a promoted tile directory"
    restarts = [
        (name, tokens)
        for name, body in ALL_DOCUMENTS.items()
        for tokens in snippet_commands(body)
        if tokens[:3] == ["docker", "compose", "restart"]
    ]
    assert restarts, "no guide restarts the routers after a rebuild"
    for name, tokens in restarts:
        named = {token for token in tokens[3:] if not token.startswith("-")}
        assert named == routers, (
            f"{name} runs `{' '.join(tokens)}`; the services that load tiles at start, "
            f"which are the only ones a restart is for, are {sorted(routers)}"
        )


# --- Numbers and inputs the documents share with the code ---------------------


def test_the_documented_urban_fraction_is_the_installers_own_constant() -> None:
    """The rule changed in wave 5 - from "any intersection" to a majority of the
    way's length - and docs/DEVELOPMENT.md kept describing the old one. Not a
    cosmetic difference: the switch chooses the default speed table, 30 mph
    urban against 50 rural, so under the documented rule a Loudoun through road
    with a hundred metres inside Leesburg's polygon reads urban end to end,
    which is the lower-stress reading of an ambiguous input on every mile of it.

    The constant is quoted with its value, read from the installer; what the
    words around it say is the reader's to judge, and two phrase pins about
    them are gone.
    """
    fraction = load_script("install_reference_data").MIN_URBAN_FRACTION
    quoted = re.findall(
        r"MIN_URBAN_FRACTION = ([0-9.]+)", section(DEVELOPMENT, "## Reference data")
    )
    assert quoted, "docs/DEVELOPMENT.md's reference-data section does not quote MIN_URBAN_FRACTION"
    assert {float(value) for value in quoted} == {fraction}, (
        f"docs/DEVELOPMENT.md quotes MIN_URBAN_FRACTION as {quoted} and the installer's "
        f"constant is {fraction}"
    )


def flag_values(tokens: list[str], flag: str) -> list[str]:
    """Every value given to a repeated option, in order."""
    return [tokens[i + 1] for i, token in enumerate(tokens[:-1]) if token == flag]


def test_the_first_host_procedure_installs_both_agencies_volume_files() -> None:
    """`scripts/install_reference_data.py`'s own docstring: a single agency
    leaves the precedence rule nothing to arbitrate, which is the whole reason
    `--volume` and its two companions repeat. The procedure installed VDOT
    alone.

    Read as argv, from every guide that runs the installer: at least two
    distinct agencies, each one the installer knows (`SOURCE_TIERS`, which is
    what it refuses an unknown agency against), one `--volume-source` per
    `--volume`, and a `--volume-year` once or once per file, which is how it
    pairs them up.
    """
    known = set(load_script("install_reference_data").SOURCE_TIERS)
    runs = [
        (name, tokens)
        for name, body in ALL_DOCUMENTS.items()
        for tokens in snippet_commands(body)
        if "scripts/install_reference_data.py" in tokens and "--volume" in tokens
    ]
    assert any(name == "docs/OPERATIONS.md" for name, _ in runs), (
        "the first-host procedure in docs/OPERATIONS.md installs no volume files"
    )
    for name, tokens in runs:
        volumes, sources, years = (
            flag_values(tokens, "--volume"),
            flag_values(tokens, "--volume-source"),
            flag_values(tokens, "--volume-year"),
        )
        assert len(set(sources)) >= 2 and len(set(sources)) == len(sources), (
            f"{name} installs the agencies {sources}; with one agency, or one twice, the "
            "conflation step has nothing to arbitrate"
        )
        assert set(sources) <= known, (
            f"{name} names agencies the installer refuses: {sorted(set(sources) - known)}"
        )
        assert len(sources) == len(volumes) and len(years) in {0, 1, len(volumes)}, (
            f"{name} passes {len(volumes)} --volume, {len(sources)} --volume-source and "
            f"{len(years)} --volume-year; the installer takes a companion once or once "
            "per file, and distinct agencies are once per file"
        )


def test_the_reference_inputs_are_named_by_a_path_the_container_can_resolve() -> None:
    """The image's WORKDIR is `/app`, so a bare `tl_2024_us_uac20.geojson` in a
    `docker compose exec` line names a file that is not there and cannot be: the
    inputs come from outside the stack and live on the data volume, which the
    api does not mount at all and the rebuild mounts five directories of.
    """
    for name, body in DOCUMENTS.items():
        for flag, value in re.findall(r"--(urban-areas|volume)\s+(\S+)", body):
            assert value.startswith(("/data/", '"$DATA_ROOT/', "$DATA_ROOT/", "<")), (
                f"{name} passes --{flag} {value}, a relative name that resolves under the "
                "image's /app rather than on the data volume"
            )


# --- The runbook's own commands, and the stack they are run against ----------

# A crontab line: five schedule fields of digits, `*`, `/`, `,` and `-`, then
# the command. Narrower than "five whitespace-separated tokens", which matched
# the prose sentence above the block as well.
CRON_SCHEDULE = re.compile(r"^(?:[\d*/,\-]+\s+){5}\S")

# Prose wraps at eighty columns in these files, so a figure the text attaches
# to a name can sit on the next line. Matched against the unwrapped form.
OPERATIONS_PROSE = " ".join(OPERATIONS.split())


def test_the_cron_entry_finds_the_compose_project() -> None:
    """The entry ran from cron and not from a shell in the checkout.

    `docker compose` finds its project by looking for a compose file in the
    working directory and upwards, and cron runs a job from the owner's home
    directory. The documented line had neither a `cd` nor a
    `--project-directory`, so every tick was `no configuration file provided`
    and exit 1 - which the `|| mail-the-ops-channel` turns into a page every
    ten minutes, from the monitor, about nothing.
    """
    lines = [
        line
        for line in OPERATIONS.splitlines()
        if "check_operations" in line and CRON_SCHEDULE.match(line.strip())
    ]
    assert lines, "docs/OPERATIONS.md no longer shows a cron entry for check_operations"
    for line in lines:
        assert "cd " in line or "--project-directory" in line, (
            f"the cron entry is `{line.strip()}`; run from cron's working directory "
            "`docker compose` finds no project and exits 1 on every tick"
        )
        if "cd " in line:
            assert line.index("cd ") < line.index("docker compose"), line


def test_the_documents_quote_the_grace_period_the_stack_actually_gives(tmp_path) -> None:
    """Both documents explain what a `down` or an `up -d` does to a running
    rebuild in terms of a number that lives in `compose.yaml`. Quoted, not
    restated: a grace period changed in one place and described in two is a
    runbook that is wrong about the thing it is warning you of."""
    grace = SERVICES["rebuild"].get("stop_grace_period")
    assert grace, "the rebuild service no longer declares a stop_grace_period"
    quoted = f"stop_grace_period: {grace}"
    for name, body in (("docs/OPERATIONS.md", OPERATIONS), ("docs/DEPLOYMENT.md", DEPLOYMENT)):
        assert quoted in body, f"{name} does not quote `{quoted}`"


def test_the_dropped_tick_is_documented_with_procrastinates_own_number() -> None:
    """A stack down across Tuesday 08:00 UTC loses that week's rebuild rather
    than catching it up: the periodic deferrer ignores any tick further in the
    past than `procrastinate.periodic.MAX_DELAY`. Read from the library, so the
    figure in the runbook cannot outlive an upgrade that changes it.

    The figure is the one after the name, wherever the runbook gives it; the
    paragraph's other words, and a pin that it named `run_rebuild_now`, are
    not this test's business."""
    from procrastinate import periodic

    minutes = periodic.MAX_DELAY // 60
    quoted = re.findall(r"MAX_DELAY\b[^\d.]{0,30}?(\d+) minutes", OPERATIONS_PROSE)
    assert quoted, "docs/OPERATIONS.md does not give procrastinate's MAX_DELAY as a figure"
    assert {int(value) for value in quoted} == {minutes}, (
        f"procrastinate drops a tick more than {minutes} minutes late and docs/OPERATIONS.md "
        f"gives MAX_DELAY as {quoted} minutes"
    )


def test_the_first_boot_window_is_the_one_the_health_check_declares() -> None:
    """docs/OPERATIONS.md tells an operator to re-run a first `up` whose
    `migrate` failed, and quotes the start period as the reason. The start
    period is what makes first-boot probe failures not count against the
    retries; deleted, a slow initdb is a `postgis` marked unhealthy and three
    services that never start.

    Every figure a guide attaches to a start period is compose's, however the
    sentence around it is worded."""
    start = SERVICES["postgis"]["healthcheck"].get("start_period")
    assert start, "the database health check has no start period"
    seconds = int(str(start).rstrip("s"))
    quoted = [
        (name, int(value))
        for name, body in ALL_DOCUMENTS.items()
        for value in re.findall(
            r"start[ _]period\b\D{0,20}?(\d+)\s*(?:s\b|seconds)", " ".join(body.split())
        )
    ]
    assert quoted, "no guide gives the database's start period as a figure"
    wrong = [(name, value) for name, value in quoted if value != seconds]
    assert not wrong, (
        f"the health check declares a {start} start period and the guides give {wrong}"
    )


# --- Rotating a secret --------------------------------------------------------


def test_the_password_rotation_alters_the_role_before_it_edits_the_file() -> None:
    """The postgis image reads POSTGRES_PASSWORD only when it initialises an
    empty PGDATA, so on an existing volume a new value in `.env` changes
    nothing in the database. `pg_isready` does not authenticate, so the health
    gate still goes green; `migrate` fails on the password and `api`, `worker`
    and `rebuild` - held on `service_completed_successfully` - never start."""
    assert "ALTER ROLE" in DEPLOYMENT, (
        "docs/DEPLOYMENT.md documents no way to rotate the database password"
    )
    blocks = [b for b in re.findall(r"```sh\n(.*?)```", DEPLOYMENT, re.DOTALL) if "ALTER ROLE" in b]
    assert len(blocks) == 1, f"expected one password-rotation snippet, found {len(blocks)}"
    block = blocks[0]
    assert "docker compose exec" in block and "postgis" in block, (
        f"the ALTER ROLE is not shown inside the database container: {block!r}"
    )
    assert block.index("ALTER ROLE") < block.index(".env"), (
        "the snippet edits .env before it alters the role; the ALTER has to run under "
        f"the old password, which only the running container still has: {block!r}"
    )
    commands = snippet_commands(f"```sh\n{block}```")
    assert any(tokens[:4] == ["docker", "compose", "up", "-d"] for tokens in commands), (
        f"the snippet never recreates the containers with `up -d`: {block!r}"
    )
    assert not any(tokens[:3] == ["docker", "compose", "restart"] for tokens in commands), (
        f"a restarted container keeps the environment it was created with: {block!r}"
    )


def test_the_tombstone_key_is_documented_as_what_the_table_makes_it() -> None:
    """docs/DEVELOPMENT.md called a KEY_ENCRYPTION_KEY rotation "a
    re-tombstoning job", which implies there is something to re-tombstone
    from. A `BanTombstone` row is the HMAC, a timestamp and a free-text reason:
    the Discord id the digest was taken over is stored nowhere, so a rotation
    cannot be undone and it silently re-admits every banned account.

    The claim is checked against the model rather than restated, so the day a
    column is added that *would* make a rotation possible, this fails and the
    paragraph gets rewritten rather than staying pessimistic. (Whether to add
    one is the owner's decision; this only holds the paragraph to the table.)
    Three pins of the paragraph's wording are gone."""
    from core.models import BanTombstone

    fields = {field.name for field in BanTombstone._meta.fields}
    assert fields == {"id", "tombstone", "created_at", "reason"}, (
        f"BanTombstone now stores {sorted(fields)}; docs/DEVELOPMENT.md says a rotation "
        "is unrecoverable because the id the digest covers is kept nowhere"
    )
    section(DEVELOPMENT, "### `KEY_ENCRYPTION_KEY` — required, no default")


def test_the_secret_key_rotation_is_documented_as_signing_everyone_out() -> None:
    """Sessions are database-backed and signed with `SECRET_KEY`, and
    `settings.py` declares no `SECRET_KEY_FALLBACKS`, so every session fails to
    decode after a rotation. Read from the loaded settings, because a fallback
    list added later would make both guides' paragraph wrong; it used to grep
    the settings source and pin the setting's name in both guides."""
    from django.conf import settings

    assert not settings.SECRET_KEY_FALLBACKS, (
        f"settings declare SECRET_KEY_FALLBACKS {settings.SECRET_KEY_FALLBACKS!r}, so a "
        "rotation no longer ends every session and docs/DEPLOYMENT.md and "
        "docs/DEVELOPMENT.md both say it does"
    )


def secrets_a_running_service_holds() -> set[str]:
    """Every `.env` variable that a service outside the `unbuilt` profile
    receives and whose name says it is a secret."""
    held = set()
    for service in SERVICES.values():
        if "unbuilt" in (service.get("profiles") or []):
            continue
        for value in (service.get("environment") or {}).values():
            for name in re.findall(r"\$\{([A-Z][A-Z0-9_]*)", str(value)):
                if re.search(r"SECRET|PASSWORD|TOKEN|_KEY$", name):
                    held.add(name)
    return held


def test_the_rotation_section_covers_every_secret_a_running_service_holds() -> None:
    """`DISCORD_CLIENT_SECRET` is the fifth secret in `.env` and the only one
    issued by somebody else, and the rotation section listed four. Derived now
    from what compose hands the services that run, so the next secret added to
    the stack is missing from the section until someone writes down what
    rotating it costs. This used to pin that one name and the words `up -d`
    and `restart` after it."""
    held = secrets_a_running_service_holds()
    assert {"PGPASSWORD", "DJANGO_SECRET_KEY"} <= held, (
        f"the derivation stopped finding secrets: {sorted(held)}"
    )
    body = section(DEPLOYMENT, "## Secrets, and what rotating one costs")
    named = set(re.findall(r"`([A-Z][A-Z0-9_]*)`", body))
    missing = sorted(held - named)
    assert not missing, (
        f"these reach a running container and docs/DEPLOYMENT.md's rotation section says "
        f"nothing about rotating them: {missing}"
    )


# --- Log rotation -------------------------------------------------------------


def test_the_log_ceiling_in_the_document_is_the_one_compose_sets() -> None:
    """A per-container ceiling written down in one place and configured in
    another is a figure that drifts. Both options are quoted from
    `compose.yaml`'s own anchor, in the section about them."""
    options = SERVICES["rebuild"]["logging"]["options"]
    body = section(DEPLOYMENT, "## Log rotation")
    for option, value in sorted(options.items()):
        assert f"{option}: {value}" in body, (
            f"docs/DEPLOYMENT.md's log-rotation section does not state `{option}: {value}`, "
            "which is what compose.yaml configures"
        )


# --- Going back a release -----------------------------------------------------


def test_the_migration_rule_the_rollback_depends_on_is_the_plan_line_cited() -> None:
    """Moving `TAG` back puts the old code in front of the new schema, and
    nothing runs a migration backwards. That is survivable only under PLAN:65's
    backwards-compatible-migration rule, and docs/DEPLOYMENT.md cites that line
    as the reason: the citation is resolved here, so a plan edit that moves the
    rule leaves the guide pointing at the wrong line and this fails. Three pins
    of the paragraph's opening sentence and its words are gone."""
    plan = (REPO / "PLAN.md").read_text().splitlines()
    rule = plan[64]
    assert "backwards-compatible" in rule.lower() or "backward-compatible" in rule.lower(), (
        f"PLAN.md:65 is no longer the migration rule: {rule!r}"
    )
    build = section(DEPLOYMENT, "## Build")
    assert "PLAN.md:65" in build, (
        "the build section's rollback paragraph no longer cites the migration rule"
    )


# --- The procedures this round added -----------------------------------------


def section(text: str, heading: str) -> str:
    """The body of one `##`/`###` section, up to the next heading of its level
    or shallower.

    Fenced blocks are skipped: a shell comment inside one starts with `#` and
    would otherwise end the section at the first `# 2. then ...` line.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    assert start is not None, f"no section {heading!r}"
    depth = len(heading.split(" ", 1)[0])
    fenced = False
    for end in range(start + 1, len(lines)):
        stripped = lines[end].strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if stripped.startswith("#") and len(stripped.split(" ", 1)[0]) <= depth:
            return "\n".join(lines[start:end])
    return "\n".join(lines[start:])


def is_up(tokens: list[str]) -> bool:
    return tokens[:4] == ["docker", "compose", "up", "-d"]


def up_services(tokens: list[str]) -> list[str]:
    """The services an `up -d` names; empty is the whole stack."""
    return [token for token in tokens[4:] if not token.startswith("-")]


def test_the_restore_runbook_restores_before_the_rest_of_the_stack_is_up() -> None:
    """The ordering is the runbook, and it is the part that cannot be fixed
    afterwards.

    On the stack's postgis image, a `pg_restore` into a database `migrate` had
    already populated gave errors and exit 1 - `pg_restore` carries on past
    each failing statement and applies the rest of the archive around it, so
    the non-zero exit arrives after the damage is done. The exit codes are
    measured, not read, by
    tests/test_worker_schedule.py::test_the_runbooks_restore_is_clean_into_an_
    empty_database_and_fails_into_a_full_one.

    Read as argv: the first `up -d` names postgis alone, the `pg_restore` comes
    before any `up -d` of the rest, and `collectstatic` - the assets are on the
    volume and not in the dump - comes after it. This used to pin the error
    counts the prose quotes, which round 10 re-measured as different.
    """
    commands = snippet_commands(section(OPERATIONS, "## Restoring one"))
    ups = [i for i, tokens in enumerate(commands) if is_up(tokens)]
    assert ups, "the restore runbook never starts the stack"
    assert up_services(commands[ups[0]]) == ["postgis"], (
        f"the first `up -d` in the restore runbook is {' '.join(commands[ups[0]])!r}; "
        "restoring into a database `migrate` has already run against collides on every "
        "table both it and the dump create"
    )
    restore = next((i for i, tokens in enumerate(commands) if "pg_restore" in tokens), None)
    assert restore is not None, "no command in the restore runbook runs pg_restore"
    rest = [i for i in ups if not up_services(commands[i])]
    assert rest, "the runbook never brings the rest of the stack up after the restore"
    assert all(i > restore for i in ups[1:]), (
        "the runbook starts more than postgis before the restore has run"
    )
    collect = [i for i, tokens in enumerate(commands) if "collectstatic" in tokens]
    assert collect and collect[-1] > rest[-1], (
        "the restore runbook does not re-run collectstatic once the stack is up; the "
        "collected assets are on the volume and not in the dump"
    )


# What the restore runbook does to the database between starting postgis and
# restoring into it, in order. Each step is the command as it must start after
# `docker compose`, the option-and-value pairs it must carry after that, and
# the positional argument it must end on (before any `<` redirect), or None.
# Pairs and the positional are read by place, not by membership: `-U
# routemaker` holds the same word as the database name, and `exec -T` the same
# flag as `createdb -T`. tests/test_worker_schedule.py runs the drop and the
# create for real.
RESTORE_DATABASE_STEPS = (
    (("up", "-d", "--wait"), (), "postgis"),
    (("exec", "-T", "postgis", "dropdb"), (), "routemaker"),
    (("exec", "-T", "postgis", "createdb"), (("-T", "template0"),), "routemaker"),
    (("exec", "-T", "postgis", "pg_restore"), (("-d", "routemaker"),), None),
)


def command_matches(tokens: list[str], start, pairs, last) -> bool:
    """Whether one `docker compose` command line is this restore step."""
    if tokens[:2] != ["docker", "compose"]:
        return False
    head = tuple(tokens[2 : 2 + len(start)])
    arguments = tokens[2 + len(start) :]
    if "<" in arguments:
        arguments = arguments[: arguments.index("<")]
    adjacent = set(zip(arguments, arguments[1:], strict=False))
    return (
        head == start
        and all(pair in adjacent for pair in pairs)
        and (last is None or arguments[-1:] == [last])
    )


def snippet_commands(text: str) -> list[list[str]]:
    """Every command line in the text's `sh` blocks, continuations joined and
    comments dropped, as tokens."""
    commands = []
    for block in shell_snippets(text):
        for line in block.replace("\\\n", " ").splitlines():
            tokens = line.split("#", 1)[0].split()
            if tokens:
                commands.append(tokens)
    return commands


def test_the_restore_runbook_empties_the_images_database_before_restoring() -> None:
    """An empty PGDATA is not an empty database on this image: its first boot
    creates postgis, postgis_topology, fuzzystrmatch and postgis_tiger_geocoder
    in PGDATABASE, and the dump carries the tiger, tiger_data and topology
    schemas, so a restore straight in exits 1 (3 errors, measured on
    postgis/postgis:16-3.4). The runbook drops the database and creates it from
    template0 first, after waiting for the health gate - without `--wait` the
    first command ran before the server's socket existed."""
    commands = snippet_commands(section(OPERATIONS, "## Restoring one"))
    position = -1
    for step in RESTORE_DATABASE_STEPS:
        found = next(
            (
                i
                for i, tokens in enumerate(commands)
                if i > position and command_matches(tokens, *step)
            ),
            None,
        )
        assert found is not None, (
            f"the restore runbook has no {step!r} after command {position}: "
            f"{[' '.join(tokens) for tokens in commands]}"
        )
        position = found


def test_the_posture_change_edits_every_value_the_local_block_sets() -> None:
    """Changing `CADDY_SITE_ADDRESS` alone half-works, which is the worst
    shape: Caddy gets its certificate and serves the name, and every request is
    a DisallowedHost 400 because ALLOWED_HOSTS still says localhost.

    The values that make up a posture are the ones `.env.example`'s local
    block sets, so that is where the list is read from: the block of `.env`
    lines the procedure gives has to name each of them - `DJANGO_DEBUG`, the
    one that is easy to leave behind, included - and the procedure has to
    apply them with `up -d`. This used to pin the five names by hand, and the
    words "DNS", "Discord" and "not `restart`".
    """
    from test_compose_render import local_block_assignments

    posture = set(local_block_assignments())
    assert "CADDY_SITE_ADDRESS" in posture, f"the local block stopped being found: {posture}"
    body = section(DEPLOYMENT, "## Changing posture on a running stack: `:80` to a hostname")
    # In a snippet, not in prose: the point of the section is the block an
    # operator copies, and a value explained in a paragraph and missing from
    # the block is the one that gets left behind.
    edited = set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", "\n".join(shell_snippets(body))))
    missing = sorted(posture - edited)
    assert not missing, f"the block of `.env` lines the posture change asks for omits {missing}"
    commands = snippet_commands(body)
    assert any(is_up(tokens) for tokens in commands), "the procedure never runs `up -d`"
    assert not any(tokens[:3] == ["docker", "compose", "restart"] for tokens in commands), (
        "the procedure restarts containers, which keeps the environment they were created with"
    )


def documented_paths() -> list[tuple[str, str]]:
    """(document, path) for every URL path a guide sends a reader to: the
    admin's, written `<DJANGO_ADMIN_PATH>...` or under the default prefix,
    and the application's own
    `/auth/...` and `/healthz`, wherever they appear."""
    from django.conf import settings

    found = []
    for name, body in ALL_DOCUMENTS.items():
        for rest in re.findall(r"<DJANGO_ADMIN_PATH>([A-Za-z0-9_/.-]*)", body):
            found.append((name, f"/{settings.ADMIN_PATH}{rest}"))
        # ...and the same pages written out under the default prefix.
        for rest in re.findall(rf"/{re.escape(settings.ADMIN_PATH)}([A-Za-z0-9_/.-]*)", body):
            found.append((name, f"/{settings.ADMIN_PATH}{rest}"))
        for path in re.findall(r"(?<![\w/.-])(/(?:auth/[a-z]+|healthz))\b", body):
            found.append((name, path))
    return found


def test_every_path_the_guides_send_an_operator_to_is_routed() -> None:
    """The second-admin procedure sends a reader to `<DJANGO_ADMIN_PATH>core/user/`,
    the pending-removal page and `/auth/login`; the deployment actions send
    them to the operations page. Each is resolved through the URLconf, so a
    model renamed, an admin unregistered or a route moved fails here rather
    than on an operator's screen. This replaces pins of `core/user/` and
    `/auth/login` as substrings."""
    from django.urls import Resolver404, resolve

    paths = documented_paths()
    admin = [path for _name, path in paths if "/auth/" not in path and path != "/healthz"]
    assert len(admin) >= 3, f"the admin pages the guides name stopped being found: {paths}"
    unrouted = []
    for name, path in paths:
        try:
            match = resolve(path)
        except Resolver404:
            unrouted.append((name, path))
            continue
        # The admin ends in a catch-all that resolves anything under its
        # prefix and answers it with a redirect or a 404; it has no name.
        if not match.url_name:
            unrouted.append((name, path))
    assert not unrouted, f"the guides send a reader to paths nothing routes: {unrouted}"


def test_the_second_instance_admin_is_promoted_on_a_page_with_no_add() -> None:
    """There is no add on the user admin - accounts are created by signing in -
    so the procedure is sign in, then promote. What that rests on is checked
    where it lives: the user admin refuses an add even to an instance admin,
    and the flag the procedure says to tick is the model field's own label.
    This used to pin "no add" and "is instance admin" in the prose."""
    from django.test import RequestFactory

    from core.admin import site
    from core.models import User

    body = section(DEPLOYMENT, "## Adding a second instance admin")
    request = RequestFactory().get("/")
    request.user = User(is_instance_admin=True)
    admin = site._registry[User]
    assert not admin.has_add_permission(request), (
        "the user admin offers an add to an instance admin; the procedure says accounts "
        "are created only by signing in"
    )
    label = str(User._meta.get_field("is_instance_admin").verbose_name)
    assert label in body.lower(), (
        f"the procedure does not name the field it has an operator tick ({label!r})"
    )
    assert any("/auth/login" in path for path in re.findall(r"`([^`]+)`", body)), (
        "the procedure does not send the new admin to sign in first"
    )


def test_the_postgis_bump_keeps_the_dump_client_on_the_servers_major() -> None:
    """A PostgreSQL major bump is a dump and restore, and the dump is taken by
    the api image's pinned client, so the pin and the server have to move
    together. Checked between `docker/api.Dockerfile` and `compose.yaml`, and
    the procedure's own command - `ALTER EXTENSION postgis UPDATE` inside the
    database container - read as argv. Three word pins are gone."""
    major = re.search(r"ARG PG_MAJOR=(\d+)", (REPO / "docker" / "api.Dockerfile").read_text())
    assert major, "docker/api.Dockerfile no longer pins a client major"
    assert re.search(rf":{major.group(1)}(?:\D|$)", SERVICES["postgis"]["image"]), (
        f"the api image pins postgresql-client-{major.group(1)} and the postgis service "
        f"runs {SERVICES['postgis']['image']}; the nightly pg_dump is the thing between them"
    )
    commands = [
        " ".join(tokens)
        for tokens in snippet_commands(section(DEPLOYMENT, "## Bumping the `postgis` image"))
    ]
    updates = [line for line in commands if "ALTER EXTENSION postgis UPDATE" in line]
    assert updates, "the procedure does not update the extension after a bump"
    assert all(line.startswith("docker compose exec -T postgis psql ") for line in updates), (
        f"the extension update does not run in the database container: {updates}"
    )


def test_moving_the_data_root_stops_the_stack_before_it_copies() -> None:
    """`${DATA_ROOT}/postgres` is PGDATA, bound straight into the running
    postgis container. Copying it out from under a live server produces a copy
    that is neither a backup nor a consistent snapshot. Read as argv: a
    `docker compose down` before the copy, the copy a `cp -a` (ownership and
    modes are the point - uid 10001, the postgis uid, a private key under
    caddy/), and the prepare script and an `up -d` after it."""
    commands = snippet_commands(section(DEPLOYMENT, "## Moving `${DATA_ROOT}` to a bigger disk"))
    down = next((i for i, t in enumerate(commands) if t[:3] == ["docker", "compose", "down"]), None)
    copy = next((i for i, t in enumerate(commands) if "cp" in t), None)
    assert down is not None, "the procedure never stops the stack"
    assert copy is not None, "the procedure never copies anything"
    assert down < copy, "the procedure copies the data volume before stopping the stack"
    tokens = commands[copy]
    assert tokens[tokens.index("cp") + 1] == "-a", (
        f"the copy is `{' '.join(tokens)}`, not `cp -a`; ownership and modes are the point"
    )
    after = commands[copy + 1 :]
    assert any(any(t.endswith("prepare_data_root.sh") for t in c) for c in after), (
        "the procedure does not re-run the prepare script on the new root"
    )
    assert any(is_up(c) for c in after), "the procedure never starts the stack again"


# --- Every command a guide shows, against the thing it runs ------------------

PLACEHOLDER = re.compile(r"<[^>]*>")


def inline_code(text: str) -> list[str]:
    """The inline code spans outside fenced blocks, wrapped lines joined."""
    prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return re.findall(r"`([^`]+)`", " ".join(prose.split()))


def inline_commands(text: str) -> list[list[str]]:
    """The inline code spans, as tokens: a command written into a sentence is
    still one an operator types."""
    return [span.split() for span in inline_code(text) if span.split()]


def documented_manage_commands(documents=None) -> list[tuple[str, str | None, list[str]]]:
    """(document, service, argv after `manage.py`) for every `manage.py`
    command a guide shows, in a shell block or inline. `service` is the
    compose service a `docker compose exec`/`run` puts it in, or None.
    Placeholders such as `<job_id>` become `1`, which every argument the
    commands take accepts."""
    import shlex

    found = []
    for name, body in (documents if documents is not None else ALL_DOCUMENTS).items():
        lines = [
            line.split(" #", 1)[0]
            for block in shell_snippets(body)
            for line in block.replace("\\\n", " ").splitlines()
        ] + inline_code(body)
        for line in lines:
            match = re.search(r"(?:^|\s)(?:\./)?manage\.py\s+(.+)", line)
            if not match:
                continue
            command = re.split(r"\s(?:\|\||&&|;|\|)\s", PLACEHOLDER.sub("1", match.group(1)))[0]
            service = re.search(
                r"docker compose (?:exec|run)\s+(?:-\S+\s+)*(\S+)\s+(?:\./)?manage\.py", line
            )
            found.append((name, service.group(1) if service else None, shlex.split(command)))
    return found


def test_every_documented_management_command_is_one_django_would_run() -> None:
    """The guides describe flags a command no longer has - round 10 found
    `rollback_rebuild` documented with two - and nothing noticed, because a
    runbook is read and not executed. Each documented invocation is handed to
    the command's own parser here: the command has to exist, and its arguments
    have to parse. A `docker compose exec`/`run` has to name a service built
    from this repository, the only images with a `manage.py` in them. This is
    what the counts of how often `unwedge_job` was mentioned stood in for."""
    from django.core.management import CommandError, get_commands, load_command_class

    commands = get_commands()
    ours = {name for name, service in SERVICES.items() if "build" in service}
    found = documented_manage_commands()
    assert {"rollback_rebuild", "unwedge_job", "run_rebuild_now", "check_operations"} <= {
        argv[0] for _name, _service, argv in found
    }, f"the collector stopped finding the runbook's commands: {found}"
    for name, service, argv in found:
        assert argv[0] in commands, f"{name} runs `manage.py {' '.join(argv)}`: no such command"
        assert service is None or service in ours, (
            f"{name} runs `manage.py {argv[0]}` in {service!r}, which has no manage.py; the "
            f"services built from this repository are {sorted(ours)}"
        )
        parser = load_command_class(commands[argv[0]], argv[0]).create_parser("manage.py", argv[0])
        try:
            parser.parse_args(argv[1:])
        except CommandError as refused:
            raise AssertionError(
                f"{name} runs `manage.py {' '.join(argv)}`, which the command refuses: {refused}"
            ) from None


@pytest.mark.django_db
def test_the_documented_repairs_run_against_the_real_models() -> None:
    """The half-restored-swap repair is two `manage.py shell -c` one-liners that
    rewrite or delete a `ValhallaUpstream` row. Executed here, against the test
    database with the placeholders filled in, so a renamed model or field makes
    the runbook's repair fail in the suite rather than on the night. They match
    no row, so they change nothing."""
    snippets = [
        argv[argv.index("-c") + 1]
        for _name, _service, argv in documented_manage_commands()
        if argv[0] == "shell" and "-c" in argv
    ]
    assert len(snippets) >= 2, f"the repair's shell one-liners stopped being found: {snippets}"
    for code in snippets:
        exec(compile(code, "<documented repair>", "exec"), {})


def test_every_repository_file_a_documented_command_runs_exists() -> None:
    """A command that runs `scripts/<name>` or reads `docker/<file>` is a path
    that has to be in the repository the operator is standing in."""
    missing = []
    checked = 0
    for name, body in ALL_DOCUMENTS.items():
        for tokens in snippet_commands(body):
            for token in tokens:
                token = token.strip("\"'")
                if PLACEHOLDER.search(token) or not re.match(
                    r"^(?:scripts|docker|src|tests|lua|fixtures)/", token
                ):
                    continue
                checked += 1
                if not (REPO / token).exists():
                    missing.append((name, token))
    assert checked, "no documented command names a repository file, so this checks nothing"
    assert not missing, f"documented commands run files that are not in the repository: {missing}"


def test_every_documented_run_of_the_reference_installer_parses() -> None:
    """The installer is run by hand on the first host, from a command in the
    runbook and the playbook. Its own parser is handed each documented argv -
    stopped as soon as it has parsed, before anything is installed - so a flag
    renamed in the script fails here rather than at step 6 of a first
    deployment."""
    import argparse

    installer = load_script("install_reference_data")
    runs = [
        (name, tokens[tokens.index("scripts/install_reference_data.py") + 1 :])
        for name, body in ALL_DOCUMENTS.items()
        for tokens in snippet_commands(body)
        if "scripts/install_reference_data.py" in tokens
    ]
    assert runs, "no guide runs the reference installer"

    class Parsed(Exception):
        pass

    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(parser, args=None, namespace=None):
        original(parser, args, namespace)
        raise Parsed

    for name, argv in runs:
        argparse.ArgumentParser.parse_args = parse_then_stop
        try:
            installer.main([PLACEHOLDER.sub("1", token) for token in argv])
        except Parsed:
            continue
        except SystemExit as refused:
            raise AssertionError(
                f"{name} runs the installer with {argv}, which its parser refuses ({refused})"
            ) from None
        finally:
            argparse.ArgumentParser.parse_args = original
        raise AssertionError(f"the installer returned without parsing {argv}")
