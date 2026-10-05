// What a Mass Ride says about riders per minute (OWNER-DECISIONS 325-327, 387): the route's
// narrowest point and band shares, the legend, the route line's classes and the description.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { StressSpan } from "./api.ts";
import {
  AVOID_LEGEND_TEXT,
  CAPACITY_FIGURE_TITLE,
  CAPACITY_LEGEND_TITLE,
  bandLegendText,
  bandName,
  capacityDescription,
  capacityRows,
  capacitySummary,
  isMassRide,
  massZoomNotice,
  narrowestText,
  ridersPerMinute,
} from "./massCapacity.ts";
import { CapacityFigures, CapacityStats, MassLegend, MassZoomNotes } from "./massLegend.ts";
import { capacityLead, descriptionText } from "./routeDescription.ts";
import { routeLegend, routeSections, sectionFeatures, spanClass, usesCapacity } from "./routeColours.ts";
import { MASS_BANDS } from "../massStyle.js";
import { dashedRouteKeys, routeDashLayers, solidRouteFilter } from "./mapGlue.ts";

const M = 1609.344;

/** A route of three miles: a pinch, a good road, a wide road, a stretch marked Avoid, and a section with no figure. */
const SPANS: StressSpan[] = [
  { from_m: 0, to_m: 300, tier: 2, facility: "none", rpm: 50 },
  { from_m: 300, to_m: 1500, tier: 3, facility: "none", rpm: 90 },
  { from_m: 1500, to_m: 2700, tier: 3, facility: "none", rpm: 190 },
  { from_m: 2700, to_m: 3400, tier: 4, facility: "none", rpm: 590 },
  { from_m: 3400, to_m: 3600, tier: 5, facility: "none", rpm: null },
  { from_m: 3600, to_m: 4000, tier: null, facility: null, rpm: null },
];

test("a Mass Ride is the ride type whose map this is", () => {
  assert.equal(isMassRide("mass-ride"), true);
  for (const other of ["default", "calm", "fast", null, undefined]) assert.equal(isMassRide(other as never), false);
});

test("the narrowest point is the route's lowest figure, with where its section starts", () => {
  const summary = capacitySummary(SPANS);
  assert.ok(summary);
  assert.equal(summary.minRpm, 50);
  assert.equal(summary.minAtM, 0);
  assert.equal(summary.totalM, 4000);
  assert.equal(narrowestText(summary), "50 riders per minute (bottleneck), at the start");
  const later = capacitySummary([
    { from_m: 0, to_m: 1000, tier: 2, facility: "none", rpm: 200 },
    { from_m: 1000, to_m: 1500, tier: 2, facility: "none", rpm: 55 },
  ]);
  assert.equal(narrowestText(later!), `55 riders per minute (bottleneck), at ${(1000 / M).toFixed(1)} mi (1.0 km) along`);
});

test("each band's share of the distance, Avoid and no-figure apart; the whole percents add up to 100", () => {
  const summary = capacitySummary(SPANS)!;
  assert.deepEqual(summary.bandM, [300, 1200, 1200, 700]);
  assert.equal(summary.avoidM, 200);
  assert.equal(summary.unknownM, 400);
  assert.equal(summary.percents.reduce((a, b) => a + b, 0), 100);
  assert.deepEqual(summary.percents, [8, 30, 30, 17, 5, 10]);
  const rows = capacityRows(summary);
  assert.deepEqual(
    rows.map((r) => r.text),
    ["Under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open", "Avoid: no capacity given", "No capacity figure"],
  );
});

test("Avoid shows only Avoid: it is never counted in a band, and never the narrowest point", () => {
  const summary = capacitySummary([
    { from_m: 0, to_m: 500, tier: 5, facility: "none", rpm: 30 },
    { from_m: 500, to_m: 1500, tier: 2, facility: "none", rpm: 100 },
  ])!;
  assert.equal(summary.minRpm, 100);
  assert.deepEqual(summary.bandM, [0, 1000, 0, 0]);
  assert.equal(summary.avoidM, 500);
});

test("the typical capacity is the distance-weighted median", () => {
  // 300 m at 50, 1,200 at 90, 1,200 at 190 and 700 at 590: half of the 3,400 m is passed in the third.
  assert.equal(capacitySummary(SPANS)!.typicalRpm, 190);
});

test("a route with no figures (another ride type, an older API, a table without the column) has no summary", () => {
  assert.equal(capacitySummary(undefined), null);
  assert.equal(capacitySummary([]), null);
  assert.equal(capacitySummary([{ from_m: 0, to_m: 100, tier: 2, facility: "none" }]), null);
  assert.equal(capacitySummary([{ from_m: 0, to_m: 100, tier: 2, facility: "none", rpm: null }]), null);
});

