// What the legend says about zoom (owner, 2026-09-28: "Zoomed out just show the trails.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { STRESS_ZOOMS } from "./mapStyle.ts";
import { StressZoomNotes, stressZoomHint, stressZoomNotice } from "./stressLegend.ts";

test("zoomed out, with the overlay on, the notice says the road stress is a zoom away", () => {
  const out = stressZoomNotice(STRESS_ZOOMS.roads - 0.01, true);
  assert.equal(out, "Zoom in to see traffic stress on roads. Zoomed out, only the trails are shown.");
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min, true), out);
});

test("from the roads' zoom there is no notice; below the tiles' zoom it asks for a zoom in", () => {
  assert.equal(stressZoomNotice(STRESS_ZOOMS.roads, true), null);
  assert.equal(stressZoomNotice(16, true), null);
  assert.equal(stressZoomNotice(STRESS_ZOOMS.min - 0.5, true), "Zoom in to see the trails and traffic stress.");
});

test("with the overlay off, or before the map has a zoom, there is no notice", () => {
  assert.equal(stressZoomNotice(11, false), null);
  assert.equal(stressZoomNotice(null, true), null);
});

test("the standing hint names the zooms from STRESS_ZOOMS and the zoom the map is at", () => {
  const hint = stressZoomHint(12.7);
  assert.match(hint, /^Zoomed out, only the traffic-free trails and paths are drawn\./);
  assert.match(hint, new RegExp(`roads and streets shows from zoom ${STRESS_ZOOMS.roads},`));
  assert.match(hint, new RegExp(`sidewalks from zoom ${STRESS_ZOOMS.full}\\.`));
  assert.match(hint, new RegExp(`Further out than zoom ${STRESS_ZOOMS.min} nothing`));
  assert.match(hint, / The map is at zoom 12\.$/);
  assert.doesNotMatch(stressZoomHint(null), /The map is at/);
});

test("rendered: the notice as a status, then the hint", () => {
  const html = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 11.2, shown: true }));
  assert.match(html, /^<p class="notice" role="status">Zoom in to see traffic stress on roads\./);
  assert.match(html, /<p class="hint">Zoomed out, only the traffic-free trails/);
  const street = renderToStaticMarkup(createElement(StressZoomNotes, { zoom: 14, shown: true }));
  assert.doesNotMatch(street, /notice/);
  assert.match(street, /<p class="hint">/);
});

test("App's legend passes the zoom and whether the overlay is on", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /<StressLegend facilities=\{facilitiesShown\} zoom=\{zoom\} shown=\{stressVisible\} \/>/);
  assert.match(app, /<StressZoomNotes zoom=\{zoom\} shown=\{shown\} \/>/);
});
