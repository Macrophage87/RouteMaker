"""Categorised climbs for the Climbs layer (routemaker.climb_categories).

The owner, 2026-10-10 and 2026-10-11 (PLAN.md, "Climbs layer"): Garmin's scale, score =
length (m) x average grade (%), Cat 5 over 4,000 up to HC over 80,000, nothing under Cat 5
("Uncategorized is not a hill"); "if you climb 2000 feet net, but there's a short dip in the
middle, it's still a 2000 foot climb"; long gentle grades count (1% minimum, 500 m, a Cat 5
score); the summit marker's shape by grade: circle under 4%, square 4-7.9%, diamond 8%+.
"""

from __future__ import annotations

import pytest

from routemaker import climb_categories as cc
from routemaker.climb_categories import category, describe, find_climbs, grade_pct, shape


def ramp(length_m, grade, step=30.0):
    """A straight grade from (0, 0), sampled every `step` metres."""
    points = []
    d = 0.0
    while d < length_m:
        points.append((d, grade * d))
        d += step
    points.append((length_m, grade * length_m))
    return points


def join(*parts):
    out = list(parts[0])
    for part in parts[1:]:
        offset_d, offset_e = out[-1]
        out.extend((offset_d + d, offset_e + e) for d, e in part[1:])
    return out


def flat(length_m, step=30.0):
    return ramp(length_m, 0.0, step)


class TestScale:
    @pytest.mark.parametrize(
        "score, expected",
        [
            (4_000, None),
            (4_001, "5"),
            (8_000, "5"),
            (8_001, "4"),
            (16_001, "3"),
            (32_001, "2"),
            (64_001, "1"),
            (80_000, "1"),
            (80_001, "HC"),
            (500, None),
        ],
    )
    def test_garmin_thresholds_with_cat_5_and_nothing_under_it(self, score, expected):
        assert category(score) == expected

    @pytest.mark.parametrize(
        "pct, expected",
        [
            (1.0, "circle"),
            (3.9, "circle"),
            (4.0, "square"),
            (7.9, "square"),
            (8.0, "diamond"),
            (15, "diamond"),
        ],
    )
    def test_shape_by_average_grade(self, pct, expected):
        assert shape(pct) == expected

    def test_grade_is_shown_to_a_tenth_and_the_shape_follows_the_shown_figure(self):
        # 7.96% shows as 8.0%, so the marker is a diamond, not a square under an "8.0%" label.
        assert grade_pct(79.6, 1000) == 8.0
        assert shape(grade_pct(79.6, 1000)) == "diamond"


