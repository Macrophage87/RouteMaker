// Go's Bikeshare options (#94's bikeshare.options, lettered A, B, C): the first answer's list kept for the trip,
// the option the shown plan rides, and the pins that re-plan an option.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { BikeshareOption, BikesharePlan } from "./api.ts";
import { keepOptions, optionName, optionPins, optionsKey, pickedOption } from "./bikeshareOptions.ts";
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
  const key = optionsKey([A, B]);
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
  const first = keepOptions(null, plan(three), optionsKey([A, B]));
  const moved = keepOptions(first, plan([option(1, "q1", "q2")]), optionsKey([B, A]));
  assert.equal(moved?.options[0].pickup_station, "q1");
  assert.equal(keepOptions(first, plan(three), optionsKey([A])), null);
  assert.equal(keepOptions(null, null, optionsKey([A, B])), null);
});

test("an option's pins hold its stations to the trip's ends; a stationless end is left to the server", () => {
  assert.deepEqual(optionPins(three[1], [A, B]), { pickup: { id: "p2", name: "Dock p2", at: A }, dropoff: { id: "d1", name: "Dock d1", at: B } });
  assert.deepEqual(optionPins(option(1, null, "d1"), [A, B]), { dropoff: { id: "d1", name: "Dock d1", at: B } });
  assert.equal(optionName("B", three[1]), "B: Pick up at Dock p2, return at Dock d1");
});
