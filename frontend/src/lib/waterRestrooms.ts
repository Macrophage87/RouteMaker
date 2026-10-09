/**
 * Public drinking water and restrooms from OpenStreetMap (owner, 2026-10-09:
 * "OSM sometimes has public water fountains and restrooms. That should be a
 * layer, especially on trailmaxxing and gravel").
 *
 * The data is amenity-data/water-restrooms.json, built from the project's
 * extract by scripts/build_water_restrooms.py (what counts is in its
 * docstring), loaded only when the layer is first shown. The layer is on by
 * default for Trailmaxxing and Gravel and off for every other ride type; the
 * rider's switch overrides that, per ride type, for the visit.
 *
 * Each kind is told apart by shape as well as colour (a drop for water, a
 * diamond for a restroom, a diamond with a drop in it for both), and the same
 * points are listed in words along the planned route (waterLegend.ts), so a
 * screen-reader or keyboard rider has them without the map.
 *
 * These are functions of a small map interface so a test can run them against
 * a stand-in (the real map needs WebGL), like railLayer.ts and federalLand.ts.
 */
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export type WaterKind = "w" | "t" | "wt";
export const WATER_KINDS: readonly WaterKind[] = ["w", "t", "wt"];

export interface WaterPoint {
  /** OSM element, "n123" or "w456". */
  id: string;
  lon: number;
  lat: number;
  kind: WaterKind;
  name?: string;
  fee?: "yes" | "no";
  wheelchair?: "yes" | "limited" | "no";
  hours?: string;
  seasonal?: string;
  bottle?: boolean;
}

export type WaterStatus = "loading" | "ready" | "unavailable";

/** The ride types the layer is on for until the rider says otherwise. */
export const WATER_DEFAULT_ON: readonly PresetId[] = ["trailmaxxing", "gravel"];

/** The rider's own choices this visit, per ride type; a ride type left out follows the default. */
export type WaterChoices = Partial<Record<PresetId, boolean>>;

export function waterShown(preset: PresetId, choices: WaterChoices): boolean {
  return choices[preset] ?? WATER_DEFAULT_ON.includes(preset);
}

const isKind = (value: unknown): value is WaterKind => typeof value === "string" && (WATER_KINDS as readonly string[]).includes(value);
const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value.trim() : undefined);

/** The file's points with a kind and a place; null if it is not the file's shape. */
export function parseWaterRestrooms(value: unknown): WaterPoint[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: WaterPoint[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string" || !isKind(raw.k)) continue;
    const lon = raw.x;
    const lat = raw.y;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const p: WaterPoint = { id: raw.id, lon, lat, kind: raw.k };
    const name = text(raw.n);
    if (name) p.name = name;
    if (raw.fee === "yes" || raw.fee === "no") p.fee = raw.fee;
    if (raw.wc === "yes" || raw.wc === "limited" || raw.wc === "no") p.wheelchair = raw.wc;
    const hours = text(raw.h);
    if (hours) p.hours = hours;
    const seasonal = text(raw.s);
    if (seasonal) p.seasonal = seasonal;
    if (raw.b === 1 && p.kind !== "t") p.bottle = true;
    out.push(p);
  }
  return out;
}

/** Fetch and parse the file; null if it cannot be had or holds no points (the layer then says it is unavailable). */
export async function loadWaterRestrooms(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<WaterPoint[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    const points = parseWaterRestrooms(await response.json());
    return points && points.length > 0 ? points : null;
  } catch {
    return null;
  }
}

// --- Words ---------------------------------------------------------------

export const KIND_LABEL: Record<WaterKind, string> = {
  w: "Drinking water",
  t: "Restroom",
  wt: "Restroom with drinking water",
};

/** The point's details, each a short sentence: what the map's card and the list say after the kind. */
export function waterDetails(p: WaterPoint): string[] {
  const out: string[] = [];
  if (p.bottle) out.push("Bottle filler.");
  if (p.fee === "no") out.push("Free.");
  if (p.fee === "yes") out.push("Fee to use.");
  if (p.wheelchair === "yes") out.push("Wheelchair accessible.");
  if (p.wheelchair === "limited") out.push("Partly wheelchair accessible.");
  if (p.wheelchair === "no") out.push("Not wheelchair accessible.");
  if (p.seasonal) out.push(p.seasonal === "yes" ? "Seasonal." : `Seasonal: ${p.seasonal}.`);
  if (p.hours) out.push(p.hours === "24/7" ? "Open 24/7." : `Hours: ${p.hours}.`);
  return out;
}

