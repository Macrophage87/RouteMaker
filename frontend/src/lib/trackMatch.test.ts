import { test } from "node:test";
import assert from "node:assert/strict";
import { haversineM, pathLengthM, type LonLat } from "./geo.ts";
import {
  cumulative,
  dedupe,
  distancesToLine,
  fidelity,
  pointAlong,
  refineVias,
  resample,
  significantIndexes,
  viaPoints,
} from "./trackMatch.ts";

const M_LAT = 1 / 111_195;
const M_LON = 1 / (111_195 * Math.cos((38.9 * Math.PI) / 180));
/** A point `east` and `north` metres from a DC origin. */
const at = (east: number, north: number): LonLat => [-77.03 + east * M_LON, 38.9 + north * M_LAT];

/** A line through the given corners, a point every `step` metres. */
function dense(corners: LonLat[], step = 5): LonLat[] {
  const out: LonLat[] = [];
  for (let i = 1; i < corners.length; i += 1) {
    const d = haversineM(corners[i - 1], corners[i]);
    const n = Math.max(1, Math.round(d / step));
    for (let k = i === 1 ? 0 : 1; k <= n; k += 1) {
      const t = k / n;
      out.push([
        corners[i - 1][0] + t * (corners[i][0] - corners[i - 1][0]),
        corners[i - 1][1] + t * (corners[i][1] - corners[i - 1][1]),
      ]);
    }
  }
  return out;
}

/** Brute-force distance from p to a line, for checking the grid. */
function bruteDistance(p: LonLat, line: LonLat[]): number {
  let best = Number.POSITIVE_INFINITY;
  const fine = dense(line, 0.5);
  for (const q of fine) best = Math.min(best, haversineM(p, q));
  return best;
}

const L_SHAPE = dense([at(0, 0), at(1000, 0), at(1000, 800)]);
const ZIGZAG = dense([at(0, 0), at(500, 300), at(1000, 0), at(1500, 300), at(2000, 0), at(2500, 300)]);

test("the most significant points of an L are its two ends and its corner", () => {
  const kept = significantIndexes(L_SHAPE, 3);
  assert.equal(kept.length, 3);
  assert.equal(kept[0], 0);
  assert.equal(kept[2], L_SHAPE.length - 1);
  assert.ok(haversineM(L_SHAPE[kept[1]], at(1000, 0)) < 1, `${haversineM(L_SHAPE[kept[1]], at(1000, 0))}`);
});

test("significant points are sorted, unique, capped, and stop at the tolerance", () => {
  const kept = significantIndexes(ZIGZAG, 25);
  assert.deepEqual(kept, [...new Set(kept)].sort((a, b) => a - b));
  // Six corners; within a metre after that, so a 1 m tolerance keeps exactly them.
  assert.equal(significantIndexes(ZIGZAG, 25, 1).length, 6);
  assert.equal(significantIndexes(ZIGZAG, 4).length, 4);
  assert.deepEqual(significantIndexes([at(0, 0)], 5), [0]);
  assert.deepEqual(significantIndexes([at(0, 0), at(5, 5)], 5), [0, 1]);
});

test("a loop, whose two ends coincide, still keeps its far side", () => {
  const loop = dense([at(0, 0), at(800, 0), at(800, 800), at(0, 800), at(0, 0)]);
  const kept = significantIndexes(loop, 3);
  assert.equal(kept.length, 3);
  assert.ok(haversineM(loop[kept[1]], at(800, 800)) < 1);
});

