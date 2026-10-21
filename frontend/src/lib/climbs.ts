/**
 * The Climbs map layer (OWNER-DECISIONS 454: "Three map layers for everyone (every mode, signed
 * out too), off until clicked on: topo lines, climbs, mountain-bike trails"; docs/MTB-TOPO-PLAN.md,
 * slice 5). Every categorised climb on the network, on the owner's scale (PLAN.md, "Climbs layer";
 * `routemaker.climb_categories`): score = length (m) x average grade (%), Cat 5 over 4,000, Cat 4
 * over 8,000, Cat 3 over 16,000, Cat 2 over 32,000, Cat 1 over 64,000, HC over 80,000; at least
 * 500 m at 1%; nothing under Cat 5 ("Uncategorized is not a hill").
 *
 * The owner, 2026-10-11: "the top of the climb be the number, but the shape at the top should vary
 * by grade." So each climb has a marker at its summit with its category ("5" to "1", "HC") inside
 * a shape set by its average grade: a circle under 4%, a square from 4% to 7.9%, a diamond from 8%.
 * The shape, not a colour, carries the grade; every marker is the same colour. Its line, start to
 * summit, is drawn from zoom 12. The climbs the planned route rides are listed in words under the
 * route ("Category 3 climb, 2.1 miles (3.4 km) at 4.6%"), so nothing here is map-only.
 *
 * The data is climb-data/climbs.json, written on the build host by `manage.py build_climbs`
 * (`pipeline.climb_layer`), loaded the first time the layer is shown. As waterRestrooms.ts, the
 * map parts are functions of a small map interface so a test can run them against a stand-in.
 */
import { EXCLUDED_CLIMB_IDS } from "./climbExclusions.ts";
import { formatClimb, formatDistance, formatFeet, formatMilesSpelled } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";

export type ClimbCategory = "5" | "4" | "3" | "2" | "1" | "HC";
export const CLIMB_CATEGORIES: readonly ClimbCategory[] = ["HC", "1", "2", "3", "4", "5"];
export type ClimbShape = "circle" | "square" | "diamond";
export const CLIMB_SHAPES: readonly ClimbShape[] = ["circle", "square", "diamond"];

export interface Climb {
  id: string;
  category: ClimbCategory;
  /** Length, metres. */
  lengthM: number;
  /** Net gain, metres. */
  gainM: number;
  /** Average grade, percent to a tenth. */
  gradePct: number;
  /** The summit. */
  lon: number;
  lat: number;
  /** Start to summit. */
  line: LonLat[];
  unpaved?: boolean;
  name?: string;
  /** What most of it is ridden on (the file's `s`); a road where absent. */
  surface?: ClimbSurface;
  /** Most of it on roads rated LTS 3 or higher (the file's `b`). */
  busy?: boolean;
}

/**
 * The climb's colour by what it is ridden on (the owner, 2026-10-19: "color the climbs by surface: road, gravel,
 * mtb, etc" and "a different color for traffic free paved climbs"), from the file's `s` (pipeline.climb_layer
 * surface_class). Each is dark enough for the white number over it (4.5:1 or more) and none is a stress tier's
 * colour; the shape still carries the steepness, and the card and the list say the surface in words.
 */
export type ClimbSurface = "road" | "path" | "gravel" | "mtb";
export const CLIMB_SURFACES: ReadonlyArray<{ surface: ClimbSurface; code: string | null; colour: string; label: string; words: string }> = [
  { surface: "road", code: null, colour: "#9d174d", label: "Road", words: "On roads." },
  { surface: "path", code: "p", colour: "#0f766e", label: "Paved path, no traffic", words: "On a paved traffic-free path." },
  { surface: "gravel", code: "g", colour: "#8a4b08", label: "Gravel or dirt", words: "Mostly gravel or dirt." },
  { surface: "mtb", code: "m", colour: "#5b21b6", label: "Mountain-bike trail", words: "On a mountain-bike trail." },
];
const SURFACE_BY_CODE = new Map(CLIMB_SURFACES.filter((s) => s.code).map((s) => [s.code as string, s.surface]));
export const climbSurfaceOf = (c: Pick<Climb, "surface">): ClimbSurface => c.surface ?? "road";
export const climbSurfaceColour = (surface: ClimbSurface): string => CLIMB_SURFACES.find((s) => s.surface === surface)!.colour;

