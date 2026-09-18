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
    assert "${DATA_ROOT}:/data" in rebuild_volumes
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


def test_the_script_also_creates_what_the_rebuild_writes_inside_its_whole_mount() -> None:
    """`rebuild` mounts `${DATA_ROOT}` whole, so these are not mappings of their
    own and the derivation above cannot see them. They are named in settings and
    the rebuild writes all three."""
    assert {"extracts", "reference", "rebuild"} <= prepared_directories()


def test_the_script_refuses_to_run_without_an_absolute_data_root() -> None:
    """`chown -R` is the last line of that script. With `DATA_ROOT` unset or
    empty the argument that reaches `chown` can be `/`, which ends the host -
    which is why the guard is in the script and not only in the document."""
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
