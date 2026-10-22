/**
 * Roam (the owner, 2026-10-22: "Add a free ride mode on go. Basically just show the map and the roads upcoming. Let
 * people detour still to bathroom food water etc", then "or call it roam"): a ride with no destination. The map
 * follows the rider, and the card names the road they are on and the roads coming up ahead, each with its traffic
 * stress, read from the map's own tiles on the device: the base map's road names and the stress tiles' levels.
 * Nothing is sent for it: no position leaves the phone until the rider asks for a detour.
 *
 * Everything here is pure, so a test runs it on made-up roads: the map's features in, the words out.
 */
import type { FoodPlace } from "./food.ts";
import { foodKindText } from "./food.ts";
import { formatDistance, spokenDistance } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { BASEMAP_SOURCE_ID, STRESS_SOURCE_ID } from "./mapStyle.ts";
import type { NearestPlace } from "./nearest.ts";
import { STRESS_TILE_LAYER } from "../stressStyle.js";
import { tierWords } from "./profileChart.ts";

/** The big button's name in Go with no destination, the card's heading, and its end. */
export const ROAM_NAME = "Roam";
export const END_ROAM_NAME = "End roam";
export const ROAM_STARTED = "Roaming. The map follows you and shows the roads ahead.";
export const ROAM_ENDED = "Roam ended.";
/** Said and shown when a detour ends (End ride, or arrived and ended): the ride goes back to roaming. */
export const BACK_TO_ROAM = "Back to roaming.";
/** Shown on the card before the map has a road near the rider. */
export const NO_ROAD_YET = "Looking for the road you're on…";
/** No named road near: on an unnamed path, or off the map's roads. */
export const NO_NAMED_ROAD = "No named road here";
/** What Roam's Detour menu offers (the owner: "bathroom food water"). */
export const ROAM_DETOUR_HELP = "Detour plans a ride from where you are to that place. End the ride there to go back to roaming.";

/** One line of the map: a named road (the base map's) or a stress line (the stress tiles'), each as lon/lat lines. */
export interface RoadLine {
  name: string;
  lines: LonLat[][];
}
export interface StressLine {
  tier: number;
  /** A half step (the next level's dash over this one; OWNER-DECISIONS 441r). */
  half?: boolean;
  lines: LonLat[][];
}

export interface RoadNow {
  name: string;
  tier: number | null;
}
export interface RoadAhead extends RoadNow {
  /** Straight-line metres from the rider to where it crosses or meets the road ahead. */
  distanceM: number;
}
export interface RoadsAhead {
  /** The road the rider is on, or null with no named road close. */
  on: RoadNow | null;
  /** The next roads ahead, nearest first, each once (ROADS_AHEAD of them at most). */
  ahead: RoadAhead[];
}

/** How far a road may be from the rider and still be the one they are on (GPS on a phone is often 5 to 15 m out). */
export const ON_ROAD_M = 25;
/** How far ahead the card looks: about half a mile. */
export const AHEAD_M = 800;
/** How many roads ahead the card shows: fewer words on screen (the owner, 2026-10-20). */
export const ROADS_AHEAD = 3;
/** How far a stress line may be from a spot and still be that road's. */
const STRESS_NEAR_M = 20;
/** Where a road's stress is read: this far along it from the junction, so the road being ridden is not read instead. */
const STRESS_ALONG_M = 15;
/** With no road under the rider (an unnamed path, a park), the line ahead is straight on this far. */
const RAY_M = 500;
/** A junction closer than this is the one being ridden through, not one ahead. */
const PASSING_M = 8;
/** How close a road's end must be to the road ridden to meet it (a T junction mapped as a shared node, give or take). */
const MEETS_M = 3;

type XY = [number, number];

/** A flat view in metres around `origin` (x east, y north): fine over a mile. */
function flat(origin: LonLat): (p: LonLat) => XY {
  const kx = 111_320 * Math.cos((origin[1] * Math.PI) / 180);
  const ky = 110_540;
  return (p) => [(p[0] - origin[0]) * kx, (p[1] - origin[1]) * ky];
}

