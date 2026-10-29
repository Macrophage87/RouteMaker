// Stops and via points (Stephen 2026-10-24): via points the default, a stop asks for a name, a re-route treats via
// points as guides and stops as mandatory, stops shown while riding, a file's named points are stops.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { planPointNames, writeGpx } from "./gpx.ts";
import {
  REPLAN_FAILED,
  REPLAN_FOUND,
  REPLAN_UTURN,
  REPLAN_REACH_FACTOR,
  VIA_SKIP_EXTRA_S,
  cueSpoken,
  replanFromM,
  replanKept,
  replanTold,
  rideModel,
  skippableVia,
  stopsAhead,
  viaSkipWorth,
  viaSkippedNote,
} from "./navigate.ts";
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
import {
  RESTART_AUTO_M,
  RESTART_AUTO_SAID,
  detourButtonName,
  insteadName,
  skipStopName,
  restartKept,
  restartReplanSaid,
  restartSaid,
  restartStops,
  restartUnchanged,
  skippingSaid,
  withoutStop,
} from "./rideStops.ts";

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
  assert.match(src("../App.tsx"), /\}, \[points, preset, dials, namesVersion, groupSecret\]\);/);
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
  assert.match(src("./offlineRoutes.ts"), /encodePlan\(points, preset, dials, vias, undefined, new Map\(\), "p"\)/);
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

/** `east` metres along and `north` metres off the line. */
const off = (east: number, north: number): LonLat => [at(east)[0], LAT + north / M_PER_DEG];

test("a re-route keeps every stop and via point still ahead, close or not (only the next via may be skipped)", () => {
  const { route, points, vias } = ride();
  const model = rideModel(route, vias);
  // 100 m along: the via at 300 m is close ahead and kept, with the stop at 1,000 m and the via at 2,000 m.
  assert.deepEqual(replanKept(model, 100, points, false), [1, 2, 3, 4]);
  assert.deepEqual(replanKept(model, 900, points, false), [2, 3, 4]);
  assert.deepEqual(replanKept(model, 1500, points, false), [3, 4], "the via at 2,000 m is close ahead and kept");
  // Skip this stop: the re-plan's points without it.
  const here = at(950);
  assert.deepEqual(withoutStop(points, replanKept(model, 900, points, false), here, 2), [here, points[3], points[4]]);
  // The re-route and its way back use the same kept points (the skipped stop left out).
  const rideSrc = src("../RideMode.tsx");
  assert.match(rideSrc, /const fromM = replanFromM\(modelRef\.current, current\.progressM \?\? 0, here\);/);
  assert.match(rideSrc, /: replanKept\(modelRef\.current, current\.progressM \?\? 0, plan\.current\.points, plan\.current\.loop, fromM\)\.filter\(\(i\) => i !== skip\);/);
  assert.match(rideSrc, /const kept = keptPoints;/);
});

test("a rider who rode on beside the line has passed its via points, never its stops, and is measured from there", () => {
  const { route, points, vias } = ride();
  const model = rideModel(route, vias);
  // Left the line at 100 m (Keep going) and rode a parallel street 150 m north to 2,100 m along.
  const fromM = replanFromM(model, 100, off(2100, 150));
  assert.ok(Math.abs(fromM - 2100) < 2);
  // Both via points are behind them now; the stop at 1,000 m they never reached is kept.
  assert.deepEqual(replanKept(model, 100, points, false, fromM), [2, 4]);
  // Back toward the start of the line: never before where they left it.
  assert.equal(replanFromM(model, 1500, off(200, 50)), 1500);
  // Far ahead of where they could have ridden: no further than about 1.5 times the way, as the crow flies.
  assert.ok(replanFromM(model, 100, off(400, 400)) <= 100 + REPLAN_REACH_FACTOR * 500 + 100);
});

// ---- A re-route may leave out the next via point (Stephen 2026-10-27: "Vias can be skipped a little more ... Those
// are guides. Stops are where you want to end up."; "it shouldn't skip all of the vias") -------------------------

/** A new route from the rider to the via point (point 1) and on to the end, due east, at 5 m/s. */
function fresh(viaM: number, endM: number): RouteResponse {
  return {
    ...ride().route,
    geometry: { type: "LineString", coordinates: [at(0), at(viaM), at(endM)] },
    distance_m: endM,
    duration_s: endM / 5,
    leg_ends: [1, 2],
    description: [stretch(0, endM, "A Street"), point(viaM, 1)],
  } as RouteResponse;
}

