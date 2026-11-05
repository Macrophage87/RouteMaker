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
import { language, t } from "./i18n.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { withoutSecret } from "./rideSeal.ts";
import type { PresetId } from "./presets.ts";
import { VIA_MARKS, namePoints } from "./pointKinds.ts";

export type ReachDirection = "from" | "to";
export type ReachCombine = "any" | "all" | "each";

export interface ReachView {
  direction: ReachDirection;
  combine: ReachCombine;
  /** Lay the calm streets' rings over the rider's own. */
  calm: boolean;
  /** The rings drawn, some of REACH_MINUTES, never none (Stephen 2026-11-04: "Allow for only certain isochrones to be selected"). */
  minutes: readonly number[];
}

export const REACH_MINUTES = [15, 30, 45, 60] as const;
export const REACH_DEFAULT: ReachView = { direction: "from", combine: "any", calm: true, minutes: REACH_MINUTES };

/** The rings with one minute turned on or off; the last one left stays on. */
export function toggleMinutes(chosen: readonly number[], minute: number): number[] {
  const next = chosen.includes(minute) ? chosen.filter((m) => m !== minute) : [...chosen, minute];
  return next.length ? REACH_MINUTES.filter((m) => next.includes(m)) : [...chosen];
}

function allMinutes(chosen: readonly number[]): boolean {
  return REACH_MINUTES.every((m) => chosen.includes(m));
}
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
  /** False when this ride type and slider have no calmer rings to show (Calm streets is then hidden). */
  calm_offered?: boolean;
  unplaced: number[];
  /** Mountain Bike: false, the rings take trails of every level (a plan keeps to the rider's); null elsewhere. */
  trail_level_applied?: boolean | null;
}

export type ReachResult = { ok: true; answer: ReachAnswer } | { ok: false; message: string };

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

/** The request's body: the points (at most REACH_MAX_POINTS, the first ones), the ride type and its dials. */
export function reachBody(points: readonly LonLat[], preset: PresetId, dials: Dials, view: ReachView, runPaceKmh?: number): Record<string, unknown> {
  const sent = points.slice(0, REACH_MAX_POINTS);
  const fields = dialFields({ ...dials, systemWeightKg: undefined, targetDistanceM: undefined, loop: false });
  // A ride's own fields the rings do not take: Mass Ride's size, Mountain Bike's levels, a share bike's docks.
  // A share e-bike is Reach's `assist` on Bikeshare: its pace, hills and graph, as the plan rides it.
  const shareEbike = preset === "bikeshare" && fields.bike === "ebike";
  for (const key of ["ride_size", "mtb_level", "mtb_preferred", "bike", "ending", "pickup_station", "dropoff_station", "transit_option", "novice_legs", "novice_hop"]) delete fields[key];
  return {
    points: sent,
    preset,
    ...fields,
    ...(shareEbike ? { assist: true } : {}),
    ...(preset === "run" && runPaceKmh ? { run_pace_kmh: runPaceKmh } : {}),
    ...closureFields(dials),
    minutes: REACH_MINUTES.filter((m) => view.minutes.includes(m)),
    direction: view.direction,
    combine: sent.length > 1 ? view.combine : "any",
    // Side by side draws a colour a point; a dashed calm set for each as well would not read.
    calm: view.calm && !sideBySide(sent.length, view),
  };
}

/** Several points drawn one colour each, where the calm layer is not offered. */
export function sideBySide(pointCount: number, view: ReachView): boolean {
  return pointCount > 1 && view.combine === "each";
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
  // The server's refusals are English sentences: the two Reach has are worded here, in the page's language; any other
  // is shown as written only on an English page.
  if (response.status === 422) return { ok: false, message: t("None of the points is on a street or path this ride type rides; move them onto one and try again.") };
  if (response.status === 502) return { ok: false, message: t("The router could not draw these rings. Try again.") };
  const error = (payload as { error?: unknown } | null)?.error;
  if (typeof error === "string" && error && language() === "en") return { ok: false, message: error };
  return { ok: false, message: t("The rings could not be drawn. Try again.") };
}