class TestFinding:
    def test_score_is_length_times_grade(self):
        (climb,) = find_climbs(ramp(1000, 0.05))
        assert climb.length_m == pytest.approx(1000)
        assert climb.gain_m == pytest.approx(50)
        assert climb.score == pytest.approx(5000)
        assert climb.category == "5"
        assert climb.shape == "square"

    def test_under_cat_5_is_not_a_climb(self):
        # 1 km at 4% gains 40 m: a score of 4,000, not over it.
        assert find_climbs(ramp(1000, 0.04)) == []

    def test_shorter_than_500_m_is_not_a_climb_however_steep(self):
        # 480 m at 10% is a score of 4,800, but under Garmin's 500 m.
        assert find_climbs(ramp(480, 0.10)) == []

    def test_a_long_rail_trail_grade_counts(self):
        # 6 km at 1.2%: 72 m gained, Cat 5, a circle.
        (climb,) = find_climbs(ramp(6000, 0.012))
        assert climb.category == "5"
        assert climb.shape == "circle"
        assert climb.grade_pct == 1.2

    def test_under_one_percent_is_not_a_climb_however_long(self):
        # The GAP to the Eastern Continental Divide: about 38 km at 1.4% counts, but 0.9% does not.
        assert find_climbs(ramp(10_000, 0.009)) == []
        assert find_climbs(ramp(38_000, 0.014))[0].category == "2"

    def test_a_short_dip_in_the_middle_is_a_break_not_the_top(self):
        # 300 m (984 ft) up, a 15 m dip over 150 m, then 300 m more: one climb on net gain.
        profile = join(ramp(3000, 0.10), ramp(150, -0.10), ramp(3150, 0.10))
        (climb,) = find_climbs(profile)
        assert climb.gain_m == pytest.approx(300 - 15 + 315)
        assert climb.length_m == pytest.approx(6300)
        assert climb.category == "2"

    def test_the_owners_2000_ft_climb_with_a_dip_is_one_2000_ft_climb(self):
        # "If you climb 2000 feet net, but there's a short dip in the middle, it's still a 2000
        # foot climb": 8 mi (12.9 km) at 4.7%, with a 130 ft (40 m) dip over 0.6 mi (1 km) at
        # halfway and the 40 m back at 5% (800 m). The dip and the climb back together run
        # 1.8 km, past the 1,600 m break, which used to split it; the climb back is climbing.
        half = 6_437.0
        net = 2_000 * 0.3048
        up = (net + 40) / 2
        profile = join(
            ramp(half, up / half),
            ramp(1_000, -0.04),
            ramp(800, 0.05),
            ramp(half - 800, (up - 40) / (half - 800)),
        )
        (climb,) = find_climbs(profile)
        assert climb.gain_m == pytest.approx(net, abs=0.5)
        assert climb.length_m == pytest.approx(2 * half + 1_000, abs=1)

    def test_a_climb_that_levels_off_part_way_back_up_from_a_dip_ends_at_its_top(self):
        # 1 km at 6%, down 30 m, back up 20 m, then 3 km level 10 m below the top, then up again:
        # the climb back is not counted as break, but the whole stretch is capped.
        profile = join(
            ramp(1_000, 0.06), ramp(600, -0.05), ramp(400, 0.05), flat(3_000), ramp(1_000, 0.06)
        )
        climbs = find_climbs(profile)
        assert len(climbs) == 2
        assert climbs[0].end_m == pytest.approx(1_000, abs=31)

    def test_the_old_three_metre_rule_would_have_split_it(self):
        from routemaker.climbs import runs

        profile = join(ramp(3000, 0.10), ramp(150, -0.10), ramp(3150, 0.10))
        assert len([r for r in runs(profile) if r.rise_m > 0]) == 2

    def test_a_short_flat_is_a_break(self):
        profile = join(ramp(800, 0.06), flat(300), ramp(800, 0.06))
        (climb,) = find_climbs(profile)
        assert climb.gain_m == pytest.approx(96)
        assert climb.length_m == pytest.approx(1900)

    def test_a_real_descent_between_two_hills_makes_two_climbs(self):
        # 60 m up, 55 m down (more than DIP_MAX_M), 60 m up.
        profile = join(ramp(1000, 0.06), ramp(1100, -0.05), ramp(1000, 0.06))
        climbs = find_climbs(profile)
        assert [c.category for c in climbs] == ["5", "5"]

    def test_a_dip_bigger_than_its_share_of_a_small_climb_ends_it(self):
        # 45 m gained, then a 12 m dip: over 10 m and over 20% of 45 m, so the top was at 45 m.
        profile = join(ramp(900, 0.05), ramp(240, -0.05), ramp(900, 0.05))
        climbs = find_climbs(profile)
        assert len(climbs) == 2

    def test_a_long_flat_ends_the_climb(self):
        # 2 km of flat after 1 km: past the quarter-length break and the 400 m floor.
        profile = join(ramp(1000, 0.05), flat(2000), ramp(1000, 0.05))
        assert len(find_climbs(profile)) == 2

    def test_a_gentle_approach_is_trimmed_off(self):
        # 3 km at 0.3%, then 1 km at 6%: the climb is the 1 km.
        profile = join(ramp(3000, 0.003), ramp(1000, 0.06))
        (climb,) = find_climbs(profile)
        assert climb.length_m == pytest.approx(1000, abs=60)
        assert climb.grade_pct == pytest.approx(6.0, abs=0.4)

    def test_a_flat_top_is_trimmed_off(self):
        profile = join(ramp(1000, 0.06), ramp(1500, 0.002))
        (climb,) = find_climbs(profile)
        assert climb.end_m == pytest.approx(1000, abs=60)

    def test_the_climb_starts_at_the_bottom_after_a_descent(self):
        profile = join(ramp(600, -0.05), ramp(1000, 0.06))
        (climb,) = find_climbs(profile)
        assert climb.start_m == pytest.approx(600)
        assert climb.gain_m == pytest.approx(60)

    def test_spruce_knob_from_judy_gap_is_hc_as_one_climb(self):
        # 18.7 km at 4.7% with three small dips along the way: about 880 m net, HC.
        segment = ramp(4600, 0.05)
        dip = ramp(200, -0.04)
        profile = join(segment, dip, segment, dip, segment, dip, ramp(4700, 0.05))
        (climb,) = find_climbs(profile)
        assert climb.category == "HC"
        assert climb.length_m == pytest.approx(19_100)

    def test_missing_elevation_splits_the_profile(self):
        profile = (
            ramp(1000, 0.06) + [(1030.0, None)] + [(1060 + d, 60 + e) for d, e in ramp(1000, 0.06)]
        )
        assert len(find_climbs(profile)) == 2

    def test_noise_does_not_end_a_climb(self):
        import random

        rng = random.Random(4)
        profile = [(d, e + rng.uniform(-1.5, 1.5)) for d, e in ramp(3000, 0.04)]
        climbs = find_climbs(profile)
        assert len(climbs) == 1
        assert climbs[0].length_m > 2800


class TestWords:
    def test_the_owners_wording(self):
        # The plan's example sentence, "Category 3 climb, 2.1 miles (3.4 km) at 4.6%": 3.4 km at
        # 4.6% scores 15,640, which is Cat 4 on the scale, so the words are the example's and the
        # category the scale's.
        climb = cc.Climb(start_m=0, end_m=3380, gain_m=155.5)
        assert describe(climb) == "Category 4 climb, 2.1 miles (3.4 km) at 4.6%"
        climb = cc.Climb(start_m=0, end_m=3500, gain_m=161)
        assert describe(climb) == "Category 3 climb, 2.2 miles (3.5 km) at 4.6%"

    def test_one_mile_is_singular(self):
        assert ", 1.0 mile (" in describe(cc.Climb(start_m=0, end_m=1609, gain_m=80))

    def test_hc_is_spelled_out(self):
        climb = cc.Climb(start_m=0, end_m=18_700, gain_m=880)
        assert describe(climb).startswith("Hors catégorie (HC) climb, 11.6 miles (18.7 km) at 4.7%")
