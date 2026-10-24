// Stops and via points (Stephen 2026-10-24): via points the default, a stop asks for a name, a re-route treats via
// points as guides and stops as mandatory, stops shown while riding, a file's named points are stops.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { planPointNames, writeGpx } from "./gpx.ts";
import { VIA_GUIDE_SKIP_M, cueSpoken, replanKept, rideModel, stopsAhead } from "./navigate.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { asKept } from "./gpxEdit.ts";
import type { ImportedPlan } from "./gpxPlan.ts";
import { compileCourse } from "./course.ts";
import { deviceProfile } from "./deviceProfiles.ts";
import {
  STOP_NAME_MAX,
  VIA_MARKS,
  ViaMarks,
  cleanStopName,
  decodeStopNames,
  encodeStopNames,
  importedKinds,
  renameLabel,
  rideStopLabel,
  stopNames,
} from "./pointKinds.ts";
import { detourButtonName, insteadName, nextStopLine, skippingSaid, withoutStop } from "./rideStops.ts";

const p = (lon: number, lat = 38.9): LonLat => [lon, lat];
const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("a stop's name is kept on its pair: through a move, a switch of kind and back, and a rename", () => {
  const marks = new ViaMarks();
  const stop = marks.named(p(-77.01), "  Union   Market ");
  assert.equal(marks.nameOf(stop), "Union Market");
  assert.equal(marks.nameOf(marks.moved(stop, p(-77.011))), "Union Market");
  const via = marks.withKind(stop, "via");
  assert.equal(marks.isVia(via), true);
  // A via point shows no name, but switched back it is the same stop again.
  assert.equal(marks.nameOf(marks.withKind(via, "stop")), "Union Market");
  // A rename is in place: the same pair, so no new route is asked for.
  marks.rename(stop, "Coffee");
  assert.equal(marks.nameOf(stop), "Coffee");
  marks.rename(stop, "   ");
  assert.equal(marks.nameOf(stop), undefined, "a blank name takes it away");
  assert.match(src("../App.tsx"), /VIA_MARKS\.rename\(point, name\);\s*setNamesVersion\(\(v\) => v \+ 1\);/);
  assert.match(src("../App.tsx"), /\}, \[points, preset, dials, namesVersion\]\);/);
  // A via point never shows a stop name it had before it was switched.
  assert.match(src("../usePlaceNames.ts"), /own: \(point\) => \(VIA_MARKS\.isVia\(point\) \? undefined : VIA_MARKS\.nameOf\(point\)\)/);
  assert.equal(cleanStopName("x".repeat(STOP_NAME_MAX + 9))?.length, STOP_NAME_MAX);
  assert.equal(renameLabel(false), "Name this stop");
  assert.equal(renameLabel(true), "Rename stop");
});

test("a link and a saved route carry each stop's name, and only stops between the ends", () => {
  const marks = new ViaMarks();
  const points = [marks.named(p(-77.0), "Home"), marks.named(p(-77.01), "Café: A & B"), marks.via(marks.named(p(-77.02), "x")), p(-77.03)];
  const names = stopNames(points, marks.nameOf, marks.isVia);
  assert.deepEqual([...names], [[1, "Café: A & B"]]);
  assert.deepEqual(encodeStopNames(names), ["1:Café: A & B"]);
  const hash = encodePlan(points, "default", undefined, [2], [], names);
  const plan = decodePlan(hash);
  assert.deepEqual(plan.vias, [2]);
  assert.deepEqual([...plan.names], [[1, "Café: A & B"]]);
  // An older link has none; a name for an end or past the points is dropped.
  assert.equal(decodePlan(encodePlan(points, "default")).names.size, 0);
  assert.deepEqual([...decodeStopNames(["0:Start", "4:Past", "2:Ok", "junk", "1:"], 4)], [[2, "Ok"]]);
  // A loop's last point is a stop: its name is kept, a via mark or not.
  const loop = [p(-77.0), marks.via(p(-77.01)), marks.named(p(-77.02), "Back")];
  assert.deepEqual([...stopNames(loop, marks.nameOf, marks.isVia, true)], [[2, "Back"]]);
  assert.deepEqual([...stopNames(loop, marks.nameOf, marks.isVia, false)], []);
  assert.deepEqual([...decodeStopNames(["2:Back"], 3)], [[2, "Back"]]);
});

test("the page's link, its saved routes and its kept routes: names in the first two, never in a kept route's key", () => {
  const saved = src("./savedRoutes.ts");
  assert.equal(saved.match(/hash: encodePlan\(points, preset, dials, viaIndices\(points, VIA_MARKS\.isVia\)\)/g)?.length, 2);
  assert.match(src("./planHash.ts"), /names: ReadonlyMap<number, string> = stopNames\(points, VIA_MARKS\.nameOf, VIA_MARKS\.isVia, dials\?\.loop === true\)/);
  assert.match(src("./offlineRoutes.ts"), /encodePlan\(points, preset, sent, vias, undefined, new Map\(\)\)/);
  const app = src("../App.tsx");
  assert.match(app, /VIA_MARKS\.nameAt\(initialPlan\.points, initialPlan\.names\)/);
});

