"""The language the route's words are written in (the owner, 2026-10-27: Spanish, "yes. build
that"). English is the source, as in the app (frontend/src/lib/i18n.ts): each sentence is
written in English and passed through `t`, which looks it up in the language's list
(`routemaker.lang_es`) and falls back to the English where a phrase has none. Street, trail
and place names are never translated; neither are the API's data fields (`street`, `onto`,
`cross`), which the app reads as names.

The language is the request's (`core.api` RouteIn.lang), held for the plan in a context
variable, which `core.parallel.submit` carries into the router's threads.
"""

from __future__ import annotations

import contextvars
import importlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache

from routemaker.lang_es import ES

# DC's languages (the owner, 2026-10-28, the city's Language ID poster), as the app names them
# (frontend/src/lib/i18n.ts LANGUAGES): Spanish in the whole app, the rest in Go and Ride. Mandarin
# ("zh") in Simplified characters, Cantonese ("yue") in Traditional.
LANGUAGES = (
    "en", "es", "am", "ar", "bn", "yue", "fa", "fr", "ht", "hi", "id",
    "ja", "ko", "zh", "ps", "pt", "ru", "th", "ti", "tr", "vi",
)  # fmt: skip


@cache
def catalog(lang: str) -> dict[str, str]:
    """A language's phrases (`routemaker.lang_<lang>`, CATALOG; Spanish's is ES), empty for
    English or a language with none yet: its sentences are then the English."""
    if lang == "es":
        return ES
    if lang not in LANGUAGES or lang == "en":
        return {}
    try:
        module = importlib.import_module(f"routemaker.lang_{lang}")
    except ModuleNotFoundError:
        return {}
    return dict(module.CATALOG)


_current: contextvars.ContextVar[str] = contextvars.ContextVar("route_language", default="en")


def language() -> str:
    """The language in force: "en" unless a request asked for another."""
    return _current.get()


@contextmanager
def speaking(lang: str | None) -> Iterator[None]:
    """The route's words in `lang` within the block; English for anything not in LANGUAGES or
    with no catalog yet."""
    # A language with no catalog yet is answered wholly in English, never half (an ordinal or a
    # way's words worded for a sentence that stays English).
    token = _current.set(lang if lang in LANGUAGES and (lang == "en" or catalog(lang)) else "en")
    try:
        yield
    finally:
        _current.reset(token)


_PLACE = re.compile(r"\{(\w+)\}")


def t(english: str, **places: object) -> str:
    """A phrase in the language in force, from its English, its {places} filled after the
    lookup so a translation can put them where its grammar wants them."""
    text = catalog(language()).get(english, english)
    if not places:
        return text
    return _PLACE.sub(lambda m: str(places[m[1]]) if m[1] in places else m[0], text)


def spanish() -> bool:
    return language() == "es"


def english() -> bool:
    return language() == "en"


# The API's names for a way by what it is ("service road beside East-West Highway"), as a
# Spanish sentence says them; the app's wayWords does the same (frontend/src/lib/navigate.ts).
_WAY_ES = (
    (re.compile(r"^path\b"), "el sendero"),
    (re.compile(r"^sidewalk\b"), "la acera"),
    (re.compile(r"^service road\b"), "la vía de servicio"),
    (re.compile(r"^alley\b"), "el callejón"),
    (re.compile(r"^parking aisle\b"), "el pasillo del estacionamiento"),
    (re.compile(r"^unnamed road\b"), "una calle sin nombre"),
    (re.compile(r"^an unnamed road\b"), "una calle sin nombre"),
    (re.compile(r"^the road\b"), "la calle"),
    (re.compile(r"^this part of the route\b"), "esta parte de la ruta"),
    # An unnamed lane named after its street at the rebuild (facility.sidepath_name,
    # "9th Street Northwest protected bike lane"), the protected one first (round-2
    # audit D16): the facility words lang_es already uses, the street as it is.
    (re.compile(r"^(.+) protected bike lane$"), r"el carril bici protegido de \1"),
    (re.compile(r"^(.+) bike lane$"), r"el carril bici de \1"),
)


def way_es(street: str) -> str | None:
    """A way the API names by what it is, in Spanish with its article; None for a real name."""
    for head, words in _WAY_ES:
        if head.match(street):
            return head.sub(words, street, count=1).replace(" beside ", " junto a ")
    return None


_COMMON_WAY = re.compile(r"^(path|sidewalk|service road|alley|parking aisle)\b(?: beside (.+))?")
_LANE = re.compile(r"^(.+) (protected )?bike lane$")


def way_said(street: str) -> str | None:
    """A way the API names by what it is, in the language in force (Spanish by its own
    rules above, the rest by their catalogs, as the app's wayWordsOther); None for a
    real name, and in English."""
    if english():
        return None
    if spanish():
        return way_es(street)
    if street in ("the road", "unnamed road", "an unnamed road"):
        return t("the road")
    lane = _LANE.match(street)
    if lane:
        phrase = "the protected bike lane on {street}" if lane[2] else "the bike lane on {street}"
        return t(phrase, street=lane[1])
    kind = _COMMON_WAY.match(street)
    if not kind:
        return None
    words = {
        "path": t("the path"),
        "sidewalk": t("the sidewalk"),
        "service road": t("the service road"),
        "alley": t("the alley"),
        "parking aisle": t("the parking aisle"),
    }[kind[1]]
    return t("{way} beside {road}", way=words, road=kind[2]) if kind[2] else words
