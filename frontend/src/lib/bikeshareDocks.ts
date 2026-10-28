/**
 * Bikeshare docks and free e-bikes on the map (v0.7.0, "Bikeshare docks on the map"). The owner, 2026-10-13:
 * "If someone is on a bikeshare mode, show bikeshare docks (and free ebikes) on the map. The docks should show
 * with emojis a bike for regular, some sort of electric symbol for ebike, and the number of empty slots." And:
 * "Allow the other ebike services to also show up on the map, but only show cabi by default."
 *
 * Shown whenever its switch in Layers is on. The owner, 2026-10-17: "they only matter for rideshare modes and
 * should be turned off by default outside of it." So the switch is on by default in the Bikeshare, Bikeshare +
 * Transit and Rebalance ride types and off by default in the others, each choice kept on the device apart. From
 * GET /api/bikeshare/docks for the map's view (core.micromobility), about every minute while the page is in
 * front. Below zoom 14 the docks are count bubbles and free e-bikes are hidden; from 14 each dock is labelled
 * 🚲 5 ⚡ 2 🅿️ 3 (classic bikes, e-bikes, open docks; 0 is shown as 0). The three signs are drawn here as small
 * images (a map label cannot draw colour emoji), so they look the same on every phone. A closed dock is grey,
 * labelled "Closed". Labels that would collide are left out by the map, not crowded.
 *
 * Free e-bikes: a ⚡ in the operator's colour with its initial beside it, so colour is never the only cue. Capital
 * Bikeshare is the only service (Lime and Veo were left out, the owner 2026-10-15: neither has usable terms;
 * docs/SOURCES.md), so the Layers sheet's bikeshare section is its one switch. A service the server says is
 * licensed later gets a switch of its own there.
 *
 * The owner, 2026-10-19: "Put a white bubble around the bikeshare docks so they pop out." From zoom 14 each dock
 * and its counts sit on one white, grey-edged bubble (a stretched image behind the label, wide enough on the left
 * to hold the dot), and every dot and count bubble has a thick white ring, so they stand out from the red and
 * orange stress lines. The bubble is part of the label, so it is thinned with it and a tap on it opens the card.
 *
 * Screen readers: the map's labels are decorative; a tap gives a card in words, and the route's station list
 * says the same counts ("5 classic, 2 e-bikes, 3 open docks", lib/stations.ts).
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { CLIMB_FONT } from "./climbs.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";
import { t } from "./i18n.ts";

export interface DockInfo {
  id: string;
  name: string;
  lon: number;
  lat: number;
  /** Null when the counts are unknown. */
  classic: number | null;
  ebikes: number | null;
  docks: number | null;
  closed: boolean;
}

export interface FreeBike {
  operator: string;
  lon: number;
  lat: number;
}

export interface OperatorInfo {
  id: string;
  name: string;
  initial: string;
  colour: string;
  /** Its feed licence is recorded (docs/SOURCES.md): only then is it fetched and shown. */
  licensed: boolean;
  on_by_default: boolean;
  docked: boolean;
}

/** The answer (core.api.DocksOut). */
export interface DocksAnswer {
  availability: "live" | "stale" | "unknown" | "unavailable";
  as_of: number | null;
  docks: DockInfo[];
  free_bikes: FreeBike[];
  operators: OperatorInfo[];
  credit: string[];
}

/**
 * The operators as core.micromobility.OPERATORS lists them (tests/test_micromobility.py holds the two to the same
 * ids, names, initials and colours), for the Layers section before the server has answered. The server's
 * `licensed` wins.
 */
export const KNOWN_OPERATORS: readonly OperatorInfo[] = [
  { id: "cabi", name: "Capital Bikeshare", initial: "C", colour: "#c8102e", licensed: true, on_by_default: true, docked: true },
];

export const DOCKS_MIN_ZOOM = 11;
export const DOCK_LABELS_ZOOM = 14;
export const DOCKS_POLL_MS = 60_000;
/** The largest view the server answers (core.micromobility.MAX_SPAN_*), a hair under. */
export const MAX_SPAN_LON = 0.249;
export const MAX_SPAN_LAT = 0.199;

// --- Asking --------------------------------------------------------------------------------

export interface Bounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

