"""The public data download: what each row says, and what the licences keep out of it.

The owner, 2026-11-05: "In our documentation is it possible to offer a link to download all
of our data in common formats that could be readable by gis and the like?", then, of where
the files live, "GitHub Releases" (one data release per map rebuild), and of every source
without a licence that lets us pass it on: "For anything we don't hava license on, just link
to it." `core.open_data_export` reads the live map tables and writes the files; this module
is the part with no database in it, so every licence rule below is tested on plain rows.

The download is an ODbL derivative database (PLAN.md, "Licensing"): it is built on
OpenStreetMap, so it goes out under ODbL 1.0 with the credits of every other source in it.

Every level is RouteMaker's own, as the map shows it. The owner, 2026-11-05: "For Maryland,
we have used our ratings and only consulted the state numbers for agreement. There's only
additional scrutiny if there's disagreement. We can cite all these agency data as fair use.",
then "In our why's" and "Same with arlington". So an agency's figures reach the download
only as the map's "Why" notes cite them, as written; no column carries a source we have no
licence for. Kept out of the columns, and linked instead (`LINKED_NOT_INCLUDED`):

- **Maryland's state layers**: MDOT SHA's traffic counts (`aadt` is blank where the count
  held is Maryland's, and `md_count_linked` says so), its Bicycle LTS (no column, as
  Montgomery's and DDOT's have) and its scenic byway names (left out of `scenic`).
- **Arlington County's Bike Comfort Index**: cited in the Why notes only.
- **Capital Bikeshare** trip data (its licence agreement forbids handing it on as a
  dataset): the modelled trips and the popular-corridor class are not exported.
- Live closure feeds, which change by the hour; the app is the place for those.

Nothing here reads a ride, a rider or the server: the inputs are segment rows and the
rack file, and `core.open_data_export` reads nothing else.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from . import agency_lts

# A level as a number a GIS can colour by: 1 to 4.5 in half steps, and 5 for Avoid.
AVOID_LEVEL = 5.0

# The agency whose layers stay out until Maryland's waiver (PLAN.md, "Licensing").
MARYLAND = "mdot-sha"

# The open agencies whose own levels the download carries beside ours.
AGENCY_COLUMNS = {"moco": "moco_lts", "ddot": "ddot_lts"}

# How `rated_by` names who set a way's level.
RATED_BY_WORDS = {
    agency_lts.OWNER: "owner (reviewed)",
    agency_lts.COMMUNITY: "community (reviewed)",
    agency_lts.FORMULA_USED: "formula",
    "rural floor": "formula, rural floor",
    "service road": "formula, service-road step",
    agency_lts.PAINTED_LANE_USED: "formula, painted-lane rule",
}
# Maryland's layer is consulted for agreement, never taken as the method (the owner,
# 2026-11-05: "if our methodology agrees with MD SHA, we state our methodology and that it's
# in agreement"). Our formula's level is given beside the level (`formula_lts`).
MD_AGREES = "formula, in agreement with MDOT SHA"
MD_DIFFERS = "formula; MDOT SHA differs"
MD_CHECKED = "RouteMaker, checked against MDOT SHA"


def level_of(tier: int | None, half: bool | None) -> float | None:
    """A tier and its half flag as one number: 2 and True is 2.5; 5 is Avoid."""
    if tier is None:
        return None
    return float(tier) + (0.5 if half and tier < 5 else 0.0)


def level_text(level: float | None) -> str:
    """'LTS 2.5', 'Avoid', or '' where there is no level."""
    if level is None:
        return ""
    if level >= AVOID_LEVEL:
        return "Avoid"
    return f"LTS {level:g}"


def public_note(note: str | None, display: str | None) -> str | None:
    """The approved "Why" note the map shows on a click, as written (its citations of an
    agency's figures included: the owner, 2026-11-05). A note meant only for a route's
    summary (`route_only`) stays there."""
    if not note or display != "map":
        return None
    return note


def open_scenic(text: str | None) -> str | None:
    """The scenic designations without Maryland's byway names (`routemaker.scenic`: every
    "... Byway" is MDOT SHA's)."""
    if not text:
        return None
    kept = [part for part in text.split(" · ") if not part.rstrip().endswith("Byway")]
    return " · ".join(kept) or None


def formula_level(row: Mapping) -> float | None:
    """Our formula's own level for the way, before any agency's rating or reviewed row: the
    classifier's tier as `stress_ratings` records it, else as the reviewed row records it
    (`stress_computed_tier`), else the level itself (nothing replaced the formula's)."""
    ratings = row.get("stress_ratings")
    if isinstance(ratings, Mapping) and ratings.get("formula") is not None:
        return level_of(ratings["formula"], ratings.get("formula_half"))
    if row.get("stress_adjustment_id"):
        return level_of(row.get("stress_computed_tier"), False)
    return level_of(row.get("stress_tier"), row.get("stress_half"))


def maryland_used(row: Mapping) -> bool:
    """Whether the map's level on the way is MDOT SHA's (its rating chosen, or a row of its
    loaded as an override), with no owner's or community row over it."""
    ratings = row.get("stress_ratings") or {}
    used = ratings.get("used") if isinstance(ratings, Mapping) else None
    adjustment = row.get("stress_adjustment_id")
    source = agency_lts.adjustment_source(adjustment) if adjustment else used
    return source == MARYLAND


def download_level(row: Mapping) -> float | None:
    """The level the download gives the way: the map's, except where the map's is MDOT
    SHA's, where it is ours, the formula's with the owner's rules (the owner, 2026-11-05:
    "we have used our ratings and only consulted the state numbers for agreement")."""
    if maryland_used(row):
        formula = formula_level(row)
        if formula is not None:
            return formula
    return level_of(row.get("stress_tier"), row.get("stress_half"))


def rated_by(row: Mapping) -> str:
    """Who set the download's level, in words: an owner's or the community's reviewed row,
    a county's or the District's rating, the formula and its owner rules, and, where MDOT
    SHA rates the way too, whether our formula agrees with it."""
    ratings = row.get("stress_ratings") or {}
    used = ratings.get("used") if isinstance(ratings, Mapping) else None
    adjustment = row.get("stress_adjustment_id")
    source = agency_lts.adjustment_source(adjustment) if adjustment else used
    if source == MARYLAND:
        formula = formula_level(row)
        if formula is None:
            return MD_CHECKED
        if formula == level_of(row.get("stress_tier"), row.get("stress_half")):
            return MD_AGREES
        return MD_DIFFERS
    if source in RATED_BY_WORDS:
        return RATED_BY_WORDS[source]
    if source in agency_lts.AGENCIES:
        return agency_lts.source_name(source)
    return RATED_BY_WORDS[agency_lts.FORMULA_USED]


def agency_levels(row: Mapping) -> dict[str, float | None]:
    """The open agencies' own published levels on the way (never Maryland's)."""
    out: dict[str, float | None] = dict.fromkeys(AGENCY_COLUMNS.values())
    ratings = row.get("stress_ratings") or {}
    for held in ratings.get("agencies", ()) if isinstance(ratings, Mapping) else ():
        column = AGENCY_COLUMNS.get(held.get("agency"))
        if column is not None and held.get("level") is not None:
            out[column] = float(held["level"])
    return out


def access_words(code: str | None, words: Mapping[str, tuple[bool, str]]) -> str | None:
    """A way's bike-access code in words, as the road panel says it
    (`core.segment_info.ACCESS_WORDS`)."""
    if not code:
        return None
    known = words.get(code)
    return known[1] if known else code


# The road layer's columns, in order, with their GeoPackage types. The README documents
# each (`FIELD_NOTES`); a test holds the two lists together.
ROAD_FIELDS: tuple[tuple[str, str], ...] = (
    ("osm_way_id", "INTEGER"),
    ("ordinal", "INTEGER"),
    ("lts", "REAL"),
    ("lts_text", "TEXT"),
    ("rated_by", "TEXT"),
    ("formula_lts", "REAL"),
    ("why", "TEXT"),
    ("rule", "TEXT"),
    ("facility", "TEXT"),
    ("trail", "BOOLEAN"),
    ("unpaved", "BOOLEAN"),
    ("rough", "BOOLEAN"),
    ("lit", "BOOLEAN"),
    ("speed_mph", "INTEGER"),
    ("lanes", "INTEGER"),
    ("oneway", "BOOLEAN"),
    ("aadt", "INTEGER"),
    ("aadt_year", "INTEGER"),
    ("aadt_source", "TEXT"),
    ("moco_lts", "REAL"),
    ("ddot_lts", "REAL"),
    ("bike_access", "TEXT"),
    ("car_free_when", "TEXT"),
    ("map_class", "TEXT"),
    ("trail_name", "TEXT"),
    ("sidepath_name", "TEXT"),
    ("mtb_only", "BOOLEAN"),
    ("mtb_level", "INTEGER"),
    ("mtb_name", "TEXT"),
    ("walk_bike", "BOOLEAN"),
    ("hazard", "TEXT"),
    ("scenic", "TEXT"),
    ("md_count_linked", "BOOLEAN"),
)


def road_row(row: Mapping, access: Mapping[str, tuple[bool, str]]) -> dict:
    """One segment row as the download carries it (`ROAD_FIELDS`, geometry aside)."""
    md_count = row.get("volume_source") == MARYLAND
    level = download_level(row)
    out = {
        "osm_way_id": row["osm_way_id"],
        "ordinal": row["ordinal"],
        "lts": level,
        "lts_text": level_text(level),
        "rated_by": rated_by(row),
        "formula_lts": formula_level(row),
        "why": public_note(row.get("stress_adjustment_note"), row.get("stress_adjustment_display")),
        "rule": (row.get("stress_ratings") or {}).get("formula_rule")
        if maryland_used(row)
        else row.get("stress_rule"),
        "facility": row.get("facility"),
        "trail": row.get("is_trail_class"),
        "unpaved": row.get("is_unpaved"),
        "rough": row.get("is_rough"),
        "lit": row.get("lit"),
        "speed_mph": row.get("road_speed_mph"),
        "lanes": row.get("road_lanes"),
        "oneway": row.get("road_oneway"),
        "aadt": None if md_count else row.get("volume_aadt"),
        "aadt_year": None if md_count else row.get("volume_year"),
        "aadt_source": None if md_count else row.get("volume_source"),
        **agency_levels(row),
        "bike_access": access_words(row.get("bike_access_reason"), access),
        "car_free_when": ", ".join(row.get("car_free_when") or ()) or None,
        "map_class": row.get("map_class"),
        "trail_name": row.get("trail_name"),
        "sidepath_name": row.get("sidepath_name"),
        "mtb_only": row.get("mtb_only"),
        "mtb_level": row.get("mtb_level"),
        "mtb_name": row.get("mtb_name"),
        "walk_bike": row.get("walk_bike"),
        "hazard": row.get("hazard"),
        "scenic": open_scenic(row.get("scenic")),
        "md_count_linked": md_count,
    }
    return out


OWNER_ROW_FIELDS: tuple[tuple[str, str], ...] = (
    ("row_id", "TEXT"),
    ("rated_by", "TEXT"),
    ("lts", "REAL"),
    ("lts_text", "TEXT"),
    ("formula_lts", "REAL"),
    ("change", "TEXT"),
    ("category", "TEXT"),
    ("why", "TEXT"),
    ("ways", "INTEGER"),
    ("length_mi", "REAL"),
)


def owner_row(row: Mapping) -> dict:
    """One rating row (every way it covers, collected). `formula` and `formula_half` are
    the formula's level on its ways (`stress_ratings`), where an agency rated them; the tier
    before the row (`computed_tier`) is the formula's only where none did."""
    way = {
        "stress_adjustment_id": row["row_id"],
        "stress_tier": row.get("tier"),
        "stress_half": row.get("half"),
        "stress_computed_tier": row.get("computed_tier"),
        "stress_ratings": None
        if row.get("formula") is None
        else {"formula": row["formula"], "formula_half": row.get("formula_half")},
    }
    level = download_level(way)
    return {
        "row_id": row["row_id"],
        "rated_by": rated_by(way),
        "lts": level,
        "lts_text": level_text(level),
        "formula_lts": formula_level(way),
        "change": row.get("direction"),
        "category": row.get("category"),
        "why": public_note(row.get("note"), row.get("display")),
        "ways": row.get("ways"),
        "length_mi": None if row.get("length_m") is None else round(row["length_m"] / 1609.344, 3),
    }


TRAIL_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "TEXT"),
    ("length_mi", "REAL"),
    ("length_km", "REAL"),
    ("unpaved_share", "REAL"),
    ("ways", "INTEGER"),
)


