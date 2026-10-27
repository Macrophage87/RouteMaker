"""The known road hazards a route rides (v0.10.0; `routemaker.hazards`).

The owner, 2026-10-19: "We should have a symbol for roads with known other hazards on the
map. One example is the cobblestones in Georgetown or the streetcar rails on H street", then
"Roads with hazards like this should get a major penalty. You only need to show it if it's
routed on". So the graph prices them as LTS 4 (lua/routemaker_remap.lua `hazard_priced`) and
the map marks them only on a route that still takes one: this module finds those stretches,
in metres along the traced route as the stress sections are measured
(`routing.stress_spans`), for the map's symbols, the directions and the route's announcement
(frontend/src/lib/routeHazards.ts). Never colour or a symbol alone: each is said in words.
"""

from __future__ import annotations

import logging

from django.conf import settings

from pipeline.schema import HAZARD_COLUMN, validate_schema_name
from routemaker import hazards
from routemaker.lang import spanish, t

from . import segment_info

logger = logging.getLogger(__name__)

# A hazard stretch shorter than this is still said (a rail crossing a few metres long is
# the hazard), but two of one kind on one road this close are one.
JOIN_GAP_M = 25.0

_HAZARD_JOIN = """
SELECT seg.{column}
FROM unnest(%s::bigint[], %s::float8[], %s::float8[])
     WITH ORDINALITY AS p(way_id, lon, lat, ordinality)
LEFT JOIN LATERAL (
    SELECT s.{column}
    FROM {schema}.segment AS s
    WHERE s.osm_way_id = p.way_id
    ORDER BY s.geometry <-> ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)
    LIMIT 1
) AS seg ON true
ORDER BY p.ordinality
"""


def kinds_of(pieces: list) -> list[tuple[str, ...]]:
    """Each piece's hazard kinds, in the pieces' order; all empty where the live table has
    no hazard column (a table built before it) or the query fails."""
    if not pieces:
        return []
    none: list[tuple[str, ...]] = [()] * len(pieces)
    try:
        schema = validate_schema_name(settings.SEGMENT_SCHEMA_LIVE)
        if not segment_info.has_columns(schema, HAZARD_COLUMN):
            return none
        from .routing import plan_cursor

        with plan_cursor() as cursor:
            cursor.execute(
                _HAZARD_JOIN.format(schema=schema, column=HAZARD_COLUMN),
                [
                    [p.way_id for p in pieces],
                    [p.lon for p in pieces],
                    [p.lat for p in pieces],
                ],
            )
            rows = cursor.fetchall()
    except Exception:  # noqa: BLE001 - a table that fails, or a plan out of time, says none
        logger.warning("the route's hazards could not be read", exc_info=True)
        return none
    return decoded([row[0] for row in rows])


def decoded(values: list) -> list[tuple[str, ...]]:
    """Each of the hazard column's `values` (one a piece) as its kinds; all empty where one
    cannot be read: a bad value loses the route its hazards, never its reading
    (`routing.classify` reads the column in the stress query, audit S16)."""
    try:
        return [tuple(kind for kind, _ in hazards.decode(value)) for value in values]
    except Exception:  # noqa: BLE001 - as a table that fails: no hazards
        logger.warning("the route's hazards could not be read", exc_info=True)
        return [()] * len(values)


def road_of(piece) -> str:
    names = getattr(piece, "names", ()) or ()
    return names[0] if names else "an unnamed road"


