/** A loop has stops after its start and no end (OWNER-DECISIONS 374). */
import assert from "node:assert/strict";
import test from "node:test";
import { MAX_POINTS, addPoint, type LonLat } from "./geo.ts";
import { applyPlace, choiceInForce, choicesFor, defaultChoice, placeEffect, pointRows, searchView } from "./geocode.ts";
import { parseGpx, planPointName, writeGpx } from "./gpx.ts";
import { exportOf } from "./gpxText.ts";
import { loopStops, loopView } from "./loop.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { placeAtStation, stationEdit, stationRoles } from "./railStations.ts";
import { pointName } from "./summary.ts";
import { startDials } from "./dials.ts";
import { namesToKeep, rideAfterImport } from "./gpxEdit.ts";
import { planFromGpx } from "./gpxPlan.ts";

// A west-east line of places, 0.02 degrees (about 1.7 km) apart.
const A: LonLat = [-77.0, 38.9];
const B: LonLat = [-76.98, 38.9];
const C: LonLat = [-76.96, 38.9];
const D: LonLat = [-76.94, 38.9];

test("non-loop addPoint is exactly as before", () => {
  assert.deepEqual(addPoint([A, D], B), [A, B, D]);
  assert.deepEqual(addPoint([A, B], C), [A, C, B]);
  assert.deepEqual(addPoint([A, B], C, false), addPoint([A, B], C));
  assert.deepEqual(addPoint([A], B, true), [A, B]);
});

test("in a loop the closing leg is a slot: a click on the way back is appended, not jammed into the way out", () => {
  // A to B and back: a click past B costs the same on either leg, and the closing leg wins the tie.
  assert.deepEqual(addPoint([A, B], D, true), [A, B, D]);
  assert.deepEqual(addPoint([A, B], D, false), [A, D, B]);
  // A triangle out and around: a click on the closing leg (C back to A) is appended.
  const tri: LonLat[] = [A, B, [-76.98, 38.92]];
  const onWayBack: LonLat = [-76.9902, 38.9102];
  assert.deepEqual(addPoint(tri, onWayBack, true), [...tri, onWayBack]);
  assert.deepEqual(addPoint(tri, onWayBack, false), [A, B, onWayBack, tri[2]], "non-loop: the leg B to C is cheapest");
  // A click beside the way out stays on that leg.
  const beside: LonLat = [-76.99, 38.8995];
  assert.deepEqual(addPoint(tri, beside, true), [A, beside, B, tri[2]]);
});

test("in a loop of a start and one stop, the two legs tie exactly and the click is appended", () => {
  // Off the line A-B, so the tie is not an artefact of collinear points: the
  // closing leg (B back to A) costs exactly what A to B costs, and wins.
  for (const p of [[-76.97, 38.91], [-76.99, 38.885], [-77.01, 38.93]] as LonLat[]) {
    assert.deepEqual(addPoint([A, B], p, true), [A, B, p]);
  }
});

test("in a loop a click on an inner leg still goes into that leg", () => {
  const square: LonLat[] = [A, [-77.0, 38.92], [-76.98, 38.92], [-76.98, 38.9]];
  const onFirstLeg: LonLat = [-77.0002, 38.91];
  assert.deepEqual(addPoint(square, onFirstLeg, true), [square[0], onFirstLeg, ...square.slice(1)]);
});

test("the cap holds in a loop", () => {
  let route: LonLat[] = [A];
  for (let i = 0; i < 40; i += 1) route = addPoint(route, [-77 + i / 1000, 38.9], true);
  assert.equal(route.length, MAX_POINTS);
});

test("names: the first point of a loop is start and finish and no later point is the end", () => {
  assert.equal(pointName(0, 3, true), "Start and finish");
  assert.equal(pointName(1, 3, true), "Stop 1");
  assert.equal(pointName(2, 3, true), "Stop 2");
  assert.equal(pointName(0, 1, true), "Start and finish");
  for (let count = 1; count <= 5; count += 1) {
    for (let i = 0; i < count; i += 1) assert.notEqual(pointName(i, count, true), "End");
  }
  assert.deepEqual([pointName(0, 3), pointName(1, 3), pointName(2, 3)], ["Start", "Stop 1", "End"]);
  assert.deepEqual([planPointName(0, 3), planPointName(2, 3)], ["Start", "End"]);
  assert.deepEqual(
    [planPointName(0, 3, true), planPointName(1, 3, true), planPointName(2, 3, true)],
    ["Start and finish", "Stop 1", "Stop 2"],
  );
});