export type ClimbsStatus = "loading" | "ready" | "empty" | "unavailable";

// --- The owner's scale, as the file carries it ----------------------------------

/** The marker's shape by average grade (percent, to a tenth): circle under 4, square 4 to 7.9, diamond 8 and up. */
export const SQUARE_FROM_PCT = 4;
export const DIAMOND_FROM_PCT = 8;

export function climbShape(gradePct: number): ClimbShape {
  if (gradePct >= DIAMOND_FROM_PCT) return "diamond";
  if (gradePct >= SQUARE_FROM_PCT) return "square";
  return "circle";
}

// --- The rider's switch ----------------------------------------------------------

export const CLIMBS_KEY = "routemaker.climbs";

type Store = Pick<Storage, "getItem" | "setItem">;

function defaultStore(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Off unless the rider turned it on on this device (454: "off until clicked on"). */
export function readClimbsOn(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(CLIMBS_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveClimbsOn(on: boolean, store: Store | null = defaultStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(CLIMBS_KEY, on ? "1" : "0");
    return true;
  } catch {
    return false;
  }
}

/**
 * "Show climbs from" (the owner, 2026-10-12: "let people pick the minimum level to count for climbing on
 * the map"): the smallest category the layer shows, the list and the keyboard's way to a climb included.
 * Category 4 and up unless the rider chose another on this device (the owner, 2026-10-19: "Make the default
 * climb filter at 4. 5 is too numerous"; it was 5, every climb).
 */
export const CLIMBS_FROM_KEY = "routemaker.climbsFrom";
export const CLIMBS_FROM_DEFAULT: ClimbCategory = "4";

export function readClimbsFrom(store: Store | null = defaultStore()): ClimbCategory {
  try {
    const kept = store?.getItem(CLIMBS_FROM_KEY) as ClimbCategory | null | undefined;
    return kept && CLIMB_CATEGORIES.includes(kept) ? kept : CLIMBS_FROM_DEFAULT;
  } catch {
    return CLIMBS_FROM_DEFAULT;
  }
}

export function saveClimbsFrom(from: ClimbCategory, store: Store | null = defaultStore()): boolean {
  try {
    if (!store) return false;
    store.setItem(CLIMBS_FROM_KEY, from);
    return true;
  } catch {
    return false;
  }
}

/** HC ranks 0, Category 5 ranks 5: the order the markers are sorted in. */
export const climbRank = (category: ClimbCategory): number => CLIMB_CATEGORIES.indexOf(category);

/**
 * "Hide climbs on busy roads" (the owner, 2026-10-19: "optionally (default on) hide climbs on LTS 3+ roads"):
 * on unless the rider turned it off on this device. One value for the page, read by the map, the list and the
 * road panel through climbShown and climbsFilter, as the trail layer's switch is (stressStyle.js).
 */
export const CLIMBS_HIDE_BUSY_KEY = "routemaker.climbsHideBusy";

export function readHideBusy(store: Store | null = defaultStore()): boolean {
  try {
    return store?.getItem(CLIMBS_HIDE_BUSY_KEY) !== "off";
  } catch {
    return true;
  }
}

let hideBusy = readHideBusy();
const hideBusyListeners = new Set<() => void>();

export function hideBusyClimbs(): boolean {
  return hideBusy;
}

export function setHideBusyClimbs(on: boolean, store: Store | null = defaultStore()): void {
  try {
    store?.setItem(CLIMBS_HIDE_BUSY_KEY, on ? "on" : "off");
  } catch {
    // Kept for this visit only.
  }
  if (on === hideBusy) return;
  hideBusy = on;
  for (const listener of [...hideBusyListeners]) listener();
}

export function subscribeHideBusy(listener: () => void): () => void {
  hideBusyListeners.add(listener);
  return () => void hideBusyListeners.delete(listener);
}

/**
 * Whether climbs mostly on mountain-bike trails show: only while the map draws those trails (their layer on, or the
 * Mountain Bike ride type), so a road ride type's map shows no climb on a trail its routes do not use. MapView sets
 * it; a change reaches the same listeners as the busy-road switch.
 */
let trailClimbsShown = false;

export function trailClimbs(): boolean {
  return trailClimbsShown;
}

export function setTrailClimbs(on: boolean): void {
  if (on === trailClimbsShown) return;
  trailClimbsShown = on;
  for (const listener of [...hideBusyListeners]) listener();
}

/**
 * Whether a climb is shown with "Show climbs from" at `from`: that category or a harder one, and, while busy
 * roads' climbs are hidden, not one mostly on LTS 3 or higher.
 */
export function climbShown(
  c: Pick<Climb, "category" | "busy" | "surface">,
  from: ClimbCategory,
  hidingBusy: boolean = hideBusy,
  trails: boolean = trailClimbsShown,
): boolean {
  return climbRank(c.category) <= climbRank(from) && !(hidingBusy && c.busy === true) && (trails || c.surface !== "mtb");
}

/** The map's filter for both layers: the same rule as climbShown, on each feature's rank, `b` and `s`. */
export function climbsFilter(from: ClimbCategory, hidingBusy: boolean = hideBusy, trails: boolean = trailClimbsShown): unknown[] {
  const rank = ["<=", ["get", "rank"], climbRank(from)];
  const hides = [...(hidingBusy ? [["!=", ["get", "b"], true]] : []), ...(trails ? [] : [["!=", ["get", "s"], "mtb"]])];
  return hides.length > 0 ? ["all", rank, ...hides] : rank;
}

// --- The file --------------------------------------------------------------------

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function lonLat(value: unknown): LonLat | null {
  return Array.isArray(value) && value.length >= 2 && finite(value[0]) && finite(value[1]) ? [value[0], value[1]] : null;
}

/** The file's climbs, each checked against the scale's floor; null if it is not the file's shape. */
export function parseClimbs(value: unknown): Climb[] | null {
  const body = value as { climbs?: unknown } | null;
  if (!body || !Array.isArray(body.climbs)) return null;
  const out: Climb[] = [];
  for (const raw of body.climbs as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    // Taken off by hand: not a public way open to bikes (lib/climbExclusions.ts).
    if (EXCLUDED_CLIMB_IDS.has(raw.id)) continue;
    const category = raw.c as ClimbCategory;
    if (!CLIMB_CATEGORIES.includes(category)) continue;
    if (!finite(raw.l) || !finite(raw.r) || !finite(raw.g) || !finite(raw.x) || !finite(raw.y)) continue;
    if (raw.l < 500 || raw.g < 1) continue;
    const line = Array.isArray(raw.line) ? raw.line.map(lonLat).filter((p): p is LonLat => p !== null) : [];
    if (line.length < 2) continue;
    const climb: Climb = { id: raw.id, category, lengthM: raw.l, gainM: raw.r, gradePct: raw.g, lon: raw.x, lat: raw.y, line };
    if (raw.u === 1) climb.unpaved = true;
    if (typeof raw.n === "string" && raw.n.trim()) climb.name = raw.n.trim();
    const surface = typeof raw.s === "string" ? SURFACE_BY_CODE.get(raw.s) : undefined;
    if (surface) climb.surface = surface;
    if (raw.b === 1) climb.busy = true;
    out.push(climb);
  }
  return out;
}

/** Fetch and parse the file: the climbs (empty before the build host has written any), or null when it cannot be had. */
export async function loadClimbs(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<Climb[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parseClimbs(await response.json());
  } catch {
    return null;
  }
}

// --- Words -----------------------------------------------------------------------

/** "Category 3", or "Hors catégorie (HC)" spelled out, as a screen reader would otherwise read "H C". */
export function categoryName(category: ClimbCategory): string {
  return category === "HC" ? "Hors catégorie (HC)" : `Category ${category}`;
}

/** The climb's length in words, miles first: "2.1 miles (3.4 km)", "1.0 mile (1.6 km)" (format.ts). */
export const climbLength = formatMilesSpelled;

/** The accessible name, as the owner's example: "Category 3 climb, 2.1 miles (3.4 km) at 4.6%". */
export function climbLabel(c: Pick<Climb, "category" | "lengthM" | "gradePct">): string {
  return `${categoryName(c.category)} climb, ${climbLength(c.lengthM)} at ${c.gradePct.toFixed(1)}%`;
}

/** The shape in words, so the cue is never the picture alone. */
export const SHAPE_WORDS: Record<ClimbShape, string> = {
  circle: "circle, under 4% average",
  square: "square, 4% to 7.9% average",
  diamond: "diamond, 8% or steeper average",
};

/**
 * The shape's meaning, short, for the climb card beside the shape itself (the owner, 2026-10-12: "Also
 * note that the icon means steepness on the map"): the same three bands as the legend.
 */
export const SHAPE_STEEPNESS: Record<ClimbShape, string> = {
  circle: "Gentle: under 4%",
  square: "Moderate: 4 to 7.9%",
  diamond: "Steep: 8% or more",
};

/**
 * The accessible name with the climb's own name in front, where the file has one (the owner, 2026-10-19: "have
 * them named, by a combination of road names and mountain names"; pipeline.climb_names): "Foxville Road up
 * Catoctin Mountain, Category 2 climb, 7.5 miles (12.1 km) at 3.0%".
 */
export function climbNamedLabel(c: Pick<Climb, "name" | "category" | "lengthM" | "gradePct">): string {
  return c.name ? `${c.name}, ${climbLabel(c)}` : climbLabel(c);
}

/** The details after the name: the gain, the surface, the roads' stress. */
export function climbDetails(c: Climb): string[] {
  const out = [`${formatClimb(c.gainM)} gained.`];
  // Its surface in words, so the colour is never the only cue; a file before `s` has only `u`.
  if (c.surface) out.push(CLIMB_SURFACES.find((s) => s.surface === c.surface)!.words);
  else if (c.unpaved) out.push("Mostly unpaved.");
  if (c.busy) out.push("Mostly on busy roads (LTS 3 or higher).");
  return out;
}

/** What the map's card says (climbInteraction.ts draws it). */
export function climbCard(c: Climb): { title: string; details: string[]; caution: string } {
  return { title: climbNamedLabel(c), details: climbDetails(c), caution: CLIMB_CAUTION };
}

export const CLIMB_CAUTION = `Measured from elevation data sampled about every ${formatFeet(30.48)}: short pitches may be steeper than the average.`;

// --- Along the route -------------------------------------------------------------

/** How close the route must pass every point of a climb's line to ride it: 165 ft (50 m), a road's width and the line's simplification. */
export const ON_CLIMB_M = 50;

export interface ClimbAlong {
  climb: Climb;
  /** Distance along the route to the climb's start, metres. */
  startM: number;
  /** Distance along the route to its summit, metres. */
  summitM: number;
}

const M_PER_DEG_LAT = 111_320;

/**
 * The climbs the route rides uphill, in the order it reaches them: each point of the climb's line,
 * start to summit, must be within ON_CLIMB_M of the route, each further along the route than the
 * one before (so a descent of the same road does not count), and the stretch of route between its
 * start and summit about as long as the climb (0.8 to 1.3 times; a route that leaves and comes back
 * does not ride it).
 */
export function climbsAlongRoute(line: readonly LonLat[], climbs: readonly Climb[], tolM = ON_CLIMB_M): ClimbAlong[] {
  if (line.length < 2 || climbs.length === 0) return [];
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
  const padLon = tolM / kx;
  const padLat = tolM / ky;
  const xy = line.map(([lon, lat]) => [lon * kx, lat * ky] as const);
  const cumulative: number[] = [0];
  for (let i = 1; i < xy.length; i += 1) {
    cumulative.push(cumulative[i - 1] + Math.hypot(xy[i][0] - xy[i - 1][0], xy[i][1] - xy[i - 1][1]));
  }
  const inBox = ([lon, lat]: LonLat) => lon >= west - padLon && lon <= east + padLon && lat >= south - padLat && lat <= north + padLat;

  /** The first place on the route at or after `fromM` within tolM of the point, or null. */
  const firstNear = (point: LonLat, fromSegment: number, fromM: number): { segment: number; along: number } | null => {
    const px = point[0] * kx;
    const py = point[1] * ky;
    for (let i = Math.max(1, fromSegment); i < xy.length; i += 1) {
      const [ax, ay] = xy[i - 1];
      const [bx, by] = xy[i];
      if (px < Math.min(ax, bx) - tolM || px > Math.max(ax, bx) + tolM) continue;
      if (py < Math.min(ay, by) - tolM || py > Math.max(ay, by) + tolM) continue;
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      if (Math.hypot(px - (ax + t * dx), py - (ay + t * dy)) > tolM) continue;
      const along = cumulative[i - 1] + t * Math.sqrt(len2);
      // On the segment where the last point was matched, not behind it.
      if (along + 1e-6 < fromM) continue;
      return { segment: i, along };
    }
    return null;
  };

  /** The last place on the route at or before `toM` within tolM of the point, or null. */
  const lastNear = (point: LonLat, toSegment: number, toM: number): { segment: number; along: number } | null => {
    const px = point[0] * kx;
    const py = point[1] * ky;
    for (let i = Math.min(toSegment, xy.length - 1); i >= 1; i -= 1) {
      const [ax, ay] = xy[i - 1];
      const [bx, by] = xy[i];
      if (px < Math.min(ax, bx) - tolM || px > Math.max(ax, bx) + tolM) continue;
      if (py < Math.min(ay, by) - tolM || py > Math.max(ay, by) + tolM) continue;
      const dx = bx - ax;
      const dy = by - ay;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      if (Math.hypot(px - (ax + t * dx), py - (ay + t * dy)) > tolM) continue;
      const along = cumulative[i - 1] + t * Math.sqrt(len2);
      if (along > toM + 1e-6) continue;
      return { segment: i, along };
    }
    return null;
  };

  const out: ClimbAlong[] = [];
  for (const climb of climbs) {
    if (!inBox(climb.line[0]) || !inBox(climb.line[climb.line.length - 1])) continue;
    // Forward: the first time the route reaches each point in turn, which finds where it reaches the summit.
    let segment = 1;
    let along = 0;
    const hits: Array<{ segment: number; along: number }> = [];
    for (const point of climb.line) {
      const hit = firstNear(point, segment, along);
      if (!hit) break;
      hits.push(hit);
      segment = hit.segment;
      along = hit.along;
    }
    if (hits.length < climb.line.length) continue;
    // Back from the summit: the last time before it that the route passed each point, so an
    // out-and-back that rolls down the climb first starts the climb at the turn, not at the top.
    let start = hits[hits.length - 1];
    for (let k = climb.line.length - 2; k >= 0; k -= 1) {
      const hit = lastNear(climb.line[k], start.segment, start.along);
      if (!hit) break;
      start = hit;
    }
    const startM = start.along;
    const ridden = along - startM;
    if (ridden < 0.8 * climb.lengthM || ridden > 1.3 * climb.lengthM) continue;
    out.push({ climb, startM, summitM: along });
  }
  return out.sort((a, b) => a.startM - b.startM);
}

/** One line of the list: "At 4.2 mi (6.8 km): Snider Lane, Category 4 climb, 1.3 miles (2.1 km) at 4.6%. 318 ft (97 m) gained." */
export function climbAlongText(item: ClimbAlong): string {
  return [`At ${formatDistance(item.startM)}: ${climbNamedLabel(item.climb)}.`, ...climbDetails(item.climb)].join(" ");
}

/** The list's count line: "2 climbs on your route: 1 Category 4, 1 Category 5." */
export function climbAlongCount(items: readonly ClimbAlong[]): string {
  const parts = CLIMB_CATEGORIES.map((category) => [category, items.filter((i) => i.climb.category === category).length] as const)
    .filter(([, n]) => n > 0)
    .map(([category, n]) => `${n} ${categoryName(category)}`);
  return `${items.length} ${items.length === 1 ? "climb" : "climbs"} on your route: ${parts.join(", ")}.`;
}

// --- The map's layers ------------------------------------------------------------

export const CLIMBS_SOURCE_ID = "climbs";
export const CLIMBS_LINE_SOURCE_ID = "climbs-lines";
export const CLIMBS_LINE_LAYER = "climbs-line";
export const CLIMBS_MARKER_LAYER = "climbs-summit";
export const CLIMBS_LAYERS = [CLIMBS_LINE_LAYER, CLIMBS_MARKER_LAYER] as const;
/** Summits from zoom 9 (the region's climbs are few and far between); lines from street-network zoom. */
export const CLIMBS_MIN_ZOOM = 9;
export const CLIMBS_LINE_MIN_ZOOM = 12;
export const CLIMB_ICON_PX = 24;
/** The road climbs' colour, and the one the legend's number and line samples use (CLIMB_SURFACES has the rest). */
export const CLIMB_COLOUR = "#9d174d";
const WHITE = "#ffffff";
export const climbIconId = (shape: ClimbShape, surface: ClimbSurface = "road") => `climb-${shape}-${surface}`;
/** The base map's glyphs include this face (scripts/fetch_basemap.sh), as railLayer.ts's labels use. */
export const CLIMB_FONT = "Noto Sans Medium";

/** Whether (x, y), from the icon's centre, is inside the shape of half-size `r`. */
export function inShape(shape: ClimbShape, x: number, y: number, r: number): boolean {
  if (shape === "circle") return Math.hypot(x, y) <= r;
  if (shape === "square") return Math.abs(x) <= r * 0.86 && Math.abs(y) <= r * 0.86;
  return Math.abs(x) + Math.abs(y) <= r * 1.12;
}

/** The marker's shape: filled in its surface's colour inside a white edge; the number is drawn over it as text. */
export function climbIcon(shape: ClimbShape, pixelRatio = 2, cssSize = CLIMB_ICON_PX, surface: ClimbSurface = "road"): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const c = size / 2;
  const r = size / 2 - 0.5;
  const edge = 1.5 * pixelRatio;
  const fill: Rgb = hexToRgb(climbSurfaceColour(surface));
  const white: Rgb = hexToRgb(WHITE);
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    if (!inShape(shape, x - c, y - c, r)) return null;
    return inShape(shape, x - c, y - c, r - edge) ? fill : white;
  });
}

