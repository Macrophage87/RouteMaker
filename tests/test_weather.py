"""Weather along a route (Stephen 2026-10-24; core.weather, POST /api/weather/check)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from core import weather

# 6 PM in Washington.
NOW = datetime(2026, 10, 24, 22, 0, tzinfo=UTC).timestamp()


def steps(amounts):
    """15-minute steps from NOW: (end of step, inches)."""
    return [(NOW + 900 * (i + 1), a) for i, a in enumerate(amounts)]


def alert(
    event,
    severity="Severe",
    ident="a1",
    status="Actual",
    kind="Alert",
    onset=None,
    ends=None,
    instruction=None,
):
    return {
        "id": ident,
        "properties": {
            "id": ident,
            "event": event,
            "severity": severity,
            "status": status,
            "messageType": kind,
            "onset": onset or "2026-10-24T17:30:00-04:00",
            "ends": ends or "2026-10-24T19:00:00-04:00",
            "expires": "2026-10-24T18:30:00-04:00",
            "areaDesc": "District of Columbia",
            "instruction": instruction,
        },
    }


def rain_doc(amounts_by_point):
    """Open-Meteo's answer: steps ending every 15 minutes from the step after NOW."""
    docs = []
    for amounts in amounts_by_point:
        times = [int(NOW) + 900 * (i + 1) for i in range(len(amounts))]
        docs.append({"minutely_15": {"time": times, "precipitation": amounts}})
    return docs if len(docs) > 1 else docs[0]


class Fake:
    """The two services, answering by URL; every URL asked is kept."""

    def __init__(self, alerts=None, rain=None, fail=()):
        self.alerts = alerts or {}
        self.rain = rain
        self.fail = set(fail)
        self.asked: list[str] = []

    def __call__(self, url, timeout):
        self.asked.append(url)
        assert timeout <= weather.TIMEOUT_S
        if url.startswith(weather.ALERTS_URL):
            if "alerts" in self.fail:
                raise weather.Unavailable("HTTP 503")
            point = url.split("point=")[1].replace("%2C", ",")
            return json.dumps({"features": self.alerts.get(point, [])}).encode()
        if "rain" in self.fail:
            raise weather.Unavailable("URLError")
        return json.dumps(self.rain).encode()


@pytest.mark.parametrize(
    "event, severity, kept",
    [
        ("Tornado Warning", "Extreme", True),
        ("Severe Thunderstorm Warning", "Severe", True),
        ("Flash Flood Watch", "Severe", True),
        ("Heat Advisory", "Moderate", True),
        ("Special Weather Statement", "Moderate", True),
        ("Air Quality Alert", "Unknown", True),
        ("Hydrologic Outlook", "Minor", False),
        ("Small Craft Advisory", "Minor", False),
        ("Gale Warning", "Severe", False),
        ("Rip Current Statement", "Moderate", False),
        ("Freeze Warning", "Severe", False),
        ("Frost Advisory", "Minor", False),
    ],
)
def test_only_the_alerts_that_matter_on_a_bike(event, severity, kept) -> None:
    assert weather.relevant(alert(event, severity)["properties"]) is kept


def test_tests_and_cancellations_are_left_out() -> None:
    assert not weather.relevant(alert("Tornado Warning", status="Test")["properties"])
    assert not weather.relevant(alert("Tornado Warning", kind="Cancel")["properties"])
    assert weather.relevant(alert("Tornado Warning", kind="Update")["properties"])


def test_an_alert_as_the_page_gets_it() -> None:
    words = "Move to an interior room.  " + "Stay put. " * 80
    [out] = weather.parse_alerts(
        {"features": [alert("Tornado Warning", "Extreme", instruction=words)]}, (38.9, -77.03)
    )
    assert out["event"] == "Tornado Warning" and out["severity"] == "Extreme"
    assert out["ends"] == "2026-10-24T19:00:00-04:00"
    assert out["url"] == "https://forecast.weather.gov/MapClick.php?lat=38.90&lon=-77.03"
    assert out["instruction"].startswith("Move to an interior room. Stay")
    assert len(out["instruction"]) <= weather.INSTRUCTION_MAX and out["instruction"].endswith("…")


def test_first_rain_is_where_the_rider_will_be() -> None:
    points = [(-77.0, 38.9, 0), (-77.0, 39.0, 1800), (-77.0, 39.1, 3600)]
    dry, wet_later, wet = [0.0] * 8, [0.0, 0.0, 0.0, 0.0, 0.05, 0.05, 0, 0], [0.2] * 8
    # Rain at the first point only after the rider has left it; the second point is dry at 30
    # min; the third has rain as the rider gets there (60 min: the step from 60 to 75 min).
    out = weather.first_rain(points, [steps(wet_later), steps(dry), steps(wet_later)], NOW)
    assert out == {
        "index": 2,
        "offset_s": 3600,
        "starts_in_s": 3600,
        "inches": 0.05,
        "heavy": False,
    }
    assert weather.first_rain(points, [steps(dry)] * 3, NOW) is None
    assert weather.first_rain(points, [steps(wet), steps(dry), steps(dry)], NOW)["heavy"] is True


