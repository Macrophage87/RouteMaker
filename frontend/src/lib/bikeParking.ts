/**
 * Bike racks (Stephen, 2026-11-01: "When people select a location in Go, by map press or by selecting a location,
 * show the nearby racks and offer them as a routing option", then "They should also be seen on the map").
 *
 * The data is amenity-data/bike-parking.json, built by scripts/build_bike_parking.py: DDOT's Public Bike Racks in DC
 * (DC Open Data, CC BY 4.0; DC's data wins over OSM), and OpenStreetMap's public bicycle parking elsewhere (ODbL).
 * Loaded the first time Go asks for it or the layer is shown.
 *
 * Three places use it:
 * - Go's card for a tapped spot (GoSpotDialog.tsx): the nearest racks are pins beside its other places, and one
 *   button, "Ride to the bike rack", routes to the nearest.
 * - Go's route to a place picked or pressed: the racks near its end are pins, and one button under the route card,
 *   "End at the bike rack", moves the end there.
 * - The map: every rack, drawn with the Water and restrooms layer's switch from RACK_MIN_ZOOM in (no new switch).
 *
 * A rack's card (lib/stopCard.ts) says what it is, how many racks or spaces, who mapped it and how far.
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { hexToRgb, rasterise, type Raster, type Rgb } from "./stationIcons.ts";
import type { StopCardWords } from "./stopCard.ts";
import { WATER_ICON_PADDING } from "./waterRestrooms.ts";
import { t } from "./i18n.ts";

export interface BikeRack {
  /** "dc123" for DDOT's OBJECTID, else the OSM element ("n123", "w456"). */
  id: string;
  lon: number;
  lat: number;
  /** DDOT: how many racks (a U-rack holds two bikes). */
  racks?: number;
  /** OSM: how many bikes. */
  capacity?: number;
  /** OSM: "l" lockers, "b" a bike room or shed; stands otherwise. */
  kind?: "l" | "b";
  covered?: boolean;
  name?: string;
}

const count = (value: unknown): number | undefined =>
  typeof value === "number" && Number.isInteger(value) && value > 0 ? value : undefined;

/** The racks in the file; null if it is not the file's shape. */
export function parseBikeParking(value: unknown): BikeRack[] | null {
  const body = value as { points?: unknown } | null;
  if (!body || !Array.isArray(body.points)) return null;
  const out: BikeRack[] = [];
  for (const raw of body.points as Array<Record<string, unknown>>) {
    if (!raw || typeof raw.id !== "string") continue;
    const { x: lon, y: lat } = raw;
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    const rack: BikeRack = { id: raw.id, lon, lat };
    const racks = count(raw.r);
    if (racks) rack.racks = racks;
    const capacity = count(raw.c);
    if (capacity) rack.capacity = capacity;
    if (raw.k === "l" || raw.k === "b") rack.kind = raw.k;
    if (raw.cv === 1) rack.covered = true;
    if (typeof raw.n === "string" && raw.n.trim()) rack.name = raw.n.trim();
    out.push(rack);
  }
  return out;
}

export async function loadBikeParking(
  url: string,
  fetcher: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }> = (u) => fetch(u),
): Promise<BikeRack[] | null> {
  try {
    const response = await fetcher(url);
    if (!response.ok) return null;
    return parseBikeParking(await response.json());
  } catch {
    return null;
  }
}

export const rackPoint = (rack: BikeRack): LonLat => [rack.lon, rack.lat];
const fromDdot = (rack: BikeRack) => rack.id.startsWith("dc");

/** What it is: "Bike rack", "Bike lockers" or "Bike room". */
export function rackKindText(rack: BikeRack): string {
  return rack.kind === "l" ? t("Bike lockers") : rack.kind === "b" ? t("Bike room") : t("Bike rack");
}

/** The card's and the list's name: "Bike rack", or "Bike rack, Union Station" with a name. */
export function rackTitle(rack: BikeRack): string {
  return rack.name ? `${rackKindText(rack)}, ${rack.name}` : rackKindText(rack);
}

/** What is known of it, a short line each: how many, covered, a key for lockers, and whose list it is from. */
export function rackDetails(rack: BikeRack): string[] {
  const out: string[] = [];
  if (rack.racks) out.push(t("Racks: {count}.", { count: rack.racks }));
  else if (rack.capacity) out.push(t("Spaces: {count}.", { count: rack.capacity }));
  if (rack.covered) out.push(t("Covered."));
  if (rack.kind === "l") out.push(t("You may need a key, a card or a rental."));
  out.push(fromDdot(rack) ? t("From DDOT's public bike racks.") : t("From OpenStreetMap."));
  return out;
}

