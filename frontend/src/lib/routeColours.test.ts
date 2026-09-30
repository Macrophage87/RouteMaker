import { test } from "node:test";
import assert from "node:assert/strict";
import { FACILITIES, STRESS_TIERS } from "../stressStyle.js";
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import {
  ROUTE_BLUE,
  ROUTE_CASING_PLAIN,
  ROUTE_CLASSES,
  routeLegend,
  routePaint,
  routeSections,
  sectionFeatures,
  spanClass,
} from "./routeColours.ts";
import { UNRATED } from "./stressBar.ts";

// A straight line east along 38.9 N, one vertex every 0.001 degrees (~86.6 m).
const LINE: LonLat[] = Array.from({ length: 11 }, (_, i) => [-77.05 + i * 0.001, 38.9] as LonLat);
const LENGTH = LINE.slice(1).reduce((sum, p, i) => sum + haversineM(LINE[i], p), 0);

function span(from_m: number, to_m: number, tier: number | null, facility: StressSpan["facility"] = "none"): StressSpan {
  return { from_m, to_m, tier, facility };
}

test("each class is drawn in the stress map's own colour, from the shared tokens", () => {
  // OWNER-DECISIONS item 81; the tiles lane owns the palette (item 74).
  for (const tier of STRESS_TIERS) {
    assert.equal(spanClass({ tier: tier.tier, facility: "none" }).color, tier.color, `LTS ${tier.tier}`);
  }
  const path = FACILITIES.find((f) => f.facility === "path");
  assert.equal(spanClass({ tier: 2, facility: "path" }).color, path?.color);
  assert.equal(spanClass({ tier: null, facility: null }).color, UNRATED.color);
  assert.equal(spanClass({ tier: 9, facility: "lane" }).key, "unknown", "a tier the style does not know");
});

test("traffic-free comes before the tier, and a lane is its tier", () => {
  assert.equal(spanClass({ tier: 1, facility: "path" }).key, "path");
  assert.equal(spanClass({ tier: 3, facility: "lane" }).key, "3");
  assert.equal(spanClass({ tier: 5, facility: "protected" }).key, "5");
  assert.equal(spanClass({ tier: null, facility: "path" }).key, "path");
});

test("the legend's classes are traffic-free, the five tiers, then not rated", () => {
  assert.deepEqual(
    ROUTE_CLASSES.map((c) => c.key),
    ["path", "1", "2", "3", "4", "5", "unknown"],
  );
  for (const c of ROUTE_CLASSES) assert.ok(c.short && c.label && /^#[0-9a-f]{6}$/i.test(c.color), c.key);
});

test("the line is cut where the sections meet, in route order, with no gap", () => {
  // Three sections on a 1000 m trace: the line is drawn about 866 m long, so
  // the cuts are scaled to it.
  const sections = routeSections(LINE, [span(0, 300, 3), span(300, 700, 1, "path"), span(700, 1000, 4)]);
  assert.ok(sections);
  assert.deepEqual(
    sections.map((s) => s.key),
    ["3", "path", "4"],
  );
  assert.deepEqual(sections[0].coordinates[0], LINE[0]);
  assert.deepEqual(sections[2].coordinates.at(-1), LINE.at(-1));
  for (let i = 1; i < sections.length; i += 1) {
    assert.deepEqual(sections[i].coordinates[0], sections[i - 1].coordinates.at(-1), "sections meet");
  }
  const lengths = sections.map((s) => s.coordinates.slice(1).reduce((sum, p, i) => sum + haversineM(s.coordinates[i], p), 0));
  assert.ok(Math.abs(lengths[0] - 0.3 * LENGTH) < 1, `first ${lengths[0]}`);
  assert.ok(Math.abs(lengths[1] - 0.4 * LENGTH) < 1, `second ${lengths[1]}`);
  assert.ok(Math.abs(lengths.reduce((a, b) => a + b, 0) - LENGTH) < 0.01);
});

test("a cut between two vertices lands on the line between them", () => {
  const sections = routeSections(LINE, [span(0, 50, 2), span(50, 100, 4)]);
  assert.ok(sections);
  const cut = sections[0].coordinates.at(-1) as LonLat;
  assert.ok(Math.abs(cut[0] - (-77.05 + 0.005)) < 1e-9, `${cut[0]}`);
  assert.equal(cut[1], 38.9);
});

test("adjacent sections of one class are drawn as one", () => {
  const sections = routeSections(LINE, [span(0, 100, 2, "none"), span(100, 200, 2, "lane"), span(200, 300, 3)]);
  assert.deepEqual(
    sections?.map((s) => s.key),
    ["2", "3"],
  );
});

test("no usable sections draws the route in one colour, as before", () => {
  assert.equal(routeSections(LINE, undefined), null);
  assert.equal(routeSections(LINE, []), null);
  assert.equal(routeSections(LINE, [span(10, 100, 1)]), null, "not from 0");
  assert.equal(routeSections(LINE, [span(0, 100, 1), span(120, 200, 2)]), null, "a gap");
  assert.equal(routeSections(LINE, [span(0, 0, 1)]), null, "empty");
  assert.equal(routeSections([LINE[0]], [span(0, 100, 1)]), null, "one point");
  assert.equal(routeSections([LINE[0], LINE[0]], [span(0, 100, 1)]), null, "no length");
});

test("one section covers the whole line", () => {
  const sections = routeSections(LINE, [span(0, 1234, null, null)]);
  assert.equal(sections?.length, 1);
  assert.equal(sections?.[0].key, "unknown");
  assert.deepEqual(sections?.[0].coordinates, LINE);
});

test("the sections become one GeoJSON feature each, coloured", () => {
  const collection = sectionFeatures(routeSections(LINE, [span(0, 500, 1), span(500, 1000, 5)]));
  assert.equal(collection.features.length, 2);
  assert.equal(collection.features[1].properties.color, STRESS_TIERS[4].color);
  assert.equal(collection.features[1].properties.key, "5");
  assert.deepEqual(sectionFeatures(null), { type: "FeatureCollection", features: [] });
});

test("the legend lists this route's classes with their length, miles first", () => {
  const rows = routeLegend([span(0, 1609, 4), span(1609, 2000, 1, "path"), span(2000, 3609, 4)]);
  assert.deepEqual(
    rows.map((r) => [r.key, r.metres]),
    [
      ["path", 391],
      ["4", 3218],
    ],
  );
  assert.deepEqual(routeLegend(undefined), []);
});

test("with sections the casing is the route's blue and the one-colour line is hidden", () => {
  assert.deepEqual(routePaint(true, false), { lineOpacity: 0, sectionOpacity: 1, casingColor: ROUTE_BLUE });
  assert.deepEqual(routePaint(false, false), { lineOpacity: 1, sectionOpacity: 0, casingColor: ROUTE_CASING_PLAIN });
  assert.deepEqual(routePaint(true, true), { lineOpacity: 0, sectionOpacity: 0.45, casingColor: ROUTE_BLUE });
  assert.equal(routePaint(false, true).lineOpacity, 0.45);
});
