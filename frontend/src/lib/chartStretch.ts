/**
 * A stretch picked on Plan's route chart (the 2026-11-12 backlog, Plan experience item 5): drag across the chart to
 * pick it, read its miles, climb and stress, and, where it is busy or steep, try a way round it and take that way.
 *
 * The way round is Check a route's calmer way (lib/worstStretches.ts) made general: planned between points just outside
 * the stretch (stretchEnds), at the calmest traffic setting where the stretch is busy and the hills slider's most
 * avoiding end where it is steep, and kept only where it is better on what made the stretch bad and worse on neither.
 * Taking it: on an opened file the plan follows, the calmer way is spliced into the file's line (App takeCalmerWay); on
 * any other plan, the points inside the stretch go and via points on the way round take their place (viasAround).
 *
 * Every threshold here is our default, unmeasured, except where it names its source.
 */
import type { RouteProfile, RouteResponse } from "./api.ts";
import { HILLS_MIN, type Dials } from "./dials.ts";
import { formatClimb, formatDistance, formatDistanceChange, METRES_PER_MILE } from "./format.ts";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { t } from "./i18n.ts";
import { legEnds, legPoints } from "./lineEdit.ts";
import { lineAlong, measureMap } from "./navigate.ts";
import { mileWord, miles } from "./profileChart.ts";
import type { PresetId } from "./presets.ts";
import {
  BUSY_LEVEL,
  DETOUR_MOST_RATIO,
  PAD_M,
  busiestLevel,
  calmerDials,
  levelText,
  sectionLevel,
  stretchEnds,
  streetOf,
  type Planner,
  type WorstStretch,
} from "./worstStretches.ts";

/** A stretch is steep where it climbs at this grade or more: the chart's own first amber band (GRADE_BANDS, 5% to 8%). */
export const STEEP_PCT = 5;
/** A way round is flatter only where it climbs at least this much less (our default, unmeasured): a few metres is noise. */
export const LESS_CLIMB_M = 5;
/** Via points put on a taken way round (our default): enough to hold the route on it, few enough not to clutter the map. */
export const WAY_VIAS = 2;

/** What the chart's picked stretch is, in the route's metres. */
export interface StretchFacts {
  fromM: number;
  toM: number;
  /** Metres climbed over it, from the profile; null with no elevation there. */
  climbM: number | null;
  /** Its steepest uphill grade, percent; null with none. */
  steepestPct: number | null;
  /** Its busiest level (lib/worstStretches.ts sectionLevel); null where none is rated. */
  level: number | null;
  street: string | null;
}

/** Metres climbed between two places along the profile (each rise between samples, added up); null with no elevation. */
export function climbBetween(profile: Pick<RouteProfile, "m" | "elevation_m">, fromM: number, toM: number): number | null {
  let climb = 0;
  let last: number | null = null;
  let any = false;
  profile.m.forEach((m, i) => {
    const e = profile.elevation_m[i];
    if (m < fromM || m > toM || e === null || e === undefined) {
      last = null;
      return;
    }
    if (last !== null && e > last) climb += e - last;
    last = e;
    any = true;
  });
  return any ? climb : null;
}

/** The facts of the stretch from `fromM` to `toM`. */
export function stretchFacts(route: Pick<RouteResponse, "stress_spans" | "description">, profile: RouteProfile, fromM: number, toM: number): StretchFacts {
  let steepestPct: number | null = null;
  profile.m.forEach((m, i) => {
    const g = profile.grade_pct[i];
    if (m >= fromM && m <= toM && g !== null && g !== undefined && g > 0 && (steepestPct === null || g > steepestPct)) steepestPct = g;
  });
  let level: number | null = null;
  for (const span of route.stress_spans ?? []) {
    const l = sectionLevel(span);
    if (l !== null && span.to_m > fromM && span.from_m < toM && (level === null || l > level)) level = l;
  }
  return { fromM, toM, climbM: climbBetween(profile, fromM, toM), steepestPct, level, street: streetOf(route, fromM, toM) };
}

