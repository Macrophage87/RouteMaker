/** The rolling stress chart's decisions (OWNER-DECISIONS 460.12, 461d, 461e; profileChart.ts "The rolling stress chart"). */
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ProfileCalm, RouteProfile, RouteResponse } from "./api.ts";
import {
  CALM_FLOOR,
  calmAvoid,
  calmBand,
  calmFigure,
  calmLine,
  calmPeak,
  calmRows,
  calmScale,
  calmSentences,
  calmShapes,
  calmStepLine,
  calmTop,
  calmWords,
  readingAt,
  summaryText,
  usableCalm,
} from "./profileChart.ts";

const MILE = 1609.344;

/** 2 mi sampled every 30 m, LTS 2 throughout, one red crossing at mile 1 (3,300 ft): stress-number.md's worked example. */
function build(over: Partial<ProfileCalm> = {}): { route: RouteResponse; profile: RouteProfile; calm: ProfileCalm } {
  const n = Math.round((2 * MILE) / 30) + 1;
  const m = Array.from({ length: n }, (_, i) => Math.min(i * 30, 2 * MILE));
  const ratio = m.map((d) => (Math.abs(d - MILE) <= MILE / 2 ? 1.62 : 1.0));
  const calm: ProfileCalm = {
    window_m: Math.round(MILE),
    ratio,
    steps: [{ from_m: 0, to_m: Math.round(2 * MILE), ratio: 1, tier: 2 }],
    points: [{ m: Math.round(MILE), calm_m: 1006, kind: "junction", severity: "red" }],
    total_calm_m: Math.round(2.625 * MILE),
    rated_m: Math.round(2 * MILE),
    junctions_counted: true,
    bands: [2.67, 9.34],
    estimate: true,
    ...over,
  };
  const profile: RouteProfile = { interval_m: 30, m, elevation_m: m.map(() => 20), grade_pct: m.map(() => 0), climbs: [], calm };
  const route = {
    preset: "default",
    distance_m: 2 * MILE,
    geometry: { type: "LineString", coordinates: [[-77, 38.9], [-77.01, 38.9]] },
    stress_spans: [{ from_m: 0, to_m: Math.round(2 * MILE), tier: 2, facility: "none" }],
  } as unknown as RouteResponse;
  return { route, profile, calm };
}

test("the score is used only when it has one value a sample and at least one known", () => {
  const { profile, calm } = build();
  assert.equal(usableCalm(profile), calm);
  assert.equal(usableCalm({ ...profile, calm: null }), null);
  assert.equal(usableCalm({ ...profile, calm: { ...calm, ratio: calm.ratio.slice(1) } }), null);
  assert.equal(usableCalm({ ...profile, calm: { ...calm, ratio: calm.ratio.map(() => null) } }), null);
});

test("the bands change at the half-step midpoints the API sends", () => {
  const bands = [2.67, 9.34];
  assert.equal(calmBand(0.55, bands).tier, 2);
  assert.equal(calmBand(2.66, bands).tier, 2);
  assert.equal(calmBand(2.67, bands).tier, 3);
  assert.equal(calmBand(9.34, bands).tier, 4);
});

test("figures: one place under 10, whole above", () => {
  assert.equal(calmFigure(1.42), "1.4");
  assert.equal(calmFigure(0.55), "0.6");
  assert.equal(calmFigure(14.3), "14");
});

test("the scale tops out at 2, 5, 10, 20 ... above the values and the upper guide, and is logarithmic from the floor", () => {
  const { calm } = build();
  assert.equal(calmTop(calm), 20); // 9.34 x 1.15 = 10.7
  assert.equal(calmTop({ ...calm, bands: [1.1, 1.2] }), 2);
  assert.equal(calmTop({ ...calm, bands: [1.1, 1.2], ratio: [...calm.ratio.slice(1), 31] }), 50);
  const y = calmScale(20, 160, 100);
  assert.equal(y(CALM_FLOOR), 160);
  assert.equal(y(0.1), 160);
  assert.equal(y(20), 100);
  // Equal ratios are equal steps: 1 to 2 is as tall as 5 to 10.
  assert.ok(Math.abs(y(1) - y(2) - (y(5) - y(10))) < 1e-9);
});

