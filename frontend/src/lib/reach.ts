/**
 * Reach: where the rider can be in 15, 30, 45 and 60 minutes (isochrones), on Plan's map.
 *
 * Stephen, 2026-11-04: "have a full set of isochrone tools. Like where can I be in 15, 30, 45 min, 1 hr by bike.
 * Then we'd change things by traffic tolerance, etc."; "Allow isochrones from several points too."; "Allow
 * different modalities too, such as mass ride, fast, etc."; "It should be sharable too".
 *
 * The rings are the router's (POST /api/reach, core/reach.py) for the plan's own points, ride type and Ride
 * settings, so the traffic slider, the ride type, the riding speed and the hills change them as they change a route.
 * Several points combine three ways (any, all, each). The calm layer is the same rings at Low-stress, laid over as
 * dashed outlines. The view is shareable: the plan's link with `reach=` added (`reachHashParam`), which opens Reach.
 *
 * Plain data in, plain data out, so node --test runs all of it; the sheet is ReachSheet.tsx.
 */
import { closureFields, dialFields, type Dials } from "./dials.ts";
import { areaText, KM_PER_MILE } from "./format.ts";
import { t } from "./i18n.ts";
import { haversineM, type LonLat } from "./geo.ts";
import type { PresetId } from "./presets.ts";

export type ReachDirection = "from" | "to";
export type ReachCombine = "any" | "all" | "each";

export interface ReachView {
  direction: ReachDirection;
  combine: ReachCombine;
  /** Lay the calm streets' rings over the rider's own. */
  calm: boolean;
}

export const REACH_DEFAULT: ReachView = { direction: "from", combine: "any", calm: true };
export const REACH_MINUTES = [15, 30, 45, 60] as const;
/** core/reach.py MAX_POINTS. */
export const REACH_MAX_POINTS = 5;

/** The ride types with no rings yet (phase 2, transit); core/reach.py NOT_YET. */
const NOT_YET: ReadonlySet<string> = new Set(["bike-transit", "bikeshare-transit", "walk-transit"]);

export function reachOffered(preset: PresetId): boolean {
  return !NOT_YET.has(preset);
}

export interface ReachPlaces {
  metro: number;
  racks: number;
  food: number;
  sights: number;
}

export interface ReachRing {
  minutes: number;
  geometry: { type: "Polygon" | "MultiPolygon"; coordinates: unknown } | null;
  area_sq_mi: number;
  area_km2: number;
  places: ReachPlaces;
}

export interface ReachGroup {
  point: number | null;
  rings: ReachRing[];
  metro_stations: string[];
}

export interface ReachAnswer {
  preset: string;
  minutes: number[];
  direction: ReachDirection;
  combine: ReachCombine;
  stress_used: number | null;
  groups: ReachGroup[];
  calm: { stress: number; groups: ReachGroup[] } | null;
  unplaced: number[];
}

export type ReachResult = { ok: true; answer: ReachAnswer } | { ok: false; message: string };

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

/** The request's body: the points (at most REACH_MAX_POINTS, the first ones), the ride type and its dials. */
export function reachBody(points: readonly LonLat[], preset: PresetId, dials: Dials, view: ReachView, runPaceKmh?: number): Record<string, unknown> {
  const sent = points.slice(0, REACH_MAX_POINTS);
  const fields = dialFields({ ...dials, systemWeightKg: undefined, targetDistanceM: undefined, loop: false });
  // A ride's own fields the rings do not take: Mass Ride's size, Mountain Bike's levels, a share bike's docks.
  for (const key of ["ride_size", "mtb_level", "mtb_preferred", "bike", "ending", "pickup_station", "dropoff_station", "transit_option", "novice_legs", "novice_hop"]) delete fields[key];
  return {
    points: sent,
    preset,
    ...fields,
    ...(preset === "run" && runPaceKmh ? { run_pace_kmh: runPaceKmh } : {}),
    ...closureFields(dials),
    direction: view.direction,
    combine: sent.length > 1 ? view.combine : "any",
    calm: view.calm,
  };
}

function isAnswer(value: unknown): value is ReachAnswer {
  const v = value as ReachAnswer | null;
  return !!v && Array.isArray(v.groups) && Array.isArray(v.minutes) && v.groups.every((g) => Array.isArray(g.rings));
}

