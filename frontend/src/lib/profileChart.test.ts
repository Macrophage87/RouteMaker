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
  GRADE_BANDS,
  axisDistance,
  bottleneckMark,
  bottleneckRows,
  chartKind,
  climbRows,
  corkerWords,
  crossingClause,
  crossingMarkerWords,
  crossingRows,
  elevationLine,
  elevationRange,
  flowBand,
  flowShapes,
  foldName,
  gradeBand,
  gradeBandShapes,
  gradeWords,
  jumpTargets,
  labelWidth,
  linear,
  lonLatAt,
  nearestIndex,
  nextCrossing,
  placeCrossings,
  shortStreet,
  positionAfterKey,
  readingAt,
  ridersTop,
  ridersWords,
  sectionWords,
  spanAt,
  stepLength,
  stripSections,
  summaryText,
  tierAt,
  tierWords,
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
          { m: 2100, street: null, severity: null, control: "cross_stop", lanes: 2, crossed_tier: 3, kind: "crossing", corkers_needed: true },
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
  assert.equal(r.text, "Mile 0.7: grade 6%, about 90 riders per minute (tight, slowed by the climb). Next: an unnamed street at mile 1.3, corkers needed.");
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
  assert.match(text, /The narrowest point carries about 90 riders per minute \(tight\) at mile 0\.7, marked on the chart; the typical stretch about 190\./);
  assert.match(text, /2 major intersections, 2 needing corkers\./);
  assert.doesNotMatch(text, /not checked|could not be traced|Avoid/);
  assert.doesNotMatch(text, /Traffic stress/);
});

test("the intersections table says each marker's shape and whether corkers are needed", () => {
  const { profile } = build("mass-ride", true);
  const rows = crossingRows(profile);
  assert.deepEqual(rows[0], { mile: "Mile 0.5", street: "7th St", marker: "Higher stress (orange triangle)", corkers: "Corkers needed" });
  assert.deepEqual(rows[1], { mile: "Mile 1.3", street: "an unnamed street", marker: "Crosses a busy road (LTS 3), cross traffic stops (dot)", corkers: "Corkers needed" });
  const crossing = (profile.crossings as ProfileCrossing[])[0];
  assert.equal(corkerWords(crossing), "corkers needed");
  assert.equal(corkerWords({ ...crossing, corkers_needed: false }), "no corkers needed");
  assert.equal(nextCrossing(profile.crossings, 800), profile.crossings![1]);
  assert.equal(nextCrossing(profile.crossings, 790), profile.crossings![0]);
  assert.equal(nextCrossing(null, 0), null);
});

function crossing(m: number, street: string, severity: ProfileCrossing["severity"]): ProfileCrossing {
  return { m, street, severity, control: "signal", lanes: 4, crossed_tier: severity ? 3 : 2, corkers_needed: severity !== null };
}

test("street names are abbreviated on the chart only", () => {
  assert.equal(shortStreet("15th Street Northwest"), "15th St NW");
  assert.equal(shortStreet("Pennsylvania Avenue Southeast"), "Pennsylvania Ave SE");
  assert.equal(shortStreet("Mass Ave"), "Mass Ave");
  assert.equal(shortStreet("Pierce Street"), "Pierce St");
});

test("labels that would collide go on a second line, or are thinned, the more stressful kept first, and every junction keeps its marker", () => {
  const x = linear(0, 1000, 46, 352);
  const list = [crossing(100, "Mass Avenue", null), crossing(120, "7th Street Northwest", "red"), crossing(140, "8th Street", null), crossing(600, "14th Street", "orange")];
  const placed = placeCrossings(list, x, 46, 352);
  assert.equal(placed.length, 4);
  // 7th St NW (very high stress) takes the first line, Mass Ave goes under it, and 8th St, which clears neither, is dropped.
  assert.deepEqual(
    placed.map((p) => [p.labelled, p.row]),
    [
      [true, 1],
      [true, 0],
      [false, 0],
      [true, 0],
    ],
  );
  assert.deepEqual(
    placed.map((p) => p.label),
    ["Mass Ave", "7th St NW", "8th St", "14th St"],
  );
  // Nothing written on one line overlaps another there.
  for (const row of [0, 1]) {
    const line = placed.filter((p) => p.labelled && p.row === row).sort((a, b) => a.x - b.x);
    for (let i = 1; i < line.length; i += 1) assert.ok(line[i].x - line[i - 1].x > 30);
  }
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
    { from_m: 0, to_m: 500, tier: 1, facility: "path", unpaved: null },
    { from_m: 500, to_m: 1000, tier: 4, facility: "none", unpaved: null },
  ]);
  assert.equal(stripSections([{ from_m: 0, to_m: 10, tier: 2, facility: "none", unpaved: true }], 10)[0].unpaved, true);
  assert.deepEqual(stripSections(undefined, 1000), []);
});

