// What the legend says about zoom (owner, 2026-09-28: "Zoomed out just show the trails.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { CAR_FREE_NOTE, ROADWAY_LANES, StressZoomNotes, ZOOMED_OUT, stressZoomHint, stressZoomNotice } from "./stressLegend.ts";

test("zoomed out, with the overlay on, the notice says the road stress is a zoom away", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.roads - 0.01, true);
  assert.equal(out, "Zoom in to see traffic stress on roads. Zoomed out, only traffic-free paths and trails are shown.");
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min, true), out);
});

test("from the roads' zoom there is no notice; below the tiles' zoom it asks for a zoom in", () => {
  assert.equal(stressZoomNotice(STRESS_ZOOMS.roads, true), null);
  assert.equal(stressZoomNotice(16, true), null);
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min - 0.5, true), "Zoom in to see traffic-free paths, trails and traffic stress.");
});

test("with the overlay off, or before the map has a zoom, there is no notice", () => {
  assert.equal(stressZoomNotice(11, false), null);
  assert.equal(stressZoomNotice(null, true), null);
});

test("the standing hint names the zooms from STRESS_ZOOMS and the zoom the map is at", () => {
  const hint = stressZoomHint(12.7);
  assert.ok(hint.startsWith(`${ZOOMED_OUT} Trails beside a road are among them.`));
  assert.ok(hint.includes(`From zoom ${STRESS_ZOOMS.roads} traffic stress on roads and streets shows, protected lanes in the roadway with it`));
  assert.ok(hint.includes(`from zoom ${STRESS_ZOOMS.full} footways and sidewalks.`));
  assert.match(hint, new RegExp(`Further out than zoom ${STRESS_ZOOMS.min} nothing`));
  assert.match(hint, / The map is at zoom 12\.$/);
  assert.doesNotMatch(stressZoomHint(null), /The map is at/);
});

test("rendered: the notice as a status, then the hint", () => {
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11.2, shown: true }));
  assert.match(html, /^<p class="notice" role="status">Zoom in to see traffic stress on roads\./);
  assert.match(html, /<p class="hint">Zoomed out, only traffic-free paths and trails are shown\./);
  // The hint rendered is the one for the map's own zoom (round-1 mutant F08).
  assert.match(html, /The map is at zoom 11\.<\/p><p class="hint">Roads closed to cars/);
  const street = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.doesNotMatch(street, /notice/);
  assert.match(street, /<p class="hint">/);
});

test("App's legend passes the zoom and whether the overlay is on", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} \/>/);
  assert.match(app, /<StressZoomNotes zoom=\{zoom\} shown=\{shown\} \/>/);
});

test("one phrase for what the map shows zoomed out, wherever the legend says it", () => {
  assert.equal(ZOOMED_OUT, "Zoomed out, only traffic-free paths and trails are shown.");
  assert.ok(stressZoomNotice(11, true)!.endsWith(ZOOMED_OUT));
  assert.ok(stressZoomHint(11).startsWith(ZOOMED_OUT));
  assert.equal(ROADWAY_LANES, `Protected lanes in the roadway show from zoom ${STRESS_ZOOMS.roads}.`);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /Sharrows count as ordinary streets\. \{ROADWAY_LANES\}/);
  assert.doesNotMatch(app, /only the paths|only the trails/);
});

test("the legend says car-free roads are traffic-free paths, and the timed ones follow the ride time", () => {
  assert.ok(CAR_FREE_NOTE.startsWith("Roads closed to cars are shown as traffic-free paths"));
  assert.match(CAR_FREE_NOTE, /Sligo Creek Parkway on weekends/);
  assert.ok(CAR_FREE_NOTE.endsWith("when that ride time is chosen."));
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.ok(html.includes(CAR_FREE_NOTE));
});
