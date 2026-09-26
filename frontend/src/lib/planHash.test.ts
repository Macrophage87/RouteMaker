import { test } from "node:test";
import assert from "node:assert/strict";
import { decodePlan, encodePlan } from "./planHash.ts";
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

test("points outside the coverage box are dropped, and at most twenty-five kept", () => {
  const many = Array.from({ length: 30 }, (_, i) => `${-77 + i / 100},38.9`).join(";");
  assert.equal(decodePlan(`#p=${many}`).points.length, 25);
  assert.deepEqual(decodePlan("#p=-77,38.9;-70,38.9").points, [[-77, 38.9]]);
});