export { areaText };

/**
 * A point's name as its marker on the map has it: Start, Stop 1, Via point, End (lib/pointKinds.ts namePoints). Two
 * via points or more are numbered among themselves (Via point 1, Via point 2), so no two groups read the same.
 */
export function reachPointNames(points: readonly LonLat[], loop: boolean, isVia: (p: LonLat) => boolean = (p) => VIA_MARKS.isVia(p)): string[] {
  const named = namePoints(points, isVia, loop);
  const vias = named.filter((n) => n.role === "via").length;
  let via = 0;
  return named.map((n) =>
    n.role === "start"
      ? loop
        ? t("Start and finish")
        : t("Start")
      : n.role === "end"
        ? t("End")
        : n.role === "via"
          ? vias > 1
            ? t("Via point {number}", { number: (via += 1) })
            : t("Via point")
          : t("Stop {number}", { number: n.number ?? 0 }),
  );
}

/** Whether a share sheet was closed by the rider (nothing to copy then), not missing or refused. */
export function shareCancelled(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

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
  if (calm) text += ` ${t("On Low-stress streets: {area} and {metro}.", { area: areaText(calm.area_sq_mi, calm.area_km2), metro: metroText(calm.places.metro) })}`;
  return text;
}

/** The note under it where the rings were drawn at another setting than the slider's, or points were left out. */
export function reachNotes(answer: ReachAnswer, stress: number | undefined, pointCount: number): string[] {
  const notes: string[] = [];
  if (answer.stress_used !== null && stress !== undefined && stress > answer.stress_used) {
    notes.push(t("At Calm and Calmest, the rings are drawn at Low-stress: they show where low-stress ways reach in the time, not the long detours a calm route takes."));
  }
  if (answer.unplaced.length) {
    notes.push(
      answer.unplaced.length === 1
        ? t("1 point is off this ride type's map and left out.")
        : t("{count} points are off this ride type's map and left out.", { count: answer.unplaced.length }),
    );
  }
  if (pointCount > REACH_MAX_POINTS) notes.push(t("Only the first {count} points are used.", { count: REACH_MAX_POINTS }));
  if (answer.trail_level_applied === false) notes.push(t("The rings take trails of every level."));
  return notes;
}

/** One colour per point for Side by side; the first is the rings' own colour. */
export const REACH_COLOURS = ["#7b4fd6", "#d6457b", "#2f8fd6", "#a86f00", "#23804f"] as const;
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

/** The fragment's field: `reach=from.any.calm`, `reach=to.each`, `reach=from.any.calm.15.45` (only some rings). */
export const REACH_PARAM = "reach";

export function reachHashParam(view: ReachView): string {
  const minutes = allMinutes(view.minutes) ? [] : REACH_MINUTES.filter((m) => view.minutes.includes(m)).map(String);
  return `${REACH_PARAM}=${[view.direction, view.combine, ...(view.calm ? ["calm"] : []), ...minutes].join(".")}`;
}

/** The view a link names, or null for a link without `reach=`. */
export function reachFromHash(hash: string): ReachView | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const raw = params.get(REACH_PARAM);
  if (raw === null) return null;
  const parts = raw.split(".");
  const minutes = REACH_MINUTES.filter((m) => parts.includes(String(m)));
  return {
    direction: parts.includes("to") ? "to" : "from",
    combine: parts.includes("all") ? "all" : parts.includes("each") ? "each" : "any",
    calm: parts.includes("calm"),
    minutes: minutes.length ? minutes : REACH_MINUTES,
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

/** The link "Share these rings" hands out: the plan with its rings, never the Group or Mass Ride
 * secret (`k=`), since a ring link is often posted where anyone can read it. */
export function reachShareLink(
  where: { origin: string; pathname: string; search: string; hash: string },
  view: ReachView,
): string {
  return withoutSecret(`${where.origin}${where.pathname}${where.search}${withReach(where.hash, view)}`);
}
