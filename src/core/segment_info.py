"""What is known about the road or path at a map spot: GET /api/segment-info.

OWNER-DECISIONS 441 and 441a: a right-click (a long press on a phone, or the
keyboard's way to the map's centre) opens a panel naming the nearest road or
path and what RouteMaker knows of it - its name and kind, its traffic stress
and why, lanes, speed limit, traffic volume, bike facility, surface, whether a
bicycle may use it and why, and on the Mass Ride map its usable width and riders
a minute - each with its source in words, US units first (OWNER-DECISIONS 85).

Read only. The way is the nearest row of the live segment table within
`SNAP_RADIUS_M` (a drawn road or path is preferred to a hidden sidewalk or
driveway a few metres nearer); its name and kind, and whether the graph lets a
bicycle on it, come from the standard router's `/locate` at the spot on the way,
as the route's own street names do. Every column newer than the oldest live
table is optional: an older table answers with what it has and says the rest is
"available after the next data update".

Privacy (OWNER-DECISIONS 395): the spot is in the query string, which neither
gunicorn's access log nor the beta's nginx records, and nothing here logs it.
"""

from __future__ import annotations

import json
import re
import time

from django.conf import settings
from django.db import connection

from pipeline.schema import validate_schema_name
from routemaker import flow

# How far from the spot a way may be and still be the one the rider meant: a
# right-click on a drawn road lands within a few metres of its centre line at
# street zoom; past about 100 ft it is as likely the next street.
SNAP_RADIUS_M = 30.0
# A drawn road or path this much further than a hidden way (a sidewalk mapped
# beside it, a driveway) or a mountain-bike trail (drawn only as a thin dotted
# line, not for routes, and only while its map layer is on: OWNER-DECISIONS
# 452a, 454) is still the one meant: the rider
# clicked what the map shows as a way to ride.
DRAWN_PREFERENCE_M = 15.0
# Rows the nearest-neighbour scan reads before the distances are compared.
CANDIDATES = 24
# How far around the spot on the way `/locate` looks for its edges.
LOCATE_RADIUS_M = 8
LOCATE_TIMEOUT_S = 3.0
# Missing optional columns are looked for again this often, so the first
# answer after a rebuild's swap sees the new ones without a restart.
COLUMN_RECHECK_S = 300.0

FEET_PER_METRE = 3.28084
KMH_PER_MPH = 1.609344

OSM = "OpenStreetMap"
CLASSIFIER = "RouteMaker classifier"
OWNER = "Owner override"
ROUTER = "OpenStreetMap, through RouteMaker's routing graph"
NEXT_UPDATE = "Available after the next data update"

# The step words (OWNER-DECISIONS 441i-l: whole tiers only in this release).
TIER_WORDS = {
    1: "Comfortable for everyone",
    2: "Fine for adults",
    3: "For experienced cyclists",
    4: "High stress: busy, fast traffic",
    5: "Avoid",
}

# Who published a traffic count (`segment.volume_source`), in the words
# docs/SOURCES.md credits them by.
VOLUME_SOURCES = {
    "ddot": "DDOT 2024 Traffic Volume, DC Open Data (CC BY 4.0, adapted)",
    "dc-roadway-block": "DC Roadway Block (DDOT / DC GIS), DC Open Data (CC BY 4.0, adapted)",
    "vdot": "VDOT",
    "mdot-sha": "MDOT SHA",
}

# Where a classifier input came from (`segment.attr_sources`).
ATTR_SOURCES = {
    "osm": OSM,
    "dc-roadway-block": "DC Roadway Block (DDOT / DC GIS), DC Open Data (CC BY 4.0, adapted)",
    "baltimore-centerline": "Open Baltimore street centerline",
}

FACILITY_WORDS = {
    "path": "Traffic-free path",
    "protected": "Protected bike lane",
    "lane": "Painted bike lane",
    "none": "None: shared with traffic",
}

# Valhalla's edge use, then its road classification, in plain words.
USE_WORDS = {
    "cycleway": "Bike path",
    "path": "Path",
    "footway": "Footpath",
    "pedestrian": "Pedestrian street or plaza",
    "bridleway": "Bridle path",
    "mountain_bike": "Mountain-bike trail",
    "track": "Track (farm or forest road)",
    "living_street": "Living street",
    "alley": "Alley",
    "driveway": "Driveway",
    "parking_aisle": "Parking aisle",
    "service_road": "Service road",
    "ramp": "Ramp",
    "turn_channel": "Turn lane",
    "sidewalk": "Sidewalk",
    "steps": "Steps",
    "elevator": "Elevator",
    "pedestrian_crossing": "Crosswalk",
    "ferry": "Ferry",
}
PATH_USES = frozenset(
    {"cycleway", "path", "footway", "pedestrian", "bridleway", "mountain_bike", "sidewalk", "steps"}
)
CLASS_WORDS = {
    "motorway": "Freeway",
    "trunk": "Major highway",
    "primary": "Main road",
    "secondary": "Secondary road",
    "tertiary": "Through street",
    "unclassified": "Minor road",
    "residential": "Residential street",
    "service_other": "Service road",
}

