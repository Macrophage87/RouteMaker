// Check a route (the 2026-11-13 backlog, item 3): an opened file's worst stretches and a calmer way round each.
// Made-up lines only: no rider's file or ride is used.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { RouteResponse, RouteResult, StressSpan } from "./api.ts";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { spliceDetours } from "./closureCheck.ts";
import {
  CALMEST_STRESS,
  WORST_MOST,
  busiestLevel,
  calmerDials,
  calmerLine,
  judgeCalmerWay,
  levelWeight,
  planCalmerWay,
  pointsKept,
  spliceAt,
  stretchEnds,
  stretchLine,
  worstStretches,
} from "./worstStretches.ts";

const span = (from_m: number, to_m: number, tier: number | null, half = false): StressSpan => ({ from_m, to_m, tier, facility: null, ...(half ? { half: true } : {}) });

// A straight line east, about 11 m a vertex: 400 vertices, about 4.4 km.
const LINE: LonLat[] = Array.from({ length: 400 }, (_, i) => [-77.05 + i * 0.000128, 38.9]);

function route(spans: StressSpan[], extra: Partial<RouteResponse> = {}): RouteResponse {
  return {
    geometry: { type: "LineString", coordinates: LINE },
    distance_m: 4400,
    duration_s: 900,
    stress_spans: spans,
    description: [],
    ...extra,
  } as unknown as RouteResponse;
}

test("each half level up doubles a mile's weight; Avoid weighs the most", () => {
  assert.equal(levelWeight(3), 1);
  assert.equal(levelWeight(3.5), 2);
  assert.equal(levelWeight(4), 4);
  assert.equal(levelWeight(5), 16);
});

test("a calm route has no worst stretches", () => {
  assert.deepEqual(worstStretches(route([span(0, 2000, 1), span(2000, 4400, 2, true)])), []);
});

test("busy sections a little apart are one stretch, and the busiest level is kept", () => {
  const found = worstStretches(route([span(0, 1000, 2), span(1000, 1300, 3), span(1300, 1350, 2), span(1350, 1500, 4), span(1500, 4400, 1)]));
  assert.equal(found.length, 1);
  assert.equal(found[0].fromM, 1000);
  assert.equal(found[0].toM, 1500);
  assert.equal(found[0].level, 4);
  assert.equal(found[0].busyM, 450);
});

test("ranked by length weighted by level: a short Avoid beats a longer LTS 3; at most three", () => {
  const found = worstStretches(
    route([span(0, 600, 3), span(600, 1000, 1), span(1000, 1200, 5), span(1200, 1600, 1), span(1600, 1900, 3, true), span(1900, 2400, 1), span(2400, 2500, 3), span(2500, 3000, 1), span(3000, 3500, 3, true)]),
  );
  assert.equal(found.length, WORST_MOST);
  assert.equal(found[0].level, 5);
  // 500 m at 3.5 (half step) weighs more than 600 m at 3.
  assert.equal(found[1].fromM, 3000);
  assert.equal(found[1].level, 3.5);
  assert.equal(found[2].fromM, 0);
});

test("an unrated section is not busy", () => {
  assert.deepEqual(worstStretches(route([span(0, 4400, null)])), []);
});

test("the stretch is named after the street most of it is on", () => {
  const r = route([span(1000, 2000, 4)], {
    description: [
      { kind: "stretch", from_m: 900, to_m: 1200, street: "Side Street", tier: 2 },
      { kind: "stretch", from_m: 1200, to_m: 2100, street: "Big Road", tier: 4 },
    ] as unknown as RouteResponse["description"],
  });
  const [worst] = worstStretches(r);
  assert.equal(worst.street, "Big Road");
  assert.match(stretchLine(worst), /^Big Road: 0\.6 mi .*LTS 4 at worst$/);
  assert.match(stretchLine({ ...worst, street: null }), /^an unnamed way: /);
});

test("a calmer way is planned between points just outside the stretch, on the calmest setting, no loop or target", async () => {
  const r = route([span(1000, 2000, 4)]);
  const [worst] = worstStretches(r);
  const ends = stretchEnds(r, worst);
  assert.ok(ends.paddedM > 1290 && ends.paddedM < 1310, String(ends.paddedM));
  let asked: { points: LonLat[]; stress: number; loop?: boolean; target?: number } | null = null;
  const way = await planCalmerWay(r, worst, "default", { ...startDials("default"), loop: true, targetDistanceM: 9000 }, async (points, _preset, dials): Promise<RouteResult> => {
    asked = { points, stress: dials.stress, loop: dials.loop, target: dials.targetDistanceM };
    return { ok: true, route: route([span(0, 1600, 2)], { distance_m: 1600, geometry: { type: "LineString", coordinates: [ends.from, [-77.0, 38.905], ends.to] } }) };
  });
  assert.ok(asked);
  const got = asked as unknown as { points: LonLat[]; stress: number; loop?: boolean; target?: number };
  assert.equal(got.points.length, 2);
  assert.equal(got.stress, CALMEST_STRESS);
  assert.equal(got.loop, false);
  assert.equal(got.target, undefined);
  assert.equal(way.kind, "found");
  if (way.kind === "found") {
    assert.equal(way.level, 2);
    assert.ok(way.extraM > 290 && way.extraM < 310);
    assert.match(calmerLine(way), /^Calmer way: .* longer, LTS 2 at worst\.$/);
  }
});