test("a file's unnamed points are via points, its named ones stops with their names (a track's points are vias)", () => {
  const kinds = importedKinds(["Start", undefined, "Union Market", "  ", "Via point", "Stop 4", "End"], 7);
  assert.deepEqual(kinds.vias, [1, 3, 4]);
  // "Stop 4" only says its role: a stop, but not a name of its own.
  assert.deepEqual([...kinds.names], [[2, "Union Market"]]);
  assert.deepEqual(importedKinds(undefined, 4).vias, [1, 2]);
  assert.deepEqual(importedKinds(["Start", "Via 3", "End"], 3).vias, [1], "an older file's via name");
  assert.match(src("../App.tsx"), /const kinds = importedKinds\(plan\.pointNames, opened\.length\);\s*VIA_MARKS\.nameAt\(VIA_MARKS\.markAt\(opened, kinds\.vias\), kinds\.names\);/);
});

test("a file and a course name a named stop by its name; the file reads back as the same stops and vias", () => {
  const names = new Map([[2, "Tom's <Bikes>"]]);
  assert.deepEqual(planPointNames(5, false, [1], names), ["Start", "Via point", "Tom's <Bikes>", "Stop 2", "End"]);
  const points = [p(-77.0), p(-77.01), p(-77.02), p(-77.03), p(-77.04)];
  const gpx = writeGpx({ name: "n", description: "d", attribution: [], preset: "default", planPoints: points, vias: [1], stopNames: names, geometry: points });
  assert.match(gpx, /<name>Tom's &lt;Bikes&gt;<\/name>/);
  const read = [...gpx.matchAll(/<rtept [^>]*>\s*<name>([^<]*)<\/name>/g)].map((m) => m[1].replace("&lt;", "<").replace("&gt;", ">"));
  const kinds = importedKinds(read, 5);
  assert.deepEqual(kinds.vias, [1]);
  assert.deepEqual([...kinds.names], [[2, "Tom's <Bikes>"]]);
});

// ---- Riding -----------------------------------------------------------------------------------------------------

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
const at = (east: number): LonLat => [-77.05 + east / KX, LAT];

function stretch(from: number, to: number, street: string): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street, tier: 1, facility: null, turn: null, text: street };
}
const point = (m: number, via: number): DescriptionEntry => ({ ...stretch(m, m, `Point ${via}.`), kind: "via", via, street: null });

/** Start, a via at 300 m, a stop at 1,000 m, a via at 2,000 m, end at 3,000 m, due east. */
function ride(): { route: RouteResponse; points: LonLat[]; vias: number[] } {
  const points = [at(0), at(300), at(1000), at(2000), at(3000)];
  const route = {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0), at(1000), at(2000), at(3000)] },
    distance_m: 3000,
    duration_s: 600,
    climb_m: 0,
    descent_m: 0,
    stress_m: {},
    attribution: [],
    leg_ends: [3],
    description: [stretch(0, 3000, "A Street"), point(300, 1), point(1000, 2), point(2000, 3)],
    stress_spans: [],
  } as unknown as RouteResponse;
  return { route, points, vias: [1, 3] };
}

test("a re-route keeps the stops and the far via points, and drops a via point close ahead", () => {
  const { route, points, vias } = ride();
  const model = rideModel(route, vias);
  // 100 m along: the via at 300 m is close ahead, the stop at 1,000 m and the via at 2,000 m are not.
  assert.ok(300 - 100 < VIA_GUIDE_SKIP_M && 2000 - 100 > VIA_GUIDE_SKIP_M);
  assert.deepEqual(replanKept(model, 100, points, false, true), [2, 3, 4]);
  // Without `guides` (End ride's plan left), every via point not passed stays.
  assert.deepEqual(replanKept(model, 100, points, false), [1, 2, 3, 4]);
  // Close to a stop: the stop is never dropped.
  assert.deepEqual(replanKept(model, 900, points, false, true), [2, 3, 4]);
  assert.deepEqual(replanKept(model, 1500, points, false, true), [4], "the via at 2,000 m is close ahead now");
  // Skip this stop: the re-plan's points without it.
  const here = at(950);
  assert.deepEqual(withoutStop(points, replanKept(model, 900, points, false, true), here, 2), [here, points[3], points[4]]);
  // The re-route and its way back use the same kept points (guides dropped, the skipped stop left out).
  const rideSrc = src("../RideMode.tsx");
  assert.match(rideSrc, /const keptPoints = replanKept\(modelRef\.current, current\.progressM \?\? 0, plan\.current\.points, plan\.current\.loop, true\)\.filter\(\(i\) => i !== skip\);/);
  assert.match(rideSrc, /const kept = keptPoints;/);
});

