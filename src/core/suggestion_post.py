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
reason is quoted, with mentions, links and markdown made inert. Nor is the spot the rider
clicked: the place is the road and its cross streets in words, and the map link (made by the
caller) points at the road piece's middle. The post is at most `POST_MAX` characters (Discord's
limit for one message); the reason is shortened first to fit.
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

# One plain label per whole level: new plain-English labels written for the poll under the
# owner's 14:08 request ("Not everyone is familiar with that scale, so give a plain english
# request"), not 441l's step words (those stay the map's and the panel's).
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
    # The whole tier a vote for it means; None for "Not sure" (and on a hazard's poll).
    tier: int | None
    # A hazard poll's (`build_hazard`): the level a vote for it means, "none" for no mark,
    # None for "Not sure"; None on a level poll.
    level: str | None = None


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
# A zero-width space: after @ it keeps @everyone, @here and @name from pinging anyone.
_ZWSP = "\u200b"
# Markdown that would change the post around a rider's words: emphasis, code, spoilers and
# masked links ([text](url)); a backslash first, so the escapes added are not escaped again.
_MARKS = ("\\", "*", "_", "~", "`", "|", "[", "]", "(", ")")
# Line starts Discord reads as a heading, subtext or quote.
_LINE_STARTS = ("#", "-#", ">")


def inert(text: str) -> str:
    """A rider's words safe to paste: one paragraph, no mention, no role ping, no embed,
    no markdown that would change the post around it."""
    text = " ".join((text or "").split())
    text = _MENTION.sub("mention removed", text)
    text = text.replace("@", "@" + _ZWSP)
    parts = _URL.split(text)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            # <link> shows a link without the preview card.
            out.append(f"<{part.rstrip('>')}>")
            continue
        for mark in _MARKS:
            part = part.replace(mark, "\\" + mark)
        out.append(part)
    text = "".join(out)
    if text.startswith(_LINE_STARTS):
        text = "\\" + text
    return text


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def where_words(road: str | None, between: tuple[str, str] | None) -> str:
    """The plain-text location: the road and its cross streets where known. Never coordinates:
    the map link shows the road."""
    name = road or "An unnamed road"
    if between and all(between) and between[0] != between[1]:
        return f"{name} between {between[0]} and {between[1]}"
    return f"{name}, shown on the map link below"


def junction_where(road: str | None, crossing: str | None) -> str:
    """A junction in words: its two roads where known. Never coordinates."""
    if road and crossing and road != crossing:
        return f"{road} at {crossing}"
    if road:
        return f"A junction on {road}, shown on the map link below"
    return "A junction shown on the map link below"


def build(
    *,
    kind: str,
    road: str | None,
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
        question = (
            f"Is crossing {name} at {other} harder or easier than we show?"
            if road
            else "Is this junction harder or easier to get through than we show?"
        )
        lean = (
            "A rider suggested it's easier than we show."
            if calmer
            else "A rider suggested it's harder than we show."
        )
        now, then = junction_words(current), junction_words(suggested)
        options = junction_options()

    if kind == "road":
        place, thing = where_words(road, between), "road"
    else:
        place, thing = junction_where(road, crossing), "junction"

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
            f"Where: {inert(place)}",
            f"Map: <{map_url}>",
            "",
            "Please weigh in by reacting with one letter:",
            *(f"{o.emoji} {o.label}" for o in options),
            "",
            f"Votes help set how the {thing} is shown on the bike map.",
        ]
        return "\n".join(lines)

    # Shortened as the rider wrote it, then made inert, so a cut never splits an escape.
    raw = " ".join((reason or "").split())
    limit = REASON_QUOTE_MAX
    text = compose(inert(_shorten(raw, limit)) if raw else "")
    while len(text) > POST_MAX and limit > 20:
        limit = max(20, limit - (len(text) - POST_MAX) - 1)
        text = compose(inert(_shorten(raw, limit)))
    if len(text) > POST_MAX:
        text = compose("")
    if len(text) > POST_MAX:
        text = _shorten(text, POST_MAX)
    return Post(text=text, options=options)