def trail_row(row: Mapping) -> dict:
    length_m = row.get("length_m") or 0.0
    return {
        "name": row["name"],
        "length_mi": round(length_m / 1609.344, 2),
        "length_km": round(length_m / 1000, 2),
        "unpaved_share": None
        if row.get("unpaved_share") is None
        else round(row["unpaved_share"], 3),
        "ways": row.get("ways"),
    }


# The racks file (`scripts/build_bike_parking.py`): one layer a source, so each keeps its
# own licence. Ids are "dc<n>" (DDOT), "bc"/"bs"/"ba"<n> (Baltimore City DOT), and "n"/"w"
# plus an OSM id (OpenStreetMap).
RACK_LAYERS = ("racks_ddot", "racks_baltimore", "racks_osm")
RACK_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "racks_ddot": (("ddot_id", "TEXT"), ("racks", "INTEGER")),
    "racks_baltimore": (("bcdot_id", "TEXT"), ("racks", "INTEGER"), ("covered", "BOOLEAN")),
    "racks_osm": (
        ("osm_type", "TEXT"),
        ("osm_id", "INTEGER"),
        ("capacity", "INTEGER"),
        ("kind", "TEXT"),
        ("covered", "BOOLEAN"),
        ("name", "TEXT"),
    ),
}
_KIND = {"l": "lockers", "b": "building or room", "s": "stands"}
_OSM_TYPE = {"n": "node", "w": "way"}


