"""The post an instance admin copies into Discord to let riders weigh in on a suggestion.

The owner, 2026-10-10 (docs/OPERATIONS.md, "Rider suggestions"): the third action on a
rider's suggestion is to send it to Discord ("I meant discord itself"), and "If it's too
much to send directly, then provide something I can copy paste as a post to discord." The
copy is the action that is always there ("I like the fallback because I can also poll one
of several bike groups I'm a part of"), so the post is self-contained: it names no server
or channel, mentions nobody, pings no role, and says where the road is in words as well as
by a link. It is a simple poll answered with letter reactions.

"Not everyone is familiar with that scale, so give a plain english request." (2026-10-10
14:08 UTC): the question, the levels and the options are plain US English, never an LTS
number alone. Each option maps to a tier (`PollOption.tier`) so the votes can be read back.

Nothing about the rider who suggested it is in the post: no name, no account, no id. Their
reason is quoted, with mentions and links made inert. The post is at most `POST_MAX`
characters (Discord's limit for one message); the reason is shortened first to fit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Discord's limit for one message.
POST_MAX = 2000
# The longest road or cross-street name the post quotes.
NAME_MAX = 120
# The longest quoted reason before the whole post is measured.
REASON_QUOTE_MAX = 600

# One plain label per whole level (OWNER-DECISIONS 441l's words, said for anyone).
ROAD_WORDS = {
    1: "Fine for anyone, kids included",
    2: "Fine for most people, even nervous riders",
    3: "OK for confident riders",
    4: "Only for very experienced riders",
    5: "Avoid it",
}
# A junction's options, by the tier of the road crossed that would make it so
# (`routemaker.intersections`: calm below LTS 3, orange at 3, red at 4, Avoid at 5).
JUNCTION_WORDS = {
    2: "Easy: little waiting, and drivers are slow",
    3: "Takes patience: you wait for a gap",
    4: "Hard: long waits or fast traffic",
    5: "Avoid crossing here",
}
NOT_SURE = "Not sure"

# Regional-indicator letters, the reactions Discord shows as A, B, C ...
_LETTERS = "ABCDEFGH"
_EMOJI = {c: chr(0x1F1E6 + i) for i, c in enumerate(_LETTERS)}


@dataclass(frozen=True)
class PollOption:
    letter: str
    emoji: str
    label: str
    # The whole tier a vote for it means; None for "Not sure".
    tier: int | None


@dataclass(frozen=True)
class Post:
    text: str
    options: tuple[PollOption, ...]


def road_words(step: float) -> str:
    """A level in plain words; a half step as the two it lies between."""
    tier = int(step)
    if step != tier and tier in ROAD_WORDS and tier + 1 in ROAD_WORDS:
        return f'Between "{ROAD_WORDS[tier]}" and "{ROAD_WORDS[tier + 1]}"'
    return ROAD_WORDS.get(tier, "Not rated")


def junction_words(step: float) -> str:
    tier = max(2, min(5, int(step + 0.5)))
    return JUNCTION_WORDS[tier]


def road_options() -> tuple[PollOption, ...]:
    return _options([(t, ROAD_WORDS[t]) for t in sorted(ROAD_WORDS)])


def junction_options() -> tuple[PollOption, ...]:
    return _options([(t, JUNCTION_WORDS[t]) for t in sorted(JUNCTION_WORDS)])


def _options(levels: list[tuple[int, str]]) -> tuple[PollOption, ...]:
    out = [
        PollOption(c, _EMOJI[c], label, tier)
        for c, (tier, label) in zip(_LETTERS, levels, strict=False)
    ]
    c = _LETTERS[len(out)]
    out.append(PollOption(c, _EMOJI[c], NOT_SURE, None))
    return tuple(out)


def tier_for_vote(options: tuple[PollOption, ...], letter: str) -> int | None:
    """The tier a reaction stands for: read the votes back (None: not sure, or no such letter)."""
    for option in options:
        if option.letter == letter.strip().upper():
            return option.tier
    return None


_MENTION = re.compile(r"<(@[!&]?|#)\d+>")
_URL = re.compile(r"(https?://\S+)")


def inert(text: str) -> str:
    """A rider's words safe to paste: one paragraph, no mention, no role ping, no embed,
    no markdown that would change the post around it."""
    text = " ".join((text or "").split())
    text = _MENTION.sub("(mention removed)", text)
    # A zero-width space after @ keeps @everyone, @here and @name from pinging anyone.
    text = text.replace("@", "@​")
    parts = _URL.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            # <link> shows a link without the preview card.
            out.append(f"<{part.rstrip('>')}>")
            continue
        for mark in ("*", "_", "~", "`", "|"):
            part = part.replace(mark, "\\" + mark)
        out.append(part)
    return "".join(out)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def where_words(road: str | None, between: tuple[str, str] | None, lat: float, lon: float) -> str:
    """The plain-text location: the road, its cross streets where known, and the spot."""
    name = road or "An unnamed road"
    spot = f"{lat:.5f}, {lon:.5f}"
    if between and all(between) and between[0] != between[1]:
        return f"{name} between {between[0]} and {between[1]} (near {spot})"
    return f"{name} near {spot}"


def build(
    *,
    kind: str,
    road: str | None,
    lat: float,
    lon: float,
    current: float,
    suggested: float,
    reason: str,
    map_url: str,
    between: tuple[str, str] | None = None,
    crossing: str | None = None,
) -> Post:
    """The post for one suggestion, at most POST_MAX characters.

    `kind` "road": a road piece's traffic stress; "junction": crossing `road` at `crossing`.
    `current` and `suggested` are steps (1 to 5 by halves).
    """
    if kind not in ("road", "junction"):
        raise ValueError(f"unknown suggestion kind {kind!r}")
    # OSM names are short; a cap keeps a mistagged one from crowding out the poll.
    road = _shorten(road, NAME_MAX) if road else road
    crossing = _shorten(crossing, NAME_MAX) if crossing else crossing
    if between:
        between = (_shorten(between[0] or "", NAME_MAX), _shorten(between[1] or "", NAME_MAX))
    name = road or "an unnamed road"
    calmer = suggested < current
    if kind == "road":
        stretch = f"{name}, between {between[0]} and {between[1]}" if _has(between) else name
        question = f"How comfortable is biking on {stretch}?"
        lean = (
            "A rider suggested it's calmer than we rate it."
            if calmer
            else "A rider suggested it's more stressful than we rate it."
        )
        now, then = road_words(current), road_words(suggested)
        options = road_options()
    else:
        other = crossing or "the cross street"
        question = f"Is crossing {name} at {other} harder or easier than we show?"
        lean = (
            "A rider suggested it's easier than we show."
            if calmer
            else "A rider suggested it's harder than we show."
        )
        now, then = junction_words(current), junction_words(suggested)
        options = junction_options()

    def compose(quote: str) -> str:
        lines = [
            f"**{inert(question)}**",
            inert(lean),
            "",
            f"We currently show it as: {now}",
            f"The rider suggested: {then}",
        ]
        if quote:
            lines.append(f"> {quote}")
        lines += [
            "",
            f"Where: {inert(where_words(road, between, lat, lon))}",
            f"Map: <{map_url}>",
            "",
            "Please weigh in by reacting with one letter:",
            *(f"{o.emoji} {o.label}" for o in options),
            "",
            "Votes help set how the road is shown on the bike map.",
        ]
        return "\n".join(lines)

    quote = _shorten(inert(reason), REASON_QUOTE_MAX)
    text = compose(quote)
    if len(text) > POST_MAX:
        room = max(0, len(quote) - (len(text) - POST_MAX))
        text = compose(_shorten(quote, room) if room > 20 else "")
    if len(text) > POST_MAX:
        text = _shorten(text, POST_MAX)
    return Post(text=text, options=options)


def _has(between) -> bool:
    return bool(between and all(between) and between[0] != between[1])
