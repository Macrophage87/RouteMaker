"""MORE (Mid-Atlantic Off-Road Enthusiasts) links for a mountain-bike trail's page.

OWNER-DECISIONS 454: "Link to MORE for trailheads and trail info." The owner's defaults of
2026-10-11 for the Mountain Bike ride type: "one MORE link per trail system where MORE has a
page, else one general link", and "the trail page links to MORE's conditions". MORE's trail
pages give the system's trailheads, maps, and the links its riders use for the day's
conditions (the park's own page, its Facebook group, the MORE trail liaison), so one link
serves both.

The systems and their pages are MORE's own list, https://more-mtb.org/collections/trails
(pages 1 and 2, read 2026-10-11), limited to systems inside the planner's coverage
(`settings.COVERAGE_BBOX`) or at its edge; skills parks and pump tracks are left out, as a
route does not end on one by way of its trails. A trail is matched to a system by the names
OSM gives it (the way's `name`, `mtb:name` or `ref`, `segment.mtb_name`): each system lists
the words its trails are named with. Where no name matches, the general link is given,
never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GENERAL_URL = "https://more-mtb.org/collections/trails"
GENERAL_LABEL = "MORE trail guide and conditions"
_PAGE = "https://more-mtb.org/products/"


@dataclass(frozen=True)
class System:
    name: str
    slug: str
    # Lower-case words or phrases a trail's OSM name carries in this system.
    words: tuple[str, ...]

    @property
    def url(self) -> str:
        return _PAGE + self.slug


# MORE's slug for each system, as its trail list links it (read 2026-10-11).
SYSTEMS = (
    System("Andrew Leitch Park", "andrew-leitch-park", ("andrew leitch",)),
    System("Annapolis Waterworks", "waterworks-park", ("waterworks",)),
    System("Bacon Ridge", "bacon-ridge", ("bacon ridge",)),
    System("Black Hill Regional Park", "black-hill-regional-park", ("black hill",)),
    System("Cabin John Park", "cabin-john-park", ("cabin john",)),
    System("Cedarville State Forest", "cedarville-state-forest", ("cedarville",)),
    System("Conway Robinson", "conway-robinson", ("conway robinson",)),
    System("Cosca Regional Park", "cosca-regional-park", ("cosca",)),
    System(
        "Crownsville Hospital Memorial Park", "crownsville-hospital-memorial-park", ("crownsville",)
    ),
    System("Edgar Tillett", "edgar-tillet", ("tillett",)),
    System("Fairland Recreational Park", "fairland-recreational-park", ("fairland",)),
    System("Fort Dupont - Fort Circle Parks", "fort-dupont", ("fort dupont", "fort circle")),
    System("Fountainhead Regional Park", "fountainhead-regional-park", ("fountainhead",)),
    System("Fred Crabtree", "fred-crabtree", ("crabtree",)),
    System("Frederick Watershed", "frederick-watershed", ("frederick watershed",)),
    System("Gambrill State Park", "gambrill-state-park", ("gambrill",)),
    System(
        "Gerry Connolly Cross County Trail (GCCCT)",
        "cross-county-trail-cct",
        ("cross county trail", "gerry connolly"),
    ),
    System("Gillis Falls", "gillis-falls", ("gillis falls",)),
    System("Greenbrier State Park", "greenbrier-state-park", ("greenbrier",)),
    System("Hashawha", "hashawha", ("hashawha",)),
    System("Hoyles Mill/Diabase Trail", "hoyles-mill-diabase-trail", ("hoyles mill", "diabase")),
    System("James Long Park", "james-long-park", ("james long",)),
    System("Jug Bay - Patuxent River Park", "jug-bay-patuxent-river-park", ("jug bay",)),
    System("Lake Accotink", "lake-accotink", ("accotink",)),
    System("Lake Fairfax Park", "lake-fairfax-park", ("lake fairfax",)),
    System("Laurel Hill", "laurel-hill", ("laurel hill",)),
    System("Little Bennett Regional Park", "little-bennett-regional-park", ("little bennett",)),
    System(
        "Little Gunpowder Falls State Park",
        "little-gunpowder-falls-state-park",
        ("little gunpowder",),
    ),
    System("Loch Raven", "loch-raven", ("loch raven",)),
    System("Locust Shade", "locust-shade", ("locust shade",)),
    System("Meadowood Recreation Area", "meadowood-recreation-area", ("meadowood",)),
    System("Monocacy Natural Resources Area", "monocacy-natural-resources-area", ("monocacy",)),
    System("Mount Vernon Park", "mt-vernon-park", ("mount vernon park", "mt vernon park")),
    System("Muddy Branch Park", "muddy-branch-park", ("muddy branch",)),
    System("Northwest Branch Park", "northwest-branch-park", ("northwest branch",)),
    System("Paint Branch Trail", "paint-branch", ("paint branch",)),
    System("Patapsco Valley State Park", "patapsco-valley-state-park", ("patapsco",)),
    System("Patuxent River State Park", "patuxent-river-state-park", ("patuxent river state",)),
    System("Pepco Trail", "pepco-trail", ("pepco",)),
    System("Prince William Forest Park", "prince-william-forest-park", ("prince william forest",)),
    System("Rivers Edge at Brunswick", "rivers-edge-at-brunswick", ("rivers edge",)),
    System("Rockburn Branch Park", "rockburn-branch-park", ("rockburn",)),
    System("Rosaryville State Park", "rosaryville-state-park", ("rosaryville",)),
    System("Schaeffer Farms", "schaeffer-arms", ("schaeffer farm",)),
    System("Seneca Bluffs Trail", "seneca-bluffs-trail", ("seneca bluffs",)),
    System("Seneca Greenway", "seneca-greenway", ("seneca greenway", "seneca creek greenway")),
    System("Seneca Ridge Trail (SRT)", "seneca-ridge-trail-srt", ("seneca ridge",)),
    System("Severn Run", "severn-run", ("severn run",)),
    System("Upper Rock Creek Park", "upper-rock-creek-park", ("upper rock creek",)),
    System("Wakefield Park", "wakefield-park", ("wakefield",)),
    System("Wheaton Regional Park", "wheaton-regional-park", ("wheaton",)),
    System("Windy Ridge", "windy-ridge", ("windy ridge",)),
)

_SPACE = re.compile(r"[^a-z0-9]+")


def _normal(text: str) -> str:
    return " " + _SPACE.sub(" ", text.lower()).strip() + " "


def system_for(*names: str | None) -> System | None:
    """The MORE system a trail's names place it in: the first system whose words appear, as
    whole words, in any of the names; None where none does. The longest match wins, so
    "Seneca Ridge" is never read as a shorter system's word."""
    texts = [_normal(n) for n in names if n and n.strip()]
    found: tuple[int, System] | None = None
    for system in SYSTEMS:
        for word in system.words:
            needle = _normal(word)
            if any(needle in text for text in texts) and (found is None or len(word) > found[0]):
                found = (len(word), system)
    return found[1] if found else None


def link_for(*names: str | None) -> dict:
    """The link the trail page gives: `{"label", "url", "system"}`, the system's MORE page
    where its names place it, else MORE's trail guide (`system` null)."""
    system = system_for(*names)
    if system is None:
        return {"label": GENERAL_LABEL, "url": GENERAL_URL, "system": None}
    return {
        "label": f"{system.name} on MORE: trailheads, trail info and conditions",
        "url": system.url,
        "system": system.name,
    }
