/** Stops in any order (OWNER-DECISIONS 449): the Best order button's logic and words. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { Dials } from "./dials.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import {
  BEST_ORDER_LABEL,
  STILL_FINDING_ORDER_SAID,
  applyAnswer,
  bestOrderSaid,
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
    by: "route_cost",
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

test("a new order says each stop that moved, by name, how many stayed, what it saves and how to undo it", () => {
  const said = bestOrderSaid(
    [S, A, B, C, E],
    answer({ order: [0, 2, 1, 3, 4], changed: true, before_s: 1500, after_s: 780, before_m: 6000, after_m: 4400 }),
    names,
    false,
  );
  assert.equal(
    said,
    "Stops put in the best order: Stop 1 is now Eastern Market (was Stop 2), Stop 2 is now Union Market (was Stop 1)." +
      " The other stop stays where it was. About 12 min less riding, 1.0 mi (1.6 km) shorter." +
      " Undo puts the old order back.",
  );
});

test("a loop's last stop is said too, and named as a stop", () => {
  const said = bestOrderSaid([S, A, B], answer({ order: [0, 2, 1], changed: true, before_s: 900, after_s: 600 }), names, true);
  assert.match(said, /^Stops put in the best order: Stop 1 is now Eastern Market \(was Stop 2\), Stop 2 is now Union Market \(was Stop 1\)\./);
  assert.match(said, /About 5 min less riding\./);
  assert.doesNotMatch(said, /stays? where/, "every stop moved");
});

test("a stop with no name is said by its coordinates, and several unmoved stops are counted", () => {
  const D: LonLat = [-77.015, 38.9];
  const said = bestOrderSaid([S, C, A, B, D, E], answer({ order: [0, 4, 2, 3, 1, 5], changed: true }), names, false);
  assert.match(said, /Stop 1 is now the point at 38\.9000, -77\.0150 \(was Stop 4\), Stop 4 is now the point at 38\.9000, -77\.0200 \(was Stop 1\)\./);
  assert.match(said, / The other 2 stops stay where they were\./);
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
  const unknown = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, by: "riding_time", before_s: null, before_m: null }),
    names,
    false,
  );
  assert.match(unknown, /\(was Stop 1\)\. The router could not weigh traffic stress and hills for these stops, so this is by riding time alone\./);
});

test("an order chosen by the router's cost that rides longer says it is calmer or flatter", () => {
  const slower = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, before_s: 600, after_s: 780, before_m: 2000, after_m: 2400 }),
    names,
    false,
  );
  assert.match(slower, / About 3 min more riding and 0\.2 mi \(0\.4 km\) longer, but on calmer or flatter roads\. Undo puts/);
  const same = bestOrderSaid([S, A, B, E], answer({ order: [0, 2, 1, 3], changed: true }), names, false);
  assert.match(same, /\(was Stop 1\)\. The new order is on calmer or flatter roads\. Undo puts/);
  const shorter = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, before_s: 600, after_s: 780, before_m: 2400, after_m: 2000 }),
    names,
    false,
  );
  assert.match(shorter, / About 3 min more riding and 0\.2 mi \(0\.4 km\) shorter, on calmer or flatter roads\. Undo/);
  const quicker = bestOrderSaid([S, A, B, E], answer({ order: [0, 2, 1, 3], changed: true, after_s: 500 }), names, false);
  assert.doesNotMatch(quicker, /calmer/, "a quicker order needs no reason");
});

test("an order by riding time alone says it did not weigh stress and hills", () => {
  const said = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, by: "riding_time", before_s: 900, after_s: 600 }),
    names,
    false,
  );
  assert.match(said, /About 5 min less riding\. The router could not weigh traffic stress and hills for these stops, so this is by riding time alone\. Undo/);
  assert.doesNotMatch(said, /more riding|calmer/);
  const slower = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, by: "riding_time", before_s: 600, after_s: 700 }),
    names,
    false,
  );
  assert.doesNotMatch(slower, /more riding/);
  assert.match(bestOrderSaid([S, A, B, E], answer({ by: "riding_time" }), names, false), /^The stops are already in the best order\. The router could not weigh/);
  const many: LonLat[] = Array.from({ length: 13 }, (_, i) => [-77.05 + 0.001 * i, 38.9] as LonLat);
  assert.match(
    bestOrderSaid(many, answer({ order: many.map((_, i) => i), by: "riding_time" }), names, false),
    / With more than 10 stops, this is by riding time alone, without traffic stress and hills\.$/,
  );
  assert.doesNotMatch(
    bestOrderSaid(many.slice(0, 12), answer({ order: many.slice(0, 12).map((_, i) => i), by: "riding_time" }), names, false),
    /more than 10/,
    "ten stops are within the router's cost",
  );
  // A loop the rider chose: 11 points are ten stops (every one after the start), 12 are eleven.
  const loopSaid = (k: number) =>
    bestOrderSaid(many.slice(0, k), answer({ order: many.slice(0, k).map((_, i) => i), by: "riding_time" }), names, true);
  assert.match(loopSaid(11), /The router could not weigh/);
  assert.match(loopSaid(12), /With more than 10 stops/);
  const straightTimes = bestOrderSaid(
    [S, A, B, E],
    answer({ order: [0, 2, 1, 3], changed: true, by: "straight_line", before_s: 900, after_s: 600 }),
    names,
    false,
  );
  assert.doesNotMatch(straightTimes, /less riding/, "a straight-line answer says no riding time");
});

const dials: Dials = { ...startDials("default"), loop: true };

test("the request is the route request's body, without the weight", async () => {
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
  await requestStopOrder([S, A, B, E], "group-ride", startDials("group-ride"), fetchImpl);
  for (const { body } of sent) assert.equal(body.system_weight_kg, undefined, "the weight is not sent");
  assert.equal(sent[0].body.stress, dials.stress, "the dials are");
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

const asked = { points: [S, A, B, E] as readonly LonLat[], preset: "default" as const, dials, loop: false };
const swapped = { ok: true as const, answer: answer({ order: [0, 2, 1, 3], changed: true, before_s: 900, after_s: 600 }) };

test("an answer for the ride asked about is committed and said", () => {
  const done = applyAnswer(asked, { points: asked.points, preset: "default", dials }, swapped, names);
  assert.deepEqual(done.commit, [S, B, A, E]);
  assert.match(done.say, /^Stops put in the best order: Stop 1 is now Eastern Market/);
});

test("an answer already best is said and not committed, so Undo gets no empty step", () => {
  const done = applyAnswer(asked, { points: asked.points, preset: "default", dials }, { ok: true, answer: answer({}) }, names);
  assert.equal(done.commit, undefined);
  assert.equal(done.say, "The stops are already in the best order.");
});

test("an answer is not used when the points, ride type or dials changed meanwhile, or when it does not fit", () => {
  const changed = /The ride changed while the best order was being found/;
  assert.match(applyAnswer(asked, { points: [S, A, B, E], preset: "default", dials }, swapped, names).say, changed, "new points, same places");
  assert.match(applyAnswer(asked, { points: asked.points, preset: "group-ride", dials }, swapped, names).say, changed);
  assert.match(applyAnswer(asked, { points: asked.points, preset: "default", dials: { ...dials } }, swapped, names).say, changed);
  for (const now of [
    { points: [S, A, B, E], preset: "default" as const, dials },
    { points: asked.points, preset: "group-ride" as const, dials },
    { points: asked.points, preset: "default" as const, dials: { ...dials } },
  ]) {
    assert.equal(applyAnswer(asked, now, swapped, names).commit, undefined);
  }
  const bad = applyAnswer(asked, { points: asked.points, preset: "default", dials }, { ok: true, answer: answer({ order: [0, 2, 3, 1], changed: true }) }, names);
  assert.equal(bad.commit, undefined);
  assert.match(bad.say, /did not fit these points/);
  const refused = applyAnswer(asked, { points: asked.points, preset: "default", dials }, { ok: false, message: "Best order not found. Busy." }, names);
  assert.deepEqual(refused, { say: "Best order not found. Busy." });
});

test("the button is in the point tools, only with two or more stops, and says when it is still working", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.equal(BEST_ORDER_LABEL, "Best order");
  assert.equal(STILL_FINDING_ORDER_SAID, "Still finding the best order.");
  assert.match(app, /const orderShown = !isMassRide\(preset\) && stopsThatMove\(points, loopVias\) >= 2;/);
  assert.match(app, /\{orderShown && \(\s*<button[\s\S]{0,600}aria-disabled=\{ordering \? true : undefined\}\s*>\s*\{BEST_ORDER_LABEL\}/);
  // A second press while one is being found is answered, not sent.
  assert.match(app, /if \(orderingRef\.current\) \{\s*announce\(STILL_FINDING_ORDER_SAID\);\s*return;/);
  // The answer goes through applyAnswer with the ride as asked and as it is now, and only a new order is committed.
  assert.match(app, /applyAnswer\(\s*\{ points: current, preset: ride\.preset, dials: ride\.dials, loop \},\s*\{ points: pointsRef\.current, preset: now\.preset, dials: now\.dials \}/);
  assert.match(app, /if \(applied\.commit\) commit\(applied\.commit\);\s*orderNotice\(applied\.say, pointsRef\.current\);/);
  // When the button leaves with the focus on it, the focus goes to Reverse.
  assert.match(app, /if \(orderShown \|\| !orderFocused\.current\) return;[\s\S]{0,200}reverseButton\.current\?\.focus\(\)/);
});