test("the points list says it too", () => {
  const none = { name: () => undefined };
  assert.deepEqual(pointRows([A, B, C], none, true).map((r) => r.role), ["Start and finish", "Stop 1", "Stop 2"]);
  assert.deepEqual(pointRows([A, B, C], none).map((r) => r.role), ["Start", "Stop 1", "End"]);
});

test("loopStops: chosen and not Mass Ride; an implied loop keeps the usual names", () => {
  assert.equal(loopStops("default", true), true);
  assert.equal(loopStops("default", undefined), false);
  assert.equal(loopStops("default", false), false);
  assert.equal(loopStops("mass-ride", true), false);
});

test("the toggle can be chosen with the start alone, and its hint no longer says end point", () => {
  const view = loopView("default", true, [A])!;
  assert.ok(view.checked && !view.implied);
  assert.doesNotMatch(view.hint, /end point/);
  assert.match(view.hint, /stop/);
  // Off, with the start alone, there is no end point yet to speak of; with two points there is.
  assert.doesNotMatch(loopView("default", undefined, [A])!.hint, /end point/);
  assert.match(loopView("default", undefined, [A, B])!.hint, /end point/);
  assert.equal(loopView("default", true, []), null);
  assert.equal(loopView("mass-ride", true, [A]), null);
  const implied = loopView("default", undefined, [A, B, A])!;
  assert.deepEqual([implied.checked, implied.implied], [true, true]);
});

test("search: in a loop a place is the start or a stop, never the destination", () => {
  assert.deepEqual(choicesFor(1, false, true), ["start", "via"]);
  assert.deepEqual(choicesFor(3, false, true), ["start", "via"]);
  assert.deepEqual(choicesFor(MAX_POINTS, true, true), ["start"]);
  assert.deepEqual(choicesFor(0, false, true), ["start"]);
  assert.equal(defaultChoice(1, true), "via");
  assert.equal(defaultChoice(1), "end");
  assert.equal(choiceInForce("end", 2, false, true), "via");
  assert.equal(placeEffect(1, "via", true), "via");
  assert.equal(placeEffect(2, "end", true), "via");
  assert.equal(placeEffect(2, "start", true), "replace-start");
  assert.deepEqual(applyPlace([A], B, "via", true), [A, B]);
  assert.deepEqual(applyPlace([A, B], D, defaultChoice(2, true), true), [A, B, D]);
  assert.deepEqual(applyPlace([A, B], C, "end"), [A, C]);
  const view = searchView({ query: "x", answered: "", result: null, open: false, pointCount: 2, full: false, chosen: null, loop: true });
  assert.deepEqual([view.choice, view.effect], ["via", "via"]);
});

test("rail stations: a loop offers start and stop, not end", () => {
  assert.deepEqual(stationRoles(1, true), ["start", "via"]);
  assert.deepEqual(stationRoles(3, true), ["start", "via"]);
  assert.deepEqual(stationRoles(MAX_POINTS, true), ["start"]);
  assert.deepEqual(stationRoles(1), ["start", "end"]);
  assert.deepEqual(placeAtStation([A], B, "via", true), [A, B]);
  assert.deepEqual(placeAtStation([A, B], D, "end", true), [A, B]);
  assert.deepEqual(stationEdit([A, B], D, "via", true), { next: [A, B, D], index: 2 });
  assert.deepEqual(stationEdit([A, B], D, "end", true), { refused: "role" });
});

