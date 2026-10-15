"""Bikeshare docks and free e-bikes on the map (v0.7.0, "Bikeshare docks on the map").

The owner, 2026-10-13 17:29 UTC: "If someone is on a bikeshare mode, show bikeshare docks (and
free ebikes) on the map. The docks should show with emojis a bike for regular, some sort of
electric symbol for ebike, and the number of empty slots." Then 17:58 UTC: "Allow the other ebike
services to also show up on the map, but only show cabi by default", and 17:59 UTC: "Make them
show up with a similar color perhaps on the map".

GET /api/bikeshare/docks answers for the rider's map view only: the docks and free e-bikes inside
a bounded box (`MAX_SPAN_LON`, `MAX_SPAN_LAT`), at most `MAX_DOCKS` and `MAX_FREE_BIKES` of each,
read from each operator's one shared live copy (`core.gbfs`), and kept nowhere. That is a live
view for the map, not the data handed on as a dataset (the Capital Bikeshare Data License
Agreement forbids hosting or distributing the data as a stand-alone dataset; docs/SOURCES.md).
A free bike's id is never passed on, and its position is rounded to about 36 ft (11 m).

The operators (`OPERATORS`): Capital Bikeshare only, shown by default and the only one routing
uses. Lime and Veo were left out (the owner, 2026-10-15): Lime's feed is internal-only and Veo
publishes no data terms, so neither has terms that allow display (docs/SOURCES.md). Another
operator is added only once its licence has been read, confirmed by the owner and recorded in
docs/SOURCES.md, with `licensed` set here (tests/test_micromobility.py holds every licensed
operator to a section of docs/SOURCES.md); a listed operator that is not licensed is never
contacted. Each operator has a colour near its own and an initial, so colour is never the only
cue; no logos.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from . import gbfs

# The largest view answered, in degrees: about 13 by 14 miles (21 by 22 km) at DC's
# latitude, the map at about zoom 11 on a large screen. The map asks from zoom 11 in.
MAX_SPAN_LON = 0.25
MAX_SPAN_LAT = 0.2
MAX_DOCKS = 500
MAX_FREE_BIKES = 500
# A free bike's position, rounded: 4 decimals is about 36 ft (11 m).
FREE_BIKE_DECIMALS = 4


@dataclass(frozen=True)
class Operator:
    id: str
    name: str
    # The map marker's letter and colour (white letter on it; contrast checked in the front end).
    initial: str
    colour: str
    # The operator's GBFS discovery feed and the hosts its feeds are on; None until known.
    discovery_url: str | None
    hosts: frozenset[str]
    # The feed's licence read, confirmed by the owner and recorded in docs/SOURCES.md.
    licensed: bool
    on_by_default: bool
    # Docked (stations) as well as free bikes.
    docked: bool
    credit: str


OPERATORS: tuple[Operator, ...] = (
    Operator(
        id="cabi",
        name="Capital Bikeshare",
        initial="C",
        colour="#c8102e",
        discovery_url=gbfs.DISCOVERY_URL,
        hosts=gbfs.ALLOWED_HOSTS,
        licensed=True,  # docs/SOURCES.md, "Capital Bikeshare" (OWNER-DECISIONS 300, 466)
        on_by_default=True,
        docked=True,
        credit=gbfs.CREDIT,
    ),
)
BY_ID = {o.id: o for o in OPERATORS}


def usable(operator: Operator) -> bool:
    """Whether the operator's feed may be fetched and shown: licensed and its feed known."""
    return operator.licensed and operator.discovery_url is not None


# One cache per other operator, made the first time it is asked for (Capital Bikeshare's is
# `gbfs.client`, shared by every worker). In memory only: a minute's copy, as gbfs's.
_clients: dict[str, gbfs.Gbfs] = {}
_clients_lock = threading.Lock()


def client_for(operator: Operator) -> gbfs.Gbfs | None:
    """The operator's live copy, or None when its feed may not be fetched."""
    if not usable(operator):
        return None
    if operator.id == "cabi":
        return gbfs.client
    with _clients_lock:
        found = _clients.get(operator.id)
        if found is None:
            hosts = operator.hosts

            def fetch(url: str, timeout: float) -> bytes:
                return gbfs.http_get(url, timeout, hosts)

            found = gbfs.Gbfs(
                fetch, discovery_url=operator.discovery_url or "", allowed=gbfs.hosts_only(hosts)
            )
            _clients[operator.id] = found
        return found


Box = tuple[float, float, float, float]  # west, south, east, north


def parse_bbox(text: str) -> Box:
    """The view as west,south,east,north in degrees: in range, and not too big."""
    parts = text.split(",")
    if len(parts) != 4:
        raise ValueError("bbox is west,south,east,north")
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError as error:
        raise ValueError("bbox is four numbers") from error
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox is west,south,east,north, each in range, west before east")
    if east - west > MAX_SPAN_LON or north - south > MAX_SPAN_LAT:
        raise ValueError("zoom in: the view is too large to show docks")
    return west, south, east, north


def _inside(lon: float, lat: float, box: Box) -> bool:
    west, south, east, north = box
    return west <= lon <= east and south <= lat <= north


@dataclass(frozen=True)
class Dock:
    id: str
    name: str
    lon: float
    lat: float
    classic: int | None  # None: availability unknown
    ebikes: int | None
    docks: int | None  # free slots
    closed: bool


def docks_in(snapshot: gbfs.Snapshot, box: Box) -> list[Dock]:
    """The docks in the box with their counts now; a dock not in service, or silent for half an
    hour, is closed (its counts are not trusted). At most MAX_DOCKS."""
    out: list[Dock] = []
    for station in snapshot.stations:
        if not _inside(station.lon, station.lat, box):
            continue
        status = snapshot.status.get(station.station_id) if snapshot.status is not None else None
        if snapshot.status is None:
            dock = Dock(
                station.station_id, station.name, station.lon, station.lat, None, None, None, False
            )
        elif (
            status is None
            or snapshot.reporting_stale(status)
            or not status.installed
            or not (status.renting or status.returning)
        ):
            dock = Dock(station.station_id, station.name, station.lon, station.lat, 0, 0, 0, True)
        else:
            dock = Dock(
                station.station_id,
                station.name,
                station.lon,
                station.lat,
                status.classic,
                min(status.ebikes, status.bikes),
                status.docks,
                False,
            )
        out.append(dock)
        if len(out) >= MAX_DOCKS:
            break
    return out


def free_bikes_in(snapshot: gbfs.Snapshot, box: Box) -> list[tuple[float, float]]:
    """The free e-bikes in the box, positions rounded, no ids. At most MAX_FREE_BIKES."""
    out: list[tuple[float, float]] = []
    for bike in snapshot.free_bikes or []:
        if _inside(bike.lon, bike.lat, box):
            out.append((round(bike.lon, FREE_BIKE_DECIMALS), round(bike.lat, FREE_BIKE_DECIMALS)))
            if len(out) >= MAX_FREE_BIKES:
                break
    return out
