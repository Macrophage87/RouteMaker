/**
 * The District of Columbia's boundary, for the Mass Ride map (OWNER-DECISIONS 418, 418a):
 * "Grey out everywhere outside DC on that map too as we don't support it yet." Mass Ride
 * planning covers the District only for now, so in Mass Ride mode the map greys out
 * everything outside it (`dcMask`, under the capacity colours, which the Mass Ride tiles
 * draw only inside it: core/mass_tiles.py clips to the same boundary), the legend says so
 * in words, and a route that leaves the District gets a notice, shown and said
 * (`outsideDcNote`).
 *
 * The boundary is OpenStreetMap's (the admin_level=4 US-DC relation in the rebuild's
 * extract), written by scripts/build_dc_boundary.py: the same bytes as
 * src/core/geodata/dc-boundary.geojson, which tests/test_dc_boundary.py holds equal.
 * Credit: © OpenStreetMap contributors (ODbL), docs/SOURCES.md.
 */
import DC_DATA from "../massride-data/dc-boundary.json" with { type: "json" };
import type { LonLat } from "./geo.ts";
import type { RouteResponse } from "./api.ts";

type Ring = number[][];
interface DcFeature {
  type: "Feature";
  properties: { name: string; source: string; credit: string };
  geometry: { type: "MultiPolygon"; coordinates: Ring[][] };
}

export const DC_BOUNDARY = DC_DATA as unknown as DcFeature;

/** The polygons, each an outer ring and its holes. */
const POLYGONS: Ring[][] = DC_BOUNDARY.geometry.coordinates;

/** In words, wherever the Mass Ride map is described (the legend, the planner). */
export const MASS_DC_ONLY =
  "Mass Ride planning covers DC only for now. Outside the District of Columbia the map is grayed out and no riders-per-minute figures are drawn.";

/** The boundary's credit, under the legend (OWNER-DECISIONS 301, 306: every source a rider sees is named). */
export const DC_BOUNDARY_CREDIT = "District of Columbia boundary: © OpenStreetMap contributors (ODbL).";

/** The notice for a Mass Ride route that leaves the District (418a). */
export const MASS_OUTSIDE_DC_NOTICE = "Part of this route is outside the area Mass Ride planning covers (DC only for now).";

function inRing(lon: number, lat: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Whether a point is inside the District (on the boundary itself counts either way). */
export function inDc([lon, lat]: LonLat): boolean {
  return POLYGONS.some(([outer, ...holes]) => inRing(lon, lat, outer) && !holes.some((hole) => inRing(lon, lat, hole)));
}

/**
 * Whether any part of a line is outside the District: any vertex, or the middle of any
 * stretch between two (a straight stretch can cut across a bend in the boundary).
 */
export function leavesDc(line: readonly LonLat[]): boolean {
  for (let i = 0; i < line.length; i++) {
    if (!inDc(line[i])) return true;
    if (i > 0) {
      const mid: LonLat = [(line[i - 1][0] + line[i][0]) / 2, (line[i - 1][1] + line[i][1]) / 2];
      if (!inDc(mid)) return true;
    }
  }
  return false;
}

/** The notice for a route, or null: only a Mass Ride's, and only when it leaves the District. */
export function outsideDcNote(route: Pick<RouteResponse, "preset" | "geometry"> | null | undefined): string | null {
  if (!route || route.preset !== "mass-ride") return null;
  return leavesDc(route.geometry?.coordinates ?? []) ? MASS_OUTSIDE_DC_NOTICE : null;
}

export const DC_MASK_SOURCE_ID = "massride-dc";

// The world as Web Mercator draws it: the mask's outer ring (as mapGlue.ts coverageMask's).
const WORLD: Ring = [
  [-180, -85.0511],
  [180, -85.0511],
  [180, 85.0511],
  [-180, 85.0511],
  [-180, -85.0511],
];

/** The world with the District as its hole, and the District's edge as a line. */
export function dcMask() {
  const outers = POLYGONS.map((polygon) => polygon[0]);
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { part: "mask" },
        // A hole winds the other way from its outer ring (RFC 7946 3.1.6).
        geometry: { type: "Polygon" as const, coordinates: [WORLD, ...outers.map((ring) => [...ring].reverse())] },
      },
      {
        type: "Feature" as const,
        properties: { part: "edge" },
        geometry: { type: "MultiLineString" as const, coordinates: outers },
      },
    ],
  };
}

/**
 * The mask's two layers, bottom first: the coverage mask's grey (mapGlue.ts
 * COVERAGE_MASK_LAYERS), a little darker so the District reads as the one place this
 * map plans, and a dashed edge, so the boundary is not told by the shading alone.
 * Shown only in Mass Ride mode.
 */
export const DC_MASK_LAYERS = [
  {
    id: "massride-dc-mask",
    type: "fill",
    source: DC_MASK_SOURCE_ID,
    filter: ["==", ["get", "part"], "mask"],
    paint: { "fill-color": "#5b616b", "fill-opacity": 0.5 },
  },
  {
    id: "massride-dc-edge",
    type: "line",
    source: DC_MASK_SOURCE_ID,
    filter: ["==", ["get", "part"], "edge"],
    paint: { "line-color": "#2f343b", "line-width": 2, "line-dasharray": [3, 2] },
  },
] as const;

export const DC_MASK_LAYER_IDS: readonly string[] = DC_MASK_LAYERS.map((layer) => layer.id);

/** The parts of a MapLibre map the mask uses. */
export interface DcMaskMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  setLayoutProperty(id: string, name: string, value: string): void;
}

/**
 * Add the mask, once, over the base map and under its labels and the overlays (as the
 * coverage mask is: `before` is the first label, or the first overlay layer, whichever
 * comes first), shown only when `visible`.
 */
export function addDcMask(map: DcMaskMap, visible: boolean, overlayIds: ReadonlySet<string> = new Set()): boolean {
  if (map.getSource(DC_MASK_SOURCE_ID)) return false;
  map.addSource(DC_MASK_SOURCE_ID, { type: "geojson", data: dcMask() });
  const before = map.getStyle().layers.find((layer) => layer.type === "symbol" || overlayIds.has(layer.id))?.id;
  for (const layer of DC_MASK_LAYERS) map.addLayer({ ...layer, layout: { visibility: visible ? "visible" : "none" } }, before);
  return true;
}

/** Show or hide the mask (Mass Ride mode or not). */
export function setDcMaskVisibility(map: Pick<DcMaskMap, "getLayer" | "setLayoutProperty">, visible: boolean): void {
  for (const id of DC_MASK_LAYER_IDS) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}
