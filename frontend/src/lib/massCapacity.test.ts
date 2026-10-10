// What a Mass Ride says about riders per minute (OWNER-DECISIONS 325-327, 387): the route's
// narrowest point and band shares, the legend, the route line's classes and the description.
import { readFileSync } from "node:fs";
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
  massBandsChangeSaid,
  massBandsSaid,
  massZoomNotice,
  capacityPair,
  narrowestLines,
  narrowestText,
  ridersPerMinute,
  typicalLines,
} from "./massCapacity.ts";
import { CapacityFigures, CapacityStats, MassLegend, MassZoomNotes } from "./massLegend.ts";
import { capacityLead, descriptionText } from "./routeDescription.ts";
import { ROUTE_AVOID_HALO, ROUTE_AVOID_MAGENTA, ROUTE_AVOID_MARK, routeLegend, routeSections, sectionFeatures, spanClass, usesCapacity } from "./routeColours.ts";
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
  assert.deepEqual(summary.percents, [8, 30, 30, 17, 5, 10, 0]);
  const rows = capacityRows(summary);
  assert.deepEqual(
    rows.map((r) => r.text),
    ["Under 60: bottleneck", "60 to 120: tight", "120 to 200: good", "200 and up: wide open", "Marked Avoid: no capacity given", "No capacity figure"],
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
  assert.match(lead, /^Carrying capacity: narrowest on the flat: 50 riders per minute \(bottleneck\), at the start\./);
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
  assert.equal(CAPACITY_LEGEND_TITLE, "Riders per minute at 6 to 8 mph (10 to 13 km/h)");
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
  // Both width sources are credited (OWNER-DECISIONS 404; docs/SOURCES.md's credit lines), and the
  // working model is never called calibrated (394).
  assert.ok(html.includes("OpenStreetMap contributors"), "OSM is credited");
  assert.ok(
    html.includes("DC Open Data, Roadway Block (CC BY 4.0, adapted)") && html.includes("© OpenStreetMap contributors"),
    "the District's Roadway Block is credited",
  );
  assert.ok(!/calibrat/i.test(html), "the model is not called calibrated");
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
  assert.match(html, /<dt>Narrowest on the flat<\/dt><dd>50 riders per minute \(bottleneck\), at the start<\/dd>/);
  assert.match(html, /<dt>Typical on the flat<\/dt><dd>190 riders per minute<\/dd>/);
  assert.equal(renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: [] } })), "");
});

// OWNER-DECISIONS 424: "Show both." The narrowest on the flat (the sections, width only) and with the hills
// (the profile, width and grade), labelled the same way in the card, the directions, the chart and the fold.
const hills = (rpm: number, m: number, typical: number | null = 120) => ({
  narrowest_riders_per_min: rpm,
  narrowest_m: m,
  typical_riders_per_min: typical,
});

test("424: two places, two figures, each labelled, in the card, the directions and the fold", () => {
  const route = { stress_spans: SPANS, profile: { flow: hills(35, 2000) } as never };
  const pair = capacityPair(capacitySummary(SPANS), hills(35, 2000));
  assert.equal(pair.samePlace, false);
  assert.deepEqual(narrowestLines(pair), [
    { key: "narrowest-flat", label: "narrowest on the flat", text: "50 riders per minute (bottleneck), at the start" },
    { key: "narrowest-hills", label: "narrowest with the hills", text: `35 riders per minute (bottleneck), at ${(2000 / M).toFixed(1)} mi (2.0 km) along` },
  ]);
  const card = renderToStaticMarkup(createElement(CapacityStats, { route }));
  assert.match(card, /<dt>Narrowest on the flat<\/dt><dd>50 riders per minute \(bottleneck\), at the start<\/dd>/);
  assert.match(card, /<dt>Narrowest with the hills<\/dt><dd>35 riders per minute \(bottleneck\), at 1\.2 mi \(2\.0 km\) along<\/dd>/);
  assert.match(card, /<dt>Typical on the flat<\/dt><dd>190 riders per minute<\/dd>.*<dt>Typical with the hills<\/dt><dd>120 riders per minute<\/dd>/);
  const lead = capacityLead(route)!;
  assert.match(lead, /^Carrying capacity: narrowest on the flat: 50 riders per minute \(bottleneck\), at the start; narrowest with the hills: 35 riders per minute \(bottleneck\), at 1\.2 mi \(2\.0 km\) along\. By distance: /);
  const fold = renderToStaticMarkup(createElement(CapacityFigures, { route }));
  assert.ok(fold.includes("Narrowest on the flat: 50 riders per minute (bottleneck), at the start; narrowest with the hills: 35 riders per minute"), fold);
});