export interface ClimbSummitFeature {
  type: "Feature";
  properties: { id: string; c: ClimbCategory; shape: ClimbShape; rank: number; label: string; s: ClimbSurface; b: boolean };
  geometry: { type: "Point"; coordinates: LonLat };
}

export function climbSummits(climbs: readonly Climb[]): { type: "FeatureCollection"; features: ClimbSummitFeature[] } {
  return {
    type: "FeatureCollection",
    features: climbs.map((c) => ({
      type: "Feature",
      properties: { id: c.id, c: c.category, shape: climbShape(c.gradePct), rank: CLIMB_CATEGORIES.indexOf(c.category), label: climbNamedLabel(c), s: climbSurfaceOf(c), b: c.busy === true },
      geometry: { type: "Point", coordinates: [c.lon, c.lat] },
    })),
  };
}

export function climbLines(climbs: readonly Climb[]) {
  return {
    type: "FeatureCollection" as const,
    features: climbs.map((c) => ({
      type: "Feature" as const,
      properties: { id: c.id, c: c.category, rank: climbRank(c.category), s: climbSurfaceOf(c), b: c.busy === true },
      geometry: { type: "LineString" as const, coordinates: c.line },
    })),
  };
}

export function climbLineLayer(): Record<string, unknown> {
  return {
    id: CLIMBS_LINE_LAYER,
    type: "line",
    source: CLIMBS_LINE_SOURCE_ID,
    minzoom: CLIMBS_LINE_MIN_ZOOM,
    layout: { "line-join": "round", "line-cap": "butt" },
    // Dashed, so the climb's line is never read as one more stress tier (every tier is solid).
    paint: {
      "line-color": ["match", ["get", "s"], ...CLIMB_SURFACES.filter((s) => s.surface !== "road").flatMap((s) => [s.surface, s.colour]), CLIMB_COLOUR],
      "line-width": ["interpolate", ["linear"], ["zoom"], CLIMBS_LINE_MIN_ZOOM, 3, 16, 5],
      "line-opacity": 0.85,
      "line-dasharray": [1, 1],
    },
  };
}