test("the GPX of a chosen loop names its points as a loop, and reads back without those as place names", () => {
  const route = {
    preset: "default",
    distance_m: 10000,
    climb_m: 10,
    descent_m: 10,
    geometry: { type: "LineString" as const, coordinates: [A, B, C, A] },
    attribution: [],
    dials: { stress: 1, hills: 0, when: null, carrying: null, loop: true },
  } as unknown as Parameters<typeof exportOf>[0];
  const xml = writeGpx(exportOf(route, [A, B, C], true));
  assert.match(xml, /<name>Start and finish<\/name>/);
  assert.match(xml, /<name>Stop 2<\/name>/);
  assert.doesNotMatch(xml, /<name>End<\/name>/);
  const plain = writeGpx(exportOf({ ...route, dials: { ...route.dials!, loop: false } }, [A, B, C]));
  assert.match(plain, /<name>End<\/name>/);
  assert.deepEqual(namesToKeep({ points: [A, B], pointNames: ["Start and finish", "Stop 1"] }), []);
});

const names = (xml: string) => [...xml.matchAll(/<rtept [^>]*>\s*<name>([^<]*)<\/name>/g)].map((m) => m[1]);
const loopRoute = {
  preset: "default",
  distance_m: 10000,
  climb_m: 10,
  descent_m: 10,
  geometry: { type: "LineString" as const, coordinates: [A, B, C, A] },
  attribution: [],
  dials: { stress: 40, hills: 50, when: null, carrying: null, loop: true },
} as unknown as Parameters<typeof exportOf>[0];

test("the GPX names its points from the rider's toggle, not the API's echo", () => {
  // A ride that ends on its start with the toggle off: the API echoes loop
  // true, the page says Start, Stop 1, End, and so does the file.
  const back: LonLat = [-77.0001, 38.9001];
  const implied = writeGpx(exportOf(loopRoute, [A, B, back], false));
  assert.deepEqual(names(implied), ["Start", "Stop 1", "End"]);
  assert.deepEqual(names(implied), pointRows([A, B, back], { name: () => undefined }, false).map((r) => r.role));
  assert.doesNotMatch(implied, /loop=1/);
  const chosen = writeGpx(exportOf(loopRoute, [A, B, C], true));
  assert.deepEqual(names(chosen), pointRows([A, B, C], { name: () => undefined }, true).map((r) => r.role));
});

test("Mass Ride has no loop in the GPX, whatever the toggle says", () => {
  const mass = writeGpx(exportOf({ ...loopRoute, preset: "mass-ride" }, [A, B, C], true));
  assert.deepEqual(names(mass), ["Start", "Stop 1", "End"]);
  assert.doesNotMatch(mass, /loop=1/);
});

test("a loop survives a GPX export and re-import", () => {
  const xml = writeGpx(exportOf(loopRoute, [A, B, C], true));
  assert.match(xml, /<cmt>routemaker:[^<]*;loop=1<\/cmt>/);
  const plan = planFromGpx(parseGpx(xml));
  assert.equal(plan.dials?.loop, true);
  assert.deepEqual(namesToKeep(plan), [], "the role names are not taken for place names");
  const now = { preset: "default" as const, dials: startDials("default") };
  const ride = rideAfterImport(plan, now);
  assert.equal(ride.dials.loop, true);
  assert.equal(loopStops(ride.preset, ride.dials.loop), true);
  const roles = pointRows(plan.points, { name: () => undefined }, true).map((r) => r.role);
  assert.deepEqual(roles, ["Start and finish", "Stop 1", "Stop 2"]);
  // A one-way export opens one-way, even with the loop on before the import.
  const oneWay = planFromGpx(parseGpx(writeGpx(exportOf(loopRoute, [A, B, C], false))));
  const looped = { preset: "default" as const, dials: { ...startDials("default"), loop: true } };
  assert.notEqual(rideAfterImport(oneWay, looped).dials.loop, true);
});

test("share links: loop with a start and a stop round-trips, and an old hash decodes as before", () => {
  const dials = { ...startDials("default"), loop: true };
  const back = decodePlan(encodePlan([A, B], "default", dials));
  assert.deepEqual(back.points, [A, B]);
  assert.equal(back.dials.loop, true);
  const old = decodePlan(encodePlan([A, B, A], "default", startDials("default")));
  assert.ok(!old.dials.loop);
  assert.equal(old.points.length, 3);
});
