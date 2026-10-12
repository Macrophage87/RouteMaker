import { test } from "node:test";
import assert from "node:assert/strict";
import { fidelity } from "./trackMatch.ts";
import { COVERAGE_BBOX, MAX_POINTS, haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { GPX_NS_11, PLAN_TYPE_PREFIX, parseGpx, writeGpx, type GpxFile } from "./gpx.ts";
import {
  IMPORT_START_POINTS,
  ImportError,
  JOIN_GAP_M,
  REFERENCE_MAX_VERTICES,
  REFINE_ADD,
  REFINE_ROUNDS,
  PRUNE_MAX,
  SPUR_MIN_M,
  clipToCoverage,
  fitScore,
  followedPart,
  nextFitStep,
  nextRefinement,
  planFromGpx,
  prunedCount,
  spurRemoval,
  startFit,
  type ImportNote,
} from "./gpxPlan.ts";

const M_LAT = 1 / 111_195;
const M_LON = 1 / (111_195 * Math.cos((38.9 * Math.PI) / 180));
const at = (east: number, north: number): LonLat => [-77.03 + east * M_LON, 38.9 + north * M_LAT];

function file(parts: Partial<GpxFile>): GpxFile {
  return { version: "1.1", tracks: [], routes: [], waypoints: [], skipped: 0, ...parts };
}

function line(from: LonLat, to: LonLat, n: number): LonLat[] {
  return Array.from({ length: n }, (_, i) => [
    from[0] + ((to[0] - from[0]) * i) / (n - 1),
    from[1] + ((to[1] - from[1]) * i) / (n - 1),
  ]);
}

const note = (notes: ImportNote[], kind: ImportNote["kind"]) => notes.find((n) => n.kind === kind);

test("a route of at most 25 points inside the area is the plan, point for point", () => {
  const points = [at(0, 0), at(500, 200), at(900, 900)];
  const plan = planFromGpx(
    file({ routes: [{ type: `${PLAN_TYPE_PREFIX}mass-ride`, points: points.map(([lon, lat]) => ({ lon, lat })) }] }),
  );
  assert.equal(plan.source, "route");
  assert.deepEqual(plan.points, points);
  assert.equal(plan.preset, "mass-ride");
});

test("a route type that is not a RouteMaker ride type sets no ride type", () => {
  // "garmin_gpx:" is as long as the prefix, so only the prefix itself is checked.
  for (const type of [undefined, "cycling", "mass-ride", "garmin_gpx:default"]) {
    const plan = planFromGpx(file({ routes: [{ type, points: [{ lon: -77, lat: 38.9 }, { lon: -77.01, lat: 38.91 }] }] }));
    assert.equal(plan.preset, null, String(type));
    assert.equal(note(plan.notes, "preset-gone"), undefined, String(type));
  }
});

test("a RouteMaker ride type the planner no longer offers opens as Default, with a note", () => {
  const plan = planFromGpx(
    file({
      routes: [
        {
          type: `${PLAN_TYPE_PREFIX}rocket`,
          cmt: `${PLAN_TYPE_PREFIX}stress=5;hills=80`,
          points: [{ lon: -77, lat: 38.9 }, { lon: -77.01, lat: 38.91 }],
        },
      ],
    }),
  );
  assert.equal(plan.preset, "default");
  assert.equal(plan.dials, undefined);
  assert.deepEqual(note(plan.notes, "preset-gone"), { kind: "preset-gone", id: "rocket" });
});

test("an export's sliders and its points' names come back with its ride type", () => {
  const points: LonLat[] = [at(0, 0), at(500, 200), at(900, 900)];
  const text = writeGpx({
    name: "n",
    description: "d",
    attribution: [],
    preset: "cargo",
    dials: { stress: 95, hills: -40, when: "weekday_rush", carrying: "people", assist: true },
    planPoints: points,
    geometry: points,
  });
  const plan = planFromGpx(parseGpx(text));
  assert.equal(plan.preset, "cargo");
  assert.deepEqual(plan.dials, { stress: 95, hills: -40, when: "weekday_rush", carrying: "people", assist: true });
  assert.deepEqual(plan.pointNames, ["Start", "Stop 1", "End"]);
  // "Keep to roads, not trails" comes back too (the trails-off correctness review, 4).
  const roads = planFromGpx(
    parseGpx(
      writeGpx({
        name: "n",
        description: "d",
        attribution: [],
        preset: "default",
        dials: { stress: 70, hills: 0, trailsOff: true },
        planPoints: points,
        geometry: points,
      }),
    ),
  );
  assert.equal(roads.preset, "default");
  assert.deepEqual(roads.dials, { stress: 70, hills: 0, trailsOff: true });
  assert.equal(planFromGpx(parseGpx(text)).dials?.trailsOff, undefined, "absent is trails on");
  // Nonsense in the comment is left out, not guessed.
  const odd = planFromGpx(
    file({
      routes: [
        {
          type: `${PLAN_TYPE_PREFIX}fast`,
          cmt: `${PLAN_TYPE_PREFIX}stress=lots;hills=-10;when=someday;carrying=piano`,
          points: points.map(([lon, lat], i) => ({ lon, lat, ...(i === 1 ? { name: "Union Station" } : {}) })),
        },
      ],
    }),
  );
  assert.deepEqual(odd.dials, { hills: -10 });
  assert.deepEqual(odd.pointNames, [undefined, "Union Station", undefined]);
  // A comment of anyone else's is not sliders.
  const other = planFromGpx(file({ routes: [{ type: `${PLAN_TYPE_PREFIX}fast`, cmt: "Nice ride", points: points.map(([lon, lat]) => ({ lon, lat })) }] }));
  assert.equal(other.preset, "fast");
  assert.equal(other.dials, undefined);
});

test("a track becomes at most 25 points, from its start to its end, all inside the area", () => {
  const track = line(at(0, 0), at(20_000, 5000), 4000);
  const plan = planFromGpx(file({ tracks: [{ segments: [track] }] }));
  assert.equal(plan.source, "track");
  assert.ok(plan.points.length >= 2 && plan.points.length <= MAX_POINTS);
  assert.deepEqual(plan.points[0], track[0]);
  assert.deepEqual(plan.points.at(-1), track.at(-1));
  assert.ok(plan.points.every(insideCoverage));
  assert.ok(Math.abs(plan.referenceM - haversineM(track[0], track.at(-1)!)) < 5);
});

test("segments and tracks are joined in order, and the join is noted", () => {
  const a = line(at(0, 0), at(1000, 0), 50);
  const b = line(at(1000, 100), at(2000, 100), 50);
  const c = line(at(2000, 200), at(3000, 200), 50);
  const plan = planFromGpx(file({ tracks: [{ segments: [a, b] }, { segments: [c] }] }));
  assert.deepEqual(plan.points[0], a[0]);
  assert.deepEqual(plan.points.at(-1), c.at(-1));
  assert.deepEqual(note(plan.notes, "joined"), { kind: "joined", parts: 3 });
  const one = planFromGpx(file({ tracks: [{ segments: [a] }] }));
  assert.equal(note(one.notes, "joined"), undefined);
});

test("the part of a track outside the area is left out and its share said", () => {
  const [, , east] = COVERAGE_BBOX;
  // 3/4 inside, 1/4 beyond the east edge.
  const track = line([east - 0.3, 39.0], [east + 0.1, 39.0], 401);
  const plan = planFromGpx(file({ tracks: [{ segments: [track] }] }));
  assert.ok(plan.points.every(insideCoverage));
  assert.ok(plan.reference.every(insideCoverage));
  const outside = note(plan.notes, "outside");
  assert.ok(outside && outside.kind === "outside" && Math.abs(outside.share - 0.25) < 0.01, JSON.stringify(outside));
});

test("a track that leaves the area and comes back close by is one plan, with the gap noted as a join", () => {
  const [, , east] = COVERAGE_BBOX;
  // Back in about 330 m (0.003 degrees of latitude) from where it left.
  const out = [line([east - 0.1, 39.0], [east + 0.1, 39.0], 21), line([east + 0.1, 39.003], [east - 0.1, 39.003], 21)].flat();
  const plan = planFromGpx(file({ tracks: [{ segments: [out] }] }));
  assert.deepEqual(note(plan.notes, "joined"), { kind: "joined", parts: 2 });
  assert.equal(note(plan.notes, "far-parts"), undefined);
  assert.ok(clipToCoverage(out).runs.length === 2);
});

test("a track that comes back into the area far from where it left follows the longer part only", () => {
  const [, , east] = COVERAGE_BBOX;
  // Leaves at 39.0 N and comes back 0.2 degrees (about 22 km) further north, with a shorter run inside.
  const out = [line([east - 0.1, 39.0], [east + 0.1, 39.0], 21), line([east + 0.1, 39.2], [east - 0.05, 39.2], 21)].flat();
  const plan = planFromGpx(file({ tracks: [{ segments: [out] }] }));
  assert.equal(note(plan.notes, "joined"), undefined);
  assert.deepEqual(note(plan.notes, "far-parts"), { kind: "far-parts", count: 1 });
  assert.ok(plan.reference.every(([, lat]) => lat === 39.0), "only the first, longer run is the reference");
  assert.ok(plan.points.every(([, lat]) => lat === 39.0));
  // About 0.1 degrees of longitude at 39 N, not the 22 km jump.
  assert.ok(plan.referenceM < 9_000, String(plan.referenceM));
});

test("tracks far apart are not joined: the longest is followed and the others are noted as left out", () => {
  const a = line(at(0, 0), at(2000, 0), 50);
  const b = line(at(0, 30_000), at(5000, 30_000), 50);
  const c = line(at(0, 60_000), at(1000, 60_000), 50);
  const plan = planFromGpx(file({ tracks: [{ segments: [a] }, { segments: [b] }, { segments: [c] }] }));
  assert.equal(plan.source, "track");
  assert.deepEqual(plan.points[0], b[0]);
  assert.deepEqual(plan.points.at(-1), b.at(-1));
  assert.ok(Math.abs(plan.referenceM - haversineM(b[0], b.at(-1)!)) < 5, String(plan.referenceM));
  assert.deepEqual(note(plan.notes, "far-parts"), { kind: "far-parts", count: 2 });
  assert.equal(note(plan.notes, "joined"), undefined);
  assert.equal(note(plan.notes, "outside"), undefined, "a gap between parts is not outside the area");
});

test("parts within the join gap of each other are joined, and a far one breaks the chain", () => {
  const a = line(at(0, 0), at(1000, 0), 20);
  const near = JOIN_GAP_M - 50;
  const b = line(at(1000, near), at(2000, near), 20);
  const c = line(at(2000, near + JOIN_GAP_M + 50), at(2500, near + JOIN_GAP_M + 50), 20);
  const result = followedPart([a, b, c]);
  assert.equal(result.pieces.length, 2);
  assert.deepEqual(result.pieces[0][0], a[0]);
  assert.equal(result.leftOut, 1);
  assert.equal(result.outsideShare, 0);
});

test("a track written a segment per point is still one line, as before the far-apart fix", () => {
  const points = line(at(0, 0), at(3000, 0), 40);
  const plan = planFromGpx(file({ tracks: [{ segments: points.map((p) => [p]) }] }));
  assert.equal(plan.source, "track");
  assert.ok(Math.abs(plan.referenceM - 3000) < 5, String(plan.referenceM));
  assert.equal(note(plan.notes, "far-parts"), undefined);
});

test("a far group of several close segments counts as one part left out, and a lone far point as none", () => {
  const main = line(at(0, 0), at(5000, 0), 50);
  const farA = line(at(0, 20_000), at(500, 20_000), 10);
  const farB = line(at(600, 20_000), at(1000, 20_000), 10);
  const lone = [at(0, 40_000)];
  const result = followedPart([main, farA, farB, lone]);
  assert.equal(result.pieces.length, 1);
  assert.equal(result.leftOut, 1);
  const plan = planFromGpx(file({ tracks: [{ segments: [main, farA, farB, lone] }] }));
  assert.deepEqual(note(plan.notes, "far-parts"), { kind: "far-parts", count: 1 });
});

test("a file entirely outside the area is refused as such", () => {
  const far = line([-80, 40], [-80.1, 40.1], 10);
  assert.throws(
    () => planFromGpx(file({ tracks: [{ segments: [far] }], waypoints: [{ lon: -80, lat: 40 }] })),
    (e: unknown) => e instanceof ImportError && e.code === "outside",
  );
});

test("an empty file is refused as empty", () => {
  assert.throws(() => planFromGpx(file({})), (e: unknown) => e instanceof ImportError && e.code === "empty");
});

test("waypoints alone are points in file order; unused waypoints beside a track are counted", () => {
  const w = [at(0, 0), at(100, 100), at(300, 0)].map(([lon, lat]) => ({ lon, lat }));
  const plan = planFromGpx(file({ waypoints: w }));
  assert.equal(plan.source, "waypoints");
  assert.deepEqual(plan.points, w.map((p) => [p.lon, p.lat]));
  const withTrack = planFromGpx(file({ waypoints: w, tracks: [{ segments: [line(at(0, 0), at(900, 0), 30)] }] }));
  assert.equal(withTrack.source, "track");
  assert.deepEqual(note(withTrack.notes, "waypoints-unused"), { kind: "waypoints-unused", count: 3 });
});

test("more than 25 waypoints and nothing else cannot be ordered, and is refused", () => {
  const w = Array.from({ length: 30 }, (_, i) => ({ lon: at(i * 50, 0)[0], lat: 38.9 }));
  assert.throws(() => planFromGpx(file({ waypoints: w })), (e: unknown) => e instanceof ImportError && e.code === "waypoints");
});

test("a route denser than 25 points is followed as a line", () => {
  const dense = line(at(0, 0), at(5000, 3000), 200).map(([lon, lat]) => ({ lon, lat }));
  const plan = planFromGpx(file({ routes: [{ points: dense }] }));
  assert.equal(plan.source, "track");
  assert.ok(plan.points.length <= MAX_POINTS);
  assert.deepEqual(note(plan.notes, "dense-route"), { kind: "dense-route", count: 200 });
});

test("a route partly outside the area, with no track, keeps its inside points", () => {
  const points = [at(0, 0), [-80, 40] as LonLat, at(500, 0), at(900, 0)].map(([lon, lat]) => ({ lon, lat }));
  const plan = planFromGpx(file({ routes: [{ points }] }));
  assert.equal(plan.source, "route");
  assert.equal(plan.points.length, 3);
  assert.ok(note(plan.notes, "outside"));
});

test("skipped points are passed on as a note", () => {
  const plan = planFromGpx(file({ skipped: 4, tracks: [{ segments: [line(at(0, 0), at(900, 0), 30)] }] }));
  assert.deepEqual(note(plan.notes, "skipped"), { kind: "skipped", count: 4 });
});

test("a 20,000-point track plans quickly, with a drawing line of at most 5,000 vertices", () => {
  // A wiggly 20k-point line: 100 m legs zigzagging 30 m, 5 m apart.
  const track: LonLat[] = Array.from({ length: 20_000 }, (_, i) => at(i * 5, (Math.floor(i / 20) % 2) * 30 + (i % 20) * 1.5 * ((Math.floor(i / 20) % 2) ? -1 : 1)));
  const started = performance.now();
  const plan = planFromGpx(file({ tracks: [{ segments: [track] }] }));
  const elapsed = performance.now() - started;
  assert.ok(plan.reference.length <= REFERENCE_MAX_VERTICES, `${plan.reference.length}`);
  assert.ok(plan.points.length <= MAX_POINTS);
  assert.ok(elapsed < 5000, `${elapsed} ms`);
});

test("an exported plan opens again as the same points and ride type", () => {
  const planPoints = [at(0, 0), at(1200, 300), at(2000, -400), at(2600, 100)];
  const xml = writeGpx({
    name: "Mass Ride route, 3.2 km",
    description: "x",
    attribution: [],
    preset: "mass-ride",
    planPoints,
    geometry: line(at(0, 0), at(2600, 100), 300),
  });
  assert.match(xml, new RegExp(`xmlns="${GPX_NS_11}"`));
  const plan = planFromGpx(parseGpx(xml));
  assert.equal(plan.source, "route");
  assert.equal(plan.preset, "mass-ride");
  assert.equal(plan.points.length, planPoints.length);
  plan.points.forEach((p, i) => assert.ok(haversineM(p, planPoints[i]) < 0.2, `${i}`));
  // The exported track comes back as the line to compare against.
  assert.ok(plan.reference.length >= 2);
});

/** A wiggly track: 40 legs of 300 m, alternately 150 m north and south. */
const WIGGLE: LonLat[] = line(at(0, 0), at(300, 150), 30).concat(
  ...Array.from({ length: 39 }, (_, k) => line(at(300 * (k + 1), k % 2 ? 0 : 150), at(300 * (k + 2), k % 2 ? 150 : 0), 30).slice(1)),
);

test("a track starts from its 15 most significant corners", () => {
  const plan = planFromGpx(file({ tracks: [{ segments: [WIGGLE] }] }));
  assert.equal(plan.points.length, IMPORT_START_POINTS);
});

test("fitting adds points where the route missed the track, up to 25 and three rounds", () => {
  const plan = planFromGpx(file({ tracks: [{ segments: [WIGGLE] }] }));
  // A route straight from start to end misses most of the wiggle.
  const straight = line(WIGGLE[0], WIGGLE.at(-1)!, 500);
  const next = nextRefinement(plan.reference, plan.points, straight, 0);
  assert.ok(next && next.length > plan.points.length && next.length <= plan.points.length + REFINE_ADD, `${next?.length}`);
  assert.deepEqual(next[0], plan.points[0]);
  assert.deepEqual(next.at(-1), plan.points.at(-1));
  // No more rounds than allowed, never past the cap, and none once the track is followed.
  assert.equal(nextRefinement(plan.reference, plan.points, straight, REFINE_ROUNDS), null);
  const full = Array.from({ length: MAX_POINTS }, (_, i) => WIGGLE[i * 40]);
  assert.equal(nextRefinement(plan.reference, full, straight, 0), null);
  const near = Array.from({ length: MAX_POINTS - 2 }, (_, i) => WIGGLE[i * 40]);
  assert.equal(nextRefinement(plan.reference, near, straight, 0)?.length, MAX_POINTS);
  assert.equal(nextRefinement(plan.reference, plan.points, plan.reference, 0), null);
  // A route that follows 97% or more is left alone, even with a short miss to fill.
  const nearly = WIGGLE.map((p, i): LonLat => (i >= 600 && i < 615 ? [p[0], p[1] + 80 / 111_195] : p));
  assert.equal(nextRefinement(plan.reference, plan.points, nearly, 0), null);
});

/**
 * The Mass Ride import fix: a straight 4 km track east with a point halfway,
 * which the route can reach only by leaving the track at 1.5 km, looping 800 m
 * north round the block and coming back to the point from the far side, then
 * riding on east. The file's way there is one the ride type does not ride.
 */
const EAST: LonLat[] = line(at(0, 0), at(4000, 0), 401);
const EAST_STOPS: LonLat[] = [EAST[0], EAST[200], EAST[400]];
function path(...corners: Array<[number, number]>): LonLat[] {
  const out: LonLat[] = [];
  corners.forEach(([e, n], i) => {
    if (i === 0) return;
    const [e0, n0] = corners[i - 1];
    const steps = Math.max(1, Math.round(Math.hypot(e - e0, n - n0) / 10));
    out.push(...line(at(e0, n0), at(e, n), steps + 1).slice(i === 1 ? 0 : 1));
  });
  return out;
}
const LOOPED = path([0, 0], [1500, 0], [1500, 800], [2500, 800], [2500, 0], [2000, 0]);
const LOOPED_ROUTE = [...LOOPED, ...path([2000, 0], [4000, 0]).slice(1)];
const LOOPED_ENDS = [LOOPED.length - 1, LOOPED_ROUTE.length - 1];

test("a point the route loops round to reach is the one to take out; a block's detour is not", () => {
  assert.deepEqual(spurRemoval(EAST, EAST_STOPS, LOOPED_ROUTE, LOOPED_ENDS), [1]);
  // Without leg ends, or with too few of them, nothing is offered.
  assert.equal(spurRemoval(EAST, EAST_STOPS, LOOPED_ROUTE, undefined), null);
  assert.equal(spurRemoval(EAST, EAST_STOPS, LOOPED_ROUTE, [LOOPED_ROUTE.length - 1]), null);
  // A loop's return leg after the last point is not read.
  const back = [...LOOPED_ROUTE, ...path([4000, 0], [0, 0]).slice(1)];
  assert.deepEqual(spurRemoval(EAST, EAST_STOPS, back, [...LOOPED_ENDS, back.length - 1]), [1]);
  // A removal already tried is not offered again.
  assert.equal(spurRemoval(EAST, EAST_STOPS, LOOPED_ROUTE, LOOPED_ENDS, [`${EAST_STOPS[1][0]},${EAST_STOPS[1][1]}`]), null);
  // Round one block (100 m north, so 200 m extra, under SPUR_MIN_M) is a one-way's detour, left alone.
  const block = path([0, 0], [1900, 0], [1900, 100], [2000, 100], [2000, 0]);
  const blockRoute = [...block, ...path([2000, 0], [4000, 0]).slice(1)];
  assert.ok(200 < SPUR_MIN_M);
  assert.equal(spurRemoval(EAST, EAST_STOPS, blockRoute, [block.length - 1, blockRoute.length - 1]), null);
});

/** Two points on the stretch the ride type cannot ride, at 2.0 and 2.2 km, each looped round for. */
const TWO_STOPS: LonLat[] = [EAST[0], EAST[200], EAST[220], EAST[400]];
const TWO_LEGS = [
  LOOPED,
  path([2000, 0], [2000, -600], [2700, -600], [2700, 0], [2200, 0]),
  path([2200, 0], [4000, 0]),
];
const TWO_ROUTE = TWO_LEGS.reduce<LonLat[]>((all, leg) => (all.length ? [...all, ...leg.slice(1)] : [...leg]), []);
const TWO_ENDS = TWO_LEGS.reduce<number[]>((ends, leg) => [...ends, (ends.at(-1) ?? 0) + leg.length - 1], []);

test("points next to each other on one looped stretch are taken out together first, then one at a time", () => {
  assert.deepEqual(spurRemoval(EAST, TWO_STOPS, TWO_ROUTE, TWO_ENDS), [1, 2]);
  const fit = { ...startFit(TWO_STOPS), rounds: REFINE_ROUNDS };
  const both = nextFitStep(EAST, fit, TWO_ROUTE, TWO_ENDS)!;
  assert.deepEqual(both.points, [EAST[0], EAST[400]]);
  // That went worse: back to the four points, and the worst on its own is tried next.
  const worse = path([0, 0], [0, 1500], [4000, 1500], [4000, 0]);
  const back = nextFitStep(EAST, both, worse, [worse.length - 1])!;
  assert.deepEqual(back.points, TWO_STOPS);
  const single = nextFitStep(EAST, back, TWO_ROUTE, TWO_ENDS)!;
  assert.equal(single.points.length, 3);
  assert.equal(single.removing, 1);
});

test("the fit score counts the route's own detours, not only the file it covers", () => {
  assert.ok(Math.abs(fitScore(fidelity(EAST, EAST)) - 1) < 1e-9);
  // The loop covers 89% of the file, yet 38% of it is off the file, and the score says so.
  const looped = fidelity(EAST, LOOPED_ROUTE);
  assert.ok(looped.trackCovered > 0.85 && looped.routeOnTrack < 0.65);
  assert.ok(fitScore(looped) < 0.75);
  assert.equal(fitScore({ trackCovered: 0, routeOnTrack: 0, lengthRatio: 0 }), 0);
});

test("fitting takes out a point the route looped round for, and keeps it out when that helps", () => {
  const fit = { ...startFit(EAST_STOPS), rounds: REFINE_ROUNDS };
  const step = nextFitStep(EAST, fit, LOOPED_ROUTE, LOOPED_ENDS);
  assert.ok(step);
  assert.equal(step.phase, "prune");
  assert.deepEqual(step.points, [EAST_STOPS[0], EAST_STOPS[2]]);
  // Without that point the route follows the file: kept, and nothing more to try.
  assert.equal(nextFitStep(EAST, step, EAST, [EAST.length - 1]), null);
  assert.equal(prunedCount(step), 1);
});

test("a removal that leaves the fit no better is undone, and the point stays", () => {
  const fit = { ...startFit(EAST_STOPS), rounds: REFINE_ROUNDS };
  const step = nextFitStep(EAST, fit, LOOPED_ROUTE, LOOPED_ENDS)!;
  // Without the point the route went even farther off the file: back to the three points.
  const worse = path([0, 0], [0, 1500], [4000, 1500], [4000, 0]);
  const back = nextFitStep(EAST, step, worse, [worse.length - 1]);
  assert.ok(back);
  assert.deepEqual(back.points, EAST_STOPS);
  // Their route comes again; the point was tried, so fitting ends with them, none taken out.
  assert.equal(nextFitStep(EAST, back, LOOPED_ROUTE, LOOPED_ENDS), null);
  assert.equal(prunedCount(back), 0);
});

test("no more than PRUNE_MAX removals are tried", () => {
  const fit = { ...startFit(EAST_STOPS), rounds: REFINE_ROUNDS, tried: Array.from({ length: PRUNE_MAX }, (_, i) => `x${i}`) };
  assert.equal(nextFitStep(EAST, fit, LOOPED_ROUTE, LOOPED_ENDS), null);
});

test("a round of added points is kept unless it lowers the score, and undone when it does", () => {
  const plan = planFromGpx(file({ tracks: [{ segments: [WIGGLE] }] }));
  const straight = line(WIGGLE[0], WIGGLE.at(-1)!, 500);
  const round = nextFitStep(plan.reference, startFit(plan.points), straight, undefined);
  assert.ok(round && round.rounds === 1 && round.points.length > plan.points.length);
  // A round that leaves the score where it was is kept, and the next round follows it.
  const kept = nextFitStep(plan.reference, round, straight, undefined);
  assert.ok(kept && kept.rounds === 2 && kept.points.length > round.points.length);
  // The route through the added points wandered off the track altogether: undone.
  const astray = line(at(0, 5000), at(12_000, 5000), 500);
  const back = nextFitStep(plan.reference, kept, astray, undefined);
  assert.ok(back);
  assert.deepEqual(back.points, round.points);
  assert.equal(back.phase, "prune");
});
