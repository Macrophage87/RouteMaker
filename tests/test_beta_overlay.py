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
OVERLAY = yaml.safe_load((REPO / "compose.beta.yaml").read_text())
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


@needs_docker
def test_the_overlay_renders_and_passes_the_beta_checker(rendered: dict) -> None:
    problems = beta.check(rendered, beta.DUMMY_ENV["DATA_ROOT"])
    assert not problems, problems


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
def test_the_resident_total_is_about_six_and_three_quarter_gib(rendered: dict) -> None:
    total = beta.resident_bytes(rendered["services"]) / 1024**3
    assert 6.0 <= total <= beta.MAX_RESIDENT_GB, total


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
    assert api["WEB_CONCURRENCY"] == "3"
    assert api["WEEKLY_REBUILD_PAUSED"] == "1"


def test_the_overlay_parks_caddy_and_rebuild_behind_a_profile() -> None:
    for name in ("caddy", "rebuild"):
        assert OVERLAY["services"][name] == {"profiles": ["not-in-beta"]}


def test_photons_command_differs_from_the_base_only_in_the_jvm_heap() -> None:
    """The overlay restates the whole command to change the heap; if the base moves, this fails."""
    base = BASE["services"]["photon"]["command"]
    mine = OVERLAY["services"]["photon"]["command"]
    assert base[:2] == mine[:2]
    heap = re.compile(r"-Xm[sx]\d+[mg]")
    assert heap.sub("-XmX", base[2]) == heap.sub("-XmX", mine[2])
    assert heap.findall(mine[2]) == ["-Xms512m", "-Xmx896m"]


def test_every_overridden_service_exists_in_the_base() -> None:
    placeholder = {"valhalla-offroad"}
    assert set(OVERLAY["services"]) - placeholder <= set(BASE["services"])


# --- the checker catches what it exists to catch ---


def good() -> dict:
    def svc(mem_mb: int, cpus: str = "1", **extra) -> dict:
        return {
            "deploy": {"resources": {"limits": {"memory": f"{mem_mb}M", "cpus": cpus}}},
            "memswap_limit": f"{mem_mb}M",
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
                1200,
                "2",
                environment={"WEB_CONCURRENCY": "3", "WEEKLY_REBUILD_PAUSED": "1"},
                ports=[{"host_ip": "127.0.0.1", "published": "8087", "target": 8000}],
            ),
            "worker": svc(320, "0.5", environment={"WEEKLY_REBUILD_PAUSED": "1"}),
            "migrate": svc(256, "0.5", environment={"WEEKLY_REBUILD_PAUSED": "1"}),
            "postgis": svc(1024, "1.5", command=["postgres", "-c", "shared_buffers=256MB"]),
            "photon": svc(
                1300, "1", command=["sh", "-c", "exec java -Xms512m -Xmx896m -jar photon.jar"]
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
            lambda s: s["photon"].update(command=["sh", "-c", "exec java -Xmx1200m -jar p.jar"]),
            "photon: -Xmx1200m",
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


def test_the_checker_reads_compose_rendered_byte_counts() -> None:
    assert beta.parse_bytes("1258291200") == 1200 * 1024**2
    assert beta.parse_bytes("768M") == 768 * 1024**2
    assert beta.parse_bytes("1.5G") == int(1.5 * 1024**3)
    assert beta.parse_bytes("768MiB") == 768 * 1024**2


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
    names = re.findall(r"^(?:upstream\s+(\S+)|map\s+\S+\s+(\$\S+))", full, re.M)
    flat = [n for pair in names for n in pair if n]
    assert flat and all(n.lstrip("$").startswith("rmbeta_") for n in flat), flat
    assert (
        "limit_req_zone" not in full
        and "ssl_session_cache" not in full
        and "ssl_dhparam" not in full
    )


def test_basic_auth_is_on_for_the_whole_https_server_and_off_only_for_robots_and_acme() -> None:
    full = stage("full")
    https = full[full.index("listen 443") :]
    assert re.search(r'^\s*auth_basic\s+"RouteMaker beta";', https, re.M)
    assert "auth_basic_user_file @HTPASSWD_FILE@;" in https
    exempt = [path for path, body in locations(full) if "auth_basic off" in body]
    assert sorted(exempt) == sorted(["^~ /.well-known/acme-challenge/", "= /robots.txt"]), exempt


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
        assert not re.search(
            r"(?m)^\s*(?:PGPASSWORD|DJANGO_SECRET_KEY|KEY_ENCRYPTION_KEY)=[0-9a-f]{20,}", text
        ), path.name
        assert "BEGIN PRIVATE KEY" not in text and "BEGIN RSA PRIVATE" not in text, path.name
