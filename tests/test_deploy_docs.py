"""The runbook, held to the stack it describes.

Cheap tests, and the round-6 review is the argument for them: the two defects
below were both a document that had drifted from `compose.yaml` in a way no
reader could see, and a wrong runbook is not a documentation problem when it is
the only description of a procedure nobody has executed.

- `docs/OPERATIONS.md` told an operator to roll a rebuild back with
  `docker compose exec -T api`. The `api` service mounts no part of the data
  volume and sets no `DATA_ROOT`, so `settings.TILES_DIR` inside it is
  `/app/data/tiles` on the container's own writable layer: `rollback_rebuild`
  finds no `previous` link for any variant and refuses, which reads like a
  deployment that has never rebuilt rather than like a command in the wrong
  container.
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
# `rebuild` mounts ${DATA_ROOT} whole at /data, `worker` mounts the backups
# directory there. The api mounts nothing.
DATA_SERVICES = {"rebuild", "worker"}


def documented_exec_invocations(text: str) -> list[tuple[str, str]]:
    """(service, command line) for every `docker compose exec` in a document."""
    return [(match.group(2), match.group(3).strip()) for match in EXEC.finditer(text)]


def test_the_services_this_file_reasons_about_still_mount_what_it_says() -> None:
    """The premise of everything below, asserted rather than assumed: `rebuild`
    has the whole volume and `api` has none of it. A stack that gave the api a
    data mount would make these tests wrong rather than failing."""
    rebuild_volumes = SERVICES["rebuild"]["volumes"]
    assert "${DATA_ROOT}/tiles:/data/tiles" in rebuild_volumes
    assert "${DATA_ROOT}/reference:/data/reference" in rebuild_volumes
    assert SERVICES["rebuild"]["environment"]["DATA_ROOT"] == "/data"
    assert not SERVICES["api"].get("volumes"), (
        f"the api now mounts {SERVICES['api']['volumes']}; docs/DEPLOYMENT.md says it "
        "mounts nothing durable and the table of which command runs where follows from that"
    )
    assert "DATA_ROOT" not in (SERVICES["api"].get("environment") or {})


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
            f"the rollback is documented as `{line.strip()}`; the api has no data mount "
            "and would refuse on every tile link"
        )


def test_the_deployment_doc_says_plainly_that_the_api_mounts_no_data() -> None:
    """It used to point at "the blocker below", which was about the *worker*
    having no DATA_ROOT - a fixed defect, and a different service. The api
    having no data mount is not a blocker and is not going to be fixed; it is a
    rule about where a command runs."""
    assert "mounts no part of the data volume" in DEPLOYMENT_PROSE
    for command in ("rollback_rebuild", "run_rebuild_now", "install_reference_data"):
        assert command in DEPLOYMENT, f"the table of what runs where omits {command}"


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


def test_every_documented_data_root_snippet_loads_the_environment_first() -> None:
    """`$DATA_ROOT` lives in `.env`, which is compose's input and not the
    shell's, so a snippet that uses it without `set -a; . ./.env; set +a` is a
    snippet that runs with it empty. In the `chown -R` case that is a chown of
    `/`; in the `collectstatic` case it is a mount of the host's root that
    reports success and leaves the volume empty."""
    blocks = re.findall(r"```sh\n(.*?)```", DEPLOYMENT, re.DOTALL)
    using = [block for block in blocks if "$DATA_ROOT" in block]
    assert using, "docs/DEPLOYMENT.md has no shell snippet using $DATA_ROOT any more"
    unguarded = [
        block
        for block in using
        if ". ./.env" not in block and not re.search(r"^\s*export DATA_ROOT=", block, re.M)
    ]
    assert not unguarded, (
        "these snippets use $DATA_ROOT without loading the environment file first: "
        + "\n---\n".join(unguarded)
    )


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


def documented_osmium_commands() -> list[tuple[str, list[str]]]:
    """(document, argv) for every osmium command line in docs/*.md.

    Shell blocks only, with the eighty-column continuations folded back in, so
    what is checked is what an operator would paste.
    """
    found = []
    for name, body in DOCUMENTS.items():
        for block in re.findall(r"```sh\n(.*?)```", body, re.DOTALL):
            for line in block.replace("\\\n", " ").splitlines():
                if line.strip().startswith("osmium "):
                    found.append((name, line.split()))
    return found


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
