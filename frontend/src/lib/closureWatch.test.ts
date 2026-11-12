import assert from "node:assert/strict";
import test from "node:test";
import type { Closure } from "./closureCheck.ts";
import { METRES_PER_MILE } from "./format.ts";
import { NEAR_M, closedAheadSaid, closuresStamp, lineFromIndex, newWatchState, watchStep, watchedOf } from "./closureWatch.ts";

const MI = METRES_PER_MILE;

function closure(id: string, fromM: number, toM: number, extra: Partial<Closure> = {}): Closure {
  return { id, kind: "closed", road: "P St NW", from_m: fromM, to_m: toM, end: null, source: "AlertDC", text: "", title: `Closure ${id}`, ...extra };
}

test("an answer's closures are placed on the ride's own line, from where the check's line began", () => {
  const watched = watchedOf([closure("a", 100, 400), closure("b", 0, 50, { may_still_apply: true })], 5000);
  assert.deepEqual(watched, [{ id: "a", name: "Closure a", atM: 5100, toM: 5400 }]);
});

test("the closures already on the route when the ride starts are known, never asked about again", () => {
  const state = newWatchState();
  assert.deepEqual(watchStep(state, watchedOf([closure("start", 1000, 1200)], 0), 0), []);
  assert.deepEqual(watchStep(state, watchedOf([closure("start", 1000, 1200)], 0), 500), []);
});

test("a new closure within 10 miles is asked about once; one further is said quietly, then asked about within 10 miles", () => {
  const state = newWatchState();
  watchStep(state, [], 0);
  const near = { id: "near", name: "Police activity: streets closed near 15th St & P St NW", atM: 2 * MI, toM: 2.3 * MI };
  const far = { id: "far", name: "Georgia Ave & Missouri Ave NW closed", atM: 14 * MI, toM: 14.01 * MI };
  const first = watchStep(state, [near, far], 0);
  assert.deepEqual(first.map((s) => [s.kind, s.closure.id]), [["note", "far"], ["ask", "near"]]);
  assert.deepEqual(watchStep(state, [near, far], 0.5 * MI), [], "each said once");
  // Ridden on until the far one is within 10 miles: asked about now.
  const later = watchStep(state, [far], far.atM - NEAR_M + 10);
  assert.deepEqual(later.map((s) => [s.kind, s.closure.id]), [["ask", "far"]]);
});

test("only the nearest is asked at a time, and a closure behind the rider is left alone", () => {
  const state = newWatchState();
  watchStep(state, [], 0);
  const a = { id: "a", name: "A", atM: 3000, toM: 3100 };
  const b = { id: "b", name: "B", atM: 1000, toM: 1100 };
  const behind = { id: "c", name: "C", atM: 100, toM: 200 };
  assert.deepEqual(watchStep(state, [a, b, behind], 500).map((s) => s.closure.id), ["b"]);
  assert.deepEqual(watchStep(state, [a, b, behind], 600).map((s) => s.closure.id), ["a"]);
});

test("the line is sent from the last vertex at or before the rider", () => {
  const along = Float64Array.from([0, 10, 25, 40]);
  assert.equal(lineFromIndex(along, 0), 0);
  assert.equal(lineFromIndex(along, 24.9), 1);
  assert.equal(lineFromIndex(along, 25), 2);
  assert.equal(lineFromIndex(along, 99), 3);
});

test("the spoken line names the distance and the closure", () => {
  assert.equal(closedAheadSaid("2.1 mi", "Georgia Ave & Missouri Ave NW closed"), "Road closed ahead, 2.1 mi: Georgia Ave & Missouri Ave NW closed");
});

test("the stamp is asked with a GET and nothing of the rider's; a failure is null", async () => {
  const asked: string[] = [];
  const ok = (async (url: string) => {
    asked.push(url);
    return new Response(JSON.stringify({ stamp: "abc123" }), { status: 200 });
  }) as unknown as typeof fetch;
  assert.equal(await closuresStamp("https://x.test", ok), "abc123");
  assert.deepEqual(asked, ["https://x.test/api/closures/stamp"]);
  const down = (async () => {
    throw new Error("offline");
  }) as unknown as typeof fetch;
  assert.equal(await closuresStamp("https://x.test", down), null);
});
