"""The stack's own images.

Five review rounds read this code and none asked whether the stack could be
built. It could not: `compose.yaml` named four `routemaker/*` images, there was
no Dockerfile anywhere and no `build:` stanza, so `docker compose up` on a host
with a working daemon would have stopped at the first pull of an image that
exists in no registry.

These tests are what stands in for a build. No image has been built in this
environment - there is no Docker daemon and registries are blocked - so nothing
here claims an image builds. What they assert is the set of things that are
false in a Dockerfile that certainly does not: a COPY of a path that is not in
the repository, a compose service whose image nothing produces, a pipeline image
built from a different Valhalla than the one serving the tiles it writes, an
`ENV` line that bakes a secret into a layer, and a `WORKDIR`/`COPY` layout that
puts `manage.py` somewhere other than where compose's `["./manage.py", ...]`
command looks for it.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]

# Images the stack pulls. Every one is pinned to a specific tag, per PLAN:293
# ("all images pinned"), which is the property this list exists to make visible.
# Photon was the exception and carried `latest` - not a pin at all: whatever that
# repository's maintainer had pushed last would arrive on the next
# `docker compose pull`, with no change in this repository to point at. It is
# 2.4.0 now, the newest release tag on Docker Hub when that was written.
#
# Every one also names its registry. An unqualified reference is a Docker Hub
# one, so the registry was always there - it was just the default rather than
# something this file said, and a default is what a registry mirror or a
# namespace somebody else registers gets to reinterpret.
EXTERNAL_IMAGES = {
    "docker.io/library/caddy:2.8-alpine",
    "docker.io/postgis/postgis:16-3.4",
    "docker.io/rtuszik/photon-docker:2.4.0",
    "ghcr.io/valhalla/valhalla:3.5.1",
}

# Images compose names for components that have no source in this repository, so
# there is nothing to put in an image and a Dockerfile for either would mean
# inventing the service.
#
# The bot is handoff.md section 7's first row ("No bot ... there is no bot
# source, no gateway handler and no ingest route"). The renderer is the same
# case and belongs beside it: PLAN.md:63 describes "a small Node sidecar using
# `@maplibre/maplibre-gl-native`", and `frontend/` holds one stress-style module
# and its test while `scripts/` holds five Python scripts and a shell script -
# no Node service anywhere.
#
# A row leaves this set when the source lands, and the test below then requires
# a `build:` for it. That is the point of the set: an unbuilt image is recorded,
# not tolerated silently.
UNBUILT_IMAGES = {
    "ghcr.io/macrophage87/routemaker-renderer:${TAG}",
    "ghcr.io/macrophage87/routemaker-bot:${TAG}",
}

SECRET_ENV_NAMES = {
    "KEY_ENCRYPTION_KEY",
    "DISCORD_CLIENT_SECRET",
    "PGPASSWORD",
    "DJANGO_SECRET_KEY",
    "DISCORD_BOT_TOKEN",
    "BOT_INTERNAL_SECRET",
}

# The apt packages the rebuild's stages shell out to, and the reason each one is
# required rather than nice to have. Named here so that dropping one from the
# Dockerfile fails in the suite rather than six hours into a rebuild.
PIPELINE_REQUIRED_PACKAGES = {
    "gdal-bin": "gdalwarp, resampling every HGT tile (pipeline/elevation.py)",
    "osmium-tool": "the osmium CLI for the source-extract stage (PLAN.md:13)",
    "sqlite3": "querying tz_world in the built timezone database",
    "curl": "valhalla_build_timezones fetches the boundary release",
    "unzip": "valhalla_build_timezones unzips it, and checks for it by name",
    "spatialite-bin": "valhalla_build_timezones loads the shapefile with it",
}

# The binaries the pipeline image's own `command -v` loop has to name. The loop
# is what turns "this stage will fail six hours in" into "this image does not
# build", so what it leaves out is what nothing checks.
#
# spatialite_tool is the one that was left out and is the reason this list
# exists. valhalla_build_timezones checks for `spatialite` and `unzip` by name
# and exits if either is missing, then runs `spatialite_tool -i -shp ...` with
# no check at all (3.5.1 scripts/valhalla_build_timezones), so a missing
# spatialite_tool is a timezone build that passes the script's own guards and
# dies on the shapefile import - after the hundred-megabyte download. It is in
# the same package as spatialite, so nothing here has to be installed for it;
# noble's spatialite-bin ships /usr/bin/spatialite and /usr/bin/spatialite_tool
# (packages.ubuntu.com/noble/amd64/spatialite-bin/filelist).
# The runtime stage installs four packages that are not there for a binary the
# rebuild shells out to, so they are not in the table above and this is where
# that is said rather than left as a silent difference: TLS roots for the
# downloads, libpq for psycopg, and the two python3 packages the virtualenv is
# built with.
PACKAGES_NOT_FOR_A_REBUILD_BINARY = {
    "ca-certificates",
    "libpq5",
    "python3-pip",
    "python3-venv",
}

PIPELINE_GUARDED_BINARIES = (
    "valhalla_build_admins",
    "valhalla_build_timezones",
    "valhalla_build_tiles",
    "valhalla_build_extract",
    "valhalla_service",
    "gdalwarp",
    "osmium",
    "sqlite3",
    "spatialite",
    "spatialite_tool",
    "unzip",
    "curl",
)


# --- a Dockerfile, as far as these tests need to understand one ---------------


class Dockerfile:
    """Enough of the format to answer the questions below.

    Line continuations joined, comments dropped, global ARG defaults
    substituted. Not a general parser: it does not evaluate heredocs or
    per-stage ARG scoping, and it does not need to.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.instructions = self._parse(path.read_text())
        self.args = {
            name: value
            for name, _, value in (arg.partition("=") for _, arg in self.of("ARG") if "=" in arg)
            for name, value in [(name.strip(), value.strip())]
        }

    @staticmethod
    def _parse(text: str) -> list[tuple[str, str]]:
        joined: list[str] = []
        buffer = ""
        for raw in text.splitlines():
            line = raw.rstrip()
            if not buffer and (not line.strip() or line.lstrip().startswith("#")):
                continue
            if line.endswith("\\"):
                buffer += line[:-1]
                continue
            buffer += line
            joined.append(buffer)
            buffer = ""
        if buffer:
            joined.append(buffer)
        out = []
        for line in joined:
            keyword, _, rest = line.strip().partition(" ")
            out.append((keyword.upper(), rest.strip()))
        return out

    def of(self, keyword: str) -> list[tuple[str, str]]:
        return [(k, rest) for k, rest in self.instructions if k == keyword]

    def expand(self, value: str) -> str:
        for name, default in self.args.items():
            value = value.replace(f"${{{name}}}", default).replace(f"${name}", default)
        return value

    @property
    def froms(self) -> list[str]:
        return [self.expand(rest).split()[0] for _, rest in self.of("FROM")]

    @property
    def final_workdir(self) -> str:
        workdir = "/"
        for keyword, rest in self.instructions:
            if keyword == "WORKDIR":
                candidate = self.expand(rest).strip()
                workdir = (
                    candidate if candidate.startswith("/") else f"{workdir.rstrip('/')}/{candidate}"
                )
        return workdir

    def copies(self) -> list[tuple[list[str], str]]:
        """(sources, destination) for every COPY that reads the build context.

        `COPY --from=<stage>` reads another stage rather than the context, so its
        sources are not repository paths and are skipped.
        """
        out = []
        for _, rest in self.of("COPY"):
            tokens = self.expand(rest).split()
            if any(t.startswith("--from=") for t in tokens):
                continue
            paths = [t for t in tokens if not t.startswith("--")]
            if len(paths) < 2:
                continue
            out.append((paths[:-1], paths[-1]))
        return out

    def env_names(self) -> set[str]:
        names: set[str] = set()
        for keyword in ("ENV", "ARG"):
            for _, rest in self.of(keyword):
                for token in rest.split():
                    name, sep, _ = token.partition("=")
                    if sep:
                        names.add(name)
        return names