export async function requestReach(body: Record<string, unknown>, fetchImpl: FetchLike = (url, init) => fetch(url, init), signal?: AbortSignal): Promise<ReachResult> {
  let response: Response;
  try {
    response = await fetchImpl("/api/reach", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    return { ok: false, message: t("The rings did not get through. Check your connection and try again.") };
  }
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (response.ok && isAnswer(payload)) return { ok: true, answer: payload };
  if (response.status === 429 || response.status === 503) return { ok: false, message: t("The router is busy. Try again in a moment.") };
  const error = (payload as { error?: unknown } | null)?.error;
  if (typeof error === "string" && error) return { ok: false, message: error };
  return { ok: false, message: t("The rings could not be drawn. Try again.") };
}

export { areaText };

function metroText(n: number): string {
  return n === 1 ? t("{count} Metro station", { count: n }) : t("{count} Metro stations", { count: n });
}

/** What a ring holds, in words: "4 Metro stations, 120 bike racks, 300 places to eat, 12 places to see". */
export function placesText(places: ReachPlaces): string {
  return [
    metroText(places.metro),
    places.racks === 1 ? t("{count} bike rack", { count: 1 }) : t("{count} bike racks", { count: places.racks }),
    places.food === 1 ? t("{count} place to eat", { count: 1 }) : t("{count} places to eat", { count: places.food }),
    places.sights === 1 ? t("{count} place to see", { count: 1 }) : t("{count} places to see", { count: places.sights }),
  ].join(", ");
}

/**
 * The answer in one sentence, at the top (inverted pyramid): the 30 minute ring when there is one, else the largest.
 * "From here, 30 min reaches 14 sq mi (36 km²) and 3 Metro stations; on calm streets, 9.2 sq mi and 1."
 */
export function reachSentence(answer: ReachAnswer, pointCount: number): string {
  const group = answer.groups[0];
  if (!group) return "";
  const pick = answer.minutes.includes(30) ? answer.minutes.indexOf(30) : answer.minutes.length - 1;
  const ring = group.rings[pick];
  if (!ring) return "";
  const to = answer.direction === "to";
  const where =
    pointCount <= 1
      ? to
        ? t("To here")
        : t("From here")
      : answer.combine === "all"
        ? to
          ? t("Reaching all the points")
          : t("From every point")
        : answer.combine === "each" && answer.groups.length > 1
          ? to
            ? t("Reaching the first point")
            : t("From the first point")
          : to
            ? t("Reaching any of the points")
            : t("From any of the points");
  const vars = { where, minutes: ring.minutes, area: areaText(ring.area_sq_mi, ring.area_km2), metro: metroText(ring.places.metro) };
  let text = to ? t("{where}, {minutes} min comes from {area} and {metro}.", vars) : t("{where}, {minutes} min reaches {area} and {metro}.", vars);
  const calm = answer.calm?.groups[0]?.rings[pick];
  if (calm) text += ` ${t("On calm streets: {area} and {metro}.", { area: areaText(calm.area_sq_mi, calm.area_km2), metro: metroText(calm.places.metro) })}`;
  return text;
}

/** The note under it where the rings were drawn at another setting than the slider's, or points were left out. */
export function reachNotes(answer: ReachAnswer, stress: number | undefined, pointCount: number): string[] {
  const notes: string[] = [];
  if (answer.stress_used !== null && stress !== undefined && stress > answer.stress_used) {
    notes.push(t("Above Low-stress the rings are Low-stress's: they show where calm ways reach, not the long calm detours a route may take."));
  }
  if (answer.unplaced.length) {
    notes.push(
      answer.unplaced.length === 1
        ? t("1 point is off this ride type's map and left out.")
        : t("{count} points are off this ride type's map and left out.", { count: answer.unplaced.length }),
    );
  }
  if (pointCount > REACH_MAX_POINTS) notes.push(t("Only the first {count} points are used.", { count: REACH_MAX_POINTS }));
  return notes;
}

/** One colour per point for Side by side; the first is the rings' own colour. */
export const REACH_COLOURS = ["#7b4fd6", "#d6457b", "#2f8fd6", "#c98a00", "#2fa36b"] as const;
export const REACH_CALM_COLOUR = "#00897b";

export interface ReachFeature {
  type: "Feature";
  geometry: NonNullable<ReachRing["geometry"]>;
  properties: { minutes: number; colour: string; calm: boolean };
}

/** The rings as GeoJSON for the map, largest first so the smaller ones draw on top. */
export function reachFeatures(answer: ReachAnswer): { type: "FeatureCollection"; features: ReachFeature[] } {
  const features: ReachFeature[] = [];
  const add = (groups: ReachGroup[], calm: boolean) =>
    groups.forEach((group, g) => {
      const colour = calm ? REACH_CALM_COLOUR : REACH_COLOURS[(group.point ?? g) % REACH_COLOURS.length];
      for (const ring of [...group.rings].reverse()) {
        if (ring.geometry) features.push({ type: "Feature", geometry: ring.geometry, properties: { minutes: ring.minutes, colour, calm } });
      }
    });
  add(answer.groups, false);
  if (answer.calm) add(answer.calm.groups, true);
  return { type: "FeatureCollection", features };
}

// --- the link ------------------------------------------------------------------------------------------------------

/** The fragment's field: `reach=from.any.calm`, `reach=to.each`. */
export const REACH_PARAM = "reach";

export function reachHashParam(view: ReachView): string {
  return `${REACH_PARAM}=${[view.direction, view.combine, ...(view.calm ? ["calm"] : [])].join(".")}`;
}

/** The view a link names, or null for a link without `reach=`. */
export function reachFromHash(hash: string): ReachView | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const raw = params.get(REACH_PARAM);
  if (raw === null) return null;
  const parts = raw.split(".");
  return {
    direction: parts.includes("to") ? "to" : "from",
    combine: parts.includes("all") ? "all" : parts.includes("each") ? "each" : "any",
    calm: parts.includes("calm"),
  };
}

/** The plan's fragment with the view added (or replaced). */
export function withReach(hash: string, view: ReachView | null): string {
  const bare = hash.replace(/^#/, "");
  const params = bare
    .split("&")
    .filter((part) => part && !part.startsWith(`${REACH_PARAM}=`));
  if (view) params.push(reachHashParam(view));
  return params.length ? `#${params.join("&")}` : "";
}

/** How close to Home a point gives the share its warning (lib/sharedRoutes.ts HOME_REACH_M's order). */
export const REACH_HOME_M = 400;

export function sharesHome(points: readonly LonLat[], home: LonLat | null | undefined): boolean {
  return !!home && points.some((p) => haversineM(p, home) <= REACH_HOME_M);
}

/** Square miles in square kilometres, for tests and the MCP's figures. */
export const KM2_PER_SQ_MI = KM_PER_MILE * KM_PER_MILE;
