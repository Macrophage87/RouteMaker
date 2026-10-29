"""What the servers' own logs keep: PostgreSQL's error log, the api's and the beta's nginx access
logs, the home stack's Caddy, and who can reach the beta's answer cache.

Read from the files the deployments run (compose.yaml, compose.beta.yaml, docker/api-entrypoint.sh,
deploy/beta/nginx-routemaker.conf.template, Caddyfile), as tests/test_beta_overlay.py does. The
rule they hold (Stephen 2026-10-29): nothing that could identify a person's location stays on the
server for more than 2 minutes, except what the rider saves on purpose. A log line is kept for
days or months, so it must not hold a route's points, a link's id or the map a rider is viewing.
"""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

import pytest
from test_beta_overlay import BASE, OVERLAY, beta

from config import access_log

REPO = Path(__file__).resolve().parents[1]
ENTRYPOINT = (REPO / "docker" / "api-entrypoint.sh").read_text()
TEMPLATE = (REPO / "deploy" / "beta" / "nginx-routemaker.conf.template").read_text()
CADDYFILE = (REPO / "Caddyfile").read_text()

RIDE = "9f" * 32
SHARE = "Xy3kQ9vLm2"

# Each path a client asks for, and what the access logs write for it.
LOGGED = {
    f"/api/rides/{RIDE}": "/api/rides/:id",
    f"/api/rides/{RIDE}/here": "/api/rides/:id/here",
    f"/api/rides/{RIDE}/leave": "/api/rides/:id/leave",
    f"/api/rides/{RIDE}/alerts": "/api/rides/:id/alerts",
    f"/api/rides/{RIDE}/alerts/a1b2c3/clear": "/api/rides/:id/alerts/:id/clear",
    f"/api/shared-routes/{SHARE}": "/api/shared-routes/:id",
    f"/api/me/shared-routes/{SHARE}/revoke": "/api/me/shared-routes/:id/revoke",
    f"/s/{SHARE}": "/s/:id",
    f"/s/{SHARE}/preview.png": "/s/:id/preview.png",
    "/mcp/gpx/tok_abc.def-123": "/mcp/gpx/:token",
    "/tiles/stress/16/18750/25074.pbf": "/tiles/stress/:zxy",
    "/tiles/mass/15/9375/12537.pbf": "/tiles/mass/:zxy",
    # Paths with nothing of the kind are logged as they are.
    "/api/route": "/api/route",
    "/api/shared-routes": "/api/shared-routes",
    "/api/me/shared-routes": "/api/me/shared-routes",
    "/api/reverse": "/api/reverse",
    "/mcp": "/mcp",
    "/healthz": "/healthz",
}

# The digits and ids that must not reach a log line.
NEVER_LOGGED = (RIDE, SHARE, "a1b2c3", "tok_abc", "18750", "25074", "9375", "12537")

POSTGRES_LOG_SETTINGS = {
    "log_min_error_statement": "panic",
    "log_error_verbosity": "terse",
    "log_statement": "none",
    "log_min_duration_statement": "-1",
}


def postgres_settings(command: list[str]) -> dict[str, str]:
    """The `-c name=value` settings of a `postgres ...` command."""
    assert command and command[0] == "postgres", command
    flags = [command[i + 1] for i, word in enumerate(command[:-1]) if word == "-c"]
    return dict(flag.split("=", 1) for flag in flags)


# --- PostgreSQL ---------------------------------------------------------------------


@pytest.mark.parametrize("name", ["compose.yaml", "compose.beta.yaml"])
def test_postgres_logs_a_failed_statement_without_its_text_or_values(name: str) -> None:
    """psycopg2 fills the parameters into the SQL it sends, so a failed statement's text holds
    a route's points or the saved Home; its DETAIL holds the refused row."""
    services = (BASE if name == "compose.yaml" else OVERLAY)["services"]
    found = postgres_settings(services["postgis"]["command"])
    for setting, value in POSTGRES_LOG_SETTINGS.items():
        assert found.get(setting) == value, (name, setting, found)


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_the_beta_postgres_keeps_its_memory_settings_and_the_log_settings() -> None:
    """The overlay's command replaces the base file's, so both sets must be in what runs."""
    found = postgres_settings(beta.render()["services"]["postgis"]["command"])
    for setting, value in POSTGRES_LOG_SETTINGS.items():
        assert found.get(setting) == value, (setting, found)
    assert found["shared_buffers"] == "256MB"


# --- the api's access log (gunicorn) ------------------------------------------------


def test_gunicorn_writes_its_access_log_through_the_path_redacting_logger() -> None:
    match = re.search(r"--logger-class\s+(\S+)", ENTRYPOINT)
    assert match and match.group(1) == "config.access_log.Logger", ENTRYPOINT[-800:]
    fmt = re.search(r"--access-logformat\s+'([^']*)'", ENTRYPOINT).group(1)
    # What ops reads the log for: the method, the path, the status and the time taken.
    for atom in ("%(m)s", "%(U)s", "%(s)s", "%(D)s"):
        assert atom in fmt, fmt


@pytest.mark.parametrize(("path", "logged"), LOGGED.items())
def test_link_ids_and_tile_coordinates_are_logged_as_the_routes_shape(path, logged) -> None:
    assert access_log.logged_path(path) == logged


