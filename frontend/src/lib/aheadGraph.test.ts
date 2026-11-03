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
  spreadMarks,
  turnMarks,
  turnsSentence,
  spacedTicks,
  plotHeight,
  PLOT_MAX,
  PLOT_MIN,
  placeCorkerLabels,
  labelStreet,
  graphsThatFit,
  type TurnMark,
  ridersSentence,
  shortStreet,
  spanLevel,
  stressBars,
  stressSentence,
  writeAhead,
  STRESS_TICKS,
  elevationTicks,
  flowTicks,
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

test("off by default; the graphs chosen are kept on this device in More's order, and turning them off is kept too", () => {
  const s = store();
  assert.deepEqual(readAhead(s), []);
  writeAhead(["elevation", "stress"], s);
  assert.equal(s.kept.get(AHEAD_KEY), "stress,elevation");
  assert.deepEqual(readAhead(s), ["stress", "elevation"]);
  writeAhead([], s);
  assert.deepEqual(readAhead(s), []);
  s.setItem(AHEAD_KEY, "nonsense,flow");
  assert.deepEqual(readAhead(s), ["flow"]);
  assert.deepEqual(readAhead({ getItem: () => { throw new Error("blocked"); }, setItem: () => {} }), []);
});

test("the turns strip: each turn the card shows, flagged junctions and Avoid; never work zones; said as counts ahead", () => {
  const cue = (kind: string, atM: number, movement: TurnMark["movement"], severity: TurnMark["severity"], more: object = {}) => ({ kind, atM, movement, severity, ...more });
  const cues = [
    cue("turn", 100, "left", null),
    cue("turn", 900, "right", "orange"),
    cue("turn", 960, "left", null, { joined: true }),
    cue("turn", 1200, "right", null, { cross: "Redland Road" }),
    cue("hazard", 1500, null, "red", { source: "junction" }),
    cue("hazard", 1600, null, "red", { source: "workzone" }),
    cue("busy", 1700, null, "avoid", { source: "avoid" }),
    cue("busy", 1800, null, null),
    cue("turn", 9000, "left", null),
  ];
  const marks = turnMarks(cues, { fromM: 0, toM: AHEAD_M });
  assert.deepEqual(marks, [
    { m: 100, movement: "left", severity: null },
    { m: 900, movement: "right", severity: "orange" },
    { m: 1500, movement: null, severity: "red" },
    { m: 1700, movement: null, severity: "avoid" },
  ], "a jog's later turn, a crossing straight over and a work zone are left off");
  assert.equal(turnsSentence(marks, 500), "Turns ahead: 1. Busy junctions: 2.");
  assert.equal(turnsSentence([], 0), "", "nothing said where there is nothing");
  // Two marks closer than the gap are drawn as one: the arrow kept, in the worse colour.
  assert.deepEqual(spreadMarks([{ m: 900, movement: "right", severity: "orange" }, { m: 1000, movement: null, severity: "red" }, { m: 1500, movement: "left", severity: null }], 200), [
    { m: 900, movement: "right", severity: "red" },
    { m: 1500, movement: "left", severity: null },
  ]);
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
  assert.deepEqual(axisTicks(aheadWindow(0, 50_000)).map((tick) => tick.label), ["0.5", "1", "1.5", "2 mi"]);
  assert.deepEqual(axisTicks(aheadWindow(MI, 50_000, [0])).map((tick) => tick.label), ["−1", "−0.5", "0.5", "1", "1.5", "2 mi"]);
});

test("Ride wires it: one bubble a graph in More, pressed state, off by default, the graph at the top of the bottom panel", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const \[ahead, setAhead\] = useState<AheadView\[\]>\(\(\) => readAhead\(\)\);/);
  assert.match(ride, /aria-pressed=\{aheadShownViews\.includes\(view\)\}/);
  assert.match(ride, /onClick=\{\(\) => toggleAhead\(view\)\}/, "More stays open after a graph bubble (Stephen 2026-11-03: Stay open)");
  assert.match(ride, /const next = on \? ahead\.filter\(\(v\) => v !== view\) : \[\.\.\.ahead, view\];/, "each bubble on or off on its own");
  assert.match(ride, /<AheadGraph views=\{aheadShownViews\} route=\{route\} cues=\{model\.cues\}/, "the graphs on stack, with the turns");
  assert.match(ride, /const sheetShown = notesShown \|\| restShown \|\| aheadShown;/);
  assert.ok(ride.indexOf("<AheadGraph") > ride.indexOf('className="ride-controls"'));
  assert.ok(ride.indexOf("ride-ahead-bubble") < ride.indexOf('className="ride-round ride-topo"'), "before Topo and Settings");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /riderDots=\{rideDots\}/);
  const graph = readFileSync(new URL("../AheadGraph.tsx", import.meta.url), "utf8");
  assert.match(graph, /aria-hidden="true"\s+focusable="false"/, "the picture is hidden; its sentence is read instead");
  assert.doesNotMatch(graph, /aria-describedby/, "the sentence is read once, in its place");
});

