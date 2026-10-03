import { test } from "node:test";
import assert from "node:assert/strict";
import { COVERAGE_BBOX, MAX_POINTS, haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { GPX_NS_11, PLAN_TYPE_PREFIX, parseGpx, writeGpx, type GpxFile } from "./gpx.ts";
import {
  IMPORT_START_POINTS,
  ImportError,
  REFERENCE_MAX_VERTICES,
  REFINE_ADD,
  REFINE_ROUNDS,
  clipToCoverage,
  nextRefinement,
  planFromGpx,
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

test("a track that leaves the area and comes back is one plan, with the gap noted as a join", () => {
  const [, , east] = COVERAGE_BBOX;
  const out = [line([east - 0.1, 39.0], [east + 0.1, 39.0], 21), line([east + 0.1, 39.01], [east - 0.1, 39.01], 21)].flat();
  const plan = planFromGpx(file({ tracks: [{ segments: [out] }] }));
  assert.deepEqual(note(plan.notes, "joined"), { kind: "joined", parts: 2 });
  assert.ok(clipToCoverage(out).runs.length === 2);
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