def rack_layer(point_id: str) -> str | None:
    if point_id.startswith("dc"):
        return "racks_ddot"
    if point_id[:2] in ("bc", "bs", "ba"):
        return "racks_baltimore"
    if point_id[:1] in _OSM_TYPE and point_id[1:].isdigit():
        return "racks_osm"
    return None


def rack_rows(points: Iterable[Mapping]) -> dict[str, list[tuple[dict, float, float]]]:
    """The rack file's points by layer: (fields, lon, lat)."""
    out: dict[str, list[tuple[dict, float, float]]] = {name: [] for name in RACK_LAYERS}
    for p in points:
        layer = rack_layer(str(p.get("id", "")))
        if layer is None:
            continue
        pid = str(p["id"])
        if layer == "racks_ddot":
            fields = {"ddot_id": pid[2:], "racks": p.get("r")}
        elif layer == "racks_baltimore":
            fields = {"bcdot_id": pid, "racks": p.get("r"), "covered": p.get("cv") == 1}
        else:
            fields = {
                "osm_type": _OSM_TYPE[pid[0]],
                "osm_id": int(pid[1:]),
                "capacity": p.get("c"),
                "kind": _KIND.get(p.get("k") or "s"),
                "covered": p.get("cv") == 1,
                "name": p.get("n"),
            }
        out[layer].append((fields, float(p["x"]), float(p["y"])))
    return out