def test_rain_past_the_forecast_is_not_looked_for() -> None:
    assert weather.first_rain([(-77.0, 38.9, 5 * 3600)], [[(NOW + 900, 1.0)]], NOW) is None


def test_the_check_rounds_points_and_shares_answers() -> None:
    fake = Fake(
        alerts={
            "38.90,-77.03": [alert("Severe Thunderstorm Warning")],
            "39.29,-76.61": [
                alert("Severe Thunderstorm Warning"),
                alert("Heat Advisory", "Moderate", "a2"),
            ],
        },
        rain=rain_doc([[0.0] * 8, [0.0, 0.0, 0.0, 0.0, 0.3, 0, 0, 0]]),
    )
    w = weather.Weather(fetch=fake, clock=lambda: NOW)
    points = [(-77.03214, 38.90123, 0), (-77.0301, 38.8999, 300), (-76.6122, 39.2904, 3600)]
    out = w.check(points)
    # Two cells, not three points; no unrounded coordinate leaves the server.
    assert len([u for u in fake.asked if u.startswith(weather.ALERTS_URL)]) == 2
    assert not any("38.901" in u or "77.032" in u for u in fake.asked)
    assert [a["event"] for a in out["alerts"]] == ["Severe Thunderstorm Warning", "Heat Advisory"]
    assert out["rain"]["index"] == 2 and out["rain"]["heavy"] is True
    assert out["unchecked"] == []
    # Asked again inside the 2 minutes: nothing new is fetched.
    before = len(fake.asked)
    w.check(points)
    assert len(fake.asked) == before


def test_nothing_is_kept_past_two_minutes() -> None:
    clock = [NOW]
    fake = Fake(rain=rain_doc([[0.0] * 8]))
    w = weather.Weather(fetch=fake, clock=lambda: clock[0])
    w.check([(-77.0, 38.9, 0)])
    clock[0] += weather.KEEP_S
    w.check([(-77.0, 38.9, 0)])
    assert len(fake.asked) == 4
    assert all(at >= clock[0] - weather.KEEP_S for at, _ in w._alerts.values())


def test_an_alert_over_before_the_ride_or_after_it_is_left_out() -> None:
    moment = datetime.fromtimestamp(NOW, UTC)
    assert not weather.in_ride({"ends": "2026-10-24T13:00:00-04:00", "onset": None}, moment, 3600)
    assert not weather.in_ride({"onset": "2026-10-24T20:00:00-04:00", "ends": None}, moment, 3600)
    assert weather.in_ride({"onset": "2026-10-24T14:30:00-04:00", "ends": None}, moment, 3600)


def test_a_service_down_is_said_not_failed() -> None:
    w = weather.Weather(fetch=Fake(fail=("alerts", "rain")), clock=lambda: NOW)
    out = w.check([(-77.0, 38.9, 0)])
    assert out == {"alerts": [], "rain": None, "unchecked": ["alerts", "rain"]}


@pytest.mark.parametrize(
    "points, ok",
    [
        ([[-77.0, 38.9, 0]], True),
        ([[-77.0, 38.9, 0]] * weather.MAX_POINTS, True),
        ([[-77.0, 38.9, 0]] * (weather.MAX_POINTS + 1), False),
        ([], False),
        ([[-77.0, 38.9]], False),
        ([[-77.0, 98.9, 0]], False),
        ([[-77.0, 38.9, -1]], False),
        ([[-77.0, 38.9, True]], False),
        ("nope", False),
    ],
)
def test_points_problem(points, ok) -> None:
    assert (weather.points_problem(points) is None) is ok


@pytest.mark.django_db
def test_the_endpoint(client, monkeypatch) -> None:
    fake = Fake(
        alerts={"38.90,-77.03": [alert("Tornado Warning", "Extreme")]}, rain=rain_doc([[0.0] * 8])
    )
    monkeypatch.setattr(weather, "_shared", weather.Weather(fetch=fake, clock=lambda: NOW))
    headers = {"HTTP_X_FORWARDED_FOR": "198.51.100.12"}
    r = client.post(
        "/api/weather/check",
        data=json.dumps({"points": [[-77.031, 38.901, 0]]}),
        content_type="application/json",
        **headers,
    )
    assert r.status_code == 200 and r["Cache-Control"] == "no-store"
    assert [a["event"] for a in r.json()["alerts"]] == ["Tornado Warning"]
    bad = client.post(
        "/api/weather/check",
        data=json.dumps({"points": [[-77.0, 38.9]]}),
        content_type="application/json",
        **headers,
    )
    assert bad.status_code == 400
