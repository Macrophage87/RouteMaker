"""Crossing collapse rules."""

from __future__ import annotations

from pipeline.crossings import (
    DEFAULT_MIN_CROSSING_M,
    Crossing,
    collapse_short_crossings,
    distinct_authorities,
    state_line_crossings,
)

LONG = DEFAULT_MIN_CROSSING_M * 3
SHORT = DEFAULT_MIN_CROSSING_M / 4


def crossing(authority: str, length: float, **kwargs) -> Crossing:
    return Crossing(
        layer=kwargs.pop("layer", "police"),
        authority=authority,
        start_m=0.0,
        end_m=length,
        **kwargs,
    )


def test_short_crossings_collapse() -> None:
    kept = collapse_short_crossings([crossing("MPD", LONG), crossing("USPP", SHORT)])
    assert [c.authority for c in kept] == ["MPD"]


def test_federal_enclave_survives_at_any_length() -> None:
    """The NPS land at the foot of Memorial Bridge is short. Short is not the same
    as unimportant when the question is whose permit is needed."""
    kept = collapse_short_crossings(
        [crossing("MPD", LONG), crossing("USPP", SHORT, is_federal_enclave=True)]
    )
    assert [c.authority for c in kept] == ["MPD", "USPP"]


def test_crossing_with_a_control_point_survives() -> None:
    """The route stops there, so the authority matters however brief the stretch."""
    kept = collapse_short_crossings(
        [crossing("MPD", LONG), crossing("AOC", SHORT, contains_control_point=True)]
    )
    assert len(kept) == 2


def test_all_three_layers_are_reported() -> None:
    """The permit issuer is frequently not a police agency."""
    authorities = distinct_authorities(
        [
            crossing("MPD", LONG, layer="police"),
            crossing("DDOT", LONG, layer="row"),
            crossing("NOVA Parks", LONG, layer="manager"),
        ]
    )
    assert set(authorities) == {"police", "row", "manager"}


def test_authorities_are_deduplicated_in_encounter_order() -> None:
    authorities = distinct_authorities(
        [
            crossing("MPD", LONG),
            crossing("USPP", LONG),
            crossing("MPD", LONG),
        ]
    )
    assert authorities["police"] == ["MPD", "USPP"]


def test_state_crossings_are_relative_to_the_home_jurisdiction() -> None:
    """Leaving and returning are both crossings; the penalty for them is off by
    default for every modality, Mass Ride included."""
    crossings = [
        crossing("DC", LONG, layer="state"),
        crossing("VA", LONG, layer="state"),
        crossing("DC", LONG, layer="state"),
    ]
    assert [c.authority for c in state_line_crossings(crossings, "DC")] == ["VA"]