test("via points: the track's two ends, at most the cap, each on the track and in order along it", () => {
  for (const mode of ["mid", "corners"] as const) {
    for (const cap of [2, 3, 5, 25]) {
      const vias = viaPoints(ZIGZAG, cap, mode);
      assert.ok(vias.length <= cap && vias.length >= 2, `${mode} ${cap}: ${vias.length}`);
      assert.deepEqual(vias[0], ZIGZAG[0]);
      assert.deepEqual(vias.at(-1), ZIGZAG.at(-1));
      const along = cumulative(ZIGZAG);
      let last = -1;
      for (const v of vias) {
        // Nearest track position of each via: on the track, and further along than the last.
        let best = 0;
        for (let i = 1; i < ZIGZAG.length; i += 1) {
          if (haversineM(v, ZIGZAG[i]) < haversineM(v, ZIGZAG[best])) best = i;
        }
        assert.ok(haversineM(v, ZIGZAG[best]) < 3, `${mode}: via off the track`);
        assert.ok(along[best] >= last, `${mode}: out of order`);
        last = along[best];
      }
    }
  }
});

test("midpoint vias sit between corners, not on them; corner vias are the corners", () => {
  const mid = viaPoints(ZIGZAG, 7, "mid");
  const corners = viaPoints(ZIGZAG, 6, "corners");
  const cornerPoints = [at(500, 300), at(1000, 0), at(1500, 300), at(2000, 0)];
  for (const c of cornerPoints) assert.ok(corners.some((v) => haversineM(v, c) < 1), "a corner kept");
  // Five stretches between the six corners, one midpoint each, plus both ends.
  assert.equal(mid.length, 7);
  for (const v of mid.slice(1, -1)) {
    const nearestCorner = Math.min(...cornerPoints.map((c) => haversineM(v, c)));
    assert.ok(nearestCorner > 200, `${nearestCorner}`);
  }
});

test("pointAlong and resample walk the line by ground distance", () => {
  const line = [at(0, 0), at(100, 0), at(100, 100)];
  const along = cumulative(line);
  assert.ok(Math.abs(along[2] - 200) < 0.5);
  assert.ok(haversineM(pointAlong(line, along, 150), at(100, 50)) < 0.5);
  assert.deepEqual(pointAlong(line, along, -5), line[0]);
  assert.deepEqual(pointAlong(line, along, 1e9), line[2]);
  const samples = resample(line, 10);
  assert.equal(samples.length, Math.ceil(along[2] / 10) + 1);
  assert.deepEqual(samples[0], line[0]);
  assert.deepEqual(samples.at(-1), line[2]);
  for (let i = 1; i < samples.length; i += 1) {
    const d = haversineM(samples[i - 1], samples[i]);
    assert.ok(d <= 10.5, `${d}`);
  }
});

test("dedupe drops a paused recorder's repeats and keeps the ends of a real move", () => {
  const p = at(0, 0);
  const q = at(10, 0);
  assert.deepEqual(dedupe([p, p, p, q, q]), [p, q]);
});

test("the gridded distance to a line agrees with brute force, up to its cap", () => {
  const line = [at(0, 0), at(700, 100), at(900, 900), at(-300, 1200)];
  let seed = 7;
  const random = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const probes: LonLat[] = Array.from({ length: 300 }, () => at(random() * 1600 - 500, random() * 1600 - 200));
  const got = distancesToLine(probes, line, 200);
  probes.forEach((p, i) => {
    const want = Math.min(200, bruteDistance(p, line));
    assert.ok(Math.abs(got[i] - want) < 1.5, `${i}: ${got[i]} vs ${want}`);
  });
});

test("fidelity: a line against itself is whole; against a parallel street 60 m off it is none", () => {
  const same = fidelity(ZIGZAG, ZIGZAG);
  assert.equal(same.trackCovered, 1);
  assert.equal(same.routeOnTrack, 1);
  assert.ok(Math.abs(same.lengthRatio - 1) < 1e-9);
  const parallel = dense([at(0, 60), at(2500, 60)]);
  const straight = dense([at(0, 0), at(2500, 0)]);
  const off = fidelity(straight, parallel);
  assert.equal(off.trackCovered, 0);
  assert.equal(off.routeOnTrack, 0);
});

