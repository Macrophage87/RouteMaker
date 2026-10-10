"""The copy-paste Discord post for a rider's suggestion (the owner, 2026-10-10)."""

from __future__ import annotations

import pytest

from core import suggestion_post as sp

URL = "https://example.test/#at=-77.03650,38.89770"


def road_post(**kw):
    args = {
        "kind": "road",
        "road": "Rhode Island Avenue NE",
        "between": ("4th Street NE", "Montana Avenue NE"),
        "lat": 38.9213,
        "lon": -76.9931,
        "current": 3,
        "suggested": 2,
        "reason": "There is a protected lane here now.",
        "map_url": URL,
    }
    args.update(kw)
    return sp.build(**args)


class TestWords:
    def test_each_tier_has_its_own_plain_label_and_no_lts_number(self) -> None:
        assert sorted(sp.ROAD_WORDS) == [1, 2, 3, 4, 5]
        labels = list(sp.ROAD_WORDS.values())
        assert len(set(labels)) == 5
        for label in labels:
            assert "LTS" not in label and not any(c.isdigit() for c in label)
        assert sp.ROAD_WORDS[3] == "OK for confident riders"
        assert sp.ROAD_WORDS[5] == "Avoid it"

    def test_a_half_step_is_the_two_it_lies_between(self) -> None:
        assert sp.road_words(2.5) == (
            'Between "Fine for most people, even nervous riders" and "OK for confident riders"'
        )
        assert sp.road_words(4) == "Only for very experienced riders"

    def test_every_option_reads_back_to_its_tier(self) -> None:
        options = sp.road_options()
        assert [o.letter for o in options] == ["A", "B", "C", "D", "E", "F"]
        assert [o.tier for o in options] == [1, 2, 3, 4, 5, None]
        assert options[-1].label == "Not sure"
        for option in options:
            assert sp.tier_for_vote(options, option.letter.lower()) == option.tier
        assert sp.tier_for_vote(options, "Z") is None

    def test_a_junction_has_plain_options_that_read_back_too(self) -> None:
        options = sp.junction_options()
        assert [o.tier for o in options] == [2, 3, 4, 5, None]
        for option in options[:-1]:
            assert "LTS" not in option.label
            assert sp.tier_for_vote(options, option.letter) == option.tier


class TestRoadPost:
    def test_the_question_names_the_road_and_its_cross_streets_in_plain_words(self) -> None:
        text = road_post().text
        first = text.splitlines()[0]
        assert first == (
            "**How comfortable is biking on Rhode Island Avenue NE, between 4th Street NE "
            "and Montana Avenue NE?**"
        )
        assert "A rider suggested it's calmer than we rate it." in text
        assert "We currently show it as: OK for confident riders" in text
        assert "The rider suggested: Fine for most people, even nervous riders" in text
        assert "LTS" not in text

    def test_it_has_the_reason_the_link_the_place_in_words_and_the_poll(self) -> None:
        post = road_post()
        assert "> There is a protected lane here now." in post.text
        assert f"Map: <{URL}>" in post.text
        assert (
            "Where: Rhode Island Avenue NE between 4th Street NE and Montana Avenue NE "
            "(near 38.92130, -76.99310)"
        ) in post.text
        for option in post.options:
            assert f"{option.emoji} {option.label}" in post.text
        assert "weigh in" in post.text

    def test_more_stressful_is_said_too(self) -> None:
        assert "more stressful than we rate it" in road_post(current=2, suggested=4).text

    def test_without_cross_streets_it_says_near_the_spot(self) -> None:
        text = road_post(between=None, road=None).text
        assert text.splitlines()[0] == "**How comfortable is biking on an unnamed road?**"
        assert "Where: An unnamed road near 38.92130, -76.99310" in text

    def test_it_mentions_nobody_pings_no_role_and_names_no_server(self) -> None:
        text = road_post(reason="@everyone look <@1234> and <@&99> in <#55> @here").text
        assert "@everyone" not in text and "@here" not in text
        assert "<@" not in text and "<#" not in text
        assert "discord.gg" not in text and "server" not in text.lower()

    def test_a_link_in_the_reason_shows_no_preview_and_markdown_is_inert(self) -> None:
        text = road_post(reason="see https://example.org/a_b and **shout**").text
        assert "<https://example.org/a_b>" in text
        assert "\\*\\*shout\\*\\*" in text

    def test_nothing_about_the_rider_is_in_it(self) -> None:
        text = road_post().text
        assert "suggested by" not in text.lower()

    @pytest.mark.parametrize("current,suggested", [(1, 5), (5, 1), (2.5, 3.5), (4.5, 1.5)])
    def test_it_stays_within_discords_limit_even_with_a_long_reason(
        self, current, suggested
    ) -> None:
        post = road_post(
            reason="word " * 3000,
            road="A" * 300,
            between=("B" * 200, "C" * 200),
            current=current,
            suggested=suggested,
        )
        assert len(post.text) <= sp.POST_MAX
        assert "Not sure" in post.text
        assert post.text.rstrip().endswith("bike map.")


class TestJunctionPost:
    def test_the_junction_question_is_plain(self) -> None:
        post = sp.build(
            kind="junction",
            road="New York Avenue NE",
            crossing="Florida Avenue NE",
            lat=38.9150,
            lon=-77.0010,
            current=4,
            suggested=3,
            reason="The new signal gives a long walk phase.",
            map_url=URL,
        )
        assert post.text.splitlines()[0] == (
            "**Is crossing New York Avenue NE at Florida Avenue NE harder or easier than we show?**"
        )
        assert "A rider suggested it's easier than we show." in post.text
        assert "We currently show it as: Hard: long waits or fast traffic" in post.text
        assert "The rider suggested: Takes patience: you wait for a gap" in post.text
        assert len(post.text) <= sp.POST_MAX

    def test_an_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError):
            road_post(kind="bridge")
