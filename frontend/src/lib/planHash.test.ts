import { test } from "node:test";
import assert from "node:assert/strict";
import { decodePlan, encodePlan, stressFromV1 } from "./planHash.ts";
import { STRESS_DEFAULT_AT, STRESS_TODAYS_TOP, fitDials, startDials } from "./dials.ts";
import { PRESETS } from "./presets.ts";
import type { LonLat } from "./geo.ts";
import { decodePoints, encodePoints } from "./linkCode.ts";
import { hasPlanLink } from "./appMode.ts";
import { keptPlanKey } from "./offlineRoutes.ts";
import { newRideSecret, secretFrom, withSecret } from "./rideSeal.ts";
import { asRideLink, leadKeyFrom, withSharedId } from "./sharedRoutes.ts";
import { leaderKey, newToken } from "./rideGroup.ts";

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

test("the link carries the ride type and the slider position, and nothing about trails (OWNER-DECISIONS 257 supersedes 202)", () => {
  // There is no trail credit any more (a quiet street counts the same as a trail):
  // the link carries the preset and the slider, and nothing that would read as one.
  const points: LonLat[] = [[-77.0434, 38.9096], [-77.0091, 38.8899]];
  const start = startDials("trailmaxxing");
  const hash = encodePlan(points, "trailmaxxing", start);
  assert.doesNotMatch(hash, /credit|trail(?!maxxing)/i);
  const plan = decodePlan(hash);
  assert.equal(plan.preset, "trailmaxxing");
  assert.equal(plan.dials.stress, 100);
  // A slider moved down from the ride type's top is the same ride type at that position,
  // and another ride type at the same position stays that ride type.
  const moved = decodePlan(encodePlan(points, "trailmaxxing", { ...start, stress: 90 }));
  assert.deepEqual([moved.preset, moved.dials.stress], ["trailmaxxing", 90]);
  const other = decodePlan(encodePlan(points, "default", { ...start, stress: 100 }));
  assert.deepEqual([other.preset, other.dials.stress], ["default", 100]);
  assert.equal(decodePlan(hash.replace("preset=trailmaxxing", "preset=default")).preset, "default");
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

// Owner item 204: beta.example.org/trailmaxxing is redirected by the edge to
// "/#preset=trailmaxxing", a link with a ride type and nothing else.
test("a link with only a ride type opens the planner on it, with that ride type's own dials", () => {
  for (const id of PRESETS.map((p) => p.id)) {
    const plan = decodePlan(`#preset=${id}`);
    assert.equal(plan.preset, id, id);
    assert.deepEqual(plan.points, [], id);
    assert.deepEqual(plan.dials, fitDials(id, {}), id);
    assert.deepEqual(plan.dials, startDials(id, null, null, false), id);
  }
  // What the redirect is for: Trailmaxxing's own start, not Default's.
  const trailmaxxing = decodePlan("#preset=trailmaxxing");
  assert.equal(trailmaxxing.dials.stress, startDials("trailmaxxing", null, null, false).stress);
  assert.notEqual(trailmaxxing.dials.stress, decodePlan("#preset=default").dials.stress);
});

test("a ride-type link survives being re-encoded, and an unknown or wrongly cased id is Default", () => {
  const plan = decodePlan("#preset=trailmaxxing");
  assert.equal(decodePlan(encodePlan(plan.points, plan.preset, plan.dials)).preset, "trailmaxxing");
  // The edge always sends the lowercase id; the app reads only that spelling.
  assert.equal(decodePlan("#preset=Trailmaxxing").preset, "default");
  assert.equal(decodePlan("#preset=nonsense").preset, "default");
});

// ---- shorter links (Stephen 2026-10-29, "yes"): the stops as `q=`, the leader mark and the key short --------------

const FIVE = (n: number) => Number(n.toFixed(5));
const OLD_P = (points: readonly LonLat[]) => points.map(([lon, lat]) => `${lon.toFixed(5)},${lat.toFixed(5)}`).join(";");

test("stops round-trip through the link exactly at 5 decimals, west longitudes and all", () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993], [-76.61, 39.29], [-78.04999, 38.20001], [-77.000005, 38.999995]];
  const hash = encodePlan(points, "default");
  const back = decodePlan(hash).points;
  assert.deepEqual(back, points.map(([lon, lat]) => [FIVE(lon), FIVE(lat)]));
  // The same numbers an older `p=` link of the same stops reads as, to the last bit.
  assert.deepEqual(back, decodePlan(`#p=${OLD_P(points)}&preset=default`).points);
});