def test_an_access_line_holds_the_method_status_and_time_but_no_id_or_tile() -> None:
    glogging = pytest.importorskip("gunicorn.glogging")
    from gunicorn.config import Config

    fmt = re.search(r"--access-logformat\s+'([^']*)'", ENTRYPOINT).group(1)
    logger = access_log.Logger(Config())
    assert isinstance(logger, glogging.Logger)

    class Response:
        status = "200 OK"
        sent = 512
        headers: list = []

    class Request:
        headers = [("USER-AGENT", "test")]

    for path, logged in LOGGED.items():
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "RAW_URI": f"{path}?lat=38.91234&lon=-77.03456",
            "QUERY_STRING": "lat=38.91234&lon=-77.03456",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_USER_AGENT": "test",
        }
        atoms = logger.atoms(Response(), Request(), environ, datetime.timedelta(milliseconds=42))
        line = fmt % logger.atoms_wrapper_class(atoms)
        assert f'"GET {logged}" 200 512 42000' in line, line
        assert all(atoms[key] == "-" or logged in atoms[key] for key in ("r", "q", "f")), atoms
        assert "38.91234" not in repr(dict(atoms)), atoms
        if logged != path:
            assert not any(secret in line for secret in NEVER_LOGGED), line


# --- the beta's nginx -----------------------------------------------------------------


def nginx_logpath_map() -> list[tuple[re.Pattern[str], str]]:
    """`map $uri $rmbeta_logpath`'s regex entries, in order, as Python regexes."""
    block = re.search(r"map \$uri \$rmbeta_logpath \{\n(.*?)\n\}", TEMPLATE, re.S)
    assert block, "the nginx template has no `map $uri $rmbeta_logpath`"
    entries = []
    for line in block.group(1).splitlines():
        line = line.strip()
        if line.startswith("default"):
            assert line == "default $uri;", line
            continue
        source, value = re.fullmatch(r'"~(.*)" (\S+);', line).groups()
        entries.append((re.compile(source.replace("(?<", "(?P<")), value))
    return entries


def nginx_logged_path(path: str) -> str:
    for pattern, value in nginx_logpath_map():
        found = pattern.match(path)
        if found:
            groups = found.groupdict()
            return re.sub(r"\$\{?(\w+)\}?", lambda m, g=groups: g[m.group(1)] or "", value)
    return path


def test_nginx_logs_the_redacted_path_and_never_the_query() -> None:
    (fmt,) = re.findall(r"log_format rmbeta_noquery '([^']*)'", TEMPLATE)
    assert "$rmbeta_logpath" in fmt
    for raw in ("$uri", "$request ", "$request_uri", "$args", "$query_string", "$remote_addr"):
        assert raw not in fmt, (raw, fmt)
    for atom in ("$request_method", "$status", "$request_time"):
        assert atom in fmt, fmt
    # Every access log of the site uses that format.
    for line in re.findall(r"^\s*access_log .*$", TEMPLATE, re.M):
        assert line.strip().endswith("rmbeta_noquery;"), line


@pytest.mark.parametrize(("path", "logged"), LOGGED.items())
def test_nginx_logs_the_same_path_as_the_api(path: str, logged: str) -> None:
    assert nginx_logged_path(path) == logged


def test_nginx_logs_only_critical_errors_for_tiles_links_and_gpx() -> None:
    """An upstream error line records the request, its query and the client's address."""
    # The https server's: the last `location / {` in the file (port 80's only redirects).
    for location in ("location / {", "location ~ ^/s/[^/]+(/preview\\.png)?$ {"):
        body = TEMPLATE.rsplit(location, 1)[1].split("\n    }", 1)[0]
        assert "error_log /var/log/nginx/rmbeta-error.log crit;" in body, location


# --- the home stack's Caddy -------------------------------------------------------------


def test_caddys_error_entries_leave_out_the_uri_and_the_client() -> None:
    """With no access log, Caddy still logs an error entry (the API down during a deploy), and
    that entry carries the request URI with its lat/lon query and the client's address."""
    first = CADDYFILE.split("{$CADDY_SITE_ADDRESS}", 1)[0]
    block = re.search(r"(?m)^\{\n(.*?)^\}", first, re.S)
    assert block, "the Caddyfile has no global options block before its site"
    options = block.group(1)
    assert re.search(r"log default \{\s*format filter \{", options), options
    for field in ("request>uri", "request>remote_ip", "request>client_ip", "request>headers"):
        assert re.search(rf"^\s*{re.escape(field)} delete$", options, re.M), field
    assert "output discard" not in options  # the error itself is still logged


# --- the beta's answer cache ------------------------------------------------------------


def test_the_answer_cache_is_reachable_only_from_the_api() -> None:
    """memcached has no sign-in, so it sits on a network that only the api joins."""
    services = OVERLAY["services"]
    assert services["memcached"]["networks"] == ["routecache"]
    assert set(services["api"]["networks"]) == {"default", "routecache"}
    assert OVERLAY["networks"]["routecache"] == {"internal": True}
    for name, service in services.items():
        if name not in ("api", "memcached"):
            assert "routecache" not in (service.get("networks") or []), name


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker is not installed")
def test_the_rendered_beta_puts_only_the_api_beside_the_answer_cache() -> None:
    services = beta.render()["services"]
    joined = {name for name, s in services.items() if "routecache" in (s.get("networks") or {})}
    assert joined == {"api", "memcached"}
    assert set(services["memcached"]["networks"]) == {"routecache"}
