// Ride's re-plans and re-routes, after the hunt for hidden causes of bad routing (2026-11-08): what a re-plan sends
// (R3 share-bike fields, V6 the way back's arrival, V1 a loop's shape), when dirt opens (V5),
// where a half step is said (X4), Best order's via points (V3) and the crossing search's line below the top (S6, in
// summary.test.ts). Each test says what was before and pins what is now.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { DescriptionEntry, RouteResponse, RouteResult, StressSpan } from "./api.ts";
import { routeRequestBody } from "./api.ts";
import { dialFields, startDials } from "./dials.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { LOOP_SHAPE_MIN_M, endsOnStart, loopShapePoint, onHalfStep, rideModel, shapesHome } from "./navigate.ts";
import { isRoundTrip } from "./loop.ts";
import { ViaMarks, VIA_MARKS, stopsOnly, withVias, withViasOnLegs } from "./pointKinds.ts";
import { REJOIN_ONWARD_M, rejoinTargets, rejoinsFirst, wayBackRoute } from "./rejoin.ts";
import { DIRT_RIDDEN_M, SHARE_BIKE, legDials, rideNowDials, rodeDirt, shareBikeOf } from "./rideTrip.ts";
import { VIA_LEGS_KEPT_SAID, applyAnswer, type StopOrder } from "./stopOrder.ts";
import { keepLeftRide, leftRide } from "./rideResume.ts";

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

function span(from: number, to: number, tier: number, extra: Partial<StressSpan> = {}): StressSpan {
  return { from_m: from, to_m: to, tier, facility: null, ...extra };
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
    [stretch(0, 1000, "A Street"), stretch(1000, 2000, "B Street", { turn: { movement: "left", onto: "B Street", control: "signal", severity: null } })],
    [span(0, 1000, 1), span(1000, 2000, 3)],
  );
}

const close = (a: number, b: number, tol = 2) => assert.ok(Math.abs(a - b) <= tol, `${a} is not about ${b}`);

// ---- R3: a share-bike or transit leg's requests on its plain ride type ---------------------------------------------

test("a share-bike leg's re-plan sends no Bikeshare fields on its plain ride type, and keeps the share bike's pace", () => {
  const plan = { ...startDials("bikeshare", null, null, false, "classic"), pickupStation: "s1", dropoffStation: "s2", ridingSpeedKmh: 26 };
  // Before: the plan's dials as they were, which the API refuses on "default" with a 422 (core/api.py: "bike, ending,
  // pickup_station and dropoff_station apply to Bikeshare and Rebalance Ride only").
  const before = JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "default", { dials: { ...plan, loop: false }, rideReplan: true }));
  assert.equal(before.bike, "classic");
  const body = JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "default", { dials: legDials({ ...plan, loop: false }, "default", "classic"), rideReplan: true }));
  for (const field of ["bike", "ending", "pickup_station", "dropoff_station", "novice_legs", "transit_option"]) assert.equal(body[field], undefined, field);
  // The share bike's own pace and weight (core.presets BIKESHARE_BIKES), not the rider's own bike's 26 km/h.
  assert.equal(body.cycling_speed_kmh, 13);
  assert.equal(body.system_weight_kg, 100);
  assert.equal(SHARE_BIKE.ebike.speedKmh, 20);
  // Its stress and hills are the plan's.
  assert.equal(body.stress, plan.stress);
  assert.equal(body.hills, plan.hills);
  // The e-bike on the e-bike ride type, at its own pace.
  const ebike = legDials({ ...startDials("bikeshare", null, null, false, "ebike"), loop: false }, "ebike", "ebike");
  assert.equal(ebike.bike, undefined);
  assert.equal(ebike.ridingSpeedKmh, 20);
  assert.equal(ebike.systemWeightKg, 108);
});

