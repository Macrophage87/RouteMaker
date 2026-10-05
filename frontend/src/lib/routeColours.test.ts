import { test } from "node:test";
import assert from "node:assert/strict";
import { FACILITIES, contrastRatio, currentTiers, setAccessibility } from "../stressStyle.js";
import type { StressSpan } from "./api.ts";
import { haversineM, type LonLat } from "./geo.ts";
import {
  ROUTE_AVOID_HALO,
  ROUTE_AVOID_MAGENTA,
  ROUTE_AVOID_MARK,
  ROUTE_AVOID_MARK_DASH,
  ROUTE_BLUE,
  ROUTE_CASING_PLAIN,
  routeClasses,
  routeLegend,
  routeMarkDash,
  routeMarkWidth,
  routePaint,
  routeSections,
  sectionFeatures,
  spanClass,
} from "./routeColours.ts";
import { UNRATED } from "./stressBar.ts";
import { ROUTE_AVOID_LAYER_ID, routeAvoidLayer } from "./mapGlue.ts";
import { readFileSync } from "node:fs";

// A straight line east along 38.9 N, one vertex every 0.001 degrees (~86.6 m).
const LINE: LonLat[] = Array.from({ length: 11 }, (_, i) => [-77.05 + i * 0.001, 38.9] as LonLat);
const LENGTH = LINE.slice(1).reduce((sum, p, i) => sum + haversineM(LINE[i], p), 0);

function span(from_m: number, to_m: number, tier: number | null, facility: StressSpan["facility"] = "none"): StressSpan {
  return { from_m, to_m, tier, facility };
}

test("each class is drawn in the stress map's own colour, from the shared tokens", () => {
  // OWNER-DECISIONS item 81; the tiles lane owns the palette (item 74).
  for (const tier of currentTiers()) {
    if (tier.tier === 5) continue;
    assert.equal(spanClass({ tier: tier.tier, facility: "none" }).color, tier.color, `LTS ${tier.tier}`);
  }
  // Avoid on the route is one magenta (OWNER-DECISIONS 397), paved or unpaved.
  assert.equal(spanClass({ tier: 5, facility: "none" }).color, ROUTE_AVOID_MAGENTA);
  assert.equal(spanClass({ tier: 5, facility: "none", unpaved: true }).color, ROUTE_AVOID_MAGENTA);
  const path = FACILITIES.find((f) => f.facility === "path");
  assert.equal(spanClass({ tier: 2, facility: "path" }).color, path?.color);
  assert.equal(spanClass({ tier: null, facility: null }).color, UNRATED.color);
  assert.equal(spanClass({ tier: 9, facility: "lane" }).key, "unknown", "a tier the style does not know");
});