# The reason a way is closed to bicycles, or reopened (`segment.bike_access_reason`,
# written by the rebuild: `pipeline.run.bike_access_reason`), in plain words. No
# person is ever named: an owner override is "an owner override".
ACCESS_WORDS = {
    "override_open": (
        True,
        "Open: reopened by an owner override, with evidence that bikes are allowed",
    ),
    "override_closed": (
        False,
        "Closed: an owner override, with evidence that bikes are not allowed",
    ),
    "military": (
        False,
        "Closed: inside a military area (closed unless there is evidence bikes are allowed)",
    ),
    "secured": (
        False,
        "Closed: inside a secure government site"
        " (closed unless there is evidence bikes are allowed)",
    ),
    "bicycle_no": (False, "Closed: no bicycles (a no-bike sign or rule, as mapped)"),
    "bicycle_use_sidepath": (False, "Closed: bicycles must use the side path"),
    "motorway": (False, "Closed: a freeway"),
    "motorroad": (False, "Closed: a motor-vehicle-only road"),
    "private": (False, "Closed: private, or no public access"),
    "impassable": (False, "Closed: mapped as impassable"),
    "cbd_sidewalk": (False, "Closed: a downtown sidewalk where riding is not allowed"),
    "zoo": (False, "Closed: a National Zoo path closed to bicycles"),
    "singletrack": (
        False,
        "Closed: mountain-bike singletrack, not used for routes by any ride type",
    ),
    "mtb": (
        False,
        "Closed: a mountain-bike trail, not used for routes except by the Gravel and"
        " Mountain Goat ride types (drawn as a thin grey dotted line when the"
        " Mountain-bike trails map layer is on)",
    ),
    "dismount": (False, "Closed: a long walk-your-bike stretch"),
    "sac_scale": (False, "Closed: a rough hiking trail"),
    "informal": (False, "Closed: an informal path"),
    "foot_designated": (False, "Closed: a footpath for walkers"),
    "trail_visibility": (False, "Closed: a faint trail"),
    "hiking_route": (False, "Closed: a hiking trail"),
    "natural_surface": (False, "Closed: a natural-surface footpath"),
    "park_path": (False, "Closed: a park footpath not open to bicycles"),
    "err_closed": (False, "Closed: unclear whether bikes are allowed, so treated as closed"),
}

# Every column this endpoint reads that an older live table may lack.
OPTIONAL_COLUMNS = (
    "facility",
    "car_free_when",
    "map_class",
    "road_speed_mph",
    "road_lanes",
    "road_oneway",
    "attr_sources",
    "stress_adjustment_id",
    "stress_computed_tier",
    "stress_adjustment_direction",
    "stress_adjustment_category",
    "stress_adjustment_note",
    "stress_adjustment_display",
    "trail_name",
    "roadside",
    "walk_bike",
    "mass_usable_width_m",
    "bike_access_reason",
    "mtb_only",
    "trail_bridge",
    "mtb_level",
    "mtb_name",
)
REQUIRED_COLUMNS = (
    "osm_way_id",
    "stress_tier",
    "stress_rule",
    "stress_assumed",
    "volume_source",
    "volume_aadt",
    "volume_year",
    "is_trail_class",
    "is_unpaved",
    "is_rough",
)

_columns: dict[str, tuple[frozenset[str], float]] = {}


def live_columns(schema: str) -> frozenset[str]:
    """The live segment table's columns; looked for again every COLUMN_RECHECK_S
    while one of OPTIONAL_COLUMNS is missing, since a swap only adds columns."""
    known = _columns.get(schema)
    now = time.monotonic()
    if known and (set(OPTIONAL_COLUMNS) <= known[0] or now - known[1] < COLUMN_RECHECK_S):
        return known[0]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'segment'",
            [schema],
        )
        found = frozenset(row[0] for row in cursor.fetchall())
    _columns[schema] = (found, now)
    return found


def forget_columns() -> None:
    """For tests: the next answer reads the table's columns afresh."""
    _columns.clear()


# --- the nearest way -------------------------------------------------------------------