def _has(between) -> bool:
    return bool(between and all(between) and between[0] != between[1])


# A Mass Ride hazard's poll (FOLLOWUP-MASSRIDE-MAP part 3; OWNER-DECISIONS 325, 326): the two
# levels in plain words, strongest first, then no mark. Written for the poll, like ROAD_WORDS:
# "Not everyone is familiar with that scale" holds for Caution and Warning too.
HAZARD_WORDS = {
    "warning": "Warning: a big group has had real trouble here",
    "caution": "Caution: a big group should take care here",
}
HAZARD_NONE = "No mark needed"


def hazard_options() -> tuple[PollOption, ...]:
    levels = [*HAZARD_WORDS.items(), ("none", HAZARD_NONE)]
    out = [
        PollOption(c, _EMOJI[c], label, None, level)
        for c, (level, label) in zip(_LETTERS, levels, strict=False)
    ]
    c = _LETTERS[len(out)]
    out.append(PollOption(c, _EMOJI[c], NOT_SURE, None, None))
    return tuple(out)


def level_for_vote(options: tuple[PollOption, ...], letter: str) -> str | None:
    """The hazard level a reaction stands for ("none": no mark; None: not sure, or no such
    letter)."""
    for option in options:
        if option.letter == letter.strip().upper():
            return option.level
    return None


def build_hazard(
    *,
    road: str | None,
    level: str,
    reason: str,
    map_url: str,
    between: tuple[str, str] | None = None,
) -> Post:
    """The poll for a rider's Mass Ride hazard report, at most POST_MAX characters.

    The same rules as `build`: no name, account or id of the rider, no spot they clicked (the
    road and its cross streets in words, the link at the road piece's middle), mentions and
    markdown in the reason made inert, plain words for the levels.
    """
    if level not in HAZARD_WORDS:
        raise ValueError(f"unknown hazard level {level!r}")
    road = _shorten(road, NAME_MAX) if road else road
    if between:
        between = (_shorten(between[0] or "", NAME_MAX), _shorten(between[1] or "", NAME_MAX))
    name = road or "an unnamed road"
    stretch = f"{name}, between {between[0]} and {between[1]}" if _has(between) else name
    question = f"Should the Mass Ride map warn big group rides about {stretch}?"
    asked = HAZARD_WORDS[level].split(":")[0]
    options = hazard_options()

    def compose(quote: str) -> str:
        lines = [
            f"**{inert(question)}**",
            f'A rider asked us to mark it "{asked}" for mass rides.',
            "",
            f"The rider suggested: {HAZARD_WORDS[level]}",
        ]
        if quote:
            lines.append(f"> {quote}")
        lines += [
            "",
            f"Where: {inert(where_words(road, between))}",
            f"Map: <{map_url}>",
            "",
            "Please weigh in by reacting with one letter:",
            *(f"{o.emoji} {o.label}" for o in options),
            "",
            "Votes help decide what the Mass Ride map shows. Either way, rides can still use "
            "the road.",
        ]
        return "\n".join(lines)

    return Post(text=_fit(compose, reason), options=options)


def _fit(compose, reason: str) -> str:
    """The post with the reason quoted, shortened (as the rider wrote it, then made inert, so
    a cut never splits an escape) until the post fits POST_MAX."""
    raw = " ".join((reason or "").split())
    limit = REASON_QUOTE_MAX
    text = compose(inert(_shorten(raw, limit)) if raw else "")
    while len(text) > POST_MAX and limit > 20:
        limit = max(20, limit - (len(text) - POST_MAX) - 1)
        text = compose(inert(_shorten(raw, limit)))
    if len(text) > POST_MAX:
        text = compose("")
    if len(text) > POST_MAX:
        text = _shorten(text, POST_MAX)
    return text
