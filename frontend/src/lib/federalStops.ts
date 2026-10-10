/**
 * The routing half of the federal-land item (PLAN.md FOLLOWUP-FEDERAL-LAYER, owner
 * item 239): for a Mass Ride, the places where the group stops on federal land and
 * the stretches it rides on a National Park Service parkway, in words.
 *
 * - The start, the end and each Stop N inside a shaded area get "federal land: check
 *   permit requirements for gathering here", naming the area and its manager where the
 *   data names one (239 (b)). The planner has no separate regroup or staging point: a
 *   regroup is planned as a stop, so it is a Stop N here.
 * - Riding through an area on an ordinary city street is not warned (239 (c)).
 * - A stretch on one of the five NPS parkways is named and warned as a federal road
 *   (239 (d)), found from the stretch's OpenStreetMap name, or, for an unnamed or
 *   parkway-named road stretch, from the NPS layer's polygon of that parkway.
 *
 * All of it is client side: the overlay's file is already in the page for a Mass Ride
 * (MapView loads it whatever the shading switch says), and the point-in-polygon test is
 * federalLand.ts's own. Information, not legal advice: ownership is not police
 * jurisdiction.
 */
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import { formatMileRange } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { FEDERAL_KINDS, FEDERAL_STYLE, inFederalArea, type FederalData, type FederalFeature, type FederalKind } from "./federalLand.ts";
import { pointName } from "./summary.ts";

/** The owner's words for a stop on federal land (item 239 (b)). */
export const FEDERAL_STOP_WARNING = "federal land: check permit requirements for gathering here";
/** A parkway stretch's warning (item 239 (d)). */
export const FEDERAL_ROAD_WARNING = "federal road: check permit requirements for riding it as a group";
/** The caveat every one of these carries once (items 236, 239). */
export const FEDERAL_ADVICE = "Information, not legal advice: federal ownership is not police jurisdiction.";
/** The description's heading line for the federal notes. */
export const FEDERAL_DESCRIPTION_HEADING = `Federal land on this route. ${FEDERAL_ADVICE}`;

/** An area a point is in: the most specific kind first (FEDERAL_KINDS order). */
export interface FederalArea {
  name: string;
  kind: FederalKind;
  agency: string | null;
}

type Box = [number, number, number, number];
const boxes = new WeakMap<FederalFeature, Box>();

/** A feature's bounding box, worked out once: most areas are far from any one point. */
function boxOf(feature: FederalFeature): Box {
  const cached = boxes.get(feature);
  if (cached) return cached;
  const box: Box = [Infinity, Infinity, -Infinity, -Infinity];
  const walk = (value: unknown): void => {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === "number" && typeof value[1] === "number") {
      box[0] = Math.min(box[0], value[0]);
      box[1] = Math.min(box[1], value[1]);
      box[2] = Math.max(box[2], value[0]);
      box[3] = Math.max(box[3], value[1]);
      return;
    }
    for (const item of value) walk(item);
  };
  walk(feature.geometry.coordinates);
  boxes.set(feature, box);
  return box;
}

const inBox = ([x, y]: readonly [number, number], [w, s, e, n]: Box) => x >= w && x <= e && y >= s && y <= n;

/** Whether `point` is inside `feature`. */
export function inFeature(point: readonly [number, number], feature: FederalFeature): boolean {
  return inBox(point, boxOf(feature)) && inFederalArea(point, feature.geometry);
}

/** The most specific federal area `point` is in, or null (none, or no data yet). */
export function federalAreaAt(point: readonly [number, number], data: FederalData | null): FederalArea | null {
  if (!data) return null;
  let best: FederalFeature | null = null;
  for (const feature of data.features) {
    if (!inFeature(point, feature)) continue;
    if (!best || FEDERAL_KINDS.indexOf(feature.properties.kind) < FEDERAL_KINDS.indexOf(best.properties.kind)) best = feature;
  }
  if (!best) return null;
  return { name: best.properties.name, kind: best.properties.kind, agency: best.properties.agency ?? null };
}