test("figures read in words: unit spelled out, one rider singular, the band named", () => {
  assert.equal(ridersPerMinute(1), "1 rider per minute");
  assert.equal(ridersPerMinute(185), "185 riders per minute");
  assert.deepEqual([bandName(10), bandName(60), bandName(150), bandName(200), bandName(null)], ["bottleneck", "tight", "good", "wide open", ""]);
  assert.equal(bandLegendText(3), "200 and up: wide open");
});

test("the description's lead says the narrowest point and every share, in words", () => {
  const lead = capacityLead({ stress_spans: SPANS });
  assert.ok(lead);
  assert.match(lead, /^Carrying capacity: narrowest point 50 riders per minute \(bottleneck\), at the start\./);
  for (const part of ["under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open", "avoid"]) {
    assert.ok(lead.toLowerCase().includes(part), part);
  }
  assert.equal(lead, capacityDescription(capacitySummary(SPANS)!));
  assert.equal(capacityLead({ stress_spans: [{ from_m: 0, to_m: 10, tier: 1, facility: "none" }] }), null, "no lead on another ride type");
  const text = descriptionText({
    preset: "mass-ride",
    distance_m: 4000,
    description: [{ kind: "stretch", text: "Ride east." }] as never,
    stress_spans: SPANS,
  });
  assert.equal(text.split("\n")[1], lead, "the lead follows the head, before the numbered steps");
});

test("US units first: the speed the figure is for is miles an hour, with kilometres in brackets", () => {
  assert.equal(CAPACITY_LEGEND_TITLE, "Riders per minute at 6-8 mph (10-13 km/h)");
});

// --- The legend and the panel -------------------------------------------------------------

test("the legend lists the four bands in order, then Avoid, each with its words", () => {
  const html = renderToStaticMarkup(createElement(MassLegend));
  const at = ["Under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open", AVOID_LEGEND_TEXT].map((t) => html.indexOf(t));
  assert.ok(at.every((i) => i > 0), JSON.stringify(at));
  assert.deepEqual(at, [...at].sort((a, b) => a - b));
  assert.ok(html.includes(`aria-label="${CAPACITY_LEGEND_TITLE}"`), "the list is named for a screen reader");
  // Every swatch is a hidden picture; the words carry the meaning.
  assert.equal((html.match(/<svg[^>]*aria-hidden="true"/g) ?? []).length, 5);
  // The bands' own stroke widths, and the dashes of the two lower ones.
  for (const band of MASS_BANDS) assert.ok(html.includes(`stroke="${band.color}"`), band.key);
  assert.ok(html.includes('stroke-dasharray="6 4"') && html.includes('stroke-dasharray="14 4"'));
  assert.ok(!/LTS|stress/i.test(html.replace(/<[^>]*>/g, "")), "no LTS or stress words in the Mass Ride legend");
});

test("the route's list says each band's share and length in words, one row each, empty bands left out", () => {
  const html = renderToStaticMarkup(createElement(CapacityFigures, { route: { stress_spans: SPANS } }));
  assert.ok(html.includes(CAPACITY_FIGURE_TITLE));
  for (const text of ["Under 60: bottleneck", "60 to 120: tight", "200 and up: wide open", "No capacity figure"]) assert.ok(html.includes(text), text);
  assert.ok(html.includes("8%") && html.includes("30%"));
  assert.equal(renderToStaticMarkup(createElement(CapacityFigures, { route: { stress_spans: [{ from_m: 0, to_m: 9, tier: 1, facility: "none" }] } })), "");
  const one = renderToStaticMarkup(createElement(CapacityFigures, { route: { stress_spans: [{ from_m: 0, to_m: 1000, tier: 2, facility: "none", rpm: 100 }] } }));
  assert.ok(!one.includes("Under 60"), "a band the route never enters is not listed");
});

test("the route view's figures: the narrowest point and the typical, each a term with its description", () => {
  const html = renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: SPANS } }));
  assert.match(html, /<dt>Narrowest point<\/dt><dd>50 riders per minute \(bottleneck\), at the start<\/dd>/);
  assert.match(html, /<dt>Typical<\/dt><dd>190 riders per minute<\/dd>/);
  assert.equal(renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: [] } })), "");
});