test("the short form keeps any sign and size, and reads as the older form would", () => {
  // Outside the map too (decodePlan drops those later): the form itself carries any coordinate.
  const points: LonLat[] = [[-180, -90], [180, 90], [0, 0], [-0.00001, 0.00001], [12.345674, -45.678915], [-77.1, 38.9]];
  assert.deepEqual(decodePoints(encodePoints(points)), points.map(([lon, lat]) => [FIVE(lon), FIVE(lat)]));
  let seed = 7;
  const next = () => (seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31;
  for (let n = 0; n < 500; n += 1) {
    const many: LonLat[] = Array.from({ length: 1 + (n % 25) }, () => [-78.05 + next() * 2.03, 38.2 + next() * 1.52]);
    const hash = encodePlan(many, "default");
    assert.deepEqual(decodePlan(hash).points, decodePlan(`#p=${OLD_P(many)}`).points, hash);
  }
  assert.equal(encodePoints([]), "");
  assert.deepEqual(decodePoints(""), []);
});

test("the stops go in characters a link never escapes", () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993], [-76.61, 39.29]];
  const hash = encodePlan(points, "default", startDials("default", null));
  const q = new URLSearchParams(hash.slice(1)).get("q")!;
  assert.match(q, /^[A-Za-z0-9_-]+$/);
  assert.ok(hash.includes(`q=${q}&`), "written as it is, not percent-escaped");
  assert.equal(encodeURIComponent(q), q);
  assert.ok(q.length <= 8 * points.length, `${q.length} characters for ${points.length} stops`);
  assert.doesNotMatch(hash, /(^#|&)p=/, "a new link writes no p=");
});

test("an older link with p= stops still opens", () => {
  const old = "#p=-77.04000,38.91000;-77.01000,38.89000;-76.61000,39.29000&via=1&sn=2:Penn%20Station&preset=group-ride&v=2&stress=70&hills=0";
  const plan = decodePlan(old);
  assert.deepEqual(plan.points, [[-77.04, 38.91], [-77.01, 38.89], [-76.61, 39.29]]);
  assert.deepEqual(plan.vias, [1]);
  assert.deepEqual([...plan.names], [[2, "Penn Station"]]);
  assert.equal(plan.preset, "group-ride");
  assert.equal(hasPlanLink(old), true);
  // Written again, it is the short form of the same plan.
  const again = encodePlan(plan.points, plan.preset, plan.dials, plan.vias, [], plan.names);
  assert.deepEqual(decodePlan(again).points, plan.points);
  assert.deepEqual(decodePlan(again).vias, plan.vias);
  assert.equal(hasPlanLink(again.replace(/&preset=[^&]*/, "")), true, "q= alone is a plan link");
});

test("a link cut short opens with the stops it still has whole; a broken one with none", () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993], [-76.61, 39.29]];
  const q = encodePoints(points);
  for (let cut = 0; cut <= q.length; cut += 1) {
    const back = decodePlan(`#q=${q.slice(0, cut)}`).points;
    assert.deepEqual(back, points.slice(0, back.length), `cut at ${cut}`);
  }
  assert.deepEqual(decodePlan("#q=%2C%3B!&preset=default").points, []);
  assert.deepEqual(decodePlan("#q=").points, []);
  // A point outside the map is dropped, as with p=.
  assert.deepEqual(decodePlan(`#q=${encodePoints([[-77.03652, 38.89768], [0, 0]])}`).points, [[-77.03652, 38.89768]]);
});

test("a q= that holds no stop falls back to the link's p=", () => {
  const old = "p=-77.04000,38.91000;-77.01000,38.89000";
  assert.deepEqual(decodePlan(`#q=!!&${old}&preset=default`).points, [[-77.04, 38.91], [-77.01, 38.89]]);
  assert.deepEqual(decodePlan(`#q=&${old}`).points, [[-77.04, 38.91], [-77.01, 38.89]]);
  // A q= with stops wins over a p= beside it.
  const q = encodePoints([[-77.03652, 38.89768], [-77.00911, 38.88993]]);
  assert.deepEqual(decodePlan(`#q=${q}&${old}`).points, [[-77.03652, 38.89768], [-77.00911, 38.88993]]);
});

test("a kept route's key keeps the older p= form, so routes kept before the change are still found", () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993]];
  const dials = startDials("default", null);
  const key = keptPlanKey(points, "default", dials);
  assert.ok(key.startsWith(`#p=${OLD_P(points)}&`), key);
  assert.deepEqual(decodePlan(key).points, decodePlan(encodePlan(points, "default", dials)).points);
});

test("a ride link with two stops and its key is under 100 characters after the #", () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993]];
  // A Group Ride's link (App.tsx: the plan with the ride's secret).
  const link = withSecret(`https://routemaker.example/${encodePlan(points, "group-ride", startDials("group-ride", null))}`, newRideSecret());
  const fragment = link.slice(link.indexOf("#") + 1);
  assert.ok(fragment.length < 100, `${fragment.length}: ${fragment}`);
});

test("a broadcast link with two stops, its line, its leader and its key is under 160 characters after the # (206 before)", async () => {
  const points: LonLat[] = [[-77.03652, 38.89768], [-77.00911, 38.88993]];
  const hash = encodePlan(points, "default", startDials("default", null));
  const lead = await leaderKey(newToken());
  const link = withSecret(asRideLink(withSharedId(`https://routemaker.example/${hash}`, "0123456789abcdef0123456789abcdef"), lead), newRideSecret());
  const fragment = link.slice(link.indexOf("#") + 1);
  assert.ok(fragment.length < 160, `${fragment.length}: ${fragment}`);
  // Opened, it reads back whole: the stops, the leader key in hex, the key.
  assert.deepEqual(decodePlan(`#${fragment}`).points, points);
  assert.equal(leadKeyFrom(`#${fragment}`), lead);
  assert.ok(secretFrom(`#${fragment}`));
});
