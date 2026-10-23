"""The bike network's shape for the zoomed-out map (`pipeline.bike_network`): the owner,
2026-10-23, "If it doesn't connect to anything, don't include it" ... "Or try to see if you
can make a connection through <LTS3 roads", "all these cul-de-sacs. They aren't useful for
transportation", "These bits too" (zoom 10-11) and "make connections across from the MBT to
Rock Creek trail ... Include the minor trails and connections to them"."""

from __future__ import annotations

import pytest
from django.db import connection

from pipeline import bike_network as bn

LON, LAT = -77.03, 38.90
STEP = 0.001  # about 285 ft (87 m) east-west, 365 ft (111 m) north-south


def insert(schema, way, a, b, tier=2, **columns) -> None:
    names = "".join(f", {name}" for name in columns)
    marks = "".join(", %s" for _ in columns)
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO {schema}.segment (osm_way_id, ordinal, geometry, stress_tier, "
            f"stress_rule{names}) VALUES (%s, 0, ST_SetSRID(ST_MakeLine(ST_MakePoint(%s, %s), "
            f"ST_MakePoint(%s, %s)), 4326), %s, 'x'{marks})",
            [way, LON + a[0] * STEP, LAT + a[1] * STEP, LON + b[0] * STEP, LAT + b[1] * STEP,
             tier, *columns.values()],
        )  # fmt: skip


def found(schema, column="overview") -> dict:
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT osm_way_id, {column} FROM {schema}.segment")
        return dict(cursor.fetchall())


def lane(schema, way, a, b, tier=2) -> None:
    insert(schema, way, a, b, tier, facility="lane")


@pytest.mark.django_db(transaction=True)
class TestMark:
    def main_lane(self, schema) -> None:
        """A bike lane of about 1,040 m (3,420 ft) along y = 0, cut at x = 3 and x = 6."""
        lane(schema, 1, (0, 0), (3, 0))
        lane(schema, 2, (3, 0), (6, 0))
        lane(schema, 3, (6, 0), (12, 0))

    def test_a_short_bit_joins_the_rest_through_a_calm_street(self, segment_schemas) -> None:
        _, staging = segment_schemas
        self.main_lane(staging)
        lane(staging, 10, (3, 3), (5, 3))  # 174 m of lane
        insert(staging, 11, (3, 0), (3, 3), tier=2)  # 333 m at LTS 2
        stats = bn.mark(staging)
        assert found(staging) == {1: 0, 2: 0, 3: 0, 10: 0, 11: bn.OVERVIEW_LINK}
        assert stats["links"] == 1 and stats["orphans"] == 0

    def test_a_short_bit_with_no_calm_way_to_the_rest_is_an_orphan(self, segment_schemas) -> None:
        _, staging = segment_schemas
        self.main_lane(staging)
        lane(staging, 10, (3, 3), (5, 3))
        insert(staging, 11, (3, 0), (3, 3), tier=3)  # "<LTS3": not this one
        bn.mark(staging)
        assert found(staging) == {1: 0, 2: 0, 3: 0, 10: bn.OVERVIEW_ORPHAN, 11: 0}

    def test_a_cul_de_sac_is_a_dead_end_and_one_with_a_path_through_is_not(
        self, segment_schemas
    ) -> None:
        _, staging = segment_schemas
        self.main_lane(staging)
        insert(staging, 20, (3, 0), (3, 2), tier=1)  # 222 m, then nothing
        insert(staging, 21, (6, 0), (6, 2), tier=1)  # 222 m, then a path on to a lane
        insert(staging, 22, (6, 2), (6, 5), tier=1, facility="path", is_trail_class=True)
        lane(staging, 23, (0, 5), (6, 5))
        lane(staging, 25, (6, 5), (12, 5))
        insert(staging, 24, (12, 0), (12, 2), tier=1)  # 222 m off a lane's end
        bn.mark(staging)
        marks = found(staging)
        assert marks[20] == bn.OVERVIEW_SPUR and marks[24] == bn.OVERVIEW_SPUR
        assert marks[21] == 0 and marks[22] == 0

    def test_a_sidewalk_does_not_close_a_cul_de_sac(self, segment_schemas) -> None:
        _, staging = segment_schemas
        self.main_lane(staging)
        insert(staging, 20, (3, 0), (3, 2), tier=1)
        # A sidewalk from the cul-de-sac's end back to the lane.
        insert(staging, 21, (3, 2), (6, 0), tier=1, is_trail_class=True, roadside=True)
        bn.mark(staging)
        assert found(staging)[20] == bn.OVERVIEW_SPUR

    def test_one_busy_block_on_a_drawn_street_is_bridged(self, segment_schemas) -> None:
        """The owner, 2026-10-23, near NoMa: "So much are broken up"."""
        _, staging = segment_schemas
        lane(staging, 1, (0, 0), (6, 0))
        insert(staging, 2, (6, 0), (8, 0), tier=3)  # 174 m at LTS 3, the street runs on
        lane(staging, 3, (8, 0), (14, 0))
        insert(staging, 4, (6, 0), (6, 2), tier=3)  # a busy cross street: no
        insert(staging, 5, (0, 3), (12, 3), tier=3)  # long and not between drawn ways: no
        stats = bn.mark(staging)
        marks = found(staging)
        assert marks[2] == bn.OVERVIEW_LINK and marks[5] == 0
        assert marks[4] != bn.OVERVIEW_LINK
        assert stats["busy blocks bridged"] == 1

    def test_a_join_inside_a_bit_that_joins_nothing_is_an_orphan(self, segment_schemas) -> None:
        _, staging = segment_schemas
        lane(staging, 1, (0, 0), (2, 0))
        insert(staging, 2, (2, 0), (3, 0), tier=2, overview=bn.OVERVIEW_LINK)  # from `tidy`
        lane(staging, 3, (3, 0), (5, 0))
        bn.mark(staging)
        assert found(staging) == {1: 2, 2: 2, 3: 2}

    def test_the_live_table_is_refused(self, segment_schemas) -> None:
        live, _ = segment_schemas
        with pytest.raises(Exception, match="live"):
            bn.mark(live)


