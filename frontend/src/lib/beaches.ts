/**
 * The beaches and the beach path (the owner, 2026-11-23, of Southwest Florida: "you can ride your bike on the
 * beach here, but generally only adviseable in low tide below the high tide lines"; "show the beaches as bikeable
 * areas"; the tide line as "a specific beach biking path").
 *
 * The data is beach-data/beaches.json, written by scripts/build_beaches.py from the map's extract: the beaches,
 * shaded on the map, and the beach paths along their tide line (OSM's coastline, drawn at mean high water), which
 * the router rides as sand (`pipeline.beaches`). A route on one says so, with the day's low tides from the nearest
 * NOAA station (lib/tides.ts).
 *
 * The map parts are functions of a small map interface so a test can run them against a stand-in, like
 * waterRestrooms.ts.
 */
import { formatDistance } from "./format.ts";
import { clockLocale, t } from "./i18n.ts";
import type { LonLat } from "./geo.ts";
import type { LowTide } from "./tides.ts";

export interface BeachData {
  type: "FeatureCollection";
  features: BeachFeature[];
}

export type BeachFeature =
  | { type: "Feature"; properties: { kind: "beach"; name: string; osm: string }; geometry: { type: "Polygon"; coordinates: LonLat[][] } }
  | { type: "Feature"; properties: { kind: "path"; way: number }; geometry: { type: "LineString"; coordinates: LonLat[] } };

export const BEACH_SOURCE_ID = "beaches";
export const BEACH_FILL_LAYER = "beaches-fill";
export const BEACH_PATH_LAYER = "beaches-path";
export const BEACH_MIN_ZOOM = 10;
/** Sand, light enough to leave the base map's labels readable; the path a darker, dashed tide line. */
export const BEACH_FILL = "#f2d58a";
export const BEACH_PATH = "#9a6b12";
/** How near the route must run to a beach path to be on it (the two lines are drawn from the same nodes). */
export const ON_BEACH_M = 15;

const isPair = (p: unknown): p is LonLat => Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

/** The read file, keeping only the features drawn right; null when it is not beach data. */
export function parseBeaches(raw: unknown): BeachData | null {
  const data = raw as { features?: unknown } | null;
  if (!data || !Array.isArray(data.features)) return null;
  const features = data.features.filter((f): f is BeachFeature => {
    const feature = f as BeachFeature | null;
    if (!feature?.properties || !feature.geometry) return false;
    if (feature.properties.kind === "beach") {
      return feature.geometry.type === "Polygon" && Array.isArray(feature.geometry.coordinates) && feature.geometry.coordinates.every((ring) => Array.isArray(ring) && ring.length >= 4 && ring.every(isPair));
    }
    return feature.properties.kind === "path" && feature.geometry.type === "LineString" && feature.geometry.coordinates.length >= 2 && feature.geometry.coordinates.every(isPair);
  });
  return { type: "FeatureCollection", features };
}

let loading: Promise<BeachData | null> | null = null;

/** The beach file, fetched once; a failed fetch is tried again next time. */
export function loadBeaches(url: string, fetcher: typeof fetch = fetch): Promise<BeachData | null> {
  loading ??= fetcher(url)
    .then((r) => (r.ok ? r.json() : null))
    .then(parseBeaches)
    .catch(() => {
      loading = null;
      return null;
    });
  return loading;
}

const M_PER_DEG = 111_320;

function metres(a: LonLat, b: LonLat): number {
  const scale = Math.cos((((a[1] + b[1]) / 2) * Math.PI) / 180);
  return Math.hypot((a[0] - b[0]) * scale, a[1] - b[1]) * M_PER_DEG;
}

/** Distance in metres from `p` to the segment a-b. */
function toSegment(p: LonLat, a: LonLat, b: LonLat): number {
  const scale = Math.cos((p[1] * Math.PI) / 180);
  const ax = (a[0] - p[0]) * scale, ay = a[1] - p[1];
  const bx = (b[0] - p[0]) * scale, by = b[1] - p[1];
  const dx = bx - ax, dy = by - ay;
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len));
  return Math.hypot(ax + t * dx, ay + t * dy) * M_PER_DEG;
}