/** Why a way round is worth looking for: the stretch is busy (LTS 3 or more, as Check a route), steep, or both. */
export function whyAvoid(facts: StretchFacts): { busy: boolean; steep: boolean } {
  return { busy: facts.level !== null && facts.level >= BUSY_LEVEL, steep: facts.steepestPct !== null && facts.steepestPct >= STEEP_PCT };
}

/** "Mile 2.1 to 3.4: 1.3 mi (2.1 km), 120 ft (37 m) of climb, steepest 7%, LTS 3.5 at worst." */
export function factsLine(facts: StretchFacts): string {
  const parts = [formatDistance(facts.toM - facts.fromM)];
  if (facts.climbM !== null) parts.push(t("{climb} of climb", { climb: formatClimb(facts.climbM) }));
  if (facts.steepestPct !== null && facts.steepestPct >= 1) parts.push(t("steepest {grade}%", { grade: Math.round(facts.steepestPct) }));
  parts.push(facts.level === null ? t("stress not rated") : t("{level} at worst", { level: levelText(facts.level) }));
  return t("{from} to {to}: {facts}.", { from: mileWord(facts.fromM), to: miles(facts.toM), facts: parts.join(", ") });
}

/** A way round a picked stretch, or why there is none. */
export type WayRound =
  | { kind: "found"; line: LonLat[]; extraM: number; level: number | null; climbChangeM: number | null }
  | { kind: "none" }
  | { kind: "failed" };

/** The dials a way round is planned with: the plan's own, two points, calmest traffic where busy, fewest hills where steep. */
export function aroundDials(dials: Dials, why: { busy: boolean; steep: boolean }): Dials {
  const calm = calmerDials(dials);
  return { ...calm, stress: why.busy ? calm.stress : dials.stress, hills: why.steep ? HILLS_MIN : dials.hills };
}

/**
 * Judge the route planned round a stretch: kept where it is calmer (on a busy stretch) or climbs less (on a steep one),
 * is neither busier nor climbs more than the stretch padded, and is at most DETOUR_MOST_RATIO times it plus a mile.
 */
export function judgeWayRound(facts: StretchFacts, paddedM: number, paddedClimbM: number | null, around: RouteResponse): WayRound {
  const why = whyAvoid(facts);
  if (around.distance_m > paddedM * DETOUR_MOST_RATIO + METRES_PER_MILE) return { kind: "none" };
  const level = busiestLevel(around);
  const climb = around.profile ? climbBetween(around.profile, -Infinity, Infinity) : null;
  const change = climb !== null && paddedClimbM !== null ? climb - paddedClimbM : null;
  const calmer = facts.level !== null && level !== null && level < facts.level;
  const busier = facts.level !== null && level !== null && level > facts.level;
  const flatter = change !== null && change <= -LESS_CLIMB_M;
  const steeper = change !== null && change > LESS_CLIMB_M;
  if (!((why.busy && calmer) || (why.steep && flatter)) || busier || steeper) return { kind: "none" };
  return { kind: "found", line: around.geometry.coordinates.map(([lon, lat]) => [lon, lat] as LonLat), extraM: around.distance_m - paddedM, level, climbChangeM: change };
}

/** Plan the way round a picked stretch of `route` and judge it. */
export async function planAround(route: RouteResponse, profile: RouteProfile, facts: StretchFacts, preset: PresetId, dials: Dials, plan: Planner): Promise<WayRound> {
  const ends = stretchEnds(route, facts);
  const result = await plan([ends.from, ends.to], preset, aroundDials(dials, whyAvoid(facts)));
  if (!result.ok) return { kind: "failed" };
  return judgeWayRound(facts, ends.paddedM, climbBetween(profile, facts.fromM - PAD_M, facts.toM + PAD_M), result.route);
}

