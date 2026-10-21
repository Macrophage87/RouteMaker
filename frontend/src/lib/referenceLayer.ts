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

// The opened file's named waypoints (gpxPlan.ts waypointMarks): a dot and its name, beside the file's line and
// under the route. The name is a text field drawn on the map's canvas, never markup.
export const WAYPOINTS_SOURCE = "gpx-waypoints";
export const WAYPOINT_DOT_LAYER = "gpx-waypoint-dots";
export const WAYPOINT_NAME_LAYER = "gpx-waypoint-names";
/** The base map's label font (railLayer.ts LABEL_FONT), which its glyphs carry. */
const WAYPOINT_FONT = "Noto Sans Medium";

export function waypointLayers(): object[] {
  return [
    {
      id: WAYPOINT_DOT_LAYER,
      type: "circle",
      source: WAYPOINTS_SOURCE,
      paint: { "circle-radius": 5, "circle-color": "#7c3aed", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 },
    },
    {
      id: WAYPOINT_NAME_LAYER,
      type: "symbol",
      source: WAYPOINTS_SOURCE,
      layout: {
        "text-field": ["get", "name"],
        "text-font": [WAYPOINT_FONT],
        // The street names' size and halo (the owner, 2026-10-21: "All into stret name style").
        "text-size": 15,
        "text-anchor": "top",
        "text-offset": [0, 0.7],
        "text-optional": true,
      },
      paint: { "text-color": "#4c1d95", "text-halo-color": "#ffffff", "text-halo-width": 3.5 },
    },
  ];
}

/** Show `marks` as the file's waypoints, replacing any before; null or none removes them. */
export function showWaypoints(map: ReferenceMap, marks: readonly { at: LonLat; name: string }[] | null): void {
  for (const id of [WAYPOINT_NAME_LAYER, WAYPOINT_DOT_LAYER]) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(WAYPOINTS_SOURCE)) map.removeSource(WAYPOINTS_SOURCE);
  if (!marks || marks.length === 0) return;
  map.addSource(WAYPOINTS_SOURCE, {
    type: "geojson",
    data: {
      type: "FeatureCollection",
      features: marks.map((m) => ({ type: "Feature", properties: { name: m.name }, geometry: { type: "Point", coordinates: [m.at[0], m.at[1]] } })),
    },
  });
  const before = [RAIL_BOTTOM_LAYER, ROUTE_CASING_LAYER].find((id) => map.getLayer(id));
  for (const layer of waypointLayers()) map.addLayer(layer, before);
}