export function climbMarkerLayer(): Record<string, unknown> {
  return {
    id: CLIMBS_MARKER_LAYER,
    type: "symbol",
    source: CLIMBS_SOURCE_ID,
    minzoom: CLIMBS_MIN_ZOOM,
    layout: {
      "icon-image": ["concat", "climb-", ["get", "shape"], "-", ["get", "s"]],
      "icon-size": ["interpolate", ["linear"], ["zoom"], CLIMBS_MIN_ZOOM, 0.8, 14, 1],
      "text-field": ["get", "c"],
      "text-font": [CLIMB_FONT],
      "text-size": ["interpolate", ["linear"], ["zoom"], CLIMBS_MIN_ZOOM, 9, 14, 11],
      "text-allow-overlap": true,
      "icon-allow-overlap": false,
      // The bigger climb wins where two summits meet (HC ranks 0); the list has them all.
      "symbol-sort-key": ["get", "rank"],
    },
    paint: { "text-color": WHITE },
  };
}

/** The parts of a MapLibre map these use. */
export interface ClimbsMap {
  getSource(id: string): unknown;
  addSource(id: string, source: { type: "geojson"; data: unknown }): void;
  addLayer(layer: object, beforeId?: string): void;
  getLayer(id: string): unknown;
  hasImage(id: string): boolean;
  addImage(id: string, image: Omit<Raster, "pixelRatio">, options: { pixelRatio: number }): void;
  setLayoutProperty(id: string, name: string, value: unknown): void;
  setFilter?(id: string, filter: unknown): void;
}

