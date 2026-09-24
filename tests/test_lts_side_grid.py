"""The side model as a property over every key-form combination.

A generated grid - presence on each of the four key forms, the width on each
of the four width keys, and every reading of `oneway` - classified once, then
walked edge by edge. Two properties from the retrospective's design note, and
a third that pins the precedence against an oracle written here rather than
read from the code:

- **adding a facility never raises the tier**: upgrading what a key says, where
  the upgrade reaches the sides it speaks for without shadowing something
  better on any of them;
- **a narrower width never lowers the tier**;
- **the key form does not matter**: a way scores exactly as the same two sides
  spelled on their own side keys, each with the value and width the precedence
  gives it (side-specific over `both` over the general key).

The road is a 30 mph two-lane two-way secondary with no parking, where mixed
traffic, a narrow lane, an adequate lane and a track are LTS3, LTS3, LTS2 and
LTS1, so every provision and both widths can move the tier. A calm 20 mph
street is deliberately not in the grid: Furth rates a narrow painted lane there
a tier worse than no lane, and this module keeps that reading with no floor
under it (an owner decision, pinned by
`test_a_bike_lane_is_scored_on_furths_table_without_the_shoulders_floor`), so
"adding a facility never raises the tier" is false there by design.

One class of edge is excused from the first property, and only after it is
shown to be that class: an upgrade that takes the only *surveyed* side out of
the provision, leaving a side whose width nobody measured. The round-7 pin
`test_one_surveyed_side_is_still_a_surveyed_width` lets one surveyed side of a
two-sided lane stand for the other, so `cycleway=lane` + `cycleway:right:width
=2.0` reads as a 2.0 m lane; upgrade the right side to a track and the left
lane's width is unknown, which reads as narrow. The tier rises on what was
learned, not on what was built. Each such edge is re-read with every
unsurveyed side given a narrow width - the reading an unknown width gets
anyway - and there the property must hold.
"""

from __future__ import annotations

import itertools

import pytest

from routemaker.stress import Stress, classify

ROAD = {"highway": "secondary", "maxspeed": "30 mph", "lanes": "2", "parking:both": "no"}

ONEWAYS: tuple[dict[str, str], ...] = (
    {},
    {"oneway": "no"},
    {"oneway": "yes"},
    {"oneway": "-1"},
    {"oneway": "yes", "oneway:bicycle": "no"},
)

SIDES = ("left", "right")

# Key positions, shared by both provisions: the bare key, `:both`, then the two
# side keys. The precedence below is written in these terms.
GENERAL, BOTH, LEFT, RIGHT = range(4)
SIDE_POSITION = {"left": LEFT, "right": RIGHT}


def _tags(keys, values, width_keys, widths, oneway) -> dict[str, str]:
    tags = {**ROAD, **oneway}
    tags.update({k: v for k, v in zip(keys, values, strict=True) if v is not None})
    tags.update({k: w for k, w in zip(width_keys, widths, strict=True) if w is not None})
    return tags


def _grid(keys, value_choices, width_keys, width_choices):
    """Every combination, classified once, keyed by (values, widths, oneway)."""
    tiers = {}
    for values in itertools.product(*value_choices):
        for widths in itertools.product(width_choices, repeat=len(width_keys)):
            for index, oneway in enumerate(ONEWAYS):
                tags = _tags(keys, values, width_keys, widths, oneway)
                tiers[values, widths, index] = classify(tags).tier
    return tiers


def _governs(position: int, present: tuple) -> tuple[str, ...]:
    """The sides a key at `position` answers for: those no more specific key
    speaks for. The precedence, written out here rather than read from `tags`."""
    if position in (LEFT, RIGHT):
        return (SIDES[position - LEFT],)
    unsaid = tuple(side for side in SIDES if present[SIDE_POSITION[side]] is None)
    if position == GENERAL and present[BOTH] is not None:
        return ()
    return unsaid


def _resolve(present: tuple, side: str):
    """The oracle: the side key, then `:both`, then the bare key."""
    order = (SIDE_POSITION[side], BOTH, GENERAL)
    return next((present[i] for i in order if present[i] is not None), None)


def _replace(values: tuple, position: int, new) -> tuple:
    return (*values[:position], new, *values[position + 1 :])


def _surveyed_everywhere(widths: tuple, unsurveyed: tuple[str, ...], narrow: str) -> tuple:
    """`widths` with a narrow width on each named side, at its own key."""
    for side in unsurveyed:
        widths = _replace(widths, SIDE_POSITION[side], narrow)
    return widths


