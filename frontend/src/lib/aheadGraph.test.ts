// The ride's graphs of the road ahead (Stephen 2026-11-03): the window, each graph's shapes and words, and More's bubbles.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { RouteProfile, StressSpan } from "./api.ts";
import {
  AHEAD_KEY,
  AHEAD_M,
  aheadViews,
  aheadWindow,
  axisTicks,
  barHeight,
  corkerMarks,
  corkerSentence,
  elevationSentence,
  elevationShape,
  flowSentence,
  flowSteps,
  inkOn,
  readAhead,
  ridersSentence,
  shortStreet,
  spanLevel,
  stressBars,
  stressSentence,
  writeAhead,
} from "./aheadGraph.ts";
import { METRES_PER_MILE } from "./format.ts";

const MI = METRES_PER_MILE;
const span = (from_m: number, to_m: number, tier: number | null, half = false, facility: StressSpan["facility"] = "none"): StressSpan => ({ from_m, to_m, tier, facility, half });
const SPANS = [span(0, 1000, 2), span(1000, 1500, 3, true), span(1500, 2500, 2), span(2500, 3000, 5), span(3000, 9000, 1, false, "path")];

function profileOf(n: number, every: number, elevation: (m: number) => number, extra: Partial<RouteProfile> = {}): RouteProfile {
  const m = Array.from({ length: n }, (_, i) => i * every);
  const e = m.map(elevation);
  const g = m.map((_, i) => (i + 1 < n ? ((e[i + 1] - e[i]) / every) * 100 : 0));
  return { interval_m: every, m, elevation_m: e, grade_pct: g, climbs: [], ...extra } as RouteProfile;
}

function store() {
  const kept = new Map<string, string>();
  return { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v), kept };
}

test("off by default; the graph chosen is kept on this device, and turning it off is kept too", () => {
  const s = store();
  assert.equal(readAhead(s), null);
  writeAhead("elevation", s);
  assert.equal(s.kept.get(AHEAD_KEY), "elevation");
  assert.equal(readAhead(s), "elevation");
  writeAhead(null, s);
  assert.equal(readAhead(s), null);
  s.setItem(AHEAD_KEY, "nonsense");
  assert.equal(readAhead(s), null);
  assert.equal(readAhead({ getItem: () => { throw new Error("blocked"); }, setItem: () => {} }), null);
});

test("the bubbles: stress and elevation on any ride with them; flow and corkers first on a Mass Ride only", () => {
  const profile = profileOf(10, 100, () => 50, { riders_per_min: Array(10).fill(150), crossings: [] });
  assert.deepEqual(aheadViews({ preset: "default", profile, stress_spans: SPANS }), ["stress", "elevation"]);
  assert.deepEqual(aheadViews({ preset: "mass-ride", profile, stress_spans: SPANS }), ["flow", "corkers", "stress", "elevation"]);
  assert.deepEqual(aheadViews({ preset: "default", profile: null, stress_spans: undefined }), [], "nothing to draw, no bubble");
  const noCrossings = profileOf(10, 100, () => 50, { riders_per_min: Array(10).fill(null), crossings: null });
  assert.deepEqual(aheadViews({ preset: "mass-ride", profile: noCrossings, stress_spans: SPANS }), ["stress", "elevation"]);
});

test("the window: 2 miles from you, cut at the route's end; on a shared ride, back to the last rider and on to the first", () => {
  assert.deepEqual(aheadWindow(500, 50_000), { fromM: 500, toM: 500 + AHEAD_M, youM: 500, riders: [] });
  assert.equal(aheadWindow(49_000, 50_000).toM, 50_000, "near the end it is shorter");
  const shared = aheadWindow(5000, 50_000, [4200, 9000, 5100]);
  assert.equal(shared.fromM, 4200, "scaled back to the last rider");
  assert.equal(shared.toM, 9000, "and on to the first, where that is past 2 miles");
  assert.deepEqual(shared.riders, [4200, 5100, 9000]);
  assert.deepEqual(aheadWindow(5000, 80_000, [5000 + 11 * MI]).riders, [], "a dot far along a loop is left off");
});

test("stress: half steps and Avoid, the bars taller with the level and labelled, joined where alike", () => {
  assert.equal(spanLevel(span(0, 1, 3, true)), 3.5);
  assert.equal(spanLevel(span(0, 1, 5)), 5);
  assert.equal(spanLevel(span(0, 1, null, false, "path")), 1);
  assert.equal(spanLevel(span(0, 1, null)), null);
  const bars = stressBars(SPANS, { fromM: 500, toM: 3500 });
  assert.deepEqual(bars.map((b) => [b.fromM, b.toM, b.label]), [[500, 1000, "2"], [1000, 1500, "3.5"], [1500, 2500, "2"], [2500, 3000, "A"], [3000, 3500, "1"]]);
  assert.ok(barHeight(1) < barHeight(2) && barHeight(2) < barHeight(3.5) && barHeight(3.5) < barHeight(5), "the height says the level, not colour alone");
  assert.equal(barHeight(5), 1);
  const joined = stressBars([span(0, 100, 2), span(100, 200, 2)], { fromM: 0, toM: 200 });
  assert.equal(joined.length, 1);
  assert.equal(stressSentence(bars, 500), "Mostly LTS 2, up to Avoid in 1.2 miles.");
  assert.equal(stressSentence(stressBars([span(0, 5000, 2)], { fromM: 0, toM: 3000 }), 0), "LTS 2 the whole way.");
});