test("424: the same spot is said once, with both figures where the hills lower it, and one figure where they agree", () => {
  const lowered = capacityPair(capacitySummary(SPANS), hills(40, 150));
  assert.equal(lowered.samePlace, true);
  assert.deepEqual(narrowestLines(lowered), [
    { key: "narrowest", label: "narrowest on the flat and with the hills", text: "50 riders per minute (bottleneck) on the flat, 40 riders per minute (bottleneck) with the hills, at the start" },
  ]);
  const agree = capacityPair(capacitySummary(SPANS), hills(50, 0, 190));
  assert.deepEqual(narrowestLines(agree), [{ key: "narrowest", label: "narrowest on the flat and with the hills", text: "50 riders per minute (bottleneck), at the start" }]);
  assert.deepEqual(typicalLines(agree), [{ key: "typical", label: "typical on the flat and with the hills", text: "190 riders per minute" }]);
  const card = renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: SPANS, profile: { flow: hills(50, 0, 190) } as never } }));
  assert.equal((card.match(/<dt>/g) ?? []).length, 2, "one narrowest and one typical, each said once");
  // No profile (or no flow): the flat figures alone, still labelled as on the flat.
  assert.deepEqual(narrowestLines(capacityPair(capacitySummary(SPANS), null)).map((l) => l.label), ["narrowest on the flat"]);
});

test("the route list's Avoid and no-figure rows have the route line's own swatches", () => {
  const html = renderToStaticMarkup(createElement(CapacityFigures, { route: { stress_spans: SPANS } }));
  const avoidRow = html.split("<li>").find((li) => li.includes("Marked Avoid"))!;
  assert.ok(avoidRow.includes(ROUTE_AVOID_MAGENTA) && avoidRow.includes('class="route-avoid-mark"') && avoidRow.includes(ROUTE_AVOID_MARK), avoidRow);
  const noneRow = html.split("<li>").find((li) => li.includes("No capacity figure"))!;
  assert.ok(noneRow.includes("route-swatch") && !noneRow.includes('class="swatch"'), noneRow);
});

test("the zoom note says where roads come in, and what this map leaves out", () => {
  // The Mass Ride tiles draw roads from z10, busy ones too (OWNER-DECISIONS 415), by band (421, 422).
  assert.equal(massZoomNotice(null, true), null);
  assert.equal(massZoomNotice(9, false), null);
  assert.match(massZoomNotice(9, true)!, /Zoom in to see roads/);
  for (const z of [10, 11, 12, 13, 14, 16]) assert.equal(massZoomNotice(z, true), null, `z${z}`);
  const html = renderToStaticMarkup(createElement(MassZoomNotes, { zoom: 11, shown: true }));
  assert.match(html, /Roads in DC show their riders per minute from zoom 10, busy roads included: at zoom 10 and 11 only wide open roads that run 0\.5 mi \(0\.8 km\) or more, at zoom 12 and 13 good roads too, and every road from zoom 14\./);
  assert.match(html, /Stretches marked Avoid show at every zoom\./);
  assert.match(html, /Trails, paths, protected bike lanes and bike lanes are not drawn on this map at any zoom/);
  assert.doesNotMatch(html, /long calm roads/);
});