# What each layer is, for the GeoPackage's contents table and the README.
LAYER_DESCRIPTIONS = {
    "roads": "Every way RouteMaker rates, one row per segment: traffic stress (LTS) and why.",
    "rating_rows": "The reviewed rating rows (owner and community), each with every way it covers.",
    "trails": "The named long trails the zoomed-out map draws, one row per trail name.",
    "racks_ddot": "DDOT Public Bike Racks (DC Open Data, CC BY 4.0).",
    "racks_baltimore": "Baltimore City DOT bike racks and scooter corrals with racks "
    "(Baltimore City Code Art. 1 §9-1(h)).",
    "racks_osm": "Bike parking mapped in OpenStreetMap (ODbL 1.0).",
}

# Each field in words, for the README.
FIELD_NOTES = {
    "osm_way_id": "The OpenStreetMap way id (https://www.openstreetmap.org/way/<id>).",
    "ordinal": "The segment's place along its way, from 0 (ways are cut at junctions).",
    "lts": "Level of traffic stress: 1 (calmest) to 4.5 in half steps, 5 = Avoid.",
    "lts_text": "The level in words: 'LTS 2.5' or 'Avoid'.",
    "rated_by": "Who set the level: formula (and its owner rules), owner (reviewed), "
    "community (reviewed), Montgomery County Planning, DDOT, or, where MDOT SHA's level was "
    "consulted, our formula and whether it agrees.",
    "why": "The reviewed note the map shows for the road, where there is one; agency figures "
    "in it are cited.",
    "rule": "The rule that set the level, in words (the formula's, where MDOT SHA also rates "
    "the way).",
    "facility": "Bike facility: path, protected, lane or none.",
    "trail": "True for a path or trail (no motor traffic).",
    "unpaved": "True where unpaved, false where paved, blank where not mapped.",
    "rough": "True where the surface is mapped as rough.",
    "lit": "Street lighting as mapped (blank where not mapped).",
    "speed_mph": "The speed limit read, mph (blank where none was posted).",
    "lanes": "Through lanes each way, as read.",
    "oneway": "True for a one-way road.",
    "aadt": "Annual average daily traffic, both directions (blank where none, or Maryland's).",
    "aadt_year": "The year of that count.",
    "aadt_source": "Who published the count: ddot or vdot.",
    "moco_lts": "Montgomery County Planning's own Bicycle LTS for the way, where it rates it.",
    "ddot_lts": "DDOT's 2020 Level of Traffic Stress for the way, where it rates it.",
    "bike_access": "Why bicycles may not use the way (or why it was reopened), in words.",
    "car_free_when": "The ride times when the road is closed to cars (weekends, for one).",
    "map_class": "How the map draws it: road, alley, barred (no bikes) or hidden (not drawn).",
    "trail_name": "The long trail the way is part of.",
    "sidepath_name": "An unnamed path's name from the street beside it.",
    "mtb_only": "A mountain-bike trail, routed only by the mountain-bike ride types.",
    "mtb_level": "Singletrack difficulty, 1 to 4 (from mtb:scale).",
    "mtb_name": "A mountain-bike trail's name.",
    "walk_bike": "A short connector where riders walk their bikes.",
    "hazard": "Known hazards: cobbles, rails.",
    "scenic": "Scenic designations (rustic roads, East Coast Greenway, US Bike Routes).",
    "md_count_linked": "True where the traffic count used is Maryland's (MDOT SHA), left out "
    "of aadt and linked in the README.",
    "row_id": "The reviewed row's id, stable across map rebuilds.",
    "formula_lts": "RouteMaker's formula's own level, before any agency rating or reviewed row.",
    "change": "Whether the row raised (up) or lowered (down) the formula's level.",
    "category": "What the row is about: speed, road conditions, driver behaviour, ...",
    "ways": "How many OSM ways it covers.",
    "length_mi": "Length in miles.",
    "length_km": "Length in kilometres.",
    "name": "The name.",
    "unpaved_share": "The share of its length that is unpaved, 0 to 1.",
    "ddot_id": "DDOT's rack id.",
    "bcdot_id": "Baltimore City's rack id (bc = installed rack, bs = corral, ba = 2021 inventory).",
    "racks": "Number of racks.",
    "covered": "True where covered.",
    "osm_type": "node or way.",
    "osm_id": "The OpenStreetMap id.",
    "capacity": "Bikes it holds, as mapped.",
    "kind": "stands, lockers, or a building or room.",
}

