// The stretch picked on Plan's chart (lib/chartStretch.ts): its facts, the way round's judging, and the points once a
// way round is taken. Made-up routes; no rider's file.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { RouteProfile, RouteResponse, StressSpan } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { HILLS_MIN, startDials } from "./dials.ts";
import { aroundDials, climbBetween, judgeWayRound, stretchFacts, viasAround, whyAvoid, WAY_VIAS, type StretchFacts } from "./chartStretch.ts";

// A straight line east, about 11 m a vertex, 400 vertices: about 4.4 km.
const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);
const span = (from_m: number, to_m: number, tier: number): StressSpan => ({ from_m, to_m, tier, facility: null });
const profile = (elevation: number[]): RouteProfile => {
  const m = elevation.map((_, i) => i * 100);
  const grade = elevation.map((e, i) => (i === 0 ? 0 : e - elevation[i - 1]));
  return { interval_m: 100, m, elevation_m: elevation, grade_pct: grade, climbs: [] } as RouteProfile;
};
const route = (extra: Partial<RouteResponse> = {}): RouteResponse =>
  ({ geometry: { type: "LineString", coordinates: LINE }, distance_m: 4400, duration_s: 900, stress_spans: [span(0, 1000, 2), span(1000, 2000, 4), span(2000, 4400, 2)], description: [], ...extra }) as unknown as RouteResponse;

test("a picked stretch's climb, steepest grade and busiest level", () => {
  const p = profile([10, 10, 12, 18, 18, 15, 15]);
  assert.equal(climbBetween(p, 0, 600), 8);
  const facts = stretchFacts(route(), p, 150, 1200);
  assert.equal(facts.climbM, 6);
  assert.equal(facts.steepestPct, 6);
  assert.equal(facts.level, 4);
  assert.deepEqual(whyAvoid(facts), { busy: true, steep: true });
  assert.deepEqual(whyAvoid({ ...facts, level: 2, steepestPct: 3 }), { busy: false, steep: false });
});

test("the way round is planned calmest where busy, with the fewest hills where steep, and the plan's own dials else", () => {
  const dials = { ...startDials("default"), stress: 40, hills: 20 };
  assert.deepEqual([aroundDials(dials, { busy: true, steep: false }).stress, aroundDials(dials, { busy: true, steep: false }).hills], [100, 20]);
  assert.deepEqual([aroundDials(dials, { busy: false, steep: true }).stress, aroundDials(dials, { busy: false, steep: true }).hills], [40, HILLS_MIN]);
});

test("a way round is kept only where it is better on what made the stretch bad and worse on nothing", () => {
  const busy: StretchFacts = { fromM: 1000, toM: 2000, climbM: 2, steepestPct: 1, level: 4, street: "Big Road" };
  const around = (tier: number, elevation: number[], distance_m = 1500) =>
    route({ distance_m, stress_spans: [span(0, distance_m, tier)], profile: profile(elevation) });
  assert.equal(judgeWayRound(busy, 1300, 2, around(2, [0, 1, 2])).kind, "found");
  assert.equal(judgeWayRound(busy, 1300, 2, around(4, [0, 1, 2])).kind, "none", "no calmer");
  assert.equal(judgeWayRound(busy, 1300, 2, around(2, [0, 30, 60])).kind, "none", "calmer but far more climb");
  assert.equal(judgeWayRound(busy, 1300, 2, around(2, [0, 1, 2], 6000)).kind, "none", "too long");
  const steep: StretchFacts = { fromM: 1000, toM: 2000, climbM: 40, steepestPct: 9, level: 2, street: null };
  const found = judgeWayRound(steep, 1300, 40, around(2, [0, 5, 10]));
  assert.equal(found.kind, "found");
  assert.equal(found.kind === "found" ? found.climbChangeM : null, -30);
  assert.equal(judgeWayRound(steep, 1300, 40, around(3, [0, 5, 10])).kind, "none", "flatter but busier");
});

test("taking a way round drops the points inside the stretch and puts vias on the way round in that leg", () => {
  const a = LINE[0];
  const inside = LINE[130];
  const later = LINE[300];
  const end = LINE[399];
  // The legs end at the points' vertices.
  const r = route({ leg_ends: [130, 300, 399] });
  const way: LonLat[] = [LINE[75], [-77.035, 38.905], LINE[195]];
  const via = (p: LonLat): LonLat => [p[0], p[1]];
  const isVia = (p: LonLat) => p === inside;
  const next = viasAround([a, inside, later, end], r, { fromM: 1000, toM: 2000 }, way, false, via, isVia);
  assert.ok(next !== "stop");
  assert.ok(next);
  assert.equal(next.length, 3 + WAY_VIAS, "the start, two vias, the later point and the end");
  assert.deepEqual(next[0], a);
  assert.deepEqual(next[next.length - 2], later);
  assert.ok(!next.some((p) => p === inside), "the point inside the stretch goes");
  assert.ok(next.slice(1, 1 + WAY_VIAS).every((p) => Math.abs(p[1] - 38.9) > 0.001), "the vias are on the way round");
});

test("a stretch on a loop's closing leg puts the vias after the last point", () => {
  const r = route({ leg_ends: [130, 399] });
  const way: LonLat[] = [LINE[250], [-77.01, 38.905], LINE[390]];
  const next = viasAround([LINE[0], LINE[130]], { ...r, geometry: { type: "LineString", coordinates: LINE } } as RouteResponse, { fromM: 3000, toM: 4000 }, way, true, (p) => p, () => false);
  assert.ok(next && next !== "stop");
  assert.equal(next.length, 2 + WAY_VIAS);
  assert.deepEqual(next.slice(0, 2), [LINE[0], LINE[130]]);
});

test("a stop the rider placed inside the stretch is never dropped: nothing changes, and the answer says why", () => {
  const r = route({ leg_ends: [130, 300, 399] });
  const way: LonLat[] = [LINE[75], [-77.035, 38.905], LINE[195]];
  assert.equal(viasAround([LINE[0], LINE[130], LINE[300], LINE[399]], r, { fromM: 1000, toM: 2000 }, way, false, (p) => p, () => false), "stop");
});
