// The street names (stressStyle.js, ROAD_LABEL; the owner, 2026-10-20: the names "seem to disappear over the
// colored lanes"): the base map's road-name layers, as this app ships them, read clearly over the stress lines.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { PLACE_LABEL, PLACE_LABEL_LAYER_IDS, ROAD_LABEL, ROAD_LABEL_LAYER_IDS, contrastRatio, placeLabelPaint, rideRoadLabelField, roadLabelPaint, withClearRoadLabels } from "./stressStyle.js";
import { setStressPalette } from "./lib/mapGlue.ts";

type Layer = { id: string; type: string; layout?: Record<string, unknown>; paint?: Record<string, unknown> };
const shipped = (strong: boolean) => withClearRoadLabels(protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }), strong) as Layer[];

test("road names: both base map name layers are restyled, and only they and the place names", () => {
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
    } else if (PLACE_LABEL_LAYER_IDS.includes(layer.id)) {
      // Only the face, size, case and spacing change: the name, placement, icon and filter are the base map's.
      const restyled = ["text-font", "text-size", "text-transform", "text-letter-spacing"];
      const keep = (l: Layer) => Object.fromEntries(Object.entries(l.layout ?? {}).filter(([k]) => !restyled.includes(k)));
      assert.deepEqual(keep(layer), keep(before[i]));
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

// The owner, 2026-10-21: "Make the neighborhood names also in bold an with the same font so they are readable. Cities too."
type Stops = (string | number | string[])[];
const sizeAt = (size: Stops, zoom: number): number => {
  const stops = size.slice(3) as number[];
  for (let k = 0; k < stops.length; k += 2) if (zoom <= stops[k]) return k === 0 ? stops[1] : stops[k - 1] + ((stops[k + 1] - stops[k - 1]) * (zoom - stops[k - 2])) / (stops[k] - stops[k - 2]);
  return stops[stops.length - 1];
};

test("place names: the shipped style validates", async () => {
  const { validateStyleMin } = await import("@maplibre/maplibre-gl-style-spec");
  const layers = shipped(false).filter((l) => PLACE_LABEL_LAYER_IDS.includes(l.id));
  const style = { version: 8, glyphs: "https://x/{fontstack}/{range}.pbf", sources: { protomaps: { type: "vector", url: "https://x/t.json" } }, layers };
  assert.deepEqual(validateStyleMin(style as never), []);
});

test("place names: neighbourhoods and towns in the street names' family, heavier, on the white halo", () => {
  const before = protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Layer[];
  for (const id of PLACE_LABEL_LAYER_IDS) assert.ok(before.some((l) => l.id === id), `${id} is in the base map`);
  assert.equal(PLACE_LABEL.font, "Atkinson Hyperlegible Next ExtraBold");
  for (const strong of [false, true]) {
    for (const layer of shipped(strong).filter((l) => PLACE_LABEL_LAYER_IDS.includes(l.id))) {
      assert.deepEqual(layer.layout?.["text-font"], [PLACE_LABEL.font]);
      // A town in mixed case; a neighbourhood in small capitals, apart from a street name.
      const town = layer.id === "places_locality";
      assert.equal(layer.layout?.["text-transform"], town ? "none" : "uppercase");
      assert.equal(layer.layout?.["text-letter-spacing"], town ? 0 : 0.04);
      const paint = placeLabelPaint(layer.id, strong);
      assert.deepEqual({ ...layer.paint, ...paint }, layer.paint);
      const ratio = contrastRatio(paint["text-color"], paint["text-halo-color"]);
      assert.ok(ratio >= (strong ? 15 : 7), `${layer.id} ${ratio.toFixed(2)}:1 on its halo`);
      assert.ok(paint["text-halo-width"] >= 2 && paint["text-halo-width"] <= 11 / 4, "MapLibre draws a halo up to a quarter of the smallest size");
    }
  }
  assert.ok(placeLabelPaint("places_subplace", true)["text-halo-width"] > placeLabelPaint("places_subplace", false)["text-halo-width"]);
});

test("place names: a town reads above a neighbourhood, both under the station names' 18 px", () => {
  for (const zoom of [12, 13, 14, 16, 18]) {
    const town = sizeAt(PLACE_LABEL.town.size as Stops, zoom);
    const large = sizeAt(PLACE_LABEL.town.largeSize as Stops, zoom);
    const hood = sizeAt(PLACE_LABEL.neighbourhood.size as Stops, zoom);
    assert.ok(town > hood, `zoom ${zoom}: town ${town} over neighbourhood ${hood}`);
    assert.ok(large >= town, `zoom ${zoom}: a large town ${large} at least a town's ${town}`);
    assert.ok(large < 18, `zoom ${zoom}: town ${large} under a station's 18 px`);
    assert.ok(hood >= 11 && hood < ROAD_LABEL.size, `zoom ${zoom}: capitals ${hood} under a street name's ${ROAD_LABEL.size}`);
  }
  const locality = shipped(false).find((l) => l.id === "places_locality");
  // One zoom ramp at the top (MapLibre allows no other), the rank picking each stop's size.
  const size = locality?.layout?.["text-size"] as unknown[];
  assert.deepEqual(size.slice(0, 3), ["interpolate", ["linear"], ["zoom"]]);
  for (let k = 3; k < size.length; k += 2) {
    const zoom = size[k] as number;
    const [, isLarge, large, small] = size[k + 1] as [string, unknown, number, number];
    assert.deepEqual(isLarge, [">=", ["coalesce", ["get", "population_rank"], 0], PLACE_LABEL.largeTownRank]);
    assert.equal(large, sizeAt(PLACE_LABEL.town.largeSize as Stops, zoom));
    assert.equal(small, sizeAt(PLACE_LABEL.town.size as Stops, zoom));
  }
  // The stops written out, so a fault shared by the style and sizeAt shows.
  const isLarge = [">=", ["coalesce", ["get", "population_rank"], 0], 9];
  assert.deepEqual(size.slice(3), [8, ["case", isLarge, 15, 13], 11, ["case", isLarge, 17, 15], 14, ["case", isLarge, 17, 16], 17, ["case", isLarge, 17, 17]]);
  assert.ok(contrastRatio(PLACE_LABEL.town.color, "#ffffff") > contrastRatio(PLACE_LABEL.neighbourhood.color, "#ffffff"));
});

test("place names: the switch repaints them in place", () => {
  const set: Record<string, Record<string, unknown>> = {};
  const map = {
    getLayer: (id: string) => (PLACE_LABEL_LAYER_IDS.includes(id) ? { id } : undefined),
    setPaintProperty: (id: string, name: string, value: unknown) => {
      (set[id] ??= {})[name] = value;
    },
  };
  setStressPalette(map as never);
  for (const id of PLACE_LABEL_LAYER_IDS) assert.deepEqual(set[id], placeLabelPaint(id));
});
