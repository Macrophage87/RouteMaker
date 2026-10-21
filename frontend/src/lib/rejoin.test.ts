// The way back to the planned route when a re-plan finds none (lib/rejoin.ts; the owner, 2026-10-17).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse, RouteResult, StressSpan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { REPLAN_REJOIN, replanKept, replanPoints, replanTold, rideModel } from "./navigate.ts";
import { REJOIN_AHEAD_M, joinRoutes, rejoinTargets, startsWayBack, triesWayBack, wayBackRoute } from "./rejoin.ts";
import { usableSpans } from "./routeColours.ts";

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

function span(from: number, to: number, tier: number): StressSpan {
  return { from_m: from, to_m: to, tier, facility: null };
}

function route(coordinates: LonLat[], description: DescriptionEntry[], spans: StressSpan[], extra: Partial<RouteResponse> = {}): RouteResponse {
  const distance = description.length ? description[description.length - 1].to_m : 0;
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
    stress_spans: spans,
    ...extra,
  } as RouteResponse;
}

/** East 1,000 m on A Street, then left (north) 1,000 m on B Street. */
function planned(): RouteResponse {
  return route(
    [at(0, 0), at(500, 0), at(1000, 0), at(1000, 500), at(1000, 1000)],
    [
      stretch(0, 1000, "A Street"),
      stretch(1000, 2000, "B Street", { turn: { movement: "left", onto: "B Street", control: "signal", severity: null } }),
    ],
    [span(0, 1000, 1), span(1000, 2000, 3)],
  );
}

/** The way back: from 200 m north of A Street, south on a side street, then left onto A Street. */
function leg(to: number): RouteResponse {
  return route(
    [at(600, 200), at(600, 0), at(to, 0)],
    [
      stretch(0, 200, "Side Street"),
      stretch(200, 200 + (to - 600), "A Street", { turn: { movement: "left", onto: "A Street", control: "stop", severity: null } }),
    ],
    [span(0, 200, 2), span(200, 200 + (to - 600), 1)],
  );
}

const close = (a: number, b: number, tol = 2) => assert.ok(Math.abs(a - b) <= tol, `${a} is not about ${b}`);

test("the way back aims a little past the line's nearest point ahead of the rider, then further along, never past the end", () => {
  const model = rideModel(planned());
  // Off A Street at 300 m along, now 200 m north of its 600 m mark.
  const targets = rejoinTargets(model, 300, at(600, 200));
  assert.deepEqual(targets.map((t) => Math.round(t.atM)), [600 + REJOIN_AHEAD_M, 1200, 2000]);
  close(targets[1].point[0], at(1000, 200)[0], 1e-6);
  // Nothing ahead: nothing to aim for.
  assert.deepEqual(rejoinTargets(model, model.lengthM, at(600, 200)), []);
});

test("the way back never aims past a stop not yet reached, so none is skipped", () => {
  const withStop = route(
    planned().geometry.coordinates,
    [...(planned().description ?? []), { ...stretch(1500, 1500, "Stop 1"), kind: "via", via: 1, street: null }],
    planned().stress_spans ?? [],
  );
  const targets = rejoinTargets(rideModel(withStop), 300, at(1200, 1600));
  assert.ok(targets.length > 0);
  assert.ok(targets.every((t) => t.atM <= 1500.01), JSON.stringify(targets));
});

test("joined: the way back, its turn onto the route, then the planned route from there with its own turns", () => {
  const joined = joinRoutes(leg(700), planned(), 700, new Map());
  const line = joined.geometry.coordinates;
  assert.deepEqual(line[0], at(600, 200));
  assert.deepEqual(line[line.length - 1], at(1000, 1000));
  close(joined.distance_m, 300 + 1300);
  const model = rideModel(joined);
  close(model.lengthM, 1600);
  const turns = model.cues.filter((c) => c.kind === "turn");
  assert.deepEqual(turns.map((c) => c.street), ["A Street", "B Street"]);
  close(turns[0].atM, 200);
  // B Street's left turn: 300 m of A Street ridden after joining it at 700 m.
  close(turns[1].atM, 600);
  // Joined part way along A Street: the planned route's turn onto it is not said again.
  const a = (joined.description ?? []).filter((e) => e.street === "A Street");
  assert.equal(a[a.length - 1].turn, null);
  // A stretch the planned route turned onto, joined part way: its turn and its words both go.
  const turnedOnto = joinRoutes(leg(1200), planned(), 1200, new Map());
  const b = (turnedOnto.description ?? []).find((e) => e.street === "B Street");
  assert.equal(b?.turn, null);
  assert.equal(b?.text, "Continue on B Street.");
  assert.equal(model.cues[model.cues.length - 1].kind, "end");
});

test("joined: the stress sections meet end to end over the whole line, the way back's then the planned route's", () => {
  const joined = joinRoutes(leg(700), planned(), 700, new Map());
  assert.ok(usableSpans(joined.stress_spans));
  const spans = joined.stress_spans ?? [];
  assert.deepEqual(spans.map((s) => s.tier), [2, 1, 1, 3]);
  close(spans[spans.length - 1].to_m, 1600);
  close(spans[2].from_m, 300);
  close(spans[3].from_m, 600);
});

