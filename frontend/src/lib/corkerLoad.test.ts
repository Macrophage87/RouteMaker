/**
 * A Mass Ride's three charts (the owner, 2026-10-10: "Riders per minute, Corker load, Elevation") and the
 * corker load's math (lib/profileChart.ts "The corker load"; OWNER-DECISIONS 139, 142, 147, 400; the owner,
 * 2026-10-10: "Corkers were intended to also have a rollback based on the length of the ride"): a window
 * the group's length at the anticipated ride size, slid along the route, and the corkers its junctions
 * hold at once; the ride's headline; and the ride size control.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileCrossing, RouteProfile, RouteResponse } from "./api.ts";
import { RIDE_SIZE_DEFAULT, RIDE_SIZE_MAX, RIDE_SIZE_MIN, fitDials, fitRideSize, rideSizeOf } from "./dials.ts";
import { RIDE_SIZE_LABEL, panelView, rideSizeView } from "./dialsPanel.ts";
import { formatGroupLength } from "./format.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import {
  MASS_CHARTS,
  ROTATION_FACTOR,
  corkerArea,
  corkerAt,
  corkerCell,
  corkerFigure,
  corkerHeadline,
  corkerLine,
  corkerLoad,
  corkerReading,
  corkerSentences,
  corkerTop,
  corkersFor,
  corkersMayBeLow,
  crossingRows,
  elevationReading,
  exitOf,
  groupLengthAt,
  groupLengthM,
  groupRoad,
  massReadings,
  massSummaries,
  readingAt,
  summaryText,
} from "./profileChart.ts";

const MILE = 1609.344;
/** The cruising pace the API sends (flow.CRUISE_PACE_MS, 7 mph). */
const PACE = 7 * 0.44704;
/** The level figure the API sends for a 22 ft (6.7 m) road (flow.level_riders_per_min). */
const LEVEL_22FT = 197.98;
/** The group's length at 500 riders on that road. */
const G = (500 / (LEVEL_22FT / 60)) * PACE;

function junction(m: number, corkers = true, street: string | null = `${Math.round(m)} St`, oneway: boolean | null = null): ProfileCrossing {
  return { m, street, severity: null, control: "signal", lanes: 2, crossed_tier: corkers ? 3 : 2, kind: "crossing", corkers_needed: corkers, oneway };
}