test("a transit leg's re-plan leaves out novice_legs and transit_option on its plain ride type; its own ride type keeps them", () => {
  const plan = { ...startDials("bike-transit"), noviceLegs: true, noviceHop: [at(0, 0), at(10, 10)] as [LonLat, LonLat], transitOption: "o1" };
  // Before: novice_legs went with the default ride type's re-plan (core/api.py: "novice_legs applies to the transit ride
  // types with a bike only").
  assert.equal(dialFields(plan).novice_legs, true);
  const plain = dialFields(legDials(plan, "default", null));
  assert.equal(plain.novice_legs, undefined);
  assert.equal(plain.novice_hop, undefined);
  assert.equal(plain.transit_option, undefined);
  // The rider's own bike: no share-bike pace is added.
  assert.equal(plain.cycling_speed_kmh, undefined);
  const own = dialFields(legDials(plan, "bike-transit", null));
  assert.equal(own.novice_legs, true);
  assert.equal(own.transit_option, "o1");
  // A Bikeshare ride asked as Bikeshare keeps its bike; a walk is never given a bike's pace.
  assert.equal(dialFields(legDials(startDials("bikeshare", null, null, false, "ebike"), "bikeshare", "ebike")).bike, "ebike");
  assert.equal(legDials({ ...startDials("bikeshare"), loop: false }, "walk", "classic").ridingSpeedKmh, undefined);
});

test("a ride's re-plan is planned for now, not at the plan's chosen time (hunt 3, R3-1)", () => {
  const plan = { ...startDials("road-bike"), when: "weekend" as const };
  // Before: the plan's "Weekend" went with every re-plan, so a Tuesday ride re-planned on the weekend map.
  assert.equal(dialFields(plan).when, "weekend");
  const body = JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "road-bike", { dials: legDials({ ...plan, loop: false }, "road-bike", null), rideReplan: true }));
  assert.equal(body.when, undefined, "the API works out the time of the ride");
  assert.equal(legDials({ ...plan, when: "weekday_rush" }, "default", null).when, null);
  // The plan's dials are never changed.
  assert.equal(plan.when, "weekend");
});

test("the next leg at a stop, the transit trip's check and Roam's Detour are planned for now too (hunt 3, R3-1)", () => {
  const plan = { ...startDials("road-bike"), when: "weekend" as const, loop: true };
  // Before: nextLeg, checkTrip and roamDetour (App.tsx) sent { ...planDials, loop: false, closuresNow: true }, the plan's "Weekend" with it.
  const body = JSON.parse(routeRequestBody([at(0, 0), at(1000, 0)], "road-bike", { dials: rideNowDials(plan) }));
  assert.equal(body.when, undefined, "the API works out the time of the ride");
  const dials = rideNowDials(plan);
  assert.equal(dials.loop, false);
  assert.equal(dials.closuresNow, true);
  assert.equal(plan.when, "weekend");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.ok(app.includes("{ dials: rideNowDials(legDials) }"), "nextLeg goes through rideNowDials");
  assert.ok(app.includes("{ dials: { ...rideNowDials(planDials), transitOption: key } }"), "checkTrip goes through rideNowDials");
  assert.ok(app.includes(": rideNowDials(planDials);"), "Roam's Detour goes through rideNowDials");
  // The one ride request left that builds its own one-way dials goes through legDials, which drops `when` too.
  assert.equal(app.split("loop: false, closuresNow: true").length - 1, 1, "no other ride request builds its own dials");
});

test("the share bike a leg is on: the plan's dial, the plan's answer, or Bikeshare + transit's classic bike", () => {
  const base = planned();
  assert.equal(shareBikeOf(base, { bike: "ebike" }), "ebike");
  assert.equal(shareBikeOf({ ...base, bikeshare: { bike: "ebike" } as RouteResponse["bikeshare"] }, {}), "ebike");
  assert.equal(shareBikeOf({ ...base, preset: "bikeshare-transit" as RouteResponse["preset"] }, {}), "classic");
  assert.equal(shareBikeOf({ ...base, preset: "bike-transit" as RouteResponse["preset"] }, {}), null);
  assert.equal(shareBikeOf(base, {}), null);
});

test("Ride's re-plans, nearest searches and Ride the rest fit the dials to the leg's ride type", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const legBike = useRef\(shareBikeOf\(plannedRoute, dials\)\)\.current;/);
  assert.match(ride, /requestRoute\(to, preset, \{ dials: legDials\(\{ \.\.\.dialsRef\.current, loop: false \}, preset, legBike\)/);
  assert.doesNotMatch(ride, /requestNearest\(from, places, preset, \{ \.\.\.dialsRef\.current, loop: false \}\)/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const restDials = legDials\(\{ \.\.\.planDials, loop: false, closuresNow: true \}, asked\.preset, shown \? shareBikeOf\(shown, planDials\) : null\);/);
});

// ---- V5: dirt is opened by riding it, not by a route that rides it ---------------------------------------------------

