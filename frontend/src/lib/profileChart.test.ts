/**
 * The route chart's decisions (OWNER-DECISIONS 322, 323, 328, 329, 332, 333): what a scrub says, the
 * climbs table, the summary, the band shapes, the junction labels' thinning, the keyboard's steps.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileCrossing, RouteProfile, RouteResponse } from "./api.ts";
import {
  FLOW_BANDS,
  FLOW_GUIDES,
  axisDistance,
  chartKind,
  climbRows,
  corkerWords,
  crossingRows,
  elevationLine,
  elevationRange,
  flowBand,
  flowShapes,
  foldName,
  gradeBand,
  gradeBandShapes,
  gradeWords,
  linear,
  lonLatAt,
  nearestIndex,
  nextCrossing,
  placeCrossings,
  positionAfterKey,
  readingAt,
  ridersTop,
  stepLength,
  stripSections,
  summaryText,
  usableProfile,
} from "./profileChart.ts";

const MILE = 1609.344;
const FT = 3.28084;

/** A 3.0 mile route sampled every 30 m: level, a 6% climb from 1000 m, then level; stress and flow built to match. */
function build(preset: RouteResponse["preset"] = "default", withFlow = false): { route: RouteResponse; profile: RouteProfile } {
  const n = Math.round(3 * MILE / 30) + 1;
  const m: number[] = [];
  const elevation: (number | null)[] = [];
  const grade: (number | null)[] = [];
  const riders: (number | null)[] = [];
  for (let i = 0; i < n; i += 1) {
    const d = i * 30;
    m.push(d);
    const up = Math.min(Math.max(d - 1000, 0), 400);
    elevation.push(30 + up * 0.06);
    grade.push(d >= 1000 && d <= 1400 ? 6 : 0);
    riders.push(d >= 1000 && d <= 1400 ? 90 : 190);
  }
  const profile: RouteProfile = {
    interval_m: 30,
    m,
    elevation_m: elevation,
    grade_pct: grade,
    climbs: [
      withFlow
        ? { from_m: 1000, to_m: 1400, gain_m: 24, avg_grade_pct: 6, max_grade_pct: 6.8, tier: 3, capacity_drop_pct: 52, min_riders_per_min: 90 }
        : { from_m: 1000, to_m: 1400, gain_m: 24, avg_grade_pct: 6, max_grade_pct: 6.8, tier: 3 },
    ],
    riders_per_min: withFlow ? riders : null,
    flow: withFlow ? { narrowest_riders_per_min: 90, narrowest_m: 1200, typical_riders_per_min: 190 } : null,
    crossings: withFlow
      ? [
          { m: 800, street: "7th St", severity: "orange", control: "signal", lanes: 4, crossed_tier: 3, corkers_needed: true },
          { m: 2100, street: null, severity: null, control: "stop", lanes: 2, crossed_tier: 2, corkers_needed: false },
        ]
      : null,
  };
  const route = {
    preset,
    distance_m: 3 * MILE,
    geometry: { type: "LineString", coordinates: [[-77, 38.9], [-77.01, 38.9]] },
    stress_spans: [
      { from_m: 0, to_m: 900, tier: 1, facility: "path" },
      { from_m: 900, to_m: 1500, tier: 3, facility: "none" },
      { from_m: 1500, to_m: 3 * MILE, tier: 2, facility: "none" },
    ],
    stress_m: {},
    attribution: [],
    duration_s: 1,
  } as unknown as RouteResponse;
  return { route, profile };
}

test("a ride type other than Mass Ride has the stress chart, a Mass Ride the riders chart", () => {
  assert.equal(chartKind({ preset: "default" }), "stress");
  assert.equal(chartKind({ preset: "mass-ride" }), "mass");
  assert.equal(foldName("stress"), "Elevation and stress");
  assert.equal(foldName("mass"), "Elevation and riders per minute");
});

test("a profile is used only when two samples have a height", () => {
  const { route, profile } = build();
  assert.ok(usableProfile(route) === null);
  assert.ok(usableProfile({ ...route, profile }) !== null);
  assert.equal(usableProfile({ ...route, profile: { ...profile, elevation_m: profile.elevation_m.map(() => null) } }), null);
  assert.equal(usableProfile({ ...route, profile: null }), null);
});

test("the scrub says the mile, the elevation in feet then metres, the grade and the stress tier", () => {
  const { route, profile } = build();
  const r = readingAt(route, profile, 1200);
  assert.equal(r.m, 1200);
  assert.match(r.text, /^Mile 0\.7: elevation \d+ ft \(\d+ m\), grade 6%, LTS 3\.$/);
});

