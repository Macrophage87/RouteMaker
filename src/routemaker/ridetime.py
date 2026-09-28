"""The three ride times a plan can be for, and what OSM's conditions say at each.

The owner's words, 2026-09-27: "We can maybe just use three settings: Weekend,
Weekday Rush, Weekday Off-hours?" So a plan is for one of `WHENS`, and nothing
finer. Two things read it:

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
  each setting's instants.

Rush hours are Monday to Friday, 07:00-10:00 and 16:00-19:00 in the region's
time. A US federal holiday counts as the weekend, since the closures here that
name holidays (`PH`) name them alongside Saturday and Sunday.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")

WEEKEND = "weekend"
WEEKDAY_RUSH = "weekday_rush"
WEEKDAY_OFFPEAK = "weekday_offpeak"
WHENS = (WEEKEND, WEEKDAY_RUSH, WEEKDAY_OFFPEAK)

# (start, end) in minutes of the day, end exclusive.
RUSH_WINDOWS = ((7 * 60, 10 * 60), (16 * 60, 19 * 60))

_DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

# The instants a setting stands for, as (weekday, minute of day) with Monday 0.
# A road is car-free in a setting only if it is car-free at every one of them,
# so a closure covering part of a weekend (Sunday afternoon only, say) does not
# make a Saturday morning ride's road a path.
INSTANTS = {
    WEEKEND: ((5, 9 * 60), (5, 15 * 60), (6, 11 * 60)),
    WEEKDAY_RUSH: ((1, 8 * 60), (1, 17 * 60 + 30)),
    WEEKDAY_OFFPEAK: ((1, 12 * 60), (1, 21 * 60)),
}

# What the router is told for each setting: the next such day at the first of
# its instants. Saturday 09:00 is PLAN's own default planning time
# ("the next Saturday at 9:00 local time").
REPRESENTATIVE_TIME = {WEEKEND: (5, 9, 0), WEEKDAY_RUSH: (1, 8, 0), WEEKDAY_OFFPEAK: (1, 12, 0)}


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


def when_at(moment: datetime) -> str:
    """The setting a moment falls in, read in the region's time."""
    local = moment.astimezone(ZONE)
    if local.weekday() >= 5 or local.date() in federal_holidays(local.year):
        return WEEKEND
    minute = local.hour * 60 + local.minute
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


def holds_at(condition: str, weekday: int, minute: int) -> bool:
    moment = weekday * 1440 + minute
    return any(start <= moment < end for start, end in condition_intervals(condition))


def branches(value: str | None) -> list[tuple[str, str]]:
    """`value @ (condition)` branches of an OSM conditional tag."""
    return [(v, c) for v, c in _BRANCH.findall(value or "")]


def closed_settings(value: str | None) -> frozenset[str]:
    """The settings in which a `*:conditional` value closes the way (`no`).

    Every instant of a setting must fall inside one of the `no` branches. A
    condition this cannot read (a month range, sunset) closes nothing: an
    unreadable closure is reported as the road it is on every other day.
    """
    closed = []
    for when in WHENS:
        try:
            if all(
                any(
                    value_ == "no" and holds_at(cond, day, minute)
                    for value_, cond in branches(value)
                )
                for day, minute in INSTANTS[when]
            ):
                closed.append(when)
        except Unreadable:
            return frozenset()
    return frozenset(closed)