# Sources we have no licence to pass on: linked, not included (the owner, 2026-11-05).
LINKED_NOT_INCLUDED: tuple[tuple[str, str, str], ...] = (
    (
        "MDOT SHA Annual Average Daily Traffic (Maryland traffic counts)",
        "https://www.arcgis.com/home/item.html?id=77010abe7558425997b4fcdab02e2b64",
        "Not included as data; a Why note may cite a count.",
    ),
    (
        "Maryland Bicycle Level of Traffic Stress (MDOT)",
        "https://www.arcgis.com/home/item.html?id=fc3c7b650076475ba9a4b0232f6d8655",
        "Consulted for agreement with our ratings; not included as data, cited in Why notes.",
    ),
    (
        "MDOT SHA Scenic Byways",
        "https://www.arcgis.com/home/item.html?id=dc571b56e48a4f4292986c97a119e88a",
        "Not included as data.",
    ),
    (
        "Arlington County Bike Comfort Index",
        "https://services1.arcgis.com/JrtUzVcH8S2wnzVH/arcgis/rest/services/Bike_Comfort_Index/FeatureServer/0",
        "Not included as data; our Arlington ratings are, and their Why notes cite it.",
    ),
    (
        "Capital Bikeshare system data",
        "https://capitalbikeshare.com/data-license-agreement",
        "Its licence agreement forbids handing the data on as a dataset.",
    ),
    (
        "Live closures (DDOT permits, MPD, AlertDC, work zones)",
        "https://opendata.dc.gov",
        "They change by the hour: the app shows them live, from each agency's own feed.",
    ),
)

ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
CREDITS: tuple[str, ...] = (
    "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)",
    "DC Open Data: DDOT (CC BY 4.0, adapted): Roadway Block, 2024 Traffic Volume, Public "
    "Bike Racks, DDOT Level of Traffic Stress 2020",
    "City of Baltimore, Department of Transportation (open, Baltimore City Code Art. 1 §9-1(h))",
    "Montgomery County Planning Department: Bicycle Level of Traffic Stress",
    "VDOT: traffic volume and posted speed limits",
    "City of Alexandria, VA (CC0): Transport Streets",
    "U.S. Census Bureau (urban areas) and USGS 3DEP (elevation), U.S. public domain",
)