test("joined: the stops ahead keep their places and take their numbers in the new plan's points", () => {
  // Start, stop 1 at 500 m (passed), stop 2 at 1,500 m, end.
  const points: LonLat[] = [at(0, 0), at(500, 0), at(1000, 500), at(1000, 1000)];
  const description: DescriptionEntry[] = [
    stretch(0, 1000, "A Street"),
    { ...stretch(500, 500, "Stop 1"), kind: "via", via: 1, street: null },
    stretch(1000, 2000, "B Street", { turn: { movement: "left", onto: "B Street", control: "signal", severity: null } }),
    { ...stretch(1500, 1500, "Stop 2"), kind: "via", via: 2, street: null },
  ];
  const plan = route(planned().geometry.coordinates, description, planned().stress_spans ?? []);
  const model = rideModel(plan);
  const kept = replanKept(model, 600, points, false);
  assert.deepEqual(kept, [2, 3]);
  assert.deepEqual(replanPoints(model, 600, at(600, 200), points, false).slice(1), [points[2], points[3]]);
  const joined = joinRoutes(leg(700), plan, 700, new Map(kept.map((old, i) => [old, i + 1] as const)));
  const vias = (joined.description ?? []).filter((e) => e.kind === "via");
  assert.deepEqual(vias.map((v) => v.via), [1]);
  const stops = rideModel(joined).cues.filter((c) => c.kind === "stop");
  assert.deepEqual(stops.map((c) => c.text), ["Stop 1."]);
  close(stops[0].atM, 1100);
});

test("joined at the very end: the way back alone, with its own arrival side", () => {
  const joined = joinRoutes({ ...leg(1000), arrival_side: "left" }, { ...planned(), arrival_side: "right" }, 2000, new Map());
  assert.deepEqual(joined.geometry.coordinates, leg(1000).geometry.coordinates);
  assert.equal(joined.arrival_side, "left");
  assert.ok(usableSpans(joined.stress_spans));
});

test("the way back tries the next point when one cannot be reached, and stops at no signal or a slow-down", async () => {
  const plan = planned();
  const model = rideModel(plan);
  const asked: LonLat[][] = [];
  const noRoute: RouteResult = { ok: false, error: { kind: "no-route", status: 422, title: "", message: "" } };
  const found = await wayBackRoute(plan, model, 300, at(600, 200), [1], async (points) => {
    asked.push(points);
    // Across to B Street, 200 m up it.
    return asked.length === 1 ? noRoute : { ok: true, route: route([at(600, 200), at(1000, 200)], [stretch(0, 400, "Cut Through")], [span(0, 400, 2)]) };
  });
  assert.equal(asked.length, 2);
  assert.deepEqual(asked[0][0], at(600, 200));
  assert.ok("route" in found);
  // Joined at the second target, 1,200 m along: then the last 800 m of B Street.
  close(rideModel(found.route).lengthM, 400 + 800);

  let tries = 0;
  const none = await wayBackRoute(plan, model, 300, at(600, 200), [1], async () => {
    tries += 1;
    return { ok: false, error: { kind: "network", status: 0, title: "", message: "" } };
  });
  assert.deepEqual(none, { failed: "network" });
  assert.equal(tries, 1);
  // Ended or kept to the planned route: no more tries.
  let after = 0;
  const cancelled = await wayBackRoute(plan, model, 300, at(600, 200), [1], async () => {
    after += 1;
    return noRoute;
  }, () => after >= 1);
  assert.deepEqual(cancelled, { failed: "no-route" });
  assert.equal(after, 1);
  assert.equal(startsWayBack("rate-limited"), true, "a long re-plan refused for the long ride's slot");
  assert.equal(startsWayBack("network"), false);
  assert.equal(triesWayBack("network"), false);
  assert.equal(triesWayBack("rate-limited"), false);
  assert.equal(triesWayBack("timed-out"), true);
  assert.equal(triesWayBack("no-route"), true);
});

test("the stoker's level hears that a way back was found, as it hears a new route", () => {
  assert.equal(replanTold(false, "stoker", REPLAN_REJOIN), "say");
  assert.equal(replanTold(false, "quiet", REPLAN_REJOIN), "quiet");
});

test("Ride mode: a re-plan that finds no route asks for the way back, not for a detour, and confirms a long ride", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  const replan = ride.slice(ride.indexOf("const replan = useCallback("), ride.indexOf("// No good fix for a minute"));
  assert.match(replan, /confirmLong: true/);
  assert.match(replan, /if \(!result\.ok && !via && !check && startsWayBack\(result\.error\.kind\) && !voided\(\)\)/);
  assert.match(replan, /await wayBackRoute\(routeRef\.current, modelRef\.current, current\.progressM \?\? 0, here, kept, ask, voided, closed\);/);
  // The ride's closed roads go with every re-plan (v0.8.2).
  assert.match(replan, /blocked: blockedRef\.current/);
  // The no-signal timer runs until the way back settles.
  assert.ok(replan.indexOf("window.clearTimeout(timer);") > replan.indexOf("await wayBackRoute("));
  assert.match(replan, /setReplanNote\(note\);\s*tell\(note\);/);
});

test("the way back joins past a road the rider marked closed, never on it (v0.8.2)", () => {
  const model = rideModel(planned());
  // Nearest ahead is about 600 m along; the rider marked closed up to 900 m.
  const targets = rejoinTargets(model, 300, at(600, 200), 900);
  assert.ok(targets.length > 0);
  assert.ok(targets.every((t) => t.atM >= 900 + REJOIN_AHEAD_M - 1));
  // Closed to the end: nowhere to join.
  assert.deepEqual(rejoinTargets(model, 300, at(600, 200), model.lengthM), []);
});
