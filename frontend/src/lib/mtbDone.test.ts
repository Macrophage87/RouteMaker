// Ride's Done with MTB (lib/mtbDone.ts; the owner, 2026-11-08): shown while a mountain-bike trail is ahead, and every
// re-plan after the press sends mtb_done, kept with the ride for a Resume.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { routeRequestBody } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { mtbTrailAhead } from "./mtbDone.ts";
import { rideReplans } from "./rideResume.ts";

const LINE: LonLat[] = [
  [-77.05, 38.9],
  [-77.02, 38.9],
];
const TRAILS = { trail_levels: [{ from_m: 1000, to_m: 2500, level: 2 }] };

test("shown only while a mountain-bike trail is on the route ahead", () => {
  assert.equal(mtbTrailAhead(TRAILS, 0), true);
  assert.equal(mtbTrailAhead(TRAILS, 2000), true);
  assert.equal(mtbTrailAhead(TRAILS, 2600), false);
  assert.equal(mtbTrailAhead(TRAILS, null), true);
  assert.equal(mtbTrailAhead({ trail_levels: [] }, 0), false);
  assert.equal(mtbTrailAhead({ trail_levels: null }, null), false);
  assert.equal(mtbTrailAhead(null, 0), false);
});

test("a ride's re-plan after the press sends mtb_done; a plan never does", () => {
  assert.equal(JSON.parse(routeRequestBody(LINE, "mountain-bike", { rideReplan: true, mtbDone: true })).mtb_done, true);
  assert.equal(JSON.parse(routeRequestBody(LINE, "mountain-bike", { rideReplan: true })).mtb_done, undefined);
  assert.equal(JSON.parse(routeRequestBody(LINE, "mountain-bike", { mtbDone: true })).mtb_done, undefined);
});

test("kept with the ride for a Resume, and only when pressed", () => {
  assert.deepEqual(rideReplans(false, [], false, false, true), { mtbDone: true });
  assert.deepEqual(rideReplans(false, [], false, false, false), {});
});

test("Ride shows it under Go round, re-plans with it, and keeps it", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const mtbDone = useRef\(replans\?\.mtbDone === true\);/);
  assert.match(ride, /dirtClosed: dirtClosed\.current, mtbDone: mtbDone\.current \}\);/);
  assert.match(ride, /className="secondary ride-mtb-done"/);
  assert.doesNotMatch(ride, /rideReplans\(loopRide, blockedRef\.current, (dirtRidden\.current|true), dirtClosed\.current\)/);
});
