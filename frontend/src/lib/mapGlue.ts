/**
 * What MapView does to the map, as functions of a small map interface, so a
 * test can run them against a stand-in (MapView itself needs WebGL).
 */
import { FACILITIES, STRESS_TILE_LAYER, stressOverlayLayers } from "../stressStyle.js";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";

/** The parts of a MapLibre map these use. */
export interface OverlayMap {
  getSource(id: string): unknown;
  addSource(id: string, source: ReturnType<typeof stressSource>): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  setLayoutProperty(id: string, name: string, value: string): void;
}

/**
 * Add the stress overlay, once: under the base map's labels (and the route,
 * added later), over its roads, in exactly the order stressOverlayLayers
 * gives - every casing under every tier. Returns whether it was added.
 */
export function addStressOverlay(map: OverlayMap, origin: string, visible: boolean): boolean {
  if (map.getSource(STRESS_SOURCE_ID)) return false;
  map.addSource(STRESS_SOURCE_ID, stressSource(origin));
  const firstSymbol = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
  const layout = { visibility: visible ? "visible" : "none" };
  for (const layer of stressOverlayLayers(STRESS_SOURCE_ID)) {
    map.addLayer({ ...layer, layout }, firstSymbol);
  }
  return true;
}

/** Show or hide every overlay layer that is on the map. */
export function setStressVisibility(map: OverlayMap, visible: boolean): void {
  for (const { id } of stressOverlayLayers(STRESS_SOURCE_ID)) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
  }
}

/**
 * The markers effect's dependencies: the points, and the counter App bumps to
 * put a dragged marker back without changing the points (a drag outside the
 * area). Without the counter a put-back marker stays where it was dropped.
 */
export function markerDeps<P>(points: readonly P[], markerReset: number): readonly unknown[] {
  return [points, markerReset];
}

/** GET /api/coverage: the area the API routes in, as a GeoJSON polygon feature. */
export interface Coverage {
  type: "Feature";
  geometry: { type: "Polygon"; coordinates: number[][][] };
  properties: Record<string, unknown>;
}

export const COVERAGE_SOURCE_ID = "coverage";

// The world as Web Mercator draws it: the mask's outer ring.
const WORLD: number[][] = [
  [-180, -85.0511],
  [180, -85.0511],
  [180, 85.0511],
  [-180, 85.0511],
  [-180, -85.0511],
];

/**
 * What greys out the map beyond the covered area (owner request of
 * 2026-09-27): the world with the coverage ring as its hole, and the ring
 * again as a line for the edge. The ring is the API's own
 * (`core.api.coverage_ring`, the box its route validator enforces), so what
 * the map shows as covered is what the planner accepts.
 */
export function coverageMask(coverage: Coverage) {
  const ring = coverage.geometry.coordinates[0];
  return {
    type: "FeatureCollection" as const,
    features: [
      {
        type: "Feature" as const,
        properties: { part: "mask" },
        // A hole winds the other way from its outer ring (RFC 7946 3.1.6).
        geometry: { type: "Polygon" as const, coordinates: [WORLD, [...ring].reverse()] },
      },
      {
        type: "Feature" as const,
        properties: { part: "edge" },
        geometry: { type: "LineString" as const, coordinates: ring },
      },
    ],
  };
}

/**
 * The mask's two layers, bottom first. The base map is the same light flavour
 * in both themes (mapStyle.ts, SPRITE_FLAVOR), so one grey serves both: dark
 * enough to read as "not here", open enough that the roads beyond stay legible
 * for someone riding in from outside; the edge is a solid dark line.
 */
export const COVERAGE_MASK_LAYERS = [
  {
    id: "coverage-mask",
    type: "fill",
    source: COVERAGE_SOURCE_ID,
    filter: ["==", ["get", "part"], "mask"],
    paint: { "fill-color": "#5b616b", "fill-opacity": 0.42 },
  },
  {
    id: "coverage-edge",
    type: "line",
    source: COVERAGE_SOURCE_ID,
    filter: ["==", ["get", "part"], "edge"],
    paint: { "line-color": "#2f343b", "line-width": 1.5 },
  },
] as const;

