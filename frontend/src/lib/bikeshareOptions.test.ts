// Go's Bikeshare options (#94's bikeshare.options, lettered A, B, C): the first answer's list kept for the trip,
// the option the shown plan rides, and the pins that re-plan an option.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { BikeshareOption, BikesharePlan } from "./api.ts";
import { FIRST_ANSWER_PINS, keepOptions, keepsFirst, optionName, optionPins, optionReplaySaid, optionsKey, pickedOption, replayFor, replaysFirst, sentPlanKey, stationlessUnavailable } from "./bikeshareOptions.ts";
import { withStations } from "./stations.ts";
import { readFileSync } from "node:fs";
import type { LonLat } from "./geo.ts";

const A: LonLat = [-77.0063, 38.8973];
const B: LonLat = [-77.0436, 38.9096];

function end(name: string, id: string | null) {
  return { kind: "dock" as const, name, lon: -77, lat: 38.9, station_id: id, availability: "known" as const, bikes_available: 3, docks_available: 4, walk_m: 100, walk_s: 80, extra_m: 0, on_the_way: true, way_text: "on your way" };
}
function option(rank: number, pickup: string | null, dropoff: string | null): BikeshareOption {
  return {
    rank, chosen: rank === 1, pickup: end(`Dock ${pickup}`, pickup), dropoff: end(`Dock ${dropoff}`, dropoff),
    pickup_station: pickup, dropoff_station: dropoff, ending: "dock", ride_m: 2000, total_s: 900, estimated: rank !== 1, cost_m: rank * 100,
    text: `Pick up at Dock ${pickup}, return at Dock ${dropoff}`,
  };
}
const plan = (options: BikeshareOption[]) => ({ options }) as unknown as BikesharePlan;
const three = [option(1, "p1", "d1"), option(2, "p2", "d1"), option(3, "p1", "d2")];

test("the first answer's options are kept for the trip; a re-plan of one pair does not shrink them", () => {
  const key = optionsKey([A, B], "bikeshare");
  const first = keepOptions(null, plan(three), key);
  assert.equal(first?.options.length, 3);
  const replanned = { ...option(2, "p2", "d1"), chosen: true };
  const after = keepOptions(first, plan([replanned]), key);
  assert.equal(after, first, "the same trip keeps its list");
  assert.equal(keepOptions(after, null, key), first, "another ride type's answer (no options) keeps it too");
  const refreshed = keepOptions(first, plan([option(1, "p9", "d9"), option(2, "p2", "d1")]), key);
  assert.equal(refreshed?.options[0].pickup_station, "p9", "a full list is fresh");
  assert.equal(pickedOption(after!.options, plan([replanned])), 1, "B is the one now ridden");
  assert.equal(pickedOption(after!.options, plan(three)), 0, "A, the chosen first");
});

test("a new trip takes its own list; no trip, or no options, none", () => {
  const first = keepOptions(null, plan(three), optionsKey([A, B], "bikeshare"));
  const moved = keepOptions(first, plan([option(1, "q1", "q2")]), optionsKey([B, A], "bikeshare"));
  assert.equal(moved?.options[0].pickup_station, "q1");
  assert.equal(keepOptions(first, plan(three), optionsKey([A], "bikeshare")), null);
  assert.equal(keepOptions(null, null, optionsKey([A, B], "bikeshare")), null);
});

test("Bikeshare's options never carry over to a Rebalance Ride on the same trip, nor the other way round", () => {
  const bikeshare = optionsKey([A, B], "bikeshare");
  const rebalance = optionsKey([A, B], "rebalance");
  assert.notEqual(bikeshare, rebalance);
  // Bikeshare lists three; the Rebalance Ride's answer lists one: its own, not Bikeshare's three.
  const first = keepOptions(null, plan(three), bikeshare);
  const rebalanced = keepOptions(first, plan([option(1, "c1", "n1")]), rebalance);
  assert.equal(rebalanced?.key, rebalance);
  assert.deepEqual(rebalanced?.options.map((o) => o.pickup_station), ["c1"]);
  // And back: Rebalance lists three; Bikeshare's one-pair answer is its own.
  const rebalanceFirst = keepOptions(null, plan([option(1, "c1", "n1"), option(2, "c2", "n1")]), rebalance);
  const back = keepOptions(rebalanceFirst, plan([option(1, "p1", "d1")]), bikeshare);
  assert.equal(back?.key, bikeshare);
  assert.deepEqual(back?.options.map((o) => o.pickup_station), ["p1"]);
  // A list kept for one ride type is not the list for the other (Go matches the key it shows for).
  assert.notEqual(first?.key, rebalance);
  // Another ride type's answer (no bikeshare plan) leaves the list as it was.
  assert.equal(keepOptions(first, null, optionsKey([A, B], "road")), first);
});

test("an option's pins hold its stations to the trip's ends; a stationless end is left to the server", () => {
  assert.deepEqual(optionPins(three[1], [A, B]), { pickup: { id: "p2", name: "Dock p2", at: A }, dropoff: { id: "d1", name: "Dock d1", at: B } });
  assert.deepEqual(optionPins(option(1, null, "d1"), [A, B]), { dropoff: { id: "d1", name: "Dock d1", at: B } });
  assert.equal(optionName("B", three[1]), "B: Pick up at Dock p2, return at Dock d1");
});