const len = (v: XY): number => Math.hypot(v[0], v[1]);

/** The closest point of segment ab to p, and how far along ab (0 to 1) it is. */
function closest(p: XY, a: XY, b: XY): { at: XY; t: number; m: number } {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
  const at: XY = [a[0] + t * dx, a[1] + t * dy];
  return { at, t, m: len([p[0] - at[0], p[1] - at[1]]) };
}

/** Where segments ab and cd cross, or null. */
function crossing(a: XY, b: XY, c: XY, d: XY): XY | null {
  const r: XY = [b[0] - a[0], b[1] - a[1]];
  const s: XY = [d[0] - c[0], d[1] - c[1]];
  const den = r[0] * s[1] - r[1] * s[0];
  if (den === 0) return null;
  const qp: XY = [c[0] - a[0], c[1] - a[1]];
  const t = (qp[0] * s[1] - qp[1] * s[0]) / den;
  const u = (qp[0] * r[1] - qp[1] * r[0]) / den;
  if (t < 0 || t > 1 || u < 0 || u > 1) return null;
  return [a[0] + t * r[0], a[1] + t * r[1]];
}

/** A point `metres` from `from` towards `to` (no further than `to`). */
function along(from: XY, to: XY, metres: number): XY {
  const v: XY = [to[0] - from[0], to[1] - from[1]];
  const l = len(v);
  if (l === 0) return from;
  const k = Math.min(1, metres / l);
  return [from[0] + v[0] * k, from[1] + v[1] * k];
}

interface FlatRoad {
  name: string;
  segs: Array<[XY, XY]>;
}

/** Each road's segments in the flat view, those with no point within `reach` metres of the rider left out. */
function flatRoads(roads: readonly RoadLine[], to: (p: LonLat) => XY, reach: number): FlatRoad[] {
  const out: FlatRoad[] = [];
  for (const road of roads) {
    if (!road.name) continue;
    const segs: Array<[XY, XY]> = [];
    for (const line of road.lines) {
      for (let i = 1; i < line.length; i++) {
        const a = to(line[i - 1]);
        const b = to(line[i]);
        if (closest([0, 0], a, b).m <= reach) segs.push([a, b]);
      }
    }
    if (segs.length > 0) out.push({ name: road.name, segs });
  }
  return out;
}

/** The stress level of the line nearest `p` within STRESS_NEAR_M, or null. A half step is read as the level above. */
function tierNear(p: XY, stress: ReadonlyArray<{ tier: number; segs: Array<[XY, XY]> }>): number | null {
  let best: { tier: number; m: number } | null = null;
  for (const line of stress) {
    for (const [a, b] of line.segs) {
      const m = closest(p, a, b).m;
      if (m <= STRESS_NEAR_M && (!best || m < best.m)) best = { tier: line.tier, m };
    }
  }
  return best?.tier ?? null;
}

/**
 * The road the rider is on and the roads ahead of them. `headingDeg` (clockwise from north) says which way is ahead;
 * with none (standing still), only the road they are on is named. The roads ahead are the ones that cross or meet
 * the road ridden (all of it by that name, so a bend is followed), in front of the rider; with no named road under
 * them, the ones a straight line ahead crosses.
 */