// ---- The review revision (the six-lens review's should-fixes; OWNER-DECISIONS 147, 325, 396) ----

test("the grade key reads as words, and each band has a pattern as well as the amber", () => {
  assert.deepEqual(
    GRADE_BANDS.map((b) => [b.label, b.pattern]),
    [
      ["Grade 5% to 8%", "dots"],
      ["Grade 8% or more", "hatch"],
    ],
  );
});

test("the guides keep the 327 colours for their lines and swatches", () => {
  assert.deepEqual(
    FLOW_GUIDES.map((g) => [g.at, g.color, g.band]),
    [
      [60, "#d7191c", 0],
      [120, "#f28e2b", 1],
      [200, "#1a9850", 2],
    ],
  );
});

test("a falling estimate is cut at each threshold it crosses, in order along the route", () => {
  const profile: RouteProfile = { interval_m: 30, m: [0, 90], elevation_m: [1, 1], grade_pct: [0, 0], climbs: [], riders_per_min: [210, 50] };
  const x = linear(0, 90, 0, 90);
  const shapes = flowShapes(profile, x, linear(0, 250, 100, 0), 100);
  assert.deepEqual(
    shapes.map((s) => s.band.index),
    [3, 2, 1, 0],
  );
  const starts = shapes.map((s) => Number(/^M([\d.]+) /.exec(s.d)?.[1]));
  for (let i = 1; i < starts.length; i += 1) assert.ok(starts[i] > starts[i - 1], `${starts}`);
  // Where 210 to 50 crosses 120: 90 m x (210 - 120) / 160.
  assert.ok(Math.abs(starts[2] - (90 * 90) / 160) < 0.01, `${starts}`);
});

test("a grade band change splits the shape, and a stretch is in the band of its two grades' mean", () => {
  const m = [0, 30, 60, 90, 120, 150, 180, 210];
  const profile: RouteProfile = { interval_m: 30, m, elevation_m: m.map(() => 10), grade_pct: [0, 6, 6, 6, 9, 9, 9, 0], climbs: [] };
  const plot = { x: linear(0, 210, 0, 210), y: linear(0, 20, 50, 0), left: 0, right: 210, top: 0, bottom: 50 };
  const shapes = gradeBandShapes(profile, plot);
  assert.deepEqual(
    shapes.map((s) => s.band),
    [1, 2],
  );
  // The first stretch (0 then 6: a mean of 3) is not steep, so band 1 starts at 30 m and runs to 120 m.
  assert.match(shapes[0].d, /^M30 50 L30 /);
  assert.match(shapes[0].d, /L120 50 Z$/);
});

test("the scrub never invents a figure: unknown riders are not known, Avoid has no capacity", () => {
  const { route, profile } = build("mass-ride", true);
  const unknown = { ...profile, riders_per_min: profile.riders_per_min!.map((r, i) => (profile.m[i] === 600 ? null : r)) };
  const text = readingAt(route, unknown, 600).text;
  assert.match(text, /^Mile 0\.4: level, riders per minute not known\./);
  assert.doesNotMatch(text, /about 0|bottleneck/);
  const avoid = { ...unknown, avoid: [{ from_m: 570, to_m: 630 }] };
  assert.match(readingAt(route, avoid, 600).text, /^Mile 0\.4: level, Avoid, no carrying capacity\./);
  assert.equal(ridersWords(profile, 0, 3000, 0), "about 0 riders per minute (bottleneck)");
  assert.equal(ridersWords(profile, null, 3000, 0), "riders per minute not known");
  assert.equal(ridersWords(profile, 100, 3000, -6), "about 100 riders per minute (tight, spaced out for the descent)");
  assert.equal(ridersWords(profile, 100, 1200, 6), "about 100 riders per minute (tight, slowed by the climb)");
  assert.equal(ridersWords(profile, 100, 1200, 0.5), "about 100 riders per minute (tight)");
});