def dockerfile_for(service: dict) -> Path | None:
    build = service.get("build")
    if not build:
        return None
    if isinstance(build, str):
        return REPO / build / "Dockerfile"
    return REPO / build.get("context", ".") / build.get("dockerfile", "Dockerfile")


BUILT = {
    name: dockerfile_for(service)
    for name, service in sorted(SERVICES.items())
    if service.get("build")
}


# --- the tests ----------------------------------------------------------------


def test_every_image_is_built_here_pulled_or_recorded_unbuilt() -> None:
    """Nothing in compose.yaml may name an image that no one produces.

    This is the test that would have caught the whole gap: four
    `routemaker/*` images, no Dockerfile in the repository and no `build:`
    anywhere, so three of the stack's own services could only ever have been
    pulled from a registry that has never seen them.
    """
    unaccounted = {
        name: service["image"]
        for name, service in sorted(SERVICES.items())
        if "image" in service
        and not service.get("build")
        and service["image"] not in EXTERNAL_IMAGES
        and service["image"] not in UNBUILT_IMAGES
    }
    assert not unaccounted, (
        "services naming an image nothing builds, that is not a pinned external "
        f"image and is not recorded in handoff.md section 7: {unaccounted}"
    )


def test_the_recorded_unbuilt_images_really_have_no_source() -> None:
    """The allow-list above is a record, not an excuse.

    If a bot or renderer source ever lands, this fails and the row has to leave
    UNBUILT_IMAGES - at which point the previous test demands a `build:` for it.
    """
    node_sources = sorted(
        p.relative_to(REPO).as_posix()
        for p in (REPO / "frontend").rglob("*")
        if p.suffix in {".ts", ".tsx"} or p.name in {"index.js", "server.js", "bot.js"}
    )
    assert not node_sources, f"frontend/ now holds service source: {node_sources}"
    assert not (REPO / "bot").exists(), "a bot/ directory exists; give it a Dockerfile"
    assert not (REPO / "renderer").exists(), "a renderer/ directory exists; give it a Dockerfile"