# --- How our ratings compare with each agency's (the owner, 2026-11-05: "Also put comparison
# charts for each if the agencies in the documentation") --------------------------------------
#
# Over the roads both rate, the agency's published level (on our scale: Montgomery's 5 is our
# 4.5, `agency_lts.map_level`) against RouteMaker's own: a reviewed row's level where one is
# on the way, else the formula's. Never the level the map shows where the agency's own was
# used, which would agree with itself. Totals only, in miles: a summary that cites, not data.
COMPARE_BUCKETS = (
    ("agency_much_higher", "{agency} 2 or more levels more stressful"),
    ("agency_higher", "{agency} a half to 1.5 levels more stressful"),
    ("same", "Same level"),
    ("ours_higher", "RouteMaker a half to 1.5 levels more stressful"),
    ("ours_much_higher", "RouteMaker 2 or more levels more stressful"),
)
COMPARED_AGENCIES = ("moco", "ddot", MARYLAND)


def our_own_level(row: Mapping) -> float | None:
    """RouteMaker's own level for a way: an owner's or the community's reviewed row, else the
    formula's (`formula_level`)."""
    adjustment = row.get("stress_adjustment_id")
    if adjustment and agency_lts.adjustment_source(adjustment) in (
        agency_lts.OWNER,
        agency_lts.COMMUNITY,
    ):
        return level_of(row.get("stress_tier"), row.get("stress_half"))
    ratings = row.get("stress_ratings")
    if isinstance(ratings, Mapping) and ratings.get("formula") is not None:
        return level_of(ratings["formula"], ratings.get("formula_half"))
    return None


def compare_bucket(agency_level: float, ours: float) -> str:
    diff = agency_level - ours
    if diff >= 2:
        return "agency_much_higher"
    if diff > 0:
        return "agency_higher"
    if diff == 0:
        return "same"
    if diff > -2:
        return "ours_higher"
    return "ours_much_higher"


class Comparison:
    """Miles by agency and bucket, added one segment at a time."""

    def __init__(self) -> None:
        self.metres: dict[str, dict[str, float]] = {
            agency: dict.fromkeys((key for key, _ in COMPARE_BUCKETS), 0.0)
            for agency in COMPARED_AGENCIES
        }

    def add(self, row: Mapping, length_m: float) -> None:
        if row.get("map_class") not in (None, "road", "alley"):
            return
        ours = our_own_level(row)
        ratings = row.get("stress_ratings")
        if ours is None or not isinstance(ratings, Mapping):
            return
        for held in ratings.get("agencies", ()):
            agency, level = held.get("agency"), held.get("level")
            if agency not in self.metres or level is None:
                continue
            if agency_lts.PROHIBITING_LEVELS.get(agency) == float(level):
                continue  # a ban is access, not a level
            mapped = agency_lts.map_level(agency, float(level))
            self.metres[agency][compare_bucket(mapped, ours)] += length_m

    def summary(self) -> dict:
        out = {}
        for agency, buckets in self.metres.items():
            total = sum(buckets.values())
            out[agency] = {
                "name": agency_lts.source_name(agency),
                "miles": round(total / 1609.344, 1),
                "buckets": {
                    key: {
                        "miles": round(m / 1609.344, 1),
                        "percent": round(100 * m / total, 1) if total else 0.0,
                    }
                    for key, m in buckets.items()
                },
            }
        return out