/** The view to ask for: the map's, cut to the server's largest around its middle, to 4 decimals. */
export function docksBox(view: Bounds): Bounds {
  const cx = (view.west + view.east) / 2;
  const cy = (view.south + view.north) / 2;
  const halfLon = Math.min(view.east - view.west, MAX_SPAN_LON) / 2;
  const halfLat = Math.min(view.north - view.south, MAX_SPAN_LAT) / 2;
  const r = (v: number) => Math.round(v * 1e4) / 1e4;
  return { west: r(cx - halfLon), south: r(Math.max(-90, cy - halfLat)), east: r(cx + halfLon), north: r(Math.min(90, cy + halfLat)) };
}

/** The request's path, or null when there is nothing to ask (zoomed out, or every operator off). */
export function docksPath(view: Bounds, zoom: number, operators: readonly string[]): string | null {
  if (zoom < DOCKS_MIN_ZOOM || operators.length === 0) return null;
  const b = docksBox(view);
  const bbox = [b.west, b.south, b.east, b.north].join(",");
  return `/api/bikeshare/docks?bbox=${encodeURIComponent(bbox)}&operators=${encodeURIComponent(operators.join(","))}`;
}

const count = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.round(v) : null);

/** The answer, checked; null if it is not the answer's shape. */
export function parseDocks(value: unknown): DocksAnswer | null {
  const body = value as Partial<DocksAnswer> | null;
  if (!body || !Array.isArray(body.docks) || !Array.isArray(body.free_bikes) || !Array.isArray(body.operators)) return null;
  const availability = (["live", "stale", "unknown", "unavailable"] as const).find((a) => a === body.availability) ?? "unavailable";
  const docks: DockInfo[] = [];
  for (const d of body.docks as unknown as Array<Record<string, unknown>>) {
    if (!d || typeof d.id !== "string" || typeof d.lon !== "number" || typeof d.lat !== "number") continue;
    docks.push({
      id: d.id,
      name: typeof d.name === "string" && d.name.trim() ? d.name.trim() : "Bikeshare dock",
      lon: d.lon,
      lat: d.lat,
      classic: count(d.classic),
      ebikes: count(d.ebikes),
      docks: count(d.docks),
      closed: d.closed === true,
    });
  }
  const free = (body.free_bikes as unknown as Array<Record<string, unknown>>).filter(
    (f): f is Record<string, unknown> & FreeBike => !!f && typeof f.operator === "string" && typeof f.lon === "number" && typeof f.lat === "number",
  );
  const operators = (body.operators as unknown as Array<Record<string, unknown>>).filter(
    (o): o is Record<string, unknown> & OperatorInfo => !!o && typeof o.id === "string" && typeof o.name === "string" && /^#[0-9a-f]{6}$/i.test(String(o.colour)),
  );
  return {
    availability,
    as_of: typeof body.as_of === "number" ? body.as_of : null,
    docks,
    free_bikes: free.map((f) => ({ operator: f.operator, lon: f.lon, lat: f.lat })),
    operators: operators.map((o) => ({
      id: o.id,
      name: o.name,
      initial: String(o.initial ?? o.name.charAt(0)).slice(0, 1),
      colour: o.colour,
      licensed: o.licensed === true,
      on_by_default: o.on_by_default === true,
      docked: o.docked === true,
    })),
    credit: Array.isArray(body.credit) ? body.credit.filter((c): c is string => typeof c === "string") : [],
  };
}

export async function loadDocks(
  path: string,
  fetcher: (url: string, init?: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u, init) => fetch(u, init),
  signal?: AbortSignal,
): Promise<DocksAnswer | null> {
  try {
    const response = await fetcher(path, { signal, credentials: "same-origin" });
    if (!response.ok) return null;
    return parseDocks(await response.json());
  } catch {
    return null;
  }
}

// --- The rider's choices (one switch per service, kept on the device) -----------------------

/** The choice in the bikeshare ride types (on by default), and in every other ride type (off by default). */
export const OPERATORS_PREF_KEY = "routemaker.bikeshareOperators";
export const OTHER_RIDES_PREF_KEY = "routemaker.bikeshareOperators.otherRides";
type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/**
 * Each operator on or off: what was kept, else its default. In a bikeshare ride type that is the operator's own
 * (Capital Bikeshare on); in any other ride type every operator is off.
 */
