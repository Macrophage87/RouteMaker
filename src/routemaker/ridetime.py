"""The ride times a plan can be for, and what OSM's conditions say at each.

The owner's words, 2026-09-27: "We can maybe just use three settings: Weekend,
Weekday Rush, Weekday Off-hours?" A fourth, night, came with the junction
model's time of day (OWNER-DECISIONS 469c: "Evenings are probably 1x till about
9. Then reduced to about half to 7"). So a plan is for one of `WHENS`, and
nothing finer. Three things read it:

- the router's `date_time` (`REPRESENTATIVE_TIME`), which is what Valhalla
  evaluates the conditional restrictions it does read against - `access:
  conditional`, `oneway:conditional`, `restriction:conditional` are in the
  pinned supported-key list (lua/vendor/supported_keys.txt);
- the roads closed to motor traffic only at set times (Beach Drive in
  Montgomery County, Sligo Creek Parkway, Little Falls Parkway), which count
  as off-road paths in a plan whose ride time falls inside the closure
  (`car_free_when`). Valhalla does not read `motor_vehicle:conditional`, and a
  closure to cars is a comfort fact for a bicycle, not an access one, so no
  `date_time` could express it; it is evaluated here, at the rebuild, against
  each setting's instants;
- the junction model's hour of traffic (`routemaker.intersections.HOUR_SHARE`).

Night is 21:00 to 07:00 on any day, weekend nights included; it routes on the
standard graph, as a weekday does, and a road counts as car-free at night only
if its closure covers every night instant. Rush hours are Monday to Friday,
07:00-10:00 and 16:00-19:00 in the region's time.

A US federal holiday on a weekday is weekday off-peak all day, rush hours
included; one on a Saturday or Sunday stays the weekend. The owner, 2026-11-08:
"Holidays should use the weekday off-peak graph." "Unless it's a weekend." It
used to count as the weekend, which planned Sligo Creek Parkway (whose closure,
`no @ (Fr 09:00-24:00; Sa; Su 00:00-18:00)`, names no `PH`) as car-free on
Columbus Day and Veterans Day while it is open to cars, and gave the holiday
the weekend junction factor (hunt M6). Beach Drive's own `PH 07:00-19:00` is
therefore not read on a weekday holiday: it plans as open to cars (hunt 3,
T3-11). The owner, round 3, 2026-11-08, kept it so: "there's a side trail
anyway".

Sunday from 18:00 to 21:00 is weekday off-peak too. The weekend graph's
instants are Saturday 09:00 and 15:00 and Sunday 11:00, so it holds Beach
Drive (`Su 00:00-19:00`) and Sligo Creek (`Su 00:00-18:00`) car-free, but cars
are back on them by Sunday evening. The owner, 2026-11-08: Sunday 7-9 PM, after
the weekend car-free windows end, plans as off-peak. Then, told Sligo Creek
opens to cars at 18:00 (hunt 3, T3-5), round 3, 2026-11-08: "Let's just go at 6 on Sunday." So
Sunday evening starts at 18:00, and Beach Drive's last closed hour, Sunday
18:00-19:00, is planned as open to cars (a per-road check would need a new
instant or graph).
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")

WEEKEND = "weekend"
WEEKDAY_RUSH = "weekday_rush"
WEEKDAY_OFFPEAK = "weekday_offpeak"
NIGHT = "night"
WHENS = (WEEKEND, WEEKDAY_RUSH, WEEKDAY_OFFPEAK, NIGHT)

# (start, end) in minutes of the day, end exclusive.
RUSH_WINDOWS = ((7 * 60, 10 * 60), (16 * 60, 19 * 60))
# Night: from 21:00 to 07:00, every day (469c).
NIGHT_START = 21 * 60
NIGHT_END = 7 * 60
# Sunday evening, after the weekend car-free windows end and before night:
# planned as weekday off-peak (the owner, 2026-11-08; hunt M6). From 18:00, when Sligo
# Creek Parkway opens to cars (the owner, round 3, 2026-11-08: "Let's just go at 6 on Sunday.");
# it was 19:00, Beach Drive's end, which planned Sligo Creek car-free with cars back on it.
# Beach Drive's 18:00-19:00 is then planned as open to cars.
SUNDAY_EVENING_START = 18 * 60

_DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

# The instants a setting stands for, as (weekday, minute of day) with Monday 0.
# A road is car-free in a setting only if it is car-free at every one of them,
# so a closure covering part of a weekend (Sunday afternoon only, say) does not
# make a Saturday morning ride's road a path.
INSTANTS = {
    WEEKEND: ((5, 9 * 60), (5, 15 * 60), (6, 11 * 60)),
    WEEKDAY_RUSH: ((1, 8 * 60), (1, 17 * 60 + 30)),
    WEEKDAY_OFFPEAK: ((1, 12 * 60), (1, 20 * 60 + 30)),
    NIGHT: ((1, 22 * 60), (2, 3 * 60), (5, 22 * 60), (6, 3 * 60)),
}

# What the router is told for each setting: the next such day at the first of
# its instants. Saturday 09:00 is PLAN's own default planning time
# ("the next Saturday at 9:00 local time").
REPRESENTATIVE_TIME = {
    WEEKEND: (5, 9, 0),
    WEEKDAY_RUSH: (1, 8, 0),
    WEEKDAY_OFFPEAK: (1, 12, 0),
    NIGHT: (1, 22, 0),
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def federal_holidays(year: int) -> set[date]:
    """The eleven US federal holidays, as observed (5 U.S.C. 6103)."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 11, 11)]
    fixed.append(date(year, 12, 25))
    return {_observed(d) for d in fixed} | {
        _nth_weekday(year, 1, 0, 3),  # Birthday of Martin Luther King, Jr.
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _last_weekday(year, 5, 0),  # Memorial Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving Day
    }


