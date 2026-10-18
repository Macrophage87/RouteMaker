// Where the next train or bus is while waiting to board (v0.9.0; the owner: "When waiting for each, can you
// show where the next train or bus is?"), and Metrobus's live line on a plan: the question asked, the polling's
// stop condition, saying it only when the count changes, the map's mark, and the plan's footnote.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { NextVehicle, TransitStep } from "./api.ts";
import {
  POLL_MS,
  askOf,
  boarded,
  MAX_WAIT_MS,
  MISSES_KEPT,
  nextVehicleUrl,
  requestNextVehicle,
  shouldPoll,
  vehicleBadge,
  vehicleMark,
  vehicleSaid,
  vehicleShown,
  type NextVehicleAsk,
} from "./nextVehicle.ts";
import { liveTimesText } from "./transit.ts";

const SRC = new URL("../", import.meta.url);
const src = (path: string) => readFileSync(new URL(path, SRC), "utf8");

const step = (s: Partial<TransitStep>): TransitStep =>
  ({ text: "", seconds: 60, wait_s: 0, to: null, lines: [], with_bike: false, route_line: false, coordinates: [], ...s }) as TransitStep;

const BUS = step({
  mode: "bus",
  system: "Metrobus",
  lines: ["52"],
  coordinates: [
    [-77.0321, 38.9101],
    [-77.0322, 38.9201],
    [-77.0323, 38.9301],
  ],
});
const METRO = step({
  mode: "metro",
  system: "Metro",
  lines: ["Red Line"],
  coordinates: [
    [-77.0064, 38.8977],
    [-77.0281, 38.8983],
  ],
});
const MARC = step({ mode: "rail", system: "MARC", lines: ["Penn Line"], coordinates: [[-77.0, 38.9], [-76.6, 39.3]] });

const ASK: NextVehicleAsk = { system: "Metrobus", line: "52", from: [-77.0321, 38.9101], to: [-77.0323, 38.9301] };

const vehicle = (v: Partial<NextVehicle>): NextVehicle => ({
  kind: "bus",
  text: "Bus 52 is 0.8 mi away (1.3 km), 3 stops back.",
  label: "Next bus: Bus 52 is 0.8 mi away (1.3 km), 3 stops back (Data: WMATA, live)",
  point: [-77.03, 38.9],
  away: 3,
  credit: "Data: WMATA",
  source: "live",
  as_of: "2026-10-18T08:00:00-04:00",
  ...v,
});

test("the question: a Metro or Metrobus step's line, its first stop and its last; nothing for MARC", () => {
  assert.deepEqual(askOf(BUS), ASK);
  assert.deepEqual(askOf(METRO), { system: "Metro", line: "Red Line", from: [-77.0064, 38.8977], to: [-77.0281, 38.8983] });
  assert.equal(askOf(MARC), null);
  assert.equal(askOf(step({ mode: "bus", system: "Metrobus", lines: ["52"], coordinates: [[-77, 38.9]] })), null);
});

test("asking stops once the vehicle at the boarding has gone (boarded), or after the longest wait", () => {
  assert.equal(boarded(vehicle({ away: 0 }), vehicle({ away: 4 })), true);
  assert.equal(boarded(vehicle({ away: 1 }), vehicle({ away: 0 })), false);
  assert.equal(boarded(vehicle({ away: 0 }), vehicle({ away: 0 })), false);
  assert.equal(boarded(null, vehicle({ away: 4 })), false);
  assert.equal(boarded(vehicle({ away: 0 }), null), false);
  assert.equal(MAX_WAIT_MS, 20 * 60_000);
  const line = src("NextVehicleLine.tsx");
  assert.match(line, /Date\.now\(\) - started > MAX_WAIT_MS\) return stop\(\)/);
  assert.match(line, /if \(boarded\(last\.current, found\)\) return stop\(\)/);
});

test("a missed answer or two keeps the last one shown, so the same count is not said again", () => {
  assert.equal(MISSES_KEPT, 2);
  assert.match(src("NextVehicleLine.tsx"), /if \(misses <= MISSES_KEPT && last\.current\) return;/);
  // Compared with the last answer kept, the same count after a miss is not said.
  assert.equal(vehicleSaid(vehicle({ away: 3 }), vehicle({ away: 3 })), null);
});