// Follow-up review of PR #95: a free-floating e-bike's option has no pick-up station id, so its pins would let the
// server plan the best option again; it is shown again from the first answer, which planned it (#94's choice 6).
function freeBike(): BikeshareOption {
  const o = option(1, null, "d1");
  return { ...o, pickup: { ...o.pickup, kind: "free_bike" as never, name: "an e-bike outside a dock", station_id: null }, text: "Pick up an e-bike outside a dock" };
}

test("a free e-bike's option replays the first answer; a dock's option is re-planned with its stations", () => {
  assert.equal(replaysFirst(freeBike()), true);
  assert.equal(replaysFirst(three[1]), false);
  assert.equal(replaysFirst(option(1, "p1", null)), false, "an outside-dock ending still has its pick-up station");
  assert.deepEqual(FIRST_ANSWER_PINS, {});
  assert.equal(keepsFirst(plan([freeBike(), three[1]])), true, "a full list is the answer to keep");
  assert.equal(keepsFirst(plan([three[1]])), false, "a re-plan of one pair is not");
  assert.equal(keepsFirst(null), false);
});

test("the first answer is replayed only when the free e-bike asked for it and the request is exactly its plan", () => {
  const dials = { bike: "ebike", stress: 80, ending: "dock" };
  const firstKey = sentPlanKey([A, B], "bikeshare", withStations(dials as never, {}));
  const first = { key: firstKey, trip: optionsKey([A, B], "bikeshare"), route: "first route" };
  // The key holds the stations (the link's key does not), so B's pinned plan never matches.
  const pinned = sentPlanKey([A, B], "bikeshare", withStations(dials as never, optionPins(three[1], [A, B])));
  assert.notEqual(pinned, firstKey);
  // Key order does not matter; the stations stripped give the first plan's key back.
  assert.equal(sentPlanKey([A, B], "bikeshare", { ending: "dock", stress: 80, bike: "ebike" }), firstKey);
  assert.equal(sentPlanKey([A, B], "bikeshare", withStations(JSON.parse(pinned)[2], FIRST_ANSWER_PINS)), firstKey);
  // A dock ending set by an option's press (the default either way) is the same plan; outside a dock is not.
  assert.equal(sentPlanKey([A, B], "bikeshare", { bike: "ebike", stress: 80 }), firstKey);
  assert.notEqual(sentPlanKey([A, B], "bikeshare", { ...dials, ending: "outside_dock" }), firstKey);
  assert.equal(replayFor(first, firstKey, firstKey), "first route");
  assert.equal(replayFor(first, null, firstKey), null, "not asked: sent (another change reaching the same plan asks the planner)");
  assert.equal(replayFor(first, firstKey, pinned), null, "another plan: sent");
  assert.equal(replayFor(null, firstKey, firstKey), null);
  const changed = sentPlanKey([A, B], "bikeshare", { ...dials, stress: 40 });
  assert.equal(replayFor(first, changed, changed), null, "settings changed since: never replayed");
  assert.equal(optionReplaySaid("A", freeBike()), "Option A: picking up at an e-bike outside a dock, as first planned.");
  assert.match(stationlessUnavailable("A"), /^Option A, an e-bike outside a dock, came from the first plan.*cannot be planned again\.$/);
});

test("App replays the first answer for a free e-bike's option and keeps a pinned option re-planned", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const send = app.slice(app.indexOf("send: async (plan) => {"), app.indexOf("const result = await requestRoute("));
  assert.match(send, /const replay = replayFor\(firstAnswer\.current, replayAsked\.current, sentPlanKey\(plan\.points, plan\.preset, plan\.dials\)\);\s*replayAsked\.current = null;\s*if \(replay\) \{\s*keptShown\.current = null;\s*return \{ ok: true, route: replay \};/);
  assert.match(app, /if \(usesBikeshare\(plan\.preset\) && keepsFirst\(bikeshareOf\(result\.route\)\)\)\s*firstAnswer\.current = \{ key: sentPlanKey\(plan\.points, plan\.preset, plan\.dials\)/);
  const pick = app.slice(app.indexOf("const pickOption = "), app.indexOf("// A new answer: the Keep button"));
  assert.match(pick, /if \(replaysFirst\(option\)\) \{[\s\S]*?setNotice\(stationlessUnavailable\(placeLetter\(index\)\)\);\s*return;[\s\S]*?replayAsked\.current = first\.key;\s*setStationPins\(FIRST_ANSWER_PINS\);[\s\S]*?return;\s*\}\s*setStationPins\(optionPins\(option, points\)\);/);
  // The free e-bike's branch never sets the pins that would let the server choose again.
  const free = pick.slice(pick.indexOf("if (replaysFirst(option))"), pick.indexOf("setStationPins(optionPins("));
  assert.doesNotMatch(free, /optionPins\(/);
});