export function readOperatorChoices(
  operators: readonly OperatorInfo[] = KNOWN_OPERATORS,
  store: Store | null = defaultStore(),
  bikeshareRide = true,
): Record<string, boolean> {
  let kept: Record<string, unknown> = {};
  try {
    const raw = store?.getItem(bikeshareRide ? OPERATORS_PREF_KEY : OTHER_RIDES_PREF_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) kept = parsed as Record<string, unknown>;
  } catch {
    kept = {};
  }
  return Object.fromEntries(operators.map((o) => [o.id, typeof kept[o.id] === "boolean" ? (kept[o.id] as boolean) : bikeshareRide && o.on_by_default]));
}

export function saveOperatorChoices(choices: Record<string, boolean>, store: Store | null = defaultStore(), bikeshareRide = true): void {
  try {
    store?.setItem(bikeshareRide ? OPERATORS_PREF_KEY : OTHER_RIDES_PREF_KEY, JSON.stringify(choices));
  } catch {
    // Not kept: the switches still work for this visit.
  }
}

/** The operators to ask for: switched on and licensed. */
export function operatorsToAsk(choices: Record<string, boolean>, operators: readonly OperatorInfo[]): string[] {
  return operators.filter((o) => o.licensed && choices[o.id] === true).map((o) => o.id);
}

/** The server's word on each operator over the list known here (a licence recorded since, or one more). */
export function mergeOperators(known: readonly OperatorInfo[], told: readonly OperatorInfo[] | undefined): OperatorInfo[] {
  if (!told || told.length === 0) return [...known];
  const byId = new Map(told.map((o) => [o.id, o]));
  const out = known.map((o) => byId.get(o.id) ?? o);
  for (const o of told) if (!known.some((k) => k.id === o.id)) out.push(o);
  return out;
}

// --- Words ---------------------------------------------------------------------------------

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "5 classic, 2 e-bikes, 3 open docks"; "Closed"; "Counts unknown". */
export function dockCounts(dock: Pick<DockInfo, "classic" | "ebikes" | "docks" | "closed">): string {
  if (dock.closed) return "Closed";
  if (dock.classic === null || dock.ebikes === null || dock.docks === null) return "Counts unknown";
  return `${dock.classic} classic, ${plural(dock.ebikes, "e-bike", "e-bikes")}, ${plural(dock.docks, "open dock", "open docks")}`;
}