/** "U.S. Capitol grounds, managed by Architect of the Capitol"; the kind where no agency is known. */
export function areaWords(area: FederalArea): string {
  return area.agency ? `${area.name}, managed by ${area.agency}` : `${area.name} (${FEDERAL_STYLE[area.kind].label})`;
}

/** A stop's warning without its name, for its own row and marker: "Inside ... – federal land: ...". */
export function stopWarningShort(area: FederalArea): string {
  return `Inside ${areaWords(area)} – ${FEDERAL_STOP_WARNING}.`;
}

/** "End is inside U.S. Capitol grounds, managed by ... – federal land: check permit requirements for gathering here." */
export function stopWarning(name: string, area: FederalArea): string {
  return `${name} is inside ${areaWords(area)} – ${FEDERAL_STOP_WARNING}.`;
}

/** Each point's area, or null: the stop list's rows and the map's markers. Empty unless it is a Mass Ride with the data in. */
export function pointAreas(points: readonly LonLat[], data: FederalData | null, massRide: boolean): Array<FederalArea | null> {
  if (!massRide || !data) return [];
  return points.map((point) => federalAreaAt(point, data));
}

/** The five parkways the owner named (item 239 (d)), all kept by the National Park Service. */
export interface Parkway {
  name: string;
  /** An OpenStreetMap street name of it. */
  street: RegExp;
  /** The NPS layer's name of its polygon (only the parkways inside the District are in that layer). */
  area: RegExp;
}

export const PARKWAYS: readonly Parkway[] = [
  {
    name: "Rock Creek and Potomac Pkwy",
    street: /\brock creek (?:(?:and|&) potomac )?(?:parkway|pkwy)\b/i,
    area: /^rock creek (?:and|&) potomac parkway\b/i,
  },
  {
    name: "George Washington Memorial Pkwy",
    street: /\bgeorge washington (?:memorial )?(?:parkway|pkwy)\b/i,
    area: /^george washington memorial parkway\b/i,
  },
  { name: "Clara Barton Pkwy", street: /\bclara barton (?:parkway|pkwy)\b/i, area: /^clara barton parkway\b/i },
  { name: "Suitland Pkwy", street: /\bsuitland (?:parkway|pkwy)\b/i, area: /^suitland parkway\b/i },
  {
    name: "Baltimore-Washington Pkwy",
    street: /\bbaltimore[- ]washington (?:parkway|pkwy)\b/i,
    area: /^baltimore[- ]washington parkway\b/i,
  },
];

const PARKWAY_WORD = /\b(?:parkway|pkwy)\b/i;
/** Stretches on one parkway closer than this are one run (a junction entry between them, a short gap). */
export const PARKWAY_JOIN_M = 160;

/** The parkway a street name is, or null. */
export function parkwayByName(street: string | null | undefined): Parkway | null {
  if (!street) return null;
  return PARKWAYS.find((p) => p.street.test(street)) ?? null;
}

/** The point `metres` along a line, or null for an empty line. */
export function pointAlong(line: readonly LonLat[], metres: number): LonLat | null {
  if (line.length === 0) return null;
  let walked = 0;
  for (let i = 1; i < line.length; i++) {
    const step = haversineM(line[i - 1], line[i]);
    if (walked + step >= metres && step > 0) {
      const t = (metres - walked) / step;
      return [line[i - 1][0] + t * (line[i][0] - line[i - 1][0]), line[i - 1][1] + t * (line[i][1] - line[i - 1][1])];
    }
    walked += step;
  }
  return line[line.length - 1];
}

/**
 * The parkway an unnamed (or parkway-named) road stretch lies on by the NPS layer: two of
 * its quarter points inside that parkway's polygon. A path is never a federal road here: the
 * trails beside a parkway (Rock Creek's) are in its polygon too.
 */
