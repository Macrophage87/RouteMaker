"""A junction reads a crossed road by its traffic (the owner, 2026-10-31: "a protected bike
lane on a busy road is just as hard to cross", "Traffic only, everywhere"): the lanes
crossed and the speed on Furth's crossing tables and the count on Broach's bins
(`intersections.traffic_level`). That is one reading, kept in one place. The table for
riding ALONG a road (`stress.mixed_traffic_level`) is a different question and is not read
at a junction, and a crossed road with no count is read by its lanes and speed alone, with
no count assumed for it."""

from __future__ import annotations

import pytest

from routemaker.intersections import Control, Junction, Movement, Road, assess, traffic_level


@pytest.mark.parametrize("urban", [True, False])
def test_an_unposted_quiet_street_keeps_its_map_level(urban) -> None:
    # Maryland's statutory 30 in town and 50 out of it are not what the classifier read on a
    # residential street (its own 25), so the junction does not guess: the map stands.
    quiet = Road(1, lanes=1, oneway=False, default_speed_mph=30.0 if urban else 50.0, urban=urban)
    assert traffic_level(quiet) is None
    assert (
        assess(
            Junction(0.0, -77.0, 38.9, Movement.STRAIGHT, Road(1), Road(1), (quiet,), Control.STOP)
        )
        is None
    )
