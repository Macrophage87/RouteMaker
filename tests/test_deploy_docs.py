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
# Prose wraps at eighty columns in these files, so a sentence to look for is
# almost always split across a newline. Matched against the unwrapped form.
DEPLOYMENT_PROSE = " ".join(DEPLOYMENT.split())
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


def test_the_rollback_procedure_names_the_rebuild_service_specifically() -> None:
    """The regressed line itself, pinned. It is the command an operator reaches
    for at three in the morning after a bad promotion, and the dry run and the
    `--confirm` are two separate lines that both have to be right."""
    section = OPERATIONS.split("## Rolling back a rebuild", 1)
    assert len(section) == 2, "docs/OPERATIONS.md has no rollback section"
    lines = [line for line in section[1].splitlines() if "rollback_rebuild" in line]
    invocations = [line for line in lines if "docker compose exec" in line]
    assert len(invocations) >= 2, f"the dry run and the --confirm are not both shown: {lines}"
    for line in invocations:
        assert "exec -T rebuild " in line, (
            f"the rollback is documented as `{line.strip()}`; only rebuild can write the "
            "tile links it moves"
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
    for command in ("rollback_rebuild", "run_rebuild_now", "install_reference_data"):
        assert command in DEPLOYMENT, f"the table of what runs where omits {command}"


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


def test_the_script_refuses_to_run_without_an_absolute_data_root() -> None:
    """The script ends in a `chown` per directory it owns. With `DATA_ROOT`
    unset or empty the argument that reaches each one is rooted at `/`, which
    ends the host - which is why the guard is in the script and not only in the
    document."""
    body = PREPARE.read_text()
    assert "${DATA_ROOT:?" in body, "the script no longer refuses an unset DATA_ROOT"
    assert "must be an absolute path" in body, "the script no longer refuses a relative path"


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


def test_the_prepare_script_reads_the_env_file_rather_than_sourcing_it() -> None:
    """The option that let the guide stop sourcing, and the property that makes
    it worth having: it never evaluates the file, so a `$`, a backtick or a
    semicolon in a password beside the `DATA_ROOT=` line is a string it does not
    touch."""
    script = PREPARE.read_text()
    assert "--env-file" in script, "scripts/prepare_data_root.sh takes no --env-file"
    assert not SOURCES_ENV.search(script.split("set -eu", 1)[1]), (
        "scripts/prepare_data_root.sh sources the file it was given instead of reading "
        "one line out of it"
    )
    assert "sed -n" in script, (
        "the script no longer extracts DATA_ROOT with sed; anything that evaluates the "
        "file runs whatever is in the other values"
    )
    for name, body in DOCUMENTS.items():
        for line in body.splitlines():
            stripped = line.strip()
            if "prepare_data_root.sh" in stripped and stripped.startswith(("sudo ", "sh ", "./")):
                assert "--env-file" in stripped, (
                    f"{name} runs the script without naming an env file: {stripped}"
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


def test_the_deployment_doc_carries_the_plans_host_and_the_gate_it_implies() -> None:
    """Three numbers that are assumptions in the repository rather than
    aspirations: the RAM figure `scripts/check_compose_limits.py` fails against,
    the core count the CPU limits are written for, and the volume the rebuild's
    disk gate is sized against."""
    for figure in ("8 vCPU", "32 GB", "200 GB"):
        assert figure in DEPLOYMENT, f"the host requirements omit {figure}"
    assert "HOST_RAM_GB = 32" in DEPLOYMENT, (
        "the 32 GB figure is not tied to the script that enforces it"
    )

    script = (REPO / "scripts" / "check_compose_limits.py").read_text()
    assert "HOST_RAM_GB = 32" in script, (
        "scripts/check_compose_limits.py no longer assumes 32 GB; docs/DEPLOYMENT.md says it does"
    )

    default = SERVICES["rebuild"]["environment"]["REBUILD_MIN_FREE_BYTES"]
    documented = default.removeprefix("${REBUILD_MIN_FREE_BYTES:-").removesuffix("}")
    assert documented in DEPLOYMENT, (
        f"compose defaults REBUILD_MIN_FREE_BYTES to {documented} and the host requirements "
        "section names a different number"
    )


def test_the_photon_pin_and_what_it_is_serving_are_both_written_down() -> None:
    """A pinned image and an empty index. PLAN:60's population step is unbuilt,
    nothing in phase 1 calls this service, and a reader who finds it in the
    stack should find that out here rather than by querying it."""
    image = SERVICES["photon"]["image"]
    assert not image.endswith(":latest"), "the photon image is unpinned again"
    assert image in DEPLOYMENT, f"docs/DEPLOYMENT.md does not record the pin {image}"
    assert "PLAN:60" in DEPLOYMENT, "the unbuilt index is not tied to the plan line"


def test_the_entry_points_are_documented_because_the_root_path_is_a_404() -> None:
    """`config/urls.py` routes the admin and three auth paths and nothing else,
    so a first deployment that checks `/` sees a 404 on a stack that is working.
    Derived from the URLconf so this cannot quietly become untrue."""
    urls = (REPO / "src" / "config" / "urls.py").read_text()
    assert 'path("", ' not in urls, "there is a root route now; the 404 note is stale"
    assert "/auth/login" in DEPLOYMENT and "404" in DEPLOYMENT
    assert "DJANGO_ADMIN_PATH" in DEPLOYMENT


def test_the_pipeline_image_is_not_described_as_debian() -> None:
    """It is `FROM ghcr.io/valhalla/valhalla:3.5.1`, whose runner stage is
    ubuntu:24.04, and `osmium-tool` is a noble package there. The api image is
    the Debian one."""
    assert "Debian's `osmium-tool`" not in OPERATIONS
    assert "Ubuntu's `osmium-tool`" in OPERATIONS


def test_the_api_dockerfile_does_not_still_say_there_is_no_static_root() -> None:
    """A comment describing a fixed defect as a current one, which is worse than
    no comment: `settings.STATIC_ROOT` is `DATA_ROOT / "static"` and the
    `collectstatic` deploy step runs. Read from settings rather than trusted."""
    from django.conf import settings

    assert settings.STATIC_ROOT, "settings defines no STATIC_ROOT; the comment was right"
    # Comment markers stripped before the lines are joined, so a claim wrapped
    # across two `#` lines is still found as one sentence.
    lines = (REPO / "docker" / "api.Dockerfile").read_text().splitlines()
    prose = " ".join(" ".join(line.lstrip().lstrip("#").split()) for line in lines)
    assert "cannot run yet because settings.py defines no STATIC_ROOT" not in prose


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
            "    -b -78.0,38.2,-76.3,39.5 merged.osm.pbf -o source.osm.pbf\n"
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
            Path("merged.osm.pbf"), Path("source.osm.pbf.part"), (-78.0, 38.2, -76.3, 39.5)
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


# --- Rolling a release back ---------------------------------------------------


def test_no_document_calls_a_tag_rollback_a_restart() -> None:
    """`docker compose restart` restarts the containers that exist, on the
    image they were created from. A rollback moves `TAG`, which changes which
    image the service should run, and only `up -d` acts on that: it re-reads
    `.env`, sees the image has changed and recreates the container. Documented
    as a restart, the rollback is a stack that reports success and goes on
    serving the release it was rolling back from.
    """
    for name, body in DOCUMENTS.items():
        prose = " ".join(body.split())
        for sentence in re.split(r"(?<=[.:]) ", prose):
            if "TAG" not in sentence or "rollback" not in sentence.lower():
                continue
            assert "restart" not in sentence.lower(), (
                f"{name} gives a TAG rollback as a restart: {sentence!r}. It is "
                "`docker compose up -d`; a restart reuses the image the container was "
                "created from"
            )
            assert "up -d" in sentence, (
                f"{name} describes a TAG rollback without naming `docker compose up -d`: "
                f"{sentence!r}"
            )


# --- Numbers and inputs the documents share with the code ---------------------


def test_the_documented_urban_fraction_is_the_installers_own_constant() -> None:
    """The rule changed in wave 5 - from "any intersection" to a majority of the
    way's length - and docs/DEVELOPMENT.md kept describing the old one. Not a
    cosmetic difference: the switch chooses the default speed table, 30 mph
    urban against 50 rural, so under the documented rule a Loudoun through road
    with a hundred metres inside Leesburg's polygon reads urban end to end,
    which is the lower-stress reading of an ambiguous input on every mile of it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "install_reference_data", REPO / "scripts" / "install_reference_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fraction = module.MIN_URBAN_FRACTION
    assert f"MIN_URBAN_FRACTION = {fraction}" in DEVELOPMENT, (
        f"docs/DEVELOPMENT.md does not name the constant it is describing ({fraction})"
    )
    assert "at least half their" in DEVELOPMENT, (
        "docs/DEVELOPMENT.md no longer states the majority-of-length rule in words"
    )
    assert "Intersection rather than containment" not in DEVELOPMENT, (
        "docs/DEVELOPMENT.md still states the pre-wave-5 intersection rule"
    )


def test_the_first_host_procedure_installs_both_agencies_volume_files() -> None:
    """`scripts/install_reference_data.py`'s own docstring: a single agency
    leaves the precedence rule nothing to arbitrate, which is the whole reason
    `--volume` and its two companions repeat. The procedure installed VDOT
    alone.
    """
    step = OPERATIONS.split("First rebuild on a fresh host", 1)[1].split("\n## ", 1)[0]
    sources = re.findall(r"--volume-source\s+(\S+)", step)
    assert len(sources) >= 2, (
        f"the first-host procedure installs {sources or 'no'} agency volume file(s); with "
        "one agency the conflation step has nothing to arbitrate"
    )
    assert len(set(sources)) == len(sources), f"the same agency twice: {sources}"
    assert {"vdot", "ddot"} <= set(sources), f"the two the docstring's example installs: {sources}"


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

OPERATIONS_PROSE = " ".join(OPERATIONS.split())
DEVELOPMENT_PROSE = " ".join(DEVELOPMENT.split())
ENV_EXAMPLE = (REPO / ".env.example").read_text()


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


def test_the_deployment_doc_does_not_bless_a_cron_entry_that_cannot_run() -> None:
    """docs/DEPLOYMENT.md's table of which command runs where used to end the
    `check_operations` row with "the cron entry in docs/OPERATIONS.md stays as
    written", which was a second document vouching for the broken line."""
    rows = [line for line in DEPLOYMENT.splitlines() if line.startswith("| `check_operations`")]
    assert len(rows) == 1, f"expected one check_operations row, found {len(rows)}"
    assert "stays as written" not in rows[0], rows[0]
    assert "cd" in rows[0], (
        f"the row says nothing about the working directory the entry needs: {rows[0]}"
    )


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


def test_both_documents_point_a_wedged_rebuild_at_the_command_that_frees_it() -> None:
    """A SIGKILL mid-build leaves the `weekly_rebuild` row `doing` with no
    worker behind it, and no grace period covers a six-hour build - so the
    residual is a documented repair rather than a fix. Every place that warns
    about the stop has to name it, or the warning ends in a shrug."""
    assert OPERATIONS.count("unwedge_job") >= 2, (
        "docs/OPERATIONS.md names unwedge_job fewer than twice: the wedged-job surface "
        "and the warning against stopping a running rebuild both need it"
    )
    assert "unwedge_job" in DEPLOYMENT, (
        "docs/DEPLOYMENT.md warns that moving TAG recreates the rebuild container "
        "without saying what frees the job that leaves behind"
    )


def test_the_dropped_tick_is_documented_with_procrastinates_own_number() -> None:
    """A stack down across Tuesday 08:00 UTC loses that week's rebuild rather
    than catching it up: the periodic deferrer ignores any tick further in the
    past than `procrastinate.periodic.MAX_DELAY`. Read from the library, so the
    figure in the runbook cannot outlive an upgrade that changes it."""
    from procrastinate import periodic

    assert "MAX_DELAY" in OPERATIONS, (
        "docs/OPERATIONS.md does not say that a missed tick is dropped rather than deferred late"
    )
    minutes = periodic.MAX_DELAY // 60
    paragraph = OPERATIONS_PROSE.split("MAX_DELAY", 1)[1][:900]
    assert f"{minutes} minutes" in paragraph, (
        f"procrastinate drops a tick more than {minutes} minutes late and the paragraph "
        f"that names MAX_DELAY states a different figure: {paragraph[:200]!r}"
    )
    catch_up = paragraph
    assert "run_rebuild_now" in catch_up, (
        "the dropped-tick paragraph does not name the hand-fired rebuild that is the "
        "catch-up for it"
    )


def test_the_first_boot_window_is_the_one_the_health_check_declares() -> None:
    """docs/OPERATIONS.md tells an operator to re-run a first `up` whose
    `migrate` failed, and quotes the start period as the reason. The start
    period is what makes first-boot probe failures not count against the
    retries; deleted, a slow initdb is a `postgis` marked unhealthy and three
    services that never start."""
    start = SERVICES["postgis"]["healthcheck"].get("start_period")
    assert start, "the database health check has no start period"
    seconds = int(str(start).rstrip("s"))
    assert f"start period is {seconds} seconds" in OPERATIONS_PROSE, (
        f"the health check declares a {start} start period and the runbook states something else"
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
    assert "up -d" in block and "restart" not in block, (
        f"a restarted container keeps the environment it was created with: {block!r}"
    )
    assert "ALTER ROLE" in ENV_EXAMPLE, (
        ".env.example lets an operator edit PGPASSWORD with no note that the database "
        "will not follow it"
    )


def test_the_tombstone_key_is_documented_as_what_the_table_makes_it() -> None:
    """docs/DEVELOPMENT.md called a KEY_ENCRYPTION_KEY rotation "a
    re-tombstoning job", which implies there is something to re-tombstone
    from. A `BanTombstone` row is the HMAC, a timestamp and a free-text reason:
    the Discord id the digest was taken over is stored nowhere, so a rotation
    cannot be undone and it silently re-admits every banned account.

    The claim is checked against the model rather than restated, so the day a
    column is added that *would* make a rotation possible, this fails and the
    paragraph gets rewritten rather than staying pessimistic."""
    from core.models import BanTombstone

    fields = {field.name for field in BanTombstone._meta.fields}
    assert fields == {"id", "tombstone", "created_at", "reason"}, (
        f"BanTombstone now stores {sorted(fields)}; docs/DEVELOPMENT.md says a rotation "
        "is unrecoverable because the id the digest covers is kept nowhere"
    )
    assert "which is a re-tombstoning job and not a restart" not in DEVELOPMENT_PROSE, (
        "docs/DEVELOPMENT.md still claims the rotation is a job that could be run"
    )
    assert "not rotatable in phase 1" in DEVELOPMENT_PROSE, (
        "docs/DEVELOPMENT.md does not say plainly that the key cannot be rotated"
    )
    assert "re-admit every banned account" in DEVELOPMENT_PROSE, (
        "the paragraph does not say what a rotation actually does"
    )


def test_the_secret_key_rotation_is_documented_as_signing_everyone_out() -> None:
    """Sessions are database-backed and signed with `SECRET_KEY`, and
    `settings.py` declares no `SECRET_KEY_FALLBACKS`, so every session fails to
    decode after a rotation. Derived from the settings source, because a
    fallback list added later would make the sentence wrong."""
    settings_source = (REPO / "src" / "config" / "settings.py").read_text()
    assert "SECRET_KEY_FALLBACKS" not in settings_source, (
        "settings.py now declares SECRET_KEY_FALLBACKS, so a rotation no longer ends "
        "every session and both documents say it does"
    )
    for name, prose in (
        ("docs/DEPLOYMENT.md", DEPLOYMENT_PROSE),
        ("docs/DEVELOPMENT.md", DEVELOPMENT_PROSE),
    ):
        assert "SECRET_KEY_FALLBACKS" in prose, (
            f"{name} does not say why a rotation ends every session"
        )


# --- Log rotation -------------------------------------------------------------


def test_the_log_ceiling_in_the_document_is_the_one_compose_sets() -> None:
    """A per-container ceiling written down in one place and configured in
    another is a figure that drifts. Both options are quoted from
    `compose.yaml`'s own anchor."""
    options = SERVICES["rebuild"]["logging"]["options"]
    assert "Log rotation" in DEPLOYMENT, "docs/DEPLOYMENT.md has no log-rotation section"
    for option, value in sorted(options.items()):
        assert f"{option}: {value}" in DEPLOYMENT, (
            f"docs/DEPLOYMENT.md does not state `{option}: {value}`, which is what "
            "compose.yaml configures"
        )


# --- Going back a release -----------------------------------------------------


def test_the_migration_rule_the_rollback_depends_on_is_written_down() -> None:
    """Moving `TAG` back puts the old code in front of the new schema, and
    nothing runs a migration backwards. That is survivable only under PLAN:65's
    backwards-compatible-migration rule, which lived in PLAN.md alone - so the
    document that tells an operator to roll back by moving a tag never said
    what makes it safe, or that the safety is a convention nothing enforces.

    The plan line is read rather than cited blind."""
    plan = (REPO / "PLAN.md").read_text().splitlines()
    rule = plan[64]
    assert "backwards-compatible" in rule.lower() or "backward-compatible" in rule.lower(), (
        f"PLAN.md:65 is no longer the migration rule: {rule!r}"
    )
    upgrade = DEPLOYMENT_PROSE.split("Moving `TAG` back does not undo a migration", 1)
    assert len(upgrade) == 2, "docs/DEPLOYMENT.md no longer has the migration paragraph"
    paragraph = upgrade[1][:1400]
    # In the paragraph, not merely somewhere in the document: PLAN.md:65 is one
    # long line and four other claims here cite it.
    assert "PLAN.md:65" in paragraph, (
        "the paragraph does not tie the rollback to the migration rule that makes it survivable"
    )
    assert "collectstatic" in paragraph, (
        "the paragraph does not say that a rollback needs collectstatic re-run, which is "
        "the same deploy step a build needs"
    )
    assert "not enforced" in paragraph or "stated and not enforced" in paragraph, (
        "the paragraph presents the rule as something the suite checks; nothing reads a "
        "migration and refuses a DROP COLUMN"
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


def test_the_restore_runbook_restores_into_an_empty_database() -> None:
    """The ordering is the runbook, and it is the part that cannot be fixed
    afterwards.

    On the stack's postgis image, a `pg_restore` into a database `migrate` had
    already populated gave 172 errors and exit 1 - `pg_restore` carries on past
    each failing statement and applies the rest of the archive around it, so
    the non-zero exit arrives after the damage is done. `django_content_type`,
    `auth_permission` and `django_migrations` are all created by `migrate` and
    all carried by the dump. The same archive into a database dropped and
    recreated from template0 gave 0 errors. The exit codes themselves are
    measured, not read, by
    tests/test_worker_schedule.py::test_the_runbooks_restore_is_clean_into_an_
    empty_database_and_fails_into_a_full_one.
    """
    body = section(OPERATIONS, "## Restoring one")
    commanded = "\n".join(shell_snippets(body))
    assert "pg_restore" in commanded, (
        "no command in the restore runbook runs pg_restore; the prose may mention it, "
        "but the runbook is the snippet"
    )
    commands = [line for line in body.splitlines() if "docker compose up -d" in line]
    assert commands, "the restore runbook never starts the stack"
    first, rest = commands[0], commands[1:]
    assert "postgis" in first, (
        f"the first `up -d` in the restore runbook is {first.strip()!r}; restoring into "
        "a database `migrate` has already run against collides on every table both it "
        "and the dump create, and pg_restore applies the rest of the archive around "
        "every collision before it exits 1"
    )
    assert rest, "the runbook never brings the rest of the stack up after the restore"
    assert all("postgis" not in line for line in rest), rest
    for expected in ("empty", "0 errors", "172"):
        assert expected in body, (
            f"the restore runbook does not say {expected!r}, which is what makes the "
            "ordering an instruction rather than a preference"
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


def test_the_restore_runbook_says_what_the_deployment_has_afterwards() -> None:
    """A restore is not a rollback: the membership cache and the sessions are
    excluded from the dump and nothing in phase 1 refills the cache, the tiles
    are not in the database at all, and `nightly_backup` is stale until the next
    07:00 UTC because the dump is taken from inside its own run row."""
    body = section(OPERATIONS, "## Restoring one")
    for expected in ("membership", "tiles", "nightly_backup", "collectstatic"):
        assert expected in body, f"the restore runbook says nothing about {expected}"


def test_the_snapshot_is_in_the_action_list_and_not_only_in_a_sentence() -> None:
    """It was named as the thing standing between this deployment and a lost
    host, in a paragraph, and appeared in no list of things to do."""
    body = section(OPERATIONS, "## Deployment actions")
    assert "snapshot" in body.lower(), (
        "docs/OPERATIONS.md's deployment actions do not include the volume snapshot, "
        "which is the only copy of the database that is not on the volume itself"
    )


def test_the_epoch_rule_is_the_one_the_code_computes() -> None:
    """`core.runs.deployment_epoch` is the earlier of the oldest run row and
    `MAX(django_migrations.applied)`. The document still carried the rule from
    before that - "on a database with no rows at all nothing is stale" - which
    is the state a `--queues` typo or a crash-looping worker leaves, and it was
    being described as the reason the alerts are trustworthy."""
    body = section(OPERATIONS, "## What is watched, and for how long")
    assert "django_migrations" in body, (
        "the staleness section does not mention the migration half of the epoch, so it "
        "is still describing the run-row-only rule"
    )
    assert "with no rows at all nothing is stale" not in " ".join(body.split()), (
        "the pre-wave-7 epoch rule is back in docs/OPERATIONS.md"
    )
    source = REPO / "src" / "core" / "runs.py"
    assert "MAX(applied) FROM django_migrations" in source.read_text(), (
        "core.runs no longer reads django_migrations, so the documented rule is now the "
        "one that is wrong"
    )


def test_the_posture_change_is_documented_as_five_values_and_an_up() -> None:
    """Changing `CADDY_SITE_ADDRESS` alone half-works, which is the worst
    shape: Caddy gets its certificate and serves the name, and every request is
    a DisallowedHost 400 because ALLOWED_HOSTS still says localhost."""
    body = section(DEPLOYMENT, "## Changing posture on a running stack: `:80` to a hostname")
    # In a snippet, not in prose: the point of the section is the block an
    # operator copies, and a value explained in a paragraph and missing from
    # the block is the one that gets left behind. `DJANGO_DEBUG` is that value.
    edited = "\n".join(shell_snippets(body))
    for name in (
        "CADDY_SITE_ADDRESS",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DISCORD_REDIRECT_URI",
        "DJANGO_DEBUG",
    ):
        assert name in edited, f"the block of `.env` lines the posture change asks for omits {name}"
    assert "DNS" in body, "the procedure does not say the name has to resolve here first"
    assert "Discord" in body, "the procedure does not say to register the new redirect URI"
    assert "not `restart`" in body or "not\n`restart`" in body, (
        "the procedure does not say `up -d` rather than `restart`, which is the "
        "difference between the new values reaching a container and not"
    )


def test_the_second_instance_admin_procedure_names_the_page_that_exists() -> None:
    """There is no add on the user admin - accounts are created by signing in -
    so the procedure is sign in, then promote, and the page it happens on is
    derived here rather than restated."""
    body = section(DEPLOYMENT, "## Adding a second instance admin")
    assert "/auth/login" in body, (
        "the procedure does not say the new admin signs in first; without the account "
        "row there is nothing on the page to promote"
    )
    assert "core/user/" in body, "the procedure does not name the page the promotion happens on"
    assert "is instance admin" in body.lower()
    assert "no add" in body.lower() or 'no "add"' in body.lower(), (
        "the procedure does not say there is no add button, which is the thing a reader "
        "goes looking for first"
    )


def test_the_discord_client_secret_is_in_the_rotation_section() -> None:
    """It is the fifth secret in `.env` and the only one issued by somebody
    else, and the rotation section listed four."""
    body = section(DEPLOYMENT, "## Secrets, and what rotating one costs")
    assert "DISCORD_CLIENT_SECRET" in body, (
        "docs/DEPLOYMENT.md's rotation section does not cover DISCORD_CLIENT_SECRET"
    )
    after = body.split("DISCORD_CLIENT_SECRET", 1)[1]
    assert "up -d" in after and "restart" in after, (
        "the DISCORD_CLIENT_SECRET rotation does not say `up -d` rather than `restart`; "
        "a restarted container keeps the secret it was created with"
    )


def test_the_postgis_bump_covers_both_kinds() -> None:
    """A patch bump of a floating tag is a pull and one SQL statement; a
    PostgreSQL major bump is a dump and restore, because PGDATA's on-disk format
    is major-version-specific."""
    body = section(DEPLOYMENT, "## Bumping the `postgis` image")
    assert "ALTER EXTENSION postgis UPDATE" in body, (
        "the procedure does not name ALTER EXTENSION postgis UPDATE, so the extension "
        "stays at the version it was created with while the library moves"
    )
    assert "pg_dump" in body and "pg_restore" in body, (
        "the major-version half of the procedure does not name the dump and restore"
    )
    assert "postgresql-client" in body, (
        "the procedure does not mention the pinned client major in docker/api.Dockerfile, "
        "which is what takes the nightly dump"
    )
    major = re.search(r"ARG PG_MAJOR=(\d+)", (REPO / "docker" / "api.Dockerfile").read_text())
    assert major, "docker/api.Dockerfile no longer pins a client major"
    assert major.group(1) in SERVICES["postgis"]["image"], (
        f"the api image pins postgresql-client-{major.group(1)} and the postgis service "
        f"runs {SERVICES['postgis']['image']}; the nightly pg_dump is the thing between them"
    )


def test_moving_the_data_root_says_to_stop_the_stack_first() -> None:
    """`${DATA_ROOT}/postgres` is PGDATA, bound straight into the running
    postgis container. Copying it out from under a live server produces a copy
    that is neither a backup nor a consistent snapshot."""
    body = section(DEPLOYMENT, "## Moving `${DATA_ROOT}` to a bigger disk")
    assert "PGDATA" in body, "the procedure does not say what makes the live case dangerous"
    lines = body.splitlines()
    down = next((i for i, line in enumerate(lines) if "docker compose down" in line), None)
    copy = next((i for i, line in enumerate(lines) if line.strip().startswith("sudo cp")), None)
    assert down is not None, "the procedure never stops the stack"
    assert copy is not None, "the procedure never copies anything"
    assert down < copy, "the procedure copies the data volume before stopping the stack"
    assert "cp -a" in body, (
        "the copy is not `cp -a`; ownership and modes are the point - uid 10001 on seven "
        "directories, the postgis uid on PGDATA, and a private key under caddy/"
    )


@pytest.mark.parametrize("name", ["docs/OPERATIONS.md", "docs/DEPLOYMENT.md"])
def test_the_sigkill_warnings_cover_the_worker_too(name: str) -> None:
    """`worker` has the same grace period and the same Procrastinate worker, so
    a nightly dump or a sweep killed mid-run leaves the same `doing` row. Both
    documents warned about `rebuild` alone."""
    body = DOCUMENTS[name]
    grace = SERVICES["worker"]["stop_grace_period"]
    quoted = f"stop_grace_period: {grace}"
    windows = [
        " ".join(body.split())[max(0, m.start() - 600) : m.end() + 600]
        for m in re.finditer(re.escape(quoted), body)
    ]
    assert windows, f"{name} does not quote `{quoted}` anywhere"
    assert any("worker" in window and "rebuild" in window for window in windows), (
        f"{name} explains the grace period against `rebuild` alone; `worker` carries the "
        "same one and wedges the same way"
    )
