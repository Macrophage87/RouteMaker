/** Stops in any order (OWNER-DECISIONS 449): the Best order button's logic and words. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { Dials } from "./dials.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import {
  BEST_ORDER_LABEL,
  bestOrderSaid,
  bestOrderUnavailableHint,
  fitsOrder,
  reorderedPoints,
  requestStopOrder,
  stopsThatMove,
  type StopOrder,
} from "./stopOrder.ts";

const S: LonLat = [-77.05, 38.9];
const A: LonLat = [-77.03, 38.9];
const B: LonLat = [-77.04, 38.9];
const C: LonLat = [-77.02, 38.9];
const E: LonLat = [-77.01, 38.9];

const NAMES = new Map<string, string>([
  [String(A), "Union Market"],
  [String(B), "Eastern Market"],
]);
const names = { name: (p: LonLat) => (NAMES.has(String(p)) ? { name: NAMES.get(String(p))! } : undefined) };

function answer(over: Partial<StopOrder>): StopOrder {
  return {
    order: [0, 1, 2, 3],
    changed: false,
    by: "riding_time",
    exact: true,
    before_s: 600,
    after_s: 600,
    before_m: 2000,
    after_m: 2000,
    ...over,
  };
}

test("the stops that may move: those between the ends, or every one after a loop's start", () => {
  assert.equal(stopsThatMove([S, A, B, E], false), 2);
  assert.equal(stopsThatMove([S, A, B], true), 2);
  assert.equal(stopsThatMove([S, A, B, S], true), 2, "a ride that already ends on its start keeps that end");
  assert.equal(stopsThatMove([S, A, E], false), 1);
  assert.equal(stopsThatMove([S], false), 0);
  assert.equal(stopsThatMove([], true), 0);
});

test("with fewer than two stops there is a reason, said when pressed; with two there is none", () => {
  assert.match(bestOrderUnavailableHint([S, A, E], false)!, /at least two stops between the start and the end/);
  assert.match(bestOrderUnavailableHint([S, A], true)!, /at least two stops in the loop/);
  assert.equal(bestOrderUnavailableHint([S, A, B, E], false), null);
  assert.equal(bestOrderUnavailableHint([S, A, B], true), null);
  assert.equal(bestOrderUnavailableHint([S], false), null, "no ride, no reason: there is no button");
});

test("an answer fits only when it keeps the start, the end unless it is a stop, and every point once", () => {
  assert.ok(fitsOrder([0, 2, 1, 3], [S, A, B, E], false));
  assert.ok(!fitsOrder([0, 2, 3, 1], [S, A, B, E], false), "the end moved");
  assert.ok(fitsOrder([0, 2, 1], [S, A, B], true), "a loop's last point is a stop");
  assert.ok(!fitsOrder([1, 0, 2, 3], [S, A, B, E], false), "the start moved");
  assert.ok(!fitsOrder([0, 1, 1, 3], [S, A, B, E], false), "a point twice");
  assert.ok(!fitsOrder([0, 1, 3], [S, A, B, E], false), "a point missing");
  assert.ok(!fitsOrder([0, 2, 1, 3], [S, A, B], true), "for other points");
  assert.ok(!fitsOrder([0, 1.5, 2, 3], [S, A, B, E], false));
  assert.ok(!fitsOrder([0, 2, 9, 3], [S, A, B, E], false));
});

test("the points are reordered as the answer says", () => {
  assert.deepEqual(reorderedPoints([S, A, B, E], [0, 2, 1, 3]), [S, B, A, E]);
});

test("a new order is said stop by stop, by name, with what it saves and how to undo it", () => {
  const said = bestOrderSaid(
    [S, A, B, C, E],
    answer({ order: [0, 2, 1, 3, 4], changed: true, before_s: 1500, after_s: 780, before_m: 6000, after_m: 4400 }),
    names,
    false,
  );
  assert.equal(
    said,
    "Stops put in the best order: Stop 1 is now Eastern Market (was Stop 2), Stop 2 is now Union Market (was Stop 1)," +
      " Stop 3 stays the point at 38.9000, -77.0200. About 12 min less riding, 1.0 mi (1.6 km) shorter." +
      " Undo puts the old order back.",
  );
});

test("a loop's last stop is said too, and named as a stop", () => {
  const said = bestOrderSaid([S, A, B], answer({ order: [0, 2, 1], changed: true, before_s: 900, after_s: 600 }), names, true);
  assert.match(said, /^Stops put in the best order: Stop 1 is now Eastern Market \(was Stop 2\), Stop 2 is now Union Market \(was Stop 1\)\./);
  assert.match(said, /About 5 min less riding\./);
});

test("an order already best says so; straight-line answers say what they are", () => {
  assert.equal(bestOrderSaid([S, A, B, E], answer({}), names, false), "The stops are already in the best order.");
  const straight = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, by: "straight_line", before_s: null, after_s: null, before_m: 3000, after_m: 2000 }),
    names,
    false,
  );
  assert.match(straight, /0\.6 mi \(1\.0 km\) shorter in straight lines\./);
  assert.match(straight, /riding times were not available, so this is by straight-line distance\./);
  assert.doesNotMatch(straight, /less riding/);
  assert.match(
    bestOrderSaid([S, A, B, E], answer({ by: "straight_line" }), names, false),
    /^The stops are already in the best order\. The router's riding times were not available/,
  );
});

test("a quicker order that is longer says it is longer; an unknown saving is left unsaid", () => {
  const longer = bestOrderSaid([S, A, B, E], answer({ order: [0, 2, 1, 3], changed: true, before_s: 900, after_s: 700, before_m: 2000, after_m: 2400 }), names, false);
  assert.match(longer, /About 3 min less riding, 0\.2 mi \(0\.4 km\) longer\./);
  const unknown = bestOrderSaid([S, A, B, E], answer({ order: [0, 2, 1, 3], changed: true, before_s: null, before_m: null }), names, false);
  assert.match(unknown, /\(was Stop 1\)\. Undo puts the old order back\.$/);
});

const dials: Dials = { ...startDials("default"), loop: true };

test("the request is the route request's body, without a Mass Ride's loop or the weight", async () => {
  const sent: { url: string; body: Record<string, unknown> }[] = [];
  const fetchImpl = async (url: string, init: RequestInit) => {
    sent.push({ url, body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify(answer({ order: [0, 2, 1], changed: true })), { status: 200 });
  };
  const result = await requestStopOrder([S, A, B], "default", { ...dials, systemWeightKg: 80 }, fetchImpl);
  assert.ok(result.ok && result.answer.changed);
  assert.equal(sent[0].url, "/api/stop-order");
  assert.deepEqual(sent[0].body.points, [S, A, B]);
  assert.equal(sent[0].body.loop, true);
  await requestStopOrder([S, A, B, E], "mass-ride", { ...startDials("mass-ride"), loop: true }, fetchImpl);
  assert.equal(sent[1].body.loop, undefined);
});

test("a refusal or a lost connection is a sentence to say", async () => {
  const busy = await requestStopOrder([S, A, B, E], "default", dials, async () =>
    new Response(JSON.stringify({ error: "busy" }), { status: 503, headers: { "Retry-After": "5" } }),
  );
  assert.ok(!busy.ok && /^Best order not found\. The planner is busy/.test(busy.message));
  const lost = await requestStopOrder([S, A, B, E], "default", dials, async () => {
    throw new Error("offline");
  });
  assert.ok(!lost.ok && /did not get through/.test(lost.message));
  const odd = await requestStopOrder([S, A, B, E], "default", dials, async () => new Response("{}", { status: 200 }));
  assert.ok(!odd.ok);
});

test("the button is in the point tools, only with two or more stops, and busy while it works", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.equal(BEST_ORDER_LABEL, "Best order");
  assert.match(app, /const orderShown = stopsThatMove\(points, loopVias\) >= 2;/);
  assert.match(app, /\{orderShown && \(\s*<button[\s\S]{0,200}aria-busy=\{ordering \? true : undefined\}/);
  // The answer is used only for the ride it was asked about, and it is checked before use.
  assert.match(app, /pointsRef\.current !== current/);
  assert.match(app, /fitsOrder\(result\.answer\.order, current, loop\)/);
  // One edit, so Undo takes it back, and the result is said.
  assert.match(app, /commit\(reorderedPoints\(current, result\.answer\.order\)\)/);
  assert.match(app, /announce\(bestOrderSaid\(current, result\.answer, namer, loop\)\)/);
});
