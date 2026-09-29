/**
 * The opened file's own line on the map: faint and dashed, under the planned
 * route, so a rider can see where the two part. In the map's layer order it
 * sits over the stress overlay (which is under the base map's labels) and
 * under the rail stations and the route: stress, labels, file line,
 * stations, route. Drawn from the page (App
 * holds the map), not by MapView, and only ever from the file in hand.
 */
import type { LonLat } from "./geo.ts";

export const REFERENCE_SOURCE = "gpx-reference";
export const REFERENCE_LAYER = "gpx-reference-line";
/** The planned route's lowest layer (MapView); the reference goes under it. */
export const ROUTE_CASING_LAYER = "route-casing";
/** The rail stations' lowest layer (railLayer.ts), which also sits under the route. */
export const RAIL_BOTTOM_LAYER = "rail-entrances";

export interface ReferenceMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  removeSource(id: string): void;
  getLayer(id: string): unknown;
  addLayer(layer: object, beforeId?: string): void;
  removeLayer(id: string): void;
}

export function referenceLayer(): object {
  return {
    id: REFERENCE_LAYER,
    type: "line",
    source: REFERENCE_SOURCE,
    layout: { "line-join": "round", "line-cap": "round" },
    paint: { "line-color": "#7c3aed", "line-width": 3, "line-opacity": 0.6, "line-dasharray": [1.5, 1.5] },
  };
}

/** Show `line` as the reference, replacing any before it; null or too short removes it. */
export function showReference(map: ReferenceMap, line: readonly LonLat[] | null): void {
  if (map.getLayer(REFERENCE_LAYER)) map.removeLayer(REFERENCE_LAYER);
  if (map.getSource(REFERENCE_SOURCE)) map.removeSource(REFERENCE_SOURCE);
  if (!line || line.length < 2) return;
  map.addSource(REFERENCE_SOURCE, {
    type: "geojson",
    data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } },
  });
  const before = [RAIL_BOTTOM_LAYER, ROUTE_CASING_LAYER].find((id) => map.getLayer(id));
  map.addLayer(referenceLayer(), before);
}
