#!/usr/bin/env python3
"""Mutants on the bikeshare plan (`core.bikeshare`), the GBFS client (`core.gbfs`) and the
bikeshare ride type's own settings (`core.presets`, `core.api`).

FOLLOWUP-BIKESHARE (OWNER-DECISIONS 243-245, 299, 300). A mutation pass run against WHOLE
test files, as `scripts/mutants_trailseek.py` does: a mutant is killed when any test in the
files named for it fails. It works on a copy of the repository and runs each test file in a
process of its own:

    scripts/mutants_bikeshare.py [--only NAME] [--list] [--check]

Needs the native test environment (`docs/DEVELOPMENT.md`, "The native loop"): PGDATABASE
should name a private database (the API tests use it). Each line of MUTANTS is
(name, file, old text, new text, test files); `old` must occur exactly once. Survivors are
printed last and the exit status is the number of them.

What it covers: dock selection (nearest first, radius, the candidates walked, the pair chosen
by walk plus ride), the availability fallback (a dock needs a bike of the type, a free slot,
to be renting or returning, and the unknown-availability path), the fee and zone rules (the
fee is the feed's, never built in; never outside a dock in a zone that bars it; none without
zone data; classic never), free-floating selection (e-bike only, shortest walk plus ride,
never reserved or disabled), and the cache and the endpoints' limits.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PLAN_T = ["tests/test_bikeshare.py"]
GBFS_T = ["tests/test_gbfs.py"]
API_T = ["tests/test_bikeshare_api.py"]

BS = "src/core/bikeshare.py"
GB = "src/core/gbfs.py"
PR = "src/core/presets.py"
AP = "src/core/api.py"

NL = "\n"
# The longest a test file may take against a mutant.
TEST_TIMEOUT_S = 300

MUTANTS: list[tuple[str, str, str, str, list[str]]] = [
    # --- dock selection ------------------------------------------------------------
    (
        "nearest: farthest first",
        BS,
        "key=lambda t: (t[0], t[1].name)",
        "key=lambda t: (-t[0], t[1].name)",
        PLAN_T,
    ),
    (
        "nearest: no search radius",
        BS,
        "for d, s in near if d <= SEARCH_RADIUS_M)",
        "for d, s in near if True)",
        PLAN_T,
    ),
    (
        "start: more docks walked than the limit",
        BS,
        "            if len(picks) == START_DOCKS:" + NL + "                break",
        "            if len(picks) == START_DOCKS + 40:" + NL + "                break",
        PLAN_T,
    ),
    (
        "end: more docks walked than the limit",
        BS,
        "            if len(picks) == END_DOCKS:" + NL + "                break",
        "            if len(picks) == END_DOCKS + 40:" + NL + "                break",
        PLAN_T,
    ),
    (
        "pair: longest walk plus ride wins",
        BS,
        "if best is None or total < best[0]:",
        "if best is None or total > best[0]:",
        PLAN_T,
    ),
    (
        "pair: the ride is not weighed",
        BS,
        "                + _ride_s(s_pick.point, e_pick.point, speed_kmh)" + NL,
        "",
        PLAN_T,
    ),
    (
        "pair: the walk to the destination is not weighed",
        BS,
        "                + (e_walk.duration_s if e_walk else 0.0)" + NL,
        "",
        PLAN_T,
    ),
    (
        "pair: the walk from the start is not weighed",
        BS,
        "                s_walk.duration_s" + NL + "                + _ride_s",
        "                0.0" + NL + "                + _ride_s",
        PLAN_T,
    ),
    (
        "pair: the same dock at both ends",
        BS,
        "            if s_pick.station_id is not None and s_pick.station_id == e_pick.station_id:"
        + NL
        + "                continue"
        + NL
        + "            if _distance(s_pick.point, e_pick.point) < 50.0:"
        + NL
        + "                continue",
        "            pass",
        PLAN_T,
    ),
    (
        "walk: a dock with no way on foot is kept",
        BS,
        "        if leg is not None:" + NL + "            starts.append((pick, leg))",
        "        starts.append((pick, leg or WalkLeg([origin, pick.point], 0.0, 0.0)))",
        PLAN_T,
    ),
    # --- availability and fallback ---------------------------------------------------
    (
        "start: a dock needs no bike",
        BS,
        "    return pick.status is not None and pick.status.can_rent and pick.status.bikes_of(bike) > 0",
        "    return True",
        PLAN_T,
    ),
    (
        "start: a dock need not be renting",
        BS,
        "    return pick.status is not None and pick.status.can_rent and pick.status.bikes_of(bike) > 0",
        "    return pick.status is not None and pick.status.bikes_of(bike) > 0",
        PLAN_T,
    ),
    (
        "start: any bike counts for the type",
        GB,
        '        return min(self.ebikes, self.bikes) if bike == "ebike" else self.classic',
        '        return min(self.ebikes, self.bikes) if bike == "ebike" else self.bikes',
        PLAN_T + GBFS_T,
    ),
    (
        "start: a classic is every bike",
        GB,
        "        return max(0, self.bikes - self.ebikes)",
        "        return self.bikes",
        PLAN_T + GBFS_T,
    ),
    (
        "start: an e-bike is every bike",
        GB,
        '        return min(self.ebikes, self.bikes) if bike == "ebike" else self.classic',
        '        return self.bikes if bike == "ebike" else self.classic',
        PLAN_T + GBFS_T,
    ),
    (
        "end: a dock needs no free slot",
        BS,
        "    return pick.status is not None and pick.status.can_return",
        "    return True",
        PLAN_T,
    ),
    (
        "end: a dock that is not returning is used",
        GB,
        "        return self.installed and self.returning and self.docks > 0",
        "        return self.installed and self.docks > 0",
        PLAN_T + GBFS_T,
    ),
    (
        "end: a full dock is used",
        GB,
        "        return self.installed and self.returning and self.docks > 0",
        "        return self.installed and self.returning",
        PLAN_T + GBFS_T,
    ),
    (
        "end: a dock out of service is used",
        GB,
        "        return self.installed and self.returning and self.docks > 0",
        "        return self.returning and self.docks > 0",
        PLAN_T + GBFS_T,
    ),
    (
        "start: unknown availability uses no dock",
        BS,
        "    if snapshot.status is None:" + NL + "        return True  # unknown",
        "    if snapshot.status is None:" + NL + "        return False  # unknown",
        PLAN_T,
    ),
    (
        "end: unknown availability uses no dock",
        BS,
        "    if snapshot.status is None:"
        + NL
        + "        return True"
        + NL
        + "    return pick.status is not None and pick.status.can_return",
        "    if snapshot.status is None:"
        + NL
        + "        return False"
        + NL
        + "    return pick.status is not None and pick.status.can_return",
        PLAN_T,
    ),
    (
        "notes: unknown availability not said",
        BS,
        "    if snapshot.status is None:" + NL + "        notes.append(",
        "    if False:" + NL + "        notes.append(",
        PLAN_T,
    ),
    (
        "notes: unknown availability labelled live",
        BS,
        'availability = "unknown" if snapshot.status is None else ("stale" if snapshot.stale else "live")',
        'availability = "live"',
        PLAN_T,
    ),
    (
        "notes: a stale snapshot not said",
        BS,
        "    if snapshot.stale:" + NL + "        notes.append(",
        "    if False:" + NL + "        notes.append(",
        PLAN_T,
    ),
    (
        "notes: the operator's alerts dropped",
        BS,
        "    for alert in (snapshot.alerts or [])[:2]:",
        "    for alert in []:",
        PLAN_T,
    ),
    (
        "notes: the whole walk is never compared",
        BS,
        "    if direct is not None and direct.duration_s <= walk_s + ride_s:",
        "    if False:",
        PLAN_T,
    ),
    (
        "notes: a dock passed over is not said (start)",
        BS,
        "    for distance, pick in passed[:2]:"
        + NL
        + "        notes.append("
        + NL
        + '            f"The nearest dock, {pick.name}',
        "    for distance, pick in passed[:0]:"
        + NL
        + "        notes.append("
        + NL
        + '            f"The nearest dock, {pick.name}',
        PLAN_T,
    ),
    (
        "notes: a dock passed over is not said (end)",
        BS,
        "    for distance, pick in passed[:2]:"
        + NL
        + "        notes.append("
        + NL
        + '            f"The dock nearest your destination',
        "    for distance, pick in passed[:0]:"
        + NL
        + "        notes.append("
        + NL
        + '            f"The dock nearest your destination',
        PLAN_T,
    ),
    # --- free-floating e-bikes (245) -----------------------------------------------------
    (
        "free: a classic may start at a free bike",
        BS,
        "    if bike == presets.BIKE_EBIKE and snapshot.free_bikes:",
        "    if snapshot.free_bikes:",
        PLAN_T,
    ),
    (
        "free: never considered",
        BS,
        "        for distance, found in near[:START_FREE_BIKES]:",
        "        for distance, found in near[:0]:",
        PLAN_T,
    ),
    (
        "free: the farthest bikes are the ones considered",
        BS,
        "        for distance, found in near[:START_FREE_BIKES]:",
        "        for distance, found in near[::-1][:START_FREE_BIKES]:",
        PLAN_T,
    ),
    (
        "free: no search radius",
        BS,
        "            if distance <= SEARCH_RADIUS_M:" + NL + "                free.append(",
        "            if True:" + NL + "                free.append(",
        PLAN_T,
    ),
    (
        "free: a reserved bike is taken",
        GB,
        '            or _flag(item.get("is_reserved"))' + NL,
        "",
        GBFS_T,
    ),
    (
        "free: a disabled bike is taken",
        GB,
        '            or _flag(item.get("is_disabled"))' + NL,
        "",
        GBFS_T,
    ),
    (
        "free: a scooter is taken",
        GB,
        "            or (isinstance(kind, str) and kind.lower() not in EBIKE_TYPES)" + NL,
        "",
        GBFS_T,
    ),
    (
        "free: a missing feed is taken as no bikes",
        BS,
        "    if bike == presets.BIKE_EBIKE and snapshot.free_bikes is None:",
        "    if False:",
        PLAN_T,
    ),
    # --- E-bike endings, the fee and the zones (244) -------------------------------------------
    (
        "ending: a classic may end outside a dock",
        BS,
        "    if bike != presets.BIKE_EBIKE:"
        + NL
        + '        return {"offered": False, "reason": "classic_bikes_end_at_docks"',
        "    if False:"
        + NL
        + '        return {"offered": False, "reason": "classic_bikes_end_at_docks"',
        PLAN_T,
    ),
    (
        "ending: offered with no zone data",
        BS,
        "    if snapshot.zones is None:" + NL + '        reason = "zones_unreadable"',
        "    if False:" + NL + '        reason = "zones_unreadable"',
        PLAN_T,
    ),
    (
        "ending: the zone is not consulted",
        BS,
        "    if not snapshot.zones.allows_ending(dest[0], dest[1]):",
        "    if False:",
        PLAN_T,
    ),
    (
        "ending: unreadable zones said to be absent",
        BS,
        'reason = "zones_unreadable" if "geofencing_zones" in snapshot.failed else "no_zone_data"',
        'reason = "no_zone_data"',
        PLAN_T,
    ),
    (
        "ending: outside taken though not offered",
        BS,
        '    use_outside = ending == ENDING_OUTSIDE and offer["offered"]',
        "    use_outside = ending == ENDING_OUTSIDE",
        PLAN_T,
    ),
    (
        "ending: outside taken unasked",
        BS,
        '    use_outside = ending == ENDING_OUTSIDE and offer["offered"]',
        '    use_outside = offer["offered"]',
        PLAN_T,
    ),
    (
        "ending: a fallback to a dock is not said",
        BS,
        "    if ending == ENDING_OUTSIDE and not use_outside:",
        "    if False:",
        PLAN_T,
    ),
    (
        "ending: the dock ending is not listed",
        BS,
        '            "kind": ENDING_DOCK,' + NL + '            "offered": True,',
        '            "kind": ENDING_DOCK,' + NL + '            "offered": False,',
        PLAN_T,
    ),
    (
        "fee: hard-coded",
        BS,
        '            "price": plan.price,',
        '            "price": "1.00",',
        PLAN_T,
    ),
    (
        "fee: the pricing plans are not read",
        BS,
        "    plan = gbfs.out_of_dock_fee(snapshot.pricing or [])",
        "    plan = None",
        PLAN_T,
    ),
    (
        "fee: any plan is the out-of-dock fee",
        GB,
        '        if OUT_OF_DOCK.search(f"{plan.plan_id} {plan.name} {plan.description}"):',
        "        if True:",
        PLAN_T + GBFS_T,
    ),
    (
        "fee: no plan is the out-of-dock fee",
        GB,
        '        if OUT_OF_DOCK.search(f"{plan.plan_id} {plan.name} {plan.description}"):',
        "        if False:",
        PLAN_T + GBFS_T,
    ),
    (
        "fee: an unstated fee is not said",
        BS,
        "    if fee is None:" + NL + "        return (",
        "    if False:" + NL + "        return (",
        PLAN_T,
    ),
    (
        "fee: the price information is not the feed's",
        BS,
        '    parts = [p.description or f"{p.name}: {p.price} {p.currency}" for p in snapshot.pricing]',
        '    parts = ["$1.00 unlock fee, $0.15 per minute."]',
        PLAN_T,
    ),
    (
        "fee: classic shows e-bike prices",
        BS,
        "    if bike != presets.BIKE_EBIKE or not snapshot.pricing:",
        "    if not snapshot.pricing:",
        PLAN_T,
    ),
    (
        "zone: ride_allowed ignored",
        GB,
        '    return rule.get("ride_allowed") is False or rule.get("station_parking") is True',
        '    return rule.get("station_parking") is True',
        GBFS_T + PLAN_T,
    ),
    (
        "zone: station_parking ignored",
        GB,
        '    return rule.get("ride_allowed") is False or rule.get("station_parking") is True',
        '    return rule.get("ride_allowed") is False',
        GBFS_T,
    ),
    (
        "zone: global rules ignored",
        GB,
        "        for rule in self.global_rules:"
        + NL
        + "            if _bars_ending(rule):"
        + NL
        + "                return False",
        "        pass",
        GBFS_T,
    ),
    (
        "zone: holes ignored",
        GB,
        "    return not any(_in_ring(lon, lat, hole) for hole in rings[1:])",
        "    return True",
        GBFS_T,
    ),
    (
        "zone: another zone's rules apply",
        GB,
        "            if _in_polygon(lon, lat, rings) and any(_bars_ending(rule) for rule in rules):",
        "            if any(_bars_ending(rule) for rule in rules):",
        GBFS_T,
    ),
    (
        "zone: outer ring not required",
        GB,
        "    if not rings or not _in_ring(lon, lat, rings[0]):",
        "    if not rings:",
        GBFS_T,
    ),
    (
        "zone: multipolygons dropped",
        GB,
        '        elif geometry.get("type") == "MultiPolygon":',
        "        elif False:",
        GBFS_T,
    ),
    (
        "zone: a document that is not zones is zones",
        GB,
        "    if not isinstance(features, list):" + NL + "        return None",
        "    if not isinstance(features, list):" + NL + "        features = []",
        GBFS_T,
    ),
    # --- the cache and the endpoints (300) -----------------------------------------------------------
    (
        "cache: kept ten minutes",
        GB,
        "CACHE_TTL_S = 60.0",
        "CACHE_TTL_S = 600.0",
        GBFS_T,
    ),
    (
        "cache: never kept",
        GB,
        "            if held is not None and now - held.fetched_at < CACHE_TTL_S:",
        "            if False:",
        GBFS_T + API_T,
    ),
    (
        "cache: stale served for ever",
        GB,
        "if held is not None and now - held.fetched_at < CACHE_TTL_S + STALE_GRACE_S:",
        "if held is not None:",
        GBFS_T,
    ),
    (
        "cache: a failure is tried again at once",
        GB,
        "            paused = self._failed_at is not None and now - self._failed_at < FAILURE_PAUSE_S",
        "            paused = False",
        GBFS_T,
    ),
    (
        "cache: a stale snapshot is not marked",
        GB,
        '                return Snapshot(**{**held.__dict__, "stale": True})',
        "                return held",
        GBFS_T,
    ),
    (
        "cache: a failed feed is taken as empty",
        GB,
        "                if parsed is None:  # listed, but not the feed it should be"
        + NL
        + "                    failed.add(name)"
        + NL
        + "                    continue",
        "                parsed = parsed or []",
        GBFS_T,
    ),
    (
        "cache: an optional feed's failure fails the snapshot",
        GB,
        "                except (Unavailable, FutureTimeout):"
        + NL
        + "                    failed.add(name)"
        + NL
        + "                    continue",
        "                except (Unavailable, FutureTimeout):"
        + NL
        + "                    raise Unavailable('a feed failed')",
        GBFS_T,
    ),
    (
        "net: plain http allowed",
        GB,
        '    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username',
        "    return parts.hostname in ALLOWED_HOSTS and not parts.username",
        GBFS_T,
    ),
    (
        "net: any host allowed",
        GB,
        '    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username',
        '    return parts.scheme == "https" and not parts.username',
        GBFS_T,
    ),
    (
        "net: a URL with a login allowed",
        GB,
        '    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS and not parts.username',
        '    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS',
        GBFS_T,
    ),
    (
        "net: a redirect off the hosts followed",
        GB,
        "        if not allowed_url(newurl):",
        "        if False:",
        GBFS_T,
    ),
    (
        "net: the size limit not applied",
        GB,
        "    if len(body) > MAX_BYTES:",
        "    if False:",
        GBFS_T,
    ),
    (
        "net: discovery's off-host feeds kept",
        GB,
        "if isinstance(name, str) and isinstance(url, str) and allowed_url(url):",
        "if isinstance(name, str) and isinstance(url, str):",
        GBFS_T,
    ),
    (
        "net: a cookie header sent",
        GB,
        '        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}',
        '        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT, "Cookie": "a=b"}',
        GBFS_T,
    ),
    (
        "net: more feeds than the planner reads are fetched",
        GB,
        '    "system_alerts",' + NL + ")",
        '    "system_alerts",' + NL + '    "system_hours",' + NL + ")",
        GBFS_T,
    ),
    # --- words and the credit (301) ----------------------------------------------------------------------
    (
        "credit: not added to the attribution",
        BS,
        '    body["attribution"] = [*ride.get("attribution", []), gbfs.CREDIT]',
        '    body["attribution"] = list(ride.get("attribution", []))',
        PLAN_T + API_T,
    ),
    (
        "credit: not in the plan",
        BS,
        '        "credit": gbfs.CREDIT,',
        '        "credit": "",',
        PLAN_T,
    ),
    (
        "credit: claims an affiliation",
        GB,
        'CREDIT = "Capital Bikeshare"',
        'CREDIT = "Official Capital Bikeshare partner"',
        PLAN_T + API_T,
    ),
    (
        "units: metric first",
        BS,
        '    return f"{metres / METRES_PER_MILE:.1f} mi ({metres / 1000:.1f} km)"',
        '    return f"{metres / 1000:.1f} km ({metres / METRES_PER_MILE:.1f} mi)"',
        PLAN_T,
    ),
    (
        "units: no feet for a short walk",
        BS,
        "    if metres < 160.0:",
        "    if False:",
        PLAN_T,
    ),
    (
        "steps: the count is not said",
        BS,
        '        count = f"{st.bikes_of(bike)} available"',
        '        count = "available"',
        PLAN_T,
    ),
    (
        "steps: at the dock is a walk",
        BS,
        "        if walk.distance_m < AT_DOCK_M",
        "        if False",
        PLAN_T,
    ),
    # --- the bike's own settings (core.presets, core.api) ------------------------------------------------------
    (
        "bike: a classic is not hill-averse",
        PR,
        "            hills=-60, speed_kmh=BIKESHARE_CLASSIC_SPEED_KMH, assist=False, system_weight_kg=100",
        "            hills=0, speed_kmh=BIKESHARE_CLASSIC_SPEED_KMH, assist=False, system_weight_kg=100",
        API_T,
    ),
    (
        "bike: an e-bike is as hill-averse as a classic",
        PR,
        "            hills=-20, speed_kmh=BIKESHARE_EBIKE_SPEED_KMH, assist=True, system_weight_kg=108",
        "            hills=-60, speed_kmh=BIKESHARE_EBIKE_SPEED_KMH, assist=True, system_weight_kg=108",
        API_T,
    ),
    (
        "bike: an e-bike is not assisted",
        PR,
        "            hills=-20, speed_kmh=BIKESHARE_EBIKE_SPEED_KMH, assist=True, system_weight_kg=108",
        "            hills=-20, speed_kmh=BIKESHARE_EBIKE_SPEED_KMH, assist=False, system_weight_kg=108",
        API_T,
    ),
    (
        "bike: a classic is as fast as an e-bike",
        PR,
        "BIKESHARE_CLASSIC_SPEED_KMH = 13.0",
        "BIKESHARE_CLASSIC_SPEED_KMH = 20.0",
        API_T,
    ),
    (
        "bike: the ride is not calm by default",
        PR,
        "BIKESHARE_STRESS = STRESS_TODAYS_TOP",
        "BIKESHARE_STRESS = DEFAULT_STRESS",
        API_T,
    ),
    (
        "bike: the ride is planned between the points",
        AP,
        "    return bikeshare.plan(" + NL + "        body.points[0],",
        "    return bikeshare.plan(" + NL + "        body.points[1],",
        API_T,
    ),
    (
        "request: any number of points",
        AP,
        "            if len(self.points) != 2:",
        "            if False:",
        API_T,
    ),
    (
        "request: a classic may end outside a dock",
        AP,
        '            if self.ending == bikeshare.ENDING_OUTSIDE and (self.bike or "classic") != "ebike":',
        "            if False:",
        API_T,
    ),
    (
        "request: a loop",
        AP,
        "            if self.loop:"
        + NL
        + '                raise ValueError("Bikeshare does not plan loops")',
        "            if False:"
        + NL
        + '                raise ValueError("Bikeshare does not plan loops")',
        API_T,
    ),
    (
        "request: bike on any ride type",
        AP,
        "        elif self.bike is not None or self.ending is not None:",
        "        elif False:",
        API_T,
    ),
    (
        "answer: unavailable data is a 500",
        AP,
        "        except gbfs.Unavailable:",
        "        except ZeroDivisionError:",
        API_T,
    ),
]


def _passes(copy: Path, tests: list[str]) -> bool:
    """Whether every test file passes, each in a process of its own (one test
    file per process: the lane's rule), stopping at the first that fails."""
    for test in tests:
        # A mutant can loop for ever: a file that has not finished in TEST_TIMEOUT_S is a
        # failure, and the process is killed, which also bounds its memory.
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test],
                cwd=copy,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return False
        if result.returncode != 0:
            return False
    return True