# ---------------------------------------------------------------------------
# The cycleway.
# ---------------------------------------------------------------------------

CW_KEYS = ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")
CW_WIDTH_KEYS = tuple(f"{key}:width" for key in CW_KEYS)
CW_VALUES = (None, "no", "lane", "opposite_lane", "track")
CW_WIDTHS = (None, "1.2", "2.0")

# What each value may be upgraded to without taking anything from any rider.
# `lane` -> `opposite_lane` is not an upgrade: where bicycles ride a one-way
# street both ways it moves the lane from the with-flow rider to the contraflow
# one. `None` -> `no` changes nothing and is in the relation as a no-op.
CW_UPGRADES = {
    None: ("no", "lane", "opposite_lane", "track"),
    "no": ("lane", "opposite_lane", "track"),
    "lane": ("track",),
    "opposite_lane": ("track",),
    "track": (),
}


@pytest.fixture(scope="module")
def cycleway_grid():
    return _grid(CW_KEYS, [CW_VALUES] * 4, CW_WIDTH_KEYS, CW_WIDTHS)


def test_the_cycleway_grid_is_the_whole_space(cycleway_grid) -> None:
    assert len(cycleway_grid) == len(CW_VALUES) ** 4 * len(CW_WIDTHS) ** 4 * len(ONEWAYS)
    # Every tier is reached, so every step below can be seen to move.
    assert set(cycleway_grid.values()) == set(Stress)


def test_adding_a_cycleway_never_raises_the_tier(cycleway_grid) -> None:
    checked = improved = excused = 0
    failures = []
    for (values, widths, oneway), tier in cycleway_grid.items():
        for position, current in enumerate(values):
            reached = [_resolve(values, side) for side in _governs(position, values)]
            for new in CW_UPGRADES[current]:
                if any(new != r and new not in CW_UPGRADES[r] for r in reached):
                    continue  # it would shadow something better on some side
                upgraded = _replace(values, position, new)
                after = cycleway_grid[upgraded, widths, oneway]
                checked += 1
                improved += after < tier
                if after <= tier:
                    continue
                # The survey artefact, and only it: with every side measured
                # the upgrade may not raise the tier, and it rose by one.
                unsurveyed = tuple(s for s in SIDES if _resolve(widths, s) is None)
                strict = _surveyed_everywhere(widths, unsurveyed, CW_WIDTHS[1])
                if (
                    unsurveyed
                    and after - tier == 1
                    and cycleway_grid[upgraded, strict, oneway]
                    <= cycleway_grid[values, strict, oneway]
                ):
                    excused += 1
                    continue
                failures.append((values, position, new, widths, ONEWAYS[oneway], tier, after))
    assert not failures, failures[:5]
    # Not vacuous: the walk crossed the space and the tier moved on many edges.
    assert checked > 100_000
    assert improved > 10_000
    assert excused < checked // 100


def test_a_narrower_cycleway_never_lowers_the_tier(cycleway_grid) -> None:
    checked = worsened = 0
    failures = []
    for (values, widths, oneway), tier in cycleway_grid.items():
        for position, current in enumerate(widths):
            for new in CW_WIDTHS[1:]:
                if current is not None:
                    if float(new) >= float(current):
                        continue
                else:
                    # A width added where none was is a narrowing only if every
                    # side the key answers for already had a wider one.
                    reached = [_resolve(widths, side) for side in _governs(position, widths)]
                    if not reached or any(r is None or float(r) <= float(new) for r in reached):
                        continue
                after = cycleway_grid[values, _replace(widths, position, new), oneway]
                checked += 1
                worsened += after > tier
                if after < tier:
                    failures.append((values, widths, position, new, ONEWAYS[oneway], tier, after))
    assert not failures, failures[:5]
    assert checked > 50_000
    assert worsened > 1_000


def test_the_cycleway_key_form_does_not_matter(cycleway_grid) -> None:
    """Every way scores as its two sides spelled on the side keys alone."""
    for (values, widths, oneway), tier in cycleway_grid.items():
        canonical_values = (None, None, _resolve(values, "left"), _resolve(values, "right"))
        canonical_widths = (None, None, _resolve(widths, "left"), _resolve(widths, "right"))
        canonical = cycleway_grid[canonical_values, canonical_widths, oneway]
        assert canonical is tier, (values, widths, ONEWAYS[oneway])