/** Add the icons, the sources and the two layers, once, under `beforeId` (the route's lowest layer); whether they were added. */
export function addClimbs(
  map: ClimbsMap,
  climbs: readonly Climb[],
  on: boolean,
  pixelRatio: number,
  beforeId?: string,
  from: ClimbCategory = CLIMBS_FROM_DEFAULT,
  hidingBusy: boolean = hideBusy,
): boolean {
  if (map.getSource(CLIMBS_SOURCE_ID)) return false;
  for (const shape of CLIMB_SHAPES) {
    for (const { surface } of CLIMB_SURFACES) {
      if (map.hasImage(climbIconId(shape, surface))) continue;
      const { pixelRatio: ratio, ...image } = climbIcon(shape, pixelRatio, CLIMB_ICON_PX, surface);
      map.addImage(climbIconId(shape, surface), image, { pixelRatio: ratio });
    }
  }
  map.addSource(CLIMBS_LINE_SOURCE_ID, { type: "geojson", data: climbLines(climbs) });
  map.addSource(CLIMBS_SOURCE_ID, { type: "geojson", data: climbSummits(climbs) });
  const before = beforeId && map.getLayer(beforeId) ? beforeId : undefined;
  const visibility = on ? "visible" : "none";
  for (const layer of [climbLineLayer(), climbMarkerLayer()]) {
    map.addLayer({ ...layer, filter: climbsFilter(from, hidingBusy), layout: { ...(layer.layout as object), visibility } }, before);
  }
  return true;
}