test("only the next via point may be left out: never a stop, never a via point behind a stop or the end", () => {
  const { route, points, vias } = ride();
  const model = rideModel(route, vias);
  // 1,100 m along: the stop at 1,000 m is passed and the via at 2,000 m is the next point.
  const kept = replanKept(model, 1100, points, false);
  assert.deepEqual(kept, [3, 4]);
  const next = skippableVia(model, kept);
  assert.equal(next?.point, 3);
  assert.ok(Math.abs((next?.atM ?? 0) - 2000) < 2);
  // A stop next: nothing is left out, not the via point after it either.
  assert.equal(skippableVia(model, [2, 3, 4]), null);
  assert.equal(skippableVia(model, [4]), null, "only the end left");
});

test("the via point is left out only where the new route takes more than 5 minutes longer to reach it", () => {
  const { route, vias } = ride();
  const planned = rideModel(route, vias);
  // The planned route: 600 s over 3,000 m, so 180 s from 1,100 m to the via at 2,000 m.
  assert.equal(VIA_SKIP_EXTRA_S, 300);
  // 3,000 m to the via at 5 m/s is 600 s: 420 s longer.
  assert.equal(viaSkipWorth(planned, 1100, 2000, rideModel(fresh(3000, 4000), [1]), 1), true);
  // 2,000 m to it is 400 s: 220 s longer, kept.
  assert.equal(viaSkipWorth(planned, 1100, 2000, rideModel(fresh(2000, 3000), [1]), 1), false);
  // Without the new route's time to it (no via entry), never left out.
  assert.equal(viaSkipWorth(planned, 1100, 2000, rideModel({ ...fresh(3000, 4000), description: [stretch(0, 4000, "A Street")] }, [1]), 1), false);
});

test("a re-route that left out its via point says so first, and the stoker still hears a new route", () => {
  assert.equal(viaSkippedNote(REPLAN_FOUND), "Skipping via point. New route found.");
  assert.equal(viaSkippedNote(REPLAN_UTURN), "Skipping via point. New route found. Make a U-turn.");
  assert.equal(viaSkippedNote(REPLAN_FAILED), REPLAN_FAILED, "no route, nothing skipped to say");
  assert.equal(replanTold(false, "stoker", viaSkippedNote(REPLAN_FOUND)), "say");
  assert.equal(replanTold(false, "quiet", viaSkippedNote(REPLAN_FOUND)), "quiet");
});

