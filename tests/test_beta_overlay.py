"""The private-beta tooling (FOLLOWUP-BETA-DEPLOY, OWNER-DECISIONS 360-362).

Covers compose.beta.yaml and its checker, the nginx template and its renderer, and
the scripts under scripts/beta/. Nothing here touches a live stack, a server or the
network; the compose render needs `docker compose config` (which starts nothing) and
is skipped without docker. The front end's banner has its own tests
(frontend/src/lib/betaBanner.test.ts).
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import check_beta_compose as beta  # noqa: E402

BETA_SCRIPTS = sorted((REPO / "scripts" / "beta").glob("*.sh"))
TEMPLATE = (REPO / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
CADDYFILE = (REPO / "Caddyfile").read_text()


class ComposeLoader(yaml.SafeLoader):
    """safe_load plus compose's `!reset` and `!override` merge tags (compose.beta.yaml uses
    `ports: !reset []` on caddy), read as the plain value they carry."""


def _compose_tag(loader: yaml.SafeLoader, node: yaml.Node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


for _tag in ("!reset", "!override"):
    ComposeLoader.add_constructor(_tag, _compose_tag)

OVERLAY = yaml.load((REPO / "compose.beta.yaml").read_text(), Loader=ComposeLoader)  # noqa: S506
BASE = yaml.safe_load((REPO / "compose.yaml").read_text())

needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
needs_sh = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")


def run(
    *args: str, env: dict | None = None, cwd: Path = REPO, stdin: str | None = None
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        args, cwd=cwd, env=full_env, capture_output=True, text=True, input=stdin, check=False
    )


# --- the overlay, rendered ---


@pytest.fixture(scope="module")
def rendered() -> dict:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    return beta.render()


def compose_version() -> str:
    done = run("docker", "compose", "version")
    return (done.stdout + done.stderr).strip()


@pytest.fixture(scope="module")
def semantics() -> str:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    return beta.bind_semantics()


@needs_docker
def test_the_overlay_renders_and_passes_the_beta_checker(rendered: dict, semantics: str) -> None:
    problems = beta.check(rendered, beta.DUMMY_ENV["DATA_ROOT"], semantics)
    assert not problems, (compose_version(), semantics, problems)


@needs_docker
def test_this_compose_renders_create_host_path_in_a_known_scheme(semantics: str) -> None:
    """Re-check CI failure: Compose v5.3.1 renders false explicitly, an older Compose drops it (and
    renders the short form's true instead). Either is readable; anything else must stop."""
    assert semantics in beta.BIND_SEMANTICS, compose_version()


@needs_docker
def test_caddy_and_rebuild_are_not_in_the_rendered_stack(rendered: dict) -> None:
    assert set(rendered["services"]) == beta.EXPECTED_SERVICES


@needs_docker
def test_the_only_published_port_is_the_apis_on_loopback(rendered: dict) -> None:
    published = {n: s["ports"] for n, s in rendered["services"].items() if s.get("ports")}
    assert list(published) == ["api"]
    (port,) = published["api"]
    assert port["host_ip"] == "127.0.0.1"
    assert str(port["target"]) == "8000"
    assert str(port["published"]) == "8087"  # the default; BETA_API_PORT overrides it


@needs_docker
def test_the_resident_total_is_about_six_point_nine_gib_and_the_peak_counts_the_one_shot(
    rendered: dict,
) -> None:
    services = rendered["services"]
    assert beta.resident_bytes(services) == 7102 * 1024**2  # compose.beta.yaml's header
    assert beta.peak_bytes(services) == (7102 + 256) * 1024**2  # plus migrate, the largest one-shot
    assert beta.resident_bytes(services) / 1024**3 <= beta.MAX_RESIDENT_GB


@needs_docker
def test_the_offroad_placeholder_is_off_by_default_and_busts_the_budget_when_on() -> None:
    plain = beta.render()
    assert "valhalla-offroad" not in plain["services"]
    with_offroad = beta.render(offroad=True)
    assert "valhalla-offroad" in with_offroad["services"]
    assert any("resident total" in p for p in beta.check(with_offroad)), (
        "adding the off-road router must force a decision about the other caps"
    )


@needs_docker
def test_gunicorn_workers_and_the_paused_rebuild_cannot_be_undone_from_dot_env() -> None:
    """compose.beta.yaml writes WEB_CONCURRENCY from BETA_WEB_CONCURRENCY, so a WEB_CONCURRENCY=7
    line in .env
    (the base file's setting) does not reach the api."""
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile("w", suffix=".env") as env_file:
        env_file.write("WEB_CONCURRENCY=7\n")
        env_file.flush()
        done = run(
            "docker",
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.beta.yaml",
            "--env-file",
            env_file.name,
            "config",
            env={**beta.DUMMY_ENV, "PATH": os.environ["PATH"]},
        )
    assert done.returncode == 0, done.stderr
    api = yaml.safe_load(done.stdout)["services"]["api"]["environment"]
    assert api["WEB_CONCURRENCY"] == "6"
    assert api["WEEKLY_REBUILD_PAUSED"] == "1"


def test_the_overlay_parks_caddy_and_rebuild_behind_a_profile_and_caps_them_tiny() -> None:
    for name in ("caddy", "rebuild"):
        service = OVERLAY["services"][name]
        assert service["profiles"] == ["not-in-beta"]
        assert service["restart"] == "no"
        cap = beta.parse_bytes(service["deploy"]["resources"]["limits"]["memory"])
        assert (
            cap <= 256 * 1024**2 and float(service["deploy"]["resources"]["limits"]["cpus"]) <= 0.25
        )
        assert beta.parse_bytes(service["memswap_limit"]) == cap


@needs_docker
def test_a_parked_service_started_anyway_gets_the_tiny_caps_and_no_port() -> None:
    """The backstop for a slipped `run rebuild`: what compose would really give it."""
    done = run(
        "docker",
        "compose",
        "-f",
        "compose.yaml",
        "-f",
        "compose.beta.yaml",
        "--env-file",
        "/dev/null",
        "--profile",
        "not-in-beta",
        "config",
        env={**beta.DUMMY_ENV, "PATH": os.environ["PATH"]},
    )
    assert done.returncode == 0, done.stderr
    services = yaml.safe_load(done.stdout)["services"]
    rebuild, caddy = services["rebuild"], services["caddy"]
    assert beta.parse_bytes(rebuild["deploy"]["resources"]["limits"]["memory"]) == 256 * 1024**2
    assert float(rebuild["deploy"]["resources"]["limits"]["cpus"]) == 0.25
    assert not caddy.get("ports"), "caddy must not grab 80/443 from the host's nginx"
    for service in (rebuild, caddy):
        assert service["restart"] == "no" and service["oom_score_adj"] == 500
    # re-check spec SF1: the one service that takes rebuild jobs is paused too
    assert rebuild["environment"]["WEEKLY_REBUILD_PAUSED"] == "1"


def test_photons_command_differs_from_the_base_only_in_the_jvm_flags() -> None:
    """The overlay restates the whole command to change the JVM flags; if the base moves, this
    fails."""
    base = BASE["services"]["photon"]["command"]
    mine = OVERLAY["services"]["photon"]["command"]
    assert base[:2] == mine[:2]
    heap = re.compile(r"-Xm[sx][0-9]+[mg]")
    extra = " -XX:MaxDirectMemorySize=192m -XX:+ExitOnOutOfMemoryError"
    assert extra in mine[2]
    assert heap.sub("-XmX", base[2]) == heap.sub("-XmX", mine[2].replace(extra, ""))
    assert heap.findall(mine[2]) == ["-Xms512m", "-Xmx896m"]


def test_photons_heap_direct_buffers_and_native_rest_fit_its_cap() -> None:
    cap_mb = beta.parse_bytes(OVERLAY["services"]["photon"]["memswap_limit"]) / 1024**2
    assert 896 + 192 + beta.PHOTON_OTHER_NATIVE_MB <= cap_mb == 1300


def test_every_overridden_service_exists_in_the_base() -> None:
    placeholder = {"valhalla-offroad"}
    assert set(OVERLAY["services"]) - placeholder <= set(BASE["services"])


# --- the checker catches what it exists to catch ---


PHOTON_XX = "-XX:MaxDirectMemorySize=192m -XX:+ExitOnOutOfMemoryError"


def good() -> dict:
    def svc(mem_mb: int, cpus: str = "1", one_shot: bool = False, **extra) -> dict:
        return {
            "deploy": {"resources": {"limits": {"memory": f"{mem_mb}M", "cpus": cpus}}},
            "memswap_limit": f"{mem_mb}M",
            "cpu_shares": 512,
            "oom_score_adj": 500,
            "restart": "no" if one_shot else "unless-stopped",
            **extra,
        }

    routers = {
        f"valhalla-{v}": svc(
            768, "2", command=["valhalla_service", f"/conf/valhalla-{v}.json", "2"]
        )
        for v in ("standard", "no-trail", "ebike", "weekend")
    }
    return {
        "services": {
            "api": svc(
                1450,
                "2",
                environment={"WEB_CONCURRENCY": "6", "WEEKLY_REBUILD_PAUSED": "1"},
                ports=[{"host_ip": "127.0.0.1", "published": "8087", "target": 8000}],
            ),
            "worker": svc(256, "0.5", environment={"WEEKLY_REBUILD_PAUSED": "1"}),
            "migrate": svc(256, "0.5", one_shot=True, environment={"WEEKLY_REBUILD_PAUSED": "1"}),
            "postgis": svc(1024, "1.5", command=["postgres", "-c", "shared_buffers=256MB"]),
            "photon": svc(
                1300,
                "1",
                command=["sh", "-c", f"exec java -Xms512m -Xmx896m {PHOTON_XX} -jar photon.jar"],
            ),
            **routers,
        }
    }


def problems_for(mutate) -> list[str]:
    compose = copy.deepcopy(good())
    mutate(compose["services"])
    return beta.check(compose)


def test_the_synthetic_good_stack_passes() -> None:
    assert beta.check(good()) == []


@pytest.mark.parametrize(
    ("mutate", "expect"),
    [
        (lambda s: s.update(caddy=copy.deepcopy(s["worker"])), "caddy: must not be part"),
        (lambda s: s.update(rebuild=copy.deepcopy(s["worker"])), "rebuild: must not be part"),
        (lambda s: s.pop("photon"), "photon: missing"),
        (
            lambda s: s.update(extra=copy.deepcopy(s["worker"])),
            "extra: not a service the beta expects",
        ),
        (
            lambda s: s["worker"]["deploy"]["resources"]["limits"].pop("memory"),
            "worker: no memory limit",
        ),
        (
            lambda s: s["worker"]["deploy"]["resources"]["limits"].pop("cpus"),
            "worker: no CPU limit",
        ),
        (lambda s: s["worker"].pop("memswap_limit"), "worker: no memswap_limit"),
        (lambda s: s["worker"].update(memswap_limit="2G"), "worker: memswap_limit"),
        (lambda s: s["photon"].update(ports=["2322:2322"]), "photon: publishes a port"),
        (lambda s: s["api"].update(ports=["8087:8000"]), "not bound to 127.0.0.1"),
        (
            lambda s: s["api"].update(
                ports=[{"host_ip": "0.0.0.0", "published": "8087", "target": 8000}]
            ),
            "not bound to 127.0.0.1",
        ),
        (lambda s: s["api"].pop("ports"), "publishes no port"),
        (
            lambda s: s["api"]["environment"].update(WEB_CONCURRENCY="7"),
            "WEB_CONCURRENCY 7 exceeds",
        ),
        (
            lambda s: s["api"]["environment"].pop("WEEKLY_REBUILD_PAUSED"),
            "api: WEEKLY_REBUILD_PAUSED",
        ),
        (
            lambda s: s["worker"]["environment"].update(WEEKLY_REBUILD_PAUSED="0"),
            "worker: WEEKLY_REBUILD_PAUSED",
        ),
        (
            lambda s: s["photon"].update(
                command=["sh", "-c", f"exec java -Xmx1200m {PHOTON_XX} -jar p.jar"]
            ),
            "photon: -Xmx1200m",
        ),
        (
            lambda s: s["photon"].update(
                command=[
                    "sh",
                    "-c",
                    "exec java -Xmx896m -XX:MaxDirectMemorySize=512m "
                    "-XX:+ExitOnOutOfMemoryError -jar p.jar",
                ]
            ),
            "plus 512 MB direct buffers",
        ),
        (
            lambda s: s["photon"].update(
                command=["sh", "-c", "exec java -Xmx896m -XX:+ExitOnOutOfMemoryError -jar p.jar"]
            ),
            "no -XX:MaxDirectMemorySize",
        ),
        (
            lambda s: s["photon"].update(
                command=["sh", "-c", "exec java -Xmx896m -XX:MaxDirectMemorySize=192m -jar p.jar"]
            ),
            "no -XX:+ExitOnOutOfMemoryError",
        ),
        (
            lambda s: s["api"]["environment"].update(WEB_CONCURRENCY="3"),
            "WEB_CONCURRENCY 3 leaves no worker free",
        ),
        (lambda s: s["api"].update(restart="always"), "api: restart is 'always'"),
        (lambda s: s["api"].update(restart="on-failure"), "api: restart is 'on-failure'"),
        (lambda s: s["photon"].pop("restart"), "photon: restart is None"),
        (lambda s: s["postgis"].pop("cpu_shares"), "postgis: cpu_shares None is not below"),
        (lambda s: s["api"].update(cpu_shares=1024), "api: cpu_shares 1024 is not below"),
        (lambda s: s["worker"].pop("oom_score_adj"), "worker: oom_score_adj None is under 500"),
        (lambda s: s["photon"].update(oom_score_adj=0), "photon: oom_score_adj 0 is under 500"),
        (
            lambda s: s["migrate"]["deploy"]["resources"]["limits"].update(memory="1500M"),
            "startup peak",
        ),
        (
            lambda s: s["photon"].update(command=["sh", "-c", "exec java -jar p.jar"]),
            "sets no -Xmx",
        ),
        (lambda s: s["postgis"].update(command=["postgres"]), "shared_buffers is not set"),
        (
            lambda s: s["postgis"].update(command=["postgres", "-c", "shared_buffers=512MB"]),
            "shared_buffers=512MB is over",
        ),
        (
            lambda s: s["valhalla-ebike"]["deploy"]["resources"]["limits"].update(memory="400M"),
            "valhalla-ebike: 2 workers",
        ),
        (
            lambda s: s["valhalla-ebike"].update(command=["valhalla_service", "/conf/x.json", "8"]),
            "valhalla-ebike: 8 workers",
        ),
        (
            lambda s: s["api"]["deploy"]["resources"]["limits"].update(memory="3G"),
            "exceeds the beta's",
        ),
    ],
)
def test_the_checker_refuses(mutate, expect) -> None:
    found = problems_for(mutate)
    assert any(expect in p for p in found), (expect, found)


LONG_RUNNING = sorted(beta.EXPECTED_SERVICES - beta.ONE_SHOT)


@pytest.mark.parametrize("name", LONG_RUNNING)
def test_the_checker_refuses_restart_no_on_every_long_running_service(name: str) -> None:
    found = problems_for(lambda s: s[name].update(restart="no"))
    assert f"{name}: restart is 'no', not 'unless-stopped'" in " ".join(found), found


def test_the_one_shot_migrate_may_have_restart_no() -> None:
    assert "migrate" in beta.ONE_SHOT and beta.ONE_SHOT == {"migrate"}
    assert problems_for(lambda s: s["migrate"].update(restart="no")) == []


@pytest.mark.parametrize("name", ["api", "worker", "migrate"])
@pytest.mark.parametrize("value", ["1", "true", "True"])
def test_the_checker_refuses_django_debug_on_in_every_django_service(name: str, value: str) -> None:
    """settings.py turns debug on only for "1"; the checker errs closed on other truthy forms."""
    found = problems_for(lambda s: s[name].setdefault("environment", {}).update(DJANGO_DEBUG=value))
    assert f"{name}: DJANGO_DEBUG is {value.lower()!r}" in " ".join(found), found


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_the_checker_allows_django_debug_off(value: str) -> None:
    assert problems_for(lambda s: s["api"]["environment"].update(DJANGO_DEBUG=value)) == []


def test_the_checker_refuses_renderer_and_bot() -> None:
    for name in ("renderer", "bot"):
        found = problems_for(lambda s, n=name: s.update({n: copy.deepcopy(s["worker"])}))
        assert f"{name}: must not be part of the beta stack" in " ".join(found), found
    assert beta.OPTIONAL_SERVICES == {"valhalla-offroad"}


# --- the memory rules at their boundaries (final review, mutation NIT 1: M6-M18) ---


def test_the_memory_constants_are_the_reviewed_figures() -> None:
    assert beta.HOST_AVAILABLE_GB == 8.6
    assert beta.MAX_RESIDENT_GB == 7.0
    assert beta.PEAK_MARGIN_GB == 1.0
    assert beta.PHOTON_OTHER_NATIVE_MB == 192
    assert beta.POSTGRES_MAX_SHARED_BUFFERS_FRACTION == 0.30
    assert beta.BETA_VALHALLA_PER_WORKER_MEMORY_MB == 300
    assert beta.MAX_GUNICORN_WORKERS == 6


def _cap(service: dict, mb: int) -> None:
    service["deploy"]["resources"]["limits"]["memory"] = f"{mb}M"
    service["memswap_limit"] = f"{mb}M"


@pytest.mark.parametrize(("api_mb", "ok"), [(1516, True), (1517, False)])
def test_the_resident_ceiling_is_exactly_seven_gib(api_mb: int, ok: bool) -> None:
    # good() is 7102 MiB resident with a 1450M api; 7168 MiB is 7.0 GiB exactly
    found = problems_for(lambda s: _cap(s["api"], api_mb))
    assert (not any("resident total" in p for p in found)) is ok, found


@pytest.mark.parametrize(("migrate_mb", "ok"), [(680, True), (681, False)])
def test_the_startup_peak_leaves_exactly_one_gib(migrate_mb: int, ok: bool) -> None:
    # 7102 MiB resident + the one-shot must stay within 8.6 - 1.0 GiB = 7782.4 MiB
    found = problems_for(lambda s: _cap(s["migrate"], migrate_mb))
    assert (not any("startup peak" in p for p in found)) is ok, found


@pytest.mark.parametrize(("photon_mb", "ok"), [(1280, True), (1279, False)])
def test_photons_heap_buffers_and_native_rest_must_fit_its_cap_exactly(
    photon_mb: int, ok: bool
) -> None:
    # -Xmx896m + 192m direct + 192 MB other native = 1280 MB
    found = problems_for(lambda s: _cap(s["photon"], photon_mb))
    assert (not any("other native memory exceeds" in p for p in found)) is ok, found


@pytest.mark.parametrize(("buffers", "ok"), [("307MB", True), ("308MB", False)])
def test_shared_buffers_may_take_at_most_thirty_percent_of_the_cap(buffers: str, ok: bool) -> None:
    # 30% of the 1024M cap is 307.2 MB
    command = ["postgres", "-c", f"shared_buffers={buffers}"]
    found = problems_for(lambda s: s["postgis"].update(command=command))
    assert (not any("shared_buffers=" in p for p in found)) is ok, found


def test_the_checker_reads_compose_rendered_byte_counts() -> None:
    assert beta.parse_bytes("1258291200") == 1200 * 1024**2
    assert beta.parse_bytes("768M") == 768 * 1024**2
    assert beta.parse_bytes("1.5G") == int(1.5 * 1024**3)
    assert beta.parse_bytes("768MiB") == 768 * 1024**2


@needs_docker
@pytest.mark.parametrize("offroad", [False, True], ids=["default", "offroad"])
def test_every_bind_the_beta_runs_refuses_to_create_a_missing_source(offroad: bool) -> None:
    """/data is mounted nofail on the server, so Docker can start first: a bind must stop its
    container rather than get an empty directory on the root disk."""
    services = beta.render(offroad=offroad)["services"]
    semantics = beta.bind_semantics()
    binds = {
        name: [v for v in service.get("volumes") or [] if v.get("type") == "bind"]
        for name, service in services.items()
    }
    for name, volumes in binds.items():
        for volume in volumes:
            assert not beta._creates_host_path(volume, semantics), (
                compose_version(),
                semantics,
                name,
                volume,
            )
    counts = {name: len(volumes) for name, volumes in binds.items() if volumes}
    expected = {"api": 2, "worker": 2, "postgis": 1, "photon": 1}
    expected.update({f"valhalla-{g}": 4 for g in ("standard", "no-trail", "ebike", "weekend")})
    if offroad:
        expected["valhalla-offroad"] = 4
    assert counts == expected
    assert not any(
        "would be created empty" in p for p in beta.check({"services": services}, None, semantics)
    )
    assert beta.check_source_binds() == []


@pytest.mark.parametrize(
    ("short", "long_false", "expected"),
    [
        ({}, {"create_host_path": False}, "explicit"),  # Compose v5.3.1 here
        ({"create_host_path": True}, {}, "omit-false"),  # an omitempty bool: CI's Compose
        ({"create_host_path": True}, None, "omit-false"),  # ... with no bind key at all
    ],
)
def test_the_render_scheme_is_read_from_the_probe(short, long_false, expected) -> None:
    long_volume = {"type": "bind", "source": "/rmbeta-probe/long", "target": "/l"}
    if long_false is not None:
        long_volume["bind"] = long_false
    probe = {
        "p": {
            "volumes": [
                {"type": "bind", "source": "/rmbeta-probe/short", "target": "/s", "bind": short},
                long_volume,
            ]
        }
    }
    assert beta.semantics_from_render(probe) == expected


def test_a_render_that_cannot_tell_the_two_forms_apart_is_refused() -> None:
    same = {"type": "bind", "bind": {}}
    probe = {"p": {"volumes": [{**same, "target": "/s"}, {**same, "target": "/l"}]}}
    with pytest.raises(beta.RenderFailed, match="cannot"):
        beta.semantics_from_render(probe)


def test_a_missing_key_means_opposite_things_under_the_two_schemes() -> None:
    absent = {"type": "bind", "source": "/data/routemaker/postgres", "bind": {}}
    assert beta._creates_host_path(absent, "explicit") is True
    assert beta._creates_host_path(absent, "omit-false") is False
    for scheme in beta.BIND_SEMANTICS:
        assert (
            beta._creates_host_path({**absent, "bind": {"create_host_path": False}}, scheme)
            is False
        )
        assert (
            beta._creates_host_path({**absent, "bind": {"create_host_path": True}}, scheme) is True
        )
        assert beta._creates_host_path("/data/routemaker/postgres:/x", scheme) is True


def test_the_source_files_restate_every_bind_with_create_host_path_false(tmp_path: Path) -> None:
    """Read from compose.beta.yaml itself, so it holds whatever the installed Compose renders."""
    assert beta.check_source_binds() == []
    (tmp_path / "compose.yaml").write_text((REPO / "compose.yaml").read_text())
    overlay = (REPO / "compose.beta.yaml").read_text()
    head, services = overlay.split("\nservices:\n", 1)  # past the header's own mentions
    weakened = (
        head
        + "\nservices:\n"
        + services.replace("bind: { create_host_path: false }", "bind: {}", 1)
    )
    assert weakened != overlay
    (tmp_path / "compose.beta.yaml").write_text(weakened)
    found = beta.check_source_binds(tmp_path)
    assert len(found) == 1 and "lacks `bind: { create_host_path: false }`" in found[0], found
    dropped = re.sub(
        r"(?s)(  postgis:.*?)    volumes:\n(?:      .*\n)+?(    memswap_limit)",
        r"\1\2",
        overlay,
        count=1,
    )
    assert dropped != overlay
    (tmp_path / "compose.beta.yaml").write_text(dropped)
    found = beta.check_source_binds(tmp_path)
    assert any(
        "postgis: the base file's bind on /var/lib/postgresql/data is not restated" in p
        for p in found
    ), found


def test_the_runbook_proves_the_binds_on_the_host_and_checks_the_compose_version() -> None:
    step1 = RUNBOOK[RUNBOOK.index("## 1. Prerequisites") : RUNBOOK.index("## 2. Get the code")]
    assert "docker compose version --short" in step1 and "2.40.0" in step1
    step8 = RUNBOOK[RUNBOOK.index("## 8. Start the stack") : RUNBOOK.index("## 9. nginx")]
    assert "LEGACY-BIND=" in step8 and ".BindOptions.CreateMountpoint" in step8
    # re-check 2: both legs pass only on the engine's own error text (ops SF-1), and the start
    # leg covers the late-/data case, a restart with the source gone (correctness SF1)
    assert '[ ! -e "${RM_STATE:?}/no-such-dir" ] && out=$(docker create --mount' in step8  # NIT A
    assert 'case $out in (*"bind source path does not exist"*) echo "PROOF OK (create)' in step8
    assert '&& rm_absent "$RM_STATE/probe-src" && mkdir "$RM_STATE/probe-src"' in step8
    assert 'rmdir "$RM_STATE/probe-src" && out=$(docker start "$id" 2>&1)' in step8
    assert 'echo "PROOF OK (start)' in step8 and '[ -z "$id" ] || docker rm "$id"' in step8
    # re-check 3 SF-A: both legs in one block (a fresh shell per block), so $img is set in both
    proof = [b for b in runbook_blocks() if any("PROOF OK (create)" in x for x in b)]
    assert len(proof) == 1 and any("PROOF OK (start)" in x for x in proof[0])
    assert proof[0][1] == 'cd "$RM_SRC"' and proof[0][2].startswith("img=$(docker inspect")
    assert "the probe did not run before the engine was asked; cleaned up" in step8
    assert "the start failed, but the source came back" in step8
    assert "docker ps -aq --filter label=com.docker.compose.project=routemaker-beta" in step8
    assert 'echo "not created"' not in step8  # the old affirmative line that could pass unrun
    assert "Docker 23 or newer (API 1.42+" in step1  # re-check 2 ops NIT-1
    assert "grep -Eq '^[0-9]+[.][0-9]+'" in step1 and "unreadable compose version" in step1  # NIT-2


def test_the_checker_refuses_a_bind_that_would_create_its_source() -> None:
    root = "/data/routemaker"
    compose = good()
    compose["services"]["postgis"]["volumes"] = [f"{root}/postgres:/var/lib/postgresql/data"]
    found = beta.check(compose, root)
    assert any("postgis: bind /data/routemaker/postgres would be created empty" in p for p in found)
    rendered_short = {
        "type": "bind",
        "source": f"{root}/photon",
        "target": "/photon/data",
        "bind": {},
    }
    compose["services"]["postgis"]["volumes"] = [rendered_short]
    assert any("would be created empty" in p for p in beta.check(compose, root))
    compose["services"]["postgis"]["volumes"] = [
        {**rendered_short, "bind": {"create_host_path": False}}
    ]
    assert beta.check(compose, root) == []
    repo_bind = {"type": "bind", "source": f"{REPO}/valhalla", "target": "/conf", "bind": {}}
    compose["services"]["postgis"]["volumes"] = [repo_bind]
    assert any("would be created empty" in p for p in beta.check(compose, root))


def test_the_runbook_says_what_a_late_data_mount_looks_like_and_never_applies_the_host_fix() -> (
    None
):
    reboot = RUNBOOK[RUNBOOK.index("**Reboot and a late `/data`:**") :]
    reboot = reboot[: reboot.index("\n- **")]
    assert "bind source path does not exist" in reboot
    assert "scripts/beta/beta-compose.sh up -d postgis" in reboot
    assert "After=data.mount" in reboot and "never apply" in reboot
    for command in runbook_commands():
        assert "After=data.mount" not in command and "daemon-reload" not in command, command


def test_the_checker_flags_a_docker_socket_mount() -> None:
    found = problems_for(
        lambda s: s["worker"].update(volumes=["/var/run/docker.sock:/var/run/docker.sock"])
    )
    assert any("Docker socket" in p for p in found)


# --- the nginx template ---


def stage(name: str) -> str:
    match = re.search(rf"# BEGIN stage:{name}\n(.*?)# END stage:{name}\n", TEMPLATE, re.S)
    assert match, name
    return match.group(1)


def locations(block: str) -> list[tuple[str, str]]:
    """Each `location ... { ... }` with its body, by brace matching (only `if` nests here)."""
    out = []
    for m in re.finditer(r"^\s*location\s+([^{]+?)\s*\{", block, re.M):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(block[i], 0)
            i += 1
        out.append((m.group(1).strip(), block[m.end() : i - 1]))
    return out


def test_the_template_has_both_stages_and_no_default_server() -> None:
    assert "# BEGIN stage:acme" in TEMPLATE and "# BEGIN stage:full" in TEMPLATE
    assert "default_server" not in TEMPLATE.replace("no default_server", "")
    assert "server_name @SERVER_NAME@;" in stage("full")


def test_every_http_level_name_is_prefixed_so_it_cannot_collide_with_the_hosts_other_sites() -> (
    None
):
    full = stage("full")
    names = re.findall(r"^(?:upstream\s+(\S+)|map\s+\S+\s+(\$\S+)|log_format\s+(\S+))", full, re.M)
    flat = [n for pair in names for n in pair if n]
    assert flat and all(n.lstrip("$").startswith("rmbeta_") for n in flat), flat
    assert (
        "limit_req_zone" not in full
        and "ssl_session_cache" not in full
        and "ssl_dhparam" not in full
    )


def test_the_access_log_never_records_a_query_string() -> None:
    """A reverse look-up or a search carries a location in its query (OWNER-DECISIONS 395)."""
    full = stage("full")
    fmt = re.search(r"^log_format\s+rmbeta_noquery\s+(.*?);$", full, re.M | re.S)
    assert fmt, "the rmbeta_noquery log format"
    body = fmt.group(1)
    assert "$uri" in body
    # an allowlist, not a denylist: any other variable (a trailing $request, the Authorization
    # header, a cookie, the request body, another way to print the client address) is a leak
    assert set(re.findall(r"\$\w+", body)) == {
        "$time_local",
        "$request_method",
        "$uri",
        "$server_protocol",
        "$status",
        "$body_bytes_sent",
        "$request_time",
    }, body
    leaks = ("$request ", '$request"', "$request_uri", "$args", "$query_string", "$http_referer")
    for leak in leaks:
        assert leak not in body, leak
    assert not re.search(r"\$arg_", body)
    # nor who asked: no client address, no tester name, no forwarded address
    for who in ("$remote_addr", "$binary_remote_addr", "$remote_user", "$http_x_forwarded_for"):
        assert who not in body, who
    # no http-level access_log either: another site on the host would inherit it
    before_servers = re.split(r"^server \{", full, flags=re.M)[0]
    assert "access_log" not in re.sub(r"^\s*#.*$", "", before_servers, flags=re.M)
    servers = re.split(r"^server \{", full, flags=re.M)[1:]
    assert len(servers) == 2
    for server in servers:
        logs = re.findall(r"^\s*access_log\s+(.*?);", server, re.M)
        assert logs == ["/var/log/nginx/rmbeta-access.log rmbeta_noquery"], logs


def test_reverse_and_geocode_log_errors_at_crit_only_with_the_api_proxy_settings() -> None:
    """An upstream error line records the request with its query (OWNER-DECISIONS 395)."""
    full = stage("full")
    found = dict(locations(full))
    body = found["~ ^/api/(reverse|geocode|segment-info)/?$"]
    assert re.findall(r"^\s*error_log\s+(.*?);", body, re.M) == [
        "/var/log/nginx/rmbeta-error.log crit"
    ]

    # the regex wins over the prefix location /, and must proxy exactly as it does
    def proxy_lines(text: str) -> list[str]:
        return [ln.strip() for ln in text.splitlines() if ln.strip().startswith("proxy_")]

    assert proxy_lines(body) == proxy_lines(found["/"])
    assert proxy_lines(body)
    # only error_log and proxy_* directives here: no add_header (the server's noindex and HSTS
    # headers must still apply), and nothing that changes who may call it (auth_basic, satisfy,
    # allow, deny) or what is logged (access_log)
    directives = re.findall(r"^\s*([a-z_0-9]+)\b", re.sub(r"^\s*#.*$", "", body, flags=re.M), re.M)
    assert directives
    assert all(d == "error_log" or d.startswith("proxy_") for d in directives), directives
    # every api path the front end sends a query string to is covered by it
    sources = [
        f.read_text() for f in (REPO / "frontend" / "src").rglob("*.ts*") if ".test." not in f.name
    ]
    queried = {m for text in sources for m in re.findall(r"[`\"'}](/api/[a-z-]+)\?", text)}
    assert queried == {"/api/reverse", "/api/geocode", "/api/segment-info"}, queried
    for path in queried:
        assert re.fullmatch(r"/api/(reverse|geocode|segment-info)/?", path), path
    assert not re.fullmatch(r"/api/(reverse|geocode|segment-info)/?", "/api/route")


def test_basic_auth_is_on_for_the_whole_https_server_and_off_only_for_robots_and_acme() -> None:
    full = stage("full")
    https = full[full.index("listen 443") :]
    assert re.search(r'^\s*auth_basic\s+"RouteMaker beta";', https, re.M)
    assert "auth_basic_user_file @HTPASSWD_FILE@;" in https
    exempt = [path for path, body in locations(full) if "auth_basic off" in body]
    assert sorted(exempt) == sorted(
        ["^~ /.well-known/acme-challenge/", "= /robots.txt", "= /rmbeta-401.html"]
    ), exempt
    # the sign-in page is reachable only as the 401's error page, never directly
    page = dict(locations(full))["= /rmbeta-401.html"]
    assert re.search(r"^\s*internal;", page, re.M), page
    assert "error_page 401 /rmbeta-401.html;" in https
    assert "alias @PAGES_DIR@/401.html;" in page


def test_the_back_soon_page_replaces_only_nginxs_own_502_and_stays_behind_the_password() -> None:
    full = stage("full")
    https = full[full.index("listen 443") :]
    assert re.search(r"^\s*error_page 502 /rmbeta-502\.html;", https, re.M)
    # no other status goes there, and the api's own error answers are never swapped for it
    assert re.findall(r"^\s*error_page\b.*$", https, re.M) == [
        "    error_page 401 /rmbeta-401.html;",
        "    error_page 502 /rmbeta-502.html;",
    ]
    assert not re.search(r"^\s*proxy_intercept_errors", full, re.M)
    page = dict(locations(full))["= /rmbeta-502.html"]
    assert re.search(r"^\s*internal;", page, re.M), page
    assert "alias @PAGES_DIR@/502.html;" in page and "auth_basic" not in page
    assert 'add_header Cache-Control "no-store" always;' in page
    assert "default-src 'none'" in page


def test_the_runbook_checks_nginx_can_read_both_pages() -> None:
    runbook = (REPO / "docs" / "BETA-RUNBOOK.md").read_text()
    loop = next(
        ln for ln in runbook.splitlines() if ln.startswith("for f in ") and "401.html" in ln
    )
    assert '"$RM_SRC/deploy/beta/502.html"' in loop


def test_the_back_soon_page_is_small_plain_and_says_what_to_do() -> None:
    page = (REPO / "deploy" / "beta" / "502.html").read_text()
    assert page.startswith("<!doctype html>") and '<html lang="en">' in page
    assert "<title>" in page and "<h1>" in page and "<main>" in page
    assert "Back button" in page and "person who gave you access" in page
    assert "<script" not in page and "http" not in page.replace("http-equiv", "")
    assert len(page) < 2000


def test_the_sign_in_page_is_small_plain_and_names_no_channel() -> None:
    page = (REPO / "deploy" / "beta" / "401.html").read_text()
    assert page.startswith("<!doctype html>") and '<html lang="en">' in page
    assert "<title>" in page and "<h1>" in page and "<main>" in page
    assert "person who gave you access" in page and "lowercase" in page
    assert "<script" not in page and "http" not in page.replace("http-equiv", "")
    assert len(page) < 2000


def test_robots_txt_disallows_everything_and_the_noindex_header_is_everywhere() -> None:
    full = stage("full")
    robots = dict(locations(full))["= /robots.txt"]
    assert 'return 200 "User-agent: *\\nDisallow: /\\n";' in robots
    assert re.search(
        r'^\s*add_header X-Robots-Tag "noindex, nofollow" always;',
        full[full.index("listen 443") :],
        re.M,
    )
    # add_header does not inherit into a location with its own add_header: each must repeat it.
    for block_name in ("acme", "full"):
        for path, body in locations(stage(block_name)):
            if "add_header" in body:
                assert 'X-Robots-Tag "noindex, nofollow"' in body, (block_name, path)
                if (
                    block_name == "full"
                    and "return 403" not in body
                    and "acme-challenge" not in path
                ):
                    assert "Strict-Transport-Security" in body, path


def test_the_proxy_timeouts_are_at_least_sixty_seconds() -> None:
    proxy = dict(locations(stage("full")))["/"]
    for directive in ("proxy_send_timeout", "proxy_read_timeout"):
        seconds = int(re.search(rf"{directive}\s+(\d+)s;", proxy).group(1))
        assert seconds >= 60, directive
    assert "proxy_pass http://rmbeta_api;" in proxy
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in proxy
    assert "proxy_set_header Host $host;" in proxy
    # the api rate-limits on the last X-Forwarded-For entry, so the client's own must not survive
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in proxy


def test_json_is_gzipped() -> None:
    full = stage("full")
    assert re.search(r"^\s*gzip on;", full, re.M)
    assert "application/json" in re.search(r"gzip_types[^;]*;", full).group(0)


def test_the_template_serves_what_the_caddyfile_serves() -> None:
    full = stage("full")
    paths = [p for p, _ in locations(full)]
    for expected in (
        "= /",
        "= /index.html",
        "= /favicon.svg",
        "= /licenses.txt",
        "^~ /assets/",
        "^~ /static/",
        "^~ /basemap/",
        "/",
    ):
        assert expected in paths, expected
    assert "= /basemap/region.pmtiles" in paths
    assert "^~ /basemap/fonts/" in paths and "^~ /basemap/sprites/" in paths
    # the preset redirects are the Caddyfile's, all of them
    caddy_presets = set(re.findall(r"@preset-([a-z-]+) path ", CADDYFILE))
    assert caddy_presets
    nginx_presets = set(re.search(r"location ~ \^/\(([^)]*)\)/\?\$", full).group(1).split("|"))
    assert nginx_presets == caddy_presets
    assert 'return 302 "/#preset=$1";' in full


def test_the_content_security_policy_is_the_caddyfiles_verbatim() -> None:
    caddy_csp = re.search(r'header Content-Security-Policy "([^"]+)"', CADDYFILE).group(1)
    full = stage("full")
    assert (
        f'add_header Content-Security-Policy "{caddy_csp}" always;' in dict(locations(full))["= /"]
    )


def test_the_basemap_is_same_origin_only_with_the_caddyfiles_three_paths() -> None:
    full = stage("full")
    assert 'map "$http_origin|$http_referer" $rmbeta_basemap_foreign' in full
    caddy_allowed = re.search(r"@unlisted not path ([^\n]+)", CADDYFILE).group(1).split()
    assert caddy_allowed == ["/region.pmtiles", "/fonts/*", "/sprites/*"]
    for path, body in locations(full):
        if path.startswith(("= /basemap", "^~ /basemap")):
            assert "if ($rmbeta_basemap_foreign)" in body and "return 403;" in body, path
    assert "return 404;" in dict(locations(full))["^~ /basemap/"]


# --- rendering ---


@needs_sh
def test_rendering_the_full_stage_fills_every_placeholder(tmp_path: Path) -> None:
    out = run(
        "sh",
        "scripts/beta/render-nginx.sh",
        "--stage",
        "full",
        "--env-file",
        "/nonexistent",
        "--cert-fullchain",
        "/etc/letsencrypt/live/routemaker.cieply.com/fullchain.pem",
        "--cert-key",
        "/etc/letsencrypt/live/routemaker.cieply.com/privkey.pem",
        "--tls-options-include",
        "/etc/letsencrypt/options-ssl-nginx.conf",
    )
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert not re.search(r"@[A-Z_]+@", text)
    assert "server_name routemaker.cieply.com;" in text
    assert "server 127.0.0.1:8087;" in text
    assert "root /data/routemaker/frontend;" in text
    assert f"alias {REPO}/deploy/beta/401.html;" in text
    assert f"alias {REPO}/deploy/beta/502.html;" in text
    assert "ssl_certificate     /etc/letsencrypt/live/routemaker.cieply.com/fullchain.pem;" in text
    assert "include /etc/letsencrypt/options-ssl-nginx.conf;" in text
    assert '"~^https://routemaker\\.cieply\\.com\\|" 0;' in text
    assert (
        "BEGIN stage" not in text and "acme" in text
    )  # the ACME location stays in the port-80 server
    assert text.count("{") == text.count("}")


@needs_sh
def test_rendering_without_a_tls_include_drops_that_line_and_reads_env_values(
    tmp_path: Path,
) -> None:
    env = tmp_path / ".env"
    env.write_text("DATA_ROOT=/data/rm-test\nBETA_API_PORT=8123\n")
    out = run(
        "sh",
        "scripts/beta/render-nginx.sh",
        "--stage",
        "full",
        "--env-file",
        str(env),
        "--cert-fullchain",
        "/c/fullchain.pem",
        "--cert-key",
        "/c/privkey.pem",
    )
    assert out.returncode == 0, out.stderr
    assert "server 127.0.0.1:8123;" in out.stdout and "root /data/rm-test/frontend;" in out.stdout
    assert "include " not in out.stdout.split("ssl_protocols")[1].split("# ---")[0]


@needs_sh
def test_rendering_the_acme_stage_has_no_tls_no_auth_and_no_app() -> None:
    out = run("sh", "scripts/beta/render-nginx.sh", "--stage", "acme", "--env-file", "/nonexistent")
    assert out.returncode == 0, out.stderr
    text = out.stdout
    assert "listen 443" not in text and "ssl_certificate" not in text and "proxy_pass" not in text
    assert "acme-challenge" in text and "return 404;" in text
    assert text.count("{") == text.count("}")


@needs_sh
@pytest.mark.parametrize(
    "args",
    [
        ["--stage", "full"],  # no certificate paths
        ["--stage", "bogus"],
        ["--stage", "acme", "--server-name", "a.example; return 200"],
        ["--stage", "acme", "--data-root", "/data"],
        ["--stage", "acme", "--data-root", "relative"],
        ["--stage", "acme", "--api-port", "80x"],
        ["--stage", "acme", "--htpasswd", "/etc/nginx/with space"],
    ],
)
def test_the_renderer_refuses_bad_input(args: list[str]) -> None:
    out = run("sh", "scripts/beta/render-nginx.sh", "--env-file", "/nonexistent", *args)
    assert out.returncode == 2, (args, out.stdout, out.stderr)


@needs_sh
def test_the_renderer_never_overwrites_without_being_told(tmp_path: Path) -> None:
    target = tmp_path / "site.conf"
    target.write_text("keep me")
    out = run(
        "sh",
        "scripts/beta/render-nginx.sh",
        "--stage",
        "acme",
        "--env-file",
        "/nonexistent",
        "--out",
        str(target),
    )
    assert out.returncode == 2 and target.read_text() == "keep me"


# --- the scripts ---


@needs_sh
@pytest.mark.parametrize("script", BETA_SCRIPTS, ids=lambda p: p.name)
def test_every_beta_script_parses_and_shellcheck_is_clean_when_available(script: Path) -> None:
    shell = "sh" if script.read_text().startswith("#!/bin/sh") else "bash"
    assert run(shell, "-n", str(script)).returncode == 0
    if shutil.which("shellcheck"):
        done = run("shellcheck", "--severity=warning", str(script))
        assert done.returncode == 0, done.stdout


@pytest.mark.parametrize("script", BETA_SCRIPTS, ids=lambda p: p.name)
def test_every_beta_script_is_executable(script: Path) -> None:
    assert os.access(script, os.X_OK)


@needs_sh
def test_make_env_writes_a_private_complete_env_and_never_overwrites(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    done = run("sh", "scripts/beta/make-env.sh", "--out", str(target), "--tag", "abc123def456")
    assert done.returncode == 0, done.stderr
    assert (target.stat().st_mode & 0o777) == 0o600
    values = dict(
        line.split("=", 1)
        for line in target.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    for key in ("DJANGO_SECRET_KEY", "KEY_ENCRYPTION_KEY", "PGPASSWORD"):
        assert re.fullmatch(r"[0-9a-f]{64}", values[key]), key
    assert len({values[k] for k in ("DJANGO_SECRET_KEY", "KEY_ENCRYPTION_KEY", "PGPASSWORD")}) == 3
    assert values["TAG"] == "abc123def456" and values["COMPOSE_PROJECT_NAME"] == "routemaker-beta"
    assert values["DATA_ROOT"] == "/data/routemaker" and values["BETA_API_PORT"] == "8087"
    assert "@" not in target.read_text().replace("routemaker.cieply.com", "")
    for secret in (values["PGPASSWORD"], values["DJANGO_SECRET_KEY"]):
        assert secret not in done.stdout and secret not in done.stderr
    again = run("sh", "scripts/beta/make-env.sh", "--out", str(target), "--tag", "x")
    assert again.returncode == 2 and "already exists" in again.stderr


def test_the_env_template_holds_no_secret_and_covers_what_the_base_requires() -> None:
    text = (REPO / "deploy" / "beta" / "env.beta.template").read_text()
    for key in ("DJANGO_SECRET_KEY", "KEY_ENCRYPTION_KEY", "PGPASSWORD"):
        assert f"{key}=@GENERATE@" in text
    assert not re.search(r"^[A-Z_]*(SECRET|TOKEN|PASSWORD|KEY)[A-Z_]*=(?!@GENERATE@|$)", text, re.M)
    for required in (
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DATA_ROOT",
        "TAG",
        "COMPOSE_PROJECT_NAME",
    ):
        assert re.search(rf"^{required}=.+", text, re.M), required


@needs_sh
def test_the_beta_compose_wrapper_refuses_a_bare_up_and_the_services_that_are_not_in_the_beta(
    tmp_path: Path,
) -> None:
    env = tmp_path / ".env"
    env.write_text("COMPOSE_PROJECT_NAME=routemaker-beta\n")
    base = {"BETA_ENV_FILE": str(env)}
    wrapper = "scripts/beta/beta-compose.sh"
    for args, message in [
        (["up", "-d"], "name the services"),
        (["up"], "name the services"),
        (["up", "-d", "caddy"], "caddy is not part of the beta"),
        (["up", "-d", "api", "rebuild"], "rebuild is not part of the beta"),
        (["--profile", "not-in-beta", "up", "-d", "api"], "not-in-beta"),
        (["down", "-v"], "refused"),
        (["down", "--rmi", "all"], "refused"),
        ([], "no compose command"),
    ]:
        done = run("sh", wrapper, *args, env=base)
        assert done.returncode == 2 and message in done.stderr, (args, done.stderr)
    missing = run("sh", wrapper, "ps", env={"BETA_ENV_FILE": str(tmp_path / "nope.env")})
    assert missing.returncode == 2
    no_project = tmp_path / "np.env"
    no_project.write_text("TAG=x\n")
    assert run("sh", wrapper, "ps", env={"BETA_ENV_FILE": str(no_project)}).returncode == 2


@needs_sh
@needs_docker
def test_the_beta_compose_wrapper_passes_a_named_up_through_to_compose(tmp_path: Path) -> None:
    """`config` stands in for `up` (it starts nothing): both files and the env file are added."""
    env = tmp_path / ".env"
    env.write_text(
        "COMPOSE_PROJECT_NAME=routemaker-beta\n"
        + "".join(f"{k}={v}\n" for k, v in beta.DUMMY_ENV.items())
    )
    done = run(
        "sh",
        "scripts/beta/beta-compose.sh",
        "config",
        "--services",
        env={"BETA_ENV_FILE": str(env)},
    )
    assert done.returncode == 0, done.stderr
    assert set(done.stdout.split()) == beta.EXPECTED_SERVICES


@needs_sh
def test_ship_data_refuses_without_a_destination_and_an_unsafe_remote_dir(tmp_path: Path) -> None:
    ship = "scripts/beta/ship-data.sh"
    assert run("bash", ship).returncode == 2
    for remote in ("relative/dir", "/etc", "/data", "/", "/tmp/with space", "/tmp/a;b"):
        done = run("bash", ship, "--live-dir", str(tmp_path), "host", remote)
        assert done.returncode == 2, (remote, done.stderr)
    helped = run("bash", ship, "--help")
    assert helped.returncode == 0 and "READ-ONLY on the live stack" in helped.stdout


SHIP = "scripts/beta/ship-data.sh"


@needs_sh
def test_ship_data_stops_when_no_front_end_source_is_given() -> None:
    """An error, not a warning (final review, accessibility nit): an old dist/ without the
    beta notice must not ship by default."""
    done = run("bash", SHIP, "--no-transfer", "--live-dir", "/nonexistent")
    assert done.returncode == 2 and "give --build-frontend" in done.stderr, done.stderr
    both = run("bash", SHIP, "--build-frontend", "--dist", "/tmp", "--no-transfer")
    assert both.returncode == 2 and "not both" in both.stderr
    skipped = run(
        "bash", SHIP, "--without", "frontend", "--no-transfer", "--live-dir", "/nonexistent"
    )
    assert skipped.returncode == 2 and "cannot read /nonexistent/.env" in skipped.stderr


@needs_sh
@pytest.mark.parametrize(
    "url",
    [
        "http://discord.gg/abc",
        "https:///x",
        "https://",
        "javascript:alert(1)",
        "https://example.org/a b",
        "https://example.org/'",
        'https://example.org/"',
        "https://example.org/<x>",
        "https://user:pw@example.org/",
    ],
)
def test_ship_data_refuses_a_report_url_that_is_not_a_plain_https_address(url: str) -> None:
    done = run(
        "bash", SHIP, "--build-frontend", "--report-url", url, "--no-transfer", "--live-dir", "/x"
    )
    assert done.returncode == 2 and "--report-url" in done.stderr, (url, done.stderr)


@needs_sh
def test_ship_data_bakes_the_report_url_into_a_tested_build_only() -> None:
    """OWNER-DECISIONS 382: the link is an optional build setting; --build-frontend also runs
    the front-end tests on the tree being shipped (accessibility S5)."""
    alone = run("bash", SHIP, "--report-url", "https://discord.gg/abc", "--dist", "/tmp")
    assert alone.returncode == 2 and "needs --build-frontend" in alone.stderr
    ok = run(
        "bash",
        SHIP,
        "--build-frontend",
        "--report-url",
        "https://discord.gg/abc?x=1&y=2",
        "--no-transfer",
        "--live-dir",
        "/nonexistent",
    )
    assert ok.returncode == 2 and "cannot read /nonexistent/.env" in ok.stderr  # got past the URL
    text = (REPO / SHIP).read_text()
    assert '-e VITE_BETA_REPORT_URL="$report_url"' in text
    assert "sh -c 'npm test && npx tsc --noEmit && npx vite build --outDir /out" in text


@needs_sh
def test_ship_data_will_not_stage_inside_the_live_data_root(tmp_path: Path) -> None:
    live = tmp_path / "live"
    data = tmp_path / "data"
    live.mkdir()
    (data / "stage").mkdir(parents=True)
    (live / "compose.yaml").write_text("services: {}\n")
    (live / ".env").write_text(f"DATA_ROOT={data}\n")
    done = run(
        "bash",
        "scripts/beta/ship-data.sh",
        "--live-dir",
        str(live),
        "--stage",
        str(data / "stage"),
        "--no-transfer",
        "--without",
        "db",
        "--without",
        "frontend",
    )
    assert done.returncode == 2 and "inside" in done.stderr, done.stderr
    done = run(
        "bash",
        "scripts/beta/ship-data.sh",
        "--live-dir",
        str(live),
        "--stage",
        str(live / "stage"),
        "--no-transfer",
        "--without",
        "db",
        "--without",
        "frontend",
    )
    assert done.returncode == 2 and "inside" in done.stderr, done.stderr


def _bundle(tmp_path: Path, sha: str | None = None) -> Path:
    """A minimal bundle: one file, its SHA256SUMS and a manifest with no parts to install."""
    bundle = tmp_path / "incoming"
    (bundle / "frontend").mkdir(parents=True)
    (bundle / "frontend" / "index.html").write_text("<html>")
    digest = subprocess.run(
        ["sha256sum", "frontend/index.html"], cwd=bundle, capture_output=True, text=True, check=True
    ).stdout
    (bundle / "SHA256SUMS").write_text(digest)
    head = (
        sha
        or subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    (bundle / "MANIFEST.txt").write_text(
        f"bundle_format=1\ngit_sha={head}\nparts=frontend \nfiles=1\nbytes=6\ncreated_utc=now\n"
    )
    return bundle


@needs_sh
def test_receive_data_verifies_and_catches_tampering_a_missing_manifest_and_a_wrong_sha(
    tmp_path: Path,
) -> None:
    if shutil.which("sha256sum") is None:
        pytest.skip("no sha256sum")
    data = tmp_path / "dr" / "routemaker"
    data.mkdir(parents=True)
    env = tmp_path / ".env"
    env.write_text(f"DATA_ROOT={data}\n")
    bundle = _bundle(tmp_path)
    receive = [
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(bundle),
        "--env-file",
        str(env),
    ]
    assert run(*receive, "verify").returncode == 0

    (bundle / "frontend" / "index.html").write_text("<html>tampered")
    tampered = run(*receive, "verify")
    assert tampered.returncode == 2 and "checksum mismatch" in tampered.stderr
    (bundle / "frontend" / "index.html").write_text("<html>")

    other = _bundle(tmp_path / "x", sha="0" * 40)
    mismatch = run(
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(other),
        "--env-file",
        str(env),
        "verify",
    )
    assert mismatch.returncode == 2 and "check out the same sha" in mismatch.stderr
    allowed = run(
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(other),
        "--env-file",
        str(env),
        "--allow-sha-mismatch",
        "verify",
    )
    assert allowed.returncode == 0

    (bundle / "MANIFEST.txt").unlink()
    unfinished = run(*receive, "verify")
    assert unfinished.returncode == 2 and "did not finish" in unfinished.stderr


@needs_sh
def test_receive_data_installs_the_frontend_and_refuses_a_system_data_root(tmp_path: Path) -> None:
    if shutil.which("rsync") is None or shutil.which("sha256sum") is None:
        pytest.skip("needs rsync and sha256sum")
    data = tmp_path / "dr" / "routemaker"
    data.mkdir(parents=True)
    env = tmp_path / ".env"
    env.write_text(f"DATA_ROOT={data}\n")
    bundle = _bundle(tmp_path)
    (bundle / "frontend" / "assets").mkdir()
    (bundle / "frontend" / "assets" / "app-abc.js").write_text("js")
    sums = subprocess.run(
        "find frontend -type f | sort | xargs sha256sum",
        shell=True,
        cwd=bundle,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (bundle / "SHA256SUMS").write_text(sums)
    done = run(
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(bundle),
        "--env-file",
        str(env),
        "files",
    )
    assert done.returncode == 0, done.stderr
    assert (data / "frontend" / "index.html").read_text() == "<html>"
    assert (data / "frontend" / "assets" / "app-abc.js").read_text() == "js"
    assert not (data / "frontend" / ".index.html.new").exists()

    bad_env = tmp_path / "bad.env"
    bad_env.write_text("DATA_ROOT=/data\n")
    refused = run(
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(bundle),
        "--env-file",
        str(bad_env),
        "files",
    )
    assert refused.returncode == 2 and "system directory" in refused.stderr


@needs_sh
def test_make_htpasswd_refuses_overwrite_and_bad_names(tmp_path: Path) -> None:
    existing = tmp_path / "pw"
    existing.write_text("keep")
    done = run("sh", "scripts/beta/make-htpasswd.sh", "--file", str(existing), "alice")
    assert done.returncode == 2 and existing.read_text() == "keep"
    assert (
        run(
            "sh", "scripts/beta/make-htpasswd.sh", "--file", str(tmp_path / "new"), "bad;name"
        ).returncode
        == 2
    )
    assert (
        run("sh", "scripts/beta/make-htpasswd.sh", "--file", str(tmp_path / "new")).returncode == 2
    )


# --- nothing secret in what this adds ---


def test_nothing_this_adds_carries_a_secret_or_a_real_credential() -> None:
    files = [
        REPO / "compose.beta.yaml",
        REPO / "deploy" / "beta" / "nginx-routemaker.conf.template",
        REPO / "deploy" / "beta" / "env.beta.template",
        REPO / "docs" / "BETA-RUNBOOK.md",
        *BETA_SCRIPTS,
    ]
    for path in files:
        text = path.read_text()
        assert not re.search(r"\$apr1\$", text), f"{path.name} holds an htpasswd hash"
        assert not re.search(r"\$6\$[./0-9A-Za-z]{8,}\$", text), f"{path.name} holds a hash"
        assert not re.search(
            r"(?m)^\s*(?:PGPASSWORD|DJANGO_SECRET_KEY|KEY_ENCRYPTION_KEY)=[0-9a-f]{20,}", text
        ), path.name
        assert "BEGIN PRIVATE KEY" not in text and "BEGIN RSA PRIVATE" not in text, path.name


# --- the wrapper, against a stub docker (review r0 S2: each bypass the reviewer found) ---


@pytest.fixture
def stub_docker(tmp_path: Path) -> tuple[dict, Path]:
    """A `docker` that only records its arguments, so nothing can start."""
    calls = tmp_path / "calls"
    stub = tmp_path / "docker"
    stub.write_text(f'#!/bin/sh\necho "$*" >> {calls}\n')
    stub.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=routemaker-beta\n")
    env = {"BETA_ENV_FILE": str(env_file), "DOCKER": str(stub)}
    for var in ("COMPOSE_PROFILES", "COMPOSE_FILE", "COMPOSE_PROJECT_NAME"):
        env[var] = ""
    return env, calls


def wrapper(env: dict, *args: str) -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    full.update({k: v for k, v in env.items() if v != ""})
    return subprocess.run(
        ["sh", "scripts/beta/beta-compose.sh", *args],
        cwd=REPO,
        env=full,
        capture_output=True,
        text=True,
        check=False,
    )


@needs_sh
@pytest.mark.parametrize(
    "args",
    [
        ["run", "--rm", "rebuild"],
        ["run", "--service-ports", "caddy"],
        ["create", "caddy"],
        ["start", "rebuild"],
        ["restart", "caddy"],
        ["pull", "rebuild"],
        ["build", "rebuild"],
        ["exec", "rebuild", "sh"],
        ["up", "-d", "--pull", "never"],
        ["up", "-d", "--wait-timeout", "30"],
        ["up", "-t", "10"],
        ["create"],
        ["-p", "other", "up", "-d", "api"],
        ["--project-name", "other", "up", "-d", "api"],
        ["--project-name=other", "ps"],
        ["-f", "other.yaml", "up", "-d", "api"],
        ["--env-file", "/tmp/x.env", "ps"],
        ["--profile", "*", "up", "-d", "api"],
        ["--profile=*", "up", "-d", "api"],
        ["--profile", "not-in-beta", "ps"],
        ["up", "-d", "--scale", "api=2", "api"],
        ["up", "-d", "--attach=caddy", "api"],
        ["run", "-p", "80:8000", "api"],
        ["rm", "-v"],
        # review r1, N5: short-option clusters and the hidden --workdir alias
        ["up", "-dt", "5"],
        ["rm", "-fsv"],
        ["down", "-tv", "5"],
        ["--workdir", "/tmp", "up", "-d"],
        ["--workdir=/tmp", "ps"],
        # final review, mutation NIT 1: refusals that had no row of their own
        ["up", "-d", "renderer"],
        ["run", "--rm", "bot"],
        ["up", "-d", "not-in-beta"],
        ["--project-directory", "/tmp", "up", "-d", "api"],
        ["--project-directory=/tmp", "ps"],
        ["up", "-d", "--scale=api=2", "api"],
        ["down", "--rmi=all"],
        ["rm", "--volumes=true"],
        ["up", "-d", "--no-attach", "worker"],
        ["--ansi", "never", "up", "-d"],
    ],
    ids=lambda a: " ".join(a),
)
def test_the_wrapper_refuses_each_bypass_and_never_calls_docker(stub_docker, args) -> None:
    env, calls = stub_docker
    done = wrapper(env, *args)
    assert done.returncode == 2, (args, done.stdout, done.stderr)
    assert done.stderr.startswith("beta-compose: ")
    assert not calls.exists(), f"docker was called for {args}"


@needs_sh
@pytest.mark.parametrize(
    "args",
    [
        ["up", "-d", "--pull", "never", "postgis"],
        ["up", "-d", "photon", "valhalla-standard", "valhalla-no-trail"],
        ["up", "-d", "-t", "30", "api", "worker"],
        ["--profile", "offroad", "up", "-d", "valhalla-offroad"],
        ["run", "--rm", "--no-deps", "migrate", "./manage.py", "migrate", "--check"],
        ["exec", "-T", "api", "./manage.py", "collectstatic", "--noinput"],
        ["exec", "-T", "api", "ls", "-la", "/data"],
        ["logs", "--tail", "30", "migrate"],
        ["ps", "postgis", "--format", "{{.Health}}"],
        ["stop", "api", "worker"],
        ["config", "--services"],
        ["down"],
    ],
    ids=lambda a: " ".join(a),
)
def test_the_wrapper_passes_the_runbooks_commands_through_with_both_files(
    stub_docker, args
) -> None:
    env, calls = stub_docker
    done = wrapper(env, *args)
    assert done.returncode == 0, (args, done.stderr)
    expected = (
        f"compose -f compose.yaml -f compose.beta.yaml --env-file {env['BETA_ENV_FILE']} "
        + " ".join(args)
    )
    assert calls.read_text().strip() == expected


@needs_sh
@pytest.mark.parametrize(
    "var",
    [
        "COMPOSE_PROFILES",
        "COMPOSE_FILE",
        "COMPOSE_PROJECT_NAME",
        "COMPOSE_PATH_SEPARATOR",
        "COMPOSE_ENV_FILES",
    ],
)
def test_the_wrapper_refuses_compose_settings_from_the_environment_or_dot_env(
    stub_docker, var: str, tmp_path: Path
) -> None:
    env, calls = stub_docker
    done = wrapper({**env, var: "x"}, "ps")
    assert done.returncode == 2 and var in done.stderr and not calls.exists()
    colon = tmp_path / "colon.env"
    colon.write_text("COMPOSE_PROJECT_NAME=routemaker-beta\nCOMPOSE_PROJECT_NAME: routemaker\n")
    done = wrapper({**env, var: "", "BETA_ENV_FILE": str(colon)}, "ps")
    assert done.returncode == 2 and "KEY: value" in done.stderr and not calls.exists()
    if var in ("COMPOSE_PROFILES", "COMPOSE_FILE"):
        dot_env = tmp_path / "with.env"
        dot_env.write_text(f"COMPOSE_PROJECT_NAME=routemaker-beta\n{var}=not-in-beta\n")
        done = wrapper({**env, "BETA_ENV_FILE": str(dot_env)}, "ps")
        assert done.returncode == 2 and not calls.exists()


@needs_sh
@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("RESTART_POLICY", "no"),
        ("RESTART_POLICY", "always"),
        ("RESTART_POLICY", "on-failure"),
        ("DJANGO_DEBUG", "1"),
        ("DJANGO_DEBUG", "0"),  # any non-empty value: it has no business on the beta
        ("DJANGO_DEBUG", "true"),
    ],
)
def test_the_wrapper_refuses_a_restart_policy_or_debug_from_the_environment(
    stub_docker, var: str, value: str
) -> None:
    env, calls = stub_docker
    done = wrapper({**env, var: value}, "ps")
    assert done.returncode == 2 and var in done.stderr and not calls.exists()
    ok = wrapper({**env, "RESTART_POLICY": "unless-stopped"}, "ps")
    assert ok.returncode == 0 and calls.exists()


@needs_sh
@pytest.mark.parametrize(
    "line",
    [
        "RESTART_POLICY=no",
        "RESTART_POLICY=always",
        "RESTART_POLICY=on-failure",
        "RESTART_POLICY=unless-stopped-x",  # re-check mutation NIT 3: a near miss
        'RESTART_POLICY="no"',
        "export RESTART_POLICY=no",
        "RESTART_POLICY: no",
        "RESTART_POLICY = no",
        "\ufeffRESTART_POLICY=no",
        "DJANGO_DEBUG=1",
        "DJANGO_DEBUG=0",
        "DJANGO_DEBUG=True",
        "DJANGO_DEBUG: 1",
        "export DJANGO_DEBUG=1",
    ],
)
def test_the_wrapper_refuses_a_restart_policy_or_debug_in_dot_env(
    stub_docker, tmp_path: Path, line: str
) -> None:
    """Final review (correctness N1, operations SF5, mutation SF1): the wrapper that runs every
    day checks .env itself, not only the gate."""
    env, calls = stub_docker
    path = tmp_path / "bad.env"
    path.write_text(f"COMPOSE_PROJECT_NAME=routemaker-beta\n{line}\n", encoding="utf-8")
    done = wrapper({**env, "BETA_ENV_FILE": str(path)}, "up", "-d", "api")
    key = "RESTART_POLICY" if "RESTART_POLICY" in line else "DJANGO_DEBUG"
    assert done.returncode == 2 and f"sets {key}" in done.stderr, (line, done.stderr)
    assert not calls.exists()


@needs_sh
@pytest.mark.parametrize(
    "line",
    [
        "RESTART_POLICY=",
        "RESTART_POLICY=unless-stopped",
        'RESTART_POLICY="unless-stopped"',
        "RESTART_POLICY=''",
        "DJANGO_DEBUG=",
        "# RESTART_POLICY=no",
        "# DJANGO_DEBUG=1",
    ],
)
def test_the_wrapper_allows_an_empty_or_unless_stopped_restart_policy_and_empty_debug(
    stub_docker, tmp_path: Path, line: str
) -> None:
    env, calls = stub_docker
    path = tmp_path / "ok.env"
    path.write_text(f"COMPOSE_PROJECT_NAME=routemaker-beta\n{line}\n")
    done = wrapper({**env, "BETA_ENV_FILE": str(path)}, "ps")
    assert done.returncode == 0 and calls.exists(), (line, done.stderr)


@needs_sh
def test_the_wrapper_runs_compose_with_a_clean_environment(tmp_path: Path) -> None:
    """A shell variable beats .env in compose's substitution, so compose gets only PATH, HOME,
    DOCKER_HOST and DOCKER_CONFIG: the four the --env-file gate renders with (final review,
    correctness SF2, operations SF5, mutation finding 1)."""
    seen = tmp_path / "seen"
    stub = tmp_path / "docker"
    stub.write_text(f"#!/bin/sh\nenv > {seen}\n")
    stub.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=routemaker-beta\nDATA_ROOT=/data/routemaker\n")
    stray = {"DATA_ROOT": "/elsewhere", "TAG": "other", "BETA_WEB_CONCURRENCY": "12"}
    full = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    full.update(stray, BETA_ENV_FILE=str(env_file), DOCKER=str(stub), DOCKER_HOST="unix:///x.sock")
    full.pop("DOCKER_CONFIG", None)
    done = subprocess.run(
        ["sh", "scripts/beta/beta-compose.sh", "ps"],
        cwd=REPO,
        env=full,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    got = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    for key in stray:
        assert key not in got, key
    assert got["PATH"] == os.environ["PATH"] and got["DOCKER_HOST"] == "unix:///x.sock"
    assert "DOCKER_CONFIG" not in got  # passed only when set
    # ... and passed through when it is set (re-check mutation NIT 1)
    with_config = subprocess.run(
        ["sh", "scripts/beta/beta-compose.sh", "ps"],
        cwd=REPO,
        env={**full, "DOCKER_CONFIG": "/x/cfg"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert with_config.returncode == 0, with_config.stderr
    again = dict(line.split("=", 1) for line in seen.read_text().splitlines() if "=" in line)
    assert again["DOCKER_CONFIG"] == "/x/cfg" and "DATA_ROOT" not in again
    # what the shell running the stub adds itself (PWD, SHLVL, _) is all that may be beside them
    assert set(got) <= {
        "PATH",
        "HOME",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "PWD",
        "OLDPWD",
        "SHLVL",
        "_",
    }
    wrapper_text = (REPO / "scripts" / "beta" / "beta-compose.sh").read_text()
    checker_text = (REPO / "scripts" / "check_beta_compose.py").read_text()
    assert 'exec env -i "PATH=$PATH" "HOME=${HOME:-/}" "$@"' in wrapper_text
    assert '("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG")' in checker_text


# --- the server-side gate: the checker on the server's own .env (S8) ---


def server_env(tmp_path: Path, **overrides: str) -> Path:
    values = {"COMPOSE_PROJECT_NAME": "routemaker-beta", **beta.DUMMY_ENV, **overrides}
    values["DJANGO_SECRET_KEY"] = "SECRET-MARKER-0123456789abcdef"
    path = tmp_path / "server.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return path


def checker(*args: str) -> subprocess.CompletedProcess:
    return run(sys.executable, "scripts/check_beta_compose.py", *args)


@needs_docker
def test_the_env_file_mode_checks_the_servers_env_and_never_prints_a_value(tmp_path: Path) -> None:
    ok = checker("--env-file", str(server_env(tmp_path)))
    assert ok.returncode == 0, ok.stderr
    assert "beta compose: ok" in ok.stdout and "resident total" in ok.stdout
    assert "SECRET-MARKER" not in ok.stdout + ok.stderr
    assert "dummy" not in ok.stdout + ok.stderr


@needs_docker
@pytest.mark.parametrize(
    ("overrides", "expect"),
    [
        ({"BETA_WEB_CONCURRENCY": "12"}, "WEB_CONCURRENCY 12 exceeds"),
        ({"BETA_API_PORT": "0.0.0.0:8087"}, ""),
        ({"COMPOSE_PROFILES": "not-in-beta"}, ".env: COMPOSE_PROFILES"),
        ({"COMPOSE_FILE": "compose.yaml"}, ".env: COMPOSE_FILE"),
        ({"WEB_CONCURRENCY": "7"}, "WEB_CONCURRENCY has no effect"),
        ({"RESTART_POLICY": "no"}, ".env: RESTART_POLICY"),
        ({"RESTART_POLICY": "always"}, ".env: RESTART_POLICY"),
        ({"DJANGO_DEBUG": "1"}, ".env: DJANGO_DEBUG"),
    ],
)
def test_the_env_file_mode_refuses_a_bad_server_env(tmp_path: Path, overrides, expect) -> None:
    done = checker("--env-file", str(server_env(tmp_path, **overrides)))
    assert done.returncode != 0, (overrides, done.stdout)
    assert expect in done.stdout + done.stderr
    assert "SECRET-MARKER" not in done.stdout + done.stderr


@needs_docker
@pytest.mark.parametrize("value", ["", "unless-stopped"])
def test_the_env_file_mode_allows_an_empty_or_unless_stopped_restart_policy(
    tmp_path: Path, value: str
) -> None:
    """compose's ${RESTART_POLICY:-unless-stopped} renders empty as unless-stopped, and the
    wrapper allows it, so the checker does too (final review, correctness N2)."""
    done = checker("--env-file", str(server_env(tmp_path, RESTART_POLICY=value)))
    assert done.returncode == 0, done.stderr


def test_the_env_file_check_refuses_compose_file_and_debug_and_allows_an_empty_restart_policy() -> (
    None
):
    base = {"COMPOSE_PROJECT_NAME": "routemaker-beta"}
    assert beta.check_env_file({**base, "RESTART_POLICY": ""}) == []
    assert beta.check_env_file({**base, "DJANGO_DEBUG": ""}) == []
    for key, value in (("COMPOSE_FILE", "x.yaml"), ("RESTART_POLICY", "no"), ("DJANGO_DEBUG", "0")):
        found = beta.check_env_file({**base, key: value})
        assert any(p.startswith(f".env: {key}") for p in found), (key, found)


@needs_docker
def test_the_env_file_mode_checks_the_rendered_project_name(tmp_path: Path) -> None:
    """The last assignment wins in compose's reader; the gate checks what compose renders."""
    path = server_env(tmp_path)
    path.write_text(path.read_text() + "COMPOSE_PROJECT_NAME=routemaker\n")
    done = checker("--env-file", str(path))
    assert done.returncode == 1 and "rendered project name is 'routemaker'" in done.stderr


def test_the_checkers_pool_arithmetic_mirrors_settings() -> None:
    settings = (REPO / "src" / "config" / "settings.py").read_text()
    geocode = int(re.search(r"^GEOCODE_CONCURRENCY = ([0-9]+)$", settings, re.M).group(1))
    assert geocode == beta.GEOCODE_CONCURRENCY
    assert "return max(1, workers - 2 - GEOCODE_CONCURRENCY)" in settings
    assert (
        "return max(1, workers - 1 - routing_concurrency(web_concurrency) - GEOCODE_CONCURRENCY)"
        in settings
    )
    # OWNER-DECISIONS 367.2: six workers is two plans at once with one worker free
    assert (beta.routing_concurrency(6), beta.tile_concurrency(6)) == (2, 1)
    assert OVERLAY["services"]["api"]["environment"]["WEB_CONCURRENCY"].endswith(":-6}")


# --- the data path (S3, S9) ---


def shipped_exclusions() -> list[str]:
    text = (REPO / "scripts" / "beta" / "ship-data.sh").read_text()
    body = re.search(r"^EXCLUDED_TABLE_DATA=\(\n(.*?)^\)", text, re.M | re.S).group(1)
    return body.split()


def test_the_dump_strips_every_identity_table_owner_decision_367() -> None:
    excluded = set(shipped_exclusions())
    identities = {
        "app_user",
        "audit_log",
        "bootstrap_claim",
        "pending_instance_admin_removal",
        "ban_tombstone",
        "configured_guild",
        "role_mapping",
        "app_session",
        "django_session",
        "django_admin_log",
        "cached_membership",
    }
    assert identities <= excluded, identities - excluded
    # what the beta needs from home stays: the overrides
    assert "override" not in excluded
    # the tile cache is keyed on the live table's oid, which the beta's restore changes, so a
    # shipped row could never be served there (BETA-final-review correctness SF1)
    assert "stress_tile_cache" in excluded


def test_every_table_that_points_at_an_excluded_table_is_excluded_too() -> None:
    """A foreign key from shipped data to stripped data would fail in pg_restore's post-data."""
    models = (REPO / "src" / "core" / "models.py").read_text()
    classes = list(re.finditer(r"^class (\w+)\(", models, re.M))
    tables: dict[str, str] = {}
    bodies: dict[str, str] = {}
    for i, match in enumerate(classes):
        end = classes[i + 1].start() if i + 1 < len(classes) else len(models)
        body = models[match.start() : end]
        table = re.search(r'db_table = "(\w+)"', body)
        if table:
            tables[match.group(1)] = table.group(1)
            bodies[table.group(1)] = body
    tables["User"] = "app_user"
    excluded = set(shipped_exclusions())
    checked = 0
    for table, body in bodies.items():
        for target in re.findall(r"models\.(?:ForeignKey|OneToOneField)\(\s*(\w+)", body):
            checked += 1
            if tables.get(target) in excluded:
                assert table in excluded, f"{table} -> {tables[target]}"
    assert checked >= 5


def test_ship_data_clears_the_remote_manifest_before_sending() -> None:
    text = (REPO / "scripts" / "beta" / "ship-data.sh").read_text()
    clear = text.index("rm -f '$remote_dir/SHA256SUMS' '$remote_dir/MANIFEST.txt'")
    assert clear < text.index('note "sending the data, manifest last')


def test_the_update_path_names_only_live_and_override_and_empties_the_stale_tile_cache() -> None:
    text = (REPO / "scripts" / "beta" / "receive-data.sh").read_text()
    line = next(x for x in text.splitlines() if "TABLE DATA public override |" in x)
    for table in shipped_exclusions():
        assert table not in line, table
    assert "SEQUENCE SET public override_)" in line
    assert 'echo "TRUNCATE public.override, public.stress_tile_cache;"' in text
    counted = next(x for x in text.splitlines() if 'case "$qualified" in "$live_schema".*' in x)
    assert "stress_tile_cache" not in counted
    assert "-q -1 -v ON_ERROR_STOP=1" in text  # one transaction
    assert "--delete-beta-accounts" in text


@needs_sh
def test_receive_files_installs_only_listed_files_and_manifest_builds(tmp_path: Path) -> None:
    if shutil.which("rsync") is None or shutil.which("sha256sum") is None:
        pytest.skip("needs rsync and sha256sum")
    data = tmp_path / "dr" / "routemaker"
    (data / "tiles" / "standard" / "current").mkdir(parents=True)  # as prepare_data_root.sh does
    env = tmp_path / ".env"
    env.write_text(f"DATA_ROOT={data}\n")
    bundle = _bundle(tmp_path)
    for build in ("20261001T0000Z", "20261004T0000Z"):
        (bundle / "tiles" / "standard" / build).mkdir(parents=True)
        (bundle / "tiles" / "standard" / build / "tiles.tar").write_text(build)
    (bundle / "frontend" / "stale.js").write_text("left by an earlier bundle")
    listed = ["frontend/index.html", "tiles/standard/20261001T0000Z/tiles.tar"]
    sums = subprocess.run(
        ["sha256sum", *listed], cwd=bundle, capture_output=True, text=True, check=True
    ).stdout
    (bundle / "SHA256SUMS").write_text(sums)
    manifest = (bundle / "MANIFEST.txt").read_text()
    manifest = manifest.replace("parts=frontend ", "parts=frontend tiles ")
    (bundle / "MANIFEST.txt").write_text(manifest + "tiles=standard=20261001T0000Z\n")
    done = run(
        "bash",
        "scripts/beta/receive-data.sh",
        "--bundle",
        str(bundle),
        "--env-file",
        str(env),
        "files",
    )
    assert done.returncode == 0, done.stderr
    assert (data / "tiles" / "standard" / "current").resolve().name == "20261001T0000Z"
    assert not (data / "tiles" / "standard" / "20261004T0000Z").exists()
    assert "skipping tiles/standard/20261004T0000Z" in done.stderr
    assert not (data / "frontend" / "stale.js").exists()
    assert "not in SHA256SUMS" in done.stderr


def test_the_smoke_test_expects_206_for_the_base_maps_byte_range() -> None:
    text = (REPO / "scripts" / "beta" / "smoke-test.sh").read_text()
    line = next(x for x in text.splitlines() if "Range: bytes=" in x and "check_status" in x)
    assert " 206 " in line and " 200 " not in line
    assert "/static/admin/css/base.css" in text


# --- the runbook (S1, S5, S10, S12) ---

RUNBOOK = (REPO / "docs" / "BETA-RUNBOOK.md").read_text()


def runbook_commands() -> list[str]:
    blocks = re.findall(r"```sh\n(.*?)```", RUNBOOK, re.S)
    return [line.strip() for block in blocks for line in block.splitlines()]


def runbook_blocks() -> list[list[str]]:
    return [
        [line.strip() for line in block.splitlines()]
        for block in re.findall(r"```sh\n(.*?)```", RUNBOOK, re.S)
    ]


def guard_function() -> str:
    return re.search(r"^rm_absent\(\) \{.*\}$", RUNBOOK, re.M).group(0)


# Commands that create a RouteMaker path; each must be gated on the same line (review r1, N1).
CREATING = ("install -d", "prepare_data_root.sh", "mkdir -m 700", "python3 -m venv", 'ln -s "')


TLS_BRANCH = re.compile(r'^\[ "\$TLS_OPTION" = ([AB]) \] && ')


def unbranched(line: str) -> str:
    """The line without step 9c's `[ "$TLS_OPTION" = A|B ] && ` prefix."""
    return TLS_BRANCH.sub("", line)


def gated_lines() -> list[str]:
    out = []
    for line in runbook_commands():
        if line.startswith("#"):
            continue
        if any(c in line for c in CREATING) or (
            "install -m 644" in line and '"$NGINX_SITE"' in line
        ):
            out.append(line)
    return out


def test_the_runbook_never_reowns_or_remodes_an_existing_directory() -> None:
    for line in runbook_commands():
        if "install -d" in line:
            assert "dirname" not in line and not re.search(r"/data(\s|$)", line), line
        assert "chmod" not in line and "chown" not in line, line


def test_every_creating_command_is_chained_behind_its_guard() -> None:
    lines = gated_lines()
    assert len(lines) >= 8, lines
    for line in lines:
        # a new path behind rm_absent, or a replacement only of the file this runbook rendered
        guarded = unbranched(line).startswith("rm_absent ") or unbranched(line).startswith(
            (
                "grep -q 'Rendered by scripts/beta/render-nginx.sh (stage acme)'",
                "grep -q 'Rendered by scripts/beta/render-nginx.sh (stage full)'",
            )
        )
        assert guarded and " && " in line, line
    for path in ('"$RM_SRC"', '"$RM_INCOMING"', '"$RM_DATA"', '"$RM_STATE"', '"$NGINX_LINK"'):
        assert any(unbranched(line).startswith("rm_absent ") and path in line for line in lines), (
            path
        )


@needs_sh
@pytest.mark.parametrize("present", [True, False], ids=["a path exists", "all absent"])
def test_a_failed_guard_stops_the_command_it_gates(tmp_path: Path, present: bool) -> None:
    """Each gated runbook line, run for real in bash with stub sudo/mkdir/python3/ln: when a
    guarded path exists, the command after the guard must not run."""
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    log = tmp_path / "ran"
    for name in ("sudo", "mkdir", "python3", "ln", "install"):
        stub = stubs / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> {log}\n')
        stub.chmod(0o755)
    where = tmp_path / ("there" if present else "nowhere")
    if present:
        where.mkdir()
    home = tmp_path / "home"
    (home / "routemaker-beta-venv").mkdir(parents=True) if present else home.mkdir()
    paths = {
        k: str(where / k.lower())
        for k in ("RM_SRC", "RM_INCOMING", "RM_DATA", "RM_STATE", "NGINX_SITE", "NGINX_LINK")
    }
    if present:
        for p in paths.values():
            Path(p).mkdir()
    env = {"PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(home), **paths}
    for line in gated_lines():
        if (
            "/var/www/routemaker-acme" in line
            and not present
            and Path("/var/www/routemaker-acme").exists()
        ):
            continue
        log.unlink(missing_ok=True)
        branch = TLS_BRANCH.match(line)
        env["TLS_OPTION"] = branch.group(1) if branch else ""
        done = subprocess.run(
            ["bash", "-c", f"{guard_function()}\n{line}"],
            cwd=REPO,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if present:
            assert not log.exists(), (line, log.read_text())
            assert done.returncode != 0, line
        elif unbranched(line).startswith("rm_absent "):
            assert log.exists(), (line, done.stderr)


def test_no_runbook_umask_outlives_its_subshell() -> None:
    """A bare `umask 077` stays set for the rest of the install (review r1, N2)."""
    seen = 0
    for block in runbook_blocks():
        depth = 0
        for line in block:
            code = line.split("  #")[0]
            if re.search(r"\bumask\b", code) and not code.startswith("#"):
                seen += 1
                assert depth > 0 or code.startswith("("), line
            depth += code.count("(") - code.count(")")
        assert depth == 0, block
    assert seen >= 2


def test_the_runbook_snapshots_before_a_release_can_migrate_and_starts_the_app_once() -> None:
    sect = RUNBOOK[RUNBOOK.index("**A new release sha**") : RUNBOOK.index("**Front end only:**")]
    stop = sect.index("beta-compose.sh stop api worker")
    snap = sect.index("snapshot-db --label release")
    migrate = sect.index("run --rm --no-deps migrate ./manage.py migrate")
    start = sect.index("`scripts/beta/beta-compose.sh up -d api worker`")
    assert stop < snap < migrate < start
    assert sect.index("git checkout --detach <new sha>") > snap
    assert "**without** their" in sect
    rollback_c = RUNBOOK[RUNBOOK.index("**C. Go back to the previous release:**") :]
    assert "restore-dump" in rollback_c.split("**D.")[0]


def test_restore_dump_restores_into_a_fresh_database_and_swaps_it_in() -> None:
    text = (REPO / "scripts" / "beta" / "receive-data.sh").read_text()
    block = text[text.index('if [ "$command_name" = restore-dump ]; then') :]
    block = block[: block.index("\nfi\n")]
    assert "--single-transaction --exit-on-error" in block and '-d "$fresh"' in block
    assert "--clean --if-exists" not in block and "restore_whole" not in block
    assert block.index("create database") < block.index("pg_restore -U") < block.index("rename to")
    assert "psql_on postgres -1 -c" in block  # both renames in one transaction


PREDRAW = "scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles"


def test_the_runbook_predraws_the_tiles_after_the_first_start_and_every_data_update() -> None:
    """The beta fills its own tile cache (none is shipped): after step 8's start, before the
    testers are invited, and after each `db --update-data`."""
    step8 = RUNBOOK[RUNBOOK.index("## 8. Start the stack") : RUNBOOK.index("## 9. nginx")]
    assert PREDRAW in step8 and "before" in step8 and "invite" in step8
    updates = RUNBOOK[RUNBOOK.index("## Shipping an update later") :]
    for update in re.finditer(r"db --update-data\n", updates):
        assert PREDRAW in updates[update.end() : update.end() + 900], update.start()
    assert updates.count(PREDRAW) >= 1
    assert "155 s" in RUNBOOK  # its expected time, measured at home


def test_the_runbook_records_the_servers_facts_and_checks_them_read_only() -> None:
    """Final review, operations SF6 and N1. The repository is public, so the server is named by
    a variable and its address is checked live, never written down."""
    step1 = RUNBOOK[RUNBOOK.index("## 1. Prerequisites") : RUNBOOK.index("## 2. Get the code")]
    assert "export RM_SSH_HOST=<" in RUNBOOK[: RUNBOOK.index("## 1. Prerequisites")]
    for fact in ('ssh "$RM_SSH_HOST"', "`nofail`", "root disk", "8400 MiB", "x86_64"):
        assert fact in step1, fact
    assert "https://api.ipify.org" in step1 and "getent ahostsv4 routemaker.cieply.com" in step1
    assert '[ -n "$dns" ] && [ -n "$me" ] && [ "$dns" = "$me" ]' in step1  # re-check ops SF-A
    assert "amazonaws" not in RUNBOOK and "7900" not in RUNBOOK
    assert "uname -m; docker info -f '{{.Architecture}}'" in step1  # ops SF-G
    assert not re.search(
        r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", RUNBOOK.replace("127.0.0.1", "")
    )
    for check in (
        "stat -c '%A %U:%G' /data",
        "findmnt -no SOURCE,FSTYPE,OPTIONS /data",
        "docker info -f '{{.DockerRootDir}}'",
        "systemctl is-enabled docker containerd",
    ):
        assert check in step1, check
    for command in runbook_commands():
        assert not re.search(r"\b(chmod|chown|chgrp)\b[^|]*\s/data\s*$", command), command
    assert "scripts/boot/" in step1 and "start-stack.sh" in step1


def test_the_runbook_ships_after_step_two_and_builds_the_image_at_home_without_compose() -> None:
    """Final review, operations SF1 and SF4."""
    step2 = RUNBOOK[RUNBOOK.index("## 2. Get the code") : RUNBOOK.index("## 3. Make")]
    assert "ships the bundle only after this step" in step2 and "same user" in step2
    step6 = RUNBOOK[RUNBOOK.index("## 6. Build") : RUNBOOK.index("## 7. Receive")]
    assert (
        'docker build -f docker/api.Dockerfile -t "ghcr.io/macrophage87/routemaker-api:$T" .'
        in step6
    )
    assert "T=$(git rev-parse --short=12 HEAD)" in step6
    assert "| gzip | ssh \"$RM_SSH_HOST\" 'gunzip | docker load'" in step6
    step7 = RUNBOOK[RUNBOOK.index("## 7. Receive") : RUNBOOK.index("## 8. Start")]
    assert '--build-frontend  "$RM_SSH_HOST"  /data/routemaker-incoming' in step7
    commands = [c for c in runbook_commands() if not c.startswith("#")]
    assert not any("docker compose build" in c for c in commands)
    assert "user@server" not in RUNBOOK


def test_the_rollbacks_restore_the_front_end_and_pair_graphs_with_the_database() -> None:
    """Final review, operations SF2, SF3 and N5."""
    rollback_a = RUNBOOK[RUNBOOK.index("**A. Go back") : RUNBOOK.index("**B. Go back")]
    assert "do **B** as well" in rollback_a and "pre-update-<time>.dump" in rollback_a
    rollback_c = RUNBOOK[RUNBOOK.index("**C. Go back") : RUNBOOK.index("**D. Take")]
    assert 'index.html.pre-release-<time>" "$RM_DATA/frontend/index.html.new"' in rollback_c
    assert (
        'sudo mv -T "$RM_DATA/frontend/index.html.new" "$RM_DATA/frontend/index.html"' in rollback_c
    )
    assert "up -d photon valhalla-standard" in rollback_c
    release = RUNBOOK[RUNBOOK.index("**A new release sha**") : RUNBOOK.index("**Front end only:**")]
    backup = release.index(
        'sudo cp -p "$RM_DATA/frontend/index.html" "$RM_DATA/backups/index.html.pre-release-'
    )
    assert release.index("snapshot-db --label release") < backup < release.index("git fetch")


def test_the_paused_rebuilds_traces_on_the_beta_are_documented_as_expected() -> None:
    """Final review, spec S1: the tick is still queued and the entry reads stale."""
    header = (REPO / "compose.beta.yaml").read_text().split("services:")[0]
    assert "so nothing queues rebuild jobs" not in header
    assert "one\n#     weekly_rebuild job waits" in header
    note = RUNBOOK[RUNBOOK.index("**No rebuild runs here.**") :]
    assert "one\n  `weekly_rebuild` job waits" in note and "as stale" in note
    found = problems_for(lambda s: s["api"]["environment"].pop("WEEKLY_REBUILD_PAUSED"))
    assert any("must only record a pause" in p for p in found), found


NOHUP_PREDRAW = (
    "( umask 077; setsid nohup sh -c 'scripts/beta/beta-compose.sh exec -T worker ./manage.py"
    ' predraw_stress_tiles ; echo "predraw exit $?"\' < /dev/null >'
    ' "${RM_STATE:?set RM_STATE (section 0)}/predraw.log" 2>&1 & )'
)
PREDRAW_LIVENESS = (
    'docker top "$(scripts/beta/beta-compose.sh ps -q worker)" -eo pid,etime,args'
    " | grep '[p]redraw_stress_tiles' || echo \"no predraw running\""
)


def test_the_predraw_runs_detached_and_follows_every_restore() -> None:
    """Re-check operations SF-C and SF-D."""
    step8 = RUNBOOK[RUNBOOK.index("## 8. Start the stack") : RUNBOOK.index("## 9. nginx")]
    assert NOHUP_PREDRAW in step8 and 'tail -n 3 "$RM_STATE/predraw.log"' in step8
    # re-check 2 (correctness SF2, ops SF-3): an end marker, its own session, a liveness check
    assert "Never start it again\nagain while the log has no `predraw exit` line" not in step8
    assert (
        "**Never start it\nagain while the log has no `predraw exit` line and the `docker top`"
        in step8
    )
    assert PREDRAW_LIVENESS in step8
    assert step8.index('"predraw exit N"') < step8.index("{{.State.OOMKilled}} {{.RestartCount}}")
    assert step8.count(NOHUP_PREDRAW) == 1
    plain = "scripts/beta/beta-compose.sh exec -T worker ./manage.py predraw_stress_tiles"
    for line in runbook_commands():
        if plain in line:
            assert line.startswith("( umask 077; setsid nohup sh -c "), line
    assert RUNBOOK.count(NOHUP_PREDRAW) == 4  # step 8, rollbacks B and C, the data update
    for name, end in (("**B. Go back", "**C. Go back"), ("**C. Go back", "**D. Take")):
        section = RUNBOOK[RUNBOOK.index(name) : RUNBOOK.index(end)]
        assert NOHUP_PREDRAW in section, name
    rollback_c = RUNBOOK[RUNBOOK.index("**C. Go back") : RUNBOOK.index("**D. Take")]
    assert "do **A** as well" in rollback_c  # SF-E
    sed = rollback_c.index("sed -i 's/^TAG=")
    assert rollback_c.index("check_beta_compose.py --env-file .env", sed) > sed  # N-c
    rollback_a = RUNBOOK[RUNBOOK.index("**A. Go back") : RUNBOOK.index("**B. Go back")]
    assert "Photon index" in rollback_a and "no `previous`" in rollback_a  # N-d


def test_the_runbook_checks_the_401_at_once_and_says_how_to_recover() -> None:
    """Re-check operations SF-F."""
    nine_c = RUNBOOK[RUNBOOK.index("### 9c. The full site") : RUNBOOK.index("## 10. Smoke")]
    assert (
        "curl -s -m 10 -o /dev/null -w '%{http_code}\\n' https://routemaker.cieply.com/" in nine_c
    )
    assert "000: no answer" in nine_c  # re-check 2 ops NIT-4
    ten = RUNBOOK[RUNBOOK.index("## 10. Smoke") : RUNBOOK.index("## 11. Report")]
    assert "**If the 401 lines fail with 403 or 404**" in ten and "--no-401-page" in ten


def test_the_runbook_uses_variables_for_the_port_the_nginx_user_and_the_ssh_host() -> None:
    """Re-check operations N-a, N-b, N-f, and the owner's home sequence (item 7)."""
    commands = [c for c in runbook_commands() if not c.startswith("#")]
    for command in commands:
        assert "127.0.0.1:8087" not in command and "--api-port 8087" not in command, command
        assert "www-data" not in command, command
    assert 'sudo -u "$NGINX_USER" test -r' in RUNBOOK and "export NGINX_USER=<" in RUNBOOK
    home = RUNBOOK[RUNBOOK.index("**At home (owner).**") : RUNBOOK.index("It sends about 4 GB")]
    assert "export RM_SSH_HOST=<" in home and "never written into a" in home
    assert '--build-frontend  "$RM_SSH_HOST"  /data/routemaker-incoming' in home
    assert "/home/" not in home and "/Users/" not in home  # variables only, no one's paths
    assert "repeat the same `--report-url` on every later ship" in home  # correctness N1
    front_end_only = RUNBOOK[RUNBOOK.index("**Front end only:**") :]
    assert "--build-frontend [--report-url" in front_end_only.split("\n\n")[0]


def test_the_runbook_says_when_the_stale_entry_appears_and_forbids_a_hand_fired_rebuild() -> None:
    """Re-check spec N1 and N2."""
    note = RUNBOOK[RUNBOOK.index("**No rebuild runs here.**") :]
    note = note[: note.index("\n- **")]
    assert "eight days after setup" in note
    assert "**Never run `run_rebuild_now` here**" in note


def test_the_checker_pauses_the_parked_rebuild_too() -> None:
    """Re-check spec SF1: rebuild is checked wherever it is rendered."""
    found = beta.check_runtime_settings({"rebuild": {"environment": {}}})
    assert any(p.startswith("rebuild: WEEKLY_REBUILD_PAUSED must be 1") for p in found), found
    ok = beta.check_runtime_settings({"rebuild": {"environment": {"WEEKLY_REBUILD_PAUSED": "1"}}})
    assert not any("rebuild" in p for p in ok), ok
    assert OVERLAY["services"]["rebuild"]["environment"]["WEEKLY_REBUILD_PAUSED"] == "1"


@needs_sh
@pytest.mark.parametrize("var", ["DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"])
@pytest.mark.parametrize(
    "form",
    [["--render"], ["--env-file", "/dev/null"], ["--env-file=/dev/null"]],
    ids=["render", "env-file", "env-file="],
)
def test_the_wrapper_and_the_checker_refuse_docker_settings_env_i_would_drop(
    stub_docker, var: str, form: list[str]
) -> None:
    """Re-check correctness N2: refused loudly, not dropped silently; in every checker form,
    the gate's `--env-file .env` included (re-check 2 mutation NIT 1)."""
    env, calls = stub_docker
    done = wrapper({**env, var: "x"}, "ps")
    assert done.returncode == 2 and var in done.stderr and not calls.exists()
    checked = run(sys.executable, "scripts/check_beta_compose.py", *form, env={var: "x"})
    assert checked.returncode == 2 and var in checked.stderr


@needs_sh
def test_the_renderer_can_leave_out_the_sign_in_page() -> None:
    """Re-check operations SF-F: the recovery is a re-render, never a hand edit."""
    args = ["--stage", "full", "--env-file", "/nonexistent", "--cert-fullchain", "/c/f.pem"]
    args += ["--cert-key", "/c/k.pem"]
    with_page = run("sh", "scripts/beta/render-nginx.sh", *args)
    without = run("sh", "scripts/beta/render-nginx.sh", *args, "--no-401-page")
    assert with_page.returncode == 0 and without.returncode == 0, without.stderr
    assert "error_page 401 /rmbeta-401.html;" in with_page.stdout
    assert not re.search(r"^\s*error_page 401", without.stdout, re.M)
    assert "location = /rmbeta-401.html" not in without.stdout
    # the 502 page is read from the same directory, so the same recovery leaves it out too
    assert "error_page 502 /rmbeta-502.html;" in with_page.stdout
    assert not re.search(r"^\s*error_page 502", without.stdout, re.M)
    assert "location = /rmbeta-502.html" not in without.stdout
    assert without.stdout.count("{") == without.stdout.count("}")
    assert "auth_basic_user_file" in without.stdout and "location = /robots.txt" in without.stdout


def test_the_sign_in_page_says_to_use_a_real_browser() -> None:
    page = (REPO / "deploy" / "beta" / "401.html").read_text()
    assert "rather than inside another app" in page  # re-check a11y N3


def test_the_handout_keeps_the_senders_notes_out_of_what_testers_get() -> None:
    """Re-check accessibility N1 and N2."""
    handout = (REPO / "docs" / "BETA-TESTER-HANDOUT.md").read_text()
    cut = handout.index("cut here: send everything below")
    sender, tester = handout[:cut], handout[cut:]
    assert "shred -u" in sender and "shred -u" not in tester
    assert "many browsers block or warn" in sender
    assert "user name and password lines" in sender and "two lines" not in handout
    assert "a landmark" in tester and "complementary" in tester
    assert "Color-blind" not in handout and "color-blind" not in handout


VARS_SOURCE = '. "$HOME/routemaker-beta-state/vars.sh"'


def test_every_server_block_sources_the_vars_file_which_holds_no_secret() -> None:
    """Re-check 2 ops SF-2: each tool call is a fresh shell, so every block re-reads the
    non-secret variables and rm_absent from $RM_STATE/vars.sh, which section 0 writes."""
    after = RUNBOOK[RUNBOOK.index("## 1. Prerequisites") :]
    blocks = re.findall(r"^( *)```sh\n(.*?)^\1```", after, re.M | re.S)
    assert len(blocks) >= 30
    for _indent, body in blocks:
        first = body.splitlines()[0].strip()
        if first.startswith(("# at home", "export RM_SSH_HOST=<your")):
            assert VARS_SOURCE not in body  # the owner's own shell at home
            continue
        assert first == VARS_SOURCE, body[:120]
    zero = RUNBOOK[RUNBOOK.index("## 0. Variables") : RUNBOOK.index("## 1. Prerequisites")]
    assert "Every tool call is a fresh shell" in zero and "never a password, key or token" in zero
    assert 'rm_absent "$RM_STATE" && mkdir -m 700 "$RM_STATE"' in zero
    assert "( umask 077; set -C; cat > \"${RM_STATE:?}/vars.sh\" ) <<'VARS'" in zero
    # re-check 3 ops NIT-A and NIT-B: the function only after a fresh write; no unfilled <...>
    assert "<<'VARS' && declare -f rm_absent >> \"$RM_STATE/vars.sh\"" in zero
    assert zero.count("declare -f rm_absent") == 1
    assert 'grep -n \'<[^>]*>\' "$RM_STATE/vars.sh" && echo "STOP: fill in' in zero
    heredoc = zero[zero.index("<<'VARS'") : zero.index("\nVARS\n")]
    assert not re.search(r"(?i)(password|secret|token|_key\b|PGPASS|htpasswd)", heredoc), heredoc
    for line in heredoc.splitlines()[1:]:
        assert line.startswith("export RM_") or line.startswith("export BETA_API_PORT="), line
    for appended in re.findall(r"echo '(export [A-Z_]+=[^']*)' >> \"\$RM_STATE/vars.sh\"", RUNBOOK):
        # RM_CERT_KEY is the private key's PATH (re-check 3 ops NIT-E), never its content
        named = appended.replace("RM_CERT_KEY=<private key path>", "")
        assert not re.search(r"(?i)(password|secret|token|key)", named), appended
    assert "7. Start every command block with" in RUNBOOK
    one = RUNBOOK[RUNBOOK.index("## 1. Prerequisites") : RUNBOOK.index("## 2. Get the code")]
    assert '"$HOME/routemaker-beta-state" "$HOME' not in one  # created in section 0 now


def test_the_certificate_paths_and_the_checkout_come_from_the_vars_file() -> None:
    """Re-check 3 ops NIT-D and NIT-E; re-check 4 NIT-H: the renders refuse an unfilled <...>."""
    guard = '{ ! grep -n \'<[^>]*>\' "$RM_STATE/vars.sh" || { echo "STOP: fill in'
    renders = [c for c in runbook_commands() if "render-nginx.sh --stage full" in c]
    assert len(renders) == 2 and all(c.startswith(guard) for c in renders), renders
    assert "--cert-fullchain <path>" not in RUNBOOK
    assert RUNBOOK.count('--cert-fullchain "$RM_CERT_FULLCHAIN" --cert-key "$RM_CERT_KEY"') == 2
    after = RUNBOOK[RUNBOOK.index("## 3. Make") :]
    for _indent, body in re.findall(r"^( *)```sh\n(.*?)^\1```", after, re.M | re.S):
        lines = [x.strip() for x in body.splitlines()]
        if lines[0] != VARS_SOURCE or "scripts/" not in body:
            continue
        assert 'cd "$RM_SRC"' in lines[:3], body[:150]


def test_the_runbook_states_the_budget_in_both_units() -> None:
    """Re-check 2 ops NIT-5: 7102 MiB is 6.94 GiB, and the two are written together."""
    assert round(7102 / 1024, 2) == 6.94 and round(7358 / 1024, 2) == 7.19
    assert "7102 MiB = 6.94 GiB" in RUNBOOK and "7358 MiB = 7.19 GiB" in RUNBOOK


@needs_sh
def test_the_smoke_test_can_skip_the_sign_in_pages_text() -> None:
    """Re-check 2 ops SF-4: after the --no-401-page recovery every other line can PASS."""
    text = (REPO / "scripts" / "beta" / "smoke-test.sh").read_text()
    assert "--no-401-page) page401=0; shift ;;" in text
    guarded = text[text.index('if [ "$page401" = 1 ]; then') :]
    guarded = guarded[: guarded.index("\tfi\n")]
    assert 'check_body "the 401 page says how to get in"' in guarded and "SKIP" in guarded
    assert text.count("person who gave you access") == 1
    ten = RUNBOOK[RUNBOOK.index("## 10. Smoke") : RUNBOOK.index("## 11. Report")]
    assert "Rerun the smoke test with\n`--no-401-page`" in ten
    unknown = run("bash", "scripts/beta/smoke-test.sh", "--bogus")
    assert unknown.returncode == 2


def test_the_ci_tool_versions_step_cannot_fail_the_required_check() -> None:
    """Re-check 2 spec C2."""
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    lines = ci[ci.index("- name: Tool versions") :].splitlines()
    step = [lines[0]] + [x for x in lines[1:3] if x.startswith("        ")]
    assert any(x.strip() == "continue-on-error: true" for x in step), step
    assert step[-1].rstrip().endswith("|| true"), step


# --- main() runs the bind probe and the source check, and passes the scheme on (re-check 2
# mutation SHOULD-FIX 1: B11-B16, S1) ---


def _crafted(name: str | None = None) -> dict:
    """good(), plus one DATA_ROOT bind rendered as `bind: {}`: it creates its source under the
    "explicit" scheme and does not under "omit-false", so the result shows which one main() used."""
    compose = good()
    compose["services"]["postgis"]["volumes"] = [
        {
            "type": "bind",
            "source": "/data/routemaker/postgres",
            "target": "/var/lib/postgresql/data",
            "bind": {},
        }
    ]
    if name:
        compose["name"] = name
    return compose


@pytest.fixture
def gate(monkeypatch, tmp_path: Path):
    """main() with the render, the probe and the source check replaced by recorders; returns a
    runner taking the mode ("render" or "env-file") and giving (exit code, stderr, calls)."""
    for var in beta.REFUSED_DOCKER_ENV:
        monkeypatch.delenv(var, raising=False)
    calls: list[str] = []
    state = {"scheme": "explicit", "source": [], "probe_fails": False}

    def probe(*_a, **_k):
        calls.append("bind_semantics")
        if state["probe_fails"]:
            raise beta.RenderFailed("PROBE-FAILED-MARKER")
        return state["scheme"]

    def source(*_a, **_k):
        calls.append("check_source_binds")
        return list(state["source"])

    def render(*_a, **_k):
        calls.append("render")
        return _crafted()

    def render_env(*_a, **_k):
        calls.append("render_env_file")
        return _crafted("routemaker-beta")

    monkeypatch.setattr(beta, "bind_semantics", probe)
    monkeypatch.setattr(beta, "check_source_binds", source)
    monkeypatch.setattr(beta, "render", render)
    monkeypatch.setattr(beta, "render_env_file", render_env)
    env_file = tmp_path / "server.env"
    env_file.write_text("COMPOSE_PROJECT_NAME=routemaker-beta\nDATA_ROOT=/data/routemaker\n")

    def run_main(mode: str, capsys) -> tuple[int, str, list[str]]:
        calls.clear()
        if mode == "render":
            argv = ["--render"]
        elif mode == "env-file":
            argv = ["--env-file", str(env_file)]
        else:
            argv = [f"--env-file={env_file}"]
        code = beta.main(argv)
        return code, capsys.readouterr().err, list(calls)

    run_main.state = state
    return run_main


MODES = ["render", "env-file", "env-file="]


@pytest.mark.parametrize("mode", MODES)
def test_main_runs_the_source_check_and_fails_on_its_problems(gate, capsys, mode: str) -> None:
    gate.state.update(scheme="omit-false", source=["compose.beta.yaml api: SOURCE-MARKER"])
    code, err, calls = gate(mode, capsys)
    assert "bind_semantics" in calls and "check_source_binds" in calls
    assert code == 1 and "SOURCE-MARKER" in err, err


@pytest.mark.parametrize("mode", MODES)
def test_main_stops_after_a_failed_probe_before_rendering(gate, capsys, mode: str) -> None:
    gate.state.update(probe_fails=True)
    code, err, calls = gate(mode, capsys)
    assert code == 1 and "PROBE-FAILED-MARKER" in err, err
    assert calls == ["bind_semantics"], calls  # no source check, no render after the failure


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("scheme", "flagged"), [("explicit", True), ("omit-false", False)])
def test_main_passes_the_probed_scheme_to_the_render_check(
    gate, capsys, mode: str, scheme: str, flagged: bool
) -> None:
    """A hard-coded scheme fails one of the two rows: `omit-false` hard-coded passes the
    explicit row's creating bind (errs open), `explicit` hard-coded flags the omit-false row."""
    gate.state.update(scheme=scheme)
    code, err, calls = gate(mode, capsys)
    assert ("render" in calls) or ("render_env_file" in calls)
    found = "postgis: bind /data/routemaker/postgres would be created empty" in err
    assert found is flagged, (scheme, err)
    assert code == (1 if flagged else 0), (scheme, err)


PROOF_STUB_DOCKER = """#!/bin/sh
# docker for the step-8 proof. inspect gives an image; create on no-such-dir fails as a refusing
# engine does; create on probe-src gives an id; start fails with the daemon's wording. Modes:
#   noimage      inspect gives nothing
#   createodd    create on no-such-dir fails with an unrelated error
#   createfails  create on probe-src fails (after its mkdir)
#   runc         start fails with runc's mount wording instead
#   creates      start succeeds and the engine recreates the source
#   recreates    start fails with the refusal, yet the source reappears
refuse() { echo "Error response from daemon: bind source path does not exist: x" >&2; exit 1; }
case "$1" in
  inspect) [ "${MODE:-}" = noimage ] || echo img:tag ;;
  create) case "$*" in
      *no-such-dir*)
        [ "${MODE:-}" != createodd ] || { echo "Error: daemon busy" >&2; exit 1; }
        refuse ;;
      *) [ "${MODE:-}" != createfails ] || { echo "Error: no space" >&2; exit 1; }; echo cid123 ;;
    esac ;;
  start)
    case "${MODE:-}" in
      creates) mkdir -p "$RM_STATE/probe-src"; echo cid123 ;;
      recreates) mkdir -p "$RM_STATE/probe-src"; refuse ;;
      runc)
        # runc's start-time wording (OCI runtime create failed ... error mounting ...)
        printf '%s' "Error response from daemon: OCI runtime create failed: runc create failed:" >&2
        printf '%s\\n' " error mounting $RM_STATE/probe-src to rootfs at /x:" >&2
        echo " mount src=$RM_STATE/probe-src, dst=/x: no such file or directory" >&2
        exit 1 ;;
      *) refuse ;;
    esac ;;
  rm) echo "rm $2" >> "$RM_STATE/rm.log" ;;
esac
"""


@needs_sh
@pytest.mark.parametrize(
    ("mode", "create_line", "start_line"),
    [
        ("", "PROOF OK (create)", "PROOF OK (start)"),
        ("noimage", "STOP (create): the probe did not run", "STOP (start): the probe did not run"),
        ("creates", "PROOF OK (create)", "STOP (start): the start did not fail as expected"),
        # re-check 4: runc's start-time wording passes (correctness SF-B)
        ("runc", "PROOF OK (create)", "PROOF OK (start)"),
        # re-check 4 mutation NIT 1: the cleanup branch, and the deciding "came back" test
        ("createfails", "PROOF OK (create)", "STOP (start): the probe did not run"),
        (
            "recreates",
            "PROOF OK (create)",
            "STOP (start): the start failed, but the source came back",
        ),
        # re-check 4 ops NIT-G: an unrelated create error is not called "made a container"
        ("createodd", "STOP (create): unexpected output, report it exactly", "PROOF OK (start)"),
    ],
    ids=["refuses", "no image", "engine creates", "runc", "create fails", "recreates", "odd"],
)
def test_the_step_8_proof_block_runs_as_one_shell(
    tmp_path: Path, mode: str, create_line: str, start_line: str
) -> None:
    """Re-check 3 SF-A: the block runs end to end in a single fresh shell, against stubs."""
    (block,) = [b for b in runbook_blocks() if any("PROOF OK (create)" in x for x in b)]
    body = "\n".join(x for x in block if not x.startswith(". "))
    state = tmp_path / "state"
    state.mkdir()
    bin_dir = tmp_path / "bin"
    (bin_dir).mkdir()
    (bin_dir / "docker").write_text(PROOF_STUB_DOCKER)
    (bin_dir / "docker").chmod(0o755)
    beta_dir = tmp_path / "scripts" / "beta"
    beta_dir.mkdir(parents=True)
    (beta_dir / "beta-compose.sh").write_text("#!/bin/sh\necho pgid\n")
    (beta_dir / "beta-compose.sh").chmod(0o755)
    script = f"{guard_function()}\n{body}\n"
    done = run(
        "bash",
        "-c",
        script,
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}", "RM_STATE": str(state), "MODE": mode},
    )
    lines = done.stdout.splitlines()
    assert any(x.startswith(create_line) for x in lines), done.stdout + done.stderr
    assert any(x.startswith(start_line) for x in lines), done.stdout + done.stderr
    if mode in ("noimage", "createfails"):
        assert not (state / "probe-src").exists()  # cleaned up, so a retry is not blocked
    if mode == "":
        assert (state / "rm.log").read_text().strip() == "rm cid123"
        assert not (state / "probe-src").exists()


def test_the_parked_services_are_exactly_caddy_and_rebuild() -> None:
    """Re-check 2 mutation NIT 2: parking another service would exempt its binds."""
    assert beta.PARKED == {"caddy", "rebuild"}


def test_the_source_check_catches_a_partly_restated_service(tmp_path: Path) -> None:
    """Re-check 2 mutation NIT 2: api has two binds; restating only one must be reported."""
    (tmp_path / "compose.yaml").write_text((REPO / "compose.yaml").read_text())
    overlay = (REPO / "compose.beta.yaml").read_text()
    static = (
        "      - type: bind\n"
        "        source: ${DATA_ROOT}/static\n"
        "        target: /data/static\n"
        "        bind: { create_host_path: false }\n"
    )
    assert overlay.count(static) == 1
    (tmp_path / "compose.beta.yaml").write_text(overlay.replace(static, ""))
    found = beta.check_source_binds(tmp_path)
    assert found == [
        "compose.beta.yaml api: the base file's bind on /data/static is not restated "
        "(it would keep the short form, which creates a missing source)"
    ], found


@needs_sh
def test_the_renderer_needs_the_sign_in_page_only_without_the_flag(tmp_path: Path) -> None:
    """Re-check 2 mutation NIT 3: from a copy whose deploy/beta has no 401.html."""
    (tmp_path / "scripts" / "beta").mkdir(parents=True)
    (tmp_path / "deploy" / "beta").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "beta" / "render-nginx.sh", tmp_path / "scripts" / "beta")
    shutil.copy(
        REPO / "deploy" / "beta" / "nginx-routemaker.conf.template", tmp_path / "deploy" / "beta"
    )
    script = str(tmp_path / "scripts" / "beta" / "render-nginx.sh")
    args = ["--stage", "full", "--env-file", "/nonexistent", "--cert-fullchain", "/c/f.pem"]
    args += ["--cert-key", "/c/k.pem"]
    refused = run("sh", script, *args, cwd=tmp_path)
    assert (
        refused.returncode == 2 and "cannot read" in refused.stderr and "401.html" in refused.stderr
    )
    accepted = run("sh", script, *args, "--no-401-page", cwd=tmp_path)
    assert accepted.returncode == 0, accepted.stderr
    assert not re.search(r"^\s*error_page 401", accepted.stdout, re.M)
    assert "location = /rmbeta-401.html" not in accepted.stdout
    # with the sign-in page back but no 502.html, the renderer still refuses
    shutil.copy(REPO / "deploy" / "beta" / "401.html", tmp_path / "deploy" / "beta")
    refused = run("sh", script, *args, cwd=tmp_path)
    assert (
        refused.returncode == 2 and "cannot read" in refused.stderr and "502.html" in refused.stderr
    )


def test_the_source_check_covers_every_beta_service_not_only_the_overlays(tmp_path: Path) -> None:
    """Re-check 2 correctness NIT 1: a beta service the overlay forgot is still reported."""
    (tmp_path / "compose.yaml").write_text((REPO / "compose.yaml").read_text())
    overlay = (REPO / "compose.beta.yaml").read_text()
    start = overlay.index("\n  photon:\n")
    end = overlay.index("\n  # --- the four routers")
    (tmp_path / "compose.beta.yaml").write_text(overlay[:start] + overlay[end:])
    found = beta.check_source_binds(tmp_path)
    assert any(
        "photon: the base file's bind on /photon/data is not restated" in p for p in found
    ), found
    source = (REPO / "scripts" / "check_beta_compose.py").read_text()
    assert "for name in sorted((EXPECTED_SERVICES | OPTIONAL_SERVICES) - PARKED):" in source


def test_no_shared_host_is_named_after_a_cloud_provider() -> None:
    """Re-check 2 scope NIT C."""
    for rel in ("compose.beta.yaml", "scripts/check_beta_compose.py", "docs/BETA-RUNBOOK.md"):
        assert "EC2" not in (REPO / rel).read_text(), rel


def test_the_runbook_documents_the_override_reset_and_installs_no_system_package() -> None:
    assert "resets `override` to home's" in RUNBOOK
    assert "apt install" not in RUNBOOK
    assert "**CPU shares are per container" in RUNBOOK and "Photon's memory margin" in RUNBOOK


def test_postgis_is_pinned_by_digest_so_a_pull_cannot_move_the_shared_tag() -> None:
    image = OVERLAY["services"]["postgis"]["image"]
    assert image.startswith(BASE["services"]["postgis"]["image"] + "@sha256:"), image


def test_the_runbook_runs_no_second_api_container_and_no_bare_compose() -> None:
    for line in runbook_commands():
        if "beta-compose.sh run " in line:
            assert "--no-deps migrate " in line, line
        assert not re.match(r"(sudo )?docker compose (up|run|create|start|restart|down)", line), (
            line
        )


def test_the_runbook_decides_tls_by_rule_and_never_uses_the_nginx_authenticator() -> None:
    for line in runbook_commands():
        assert "--nginx" not in line, line
    assert "openssl x509" in RUNBOOK and "subjectAltName" in RUNBOOK
    assert "*.cieply.com" in RUNBOOK and "14 days" in RUNBOOK
    assert "certbot certonly --webroot" in RUNBOOK


def test_the_runbook_keeps_nginx_copies_private_and_passwords_out_of_the_transcript() -> None:
    assert "/tmp/nginx" not in RUNBOOK
    assert 'mkdir -m 700 "$RM_STATE"' in RUNBOOK and "umask 077" in RUNBOOK
    assert "BETA_PASSWORD=<" not in RUNBOOK and "--passwords-file" in RUNBOOK


# --- small items (S12) ---


@needs_sh
def test_the_renderer_drops_template_lines_and_can_drop_ipv6() -> None:
    args = ["--stage", "full", "--env-file", "/nonexistent", "--cert-fullchain", "/c/f.pem"]
    args += ["--cert-key", "/c/k.pem"]
    with_v6 = run("sh", "scripts/beta/render-nginx.sh", *args)
    without = run("sh", "scripts/beta/render-nginx.sh", *args, "--no-ipv6")
    assert with_v6.returncode == 0 and without.returncode == 0, without.stderr
    assert "TEMPLATE" not in with_v6.stdout
    assert "Rendered by scripts/beta/render-nginx.sh" in with_v6.stdout
    assert with_v6.stdout.count("listen [::]") == 3
    assert "listen [::]" not in without.stdout and without.stdout.count("listen ") == 3


@needs_sh
def test_make_htpasswd_writes_readable_passwords_and_matching_hashes(tmp_path: Path) -> None:
    """Final review, accessibility S3: lowercase letters and digits without look-alikes, in
    four dash-separated groups of five (about 99 bits), and lowercase user names."""
    group = subprocess.run(["id", "-gn"], capture_output=True, text=True, check=True).stdout.strip()
    ht, pw = tmp_path / "beta.htpasswd", tmp_path / "pw.txt"
    args = ["--file", str(ht), "--passwords-file", str(pw), "--group", group]
    done = run("sh", "scripts/beta/make-htpasswd.sh", *args, "alice", "bob.smith")
    assert done.returncode == 0, done.stderr
    assert (ht.stat().st_mode & 0o777) == 0o640 and (pw.stat().st_mode & 0o777) == 0o600
    lines = [x.split() for x in pw.read_text().splitlines() if not x.startswith("#")]
    assert [u for u, _ in lines] == ["alice", "bob.smith"]
    passwords = [p for _, p in lines]
    group5 = "[a-hjkmnp-z2-9]{5}"
    for password in passwords:
        assert re.fullmatch(rf"{group5}(-{group5}){{3}}", password), "the format changed"
        assert not set(password) & set("ilo01ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        assert password not in done.stdout + done.stderr
    assert passwords[0] != passwords[1]
    # the script's own alphabet, not a copy (re-check mutation SHOULD-FIX 1): 20 of 31 = 99 bits
    script = (REPO / "scripts" / "beta" / "make-htpasswd.sh").read_text()
    assert re.search(r"^ALPHABET=abcdefghjkmnpqrstuvwxyz23456789$", script, re.M)
    assert "cut -c1-20" in script
    hashes = dict(line.split(":", 1) for line in ht.read_text().splitlines())
    for user, password in lines:
        salt = hashes[user].split("$")[2]
        again = subprocess.run(
            ["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
            input=password,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert again == hashes[user], user
    for name in ("Alice", "BOB", "eve smith"):
        refused = run(
            "sh",
            "scripts/beta/make-htpasswd.sh",
            "--file",
            str(tmp_path / f"{name}.ht"),
            "--passwords-file",
            str(tmp_path / f"{name}.pw"),
            "--group",
            group,
            name,
        )
        assert refused.returncode == 2 and "lowercase" in refused.stderr, name
        assert not (tmp_path / f"{name}.pw").exists()


@needs_sh
def test_make_htpasswd_uses_the_whole_alphabet_and_never_repeats_a_group(tmp_path: Path) -> None:
    """Re-check mutation SHOULD-FIX 1: a cut alphabet or a repeated group must fail."""
    group = subprocess.run(["id", "-gn"], capture_output=True, text=True, check=True).stdout.strip()
    users = [f"tester{i:02d}" for i in range(20)]
    pw = tmp_path / "pw.txt"
    done = run(
        "sh",
        "scripts/beta/make-htpasswd.sh",
        "--file",
        str(tmp_path / "ht"),
        "--passwords-file",
        str(pw),
        "--group",
        group,
        *users,
    )
    assert done.returncode == 0, done.stderr
    passwords = [x.split()[1] for x in pw.read_text().splitlines() if not x.startswith("#")]
    assert len(passwords) == 20 and len(set(passwords)) == 20
    for password in passwords:
        groups = password.split("-")
        assert len(groups) == 4 and len(set(groups)) == 4, password
    symbols = set("".join(passwords).replace("-", ""))
    assert len(symbols) >= 25, sorted(symbols)  # 400 draws from 31 cover nearly all of them
    assert symbols <= set("abcdefghjkmnpqrstuvwxyz23456789")


@needs_sh
def test_make_htpasswd_stops_when_openssl_gives_too_few_bytes(tmp_path: Path) -> None:
    """Re-check mutation SHOULD-FIX 1: the length check is pinned with a short openssl."""
    real = shutil.which("openssl")
    assert real
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "openssl"
    stub.write_text(
        f'#!/bin/sh\nif [ "$1" = rand ]; then printf abc; exit 0; fi\nexec {real} "$@"\n'
    )
    stub.chmod(0o755)
    group = subprocess.run(["id", "-gn"], capture_output=True, text=True, check=True).stdout.strip()
    done = run(
        "sh",
        "scripts/beta/make-htpasswd.sh",
        "--file",
        str(tmp_path / "ht"),
        "--passwords-file",
        str(tmp_path / "pw"),
        "--group",
        group,
        "alice",
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert done.returncode != 0 and "could not draw a password" in done.stderr, done.stderr
    assert "alice" not in (tmp_path / "ht").read_text()


@needs_sh
def test_ship_data_refuses_a_dump_that_carries_excluded_data(tmp_path: Path) -> None:
    """Re-check mutation NIT 2: the excluded-data refusal, through a stub docker."""
    live, data, bin_dir = tmp_path / "live", tmp_path / "data", tmp_path / "bin"
    for d in (live, data, bin_dir):
        d.mkdir()
    (live / "compose.yaml").write_text("services: {}\n")
    (live / ".env").write_text(f"DATA_ROOT={data}\n")
    stub = bin_dir / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"ps --status running"*) echo postgis ;;\n'
        "  *pg_dump*) printf dump ;;\n"
        '  *"pg_restore --list"*) cat >/dev/null; printf "%s\\n"'
        ' "1; 2 3 TABLE DATA live segment x" "4; 5 6 TABLE DATA public override x"'
        ' "7; 8 9 TABLE DATA public app_user x" ;;\n'
        "esac\n"
    )
    stub.chmod(0o755)
    without = []
    for part in ("tiles", "elevation", "basemap", "photon", "frontend"):
        without += ["--without", part]
    done = run(
        "bash",
        SHIP,
        "--live-dir",
        str(live),
        "--stage",
        str(tmp_path / "stage"),
        "--no-transfer",
        *without,
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )
    assert done.returncode == 2, done.stderr
    assert "the dump carries data for app_user, which must be excluded" in done.stderr


def test_the_tester_handout_covers_what_the_sign_in_box_cannot_say() -> None:
    """Final review, accessibility S4, and OWNER-DECISIONS 382 for where to report."""
    handout = (REPO / "docs" / "BETA-TESTER-HANDOUT.md").read_text()
    for needed in (
        "real browser",
        "not from RouteMaker",
        "case-sensitive",
        "paste",
        "say yes",
        "box comes back",
        "Skip to the route planner",
        "Beta notice",
        "Route planner",
        "Tell the person who gave you access",
        "Report a problem",
    ):
        assert needed in handout, needed
    assert "discord.gg" not in handout.lower() and "@gmail" not in handout
    assert "docs/BETA-TESTER-HANDOUT.md" in RUNBOOK
    nine_a = RUNBOOK[RUNBOOK.index("### 9a.") : RUNBOOK.index("### 9b.")]
    eleven = RUNBOOK[RUNBOOK.index("## 11.") : RUNBOOK.index("## Rollback")]
    assert "BETA-TESTER-HANDOUT.md" in nine_a and "BETA-TESTER-HANDOUT.md" in eleven


@needs_sh
def test_make_htpasswd_hashes_with_sha512_crypt_and_prints_no_password(tmp_path: Path) -> None:
    text = (REPO / "scripts" / "beta" / "make-htpasswd.sh").read_text()
    assert "openssl passwd -6 -stdin" in text and "openssl passwd -apr1 -stdin" not in text
    # the password goes only into the 600 file; standard output carries its path
    printing = [
        x for x in text.splitlines() if '"$password"' in x and "printf" in x and "openssl" not in x
    ]
    assert printing and all('>>"$passwords"' in x for x in printing), printing
    taken = tmp_path / "pw.txt"
    taken.write_text("keep")
    done = run(
        "sh",
        "scripts/beta/make-htpasswd.sh",
        "--file",
        str(tmp_path / "new.htpasswd"),
        "--passwords-file",
        str(taken),
        "alice",
    )
    assert done.returncode == 2 and taken.read_text() == "keep"
    assert not (tmp_path / "new.htpasswd").exists()


def test_every_routemaker_service_yields_to_the_hosts_other_sites() -> None:
    for name, service in OVERLAY["services"].items():
        assert service.get("cpu_shares") == 512, name
        assert service.get("oom_score_adj") == 500, name


@needs_sh
def test_rm_absent_refuses_an_empty_argument(tmp_path: Path) -> None:
    """An unset variable must not slip past the guard (`rm_absent "$UNSET" && ...`)."""
    for args in ('""', f'"{tmp_path / "absent"}" ""', ""):
        done = run("bash", "-c", f"{guard_function()}\nrm_absent {args} && echo RAN")
        assert done.returncode != 0 and "RAN" not in done.stdout, args
    ok = run("bash", "-c", f'{guard_function()}\nrm_absent "{tmp_path / "absent"}" && echo RAN')
    assert ok.returncode == 0 and "RAN" in ok.stdout


def test_step_9c_runs_only_the_chosen_tls_options_line() -> None:
    nine_c = RUNBOOK[RUNBOOK.index("### 9c. The full site") :]
    nine_c = nine_c[: nine_c.index("```", nine_c.index("```sh") + 5)]
    installs = [x.strip() for x in nine_c.splitlines() if '"$NGINX_SITE"' in x and "install" in x]
    assert [TLS_BRANCH.match(x).group(1) for x in installs] == ["A", "B"], installs
    assert "export TLS_OPTION=A" in RUNBOOK and "export TLS_OPTION=B" in RUNBOOK