/** "Restroom with drinking water, Peirce Mill comfort station". */
export function waterTitle(p: WaterPoint): string {
  return p.name ? `${KIND_LABEL[p.kind]}, ${p.name}` : KIND_LABEL[p.kind];
}

/** The standing caution: OSM is volunteers' mapping, and taps get shut off. */
export const WATER_CAUTION = "From OpenStreetMap: check it is working before you count on it.";

// --- Along the route -----------------------------------------------------

/** How far off the route a point is still "along" it: 1,000 ft (305 m), a short detour each way. */
export const ALONG_ROUTE_M = 304.8;

export interface WaterAlong {
  point: WaterPoint;
  /** Distance along the route to the nearest place on it, in metres. */
  alongM: number;
  /** Distance from that place to the point, in metres. */
  offM: number;
}

const M_PER_DEG_LAT = 111_320;

/**
 * The points within `maxOffM` of the route line, in the order the ride reaches
 * them. Each is placed at its nearest spot on the line (a flat projection,
 * plenty at these distances); a route that passes twice keeps the nearer pass.
 */
export function waterAlongRoute(line: readonly LonLat[], points: readonly WaterPoint[], maxOffM = ALONG_ROUTE_M): WaterAlong[] {
  if (line.length < 2 || points.length === 0) return [];
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lon, lat] of line) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  const lat0 = (south + north) / 2;
  const kx = M_PER_DEG_LAT * Math.cos((lat0 * Math.PI) / 180);
  const ky = M_PER_DEG_LAT;
  const padLon = maxOffM / kx;
  const padLat = maxOffM / ky;
  const xy = line.map(([lon, lat]) => [lon * kx, lat * ky] as const);
  const cumulative: number[] = [0];
  for (let i = 1; i < xy.length; i += 1) {
    cumulative.push(cumulative[i - 1] + Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]));
  }
  const out: WaterAlong[] = [];
  for (const point of points) {
    if (point.lon < west - padLon || point.lon > east + padLon || point.lat < south - padLat || point.lat > north + padLat) continue;
    const px = point.lon * kx;
    const py = point.lat * ky;
    let best = Infinity;
    let bestAlong = 0;
    for (let i = 1; i < xy.length; i += 1) {
      const [ax, ay] = xy[i - 1];
      const [bx, by] = xy[i];
      // A quick reject: the segment's box, padded, does not reach the point.
      if (px < Math.min(ax, bx) - maxOffM || px > Math.max(ax, bx) + maxOffM) continue;
      if (py < Math.min(ay, by) - maxOffM || py > Math.max(ay, by) + maxOffM) continue;
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      if (d < best) {
        best = d;
        bestAlong = cumulative[i - 1] + t * Math.sqrt(len2);
      }
    }
    if (best <= maxOffM) out.push({ point, alongM: bestAlong, offM: best });
  }
  return out.sort((a, b) => a.alongM - b.alongM || a.offM - b.offM);
}

/** Below this a point is "on the route" rather than some feet off it. */
export const ON_ROUTE_M = 15;

/**
 * One line of the list, everything in words:
 * "At 4.2 mi (6.8 km): Drinking water, Mile 4 fountain, 200 ft (61 m) off the route. Bottle filler. Free."
 */
export function waterAlongText(item: WaterAlong): string {
  const off = item.offM < ON_ROUTE_M ? "on the route" : `${formatDistance(item.offM)} off the route`;
  return [`At ${formatDistance(item.alongM)}: ${waterTitle(item.point)}, ${off}.`, ...waterDetails(item.point)].join(" ");
}

/** The list's count line: "3 along your route: 2 with drinking water, 2 restrooms." */
export function waterAlongCount(items: readonly WaterAlong[]): string {
  const water = items.filter((i) => i.point.kind !== "t").length;
  const toilets = items.filter((i) => i.point.kind !== "w").length;
  const part = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return `${items.length} along your route: ${part(water, "with drinking water", "with drinking water")}, ${part(toilets, "restroom", "restrooms")}.`;
}

// --- The map's layer -----------------------------------------------------

export const WATER_SOURCE_ID = "water-restrooms";
export const WATER_LAYER = "water-restrooms";
export const waterIconId = (kind: WaterKind) => `water-restrooms-${kind}`;
/** Drawn from street-network zoom in: further out the points would crowd the stress map. */
export const WATER_MIN_ZOOM = 12;
export const WATER_ICON_PX = 18;

export const WATER_COLOUR = "#075ea8";
export const RESTROOM_COLOUR = "#6d28d9";
const EDGE = "#ffffff";

