"""The rider's weight goes nowhere but the effort model (OWNER-DECISIONS 313: "Not
everyone wants to share their weight"): not into a log line, not into what the
routers are asked, and not into the access logs, which record neither request bodies
nor query strings. The front end keeps it out of links and GPX files, both tested in
frontend/src/lib/weight.test.ts ("the weight is never in a shared link", "the weight
is never in a downloaded GPX file")."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from test_longcalm_api import segments, top_body  # noqa: F401 - the fixture
from test_route_api import post, standard_router

from core import routing

REPO = Path(__file__).resolve().parents[1]
# An unusual weight, so that any appearance of it is the weight's.
WEIGHT = 137

db = pytest.mark.django_db(transaction=True)


@pytest.fixture
def calls(monkeypatch):
    fake = standard_router()
    monkeypatch.setattr(routing, "_transport", fake)
    return fake


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_a_plan_with_a_weight_logs_nothing_of_it(client, calls, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        response = post(client, top_body(system_weight_kg=WEIGHT))
    assert response.status_code == 200
    for record in caplog.records:
        assert not re.search(rf"\b{WEIGHT}\b", record.getMessage()), record.getMessage()


@db
@pytest.mark.usefixtures("weekday_clock", "segments")
def test_the_routers_are_never_sent_the_weight(client, calls) -> None:
    post(client, top_body(system_weight_kg=WEIGHT))
    assert calls.calls
    for _url, payload in calls.calls:
        text = json.dumps(payload)
        assert "weight" not in text and not re.search(rf"\b{WEIGHT}(\.0)?\b", text), text[:200]


def test_the_api_access_log_records_no_body_and_no_query() -> None:
    """gunicorn's access log is the method and the path alone (`%(U)s`, no query string),
    and it logs no request body at all; nothing else in the image logs one."""
    entry = (REPO / "docker" / "api-entrypoint.sh").read_text()
    (fmt,) = re.findall(r"--access-logformat '([^']+)'", entry)
    assert "%(U)s" in fmt
    for field in ("%(r)s", "%(q)s", "%(f)s"):
        assert field not in fmt
    for path in (REPO / "src").rglob("*.py"):
        text = path.read_text()
        assert not re.search(r"log\w*\.\w+\([^)]*request\.body", text), path


def test_the_edge_keeps_no_access_log() -> None:
    """Caddy writes an access log only where a `log` directive asks for one."""
    caddyfile = (REPO / "Caddyfile").read_text()
    assert not re.search(r"(?m)^\s*log(\s|\{|$)", caddyfile)
