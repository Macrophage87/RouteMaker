/**
 * A Mass Ride's three charts (the owner, 2026-10-10: "Riders per minute, Corker load, Elevation") and the
 * corker load's math (lib/profileChart.ts "The corker load"; OWNER-DECISIONS 139, 142, 147, 400): the
 * rolling count of junctions needing corkers over the half mile around each point, per mile.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileCrossing, RouteProfile, RouteResponse } from "./api.ts";
import { formatAxisPerMile } from "./format.ts";
import {
  CORKER_WINDOW_M,
  MASS_CHARTS,
  corkerArea,
  corkerAt,
  corkerCell,
  corkerLine,
  corkerLoad,
  corkerRate,
  corkerReading,
  corkerSentences,
  corkerTop,
  corkerWindowWords,
  corkersPerMile,
  crossingRows,
  elevationReading,
  massReadings,
  massSummaries,
  readingAt,
  summaryText,
} from "./profileChart.ts";

const MILE = 1609.344;
const HALF = CORKER_WINDOW_M / 2;

function junction(m: number, corkers = true, street: string | null = `${Math.round(m)} St`): ProfileCrossing {
  return { m, street, severity: null, control: "signal", lanes: 2, crossed_tier: corkers ? 3 : 2, kind: "crossing", corkers_needed: corkers };
}

function profileWith(crossings: ProfileCrossing[] | null, extra: Partial<RouteProfile> = {}, length = 3 * MILE): RouteProfile {
  const n = Math.round(length / 30) + 1;
  const m = Array.from({ length: n }, (_, i) => i * 30);
  return {
    interval_m: 30,
    m,
    elevation_m: m.map((d) => 30 + d * 0.001),
    grade_pct: m.map(() => 0),
    climbs: [],
    riders_per_min: m.map(() => 190),
    flow: { narrowest_riders_per_min: 190, narrowest_m: 0, typical_riders_per_min: 190 },
    avoid: [],
    unchecked: [],
    crossings,
    crossings_complete: crossings === null ? null : true,
    ...extra,
  };
}

const route = (length = 3 * MILE) =>
  ({
    preset: "mass-ride",
    distance_m: length,
    geometry: { type: "LineString", coordinates: [[-77, 38.9], [-77.01, 38.9]] },
    stress_spans: [{ from_m: 0, to_m: length, tier: 2, facility: "none" }],
    stress_m: {},
    attribution: [],
    duration_s: 1,
  }) as unknown as RouteResponse;

test("the three charts, in the owner's order, each with a heading and a slider name", () => {
  assert.deepEqual(
    MASS_CHARTS.map((c) => c.heading),
    ["Riders per minute", "Corker load", "Elevation"],
  );
  assert.deepEqual(
    MASS_CHARTS.map((c) => c.name),
    ["Riders per minute along the route", "Corker load along the route", "Elevation along the route"],
  );
});

test("the window is half a mile (0.8 km), and a count over it is given per mile", () => {
  assert.equal(CORKER_WINDOW_M, MILE / 2);
  assert.equal(corkerWindowWords(), "half mile (0.8 km)");
  assert.equal(corkersPerMile(1), 2);
  assert.equal(corkersPerMile(3), 6);
  assert.equal(corkerRate(6), "6 per mile (3.7 per km)");
  assert.equal(corkerRate(2), "2 per mile (1.2 per km)");
  assert.deepEqual(formatAxisPerMile(6), ["6/mi", "(3.7/km)"]);
});

test("one junction mid-route: 1 in the half mile around it, 0 elsewhere, the step a quarter mile either side", () => {
  const total = 3 * MILE;
  const load = corkerLoad(profileWith([junction(MILE)]), total);
  assert.ok(load);
  assert.deepEqual(
    load.steps.map((s) => [Math.round(s.from_m), Math.round(s.to_m), s.count, s.perMile]),
    [
      [0, Math.round(MILE - HALF), 0, 0],
      [Math.round(MILE - HALF), Math.round(MILE + HALF), 1, 2],
      [Math.round(MILE + HALF), Math.round(total), 0, 0],
    ],
  );
  assert.deepEqual(load.junctions, [MILE]);
  assert.equal(load.peak?.count, 1);
  // The window is half-open: in from a quarter mile before, out exactly a quarter mile after.
  assert.equal(corkerAt(load, MILE - HALF).count, 1);
  assert.equal(corkerAt(load, MILE - HALF - 1).count, 0);
  assert.equal(corkerAt(load, MILE + HALF - 1).count, 1);
  assert.equal(corkerAt(load, MILE + HALF).count, 0);
});

test("the window counts every junction it holds: close ones add up, and the peak is the first highest step", () => {
  // 400 m apart (about a quarter mile): the half mile around 1,400 m holds the junctions at 1,000, 1,400 and 1,800.
  const load = corkerLoad(profileWith([junction(1000), junction(1400), junction(1800), junction(4000)]), 3 * MILE);
  assert.ok(load);
  assert.equal(corkerAt(load, 1400).count, 3);
  assert.equal(corkerAt(load, 1400).perMile, 6);
  assert.equal(corkerAt(load, 1200).count, 2);
  assert.equal(corkerAt(load, 4000).count, 1);
  assert.equal(load.peak?.count, 3);
  assert.ok(load.peak && load.peak.from_m <= 1400 && load.peak.to_m > 1400);
  // Neighbouring steps never repeat a count, and the steps run end to end from 0 to the route's end.
  for (let i = 1; i < load.steps.length; i += 1) {
    assert.notEqual(load.steps[i].count, load.steps[i - 1].count);
    assert.equal(load.steps[i].from_m, load.steps[i - 1].to_m);
  }
  assert.equal(load.steps[0].from_m, 0);
  assert.equal(load.steps.at(-1)?.to_m, 3 * MILE);
  assert.equal(corkerTop(load), 6);
});

test("the edges: the window is cut at the ends and still divided by the whole half mile, so a junction at the start reads 2 a mile, not more", () => {
  const total = 2 * MILE;
  const load = corkerLoad(profileWith([junction(0), junction(total)], {}, total), total);
  assert.ok(load);
  assert.equal(corkerAt(load, 0).count, 1);
  assert.equal(corkerAt(load, 0).perMile, 2);
  assert.equal(corkerAt(load, total).count, 1);
  assert.equal(corkerAt(load, total).perMile, 2);
  assert.equal(corkerAt(load, MILE).count, 0);
  // Past either end a position reads the nearest step.
  assert.equal(corkerAt(load, -10).count, 1);
  assert.equal(corkerAt(load, total + 10).count, 1);
  // A junction placed past the route's end is drawn at the end.
  const past = corkerLoad(profileWith([junction(total + 50)], {}, total), total);
  assert.deepEqual(past?.junctions, [total]);
});

test("a route shorter than the window: one step, the count of everything on it", () => {
  const total = 300;
  const load = corkerLoad(profileWith([junction(100), junction(200)], {}, total), total);
  assert.ok(load);
  assert.deepEqual(load.steps.map((s) => [s.from_m, s.to_m, s.count]), [[0, 300, 2]]);
  assert.equal(load.peak?.perMile, 4);
});

test("junctions needing no corkers are not counted", () => {
  const load = corkerLoad(profileWith([junction(1000, false), junction(1100)]), 3 * MILE);
  assert.ok(load);
  assert.equal(corkerAt(load, 1050).count, 1);
  assert.deepEqual(load.junctions, [1100]);
});

test("no major intersections: a load of 0 along the whole route, one step, no peak, and the words say so", () => {
  const profile = profileWith([]);
  const load = corkerLoad(profile, 3 * MILE);
  assert.ok(load);
  assert.deepEqual(load.steps.map((s) => [s.from_m, s.to_m, s.count]), [[0, 3 * MILE, 0]]);
  assert.equal(load.peak, null);
  assert.equal(corkerTop(load), 4);
  const words = corkerSentences(profile, load).join(" ");
  assert.match(words, /^No major intersections\. No junction needs corkers, so the corker load is 0 along the whole route\./);
  assert.match(corkerReading(profile, load, 500), /^Mile 0\.3: no junctions needing corkers in the half mile around\.$/);
  // Junctions that all need none: the same 0 load.
  const none = profileWith([junction(500, false)]);
  assert.equal(corkerLoad(none, 3 * MILE)?.peak, null);
});

test("intersections not checked: no load at all (never a 0), and every word says it is not known", () => {
  const profile = profileWith(null);
  assert.equal(corkerLoad(profile, 3 * MILE), null);
  assert.equal(corkerLoad(profileWith(undefined as unknown as null), 3 * MILE), null);
  assert.deepEqual(corkerSentences(profile, null), ["Major intersections were not checked for this route, so the corker load is not known."]);
  assert.equal(corkerReading(profile, null, 1000), "Mile 0.6: intersections not checked, so the corker load is not known.");
  const summaries = massSummaries(route(), profile, null);
  assert.match(summaries.corkers, /not checked/);
  assert.doesNotMatch(summaries.corkers, /0 along/);
});

test("a partial list (only the flagged junctions found) is marked, and its words keep the caveat", () => {
  const profile = profileWith([junction(1000)], { crossings_complete: false });
  const load = corkerLoad(profile, 3 * MILE);
  assert.equal(load?.partial, true);
  assert.match(corkerSentences(profile, load).join(" "), /may be incomplete/);
  const empty = profileWith([junction(1000, false)], { crossings_complete: false });
  assert.match(corkerSentences(empty, corkerLoad(empty, 3 * MILE)).join(" "), /None of the junctions found needs corkers\./);
});

test("a stretch not checked for intersections is carried with the load and said where the window touches it", () => {
  const profile = profileWith([junction(1000)], { unchecked: [{ from_m: 3000, to_m: 3500 }] });
  const load = corkerLoad(profile, 3 * MILE);
  assert.ok(load);
  assert.deepEqual(load.unchecked, [{ from_m: 3000, to_m: 3500 }]);
  assert.match(corkerReading(profile, load, 3200), /Part of that half mile was not checked for intersections\./);
  assert.doesNotMatch(corkerReading(profile, load, 1000), /not checked/);
});

test("the corker reading: the count, the rate (per km in brackets) and the next intersection with corkers", () => {
  const profile = profileWith([junction(1000, true, "14th Street"), junction(1400, true, "15th Street")]);
  const load = corkerLoad(profile, 3 * MILE);
  assert.equal(
    corkerReading(profile, load, 1200),
    "Mile 0.7: 2 junctions needing corkers in the half mile around, 4 per mile (2.5 per km). Next: 15th Street at mile 0.9, corkers needed.",
  );
  assert.match(corkerReading(profile, load, 600), /^Mile 0\.4: 1 junction needing corkers in the half mile around, 2 per mile \(1\.2 per km\)\. Next: 14th Street/);
  assert.match(corkerSentences(profile, load).join(" "), /The corker load is highest from mile 0\.\d to 0\.\d: 2 junctions needing corkers in the half mile around, 4 per mile \(2\.5 per km\)\./);
});

test("where the highest load comes back further on, the summary names the first and counts the rest", () => {
  const profile = profileWith([junction(1000), junction(3000)]);
  const words = corkerSentences(profile, corkerLoad(profile, 3 * MILE)).join(" ");
  assert.match(words, /The corker load is highest from mile 0\.4 to 0\.9, and at 1 more place: 1 junction needing corkers in the half mile around, 2 per mile \(1\.2 per km\)\./);
});

test("the shapes: one step line from the start to the end, closed to the baseline for the area", () => {
  const load = corkerLoad(profileWith([junction(1000)]), 3 * MILE);
  assert.ok(load);
  const x = (m: number) => m / 100;
  const y = (v: number) => 100 - v * 10;
  const line = corkerLine(load, x, y);
  assert.ok(line.startsWith("M0 100 L"));
  assert.equal((line.match(/[ML]/g) ?? []).length, load.steps.length * 2);
  const area = corkerArea(load, x, y, 100);
  assert.ok(area.startsWith("M0 100 L0 100") && area.endsWith("Z"));
});

test("the intersections table gets the corker load at each junction when it is given one", () => {
  const profile = profileWith([junction(1000), junction(1400), junction(2500, false)]);
  const load = corkerLoad(profile, 3 * MILE);
  const rows = crossingRows(profile, load);
  assert.deepEqual(rows.map((r) => r.load), ["4 per mile (2.5 per km)", "4 per mile (2.5 per km)", "None"]);
  assert.equal(crossingRows(profile)[0].load, undefined);
  assert.equal(corkerCell({ from_m: 0, to_m: 1, count: 0, perMile: 0 }), "None");
});

test("each chart's summary and reading is its own part; together they are the old summary", () => {
  const r = route();
  const profile = profileWith([junction(1000)], { climbs: [{ from_m: 1000, to_m: 1400, gain_m: 24, avg_grade_pct: 6, max_grade_pct: 7, tier: 2 }] });
  const load = corkerLoad(profile, 3 * MILE);
  const s = massSummaries(r, profile, load);
  assert.match(s.elevation, /^Over 3\.0 mi \(4\.8 km\), elevation runs from/);
  assert.match(s.elevation, /1 sustained climb, listed in the table\.$/);
  assert.doesNotMatch(s.elevation, /riders|corker/);
  assert.match(s.riders, /riders per minute/);
  assert.doesNotMatch(s.riders, /elevation|corker/);
  assert.match(s.corkers, /^1 major intersection, 1 needing corkers\. /);
  // The old one-chart summary is unchanged: elevation, riders, intersections.
  assert.equal(summaryText(r, profile, "mass"), [s.elevation, s.riders, "1 major intersection, 1 needing corkers."].join(" "));
  const read = massReadings(r, profile, load, 1000);
  assert.equal(read.riders, readingAt(r, profile, 1000, "mass").text);
  assert.match(read.corkers, /^Mile 0\.6: 1 junction needing corkers/);
  assert.equal(read.elevation, elevationReading(profile, 1000));
  assert.match(read.elevation, /^Mile 0\.6: elevation \d+ ft \(\d+ m\), level\.$/);
});

test("a Mass Ride with no riders figures still has a riders summary", () => {
  const profile = profileWith([], { flow: null, riders_per_min: null });
  assert.equal(massSummaries(route(), profile, corkerLoad(profile, 3 * MILE)).riders, "Riders per minute are not known for this route.");
});