export function roadsAhead(rider: LonLat, headingDeg: number | null, roads: readonly RoadLine[], stressLines: readonly StressLine[]): RoadsAhead {
  const to = flat(rider);
  const near = flatRoads(roads, to, AHEAD_M + 100);
  const stress = stressLines.map((s) => ({
    tier: s.half ? Math.min(5, s.tier + 1) : s.tier,
    segs: flatRoads([{ name: "s", lines: s.lines }], to, AHEAD_M + 100)[0]?.segs ?? [],
  }));
  const dir: XY | null = headingDeg === null ? null : [Math.sin((headingDeg * Math.PI) / 180), Math.cos((headingDeg * Math.PI) / 180)];
  // The road under the rider: the nearest within ON_ROAD_M, a road along the heading preferred over a cross street
  // a few metres nearer (at a junction both are close).
  let on: { road: FlatRoad; score: number } | null = null;
  for (const road of near) {
    for (const [a, b] of road.segs) {
      const m = closest([0, 0], a, b).m;
      if (m > ON_ROAD_M) continue;
      let score = m;
      if (dir) {
        const seg: XY = [b[0] - a[0], b[1] - a[1]];
        const l = len(seg);
        const cos = l === 0 ? 1 : Math.abs((seg[0] * dir[0] + seg[1] * dir[1]) / l);
        score += 20 * (1 - cos);
      }
      if (!on || score < on.score) on = { road, score };
    }
  }
  const onNow: RoadNow | null = on ? { name: on.road.name, tier: tierNear([0, 0], stress) } : null;
  if (!dir) return { on: onNow, ahead: [] };
  const ridden: Array<[XY, XY]> = on ? near.filter((r) => r.name === on!.road.name).flatMap((r) => r.segs) : [[[0, 0], [dir[0] * RAY_M, dir[1] * RAY_M]]];
  const found = new Map<string, RoadAhead>();
  const consider = (name: string, p: XY, c: XY, d: XY) => {
    const fwd = p[0] * dir[0] + p[1] * dir[1];
    const side = Math.abs(p[0] * dir[1] - p[1] * dir[0]);
    // Ahead: in front, and not far off to one side (a bend is fine; the road behind a U-shaped one is not).
    if (fwd < PASSING_M || side > Math.max(60, fwd * 0.75)) return;
    const distanceM = len(p);
    if (distanceM > AHEAD_M) return;
    const was = found.get(name);
    if (was && was.distanceM <= distanceM) return;
    // The stress a little way along the road met, each way it goes from the junction, the busier said (the rider
    // may turn either way). A road that ends at the junction is read the one way it goes.
    const tiers: number[] = [];
    for (const end of [c, d]) {
      if (len([end[0] - p[0], end[1] - p[1]]) < 1) continue;
      const tier = tierNear(along(p, end, STRESS_ALONG_M), stress);
      if (tier !== null) tiers.push(tier);
    }
    found.set(name, { name, tier: tiers.length > 0 ? Math.max(...tiers) : null, distanceM });
  };
  for (const road of near) {
    if (on && road.name === on.road.name) continue;
    for (const [c, d] of road.segs) {
      for (const [a, b] of ridden) {
        const x = crossing(a, b, c, d);
        if (x) consider(road.name, x, c, d);
        // A road that ends on the one ridden (a T junction): its end within MEETS_M of it.
        for (const end of [c, d]) {
          if (x) break;
          const hit = closest(end, a, b);
          if (hit.m <= MEETS_M) consider(road.name, hit.at, c, d);
        }
      }
    }
  }
  const ahead = [...found.values()].sort((x, y) => x.distanceM - y.distanceM).slice(0, ROADS_AHEAD);
  return { on: onNow, ahead };
}

/** The level as the card's badge says it ("LTS 2", "Avoid"), or null where the map has none. */
export const roamTier = (tier: number | null): string | null => tierWords(tier);

/** The road ridden, as said: "On Connecticut Avenue Northwest, LTS 2." */
export function onRoadSaid(on: RoadNow | null): string {
  if (!on) return `${NO_NAMED_ROAD}.`;
  const tier = roamTier(on.tier);
  return tier ? `On ${on.name}, ${tier}.` : `On ${on.name}.`;
}

/** One road ahead, as shown under the card's road: the distance, US units first. */
export const aheadShown = (road: RoadAhead): string => formatDistance(road.distanceM);

/** The roads ahead, as said: "Ahead: Calvert Street in 300 feet, LTS 3; Ontario Road in 0.2 miles." */
export function aheadSaid(ahead: readonly RoadAhead[]): string {
  if (ahead.length === 0) return "";
  const parts = ahead.map((road) => {
    const tier = roamTier(road.tier);
    return `${road.name} in ${spokenDistance(road.distanceM)}${tier ? `, ${tier}` : ""}`;
  });
  return `Ahead: ${parts.join("; ")}.`;
}