test("the example in the decision: Mile 4.2 ... grade 6%, LTS 2", () => {
  // 4.2 mi is 6759 m: build a longer route level at 94 m / 310 ft to match the sentence the owner gave.
  const m = Array.from({ length: 300 }, (_, i) => i * 30);
  const profile: RouteProfile = {
    interval_m: 30,
    m,
    elevation_m: m.map(() => 94.4),
    grade_pct: m.map(() => 6),
    climbs: [],
  };
  const route = { preset: "default", distance_m: 9000, stress_spans: [{ from_m: 0, to_m: 9000, tier: 2, facility: "none" }] } as unknown as RouteResponse;
  const r = readingAt(route, profile, 6759);
  assert.equal(r.text, "Mile 4.2: elevation 310 ft (94 m), grade 6%, LTS 2.");
});

test("a descent says downhill, a flat stretch level, a missing tier says it is not rated", () => {
  assert.equal(gradeWords(-5.4), "grade 5% downhill");
  assert.equal(gradeWords(0.3), "level");
  assert.equal(gradeWords(null), null);
  const { route, profile } = build();
  const noSpans = { ...route, stress_spans: [] } as RouteResponse;
  assert.match(readingAt(noSpans, profile, 100).text, /stress not rated\.$/);
});

test("a Mass Ride's scrub says the grade, the riders per minute with its band, and the next major intersection with corkers", () => {
  const { route, profile } = build("mass-ride", true);
  const r = readingAt(route, profile, 1200);
  assert.equal(r.text, "Mile 0.7: grade 6%, about 90 riders per minute (tight). Next: an unnamed street at mile 1.3, no corkers needed.");
  const early = readingAt(route, profile, 600);
  assert.equal(early.text, "Mile 0.4: level, about 190 riders per minute (good). Next: 7th St at mile 0.5, corkers needed.");
  const last = readingAt(route, profile, 4000);
  assert.match(last.text, /No major intersections ahead\.$/);
});

test("the spec's own sentence is reproduced for a Mass Ride at mile 1.1", () => {
  const m = Array.from({ length: 100 }, (_, i) => i * 30);
  const profile: RouteProfile = {
    interval_m: 30,
    m,
    elevation_m: m.map(() => 20),
    grade_pct: m.map(() => 6),
    climbs: [],
    riders_per_min: m.map(() => 90),
    crossings: [{ m: 2090, street: "14th St", severity: "orange", control: "signal", lanes: 4, crossed_tier: 3, corkers_needed: true }],
  };
  const route = { preset: "mass-ride", distance_m: 3000, stress_spans: [] } as unknown as RouteResponse;
  assert.equal(readingAt(route, profile, 1770).text, "Mile 1.1: grade 6%, about 90 riders per minute (tight). Next: 14th St at mile 1.3, corkers needed.");
});

test("bands: 5-8% and 8% or more, either way", () => {
  assert.deepEqual([0, 4.9, 5, 7.9, 8, -9, null].map(gradeBand), [0, 0, 1, 1, 2, 2, 0]);
  const { profile } = build();
  const plot = { x: linear(0, 5000, 0, 100), y: linear(0, 100, 50, 0), left: 0, right: 100, top: 0, bottom: 50 };
  const shapes = gradeBandShapes(profile, plot);
  assert.ok(shapes.length >= 1);
  assert.ok(shapes.every((s) => s.band === 1 && s.d.startsWith("M") && s.d.endsWith("Z")));
  const steep = { ...profile, grade_pct: profile.grade_pct.map((g) => (g === 6 ? 9 : g)) };
  assert.ok(gradeBandShapes(steep, plot).every((s) => s.band === 2));
});

test("the elevation line breaks at a missing height, and the axis is whole ten-foot steps at least 40 ft tall", () => {
  const { profile } = build();
  const gap = { ...profile, elevation_m: profile.elevation_m.map((e, i) => (i === 10 ? null : e)) };
  const plot = { x: linear(0, 5000, 0, 100), y: linear(0, 100, 50, 0), left: 0, right: 100, top: 0, bottom: 50 };
  assert.equal((elevationLine(gap, plot).match(/M/g) ?? []).length, 2);
  const range = elevationRange(profile);
  assert.equal(Math.round(range.lo * FT) % 10, 0);
  assert.ok((range.hi - range.lo) * FT >= 39.9);
  const flat = elevationRange({ ...profile, elevation_m: profile.elevation_m.map(() => 50) });
  assert.ok(Math.abs((flat.hi - flat.lo) * FT - 40) < 0.01);
});

