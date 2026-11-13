/**
 * THE CLOSED SITES. The owner, 2026-11-12, of NASA Goddard's roads drawn white with nothing saying why: "For these
 * large closed campuses, let's put a label on them so people don't wonder why they can't go there. Maybe put some
 * shading on the areas that lack public access." A map style, not a control: always on, in every mode.
 *
 * The sites are the military areas and secured federal compounds whose roads the rebuild closes to bicycles, plus
 * closed areas drawn by hand with their source (Patuxent Research Refuge's closed area): restricted-data/
 * restricted-sites.json, by scripts/build_restricted_sites.py from the OSM extract. Each is washed grey and hatched,
 * with a dashed edge (a cue that is not colour alone), under the base map's labels and the stress lines; a named
 * site big enough (the build step's LABEL_MIN_M2, our default) carries its name and "No public access". A trip
 * point inside one is routed to its gate by the API (core.routing, move_restricted_points), which says so.
 *
 * These are functions of a small map interface so a test can run them against a stand-in (the real map needs WebGL).
 */
import { MAP_LABEL_FONT } from "./mapGlyphs.ts";
import { t } from "./i18n.ts";

export const RESTRICTED_SOURCE_ID = "restricted-sites";
export const RESTRICTED_TINT_LAYER = "restricted-sites-tint";
export const RESTRICTED_HATCH_LAYER = "restricted-sites-hatch";
export const RESTRICTED_EDGE_LAYER = "restricted-sites-edge";
export const RESTRICTED_LABEL_LAYER = "restricted-sites-label";
export const RESTRICTED_HATCH_IMAGE = "restricted-hatch";
export const RESTRICTED_HATCH_IMAGE_DARK = "restricted-hatch-dark";

/** Our defaults: the wash from zoom 10, the names from zoom 11 (where the stress lines start to show streets). */
export const RESTRICTED_MIN_ZOOM = 10;
export const RESTRICTED_LABEL_MIN_ZOOM = 11;

/** The label's second line. Short, as Go and Ride text is translated. */
export const NO_PUBLIC_ACCESS = "No public access";

/** Our defaults, unmeasured: the wash, hatch and edge colours, chosen to read on both maps without hiding the base map. */
export const RESTRICTED_STYLE = {
  light: { tint: "#6b6b78", tintOpacity: 0.12, ink: [70, 70, 85, 97] as const, edge: "#5f5f6c", text: "#33333d", halo: "#ffffff" },
  dark: { tint: "#000000", tintOpacity: 0.35, ink: [210, 210, 225, 102] as const, edge: "#a8a8bc", text: "#ececf4", halo: "#1f1f1f" },
} as const;

const isArea = ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]];
const isLabel = ["all", ["==", ["geometry-type"], "Point"], ["has", "name"]];

/** An 8x8 tile of rising diagonal stripes (RGBA), drawn at pixelRatio 1 so it reads at any density. */
export function hatchImage(ink: readonly [number, number, number, number]): { width: number; height: number; data: Uint8Array } {
  const size = 8;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if ((x + y) % 8 !== 7 && (x + y) % 8 !== 0) continue;
      data.set(ink, (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}

/** The layers, on the light map or the dark. */
export function restrictedLayers(dark = false, noAccess = t(NO_PUBLIC_ACCESS)): Record<string, unknown>[] {
  const s = dark ? RESTRICTED_STYLE.dark : RESTRICTED_STYLE.light;
  return [
    {
      id: RESTRICTED_TINT_LAYER,
      type: "fill",
      source: RESTRICTED_SOURCE_ID,
      minzoom: RESTRICTED_MIN_ZOOM,
      filter: isArea,
      paint: { "fill-color": s.tint, "fill-opacity": s.tintOpacity },
    },
    {
      id: RESTRICTED_HATCH_LAYER,
      type: "fill",
      source: RESTRICTED_SOURCE_ID,
      minzoom: RESTRICTED_MIN_ZOOM,
      filter: isArea,
      paint: { "fill-pattern": dark ? RESTRICTED_HATCH_IMAGE_DARK : RESTRICTED_HATCH_IMAGE },
    },
    {
      id: RESTRICTED_EDGE_LAYER,
      type: "line",
      source: RESTRICTED_SOURCE_ID,
      minzoom: RESTRICTED_MIN_ZOOM,
      filter: isArea,
      paint: { "line-color": s.edge, "line-width": 1.5, "line-dasharray": [3, 2] },
    },
    {
      id: RESTRICTED_LABEL_LAYER,
      type: "symbol",
      source: RESTRICTED_SOURCE_ID,
      minzoom: RESTRICTED_LABEL_MIN_ZOOM,
      filter: isLabel,
      layout: {
        "text-field": ["format", ["get", "name"], {}, "\n", {}, noAccess, { "font-scale": 0.82 }],
        "text-font": [MAP_LABEL_FONT],
        // Our default: the street names' size (ROAD_LABEL.size), the second line a little smaller.
        "text-size": 15,
        "text-max-width": 12,
      },
      paint: { "text-color": s.text, "text-halo-color": s.halo, "text-halo-width": 2.5 },
    },
  ];
}

/** The dark map's paint of the layers, by id, for lib/darkPaint.ts (set while the dark map shows, put back after). */
export function restrictedDarkPaint(): Record<string, Record<string, unknown>> {
  return Object.fromEntries(restrictedLayers(true, "").map((layer) => [layer.id as string, layer.paint as Record<string, unknown>]));
}

/** The light map's paint of the same layers, to put back. */
export function restrictedLightPaint(): Array<{ id: string; paint: Record<string, unknown> }> {
  return restrictedLayers(false, "").map((layer) => ({ id: layer.id as string, paint: layer.paint as Record<string, unknown> }));
}

/** The parts of a MapLibre map the layers use. */
export interface RestrictedMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
  hasImage(id: string): boolean;
  addImage(id: string, image: { width: number; height: number; data: Uint8Array }): void;
}

/**
 * Add the sites, once: the wash, hatch and edge over the base map's land and under its labels and the overlays (as
 * the coverage mask is: before the first label, or the first overlay layer, whichever comes first), the names over
 * the base map's labels and under the overlays (before the first overlay layer). `url` is the data file's.
 */
export function addRestrictedSites(map: RestrictedMap, url: string, dark: boolean, overlayIds: ReadonlySet<string> = new Set()): boolean {
  if (map.getSource(RESTRICTED_SOURCE_ID)) return false;
  if (!map.hasImage(RESTRICTED_HATCH_IMAGE)) map.addImage(RESTRICTED_HATCH_IMAGE, hatchImage(RESTRICTED_STYLE.light.ink));
  if (!map.hasImage(RESTRICTED_HATCH_IMAGE_DARK)) map.addImage(RESTRICTED_HATCH_IMAGE_DARK, hatchImage(RESTRICTED_STYLE.dark.ink));
  map.addSource(RESTRICTED_SOURCE_ID, { type: "geojson", data: url });
  const layers = map.getStyle().layers;
  const underLabels = layers.find((layer) => layer.type === "symbol" || overlayIds.has(layer.id))?.id;
  const underOverlays = layers.find((layer) => overlayIds.has(layer.id))?.id;
  for (const layer of restrictedLayers(dark)) {
    map.addLayer(layer, layer.type === "symbol" ? underOverlays : underLabels);
  }
  return true;
}