# ---------------------------------------------------------------------------
# The shoulder.
# ---------------------------------------------------------------------------

SH_KEYS = ("shoulder", "shoulder:both", "shoulder:left", "shoulder:right")
SH_WIDTH_KEYS = tuple(f"{key}:width" for key in SH_KEYS)
# The bare key also takes a side as its value (`shoulder=right`).
SH_VALUES = (
    (None, "no", "yes", "left", "right"),
    (None, "no", "yes"),
    (None, "no", "yes"),
    (None, "no", "yes"),
)
SH_WIDTHS = (None, "1.3", "2.4")

# `yes` never takes anything from a side: at its own level it is presence, and
# the width it carries is the most specific one surveyed at or below it, which
# is what the side had. `left` and `right` are upgrades only to `yes`.
SH_UPGRADES = {None: ("yes",), "no": ("yes",), "yes": (), "left": ("yes",), "right": ("yes",)}


def _shoulder_side(values: tuple, widths: tuple, side: str) -> tuple[bool | None, str | None]:
    """The oracle: the first level that says anything answers, a width at a
    level beats a `no` at the same level, and a side found present takes the
    most specific width at or below that level."""
    levels = []
    for i in (SIDE_POSITION[side], BOTH, GENERAL):
        value, width = values[i], widths[i]
        if i == GENERAL and value in SIDES and value != side:
            value, width = "no", None
        levels.append((value, width))
    for index, (value, width) in enumerate(levels):
        if value is None and width is None:
            continue
        if width is None and value == "no":
            return False, None
        below = [w for _, w in levels[index:] if w is not None]
        return True, (below[0] if below else None)
    return None, None


@pytest.fixture(scope="module")
def shoulder_grid():
    return _grid(SH_KEYS, SH_VALUES, SH_WIDTH_KEYS, SH_WIDTHS)


def _shoulder_tier_surveyed_everywhere(values: tuple, widths: tuple, oneway: int) -> Stress:
    """The tier with every present shoulder of unknown width given one too
    narrow to ride - the reading an unknown width gets anyway."""
    unsurveyed = tuple(
        side for side in SIDES if _shoulder_side(values, widths, side) == (True, None)
    )
    strict = _surveyed_everywhere(widths, unsurveyed, "1.0")
    return classify(_tags(SH_KEYS, values, SH_WIDTH_KEYS, strict, ONEWAYS[oneway])).tier


def test_adding_a_shoulder_never_raises_the_tier(shoulder_grid) -> None:
    checked = improved = excused = 0
    failures = []
    for (values, widths, oneway), tier in shoulder_grid.items():
        for position, current in enumerate(values):
            for new in SH_UPGRADES[current]:
                upgraded = _replace(values, position, new)
                after = shoulder_grid[upgraded, widths, oneway]
                checked += 1
                improved += after < tier
                if after <= tier:
                    continue
                if after - tier == 1 and _shoulder_tier_surveyed_everywhere(
                    upgraded, widths, oneway
                ) <= _shoulder_tier_surveyed_everywhere(values, widths, oneway):
                    excused += 1
                    continue
                failures.append((values, position, new, widths, ONEWAYS[oneway], tier, after))
    assert not failures, failures[:5]
    assert checked > 50_000
    assert improved > 1_000
    assert excused < checked // 100


def test_a_narrower_shoulder_never_lowers_the_tier(shoulder_grid) -> None:
    checked = worsened = 0
    failures = []
    for (values, widths, oneway), tier in shoulder_grid.items():
        for position, current in enumerate(widths):
            if current != "2.4":
                continue
            after = shoulder_grid[values, _replace(widths, position, "1.3"), oneway]
            checked += 1
            worsened += after > tier
            if after < tier:
                failures.append((values, widths, position, ONEWAYS[oneway], tier, after))
    assert not failures, failures[:5]
    assert checked > 50_000
    assert worsened > 1_000


def test_the_shoulder_key_form_does_not_matter(shoulder_grid) -> None:
    for (values, widths, oneway), tier in shoulder_grid.items():
        canonical_values, canonical_widths = [None, None], [None, None]
        for side in SIDES:
            present, width = _shoulder_side(values, widths, side)
            canonical_values.append(None if present is None else ("yes" if present else "no"))
            canonical_widths.append(width)
        canonical = shoulder_grid[tuple(canonical_values), tuple(canonical_widths), oneway]
        assert canonical is tier, (values, widths, ONEWAYS[oneway])
