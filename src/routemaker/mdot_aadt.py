"""Maryland's traffic counts: MDOT SHA's AADT segments (FOLLOWUP-MDOT-AADT, OWNER-DECISIONS 429).

The owner, 2026-10-05: "yes" to adding MDOT SHA traffic counts to the classifier
where OSM and the agency layers have none. The first case is MD 185 (Connecticut
Ave) from Chevy Chase Circle to about 38.988 N, LTS 3 only for want of a count.
The download was approved for the v0.5.0 rebuild (plans/v0.5.0-plan.md, Track B,
"Approved by Stephen 2026-10-10").

The layer is "MDOT SHA Annual Average Daily Traffic (AADT)", ArcGIS item
`ITEM_ID`, layer 1 ("... (AADT) Segments", polylines). Read 2026-10-11 from the
service's own metadata (`LAYER_URL?f=pjson`): pages of 2,000, pagination
supported, and these fields among others:

- `AADT` ("AADT (Current)"): the latest year's count, both directions together.
  The layer's `NORTH_EAST_SPLIT` and `SOUTH_WEST_SPLIT` give each direction's
  share of it, so `AADT` is the bidirectional figure the classifier reads.
- `AADT_2015` ... `AADT_2023`: the earlier years. The layer's description says
  the current figure "is for the year 2024", one after the newest dated field,
  and it gains a field a year; so the year is read from the fields
  (`current_year`) rather than typed at install time.
- `LOC_ERROR`: "NO ERROR" on every row read (MD 185's seven state segments and
  two county roads numbered 185, 2026-10-11). Anything else says the count's
  line was not placed on the road and the row is not installed (`usable`).

Licence: Maryland iMAP's terms, recorded verbatim in docs/SOURCES.md (and PLAN.md,
Licensing): "The Data can be freely distributed as long as the metadata entry is
not modified or deleted. Any data derived from the Data must acknowledge the
State of Maryland in the metadata." So the counts are credited to the State of
Maryland wherever a credit is shown (`CREDIT`), and the segment table names each
segment they reached (`volume_source = 'mdot-sha'`), which is what keeps them out
of any published derivative until the waiver PLAN.md asks for is in hand.

Pure: nothing here reads a file or the network.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

AGENCY = "mdot-sha"
ITEM_ID = "77010abe7558425997b4fcdab02e2b64"
LAYER_URL = (
    "https://services.arcgis.com/njFNhDsUCentVYJW/arcgis/rest/services/"
    "MDOT_SHA_Annual_Average_Daily_Traffic/FeatureServer/1"
)
AADT_PROPERTY = "AADT"
CREDIT = "State of Maryland (MDOT SHA)"

# A dated count field: `AADT_2023`. Not `AAWDT_2023` (weekday traffic) and not
# the `_ANNO` text copies the older MapServer layer carried.
_DATED_FIELD = re.compile(r"^AADT_(\d{4})$")

# What `LOC_ERROR` says on a row whose line is where the count is.
NO_ERROR = frozenset({"", "NO ERROR", "NONE", "0"})


def current_year(field_names: Iterable[str]) -> int | None:
    """The year `AADT` is for: one after the newest `AADT_<year>` field.

    None where the layer has no dated field to read it from, which leaves the
    count undated rather than guessed (`volume_year` is nullable for that).
    """
    years = [int(match.group(1)) for name in field_names if (match := _DATED_FIELD.match(name))]
    return max(years) + 1 if years else None


def usable(properties: Mapping[str, object]) -> bool:
    """Whether a row's count may be installed: it has one above zero, and the
    agency does not flag its line as misplaced."""
    value = properties.get(AADT_PROPERTY)
    try:
        if value in (None, "") or float(value) <= 0:  # type: ignore[arg-type]
            return False
    except (TypeError, ValueError):
        return False
    flag = properties.get("LOC_ERROR")
    return flag is None or str(flag).strip().upper() in NO_ERROR


# The route systems OSM tags with a `ref` MDOT SHA's `ID_PREFIX` can be read against:
# interstates ("IS" to OSM's "I 95"), US and Maryland routes. County ("CO"), municipal
# ("MU"), ramp ("RP") and the other prefixes number roads OSM does not.
_REF_PREFIXES = {"IS": "I", "US": "US", "MD": "MD"}


def road_name(properties: Mapping[str, object]) -> str | None:
    """The street a count's section is named for: `ROADNAME` ("THIRD AVE")."""
    value = properties.get("ROADNAME")
    text = str(value).strip() if value is not None else ""
    return text or None


def route_ref(properties: Mapping[str, object]) -> str | None:
    """The section's route number as OSM writes a `ref`, "MD 97", or None where OSM
    numbers no such route (a county or municipal road, a ramp)."""
    prefix = _REF_PREFIXES.get(str(properties.get("ID_PREFIX") or "").strip().upper())
    number = str(properties.get("ID_RTE_NO") or "").strip()
    if not prefix or not number:
        return None
    try:
        number = str(int(float(number)))
    except ValueError:
        return None
    return f"{prefix} {number}"