test("review fixes: the climb counts from your own height between samples, a steep stretch behind you is drawn but not said, and 'here' for one you are on", () => {
  // A steady 5% climb from 0 to 2000 m, then level.
  const profile = profileOf(80, 50, (m) => (m < 2000 ? m * 0.05 : 100));
  const mid = elevationShape(profile, aheadWindow(1025, 3950));
  assert.ok(mid);
  assert.equal(Math.round(mid.climbM * 10) / 10, 48.8, "from 1025 m, not from the next sample at 1050 m");
  // 5% behind you, level ahead: drawn (a rider stretched the window back), but the sentence's steepest is ahead only.
  const back = elevationShape(profile, aheadWindow(2500, 3950, [1500]));
  assert.ok(back && back.steep.some((s) => s.toM <= 2000));
  assert.ok((back.steepestPct ?? 0) < 1);
  assert.equal(stressSentence(stressBars([span(0, 500, 4), span(500, 5000, 2)], { fromM: 100, toM: 3000 }), 100), "Mostly LTS 2, LTS 4 here.");
  const steps = flowSteps(profileOf(40, 100, () => 10, { riders_per_min: Array.from({ length: 40 }, (_, i) => (i === 0 ? 40 : 150)) }), { fromM: 50, toM: 3000 });
  assert.equal(flowSentence(steps, 50), "Narrowest 40 riders a minute, here.");
});

test("the y axis is labelled: stress levels 1 to 4 and A, round heights in feet, the flow guides", () => {
  assert.deepEqual(STRESS_TICKS.map((tick) => tick.label), ["1", "2", "3", "4", "A"]);
  assert.deepEqual(elevationTicks(10, 30).map((tick) => tick.label), ["50 ft", "75 ft"]);
  assert.deepEqual(elevationTicks(0, 400).map((tick) => tick.label), ["0 ft", "500 ft", "1,000 ft"]);
  for (const [low, high] of [[5, 25], [100, 160], [0, 400]]) {
    const ticks = elevationTicks(low, high);
    assert.ok(ticks.length >= 1 && ticks.length <= 4, `${ticks.length} ticks`);
    assert.ok(ticks.every((tick) => tick.m >= low - 1e-9 && tick.m <= high + 1e-9), "every tick inside the graph");
  }
  assert.deepEqual(flowTicks(150), [60, 120]);
  assert.deepEqual(flowTicks(260), [60, 120, 200]);
  const graph = readFileSync(new URL("../AheadGraph.tsx", import.meta.url), "utf8");
  assert.match(graph, /<YAxis ticks=\{drawn\.yTicks\} panel=\{panel\} \/>/);
});

test("the turns sentence leaves out a part that is zero (v0.19.0 release review)", () => {
  const turn = { m: 600, movement: "left" as const, severity: null };
  const busy = { m: 700, movement: null, severity: "red" as const };
  assert.equal(turnsSentence([turn], 0), "Turns ahead: 1.");
  assert.equal(turnsSentence([busy, busy], 0), "Busy junctions: 2.");
});

test("y labels keep their distance; the bottom one is always kept", () => {
  const ticks = [1, 2, 3, 4, 5].map((n) => ({ y: 100 - n * 9, label: String(n) }));
  assert.deepEqual(spacedTicks(ticks, 13).map((t) => t.label), ["1", "3", "5"]);
  assert.deepEqual(spacedTicks(ticks, 9).map((t) => t.label), ["1", "2", "3", "4", "5"]);
});

test("plots shrink to fit the room the side buttons leave, between their least and most", () => {
  assert.equal(plotHeight(2, Infinity, 100), PLOT_MAX);
  assert.equal(plotHeight(2, 180, 100), 40);
  assert.equal(plotHeight(4, 150, 130), PLOT_MIN);
  assert.equal(plotHeight(1, 1000, 60), PLOT_MAX);
});

test("corker labels: short names, a row each where they would run into one another, left off where no row has room", () => {
  assert.equal(labelStreet("14th Street Northwest"), "14th St NW");
  assert.equal(labelStreet("Massachusetts Avenue Northwest"), "Massachusetts…");
  const near = [
    { at: 100, street: "14th Street Northwest", leftOf: false },
    { at: 110, street: "13th Street Northwest", leftOf: false },
    { at: 120, street: "12th Street Northwest", leftOf: false },
  ];
  const two = placeCorkerLabels(near, 2, 8.4);
  assert.deepEqual(two.map((p) => p.row), [0, 1, null]);
  assert.deepEqual(two.map((p) => p.text), ["14th St NW", "13th St NW", ""], "the third has no room: its name is left off");
  const apart = placeCorkerLabels([{ at: 60, street: "R St", leftOf: false }, { at: 250, street: "Q St", leftOf: true }], 1, 8.4);
  assert.deepEqual(apart.map((p) => [p.row, p.text]), [[0, "R St"], [0, "Q St"]]);
  assert.deepEqual(placeCorkerLabels(near, 0, 8.4).map((p) => p.text), ["", "", ""], "no rows: markers alone");
});

test("Ride gives the graphs only the room the side buttons leave, and their text grows with Large text", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /large=\{textSize === "large"\} maxPx=\{aheadMaxPx\}/);
  assert.match(ride, /middle\.clientHeight \+ graph - railLeastPx\(buttons\) - RAIL_INSET_PX - clear/);
  const graph = readFileSync(new URL("../AheadGraph.tsx", import.meta.url), "utf8");
  assert.match(graph, /const width = Math\.round\(W \/ textZoom\(large\)\);/);
  assert.match(graph, /root\.classList\.contains\(ACCESS_MODE_CLASS\)/);
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /@media \(forced-colors: active\) \{\s*\.ride-ahead-plot \{\s*forced-color-adjust: none;/);
  assert.match(css, /:root\.theme-dark \.ride-ahead-bar \{\s*stroke: var\(--text-muted\);/);
});

test("as many graphs are drawn as fit the room readably, at least one", () => {
  assert.equal(graphsThatFit(4, Infinity, 44, 18), 4);
  assert.equal(graphsThatFit(4, 44 + 3 * 48, 44, 18), 3);
  assert.equal(graphsThatFit(2, 60, 44, 18), 1);
  assert.equal(graphsThatFit(0, 60, 44, 18), 0);
});
