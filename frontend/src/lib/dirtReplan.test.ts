// A ride's re-plan starts at the rider (the owner, 2026-10-21: "If someone goes onto a dirt trail, any reroutes should
// include dirt"): it says so, and whether the rider has been on a dirt trail; a plan says neither.
import { test } from "node:test";
import assert from "node:assert/strict";
import { routeRequestBody } from "./api.ts";
import type { LonLat } from "./geo.ts";

const LINE: LonLat[] = [
  [-77.05, 38.9],
  [-77.02, 38.9],
];

test("a plan sends neither ride flag", () => {
  const body = JSON.parse(routeRequestBody(LINE, "default", { dirtRidden: true }));
  assert.equal(body.ride_replan, undefined);
  assert.equal(body.dirt_ridden, undefined);
});

test("a ride's re-plan says so, and sends dirt_ridden only after a dirt trail", () => {
  const before = JSON.parse(routeRequestBody(LINE, "default", { rideReplan: true }));
  assert.equal(before.ride_replan, true);
  assert.equal(before.dirt_ridden, undefined);
  const after = JSON.parse(routeRequestBody(LINE, "default", { rideReplan: true, dirtRidden: true }));
  assert.equal(after.dirt_ridden, true);
});

test("a ride's re-plan after a dirt trail was marked closed says so", () => {
  const body = JSON.parse(routeRequestBody(LINE, "default", { rideReplan: true, dirtClosed: true }));
  assert.equal(body.dirt_closed, true);
  assert.equal(JSON.parse(routeRequestBody(LINE, "default", { dirtClosed: true })).dirt_closed, undefined);
});
