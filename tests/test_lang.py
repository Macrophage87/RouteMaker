"""The route's words in Spanish (`routemaker.lang`): every phrase the code passes has its
Spanish with the same {places}, a Spanish route reads in Spanish, and English is as it was."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from core import route_hazards, workzones
from routemaker import avoid_junctions, hazards, lang, steep_grades
from routemaker import describe as d
from routemaker.intersections import Control, Event, Movement
from routemaker.lang_es import ES

SRC = Path(__file__).resolve().parents[1] / "src"
# The modules whose sentences go through lang.t.
WORDED = [
    "routemaker/describe.py",
    "routemaker/steep_grades.py",
    "routemaker/avoid_junctions.py",
    "routemaker/workzones.py",
    "core/route_hazards.py",
    "core/hillseek.py",
    "core/novice_walks.py",
    "core/workzones.py",
]
_PLACE = re.compile(r"\{(\w+)\}")


def literal_keys() -> set[str]:
    """Every t("...") whose English is written out (implicit concatenations joined)."""
    keys = set()
    for name in WORDED:
        for node in ast.walk(ast.parse((SRC / name).read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
    return keys


def built_keys() -> set[str]:
    """The phrases the code builds from its word lists, as it builds them."""
    keys = set()
    for table in (d._ONTO, d._STAY, d._THEN_ONTO, d._ON):
        keys |= set(table.values())
    keys |= {f"{verb} {{what}}" for verb in d._POINT_VERBS.values()}
    keys.add(f"{d._POINT_OTHER} {{what}}")
    for words in d.SEVERITY_WORDS.values():
        keys |= {f" ({words} junction)", f" ({words} junctions)"}
    keys |= set(d.TIER_WORDS.values()) | {d.UNRATED_WORDS, d.PATH_WORDS}
    keys |= set(d.FACILITY_WORDS.values()) | {d.SURFACE_UNPAVED, d.SURFACE_PARTLY}
    keys |= set(d.CONTROL_PHRASES.values())
    keys.add(f"{{count}} {d.GROUP_NOUN}")
    keys |= {
        f", 1 of them a {d.LTS4_ROAD}",
        f", all of them {d.LTS4_ROADS}",
        f", {{count}} of them {d.LTS4_ROADS}",
        f"no street details for this part of the route, {d.UNRATED_WORDS}.",
    }
    keys.add(route_hazards.road_of(None))
    keys |= {workzones.STALE_NOTE, workzones.BYPASS_NOTE, workzones.MAY_APPLY_NOTE}
    keys.add(workzones.rules.DISCLAIMER)
    keys |= set(route_hazards.SHORT_WORDS.values())
    keys |= {w.split(": ", 1)[1] for w in hazards.WORDS.values()}
    keys |= set(steep_grades._STEEP_WORDS.values())
    keys |= {f"{avoid_junctions.NOUN} ahead at {{where}}", avoid_junctions.PLEA}
    return keys


def test_the_code_passes_phrases():
    # The scan finds what it should: guards against it silently finding nothing.
    assert "Continue onto {street}" in literal_keys()
    assert "Left onto {street}" in built_keys()


@pytest.mark.parametrize("english", sorted(literal_keys() | built_keys()))
def test_every_phrase_has_its_spanish(english):
    assert english in ES, f"no Spanish for {english!r}"


@pytest.mark.parametrize("english", sorted(ES))
def test_the_spanish_has_the_same_places(english):
    assert sorted(_PLACE.findall(ES[english])) == sorted(_PLACE.findall(english))


def test_no_phrase_is_left_over():
    # A phrase the code no longer passes is dead weight a reviewer would still read.
    assert set(ES) <= literal_keys() | built_keys()


def test_english_unless_asked():
    assert lang.language() == "en"
    assert lang.t("Continue onto {street}", street="B") == "Continue onto B"
    with lang.speaking("fr"):
        assert lang.language() == "en"
    with lang.speaking("es"):
        assert lang.t("Continue onto {street}", street="B") == "Continúe por B"
        assert lang.t("not in the list") == "not in the list"
    assert lang.language() == "en"


def road(name, tier, metres, heading, facility="none", use="road"):
    count = max(1, round(metres / 60))
    names = (name,) if name else ()
    return [
        d.Atom(metres / count, str(tier), facility, names, use, heading, heading)
        for _ in range(count)
    ]


def legs():
    return [
        [
            *road("Capital Crescent Trail", 1, 1931, 90, facility="path", use="cycleway"),
            *road("Bethesda Avenue", 3, 480, 0),
            *road("Willow Lane", 1, 800, 90),
            *road("Woodmont Avenue", 2, 600, 90, facility="lane"),
        ]
    ]


def signal(m):
    return Event(
        m=m,
        lon=-77.0,
        lat=38.9,
        kind="left_onto",
        movement=Movement("left"),
        control=Control.SIGNAL,
        cost_ft=1000.0,
        severity="orange",
        reason="x",
        crossed_tier=3,
        flagged=True,
        road_names=frozenset({"bethesda avenue"}),
    )


def texts(entries):
    return [e["text"] for e in entries]


class TestARoute:
    def test_spanish(self):
        with lang.speaking("es"):
            said = texts(d.describe(legs(), [signal(1931)]))
        assert said[1] == (
            "1.2 a 1.5 mi (1.9 a 2.4 km): Gire a la izquierda hacia Bethesda Avenue en un"
            " semáforo (intersección de estrés más alto), calle con mucho tráfico (LTS 3)."
        )
        assert said[2].endswith(": Gire a la derecha hacia Willow Lane, estrés bajo (LTS 1).")
        assert "carril bici pintado" in said[3]
        # Names stay as written.
        assert "Capital Crescent Trail" in said[0]

    def test_english_as_it_was(self):
        said = texts(d.describe(legs(), [signal(1931)]))
        assert said[1] == (
            "1.2 to 1.5 mi (1.9 to 2.4 km): Left onto Bethesda Avenue at a signal (Higher"
            " stress junction), busy road (LTS 3)."
        )

    def test_the_data_stays_english(self):
        # The app reads street and turn fields as names and codes, never as sentences.
        with lang.speaking("es"):
            spanish = d.describe(legs(), [signal(1931)])
        english = d.describe(legs(), [signal(1931)])
        for es, en in zip(spanish, english, strict=True):
            assert {k: v for k, v in es.items() if not k.startswith("text")} == {
                k: v for k, v in en.items() if not k.startswith("text")
            }


class TestHazards:
    entry = {
        "from_m": 1931,
        "to_m": 2300,
        "kinds": [hazards.COBBLES, hazards.RAILS],
        "road": "O Street",
    }

    def test_spanish(self):
        with lang.speaking("es"):
            said = route_hazards.line(self.entry)
        assert said.startswith("Adoquines y rieles en la calle en O Street, 1.2 a 1.4 mi")

    def test_english_as_it_was(self):
        assert route_hazards.line(self.entry).startswith(
            "Cobblestones and rails in the road on O Street, 1.2 to 1.4 mi"
        )


class TestWorkZones:
    def zone(self):
        import json

        from routemaker import workzones as wz

        sample = Path(__file__).resolve().parent / "data" / "workzones" / "wzdx-v4-sample.geojson"
        found = wz.parse_feed(json.loads(sample.read_text()), "md")
        return wz, next(z for z in found if z.zone_id == "md-wz-closed-unknown")

    def test_the_citation_and_its_date_in_spanish(self):
        wz, zone = self.zone()
        with lang.speaking("es"):
            assert wz.citation(zone).startswith("Fuente: Maryland DOT SHA work zones")
            assert wz.citation(zone).endswith(", hasta el 30 de nov.")

    def test_the_cards_dates_stay_english(self):
        # Only the citation is worded in Spanish; the closure cards' when-words are not.
        wz, zone = self.zone()
        with lang.speaking("es"):
            assert wz.date_text(zone.end) == "Nov 30"

    def test_the_unread_feeds(self):
        from core import workzones

        with lang.speaking("es"):
            said = workzones.unchecked_text({"md": workzones.UNAVAILABLE})
        assert said == (
            "No se pudieron revisar las zonas de obras de esta ruta: Maryland's feed no disponible."
        )


def test_a_named_climb_reads_as_a_sentence_in_spanish():
    from core import hillseek

    climb = hillseek.Climb("x", "4", 1287.0, 80.0, 5.0, ((0, 0), (0, 0.01)), name="Snider Lane")
    with lang.speaking("es"):
        said = hillseek.sentence(hillseek.Ridden(climb, 5150.0, 6437.0))
    assert ": Snider Lane, subida de categoría 4, " in said
    assert said.startswith("En 3.2 mi (5.2 km)")
    assert ": Snider Lane, Category 4 climb, " in hillseek.sentence(
        hillseek.Ridden(climb, 5150.0, 6437.0)
    )


def test_a_pool_thread_speaks_the_requests_language(settings):
    from core import parallel

    settings.ROUTER_PARALLEL_CALLS = 2
    with lang.speaking("es"):
        assert parallel.submit(lang.language).result(timeout=10) == "es"
    assert parallel.submit(lang.language).result(timeout=10) == "en"


def test_a_language_the_server_does_not_word_is_english():
    from core.api import RouteIn

    assert RouteIn._known_language("fr") == "en"
    assert RouteIn._known_language("es") == "es"
