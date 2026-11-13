/**
 * Check a route's calmer ways (lib/worstStretches.ts) on the map: dashed, in the calm level's green, under the route
 * so the route stays on top where they meet. Drawn from the page (CheckRoute.tsx), as the opened file's line is
 * (referenceLayer.ts), and removed when the list goes.
 */
import type { LonLat } from "./geo.ts";
import { RAIL_BOTTOM_LAYER, ROUTE_CASING_LAYER, type ReferenceMap } from "./referenceLayer.ts";

export const CALMER_SOURCE = "check-calmer-ways";
export const CALMER_LAYER = "check-calmer-ways-line";

export function calmerLayer(): object {
  return {
    id: CALMER_LAYER,
    type: "line",
    source: CALMER_SOURCE,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": "#15803d", "line-width": 5, "line-opacity": 0.85, "line-dasharray": [1, 1.2] },
  };
}

/** Show `lines` as the calmer ways, replacing any before; none removes them. */
export function showCalmerWays(map: ReferenceMap, lines: readonly (readonly LonLat[])[]): void {
  if (map.getLayer(CALMER_LAYER)) map.removeLayer(CALMER_LAYER);
  if (map.getSource(CALMER_SOURCE)) map.removeSource(CALMER_SOURCE);
  const drawn = lines.filter((line) => line.length >= 2);
  if (drawn.length === 0) return;
  map.addSource(CALMER_SOURCE, {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: drawn.map((line) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } })),
    },
  });
  const before = [RAIL_BOTTOM_LAYER, ROUTE_CASING_LAYER].find((id) => map.getLayer(id));
  map.addLayer(calmerLayer(), before);
}
