/** Make it a loop (OWNER-DECISIONS 266). */
import assert from "node:assert/strict";
import test from "node:test";
import type { RouteResponse } from "./api.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { LOOP_LABEL, LOOP_SAME_M, isRoundTrip, loopNote, loopView } from "./loop.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { announceRoute } from "./summary.ts";
import { panelView } from "./dialsPanel.ts";
import type { LonLat } from "./geo.ts";

const A: LonLat = [-77.0, 38.9];
const B: LonLat = [-76.95, 38.92];
const C: LonLat = [-76.9, 38.9];

test("a ride that ends where it starts is a loop, with a place between", () => {
  assert.ok(isRoundTrip([A, B, A]));
  assert.ok(isRoundTrip([A, B, C, [A[0] + 0.0004, A[1]]]), "within 50 m");
  assert.ok(!isRoundTrip([A, B, [A[0] + 0.01, A[1]]]));
  assert.ok(!isRoundTrip([A, A]));
  assert.ok(!isRoundTrip([A]));
  assert.equal(LOOP_SAME_M, 50);
});

test("the toggle is off on a point-to-point ride, on and fixed on a round trip, and absent where it cannot apply", () => {
  const off = loopView("trailmaxxing", undefined, [A, B])!;
  assert.deepEqual([off.checked, off.implied, off.label], [false, false, LOOP_LABEL]);
  assert.equal(LOOP_LABEL, "Make it a loop");
  const chosen = loopView("trailmaxxing", true, [A, B])!;
  assert.deepEqual([chosen.checked, chosen.implied], [true, false]);
  const implied = loopView("default", undefined, [A, B, A])!;
  assert.deepEqual([implied.checked, implied.implied], [true, true]);
  assert.match(implied.hint, /ends where it starts, so it is planned as a loop/);
  assert.match(off.hint, /a different way back/);
  assert.equal(loopView("mass-ride", true, [A, B]), null);
  // With the start alone it can be chosen (OWNER-DECISIONS 374).
  assert.deepEqual([loopView("default", undefined, [A])!.checked, loopView("default", true, [A])!.checked], [false, true]);
  assert.equal(loopView("default", true, []), null);
});

test("the request and the link carry it when on, and only then", () => {
  const start = startDials("default");
  assert.equal("loop" in dialFields(start), false);
  assert.equal(dialFields({ ...start, loop: true }).loop, true);
  assert.equal("loop" in dialFields({ ...start, loop: false }), false);
  assert.equal(fitDials("default", { loop: true }).loop, true);
  assert.equal("loop" in fitDials("default", {}), false);
  const hash = encodePlan([A, B], "default", { ...start, loop: true });
  assert.match(hash, /loop=1/);
  assert.equal(decodePlan(hash).dials.loop, true);
  assert.doesNotMatch(encodePlan([A, B], "default", start), /loop/);
  assert.equal("loop" in decodePlan("#preset=default&p=-77.0,38.9;-76.9,38.9").dials, false);
  assert.equal("loop" in decodePlan("#preset=default&loop=0").dials, false);
});

test("back to the ride type's settings turns it off", () => {
  const dials = { ...startDials("default"), loop: true };
  assert.deepEqual(panelView("default", dials).reset, startDials("default"));
});

function route(loop: RouteResponse["loop"]): RouteResponse {
  return {
    preset: "default",
    distance_m: 20_000,
    duration_s: 4_000,
    climb_m: 100,
    dials: { stress: 70, hills: 0, when: "weekend", carrying: null },
    loop,
  } as RouteResponse;
}

test("the summary says how much of the way back is the way out, in miles first", () => {
  assert.equal(loopNote(route(undefined)), null);
  assert.equal(loopNote(route(null)), null);
  assert.match(
    loopNote(route({ overlap_pct: 18.4, shared_m: 1500, return_m: 8150 })) ?? "",
    /^18% of the way back, 0\.9 mi \(1\.5 km\), is on roads the way out used\.$/,
  );
  assert.equal(loopNote(route({ overlap_pct: 0, shared_m: 0, return_m: 8000 })), "The way back shares no road with the way out.");
  assert.equal(loopNote(route({ overlap_pct: null, shared_m: null, return_m: null })), null);
});

test("a loop with no other way back says it is an out-and-back", () => {
  const note = loopNote(route({ overlap_pct: 100, shared_m: 8000, return_m: 8000, fallback: "out_and_back" })) ?? "";
  assert.match(note, /no other way back that fits, so this loop returns the way it went out/);
  assert.match(loopNote(route({ overlap_pct: 50, shared_m: 1, return_m: 2, fallback: "time" })) ?? "", /could not look for another way back in time/);
});

test("a screen reader hears the loop's note with the route, once", () => {
  const said = announceRoute(route({ overlap_pct: 18.4, shared_m: 1500, return_m: 8150 }));
  assert.match(said, /^Route planned: 12\.4 mi/);
  assert.match(said, /18% of the way back/);
  assert.doesNotMatch(announceRoute(route(null)), /way back/);
});