/** Whether (x, y) is inside a drop: a circle of radius `r` at (`cx`, `cy`) drawn up to a tip at `top`. */
function inDrop(x: number, y: number, cx: number, top: number, cy: number, r: number): boolean {
  if (Math.hypot(x - cx, y - cy) <= r) return true;
  const d = cy - top;
  // The two tangents from the tip to the circle bound the drop's upper part, down to where they touch it.
  if (y < top || y > top + (d * d - r * r) / d) return false;
  const half = Math.asin(r / d);
  const across = Math.abs(x - cx);
  return across <= (y - top) * Math.tan(half);
}

/** The icon for a kind: a blue drop, a purple diamond, or a purple diamond holding a white drop. Each has a white edge. */
export function waterIcon(kind: WaterKind, pixelRatio = 2, cssSize = WATER_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const c = size / 2;
  const edge = 1.5 * pixelRatio;
  const blue = hexToRgb(WATER_COLOUR);
  const purple = hexToRgb(RESTROOM_COLOUR);
  const white = hexToRgb(EDGE);
  if (kind === "w") {
    const top = size * 0.02;
    const cy = size * 0.64;
    const r = size * 0.34;
    return rasterise(size, pixelRatio, (x, y): Rgb | null => {
      if (!inDrop(x, y, c, top, cy, r)) return null;
      return inDrop(x, y, c, top + edge * 1.8, cy, r - edge) ? blue : white;
    });
  }
  const half = size / 2;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const d = Math.abs(x - c) + Math.abs(y - c);
    if (d > half) return null;
    if (d > half - edge * 1.4) return white;
    if (kind === "wt" && inDrop(x, y, c, size * 0.24, size * 0.58, size * 0.15)) return white;
    return purple;
  });
}

export interface WaterFeature {
  type: "Feature";
  properties: { id: string; kind: WaterKind; name?: string };
  geometry: { type: "Point"; coordinates: LonLat };
}

export function waterGeoJson(points: readonly WaterPoint[]): { type: "FeatureCollection"; features: WaterFeature[] } {
  return {
    type: "FeatureCollection",
    features: points.map((p) => ({
      type: "Feature",
      properties: p.name ? { id: p.id, kind: p.kind, name: p.name } : { id: p.id, kind: p.kind },
      geometry: { type: "Point", coordinates: [p.lon, p.lat] },
    })),
  };
}

export function waterLayer(sourceId = WATER_SOURCE_ID): Record<string, unknown> {
  return {
    id: WATER_LAYER,
    type: "symbol",
    source: sourceId,
    minzoom: WATER_MIN_ZOOM,
    layout: {
      "icon-image": ["match", ["get", "kind"], ...WATER_KINDS.flatMap((k) => [k, waterIconId(k)]), waterIconId("w")],
      "icon-size": ["interpolate", ["linear"], ["zoom"], WATER_MIN_ZOOM, 0.7, 15, 1, 18, 1.2],
      "icon-allow-overlap": true,
      // The base map's labels still place around them.
      "icon-ignore-placement": true,
      // A restroom with water over a plain fountain beside it.
      "symbol-sort-key": ["match", ["get", "kind"], "wt", 2, "t", 1, 0],
    },
  };
}

/** The parts of a MapLibre map these use. */
export interface WaterMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): void;
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  hasImage(id: string): boolean;
  addImage(id: string, image: Omit<Raster, "pixelRatio">, options: { pixelRatio: number }): void;
  setLayoutProperty(id: string, name: string, value: string): void;
}

/** Add the icons, the source and the layer, once, under `beforeId` (the route's lowest layer); whether they were added. */
export function addWaterRestrooms(
  map: WaterMap,
  points: readonly WaterPoint[],
  visible: boolean,
  pixelRatio: number,
  beforeId?: string,
): boolean {
  if (map.getSource(WATER_SOURCE_ID)) return false;
  for (const kind of WATER_KINDS) {
    if (map.hasImage(waterIconId(kind))) continue;
    const { pixelRatio: ratio, ...image } = waterIcon(kind, pixelRatio);
    map.addImage(waterIconId(kind), image, { pixelRatio: ratio });
  }
  map.addSource(WATER_SOURCE_ID, { type: "geojson", data: waterGeoJson(points) });
  const layer = waterLayer();
  map.addLayer(
    { ...layer, layout: { ...(layer.layout as object), visibility: visible ? "visible" : "none" } },
    beforeId && map.getLayer(beforeId) ? beforeId : undefined,
  );
  return true;
}

export function setWaterVisibility(map: WaterMap, visible: boolean): void {
  if (map.getLayer(WATER_LAYER)) map.setLayoutProperty(WATER_LAYER, "visibility", visible ? "visible" : "none");
}