def check() -> int:
    """Every mutant's text occurs exactly once in its file."""
    bad = 0
    for name, rel, old, _new, _tests in MUTANTS:
        count = (ROOT / rel).read_text().count(old)
        if count != 1:
            print(f"BAD   {name}: occurs {count} times in {rel}")
            bad += 1
    print(f"{len(MUTANTS) - bad} of {len(MUTANTS)} mutants apply")
    return bad


def run(names: list[str] | None) -> int:
    survivors: list[str] = []
    selected = [m for m in MUTANTS if not names or m[0] in names]
    with tempfile.TemporaryDirectory(prefix="mutants-") as tmp:
        copy = Path(tmp) / "repo"
        shutil.copytree(
            ROOT,
            copy,
            ignore=shutil.ignore_patterns(".git", "node_modules", "dist", "__pycache__", ".venv*"),
        )
        # A control: the unmutated files must pass in the copy, or "killed" would
        # only mean the copy cannot run its tests.
        for tests in sorted({tuple(m[4]) for m in selected}):
            if not _passes(copy, list(tests)):
                print("CONTROL FAILED for", tests)
                return 1000
        for name, rel, old, new, tests in selected:
            target = copy / rel
            original = (ROOT / rel).read_text()
            if original.count(old) != 1:
                print(f"BAD   {name}: {old[:50]!r} occurs {original.count(old)} times in {rel}")
                survivors.append(name + " (bad mutant)")
                continue
            target.write_text(original.replace(old, new))
            killed = not _passes(copy, tests)
            target.write_text(original)
            if killed:
                print(f"killed   {name}", flush=True)
            else:
                print(f"SURVIVED {name}  ({rel})", flush=True)
                survivors.append(name)
    print(
        f"\n{len(selected) - len(survivors)} killed, {len(survivors)} survived of {len(selected)}"
    )
    for name in survivors:
        print("  survivor:", name)
    return len(survivors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", action="append", help="run just this mutant (repeatable)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true", help="only check that every mutant applies")
    args = parser.parse_args()
    if args.check:
        sys.exit(check())
    if args.list:
        for mutant in MUTANTS:
            print(mutant[0])
        sys.exit(0)
    sys.exit(run(args.only))
