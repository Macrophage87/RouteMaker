"""The same rules in every jurisdiction unless the law differs (the owner,
2026-10-31): West Virginia's speed law, and a state left out of the urban list."""

from __future__ import annotations

from pipeline.states import states_without_urban
from routemaker.stress import Stress, classify, statutory_default_mph


class TestWestVirginiaSpeedLaw:
    """W. Va. Code 17C-6-1(b): 25 in a business or residence district, 55 on
    open country highways - Virginia's figures."""

    def test_statutory_defaults(self):
        assert statutory_default_mph({}, "WV", urban=True, divided=False) == 25.0
        assert statutory_default_mph({}, "WV", urban=False, divided=False) == 55.0

    def test_no_separate_unpaved_figure(self):
        gravel = {"surface": "gravel"}
        assert statutory_default_mph(gravel, "WV", urban=False, divided=False) == 55.0

    def test_an_unposted_town_street_reads_as_in_virginia(self):
        tags = {"highway": "tertiary"}
        wv = classify(tags, urban=True, jurisdiction="WV")
        va = classify(tags, urban=True, jurisdiction="VA")
        assert (wv.tier, wv.rule) == (va.tier, va.rule)
        assert wv.tier is Stress.LTS3

    def test_a_zone_tag_names_west_virginia(self):
        tags = {"highway": "tertiary", "maxspeed:type": "US-WV:urban"}
        assert classify(tags, urban=True).tier is Stress.LTS3


class TestUrbanListCoversEveryState:
    def test_a_state_with_no_urban_way_is_named(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "WV" for i in range(1500, 3000)}
        urban = frozenset(range(100))
        assert states_without_urban(state_of, urban) == ["WV"]

    def test_every_state_with_towns_passes(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "WV" for i in range(1500, 3000)}
        urban = frozenset({1, 1501})
        assert states_without_urban(state_of, urban) == []

    def test_a_sliver_of_a_state_is_not_checked(self):
        state_of = {i: "MD" for i in range(1500)} | {i: "PA" for i in range(1500, 1600)}
        assert states_without_urban(state_of, frozenset({1})) == []