def along(leg_runs: list, pieces: list, kinds: list[tuple[str, ...]] | None = None) -> list[dict]:
    """The hazards the route rides, in riding order: {from_m, to_m, kinds, road, text}.
    Consecutive pieces with the same kinds on the same road are one entry."""
    kinds = kinds_of(pieces) if kinds is None else kinds
    if not any(kinds):
        return []
    out: list[dict | None] = []
    at = 0.0
    for run in leg_runs:
        if not isinstance(run, tuple):
            at += float(run)
            out.append(None)  # a walk between: never joined across
            continue
        for i in range(run[0], run[1]):
            piece = pieces[i]
            start, at = at, at + piece.metres
            found = kinds[i] if i < len(kinds) else ()
            if not found:
                continue
            road = road_of(piece)
            last = out[-1] if out else None
            if (
                last is not None
                and tuple(last["kinds"]) == found
                and last["road"] == road
                and start - last["to_m"] <= JOIN_GAP_M
            ):
                last["to_m"] = round(at)
                continue
            out.append(
                {"from_m": round(start), "to_m": round(at), "kinds": list(found), "road": road}
            )
    found_ = [entry for entry in out if entry is not None]
    for entry in found_:
        entry["text"] = line(entry)
    return found_


def _miles(metres: float) -> str:
    return f"{metres / 1609.344:.1f}"


def _km(metres: float) -> str:
    return f"{metres / 1000:.1f}"


SHORT_WORDS = {hazards.COBBLES: "Cobblestones", hazards.RAILS: "Rails in the road"}


def line(entry: dict) -> str:
    """The directions' line: "Cobblestones on O Street Northwest, 1.2 to 1.4 mi (1.9 to
    2.3 km): bumpy, and slippery when wet." US units first, metric in brackets."""
    if spanish():
        # "Adoquines y rieles en la calle": the first capital, the rest as in a sentence.
        said = [t(SHORT_WORDS[k]) for k in entry["kinds"]]
        what = t(" and ").join([said[0], *(w[:1].lower() + w[1:] for w in said[1:])])
    else:
        what = " and ".join(SHORT_WORDS[k] for k in entry["kinds"]).capitalize()
    if (_miles(entry["from_m"]), _km(entry["from_m"])) == (
        _miles(entry["to_m"]),
        _km(entry["to_m"]),
    ):
        where = t("at {mi} mi ({km} km)", mi=_miles(entry["from_m"]), km=_km(entry["from_m"]))
    else:
        where = t(
            "{mi} to {mi_end} mi ({km} to {km_end} km)",
            mi=_miles(entry["from_m"]),
            mi_end=_miles(entry["to_m"]),
            km=_km(entry["from_m"]),
            km_end=_km(entry["to_m"]),
        )
    why = "; ".join(t(hazards.WORDS[k].split(": ", 1)[1]) for k in entry["kinds"])
    road = entry["road"]
    if road == "an unnamed road":
        road = t(road)
    return t("{what} on {road}, {where}: {why}.", what=what, road=road, where=where, why=why)


def entries(found: list[dict]) -> list[dict]:
    """The description's entries for the hazards (`routemaker.describe._entry`'s shape,
    kind "hazard"), so the directions list them in place and the ride says them ahead. The
    pieces carry the router's own edge lengths, so these are in the description's metres."""
    return [_entry(entry) for entry in found]


def _entry(entry: dict) -> dict:
    return {
        "kind": "hazard",
        "from_m": entry["from_m"],
        "to_m": entry["to_m"],
        "from_mi": round(entry["from_m"] / 1609.344, 2),
        "to_mi": round(entry["to_m"] / 1609.344, 2),
        "street": entry["road"],
        "tier": None,
        "facility": None,
        "turn": None,
        "severity": None,
        "via": None,
        "group": None,
        "surface": None,
        "text": entry["text"],
        "text_lanes_hidden": None,
    }


def with_entries(description: list[dict] | None, found: list[dict]) -> list[dict] | None:
    """A description list with the hazards' entries in route order (each before the entry
    that starts where it does); None stays None."""
    if description is None or not found:
        return description
    pending = sorted(entries(found), key=lambda e: e["from_m"])
    out: list[dict] = []
    for entry in description:
        while pending and pending[0]["from_m"] <= entry["from_m"]:
            out.append(pending.pop(0))
        out.append(entry)
    out.extend(pending)
    return out
