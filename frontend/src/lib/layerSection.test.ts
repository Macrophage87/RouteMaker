// The Layers sheet's sections (lib/layerSection.ts; the owner, 2026-10-12: "a general off and on for each
// section, then let it expand"): one row, one switch for the section, a disclosure, the layers inside.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LAYER_SECTIONS_KEY, LayerSection, readSectionMemory, sectionPress, sectionState, someOnText, type SectionLayer } from "./layerSection.ts";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

const terrain = (mtb: boolean, climbs: boolean, topo: boolean): SectionLayer[] => [
  { key: "mtb", label: "Mountain-bike trails", on: mtb },
  { key: "climbs", label: "Climbs", on: climbs },
  { key: "topo", label: "Topo lines", on: topo },
];

test("the section's state: on, off, or some on", () => {
  assert.equal(sectionState(terrain(true, true, true)), "on");
  assert.equal(sectionState(terrain(false, false, false)), "off");
  assert.equal(sectionState(terrain(true, false, true)), "some");
  assert.equal(someOnText(terrain(true, false, true)), "Some on: Mountain-bike trails, Topo lines.");
});

test("Off hides every layer and remembers the ones on; On brings those back, else every layer", () => {
  const storage = memoryStorage();
  // Nothing remembered: On turns on the whole section.
  assert.deepEqual(sectionPress("terrain", terrain(false, false, false), storage), { mtb: true, climbs: true, topo: true });
  // Some on: the switch shows On, so a press is Off, and it remembers which.
  assert.deepEqual(sectionPress("terrain", terrain(true, false, true), storage), { mtb: false, climbs: false, topo: false });
  assert.deepEqual(JSON.parse(storage.data.get(LAYER_SECTIONS_KEY)!), { terrain: ["mtb", "topo"] });
  assert.deepEqual(sectionPress("terrain", terrain(false, false, false), storage), { mtb: true, climbs: false, topo: true });
  // Each section keeps its own.
  sectionPress("rail", [{ key: "metro", label: "Metro", on: true }, { key: "marc", label: "MARC", on: false }], storage);
  assert.deepEqual(readSectionMemory(storage), { terrain: ["mtb", "topo"], rail: ["metro"] });
});

test("a section of one layer: its switch is the layer's, nothing remembered", () => {
  const storage = memoryStorage();
  assert.deepEqual(sectionPress("water", [{ key: "water", label: "Water", on: true }], storage), { water: false });
  assert.deepEqual(sectionPress("water", [{ key: "water", label: "Water", on: false }], storage), { water: true });
  assert.equal(storage.data.get(LAYER_SECTIONS_KEY), undefined);
});

test("memory this page did not write is ignored, and a gone layer is not turned on", () => {
  for (const bad of ["garbage", "[1,2]", '{"terrain": [1]}', "null"]) {
    assert.deepEqual(readSectionMemory(memoryStorage({ [LAYER_SECTIONS_KEY]: bad })).terrain, undefined, bad);
  }
  const storage = memoryStorage({ [LAYER_SECTIONS_KEY]: JSON.stringify({ terrain: ["gone"] }) });
  assert.deepEqual(sectionPress("terrain", terrain(false, false, false), storage), { mtb: true, climbs: true, topo: true });
  // Storage that throws: the switch still works.
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.deepEqual(sectionPress("terrain", terrain(true, false, false), throwing), { mtb: false, climbs: false, topo: false });
});

test("the row: the heading names the switch; the disclosure is a named button with aria-expanded and aria-controls; closed to begin with", () => {
  const html = renderToStaticMarkup(
    createElement(LayerSection, { id: "terrain", title: "Trails and terrain", layers: terrain(true, false, false), onLayers: () => {}, status: "" }, createElement("p", null, "inside")),
  );
  assert.match(
    html,
    /^<section aria-labelledby="terrain-heading" class="layer-group layer-section"><div class="layer-section-row"><h3 id="terrain-heading">Trails and terrain<\/h3><button type="button" role="switch" id="terrain-section-switch" class="switch section-switch" aria-checked="true" aria-labelledby="terrain-heading" aria-describedby="terrain-section-some"><span class="switch-state" aria-hidden="true">Some on<\/span><\/button><button type="button" class="section-chevron" aria-expanded="false" aria-controls="terrain-section-body" aria-label="Trails and terrain layers">/,
  );
  // Keyboard order is the source order: section switch, disclosure, then the layers.
  assert.ok(html.indexOf("section-switch") < html.indexOf("section-chevron") && html.indexOf("section-chevron") < html.indexOf("inside"));
  assert.match(html, /<span id="terrain-section-some" class="visually-hidden">Some on: Mountain-bike trails\.<\/span>/);
  assert.match(html, /<p class="hint layer-section-status" role="status"><\/p>/);
  assert.match(html, /<div id="terrain-section-body" class="layer-section-body" hidden=""><p>inside<\/p><\/div>/);
  // All on or all off: the state in words, no description.
  const on = renderToStaticMarkup(createElement(LayerSection, { id: "rail", title: "Rail stations", layers: terrain(true, true, true), onLayers: () => {} }));
  assert.match(on, /aria-checked="true" aria-labelledby="rail-heading"><span class="switch-state" aria-hidden="true">On<\/span>/);
  assert.doesNotMatch(on, /aria-describedby|role="status"/);
  const off = renderToStaticMarkup(createElement(LayerSection, { id: "rail", title: "Rail stations", layers: terrain(false, false, false), onLayers: () => {} }));
  assert.match(off, /aria-checked="false" aria-labelledby="rail-heading"><span class="switch-state" aria-hidden="true">Off<\/span>/);
  // No layers to switch (the stress map unavailable): the name and the disclosure only.
  const none = renderToStaticMarkup(createElement(LayerSection, { id: "stress", title: "Traffic stress", layers: [], onLayers: () => {}, status: "Stress map unavailable for now." }));
  assert.doesNotMatch(none, /role="switch"/);
  assert.match(none, /role="status">Stress map unavailable for now\.<\/p>/);
});

test("the Layers sheet: every section is a LayerSection, and the old long paragraphs are by the legend now", async () => {
  const { readFileSync } = await import("node:fs");
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  const layers = sheets.slice(sheets.indexOf('id="sheet-layers"'), sheets.indexOf("export interface LegendSheetProps"));
  const legend = sheets.slice(sheets.indexOf('id="sheet-legend"'), sheets.indexOf("export interface GpxSheetProps"));
  for (const part of ["<FederalLegendNotes", "<WaterLegendNotes", "<RailStationsLegend", "CLIMBS_HELP"]) {
    assert.ok(legend.includes(part), part);
    assert.ok(!layers.includes(part), part);
  }
  assert.equal((layers.match(/<LayerSection\b/g) ?? []).length, 2, "Traffic stress and Trails and terrain here; federal, water and rail in their own files");
  for (const file of ["./federalLegend.ts", "./waterLegend.ts", "../RailStations.tsx"]) {
    assert.match(readFileSync(new URL(file, import.meta.url), "utf8"), /LayerSection/, file);
  }
});
