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
import re
from collections.abc import Iterator
from contextlib import contextmanager

from routemaker.lang_es import ES

LANGUAGES = ("en", "es")
_CATALOGS: dict[str, dict[str, str]] = {"es": ES}

_current: contextvars.ContextVar[str] = contextvars.ContextVar("route_language", default="en")


def language() -> str:
    """The language in force: "en" unless a request asked for another."""
    return _current.get()


@contextmanager
def speaking(lang: str | None) -> Iterator[None]:
    """The route's words in `lang` within the block; English for anything not in LANGUAGES."""
    token = _current.set(lang if lang in LANGUAGES else "en")
    try:
        yield
    finally:
        _current.reset(token)


_PLACE = re.compile(r"\{(\w+)\}")


def t(english: str, **places: object) -> str:
    """A phrase in the language in force, from its English, its {places} filled after the
    lookup so a translation can put them where its grammar wants them."""
    catalog = _CATALOGS.get(language())
    text = catalog.get(english, english) if catalog else english
    if not places:
        return text
    return _PLACE.sub(lambda m: str(places[m[1]]) if m[1] in places else m[0], text)


def spanish() -> bool:
    return language() == "es"


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
)


def way_es(street: str) -> str | None:
    """A way the API names by what it is, in Spanish with its article; None for a real name."""
    for head, words in _WAY_ES:
        if head.match(street):
            return head.sub(words, street, count=1).replace(" beside ", " junto a ")
    return None