test("Avoid is magenta on the route in every palette, over a near-black halo 3:1 from it, and only where the route rides it (397)", () => {
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    try {
      for (const key of ["5", "u5"]) {
        const c = routeClasses().find((x) => x.key === key)!;
        assert.equal(c.color, ROUTE_AVOID_MAGENTA, `${key}${on ? " (high contrast)" : ""}`);
        assert.equal(c.halo, ROUTE_AVOID_HALO);
        assert.ok(contrastRatio(c.color, c.halo) >= 3, `${contrastRatio(c.color, c.halo).toFixed(2)}:1`);
      }
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
  // The map's own Avoid roads keep the palette's colour: only the route is repainted.
  assert.notEqual(currentTiers().find((t) => t.tier === 5)?.color, ROUTE_AVOID_MAGENTA);
  assert.equal(routeLegend([span(0, 100, 2), span(100, 200, 3)]).some((r) => r.key === "5"), false, "no Avoid entry on a route without Avoid");
  assert.equal(routeLegend([span(0, 100, 2), span(100, 200, 5)]).find((r) => r.key === "5")?.color, ROUTE_AVOID_MAGENTA);
});

test("traffic-free comes before the tier, and a lane is its tier", () => {
  assert.equal(spanClass({ tier: 1, facility: "path" }).key, "path");
  assert.equal(spanClass({ tier: 3, facility: "lane" }).key, "3");
  assert.equal(spanClass({ tier: 5, facility: "protected" }).key, "5");
  assert.equal(spanClass({ tier: null, facility: "path" }).key, "path");
  // But Avoid comes before traffic-free, so the route line matches the chart's magenta (r3 N3).
  assert.equal(spanClass({ tier: 5, facility: "path" }).key, "5");
  assert.equal(spanClass({ tier: 5, facility: "path" }).color, ROUTE_AVOID_MAGENTA);
});

test("a paved Avoid section carries the white dash-dot, in every palette; nothing else does, and an unpaved Avoid keeps its dots instead", () => {
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    try {
      for (const c of routeClasses()) assert.equal(c.mark, c.key === "5" ? ROUTE_AVOID_MARK : undefined, `${c.key}${on ? " (high contrast)" : ""}`);
      const features = sectionFeatures(routeSections(LINE, [span(0, 300, 3), span(300, 600, 5), span(600, 900, 5, "none")].map((s, i) => (i === 2 ? { ...s, unpaved: true } : s)))).features;
      assert.deepEqual(features.map((f) => [f.properties.key, f.properties.avoid, f.properties.unpaved]), [["3", false, false], ["5", true, false], ["u5", false, true]]);
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
  assert.ok(contrastRatio(ROUTE_AVOID_MARK, ROUTE_AVOID_MAGENTA) >= 3);
  // Its dash is a dash-dot, unlike the unpaved mark's even dots.
  assert.equal(ROUTE_AVOID_MARK_DASH.length, 4);
  assert.notEqual(ROUTE_AVOID_MARK_DASH[0], ROUTE_AVOID_MARK_DASH[2]);
  // The map layer that draws it: only the marked sections, in their mark colour, above the unpaved dots.
  const layer = routeAvoidLayer("route-stress");
  assert.equal(layer.id, ROUTE_AVOID_LAYER_ID);
  assert.deepEqual(layer.filter, ["==", ["get", "avoid"], true]);
  assert.deepEqual(layer.paint["line-color"], ["get", "mark"]);
  assert.deepEqual(layer.paint["line-dasharray"], [...ROUTE_AVOID_MARK_DASH]);
  // At each feature's own mark width, which is the class's (r4 mutation NIT 7).
  assert.deepEqual(layer.paint["line-width"], ["get", "markWidth"]);
  const avoidFeature = sectionFeatures(routeSections(LINE, [span(0, 300, 5)])).features[0];
  const avoidClass = routeClasses().find((c) => c.key === "5")!;
  assert.equal(avoidFeature.properties.markWidth, routeMarkWidth(avoidClass.width));
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const unpavedAt = mapView.indexOf("map.addLayer(routeUnpavedLayer(");
  const avoidAt = mapView.indexOf("map.addLayer(routeAvoidLayer(");
  assert.ok(unpavedAt > 0 && avoidAt > unpavedAt && avoidAt < mapView.indexOf('id: "route-line"'));
  // The legend's swatch draws it too: the same dash-dot, in SVG units of the mark's width (r4 mutation NIT 8).
  const w = avoidClass.width;
  assert.equal(routeMarkDash(w), ROUTE_AVOID_MARK_DASH.map((d) => d * routeMarkWidth(w)).join(" "));
  const dash = routeMarkDash(w).split(" ").map(Number);
  assert.equal(dash.length, 4);
  assert.ok(dash[0] > dash[2] && dash[1] === dash[3], `a dash, a gap, a dot, a gap: ${routeMarkDash(w)}`);
  const legend = readFileSync(new URL("../FacilityBreakdown.tsx", import.meta.url), "utf8");
  const markAt = legend.indexOf("{row.mark && (");
  assert.ok(markAt > 0, "the swatch draws the mark wherever the row has one");
  const swatch = legend.slice(markAt, legend.indexOf("</svg>", markAt));
  assert.match(swatch, /stroke=\{row\.mark\}/);
  assert.match(swatch, /strokeWidth=\{routeMarkWidth\(row\.width\)\}/);
  assert.match(swatch, /strokeDasharray=\{routeMarkDash\(row\.width\)\}/);
});

test("the legend's classes are traffic-free, the five tiers, the five unpaved browns, then not rated", () => {
  assert.deepEqual(
    routeClasses().map((c) => c.key),
    ["path", "1", "2", "3", "4", "5", "u1", "u2", "u3", "u4", "u5", "unknown"],
  );
  for (const c of routeClasses()) assert.ok(c.short && c.label && /^#[0-9a-f]{6}$/i.test(c.color), c.key);
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
  assert.equal(collection.features[1].properties.color, ROUTE_AVOID_MAGENTA, "Avoid on the route is magenta (397)");
  assert.equal(collection.features[0].properties.color, currentTiers()[0].color);
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
  assert.deepEqual(routePaint(true, false), { lineOpacity: 0, sectionOpacity: 1, haloOpacity: 1, casingColor: ROUTE_BLUE });
  assert.deepEqual(routePaint(false, false), { lineOpacity: 1, sectionOpacity: 0, haloOpacity: 0, casingColor: ROUTE_CASING_PLAIN });
  assert.deepEqual(routePaint(true, true), { lineOpacity: 0, sectionOpacity: 0.45, haloOpacity: 0.45, casingColor: ROUTE_BLUE });
  assert.equal(routePaint(false, true).lineOpacity, 0.45);
});
