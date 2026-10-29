"""Weather along a route: the National Weather Service's alerts and rain in the next hours.

Stephen, 2026-10-24: "Add a check for severe weather and send an alert if there's any relevant
NWS alert both before starting a ride and during it. Link to the notice. If there's any API that
could say rain possible in the next x min or something that could be helpful too".

The page sends a few points along the line still to ride, each with the seconds until the rider
gets there at the route's pace (POST /api/weather/check). The server answers with:

- **Alerts**: the NWS's active alerts at each point (api.weather.gov `/alerts/active?point=`,
  U.S. government data, free for any use; the API asks for a User-Agent naming the app). Only the
  alerts that matter on a bike are kept (`relevant`): every Extreme or Severe one (warnings and
  watches), and the advisories in `ADVISORIES` (heat, wind, fog, ice, flooding, air quality and the
  Special Weather Statements that carry strong storms); never the marine and beach ones, which a
  point near the tidal Potomac can fall in. An alert ending before the ride starts, or starting
  after it ends, is left out.
- **Rain**: the first point where rain is forecast as the rider gets there (`first_rain`), from
  Open-Meteo's 15-minute forecast (api.open-meteo.com, `minutely_15=precipitation`), which in
  North America is NOAA's HRRR model at 15-minute steps, updated hourly. Data CC BY 4.0, the API
  free for non-commercial apps (open-meteo.com/en/terms, read 2026-10-24). NOAA's own forecast
  gives rain chances by the hour only, so cannot say "in about 30 minutes".

Privacy (Stephen 2026-10-22: nothing of a ride stays on the server more than 2 minutes): the
points come in a POST body, so no access log has them; each is rounded to 0.01 degree (about 0.7
mi, 1.1 km) before anything is asked, so neither service learns a rider's position or address
(they see only this server); the answers are kept in memory by rounded cell for `KEEP_S` seconds
(two riders near each other share them) and nothing is written anywhere. A failure is logged by
its type only, never a point.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

USER_AGENT = "RouteMaker (https://github.com/Macrophage87/RouteMaker, 1)"
ALERTS_URL = "https://api.weather.gov/alerts/active"
RAIN_URL = "https://api.open-meteo.com/v1/forecast"
# The NWS's page for a point, with its "Hazardous weather conditions" at the top, each linked to
# its full text: the link the rider follows (the alerts API's own ids answer JSON).
NOTICE_URL = "https://forecast.weather.gov/MapClick.php"
TIMEOUT_S = 6.0
MAX_BYTES = 2_000_000
# Points a check takes: the page sends one about every 5 mi (8 km) of the line still to ride.
MAX_POINTS = 12
# Decimal places a point is rounded to before it is asked about (0.01 degree, about 0.7 mi).
PLACES = 2
# Seconds an answer is kept for a cell (the 2-minute rule).
KEEP_S = 120.0
# After a service fails to answer, it is not asked again for this long: an outage would otherwise
# hold every check for a timeout and re-ask every point (each one counts against Open-Meteo's
# daily calls).
DOWN_S = 60.0
# The 15-minute steps asked for: 4 hours. Rain after that is not looked for.
RAIN_STEPS = 16
STEP_S = 15 * 60
# Inches in a 15-minute step that count as rain (0.25 mm), and as heavy rain (2.5 mm, about 0.4 in
# an hour).
RAIN_MIN_IN = 0.01
HEAVY_IN = 0.1
# Characters of an alert's instruction kept (the NWS page has the rest).
INSTRUCTION_MAX = 400

SEVERITY_RANK = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3, "Unknown": 4}

# Advisories that matter on a bike though the NWS rates them Moderate or Minor.
ADVISORIES = frozenset(
    {
        "Special Weather Statement",
        "Heat Advisory",
        "Wind Advisory",
        "Dense Fog Advisory",
        "Freezing Fog Advisory",
        "Dense Smoke Advisory",
        "Winter Weather Advisory",
        "Freezing Rain Advisory",
        "Freezing Drizzle Advisory",
        "Wind Chill Advisory",
        "Cold Weather Advisory",
        "Flood Advisory",
        "Coastal Flood Advisory",
        "Air Quality Alert",
        "Blowing Dust Advisory",
    }
)
# Never shown, whatever their severity: on the water or the beach, or for plants.
NOT_FOR_RIDERS = frozenset(
    {
        "Freeze Warning",
        "Freeze Watch",
        "Hard Freeze Warning",
        "Hard Freeze Watch",
        "Frost Advisory",
        "Storm Warning",
        "Storm Watch",
        "Hurricane Force Wind Warning",
        "Hurricane Force Wind Watch",
        "Special Marine Warning",
        "Low Water Advisory",
    }
)
NOT_FOR_RIDERS_WORDS = (
    "Marine",
    "Small Craft",
    "Gale",
    "Rip Current",
    "Beach Hazards",
    "Surf",
    "Seas",
    "Brisk Wind",
    "Lakeshore",
    "Freezing Spray",
)

Fetch = Callable[[str, float], bytes]
Point = tuple[float, float, float]  # lon, lat, seconds until the rider gets there


class Unavailable(Exception):
    """A service did not answer; the message is the failure's type, never the URL."""


