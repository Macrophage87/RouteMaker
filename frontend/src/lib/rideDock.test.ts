// Ride mode's side buttons and the share bike's dock button (the owner, 2026-10-17): lib/rideDock.ts runs here,
// and RideMode's wiring is read as source, as the other ride tests do.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { DockInfo, DocksAnswer } from "./bikeshareDocks.ts";
import type { LonLat } from "./geo.ts";
import type { NearestPlace, NearestResult } from "./nearest.ts";
import { Ride311Menu } from "./ride311.ts";
import { corridorWorry } from "./corridor.ts";
import { rideTripOf } from "./rideTrip.ts";
import {
  DOCKED_M,
  DOCK_NONE,
  DOCK_STILL_MS,
  DOCK_UNAVAILABLE,
  DOCK_WAYS,
  addedByBike,
  dockAt,
  dockButtonName,
  docksWithRoom,
  findDock,
  onTheWay,
  stillAtLength,
  stillStep,
  undockedMinutes,
  undockedShown,
  undockedWarning,
  warningDue,
} from "./rideDock.ts";

const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

const dock = (id: string, lon: number, lat: number, docks: number | null, closed = false): DockInfo => ({
  id,
  name: `Dock ${id}`,
  lon,
  lat,
  classic: 1,
  ebikes: 1,
  docks,
  closed,
});
const answer = (docks: DockInfo[], availability: DocksAnswer["availability"] = "live"): DocksAnswer => ({
  availability,
  as_of: null,
  docks,
  free_bikes: [],
  operators: [],
  credit: [],
});

test("the undocked time counts up in whole minutes, shown short and heard in words", () => {
  assert.equal(undockedMinutes(0, 59_999), 0);
  assert.equal(undockedMinutes(0, 12 * 60_000 + 5), 12);
  assert.equal(undockedMinutes(10_000, 0), 0, "never below 0");
  assert.equal(undockedShown(12), "12 min");
  assert.equal(undockedShown(65), "1:05");
  assert.equal(dockButtonName(12), "Ride to the nearest dock. Undocked about 12 minutes.");
  assert.equal(dockButtonName(1), "Ride to the nearest dock. Undocked about 1 minute.");
  assert.equal(dockButtonName(60), "Ride to the nearest dock. Undocked about 1 hour.");
  assert.equal(dockButtonName(125), "Ride to the nearest dock. Undocked about 2 hours 5 minutes.");
  assert.equal(dockButtonName(null), "Ride to the nearest dock.");
});

test("the spoken warning: at 35 minutes undocked, then every 5; each once, a missed one said at the next", () => {
  assert.equal(warningDue(34, null), null);
  assert.equal(warningDue(35, null), 35);
  assert.equal(warningDue(36, 35), null);
  assert.equal(warningDue(40, 35), 40);
  assert.equal(warningDue(47, 35), 45, "asleep through 40: 45 is said, once");
  assert.equal(warningDue(47, 45), null);
  assert.equal(undockedWarning(40), "You have been undocked for 40 minutes.");
  assert.match(ride, /const mark = warningDue\(undockedMinutes\(undockAt, now\), warnedAt\.current\);/);
  assert.match(ride, /if \(undockAt === null \|\| docked \|\| arrived \|\| ended\.current\) return;/);
});

test("only docks with room are offered: open, with a free slot or counts unknown", () => {
  const places = docksWithRoom([dock("a", 0, 0, 3), dock("b", 0, 0, 0), dock("c", 0, 0, null), dock("d", 0, 0, 5, true)]);
  assert.deepEqual(places.map((p) => p.id), ["dock-a", "dock-c"]);
  assert.deepEqual(places[0].details, ["3 open docks."]);
  assert.equal(places[0].kind, "dock");
});

const here: LonLat = [-77.03, 38.9];
const end: LonLat = [-77.03, 38.92];