test("intersections not checked say so; none at all says nothing; a gap ahead is named", () => {
  const { route, profile } = build("mass-ride", true);
  assert.match(readingAt(route, { ...profile, crossings: null }, 600).text, / Intersections not checked\.$/);
  assert.match(readingAt(route, { ...profile, crossings: [] }, 600).text, /^Mile 0\.4: level, about 190 riders per minute \(good\)\.$/);
  assert.equal(crossingClause({ ...profile, crossings: [], unchecked: [{ from_m: 3000, to_m: 4000 }] }, 600), " Part of the way ahead was not checked for intersections.");
  assert.equal(crossingClause({ ...profile, unchecked: [{ from_m: 3000, to_m: 4000 }] }, 2500), " Part of the way ahead was not checked for intersections.");
  assert.match(crossingClause({ ...profile, unchecked: [{ from_m: 1000, to_m: 1100 }] }, 900), /^ Next: an unnamed street at mile 1\.3, corkers needed\. Part of the way to it was not checked for intersections\.$/);
  assert.equal(crossingClause(profile, 4000), " No major intersections ahead.");
  const summary = summaryText(route, { ...profile, crossings: null });
  assert.match(summary, /Major intersections were not checked for this route\./);
  assert.doesNotMatch(summary, /No major intersections/);
  assert.match(summaryText(route, { ...profile, crossings: [] }), /No major intersections\./);
  assert.match(summaryText(route, { ...profile, unchecked: [{ from_m: 3000, to_m: 4000 }] }), /Part of the route could not be traced/);
  assert.match(summaryText(route, { ...profile, avoid: [{ from_m: 3000, to_m: 3100 }] }), /One stretch is marked Avoid, with no carrying capacity, from mile 1\.9\./);
});

test("the stress said at a spot: tiers, Avoid, a path and an unpaved stretch as the map has them", () => {
  assert.equal(tierWords(5), "Avoid");
  assert.equal(tierWords(4), "LTS 4");
  assert.equal(tierWords(null), null);
  assert.equal(sectionWords({ tier: 1, facility: "path" }), "traffic-free path");
  assert.equal(sectionWords({ tier: 2, facility: "none", unpaved: true }), "unpaved, LTS 2");
  assert.equal(sectionWords({ tier: 1, facility: "path", unpaved: true }), "unpaved traffic-free path");
  assert.equal(sectionWords({ tier: 3, facility: "lane", unpaved: false }), "LTS 3");
  assert.equal(sectionWords(null), null);
  const { route, profile } = build();
  assert.match(readingAt(route, profile, 300).text, /, traffic-free path\.$/);
  // A section's end is the next one's start; past the end is the last, before the start the first.
  assert.equal(tierAt(route.stress_spans, 900), 3);
  assert.equal(tierAt(route.stress_spans, 899), 1);
  assert.equal(tierAt(route.stress_spans, 1e6), 2);
  assert.equal(spanAt(route.stress_spans, -5)?.facility, "path");
  assert.equal(tierAt([], 5), null);
});

test("a grade is rounded to the nearest whole percent", () => {
  assert.equal(gradeWords(6.8), "grade 7%");
  assert.equal(gradeWords(6.4), "grade 6%");
  assert.equal(gradeWords(-0.4), "level");
});

test("the map point is scaled from the API's distance onto the line's own length", () => {
  // A line of about 866 m for a 2,000 m route: halfway along the route is halfway along the line.
  const line: [number, number][] = [
    [-77, 38.9],
    [-77.01, 38.9],
  ];
  const mid = lonLatAt(line, 1000, 2000)!;
  assert.ok(Math.abs(mid[0] - -77.005) < 1e-9 && Math.abs(mid[1] - 38.9) < 1e-9, `${mid}`);
  assert.deepEqual(lonLatAt(line, 5000, 2000), [-77.01, 38.9]);
});

test("a very high stress name is kept before a higher stress one when both lines are taken", () => {
  const x = linear(0, 1000, 46, 352);
  const c = (m: number, street: string, severity: ProfileCrossing["severity"]): ProfileCrossing => ({ m, street, severity, control: "signal", lanes: 4, crossed_tier: 3, corkers_needed: true });
  const placed = placeCrossings([c(100, "A Street", "orange"), c(105, "B Street", "orange"), c(110, "C Street", "red")], x, 46, 352);
  assert.deepEqual(
    placed.map((p) => [p.label, p.labelled, p.row]),
    [
      ["A St", true, 1],
      ["B St", false, 0],
      ["C St", true, 0],
    ],
  );
});