/** "1:42 pm", the feed's time on this device's clock. */
export function asOfTime(epochSeconds: number): string {
  return new Date(epochSeconds * 1000).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

function freshness(answer: Pick<DocksAnswer, "availability" | "as_of">): string[] {
  if (answer.as_of === null) return [];
  const at = asOfTime(answer.as_of);
  return [answer.availability === "stale" ? `Counts may be out of date: as of ${at}.` : `As of ${at}.`];
}

const sourceLine = (credit: readonly string[]) => (credit.length ? [`Source: ${credit.join(" and ")} open data.`] : []);

/** A dock's card, in words. */
export function dockCard(dock: DockInfo, answer: Pick<DocksAnswer, "availability" | "as_of" | "credit">): string[] {
  return [dock.name, `${dockCounts(dock)}.`, ...freshness(answer), ...sourceLine(answer.credit)];
}

/** A free e-bike's card, in words: the operator's name, never only its colour. */
export function freeBikeCard(bike: FreeBike, operators: readonly OperatorInfo[], answer: Pick<DocksAnswer, "availability" | "as_of" | "credit">): string[] {
  const name = operators.find((o) => o.id === bike.operator)?.name ?? "Shared";
  return [`${name} e-bike`, "Not at a dock: end the ride where the operator allows.", ...freshness(answer), ...sourceLine(answer.credit)];
}

export const DOCKS_UNAVAILABLE = t("Bikeshare docks are unavailable for now; the map tries again in a minute.");
export const DOCKS_ZOOM_IN = t("Zoom in to see bikeshare docks.");
export const DOCKS_ALL_OFF = t("Bikeshare docks are off: switch them on to see the bikes.");
export const DOCKS_HINT = t("Capital Bikeshare's docks and e-bikes. On by default in the Bikeshare, Bikeshare + Transit and Rebalance ride types.");
export const DOCKS_SECTION_TITLE = t("Bikeshare and e-bikes");

/** The section's status line. */
export function docksStatus(answer: DocksAnswer | null, asked: boolean, zoom: number, anyOn: boolean): string {
  if (!anyOn) return DOCKS_ALL_OFF;
  if (zoom < DOCKS_MIN_ZOOM) return DOCKS_ZOOM_IN;
  if (asked && answer === null) return DOCKS_UNAVAILABLE;
  if (answer?.availability === "unavailable") return DOCKS_UNAVAILABLE;
  if (answer?.availability === "stale" && answer.as_of !== null) return `Counts may be out of date: as of ${asOfTime(answer.as_of)}.`;
  return "";
}

// --- The map ------------------------------------------------------------------------------

export const DOCKS_SOURCE = "bikeshare-docks";
export const FREE_SOURCE = "bikeshare-free";
export const DOCK_CLUSTERS = "bikeshare-dock-clusters";
export const DOCK_CLUSTER_COUNT = "bikeshare-dock-cluster-count";
export const DOCK_POINTS = "bikeshare-dock-points";
export const DOCK_LABELS = "bikeshare-dock-labels";
export const FREE_POINTS = "bikeshare-free-points";
export const DOCK_LAYERS = [DOCK_CLUSTERS, DOCK_CLUSTER_COUNT, DOCK_LABELS, DOCK_POINTS, FREE_POINTS] as const;

export const DOCK_COLOUR = "#c8102e";
export const CLOSED_COLOUR = "#6b7280";
export const BIKE_ICON = "dock-bike";
export const BOLT_ICON = "dock-bolt";
export const SPACE_ICON = "dock-space";
export const FREE_ICON_PREFIX = "free-bike-";
export const BUBBLE_ICON = "dock-bubble";
/** The bubble's edge, a mid grey that stands out from white roads and pale ground (WCAG 3:1 for graphics). */
export const BUBBLE_EDGE = "#6b7280";
export const DOCK_ICON_PX = 14;
export const FREE_ICON_PX = 16;
/** The label signs' fields: the bike in the dock red, the bolt amber, the open dock (P) blue. */
export const SIGN_COLOURS = { bike: DOCK_COLOUR, bolt: "#a14a00", space: "#1d4ed8" } as const;

const shown = (n: number | null) => (n === null ? "?" : String(n));

export function docksGeoJson(docks: readonly DockInfo[]): object {
  return {
    type: "FeatureCollection",
    features: docks.map((d) => ({
      type: "Feature",
      properties: { id: d.id, c: shown(d.classic), e: shown(d.ebikes), d: shown(d.docks), closed: d.closed },
      geometry: { type: "Point", coordinates: [d.lon, d.lat] },
    })),
  };
}

/** Free e-bikes; `id` is their place in the answer (the feed's own ids are never sent). */
export function freeGeoJson(bikes: readonly FreeBike[], operators: readonly OperatorInfo[]): object {
  const initials = new Map(operators.map((o) => [o.id, o.initial]));
  return {
    type: "FeatureCollection",
    features: bikes.map((b, i) => ({
      type: "Feature",
      properties: { id: String(i), op: b.operator, initial: initials.get(b.operator) ?? "" },
      geometry: { type: "Point", coordinates: [b.lon, b.lat] },
    })),
  };
}

/** The docks' source: grouped into count bubbles below zoom 14. */
export function docksSource(data: object): Record<string, unknown> {
  return { type: "geojson", data, cluster: true, clusterMaxZoom: DOCK_LABELS_ZOOM - 1, clusterRadius: 44 };
}

const isCluster = ["has", "point_count"];
const notCluster = ["!", ["has", "point_count"]];
const HALO = { "text-halo-color": "#ffffff", "text-halo-width": 1.5 };
/**
 * Around the label's box: top, right, bottom, left in CSS pixels. The label starts 0.9em (about 11 px) right of
 * the dock; the left side reaches about 12 px past the dock's centre so the dot (7 px, 10 px with its ring) sits inside.
 */
export const BUBBLE_PADDING = [3, 4, 3, 23];

/** The layers, bottom to top. */
export function docksLayers(): Array<Record<string, unknown>> {
  const sign = (icon: string, field: string) => [["image", icon], {}, ["concat", " ", ["get", field], "  "], {}];
  return [
    {
      id: DOCK_CLUSTERS,
      type: "circle",
      source: DOCKS_SOURCE,
      filter: isCluster,
      paint: {
        "circle-color": DOCK_COLOUR,
        "circle-radius": ["step", ["get", "point_count"], 12, 10, 15, 50, 19],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 3,
      },
    },
    {
      id: DOCK_CLUSTER_COUNT,
      type: "symbol",
      source: DOCKS_SOURCE,
      filter: isCluster,
      layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": [CLIMB_FONT], "text-size": 12, "text-allow-overlap": true },
      paint: { "text-color": "#ffffff" },
    },
    {
      id: DOCK_LABELS,
      type: "symbol",
      source: DOCKS_SOURCE,
      filter: notCluster,
      minzoom: DOCK_LABELS_ZOOM,
      layout: {
        "text-field": ["case", ["get", "closed"], ["format", "Closed", {}], ["format", ...sign(BIKE_ICON, "c"), ...sign(BOLT_ICON, "e"), ...sign(SPACE_ICON, "d")]],
        "text-font": [CLIMB_FONT],
        "text-size": 12,
        "text-anchor": "left",
        "text-offset": [0.9, 0],
        // The white bubble behind the counts, reaching left under the dot (drawn above it).
        "icon-image": BUBBLE_ICON,
        "icon-text-fit": "both",
        "icon-text-fit-padding": BUBBLE_PADDING,
        // Colliding labels are left out with their bubble (the dot stays), so the map is never crowded.
        "text-allow-overlap": false,
        "icon-allow-overlap": false,
      },
      // No halo: the bubble behind the counts is white already.
      paint: { "text-color": ["case", ["get", "closed"], CLOSED_COLOUR, "#111827"] },
    },
    {
      id: DOCK_POINTS,
      type: "circle",
      source: DOCKS_SOURCE,
      filter: notCluster,
      paint: {
        "circle-color": ["case", ["get", "closed"], CLOSED_COLOUR, DOCK_COLOUR],
        "circle-radius": ["interpolate", ["linear"], ["zoom"], DOCKS_MIN_ZOOM, 4, 16, 7],
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 3,
      },
    },
    {
      id: FREE_POINTS,
      type: "symbol",
      source: FREE_SOURCE,
      minzoom: DOCK_LABELS_ZOOM,
      layout: {
        "icon-image": ["concat", FREE_ICON_PREFIX, ["get", "op"]],
        "icon-allow-overlap": true,
        "text-field": ["get", "initial"],
        "text-font": [CLIMB_FONT],
        "text-size": 11,
        "text-anchor": "left",
        "text-offset": [0.8, 0],
        "text-optional": true,
      },
      paint: { "text-color": "#111827", ...HALO },
    },
  ];
}

// --- The signs, drawn pixel by pixel (lib/stationIcons.ts) ------------------------------------

type Pt = [number, number];

function nearSegment(x: number, y: number, a: Pt, b: Pt, width: number): boolean {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy)) <= width / 2;
}

