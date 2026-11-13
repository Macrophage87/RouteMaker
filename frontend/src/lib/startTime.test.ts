import { test } from "node:test";
import assert from "node:assert/strict";
import { defaultStart, fitStart, offersStartTime, startBounds, startMs, startShort, wallClock } from "./startTime.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { whenShort } from "./rideSummary.ts";
import { reachBody } from "./reach.ts";

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