export interface BeachAlong {
  /** How far the route rides the beach path. */
  metres: number;
  /** Where it first comes onto it, for the nearest tide station. */
  at: LonLat;
}

/** How much of the route runs on a beach path, or null where none of it does. */
export function beachAlongRoute(line: readonly LonLat[], data: BeachData | null): BeachAlong | null {
  if (!data || line.length < 2) return null;
  const paths = data.features.filter((f) => f.properties.kind === "path").map((f) => f.geometry.coordinates as LonLat[]);
  if (!paths.length) return null;
  const bounds = paths.map((c) => {
    const xs = c.map((p) => p[0]), ys = c.map((p) => p[1]);
    const pad = ON_BEACH_M / M_PER_DEG * 2;
    return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
  });
  const onBeach = (p: LonLat) =>
    paths.some((c, i) => {
      const [w, s, e, n] = bounds[i];
      if (p[0] < w || p[0] > e || p[1] < s || p[1] > n) return false;
      for (let k = 1; k < c.length; k++) if (toSegment(p, c[k - 1], c[k]) <= ON_BEACH_M) return true;
      return false;
    });
  let total = 0;
  let first: LonLat | null = null;
  let prevOn = onBeach(line[0] as LonLat);
  for (let i = 1; i < line.length; i++) {
    const here = line[i] as LonLat;
    const on = onBeach(here);
    if (on && prevOn) {
      total += metres(line[i - 1] as LonLat, here);
      first ??= line[i - 1] as LonLat;
    }
    prevOn = on;
  }
  return total > 0 && first ? { metres: total, at: first } : null;
}

/**
 * The route note, one short line in Go and Plan: how far on the beach, and that day's low tides at the nearest station
 * (lib/tides.ts). `lows` null is no tide data for the day (the file not had, or the day outside it): the line then
 * says only to ride at low tide.
 */
export function beachNote(along: BeachAlong, lows: readonly LowTide[] | null, locale: string | undefined = clockLocale(), timeZone = "America/New_York"): string {
  const distance = formatDistance(along.metres);
  if (!lows) return t("Beach path, {distance}: ride at low tide.", { distance });
  if (lows.length === 0) return t("Beach path, {distance}: ride at low tide. No low tide that day.", { distance });
  const clock = new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit", timeZone });
  const times = new Intl.ListFormat(locale, { type: "unit", style: "short" }).format(lows.map((low) => clock.format(low.at)));
  return t("Beach path, {distance}: ride at low tide ({times}).", { distance, times });
}

/** The parts of a MapLibre map these use. */
export interface BeachMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): void;
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
}

/** The two layers: the beaches shaded, and the beach paths as a dashed tide line. */
export function beachLayers(sourceId = BEACH_SOURCE_ID): Record<string, unknown>[] {
  return [
    {
      id: BEACH_FILL_LAYER,
      type: "fill",
      source: sourceId,
      minzoom: BEACH_MIN_ZOOM,
      filter: ["==", ["get", "kind"], "beach"],
      paint: { "fill-color": BEACH_FILL, "fill-opacity": 0.45, "fill-outline-color": BEACH_PATH },
    },
    {
      id: BEACH_PATH_LAYER,
      type: "line",
      source: sourceId,
      minzoom: BEACH_MIN_ZOOM,
      filter: ["==", ["get", "kind"], "path"],
      layout: { "line-cap": "round" },
      paint: {
        "line-color": BEACH_PATH,
        "line-width": ["interpolate", ["linear"], ["zoom"], BEACH_MIN_ZOOM, 1.5, 16, 4],
        "line-dasharray": [2, 1.5],
      },
    },
  ];
}

/** Add the source and the layers, once, under `beforeId` (the route's lowest layer); whether they were added. */
export function addBeaches(map: BeachMap, data: BeachData, beforeId?: string): boolean {
  if (map.getSource(BEACH_SOURCE_ID) || data.features.length === 0) return false;
  map.addSource(BEACH_SOURCE_ID, { type: "geojson", data });
  const under = beforeId && map.getLayer(beforeId) ? beforeId : undefined;
  for (const layer of beachLayers()) map.addLayer(layer, under);
  return true;
}