test("closest: the nearest dock by bike from here becomes the detour; none or no answer is said", async () => {
  const docks = [dock("far", -77.03, 38.91, 2), dock("near", -77.031, 38.9005, 4)];
  const asked: LonLat[] = [];
  const out = await findDock({
    here,
    end,
    remainingM: 2200,
    docks: async () => answer(docks),
    request: async (from, places): Promise<NearestResult> => {
      asked.push(from);
      return { ok: true, answer: { by: "riding", places: places.map((p) => ({ distance_m: p.id === "dock-near" ? 150 : 1200, time_s: 40 })) } };
    },
  });
  assert.equal(out.ok, true);
  assert.equal(out.ok && out.dock.place.title, "Dock near");
  assert.match(out.said, /^Riding to Dock near, .* by bike, about 1 min\. 4 open docks\.$/);
  assert.deepEqual(asked, [here]);
  const none = await findDock({ here, end, remainingM: 1, docks: async () => answer([dock("x", 0, 0, 0)]), request: async () => ({ ok: false, message: "" }) });
  assert.deepEqual(none, { ok: false, said: DOCK_NONE });
  const down = await findDock({ here, end, remainingM: 1, docks: async () => null, request: async () => ({ ok: false, message: "" }) });
  assert.deepEqual(down, { ok: false, said: DOCK_UNAVAILABLE });
});

test("shortest detour: the dock that adds least to the ride (here to dock, dock to end, less the ride left)", async () => {
  // "behind" is closest to the rider but back the way; "ahead" is a little farther but on the way.
  const docks = [dock("behind", -77.03, 38.899, 4), dock("ahead", -77.03, 38.905, 4)];
  const distances: Record<string, { fromHere: number; fromEnd: number }> = {
    "dock-behind": { fromHere: 120, fromEnd: 2350 },
    "dock-ahead": { fromHere: 560, fromEnd: 1700 },
  };
  const out = await findDock(
    {
      here,
      end,
      remainingM: 2200,
      docks: async () => answer(docks),
      request: async (from, places: readonly NearestPlace[]) => ({
        ok: true,
        answer: { by: "riding", places: places.map((p) => ({ distance_m: from === here ? distances[p.id].fromHere : distances[p.id].fromEnd, time_s: 100 })) },
      }),
    },
    "detour",
  );
  assert.equal(out.ok && out.dock.place.title, "Dock ahead");
  assert.match(out.said, /It adds about .* to the ride\./);
  // The ride's own end dock adds nothing, but riding on to it is no detour: it is left out.
  const withEnd = await findDock(
    {
      here,
      end,
      remainingM: 2200,
      docks: async () => answer([...docks, dock("end", end[0], end[1], 9)]),
      request: async (from, places: readonly NearestPlace[]) => ({
        ok: true,
        answer: { by: "riding", places: places.map((p) => (p.id === "dock-end" ? { distance_m: from === here ? 2200 : 0, time_s: 1 } : { distance_m: from === here ? distances[p.id].fromHere : distances[p.id].fromEnd, time_s: 100 })) },
      }),
    },
    "detour",
  );
  assert.equal(withEnd.ok && withEnd.dock.place.title, "Dock ahead");
  assert.deepEqual(addedByBike({ by: "riding", places: [{ distance_m: 100, time_s: 1 }, { distance_m: null, time_s: null }] }, { by: "riding", places: [{ distance_m: 50, time_s: 1 }, { distance_m: 1, time_s: 1 }] }, 120), [30, null]);
  // The straight-line pick favours the docks on the way.
  const picked = onTheWay(here, end, docksWithRoom([dock("off", -77.05, 38.9, 2), dock("on", -77.03, 38.91, 2)]), 1);
  assert.equal(picked[0].id, "dock-on");
  assert.deepEqual(DOCK_WAYS.map((w) => w.label), ["Closest dock", "Shortest detour"]);
});

test("docked: still for long enough within a few metres of a dock; moving starts the stillness again", () => {
  let s = stillStep(null, here, 0);
  s = stillStep(s, [here[0] + 0.00005, here[1]], 20_000);
  assert.equal(s.since, 0, "a few metres is still still");
  assert.equal(stillAtLength(s, DOCK_STILL_MS - 1), false);
  assert.equal(stillAtLength(s, DOCK_STILL_MS), true);
  assert.equal(stillAtLength({ ...s, checked: true }, DOCK_STILL_MS * 2), false, "asked once per stop");
  assert.ok(DOCK_STILL_MS >= 120_000, "longer than a red light at a corner dock");
  assert.equal(stillAtLength(s, 20_000, 20_000), true, "the dock chosen with the button: a short stop is enough");
  assert.equal(stillStep(s, [here[0] + 0.001, here[1]], 30_000).since, 30_000, "moved on: afresh");
  assert.equal(dockAt(here, [dock("a", here[0] + 0.0002, here[1], 3)])?.id, "a");
  assert.equal(dockAt(here, [dock("a", here[0] + 0.001, here[1], 3)]), null, `beyond ${DOCKED_M} m`);
  assert.equal(dockAt(here, [dock("a", here[0], here[1], 3, true)]), null, "a closed dock is not one to dock at");
});

