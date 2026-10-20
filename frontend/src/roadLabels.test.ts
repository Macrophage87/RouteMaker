// The street names (stressStyle.js, ROAD_LABEL; the owner, 2026-10-20: the names "seem to disappear over the
// colored lanes"): the base map's road-name layers, as this app ships them, read clearly over the stress lines.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { ROAD_LABEL, ROAD_LABEL_LAYER_IDS, contrastRatio, rideRoadLabelField, roadLabelPaint, withClearRoadLabels } from "./stressStyle.js";
import { setStressPalette } from "./lib/mapGlue.ts";

type Layer = { id: string; type: string; layout?: Record<string, unknown>; paint?: Record<string, unknown> };
const shipped = (strong: boolean) => withClearRoadLabels(protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }), strong) as Layer[];

test("road names: both base map name layers are restyled, and only they", () => {
  const before = protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Layer[];
  const after = shipped(false);
  assert.equal(after.length, before.length);
  for (const id of ROAD_LABEL_LAYER_IDS) assert.ok(before.some((l) => l.id === id), `${id} is in the base map`);
  after.forEach((layer, i) => {
    if (ROAD_LABEL_LAYER_IDS.includes(layer.id)) {
      assert.deepEqual(layer.layout?.["text-font"], [ROAD_LABEL.font]);
      assert.equal(layer.layout?.["text-size"], ROAD_LABEL.size);
      assert.ok(ROAD_LABEL.size > (before[i].layout?.["text-size"] as number), "a size larger than the base map's");
      // The name, placement and filter are the base map's own.
      assert.deepEqual(layer.layout?.["text-field"], before[i].layout?.["text-field"]);
      assert.deepEqual((layer as { filter?: unknown }).filter, (before[i] as { filter?: unknown }).filter);
    } else {
      assert.deepEqual(layer, before[i]);
    }
  });
});

test("road names: dark text on a white halo wide enough to cover a stress line, stronger with the switch", () => {
  for (const strong of [false, true]) {
    const paint = roadLabelPaint(strong);
    assert.equal(paint["text-halo-color"], "#ffffff");
    const ratio = contrastRatio(paint["text-color"], paint["text-halo-color"]);
    assert.ok(ratio >= (strong ? 15 : 7), `${strong ? "strong" : "plain"} text ${ratio.toFixed(2)}:1 on its halo`);
    // MapLibre draws a halo up to a quarter of the text size.
    assert.ok(paint["text-halo-width"] >= 2 && paint["text-halo-width"] <= ROAD_LABEL.size / 4);
    for (const layer of shipped(strong).filter((l) => ROAD_LABEL_LAYER_IDS.includes(l.id))) assert.deepEqual({ ...layer.paint, ...paint }, layer.paint);
  }
  assert.ok(roadLabelPaint(true)["text-halo-width"] > roadLabelPaint(false)["text-halo-width"]);
});

test("road names: the switch repaints them in place", () => {
  const set: Record<string, Record<string, unknown>> = {};
  const map = {
    getLayer: (id: string) => (ROAD_LABEL_LAYER_IDS.includes(id) ? { id } : undefined),
    setPaintProperty: (id: string, name: string, value: unknown) => {
      (set[id] ??= {})[name] = value;
    },
  };
  setStressPalette(map as never);
  for (const id of ROAD_LABEL_LAYER_IDS) assert.deepEqual(set[id], roadLabelPaint());
});

test("a ride's street names are shortened as on the cue card", async () => {
  const { expression } = await import("@maplibre/maplibre-gl-style-spec");
  const field = expression.createExpression(rideRoadLabelField(), { type: "string" } as never);
  assert.equal(field.result, "success");
  const shown = (name: string) => (field.value as { evaluate: (g: object, f: object) => string }).evaluate({ zoom: 15 }, { properties: { name } });
  assert.equal(shown("R Street Northwest"), "R St NW");
  assert.equal(shown("Florida Avenue Northeast"), "Florida Ave NE");
  assert.equal(shown("East-West Highway"), "East-West Hwy");
  assert.equal(shown("Northwest Branch Trail"), "Northwest Branch Trl");
  assert.equal(shown("The Mall"), "The Mall");
  assert.equal(shown("Street"), "Street");
});
