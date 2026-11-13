import { test } from "node:test";
import assert from "node:assert/strict";
import { defaultStart, fitStart, offersStartTime, startBounds, startMs, startShort, wallClock } from "./startTime.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { whenShort } from "./rideSummary.ts";
import { reachBody } from "./reach.ts";
import { readFileSync } from "node:fs";
import { leaveNowArrival } from "./arrival.ts";

// Wednesday 12 November 2026, 9:20 PM in Washington (EST, UTC-5).
const NOW = Date.parse("2026-11-13T02:20:00Z");

test("a wall-clock time is read as Washington's, whatever the device's zone", () => {
  assert.equal(startMs("2026-11-15T08:00"), Date.parse("2026-11-15T13:00:00Z"));
  // Summer time: UTC-4.
  assert.equal(startMs("2026-07-04T08:00"), Date.parse("2026-07-04T12:00:00Z"));
  // Either side of the November change of clocks (1 Nov 2026, 2 AM EDT to 1 AM EST).
  assert.equal(startMs("2026-10-31T23:00"), Date.parse("2026-11-01T03:00:00Z"));
  assert.equal(startMs("2026-11-01T05:00"), Date.parse("2026-11-01T10:00:00Z"));
  assert.equal(wallClock(Date.parse("2026-11-15T13:00:00Z")), "2026-11-15T08:00");
  // The repeated hour in November is its first (EDT); the hour skipped in March is read with the offset before it,
  // as the API's Python reads it (fold 0), so the page and the plan agree.
  assert.equal(startMs("2026-11-01T01:30"), Date.parse("2026-11-01T05:30:00Z"));
  assert.equal(startMs("2027-03-14T02:30"), Date.parse("2027-03-14T07:30:00Z"));
  assert.equal(startMs("2027-03-14T08:00"), Date.parse("2027-03-14T12:00:00Z"));
  assert.equal(startMs("2026-11-01T08:00"), Date.parse("2026-11-01T13:00:00Z"));
  for (const bad of ["", "tomorrow", "2026-11-15", "2026-11-15T8:00", undefined, null]) assert.equal(startMs(bad), null);
});

test("our default start is the next whole hour, and the box runs from now to a year on", () => {
  assert.equal(defaultStart(NOW), "2026-11-12T22:00");
  assert.equal(defaultStart(Date.parse("2026-11-13T03:00:00Z")), "2026-11-12T23:00");
  assert.deepEqual(startBounds(NOW), { min: "2026-11-12T21:20", max: "2027-11-12T21:20" });
});

test("a start the API takes: within the year ahead, not past", () => {
  assert.equal(fitStart("2026-11-15T08:00", NOW), "2026-11-15T08:00");
  assert.equal(fitStart("2026-11-12T21:00", NOW), undefined);
  assert.equal(fitStart("2027-12-01T08:00", NOW), undefined);
  assert.equal(fitStart("not a time", NOW), undefined);
});

test("not on Bikeshare or Rebalance Ride, which plan from the docks now", () => {
  assert.equal(offersStartTime("default"), true);
  assert.equal(offersStartTime("bike-transit"), true);
  assert.equal(offersStartTime("bikeshare"), false);
  assert.equal(offersStartTime("rebalance"), false);
});

test("the start goes to the API as depart_at, and stays through a change of ride type where it can", () => {
  const dials = { ...startDials("default"), startAt: "2026-11-15T08:00" };
  assert.equal(dialFields(dials).depart_at, "2026-11-15T08:00");
  assert.equal(dialFields(startDials("default")).depart_at, undefined);
  assert.equal(fitDials("road-bike", dials).startAt, "2026-11-15T08:00");
  assert.equal(fitDials("bikeshare", dials).startAt, undefined);
});

test("the Ride settings line says the start", () => {
  const ms = startMs("2026-11-15T08:00") as number;
  assert.equal(startShort(ms, "en-US"), "Sun, Nov 15, 8:00 AM");
  assert.match(whenShort(null, "2026-11-15T08:00"), /^leave Sun, Nov 15, 8:00/);
  assert.equal(whenShort(null), "now");
  assert.equal(whenShort("night", "2026-11-15T08:00"), "night, 9 PM to 7 AM");
});

test("Reach's rings never send the start time (its API takes no depart_at)", () => {
  const dials = { ...startDials("default"), startAt: "2026-11-15T08:00" };
  const body = reachBody([[-77.03, 38.9]], "default", dials, { minutes: [15], direction: "from", combine: "any", calm: false } as never);
  assert.equal("depart_at" in body, false);
});

test("Best order, the nearest places and a ride never send the start time: they are for now", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  assert.match(read("./stopOrder.ts"), /dialFields\(\{ \.\.\.dials, systemWeightKg: undefined, startAt: undefined \}\)/);
  assert.equal((read("./nearest.ts").match(/startAt: undefined/g) ?? []).length, 2);
  assert.match(read("../App.tsx"), /rideDials\(\{ \.\.\.planDials, closuresNow: true, startAt: undefined \}/);
  // Into Go, or once the start has passed, the start goes (Now).
  assert.match(read("../App.tsx"), /if \(mode === "go" \|\| fitStart\(dials\.startAt, startClock\) === undefined\)/);
});

test("with a start set, a screen reader hears the arrival for leaving then, with its day", () => {
  const starts = startMs("2026-11-15T08:00") as number;
  const { said } = leaveNowArrival(starts + 45 * 60_000, "en-US", starts);
  assert.match(said, /^arriving about 8:45\s?AM if you leave Sun, Nov 15, 8:00\s?AM$/);
  assert.match(leaveNowArrival(starts, "en-US").said, /if you leave now$/);
});

test("a ride's own requests, saved routes and shared links never carry the start time", async () => {
  const { rideNowDials, legDials } = await import("./rideTrip.ts");
  const { withoutStart } = await import("./savedRoutes.ts");
  const dials = { ...startDials("default"), startAt: "2026-11-15T08:00" };
  assert.equal(rideNowDials(dials).startAt, undefined);
  assert.equal(legDials(dials, "default").startAt, undefined);
  assert.equal("startAt" in withoutStart(dials), false);
  assert.equal(withoutStart(startDials("default")).stress, startDials("default").stress);
  const saved = readFileSync(new URL("./savedRoutes.ts", import.meta.url), "utf8");
  assert.equal((saved.match(/preset, dials: withoutStart\(dials\) \}/g) ?? []).length, 2, "planSave and gpxSave");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(saved && !plan\.dials\.startAt && saved\.key === keptPlanKey/);
  assert.match(app, /pending\.nowOnly \? \{ \.\.\.planDials, closuresNow: true, startAt: undefined \}/);
});
