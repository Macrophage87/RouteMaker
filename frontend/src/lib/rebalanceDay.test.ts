import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { REBALANCE_DAY_KEY, dayRows, localDay, readDay, recordTrip, restoreDay, tripOf, withTrip } from "./rebalanceDay.ts";
import { maxPointsNotice } from "./geolocation.ts";
import { plansFromStart } from "./loop.ts";
import { routeRequestBody } from "./api.ts";

function memory() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), kept };
}

const MORNING = new Date(2026, 10, 7, 6, 0).getTime();
const trip = { walkM: 300, walkS: 240, rideM: 1600, rideS: 420 };

test("each Rebalance Ride ended adds to the day's trips, walking and riding (Stephen, 2026-11-07)", () => {
  const store = memory();
  assert.equal(readDay(store, MORNING).trips, 0);
  recordTrip(trip, store, MORNING);
  const day = recordTrip(trip, store, MORNING + 3_600_000);
  assert.deepEqual(day, { day: localDay(MORNING), trips: 2, walkM: 600, walkS: 480, rideM: 3200, rideS: 840 });
  assert.deepEqual(readDay(store, MORNING + 7_200_000), day);
  // Shown with this ride counted before it is recorded; only trips, walking, riding and their time.
  assert.equal(withTrip(readDay(store, MORNING), trip).trips, 3);
  assert.deepEqual(dayRows(day).map((r) => r.name), ["Trips", "Walking", "Riding", "Total time"]);
  // Kept on this device only, with no place or time of day.
  assert.deepEqual(Object.keys(JSON.parse(store.kept.get(REBALANCE_DAY_KEY)!)).sort(), ["day", "rideM", "rideS", "trips", "walkM", "walkS"]);
});

test("the day starts again at local midnight, and a broken or missing store is an empty day", () => {
  const store = memory();
  recordTrip(trip, store, MORNING);
  const tomorrow = new Date(2026, 10, 8, 0, 1).getTime();
  assert.equal(readDay(store, tomorrow).trips, 0);
  store.setItem(REBALANCE_DAY_KEY, "{not json");
  assert.equal(readDay(store, MORNING).trips, 0);
  assert.equal(readDay(null, MORNING).trips, 0);
  assert.equal(recordTrip(trip, null, MORNING).trips, 1);
});

test("a trip's walk is the plan's; its ride is the ride's own figures", () => {
  assert.deepEqual(tripOf({ walk_m: 250, walk_s: 200 }, { distanceM: 1500, movingMs: 400_000 }), { walkM: 250, walkS: 200, rideM: 1500, rideS: 400 });
});

test("a Rebalance Ride is planned from its start alone; an end is never sent", () => {
  const start: [number, number] = [-77.0063, 38.8973];
  assert.equal(plansFromStart("rebalance", [start], {}), true);
  assert.equal(plansFromStart("rebalance", [], {}), false);
  assert.equal(plansFromStart("bikeshare", [start], {}), false);
  assert.deepEqual(JSON.parse(routeRequestBody([start, [-77.04, 38.9]], "rebalance")).points, [start]);
  assert.match(maxPointsNotice(1), /starts where you are and has no destination/);
});

test("Keep riding puts the day back, but not once it is another day", () => {
  const store = memory();
  const before = readDay(store, MORNING);
  recordTrip(trip, store, MORNING);
  restoreDay(before, store, MORNING + 60_000);
  assert.equal(readDay(store, MORNING).trips, 0);
  recordTrip(trip, store, MORNING);
  restoreDay(before, store, MORNING + 86_400_000);
  assert.equal(readDay(store, MORNING).trips, 1);
});

test("the ride's summary: Do another trip first and focused, then Finish session (Stephen, 2026-11-07)", () => {
  const card = readFileSync(new URL("../RideSummaryCard.tsx", import.meta.url), "utf8");
  assert.match(card, /<button ref=\{done\} type="button" onClick=\{rebalance\.onAnother\}>\s*\{DO_ANOTHER_TRIP\}\s*<\/button>\s*<button type="button" className="secondary" onClick=\{onDone\}>\s*\{FINISH_SESSION\}/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // Counted as the ride ends (whatever closes the summary after); Keep riding puts the day back.
  assert.match(app, /day: recordTrip\(tripOf\(share, stats\)\), before,/);
  assert.match(/const undoEndRide = \(\) => \{[\s\S]*?\n {2}\};/.exec(app)![0], /if \(rideEnded\?\.rebalance\) restoreDay\(rideEnded\.rebalance\.before\);/);
  assert.doesNotMatch(/const finishRide = \(\) => \{[\s\S]*?\n {2}\};/.exec(app)![0], /recordTrip/);
});

test("a Rebalance Ride offers three docks to start from and three to end at, those near the start dock (2026-11-07)", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /dropoffNear=\{preset === "rebalance" && shown\?\.bikeshare \? \[shown\.bikeshare\.start\.lon, shown\.bikeshare\.start\.lat\] : null\}/);
  const lists = readFileSync(new URL("../NearbyStations.tsx", import.meta.url), "utf8");
  assert.match(lists, /const dropoff = dropoffNear \?\? listPoint\("dropoff", points\);/);
  const server = readFileSync(new URL("../../../src/core/bikeshare.py", import.meta.url), "utf8");
  assert.match(server, /^NEARBY_COUNT = 3$/m);
});
