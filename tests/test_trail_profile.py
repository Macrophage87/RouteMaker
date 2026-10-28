"""A tapped mountain-bike trail's elevation profile (`core.trailprofile`; the owner,
2026-10-19: "Include an elevation profile of the trail if possible")."""

from __future__ import annotations

from core import trailprofile


def test_samples_every_interval_with_both_ends() -> None:
    # About 111 m north.
    at, where, step = trailprofile.samples([(-77.0, 38.9), (-77.0, 38.901)])
    assert step == 30
    assert at[:4] == [0.0, 30.0, 60.0, 90.0]
    assert round(at[-1]) == 111 and where[-1] == (-77.0, 38.901)
    assert len(at) == len(where) == 5


def test_a_long_trail_is_sampled_more_sparsely() -> None:
    # About 33 km north: no more than MAX_SAMPLES points.
    at, _where, step = trailprofile.samples([(-77.0, 38.9), (-77.0, 39.2)])
    assert step > 30
    assert len(at) <= trailprofile.MAX_SAMPLES + 1


def test_the_body_counts_up_and_down_and_the_steepest_either_way() -> None:
    at = [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0, 210.0, 240.0]
    heights = [10.0, 12.0, 14.0, 16.0, 16.0, 13.0, 10.0, 7.0, 7.0]
    body = trailprofile.body_of(7, at, heights, 30)
    # The route chart's hysteresis (3 m): up 4 m (10 to 14 counted, 14 to 16 under it), down 6 m.
    assert body["gain_m"] == 4.0 and body["loss_m"] == 6.0
    assert body["length_m"] == 240 and body["way"] == 7
    assert body["max_grade_pct"] is not None and body["max_grade_pct"] > 0
    assert trailprofile.body_of(7, at, [None] * len(at), 30) is None


def test_noise_on_a_flat_trail_is_no_climbing() -> None:
    at = [30.0 * i for i in range(20)]
    heights = [10.0 + (1.5 if i % 2 else 0.0) for i in range(20)]
    body = trailprofile.body_of(7, at, heights, 30)
    assert body["gain_m"] == 0.0 and body["loss_m"] == 0.0


def test_the_line_is_kept_whole_or_thinned_with_both_ends() -> None:
    """The map lights up the way the chart is of (the owner, 2026-10-28: "highlight that
    trail so you know where the elevation profile and rating begins and ends")."""
    short = [(-77.0, 38.9), (-77.0000004, 38.9001234567)]
    assert trailprofile.line_out(short) == [[-77.0, 38.9], [-77.0, 38.900123]]
    long = [(-77.0, 38.9 + i * 1e-5) for i in range(2501)]
    thinned = trailprofile.line_out(long)
    assert len(thinned) <= trailprofile.MAX_LINE_POINTS
    assert thinned[0] == [-77.0, 38.9] and thinned[-1] == [-77.0, round(38.9 + 2500e-5, 6)]