test("the URL names the step, never a key; the answer is taken only when it is one", async () => {
  assert.equal(
    nextVehicleUrl(ASK),
    "/api/transit/next-vehicle?system=Metrobus&line=52&lon=-77.03210&lat=38.91010&to_lon=-77.03230&to_lat=38.93010",
  );
  assert.doesNotMatch(nextVehicleUrl(ASK), /key/i);
  const answer = (body: unknown, ok = true) => async () => ({ ok, json: async () => body });
  assert.deepEqual(await requestNextVehicle(ASK, { fetchImpl: answer({ vehicle: vehicle({}) }) }), vehicle({}));
  assert.equal(await requestNextVehicle(ASK, { fetchImpl: answer({ vehicle: null }) }), null);
  assert.equal(await requestNextVehicle(ASK, { fetchImpl: answer({ vehicle: { text: "x" } }) }), null);
  assert.equal(await requestNextVehicle(ASK, { fetchImpl: answer({}, false) }), null);
  const down = async () => {
    throw new Error("offline");
  };
  assert.equal(await requestNextVehicle(ASK, { fetchImpl: down }), null);
});

test("polling: only while a WMATA boarding is waited at with the page in view, every 25 s", () => {
  assert.equal(POLL_MS, 25_000);
  assert.equal(shouldPoll({ ask: ASK, waiting: true, hidden: false }), true);
  // Boarded (the ride moved on), never there, the page hidden, or no WMATA boarding: it stops.
  assert.equal(shouldPoll({ ask: ASK, waiting: false, hidden: false }), false);
  assert.equal(shouldPoll({ ask: ASK, waiting: true, hidden: true }), false);
  assert.equal(shouldPoll({ ask: null, waiting: true, hidden: false }), false);
});

test("said politely only when the stations or stops away change, never every poll", () => {
  const three = vehicle({});
  assert.equal(vehicleSaid(null, three), "Bus 52 is 0.8 mi away (1.3 km), 3 stops back. (Data: WMATA, live)");
  assert.equal(vehicleSaid(three, vehicle({ text: "Bus 52 is 0.7 mi away (1.1 km), 3 stops back." })), null);
  assert.ok(vehicleSaid(three, vehicle({ away: 2, text: "Bus 52 is 0.5 mi away (0.8 km), 2 stops back." }))?.includes("2 stops back"));
  // Gone: nothing said, nothing shown.
  assert.equal(vehicleSaid(three, null), null);
  const train = vehicle({ kind: "train", away: 2, text: "Next Red Line train is at Dupont Circle, 2 stations away." });
  assert.equal(vehicleShown(train), "Next Red Line train is at Dupont Circle, 2 stations away. (Data: WMATA, live)");
});

test("the map's mark: its point, its name in words, its kind's badge", () => {
  assert.deepEqual(vehicleMark(vehicle({})), {
    point: [-77.03, 38.9],
    label: "Next bus: Bus 52 is 0.8 mi away (1.3 km), 3 stops back (Data: WMATA, live)",
    kind: "bus",
  });
  assert.equal(vehicleMark(null), null);
  assert.equal(vehicleBadge("bus"), "Next bus");
  assert.equal(vehicleBadge("train"), "Next train");
  const map = src("MapView.tsx");
  assert.match(map, /next-vehicle-marker/);
  assert.match(map, /setAttribute\("aria-label", mark\.label\)/);
  assert.match(map, /setAttribute\("role", "img"\)/);
});

test("Ride mode shows it at the boarding, through the ride's polite outputs; no new control", () => {
  const ride = src("RideMode.tsx");
  assert.match(ride, /<NextVehicleLine ask=\{trip\?\.boarding \?\? null\} waiting=\{ride\.arrived\} announce=\{notify\}/);
  const line = src("NextVehicleLine.tsx");
  assert.doesNotMatch(line, /<button|checkbox|aria-live|role="status"/);
  assert.match(line, /clearInterval/);
  assert.match(src("lib/rideTrip.ts"), /askOf\(steps\[boardAt\]\)/);
  assert.match(src("App.tsx"), /nextVehicle=\{riding \? \(rideView\?\.vehicle \?\? null\) : null\}/);
});

test("a plan's footnote names what is live: trains, buses or both", () => {
  const live = { warnings: [], alerts: [], credit: "Data: WMATA", as_of: "2026-10-18T08:00:00-04:00" };
  const bus = { ...BUS, live: { text: "Live: bus 52 in 4 min, 13 min.", minutes: [4, 13], source: "live" as const } };
  const metro = { ...METRO, live: { text: "Live: Red Line toward Glenmont in 3 min.", minutes: [3], source: "live" as const } };
  assert.equal(liveTimesText({ live: null, steps: [bus] }), "Not live arrivals.");
  assert.equal(liveTimesText({ live, steps: [bus] }), "Times marked live are WMATA's next buses.");
  assert.equal(liveTimesText({ live, steps: [metro] }), "Times marked live are WMATA's next trains.");
  assert.equal(liveTimesText({ live, steps: [bus, metro] }), "Times marked live are WMATA's next trains and buses.");
  // A bus step's live line is shown as a Metro step's is, in the same span.
  assert.match(src("TransitSummary.tsx"), /\{step\.live && <span className="transit-step-live"> \{step\.live\.text\}<\/span>\}/);
});
