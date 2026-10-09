/**
 * The loop toggle reaches every way a point is added, named or said
 * (OWNER-DECISIONS 374). The lib functions are tested on their own
 * (loopVias, loopEdit, pointText); these pin the calls that hand them the
 * toggle, which no lib test can see (the mutation review's survivors).
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { pickIntoPlan, type Place } from "./geocode.ts";
import type { LonLat } from "./geo.ts";

const LINCOLN: Place = { name: "Lincoln Memorial", label: "Lincoln Memorial, Washington", lon: -77.0502, lat: 38.8893, kind: "other" };
const UNION: Place = { name: "Union Station", label: "Union Station, NoMa", lon: -77.0074, lat: 38.8978, kind: "house" };
const DUPONT: Place = { name: "Dupont Circle", label: "Dupont Circle, Washington", lon: -77.0434, lat: 38.9096, kind: "other" };
const at = (p: Place): LonLat => [p.lon, p.lat];

function plan(start: LonLat[], loop?: boolean) {
  let points = start;
  const deps = {
    current: () => points,
    commit: (next: LonLat[]) => {
      points = next;
    },
    remember: () => {},
    ...(loop === undefined ? {} : { loop }),
  };
  return { deps, points: () => points };
}

test("pickIntoPlan in a loop: a stop after the start alone, and a later stop on the way back", () => {
  const lone = plan([at(LINCOLN)], true);
  pickIntoPlan(UNION, "via", lone.deps);
  assert.deepEqual(lone.points(), [at(LINCOLN), at(UNION)]);
  // A start and one stop: the closing leg ties the way out and wins, so the pick is appended.
  const two = plan([at(LINCOLN), at(UNION)], true);
  pickIntoPlan(DUPONT, "via", two.deps);
  assert.deepEqual(two.points(), [at(LINCOLN), at(UNION), at(DUPONT)]);
  const off = plan([at(LINCOLN), at(UNION)], false);
  pickIntoPlan(DUPONT, "via", off.deps);
  assert.deepEqual(off.points(), [at(LINCOLN), at(DUPONT), at(UNION)], "off the loop the end stays the end");
});

test("pickIntoPlan in a loop: a stale destination choice is a stop, and a new start replaces the start", () => {
  const stale = plan([at(LINCOLN), at(UNION)], true);
  pickIntoPlan(DUPONT, "end", stale.deps);
  assert.deepEqual(stale.points(), [at(LINCOLN), at(UNION), at(DUPONT)]);
  const start = plan([at(LINCOLN), at(UNION)], true);
  pickIntoPlan(DUPONT, "start", start.deps);
  assert.deepEqual(start.points(), [at(DUPONT), at(UNION)]);
  const unset = plan([at(LINCOLN), at(UNION)]);
  pickIntoPlan(DUPONT, "end", unset.deps);
  assert.deepEqual(unset.points(), [at(LINCOLN), at(DUPONT)], "no loop flag: as before");
});

const source = (file: string) => readFileSync(new URL(file, import.meta.url), "utf8");
const count = (text: string, pattern: RegExp) => [...text.matchAll(pattern)].length;

test("App: the names follow the rider's toggle, not a ride that happens to end on its start", () => {
  const app = source("../App.tsx");
  assert.match(app, /const loopVias = loopStops\(preset, dials\.loop\);/);
  assert.doesNotMatch(app, /isRoundTrip/);
});

test("App: every way of adding, setting or removing a point is handed the toggle", () => {
  const app = source("../App.tsx");
  assert.match(app, /addPoint\(pointsRef\.current, point, loopVias\)/);
  assert.match(app, /announce\(addedSaid\(next\.indexOf\(point\), next\.length, loopVias\)\)/);
  assert.match(app, /stationEdit\(pointsRef\.current, point, role, loopVias\)/);
  assert.match(app, /announce\(stationSaid\(edit\.index, edit\.next\.length, loopVias\)\)/);
  assert.match(app, /removedSaid\(index, current\.length, loopVias\)/);
  assert.match(app, /insertIntoRide\(routed, leg, point, loopVias\)/);
  assert.match(app, /announce\(insertedSaid\(leg, next\.length, loopVias\)\)/);
  assert.match(app, /pickIntoPlan\(found, choice, \{[^}]*\bloop: loopVias,/);
  // place, insertOnLine, placeStation and removeFromMap are rebuilt when it flips.
  assert.ok(count(app, /\[commit, announce, loopVias\]/g) >= 4);
});

test("App: the line's legs, Reverse, the hints and the toggle's announcement use the toggle", () => {
  const app = source("../App.tsx");
  assert.match(app, /const legs = legPoints\(routedPoints, loopVias\);/);
  assert.match(app, /ends: legEnds\(path, legs, shown\.leg_ends\), points: routedPoints, legPoints: legs/);
  assert.match(app, /\}, \[shown, stale, routedPoints, points, loopVias\]\);/);
  assert.match(app, /if \(!canReverse\(current, loopVias\)\) return;\s+commit\(reversedPoints\(current, loopVias\)\);/);
  assert.match(app, /announce\(reversedSaid\(loopVias\)\);/);
  assert.match(app, /\{emptyPlanHint\(preset, loopVias, accessMode\)\}/);
  assert.match(app, /\{loneStartHint\(preset, loopVias, accessMode\)\}/);
});

test("App: the toggle, the ride type and undo or redo say when they rename the points", () => {
  const app = source("../App.tsx");
  assert.match(app, /onCommit=\{commitDials\}/);
  assert.match(app, /onChoose=\{choosePreset\}/);
  assert.match(
    app,
    /const commitDials = \(next: Dials\) => \{\s+const said = loopChangeSaid\(\{ preset, dials \}, \{ preset, dials: next \}, points\.length\);\s+if \(said\) announce\(said\);\s+setDials\(next\);/,
  );
  assert.match(
    app,
    /const choosePreset = \(id: PresetId, next: Dials\) => \{\s+const said = loopChangeSaid\(\{ preset, dials \}, \{ preset: id, dials: next \}, points\.length\);\s+if \(said\) announce\(said\);/,
  );
  assert.match(
    app,
    /const before = rideRef\.current;\s+const next = edits\.travel\(direction\);[\s\S]*?const renamed = loopChangeSaid\(before, rideRef\.current, next\.length\);[\s\S]*?announce\(renamed \? `\$\{said\} \$\{renamed\}` : said\);/,
  );
  assert.equal(count(app, /loopChangeSaid\(/g), 3, "the decision is the lib's, at these three calls");
  assert.doesNotMatch(app, /loopToggledSaid/);
});

test("App: Reverse in a loop of a start and one stop is aria-disabled with its reason, and a press says it", () => {
  const app = source("../App.tsx");
  assert.match(app, /const reverseHint = reverseUnavailableHint\(points, loopVias\);/);
  assert.match(
    app,
    /const unavailable = reverseUnavailableHint\(current, loopVias\);\s+if \(unavailable\) \{\s+announce\(unavailable\);\s+return;\s+\}/,
  );
  assert.match(
    app,
    /onClick=\{reverse\}\s+disabled=\{points\.length < 2\}\s+aria-disabled=\{reverseHint \? true : undefined\}\s+aria-describedby=\{reverseHint \? "reverse-hint" : undefined\}/,
  );
  assert.match(app, /\{reverseHint && <p className="hint" id="reverse-hint">\{reverseHint\}<\/p>\}/);
});

test("App hands the toggle to the search, the map, the points list and the GPX", () => {
  const app = source("../App.tsx");
  assert.match(app, /<PlaceSearch\s+pointCount=\{points\.length\}\s+loop=\{loopVias\}/);
  assert.match(app, /<MapView\s+points=\{points\}\s+loopVias=\{loopVias\}/);
  assert.match(app, /rows=\{pointRows\(points, namer, loopVias\)\}/);
});

test("App: the GPX names the route shown as it was planned, not as the toggle is now", () => {
  const app = source("../App.tsx");
  // Recorded with the route's points when it arrives, from the plan that was sent.
  assert.match(
    app,
    /setRoute\(result\.route\);\s+setRoutedPoints\(plan\.points\);\s+setRoutedLoop\(loopStops\(plan\.preset, plan\.dials\.loop\)\);/,
  );
  assert.equal(count(app, /setRoutedLoop\(/g), 1, "set nowhere else");
  // Handed to the GPX with the routed points, never the live toggle or points.
  assert.match(app, /<GpxPanel\s+route=\{shown\}\s+routedPoints=\{routedPoints\}\s+loop=\{routedLoop\}/);
  assert.doesNotMatch(app, /<GpxPanel[^>]*loop=\{loopVias\}/);
});

test("PlaceSearch, MapView, the rail cards and the GPX panel pass the toggle on", () => {
  const search = source("../PlaceSearch.tsx");
  assert.match(search, /searchView\(\{[^}]*\bloop,\s*\}\)/);
  assert.match(search, /\{placeEffectHint\(effect, loop\)\}/);
  const map = source("../MapView.tsx");
  assert.match(map, /pointLabel\(index, props\.points\.length, props\.loopVias === true\)/);
  assert.match(map, /\}, markerDeps\(props\.points, props\.markerReset, props\.loopVias\)\);/);
  assert.match(map, /loop: \(\) => callbacks\.current\.loopVias === true,/);
  assert.equal(count(map, /dragPreview\(grabbed\.legPoints, grabbed\.leg, /g), 2);
  assert.match(map, /points: edit\.points, legPoints: edit\.legPoints/);
  const rail = source("../railInteraction.ts");
  assert.match(rail, /stationRoles\(options\.pointCount\(\), options\.loop\?\.\(\) === true\)/);
  const gpx = source("../GpxPanel.tsx");
  assert.match(gpx, /loop = false \} = props;/);
  assert.match(gpx, /writeGpx\(exportOf\(route, routedPoints, loop\)\)/);
  assert.equal(count(gpx, /exportOf\(/g), 1, "one export, of the routed points");
});
