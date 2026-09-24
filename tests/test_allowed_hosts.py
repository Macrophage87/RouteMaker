"""`DJANGO_ALLOWED_HOSTS` as the application parses it and as the api
healthcheck in compose.yaml parses it.

Round 10 (security SF10-3): the settings did not strip whitespace while the
healthcheck and two tests did, so `a, b` made every request for `b` a 400 on
the live site. And the healthcheck sent the first entry verbatim, so `*` or an
empty first entry was a Host header Django refuses and a red check on a healthy
stack.

The properties, for a spread of ways a person writes the variable: every name
written is a host the application accepts, and the Host the healthcheck sends
is always one the application accepts - whenever the application accepts any.
"""

from __future__ import annotations

import importlib.util
import urllib.request
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import DisallowedHost
from django.test import RequestFactory, override_settings

REPO = Path(__file__).resolve().parents[1]

# The ways the variable gets written: spaced lists, a stray comma, the wildcard
# first or later, a subdomain pattern, an empty value, and the local posture.
WRITTEN = [
    "routes.example.org",
    "a.example.org, b.example.org",
    "  routes.example.org  ",
    "a.example.org,,b.example.org",
    ",routes.example.org",
    " , routes.example.org",
    "*",
    " *, routes.example.org",
    "routes.example.org,*",
    ".example.org",
    "localhost,127.0.0.1",
    "",
    ",",
    " ",
]


def settings_under(monkeypatch, value):
    """Execute `config/settings.py` afresh with the variable set (or unset, for
    None), under another module name so the live settings are untouched."""
    import config.settings as live

    if value is None:
        monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", value)
    spec = importlib.util.spec_from_file_location("settings_allowed_hosts", live.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def accepts(allowed_hosts, host, *, debug) -> bool:
    """Whether Django answers a request carrying this Host, through the real
    `HttpRequest.get_host` - which includes DEBUG's own empty-list default."""
    request = RequestFactory().get("/healthz", HTTP_HOST=host)
    with override_settings(ALLOWED_HOSTS=allowed_hosts, DEBUG=debug):
        try:
            request.get_host()
        except DisallowedHost:
            return False
    return True


def healthcheck_host(monkeypatch, value) -> str:
    """Run the api healthcheck's own `python -c` body, as compose.yaml has it,
    with urlopen replaced, and return the Host header it sent."""
    test = yaml.safe_load((REPO / "compose.yaml").read_text())["services"]["api"]["healthcheck"][
        "test"
    ]
    assert test[:3] == ["CMD", "python", "-c"], test
    sent = []

    class Answer:
        status = 200

    def fake_urlopen(request, timeout=None):
        sent.append(dict(request.header_items()))
        return Answer()

    if value is None:
        monkeypatch.delenv("DJANGO_ALLOWED_HOSTS", raising=False)
    else:
        monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", value)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(SystemExit) as exit_:
        exec(test[3], {})
    assert exit_.value.code == 0
    assert len(sent) == 1
    return sent[0]["Host"]


@pytest.mark.parametrize("value", WRITTEN)
def test_every_name_written_is_accepted(monkeypatch, value) -> None:
    hosts = settings_under(monkeypatch, value).ALLOWED_HOSTS
    for written in (part.strip() for part in value.split(",")):
        if not written:
            continue
        probe = written.lstrip(".") if written != "*" else "anything.example.net"
        assert accepts(hosts, probe, debug=False), (value, hosts, probe)
    assert all(host == host.strip() and host for host in hosts), hosts


def test_the_unset_variable_is_still_localhost(monkeypatch) -> None:
    assert settings_under(monkeypatch, None).ALLOWED_HOSTS == ["localhost"]


@pytest.mark.parametrize(
    "value",
    [
        "https://routes.example.org",
        "http://localhost, http://127.0.0.1",
        "  https://routes.example.org  ",
        "http://localhost,,http://127.0.0.1",
        ", http://localhost",
        "http://localhost, , http://127.0.0.1",
        " ",
        "",
    ],
)
def test_every_trusted_origin_written_is_trusted(monkeypatch, value) -> None:
    """The neighbouring variable, parsed the same way and with the same defect:
    the CSRF middleware matches an Origin header exactly, so an unstripped
    `" http://127.0.0.1"` trusted nothing and every POST from it was refused."""
    from django.middleware.csrf import CsrfViewMiddleware

    monkeypatch.setenv("DJANGO_CSRF_TRUSTED_ORIGINS", value)
    origins = settings_under(monkeypatch, "localhost").CSRF_TRUSTED_ORIGINS
    with override_settings(CSRF_TRUSTED_ORIGINS=origins):
        trusted = CsrfViewMiddleware(lambda request: None).allowed_origins_exact
    written = {part.strip() for part in value.split(",") if part.strip()}
    assert written <= trusted, (value, origins)
    assert all(origin == origin.strip() and origin for origin in origins), origins


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("value", [*WRITTEN, None])
def test_the_healthcheck_sends_a_host_the_application_accepts(monkeypatch, value, debug) -> None:
    hosts = settings_under(monkeypatch, value).ALLOWED_HOSTS
    if not hosts and not debug:
        pytest.skip("an empty list outside DEBUG accepts no host at all; red is right")
    host = healthcheck_host(monkeypatch, value)
    assert accepts(hosts, host, debug=debug), (value, hosts, host)