test("the distance axis gives miles first and kilometres in brackets", () => {
  assert.equal(axisDistance(0), "0 mi (0 km)");
  assert.equal(axisDistance(8.1 * MILE), "8.1 mi (13 km)");
  assert.equal(axisDistance(4 * MILE), "4 mi (6.4 km)");
  assert.equal(axisDistance(26 * MILE), "26 mi (42 km)");
});

test("the riders bands are the 327 colours, with a distinct pattern each", () => {
  assert.deepEqual(
    FLOW_BANDS.map((b) => b.color),
    ["#d7191c", "#f28e2b", "#1a9850", "#6a3d9a"],
  );
  assert.equal(new Set(FLOW_BANDS.map((b) => b.pattern)).size, 4);
  assert.deepEqual([0, 59, 60, 119, 120, 199, 200, 500].map((r) => flowBand(r).index), [0, 0, 1, 1, 2, 2, 3, 3]);
  assert.deepEqual(FLOW_GUIDES.map((g) => g.at), [60, 120, 200]);
});

test("the area is cut where the estimate crosses a threshold, each run one polygon in one band", () => {
  const profile: RouteProfile = {
    interval_m: 30,
    m: [0, 30, 60, 90],
    elevation_m: [1, 1, 1, 1],
    grade_pct: [0, 0, 0, 0],
    climbs: [],
    riders_per_min: [50, 70, 130, 130],
  };
  const x = linear(0, 90, 0, 90);
  const y = linear(0, 250, 100, 0);
  const shapes = flowShapes(profile, x, y, 100);
  assert.deepEqual(
    shapes.map((s) => s.band.index),
    [0, 1, 2],
  );
  assert.ok(shapes.every((s) => s.d.endsWith("Z")));
  // Missing figures split the area.
  const gap = { ...profile, riders_per_min: [50, null, 130, 130] };
  assert.equal(flowShapes(gap, x, y, 100).length, 1);
  assert.equal(flowShapes({ ...profile, riders_per_min: null }, x, y, 100).length, 0);
});

test("the riders axis reaches at least 250 and the next 50 above the highest figure", () => {
  const { profile } = build("mass-ride", true);
  assert.equal(ridersTop(profile), 250);
  assert.equal(ridersTop({ ...profile, riders_per_min: [120, 530, null] }), 550);
});

test("keys: arrows step, Page keys step five, Home and End go to the ends, the rest are left alone", () => {
  const total = 8.1 * MILE;
  const step = stepLength(total);
  assert.ok(total / step <= 80);
  assert.equal(positionAfterKey("ArrowRight", 0, total), step);
  assert.equal(positionAfterKey("ArrowLeft", 0, total), 0);
  assert.equal(positionAfterKey("ArrowLeft", 3 * step, total), 2 * step);
  assert.equal(positionAfterKey("PageUp", 0, total), 5 * step);
  assert.equal(positionAfterKey("Home", 500, total), 0);
  assert.equal(positionAfterKey("End", 500, total), total);
  assert.equal(positionAfterKey("ArrowRight", total, total), total);
  assert.equal(positionAfterKey("Tab", 0, total), null);
  assert.equal(stepLength(2 * MILE), 0.1 * MILE);
  assert.equal(stepLength(100 * MILE), 2 * MILE);
});

test("the nearest sample, and the map point along the line", () => {
  assert.equal(nearestIndex([0, 30, 60, 90], 44), 1);
  assert.equal(nearestIndex([0, 30, 60, 90], 46), 2);
  assert.equal(nearestIndex([0, 30, 60, 90], 500), 3);
  assert.equal(nearestIndex([0, 30, 60, 90], -5), 0);
  const line: [number, number][] = [
    [-77, 38.9],
    [-77.01, 38.9],
    [-77.01, 38.91],
  ];
  const start = lonLatAt(line, 0, 2000);
  assert.deepEqual(start, [-77, 38.9]);
  const end = lonLatAt(line, 2000, 2000);
  assert.deepEqual(end, [-77.01, 38.91]);
  const mid = lonLatAt(line, 1000, 2000);
  assert.ok(mid !== null && mid[0] < -77 && mid[0] >= -77.01 - 1e-9);
  assert.equal(lonLatAt([], 5, 10), null);
});

