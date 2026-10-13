// The Trails and terrain section's switch counts only the layers that can show, and its closed row says
// why one the rider has on cannot (lib/terrainSection.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { LayerSection, sectionPress, sectionState } from "./layerSection.ts";
import { MTB_TRAILS_ROW_UNAVAILABLE, TOPO_LINES_ROW_UNAVAILABLE, stressShowable, terrainLayers, terrainStatus, type TerrainState } from "./terrainSection.ts";
import { CLIMBS_LOADING } from "./climbsLegend.ts";

const all: TerrainState = { mtb: false, climbs: false, topo: false, stressAvailable: true, topoReady: true, climbsStatus: "ready" };
const keys = (state: TerrainState) => terrainLayers(state).map((layer) => layer.key);

test("every layer counts while each can show", () => {
  assert.deepEqual(keys(all), ["mtb", "climbs", "topo"]);
});

test("topo with no archive, and the trails without the stress map, are left out of the section switch", () => {
  assert.deepEqual(keys({ ...all, topoReady: false }), ["mtb", "climbs"]);
  assert.deepEqual(keys({ ...all, stressAvailable: false }), ["climbs", "topo"]);
  assert.deepEqual(keys({ ...all, stressAvailable: false, topoReady: false }), ["climbs"]);
});

test("so the row never reads On or Some on with nothing drawn", () => {
  // Topo stored on but unavailable, climbs off: the section is off, not "Some on".
  const topoOnly = { ...all, topo: true, topoReady: false };
  assert.equal(sectionState(terrainLayers(topoOnly)), "off");
  const html = renderToStaticMarkup(createElement(LayerSection, { id: "terrain", title: "Trails and terrain", layers: terrainLayers(topoOnly), onLayers: () => {} }));
  assert.match(html, /aria-checked="false"[^>]*><span class="switch-state" aria-hidden="true">Off</);
  // Trails on without the stress map, climbs on, no topo archive: On (climbs), not Some on.
  assert.equal(sectionState(terrainLayers({ ...all, mtb: true, climbs: true, stressAvailable: false, topoReady: false })), "on");
  // A press turns on only what can show, and never names a layer left out.
  const pressed = sectionPress("terrain-test", terrainLayers({ ...all, stressAvailable: false, topoReady: false }), null);
  assert.deepEqual(pressed, { climbs: true });
});

test("closed, the row carries the climbs status and the unavailable layers the rider has on; open, nothing", () => {
  assert.equal(terrainStatus(false, all), "");
  assert.equal(terrainStatus(false, { ...all, topoReady: false, stressAvailable: false }), "", "said only for a layer that is on");
  assert.equal(terrainStatus(false, { ...all, topo: true, topoReady: false }), TOPO_LINES_ROW_UNAVAILABLE);
  assert.equal(terrainStatus(false, { ...all, mtb: true, stressAvailable: false }), MTB_TRAILS_ROW_UNAVAILABLE);
  assert.equal(
    terrainStatus(false, { ...all, climbs: true, climbsStatus: "loading", mtb: true, stressAvailable: false, topo: true, topoReady: false }),
    `${CLIMBS_LOADING} ${MTB_TRAILS_ROW_UNAVAILABLE} ${TOPO_LINES_ROW_UNAVAILABLE}`,
  );
  assert.equal(terrainStatus(true, { ...all, topo: true, topoReady: false, climbs: true, climbsStatus: "loading" }), "", "open: each layer's own line says it");
});

test("while the stress map is still being checked (page load), the trails stay in the switch and nothing says unavailable", () => {
  assert.equal(stressShowable("checking"), true);
  assert.equal(stressShowable("available"), true);
  assert.equal(stressShowable("unavailable"), false);
  const checking = { ...all, mtb: true, stressAvailable: stressShowable("checking") };
  assert.deepEqual(keys(checking), ["mtb", "climbs", "topo"]);
  assert.equal(sectionState(terrainLayers({ ...checking, climbs: true, topoReady: false })), "on", "the trails and climbs on: On, not Some on");
  assert.equal(terrainStatus(false, checking), "", "no spurious unavailable line");
  // Once known down, it is said.
  assert.equal(terrainStatus(false, { ...checking, stressAvailable: stressShowable("unavailable") }), MTB_TRAILS_ROW_UNAVAILABLE);
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /stressAvailable: stressShowable\(stress\)/);
});