test("the zoom note says where roads come in, and what this map leaves out", () => {
  assert.equal(massZoomNotice(null, true), null);
  assert.equal(massZoomNotice(11, false), null);
  assert.match(massZoomNotice(11, true)!, /Zoom in to see roads/);
  assert.match(massZoomNotice(13, true)!, /until zoom 14/);
  assert.equal(massZoomNotice(14, true), null);
  const html = renderToStaticMarkup(createElement(MassZoomNotes, { zoom: 11, shown: true }));
  assert.match(html, /Trails, paths and bike lanes are not drawn/);
});

// --- The route line -----------------------------------------------------------------------

test("the route line is drawn by capacity when its sections carry figures, and by stress when they do not", () => {
  assert.equal(usesCapacity(SPANS), true);
  assert.equal(usesCapacity([{ from_m: 0, to_m: 10, tier: 2, facility: "none" }]), false);
  assert.equal(usesCapacity([{ from_m: 0, to_m: 10, tier: 2, facility: "none", rpm: null }]), false, "an older table: no figure anywhere");
  assert.equal(spanClass({ tier: 2, facility: "none", rpm: 50 }, true).key, "m0");
  assert.equal(spanClass({ tier: 2, facility: "none", rpm: 90 }, true).key, "m1");
  assert.equal(spanClass({ tier: 3, facility: "none", rpm: 150 }, true).key, "m2");
  assert.equal(spanClass({ tier: 4, facility: "none", rpm: 400 }, true).key, "m3");
  assert.equal(spanClass({ tier: 5, facility: "none", rpm: 400 }, true).key, "mavoid", "Avoid shows only Avoid");
  assert.equal(spanClass({ tier: 2, facility: "none", rpm: null }, true).key, "unknown", "no figure: the unrated grey, not an LTS colour");
  // Without the flag, as before.
  assert.equal(spanClass({ tier: 2, facility: "none", rpm: 400 }).key, "2");
  assert.equal(spanClass({ tier: 5, facility: "none" }).key, "5");
});

test("each capacity band's route section has its band's colour, width and dash, and a halo of its own", () => {
  const coordinates: Array<[number, number]> = [[-77.04, 38.9], [-77.03, 38.9], [-77.02, 38.9], [-77.01, 38.9], [-77.0, 38.9]];
  const spans: StressSpan[] = [
    { from_m: 0, to_m: 200, tier: 2, facility: "none", rpm: 50 },
    { from_m: 200, to_m: 400, tier: 2, facility: "none", rpm: 100 },
    { from_m: 400, to_m: 600, tier: 2, facility: "none", rpm: 150 },
    { from_m: 600, to_m: 800, tier: 2, facility: "none", rpm: 300 },
  ];
  const sections = routeSections(coordinates, spans)!;
  assert.deepEqual(sections.map((s) => s.key), ["m0", "m1", "m2", "m3"]);
  assert.deepEqual(sections.map((s) => s.color), MASS_BANDS.map((b: (typeof MASS_BANDS)[number]) => b.color));
  assert.deepEqual(sections.map((s) => s.width), [4, 5.5, 7, 8.5]);
  assert.deepEqual(sections.map((s) => Boolean(s.dash)), [true, true, false, false]);
  const features = sectionFeatures(sections).features;
  assert.equal(features.length, 4);
  // The dashed classes cannot share the solid layer: it excludes them, each has its own.
  assert.deepEqual(dashedRouteKeys(), ["m0", "m1", "mavoid"]);
  assert.deepEqual(routeDashLayers().map((l) => l.id), ["route-dash-m0", "route-dash-m1", "route-dash-mavoid"]);
  assert.deepEqual(solidRouteFilter(), ["!", ["in", ["get", "key"], ["literal", ["m0", "m1", "mavoid"]]]]);
  for (const layer of routeDashLayers()) {
    assert.ok(Array.isArray(layer.paint["line-dasharray"]) && layer.paint["line-dasharray"].length % 2 === 0, layer.id);
    assert.equal(layer.paint["line-opacity"], 0, "drawn only once setRouteSections shows it");
  }
  // The route's colour legend counts them.
  assert.deepEqual(routeLegend(spans).map((row) => row.key), ["m0", "m1", "m2", "m3"]);
});

test("a Mass Ride's adjacent sections of one band are one section", () => {
  const coordinates: Array<[number, number]> = [[-77.04, 38.9], [-77.02, 38.9], [-77.0, 38.9]];
  const sections = routeSections(coordinates, [
    { from_m: 0, to_m: 100, tier: 2, facility: "none", rpm: 130 },
    { from_m: 100, to_m: 300, tier: 3, facility: "none", rpm: 190 },
  ])!;
  assert.deepEqual(sections.map((s) => s.key), ["m2"]);
});