def nearest_row(lat: float, lon: float) -> dict | None:
    """The live segment row the spot is on, with `distance_m` and the spot on it
    (`on_lon`, `on_lat`); None when nothing is within SNAP_RADIUS_M."""
    schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
    have = live_columns(schema)
    wanted = [c for c in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if c in have]
    select = ", ".join(f"s.{c}" for c in wanted)
    sql = f"""
        WITH spot AS (SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS g)
        SELECT {select},
               ST_Distance(s.geometry::geography, spot.g::geography) AS distance_m,
               ST_X(ST_ClosestPoint(s.geometry, spot.g)) AS on_lon,
               ST_Y(ST_ClosestPoint(s.geometry, spot.g)) AS on_lat
        FROM spot, LATERAL (
            SELECT * FROM {schema}.segment AS c
            ORDER BY c.geometry <-> spot.g
            LIMIT {CANDIDATES}
        ) AS s
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [lon, lat])
        names = [d[0] for d in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
    return choose(rows)


def is_mtb_trail(row: dict) -> bool:
    """A mountain-bike-class trail the map draws in its not-for-routes look (OWNER-DECISIONS
    452a): closed as `mtb`, or `mtb_only` on a way the map draws (rated singletrack, also
    `mtb_only`, is hidden and says so in its own words)."""
    if row.get("bike_access_reason") == "mtb":
        return True
    return row.get("mtb_only") is True and row.get("map_class") != "hidden"


def _rank(row: dict) -> int:
    """0 a way the map draws as one to ride, 1 a mountain-bike trail or a barred way
    (neither drawn as one to ride; the nearer of them wins), 2 a hidden way."""
    if row.get("map_class") == "hidden":
        return 2
    return 1 if is_mtb_trail(row) or row.get("map_class") == "barred" else 0


def choose(rows: list[dict]) -> dict | None:
    """The row meant: the nearest within SNAP_RADIUS_M, unless the nearest is hidden
    or a mountain-bike trail and a way the map draws as one to ride (or, past a hidden
    one, a mountain-bike trail) is within DRAWN_PREFERENCE_M of it. A mountain-bike
    trail alone near the spot is still described."""
    near = sorted(
        (r for r in rows if r.get("distance_m") is not None and r["distance_m"] <= SNAP_RADIUS_M),
        key=lambda r: r["distance_m"],
    )
    if not near:
        return None
    first = near[0]
    reach = first["distance_m"] + DRAWN_PREFERENCE_M
    better = [r for r in near if _rank(r) < _rank(first) and r["distance_m"] <= reach]
    if better:
        return min(better, key=lambda r: (_rank(r), r["distance_m"]))
    return first


# --- the router's edges ---------------------------------------------------------------


class RouterSilent(Exception):
    """The router did not answer; the panel says what the table alone knows."""


def locate_edges(lat: float, lon: float, costing: str) -> list[dict]:
    """The router's edges around a spot for one costing (`/locate`, verbose)."""
    from . import routing

    payload = {
        "locations": [{"lat": lat, "lon": lon, "radius": LOCATE_RADIUS_M}],
        "costing": costing,
        "verbose": True,
    }
    url = f"{settings.VALHALLA_UPSTREAMS['standard'].rstrip('/')}/locate"
    try:
        answer = routing._transport(url, payload, LOCATE_TIMEOUT_S)
    except (routing.RouterUnavailable, routing.RouterRefused) as error:
        raise RouterSilent(str(error)) from error
    if not isinstance(answer, list):
        raise RouterSilent("the router's locate answer is not a list")
    edges = []
    for location in answer[:1]:
        for edge in (location or {}).get("edges") or []:
            if isinstance(edge, dict):
                edges.append(edge)
    return edges


def edge_facts(edges: list[dict], way_id: int) -> dict | None:
    """The name and kind of the way from the router's edges of it, or None."""
    from .geocode import _ROUTE_REF

    for edge in edges:
        info = edge.get("edge_info") or {}
        if info.get("way_id") != way_id:
            continue
        names = [n.strip() for n in info.get("names") or [] if isinstance(n, str) and n.strip()]
        name = next((n for n in names if not _ROUTE_REF.match(n)), names[0]) if names else None
        classification = (edge.get("edge") or {}).get("classification") or {}
        return {
            "name": name,
            "use": str(classification.get("use") or ""),
            "classification": str(classification.get("classification") or ""),
        }
    return None


def router_facts(lat: float, lon: float, way_id: int) -> dict:
    """{bicycle: bool|None, name, use, classification} from the router: whether
    a bicycle may use the way (its edges are among the bicycle costing's), and
    its name and kind from whichever costing reaches it. `bicycle` is None when
    the router did not answer."""
    try:
        found = edge_facts(locate_edges(lat, lon, "bicycle"), way_id)
    except RouterSilent:
        return {"bicycle": None, "name": None, "use": "", "classification": ""}
    if found is not None:
        return {"bicycle": True, **found}
    for costing in ("pedestrian", "auto"):
        try:
            found = edge_facts(locate_edges(lat, lon, costing), way_id)
        except RouterSilent:
            break
        if found is not None:
            return {"bicycle": False, **found}
    return {"bicycle": False, "name": None, "use": "", "classification": ""}


