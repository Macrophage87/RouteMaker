import { test } from "node:test";
import assert from "node:assert/strict";
import { CONFIRM_STEP_KM, confirmedUpTo, sendsConfirmation, spanKm } from "./longRide.ts";
import type { LonLat } from "./geo.ts";

// About 1 km per 0.009 degrees of latitude.
const along = (km: number): LonLat[] => [
  [-77.0, 38.3],
  [-77.0, 38.3 + km / 111.2],
];

test("the step a yes covers is 50 km", () => {
  assert.equal(CONFIRM_STEP_KM, 50);
});

test("span is the straight-line sum, in km", () => {
  assert.ok(Math.abs(spanKm(along(160)) - 160) < 1);
});

test("a yes covers the plan up to the next 50 km step", () => {
  assert.equal(confirmedUpTo(160), 200);
  assert.equal(confirmedUpTo(150.5), 200);
  assert.equal(confirmedUpTo(200), 250);
  assert.equal(confirmedUpTo(249.9), 250);
});

test("confirm_long goes only on a long plan the rider has said yes to", () => {
  assert.equal(sendsConfirmation(along(160), null), false, "never asked");
  assert.equal(sendsConfirmation(along(160), 200), true);
  assert.equal(sendsConfirmation(along(195), 200), true, "a drag within the step");
  assert.equal(sendsConfirmation(along(205), 200), false, "past the step: ask again");
  // Harmless below 150 km, and the API's own span can differ from ours at the edge.
  assert.equal(sendsConfirmation(along(149.9), 200), true);
});