test("a bar's number is near-black on a light bar and white on a dark one", () => {
  assert.equal(inkOn("#9ed3ac"), "#16181d");
  assert.equal(inkOn("#560a0e"), "#ffffff");
  assert.equal(inkOn("#d6008f"), "#ffffff");
});

test("elevation: the line in the window, the steep stretches marked, the climb and steepest grade ahead said", () => {
  // Flat for 1 km, then 6% for 500 m, then flat.
  const profile = profileOf(60, 50, (m) => (m < 1000 ? 20 : m < 1500 ? 20 + (m - 1000) * 0.06 : 50));
  const w = aheadWindow(0, 2950);
  const shape = elevationShape(profile, w);
  assert.ok(shape);
  assert.equal(shape.points[0][0], 0);
  assert.equal(shape.steep.length, 1);
  assert.equal(shape.steep[0].band, 1);
  assert.deepEqual([shape.steep[0].fromM, shape.steep[0].toM], [1000, 1500]);
  assert.equal(Math.round(shape.climbM), 30);
  assert.equal(elevationSentence(shape, w), "Climb 98 ft (30 m) in the next 1.8 miles, steepest 6%.");
  const flat = elevationShape(profileOf(60, 50, () => 10), aheadWindow(0, 2950));
  assert.ok(flat && flat.highM - flat.lowM >= 20, "a flat stretch is drawn flat, not stretched to fill the graph");
  assert.equal(elevationSentence(flat, aheadWindow(0, 2950)), "Mostly level for the next 1.8 miles.");
});

test("Mass Ride flow: the band colours and the narrowest point ahead", () => {
  const profile = profileOf(40, 100, () => 10, { riders_per_min: Array.from({ length: 40 }, (_, i) => (i === 12 ? 40 : 150)) });
  const steps = flowSteps(profile, { fromM: 0, toM: 3000 });
  assert.equal(steps.length, 30);
  assert.equal(steps[12].color, "#d7191c", "a bottleneck in the bottleneck band's red");
  assert.equal(flowSentence(steps, 0), "Narrowest 40 riders a minute, in 0.7 miles.");
});

test("Mass Ride corkers: each junction needing them in the window, how many, and the next one said", () => {
  const crossing = (m: number, street: string | null, corkers_needed: boolean) => ({ m, street, severity: null, control: "stop" as const, lanes: 2, crossed_tier: 3, corkers_needed, oneway: false });
  const profile = profileOf(40, 100, () => 10, { crossings: [crossing(300, "Florida Ave NW", true), crossing(900, "K St", false), crossing(1500, null, true), crossing(9000, "Far St", true)] });
  const marks = corkerMarks(profile, { fromM: 0, toM: AHEAD_M });
  assert.deepEqual(marks.map((c) => [c.m, c.street, c.corkers]), [[300, "Florida Ave NW", 2], [1500, null, 2]]);
  assert.equal(corkerSentence(marks, 0, true), "Junctions needing corkers: 2. Next: Florida Ave NW in 0.2 miles, corkers: 2.");
  assert.equal(corkerSentence([], 0, false), "No junctions needing corkers ahead. Some junctions were not checked.");
  assert.equal(shortStreet("Massachusetts Avenue Northwest"), "Massachusetts A…");
});

test("riders and the axis: the last rider behind said; ticks counted from you, the last with its unit", () => {
  assert.equal(ridersSentence(aheadWindow(5000, 50_000)), "");
  assert.equal(ridersSentence(aheadWindow(5000, 50_000, [4000, 6000])), "Other riders shown: 2, the last 0.6 miles behind you.");
  assert.equal(ridersSentence(aheadWindow(5000, 50_000, [6000])), "Other riders shown: 1, all ahead of you.");
  assert.deepEqual(axisTicks(aheadWindow(0, 50_000)).map((tick) => tick.label), ["½", "1", "1½", "2 mi"]);
  assert.deepEqual(axisTicks(aheadWindow(MI, 50_000, [0])).map((tick) => tick.label), ["−1", "−½", "½", "1", "1½", "2 mi"]);
});

test("Ride wires it: one bubble a graph in More, pressed state, off by default, the graph at the top of the bottom panel", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const \[ahead, setAhead\] = useState<AheadView \| null>\(\(\) => readAhead\(\)\);/);
  assert.match(ride, /aria-pressed=\{aheadView === view\}/);
  assert.match(ride, /const next = aheadView === view \? null : view;/, "the lit bubble turns it off");
  assert.match(ride, /const sheetShown = notesShown \|\| restShown \|\| aheadShown;/);
  assert.ok(ride.indexOf("<AheadGraph") > ride.indexOf('className="ride-controls"'));
  assert.ok(ride.indexOf("ride-ahead-bubble") < ride.indexOf('className="ride-round ride-topo"'), "before Topo and Settings");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /riderDots=\{rideDots\}/);
  const graph = readFileSync(new URL("../AheadGraph.tsx", import.meta.url), "utf8");
  assert.match(graph, /aria-hidden="true" focusable="false"/, "the picture is hidden; its sentence is read instead");
  assert.match(graph, /aria-describedby=\{`\$\{id\}-s`\}/);
});