/**
 * The rider's heading: the GPS's own while moving, else the bearing from an earlier fix at least `minM` back (a
 * phone's GPS gives no heading below walking pace), else null.
 */
export function headingOf(now: LonLat, gpsHeading: number | null, earlier: LonLat | null, minM = 10): number | null {
  if (gpsHeading !== null) return gpsHeading;
  if (!earlier) return null;
  const v = flat(earlier)(now);
  if (len(v) < minM) return null;
  return ((Math.atan2(v[0], v[1]) * 180) / Math.PI + 360) % 360;
}

/** Find food's places as the nearest search's, so Roam's Detour lists food by riding distance as it does water. */
export function foodNearestPlaces(food: readonly FoodPlace[]): NearestPlace[] {
  return food.map((place) => ({
    id: place.id,
    // Food rides like water: a stop on the way (lib/nearest.ts stopsOnTheWay). The kind is only a label here.
    kind: "water",
    point: [place.lon, place.lat],
    title: place.name || foodKindText(place),
    details: [place.name ? `${foodKindText(place)}.` : "", place.hours ? `Hours as mapped: ${place.hours}.` : ""].filter(Boolean),
  }));
}

/** The map's features as lines: a LineString or MultiLineString's coordinates, anything else none. */
export function linesOf(geometry: { type: string; coordinates?: unknown } | null | undefined): LonLat[][] {
  if (!geometry) return [];
  if (geometry.type === "LineString") return [geometry.coordinates as LonLat[]];
  if (geometry.type === "MultiLineString") return geometry.coordinates as LonLat[][];
  return [];
}

/** The parts of the map Roam reads: the tiles already on the phone, nothing fetched for it. */
export interface RoamMap {
  getSource(id: string): unknown;
  querySourceFeatures(
    id: string,
    options: { sourceLayer: string },
  ): Array<{ geometry?: { type: string; coordinates?: unknown } | null; properties?: Record<string, unknown> | null }>;
}

/** A road's name from the base map's feature, as its labels choose it (stressStyle.js rideRoadLabelField). */
function roadName(properties: Record<string, unknown> | null | undefined): string {
  const p = properties ?? {};
  for (const key of ["name:en", "pgf:name", "name"]) {
    const v = p[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

/** The map's road lines and stress lines near the rider (a box about `reach` metres round them). */
export function mapLines(map: RoamMap, rider: LonLat, reach = AHEAD_M + 200): { roads: RoadLine[]; stress: StressLine[] } {
  const dLat = reach / 110_540;
  const dLon = reach / (111_320 * Math.cos((rider[1] * Math.PI) / 180));
  const near = (lines: LonLat[][]) =>
    lines.some((line) => line.some(([lon, lat]) => Math.abs(lon - rider[0]) <= dLon && Math.abs(lat - rider[1]) <= dLat));
  const roads: RoadLine[] = [];
  if (map.getSource(BASEMAP_SOURCE_ID)) {
    for (const f of map.querySourceFeatures(BASEMAP_SOURCE_ID, { sourceLayer: "roads" })) {
      const name = roadName(f.properties);
      if (!name) continue;
      const lines = linesOf(f.geometry);
      if (near(lines)) roads.push({ name, lines });
    }
  }
  const stress: StressLine[] = [];
  if (map.getSource(STRESS_SOURCE_ID)) {
    for (const f of map.querySourceFeatures(STRESS_SOURCE_ID, { sourceLayer: STRESS_TILE_LAYER })) {
      const p = f.properties ?? {};
      const tier = Number(p.tier);
      // A mountain-bike-only trail is drawn not for routes (OWNER-DECISIONS 452a): not a road's level.
      if (!Number.isFinite(tier) || p.mtb === true) continue;
      const lines = linesOf(f.geometry);
      if (near(lines)) stress.push({ tier, half: p.half === true, lines });
    }
  }
  return { roads, stress };
}
