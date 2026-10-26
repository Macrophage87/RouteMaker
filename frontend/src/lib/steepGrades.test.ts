// v0.12.5's steep grade marks (lib/steepGrades.ts). The owner, 2026-10-26: an orange marker past 5% either way, red
// past 8%, "Have the warning marker indicate the direction of the incline (uphill/downhill)", on Mass and Novice rides.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { contrastRatio } from "../stressStyle.js";
import type { RouteResponse, SteepGradeSpan } from "./api.ts";
import { ROUTE_HAZARD_FILL } from "./routeHazards.ts";
import {
  STEEP_COLOURS,
  STEEP_EDGE,
  STEEP_GRADE_SOURCE,
  STEEP_ICONS,
  SteepGradeKey,
  steepGradeFeatures,
  steepGradeIcon,
  steepGradeLayer,
  steepGradeRepeatLayer,
  steepGradesFor,
  steepGradesSaid,
  steepIconName,
  steepLabel,
} from "./steepGrades.ts";

const LINE: [number, number][] = [
  [-77.0, 38.9],
  [-76.99, 38.9],
  [-76.98, 38.9],
];
const CLIMB: SteepGradeSpan = { from_m: 400, to_m: 900, direction: "up", level: "steep", grade_pct: 6, text: "Steep uphill, up to 6%, for 1,640 ft (500 m)." };
const DROP: SteepGradeSpan = { from_m: 1200, to_m: 1500, direction: "down", level: "very_steep", grade_pct: 11, text: "Very steep downhill, up to 11%, for 980 ft (300 m)." };

function route(extra: Partial<RouteResponse> = {}): RouteResponse {
  return { geometry: { type: "LineString", coordinates: LINE }, distance_m: 1730, ...extra } as RouteResponse;
}

test("each stretch is cut from the route's own line and carries its level, direction and grade", () => {
  const out = steepGradeFeatures(route({ steep_grades: [CLIMB, DROP] }));
  assert.equal(out.features.length, 2);
  const [first, ...rest] = out.features[0].geometry.coordinates;
  assert.ok(first[0] > -77.0 && first[0] < -76.99, "starts inside the first piece");
  assert.ok(rest[rest.length - 1][0] > -76.99, "ends inside the second");
  assert.deepEqual(out.features[0].properties, { level: "steep", direction: "up", label: "+6%" });
  assert.deepEqual(out.features[1].properties, { level: "very_steep", direction: "down", label: "-11%" });
});

test("the profile's metres are scaled by the route's distance to the line as drawn", () => {
  // The route twice the line's length: a stretch from 1,730 m starts at the line's middle.
  const out = steepGradeFeatures(route({ distance_m: 3460, steep_grades: [{ ...CLIMB, from_m: 1730, to_m: 3000 }] }));
  const coordinates = out.features[0].geometry.coordinates;
  assert.ok(Math.abs(coordinates[0][0] - -76.99) < 0.0015, `starts near the middle vertex, ${coordinates[0][0]}`);
});

test("none, null, or no route draws nothing", () => {
  assert.deepEqual(steepGradeFeatures(route()).features, []);
  assert.deepEqual(steepGradeFeatures(route({ steep_grades: null })).features, []);
  assert.deepEqual(steepGradeFeatures(null).features, []);
});

test("the layers are valid over their source and name the four icons", () => {
  const layers = [steepGradeLayer(), steepGradeRepeatLayer()];
  const errors = spec.validateStyleMin({ version: 8, glyphs: "http://x/{fontstack}/{range}.pbf", sources: { [STEEP_GRADE_SOURCE]: { type: "geojson", data: { type: "FeatureCollection", features: [] } } }, layers } as never);
  assert.deepEqual(errors, []);
  assert.deepEqual(STEEP_ICONS.map((i) => steepIconName(i.level, i.direction)), ["steep-steep-up", "steep-steep-down", "steep-very_steep-up", "steep-very_steep-down"]);
});

test("orange and red are told apart by lightness too, the ramp stands out, and neither is the hazard disc", () => {
  for (const level of ["steep", "very_steep"] as const) {
    assert.ok(contrastRatio(STEEP_COLOURS[level].mark, STEEP_COLOURS[level].fill) >= 4.5, level);
    assert.ok(contrastRatio(STEEP_COLOURS[level].fill, ROUTE_HAZARD_FILL) >= 1.5, `${level} is not the hazard's near-black`);
  }
  assert.equal(STEEP_COLOURS.steep.mark !== STEEP_COLOURS.very_steep.mark, true, "dark ramp on orange, white on red");
  assert.ok(contrastRatio(STEEP_COLOURS.steep.fill, STEEP_COLOURS.very_steep.fill) >= 2);
});

test("the ramp rises to the right uphill and falls to the right downhill", () => {
  const up = steepGradeIcon("steep", "up", 2);
  const down = steepGradeIcon("steep", "down", 2);
  assert.equal(up.width, 36);
  const rgb = (icon: typeof up, x: number, y: number) => Array.from(icon.data.slice((y * icon.width + x) * 4, (y * icon.width + x) * 4 + 3));
  const dark = [0x11, 0x18, 0x27];
  // High on the right side (y 13 of 36): ramp uphill, plain fill downhill; and mirrored on the left.
  assert.deepEqual(rgb(up, 26, 13), dark);
  assert.notDeepEqual(rgb(down, 26, 13), dark);
  assert.deepEqual(rgb(down, 9, 13), dark);
  assert.notDeepEqual(rgb(up, 9, 13), dark);
  assert.equal(up.data[3], 0, "the rounded corner is clear");
  assert.deepEqual(rgb(up, 18, 1), [0xff, 0xff, 0xff], "white rim");
  assert.equal(STEEP_EDGE, "#ffffff");
});

test("the label signs the grade by direction", () => {
  assert.equal(steepLabel(CLIMB), "+6%");
  assert.equal(steepLabel(DROP), "-11%");
});

test("the announcement counts them and names the steepest, and none says nothing", () => {
  assert.equal(steepGradesSaid({ steep_grades: [] }), null);
  assert.equal(steepGradesSaid({}), null);
  assert.equal(steepGradesSaid({ steep_grades: [CLIMB] }), "This route has 1 steep grade past 5%: the steepest is 6% uphill. The map marks each.");
  assert.equal(steepGradesSaid({ steep_grades: [CLIMB, DROP] }), "This route has 2 steep grades past 5%, 1 of them past 8%: the steepest is 11% downhill. The map marks each.");
});

test("the key says what each mark means, in words", () => {
  const html = renderToStaticMarkup(createElement(SteepGradeKey));
  assert.match(html, /aria-label="Steep grades key"/);
  assert.match(html, /aria-hidden="true"/);
  assert.ok(html.includes("Steep grade</span><span class=\"hint\"> (orange square): </span>"));
  assert.ok(html.includes("Very steep grade</span><span class=\"hint\"> (red square): </span>"));
  assert.match(html, /uphill or downhill/);
});

test("only Mass Ride and Novice and Nervous are keyed", () => {
  assert.equal(steepGradesFor("mass-ride"), true);
  assert.equal(steepGradesFor("novice"), true);
  assert.equal(steepGradesFor("default"), false);
});