/** The card's words, with how far as the last fact before the source. */
export function rackWords(rack: BikeRack, far?: string): StopCardWords {
  const details = rackDetails(rack);
  const source = details.pop() as string;
  return { title: rackTitle(rack), lines: [...details, ...(far ? [far] : []), source] };
}

// --- Near a spot ----------------------------------------------------------------

/** How far Go looks for racks around a spot or a route's end: 500 ft (152 m), a short walk with the bike. */
export const RACK_NEAR_M = 152.4;
/** How many it shows there at most. */
export const RACK_MAX = 3;
/** A spot this close to a rack is at the rack: nothing more is offered. */
export const RACK_AT_M = 10;

export interface RackNear {
  rack: BikeRack;
  /** Straight line from the spot, metres. */
  metres: number;
}

/** The nearest racks to `from`, within `withinM`, nearest first, at most `max`. */
export function racksNear(from: LonLat, racks: readonly BikeRack[], withinM = RACK_NEAR_M, max = RACK_MAX): RackNear[] {
  // A box first: a degree of latitude is 111 km, so most racks are skipped without the sum.
  const dLat = withinM / 111_000;
  const dLon = dLat / Math.max(0.2, Math.cos((from[1] * Math.PI) / 180));
  const out: RackNear[] = [];
  for (const rack of racks) {
    if (Math.abs(rack.lat - from[1]) > dLat || Math.abs(rack.lon - from[0]) > dLon) continue;
    const metres = haversineM(from, rackPoint(rack));
    if (metres <= withinM) out.push({ rack, metres });
  }
  return out.sort((a, b) => a.metres - b.metres || a.rack.id.localeCompare(b.rack.id)).slice(0, max);
}

/**
 * The rack to offer for `spot`: the nearest within RACK_NEAR_M, or null with none, or when the spot is already at a
 * rack (within RACK_AT_M), as after "End at the bike rack".
 */
export function rackOffer(spot: LonLat, racks: readonly BikeRack[]): RackNear | null {
  const near = racksNear(spot, racks, RACK_NEAR_M, 1)[0];
  if (!near || near.metres <= RACK_AT_M) return null;
  return near;
}

// --- When the rack is full ---------------------------------------------------------
// Stephen, 2026-11-01: "In DC often the problem is that Bike racks are full. So maybe a way to find other ones."

/** How far the next rack may be: 1,000 ft (305 m), a block or two on foot with the bike. */
export const RACK_NEXT_M = 304.8;

/** Whether `spot` is at a rack (within RACK_AT_M): the rack, or null. */
export function rackAt(spot: LonLat, racks: readonly BikeRack[]): BikeRack | null {
  const near = racksNear(spot, racks, RACK_AT_M, 1)[0];
  return near ? near.rack : null;
}

/**
 * The racks to try when the one at (or nearest to) `spot` is full: within RACK_NEXT_M, nearest first, leaving out the
 * ones in `tried` and the one at the spot itself.
 */
export function otherRacks(spot: LonLat, racks: readonly BikeRack[], tried: ReadonlySet<string> = new Set(), max = 10): RackNear[] {
  return racksNear(spot, racks, RACK_NEXT_M, max + tried.size + 1)
    .filter((n) => n.metres > RACK_AT_M && !tried.has(n.rack.id))
    .slice(0, max);
}

/**
 * Go's run of "Rack full? Next one" presses: where the first rack was (the search stays around it, so presses never
 * drift away from the place), the racks already tried, and the rack the route ends at now.
 */
export interface RackRun {
  from: LonLat;
  tried: readonly string[];
  at: string;
}

/** The run that still applies to a route ending at rack `at`: a run that ended elsewhere is over. */
function liveRun(run: RackRun | null, at: BikeRack): RackRun | null {
  return run && run.at === at.id ? run : null;
}

/** The next rack to offer when the route ends at rack `at` (at `end`): nearest to the run's first rack, not yet tried. */
export function nextRack(end: LonLat, at: BikeRack, racks: readonly BikeRack[], run: RackRun | null): RackNear | null {
  const live = liveRun(run, at);
  return otherRacks(live ? live.from : end, racks, new Set([...(live ? live.tried : []), at.id]), 1)[0] ?? null;
}

/** The run after a press that moved the end from rack `at` (at `end`) to `next`. */
export function rackRunAfter(run: RackRun | null, end: LonLat, at: BikeRack, next: BikeRack): RackRun {
  const live = liveRun(run, at);
  return { from: live ? live.from : end, tried: [...(live ? live.tried : []), at.id], at: next.id };
}

/** The ride's arrival: the other racks within 1,000 ft, only when the route ends at a rack (a rack 50 m from a shop is not "full"). */
export function arrivalRacks(end: LonLat, racks: readonly BikeRack[]): RackNear[] {
  return rackAt(end, racks) ? otherRacks(end, racks) : [];
}

