/**
 * The plan in the page's URL fragment, so a link opens the same route.
 *
 * The fragment and not the query string: a fragment never leaves the browser,
 * so the points a rider is looking at reach no server log - which matters when
 * some rides are unpermitted. Nothing here is saved; saving is for signed-in
 * riders (owner decision, 2026-09-26).
 */
import { MAX_POINTS, insideCoverage, type LonLat } from "./geo.ts";
import { PRESET_ALIASES, parsePreset, type PresetId } from "./presets.ts";
import { VIA_MARKS, decodeDrawn, decodeStopNames, decodeVias, drawnLegs, encodeStopNames, stopNames } from "./pointKinds.ts";
import { STRESS_DEFAULT_AT, fitDials, isBike, isCarrying, isWhen, type Dials } from "./dials.ts";
import { METRES_PER_MILE } from "./format.ts";
import { decodePoints, encodePoints } from "./linkCode.ts";

/**
 * The stops' field (2026-10-29, shorter ride links): `q=`, the points in lib/linkCode.ts's short form, about 8
 * characters a stop. `p=` is the older form, `lon,lat;lon,lat` to 5 decimals, which every link already shared and
 * every ride post the server writes still carry: it is read for ever, and written only where asked (`pointsForm`).
 */
export const POINTS_PARAM = "q";
export const OLD_POINTS_PARAM = "p";
export type PointsForm = "q" | "p";

/** The points a link's fragment holds, in either form (`q=` first), before any check of where they are. */
export function linkPoints(params: URLSearchParams): LonLat[] {
  const short = params.get(POINTS_PARAM);
  if (short !== null) return decodePoints(short);
  const points: LonLat[] = [];
  for (const pair of (params.get(OLD_POINTS_PARAM) ?? "").split(";")) {
    const parts = pair.split(",");
    if (parts.length !== 2) continue;
    points.push([Number(parts[0]), Number(parts[1])]);
  }
  return points;
}

/**
 * The link's version. It stays 2 for the target distance (OWNER-DECISIONS 256, 271):
 * `targetmi` is a new field that an older link does not have and means none, and no
 * field a link already carried changes what it names. 2 is the traffic slider after its rescale of 2026-10-01
 * (OWNER-DECISIONS 163): the old 0-100 now sits at 0-80, the old 90 (Default)
 * at 70, and above 80 is the calm detour search. A link with no `v` is from
 * before, and its `stress` is mapped onto the new scale (`stressFromV1`), so an
 * old Default link still opens Default's route and an old Trailmaxxing link the
 * old top, not the new calm search (review r1, B4).
 */
export const PLAN_VERSION = "2";

/** The old slider's position on the new one: old x 70/90 up to 90, then 70 + (old - 90). */
export function stressFromV1(old: number): number {
  const OLD_DEFAULT = 90;
  if (old <= OLD_DEFAULT) return Math.round((old * STRESS_DEFAULT_AT) / OLD_DEFAULT);
  return STRESS_DEFAULT_AT + Math.round(old - OLD_DEFAULT);
}

export interface Plan {
  points: LonLat[];
  /**
   * The via points' indices (v0.7.0, "Via points vs stops": `via=1,3`); empty for an older link, where every
   * point is a stop, as it was.
   */
  vias: number[];
  /** The legs drawn in Plan's manual mode (`line=0,2`: leg i runs from point i to i + 1); empty for an older link. */
  drawn: number[];
  /** The stops' own names by index (`sn=2:Union Market`, Stephen 2026-10-24); empty for an older link. */
  names: Map<number, string>;
  preset: PresetId;
  /** The sliders, the ride time and Cargo Bike's load (dials.ts). */
  dials: Dials;
}

