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
import { foodHoursText, foodKindText } from "./food.ts";
import { shortStreets } from "./cueShown.ts";
import { formatDistance, formatDuration, spokenDistance } from "./format.ts";
import { lightClock, solarDay } from "./lightTimes.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { BASEMAP_SOURCE_ID, STRESS_SOURCE_ID } from "./mapStyle.ts";
import type { NearestPlace } from "./nearest.ts";
import { placeWords, type ReportPlace } from "./report311.ts";
import { STRESS_TILE_LAYER } from "../stressStyle.js";
import { tierWords } from "./profileChart.ts";
import { t } from "./i18n.ts";
import { secretFrom, withSecret } from "./rideSeal.ts";
import { leadKeyOfMark, leadMark } from "./linkCode.ts";

/** The fragment key of a broadcast link's leader mark (lib/sharedRoutes.ts LEAD_PARAM). */
const LEAD_PARAM = "lead";

/** The big button's name in Go with no destination, the card's heading, and its end. */
export const ROAM_NAME = "Roam";
export const END_ROAM_NAME = t("End roam");
export const ROAM_STARTED = t("Roaming. The map follows you and shows the roads ahead.");
export const ROAM_ENDED = t("Roam ended.");
/** Said and shown when a detour ends (End ride, or arrived and ended): the ride goes back to roaming. */
export const BACK_TO_ROAM = t("Back to roaming.");
/** Said when a back gesture is held during Roam (lib/rideBack.ts holds it, as during a ride). */
export const STILL_ROAMING_SAID = t("Still roaming. Use End roam to stop.");
/** Shown on the card before the map has a road near the rider. */
export const NO_ROAD_YET = t("Looking for the road you're on…");
/** Only poor GPS fixes for a while (lib/navigate.ts weighFix): the road names wait for a good one. */
export const ROAM_GPS_WEAK = t("GPS is weak: road names paused.");
/** No named road near: on an unnamed path, or off the map's roads. */
export const NO_NAMED_ROAD = t("No named road here");
/** The rider outside the area the map covers (P11): no roads to read, and nothing to start riding for. */
export const OUTSIDE_MAP = t("Outside the map (DC to Baltimore)");
/**
 * Roam's Nearby button and menu (the owner: "bathroom food water"): named Nearby, not Detour, since Roam has no route to
 * detour from (the audit's P13, approved 2026-10-28); its results say Ride here.
 */
export const ROAM_NEARBY_NAME = t("Nearby");
export const ROAM_DETOUR_HELP = t("Nearby rides you there; end it to roam again.");

/**
 * The base map's lines that are no road to ride onto (the audit's P14: "Washington Metro - Green and Yellow Line" was
 * listed as a road ahead): rail of every kind, by its own `kind` or a rail `kind_detail`, and tunnels, which pass under
 * the roads they cross.
 */
const RAIL_DETAILS = new Set(["rail", "subway", "light_rail", "tram", "monorail", "narrow_gauge", "funicular", "miniature", "preserved", "disused"]);
export function notARoad(properties: Record<string, unknown> | null | undefined): boolean {
  const p = properties ?? {};
  if (p.kind === "rail" || typeof p.railway === "string") return true;
  if (typeof p.kind_detail === "string" && RAIL_DETAILS.has(p.kind_detail)) return true;
  return p.is_tunnel === true || p.is_tunnel === "true" || p.tunnel === "yes";
}

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
  /** Each line's first and last segment, the end first: where the road may end on another (a T junction). */
  ends: Array<[XY, XY]>;
}

