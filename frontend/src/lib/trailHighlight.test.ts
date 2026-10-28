// The trail a hover card or the road panel is about, lit up on the map (the owner, 2026-10-28: "When mousing over or
// clicking on a trail, highlight that trail so you know where the elevation profile and rating begins and ends.").
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  TRAIL_HIGHLIGHT_ENDS_LAYER_ID,
  TRAIL_HIGHLIGHT_GLOW_LAYER_ID,
  TRAIL_HIGHLIGHT_SOURCE_ID,
  attachTrailHighlight,
  setHoverTrail,
  setPanelTrail,
  trailHighlightData,
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

test("the glow goes under the trail's own lines, the ends on top, and both clear when the trail is let go", () => {
  const map = stubMap([MTB_TICKS_LAYER_ID, "mtb-trail-label"]);
  const detach = attachTrailHighlight(map);
  try {
    // Nothing lit, nothing added.
    assert.equal(map.data(), undefined);
    setHoverTrail(LINE);
    assert.deepEqual(map.order, [TRAIL_HIGHLIGHT_GLOW_LAYER_ID, MTB_TICKS_LAYER_ID, "mtb-trail-label", TRAIL_HIGHLIGHT_ENDS_LAYER_ID]);
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
    assert.deepEqual(lit, [LINE]);
  } finally {
    globalThis.fetch = real;
  }
});
