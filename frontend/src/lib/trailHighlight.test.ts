// The trail a hover card or the road panel is about, lit up on the map (the owner, 2026-10-28: "When mousing over or
// clicking on a trail, highlight that trail so you know where the elevation profile and rating begins and ends.").
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  TRAIL_HIGHLIGHT_EDGE_LAYER_ID,
  TRAIL_HIGHLIGHT_ENDS_LAYER_ID,
  TRAIL_HIGHLIGHT_GLOW_LAYER_ID,
  TRAIL_HIGHLIGHT_LETTERS_LAYER_ID,
  TRAIL_HIGHLIGHT_SOURCE_ID,
  trailHighlightLayers,
  attachTrailHighlight,
  setHoverTrail,
  setPanelTrail,
  trailHighlightData,
  withTrailHighlight,
} from "./trailHighlight.ts";
import { trailHoverChart } from "./featureHover.ts";
import { MTB_TICKS_LAYER_ID } from "../stressStyle.js";
import type { LonLat } from "./geo.ts";

const LINE: LonLat[] = [[-77.1, 39.1], [-77.11, 39.1], [-77.12, 39.11]];
const OTHER: LonLat[] = [[-77.2, 39.2], [-77.21, 39.2]];

function stubMap(layers: string[] = [MTB_TICKS_LAYER_ID]) {
  const sources = new Map<string, { data: unknown; setData(d: unknown): void }>();
  const order = [...layers];
  return {
    order,
    data: () => sources.get(TRAIL_HIGHLIGHT_SOURCE_ID)?.data as { features: { geometry: { type: string; coordinates: unknown } }[] } | undefined,
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, s: { data: unknown }) => {
      const source = { data: s.data, setData(d: unknown) { source.data = d; } };
      sources.set(id, source);
    },
    getLayer: (id: string) => (order.includes(id) ? { id } : undefined),
    addLayer: (layer: { id: string }, before?: string) => {
      const at = before ? order.indexOf(before) : -1;
      if (at < 0) order.push(layer.id);
      else order.splice(at, 0, layer.id);
    },
  };
}

test("the lit trail is its line and a dot at each end", () => {
  const data = trailHighlightData([LINE, null]);
  assert.deepEqual(data.features.map((f) => (f as { geometry: { type: string } }).geometry.type), ["LineString", "Point", "Point"]);
  assert.deepEqual((data.features[1] as { geometry: { coordinates: LonLat } }).geometry.coordinates, LINE[0]);
  assert.deepEqual((data.features[2] as { geometry: { coordinates: LonLat } }).geometry.coordinates, LINE[2]);
  assert.equal(trailHighlightData([null, [[-77, 39]]]).features.length, 0);
});

// The owner, 2026-11-03: "have a beginning and end icons on the trail with the compass directions inside the marker
// and on the graph so it's easy to tell them apart."
test("each end of the lit trail carries its compass point, as the chart's ends do; a loop's ends are plain dots", () => {
  const letters = (line: LonLat[]) =>
    trailHighlightData([line]).features.slice(1).map((f) => (f as { properties: { letter?: string } }).properties.letter);
  assert.deepEqual(letters([[-77.0, 38.91], [-77.0, 38.9]]), ["N", "S"]);
  assert.deepEqual(letters([[-77.02, 38.9], [-77.0, 38.9]]), ["W", "E"]);
  assert.deepEqual(letters([[-77.0, 38.9], [-77.0001, 38.9001]]), [undefined, undefined]);
  const layer = trailHighlightLayers(false).find((l) => (l as { id: string }).id === TRAIL_HIGHLIGHT_LETTERS_LAYER_ID) as {
    type: string; filter: unknown; layout: Record<string, unknown>;
  };
  assert.equal(layer.type, "symbol");
  assert.deepEqual(layer.layout["text-field"], ["get", "letter"]);
  assert.equal(layer.layout["text-allow-overlap"], true, "always drawn: the marker is the point of the highlight");
  assert.deepEqual(layer.layout["text-font"], ["Noto Sans Medium"], "a face the base map's glyphs carry");
});

test("the highlight's layers are a style MapLibre accepts, with the accessibility switch on and off", () => {
  for (const strong of [false, true]) {
    const errors = spec.validateStyleMin({
      version: 8,
      glyphs: "https://x/{fontstack}/{range}.pbf",
      sources: { [TRAIL_HIGHLIGHT_SOURCE_ID]: { type: "geojson", data: trailHighlightData([LINE]) } },
      layers: trailHighlightLayers(strong),
    } as never);
    assert.deepEqual(errors.map((e: { message: string }) => e.message), []);
  }
});

test("the band goes under the trail's own lines, the ends on top, and both clear when the trail is let go", () => {
  const map = stubMap([MTB_TICKS_LAYER_ID, "mtb-trail-label"]);
  const detach = attachTrailHighlight(map);
  try {
    // Nothing lit, nothing added.
    assert.equal(map.data(), undefined);
    setHoverTrail(LINE);
    assert.deepEqual(map.order, [TRAIL_HIGHLIGHT_EDGE_LAYER_ID, TRAIL_HIGHLIGHT_GLOW_LAYER_ID, MTB_TICKS_LAYER_ID, "mtb-trail-label", TRAIL_HIGHLIGHT_ENDS_LAYER_ID, TRAIL_HIGHLIGHT_LETTERS_LAYER_ID]);
    assert.equal(map.data()?.features.length, 3);
    // The panel's trail and the one under the mouse together.
    setPanelTrail(OTHER);
    assert.equal(map.data()?.features.length, 6);
    setHoverTrail(null);
    setPanelTrail(null);
    assert.equal(map.data()?.features.length, 0);
  } finally {
    setHoverTrail(null);
    setPanelTrail(null);
    detach();
  }
});

test("a trail's hover card hands the map the way's line from its profile", async () => {
  const real = globalThis.fetch;
  const profile = { way: 77, length_m: 300, gain_m: 5, loss_m: 3, max_grade_pct: 4, interval_m: 30, m: [0, 300], elevation_m: [10, 12], grade_pct: [null, 1], line: LINE };
  globalThis.fetch = (async (url: string) => {
    const body = String(url).includes("/api/trails/") ? profile : { found: true, osm_way_id: 77, sections: [] };
    return { ok: true, status: 200, json: async () => body };
  }) as unknown as typeof fetch;
  try {
    const lit: LonLat[][] = [];
    const element = await trailHoverChart("https://example.test", [-77.1, 39.1], (line) => lit.push(line))();
    assert.ok(element);
    // Drawn east to west, mostly: turned, so it reads west to east (lib/trailProfile.ts northOrWestFirst).
    assert.deepEqual(lit, [[...LINE].reverse()]);
  } finally {
    globalThis.fetch = real;
  }
});

test("the hover card lights its trail only while it is still the card shown, and lets it go when it hides", () => {
  const map = stubMap();
  const detach = attachTrailHighlight(map);
  const calls: string[] = [];
  const { card, lightUp } = withTrailHighlight({ show: (w: { key: string }) => calls.push(`show ${w.key}`), hide: () => calls.push("hide") });
  try {
    card.show({ key: "a" }, null, null);
    const late = lightUp("a");
    card.show({ key: "b" }, null, null);
    // A's line arrives after B's card: not lit.
    late(LINE);
    assert.equal(map.data(), undefined);
    lightUp("b")(OTHER);
    assert.equal(map.data()?.features.length, 3);
    card.hide();
    assert.equal(map.data()?.features.length, 0);
    assert.deepEqual(calls, ["show a", "show b", "hide"]);
  } finally {
    setHoverTrail(null);
    detach();
  }
});