/** Each road's segments in the flat view, those with no point within `reach` metres of the rider left out. */
function flatRoads(roads: readonly RoadLine[], to: (p: LonLat) => XY, reach: number): FlatRoad[] {
  const out: FlatRoad[] = [];
  for (const road of roads) {
    if (!road.name) continue;
    const segs: Array<[XY, XY]> = [];
    const ends: Array<[XY, XY]> = [];
    for (const line of road.lines) {
      for (let i = 1; i < line.length; i++) {
        const a = to(line[i - 1]);
        const b = to(line[i]);
        if (closest([0, 0], a, b).m > reach) continue;
        segs.push([a, b]);
        if (i === 1) ends.push([a, b]);
        if (i === line.length - 1) ends.push([b, a]);
      }
    }
    if (segs.length > 0) out.push({ name: road.name, segs, ends });
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
      }
    }
    // A road that ends on the one ridden (a T junction): a line's end within MEETS_M of it. Only the ends, so a path
    // mapped alongside the road a few metres off is not a road met at every bend.
    for (const [end, next] of road.ends) {
      for (const [a, b] of ridden) {
        const hit = closest(end, a, b);
        if (hit.m <= MEETS_M) consider(road.name, hit.at, end, next);
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
  return tier ? t("On {road}, {tier}.", { road: on.name, tier }) : t("On {road}.", { road: on.name });
}

/** One road ahead, as shown under the card's road: the distance, US units first. */
export const aheadShown = (road: RoadAhead): string => formatDistance(road.distanceM);

/**
 * One road ahead on one line of the card (the audit's P13): the street words as Ride's card shortens them, then the
 * distance, its metric apart so the card can show it smaller ("13th St NW", "0.1 mi", "(0.2 km)"). Shown only: `said`
 * is the whole of it in words for screen readers ("13th Street Northwest, 0.1 mi (0.2 km), LTS 4").
 */
export function aheadRow(road: RoadAhead): { name: string; us: string; metric: string; said: string } {
  const far = aheadShown(road);
  const at = far.indexOf(" (");
  return {
    name: shortStreets(road.name),
    us: at < 0 ? far : far.slice(0, at),
    metric: at < 0 ? "" : far.slice(at + 1),
    said: [road.name, far, roamTier(road.tier)].filter(Boolean).join(", "),
  };
}

/** Said when a 311 pick in Roam comes before the first GPS fix. */
export const ROAM_NO_PLACE_311 = t("Your position is not known yet, so nothing was logged.");
/** How near the next road ahead is to be named in a 311 entry from Roam ("on 14th St NW near U St NW"). */
export const ROAM_PLACE_NEAR_M = 60;
/** Where a 311 entry from Roam says the rider is: the road ridden, the next road ahead when close, and the GPS point. */
export function roamReportPlace(point: LonLat, roads: RoadsAhead | null): ReportPlace {
  const next = roads?.ahead[0];
  return { words: placeWords(roads?.on?.name ?? null, next && next.distanceM <= ROAM_PLACE_NEAR_M ? next.name : null), point };
}

/** The roads ahead, as said: "Ahead: Calvert Street in 300 feet, LTS 3; Ontario Road in 0.2 miles." */
export function aheadSaid(ahead: readonly RoadAhead[]): string {
  if (ahead.length === 0) return "";
  const parts = ahead.map((road) => {
    const tier = roamTier(road.tier);
    const at = t("{road} in {distance}", { road: road.name, distance: spokenDistance(road.distanceM) });
    return tier ? `${at}, ${tier}` : at;
  });
  return t("Ahead: {roads}.", { roads: parts.join("; ") });
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

/**
 * The rider's heading fix by fix: `headingOf` from the last point at least 10 m back, and between fixes that give
 * none (no GPS heading, and too close to the last point to take one), the last heading kept, so the card and the
 * arrow hold steady at riding speed.
 */
export class HeadingTrack {
  private earlier: LonLat | null = null;
  private last: number | null = null;
  step(point: LonLat, gpsHeading: number | null): number | null {
    const h = headingOf(point, gpsHeading, this.earlier) ?? this.last;
    this.last = h;
    if (!this.earlier || haversineM(this.earlier, point) >= 10) this.earlier = point;
    return h;
  }
}

/** Find food's places as the nearest search's, so Roam's Detour lists food by riding distance as it does water. */
export function foodNearestPlaces(food: readonly FoodPlace[], at: Date = new Date()): NearestPlace[] {
  return food.map((place) => ({
    id: place.id,
    // Food rides like water: a stop on the way (lib/nearest.ts stopsOnTheWay). The kind is only a label here.
    kind: "water",
    point: [place.lon, place.lat],
    title: place.name || foodKindText(place),
    ...(place.name ? { name: place.name } : {}),
    // Worked out when read: only the few places listed say their hours, not every place in the area.
    get details() {
      return [place.name ? `${foodKindText(place)}.` : "", place.hours ? foodHoursText(place, at) : ""].filter(Boolean);
    },
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
      if (!name || notARoad(f.properties)) continue;
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

// ---- Broadcast from Roam (Stephen 2026-10-22: "Yes, but have it as a tap within roam") ----------------------------

/** Roam's Broadcast: one tap on the Roam screen opens the share sheet; those who open the link follow the rider. */
export const ROAM_BROADCAST_NAME = t("Share live");
export const ROAM_BROADCAST_TITLE = t("Follow my ride");
export const ROAM_BROADCAST_TEXT = t("Follow my ride on RouteMaker: my dot and the way I've ridden, while my app is open.");
export const ROAM_BROADCAST_ON = t("Sharing live. Those who open your link see your dot and the way you ride.");
/** The link went without the leader key (not ready yet, or no SHA-256 here): nothing is broadcast. */
export const ROAM_BROADCAST_NOT_READY = t("Share live is not ready yet; try again in a moment.");

/** The fragment keys of a Roam broadcast link: the ride's random id, the leader key and the ride's secret (lib/rideSeal.ts). */
export const ROAM_PARAM = "roam";
const HEX32 = /^[0-9a-f]{32}$/;

/**
 * A Roam broadcast's link: the page's own address, its fragment naming the ride and its leader, nothing else. The
 * leader key (32 hex digits) goes in its short form, 22 characters (lib/linkCode.ts leadMark, 2026-10-29).
 */
export function roamLink(origin: string, id: string, lead: string, secret: string | null = null): string {
  return withSecret(`${origin}/#${ROAM_PARAM}=${id}&${LEAD_PARAM}=${leadMark(lead) ?? lead}`, secret);
}

/**
 * The ride a Roam broadcast link names, its leader key (32 hex digits, from either form of the mark) and its secret
 * (null in an older link), or null for any other address.
 */
export function roamLinkFrom(hash: string): { id: string; lead: string; secret: string | null } | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const id = params.get(ROAM_PARAM);
  const lead = leadKeyOfMark(params.get(LEAD_PARAM));
  return id && lead && HEX32.test(id) ? { id, lead, secret: secretFrom(hash) } : null;
}

// ---- Sunrise and sunset (Stephen 2026-10-22: "Also add sunrise and sunset") -------------------------------------

/**
 * Roam's corner: the next sunrise and the next sunset at the rider, in the order they come, each with the time
 * till it within the hour ("Sunset 6:19 PM (42 min)"). `said` is the whole of it in words. Null with no sun times
 * (none in the region's year, but kept safe).
 */
export function roamLight(nowMs: number, at: LonLat): { shown: string[]; said: string } | null {
  const next = (kind: "sunrise" | "sunset"): number | null => {
    // Every 12 hours over the next day and a half: each lands in today or a day after, so the earliest one still to
    // come is the next, whatever a clock change does to the day's length.
    let soonest: number | null = null;
    for (let step = 0; step <= 3; step += 1) {
      const t = solarDay(nowMs + step * 43_200_000, at[1], at[0])[kind];
      if (t !== null && t > nowMs && (soonest === null || t < soonest)) soonest = t;
    }
    return soonest;
  };
  const events = (["sunrise", "sunset"] as const)
    .map((kind) => ({ kind, at: next(kind) }))
    .filter((e): e is { kind: "sunrise" | "sunset"; at: number } => e.at !== null)
    .sort((a, b) => a.at - b.at);
  if (events.length === 0) return null;
  const name = (kind: "sunrise" | "sunset") => (kind === "sunrise" ? t("Sunrise") : t("Sunset"));
  const soon = (at: number) => at - nowMs <= 3_600_000 && at - nowMs >= 30_000;
  const shown = events.map((e) => `${name(e.kind)} ${lightClock(e.at)}${soon(e.at) ? ` (${formatDuration((e.at - nowMs) / 1000)})` : ""}`);
  const said = events.map((e) => {
    const minutes = Math.max(1, Math.round((e.at - nowMs) / 60_000));
    return `${name(e.kind)} ${lightClock(e.at)}${soon(e.at) ? (minutes === 1 ? t(", in 1 minute") : t(", in {minutes} minutes", { minutes })) : ""}`;
  });
  return { shown, said: `${said.join("; ")}.` };
}