function inPolygon(x: number, y: number, poly: readonly Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i, i += 1) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** A unit-square glyph test, x and y from 0 to 1. */
export type Glyph = (x: number, y: number) => boolean;

export const bikeGlyph: Glyph = (x, y) => {
  const ring = (cx: number, cy: number) => {
    const d = Math.hypot(x - cx, y - cy);
    return d <= 0.19 && d >= 0.12;
  };
  const w = 0.08;
  const rear: Pt = [0.27, 0.64];
  const front: Pt = [0.73, 0.64];
  const crank: Pt = [0.48, 0.64];
  const seat: Pt = [0.4, 0.36];
  const bar: Pt = [0.64, 0.33];
  return (
    ring(rear[0], rear[1]) ||
    ring(front[0], front[1]) ||
    nearSegment(x, y, rear, seat, w) ||
    nearSegment(x, y, seat, crank, w) ||
    nearSegment(x, y, rear, crank, w) ||
    nearSegment(x, y, seat, [0.62, 0.4], w) ||
    nearSegment(x, y, crank, [0.62, 0.4], w) ||
    nearSegment(x, y, bar, front, w)
  );
};

export const boltGlyph: Glyph = (x, y) =>
  inPolygon(x, y, [
    [0.6, 0.1],
    [0.26, 0.56],
    [0.47, 0.56],
    [0.38, 0.9],
    [0.74, 0.42],
    [0.53, 0.42],
  ]);