/** The parts of a MapLibre map the mask uses. */
export interface MaskMap {
  getSource(id: string): unknown;
  addSource(id: string, source: object): void;
  getStyle(): { layers: ReadonlyArray<{ id: string; type: string }> };
  addLayer(layer: object, beforeId?: string): void;
}

/**
 * Add the mask, once, over the base map and under its labels - so a place
 * name beyond the edge is still read - and under the stress overlay, whichever
 * of the two reaches the map first. A layer added this way takes no clicks:
 * the map's own click handler still decides what a click outside does.
 */
export function addCoverageMask(map: MaskMap, coverage: Coverage): boolean {
  if (map.getSource(COVERAGE_SOURCE_ID)) return false;
  map.addSource(COVERAGE_SOURCE_ID, { type: "geojson", data: coverageMask(coverage) });
  const overlay = new Set(stressOverlayLayers(STRESS_SOURCE_ID).map((layer: { id: string }) => layer.id));
  const before = map.getStyle().layers.find((layer) => layer.type === "symbol" || overlay.has(layer.id))?.id;
  for (const layer of COVERAGE_MASK_LAYERS) map.addLayer({ ...layer }, before);
  return true;
}

/** The coverage the API serves, or null if it does not answer with one. */
export async function fetchCoverage(origin: string, get: typeof fetch = fetch): Promise<Coverage | null> {
  try {
    const response = await get(`${origin}/api/coverage`);
    if (!response.ok) return null;
    const body = (await response.json()) as Coverage;
    const ring = body?.geometry?.coordinates?.[0];
    if (body?.geometry?.type !== "Polygon" || !Array.isArray(ring) || ring.length < 4) return null;
    return body;
  } catch {
    return null;
  }
}

/** The parts of a MapLibre map the facility check uses. */
export interface FacilityMap {
  getSource(id: string): unknown;
  querySourceFeatures(
    id: string,
    options: { sourceLayer: string; filter: ["has", string] },
  ): Array<{ properties?: Record<string, unknown> | null }>;
  on(event: "idle", listener: () => void): unknown;
  off(event: "idle", listener: () => void): unknown;
}

/**
 * The bike-facility kinds the stress tiles on screen carry, among the ones the
 * legend knows. Until the routing lane's column exists the tiles carry only
 * "path", derived from the trail network (core/stress_tiles.py), so the legend
 * lists only the kinds the map has actually drawn.
 */
export function facilitiesOnMap(map: FacilityMap): Set<string> {
  const kinds = new Set<string>();
  if (!map.getSource(STRESS_SOURCE_ID)) return kinds;
  const known = new Set(FACILITIES.map((f: { facility: string }) => f.facility));
  for (const feature of map.querySourceFeatures(STRESS_SOURCE_ID, {
    sourceLayer: STRESS_TILE_LAYER,
    filter: ["has", "facility"],
  })) {
    const kind = feature.properties?.facility;
    if (typeof kind === "string" && known.has(kind)) kinds.add(kind);
  }
  return kinds;
}

/**
 * Report each time the map settles having drawn a facility kind it had not
 * drawn before, with every kind seen so far; stop once it has seen them all.
 */
export function watchForFacilities(map: FacilityMap, seen: (kinds: ReadonlySet<string>) => void): void {
  const all = new Set<string>();
  const check = () => {
    const before = all.size;
    for (const kind of facilitiesOnMap(map)) all.add(kind);
    if (all.size === before) return;
    seen(new Set(all));
    if (all.size === FACILITIES.length) map.off("idle", check);
  };
  map.on("idle", check);
}

/** The parts of a MapLibre map the zoom watch uses. */
export interface ZoomMap {
  getZoom(): number;
  on(event: "zoomend", listener: () => void): unknown;
}

/** Report the zoom now and after every change, for the legend's zoom notes. */
export function watchZoom(map: ZoomMap, zoom: (z: number) => void): void {
  zoom(map.getZoom());
  map.on("zoomend", () => zoom(map.getZoom()));
}