test("a share bike's ride is marked as one; a plain route is not a trip at all", () => {
  const route = {
    geometry: { type: "LineString", coordinates: [here, end] },
    bikeshare: { bike: "classic", start: { kind: "dock", name: "A" }, end: { kind: "dock", name: "B" }, walk_start: null, walk_end: null },
  } as never;
  assert.equal(rideTripOf(route, [here, end])?.shareBike, true);
});

test("the map saved for dead spots is said only when something went wrong", () => {
  assert.equal(corridorWorry("saving"), "");
  assert.equal(corridorWorry(null), "");
});

test("the 311 menu ends with its six problems: no full report, since a pick is logged", () => {
  const html = renderToStaticMarkup(createElement(Ride311Menu, { id: "m", open: true, place: null, onPick: () => {}, onClose: () => {} }));
  assert.match(html, /Something else<\/button><\/li><\/ul><\/div>$/);
});

test("RideMode: round side buttons with names; the bottom panel only when it has something; the dock button on a share bike", () => {
  // Each round button is named for screen readers, keeps its key, and Re-centre says when the map stopped following.
  assert.match(ride, /className="ride-round" onClick=\{askWhere\} aria-keyshortcuts="W" aria-label="Where am I\?"/);
  assert.match(ride, /aria-keyshortcuts="C"\s+aria-label=\{follow \? "Re-centre" : "Re-centre: the map stopped following you"\}/);
  assert.match(ride, /<Icon name="detour" size=\{24\} \/>/);
  assert.match(ride, /\{shareBike && !ride\.arrived && \(/);
  // The bottom panel is gone by default.
  assert.match(ride, /const sheetShown = notesShown \|\| ride\.off \|\| restShown \|\| reportOpen;/);
  assert.match(ride, /\{sheetShown && \(\s*<div ref=\{sheetRef\} className="ride-controls">/);
  assert.match(ride, /const corridorText = corridorWorry\(corridor\);/);
  // The time starts at the dock (or the start with no walk), and again on riding off from a dock.
  assert.match(ride, /if \(trip\?\.shareBike\) setUndockAt\(Date\.now\(\)\);/);
  assert.match(ride, /if \(haversineM\(fix\.point, at\) > LEFT_DOCK_M\) restartTime\(\);/);
  // One menu at a time.
  assert.match(ride, /setDetourOpen\(which === "detour"\);\s*setDockOpen\(which === "dock"\);\s*setMenu311\(which === "311"\);/);
  assert.match(css, /\.ride \.ride-round \{\s*width: 56px;\s*height: 56px;/);
});

test("following track-up, the rider is held two thirds of the way down the map, and the marker is a little larger (v0.9.0)", () => {
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /export const RIDER_AT = 2 \/ 3;/);
  assert.match(map, /return Math\.round\(top \+ Math\.max\(0, bottom - top\) \* RIDER_AT - box\.height \/ 2\);/);
  assert.match(map, /const ahead = props\.headingUp \? riderOffset\(map\.getContainer\(\)\) : 0;/);
  assert.match(map, /map\.easeTo\(\{ center: rider\.point, bearing, zoom, offset: \[0, ahead\], padding: NO_PADDING, duration: still \? 0 : 400 \}\);/);
  assert.match(css, /\.rider-marker \{\s*width: 36px;\s*height: 36px;/);
});

test("in a ride the map's scales and credits sit at the bottom left, above the bottom panel when it shows", () => {
  assert.match(css, /\.app\.riding:has\(\.ride\) \.maplibregl-ctrl-bottom-right \{\s*left: 0;\s*right: auto;\s*bottom: var\(--ride-sheet-h, 0px\);/);
  assert.match(ride, /<div ref=\{sheetRef\} className="ride-controls">/);
  assert.match(ride, /root\.style\.setProperty\("--ride-sheet-h", `\$\{sheet \? Math\.round\(sheet\.getBoundingClientRect\(\)\.height\) : 0\}px`\)/);
});

test("the ride's compass turns with the map, and a press switches north up and track-up (the owner, 2026-10-17)", () => {
  const map = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(map, /map\.on\("rotate", bearingVar\);/);
  assert.match(ride, /className="ride-compass" aria-pressed=\{!headingUp\} aria-label="North up" title="North up" onClick=\{\(\) => onHeadingUp\(!headingUp\)\}/);
  assert.match(css, /transform: rotate\(calc\(-1deg \* var\(--map-bearing, 0\)\)\);/);
});
