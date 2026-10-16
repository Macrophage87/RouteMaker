"""Ride mode's 311 sent from the server (v0.7.0 "Go riding fixes" item 3; core.dc311): off
without DC311_API_KEY, and with it one GeoReport v2 POST to DC's requests.json, with DC's own
service code for the problem. No test reaches DC: the transport is replaced."""

from __future__ import annotations

import json

import pytest

from core import dc311

HERE = {"lat": 38.91234, "lon": -77.02401}
SERVICES = [
    {"service_code": "S0276", "service_name": "Pothole"},
    {"service_code": "S0346", "service_name": "Streetlight Repair Investigation"},
    {"service_code": "S0456", "service_name": "Tree Inspection"},
    {"service_code": "S0261", "service_name": "Parking Enforcement"},
]


@pytest.fixture
def dc(monkeypatch, settings):
    """DC's endpoint replaced: services.json answers SERVICES; requests.json records each form."""
    dc311.forget_services()
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(dc311, "_get", lambda url: SERVICES)

    def post(url, form):
        sent.append((url, form))
        return [{"service_request_id": "21-00012345"}]

    monkeypatch.setattr(dc311, "_post", post)
    yield sent
    dc311.forget_services()


def test_off_without_a_key(dc, settings) -> None:
    settings.DC311_API_KEY = ""
    assert not dc311.enabled()
    with pytest.raises(dc311.NotSent) as refused:
        dc311.send("pothole", HERE["lat"], HERE["lon"], "Pothole. Location: on R Street")
    assert refused.value.code == "dc311_off"
    assert dc == []


def test_a_pothole_is_sent_with_dcs_code_and_the_place(dc, settings) -> None:
    settings.DC311_API_KEY = "placeholder-not-a-key"
    ident = dc311.send("pothole", HERE["lat"], HERE["lon"], "Pothole on R Street Northwest.")
    assert ident == "21-00012345"
    ((url, form),) = dc
    assert url == f"{dc311.ENDPOINT}/requests.json"
    assert form["service_code"] == "S0276"
    assert form["jurisdiction_id"] == "dc.gov"
    assert (form["lat"], form["long"]) == ("38.91234", "-77.02401")
    assert form["description"] == "Pothole on R Street Northwest."
    assert form["api_key"] == "placeholder-not-a-key"


def test_each_problem_finds_its_service_or_is_not_sent(dc, settings) -> None:
    settings.DC311_API_KEY = "placeholder-not-a-key"
    assert dc311.service_code("streetlight", SERVICES) == "S0346"
    assert dc311.service_code("tree", SERVICES) == "S0456"
    assert dc311.service_code("bikeLane", SERVICES) == "S0261"
    assert dc311.service_code("obstruction", SERVICES) is None
    with pytest.raises(dc311.NotSent) as refused:
        dc311.send("other", HERE["lat"], HERE["lon"], "Something")
    assert refused.value.code == "no_service"
    with pytest.raises(dc311.NotSent) as refused:
        dc311.send("pothole", 39.29, -76.61, "Baltimore")
    assert refused.value.code == "outside_dc"
    assert dc == []


@pytest.mark.django_db
def test_the_endpoints(client, dc, settings) -> None:
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.31"}
    settings.DC311_API_KEY = ""
    assert client.get("/api/report311").json() == {"enabled": False}
    body = json.dumps({"kind": "pothole", **HERE, "description": "Pothole."})
    off = client.post("/api/report311", data=body, content_type="application/json", **headers)
    assert off.status_code == 503 and off.json()["code"] == "dc311_off"

    settings.DC311_API_KEY = "placeholder-not-a-key"
    status = client.get("/api/report311").json()
    assert status["enabled"] is True and dc311.ticket_ok(status["ticket"])
    # On, a send without the page's ticket (or with a forged one) is refused, nothing sent.
    for ticket in (None, "forged", status["ticket"] + "x"):
        refused = client.post(
            "/api/report311",
            data=json.dumps({"kind": "pothole", **HERE, "ticket": ticket}),
            content_type="application/json",
            **headers,
        )
        assert refused.status_code == 403 and refused.json()["code"] == "no_ticket"
    assert dc == []
    body = json.dumps(
        {"kind": "pothole", **HERE, "description": "Pothole.", "ticket": status["ticket"]}
    )
    sent = client.post("/api/report311", data=body, content_type="application/json", **headers)
    assert sent.status_code == 200 and sent.json() == {"sent": True, "id": "21-00012345"}
    bad = client.post(
        "/api/report311",
        data=json.dumps({"kind": "ufo", **HERE}),
        content_type="application/json",
        **headers,
    )
    assert bad.status_code == 400
    assert len(dc) == 1


def test_a_ticket_is_short_lived(settings, monkeypatch) -> None:
    from django.core import signing

    value = dc311.ticket()
    assert dc311.ticket_ok(value)
    later = signing.loads
    monkeypatch.setattr(
        signing,
        "loads",
        lambda v, salt, max_age: later(v, salt=salt, max_age=max_age - dc311.TICKET_MAX_AGE_S - 1),
    )
    assert not dc311.ticket_ok(value)
    assert dc311.TICKET_MAX_AGE_S <= 30 * 60


@pytest.mark.django_db
def test_every_address_together_is_held_to_an_hourly_cap(client, dc, settings, monkeypatch) -> None:
    """However many addresses send, at most HOURLY_MAX reports an hour go to DC from here."""
    settings.DC311_API_KEY = "placeholder-not-a-key"
    monkeypatch.setattr(dc311, "HOURLY_MAX", 2)
    codes = []
    for n in range(3):
        ticket = client.get("/api/report311").json()["ticket"]
        r = client.post(
            "/api/report311",
            data=json.dumps({"kind": "pothole", **HERE, "ticket": ticket}),
            content_type="application/json",
            HTTP_X_FORWARDED_FOR=f"198.51.100.{60 + n}",
        )
        codes.append(r.status_code)
    assert codes == [200, 200, 429] and len(dc) == 2


@pytest.mark.django_db
def test_the_status_answers_this_site_s_pages_only_and_is_rate_limited(client, monkeypatch) -> None:
    from core import ratelimit

    foreign = client.get("/api/report311", HTTP_SEC_FETCH_SITE="cross-site")
    assert foreign.status_code == 403
    scopes = []

    def hit(limit, key):
        scopes.append(limit.scope)
        return ratelimit.Decision(allowed=False, retry_after_s=9)

    monkeypatch.setattr(ratelimit, "hit", hit)
    busy = client.get("/api/report311")
    assert busy.status_code == 429 and busy["Retry-After"] == "9"
    assert scopes == [ratelimit.REPORT_311_STATUS.scope]
