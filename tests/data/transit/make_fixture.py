"""Writes the synthetic GTFS fixture under tests/data/transit (run once):

    python3 tests/data/transit/make_fixture.py tests/data/transit

One folder per system in src/core/transitdata/systems.json that the tests use. The station names
and places are real (WMATA's from the map's rail data); the timetables are invented.
"""

import csv
import shutil
import sys
from pathlib import Path

out = Path(sys.argv[1])

CALENDAR_HEADER = [
    "service_id",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "start_date",
    "end_date",
]
WK = ["WK", 1, 1, 1, 1, 1, 0, 0, "20260101", "20271231"]
SA = ["SA", 0, 0, 0, 0, 0, 1, 0, "20260101", "20271231"]
SU = ["SU", 0, 0, 0, 0, 0, 0, 1, "20260101", "20271231"]
WE = ["WE", 0, 0, 0, 0, 0, 1, 1, "20260101", "20271231"]
THANKSGIVING = "20261126"
STOP_TIMES_HEADER = ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"]


def write(folder, name, header, rows):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / name, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def hms(s):
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def H(h, m=0):
    return h * 3600 + m * 60


class Feed:
    def __init__(self, folder):
        self.folder = folder
        self.trips, self.times, self.freqs = [], [], []

    def trip(self, route, service, trip, direction, stops_offsets, start):
        self.trips.append([route, service, trip, direction])
        for i, (stop, offset) in enumerate(stops_offsets):
            self.times.append([trip, hms(start + offset), hms(start + offset), stop, i + 1])

    def finish(self):
        write(
            self.folder,
            "trips.txt",
            ["route_id", "service_id", "trip_id", "direction_id"],
            self.trips,
        )
        write(self.folder, "stop_times.txt", STOP_TIMES_HEADER, self.times)
        if self.freqs:
            write(
                self.folder,
                "frequencies.txt",
                ["trip_id", "start_time", "end_time", "headway_secs"],
                self.freqs,
            )


def every(feed, route, service, prefix, line, hop_s, start, end, step):
    """Both directions, a trip every `step` seconds from `start` to `end`."""
    for direction, order in ((0, line), (1, list(reversed(line)))):
        offsets = [(stop, i * hop_s) for i, stop in enumerate(order)]
        for n, t in enumerate(range(start, end, step)):
            feed.trip(route, service, f"{prefix}_{service}_{direction}_{n}", direction, offsets, t)


if out.exists():
    for child in out.iterdir():
        if child.is_dir():
            shutil.rmtree(child)

# --- WMATA Metro --------------------------------------------------------------------------
ST = {
    "EM": ("Eastern Market", -76.99600, 38.88463),
    "CS": ("Capitol South", -77.00514, 38.88507),
    "FC": ("Federal Center SW", -77.01587, 38.88508),
    "LE": ("L'Enfant Plaza", -77.02191, 38.88485),
    "SM": ("Smithsonian", -77.02807, 38.88803),
    "FT": ("Federal Triangle", -77.02813, 38.89319),
    "MC": ("Metro Center", -77.02808, 38.89832),
    "GP": ("Gallery Pl-Chinatown", -77.02192, 38.89832),
    "JS": ("Judiciary Square", -77.01664, 38.89610),
    "US": ("Union Station", -77.00742, 38.89777),
}
ORANGE = [f"PF_{k}_1" for k in ["EM", "CS", "FC", "LE", "SM", "FT", "MC"]]
RED = [f"PF_{k}_1" for k in ["US", "JS", "GP", "MC"]]
rail = out / "wmata-rail"
write(rail, "calendar.txt", CALENDAR_HEADER, [WK, SA])
# Thanksgiving has no weekday service (Metro's holiday timetable is Sunday's, and Sunday has none
# here); the weekend of 2026-10-17 is a planned shutdown, published as a removed Saturday.
write(
    rail,
    "calendar_dates.txt",
    ["service_id", "date", "exception_type"],
    [["WK", THANKSGIVING, 2], ["SA", "20261017", 2]],
)
stops = []
for key, (name, lon, lat) in ST.items():
    stops.append(
        [f"STN_{key}", f"{name.upper()} METRORAIL STATION", f"{lat:.6f}", f"{lon:.6f}", 1, ""]
    )
    stops.append(
        [
            f"PF_{key}_1",
            f"{name.upper()} PLATFORM",
            f"{lat + 0.0001:.6f}",
            f"{lon:.6f}",
            0,
            f"STN_{key}",
        ]
    )
