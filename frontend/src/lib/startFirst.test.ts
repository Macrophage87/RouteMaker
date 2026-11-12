// A ride started away from its start (Stephen, 2026-11-06: "If you start a route and aren't near the starting point,
// the starting point will be the first stop"): navigate.ts startsAway decides, rejoin.ts toStartRoute builds the route,
// RideMode.tsx rideToStart asks for it at the first fix.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { START_NEAR_M, rideModel, startsAway } from "./navigate.ts";
import { toStartRoute } from "./rejoin.ts";
import { plannedStopNumbers } from "./pointKinds.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);

/** A point `east` and `north` metres from the origin. */
function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

function stretch(from: number, to: number, street: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street, tier: 1, facility: null, turn: null, text: street, ...extra };
}

function stop(atM: number, via: number): DescriptionEntry {
  return { ...stretch(atM, atM, `Stop ${via}`), kind: "via", via, street: null };
}

function route(coordinates: LonLat[], description: DescriptionEntry[], extra: Partial<RouteResponse> = {}): RouteResponse {
  const distance = description.reduce((m, e) => Math.max(m, e.to_m), 0);
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates },
    distance_m: distance,
    duration_s: distance / 5,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [coordinates.length - 1],
    description,
    stress_spans: [],
    ...extra,
  } as RouteResponse;
}

/** East 1,000 m on A Street, then left (north) 1,000 m on B Street, a stop at 1,500 m. */
function planned(): RouteResponse {
  return route(
    [at(0, 0), at(500, 0), at(1000, 0), at(1000, 500), at(1000, 1000)],
    [
      stretch(0, 1000, "A Street"),
      stretch(1000, 2000, "B Street", { turn: { movement: "left", onto: "B Street", control: "signal", severity: null } }),
      stop(1500, 1),
    ],
    { leg_ends: [3, 4], leg_arrival_sides: ["right", null] },
  );
}

/** From 300 m north of a point 400 m west of the start: south on Side Street, then left onto A Street to the start. */
function toStart(): RouteResponse {
  return route(
    [at(-400, 300), at(-400, 0), at(0, 0)],
    [stretch(0, 300, "Side Street"), stretch(300, 700, "A Street", { turn: { movement: "left", onto: "A Street", control: "stop", severity: null } })],
    { arrival_side: "left" },
  );
}

const fix = (point: LonLat, accuracyM = 10) => ({ point, accuracyM, at: 0, speedMs: null, headingDeg: null });

test("away from the start: more than START_NEAR_M from it and off the line", () => {
  const model = rideModel(planned());
  assert.equal(START_NEAR_M, 200);
  // At the start, or a block from it off the line: the ride starts there as before.
  assert.equal(startsAway(model, fix(at(0, 0))), false);
  assert.equal(startsAway(model, fix(at(-150, 0))), false);
  // On the line part way along (joined the route): followed from there, with the stops behind asked about.
  assert.equal(startsAway(model, fix(at(700, 5))), false);
  // At home, a few blocks away and off the line: the start comes first.
  assert.equal(startsAway(model, fix(at(-400, 300))), true);
  // Beside the line part way along, but well off it: the start comes first too.
  assert.equal(startsAway(model, fix(at(600, 300))), true);
  // A poor fix decides nothing.
  assert.equal(startsAway(model, fix(at(-400, 300), 80)), false);
});

test("the way to the start, then the whole planned route: the start is point 1, a stop, the plan's stop after it", () => {
  const joined = toStartRoute(toStart(), planned(), 3, false);
  const vias = (joined.description ?? []).filter((e) => e.kind === "via");
  assert.deepEqual(vias.map((v) => [v.via, Math.round(v.from_m)]), [[1, 700], [2, 2200]]);
  // The start's side is the way there's own; the plan's stop keeps its own under its new number.
  assert.deepEqual(joined.leg_arrival_sides, ["left", "right", null]);
  // Numbered as RideMode numbers them: the start stop 1, the plan's stop 1 now stop 2.
  const model = rideModel(joined, [], new Map([[1, "Start"]]), new Map([[1, 1], [2, 2]]));
  const stops = model.cues.filter((c) => c.kind === "stop");
  assert.deepEqual(stops.map((c) => c.text), ["Stop 1, Start. Destination on your left.", "Stop 2. Destination on your right."]);
  assert.ok(Math.abs(stops[0].atM - 700) < 2 && Math.abs(stops[1].atM - 2200) < 2);
  // The planned line follows unchanged, from its start.
  assert.ok(Math.abs(model.lengthM - 2700) < 2);
  assert.equal(joined.geometry.coordinates.length, 3 + 5);
});

test("numbered as RideMode numbers them: the start 1, the plan's stops and a loop's finish one on from their own", () => {
  const plan: LonLat[] = [at(0, 0), at(500, 0), at(1000, 500)];
  const first: LonLat = [plan[0][0], plan[0][1]];
  const points = [at(-400, 300), first, plan[1], plan[2], plan[0]];
  // RideMode stopNumbers: numbered without the start stop, then one on.
  const at1 = points.indexOf(first);
  const numbers = plannedStopNumbers(points.filter((_, i) => i !== at1), plan, () => false);
  const out = new Map<number, number>([[at1, 1]]);
  for (const [i, n] of numbers) out.set(i < at1 ? i : i + 1, n + 1);
  assert.deepEqual([...out].sort((a, b) => a[0] - b[0]), [[1, 1], [2, 2], [3, 3], [4, 4]]);
});