test("the legend says in words which bands show at the zoom the map is at (421, 422)", () => {
  const wide =
    "At this zoom the map shows only wide open roads (200 and up riders per minute), and only where they run for 0.5 mi (0.8 km) or more. " +
    "Zoom in for good roads from zoom 12, and tight and bottleneck roads from zoom 14.";
  const good = "At this zoom the map shows wide open and good roads (120 and up riders per minute). Zoom in for tight and bottleneck roads from zoom 14.";
  const every = "At this zoom the map shows every road: wide open, good, tight and bottleneck.";
  assert.equal(massBandsSaid(10), wide);
  assert.equal(massBandsSaid(11.9), wide, "a map at 11.9 draws z11's tiles");
  assert.equal(massBandsSaid(12), good);
  assert.equal(massBandsSaid(13.5), good);
  assert.equal(massBandsSaid(14), every);
  assert.equal(massBandsSaid(17), every);
  assert.match(massBandsSaid(9.5)!, /^Zoom in to see roads/);
  assert.equal(massBandsSaid(null), null);
  assert.equal(massBandsSaid(12, false), null, "the colours switched off: nothing to say");
  // In the legend: one persistent status line, there with no words too.
  const at = (zoom: number | null, shown = true) => renderToStaticMarkup(createElement(MassZoomNotes, { zoom, shown }));
  assert.match(at(10), /<p class="notice mass-bands" role="status">At this zoom the map shows only wide open roads/);
  assert.match(at(12), /role="status">At this zoom the map shows wide open and good roads/);
  assert.match(at(14), /role="status">At this zoom the map shows every road/);
  assert.match(at(12, false), /<p class="notice notice-empty mass-bands" role="status"><\/p>/);
});

test("the words change only when the set of bands does, so zooming within a level says nothing", () => {
  const words = [10, 10.4, 11, 11.99].map((z) => massBandsSaid(z));
  assert.equal(new Set(words).size, 1);
  assert.equal(new Set([12, 12.5, 13.9].map((z) => massBandsSaid(z))).size, 1);
  assert.equal(new Set([14, 15, 16.2].map((z) => massBandsSaid(z))).size, 1);
});

