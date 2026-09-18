"""The three things that stopped `docker compose up` once the images built.

`docs/DEPLOYMENT.md` listed them under "Known blockers": no `config.wsgi` for
the module `settings.WSGI_APPLICATION` names and gunicorn loads, no
`STATIC_ROOT` so `collectstatic` refuses to run and the admin renders unstyled,
and no `Caddyfile` at the path compose bind-mounts - where Docker creates a
directory, so Caddy starts against a directory it cannot parse.

None of it can be executed here: there is no Docker daemon, registries are
blocked, and no Caddy binary exists in this environment, so **nothing below is a
claim that Caddy accepts this config**. What is asserted instead is the set of
things that are false in a deployment that certainly does not work - a WSGI
module that is missing or holds no callable, a static root that is not the
directory compose mounts for it, a `collectstatic` that cannot write the admin's
CSS, and an edge proxy that publishes a service PLAN.md:65 says is reachable
only through the API.

Every value that exists in two places is read from one of them: the static
directory from compose, the upstream port from the api entrypoint, the static
route from `STATIC_URL`, the forwarded-proto header from
`SECURE_PROXY_SSL_HEADER`, and the site-address variable from the caddy
service's own environment.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path, PurePosixPath

import yaml
from django.conf import settings
from django.core.management import call_command

REPO = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text())
SERVICES: dict = COMPOSE["services"]

CADDYFILE = REPO / "Caddyfile"
# Guarded, so that deleting the Caddyfile fails the one test that is about its
# existence rather than erroring the whole module out at collection.
CADDY_TEXT = CADDYFILE.read_text() if CADDYFILE.is_file() else ""

# The host directory the deploy collects into, named once. Everything else about
# it - the container path, and what settings.STATIC_ROOT must be - is derived.
STATIC_MOUNT_SOURCE = "${DATA_ROOT}/static"


def caddy_mount(source: str) -> str:
    """The container path the caddy service mounts a given host path at."""
    for volume in SERVICES["caddy"]["volumes"]:
        host, _, rest = volume.partition(":")
        if host == source:
            return rest.split(":")[0]
    raise AssertionError(f"the caddy service mounts no {source}: {SERVICES['caddy']['volumes']}")


def caddy_directives(name: str) -> list[str]:
    """Every argument list given to a directive, one string per occurrence.

    Text, not a parse: there is no Caddy binary here to validate against. A
    trailing block brace is dropped, since `reverse_proxy api:8000 {` and
    `reverse_proxy api:8000` name the same upstream.
    """
    out = []
    for line in CADDY_TEXT.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        keyword, _, rest = stripped.partition(" ")
        if keyword == name:
            out.append(rest.strip().removesuffix("{").strip())
    return out


def site_addresses() -> list[str]:
    """The address line of every site block at the top level of the file."""
    out = []
    for line in CADDY_TEXT.splitlines():
        stripped = line.strip()
        if line.startswith((" ", "\t")) or stripped.startswith("#") or not stripped.endswith("{"):
            continue
        out.append(stripped.removesuffix("{").strip())
    return out


# --- 1. the WSGI module gunicorn loads ---------------------------------------


def test_the_wsgi_module_exists_and_holds_a_callable_application() -> None:
    """`gunicorn config.wsgi:application` is the api image's default command.

    Until this module landed the api container exited at start with
    ModuleNotFoundError while every other service in the stack came up, because
    `worker`, `migrate` and `rebuild` run `./manage.py` instead.
    """
    module = importlib.import_module("config.wsgi")
    assert callable(module.application), (
        f"config.wsgi.application is not callable: {module.application!r}"
    )


def test_the_wsgi_application_setting_resolves() -> None:
    """Imported by the dotted path settings declares rather than by a literal.

    `WSGI_APPLICATION` is what Django's own `runserver` loads and what
    `tests/test_images.py` holds the entrypoint's gunicorn argument to, so a
    settings value naming a module that does not exist is a stack that starts
    nowhere - and writing `config.wsgi` here would let the two drift apart
    silently.
    """
    declared = settings.WSGI_APPLICATION
    assert declared, "settings declares no WSGI_APPLICATION"
    module_path, _, attribute = declared.rpartition(".")
    module = importlib.import_module(module_path)
    assert callable(getattr(module, attribute)), (
        f"settings.WSGI_APPLICATION names {declared}, which resolves to nothing callable"
    )


# --- 2. the static root collectstatic writes and caddy serves ----------------


def test_the_static_root_is_the_directory_caddy_mounts() -> None:
    """PLAN.md:64 collects the admin and Ninja assets "into the same named
    volume, which Caddy serves". The volume is the host directory in compose's
    caddy mount, so the setting has to be that directory under DATA_ROOT and not
    a second opinion about where assets go."""
    assert settings.STATIC_ROOT, "settings defines no STATIC_ROOT"
    static_root = Path(settings.STATIC_ROOT)
    assert static_root.parent == Path(settings.DATA_ROOT), (
        f"STATIC_ROOT {static_root} is not under DATA_ROOT {settings.DATA_ROOT}; "
        "nothing durable belongs outside the data volume"
    )
    assert static_root.name == PurePosixPath(STATIC_MOUNT_SOURCE).name, (
        f"STATIC_ROOT is {static_root}, but compose mounts {STATIC_MOUNT_SOURCE} "
        f"into caddy at {caddy_mount(STATIC_MOUNT_SOURCE)}"
    )


def test_collectstatic_writes_the_admin_assets(tmp_path, settings) -> None:  # noqa: F811
    """The deploy step itself, run rather than described.

    The configured root is redirected into tmp_path rather than replaced, so
    that a settings module with no STATIC_ROOT still reaches the command with
    nothing set and fails with Django's own ImproperlyConfigured - which is the
    failure this test exists to catch - instead of passing against a root the
    test supplied on its behalf.
    """
    configured = settings.STATIC_ROOT
    settings.STATIC_ROOT = str(tmp_path / Path(configured).name) if configured else configured

    call_command("collectstatic", "--noinput", verbosity=0)

    collected = Path(settings.STATIC_ROOT)
    assert (collected / "admin" / "css" / "base.css").is_file(), (
        f"collectstatic wrote no admin CSS into {collected}; the admin renders unstyled "
        f"behind Caddy. Collected: {sorted(p.name for p in collected.iterdir())}"
    )


# --- 3. the Caddyfile compose bind-mounts ------------------------------------


def test_the_caddyfile_exists_and_is_a_file() -> None:
    """Docker creates a *directory* at a missing bind-mount source, so an absent
    Caddyfile is not a startup error: Caddy starts and serves nothing, against a
    directory at /etc/caddy/Caddyfile."""
    volumes = SERVICES["caddy"]["volumes"]
    mounted = [v for v in volumes if v.startswith("./Caddyfile:")]
    assert mounted, f"the caddy service no longer mounts ./Caddyfile: {volumes}"
    assert CADDYFILE.exists(), "compose mounts ./Caddyfile and the repository has none"
    assert CADDYFILE.is_file(), f"{CADDYFILE} is not a file"


def test_the_site_address_comes_from_the_variable_compose_passes() -> None:
    """One file for the deployment and for a local stack. A literal hostname
    here would be a certificate request for whatever name was committed, on
    every host that ran the stack."""
    addresses = site_addresses()
    assert len(addresses) == 1, f"expected one site block, found: {addresses}"
    reference = re.fullmatch(r"\{\$([A-Z_][A-Z0-9_]*)\}", addresses[0])
    assert reference, f"the site address {addresses[0]!r} is not a `{{$VAR}}` reference"
    caddy_environment = SERVICES["caddy"].get("environment") or {}
    assert reference.group(1) in caddy_environment, (
        f"the Caddyfile reads ${reference.group(1)}, which compose does not pass to the "
        f"caddy service: {sorted(caddy_environment)}"
    )


def test_static_is_served_from_the_path_compose_mounts() -> None:
    """The route is derived from STATIC_URL and the root from the compose mount,
    because a mismatch between either pair is an admin with no CSS rather than an
    error anybody sees."""
    route = f"/{settings.STATIC_URL.strip('/')}/*"
    handled = caddy_directives("handle_path")
    assert route in handled, (
        f"STATIC_URL is {settings.STATIC_URL!r}, so the Caddyfile needs "
        f"`handle_path {route}` (stripping the prefix); it has: {handled}"
    )
    mount = caddy_mount(STATIC_MOUNT_SOURCE)
    assert f"* {mount}" in caddy_directives("root"), (
        f"the file server is not rooted at {mount}, which is where compose mounts "
        f"{STATIC_MOUNT_SOURCE}: {caddy_directives('root')}"
    )
    assert caddy_directives("file_server"), (
        "the static route serves nothing: there is no file_server directive"
    )


def test_the_upstream_is_the_api_on_the_port_the_entrypoint_binds() -> None:
    """Read out of docker/api-entrypoint.sh rather than written twice. A proxy
    to a port gunicorn does not listen on is a 502 on every request."""
    entrypoint = (REPO / "docker" / "api-entrypoint.sh").read_text()
    bind = re.search(r"--bind\s+\"\$\{GUNICORN_BIND:-([^}]+)\}\"", entrypoint)
    assert bind, "the api entrypoint does not bind gunicorn to a default address"
    host, _, port = bind.group(1).rpartition(":")
    assert host == "0.0.0.0", (
        f"gunicorn binds {bind.group(1)}, which is not reachable from the caddy container"
    )
    assert caddy_directives("reverse_proxy") == [f"api:{port}"], (
        f"the Caddyfile proxies {caddy_directives('reverse_proxy')}, but the api entrypoint "
        f"binds gunicorn to port {port}"
    )


def test_no_service_but_the_api_is_reachable_through_the_edge() -> None:
    """PLAN.md:65: Photon, Valhalla and the renderer are reachable only through
    the API, which proxies geocoding behind session authentication and a
    per-user rate limit Photon cannot enforce for itself. A route here would put
    an unauthenticated geocoder, router and renderer on the public internet -
    exactly what `test_only_the_edge_proxy_publishes_ports` prevents by the
    other route."""
    upstreams = {
        argument.split("://")[-1].split(":")[0]
        for directive in caddy_directives("reverse_proxy")
        for argument in directive.split()
        if not argument.startswith("-")
    }
    assert upstreams == {"api"}, f"the edge proxies more than the api: {sorted(upstreams)}"
    others = upstreams & (set(SERVICES) - {"api"})
    assert not others, f"the edge proxies compose services it must not reach: {sorted(others)}"


def test_the_forwarded_proto_header_django_reads_is_set() -> None:
    """Caddy terminates TLS, so the request Django sees is plain HTTP.
    `SECURE_PROXY_SSL_HEADER` is the WSGI key Django checks; the header name is
    derived from it rather than written out, so changing one without the other
    fails here instead of silently disabling `request.is_secure()` - which
    decides the CSRF origin check on every https form post."""
    key, expected_value = settings.SECURE_PROXY_SSL_HEADER
    header = key.removeprefix("HTTP_").replace("_", "-").title()
    set_headers = {
        directive.split(maxsplit=1)[0]: directive.split(maxsplit=1)[1].strip()
        for directive in caddy_directives("header_up")
        if len(directive.split(maxsplit=1)) == 2
    }
    assert header in set_headers, (
        f"settings.SECURE_PROXY_SSL_HEADER reads {key}, so the proxy must set {header}; "
        f"it sets: {sorted(set_headers)}"
    )
    # The name alone was all this pinned, and the name alone is the half that
    # cannot go wrong quietly. `{scheme}` is Caddy's placeholder for the scheme
    # the *client* used; hardcoding the value settings expects - `https` - would
    # also satisfy a name-only assertion, and would make Django call every
    # request secure, including the plain-HTTP ones a stack fronted by an
    # http:// site block or reached directly on the edge's port 80 still serves.
    # `request.is_secure()` would then be true on a connection that is not, so
    # the CSRF origin check would compare against https:// and `Secure` cookies
    # would be set on a cleartext connection.
    assert set_headers[header] == "{scheme}", (
        f"the proxy sets {header} to {set_headers[header]!r} rather than Caddy's "
        f"{{scheme}} placeholder; a literal value makes request.is_secure() report the "
        f"proxy's opinion instead of the client's connection"
    )
    assert expected_value == "https", (
        "settings expects a value this Caddyfile only produces over TLS; if that "
        f"changes, {header} has to change with it"
    )


def test_the_caddyfile_names_no_other_service_at_all() -> None:
    """Stronger than the upstream check and cheap: an internal service's name
    has no business anywhere in the edge's configuration, whether in a
    `reverse_proxy`, a `redir` or a directive nobody has reached for yet.
    Comments are exempt - this file explains what it does not route."""
    body = "\n".join(line for line in CADDY_TEXT.splitlines() if not line.strip().startswith("#"))
    named = sorted(name for name in set(SERVICES) - {"caddy", "api"} if name in body)
    assert not named, f"the Caddyfile names internal services: {named}"


# --- 5. HSTS -----------------------------------------------------------------


def test_the_edge_sets_hsts_on_every_response() -> None:
    """The one header a TLS-terminating edge owes a browser that has been here
    before.

    Neither `settings.py` nor this file had it. Under the shipped hostname
    posture the site is HTTPS-only - Caddy redirects `http` to `https` for a
    named site - and without HSTS the redirect is still a plaintext round trip
    for anyone who types the bare name or follows an old `http://` link.

    At the site level rather than inside a `handle`, so it is on the static
    responses as much as the proxied ones. It is harmless under the `:80`
    posture: RFC 6797 section 8.1 requires a user agent to ignore this header
    when the response did not arrive over a secure transport.
    """
    headers = caddy_directives("header")
    hsts = [value for value in headers if "Strict-Transport-Security" in value]
    assert hsts, f"the Caddyfile sets no Strict-Transport-Security: {headers}"
    assert len(hsts) == 1, f"more than one HSTS header: {hsts}"
    value = hsts[0]
    age = re.search(r"max-age=(\d+)", value)
    assert age, f"the HSTS header declares no max-age: {value!r}"
    assert int(age.group(1)) >= 31536000, (
        f"the HSTS max-age is {age.group(1)}s; a year is the figure worth pinning a "
        "browser to, and anything much shorter is a header without an effect"
    )
    # Both of these commit names this deployment does not serve, and `preload`
    # is a submission to a list that is slow to leave. Neither is a decision
    # this file can make for whoever runs it.
    for opt in ("includeSubDomains", "preload"):
        assert opt.lower() not in value.lower(), (
            f"the HSTS header carries {opt}, which binds more than the one name this "
            f"stack serves: {value!r}"
        )


def test_the_hsts_header_is_not_scoped_to_one_route() -> None:
    """Inside a `handle` it would cover that route's responses and no others -
    including, on the static route, none of the proxied ones. The check is
    positional: the directive sits at the site's own indentation level."""
    lines = CADDY_TEXT.splitlines()
    index = next(
        i for i, line in enumerate(lines) if line.strip().startswith("header Strict-Transport")
    )
    depth = 0
    for line in lines[:index]:
        stripped = line.split("#", 1)[0]
        depth += stripped.count("{") - stripped.count("}")
    assert depth == 1, (
        f"the HSTS header is {depth} blocks deep; at the site level it is one, and "
        "anywhere deeper it covers a subset of the responses"
    )