def is_federal_holiday(day: date) -> bool:
    """Whether `day` is a federal holiday as observed, the next year's included: New Year's
    Day on a Saturday is observed on December 31 (2027-12-31, for 2028)."""
    return day in federal_holidays(day.year) or day in federal_holidays(day.year + 1)


def when_at(moment: datetime) -> str:
    """The setting a moment falls in, read in the region's time.

    A weekday federal holiday is off-peak all day, and Sunday 18:00-21:00 is
    off-peak (the module's docstring: the owner, 2026-11-08)."""
    local = moment.astimezone(ZONE)
    minute = local.hour * 60 + local.minute
    if minute >= NIGHT_START or minute < NIGHT_END:
        return NIGHT
    if local.weekday() == 6 and minute >= SUNDAY_EVENING_START:
        return WEEKDAY_OFFPEAK
    if local.weekday() >= 5:
        return WEEKEND
    if is_federal_holiday(local.date()):
        return WEEKDAY_OFFPEAK
    if any(start <= minute < end for start, end in RUSH_WINDOWS):
        return WEEKDAY_RUSH
    return WEEKDAY_OFFPEAK


def representative_time(when: str, now: datetime) -> str:
    """Valhalla's local `date_time` value for a setting: the next such instant."""
    weekday, hour, minute = REPRESENTATIVE_TIME[when]
    local = now.astimezone(ZONE)
    candidate = (local + timedelta(days=(weekday - local.weekday()) % 7)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.strftime("%Y-%m-%dT%H:%M")


def soonest_instant(when: str, now: datetime) -> datetime:
    """The soonest of a setting's `INSTANTS` after `now`, in the region's time: the moment a
    ride planned for that setting, not for now, is taken to start (`workzones.ride_moment`).

    Hunt 3, T3-7: the closures were matched at `representative_time`, so on Saturday night
    with the dial on Weekend (tomorrow) they were next Saturday 09:00's, six and a half days
    out, though Sunday 11:00 is a weekend instant too. The router's `date_time` stays
    `representative_time`."""
    local = now.astimezone(ZONE)
    found = []
    for weekday, minute in INSTANTS[when]:
        candidate = (local + timedelta(days=(weekday - local.weekday()) % 7)).replace(
            hour=minute // 60, minute=minute % 60, second=0, microsecond=0
        )
        if candidate <= local:
            candidate += timedelta(days=7)
        found.append(candidate)
    return min(found)


# How finely `soonest_start` steps forward, and how far: every setting's boundary is on a
# quarter hour (on the hour, in fact), and a week and a day holds one of each setting. Claude's
# default, not measured (routing hunt 4, C4-2).
START_STEP = timedelta(minutes=15)
START_LOOK = timedelta(days=8)


def soonest_start(when: str, now: datetime) -> datetime:
    """The next moment at or after `now` that falls in the setting `when` (`when_at`): the
    start of its next window. Monday 15:05's rush is today 16:00 and its night tonight 21:00,
    and a weekday holiday is off-peak, not rush (routing hunt 4, C4-2: the ride was taken to
    start at one of `INSTANTS`, all next Tuesday's for rush and off-peak). Where no such
    moment is found within `START_LOOK`, the soonest of `INSTANTS` (`soonest_instant`)."""
    moment = now.astimezone(UTC)
    step = START_STEP.total_seconds()
    # Up to the next quarter hour (a whole number of them since the epoch, in UTC: the
    # region's offset is whole hours, so its quarter hours are the same).
    moment = datetime.fromtimestamp(math.ceil(moment.timestamp() / step) * step, UTC)
    end = now + START_LOOK
    while moment <= end:
        if when_at(moment) == when:
            return moment.astimezone(ZONE)
        moment += START_STEP
    return soonest_instant(when, now)


# --- OSM conditions ------------------------------------------------------------

_BRANCH = re.compile(r"([A-Za-z_]+)\s*@\s*\(([^)]*)\)")
_TIME = r"(\d{1,2}):(\d{2})"
_DAY = "(" + "|".join(_DAYS) + ")"
_TIMES = re.compile(rf"^{_TIME}-{_TIME}$")
_WEEK_SPAN = re.compile(rf"^{_DAY}\s+{_TIME}\s*-\s*{_DAY}\s+{_TIME}$")
_DAY_RANGE = re.compile(rf"^{_DAY}(?:-{_DAY})?$")

WEEK_MINUTES = 7 * 24 * 60


class Unreadable(ValueError):
    """A condition this reader does not understand; it is never guessed at."""


def _minute(hour: str, minute: str) -> int:
    value = int(hour) * 60 + int(minute)
    if not 0 <= value <= 24 * 60:
        raise Unreadable(f"{hour}:{minute}")
    return value


def _day_set(spec: str) -> set[int]:
    days: set[int] = set()
    for part in spec.split(","):
        match = _DAY_RANGE.match(part.strip())
        if not match:
            raise Unreadable(spec)
        start = _DAYS.index(match.group(1))
        end = _DAYS.index(match.group(2)) if match.group(2) else start
        day = start
        while True:
            days.add(day)
            if day == end:
                break
            day = (day + 1) % 7
    return days


def _rule_intervals(rule: str) -> list[tuple[int, int]]:
    """One rule as [start, end) intervals in minutes of the week."""
    rule = rule.strip()
    if not rule:
        return []
    span = _WEEK_SPAN.match(rule)
    if span:
        start = _DAYS.index(span.group(1)) * 1440 + _minute(span.group(2), span.group(3))
        end = _DAYS.index(span.group(4)) * 1440 + _minute(span.group(5), span.group(6))
        if end <= start:
            return [(start, WEEK_MINUTES), (0, end)]
        return [(start, end)]
    if _TIMES.match(rule.split(",", 1)[0].strip()):
        # Times with no days name every day: Clark Place NW's
        # `no @ (06:00-10:15,14:45-19:15)` (correctness note, mutation review
        # r1 - it was unreadable and closed nothing).
        days, times = set(range(7)), rule
    else:
        head, _, times = rule.partition(" ")
        if head == "PH":
            # A public holiday is never one of the instants a setting stands for.
            return []
        days = _day_set(head)
    ranges: list[tuple[int, int]] = []
    for part in times.split(",") if times.strip() else ["00:00-24:00"]:
        match = _TIMES.match(part.strip())
        if not match:
            raise Unreadable(rule)
        ranges.append((_minute(*match.group(1, 2)), _minute(*match.group(3, 4))))
    intervals = []
    for day in days:
        for start, end in ranges:
            if end <= start:
                # Past midnight: into the next day.
                intervals.append((day * 1440 + start, (day + 1) * 1440))
                nxt = (day + 1) % 7
                intervals.append((nxt * 1440, nxt * 1440 + end))
            else:
                intervals.append((day * 1440 + start, day * 1440 + end))
    return intervals


def condition_intervals(condition: str) -> list[tuple[int, int]]:
    """A condition's rules, which OSM separates by `;` or by `, ` before a day."""
    intervals: list[tuple[int, int]] = []
    for group in condition.split(";"):
        for rule in re.split(r",\s+(?=[A-Z])", group):
            intervals.extend(_rule_intervals(rule))
    return intervals


def branches(value: str | None) -> list[tuple[str, str]]:
    """`value @ (condition)` branches of an OSM conditional tag."""
    return [(v, c) for v, c in _BRANCH.findall(value or "")]


def closed_settings(value: str | None) -> frozenset[str]:
    """The settings in which a `*:conditional` value closes the way (`no`).

    Every instant of a setting must fall inside one of the `no` branches. A
    condition this cannot read (a month range, sunset) closes nothing: an
    unreadable closure is reported as the road it is on every other day.

    One unreadable `no` branch makes the whole value unreadable, whichever
    order the branches come in and whichever setting is asked about: the
    branches are all read before any setting is decided. Read as they were
    needed, `no @ (Sa-Su); no @ (sunset-sunrise)` closed nothing but
    `no @ (Mo-Su 00:00-24:00); no @ (sunset-sunrise)` closed everything,
    since the second branch was never reached (correctness review, round 3).
    """
    try:
        closures = [condition_intervals(cond) for value_, cond in branches(value) if value_ == "no"]
    except Unreadable:
        return frozenset()
    return frozenset(
        when
        for when in WHENS
        if all(
            any(
                start <= day * 1440 + minute < end
                for intervals in closures
                for start, end in intervals
            )
            for day, minute in INSTANTS[when]
        )
    )