stops.append(["PF_XX_1", "NOWHERE PLATFORM", "38.95", "-76.90", 0, ""])
write(
    rail,
    "stops.txt",
    ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type", "parent_station"],
    stops,
)
write(
    rail,
    "routes.txt",
    ["route_id", "route_short_name", "route_long_name", "route_type"],
    [["ORANGE", "OR", "Metrorail Orange Line", 1], ["RED", "RD", "Metrorail Red Line", 1]],
)
feed = Feed(rail)
# Weekday: Orange every 10 min 06:00-09:30 and every 12 min 09:30-23:30; Red every 6 min all day,
# by frequencies.txt (the path a feed may use).
every(feed, "ORANGE", "WK", "OR_AM", ORANGE, 120, H(6), H(9, 30), 600)
every(feed, "ORANGE", "WK", "OR_DAY", ORANGE, 120, H(9, 30), H(23, 30), 720)
for service, step in (("WK", 360), ("SA", 720)):
    for direction, order in ((0, RED), (1, list(reversed(RED)))):
        trip = f"RD_{service}_{direction}"
        feed.trip(
            "RED", service, trip, direction, [(s, i * 120) for i, s in enumerate(order)], H(6)
        )
        feed.freqs.append([trip, hms(H(6) if service == "WK" else H(8)), hms(H(23, 30)), step])
# Saturday: Orange every 15 min 08:00-23:00.
every(feed, "ORANGE", "SA", "OR_SA", ORANGE, 120, H(8), H(23), 900)
feed.finish()

# --- WMATA Metrobus -----------------------------------------------------------------------
bus = out / "wmata-bus"
write(bus, "calendar.txt", CALENDAR_HEADER, [WK])
write(
    bus, "calendar_dates.txt", ["service_id", "date", "exception_type"], [["WK", THANKSGIVING, 2]]
)
write(
    bus,
    "stops.txt",
    ["stop_id", "stop_name", "stop_lat", "stop_lon"],
    [
        ["1001", "Lincoln Park", "38.889700", "-76.989500"],
        ["1002", "Stanton Park", "38.893500", "-76.999300"],
        ["1003", "Union Station Bus Bay", "38.897200", "-77.007000"],
        ["1004", "Far Away Loop", "38.950000", "-76.900000"],
    ],
)
write(
    bus,
    "routes.txt",
    ["route_id", "route_short_name", "route_long_name", "route_type"],
    [["B10", "B10", "Lincoln Park - Union Station", 3], ["Z9", "Z9", "Nowhere", 3]],
)
feed = Feed(bus)
for n, start in enumerate(range(H(6), H(22), 900)):
    feed.trip("B10", "WK", f"B10_{n}", 0, [("1001", 0), ("1002", 240), ("1003", 480)], start)
feed.trip("Z9", "WK", "Z9_0", 0, [("1004", 0), ("1001", 600)], H(8))
feed.finish()

# --- MARC -----------------------------------------------------------------------------------
marc = out / "marc"
write(marc, "calendar.txt", CALENDAR_HEADER, [WK, WE])
# Thanksgiving: no weekday trains; the Penn Line runs its weekend timetable (added), Camden none.
write(
    marc,
    "calendar_dates.txt",
    ["service_id", "date", "exception_type"],
    [["WK", THANKSGIVING, 2], ["WE", THANKSGIVING, 1]],
)
write(
    marc,
    "stops.txt",
    [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "location_type",
        "parent_station",
        "wheelchair_boarding",
    ],
    [
        ["UNION", "Union Station MARC", "38.897100", "-77.006300", 1, "", 1],
        ["UNION_P", "Union Station MARC Platform", "38.897100", "-77.006300", 0, "UNION", 0],
        ["NCARR", "New Carrollton", "38.947800", "-76.871800", 0, "", 1],
        ["BWI", "BWI Marshall Rail", "39.192300", "-76.694200", 0, "", 1],
        ["PENN", "Baltimore Penn Station", "39.307500", "-76.615700", 0, "", 1],
        ["CAMDEN", "Camden Station", "39.285300", "-76.618700", 0, "", 1],
        ["CPARK", "College Park", "38.978700", "-76.928300", 0, "", ""],
    ],
)
write(
    marc,
    "routes.txt",
    ["route_id", "route_short_name", "route_long_name", "route_type"],
    [["PENN", "", "Penn Line", 2], ["CAMDEN", "", "Camden Line", 2]],
)
feed = Feed(marc)
PENN_SOUTH = [("PENN", 0), ("BWI", 720), ("NCARR", 1800), ("UNION_P", 2700)]
PENN_NORTH = [(s, 2700 - o) for s, o in reversed(PENN_SOUTH)]
# Weekdays: to Washington every 20 min 05:00-10:00, then hourly to 21:00; to Baltimore hourly
# 06:00-15:00, every 20 min 15:00-19:00, then hourly to 22:00. Weekends: every two hours.
south = list(range(H(5), H(10), 1200)) + list(range(H(10), H(21) + 1, 3600))
north = (
    list(range(H(6), H(15), 3600))
    + list(range(H(15), H(19), 1200))
    + list(range(H(19), H(22) + 1, 3600))
)
for n, t in enumerate(south):
    feed.trip("PENN", "WK", f"PS_{n}", 0, PENN_SOUTH, t)