@pytest.mark.django_db(transaction=True)
class TestZoomedOut:
    def test_a_short_bit_is_left_out_at_zoom_11_and_a_long_one_stays(self, segment_schemas) -> None:
        _, staging = segment_schemas
        insert(staging, 1, (0, 0), (2, 0), bike_popular=3)  # 174 m
        insert(staging, 2, (0, 5), (23, 5), bike_popular=3)  # 2,000 m
        stats = bn.mark_strays(staging)
        assert found(staging, "stray_zoom") == {1: 11, 2: 0}
        assert stats[11] == 1

    def test_a_bit_left_out_at_zoom_10_but_joined_at_zoom_11(self, segment_schemas) -> None:
        _, staging = segment_schemas
        insert(staging, 1, (0, 0), (2, 0), bike_popular=3)  # 174 m of class 3 ...
        insert(staging, 2, (2, 0), (25, 0), bike_popular=2)  # ... on 2,000 m of class 2
        bn.mark_strays(staging)
        assert found(staging, "stray_zoom") == {1: 10, 2: 0}

    def test_a_join_passes_through_a_small_piece_and_a_small_pair_is_not_joined(
        self, segment_schemas
    ) -> None:
        _, staging = segment_schemas
        insert(staging, 1, (0, 0), (20, 0), bike_popular=3)
        insert(staging, 2, (0, 10), (20, 10), bike_popular=3)
        insert(staging, 3, (0, 0), (0, 4), tier=2)
        insert(staging, 4, (0, 4), (0, 5), facility="path", is_trail_class=True)  # 111 m
        insert(staging, 5, (0, 5), (0, 10), tier=2)
        # Two scraps of path 222 m apart, far from the rest: joining them makes no mile.
        insert(staging, 6, (40, 40), (41, 40), facility="path", is_trail_class=True)
        insert(staging, 7, (41, 40), (41, 42), tier=1)
        insert(staging, 8, (41, 42), (42, 42), facility="path", is_trail_class=True)
        bn.connect(staging)
        marks = found(staging)
        assert {way: marks[way] for way in (3, 4, 5)} == {3: 4, 4: 4, 5: 4}
        assert {way: marks[way] for way in (6, 7, 8)} == {6: 0, 7: 0, 8: 0}

    def test_two_trails_in_different_boxes_join(self, segment_schemas) -> None:
        """Each trail's first point in its own box (BOX_DEG), the street between them
        crossing the edge."""
        _, staging = segment_schemas
        # x 0-20 and x 50-70: 30 steps (about 2,600 m) of street between them.
        insert(staging, 1, (0, 0), (20, 0), bike_popular=3)
        insert(staging, 2, (35, 0), (50, 0), tier=1)
        insert(staging, 3, (20, 0), (35, 0), tier=1)
        insert(staging, 4, (50, 0), (70, 0), bike_popular=3)
        bn.connect(staging)
        marks = found(staging)
        assert marks[2] == 4 and marks[3] == 4

    def test_two_trails_join_along_the_calmest_street_and_a_minor_trail_joins_them(
        self, segment_schemas
    ) -> None:
        _, staging = segment_schemas
        insert(staging, 1, (0, 0), (20, 0), bike_popular=3)  # 1,740 m
        insert(staging, 2, (0, 10), (20, 10), bike_popular=3)
        insert(staging, 3, (0, 0), (0, 10), tier=2)  # 1,110 m at LTS 2
        insert(staging, 4, (20, 0), (20, 10), tier=4)  # the same length at LTS 4
        insert(staging, 5, (10, 0), (10, -2), facility="path", is_trail_class=True)
        insert(staging, 6, (40, 40), (41, 40), facility="path", is_trail_class=True)
        stats = bn.connect(staging)
        assert found(staging) == {1: 0, 2: 0, 3: 4, 4: 0, 5: 4, 6: 0}
        assert stats == {"connecting ways": 1, "minor trails": 1}
        bn.mark_strays(staging)
        assert set(found(staging, "stray_zoom").values()) == {0}

    def test_the_live_table_is_refused(self, segment_schemas) -> None:
        live, _ = segment_schemas
        with pytest.raises(Exception, match="live"):
            bn.connect(live)