test("a dirt trail counts as ridden once the rider is placed DIRT_RIDDEN_M into the route's trail stretch, not before", () => {
  // 1,000 m of line over 1,100 traced metres: the trail is 550 to 770 traced, 500 to 700 on the line.
  const dirt = { dirt_trails: true, distance_m: 1050, stress_spans: [span(0, 1100, 1)], trail_levels: [{ from_m: 550, to_m: 770, level: 0 }] };
  // Before: the route's dirt_trails alone opened every dirt trail. Now the rider on the paved part has ridden none.
  assert.equal(rodeDirt(dirt, 1000, 100, 400), false);
  assert.equal(rodeDirt(dirt, 1000, 480, 500 + DIRT_RIDDEN_M - 1), false, "at the trail's start, not yet along it");
  assert.equal(rodeDirt(dirt, 1000, 520, 500 + DIRT_RIDDEN_M + 1), true);
  // Passed over it between two fixes.
  assert.equal(rodeDirt(dirt, 1000, 450, 800), true);
  // On the traced metres unscaled the trail would start at 550 and 540 would be before it; on the line it is 40 m in.
  assert.equal(rodeDirt(dirt, 1000, null, 540), true);
  // No dirt trail its ride type skips, no trail stretches, or not placed: nothing.
  assert.equal(rodeDirt({ ...dirt, dirt_trails: false }, 1000, 520, 600), false);
  assert.equal(rodeDirt({ ...dirt, trail_levels: [] }, 1000, 520, 600), false);
  assert.equal(rodeDirt(dirt, 1000, 520, null), false);
});

test("Ride mode sets dirt ridden from the rider's own ride, never from a route's dirt_trails", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Not set at start but from a Resume's or Keep riding's kept state (the hunt, round 2, R2-5).
  assert.match(ride, /const dirtRidden = useRef\(replans\?\.dirtRidden === true\);/);
  assert.doesNotMatch(ride, /dirt_trails\) dirtRidden\.current = true/);
  assert.match(ride, /if \(!dirtRidden\.current && !out\.state\.off && rodeDirt\(routeRef\.current, modelRef\.current\.lengthM, wasAtM, out\.state\.progressM\)\) \{\s*dirtRidden\.current = true;/);
});

// ---- X4: half steps on the line's scale ------------------------------------------------------------------------------

test("a half step is placed on the line by the spans' own scale, not the description's", () => {
  // 2,000 m of line; the description says 2,000 m, the traced spans 2,200 m (10% more). The half step is 1,100 to
  // 1,650 traced: 1,000 to 1,500 on the line.
  const r = route(planned().geometry.coordinates as LonLat[], planned().description ?? [], [span(0, 1100, 2), span(1100, 1650, 2, { half: true }), span(1650, 2200, 2)]);
  const model = rideModel(r);
  const half = model.halves?.[0];
  assert.ok(half);
  close(half.fromM, 1000);
  close(half.toM, 1500);
  // Before (X4): the description's map put it at 1,100 to 1,650, so 1,050 was not on it and 1,600 was.
  assert.equal(onHalfStep(model, 1050, 2), true);
  assert.equal(onHalfStep(model, 1600, 2), false);
});

// ---- V6: the way back arrives going the line's way ----------------------------------------------------------------

test("the way back goes through its target to a point a little further along the line, and joins there", async () => {
  const plan = planned();
  const model = rideModel(plan);
  const targets = rejoinTargets(model, 300, at(600, 200));
  assert.ok(targets[0].onward);
  close(targets[0].onward.atM, targets[0].atM + REJOIN_ONWARD_M, 0.01);
  const asked: LonLat[][] = [];
  const found = await wayBackRoute(plan, model, 300, at(600, 200), [1], async (points): Promise<RouteResult> => {
    asked.push(points);
    // Down a side street to A Street at the onward point, 750 m along.
    return { ok: true, route: route([at(600, 200), at(600, 0), at(750, 0)], [stretch(0, 200, "Side Street"), stretch(200, 350, "A Street")], [span(0, 350, 2)]) };
  });
  // Before (V6): [here, target], a plain end the router could reach from ahead. Now three points, the target a via.
  assert.equal(asked[0].length, 3);
  assert.equal(VIA_MARKS.isVia(asked[0][1]), true);
  assert.ok(haversineM(asked[0][1], targets[0].point) < 0.01);
  assert.ok(haversineM(asked[0][2], targets[0].onward.point) < 0.01);
  assert.ok("route" in found);
  // Joined at the onward point: the leg (350 m), then A Street on from 750 m and B Street.
  close(rideModel(found.route).lengthM, 350 + 1250);
  // At a stop or the end there is nothing further to go through to: a plain end, as before.
  const last = rejoinTargets(model, 300, at(1100, 1990));
  assert.ok(last.length > 0 && last[last.length - 1].onward === undefined);
});

