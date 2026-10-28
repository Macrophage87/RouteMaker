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
    "core/transit.py",
    "core/bikeshare.py",
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
    with lang.speaking("xx"):
        assert lang.language() == "en"
    # A language the app has but this server has no sentences for yet: wholly English.
    with lang.speaking("am"):
        assert not lang.catalog("am")
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

    assert RouteIn._known_language("de") == "en"
    # French is one of Go and Ride's languages, but the server has no catalog for it (only lang_es.py): English.
    assert RouteIn._known_language("fr") == "en"
    assert RouteIn._known_language("es") == "es"


class TestBikeLaneNames:
    """Round-2 audit D16: a lane named after its street at the rebuild says its facility
    in Spanish, the street as it is; English as it was."""

    def test_the_way_name_in_spanish(self):
        assert (
            lang.way_es("9th Street Northwest protected bike lane")
            == "el carril bici protegido de 9th Street Northwest"
        )
        assert lang.way_es("Saint Paul Street bike lane") == "el carril bici de Saint Paul Street"
        assert (
            lang.way_es("path beside Saint Paul Street") == "el sendero junto a Saint Paul Street"
        )
        assert lang.way_es("Saint Paul Street") is None

    def test_a_turn_onto_one(self):
        with lang.speaking("es"):
            assert (
                d._in_sentence("9th Street Northwest protected bike lane")
                == "el carril bici protegido de 9th Street Northwest"
            )
        assert (
            d._in_sentence("9th Street Northwest protected bike lane")
            == "9th Street Northwest protected bike lane"
        )

    def test_the_app_has_the_same_rules(self):
        """The app's wayWords (frontend/src/lib/navigate.ts WAY_ES) words a way as the API
        does: each of its rules is one of the API's."""
        source = (SRC.parent / "frontend/src/lib/navigate.ts").read_text()
        table = source.split("const WAY_ES", 1)[1].split("];", 1)[0]
        rules = re.findall(r'\[/(.+?)/, "(.+?)"\]', table)
        assert len(rules) >= 7
        api = {(head.pattern, words.replace("\\1", "$1")) for head, words in lang._WAY_ES}
        for rule in rules:
            assert rule in api, rule