# --- words ----------------------------------------------------------------------------


def feet_and_metres(metres: float) -> str:
    return f"{round(metres * FEET_PER_METRE):,} ft ({metres:.1f} m)"


def mph_and_kmh(mph: float) -> str:
    return f"{mph:g} mph ({round(mph * KMH_PER_MPH)} km/h)"


def road_kind(router: dict, row: dict) -> tuple[str, str]:
    """The kind of way in words, and where that came from."""
    use = router.get("use") or ""
    if use in USE_WORDS:
        return USE_WORDS[use], ROUTER
    classification = router.get("classification") or ""
    if classification in CLASS_WORDS:
        return CLASS_WORDS[classification], ROUTER
    if row.get("is_trail_class"):
        return "Path or trail", OSM
    return "Road", OSM


_MIXED_PARTS = {
    "single lane": "one lane each way",
    "urban multilane": "several lanes, city street",
    "multilane": "several lanes",
    "low volume": "light traffic",
    "mid volume": "moderate traffic",
    "high volume": "heavy traffic",
    "rough surface": "rough surface",
    "arterial floor": "a main road, so rated at least this",
    "collector floor": "a collector road, so rated at least this",
    "two-way floor": "a wide two-way road, so rated at least this",
    "wide one-way floor": "a wide one-way road, so rated at least this",
    "two-way busy": "a busy two-way road",
    "shoulder read as a lane": "the shoulder read as a bike lane",
}
_TRAIL_KINDS = {
    "open to bicycles": "open to bicycles",
    "not open to bicycles": "not open to bicycles",
    "sidepath for bicycles": "a side path beside a road",
    "no bicycle facility": "not marked for bicycles",
}
_SPEED = re.compile(r"(\d+(?:\.\d+)?) mph(?: or (?:below|above))?")


def _parts(text: str, table: dict[str, str]) -> list[str]:
    return [table.get(p.strip(), p.strip()) for p in text.split(",") if p.strip()]


def rule_words(rule: str) -> str:
    """The classifier's rule (`segment.stress_rule`) in plain words."""
    rule = (rule or "").strip()
    rule = re.sub(r"\s*\(Furth: [^)]*\)", "", rule)
    if rule.startswith("override: stress adjustment") or rule.startswith("named corridor:"):
        return "Owner-rated corridor"
    if "curated lane at" in rule:
        return "Owner-rated: a bike lane on a road this busy is LTS 4"
    if rule.startswith("legal but avoid"):
        posted = _SPEED.search(rule)
        return "Avoid: highway-like road" + (f" (posted {posted.group(0)})" if posted else "")
    match = re.match(r"motor-only classification \((\w+)\)", rule)
    if match:
        return f"Highway-like road for motor traffic ({match.group(1).replace('_', ' ')})"
    if rule.startswith("closed to motor traffic"):
        return "Closed to motor traffic, so rated as a path"
    match = re.match(r"trail-class way \(([^,)]+)(?:, ([^)]+))?\)", rule)
    if match:
        kind = _TRAIL_KINDS.get(match.group(2) or "", match.group(2) or "")
        return "Path away from traffic" + (f", {kind}" if kind else "")
    if rule.startswith("separated track alongside"):
        return "Separated bike track beside the road"
    if rule.startswith("mixed traffic"):
        parts = _parts(rule[len("mixed traffic") :], _MIXED_PARTS)
        speed = [p for p in parts if _SPEED.fullmatch(p)]
        rest = [p for p in parts if not _SPEED.fullmatch(p)]
        return ", ".join([*speed, "mixed traffic", *rest])
    if rule.startswith("bike lane"):
        return "Bike lane, " + ", ".join(_parts(rule[len("bike lane") :], _MIXED_PARTS))
    match = re.match(
        r"motor traffic restricted \(([^)]*)\), LTS (\d) at most(?:, posted (.*))?", rule
    )
    if match:
        posted = f", posted {match.group(3)}" if match.group(3) else ""
        return f"Little motor traffic ({match.group(1)}), so LTS {match.group(2)} at most{posted}"
    return rule[:1].upper() + rule[1:] if rule else "No reason recorded"


ADJUSTMENT_CATEGORIES = {
    "speed": "speed",
    "road_conditions": "road conditions",
    "driver_behaviour": "driver behaviour",
    "intersection": "an intersection",
    "sightlines": "sightlines",
    "better_among_alternatives": "better than the alternatives nearby",
    "other": "other",
}


def tier_text(tier: int) -> str:
    words = TIER_WORDS.get(tier, "")
    return words if tier == 5 else f"LTS {tier}: {words}"


