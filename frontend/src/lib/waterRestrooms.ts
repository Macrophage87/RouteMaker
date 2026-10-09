/**
 * Public water and restrooms from OpenStreetMap. The owner, 2026-10-09: "OSM
 * sometimes has public water fountains and restrooms. That should be a layer,
 * especially on trailmaxxing and gravel"; then "make sure there's a distinction
 * for those who care about regular flush restrooms; and port-a-potties and
 * similar facilities. Also remote areas sometimes contain nonpotable water
 * sources. Mark them too but with a different icon than potable water. People
 * would carry filters."; and "This is likely to want to be always on, but
 * perhaps not shown at every zoom" / "On by default, removable".
 *
 * The data is amenity-data/water-restrooms.json, built from the project's
 * extract by scripts/build_water_restrooms.py (what counts is in its
 * docstring), loaded the first time the layer is shown. The layer is on by
 * default for every ride type and drawn from zoom 12 in; its switches (the
 * layer, portable and pit toilets, untreated water) are kept on this device.
 *
 * Each kind has its own shape as well as colour (lib/waterLegend.ts names
 * them), and the same points are listed in words along the planned route, so a
 * screen-reader or keyboard rider has them without the map.
 *
 * The map parts are functions of a small map interface so a test can run them
 * against a stand-in (the real map needs WebGL), like railLayer.ts and
 * federalLand.ts.
 */
import { formatDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

/** "p" drinking water; "n" untreated, to filter or treat first. */
export type WaterSource = "p" | "n";
/** "f" flush; "b" portable, pit, composting or other basic toilet; "u" type not mapped. */
export type ToiletType = "f" | "b" | "u";

export interface WaterPoint {
  /** OSM element, "n123" or "w456". */
  id: string;
  lon: number;
  lat: number;
  water?: WaterSource;
  toilet?: ToiletType;
  name?: string;
  fee?: "yes" | "no";
  wheelchair?: "yes" | "limited" | "no";
  hours?: string;
  seasonal?: string;
  bottle?: boolean;
}

export type WaterStatus = "loading" | "ready" | "unavailable";

// --- The rider's switches --------------------------------------------------

export interface WaterPrefs {
  /** The layer itself. */
  on: boolean;
  /** Portable, pit and composting toilets. */
  basic: boolean;
  /** Untreated water: springs, wells and taps not marked drinkable. */
  untreated: boolean;
}

export const WATER_PREFS_DEFAULT: WaterPrefs = { on: true, basic: true, untreated: true };
export const WATER_PREFS_KEY = "routemaker.waterLayer";

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The switches as kept on this device; the defaults when nothing is kept or storage is blocked. */
export function readWaterPrefs(store: Store | null = defaultStore()): WaterPrefs {
  try {
    const raw = store?.getItem(WATER_PREFS_KEY);
    if (!raw) return { ...WATER_PREFS_DEFAULT };
    const kept = JSON.parse(raw) as Partial<Record<keyof WaterPrefs, unknown>>;
    const flag = (key: keyof WaterPrefs) => (typeof kept?.[key] === "boolean" ? (kept[key] as boolean) : WATER_PREFS_DEFAULT[key]);
    return { on: flag("on"), basic: flag("basic"), untreated: flag("untreated") };
  } catch {
    return { ...WATER_PREFS_DEFAULT };
  }
}

/** Keep the switches on this device; whether they were kept. */
export function saveWaterPrefs(prefs: WaterPrefs, store: Store | null = defaultStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(WATER_PREFS_KEY, JSON.stringify(prefs));
    return true;
  } catch {
    return false;
  }
}

/** Whether a point is drawn and listed with these switches: for its restroom or for its water. */
export function waterVisible(p: WaterPoint, prefs: WaterPrefs): boolean {
  const toilet = p.toilet !== undefined && (p.toilet !== "b" || prefs.basic);
  const water = p.water !== undefined && (p.water !== "n" || prefs.untreated);
  return toilet || water;
}

// --- The file ------------------------------------------------------------

const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value.trim() : undefined);