def test_build_contexts_and_dockerfiles_resolve() -> None:
    assert BUILT, "no service declares a build; compose can produce no image at all"
    missing = {
        name: str(path) for name, path in BUILT.items() if path is None or not path.is_file()
    }
    assert not missing, f"build declares a dockerfile that is not in the repository: {missing}"

    bad_context = {
        name: SERVICES[name]["build"]["context"]
        for name in BUILT
        if not (REPO / SERVICES[name]["build"]["context"]).is_dir()
    }
    assert not bad_context, f"build context does not resolve: {bad_context}"


def test_the_image_tag_survives_the_build() -> None:
    """`image:` stays beside `build:` so TAG still names the result.

    Without it compose would name the built image after the project and the
    service, and `TAG` - the one knob a deploy turns - would address nothing.
    """
    untagged = [name for name in BUILT if "image" not in SERVICES[name]]
    assert not untagged, f"services that build without naming the image: {untagged}"

    for name in BUILT:
        assert "${TAG}" in SERVICES[name]["image"], (
            f"{name} builds an image whose name does not carry TAG: {SERVICES[name]['image']}"
        )


@pytest.mark.parametrize("service", sorted(BUILT))
def test_every_copy_source_exists(service: str) -> None:
    """A COPY of a path that is not in the repository is a build that fails on
    the line that reads it, which is the cheapest of these failures to catch
    here and the most expensive to discover on a deploy host."""
    dockerfile = Dockerfile(BUILT[service])
    missing = [
        source
        for sources, _ in dockerfile.copies()
        for source in sources
        if not (REPO / source).exists()
    ]
    assert not missing, f"{dockerfile.path.name} copies paths that do not exist: {missing}"