/** Go's route card when the route ends at a rack: "Rack full? Next one, 80 ft (24 m) away". */
export function nextRackText(near: RackNear): string {
  return t("Rack full? Next one, {distance} away", { distance: formatDistance(near.metres) });
}

/** The ride's line once arrived: "Rack full? Next one: 80 ft (24 m) to the northeast." */
export function rideNextRackLine(metres: number, direction: string): string {
  return t("Rack full? Next one: {distance} to the {direction}.", { distance: formatDistance(metres), direction });
}

/** The ride's button for the one after: shown with the line. */
export const NEXT_RACK_TEXT = t("Next rack");

/** Go's spot card's button: "Ride to the bike rack, 120 ft (37 m) away". */
export function rideToRackText(near: RackNear): string {
  return t("Ride to the bike rack, {distance} away", { distance: formatDistance(near.metres) });
}

/** Under Go's route card: "End at the bike rack, 120 ft (37 m) away" (from the route's end). */
export function endAtRackText(near: RackNear): string {
  return t("End at the bike rack, {distance} away", { distance: formatDistance(near.metres) });
}

/** Said once the end has moved there. */
export function endAtRackSaid(near: RackNear): string {
  return t("Route now ends at the bike rack, {distance} from where it ended.", { distance: formatDistance(near.metres) });
}

/** The name a rack's point goes by in the route card and the ride: "Bike rack near {place}", else "Bike rack". */
export function rackPlaceName(near: RackNear, place: string | null): string {
  return place ? t("{kind} near {place}", { kind: rackKindText(near.rack), place }) : rackKindText(near.rack);
}

// --- The map's layer ----------------------------------------------------------

export const RACK_SOURCE_ID = "bike-racks";
export const RACK_LAYER = "bike-racks";
export const RACK_ICON_ID = "bike-rack";
/** From block level in: DC alone has nearly 5,000 racks, which would bury the stress map further out. */
export const RACK_MIN_ZOOM = 15;
export const RACK_COLOUR = "#be185d";
export const RACK_ICON_PX = 18;

/** The icon: a pink rounded square with a white edge and a white inverted U, a rack, standing on a line. */
export function rackIcon(pixelRatio = 2, cssSize = RACK_ICON_PX): Raster {
  const size = Math.round(cssSize * pixelRatio);
  const edge = 1.5 * pixelRatio;
  const fill = hexToRgb(RACK_COLOUR);
  const white = hexToRgb("#ffffff");
  const radius = size * 0.22;
  const stroke = size * 0.085;
  const inBox = (x: number, y: number, inset: number) => {
    const lo = inset;
    const hi = size - inset;
    if (x < lo || x > hi || y < lo || y > hi) return false;
    const cx = Math.min(Math.max(x, lo + radius), hi - radius);
    const cy = Math.min(Math.max(y, lo + radius), hi - radius);
    return Math.hypot(x - cx, y - cy) <= radius;
  };
  const c = size / 2;
  const archR = size * 0.2;
  const archY = size * 0.42;
  const ground = size * 0.76;
  const inRack = (x: number, y: number) => {
    // The ground line.
    if (Math.abs(y - ground) <= stroke && Math.abs(x - c) <= size * 0.3) return true;
    // The two legs.
    if (y >= archY && y <= ground && (Math.abs(x - (c - archR)) <= stroke || Math.abs(x - (c + archR)) <= stroke)) return true;
    // The arch over them.
    return y <= archY && Math.abs(Math.hypot(x - c, y - archY) - archR) <= stroke;
  };
  return rasterise(size, pixelRatio, (x, y): Rgb | null => {
    if (!inBox(x, y, 0)) return null;
    if (!inBox(x, y, edge)) return white;
    return inRack(x, y) ? white : fill;
  });
}

export function rackGeoJson(racks: readonly BikeRack[]): object {
  return {
    type: "FeatureCollection",
    features: racks.map((r) => ({ type: "Feature", properties: { id: r.id }, geometry: { type: "Point", coordinates: [r.lon, r.lat] } })),
  };
}

/** The racks' layer, thinned where crowded as the water layer is. */
export function rackLayer(minzoom = RACK_MIN_ZOOM): Record<string, unknown> {
  return {
    id: RACK_LAYER,
    type: "symbol",
    source: RACK_SOURCE_ID,
    minzoom,
    layout: {
      "icon-image": RACK_ICON_ID,
      "icon-size": ["interpolate", ["linear"], ["zoom"], minzoom, 0.8, 18, 1.2],
      "icon-allow-overlap": false,
      "icon-padding": WATER_ICON_PADDING,
      "icon-ignore-placement": false,
      // Water and restrooms first where they crowd: a rack is seldom the reason to stop.
      "symbol-sort-key": 2,
    },
  };
}
