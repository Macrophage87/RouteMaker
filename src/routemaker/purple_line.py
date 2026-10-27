"""Closures from the Maryland Purple Line's construction updates (v0.13.0).

The owner, 2026-10-27, routed onto Bonifant Street in Silver Spring: "Bonifant street is closed
for major construction. see why it's missed". The Purple Line's streets are county and city
streets, so their closures are in no WZDx feed (Maryland's covers the state's roads only), and
the project posts them only as words on its "Updates & Detours" page
(https://purplelinemd.com/updates), sometimes with a PDF notice.

So they are read by a person into `src/core/geodata/purple-line-closures.json`, in the same
shape as DDOT's project advisories (`routemaker.ddot_advisories`, whose `parse` and `zones_of`
this uses): real closures (source "purple_line"), routed round, whole days, gone after their
last day. Overnight-only closures (10 pm to 4 am) are left out, since a whole-day window would
close the road all day. A block closed through a cross street is two lines overlapping past
it, since each line's ends are left open for the cross streets (`workzones.TRIM_M`).
docs/OPERATIONS.md, "Purple Line construction closures", has the steps.

Pure: no network, no database. `core.workzones.snapshot` adds `zones(now)` to the snapshot.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from . import ddot_advisories
from . import workzones as wz

SOURCE = "purple_line"
GEODATA = Path(__file__).resolve().parents[1] / "core" / "geodata" / "purple-line-closures.json"
PAGE = "https://purplelinemd.com/updates"


@lru_cache(maxsize=1)
def _loaded() -> tuple[tuple[ddot_advisories.Closure, ...], str]:
    closures, updated = ddot_advisories.parse(json.loads(GEODATA.read_text()))
    return tuple(closures), updated


def updated() -> str:
    """The day the file last changed: the source's "read at"."""
    return _loaded()[1]


def zones(now: datetime, closures=None) -> list[wz.Zone]:
    """The closures not yet past their last day: in force now or later."""
    found = _loaded()[0] if closures is None else closures
    return [z for c in found if c.end > now for z in ddot_advisories.zones_of(c, SOURCE)]