/** "Way round: 0.4 mi (0.6 km) longer, 60 ft (18 m) less climb, LTS 2 at worst." */
export function wayLine(way: Extract<WayRound, { kind: "found" }>): string {
  // Under 50 m (our default, as Check a route's) is said as about as long.
  const parts = [
    Math.abs(way.extraM) < 50
      ? t("about as long")
      : way.extraM > 0
        ? t("{distance} longer", { distance: formatDistanceChange(way.extraM) })
        : t("{distance} shorter", { distance: formatDistanceChange(way.extraM) }),
  ];
  if (way.climbChangeM !== null && Math.abs(way.climbChangeM) >= LESS_CLIMB_M) {
    parts.push(way.climbChangeM < 0 ? t("{climb} less climb", { climb: formatClimb(-way.climbChangeM) }) : t("{climb} more climb", { climb: formatClimb(way.climbChangeM) }));
  }
  if (way.level !== null) parts.push(t("{level} at worst", { level: levelText(way.level) }));
  return t("Way round: {facts}.", { facts: parts.join(", ") });
}

/** The stretch as Check a route's Use this way takes it. */
export function asWorst(facts: StretchFacts): WorstStretch {
  return { fromM: facts.fromM, toM: facts.toM, level: facts.level ?? 0, busyM: 0, weight: 0, street: facts.street };
}

/** The point `atM` metres along `line`. */
function pointAlong(line: readonly LonLat[], along: Float64Array, atM: number): LonLat {
  for (let i = 1; i < line.length; i += 1) {
    if (along[i] >= atM) {
      const span = along[i] - along[i - 1];
      const k = span > 0 ? (atM - along[i - 1]) / span : 0;
      return [line[i - 1][0] + k * (line[i][0] - line[i - 1][0]), line[i - 1][1] + k * (line[i][1] - line[i - 1][1])];
    }
  }
  return line[line.length - 1];
}

/**
 * The plan's points once a way round is taken on a planned route: the points the route reaches inside the stretch
 * padded go (as Check a route's pointsKept), and WAY_VIAS via points spaced along the way round take their place,
 * in the leg the stretch is in. `mark` makes a point a via (pointKinds VIA_MARKS.via). Null over MAX_POINTS.
 */
export function viasAround(
  points: readonly LonLat[],
  route: Pick<RouteResponse, "geometry" | "distance_m" | "leg_ends" | "description">,
  stretch: Pick<WorstStretch, "fromM" | "toM">,
  way: readonly LonLat[],
  loop: boolean,
  mark: (point: LonLat) => LonLat,
): LonLat[] | null {
  if (points.length < 2 || way.length < 2) return null;
  const coordinates = route.geometry.coordinates as LonLat[];
  const ridden = legPoints(points, loop);
  const ends = legEnds(coordinates, ridden, route.leg_ends);
  const along = lineAlong(coordinates);
  const toLine = measureMap(route, along);
  const from = toLine(stretch.fromM) - PAD_M;
  const to = toLine(stretch.toM) + PAD_M;
  const wayAlong = lineAlong(way);
  const wayM = wayAlong[wayAlong.length - 1];
  const vias = Array.from({ length: WAY_VIAS }, (_, k) => mark(pointAlong(way, wayAlong, (wayM * (k + 1)) / (WAY_VIAS + 1))));
  // A ride that closes back on its start has one more leg than points: a stretch on it goes after the last point.
  const closing = ridden.length > points.length;
  const out: LonLat[] = [];
  let put = false;
  points.forEach((p, i) => {
    const at = i === 0 ? 0 : along[ends[i - 1]];
    const last = i === points.length - 1;
    if (i > 0 && !last && at > from && at < to) return;
    if (i > 0 && !put && (at >= to || (last && !closing))) {
      out.push(...vias);
      put = true;
    }
    out.push(p);
  });
  if (!put) out.push(...vias);
  return out.length > MAX_POINTS ? null : out;
}

// ---- Words --------------------------------------------------------------------------------------------------------

export const STRETCH_AVOID = t("Try to avoid this stretch");
export const STRETCH_PLANNING = t("Looking for a way round…");
export const STRETCH_NO_WAY = t("No better way round nearby.");
export const STRETCH_FAILED = t("Could not look for a way round just now.");
export const STRETCH_CLEAR = t("Clear");
