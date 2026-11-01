import { test } from "node:test";
import assert from "node:assert/strict";
import { FACILITIES } from "../stressStyle.js";
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { ROUTE_BAND_WIDTH, ROUTE_LANE_RAIL, laneMarkFeatures, routeLaneMarks, routeSections, spanClass } from "./routeColours.ts";
import { ROUTE_LANES_SOURCE_ID, routeLaneLayers, setRouteSections } from "./mapGlue.ts";

// A straight line east along 38.9 N, one vertex every 0.001 degrees (~86.6 m).
const LINE: LonLat[] = Array.from({ length: 11 }, (_, i) => [-77.05 + i * 0.001, 38.9] as LonLat);
const LENGTH = LINE.slice(1).reduce((sum, p, i) => sum + haversineM(LINE[i], p), 0);

function span(from_m: number, to_m: number, tier: number | null, facility: StressSpan["facility"], extra: Partial<StressSpan> = {}): StressSpan {
  return { from_m, to_m, tier, facility, ...extra };
}

const colour = (facility: string) => FACILITIES.find((f: { facility: string }) => f.facility === facility)!.color;
const lengthOf = (coords: LonLat[]) => coords.slice(1).reduce((sum, p, i) => sum + haversineM(coords[i], p), 0);

test("a route marks its protected and painted lanes, and nothing on a path or a street with no lane", () => {
  // The owner, 2026-11-01: "See if you can mark pbls and painted lanes on the highlighted route as well".
  const spans = [span(0, 200, 1, "path"), span(200, 450, 1, "protected"), span(450, 700, 2, "lane"), span(700, 1000, 3, "none")];
  const marks = routeLaneMarks(LINE, spans, false);
  assert.deepEqual(marks.map((m) => m.facility), ["protected", "lane"]);
  assert.equal(marks[0].color, colour("protected"));
  assert.equal(marks[1].color, colour("lane"));
  // Each mark covers its span's share of the drawn line, scaled as the sections are.
  const scale = LENGTH / 1000;
  assert.ok(Math.abs(lengthOf(marks[0].coordinates) - 250 * scale) < 1);
  assert.ok(Math.abs(lengthOf(marks[1].coordinates) - 250 * scale) < 1);
});

test("the rails sit in the white band: clear of the section's edge by half a pixel and of the casing by a pixel", () => {
  const spans = [span(0, 250, 1, "protected"), span(250, 500, 3, "protected"), span(500, 750, 4, "lane"), span(750, 1000, 5, "protected")];
  for (const mark of routeLaneMarks(LINE, spans, true)) {
    assert.ok(mark.gap + 2 * mark.width <= ROUTE_BAND_WIDTH - 2, `${mark.facility} ${mark.gap} ${mark.width}`);
    assert.ok(mark.width >= 1 && mark.width <= ROUTE_LANE_RAIL[mark.facility]);
  }
  // A calm section leaves room for the protected lane's full posts; a ringed LTS 3 thins them.
  const [calm, ringed] = routeLaneMarks(LINE, spans, true);
  const cls = spanClass(spans[1]);
  assert.equal(calm.width, ROUTE_LANE_RAIL.protected);
  assert.equal(ringed.gap, (cls.ringWidth ?? cls.haloWidth) + 1);
  assert.ok(ringed.width < calm.width);
});

test("painted lanes on LTS 4 and Avoid follow the 'Show bike lanes on high-stress roads' switch; protected lanes always show", () => {
  // OWNER-DECISIONS 275, as on the map.
  const spans = [span(0, 300, 4, "lane"), span(300, 600, 5, "lane"), span(600, 1000, 4, "protected")];
  assert.deepEqual(routeLaneMarks(LINE, spans, false).map((m) => m.facility), ["protected"]);
  assert.deepEqual(routeLaneMarks(LINE, spans, true).map((m) => m.facility), ["lane", "lane", "protected"]);
});

test("a run of one lane on one width is one mark; a change of section width starts another", () => {
  const same = routeLaneMarks(LINE, [span(0, 300, 1, "protected"), span(300, 600, 1, "protected"), span(600, 1000, 2, "none")], false);
  assert.equal(same.length, 1);
  const wider = routeLaneMarks(LINE, [span(0, 300, 1, "lane"), span(300, 600, 3, "lane")], false);
  assert.equal(wider.length, 2);
});

test("no marks on a Mass Ride's capacity route, without spans, or on a one-point line", () => {
  assert.deepEqual(routeLaneMarks(LINE, [span(0, 1000, 1, "protected", { rpm: 40 })], true), []);
  assert.deepEqual(routeLaneMarks(LINE, undefined, true), []);
  assert.deepEqual(routeLaneMarks([LINE[0]], [span(0, 1000, 1, "protected")], true), []);
});

test("the sections are unchanged by the lane marks: one section a class, lanes or not", () => {
  const sections = routeSections(LINE, [span(0, 300, 2, "none"), span(300, 600, 2, "lane"), span(600, 1000, 2, "protected")]);
  assert.equal(sections?.length, 1);
});

test("the map draws the marks as two rails a gap apart, painted under protected, and fills them with the route", () => {
  const layers = routeLaneLayers();
  assert.deepEqual(layers.map((l) => l.id), ["route-lanes-lane", "route-lanes-protected"]);
  for (const layer of layers) {
    assert.deepEqual(layer.paint["line-gap-width"], ["get", "gap"]);
    assert.equal(layer.source, ROUTE_LANES_SOURCE_ID);
  }
  let data: { features: unknown[] } | null = null;
  const paints: [string, string, unknown][] = [];
  const map = {
    getSource: (id: string) => (id === ROUTE_LANES_SOURCE_ID ? { setData: (d: { features: unknown[] }) => (data = d) } : { setData: () => {} }),
    getLayer: () => ({}),
    setPaintProperty: (id: string, name: string, value: unknown) => paints.push([id, name, value]),
  };
  const route = { geometry: { type: "LineString" as const, coordinates: LINE }, stress_spans: [span(0, 500, 1, "protected"), span(500, 1000, 2, "none")] };
  setRouteSections(map, route as never, false);
  assert.equal(data!.features.length, 1);
  assert.deepEqual(paints.find(([id, name]) => id === "route-lanes-protected" && name === "line-opacity")?.[2], 1);
  setRouteSections(map, null, false);
  assert.equal(data!.features.length, 0);
  assert.equal(laneMarkFeatures([]).features.length, 0);
});