function profileWith(crossings: ProfileCrossing[] | null, extra: Partial<RouteProfile> = {}, length = 3 * MILE): RouteProfile {
  const n = Math.round(length / 30) + 1;
  const m = Array.from({ length: n }, (_, i) => Math.min(i * 30, length));
  return {
    interval_m: 30,
    m,
    elevation_m: m.map((d) => 30 + d * 0.001),
    grade_pct: m.map(() => 0),
    climbs: [],
    riders_per_min: m.map(() => 190),
    level_riders_per_min: m.map(() => LEVEL_22FT),
    flow: { narrowest_riders_per_min: 190, narrowest_m: 0, typical_riders_per_min: 190, cruise_pace_ms: PACE, default_level_riders_per_min: LEVEL_22FT },
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

test("the group's length is PLAN's worked example: 500 riders on a 22 ft road at 7 mph is about 1,560 ft (474 m), 2,000 about 1.18 mi", () => {
  const short = groupLengthM(500, LEVEL_22FT, PACE);
  assert.ok(Math.abs(short - 474) < 1, String(short));
  assert.equal(formatGroupLength(short), "1,560 ft (475 m)");
  const long = groupLengthM(2000, LEVEL_22FT, PACE);
  assert.equal(formatGroupLength(long), "1.18 mi (1.9 km)");
  assert.ok(Math.abs(long / MILE - 1.18) < 0.005);
  // No width, no length (never a division by zero).
  assert.equal(groupLengthM(500, 0, PACE), 0);
});

test("the width is read at each point: the group is shorter where the road is wider, and in between across the change", () => {
  const profile = profileWith([], { level_riders_per_min: Array.from({ length: Math.round((3 * MILE) / 30) + 1 }, (_, i) => (i * 30 < 2000 ? LEVEL_22FT : 2 * LEVEL_22FT)) });
  const road = groupRoad(profile, 500);
  assert.ok(road);
  assert.ok(Math.abs(groupLengthAt(road, 1500) - G) < 1);
  assert.ok(Math.abs(groupLengthAt(road, 3500) - G / 2) < 1);
  const across = groupLengthAt(road, 2100);
  assert.ok(across > G / 2 + 1 && across < G - 1, String(across));
  // Near the start the group still forms behind it, at the first stretch's width.
  assert.ok(Math.abs(groupLengthAt(road, 50) - G) < 1);
});

test("an unknown width takes the route's median, or with none the API's default (two 11 ft lanes); with no pace there is no load", () => {
  const levels = profileWith([]).m.map((_, i) => (i % 3 === 0 ? null : LEVEL_22FT));
  const road = groupRoad(profileWith([], { level_riders_per_min: levels }), 500);
  assert.ok(road && Math.abs(groupLengthAt(road, 2000) - G) < 1);
  const none = groupRoad(profileWith([], { level_riders_per_min: null }), 500);
  assert.ok(none && Math.abs(none.typicalLengthM - G) < 1);
  const older = profileWith([junction(1000)], { flow: { narrowest_riders_per_min: 190, narrowest_m: 0, typical_riders_per_min: 190 } });
  assert.equal(groupRoad(older, 500), null);
  assert.equal(corkerLoad(older, 3 * MILE, 500), null);
  assert.match(corkerSentences(older, null).join(" "), /group's length is not known/);
});

test("the sliding window: a junction is held from when the head reaches it until the tail passes, a group's length later", () => {
  const total = 3 * MILE;
  const load = corkerLoad(profileWith([junction(MILE)]), total, 500);
  assert.ok(load);
  assert.ok(Math.abs(load.junctions[0].exit - (MILE + G)) < 1);
  assert.deepEqual(
    load.steps.map((s) => [Math.round(s.from_m), Math.round(s.to_m), s.corkers, s.junctions]),
    [
      [0, Math.round(MILE), 0, 0],
      [Math.round(MILE), Math.round(MILE + G), 2, 1],
      [Math.round(MILE + G), Math.round(total), 0, 0],
    ],
  );
  assert.equal(corkerAt(load, MILE - 1).corkers, 0);
  assert.equal(corkerAt(load, MILE).corkers, 2);
  assert.equal(corkerAt(load, MILE + G - 1).corkers, 2);
  assert.equal(corkerAt(load, MILE + G + 1).corkers, 0);
  // A bigger ride holds it longer.
  const big = corkerLoad(profileWith([junction(MILE)]), total, 1000);
  assert.ok(big && Math.abs(big.junctions[0].exit - (MILE + 2 * G)) < 1);
});

test("junctions closer than the group add up, and the peak is the first highest step", () => {
  // 400 m apart, under the group's 474 m: with the head at 1,450 m both are held.
  const load = corkerLoad(profileWith([junction(1000), junction(1400), junction(4000)]), 3 * MILE, 500);
  assert.ok(load);
  assert.deepEqual([corkerAt(load, 1200).corkers, corkerAt(load, 1450).corkers, corkerAt(load, 1600).corkers, corkerAt(load, 4000).corkers], [2, 4, 2, 2]);
  assert.equal(corkerAt(load, 1450).junctions, 2);
  assert.equal(load.peak?.corkers, 4);
  assert.equal(load.peak?.from_m, 1400);
  for (let i = 1; i < load.steps.length; i += 1) assert.equal(load.steps[i].from_m, load.steps[i - 1].to_m);
  assert.equal(load.steps[0].from_m, 0);
  assert.equal(load.steps.at(-1)?.to_m, 3 * MILE);
  assert.equal(corkerTop(load), 4);
});

test("the ends: a junction at the start is held from 0, one near the end is still held at the end, one past it is placed at the end", () => {
  const total = 2 * MILE;
  const load = corkerLoad(profileWith([junction(0), junction(total - 100)], {}, total), total, 500);
  assert.ok(load);
  assert.equal(corkerAt(load, 0).corkers, 2);
  assert.equal(corkerAt(load, -10).corkers, 2);
  assert.equal(corkerAt(load, MILE).corkers, 0);
  assert.equal(corkerAt(load, total).corkers, 2);
  assert.equal(corkerAt(load, total + 10).corkers, 2);
  const past = corkerLoad(profileWith([junction(total + 50)], {}, total), total, 500);
  assert.equal(past?.junctions[0].m, total);
  assert.equal(past && corkerAt(past, total).corkers, 2);
});

test("a group longer than the route: every junction stays held, so at the end all of them are", () => {
  const total = 600;
  const profile = profileWith([junction(100), junction(300), junction(500, true, "One Way", true)], {}, total);
  const load = corkerLoad(profile, total, 2000);
  assert.ok(load);
  for (const j of load.junctions) assert.ok(j.exit > total);
  assert.deepEqual(
    load.steps.map((s) => [s.from_m, s.to_m, s.corkers, s.junctions]),
    [
      [0, 100, 0, 0],
      [100, 300, 2, 1],
      [300, 500, 4, 2],
      [500, 600, 5, 3],
    ],
  );
  assert.equal(load.peak?.corkers, 5);
  assert.equal(load.headline, 10);
  assert.equal(corkerTop(load), 6);
});

test("corkers per junction: 2 on a two-way road, 1 on a one-way, 2 where it is not known", () => {
  assert.equal(corkersFor({ oneway: false }), 2);
  assert.equal(corkersFor({ oneway: true }), 1);
  assert.equal(corkersFor({ oneway: null }), 2);
  assert.equal(corkersFor({}), 2);
  const load = corkerLoad(profileWith([junction(1000, true, "A", true), junction(1200)]), 3 * MILE, 500);
  assert.ok(load);
  assert.deepEqual([corkerAt(load, 1100).corkers, corkerAt(load, 1300).corkers, corkerAt(load, 1300).junctions], [1, 3, 2]);
});

test("junctions needing no corkers are not held", () => {
  const load = corkerLoad(profileWith([junction(1000, false), junction(1100)]), 3 * MILE, 500);
  assert.ok(load);
  assert.equal(corkerAt(load, 1050).corkers, 0);
  assert.equal(corkerAt(load, 1150).corkers, 2);
  assert.deepEqual(load.junctions.map((j) => j.m), [1100]);
});

test("the headline: the most held at once times the rotation factor (2), rounded up", () => {
  assert.equal(ROTATION_FACTOR, 2);
  const four = corkerLoad(profileWith([junction(1000), junction(1400)]), 3 * MILE, 500);
  assert.equal(four?.headline, 8);
  assert.equal(four && corkerHeadline(four), "about 8");
  const three = corkerLoad(profileWith([junction(1000, true, "A", true), junction(1200)]), 3 * MILE, 500);
  assert.equal(three?.headline, 6);
  const one = corkerLoad(profileWith([junction(1000, true, "A", true)]), 3 * MILE, 500);
  assert.equal(one?.headline, 2);
  const none = corkerLoad(profileWith([]), 3 * MILE, 500);
  assert.equal(none?.headline, 0);
  assert.equal(none?.peak, null);
});

test("where the list may be incomplete or part was not checked, the count may be low: 'at least about', never a firm figure", () => {
  const partial = profileWith([junction(1000)], { crossings_complete: false });
  const load = corkerLoad(partial, 3 * MILE, 500);
  assert.ok(load && corkersMayBeLow(load));
  assert.equal(corkerHeadline(load), "at least about 4");
  const words = corkerSentences(partial, load).join(" ");
  assert.match(words, /At least about 4 corkers for the ride: the most held at once times 2, as corkers leapfrog to the junctions ahead; the count may be low, as only the higher or very high stress junctions were found\./);
  assert.equal(corkerFigure(route(), partial, 500)?.text, "At least about 4 for 500 riders (may be low: only the higher or very high stress junctions were found)");
  const gap = profileWith([junction(1000)], { unchecked: [{ from_m: 3000, to_m: 3500 }] });
  const gapLoad = corkerLoad(gap, 3 * MILE, 500);
  assert.ok(gapLoad && corkersMayBeLow(gapLoad));
  assert.equal(corkerFigure(route(), gap, 500)?.text, "At least about 4 for 500 riders (may be low: part of the route was not checked for intersections)");
  const firm = profileWith([junction(1000)]);
  assert.equal(corkerFigure(route(), firm, 500)?.text, "About 4 for 500 riders");
  assert.equal(corkerFigure(route(), firm, 500)?.label, "Corkers");
  assert.equal(corkerFigure({ ...route(), preset: "commute" } as RouteResponse, firm, 500), null);
});

test("no major intersections: no corkers held anywhere, no peak, and the words say so", () => {
  const profile = profileWith([]);
  const load = corkerLoad(profile, 3 * MILE, 500);
  assert.ok(load);
  assert.deepEqual(load.steps.map((s) => [s.from_m, s.to_m, s.corkers]), [[0, 3 * MILE, 0]]);
  assert.equal(corkerTop(load), 4);
  const words = corkerSentences(profile, load).join(" ");
  assert.match(words, /^No major intersections\. At 500 riders the group is about 1,560 ft \(475 m\) long at cruise, on this route's typical width\. No junction needs corkers, so no corkers are needed\./);
  assert.equal(corkerReading(profile, load, 500).split(" (")[0], "Mile 0.3: no corkers held");
  assert.equal(corkerFigure(route(), profile, 500)?.text, "None needed for 500 riders");
});

test("intersections not checked: no load at all (never a 0), and every word says it is not known", () => {
  const profile = profileWith(null);
  assert.equal(corkerLoad(profile, 3 * MILE, 500), null);
  assert.equal(corkerLoad(profileWith(undefined as unknown as null), 3 * MILE, 500), null);
  assert.deepEqual(corkerSentences(profile, null), ["Major intersections were not checked for this route, so the corkers needed are not known."]);
  assert.equal(corkerReading(profile, null, 1000), "Mile 0.6: intersections not checked, so the corkers needed are not known.");
  assert.equal(corkerFigure(route(), profile, 500), null);
  const summaries = massSummaries(route(), profile, null);
  assert.match(summaries.corkers, /not checked/);
});

test("the corker reading: the corkers and junctions held at once, the ride size and the group's length, and the next intersection", () => {
  const profile = profileWith([junction(1000, true, "14th Street"), junction(1400, true, "15th Street")]);
  const load = corkerLoad(profile, 3 * MILE, 500);
  assert.equal(corkerReading(profile, load, 1200), "Mile 0.7: 2 corkers holding 1 junction at once (500 riders, group about 1,560 ft (475 m) long). Next: 15th Street at mile 0.9, corkers needed.");
  assert.match(corkerReading(profile, load, 1440), /^Mile 0\.9: 4 corkers holding 2 junctions at once \(500 riders, group about 1,560 ft \(475 m\) long\)\./);
  const words = corkerSentences(profile, load).join(" ");
  assert.match(words, /The most held at once is 4 corkers holding 2 junctions, with the head around mile 0\.9\./);
  assert.match(words, /About 8 corkers for the ride: the most held at once times 2, as corkers leapfrog to the junctions ahead\./);
  assert.match(words, /Each junction needing corkers takes 2, or 1 where the road is one-way/);
  // A bigger ride: a longer group, and the reading says so.
  const big = corkerLoad(profile, 3 * MILE, 2000);
  assert.match(corkerReading(profile, big, 1200), /\(2,000 riders, group about 1\.18 mi \(1\.9 km\) long\)/);
});

test("a stretch not checked within the group's stretch is said in the reading", () => {
  const profile = profileWith([junction(1000)], { unchecked: [{ from_m: 3000, to_m: 3200 }] });
  const load = corkerLoad(profile, 3 * MILE, 500);
  assert.ok(load);
  assert.deepEqual(load.unchecked, [{ from_m: 3000, to_m: 3200 }]);
  assert.match(corkerReading(profile, load, 3300), /Part of the group's stretch was not checked for intersections\./);
  assert.doesNotMatch(corkerReading(profile, load, 1000), /not checked/);
});

test("where the highest load comes back further on, the summary names the first and counts the rest", () => {
  const profile = profileWith([junction(1000), junction(3000)]);
  const words = corkerSentences(profile, corkerLoad(profile, 3 * MILE, 500)).join(" ");
  assert.match(words, /The most held at once is 2 corkers holding 1 junction, with the head from mile 0\.6 to 0\.9, and at 1 more place\./);
});

test("the shapes: one step line from the start to the end, closed to the baseline for the area", () => {
  const load = corkerLoad(profileWith([junction(1000)]), 3 * MILE, 500);
  assert.ok(load);
  const x = (m: number) => m / 100;
  const y = (v: number) => 100 - v * 10;
  const line = corkerLine(load, x, y);
  assert.ok(line.startsWith("M0 100 L"));
  assert.equal((line.match(/[ML]/g) ?? []).length, load.steps.length * 2);
  const area = corkerArea(load, x, y, 100);
  assert.ok(area.startsWith("M0 100 L0 100") && area.endsWith("Z"));
  assert.equal(exitOf(load.road, 1000), load.junctions[0].exit);
});

test("the intersections table gets the corkers held at once as the head reaches each junction", () => {
  const profile = profileWith([junction(1000), junction(1400), junction(2500, false)]);
  const load = corkerLoad(profile, 3 * MILE, 500);
  const rows = crossingRows(profile, load);
  assert.deepEqual(rows.map((r) => r.load), ["2 at 1 junction", "4 at 2 junctions", "None"]);
  assert.equal(crossingRows(profile)[0].load, undefined);
  assert.equal(corkerCell({ from_m: 0, to_m: 1, corkers: 0, junctions: 0 }), "None");
});

test("each chart's summary and reading is its own part; together they are the old summary", () => {
  const r = route();
  const profile = profileWith([junction(1000)], { climbs: [{ from_m: 1000, to_m: 1400, gain_m: 24, avg_grade_pct: 6, max_grade_pct: 7, tier: 2 }] });
  const load = corkerLoad(profile, 3 * MILE, 500);
  const s = massSummaries(r, profile, load);
  assert.match(s.elevation, /^Over 3\.0 mi \(4\.8 km\), elevation runs from/);
  assert.doesNotMatch(s.elevation, /riders|corker/);
  assert.match(s.riders, /riders per minute/);
  assert.match(s.corkers, /^1 major intersection, 1 needing corkers\. /);
  // The one-chart summary is the wording before the three charts, word for word (captured from b85e617).
  assert.equal(
    summaryText(r, profile, "mass"),
    "Over 3.0 mi (4.8 km), elevation runs from 98 ft (30 m) to 114 ft (35 m). The route is close to level. 1 sustained climb, listed in the table. Narrowest with the hills: about 190 riders per minute (good), at mile 0.0, marked on the chart. Typical with the hills: about 190 riders per minute. 1 major intersection, 1 needing corkers.",
  );
  assert.equal(summaryText(r, profile, "mass"), [s.elevation, s.riders, "1 major intersection, 1 needing corkers."].join(" "));
  const read = massReadings(r, profile, load, 1020);
  assert.equal(read.riders, readingAt(r, profile, 1020, "mass").text);
  assert.match(read.corkers, /^Mile 0\.6: 2 corkers holding 1 junction at once/);
  assert.equal(read.elevation, elevationReading(profile, 1020));
});

test("a Mass Ride with no riders figures still has a riders summary", () => {
  const profile = profileWith([], { flow: null, riders_per_min: null });
  assert.equal(massSummaries(route(), profile, corkerLoad(profile, 3 * MILE, 500)).riders, "Riders per minute are not known for this route.");
});

test("the ride size: 100 to 2,000 riders in steps of 50, 500 by default, kept only on a Mass Ride and only when moved", () => {
  assert.deepEqual([RIDE_SIZE_MIN, RIDE_SIZE_DEFAULT, RIDE_SIZE_MAX], [100, 500, 2000]);
  assert.equal(fitRideSize(20), 100);
  assert.equal(fitRideSize(5000), 2000);
  assert.equal(fitRideSize(1234), 1250);
  assert.equal(fitRideSize(undefined), undefined);
  assert.equal(rideSizeOf({}), 500);
  assert.equal(rideSizeOf({ rideSize: 800 }), 800);
  assert.equal(fitDials("mass-ride", { rideSize: 800 }).rideSize, 800);
  assert.equal(fitDials("mass-ride", { rideSize: 500 }).rideSize, undefined);
  assert.equal(fitDials("default", { rideSize: 800 }).rideSize, undefined);
});

test("the ride size travels in the plan link as riders=N, and an older link reads the default", () => {
  const dials = fitDials("mass-ride", { rideSize: 1200 });
  const hash = encodePlan([[-77.03, 38.9]], "mass-ride", dials);
  assert.match(hash, /riders=1200/);
  assert.equal(decodePlan(hash).dials?.rideSize, 1200);
  const plain = encodePlan([[-77.03, 38.9]], "mass-ride", fitDials("mass-ride", {}));
  assert.doesNotMatch(plain, /riders=/);
  assert.equal(rideSizeOf(decodePlan(plain).dials ?? {}), 500);
});

test("the ride size slider: its name carries the unit, its value text says riders, and only a Mass Ride shows it", () => {
  assert.equal(RIDE_SIZE_LABEL, "Anticipated ride size (riders)");
  const view = rideSizeView(500);
  assert.equal(view.words, "500 riders");
  assert.deepEqual([view.min, view.max, view.step], [100, 2000, 50]);
  assert.deepEqual(view.ends, ["100", "", "2,000"]);
  assert.equal(rideSizeView(2000).words, "2,000 riders");
  assert.ok(panelView("mass-ride", fitDials("mass-ride", {})).rideSize);
  assert.equal(panelView("default", fitDials("default", {})).rideSize, null);
});

test("the one-chart summary with an Avoid stretch, a partial list and an untraced stretch is unchanged too (captured from b85e617)", () => {
  const profile = profileWith([junction(1000, false)], { unchecked: [{ from_m: 3000, to_m: 3500 }], avoid: [{ from_m: 4000, to_m: 4200 }], crossings_complete: false });
  assert.equal(
    summaryText(route(), profile, "mass"),
    "Over 3.0 mi (4.8 km), elevation runs from 98 ft (30 m) to 114 ft (35 m). The route is close to level. No sustained climbs. Narrowest with the hills: about 190 riders per minute (good), at mile 0.0, marked on the chart. Typical with the hills: about 190 riders per minute. One stretch is marked Avoid, no capacity given, from mile 2.5. Only the higher or very high stress junctions were found, so the list may be incomplete: 1 found, none needing corkers. Part of the route could not be traced, so its width and intersections are not known.",
  );
  // The riders chart's own summary keeps the untraced stretch's width.
  assert.match(massSummaries(route(), profile, corkerLoad(profile, 3 * MILE, 500)).riders, /Part of the route could not be traced, so its width is not known\.$/);
  assert.doesNotMatch(massSummaries(route(), profileWith([]), null).riders, /could not be traced/);
});

test("unchecked stretches and no junction needing corkers: never none along the whole route, but none found where it was checked", () => {
  const profile = profileWith([junction(1000, false)], { unchecked: [{ from_m: 3000, to_m: 3500 }] });
  const load = corkerLoad(profile, 3 * MILE, 500);
  assert.ok(load && load.peak === null && corkersMayBeLow(load));
  const words = corkerSentences(profile, load).join(" ");
  assert.match(words, /No junction needing corkers was found where the route was checked\./);
  assert.doesNotMatch(words, /whole route|no corkers are needed/);
  assert.equal(corkerFigure(route(), profile, 500)?.text, "None found for 500 riders (may be low: part of the route was not checked for intersections)");
});

test("a partial list: the reading says the count may be low at every point, as well as the summary and the headline", () => {
  const profile = profileWith([junction(1000, true, "14th Street"), junction(1400, true, "15th Street")], { crossings_complete: false });
  const load = corkerLoad(profile, 3 * MILE, 500);
  assert.match(corkerReading(profile, load, 1200), /^Mile 0\.7: at least 2 corkers holding 1 junction at once \(500 riders, group about 1,560 ft \(475 m\) long; only flagged junctions were found\)\./);
  assert.match(corkerReading(profile, load, 300), /^Mile 0\.2: no corkers held at the junctions found \(500 riders, group about 1,560 ft \(475 m\) long; only flagged junctions were found\)\./);
  const firm = profileWith([junction(1000)]);
  assert.doesNotMatch(corkerReading(firm, corkerLoad(firm, 3 * MILE, 500), 1200), /flagged|at least/);
});