/**
 * Both layers moved under `beforeId` (the major trails' names), when both are on the map; whether they were. The
 * names come with the stress overlay, which can come after the climbs: added then, they would sit over the names
 * (the v0.10.1 end review), so the map moves them once the overlay is in.
 */
export function climbsUnder(map: Pick<ClimbsMap, "getLayer"> & { moveLayer(id: string, beforeId?: string): void }, beforeId: string): boolean {
  if (!map.getLayer(beforeId) || !CLIMBS_LAYERS.every((id) => map.getLayer(id))) return false;
  // The line first, then the summits over it, as addClimbs orders them.
  for (const id of CLIMBS_LAYERS) map.moveLayer(id, beforeId);
  return true;
}

/** Show or hide both layers with the switch. */
export function setClimbsOn(map: ClimbsMap, on: boolean): void {
  for (const id of CLIMBS_LAYERS) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  }
}

/** Show only the climbs of `from` and harder ("Show climbs from"), less the busy roads' while hidden, on both layers. */
export function setClimbsFrom(map: ClimbsMap, from: ClimbCategory, hidingBusy: boolean = hideBusy): void {
  for (const id of CLIMBS_LAYERS) {
    if (map.getLayer(id)) map.setFilter?.(id, climbsFilter(from, hidingBusy));
  }
}