@pytest.mark.parametrize("service", sorted(BUILT))
def test_manage_py_lands_where_the_compose_command_looks_for_it(service: str) -> None:
    """compose runs `["./manage.py", ...]` for worker, migrate and rebuild.

    That is an execve of a path relative to WORKDIR, so three things have to
    hold at once: the image has a WORKDIR, a COPY puts manage.py in it, and the
    file carries its executable bit through the copy.
    """
    dockerfile = Dockerfile(BUILT[service])
    workdir = dockerfile.final_workdir
    assert workdir != "/", f"{dockerfile.path.name} sets no WORKDIR"

    landed: set[str] = set()
    for sources, destination in dockerfile.copies():
        base = (
            destination
            if destination.startswith("/")
            else f"{workdir.rstrip('/')}/{destination.lstrip('./')}"
        )
        for source in sources:
            if destination.endswith("/") or destination in {".", "./"}:
                landed.add(f"{base.rstrip('/')}/{Path(source).name}")
            else:
                landed.add(base)

    expected = f"{workdir.rstrip('/')}/manage.py"
    assert expected in landed, (
        f"{dockerfile.path.name} has WORKDIR {workdir} but nothing copies manage.py there; "
        f'compose commands are ["./manage.py", ...]. Copied to: {sorted(landed)}'
    )

    mode = (REPO / "manage.py").stat().st_mode
    assert mode & stat.S_IXUSR, "manage.py is not executable, so ./manage.py cannot be execve'd"
    tracked = subprocess.run(
        ["git", "ls-files", "-s", "manage.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert tracked.startswith("100755"), (
        f"manage.py is checked in without its executable bit: {tracked.strip()!r}"
    )


def test_the_pipeline_is_built_from_the_valhalla_that_serves_the_tiles() -> None:
    """Read out of compose rather than written here.

    A rebuild that writes tiles with a different Valhalla than the containers
    that read them is a tile-schema mismatch, and it surfaces after promotion as
    a routing failure rather than at build time as an error.
    """
    serving = {
        service["image"]
        for service in SERVICES.values()
        if str(service.get("image", "")).startswith("ghcr.io/valhalla/valhalla:")
    }
    assert len(serving) == 1, f"the serving containers disagree on the Valhalla image: {serving}"
    (expected,) = serving

    dockerfile = Dockerfile(REPO / "docker" / "pipeline.Dockerfile")
    assert set(dockerfile.froms) == {expected}, (
        f"docker/pipeline.Dockerfile builds FROM {dockerfile.froms}, but the serving "
        f"containers run {expected}"
    )


@pytest.mark.parametrize("service", sorted(BUILT))
def test_no_dockerfile_bakes_a_secret_into_a_layer(service: str) -> None:
    """An ENV or ARG naming one of these puts it in the image's metadata, where
    it survives every `docker history` and every push. Compose scopes all six
    per service at runtime; none of them is a build input."""
    dockerfile = Dockerfile(BUILT[service])
    baked = sorted(dockerfile.env_names() & SECRET_ENV_NAMES)
    assert not baked, f"{dockerfile.path.name} declares secret variables: {baked}"


@pytest.mark.parametrize("package", sorted(PIPELINE_REQUIRED_PACKAGES))
def test_the_pipeline_image_installs_the_binaries_the_rebuild_shells_out_to(
    package: str,
) -> None:
    """Named packages rather than an `apt-get install` diff, because each of
    these is a stage that fails at runtime and not at build time when it is
    missing - and two of them (curl, unzip) are inherited from the upstream
    Valhalla image today, which is exactly the kind of dependency that
    disappears in an upstream base change nobody here reviews."""
    text = (REPO / "docker" / "pipeline.Dockerfile").read_text()
    # One package per line inside an `apt-get install` continuation, optionally
    # version-pinned, optionally ending the command.
    pattern = rf"^\s+{re.escape(package)}(?:=\S+)?\s*;?\s*\\?$"
    installs = re.findall(pattern, text, re.MULTILINE)
    assert installs, (
        f"docker/pipeline.Dockerfile does not install {package}, needed for: "
        f"{PIPELINE_REQUIRED_PACKAGES[package]}"
    )


@pytest.mark.parametrize("binary", PIPELINE_GUARDED_BINARIES)
def test_the_pipeline_image_asserts_every_binary_it_shells_out_to_is_present(binary: str) -> None:
    """The Dockerfile's `command -v` loop, held to a list.

    Installing the package is half of it: the guard is what makes a missing
    binary a build failure instead of a rebuild that runs for hours and then
    cannot find a program. A binary the loop does not name is one nothing
    checks - which is how `spatialite_tool` came to be installed, needed, and
    unguarded.
    """
    dockerfile = Dockerfile(REPO / "docker" / "pipeline.Dockerfile")
    guards = [rest for _, rest in dockerfile.of("RUN") if "command -v" in rest]
    assert len(guards) == 1, f"expected one `command -v` guard loop, found {len(guards)}"
    named = re.findall(r"[\w.]+", guards[0].partition(" in ")[2].partition(";")[0])
    assert binary in named, (
        f"docker/pipeline.Dockerfile's `command -v` loop does not name {binary}; a missing "
        "one is a rebuild that fails at runtime rather than an image that fails to build"
    )


def runtime_apt_packages(dockerfile: Dockerfile) -> set[str]:
    """The packages the *runtime* stage installs.

    There are two `apt-get install` lines in this file - the wheel-building
    stage installs a compiler - and only the second one puts anything in the
    image that ships. Stages are tracked by `FROM ... AS <name>` rather than by
    taking the last match, so adding a third stage does not silently change
    which list this reads.
    """
    stage = None
    packages: set[str] = set()
    for keyword, rest in dockerfile.instructions:
        if keyword == "FROM":
            tokens = dockerfile.expand(rest).split()
            stage = tokens[tokens.index("AS") + 1] if "AS" in tokens else None
        elif keyword == "RUN" and stage == "runtime" and "apt-get install" in rest:
            listed = rest.split("apt-get install", 1)[1].split(";")[0]
            packages |= {
                token.strip().rstrip(";")
                for token in listed.split()
                if not token.startswith("-") and token.strip().rstrip(";")
            }
    assert packages, "no apt-get install found in the runtime stage"
    return packages


def test_the_required_package_table_is_the_runtime_stage_it_describes() -> None:
    """`PIPELINE_REQUIRED_PACKAGES`, derived.

    The table above is hand-written on purpose - it carries *why* each package
    is required, which the Dockerfile cannot - and a hand-written list is one
    that can be narrowed with the suite still green. Drop `spatialite-bin` from
    it and the parametrised test above stops asking whether the package that
    `valhalla_build_timezones` loads its shapefile with is installed at all,
    and nothing anywhere says so.

    So it is asserted equal to what the runtime stage installs, less the four
    packages that are not there for a rebuild binary. Dropping the package from
    *both* sides is still possible and is what the image's own `command -v`
    guard is for: the loop names `spatialite` and `spatialite_tool`, so the
    image would fail to build.
    """
    installed = runtime_apt_packages(Dockerfile(REPO / "docker" / "pipeline.Dockerfile"))
    assert set(PIPELINE_REQUIRED_PACKAGES) == installed - PACKAGES_NOT_FOR_A_REBUILD_BINARY, (
        f"the table names {sorted(PIPELINE_REQUIRED_PACKAGES)} and the runtime stage "
        f"installs {sorted(installed)}, of which "
        f"{sorted(PACKAGES_NOT_FOR_A_REBUILD_BINARY)} are not there for a rebuild binary"
    )
    assert PACKAGES_NOT_FOR_A_REBUILD_BINARY < installed, (
        "the exemption list names a package the runtime stage does not install: "
        f"{sorted(PACKAGES_NOT_FOR_A_REBUILD_BINARY - installed)}"
    )


def test_the_guarded_binary_list_is_the_guard_loop_it_describes() -> None:
    """`PIPELINE_GUARDED_BINARIES`, derived, and the other direction of the
    test above it.

    The parametrised test asks, for each name here, whether the Dockerfile's
    loop names it - so a name deleted from the *loop* fails. A name deleted
    from this tuple instead leaves the loop intact and the suite green while
    the list that is supposed to be the record of what the rebuild shells out
    to has quietly shrunk. `spatialite_tool` is the one this matters for: it is
    the binary `valhalla_build_timezones` runs with no check of its own, which
    is why it is in the loop at all.
    """
    dockerfile = Dockerfile(REPO / "docker" / "pipeline.Dockerfile")
    guards = [rest for _, rest in dockerfile.of("RUN") if "command -v" in rest]
    assert len(guards) == 1, f"expected one `command -v` guard loop, found {len(guards)}"
    named = re.findall(r"[\w.]+", guards[0].partition(" in ")[2].partition(";")[0])
    assert set(PIPELINE_GUARDED_BINARIES) == set(named), (
        f"PIPELINE_GUARDED_BINARIES names {sorted(PIPELINE_GUARDED_BINARIES)} and the "
        f"image's guard loop names {sorted(named)}"
    )
    assert len(set(PIPELINE_GUARDED_BINARIES)) == len(PIPELINE_GUARDED_BINARIES)


# --- the api entrypoint, run --------------------------------------------------

ENTRYPOINT = REPO / "docker" / "api-entrypoint.sh"


def run_entrypoint(tmp_path: Path, nproc: int, **environ: str) -> list[str]:
    """The entrypoint under `sh`, with gunicorn and nproc stood in for.

    It ends in `exec gunicorn ...`, so a stub named gunicorn that prints its
    own argv is the whole of the harness. `nproc` is stubbed as well, because
    what the count must *not* follow is the host this test runs on.
    """
    if shutil.which("sh") is None:  # pragma: no cover - there is always a shell
        pytest.skip("no POSIX shell")
    stubs = tmp_path / "bin"
    stubs.mkdir(exist_ok=True)
    (stubs / "gunicorn").write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
    (stubs / "nproc").write_text(f"#!/bin/sh\necho {nproc}\n")
    for stub in ("gunicorn", "nproc"):
        (stubs / stub).chmod(0o755)
    finished = subprocess.run(
        ["sh", str(ENTRYPOINT)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": f"{stubs}:{os.environ['PATH']}", **environ},
    )
    assert finished.returncode == 0, finished.stderr
    return finished.stdout.split("\n")


def workers_of(argv: list[str]) -> int:
    assert "--workers" in argv, argv
    return int(argv[argv.index("--workers") + 1])


def test_the_api_entrypoint_uses_the_worker_count_compose_hands_it(tmp_path) -> None:
    """`compose.yaml` sets `WEB_CONCURRENCY` on the api service from `.env`, and
    that is the value the operator can change. If the script derived one anyway
    the variable would be decoration."""
    argv = run_entrypoint(tmp_path, nproc=64, WEB_CONCURRENCY="3")
    assert workers_of(argv) == 3, argv


def test_the_api_entrypoint_derives_its_fallback_from_a_cpu_budget(tmp_path) -> None:
    """The fallback, for a container run by hand with no WEB_CONCURRENCY.

    `nproc` reports the *host*: a compose `cpus:` limit is a cgroup quota and
    does not change it, so on PLAN:293's 8-vCPU box the old `nproc * 2 + 1` was
    17 sync gunicorn workers - 17 full Django processes - inside the api's 2 GB
    limit. The script reads `/sys/fs/cgroup/cpu.max` first and falls through to
    `nproc` only when there is no quota, which is the case where the container
    really does have the machine.

    The expected figure is computed from whichever of the two applies *here*,
    because a test box may or may not be under a quota of its own; the stub
    `nproc` is deliberately absurd so that a script that ignored the quota
    would be obvious.
    """
    quota = Path("/sys/fs/cgroup/cpu.max")
    cores = 64
    if quota.exists():
        allowance, _, period = quota.read_text().strip().partition(" ")
        if allowance != "max":
            cores = max(1, -(-int(allowance) // int(period)))
    argv = run_entrypoint(tmp_path, nproc=64)
    assert workers_of(argv) == 2 * cores + 1, argv


def cpu_max_stub(tmp_path: Path, contents: str) -> str:
    """A stand-in for `/sys/fs/cgroup/cpu.max`, handed to the script by path.

    The box this suite runs on is usually under no cgroup v2 cpu quota at all,
    so the entrypoint's quota branch is unreachable here unless it is pointed
    somewhere a test can write - which is what `CGROUP_CPU_MAX_FILE` is for.
    """
    path = tmp_path / "cpu.max"
    path.write_text(f"{contents}\n")
    return str(path)


@pytest.mark.parametrize(
    ("cpu_max", "workers", "why"),
    [
        ("200000 100000", 5, "two whole cores: 2 * 2 + 1"),
        ("150000 100000", 5, "one and a half cores round UP to two, not down to one"),
        ("50000 100000", 3, "half a core rounds up to one"),
        ("0 100000", 3, "a degenerate zero quota is floored at one core, not zero"),
        ("max 100000", 129, "no quota at all: the host's nproc, stubbed at 64"),
    ],
)
def test_the_api_entrypoint_worker_count_follows_the_cgroup_quota(
    tmp_path, cpu_max: str, workers: int, why: str
) -> None:
    """The fallback worker count, *run* against a quota file rather than read.

    This is the test that holds the cgroup branch up. `nproc` is stubbed at an
    absurd 64 - 129 workers, the OOM-kill figure PLAN:293's 8-vCPU host used to
    produce - so a script that stopped consulting the quota, or never called
    the function, lands on 129 and every quota case below fails at once.

    The arithmetic is `2 * cores + 1` over cores = ceil(quota / period), and
    both ends of that rounding are pinned: 1.5 cores is worth two cores' worth
    of workers, and half a core is still worth one.
    """
    argv = run_entrypoint(tmp_path, nproc=64, CGROUP_CPU_MAX_FILE=cpu_max_stub(tmp_path, cpu_max))
    assert workers_of(argv) == workers, f"{cpu_max!r} ({why}): {argv}"


def test_the_api_entrypoint_ignores_an_unreadable_quota_file(tmp_path) -> None:
    """A cgroup v1 host, or a namespace that does not expose the file at all,
    falls through to `nproc` rather than failing to start."""
    argv = run_entrypoint(
        tmp_path, nproc=4, CGROUP_CPU_MAX_FILE=str(tmp_path / "absent" / "cpu.max")
    )
    assert workers_of(argv) == 9, argv


def test_the_api_entrypoint_reads_the_cgroup_quota_before_nproc() -> None:
    """The ordering, in the text, because the box this suite runs on decides
    which of the two branches the test above actually exercises."""
    body = ENTRYPOINT.read_text()
    assert "/sys/fs/cgroup/cpu.max" in body, (
        "the entrypoint no longer looks at the container's cpu quota, so its fallback is "
        "the host's core count again"
    )
    assert body.index("/sys/fs/cgroup/cpu.max") < body.index("$(nproc)"), (
        "the entrypoint reads nproc before the cgroup quota; nproc reports the host and "
        "is the answer only when there is no quota at all"
    )


def test_the_api_default_command_is_the_wsgi_application_settings_names() -> None:
    """PLAN.md:64 puts the API under gunicorn. The application path is in
    settings as `WSGI_APPLICATION`, so the entrypoint is held to that rather
    than to a string written twice.

    Read out of the settings text rather than by importing Django, so this test
    costs no database and no KEY_ENCRYPTION_KEY.
    """
    settings = (REPO / "src" / "config" / "settings.py").read_text()
    declared = re.search(r'^WSGI_APPLICATION\s*=\s*"([^"]+)"', settings, re.MULTILINE)
    assert declared, "settings.py declares no WSGI_APPLICATION"
    module, _, attribute = declared.group(1).rpartition(".")

    entrypoint = (REPO / "docker" / "api-entrypoint.sh").read_text()
    assert f"gunicorn {module}:{attribute}" in entrypoint, (
        f"the api entrypoint does not run gunicorn against {module}:{attribute}, "
        f"which is what settings.WSGI_APPLICATION names"
    )

    dockerfile = Dockerfile(REPO / "docker" / "api.Dockerfile")
    cmds = dockerfile.of("CMD")
    assert len(cmds) == 1 and "routemaker-api" in cmds[0][1], (
        f"the api image's CMD is not the entrypoint script: {cmds}"
    )


def test_the_api_image_puts_the_source_tree_on_pythonpath_under_its_workdir() -> None:
    """The layout is part of the settings contract, and it is spelled in two
    places that have to agree.

    `settings.py` computes `BASE_DIR = Path(__file__).resolve().parents[2]`, so
    `config` has to be imported from the repository layout under `<WORKDIR>/src`
    and not from site-packages. Both halves are written as absolutes in the
    Dockerfile - `WORKDIR /app` and `ENV PYTHONPATH=/app/src` - with nothing
    holding the second to the first, so moving the WORKDIR leaves PYTHONPATH
    naming a directory the COPY no longer writes to, and every import of
    `config` or `core` fails at container start.

    Both sides are read out of the Dockerfile, so this asserts the agreement
    rather than the literal `/app/src`.
    """
    dockerfile = Dockerfile(REPO / "docker" / "api.Dockerfile")

    environment: dict[str, str] = {}
    for _, rest in dockerfile.of("ENV"):
        for token in dockerfile.expand(rest).split():
            name, sep, value = token.partition("=")
            if sep:
                environment[name] = value

    workdir = dockerfile.final_workdir
    assert workdir != "/", "the api image sets no WORKDIR"
    assert "PYTHONPATH" in environment, "the api image sets no PYTHONPATH"
    assert environment["PYTHONPATH"] == f"{workdir.rstrip('/')}/src", (
        f"PYTHONPATH is {environment['PYTHONPATH']!r} but WORKDIR is {workdir!r}: "
        "the source tree is copied under the WORKDIR, so PYTHONPATH has to name it there"
    )

    # And the directory it names is the one `COPY src` actually writes to,
    # rather than a path with nothing at it.
    destinations = {destination for sources, destination in dockerfile.copies() if "src" in sources}
    landed = {
        d if d.startswith("/") else f"{workdir.rstrip('/')}/{d.lstrip('./')}" for d in destinations
    }
    assert environment["PYTHONPATH"] in landed, (
        f"nothing copies the source tree to {environment['PYTHONPATH']}; copies land at {landed}"
    )


def test_the_dockerignore_keeps_the_host_virtualenv_and_env_out_of_the_context() -> None:
    """.venv carries host-absolute shebangs and .env carries the deployment's
    real secrets. Everything else in the file is weight."""
    ignored = {
        line.strip()
        for line in (REPO / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    required = {".venv", ".env", ".git", "node_modules", "tests", "*.py[cod]", "data", "tiles"}
    assert required <= ignored, f".dockerignore is missing: {sorted(required - ignored)}"


def test_no_pulled_image_floats() -> None:
    """The rule the list above is written to, rather than a property of how it
    happens to be spelled today. `latest` is a moving target and a bare name
    with no tag is `latest` written shorter; either one makes the deployed stack
    a function of when it was pulled."""
    floating = sorted(
        image for image in EXTERNAL_IMAGES if ":" not in image or image.endswith(":latest")
    )
    assert not floating, f"external images that are not pinned: {floating}"
    named = {service["image"] for service in SERVICES.values()}
    assert EXTERNAL_IMAGES <= named, (
        f"this list has drifted from compose.yaml: {sorted(EXTERNAL_IMAGES - named)}"
    )


def test_the_data_root_is_prepared_for_the_uid_the_images_run_as() -> None:
    """One number, written in three files, and nothing held them together.

    `scripts/prepare_data_root.sh` chowns the bind-mount sources to a uid by
    number - the account exists inside the images and need not exist on the
    host - and both Dockerfiles declare that account with `USER`. Get them out
    of step and the script runs clean, the stack comes up, and every write into
    a bound directory fails with EACCES: the rebuild cannot stage tiles, the
    api cannot collect static, and the failure surfaces as a permission error
    from inside a container rather than as anything naming this script.

    Read from all three files rather than restated here, so the uid can be
    changed in one place only by changing it in all of them.
    """
    users = set()
    for path in sorted(set(BUILT.values())):
        declared = Dockerfile(path).of("USER")
        assert declared, f"{path.name} declares no USER and would run as root"
        users.add(declared[-1][1].strip())
    assert len(users) == 1, f"the images run as different accounts: {sorted(users)}"

    uid, _, gid = users.pop().partition(":")
    assert uid.isdigit() and gid.isdigit(), "USER is by number, as the script's comment says"

    script = (REPO / "scripts" / "prepare_data_root.sh").read_text()
    chowned = set(re.findall(r"^\s*chown\s+-R\s+(\d+):(\d+)\s", script, re.MULTILINE))
    assert chowned, "prepare_data_root.sh no longer chowns anything"
    assert chowned == {(uid, gid)}, (
        f"prepare_data_root.sh chowns to {sorted(chowned)} while the images run as "
        f"{uid}:{gid}; every write into a bound directory would fail with EACCES"
    )
    assert f"uid {uid}" in script, "the message it prints names a different uid than it sets"


# The gunicorn access-log atoms that carry a query string, and therefore carry
# a Discord id out of an admin search and into the container log. Read off
# gunicorn 26.2.0's own `glogging.Logger.atoms` - the version
# `docker/requirements-api.txt` pins:
#
#   'r' -> "%s %s %s" % (REQUEST_METHOD, RAW_URI, SERVER_PROTOCOL)   <- RAW_URI
#   'q' -> QUERY_STRING
#   'f' -> HTTP_REFERER
#
# `f` belongs here and is the one that is easy to miss: `settings.py` sets
# SECURE_REFERRER_POLICY = "same-origin", so a browser following a link away
# from `?q=<discord id>` sends that whole URL as the Referer. Both of the first
# two are in gunicorn's default format, which is what the entrypoint used.
QUERY_BEARING_LOG_ATOMS = {"%(r)s": "RAW_URI", "%(q)s": "QUERY_STRING", "%(f)s": "HTTP_REFERER"}


def access_log_format() -> str:
    """The `--access-logformat` argument the entrypoint gives gunicorn."""
    body = ENTRYPOINT.read_text()
    match = re.search(r"--access-logformat\s+'([^']*)'", body)
    assert match, (
        "docker/api-entrypoint.sh sets no --access-logformat, so gunicorn uses its "
        "default - which logs the request line and the Referer, both of which carry an "
        "admin search's query string"
    )
    return match.group(1)


def test_the_access_log_keeps_the_query_string_out_of_the_container_log() -> None:
    """The admin's user and instance-admin listings search by Discord id.

    gunicorn's default access line is the request line and the Referer, so
    every such search wrote the id it searched for into a file under
    /var/lib/docker/containers - read by whoever can read the host, rather than
    by whoever the admin admits. The path is what is worth logging and the
    query string is not.
    """
    fmt = access_log_format()
    present = {atom: source for atom, source in QUERY_BEARING_LOG_ATOMS.items() if atom in fmt}
    assert not present, (
        f"the access-log format is {fmt!r}, which logs {present} - each of those carries "
        "the query string of an admin search"
    )
    assert "%(U)s" in fmt, (
        f"the access-log format is {fmt!r} and names no path atom; %(U)s is PATH_INFO, "
        "the request line without its query string"
    )
    assert "%(s)s" in fmt, f"the access-log format logs no status: {fmt!r}"


def test_the_access_log_format_is_one_argument_gunicorn_parses(tmp_path) -> None:
    """Run, not read: the entrypoint under `sh` with gunicorn stood in for, so
    a quoting mistake in that line is a failure here rather than an api
    container that will not start."""
    argv = run_entrypoint(tmp_path, nproc=4, WEB_CONCURRENCY="2")
    assert "--access-logformat" in argv, argv
    assert argv[argv.index("--access-logformat") + 1] == access_log_format(), (
        f"the shell splits the format into more than one argument: {argv}"
    )