def _row(label: str, value: str, source: str | None) -> dict:
    return {"label": label, "value": value, "source": source}


def stress_rows(row: dict) -> list[dict]:
    tier = int(row["stress_tier"])
    adjusted = row.get("stress_adjustment_id") is not None or str(
        row.get("stress_rule", "")
    ).startswith(("override:", "named corridor:"))
    source = OWNER if adjusted else CLASSIFIER
    rows = [
        _row("Level", tier_text(tier), source),
        _row("Why", rule_words(row["stress_rule"]), source),
    ]
    computed = row.get("stress_computed_tier")
    direction = row.get("stress_adjustment_direction")
    if computed is not None and direction in ("up", "down"):
        rows.append(_row("Before the override", tier_text(int(computed)), CLASSIFIER))
    category = row.get("stress_adjustment_category")
    if category in ADJUSTMENT_CATEGORIES:
        rows.append(_row("Owner's reason", ADJUSTMENT_CATEGORIES[category].capitalize(), OWNER))
    note = row.get("stress_adjustment_note")
    # A note marked route_only is for a route over the stretch, never a map click.
    if note and row.get("stress_adjustment_display") == "map":
        rows.append(_row("Note", str(note), OWNER))
    return rows


def _json(value):
    """A jsonb column as Python: the driver may hand it over as text."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _attr(row: dict, key: str) -> str | None:
    sources = _json(row.get("attr_sources"))
    if isinstance(sources, dict):
        value = sources.get(key)
        return value if isinstance(value, str) else None
    return None


def traffic_rows(row: dict) -> list[dict]:
    rows = []
    path = bool(row.get("is_trail_class"))
    assumed = [str(a) for a in (_json(row.get("stress_assumed")) or [])]
    have_lane_column = "road_lanes" in row
    if not path:
        lanes = row.get("road_lanes")
        oneway = row.get("road_oneway") is True
        if lanes is not None:
            source = ATTR_SOURCES.get(_attr(row, "lanes") or "osm", OSM)
            value = (
                f"{lanes} in this direction (a one-way street, or one side of a divided road)"
                if oneway
                else f"{lanes} each way"
            )
            rows.append(_row("Lanes", value, source))
        elif "lanes" in assumed:
            value = "Not mapped; assumed 1 " + ("in this direction" if oneway else "each way")
            rows.append(_row("Lanes", value, CLASSIFIER))
        elif not have_lane_column:
            rows.append(_row("Lanes", NEXT_UPDATE, None))
        speed = row.get("road_speed_mph")
        if speed is not None:
            source = ATTR_SOURCES.get(_attr(row, "maxspeed") or "osm", OSM)
            rows.append(_row("Speed limit", f"{mph_and_kmh(float(speed))}, posted", source))
        elif "maxspeed" in assumed:
            found = _SPEED.search(str(row.get("stress_rule") or ""))
            value = (
                f"Not posted in the data; assumed {found.group(0)}"
                if found
                else "Not posted in the data; assumed"
            )
            rows.append(_row("Speed limit", value, CLASSIFIER))
        elif "road_speed_mph" not in row:
            found = _SPEED.search(str(row.get("stress_rule") or ""))
            rows.append(
                _row(
                    "Speed limit",
                    f"Read as {found.group(0)}" if found else NEXT_UPDATE,
                    CLASSIFIER if found else None,
                )
            )
    aadt = row.get("volume_aadt")
    if aadt is not None:
        source = VOLUME_SOURCES.get(
            str(row.get("volume_source") or ""), str(row.get("volume_source") or "").upper() or None
        )
        year = row.get("volume_year")
        value = f"{int(aadt):,} vehicles a day (annual average)" + (
            f", {year} count" if year else ", year not known"
        )
        rows.append(_row("Traffic volume", value, source))
    elif not path:
        rows.append(_row("Traffic volume", "No count", None))
    return rows


def riding_rows(row: dict) -> list[dict]:
    rows = []
    facility = row.get("facility")
    if facility in FACILITY_WORDS:
        value = FACILITY_WORDS[facility]
        if facility == "none" and row.get("is_trail_class"):
            # A path the classifier does not count as a bike facility: a footway, a
            # sidewalk, a path not open to bicycles. It is not "shared with traffic".
            value = "None: a path not marked for bicycles"
        when = [w for w in row.get("car_free_when") or [] if isinstance(w, str)]
        if when:
            value += (
                f"; closed to cars at set times ({', '.join(w.replace('_', ' ') for w in when)})"
            )
        rows.append(_row("Bike facility", value, OSM))
    elif "facility" not in row:
        rows.append(
            _row(
                "Bike facility",
                "Path away from traffic" if row.get("is_trail_class") else NEXT_UPDATE,
                OSM if row.get("is_trail_class") else None,
            )
        )
    rows.append(_row("Surface", surface_words(row), OSM))
    level = row.get("mtb_level")
    words = mtb_level_words(level)
    if words:
        # OWNER-DECISIONS 456: the level the mountain-bike layer draws it in, in words.
        rows.append(
            _row(
                "Mountain-bike difficulty",
                f"{words[0].upper()}{words[1:]}: rated {MTB_LEVEL_SCALES[level]}"
                " (the higher of mtb:scale and mtb:scale:imba)",
                OSM,
            )
        )
    if row.get("walk_bike"):
        rows.append(_row("Walk your bike", "Yes: a short stretch where riding is not allowed", OSM))
    return rows


def surface_words(row: dict) -> str:
    """The shared surface rule (`is_unpaved`, `is_rough`; OWNER-DECISIONS 302, 403, 440)."""
    unpaved = row.get("is_unpaved")
    rough = bool(row.get("is_rough"))
    if unpaved is None:
        if row.get("is_trail_class") and row.get("roadside"):
            return "Not mapped; probably paved (a side path beside a road)"
        return "Not mapped"
    words = (
        ("Unpaved, rough" if rough else "Unpaved")
        if unpaved
        else ("Paved, rough" if rough else "Paved")
    )
    # A short bridge the map draws in its trail's surface, not its deck's
    # (`core.stress_tiles.BRIDGE_UNPAVED`): the words say the deck, and why the line differs.
    bridge = row.get("trail_bridge")
    if bridge == 2 and not unpaved:
        return f"{words} (a bridge deck; the map draws it as part of the unpaved trail)"
    if bridge == 1 and unpaved:
        return f"{words} (a bridge deck; the map draws it as part of the paved trail)"
    return words


def access_rows(row: dict, bicycle: bool | None) -> tuple[bool | None, list[dict]]:
    """Whether a bicycle may use the way, and the rows saying so and why."""
    have_reason = "bike_access_reason" in row
    reason = row.get("bike_access_reason")
    known = ACCESS_WORDS.get(reason) if isinstance(reason, str) else None
    map_class = row.get("map_class")
    if bicycle is None:
        # The router did not answer: the table's own reading.
        if known is not None:
            bicycle = known[0]
        elif map_class == "barred":
            bicycle = False
        elif map_class is not None:
            bicycle = True
    if bicycle is None:
        return None, [_row("Bike access", "Not known right now (the router did not answer)", None)]
    if bicycle:
        if known is not None and known[0]:
            return True, [
                _row("Bike access", known[1], OWNER if reason.startswith("override") else OSM)
            ]
        return True, [_row("Bike access", "Open to bicycles", ROUTER)]
    if known is not None and not known[0]:
        source = (
            OWNER
            if reason.startswith("override")
            else (CLASSIFIER if reason in ("military", "secured", "err_closed") else OSM)
        )
        return False, [_row("Bike access", known[1], source)]
    why = "Closed to bicycles" + (
        "" if have_reason else "; the reason is available after the next data update"
    )
    return False, [_row("Bike access", why, ROUTER)]


def mass_rows(row: dict) -> list[dict]:
    if "mass_usable_width_m" not in row:
        return [
            _row("Usable width", NEXT_UPDATE, None),
            _row("Riders a minute", NEXT_UPDATE, None),
        ]
    width = row.get("mass_usable_width_m")
    if width is None:
        value = "Not used by a mass ride" if int(row["stress_tier"]) == 5 else "Not known"
        return [_row("Usable width", value, None)]
    riders = flow.level_riders_per_min(float(width))
    return [
        _row(
            "Usable width",
            feet_and_metres(float(width)),
            "RouteMaker Mass Ride model, from OpenStreetMap and DC Roadway Block"
            " (DC Open Data, CC BY 4.0, adapted)",
        ),
        _row(
            "Riders a minute", f"About {round(riders):,} on the level", "RouteMaker Mass Ride model"
        ),
    ]


# --- the compact summary ----------------------------------------------------------------
#
# The panel's first screen (owner feedback on 441a: "a bit wordy and I have to scroll"):
# one short line a fact, no source under each, and a row left out rather than "none" or
# "not known" - except bike access, which is always said. Every figure, with its source,
# stays in the sections, which the panel keeps behind "Details and sources".

# Who published a traffic count, short, for the summary line "22,000 a day (DDOT 2024)".
VOLUME_SHORT = {
    "ddot": "DDOT",
    "dc-roadway-block": "DDOT",
    "vdot": "VDOT",
    "mdot-sha": "MDOT SHA",
}

# Why a way is closed to bicycles, in a few words: "Not allowed - military area".
ACCESS_SHORT = {
    "override_closed": "owner override",
    "military": "military area",
    "secured": "secure government site",
    "bicycle_no": "no-bike rule",
    "bicycle_use_sidepath": "use the side path",
    "motorway": "freeway",
    "motorroad": "motor vehicles only",
    "private": "private",
    "impassable": "mapped as impassable",
    "cbd_sidewalk": "downtown sidewalk",
    "zoo": "National Zoo path",
    "singletrack": "mountain-bike singletrack",
    "mtb": "mountain-bike trail",
    "dismount": "walk-your-bike stretch",
    "sac_scale": "rough hiking trail",
    "informal": "informal path",
    "foot_designated": "footpath for walkers",
    "trail_visibility": "faint trail",
    "hiking_route": "hiking trail",
    "natural_surface": "natural-surface footpath",
    "park_path": "park footpath",
    "err_closed": "unclear, so treated as closed",
}

# The mountain-bike difficulty levels (`segment.mtb_level`; OWNER-DECISIONS 456, 456a-c),
# named with their map colour, so the level is in words and never in colour alone. The
# front end's copy is `MTB_LEVELS` in frontend/src/stressStyle.js (a test holds them equal).
MTB_LEVEL_COLOURS = {1: "green", 2: "blue", 3: "black", 4: "red"}
# What each level is on the two OSM scales, for the panel's details.
MTB_LEVEL_SCALES = {
    1: "S1 or IMBA 1",
    2: "S2 or IMBA 2",
    3: "S3 or IMBA 3",
    4: "S4 to S6 or IMBA 4",
}


def mtb_level_words(level: object) -> str | None:
    """'level 2 (blue)', or None for no level."""
    if not isinstance(level, int) or level not in MTB_LEVEL_COLOURS:
        return None
    return f"level {level} ({MTB_LEVEL_COLOURS[level]})"


def mtb_summary(row: dict) -> str:
    """A mountain-bike trail's Bikes line (OWNER-DECISIONS 452a, 456): what the map's line
    means, 'Mountain-bike trail, level 2 (blue), not used for routes', and, honestly, that
    Gravel and Mountain Goat (the off-road graph) do route on it, unless it is rated
    singletrack, which every graph closes."""
    level = mtb_level_words(row.get("mtb_level"))
    head = f"Mountain-bike trail, {level}" if level else "Mountain-bike trail"
    # Its name where one is mapped (the owner, 2026-10-10: "try to make sure trail names are
    # added in if they are available"): "Mountain-bike trail, level 2 (blue): Rosaryville
    # Trail, not used for routes".
    name = (row.get("mtb_name") or "").strip()
    head = f"{head}: {name}," if name else f"{head},"
    if row.get("bike_access_reason") == "singletrack":
        return f"{head} not used for routes"
    return f"{head} not used for routes (Gravel and Mountain Goat may use it)"


# The parts of the classifier's rule the Lanes line already says.
_LANE_PARTS = frozenset({"single lane", "urban multilane", "multilane"})


def stress_short(tier: int) -> str:
    """'LTS 3 · For experienced cyclists', or 'Avoid'."""
    words = TIER_WORDS.get(tier, "")
    return words if tier == 5 else f"LTS {tier} · {words}"


def why_short(rule: str) -> str | None:
    """The rule in a few words, without what the Lanes line says; None when it adds nothing."""
    rule = re.sub(r"\s*\(Furth: [^)]*\)", "", (rule or "").strip())
    for head in ("mixed traffic", "bike lane"):
        if rule.startswith(head):
            parts = [p.strip() for p in rule[len(head) :].split(",") if p.strip()]
            kept = ", ".join(p for p in parts if p not in _LANE_PARTS)
            rule = f"{head}, {kept}" if kept else head
            break
    words = rule_words(rule)
    return None if words == "No reason recorded" else words


def summary_rows(row: dict, router: dict, open_: bool | None) -> list[dict]:
    """The compact summary: [{id, label, value}], in reading order."""
    tier = int(row["stress_tier"])
    path = bool(row.get("is_trail_class"))
    assumed = [str(a) for a in (_json(row.get("stress_assumed")) or [])]
    rows = [{"id": "stress", "label": "Traffic stress", "value": stress_short(tier)}]

    def add(id_: str, label: str, value: str) -> None:
        rows.append({"id": id_, "label": label, "value": value})

    why = why_short(str(row.get("stress_rule") or ""))
    if why:
        add("why", "Why", why)
    if not path:
        speed = row.get("road_speed_mph")
        if speed is not None:
            add("speed", "Speed", f"{mph_and_kmh(float(speed))}, posted")
        elif "maxspeed" in assumed:
            found = _SPEED.search(str(row.get("stress_rule") or ""))
            if found:
                mph = float(found.group(1))
                add("speed", "Speed", f"{mph_and_kmh(mph)}, assumed")
        # road_lanes counts one direction's through lanes: on a one-way street (or one
        # carriageway of a divided road) there is no "each way" (the review's C-1).
        lanes = row.get("road_lanes")
        way = "in this direction" if row.get("road_oneway") is True else "each way"
        if lanes is not None:
            add("lanes", "Lanes", f"{lanes} {way}")
        elif "lanes" in assumed:
            add("lanes", "Lanes", f"1 {way}, assumed")
    aadt = row.get("volume_aadt")
    if aadt is not None:
        who = VOLUME_SHORT.get(str(row.get("volume_source") or ""), "")
        year = row.get("volume_year")
        credit = " ".join(str(x) for x in (who, year) if x)
        add("traffic", "Traffic", f"{int(aadt):,} a day" + (f" ({credit})" if credit else ""))
    facility = row.get("facility")
    if facility == "protected":
        add("bike_lane", "Bike lane", "Protected")
    elif facility == "lane":
        add("bike_lane", "Bike lane", "Painted")
    elif facility == "path" and not path:
        add("bike_lane", "Bike lane", "Traffic-free path")
    when = [w.replace("_", " ") for w in row.get("car_free_when") or [] if isinstance(w, str)]
    if when:
        add("car_free", "Car-free", ", ".join(when))
    unpaved = row.get("is_unpaved")
    rough = bool(row.get("is_rough"))
    if unpaved is not None and (unpaved or rough or path):
        add("surface", "Surface", surface_words(row))
    if row.get("walk_bike"):
        add("walk", "Walk your bike", "A short stretch")
    reason = row.get("bike_access_reason")
    if open_ is not True and is_mtb_trail(row):
        # OWNER-DECISIONS 452a: said as the map draws it, with its level (456); the off-road
        # graph's ride types do use it, unless it is rated singletrack.
        add("bikes", "Bikes", mtb_summary(row))
    elif open_ is True:
        add("bikes", "Bikes", "Allowed")
    elif open_ is False:
        short = ACCESS_SHORT.get(reason) if isinstance(reason, str) else None
        add("bikes", "Bikes", f"Not allowed — {short}" if short else "Not allowed")
    else:
        add("bikes", "Bikes", "Not known right now")
    width = row.get("mass_usable_width_m")
    if width is not None:
        riders = flow.level_riders_per_min(float(width))
        add("mass", "Room for", f"About {round(riders):,} riders a minute")
    return rows


def describe(row: dict, router: dict) -> dict:
    """The panel's answer for one row and the router's facts about its way."""
    path = bool(row.get("is_trail_class"))
    # A mountain-bike trail's own name (`mtb_name`: name, ref or mtb:name) where the router
    # and the long-trail name have none (the owner, 2026-10-10).
    name = router.get("name") or row.get("trail_name") or row.get("mtb_name")
    name_source = ROUTER if router.get("name") else (OSM if name else None)
    kind, kind_source = road_kind(router, row)
    title = name or ("Unnamed path" if path or router.get("use") in PATH_USES else "Unnamed road")
    open_, access = access_rows(row, router.get("bicycle"))
    sections = [
        {
            "id": "road",
            "heading": "Road or path",
            "rows": [
                _row("Name", name or "No name mapped", name_source),
                _row("Kind", kind, kind_source),
            ],
        },
        {"id": "stress", "heading": "Traffic stress", "rows": stress_rows(row)},
        {"id": "traffic", "heading": "Traffic", "rows": traffic_rows(row)},
        {"id": "riding", "heading": "Riding", "rows": riding_rows(row)},
        {"id": "access", "heading": "Bike access", "rows": access},
        {"id": "mass", "heading": "Mass Ride capacity", "rows": mass_rows(row)},
    ]
    sections = [s for s in sections if s["rows"]]
    return {
        "found": True,
        "title": title,
        "tier": int(row["stress_tier"]),
        "open": open_,
        "osm_way_id": int(row["osm_way_id"]),
        "distance_m": round(float(row["distance_m"]), 1),
        # The nearest point on the way itself, [lon, lat]: the panel's Street View link
        # opens there, on the road it describes (OWNER-DECISIONS 441o).
        "on_way": [round(float(row["on_lon"]), 6), round(float(row["on_lat"]), 6)],
        "kind": kind,
        "summary": summary_rows(row, router, open_),
        "sections": sections,
    }


def segment_info(lat: float, lon: float) -> dict:
    """What is known of the way at the spot, or `{"found": false}`."""
    row = nearest_row(lat, lon)
    if row is None:
        return {"found": False, "title": "No road here", "summary": [], "sections": []}
    router = router_facts(float(row["on_lat"]), float(row["on_lon"]), int(row["osm_way_id"]))
    return describe(row, router)