test("the way to a ride's start is asked with a moving rider's heading", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  // Before (V6): askRoute([here, start], null, false).
  assert.match(ride, /askRoute\(\[here, start\], rideRef\.current\.goodFix\?\.headingDeg \?\? null, false\)/);
});

// ---- V1: a loop stays a loop through a re-route ----------------------------------------------------------------------

test("a loop's re-route is sent through the middle of its planned way home", () => {
  const model = rideModel(planned());
  // 300 m along a 2,000 m loop: halfway along the 1,700 m left.
  const shape = loopShapePoint(model, 300);
  assert.ok(shape);
  close(shape.atM, 1150, 0.01);
  assert.ok(haversineM(shape.point, at(1000, 150)) < 1);
  // Too little left to be worth a point.
  assert.equal(loopShapePoint(model, 2000 - LOOP_SHAPE_MIN_M + 1), null);
  // A ride whose points end on its start is a loop, as Plan's own test says.
  for (const points of [[at(0, 0), at(500, 0), at(40, 0)], [at(0, 0), at(500, 0), at(60, 0)], [at(0, 0), at(30, 0)]]) {
    assert.equal(endsOnStart(points), isRoundTrip(points), JSON.stringify(points));
  }
});

test("on a loop, an automatic re-route rejoins the loop ahead first, and the plan to the start keeps its shape", () => {
  const none = { asked: false, detour: false, check: false, restart: false, skip: false };
  // Before (V1): a loop on the first route planned a new route to the start first, often the way out again.
  assert.equal(rejoinsFirst({ rank: 1 }, none), false);
  assert.equal(rejoinsFirst({ rank: 1 }, none, true), true);
  assert.equal(rejoinsFirst({ rank: 1 }, { ...none, asked: true }, true), false, "the rider's own ask plans afresh");
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const loopRide = useRef\(plannedLoop \|\| endsOnStart\(plannedPoints\) \|\| replans\?\.loopRide === true\)\.current;/);
  assert.match(ride, /const shape = shapesHome\(\{ loopRide, detour: !!via, restart: !!done, keptPoints: keptPoints\.length, endDrawn \}\) \? loopShapePoint\(modelRef\.current, fromM\) : null;/);
  // Marked as the ride's own, not the rider's (review of this branch: it was a plain via, so a later re-route said
  // "Skipping via point" for it, and End ride left it in Plan).
  assert.match(ride, /const left = shape \? \[keptLeft\[0\], VIA_MARKS\.shape\(\[shape\.point\[0\], shape\.point\[1\]\]\), \.\.\.keptLeft\.slice\(1\)\] : keptLeft;/);
  // A way back rides the planned loop ahead, so its points are the kept ones, without the shape point.
  assert.equal((ride.match(/points = keptLeft;/g) ?? []).length, 2);
  // Left out unsaid, this re-route's or a later one's; a via point the rider placed is said.
  assert.match(ride, /skippedVia = !VIA_MARKS\.isShape\(dropped\);/);
  assert.match(ride, /withoutShapes\(planAfterEnd\(modelRef\.current, rideRef\.current, plan\.current\.points, plan\.current\.loop, Date\.now\(\)\)\)/);
});

test("a loop's shape point is a via point that is never the rider's: not in End ride's plan, still the ride's own after Resume", () => {
  const marks = new ViaMarks();
  const start = at(0, 0);
  const mine = marks.via(at(500, 0));
  const made = marks.shape(at(1000, 500));
  assert.equal(marks.isVia(made), true, "it shapes the route as a via point does");
  assert.equal(marks.isShape(made), true);
  assert.equal(marks.isShape(mine), false);
  const store = new Map<string, string>();
  const memory = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) };
  keepLeftRide({ route: planned(), points: [at(300, 0), mine, made, start], loop: false, preset: "standard", dials: startDials("default"), fixed: false }, marks, 1000, memory);
  const back = new ViaMarks();
  const left = leftRide(back, 2000, memory);
  assert.ok(left);
  assert.equal(back.isShape(left.points[2]), true);
  assert.equal(back.isVia(left.points[2]), true);
  assert.equal(back.isShape(left.points[1]), false);
  assert.equal(back.isVia(left.points[1]), true);
});

// ---- V3: Best order keeps via points on their legs ---------------------------------------------------------------