test("a loop: its finish is still its start, one place on", () => {
  const plan = route(planned().geometry.coordinates, [stretch(0, 1000, "A Street"), stop(500, 1), stretch(1000, 2000, "B Street"), stop(2000, 2)]);
  const joined = toStartRoute(toStart(), plan, 2, true);
  assert.deepEqual((joined.description ?? []).filter((e) => e.kind === "via").map((v) => v.via), [1, 2, 3]);
});

test("RideMode asks for the way to the start once, at the first fix, before the rider is placed on the line", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Not on a Bikeshare or transit trip (its walk to the dock), on foot, resumed or after Undo.
  assert.match(ride, /const startChecked = useRef\(!startFirst \|\| !!trip\?\.approach \|\| !!trip\?\.onFoot \|\| resumeStats !== null \|\| resumedPast !== null\)/);
  assert.match(ride, /if \(!startChecked\.current && rideRef\.current\.progressM === null && fix\.accuracyM <= POOR_FIX_M\) \{\s+startChecked\.current = true;\s+if \(startsAway\(modelRef\.current, fix\)\)/);
  // It asks first (Stephen, 2026-11-06: "the option of going to the start or to reroute from there"), said as it opens,
  // and closes by itself once the rider has ridden RESTART_AUTO_M on: to the start if still away from it, else joined.
  assert.match(ride, /setStartAsk\(true\);\s*notify\(`\$\{START_ASK_HEADING\}\$\{fullStop\(\)\} \$\{START_ASK_LEAD\}`\);/);
  assert.match(ride, /haversineM\(fix\.point, startAskedAt\) >= RESTART_AUTO_M\) \{\s*const startAt = plan\.current\.points\[0\];\s*const toward = !!startAt && haversineM\(fix\.point, startAt\) < haversineM\(startAskedAt, startAt\);\s*chooseStartRef\.current\(toward && startsAway\(modelRef\.current, fix\), fix\.point\);/);
  // Go to the start chosen and no way found: said, not silent.
  assert.match(ride, /if \(!found\) \{\s*\/\/ The rider asked for it[^\n]*\n\s*const said = [^;]+;\s*setReplanNote\(said\);\s*\/\/[^\n]*\n\s*sayDetour\(said === REPLAN_NO_SIGNAL \? noSignalSaid\(wayBack\(modelRef\.current, rideRef\.current\)\) : said\);\s*return false;/);
  // Join from here: the ride goes on as any ride off its line, with Already done? asked as usual.
  assert.match(ride, /if \(!start \|\| !here\) \{\s*toStartAsking\.current = false;\s*return;\s*\}/);
  const dialog = readFileSync(new URL("../StartFirstDialog.tsx", import.meta.url), "utf8");
  // Go to the start takes the focus, and Escape is Go to the start.
  assert.match(dialog, /startRef\.current\?\.focus\(\)/);
  assert.match(dialog, /event\.preventDefault\(\);\s*onChoose\(true\);/);
  // The planned route itself is kept after the way there (a chosen route, a file, a group's line).
  assert.match(ride, /toStartRoute\(found, routeRef\.current, was\.points\.length, was\.loop\)/);
  // The start is stop 1 and the plan's stops one on.
  assert.match(ride, /const out = new Map<number, number>\(\[\[at, 1\]\]\);\s*for \(const \[i, n\] of numbers\) out\.set\(i < at \? i : i \+ 1, n \+ 1\);/);
  // Near the start on the way there (any entrance of a big place): the planned route again, from where the rider is.
  assert.match(ride, /beforeStart\.current = \{ route: routeRef\.current, plan: was, asked \};/);
  assert.match(ride, /haversineM\(fix\.point, startWas\) <= START_NEAR_M\) \{\s*startReachedRef\.current\(\);/);
  // Skipped, passed or a detour put before it: the way there is over, never restored later (a loop's finish).
  assert.match(ride, /if \(startWas && startStop\.current && plan\.current\.points\[1\] !== startStop\.current\) beforeStart\.current = null;/);
  // A re-plan under way is dropped, and Already done? asked as on any ride begun here.
  assert.match(ride, /autoReplan\.current = null;\s*replanTicket\.current \+= 1;\s*setReplanning\(false\);[^\n]*\n[^\n]*\n\s*restartAsked\.current = back\.asked;/);
  assert.match(ride, /plan\.current = back\.plan;[\s\S]{0,200}modelRef\.current = modelOf\(back\.route, back\.plan\.points\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // Only Start ride sets it: not Ride the rest, Roam's detour or Resume.
  assert.match(app, /startFirst: !rest, kept,/);
  assert.match(app, /kept: true, startFirst: false,/);
});
