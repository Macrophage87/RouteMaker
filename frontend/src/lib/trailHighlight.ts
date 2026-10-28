/**
 * The mountain-bike trail a hover card or the road panel is about, lit up on the map (the owner, 2026-10-28: "When
 * mousing over or clicking on a trail, highlight that trail so you know where the elevation profile and rating begins
 * and ends."): a wide white band edged in black under the trail's own line, so its difficulty colour still shows (and
 * not yellow or orange, the roads' own stress colours), and a dot at each end. The line is the OSM way the profile
 * and the rating are of (GET /api/trails/{way}/profile `line`), so the band runs exactly as far as the chart does.
 *
 * Two can be lit at once: the panel's trail, and the one under the mouse while the panel is open.
 */
import type { LonLat } from "./geo.ts";
import { MTB_MIN_ZOOM, MTB_TICKS_LAYER_ID, accessibilityOn, mtbTicksPaint } from "../stressStyle.js";

export const TRAIL_HIGHLIGHT_SOURCE_ID = "trail-highlight";
export const TRAIL_HIGHLIGHT_EDGE_LAYER_ID = "trail-highlight-edge";
export const TRAIL_HIGHLIGHT_GLOW_LAYER_ID = "trail-highlight-glow";
export const TRAIL_HIGHLIGHT_ENDS_LAYER_ID = "trail-highlight-ends";
export const TRAIL_HIGHLIGHT_COLOR = "#ffffff";
export const TRAIL_HIGHLIGHT_EDGE_COLOR = "#111111";

/** The map calls the highlight needs (MapLibre's, a stub in a test). */
export interface HighlightMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): unknown;
  getLayer(id: string): unknown;
  addLayer(layer: object, before?: string): unknown;
  setPaintProperty?(layer: string, name: string, value: unknown): unknown;
  isStyleLoaded?(): unknown;
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

/**
 * The band's widths: from MTB_MIN_ZOOM on, wider than the trail's own ticked edge (mtbTicksPaint, wider again with
 * the accessibility switch) by `pad` px, so it shows either side of it; zoomed out, a little wider than the thin
 * overview line.
 */
export function trailHighlightWidth(pad: number, strong = accessibilityOn()): unknown {
  const ticks = Number(mtbTicksPaint(strong)["line-width"]);
  return ["interpolate", ["linear"], ["zoom"], 7, 2 + pad, MTB_MIN_ZOOM - 1, 4 + pad, MTB_MIN_ZOOM, ticks + pad];
}

export function trailHighlightLayers(strong = accessibilityOn()): object[] {
  const line = { type: "line", source: TRAIL_HIGHLIGHT_SOURCE_ID, filter: ["==", ["geometry-type"], "LineString"], layout: { "line-cap": "round", "line-join": "round" } };
  return [
    {
      id: TRAIL_HIGHLIGHT_EDGE_LAYER_ID,
      ...line,
      paint: { "line-color": TRAIL_HIGHLIGHT_EDGE_COLOR, "line-opacity": 0.85, "line-width": trailHighlightWidth(8, strong) },
    },
    {
      id: TRAIL_HIGHLIGHT_GLOW_LAYER_ID,
      ...line,
      paint: { "line-color": TRAIL_HIGHLIGHT_COLOR, "line-width": trailHighlightWidth(4, strong) },
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
  // Not before the style is ready (a map just made); the next trail lit draws it.
  if (map.isStyleLoaded && !map.isStyleLoaded()) return;
  const data = trailHighlightData([panel, hover]);
  const source = map.getSource(TRAIL_HIGHLIGHT_SOURCE_ID) as { setData?: (d: unknown) => void } | undefined;
  if (source?.setData) source.setData(data);
  else if (data.features.length === 0) return;
  else map.addSource(TRAIL_HIGHLIGHT_SOURCE_ID, { type: "geojson", data });
  // Added on first use (the band under the trail's own lines, the ends on top); the widths again each time, which
  // follow the accessibility switch.
  const under = map.getLayer(MTB_TICKS_LAYER_ID) ? MTB_TICKS_LAYER_ID : undefined;
  for (const layer of trailHighlightLayers() as { id: string; paint: Record<string, unknown> }[]) {
    if (!map.getLayer(layer.id)) map.addLayer(layer, layer.id === TRAIL_HIGHLIGHT_ENDS_LAYER_ID ? undefined : under);
    else if (layer.paint["line-width"] !== undefined) map.setPaintProperty?.(layer.id, "line-width", layer.paint["line-width"]);
  }
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

/** A hover card's show and hide (featureHoverCard.ts FeatureHoverCard). */
interface HoverCard<W extends { key: string }, A, C> {
  show(words: W, at: A, chart: C): void;
  hide(): void;
}

/**
 * The hover card, lighting up its trail: `lightUp(key)` is the line's callback for the card shown for `key`, which
 * lights the trail only while that card is still the one shown; hiding the card, or showing another, lets it go.
 */
export function withTrailHighlight<W extends { key: string }, A, C>(card: HoverCard<W, A, C>): { card: HoverCard<W, A, C>; lightUp: (key: string) => (line: LonLat[]) => void } {
  let shown = "";
  return {
    card: {
      show: (words, at, chart) => {
        if (words.key !== shown) setHoverTrail(null);
        shown = words.key;
        card.show(words, at, chart);
      },
      hide: () => {
        shown = "";
        setHoverTrail(null);
        card.hide();
      },
    },
    lightUp: (key) => (line) => {
      if (key === shown) setHoverTrail(line);
    },
  };
}
