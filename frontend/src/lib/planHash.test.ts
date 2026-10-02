import { test } from "node:test";
import assert from "node:assert/strict";
import { decodePlan, encodePlan, stressFromV1 } from "./planHash.ts";
import { STRESS_DEFAULT_AT, STRESS_TODAYS_TOP } from "./dials.ts";
import type { LonLat } from "./geo.ts";

test("a plan survives a round trip through the link", () => {
  const points: LonLat[] = [[-77.0434, 38.9096], [-77.03, 38.9], [-77.0091, 38.8899]];
  const decoded = decodePlan(encodePlan(points, "mass-ride"));
  assert.equal(decoded.preset, "mass-ride");
  assert.equal(decoded.points.length, 3);
  decoded.points.forEach((p, i) => {
    assert.ok(Math.abs(p[0] - points[i][0]) < 1e-5 && Math.abs(p[1] - points[i][1]) < 1e-5);
  });
});

test("an empty or hostile hash gives an empty default plan", () => {
  for (const hash of ["", "#", "#p=", "#p=abc", "#preset=__proto__", "#p=1,2,3;4", "#p=999,999;1,1"]) {
    const plan = decodePlan(hash);
    assert.equal(plan.preset, "default", hash);
    assert.ok(plan.points.every((p) => Number.isFinite(p[0]) && Number.isFinite(p[1])), hash);
  }
  assert.deepEqual(decodePlan("#p=999,999;1,1").points, []);
});

test("a link carries its version, and the sliders survive a round trip as they are", () => {
  const dials = { stress: 95, hills: -20, when: null, carrying: null, assist: false };
  const hash = encodePlan([[-77.0434, 38.9096]], "default", dials);
  assert.match(hash, /(^#|&)v=2(&|$)/);
  assert.equal(decodePlan(hash).dials.stress, 95);
  assert.equal(decodePlan(encodePlan([], "default", { ...dials, stress: 70 })).dials.stress, 70);
});

test("an old link's traffic position is mapped onto the rescaled slider", () => {
  // Review r1, B4: the slider was rescaled on 2026-10-01 (OWNER-DECISIONS 163):
  // old x 70/90 up to the old 90, then 70 + (old - 90).
  const old = (stress: number, preset = "default") => decodePlan(`#p=-77.0434,38.9096&preset=${preset}&stress=${stress}&hills=0`).dials.stress;
  assert.equal(old(90), 70, "the old Default is the new Default");
  assert.equal(old(100, "trailmaxxing"), 80, "the old top is the old top, not the new calm search");
  assert.equal(old(95), 75);
  assert.equal(old(50, "group-ride"), 39);
  assert.equal(old(10, "fast"), 8);
  assert.equal(old(0), 0);
  assert.equal(stressFromV1(90), STRESS_DEFAULT_AT);
  assert.equal(stressFromV1(100), STRESS_TODAYS_TOP);
  // An old link without a position starts where the ride type does.
  assert.equal(decodePlan("#p=-77.0434,38.9096&preset=default").dials.stress, 70);
});

test("the mapping lands each old position on the same use_roads (core.presets.use_roads_for)", () => {
  // The API's rescale, mirrored: new positions 0-70 are the old 0-90 and 70-80 the old 90-100.
  const useRoads = (stress: number) => {
    const old = stress <= 70 ? (stress * 90) / 70 : stress <= 80 ? 90 + (stress - 70) : 100;
    return 1 - old / 100;
  };
  for (const oldPosition of [0, 9, 18, 27, 36, 45, 54, 63, 72, 81, 90, 91, 95, 99, 100]) {
    const was = 1 - oldPosition / 100;
    // Within the half-step a whole-number slider position can be off by.
    assert.ok(Math.abs(useRoads(stressFromV1(oldPosition)) - was) <= (0.5 * 90) / 70 / 100 + 1e-9, String(oldPosition));
  }
});

test("points outside the coverage box are dropped, and at most twenty-five kept", () => {
  const many = Array.from({ length: 30 }, (_, i) => `${-77 + i / 100},38.9`).join(";");
  assert.equal(decodePlan(`#p=${many}`).points.length, 25);
  assert.deepEqual(decodePlan("#p=-77,38.9;-70,38.9").points, [[-77, 38.9]]);
});