test("the label widths are for the 11-pixel type", () => {
  assert.equal(labelWidth("14th St"), 7 * 5.9 + 4);
});

test("scales: whole ten-foot steps, and the riders axis to the next 50", () => {
  const { profile } = build();
  const r = elevationRange({ ...profile, elevation_m: profile.elevation_m.map((_, i) => (i === 0 ? 30 : 38)) });
  assert.ok(Math.abs(r.lo * FT - 90) < 1e-9 && Math.abs(r.hi * FT - 130) < 1e-9, `${r.lo * FT} ${r.hi * FT}`);
  assert.equal(ridersTop({ ...profile, riders_per_min: [260] }), 300);
  assert.equal(ridersTop({ ...profile, riders_per_min: [250] }), 250);
});

test("keys: Page Down steps back five, a tie goes to the earlier sample, and letters jump to climbs and intersections", () => {
  const total = 8.1 * MILE;
  const step = stepLength(total);
  assert.equal(positionAfterKey("PageDown", 10 * step, total), 5 * step);
  assert.equal(nearestIndex([0, 30], 15), 0);
  const { profile } = build("mass-ride", true);
  const targets = jumpTargets(profile);
  assert.deepEqual(targets, { climbs: [1000], crossings: [800, 2100] });
  assert.equal(positionAfterKey("c", 0, total, targets), 1000);
  assert.equal(positionAfterKey("c", 1000, total, targets), null);
  assert.equal(positionAfterKey("C", 1500, total, targets), 1000);
  assert.equal(positionAfterKey("i", 0, total, targets), 800);
  assert.equal(positionAfterKey("i", 800, total, targets), 2100);
  assert.equal(positionAfterKey("I", 2100, total, targets), 800);
  assert.equal(positionAfterKey("I", 500, total, targets), null);
  assert.equal(positionAfterKey("i", 0, total), null);
});

test("the narrowest point is marked on the riders area with its figure, kept inside the plot", () => {
  const { profile } = build("mass-ride", true);
  const x = linear(0, 3 * MILE, 46, 352);
  const y = linear(0, 250, 150, 94);
  const mark = bottleneckMark(profile, x, y, 46, 352)!;
  assert.equal(mark.label, "Narrowest 90");
  assert.ok(Math.abs(mark.x - x(1200)) < 1e-9 && Math.abs(mark.y - y(90)) < 1e-9);
  assert.equal(mark.anchor, "middle");
  assert.equal(bottleneckMark({ ...profile, flow: { narrowest_m: 0, narrowest_riders_per_min: 40, typical_riders_per_min: 190 } }, x, y, 46, 352)!.anchor, "start");
  assert.equal(bottleneckMark({ ...profile, flow: null }, x, y, 46, 352), null);
});

test("the bottlenecks table lists each stretch under 60 a minute", () => {
  const m = [0, 30, 60, 90, 120, 150, 180];
  const profile: RouteProfile = { interval_m: 30, m, elevation_m: m.map(() => 1), grade_pct: m.map(() => 0), climbs: [], riders_per_min: [55, 40, 70, null, 59, 59, 200] };
  assert.deepEqual(bottleneckRows(profile), [
    { start: "Mile 0.0", length: "98 ft (30 m)", lowest: "About 40 a minute" },
    { start: "Mile 0.1", length: "98 ft (30 m)", lowest: "About 59 a minute" },
  ]);
  assert.deepEqual(bottleneckRows({ ...profile, riders_per_min: null }), []);
});

test("a dot says why the junction is major: a busy road crossed or joined, and its control", () => {
  const base: ProfileCrossing = { m: 0, street: "Wisconsin Avenue", severity: null, control: "signal", lanes: 4, crossed_tier: 4, kind: "joining", corkers_needed: true };
  assert.equal(crossingMarkerWords(base), "Joins a busy road (LTS 4), traffic signal (dot)");
  assert.equal(crossingMarkerWords({ ...base, kind: "crossing", control: "none", crossed_tier: 3 }), "Crosses a busy road (LTS 3), no signal or sign (dot)");
  assert.equal(crossingMarkerWords({ ...base, kind: undefined, control: "all_stop" }), "Crosses a busy road (LTS 4), all-way stop (dot)");
  assert.equal(crossingMarkerWords({ ...base, severity: "red" }), "Very high stress (red diamond)");
});