export const spaceGlyph: Glyph = (x, y) => {
  const stem = x >= 0.3 && x <= 0.43 && y >= 0.18 && y <= 0.82;
  const d = Math.hypot((x - 0.5) / 1.05, y - 0.37);
  const bowl = x >= 0.36 && d <= 0.2 && d >= 0.08;
  const bars = x >= 0.3 && x <= 0.52 && ((y >= 0.17 && y <= 0.29) || (y >= 0.45 && y <= 0.57));
  return stem || bowl || bars;
};

/** A rounded square in `fill` with the glyph in white. */
export function signIcon(glyph: Glyph, fill: string, pixelRatio = 2, cssSize = DOCK_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const field = hexToRgb(fill);
  const white = hexToRgb("#ffffff");
  const radius = size * 0.22;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const cx = Math.min(Math.max(x, radius), size - radius);
    const cy = Math.min(Math.max(y, radius), size - radius);
    if (Math.hypot(x - cx, y - cy) > radius) return null;
    return glyph(x / size, y / size) ? white : field;
  });
}

/** A free e-bike: a circle in the operator's colour, white-edged, with a white bolt. */
export function freeBikeIcon(colour: string, pixelRatio = 2, cssSize = FREE_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const field = hexToRgb(colour);
  const white = hexToRgb("#ffffff");
  const r = size / 2;
  const edge = 1.5 * pixelRatio;
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const d = Math.hypot(x - r, y - r);
    if (d > r) return null;
    if (d > r - edge) return white;
    const inner = (r - edge) * 2;
    const ox = (x - edge) / inner;
    const oy = (y - edge) / inner;
    return boltGlyph(0.5 + (ox - 0.5) * 1.15, 0.5 + (oy - 0.5) * 1.15) ? white : field;
  });
}

/** The dock's bubble: 4 px corners and a 1 px grey edge on white, stretched by the map along its middle. */
export const BUBBLE_PX = 12;
export function bubbleIcon(pixelRatio = 2): Raster & { stretchX: Array<[number, number]>; stretchY: Array<[number, number]> } {
  const size = Math.round(BUBBLE_PX * pixelRatio);
  const radius = 4 * pixelRatio;
  const edge = pixelRatio;
  const white = hexToRgb("#ffffff");
  const grey = hexToRgb(BUBBLE_EDGE);
  const raster = rasterise(size, pixelRatio, (x, y): Rgb | null => {
    const cx = Math.min(Math.max(x, radius), size - radius);
    const cy = Math.min(Math.max(y, radius), size - radius);
    const d = Math.hypot(x - cx, y - cy);
    if (d > radius) return null;
    return d > radius - edge || x < edge || y < edge || x > size - edge || y > size - edge ? grey : white;
  });
  const middle: Array<[number, number]> = [[radius, size - radius]];
  return { ...raster, stretchX: middle, stretchY: middle };
}

/** Every image the layers name, by id. */
export function docksImages(operators: readonly OperatorInfo[], pixelRatio = 2): Array<[string, Raster & Partial<Pick<ReturnType<typeof bubbleIcon>, "stretchX" | "stretchY">>]> {
  return [
    [BIKE_ICON, signIcon(bikeGlyph, SIGN_COLOURS.bike, pixelRatio)],
    [BOLT_ICON, signIcon(boltGlyph, SIGN_COLOURS.bolt, pixelRatio)],
    [SPACE_ICON, signIcon(spaceGlyph, SIGN_COLOURS.space, pixelRatio)],
    [BUBBLE_ICON, bubbleIcon(pixelRatio)],
    ...operators.map((o): [string, Raster] => [`${FREE_ICON_PREFIX}${o.id}`, freeBikeIcon(o.colour, pixelRatio)]),
  ];
}
