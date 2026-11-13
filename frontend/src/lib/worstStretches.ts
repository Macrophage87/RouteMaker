/**
 * Check a route (the 2026-11-13 backlog, item 3): an opened route file's worst stretches, each with a calmer way round.
 *
 * A rider who opens a route made elsewhere (a club's GPX, a RideWithGPS export) wants a second opinion on it, not a new
 * route. When Plan follows an opened file (core/follow.py, `follows_file`), the route's own stress sections are the
 * file's ways at our levels; this module picks the worst stretches from them, plans a calmer way round each on the same
 * ride type at the calmest traffic setting, and, on "Use this way" (the owner's pick, 2026-11-13), splices that way into
 * the line the plan follows.
 *
 * "Worst" rests on our ratings alone (the route's `stress_spans`): busy sections (BUSY_LEVEL and up) near one another
 * are one stretch, and stretches are ranked by length weighted by how busy they are (LEVEL_WEIGHT). Every number here
 * is our default, unmeasured.
 *
 * What is sent: each calmer way is an ordinary /api/route request with two points, the stretch's ends; nothing of the
 * file is sent besides what following it already sends, and the API keeps neither.
 *
 * Pure apart from `planCalmerWay`, which takes its request function, so it is tested without a server.
 */
import type { RouteResponse, RouteResult, StressSpan } from "./api.ts";
import type { Dials } from "./dials.ts";
import { formatDistance, METRES_PER_MILE } from "./format.ts";
import type { LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import { lineAlong, measureMap } from "./navigate.ts";
import type { PresetId } from "./presets.ts";
import { sliceLine } from "./routeNames.ts";
import { cumulative } from "./trackMatch.ts";
import type { Stretch } from "./closureCheck.ts";

/** At most this many stretches are listed (our default, unmeasured): a short list, not a scroll. */
export const WORST_MOST = 3;
/** A section at this level or busier counts (our default): LTS 3 is where most adults stop being at ease. */
export const BUSY_LEVEL = 3;
/** Busy sections closer than this (a tenth of a mile) are one stretch (our default, unmeasured). */
export const JOIN_GAP_M = METRES_PER_MILE / 10;
/** The calmer way starts and ends this far outside the stretch (our default, unmeasured), so it can turn off at a calm street. */
export const PAD_M = 150;
/** A calmer way longer than this many times the stretch it replaces, plus a mile, is not offered (our default, unmeasured). */
export const DETOUR_MOST_RATIO = 2;
/** The traffic setting the calmer way is planned at: the slider's top, the calmest. */
export const CALMEST_STRESS = 100;

/** How much a mile at each level weighs: each half level up doubles it (our default, unmeasured). Avoid is 5. */
export function levelWeight(level: number): number {
  return 2 ** ((Math.min(level, 5) - BUSY_LEVEL) * 2);
}

/** A section's level: its tier, half a level more on a half step, 5 for Avoid; null where not rated. */
export function sectionLevel(span: Pick<StressSpan, "tier" | "half">): number | null {
  if (span.tier === null) return null;
  if (span.tier >= 5) return 5;
  return span.tier + (span.half === true ? 0.5 : 0);
}

/** A level in words: "LTS 3.5", "Avoid". */
export function levelText(level: number): string {
  return level >= 5 ? "Avoid" : `LTS ${level}`;
}

/** One of the worst stretches, in the route's (description's) metres. */
export interface WorstStretch {
  fromM: number;
  toM: number;
  /** Its busiest level. */
  level: number;
  /** Metres at BUSY_LEVEL or busier. */
  busyM: number;
  /** Length times LEVEL weight, summed: what it is ranked by. */
  weight: number;
  /** The street it is mostly on, or null for an unnamed way. */
  street: string | null;
}

/** The worst stretches of a route, worst first, at most `most`. Empty where nothing is busy. */
export function worstStretches(route: Pick<RouteResponse, "stress_spans" | "description">, most = WORST_MOST): WorstStretch[] {
  const runs: { fromM: number; toM: number; level: number; busyM: number; weight: number }[] = [];
  const spans = [...(route.stress_spans ?? [])].sort((a, b) => a.from_m - b.from_m);
  for (const span of spans) {
    const level = sectionLevel(span);
    const m = span.to_m - span.from_m;
    if (level === null || level < BUSY_LEVEL || !(m > 0)) continue;
    const last = runs[runs.length - 1];
    if (last && span.from_m - last.toM <= JOIN_GAP_M) {
      last.toM = Math.max(last.toM, span.to_m);
      last.level = Math.max(last.level, level);
      last.busyM += m;
      last.weight += (m / METRES_PER_MILE) * levelWeight(level);
    } else {
      runs.push({ fromM: span.from_m, toM: span.to_m, level, busyM: m, weight: (m / METRES_PER_MILE) * levelWeight(level) });
    }
  }
  return runs
    .map((run) => ({ ...run, street: streetOf(route, run.fromM, run.toM) }))
    .sort((a, b) => b.weight - a.weight || a.fromM - b.fromM)
    .slice(0, most);
}

/** The street most of a stretch is on: the description's stretch entries that overlap it, longest overlap. */
function streetOf(route: Pick<RouteResponse, "description">, fromM: number, toM: number): string | null {
  const byStreet = new Map<string, number>();
  for (const entry of route.description ?? []) {
    if (entry.kind !== "stretch" || !entry.street) continue;
    const overlap = Math.min(toM, entry.to_m) - Math.max(fromM, entry.from_m);
    if (overlap > 0) byStreet.set(entry.street, (byStreet.get(entry.street) ?? 0) + overlap);
  }
  let best: string | null = null;
  let bestM = 0;
  for (const [street, m] of byStreet) {
    if (m > bestM) [best, bestM] = [street, m];
  }
  return best;
}

/** The stretch's own line, and the points a calmer way is planned between (PAD_M outside it, within the route). */
export function stretchEnds(
  route: Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description">,
  stretch: Pick<WorstStretch, "fromM" | "toM">,
): { line: LonLat[]; from: LonLat; to: LonLat; paddedM: number } {
  const coordinates = route.geometry.coordinates;
  const along = lineAlong(coordinates);
  const toLine = measureMap(route, along);
  const end = along.length ? along[along.length - 1] : 0;
  const a = Math.max(0, toLine(stretch.fromM) - PAD_M);
  const b = Math.min(end, toLine(stretch.toM) + PAD_M);
  const padded = sliceLine(coordinates, along, a, b);
  return { line: sliceLine(coordinates, along, toLine(stretch.fromM), toLine(stretch.toM)), from: padded[0], to: padded[padded.length - 1], paddedM: b - a };
}

/** A calmer way round one stretch, or why there is none. */
export type CalmerWay =
  | { kind: "found"; line: LonLat[]; distanceM: number; extraM: number; level: number }
  | { kind: "none" }
  | { kind: "failed" };

/** The busiest level a route rides, or null where none of it is rated. */
export function busiestLevel(route: Pick<RouteResponse, "stress_spans">): number | null {
  let most: number | null = null;
  for (const span of route.stress_spans ?? []) {
    const level = sectionLevel(span);
    if (level !== null && span.to_m > span.from_m && (most === null || level > most)) most = level;
  }
  return most;
}

/**
 * Judge the route planned round a stretch: kept only where its busiest level is below the stretch's, and its length is
 * at most DETOUR_MOST_RATIO times the padded stretch plus a mile.
 */
export function judgeCalmerWay(stretch: Pick<WorstStretch, "level">, paddedM: number, around: RouteResponse): CalmerWay {
  const level = busiestLevel(around);
  if (level === null || level >= stretch.level) return { kind: "none" };
  if (around.distance_m > paddedM * DETOUR_MOST_RATIO + METRES_PER_MILE) return { kind: "none" };
  return { kind: "found", line: around.geometry.coordinates, distanceM: around.distance_m, extraM: Math.max(0, around.distance_m - paddedM), level };
}

/** The dials a calmer way is planned with: the plan's own, at the calmest traffic setting, two points, no loop or target. */
export function calmerDials(dials: Dials): Dials {
  const { targetDistanceM: _target, ...rest } = dials;
  return { ...rest, stress: CALMEST_STRESS, loop: false };
}

export type Planner = (points: LonLat[], preset: PresetId, dials: Dials) => Promise<RouteResult>;

/** Plan the calmer way round one stretch of `route` and judge it. */
export async function planCalmerWay(
  route: Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description">,
  stretch: Pick<WorstStretch, "fromM" | "toM" | "level">,
  preset: PresetId,
  dials: Dials,
  plan: Planner,
): Promise<CalmerWay> {
  const ends = stretchEnds(route, stretch);
  const result = await plan([ends.from, ends.to], preset, calmerDials(dials));
  if (!result.ok) return { kind: "failed" };
  return judgeCalmerWay(stretch, ends.paddedM, result.route);
}

// ---- Use this way -------------------------------------------------------------------------------------------------

/** The index of the vertex of `line` nearest `p`, searched between `lo` and `hi`. */
function nearestIndex(line: readonly LonLat[], p: LonLat, lo: number, hi: number): number {
  const kx = Math.cos((p[1] * Math.PI) / 180);
  let best = lo;
  let bestD = Infinity;
  for (let i = Math.max(0, lo); i <= Math.min(line.length - 1, hi); i += 1) {
    const d = ((line[i][0] - p[0]) * kx) ** 2 + (line[i][1] - p[1]) ** 2;
    if (d < bestD) [best, bestD] = [i, d];
  }
  return best;
}

/**
 * Where the calmer way goes into the file's full line (closureCheck.ts spliceDetours takes it from here): the vertex
 * nearest its start, and the first after that nearest its end. `share` is how far along the route (0 to 1) the stretch
 * starts, so a line that passes the same spot twice (an out-and-back) is cut at the right pass: the search keeps to a
 * window round that share of the line. Null where the ends cannot be placed in order.
 */
export function spliceAt(line: readonly (readonly number[])[], way: readonly LonLat[], share: number): Stretch | null {
  if (line.length < 2 || way.length < 2) return null;
  const flat = line.map((v) => [v[0], v[1]] as LonLat);
  const along = cumulative(flat);
  const total = along[along.length - 1];
  const window = Math.max(total * 0.2, 2000);
  const centre = Math.min(Math.max(share, 0), 1) * total;
  let lo = 0;
  while (lo < flat.length - 1 && along[lo] < centre - window) lo += 1;
  let hi = flat.length - 1;
  while (hi > 0 && along[hi] > centre + window * 2) hi -= 1;
  const before = nearestIndex(flat, way[0], lo, hi);
  const after = nearestIndex(flat, way[way.length - 1], before + 1, hi);
  return after > before ? { before, after } : null;
}

// ---- Words --------------------------------------------------------------------------------------------------------

export const CHECK_HEADING = t("Busiest stretches");
export const CHECK_NONE = t("Nothing on this route is busier than LTS 2.5.");
export const CHECK_PLANNING = t("Looking for a calmer way round…");
export const CHECK_NO_WAY = t("No calmer way round nearby.");
export const CHECK_FAILED = t("Could not look for a calmer way round just now.");
export const CHECK_USE = t("Use this way");
export const CHECK_NOT_PUT = t("Could not put the calmer way into the route.");
/** Said once Use this way is pressed: "The route now takes the calmer way round Big Road." */
export function usedSaid(street: string | null): string {
  return t("The route now takes the calmer way round {street}.", { street: street ?? t("an unnamed way") });
}
export const CHECK_ABOUT = t(
  "The file's busiest stretches by our ratings, worst first: busier and longer counts more. Each calmer way is planned on your ride type at the calmest traffic setting, between points just outside the stretch. Use this way puts it into the route, and a download is then the route with it; Undo takes it out.",
);

/** "Georgia Avenue Northwest: 0.6 mi, LTS 4 at worst". */
export function stretchLine(stretch: WorstStretch): string {
  return t("{street}: {distance}, {level} at worst", {
    street: stretch.street ?? t("an unnamed way"),
    distance: formatDistance(stretch.toM - stretch.fromM),
    level: levelText(stretch.level),
  });
}

/** "Calmer way: 0.3 mi longer, LTS 2 at worst." */
export function calmerLine(way: Extract<CalmerWay, { kind: "found" }>): string {
  return way.extraM < 50
    ? t("Calmer way: about as long, {level} at worst.", { level: levelText(way.level) })
    : t("Calmer way: {extra} longer, {level} at worst.", { extra: formatDistance(way.extraM), level: levelText(way.level) });
}