test("the climbs table: start mile, length, gain, average and maximum grade, stress; on a Mass Ride the capacity drop", () => {
  const { profile } = build();
  const [row] = climbRows(profile, "stress");
  assert.equal(row.start, "Mile 0.6");
  assert.equal(row.length, "0.2 mi (0.4 km)");
  assert.equal(row.gain, "79 ft (24 m)");
  assert.equal(row.average, "6%");
  assert.equal(row.maximum, "7%");
  assert.equal(row.stress, "LTS 3");
  assert.equal(row.capacity, null);
  const mass = build("mass-ride", true);
  assert.equal(climbRows(mass.profile, "mass")[0].capacity, "52% fewer riders, down to 90 a minute");
});

test("the summary gives the elevation range, the steepest section, the climbs and the stress", () => {
  const { route, profile } = build();
  const text = summaryText(route, profile);
  assert.match(text, /^Over 3\.0 mi \(4\.8 km\), elevation runs from 98 ft \(30 m\) to 177 ft \(54 m\)\./);
  assert.match(text, /The steepest section is 6% uphill at mile 0\.6\./);
  assert.match(text, /1 sustained climb, listed in the table\./);
  assert.match(text, /Traffic stress along it: .*LTS 1.*LTS 3/);
  assert.match(text, /LTS 3 or worse starts at mile 0\.6\./);
});

test("a Mass Ride's summary names the narrowest point and the major intersections instead of the stress", () => {
  const { route, profile } = build("mass-ride", true);
  const text = summaryText(route, profile);
  assert.match(text, /The narrowest point carries about 90 riders per minute \(tight\) at mile 0\.7; the typical stretch about 190\./);
  assert.match(text, /2 major intersections, 1 needing corkers\./);
  assert.doesNotMatch(text, /Traffic stress/);
});

test("the intersections table says each marker's shape and whether corkers are needed", () => {
  const { profile } = build("mass-ride", true);
  const rows = crossingRows(profile);
  assert.deepEqual(rows[0], { mile: "Mile 0.5", street: "7th St", marker: "Higher stress (orange triangle)", corkers: "Corkers needed" });
  assert.deepEqual(rows[1], { mile: "Mile 1.3", street: "an unnamed street", marker: "Major crossing, stop sign (dot)", corkers: "No corkers needed" });
  const crossing = (profile.crossings as ProfileCrossing[])[0];
  assert.equal(corkerWords(crossing), "corkers needed");
  assert.equal(nextCrossing(profile.crossings, 800), profile.crossings![1]);
  assert.equal(nextCrossing(profile.crossings, 790), profile.crossings![0]);
  assert.equal(nextCrossing(null, 0), null);
});

function crossing(m: number, street: string, severity: ProfileCrossing["severity"]): ProfileCrossing {
  return { m, street, severity, control: "signal", lanes: 4, crossed_tier: severity ? 3 : 2, corkers_needed: severity !== null };
}

test("labels that would collide are thinned, the more stressful kept first, and every junction keeps its marker", () => {
  const x = linear(0, 1000, 46, 352);
  const list = [crossing(100, "Mass Avenue", null), crossing(120, "7th Street Northwest", "red"), crossing(140, "8th Street", null), crossing(600, "14th Street", "orange")];
  const placed = placeCrossings(list, x, 46, 352);
  assert.equal(placed.length, 4);
  assert.deepEqual(
    placed.map((p) => p.labelled),
    [false, true, false, true],
  );
  // Nothing written overlaps.
  const written = placed.filter((p) => p.labelled);
  assert.ok(written[0].x < written[1].x);
});

test("a label at the edge of the plot is kept inside it", () => {
  const x = linear(0, 1000, 46, 352);
  const placed = placeCrossings([crossing(2, "Constitution Avenue", "red"), crossing(998, "Pennsylvania Avenue", "orange")], x, 46, 352);
  assert.deepEqual(
    placed.map((p) => p.anchor),
    ["start", "end"],
  );
  assert.ok(placed.every((p) => p.labelled));
});

test("stress sections are clipped to the axis", () => {
  const spans = [
    { from_m: 0, to_m: 500, tier: 1, facility: "path" as const },
    { from_m: 500, to_m: 1200, tier: 4, facility: "none" as const },
  ];
  const got = stripSections(spans, 1000);
  assert.deepEqual(got, [
    { from_m: 0, to_m: 500, tier: 1 },
    { from_m: 500, to_m: 1000, tier: 4 },
  ]);
  assert.deepEqual(stripSections(undefined, 1000), []);
});
