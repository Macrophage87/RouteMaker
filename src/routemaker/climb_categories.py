"""Categorised climbs for the map's Climbs layer: what counts as a climb, and its category.

The owner's scale (2026-10-10 6:03 pm and 2026-10-11 7:44 am New York; PLAN.md, "Climbs
layer"; reports/v0.5.0/climb-categories.md in the project files): "Have a cat 5 at 4000
score. Let's use the garmin setup", then "Let's do the scale standard, but with the dips
added in." Garmin ClimbPro's scale
(https://www8.garmin.com/manuals/webhelp/GUID-08ACA9FC-DEE6-4C8D-8A95-F62181C512E9/EN-US/GUID-EBAEC138-B55A-4730-8C10-DF21A40302A9.html,
read 2026-10-10), the same as Strava's
(https://support.strava.com/hc/en-us/articles/216917057-Climb-Categorization, read 2026-10-10):

    score = length (m) x average grade (%)

with Cat 5 over 4,000 (the owner's addition), Cat 4 over 8,000, Cat 3 over 16,000, Cat 2
over 32,000, Cat 1 over 64,000 and HC over 80,000. Nothing under Cat 5 is a climb: "Uncategorized
is not a hill" (6:04 pm). Since length x grade (%) is 100 x the height gained, the score is
the net gain in metres times 100: Cat 5 is over 131 ft (40 m) gained, HC over 2,625 ft (800 m).

Three of the owner's rules shape what is found:

- **Dips and flats are breaks, not the top.** "If you climb 2000 feet net, but there's a short
  dip in the middle, it's still a 2000 foot climb"; "Most people think of those as a small
  break." A climb is scored on its net gain, start to summit. `routemaker.climbs.runs` (the
  route cost's reading) ends a climb at a 3 m dip or 150 m of flat, which split the long gap
  climbs in the owner's scan (Gambrill Park Rd twice, US 211 and Skyline Drive in pieces), so
  this reading has its own, looser break rule (`DIP_*`, `BREAK_*` below). The route cost keeps
  the 3 m rule: changing it would re-price every route, which the owner's decision did not ask.
- **Long gentle grades count.** "There's a lot of rail trails that would have them." The
  minimum average grade is 1% (Garmin's is 3%), with the 0.31 mi (500 m) minimum length and a
  Cat 5 score still required. A gentle approach is trimmed off the ends (`TRIM_WINDOW_M`), so a
  1 km wall at the end of 10 km of near-flat is listed as the wall, not as 11 km at 1%.
- **The marker.** The summit shows the category ("5" to "1", "HC"); the marker's shape follows
  the average grade: a circle under 4%, a square from 4% to 7.9%, a diamond from 8%.

Profiles are (distance along the line in metres, elevation in metres) pairs in the order
ridden; a missing elevation (None) splits the profile, as in `routemaker.climbs`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .climbs import _pieces

# --- The owner's thresholds ---------------------------------------------------------

# Score thresholds, highest first; a climb takes the first it is over.
CATEGORIES: tuple[tuple[str, float], ...] = (
    ("HC", 80_000.0),
    ("1", 64_000.0),
    ("2", 32_000.0),
    ("3", 16_000.0),
    ("4", 8_000.0),
    ("5", 4_000.0),
)
# At least about 1,640 ft (500 m), Garmin's minimum ...
MIN_LENGTH_M = 500.0
# ... at 1% or more on average (the owner's default for rail trails; Garmin's is 3%).
MIN_GRADE = 0.01

# The marker's shape by average grade, in percent rounded to a tenth as the layer shows it
# (the owner's default cut-offs, approved 2026-10-11 7:45 am): under 4 a circle, 4 to 7.9 a
# square, 8 and up a diamond.
SQUARE_FROM_PCT = 4.0
DIAMOND_FROM_PCT = 8.0

# --- The break rule (picked here; the owner asked for "short" dips to pass) -------------

# A dip below the climb's highest point so far ends the climb only when it drops more than
# this share of the net gain so far, and never ends it under DIP_MIN_M nor lets it pass over
# DIP_MAX_M. 33 ft (10 m) is three times the elevation noise `routemaker.climbs.DIP_M`
# allows for on the one-arcsecond DEM, so noise never ends a climb; 20% lets a 600 m climb
# take a 130 ft (40 m) dip in its middle; 165 ft (50 m) is a real descent at any size, so
# two hills with a valley between stay two climbs.
DIP_MIN_M = 10.0
DIP_SHARE = 0.20
DIP_MAX_M = 50.0
# And a stretch without a new high point (a flat, or a dip and the climb back to where it
# was) ends the climb when it runs longer than this share of the climb so far, never under
# BREAK_MIN_M nor over BREAK_MAX_M: a quarter mile (400 m) of flat is a cross street or a
# bench; past a mile (1,600 m) the ride has moved on.
BREAK_MIN_M = 400.0
BREAK_SHARE = 0.25
BREAK_MAX_M = 1_600.0

# The ends are trimmed while the first (or last) TRIM_WINDOW_M of the climb rises at under
# MIN_GRADE: long enough that the DEM's metre of noise is a third of a percent, short enough
# to keep a climb's real start.
TRIM_WINDOW_M = 300.0


def category(score: float) -> str | None:
    """The climb category for a score ("5" to "1", "HC"), or None: not a climb."""
    for name, over in CATEGORIES:
        if score > over:
            return name
    return None


def grade_pct(gain_m: float, length_m: float) -> float:
    """The average grade in percent, rounded to a tenth, as the layer shows it."""
    return round(100.0 * gain_m / length_m, 1) if length_m > 0 else 0.0


def shape(grade_percent: float) -> str:
    """The marker's shape for an average grade in percent: circle, square or diamond."""
    if grade_percent >= DIAMOND_FROM_PCT:
        return "diamond"
    if grade_percent >= SQUARE_FROM_PCT:
        return "square"
    return "circle"


