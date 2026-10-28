/**
 * The mountain-bike trail a hover card or the road panel is about, lit up on the map (the owner, 2026-10-28: "When
 * mousing over or clicking on a trail, highlight that trail so you know where the elevation profile and rating begins
 * and ends."): a wide yellow glow under the trail's own line, so its difficulty colour still shows, and a dot at each
 * end. The line is the OSM way the profile and the rating are of (GET /api/trails/{way}/profile `line`), so the glow
 * runs exactly as far as the chart does.
 *
 * Two can be lit at once: the panel's trail, and the one under the mouse while the panel is open.
 */
import type { LonLat } from "./geo.ts";
import { MTB_TICKS_LAYER_ID } from "../stressStyle.js";

export const TRAIL_HIGHLIGHT_SOURCE_ID = "trail-highlight";
export const TRAIL_HIGHLIGHT_GLOW_LAYER_ID = "trail-highlight-glow";
export const TRAIL_HIGHLIGHT_ENDS_LAYER_ID = "trail-highlight-ends";
export const TRAIL_HIGHLIGHT_COLOR = "#ffd60a";

/** The map calls the highlight needs (MapLibre's, a stub in a test). */
export interface HighlightMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): unknown;
  getLayer(id: string): unknown;
  addLayer(layer: object, before?: string): unknown;
}

type Line = LonLat[] | null;

/** The lines and their ends as GeoJSON: a LineString per lit trail, a Point at each end. */
export function trailHighlightData(lines: Line[]): { type: "FeatureCollection"; features: object[] } {
  const features: object[] = [];
  for (const line of lines) {
    if (!line || line.length < 2) continue;
    features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: line } });
    for (const end of [line[0], line[line.length - 1]]) features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: end } });
  }
  return { type: "FeatureCollection", features };
}

export function trailHighlightLayers(): object[] {
  return [
    {
      id: TRAIL_HIGHLIGHT_GLOW_LAYER_ID,
      type: "line",
      source: TRAIL_HIGHLIGHT_SOURCE_ID,
      filter: ["==", ["geometry-type"], "LineString"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": TRAIL_HIGHLIGHT_COLOR,
        "line-opacity": 0.9,
        "line-width": ["interpolate", ["linear"], ["zoom"], 7, 6, 12, 10, 16, 16],
      },
    },
    {
      id: TRAIL_HIGHLIGHT_ENDS_LAYER_ID,
      type: "circle",
      source: TRAIL_HIGHLIGHT_SOURCE_ID,
      filter: ["==", ["geometry-type"], "Point"],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 3.5, 14, 6],
        "circle-color": "#ffffff",
        "circle-stroke-color": "#1a1a1a",
        "circle-stroke-width": 2.5,
      },
    },
  ];
}

let panel: Line = null;
let hover: Line = null;
const maps = new Set<HighlightMap>();

function draw(map: HighlightMap): void {
  const data = trailHighlightData([panel, hover]);
  const source = map.getSource(TRAIL_HIGHLIGHT_SOURCE_ID) as { setData?: (d: unknown) => void } | undefined;
  if (source?.setData) source.setData(data);
  else if (data.features.length === 0) return;
  else map.addSource(TRAIL_HIGHLIGHT_SOURCE_ID, { type: "geojson", data });
  // Added on first use, and again after a base map change took them away: the glow under the trail's own lines, the
  // ends on top.
  const [glow, ends] = trailHighlightLayers() as [{ id: string }, { id: string }];
  if (!map.getLayer(glow.id)) map.addLayer(glow, map.getLayer(MTB_TICKS_LAYER_ID) ? MTB_TICKS_LAYER_ID : undefined);
  if (!map.getLayer(ends.id)) map.addLayer(ends);
}

function redraw(): void {
  for (const map of maps) draw(map);
}

/** Draw on `map` from now on; the returned function stops. */
export function attachTrailHighlight(map: HighlightMap): () => void {
  maps.add(map);
  draw(map);
  return () => {
    maps.delete(map);
  };
}

/** The road panel's trail, or null when the panel closes or shows something else. */
export function setPanelTrail(line: Line): void {
  if (line === panel) return;
  panel = line;
  redraw();
}

/** The trail under the mouse, or null when the hover card goes. */
export function setHoverTrail(line: Line): void {
  if (line === hover) return;
  hover = line;
  redraw();
}