def http_get(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url, headers={"Accept": "application/geo+json, application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise Unavailable(f"HTTP {error.code}") from None
    except Exception as error:  # noqa: BLE001 - the type only: the text can repeat the URL
        raise Unavailable(type(error).__name__) from None
    if len(body) > MAX_BYTES:
        raise Unavailable("larger than expected")
    return body


def cell(lon: float, lat: float) -> tuple[float, float]:
    """The rounded point asked about: (lat, lon), 0.01 degree."""
    return (round(lat, PLACES), round(lon, PLACES))


def notice_url(at: tuple[float, float]) -> str:
    lat, lon = at
    return f"{NOTICE_URL}?{urllib.parse.urlencode({'lat': f'{lat:.2f}', 'lon': f'{lon:.2f}'})}"


def _when(text: object) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        out = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=UTC)


def relevant(props: dict) -> bool:
    """Whether an alert matters on a bike (the module's "Alerts")."""
    if props.get("status") != "Actual" or props.get("messageType") not in ("Alert", "Update"):
        return False
    event = props.get("event")
    if not isinstance(event, str) or not event:
        return False
    if event in NOT_FOR_RIDERS or any(word in event for word in NOT_FOR_RIDERS_WORDS):
        return False
    return props.get("severity") in ("Extreme", "Severe") or event in ADVISORIES


def parse_alerts(doc: object, at: tuple[float, float]) -> list[dict]:
    """The relevant alerts in one `/alerts/active` answer, as the page shows them."""
    features = doc.get("features") if isinstance(doc, dict) else None
    out = []
    for feature in features if isinstance(features, list) else []:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if not isinstance(props, dict) or not relevant(props):
            continue
        # Only the hazard's own end: `expires` is when the NWS replaces the message, not when the
        # hazard ends, so a statement without `ends` is shown with no "until".
        ends = _when(props.get("ends"))
        onset = _when(props.get("onset")) or _when(props.get("effective"))
        instruction = props.get("instruction") if isinstance(props.get("instruction"), str) else ""
        instruction = " ".join(instruction.split())
        if len(instruction) > INSTRUCTION_MAX:
            instruction = instruction[: INSTRUCTION_MAX - 1].rsplit(" ", 1)[0] + "…"
        out.append(
            {
                "id": str(props.get("id") or feature.get("id") or ""),
                "event": props["event"],
                "severity": props.get("severity") or "Unknown",
                "onset": onset.isoformat() if onset else None,
                "ends": ends.isoformat() if ends else None,
                "area": props.get("areaDesc") if isinstance(props.get("areaDesc"), str) else None,
                "instruction": instruction or None,
                "url": notice_url(at),
            }
        )
    return out


def parse_rain(doc: object, count: int) -> list[list[tuple[float, float]]]:
    """Open-Meteo's answer for `count` points: each point's (end of step, unix s; inches) steps."""
    docs = doc if isinstance(doc, list) else [doc]
    if len(docs) != count:
        raise Unavailable("answer for the wrong number of points")
    out = []
    for one in docs:
        block = one.get("minutely_15") if isinstance(one, dict) else None
        times = block.get("time") if isinstance(block, dict) else None
        amounts = block.get("precipitation") if isinstance(block, dict) else None
        if not isinstance(times, list) or not isinstance(amounts, list):
            raise Unavailable("no 15-minute precipitation")
        out.append(
            [
                (float(t), float(a))
                for t, a in zip(times, amounts, strict=False)
                if isinstance(t, int | float) and isinstance(a, int | float)
            ]
        )
    return out


def first_rain(
    points: Sequence[Point], series: Sequence[Sequence[tuple[float, float]]], now: float
) -> dict | None:
    """The first point where rain is forecast as the rider gets there, or None.

    A step's amount is the sum over the 15 minutes before its time (Open-Meteo's "preceding 15
    minutes sum"), so the rider's moment falls in the step whose window holds it. A point past
    the forecast's last step is not looked at."""
    for index, ((_lon, _lat, offset), steps) in enumerate(zip(points, series, strict=True)):
        at = now + max(0.0, offset)
        for end, inches in steps:
            if end - STEP_S <= at < end:
                if inches >= RAIN_MIN_IN:
                    return {
                        "index": index,
                        "offset_s": round(offset),
                        # The step's start, from now: when the rain is due there.
                        "starts_in_s": max(0, round(end - STEP_S - now)),
                        "inches": round(inches, 3),
                        "heavy": inches >= HEAVY_IN,
                    }
                break
    return None


# Seconds before the rider reaches a point that an alert found there still counts: points are
# about 5 mi apart, and the alert's area reaches back along the line between them.
ARRIVE_SLACK_S = 30 * 60


def in_ride(alert: dict, now: datetime, ride_s: float, at_s: float = 0.0) -> bool:
    """An alert found at a point the rider reaches in `at_s` seconds, in force while the rider is
    near it: not over before then (less `ARRIVE_SLACK_S`), not starting after the ride ends."""
    ends = _when(alert.get("ends"))
    onset = _when(alert.get("onset"))
    if ends is not None and ends.timestamp() <= now.timestamp() + max(0.0, at_s - ARRIVE_SLACK_S):
        return False
    return onset is None or onset.timestamp() <= now.timestamp() + ride_s


class Weather:
    """The check, with its per-cell memory (`KEEP_S`). One per process."""

    def __init__(
        self,
        fetch: Fetch = http_get,
        clock: Callable[[], float] = time.time,
        later: Callable[[float, Callable[[], None]], None] | None = None,
    ):
        self.fetch = fetch
        self.clock = clock
        # Runs a function after a delay: a sweep that drops what is `KEEP_S` old even when no
        # other check comes (a quiet server would otherwise keep the last ride's cells).
        self.later = later or _daemon_timer
        self._sweep_due = False
        self._lock = threading.Lock()
        self._alerts: dict[tuple[float, float], tuple[float, list[dict]]] = {}
        self._rain: dict[tuple[float, float], tuple[float, list[tuple[float, float]]]] = {}
        self._down_until = {"alerts": 0.0, "rain": 0.0}

    def _sweep(self) -> None:
        with self._lock:
            self._sweep_due = False
            now = self.clock()
            self._prune(now)
            kept = [at for at, _ in [*self._alerts.values(), *self._rain.values()]]
            if kept:
                # Next when the oldest left turns `KEEP_S` old, so none outlives it.
                self._schedule(max(0.0, min(kept) + KEEP_S - now))

    def _schedule(self, delay: float = KEEP_S) -> None:
        """A sweep in `delay` seconds, unless one is due (called with the lock held)."""
        if not self._sweep_due:
            self._sweep_due = True
            self.later(delay, self._sweep)

    def _prune(self, now: float) -> None:
        for kept in (self._alerts, self._rain):
            for key in [k for k, (at, _) in kept.items() if now - at >= KEEP_S]:
                del kept[key]

    def _alerts_at(self, at: tuple[float, float]) -> list[dict]:
        lat, lon = at
        query = urllib.parse.urlencode({"point": f"{lat:.2f},{lon:.2f}"})
        return parse_alerts(json.loads(self.fetch(f"{ALERTS_URL}?{query}", TIMEOUT_S)), at)

    def _rain_at(self, cells: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
        query = urllib.parse.urlencode(
            {
                "latitude": ",".join(f"{lat:.2f}" for lat, _ in cells),
                "longitude": ",".join(f"{lon:.2f}" for _, lon in cells),
                "minutely_15": "precipitation",
                "forecast_minutely_15": RAIN_STEPS,
                "precipitation_unit": "inch",
                "timeformat": "unixtime",
            }
        )
        return parse_rain(json.loads(self.fetch(f"{RAIN_URL}?{query}", TIMEOUT_S)), len(cells))

    def check(self, points: Sequence[Point]) -> dict:
        now = self.clock()
        cells = [cell(lon, lat) for lon, lat, _ in points]
        unique = list(dict.fromkeys(cells))
        with self._lock:
            self._prune(now)
            alerts_kept = {c: self._alerts[c][1] for c in unique if c in self._alerts}
            rain_kept = {c: self._rain[c][1] for c in unique if c in self._rain}
            alerts_down = now < self._down_until["alerts"]
            rain_down = now < self._down_until["rain"]
        unchecked: list[str] = []

        missing = [] if alerts_down else [c for c in unique if c not in alerts_kept]
        need = [] if rain_down else [c for c in unique if c not in rain_kept]
        alerts_failed = 0
        answers: list[list[dict] | None] = []
        rain_steps: list[list[tuple[float, float]]] | None = None
        if missing or need:
            # The rain and every point's alerts asked at once: a slow service holds the request
            # for one timeout, not one after another.
            with ThreadPoolExecutor(max_workers=min(6, len(missing)) + 1) as pool:
                rain_job = pool.submit(self._try_rain, need) if need else None
                answers = list(pool.map(self._try_alerts, missing))
                rain_steps = rain_job.result() if rain_job else None
            if need and rain_steps is None:
                with self._lock:
                    self._down_until["rain"] = now + DOWN_S
            for c, found in zip(missing, answers, strict=True):
                if found is None:
                    alerts_failed += 1
                    with self._lock:
                        self._down_until["alerts"] = now + DOWN_S
                    continue
                alerts_kept[c] = found
                with self._lock:
                    self._alerts[c] = (now, found)
                    self._schedule()
        if len(alerts_kept) < len(unique) or alerts_failed == len(unique):
            # Some of the route was not asked, or its answer did not come: said unchecked, as
            # rain is, so a warning at the unanswered points is never read as "nothing".
            unchecked.append("alerts")
        if rain_steps is not None:
            for c, steps in zip(need, rain_steps, strict=True):
                rain_kept[c] = steps
                with self._lock:
                    self._rain[c] = (now, steps)
                    self._schedule()
        rain = None
        if all(c in rain_kept for c in cells):
            rain = first_rain(points, [rain_kept[c] for c in cells], now)
        else:
            unchecked.append("rain")

        ride_s = max((p[2] for p in points), default=0.0)
        moment = datetime.fromtimestamp(now, UTC)
        seen: dict[str, dict] = {}
        for c, (_lon, _lat, at_s) in zip(cells, points, strict=True):
            for alert in alerts_kept.get(c, []):
                if alert["id"] not in seen and in_ride(alert, moment, ride_s, at_s):
                    seen[alert["id"]] = alert
        alerts = sorted(
            seen.values(), key=lambda a: (SEVERITY_RANK.get(a["severity"], 4), a["event"])
        )
        return {"alerts": alerts, "rain": rain, "unchecked": unchecked}

    def _try_rain(self, cells: list[tuple[float, float]]) -> list[list[tuple[float, float]]] | None:
        try:
            return self._rain_at(cells)
        except (Unavailable, ValueError, TypeError) as error:
            logger.warning("Weather: the rain forecast did not answer: %s", type(error).__name__)
            return None

    def _try_alerts(self, at: tuple[float, float]) -> list[dict] | None:
        try:
            return self._alerts_at(at)
        except (Unavailable, ValueError, TypeError) as error:
            logger.warning("Weather: the NWS alerts did not answer: %s", type(error).__name__)
            return None


def _daemon_timer(delay: float, run: Callable[[], None]) -> None:
    timer = threading.Timer(delay, run)
    timer.daemon = True
    timer.start()


_shared: Weather | None = None


def shared() -> Weather:
    global _shared
    if _shared is None:
        _shared = Weather()
    return _shared


def points_problem(points: object) -> str | None:
    """Why a check's points cannot be used, or None: up to `MAX_POINTS` of [lon, lat, seconds]."""
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        return f"points is a list of 1 to {MAX_POINTS} [lon, lat, seconds]."
    for p in points:
        if (
            not isinstance(p, list)
            or len(p) != 3
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in p)
            or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90 and 0 <= p[2] <= 48 * 3600)
        ):
            return "Each point is [lon, lat, seconds until there], seconds 0 to 172800."
    return None