@dataclass(frozen=True)
class Climb:
    """One categorised climb: from `start` to the summit at `end`, indices into the profile
    piece it was found in, with the distances along the profile."""

    start_m: float
    end_m: float
    gain_m: float
    start_index: int = 0
    end_index: int = 0

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m

    @property
    def grade(self) -> float:
        return self.gain_m / self.length_m if self.length_m > 0 else 0.0

    @property
    def score(self) -> float:
        """Length (m) x average grade (%), which is the net gain x 100."""
        return self.length_m * self.grade * 100.0

    @property
    def category(self) -> str | None:
        return category(self.score)

    @property
    def grade_pct(self) -> float:
        return grade_pct(self.gain_m, self.length_m)

    @property
    def shape(self) -> str:
        return shape(self.grade_pct)


def _allowed_dip(gain_m: float) -> float:
    return min(DIP_MAX_M, max(DIP_MIN_M, DIP_SHARE * gain_m))


def _allowed_break(length_m: float) -> float:
    return min(BREAK_MAX_M, max(BREAK_MIN_M, BREAK_SHARE * length_m))


def _trim(points: Sequence[tuple[float, float]], a: int, b: int) -> tuple[int, int]:
    """Move the start up and the summit down past ends that rise at under MIN_GRADE."""
    while a < b:
        k = a + 1
        while k < b and points[k][0] - points[a][0] < TRIM_WINDOW_M:
            k += 1
        run = points[k][0] - points[a][0]
        if run < TRIM_WINDOW_M or (points[k][1] - points[a][1]) / run >= MIN_GRADE:
            break
        a += 1
    while b > a:
        k = b - 1
        while k > a and points[b][0] - points[k][0] < TRIM_WINDOW_M:
            k -= 1
        run = points[b][0] - points[k][0]
        if run < TRIM_WINDOW_M or (points[b][1] - points[k][1]) / run >= MIN_GRADE:
            break
        b -= 1

    # The window leaves up to a window of the gentle end in place where it meets the climb, so
    # the last of it goes a sample at a time, as far as the window reached.
    def step(i: int, j: int) -> float:
        run = points[j][0] - points[i][0]
        return (points[j][1] - points[i][1]) / run if run > 0 else 0.0

    reach = points[a][0] + TRIM_WINDOW_M
    while a < b and points[a + 1][0] <= reach and step(a, a + 1) < MIN_GRADE:
        a += 1
    reach = points[b][0] - TRIM_WINDOW_M
    while b > a and points[b - 1][0] >= reach and step(b - 1, b) < MIN_GRADE:
        b -= 1
    # The start is the lowest point within a window of it, so the gain is not understated by a
    # start the trim left on a bump of DEM noise.
    k = a
    while k < b and points[k + 1][0] - points[a][0] <= TRIM_WINDOW_M:
        k += 1
    low = min(range(a, k + 1), key=lambda i: (points[i][1], -i))
    return low, b