for n, t in enumerate(north):
    feed.trip("PENN", "WK", f"PN_{n}", 1, PENN_NORTH, t)
for n, t in enumerate(range(H(7), H(21) + 1, 7200)):
    feed.trip("PENN", "WE", f"PWS_{n}", 0, PENN_SOUTH, t)
    feed.trip("PENN", "WE", f"PWN_{n}", 1, PENN_NORTH, t)
# The Camden Line: weekdays only, in the peak direction only.
for n, t in enumerate((H(6), H(6, 40), H(7, 20))):
    feed.trip("CAMDEN", "WK", f"CS_{n}", 0, [("CAMDEN", 0), ("CPARK", 2700), ("UNION_P", 3900)], t)
for n, t in enumerate((H(16, 30), H(17, 10), H(17, 50))):
    feed.trip("CAMDEN", "WK", f"CN_{n}", 1, [("UNION_P", 0), ("CPARK", 1200), ("CAMDEN", 3900)], t)
feed.finish()

# --- Light RailLink -----------------------------------------------------------------------------
light = out / "mta-light-rail"
write(light, "calendar.txt", CALENDAR_HEADER, [WK, SA, SU])
write(
    light,
    "calendar_dates.txt",
    ["service_id", "date", "exception_type"],
    [["WK", THANKSGIVING, 2], ["SU", THANKSGIVING, 1]],
)
write(
    light,
    "stops.txt",
    [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "location_type",
        "parent_station",
        "wheelchair_boarding",
    ],
    [
        ["LR_CY", "Camden Yards", "39.285000", "-76.620900", 0, "", 1],
        ["LR_CC", "Convention Center", "39.286900", "-76.618600", 0, "", 1],
        ["LR_UC", "University Center/Baltimore St", "39.289600", "-76.621500", 0, "", 0],
        ["LR_LM", "Lexington Market", "39.291700", "-76.621900", 0, "", 1],
        ["LR_PS", "Penn Station", "39.306900", "-76.615800", 0, "", 1],
    ],
)
write(
    light,
    "routes.txt",
    ["route_id", "route_short_name", "route_long_name", "route_type"],
    [["LR", "", "Light RailLink", 0]],
)
feed = Feed(light)
LINE = ["LR_CY", "LR_CC", "LR_UC", "LR_LM", "LR_PS"]
every(feed, "LR", "WK", "LR", LINE, 120, H(6), H(23), 900)
every(feed, "LR", "SA", "LR", LINE, 120, H(7), H(23), 1200)
every(feed, "LR", "SU", "LR", LINE, 120, H(8), H(21), 1200)
# An owl trip on the weekday service, at 27:30 (3:30 am the next morning), northbound, its two
# middle stops not timepoints (blank times, interpolated by the build).
feed.trips.append(["LR", "WK", "LR_OWL", 0])
for i, (stop, t) in enumerate(
    [("LR_CY", hms(H(27, 30))), ("LR_CC", ""), ("LR_UC", ""), ("LR_LM", hms(H(27, 36)))]
    + [("LR_PS", hms(H(27, 40)))]
):
    feed.times.append(["LR_OWL", t, t, stop, i + 1])
feed.finish()