function parkwayByArea(entry: DescriptionEntry, route: Pick<RouteResponse, "geometry" | "distance_m">, data: FederalData | null): Parkway | null {
  if (!data || entry.facility === "path") return null;
  if (entry.street && !PARKWAY_WORD.test(entry.street)) return null;
  const line = route.geometry?.coordinates ?? [];
  if (line.length < 2 || !(entry.to_m > entry.from_m)) return null;
  let length = 0;
  for (let i = 1; i < line.length; i++) length += haversineM(line[i - 1], line[i]);
  // The entries' distances are scaled to the route's length; the line's own may differ a little.
  const scale = route.distance_m > 0 ? length / route.distance_m : 1;
  const samples = [0.25, 0.5, 0.75]
    .map((f) => pointAlong(line, (entry.from_m + f * (entry.to_m - entry.from_m)) * scale))
    .filter((p): p is LonLat => p !== null);
  for (const parkway of PARKWAYS) {
    const areas = data.features.filter((f) => f.properties.kind === "nps" && parkway.area.test(f.properties.name));
    if (areas.length === 0) continue;
    const inside = samples.filter((p) => areas.some((a) => inFeature(p, a))).length;
    if (inside >= 2) return parkway;
  }
  return null;
}

export interface ParkwayRun {
  parkway: Parkway;
  from_m: number;
  to_m: number;
}

/** The route's runs on the named parkways, in route order. */
export function parkwayRuns(
  entries: readonly DescriptionEntry[],
  route: Pick<RouteResponse, "geometry" | "distance_m">,
  data: FederalData | null,
): ParkwayRun[] {
  const runs: ParkwayRun[] = [];
  for (const entry of entries) {
    if (entry.kind !== "stretch") continue;
    const parkway = parkwayByName(entry.street) ?? parkwayByArea(entry, route, data);
    if (!parkway) continue;
    const last = runs[runs.length - 1];
    if (last && last.parkway === parkway && entry.from_m - last.to_m <= PARKWAY_JOIN_M) last.to_m = Math.max(last.to_m, entry.to_m);
    else runs.push({ parkway, from_m: entry.from_m, to_m: entry.to_m });
  }
  return runs;
}

/** "2.1 to 3.4 mi (3.4 to 5.5 km): Rock Creek and Potomac Pkwy, a National Park Service parkway – federal road: ..." */
export function parkwayWarning(run: ParkwayRun): string {
  return `${formatMileRange(run.from_m, run.to_m)}: ${run.parkway.name}, a National Park Service parkway – ${FEDERAL_ROAD_WARNING}.`;
}

export interface FederalNotes {
  stops: string[];
  parkways: string[];
}

/**
 * A Mass Ride's federal notes: each point on federal land (Start, Stop N, End) and each
 * parkway run. Empty on every other ride type and before the data has come.
 */
export function federalNotes(
  route: Pick<RouteResponse, "preset" | "geometry" | "distance_m" | "description">,
  points: readonly LonLat[],
  data: FederalData | null,
): FederalNotes {
  if (route.preset !== "mass-ride" || !data) return { stops: [], parkways: [] };
  const stops: string[] = [];
  points.forEach((point, index) => {
    const area = federalAreaAt(point, data);
    // Mass Ride has no loop.
    if (area) stops.push(stopWarning(pointName(index, points.length), area));
  });
  const entries = Array.isArray(route.description) ? route.description : [];
  const parkways = parkwayRuns(entries, route, data).map(parkwayWarning);
  return { stops, parkways };
}

/** The notes as the description's lines: the heading line, the stops, then the parkways; none when there is nothing to say. */
export function federalLines(notes: FederalNotes | null | undefined): string[] {
  if (!notes || notes.stops.length + notes.parkways.length === 0) return [];
  return [FEDERAL_DESCRIPTION_HEADING, ...notes.stops, ...notes.parkways];
}
