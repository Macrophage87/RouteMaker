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
    assert body["gain_m"] == 6.0 and body["loss_m"] == 9.0
    assert body["length_m"] == 240 and body["way"] == 7
    assert body["max_grade_pct"] is not None and body["max_grade_pct"] > 0
    assert trailprofile.body_of(7, at, [None] * len(at), 30) is None