test("Best order keeps each via point on the leg it shapes, the other way round where the leg is ridden back", () => {
  const marks = new ViaMarks();
  const start = at(0, 0);
  const v1 = marks.via(at(100, 0));
  const a = at(200, 0);
  const b = at(300, 0);
  const v2 = marks.via(at(400, 0));
  const end = at(500, 0);
  const split = stopsOnly([start, v1, a, b, v2, end], marks.isVia);
  // Before (V3): v1 went with a wherever a went, so S, B, v1, A rode v1 from B.
  assert.deepEqual(withVias([0, 2, 1, 3], split), [start, b, v1, a, v2, end]);
  // Swapping a and b splits both legs with via points: not taken.
  assert.equal(withViasOnLegs([0, 2, 1, 3], split), null);
  // The same order: as it was.
  assert.deepEqual(withViasOnLegs([0, 1, 2, 3], split), [start, v1, a, b, v2, end]);
  // A via point between two stops that swap stays between them, the other way round.
  const m = at(250, 0);
  const c = at(350, 0);
  const inner = stopsOnly([start, a, marks.via(m), b, c, end], marks.isVia);
  assert.deepEqual(withViasOnLegs([0, 3, 2, 1, 4], inner), [start, c, b, m, a, end]);
  // In a loop every stop may move: v, between b and the last stop, stays between them when the loop is ridden the
  // other way round (before: it went with the last stop, ridden from the start).
  const v = marks.via(at(450, 0));
  const last = at(600, 0);
  const loop = stopsOnly([start, a, b, v, last], marks.isVia, true);
  assert.deepEqual(withVias([0, 3, 2, 1], loop), [start, v, last, b, a]);
  assert.deepEqual(withViasOnLegs([0, 3, 2, 1], loop), [start, last, v, b, a]);
});

test("an order that splits a leg with via points is said and not taken", () => {
  const marks = new ViaMarks();
  const start = at(0, 0);
  const v1 = marks.via(at(100, 0));
  const a = at(200, 0);
  const b = at(300, 0);
  const end = at(500, 0);
  const points = [start, v1, a, b, end];
  const stops = stopsOnly(points, marks.isVia);
  const dials = startDials("default");
  const answer: StopOrder = { order: [0, 2, 1, 3], changed: true, by: "route_cost", exact: true, before_s: 900, after_s: 800, before_m: 3000, after_m: 2800 };
  const names = { name: () => undefined };
  const applied = applyAnswer({ points, preset: "default", dials, loop: false, stops }, { points, preset: "default", dials }, { ok: true, answer }, names);
  assert.equal(applied.commit, undefined);
  assert.equal(applied.say, VIA_LEGS_KEPT_SAID);
  assert.equal(VIA_LEGS_KEPT_SAID, "The stops stay in this order, to keep your via points on their way.");
  // An order that keeps the via point's leg whole is taken, the via point still between its two stops.
  const m = marks.via(at(250, 0));
  const c = at(400, 0);
  const whole = [start, a, m, b, c, end];
  const wholeStops = stopsOnly(whole, marks.isVia);
  const moved: StopOrder = { ...answer, order: [0, 3, 1, 2, 4] };
  const taken = applyAnswer({ points: whole, preset: "default", dials, loop: false, stops: wholeStops }, { points: whole, preset: "default", dials }, { ok: true, answer: moved }, names);
  assert.deepEqual(taken.commit, [start, c, a, m, b, end]);
});

// The hunt, round 2, R2-8: a loop whose last leg was drawn by hand (its end marked drawn). Before, the shape point was put
// before that end, so the drawn leg ran from the shape point: half the rest of the loop sent as one straight line.
test("a loop's way home takes no shape point where its end ends a drawn leg", () => {
  const ride = { loopRide: true, detour: false, restart: false, keptPoints: 1, endDrawn: false };
  assert.equal(shapesHome(ride), true);
  assert.equal(shapesHome({ ...ride, endDrawn: true }), false);
  assert.equal(shapesHome({ ...ride, loopRide: false }), false);
  assert.equal(shapesHome({ ...ride, detour: true }), false);
  assert.equal(shapesHome({ ...ride, restart: true }), false);
  assert.equal(shapesHome({ ...ride, keptPoints: 2 }), false);
  const src = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(src, /const endDrawn = keptLeft\.length > 0 && VIA_MARKS\.isDrawn\(keptLeft\[keptLeft\.length - 1\]\);/);
});