export function encodePlan(
  points: readonly LonLat[],
  preset: PresetId,
  dials?: Dials,
  vias: readonly number[] = [],
  // The page's marks unless given, so every link, saved route and kept route's key carries the drawn legs.
  drawn: readonly number[] = drawnLegs(points),
  // The stops' own names, likewise from the page's marks unless given.
  names: ReadonlyMap<number, string> = stopNames(points, VIA_MARKS.nameOf, VIA_MARKS.isVia, dials?.loop === true),
  // The short `q=` unless asked for the older `p=` (a kept route's key, so the routes kept before still match).
  pointsForm: PointsForm = "q",
): string {
  const params = new URLSearchParams();
  if (points.length) {
    if (pointsForm === "q") params.set(POINTS_PARAM, encodePoints(points));
    else params.set(OLD_POINTS_PARAM, points.map(([lon, lat]) => `${lon.toFixed(5)},${lat.toFixed(5)}`).join(";"));
  }
  // Each point's kind (v0.7.0): the via points by index; a new field an older link does not have.
  if (vias.length) params.set("via", vias.join(","));
  // The legs drawn in Plan's manual mode (v0.9.1): a new field an older link does not have, and means none.
  if (drawn.length) params.set("line", drawn.join(","));
  // The stops' own names (2026-10-24): a new field an older link does not have, and means none.
  for (const value of encodeStopNames(names)) params.append("sn", value);
  params.set("preset", preset);
  if (dials) {
    params.set("v", PLAN_VERSION);
    params.set("stress", String(dials.stress));
    params.set("hills", String(dials.hills));
    if (dials.when) params.set("when", dials.when);
    if (dials.carrying) params.set("carrying", dials.carrying);
    if (dials.assist) params.set("assist", "1");
    if (dials.avoidGravel) params.set("avoidgravel", "1");
    // "Keep to roads, not trails" (OWNER-DECISIONS 463, 463b). Absent is trails on, except on Mass Ride, which is always off.
    if (dials.trailsOff) params.set("trailsoff", "1");
    // A novice rider's transit plan (v0.7.0): its bike legs as Novice and Nervous plans them.
    if (dials.noviceLegs) params.set("novice", "1");
    // The target distance in miles, to a tenth. Absent is none; an older link has none.
    if (dials.targetDistanceM) params.set("targetmi", (dials.targetDistanceM / METRES_PER_MILE).toFixed(1));
    // Never the rider and bike weight (OWNER-DECISIONS 313): it is private.
    // "Make it a loop" (OWNER-DECISIONS 266); absent is off.
    if (dials.loop) params.set("loop", "1");
    // Bikeshare (OWNER-DECISIONS 243, 244): the bike, and an e-bike's ending outside a dock. New
    // fields an older link does not have, so the link's version stays 2.
    if (dials.bike) params.set("bike", dials.bike);
    if (dials.bike === "ebike" && dials.ending === "outside_dock") params.set("ending", "outside");
    // Mass Ride's "Anticipated ride size" (PLAN items 128, 139), riders; absent is the default (500).
    if (dials.rideSize) params.set("riders", String(dials.rideSize));
    // Mountain Bike's hardest trail level (slice 6); absent is level 2. Its preferred level (the second
    // pass); absent is min(2, the hardest), so an older link with only `level` plans as it did.
    if (dials.mtbLevel) params.set("level", String(dials.mtbLevel));
    if (dials.mtbPreferred) params.set("prefer", String(dials.mtbPreferred));
  }
  return `#${params.toString().replaceAll("%2C", ",").replaceAll("%3B", ";")}`;
}

function numberOrUndefined(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

/** The zoom a spot link (`#at=lon,lat`) opens at: street level, where half steps show. */
export const AT_ZOOM = 16;

/**
 * A spot on the map to open at (`#at=lon,lat`), or null: the link a rider suggestion's Discord post
 * carries (core/suggestions.py `map_url`; OWNER-DECISIONS 2026-10-10). Only a spot inside the covered
 * area; anything else opens the map as usual.
 */
export function atFromHash(hash: string): LonLat | null {
  const raw = new URLSearchParams(hash.replace(/^#/, "")).get("at");
  if (!raw) return null;
  const parts = raw.split(",");
  if (parts.length !== 2) return null;
  const point: LonLat = [Number(parts[0]), Number(parts[1])];
  if (!Number.isFinite(point[0]) || !Number.isFinite(point[1]) || !insideCoverage(point)) return null;
  return point;
}

export function decodePlan(hash: string): Plan {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const points: LonLat[] = [];
  for (const point of linkPoints(params)) {
    if (!Number.isFinite(point[0]) || !Number.isFinite(point[1]) || !insideCoverage(point)) continue;
    points.push(point);
    if (points.length === MAX_POINTS) break;
  }
  const named = params.get("preset");
  const preset = parsePreset(named);
  // A link to a ride type since renamed (Riding with kids, now Novice and Nervous, v0.7.0) opens the new ride
  // type at its own starting sliders: the old ones were the old ride type's.
  const renamed = named !== null && Object.hasOwn(PRESET_ALIASES, named);
  const when = params.get("when");
  const carrying = params.get("carrying");
  const linked = renamed ? undefined : numberOrUndefined(params.get("stress"));
  const stress = linked === undefined || params.get("v") === PLAN_VERSION ? linked : stressFromV1(linked);
  const targetMiles = numberOrUndefined(params.get("targetmi"));
  const dials = fitDials(preset, {
    stress,
    targetDistanceM: targetMiles === undefined ? undefined : Math.round(targetMiles * METRES_PER_MILE),
    // An older link's "sysweight" is ignored (OWNER-DECISIONS 313).
    loop: params.get("loop") === "1",
    hills: renamed ? undefined : numberOrUndefined(params.get("hills")),
    when: isWhen(when) ? when : null,
    carrying: isCarrying(carrying) ? carrying : null,
    assist: params.get("assist") === "1",
    avoidGravel: params.get("avoidgravel") === "1",
    trailsOff: params.get("trailsoff") === "1",
    noviceLegs: params.get("novice") === "1",
    ...(isBike(params.get("bike")) ? { bike: params.get("bike") as "classic" | "ebike" } : {}),
    ...(params.get("ending") === "outside" ? { ending: "outside_dock" as const } : {}),
    rideSize: numberOrUndefined(params.get("riders")),
    mtbLevel: numberOrUndefined(params.get("level")),
    mtbPreferred: numberOrUndefined(params.get("prefer")),
  });
  return { points, vias: decodeVias(params.get("via"), points.length), drawn: decodeDrawn(params.get("line"), points.length), names: decodeStopNames(params.getAll("sn"), points.length), preset, dials };
}