test("a way round no calmer than the stretch, or far longer, is not offered; a refusal says it failed", async () => {
  const stretch = { level: 3.5 };
  assert.equal(judgeCalmerWay(stretch, 1000, route([span(0, 1000, 3, true)], { distance_m: 1000 })).kind, "none");
  assert.equal(judgeCalmerWay(stretch, 1000, route([span(0, 5000, 2)], { distance_m: 5000 })).kind, "none");
  assert.equal(judgeCalmerWay(stretch, 1000, route([span(0, 1500, 3)], { distance_m: 1500 })).kind, "found");
  const r = route([span(1000, 2000, 4)]);
  const failed = await planCalmerWay(r, worstStretches(r)[0], "default", startDials("default"), async () => ({ ok: false, error: { kind: "server", status: 500, title: "", message: "" } }) as RouteResult);
  assert.equal(failed.kind, "failed");
});

test("calmerDials keeps the plan's other dials", () => {
  const dials = { ...startDials("default"), hills: 40 };
  assert.equal(calmerDials(dials).hills, 40);
  assert.equal(busiestLevel(route([span(0, 10, 2), span(10, 20, 4, true)])), 4.5);
});

test("Use this way: the calmer way replaces the file's line between its ends, every other vertex kept", () => {
  const track = LINE.map(([lon, lat], i) => [lon, lat, 10 + i] as [number, number, number]);
  const way: LonLat[] = [LINE[100], [LINE[150][0], 38.902], LINE[200]];
  const cut = spliceAt(track, way, 100 / 400, 1100);
  assert.deepEqual(cut, { before: 100, after: 200 });
  const out = spliceDetours(track, [cut!], [way]);
  assert.equal(out.length, 400 - 99 + 1);
  assert.deepEqual(out[100], track[100]);
  assert.deepEqual(out[101], [LINE[150][0], 38.902]);
  assert.deepEqual(out[102], track[200]);
});

// Out along LINE and back a few metres north (a GPS track's return pass): vertex k and 799 - k are nearly one spot.
const BACK: LonLat[] = LINE.slice().reverse().map(([lon, lat]) => [lon, lat + 0.00003]);
const OUT_AND_BACK = [...LINE, ...BACK];

test("an out-and-back is cut on the pass the stretch is on, on the way out and on the way back", () => {
  const out = spliceAt(OUT_AND_BACK, [LINE[150], [LINE[200][0], 38.899], LINE[250]], 150 / 800, 1100);
  assert.deepEqual(out, { before: 150, after: 250 });
  const back = spliceAt(OUT_AND_BACK, [BACK[150], [BACK[200][0], 38.899], BACK[250]], 550 / 800, 1100);
  assert.deepEqual(back, { before: 550, after: 650 });
});

test("near the turn, the cut keeps to the way out, even where the route's share is a little off", () => {
  for (const share of [300 / 800, 0.33, 0.42]) {
    assert.deepEqual(spliceAt(OUT_AND_BACK, [LINE[300], [LINE[340][0], 38.899], LINE[380]], share, 900), { before: 300, after: 380 }, String(share));
  }
});

test("a loop's stretch near the start and finish is cut at the start", () => {
  const loop: LonLat[] = [...LINE.slice(0, 200), ...LINE.slice(0, 200).reverse().map(([lon, lat]) => [lon, lat + 0.002] as LonLat), LINE[0]];
  const cut = spliceAt(loop, [LINE[5], [LINE[30][0], 38.898], LINE[60]], 5 / 401, 600);
  assert.deepEqual(cut, { before: 5, after: 60 });
});

test("the plan's points the route reaches inside the stretch go; the ends, those elsewhere and those on the other pass stay", () => {
  // The route is the out-and-back itself, 800 vertices; points at vertices 0, 120, 200, 600 (the same spot as 200, on
  // the way back) and 799.
  const r = route([span(1650, 2750, 4)], { geometry: { type: "LineString", coordinates: OUT_AND_BACK }, distance_m: 0, leg_ends: [120, 200, 600, 799] });
  const points: LonLat[] = [OUT_AND_BACK[0], OUT_AND_BACK[120], OUT_AND_BACK[200], OUT_AND_BACK[600], OUT_AND_BACK[799]];
  const [worst] = worstStretches(r);
  assert.deepEqual(pointsKept(points, r, worst), [OUT_AND_BACK[0], OUT_AND_BACK[120], OUT_AND_BACK[600], OUT_AND_BACK[799]]);
  // Legs that do not fit the points: every point kept.
  assert.equal(pointsKept(points, { ...r, leg_ends: [1, 2] }, worst).length, 5);
});