test("the area is cut at a guide, so the colour changes where the line crosses it", () => {
  const profile = { m: [0, 100, 200] } as unknown as RouteProfile;
  const calm = { ratio: [1, 5, 1], bands: [3, 9] } as unknown as ProfileCalm;
  const shapes = calmShapes(profile, calm, (m) => m, (r) => -r, 0);
  assert.deepEqual(
    shapes.map((s) => s.band.tier),
    [2, 3, 2],
  );
  // The first cut is at 50 m along (1 to 5 crosses 3 halfway).
  assert.match(shapes[0].d, /L50 -3 L50 0 Z$/);
});

test("the line and the step line break where nothing is rated", () => {
  const profile = { m: [0, 100, 200, 300] } as unknown as RouteProfile;
  const calm = {
    ratio: [1, null, 2, 2],
    steps: [
      { from_m: 0, to_m: 100, ratio: 1, tier: 2 },
      { from_m: 100, to_m: 200, ratio: null, tier: null },
      { from_m: 200, to_m: 300, ratio: 2, tier: 3 },
    ],
  } as unknown as ProfileCalm;
  assert.equal(calmLine(profile, calm, (m) => m, (r) => r), "M0 1 M200 2 L300 2");
  assert.equal(calmStepLine(calm, (m) => m, (r) => r, 300), "M0 1 L100 1 M200 2 L300 2");
});

test("Avoid stretches are joined and clipped to the axis", () => {
  const calm = {
    steps: [
      { from_m: 0, to_m: 100, ratio: 1, tier: 2 },
      { from_m: 100, to_m: 200, ratio: 14, tier: 5 },
      { from_m: 200, to_m: 400, ratio: 14, tier: 5 },
    ],
  } as unknown as ProfileCalm;
  assert.deepEqual(calmAvoid(calm, 300), [{ from_m: 100, to_m: 300 }]);
});

test("the scrub adds the rolling figure and its words after the tier", () => {
  const { route, profile } = build();
  const r = readingAt(route, profile, MILE);
  assert.equal(r.calm, 1.62);
  assert.match(r.text, /LTS 2\. Rolling stress 1\.6 calm miles per mile \(LTS 1 to 2 level\)\.$/);
  assert.match(readingAt(route, profile, 0).text, /Rolling stress 1\.0 calm miles per mile/);
});

test("a mile with Avoid in it says so", () => {
  const { calm } = build({ steps: [{ from_m: 0, to_m: 1000, ratio: 1, tier: 2 }, { from_m: 1000, to_m: 1100, ratio: 14, tier: 5 }] });
  assert.match(calmWords(calm, 3, 1500) ?? "", /LTS 3 level, with Avoid in this mile/);
  assert.doesNotMatch(calmWords(calm, 3, 3000) ?? "", /Avoid/);
  assert.equal(calmWords(calm, null, 0), null);
});

test("the summary gives the total in calm miles and km, the most stressful mile and what is in it", () => {
  const { route, profile, calm } = build();
  const peak = calmPeak(profile, calm);
  assert.ok(peak && peak.ratio === 1.62);
  const text = calmSentences(profile, calm).join(" ");
  assert.match(text, /Rolling stress: 2\.6 calm mi \(4\.2 calm km\) over 2(\.0)? mi .* rated, 1\.3 calm miles per mile on average/);
  assert.match(text, /most stressful mile is around mile 0\.5: 1\.6 calm miles per mile \(LTS 1 to 2 level\), with 1 very high stress junction\./);
  assert.match(text, /estimated from its stress level/);
  assert.match(summaryText(route, profile), /Rolling stress: /);
});

test("junctions that could not be read are said to be uncounted", () => {
  const { profile, calm } = build({ junctions_counted: false, points: [] });
  assert.match(calmSentences(profile, calm).join(" "), /Junctions could not be read for this route, so they are not counted\./);
});

test("the table reads every half mile on a short route, with the start and the end", () => {
  const { profile, calm } = build();
  const rows = calmRows(profile, calm, 2 * MILE);
  assert.deepEqual(
    rows.map((r) => r.at),
    ["Mile 0.0", "Mile 0.5", "Mile 1.0", "Mile 1.5", "Mile 2.0"],
  );
  assert.deepEqual(
    rows.map((r) => r.value),
    ["1.0", "1.6", "1.6", "1.6", "1.0"],
  );
  assert.equal(rows[1].reads, "LTS 1 to 2 level");
});