test("the app-level region says a change of bands only while the legend is off screen, and not on arriving", () => {
  const z11 = massBandsSaid(11);
  const z12 = massBandsSaid(12);
  assert.equal(massBandsChangeSaid(z11, z12, false), z12);
  assert.equal(massBandsChangeSaid(z11, z12, true), null, "the legend's own status line says it");
  assert.equal(massBandsChangeSaid(z12, z12, false), null, "the same bands: nothing");
  assert.equal(massBandsChangeSaid(null, z12, false), null, "coming to the Mass Ride map, or switching the colours on");
  assert.equal(massBandsChangeSaid(z12, null, false), null);
  // App.tsx wires it so.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const massBands = massMap && stressVisible \? massBandsSaid\(zoom\) : null;/);
  assert.match(app, /massBandsChangeSaid\(massBandsBefore\.current, massBands, layersShownNow\.current\)/);
  assert.match(app, /layersShownNow\.current = view === "layers" && panelOpen;/);
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
  // The route's own Avoid is the one magenta with its white dash-dot on a Mass Ride too (OWNER-DECISIONS 397).
  const avoid = spanClass({ tier: 5, facility: "none", rpm: 400 }, true);
  assert.deepEqual([avoid.color, avoid.halo, avoid.mark, avoid.dash], [ROUTE_AVOID_MAGENTA, ROUTE_AVOID_HALO, ROUTE_AVOID_MARK, undefined]);
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
  // The dashed classes cannot share the solid layer: it excludes them, each has its own. A Mass Ride's
  // Avoid is the route's one magenta with its white dash-dot (OWNER-DECISIONS 397), drawn by the solid
  // layer and the route-avoid mark, so it has no dash layer.
  assert.deepEqual(dashedRouteKeys(), ["m0", "m1"]);
  assert.deepEqual(routeDashLayers().map((l) => l.id), ["route-dash-m0", "route-dash-m1"]);
  assert.deepEqual(solidRouteFilter(), ["!", ["in", ["get", "key"], ["literal", ["m0", "m1"]]]]);
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

// --- Where App and MapView wire it ---------------------------------------------------------

test("the app wires the mode: the map's capacity layers, the legend and the panel follow the tiles, the grey outside DC the ride type", async () => {
  const { readFileSync } = await import("node:fs");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  // Accessibility review S2: the layers switch on the capacity seen, so a table without the column keeps the
  // stress layers its legend describes; the DC mask follows the ride type.
  assert.match(app, /massCapacity=\{massMap\}/);
  assert.match(app, /massArea=\{isMassRide\(preset\)\}/);
  assert.match(app, /watchForCapacity\(map, \(\) => setCapacityTiles\(true\)\)/);
  assert.match(app, /const massMap = isMassRide\(preset\) && capacityTiles;/);
  assert.match(app, /massMap \? \(\s*<>\s*<MassLegend \/>\s*<MassZoomNotes[^>]*\/>\s*\{\/\*[^*]*\*\/\}\s*<MtbTrailLegend \/>\s*<\/>\s*\) : \(\s*<>\s*<StressLegend/);
  // The panel's figures are the route's own: they need the sections' capacity, so an older table keeps the stress breakdown.
  assert.match(app, /const capacity = capacitySummary\(route\.stress_spans\);/);
  assert.match(app, /const segments = capacity \? \[\] : stressSegments\(route\.stress_m\);/);
  assert.match(view, /setMassMode\(null, callbacks\.current\.massCapacity === true/);
  assert.match(view, /props\.massCapacity === true/);
  assert.match(view, /addDcMask\(map, callbacks\.current\.massArea === true/);
});

test("427: the parts of a Mass Ride outside DC carry no figure, keep their stress colour, and are said in words", async () => {
  const { OUTSIDE_DC_FIGURES, OUTSIDE_DC_ROW } = await import("./massCapacity.ts");
  const spans: StressSpan[] = [
    { from_m: 0, to_m: 500, tier: 3, facility: "none", rpm: null, outside_dc: true },
    { from_m: 500, to_m: 1500, tier: 2, facility: "none", rpm: 90 },
    { from_m: 1500, to_m: 2500, tier: 2, facility: "none", rpm: 190 },
  ];
  const summary = capacitySummary(spans)!;
  assert.equal(summary.outsideM, 500);
  assert.equal(summary.unknownM, 0, "not counted as a stretch with no figure");
  assert.equal(summary.minRpm, 90, "the narrowest is DC's");
  assert.equal(summary.percents.reduce((a, b) => a + b, 0), 100);
  assert.ok(capacityRows(summary).some((r) => r.key === "outside" && r.text === OUTSIDE_DC_ROW && r.percent === 20));
  // Not greyed: the route line keeps the section's traffic-stress colour.
  assert.equal(spanClass(spans[0], true).key, "3");
  assert.equal(spanClass({ ...spans[0], outside_dc: false }, true).key, "unknown");
  const card = renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: spans } }));
  const fold = renderToStaticMarkup(createElement(CapacityFigures, { route: { stress_spans: spans } }));
  for (const html of [card, fold]) assert.ok(html.includes(OUTSIDE_DC_FIGURES.replace(/'/g, "&#x27;")), html);
  assert.ok(!renderToStaticMarkup(createElement(CapacityStats, { route: { stress_spans: SPANS } })).includes("outside DC"));
  // The directions keep "DC" and "Avoid" capitalised (a screen reader says "DC" as letters).
  const lead = capacityLead({ stress_spans: spans })!;
  assert.ok(lead.includes("20% Outside DC: no figures yet"), lead);
  assert.ok(!lead.includes("outside dc"), lead);
  const withAvoid = capacityLead({ stress_spans: SPANS })!;
  assert.ok(withAvoid.includes("Marked Avoid: no capacity given") && withAvoid.includes("no capacity figure"), withAvoid);
});
