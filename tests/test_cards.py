from __future__ import annotations

import pytest

from routemaker.cards import (
    CARD_SIZES,
    OPERATIONAL_POINTS,
    CardRequest,
    CardStyle,
    build,
)


def request(**kwargs) -> CardRequest:
    return CardRequest(
        style=kwargs.pop("style", CardStyle.FULL_ROUTE),
        size=kwargs.pop("size", "og"),
        **kwargs,
    )


@pytest.mark.parametrize("size", sorted(CARD_SIZES))
def test_attribution_appears_at_every_size(size: str) -> None:
    """Including the smallest. It is not dropped when space gets tight."""
    card = build(request(size=size), 10_000, 100)
    assert "OpenStreetMap" in card.attribution
    assert "Protomaps" in card.attribution


def test_operational_points_are_suppressed_without_standing() -> None:
    """A card is effectively unrecallable once posted, so suppression happens at
    render time rather than at serve time."""
    card = build(request(viewer_has_operational_access=False), 10_000, 100)
    assert not (card.control_points & OPERATIONAL_POINTS)


def test_operational_points_appear_for_a_viewer_who_holds_standing() -> None:
    card = build(request(viewer_has_operational_access=True), 10_000, 100)
    assert OPERATIONAL_POINTS <= card.control_points


def test_start_only_style_carries_no_geometry() -> None:
    """The style exists to publish a ride without publishing its route."""
    card = build(request(style=CardStyle.START_ONLY), 10_000, 100)
    assert not card.show_geometry


def test_start_only_suppresses_operational_points_even_with_standing() -> None:
    """The style's whole purpose would otherwise be defeated by the viewer
    happening to be a marshal."""
    card = build(
        request(style=CardStyle.START_ONLY, viewer_has_operational_access=True),
        10_000,
        100,
    )
    assert not (card.control_points & OPERATIONAL_POINTS)


def test_elevation_is_opt_in() -> None:
    assert not build(request(), 10_000, 100).show_elevation
    assert build(request(include_elevation=True), 10_000, 100).show_elevation


def test_qr_is_optional() -> None:
    assert not build(request(), 10_000, 100).show_qr
    assert build(request(include_qr=True), 10_000, 100).show_qr


def test_stats_match_the_units_the_card_prints() -> None:
    card = build(request(), 1609.344, 30.48)
    assert card.distance_mi == pytest.approx(1.0)
    assert card.gain_ft == pytest.approx(100.0)
