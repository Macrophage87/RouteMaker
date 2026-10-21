// The street names (stressStyle.js, ROAD_LABEL; the owner, 2026-10-20: the names "seem to disappear over the
// colored lanes"): the base map's road-name layers, as this app ships them, read clearly over the stress lines.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { ROAD_LABEL, ROAD_LABEL_LAYER_IDS, TRAIL_LABEL, TRAIL_LABEL_LAYER_ID, TRAIL_LABEL_MIN_ZOOM, contrastRatio, rideRoadLabelField, rideTrailLabelField, roadLabelPaint, stressFilters, trailLabelLayers, trailLabelPaint, withClearRoadLabels } from "./stressStyle.js";
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
    // A street's colour, and a path's in the trail names' purple (2026-10-21).
    const [, isPath, path, street] = paint["text-color"] as [string, unknown, string, string];
    assert.deepEqual(isPath, ["==", ["get", "kind"], "path"]);
    assert.equal(path, strong ? TRAIL_LABEL.strongColor : TRAIL_LABEL.color);
    assert.equal(street, strong ? ROAD_LABEL.strongColor : ROAD_LABEL.color);
    for (const colour of [street, path]) {
      const ratio = contrastRatio(colour, paint["text-halo-color"]);
      assert.ok(ratio >= (strong ? 15 : 7), `${strong ? "strong" : "plain"} text ${ratio.toFixed(2)}:1 on its halo`);
    }
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
  assert.equal(shown("Constitution Avenue NW"), "Constitution Ave NW");
  assert.equal(shown("Main St"), "Main St");
});

test("a ride's street name in another script, with no English name, keeps the base map's field", async () => {
  const { expression } = await import("@maplibre/maplibre-gl-style-spec");
  const field = expression.createExpression(rideRoadLabelField(["get", "name"]), { type: "string" } as never);
  assert.equal(field.result, "success");
  const shown = (properties: object) => (field.value as { evaluate: (g: object, f: object) => string }).evaluate({ zoom: 15 }, { properties });
  assert.equal(shown({ name: "Rue Street", script: "Han" }), "Rue Street");
  assert.equal(shown({ name: "R Street Northwest" }), "R St NW");
});

// THE MAJOR TRAILS' NAMES (the owner, 2026-10-21: "Major off road bike trails like the Metropolitan Branch Trail should be
// named on the map."): the tiles' `trail_name`, along the line, from the zoom every street comes in at, in the street
// names' face, size and halo, in the path rails' purple.
test("trail names: along each major trail from zoom 12, in the street names' face and size", () => {
  const [layer] = trailLabelLayers("s", "weekday_offpeak", false) as Layer[] & { minzoom?: number; filter?: unknown }[];
  assert.equal(layer.id, TRAIL_LABEL_LAYER_ID);
  assert.equal(layer.type, "symbol");
  assert.equal((layer as { minzoom?: number }).minzoom, TRAIL_LABEL_MIN_ZOOM);
  assert.equal(TRAIL_LABEL_MIN_ZOOM, 12);
  assert.equal(layer.layout?.["symbol-placement"], "line");
  assert.deepEqual(layer.layout?.["text-field"], ["get", "trail_name"]);
  assert.deepEqual(layer.layout?.["text-font"], [ROAD_LABEL.font]);
  assert.equal(layer.layout?.["text-size"], ROAD_LABEL.size);
  assert.deepEqual(layer.paint, trailLabelPaint(false));
  assert.deepEqual((layer as { filter?: unknown }).filter, stressFilters("weekday_offpeak")[TRAIL_LABEL_LAYER_ID]);
});

test("trail names: dark purple on the street names' white halo, darker with the switch, and not the street names' grey", () => {
  for (const strong of [false, true]) {
    const paint = trailLabelPaint(strong);
    assert.equal(paint["text-halo-color"], ROAD_LABEL.halo);
    assert.equal(paint["text-halo-width"], roadLabelPaint(strong)["text-halo-width"]);
    const ratio = contrastRatio(paint["text-color"], paint["text-halo-color"]);
    assert.ok(ratio >= (strong ? 15 : 7), `${strong ? "strong" : "plain"} ${ratio.toFixed(2)}:1`);
    assert.notEqual(paint["text-color"], strong ? ROAD_LABEL.strongColor : ROAD_LABEL.color);
  }
});

test("trail names: only a way that carries one, in every ride time", async () => {
  const { featureFilter } = await import("@maplibre/maplibre-gl-style-spec");
  for (const when of ["weekend", "weekday_rush", "weekday_offpeak", "night"]) {
    const filter = featureFilter(stressFilters(when)[TRAIL_LABEL_LAYER_ID] as never, `layers[${TRAIL_LABEL_LAYER_ID}].filter`);
    const draws = (properties: Record<string, unknown>) => filter.filter({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
    assert.equal(draws({ tier: 1, facility: "path", trail_name: "Metropolitan Branch Trail" }), true, when);
    assert.equal(draws({ tier: 1, facility: "path" }), false, when);
  }
});

test("a ride's trail names are shortened as the street names are", async () => {
  const { expression } = await import("@maplibre/maplibre-gl-style-spec");
  const field = expression.createExpression(rideTrailLabelField(), { type: "string" } as never);
  assert.equal(field.result, "success");
  const shown = (trail_name: string) => (field.value as { evaluate: (g: object, f: object) => string }).evaluate({ zoom: 15 }, { properties: { trail_name, name: "Other" } });
  assert.equal(shown("Rock Creek Trail"), "Rock Creek Trl");
  assert.equal(shown("Metropolitan Branch Trail"), "Metropolitan Branch Trl");
  assert.equal(shown("Anacostia Riverwalk"), "Anacostia Riverwalk");
});