test("a named stop is cued, said and drawn by its name; the stops ahead are drawn while riding, via points never", () => {
  const { route, points, vias } = ride();
  const model = rideModel(route, vias, new Map([[2, "Union Market"]]));
  const stop = model.cues.find((c) => c.kind === "stop");
  assert.equal(stop?.text, "Stop 1, Union Market.");
  assert.equal(stop && cueSpoken(stop, "arrive", 0), "You have reached stop 1, Union Market.");
  assert.deepEqual(stopsAhead(model, 0, points), [{ point: points[2], index: 2, number: 1 }]);
  assert.deepEqual(stopsAhead(model, 1000, points), [], "reached, it is no longer drawn");
  const mark = { point: points[2], number: 1, name: "Union Market" };
  assert.deepEqual(rideStopLabel(mark), { text: "1", said: "Stop 1, Union Market" });
  assert.equal(nextStopLine(mark), "Next stop: Stop 1, Union Market");
  assert.equal(skippingSaid(mark), "Skipping Stop 1, Union Market. Finding a new route.");
  assert.equal(insteadName("Water fountain", mark), "Go to Water fountain instead of stop 1, Union Market");
  assert.equal(detourButtonName("Water or restroom", mark), "Detour: water or restroom, or change stop 1");
  assert.equal(detourButtonName("Water or restroom", null), "Detour: water or restroom");
  // A course names the stop on the unit.
  const course = compileCourse(route, deviceProfile("garmin-edge"), "fit", vias, new Map([[2, "Union Market"]]));
  assert.ok(course.cues.some((c) => c.type === "stop" && c.name.startsWith("Union")));
});

test("the map: a Ctrl+click asks for a stop, a stop's menu names it, and the ride draws its stops by name", () => {
  const map = src("../MapView.tsx");
  assert.match(map, /const modified = \(event\.originalEvent as MouseEvent\)\.ctrlKey \|\| \(event\.originalEvent as MouseEvent\)\.metaKey;/);
  assert.match(map, /stopAt\(point\);\s*return;\s*\}\s*runClick\(/);
  assert.match(map, /renamer\.textContent = renameLabel\(VIA_MARKS\.nameOf\(point\) !== undefined\);/);
  assert.match(map, /label\.className = "ride-stop-name";/);
  const app = src("../App.tsx");
  // The road panel's Add as stop asks for the name first; Route through this trail is still a via point at once.
  assert.match(app, /onPlace=\{\(choice, point, asVia\) => \(choice === "via" && !asVia \? askStopAt\(point\) : placeSpot\(choice, point, asVia\)\)\}/);
  assert.match(app, /rideStops=\{riding \? \(rideView\?\.stops \?\? null\) : null\}/);
  // A ride stop's name is 20 px in the app's font, as the ride's street names are.
  assert.match(src("../styles.css"), /\.ride-stop-name \{\s*font: 700 20px\/1\.2 var\(--font\);/);
});

test("the page's marks: a place picked as a stop keeps its name", () => {
  const stop = VIA_MARKS.named([-77.01, 38.9], "Water fountain");
  assert.equal(VIA_MARKS.nameOf(stop), "Water fountain");
  assert.match(src("../App.tsx"), /placeSpot\("via", point, false, waterTitle\(item\.point\)\)/);
});

test("a saved file reopened on its kept points keeps their stops, vias and names", () => {
  const filePoints = [p(-77.0), p(-77.01), p(-77.03)];
  const keptPoints = [p(-77.0), p(-77.01), p(-77.02), p(-77.03)];
  const plan = { points: filePoints, pointNames: ["Start", "A", "End"], preset: null, notes: [], reference: [], referenceM: 0, source: "route" } as unknown as ImportedPlan;
  const answer = { follows_exactly: false } as unknown as RouteResponse;
  const kept = asKept(plan, { points: keptPoints, preset: "default", dials: decodePlan("#preset=default").dials, vias: [1], names: new Map([[2, "Bakery"]]) }, answer);
  const kinds = importedKinds(kept.pointNames, keptPoints.length);
  assert.deepEqual(kinds.vias, [1]);
  assert.deepEqual([...kinds.names], [[2, "Bakery"]]);
});

test("a stop added by search keeps the place's name; a loop's last stop keeps its name in files and courses", () => {
  const app = src("../App.tsx");
  assert.match(app, /addStopWhereShortest\(current, VIA_MARKS\.named\(\[point\[0\], point\[1\]\], name\), loop\)/);
  assert.match(app, /if \(choice === "via"\) VIA_MARKS\.named\(p, name\);/);
  const panel = src("../GpxPanel.tsx");
  assert.match(panel, /stopNames\(routedPoints, VIA_MARKS\.nameOf, VIA_MARKS\.isVia, loop\)/);
  assert.equal(panel.match(/VIA_MARKS\.isVia, route\.loop != null\)/g)?.length, 3);
  const ride = src("../RideMode.tsx");
  assert.equal(ride.match(/VIA_MARKS\.isVia, plan\.current\.loop\)/g)?.length, 2);
  // A route everyone shares offers no Skip or Instead, so its Detour button does not name them.
  assert.match(ride, /detourButtonName\(DETOUR_SUMMARY, fixed \? null : nextStop\)/);
});