test("Ride mode asks again without the via point only when that trips, and not for a detour, a check, a restart or Calmer", () => {
  const replan = src("../RideMode.tsx").slice(src("../RideMode.tsx").indexOf("const replan = useCallback("));
  assert.match(replan, /const next = result\.ok && !via && !check && !done && !eased \? skippableVia\(modelRef\.current, keptPoints\) : null;/);
  assert.match(
    replan,
    /if \(result\.ok && next && viaSkipWorth\(modelRef\.current, fromM, next\.atM, modelOf\(result\.route, points\), 1\) && !voided\(\)\) \{\s*const without = points\.filter\(\(_, i\) => i !== 1\);\s*const again = await ask\(without\);/,
  );
  assert.match(replan, /if \(skippedVia\) note = viaSkippedNote\(note\);/);
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
  assert.equal(skipStopName(mark), "Skip stop 1, Union Market");
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
  assert.match(app, /onPlace=\{\(choice, point, asVia\) =>\s*choice === "end" && mode === "go" && points\.length === 0 \? goRouteHere\(point\) : choice === "via" && !asVia \? askStopAt\(point\) : placeSpot\(choice, point, asVia\)\s*\}/);
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

// ---- Restarting part way (Stephen 2026-10-24: "let people pick the stops that are already done, with the logical
// defaults selected and continue the rest") ----------------------------------------------------------------------

/** Start, stop 1 at 1,000 m, a via at 1,500 m, stop 2 at 2,000 m, end at 3,000 m, due east. */
function twoStops(): { route: RouteResponse; points: LonLat[]; vias: number[] } {
  const points = [at(0), at(1000), at(1500), at(2000), at(3000)];
  const route = {
    ...ride().route,
    description: [stretch(0, 3000, "A Street"), point(1000, 1), point(1500, 2), point(2000, 3)],
  } as unknown as RouteResponse;
  return { route, points, vias: [2] };
}

test("restarting part way lists every stop, the ones behind ticked; none behind asks nothing", () => {
  const { route, vias } = twoStops();
  const model = rideModel(route, vias, new Map([[1, "Union Market"]]));
  assert.equal(restartStops(model, 0), null, "at the start: nothing to ask");
  assert.equal(restartStops(model, 900), null, "short of stop 1");
  const stops = restartStops(model, 1600);
  assert.deepEqual(stops, [
    { index: 1, number: 1, name: "Union Market", passed: true },
    { index: 3, number: 2, passed: false },
  ]);
  assert.equal(restartSaid(stops!), "You are part way along. 1 stop is marked done. Continue to ride the rest.");
  // The defaults ride on unchanged; untick stop 1 and it is planned again, back to it.
  assert.equal(restartUnchanged(stops!, new Set([1])), true);
  assert.equal(restartUnchanged(stops!, new Set()), false);
  assert.equal(restartReplanSaid(stops!, new Set()), "Finding a route back to Stop 1, Union Market.");
  assert.equal(restartReplanSaid(stops!, new Set([1, 3])), "Finding a new route for the stops left.");
});

test("Already done? left unanswered closes with the stops as marked once the rider has ridden 200 m on, and says so", () => {
  assert.equal(RESTART_AUTO_M, 200);
  assert.equal(RESTART_AUTO_SAID, "Riding on with the stops as marked.");
  const ride = src("../RideMode.tsx");
  assert.match(ride, /restartOpen\.current = true;\s*restartAt\.current = fix\.point;\s*setRestart\(named\);/);
  // Checked before re-routing is weighed on the same fix, so re-routing runs again at once.
  const onFix = ride.slice(ride.indexOf("const onFix = useCallback("));
  assert.match(
    onFix,
    /if \(restartOpen\.current && askedAt && fix\.accuracyM <= POOR_FIX_M && haversineM\(fix\.point, askedAt\) >= RESTART_AUTO_M\) \{\s*restartOpen\.current = false;\s*restartAt\.current = null;\s*setRestart\(null\);\s*notify\(RESTART_AUTO_SAID\);\s*\}\s*const auto = /,
  );
});

test("a restart's re-plan keeps the unticked stops, behind or not, and only the via points ahead", () => {
  const { route, points, vias } = twoStops();
  const model = rideModel(route, vias);
  // 1,600 m along, past the via at 1,500 m: stop 1 unticked is gone back to; the passed via is dropped.
  assert.deepEqual(restartKept(model, 1600, points, false, new Set()), [1, 3, 4]);
  assert.deepEqual(restartKept(model, 1600, points, false, new Set([1])), [3, 4]);
  // A stop ahead ticked as done is skipped too.
  assert.deepEqual(restartKept(model, 1600, points, false, new Set([1, 3])), [4]);
  // Short of the via, it stays.
  assert.deepEqual(restartKept(model, 1200, points, false, new Set([1])), [2, 3, 4]);
  // A loop ends at its start.
  assert.deepEqual(restartKept(model, 1600, points, true, new Set([1])), [3, 4, 0]);
});

test("the ride asks once, at its first place on the line, never after Undo or on a trip's leg; picks re-plan from here", () => {
  const rideSrc = src("../RideMode.tsx");
  assert.match(rideSrc, /const restartAsked = useRef\(resumeStats !== null \|\| trip !== null\);/);
  assert.match(rideSrc, /if \(!restartAsked\.current && out\.state\.progressM !== null\) \{\s*restartAsked\.current = true;/);
  assert.match(rideSrc, /if \(!stops \|\| restartUnchanged\(stops, done\)\) return;/);
  assert.match(rideSrc, /void replan\(here, undefined, true, back, false, undefined, done\);/);
  assert.match(rideSrc, /<RestartStopsDialog stops=\{restart\} onContinue=\{continueRestart\} \/>/);
  // Escape keeps the ticks as they are; Continue has the focus.
  const dialogSrc = src("../RestartStopsDialog.tsx");
  assert.match(dialogSrc, /onCancel=\{\(event\) => \{\s*event\.preventDefault\(\);\s*onContinue\(done\);/);
  assert.match(dialogSrc, /continueRef\.current\?\.focus\(\);/);
});