test("fidelity: half a track followed is about half; a spur lowers only the route's share", () => {
  const track = dense([at(0, 0), at(2000, 0)]);
  const half = dense([at(0, 0), at(1000, 0), at(1000, 500), at(2000, 500)]);
  const f = fidelity(track, half);
  assert.ok(f.trackCovered > 0.45 && f.trackCovered < 0.56, `${f.trackCovered}`);
  const spur = dense([at(0, 0), at(1000, 0), at(1000, 400), at(1000, 0), at(2000, 0)]);
  const s = fidelity(track, spur);
  assert.equal(s.trackCovered, 1);
  assert.ok(s.routeOnTrack < 0.75 && s.routeOnTrack > 0.6, `${s.routeOnTrack}`);
  assert.ok(Math.abs(s.lengthRatio - pathLengthM(spur) / pathLengthM(track)) < 1e-6);
});

test("fidelity of a 20,000-point track is quick", () => {
  const corners: LonLat[] = Array.from({ length: 60 }, (_, i) => at((i % 2) * 1500, i * 800));
  const track = dense(corners, 3.5);
  assert.ok(track.length >= 20_000, `${track.length}`);
  const started = performance.now();
  const f = fidelity(track, track.filter((_, i) => i % 10 === 0));
  const elapsed = performance.now() - started;
  assert.ok(f.trackCovered > 0.99);
  assert.ok(elapsed < 5000, `${elapsed} ms`);
});

test("refining adds a via in the middle of the longest stretch the route missed, in its place", () => {
  // The track takes a 600 m bulge north that the route cuts straight across.
  const track = dense([at(0, 0), at(1000, 0), at(1000, 300), at(1600, 300), at(1600, 0), at(3000, 0)]);
  const route = dense([at(0, 0), at(3000, 0)]);
  const vias = [track[0], at(500, 0), track.at(-1)!];
  const refined = refineVias(track, vias, route, 3);
  assert.equal(refined.length, 4);
  assert.deepEqual(refined[0], vias[0]);
  assert.deepEqual(refined.at(-1), vias.at(-1));
  const added = refined[2];
  assert.ok(haversineM(added, at(1300, 300)) < 40, `${haversineM(added, at(1300, 300))}`);
  assert.deepEqual(refined[1], vias[1]);
});

test("refining picks the longest misses first, and adds nothing when nothing is missed", () => {
  const track = dense([
    at(0, 0), at(500, 0), at(500, 200), at(700, 200), at(700, 0),
    at(2000, 0), at(2000, 400), at(2900, 400), at(2900, 0), at(4000, 0),
  ]);
  const route = dense([at(0, 0), at(4000, 0)]);
  const vias = [track[0], track.at(-1)!];
  const one = refineVias(track, vias, route, 1);
  assert.equal(one.length, 3);
  assert.ok(one[1][0] > at(2000, 0)[0] && one[1][0] < at(2900, 0)[0], "the longer bulge first");
  assert.equal(refineVias(track, vias, route, 5).length, 4);
  assert.deepEqual(refineVias(track, vias, track, 5), vias);
  assert.deepEqual(refineVias(track, vias, route, 0), vias);
});

test("on an out-and-back, a via missed on the way back goes after the outbound vias", () => {
  const out = dense([at(0, 0), at(2000, 0)]);
  // Back along a street 100 m north for its middle kilometre.
  const back = dense([at(2000, 0), at(1500, 0), at(1500, 100), at(500, 100), at(500, 0), at(0, 0)]);
  const track = [...out, ...back.slice(1)];
  const route = [...out, ...out.slice(0, -1).reverse()];
  const vias = [track[0], at(1000, 0), at(2000, 0), at(1000, 100), track.at(-1)!];
  const refined = refineVias(track, vias, route, 1);
  assert.equal(refined.length, 6);
  // The new via sits on the northern street and after the turnaround and the via there.
  const index = refined.findIndex((p) => !vias.includes(p));
  assert.ok(index >= 3, `${index}`);
  assert.ok(haversineM(refined[index], at(1000, 100)) < 600);
});