def _candidates(points: Sequence[tuple[float, float]]) -> list[tuple[int, int]]:
    """Start and summit indices of every rise, with short dips and flats inside it."""
    found: list[tuple[int, int]] = []
    n = len(points)
    i = 0
    while i < n - 1:
        start = peak = i
        j = i + 1
        while j < n:
            d, e = points[j]
            if e > points[peak][1]:
                peak = j
            elif peak == start and e <= points[start][1]:
                # Still going down (or level) before any rise: the climb starts lower.
                start = peak = j
            else:
                gain = points[peak][1] - points[start][1]
                length = points[peak][0] - points[start][0]
                if e < points[start][1]:
                    # Below where it began: whatever rose before was not a climb to keep.
                    break
                if points[peak][1] - e > _allowed_dip(gain):
                    break
                if d - points[peak][0] > _allowed_break(length):
                    break
            j += 1
        if peak > start:
            found.append((start, peak))
            i = peak
        else:
            i = max(j, i + 1)
    return found


def _qualifies(climb: Climb) -> bool:
    return (
        climb.length_m >= MIN_LENGTH_M and climb.grade >= MIN_GRADE and climb.category is not None
    )


def find_in_piece(points: Sequence[tuple[float, float]]) -> list[Climb]:
    """The categorised climbs along one unbroken profile, in the order ridden."""
    out: list[Climb] = []
    for start, peak in _candidates(points):
        a, b = _trim(points, start, peak)
        if b <= a:
            continue
        climb = Climb(
            start_m=points[a][0],
            end_m=points[b][0],
            gain_m=points[b][1] - points[a][1],
            start_index=a,
            end_index=b,
        )
        if _qualifies(climb):
            out.append(climb)
    return out


def find_climbs(profile: Sequence[tuple[float, float | None]]) -> list[Climb]:
    """The categorised climbs of a profile, in the order ridden.

    Indices are into the unbroken piece each was found in; use `find_in_piece` with a
    profile that has no gaps when the indices matter.
    """
    found: list[Climb] = []
    for piece in _pieces(profile):
        found.extend(find_in_piece(piece))
    return sorted(found, key=lambda c: c.start_m)


def describe(climb: Climb) -> str:
    """The climb in words, US units first: "Category 3 climb, 2.1 miles (3.4 km) at 4.6%".

    The same sentence the map's accessible names use (frontend/src/lib/climbs.ts); an HC climb
    is "Hors catégorie (HC) climb, ..."."""
    name = (
        "Hors catégorie (HC) climb"
        if climb.category == "HC"
        else f"Category {climb.category} climb"
    )
    miles = climb.length_m / 1609.344
    mi = f"{miles:.1f} {'mile' if math.isclose(round(miles, 1), 1.0) else 'miles'}"
    return f"{name}, {mi} ({climb.length_m / 1000:.1f} km) at {climb.grade_pct:.1f}%"