/** The file's points with a place and something to say; null if it is not the file's shape. */
export function parseWaterRestrooms(value: unknown): WaterPoint[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: WaterPoint[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    const lon = raw.x;
    const lat = raw.y;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const p: WaterPoint = { id: raw.id, lon, lat };
    if (raw.w === "p" || raw.w === "n") p.water = raw.w;
    if (raw.t === "f" || raw.t === "b" || raw.t === "u") p.toilet = raw.t;
    if (!p.water && !p.toilet) continue;
    const name = text(raw.n);
    if (name) p.name = name;
    if (raw.fee === "yes" || raw.fee === "no") p.fee = raw.fee;
    if (raw.wc === "yes" || raw.wc === "limited" || raw.wc === "no") p.wheelchair = raw.wc;
    const hours = text(raw.h);
    if (hours) p.hours = hours;
    const seasonal = text(raw.s);
    if (seasonal) p.seasonal = seasonal;
    if (raw.b === 1 && p.water === "p") p.bottle = true;
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

export const WATER_LABEL: Record<WaterSource, string> = {
  p: "Drinking water",
  n: "Untreated water, filter or treat it first",
};
export const TOILET_LABEL: Record<ToiletType, string> = {
  f: "Flush restroom",
  b: "Portable or pit toilet",
  u: "Restroom, type not mapped",
};

/** What the point is, in a few words: "Flush restroom with drinking water", "Untreated water, filter or treat it first". */
export function waterKindLabel(p: WaterPoint): string {
  if (!p.toilet) return WATER_LABEL[p.water ?? "p"];
  const base = TOILET_LABEL[p.toilet];
  if (p.water === "p") return `${base}, with drinking water`;
  if (p.water === "n") return `${base}, with untreated water`;
  return base;
}

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

/** "Flush restroom, with drinking water, Peirce Mill". */
export function waterTitle(p: WaterPoint): string {
  return p.name ? `${waterKindLabel(p)}, ${p.name}` : waterKindLabel(p);
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

/** The list's count line: "3 along your route: 1 with drinking water, 1 untreated water source, 2 restrooms." */
export function waterAlongCount(items: readonly WaterAlong[]): string {
  const n = (test: (p: WaterPoint) => boolean) => items.filter((i) => test(i.point)).length;
  const drinking = n((p) => p.water === "p");
  const untreated = n((p) => p.water === "n");
  const restrooms = n((p) => p.toilet !== undefined);
  const parts = [`${drinking} with drinking water`];
  if (untreated > 0) parts.push(`${untreated} untreated water ${untreated === 1 ? "source" : "sources"}`);
  parts.push(`${restrooms} ${restrooms === 1 ? "restroom" : "restrooms"}`);
  return `${items.length} along your route: ${parts.join(", ")}.`;
}

// --- The map's layer -----------------------------------------------------

export const WATER_SOURCE_ID = "water-restrooms";
export const WATER_LAYER = "water-restrooms";
/** Drawn from street-network zoom in: further out the points would crowd the stress map. */
export const WATER_MIN_ZOOM = 12;
export const WATER_ICON_PX = 18;

/** One icon per kind the map draws: water alone by source, a restroom by type, with a drop when it has drinking water. */
export type WaterIcon = "w-p" | "w-n" | "t-f" | "t-b" | "t-u" | "t-f-w" | "t-b-w" | "t-u-w";
export const WATER_ICONS: readonly WaterIcon[] = ["w-p", "w-n", "t-f", "t-b", "t-u", "t-f-w", "t-b-w", "t-u-w"];
export const waterIconId = (icon: WaterIcon) => `water-restrooms-${icon}`;

/** The icon for a point: its restroom's when it has one (with a drop for drinking water), else its water's. */
export function waterIconOf(p: WaterPoint): WaterIcon {
  if (p.toilet) return `t-${p.toilet}${p.water === "p" ? "-w" : ""}` as WaterIcon;
  return p.water === "n" ? "w-n" : "w-p";
}

export const WATER_COLOUR = "#075ea8";
export const UNTREATED_COLOUR = "#8a4b0f";
export const RESTROOM_COLOUR = "#6d28d9";
export const BASIC_COLOUR = "#0f6b5c";
const WHITE = "#ffffff";

/** Whether (x, y) is inside a drop: a circle of radius `r` at (`cx`, `cy`) drawn up to a tip at `top`. */
function inDrop(x: number, y: number, cx: number, top: number, cy: number, r: number): boolean {
  if (Math.hypot(x - cx, y - cy) <= r) return true;
  const d = cy - top;
  // The two tangents from the tip to the circle bound the drop's upper part, down to where they touch it.
  if (y < top || y > top + (d * d - r * r) / d) return false;
  const half = Math.asin(r / d);
  return Math.abs(x - cx) <= (y - top) * Math.tan(half);
}

/**
 * The icon: drinking water a blue drop; untreated water a brown drop struck through; a flush restroom a
 * purple diamond; a portable or pit toilet a green upright box (a port-a-potty's shape); a restroom of
 * unmapped type a white diamond ringed in purple. A restroom with drinking water holds a drop. Each has
 * a white edge for the base map.
 */
export function waterIcon(icon: WaterIcon, pixelRatio = 2, cssSize = WATER_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const c = size / 2;
  const edge = 1.5 * pixelRatio;
  const white = hexToRgb(WHITE);
  if (icon === "w-p" || icon === "w-n") {
    const fill = hexToRgb(icon === "w-p" ? WATER_COLOUR : UNTREATED_COLOUR);
    const top = size * 0.02;
    const cy = size * 0.64;
    const r = size * 0.34;
    const slash = 1.1 * pixelRatio;
    return rasterise(size, pixelRatio, (x, y): Rgb | null => {
      if (!inDrop(x, y, c, top, cy, r)) return null;
      if (!inDrop(x, y, c, top + edge * 1.8, cy, r - edge)) return white;
      // Untreated: a white stroke from upper right to lower left.
      if (icon === "w-n" && Math.abs(x - c + (y - cy * 0.92)) < slash) return white;
      return fill;
    });
  }
  const type = icon[2] as ToiletType;
  const withWater = icon.endsWith("-w");
  const purple = hexToRgb(RESTROOM_COLOUR);
  const blue = hexToRgb(WATER_COLOUR);
  if (type === "b") {
    const green = hexToRgb(BASIC_COLOUR);
    const halfW = size * 0.32;
    const roof = size * 0.06;
    return rasterise(size, pixelRatio, (x, y): Rgb | null => {
      const dx = Math.abs(x - c);
      if (dx > halfW || y < roof || y > size - 0.5) return null;
      // A rounded roof, as a port-a-potty has.
      const roofY = roof + (halfW - Math.sqrt(Math.max(0, halfW * halfW - dx * dx))) * 0.35;
      if (y < roofY) return null;
      if (dx > halfW - edge || y < roofY + edge || y > size - 0.5 - edge) return white;
      if (withWater && inDrop(x, y, c, size * 0.3, size * 0.64, size * 0.15)) return white;
      return green;
    });
  }
  const half = size / 2;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const d = Math.abs(x - c) + Math.abs(y - c);
    if (d > half) return null;
    if (d > half - edge * 1.4) return white;
    const drop = withWater && inDrop(x, y, c, size * 0.24, size * 0.58, size * 0.15);
    if (type === "u") {
      // Unmapped: a ring, white inside (a blue drop when it has drinking water).
      if (d > half - edge * 1.4 - 2.2 * pixelRatio) return purple;
      return drop ? blue : white;
    }
    return drop ? white : purple;
  });
}

export interface WaterFeature {
  type: "Feature";
  properties: { id: string; icon: WaterIcon; w?: WaterSource; t?: ToiletType };
  geometry: { type: "Point"; coordinates: LonLat };
}

export function waterGeoJson(points: readonly WaterPoint[]): { type: "FeatureCollection"; features: WaterFeature[] } {
  return {
    type: "FeatureCollection",
    features: points.map((p) => {
      const properties: WaterFeature["properties"] = { id: p.id, icon: waterIconOf(p) };
      if (p.water) properties.w = p.water;
      if (p.toilet) properties.t = p.toilet;
      return { type: "Feature", properties, geometry: { type: "Point", coordinates: [p.lon, p.lat] } };
    }),
  };
}

/** The layer's filter for the switches: waterVisible, as an expression. */
export function waterFilter(prefs: WaterPrefs): unknown[] {
  const toilet = prefs.basic ? ["has", "t"] : ["all", ["has", "t"], ["!=", ["get", "t"], "b"]];
  const water = prefs.untreated ? ["has", "w"] : ["all", ["has", "w"], ["!=", ["get", "w"], "n"]];
  return ["any", toilet, water];
}

export function waterLayer(prefs: WaterPrefs = WATER_PREFS_DEFAULT, sourceId = WATER_SOURCE_ID): Record<string, unknown> {
  return {
    id: WATER_LAYER,
    type: "symbol",
    source: sourceId,
    minzoom: WATER_MIN_ZOOM,
    filter: waterFilter(prefs),
    layout: {
      "icon-image": ["concat", "water-restrooms-", ["get", "icon"]],
      "icon-size": ["interpolate", ["linear"], ["zoom"], WATER_MIN_ZOOM, 0.7, 15, 1, 18, 1.2],
      "icon-allow-overlap": true,
      // The base map's labels still place around them.
      "icon-ignore-placement": true,
      // A restroom over a water source beside it.
      "symbol-sort-key": ["case", ["has", "t"], 1, 0],
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
  setFilter(id: string, filter: unknown): void;
}

/** Add the icons, the source and the layer, once, under `beforeId` (the route's lowest layer); whether they were added. */
export function addWaterRestrooms(
  map: WaterMap,
  points: readonly WaterPoint[],
  prefs: WaterPrefs,
  pixelRatio: number,
  beforeId?: string,
): boolean {
  if (map.getSource(WATER_SOURCE_ID)) return false;
  for (const icon of WATER_ICONS) {
    if (map.hasImage(waterIconId(icon))) continue;
    const { pixelRatio: ratio, ...image } = waterIcon(icon, pixelRatio);
    map.addImage(waterIconId(icon), image, { pixelRatio: ratio });
  }
  map.addSource(WATER_SOURCE_ID, { type: "geojson", data: waterGeoJson(points) });
  const layer = waterLayer(prefs);
  map.addLayer(
    { ...layer, layout: { ...(layer.layout as object), visibility: prefs.on ? "visible" : "none" } },
    beforeId && map.getLayer(beforeId) ? beforeId : undefined,
  );
  return true;
}

/** Bring the layer in line with the switches. */
export function setWaterPrefs(map: WaterMap, prefs: WaterPrefs): void {
  if (!map.getLayer(WATER_LAYER)) return;
  map.setLayoutProperty(WATER_LAYER, "visibility", prefs.on ? "visible" : "none");
  map.setFilter(WATER_LAYER, waterFilter(prefs));
}
