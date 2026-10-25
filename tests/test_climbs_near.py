"""core.climbs_near: the categorised climbs near a point, for the connector's `climbs_near`
(v0.12.3; the owner, 2026-10-25, of hill repeats: "Yep, add that")."""

from __future__ import annotations

import pytest

from core import climbs_near, hillseek


def climb(cid, line, grade=5.0, **extra):
    return hillseek.Climb(
        id=cid,
        category="5",
        length_m=1000.0,
        gain_m=50.0,
        grade_pct=grade,
        line=tuple(line),
        **extra,
    )


@pytest.fixture
def climbs(monkeypatch):
    rows = [
        climb("far", [(-77.30, 38.94), (-77.31, 38.94)]),
        climb("near", [(-77.051, 38.94), (-77.06, 38.941)], surface="p"),
        climb("gentle", [(-77.05, 38.945), (-77.05, 38.95)], grade=2.0, busy=True),
    ]
    monkeypatch.setattr(hillseek, "load", lambda: tuple(rows))
    return rows


def test_the_climbs_in_reach_nearest_first_with_points_up_them(climbs) -> None:
    found = climbs_near.near(-77.05, 38.94, 3)
    assert [c["id"] for c in found] == ["near", "gentle"]
    near = found[0]
    assert near["surface"] == "path" and near["away_mi"] == pytest.approx(0.1, abs=0.1)
    assert near["foot"] == [-77.051, 38.94] and near["summit"] == [-77.06, 38.941]
    assert near["through"] and found[1]["busy"] is True
    assert [c["id"] for c in climbs_near.near(-77.05, 38.94, 3, min_grade=4)] == ["near"]


def test_no_file_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(hillseek, "load", lambda: None)
    with pytest.raises(climbs_near.Unavailable):
        climbs_near.near(-77.05, 38.94, 3)


def test_filters_apply_before_the_cut_and_old_files_say_so(monkeypatch) -> None:
    # 30 gentle climbs right by the point, one steep one further: the steep one is found.
    rows = [climb(f"g{k}", [(-77.05, 38.94 + k * 1e-4), (-77.06, 38.94)], 2.0) for k in range(30)]
    rows.append(climb("steep", [(-77.08, 38.94), (-77.09, 38.94)], 8.0))
    # An unpaved climb from a file without `s`: its `u` still counts.
    rows.append(climb("dirt", [(-77.05, 38.941), (-77.06, 38.941)], 9.0, unpaved=True))
    monkeypatch.setattr(hillseek, "load", lambda: tuple(rows))
    found = climbs_near.near(-77.05, 38.94, 5, steepest=True, paved_only=True)
    assert found[0]["id"] == "steep" and "dirt" not in [c["id"] for c in found]
    assert climbs_near.near(-77.05, 38.94, 5, min_grade=8.5)[0]["surface"] == "gravel"
    # 1000 m at 8%: about 3.8 minutes at 18 mph, so a 5-minute effort does not fit.
    assert climbs_near.near(-77.05, 38.94, 5, on_minutes=3.5)[0]["id"] in ("steep", "dirt")
    assert climbs_near.near(-77.05, 38.94, 5, min_grade=8, on_minutes=5) == []
    # No climb in this file is marked busy: busy is unknown, not False.
    assert found[0]["busy"] is None


def test_a_long_straight_climb_is_measured_to_its_line_not_its_ends(monkeypatch) -> None:
    rows = [climb("long", [(-77.10, 38.94), (-77.00, 38.94)])]  # 5.4 mi, two vertices
    monkeypatch.setattr(hillseek, "load", lambda: tuple(rows))
    (found,) = climbs_near.near(-77.05, 38.941, 0.5)
    assert found["away_mi"] == pytest.approx(0.1, abs=0.05)