class TestTransitAndBikeshareSteps:
    """A transit or Bikeshare plan's steps in Spanish (routing audit D30): whole Spanish
    sentences, the line, stop and dock names as they are, miles first; English as it was."""

    def test_transit_steps(self):
        from core import transit

        marc = transit.Leg(
            "rail",
            2700.0,
            to="Baltimore Penn Station",
            wait_s=1200.0,
            vehicle="the MARC Penn Line",
            depart=420.0,
            after=480.0,
            board_at="Union Station MARC",
        )
        metro = transit.Leg(
            "metro",
            600.0,
            to="Federal Triangle",
            wait_s=240.0,
            vehicle="the Orange Line",
            every=8.0,
        )
        bus = transit.Leg("bus", 900.0, bike=True, vehicle="bus B10", wait_s=300.0)
        english = marc.words()
        assert english == (
            "Board the MARC Penn Line at 7:00 am scheduled from Union Station MARC: you arrive"
            " 6:40 am, 20 min spare; next train after that: 8:00 am scheduled. Ride 45 min to"
            " Baltimore Penn Station."
        )
        with lang.speaking("es"):
            assert marc.words() == (
                "Suba al tren MARC Penn Line, sale 7:00 am según horario desde Union Station"
                " MARC: llegada 6:40 am, 20 min de margen; siguiente tren: 8:00 am según horario."
                " Viaje 45 min hasta Baltimore Penn Station."
            )
            assert metro.words() == (
                "Suba al tren Orange Line (cada 8 min, según horario; unos 4 min de espera);"
                " viaje 10 min hasta Federal Triangle."
            )
            assert bus.words() == (
                "Ponga su bicicleta en el portabicicletas delantero del autobús B10 (unos 5 min"
                " de espera, según horario); viaje 15 min."
            )
            assert transit.Leg(transit.RIDE, 300.0).words(last=True) == (
                "Vaya en bicicleta 5 min hasta su destino."
            )
            assert transit.Leg(transit.ENTER, 120.0, bike=True).words() == (
                "Unos 2 min para entrar a la estación, por el ascensor."
            )
            assert transit.Leg(transit.TAKE, 300.0, to="4th & E St NW").words() == (
                "Camine 5 min hasta la estación de bicicletas compartidas 4th & E St NW y tome"
                " una bicicleta clásica."
            )
        assert marc.words() == english

    def test_the_app_takes_out_the_arrival_clause_in_both_languages(self):
        """The app's withoutSpare (frontend/src/lib/rideTrip.ts) finds the clause the API
        writes: ": you arrive " in English, ": llegada " in Spanish."""
        source = (SRC.parent / "frontend/src/lib/rideTrip.ts").read_text()
        assert "/: (?:you arrive|llegada) [^;]*; (\\w)/" in source
        assert ES["{head}: you arrive {time}, {spare} min spare; {after}. {ride}."].startswith(
            "{head}: llegada {time}, "
        )

    def test_bikeshare_steps(self):
        from core import bikeshare

        class Status:
            classic = 5
            docks = 1

            def bikes_of(self, bike):
                return self.classic

        start = bikeshare.Pick("dock", "4th & E St NW", 0.0, 0.0, status=Status())
        end = bikeshare.Pick("dock", "Union Station", 0.0, 0.0, status=Status())
        walk = bikeshare.WalkLeg([], 400.0, 300.0)
        english = bikeshare._start_step(start, "classic", walk, None)
        assert english == (
            "Walk 0.2 mi (0.4 km) to the dock at 4th & E St NW, take a classic bike (5 available)."
        )
        with lang.speaking("es"):
            assert bikeshare._start_step(start, "classic", walk, None) == (
                "Camine 0.2 mi (0.4 km) hasta la estación 4th & E St NW, tome una bicicleta"
                " clásica (5 disponibles)."
            )
            ride = bikeshare._end_step(end, 3000.0, "classic")
            assert ride == (
                "Vaya en bicicleta 1.9 mi (3.0 km) hasta la estación Union Station"
                " (1 espacio libre)."
            )
            # The way round an Avoid-rated junction rewrites the Spanish ride and summary too.
            block = {
                "ride_m": 3000.0, "ride_s": 900.0, "walk_s": 300.0, "total_s": 1200.0,
                "steps": [{"kind": "ride", "text": ride}],
                "summary": f"Bikeshare, bicicleta clásica: unos 20 min en total. {ride}",
                "notes": [],
            }  # fmt: skip
            out = bikeshare.alternate_block(block, {"distance_m": 4000.0, "duration_s": 1500.0})
            assert out["steps"][0]["text"].startswith("Vaya en bicicleta 2.5 mi (4.0 km) hasta")
            assert out["summary"].startswith("Bikeshare, bicicleta clásica: unos 30 min en total.")
            assert out["steps"][0]["text"] in out["summary"]


def test_dcs_languages_match_the_apps():
    """The server words the languages the app offers (frontend/src/lib/i18n.ts LANGUAGES),
    each catalog keeping its English's {places}."""
    app = (SRC.parent / "frontend/src/lib/i18n.ts").read_text()
    listed = re.search(r"export const LANGUAGES = \[(.*?)\] as const", app, re.S)
    assert listed
    assert tuple(re.findall(r'"(\w+)"', listed[1])) == lang.LANGUAGES
    for code in lang.LANGUAGES:
        for english, text in lang.catalog(code).items():
            assert sorted(_PLACE.findall(text)) == sorted(_PLACE.findall(english)), (code, english)


def test_a_way_by_what_it_is_in_another_language(monkeypatch):
    """The API's way words through the language's catalog; a real name as it is."""
    fake = {"the path": "le sentier", "{way} beside {road}": "{way} le long de {road}"}
    monkeypatch.setattr(lang, "catalog", lambda code: fake if code == "fr" else {})
    with lang.speaking("fr"):
        said = lang.way_said("path beside East-West Highway")
        assert said == "le sentier le long de East-West Highway"
        assert lang.way_said("path") == "le sentier"
        assert lang.way_said("R Street Northwest") is None
        assert d.ordinal(3) == "3"
    with lang.speaking("en"):
        assert lang.way_said("path") is None
    # A language with no sentences yet is English throughout: "3rd", never a bare "3".
    with lang.speaking("am"):
        assert lang.language() == "en"
        assert d.ordinal(3) == "3rd"
