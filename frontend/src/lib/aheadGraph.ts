/**
 * The ride's graphs of the road ahead (Stephen 2026-11-03: "in the expand button set, put the ability to visualize
 * the next 2 miles by either traffic stress or elevation as a short graph on the bottom, off by default"; "Mass ride
 * can also add traffic flow and corker requirements"). Each graph is a bubble of its own in More (his pick on the
 * decision card, "Separate bubbles"); one graph shows at a time, and pressing the lit bubble turns it off.
 *
 * On a shared ride (2026-11-03: "include dots on the path that show all riders, scaled back to the last one"), the
 * graph starts at the rearmost rider instead of at you, and each rider is a dot on its axis.
 *
 * Everything here is pure: the window along the route, each graph's shapes in metres, and the words a screen reader
 * hears. AheadGraph.tsx draws them. Ride's languages apply to every phrase (lib/i18n.test.ts).
 */
import type { RouteProfile, RouteResponse, StressSpan, TrailLevelSpan } from "./api.ts";
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { metricFirst } from "./units.ts";
import { FEET_PER_METRE, METRES_PER_MILE, formatAxisFeet, formatAxisMetres, formatClimb, spokenDistance } from "./format.ts";
import { t } from "./i18n.ts";
import { FLOW_BANDS, chartKind, corkersFor, flowBand, gradeBand, shortStreet as abbreviate, usableProfile } from "./profileChart.ts";
import { spanClass, usableSpans } from "./routeColours.ts";
import { FACILITIES, HIGH_STRESS_LANE_MIN_TIER, MTB_LEVELS, MTB_TRAIL, relativeLuminance } from "../stressStyle.js";

export type AheadView = "stress" | "elevation" | "flow" | "corkers";

/** How far ahead each graph looks: 2 miles. */
export const AHEAD_M = 2 * METRES_PER_MILE;
/** A rider further than this from you along the route is left off (a dot snapped onto a far pass of a loop). */
export const RIDERS_REACH_M = 10 * METRES_PER_MILE;
/** A rider's dot further than this from the route line is not on it, so it is left off. */
export const RIDER_OFF_ROUTE_M = 60;

export const AHEAD_KEY = "routemaker.ride.ahead";
const VIEWS: readonly AheadView[] = ["stress", "elevation", "flow", "corkers"];

/**
 * The graphs on (Stephen 2026-11-03: "Have each graph share the same x axis, so it only needs to be labeled once": they
 * stack, one axis under them all), kept on this device in More's order; none, the default, is off.
 */
export function readAhead(store: KeyValueStore | null = browserStore()): AheadView[] {
  try {
    const kept = (store?.getItem(AHEAD_KEY) ?? "").split(",");
    return VIEWS.filter((view) => kept.includes(view));
  } catch {
    return [];
  }
}

export function writeAhead(views: readonly AheadView[], store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(AHEAD_KEY, VIEWS.filter((view) => views.includes(view)).join(","));
  } catch {
    // Blocked site data: the choice holds for this ride only.
  }
}

/** The bubble's name, said by a screen reader and shown as its tooltip. */
export const AHEAD_NAME: Record<AheadView, string> = {
  stress: t("Traffic stress graph"),
  elevation: t("Elevation graph"),
  flow: t("Rider flow graph"),
  corkers: t("Corkers graph"),
};
/** The word under the bubble. */
export const AHEAD_WORD: Record<AheadView, string> = {
  stress: t("Stress"),
  elevation: t("Elevation"),
  flow: t("Flow"),
  corkers: t("Corkers"),
};
/** The graph's heading. */
export const AHEAD_HEADING: Record<AheadView, string> = {
  stress: t("Traffic stress"),
  elevation: t("Elevation"),
  flow: t("Rider flow"),
  corkers: t("Corkers"),
};
/** Said when a graph comes on: "Traffic stress graph: on." */
export const aheadOn = (view: AheadView): string => t("{graph}: on.", { graph: AHEAD_NAME[view] });
export const aheadOff = (view: AheadView): string => t("{graph}: off.", { graph: AHEAD_NAME[view] });
/** The stacked graphs' name, for a screen reader. */
export const AHEAD_GROUP = t("Road ahead");
const NO_FIGURES = t("No figures for this stretch.");
export const AHEAD_YOU = t("You");

/** The graphs this route can draw, in More's order: Mass Ride's own two first, then stress and elevation. */
export function aheadViews(route: Pick<RouteResponse, "preset" | "profile" | "stress_spans">): AheadView[] {
  const views: AheadView[] = [];
  const profile = route.profile ?? null;
  if (chartKind(route) === "mass" && profile) {
    if ((profile.riders_per_min ?? []).some((r) => typeof r === "number")) views.push("flow");
    if (Array.isArray(profile.crossings)) views.push("corkers");
  }
  if (usableSpans(route.stress_spans)) views.push("stress");
  if (usableProfile(route)) views.push("elevation");
  return views;
}

export interface AheadWindow {
  fromM: number;
  toM: number;
  /** You, metres along. */
  youM: number;
  /** The other riders on the line, metres along, within the window. */
  riders: number[];
}

/**
 * The stretch the graph draws: from you (or the rearmost rider) to 2 miles ahead of you (or the frontmost rider),
 * never past the route's end; riders more than RIDERS_REACH_M away are left off.
 */
export function aheadWindow(youM: number, lengthM: number, ridersAlong: readonly number[] = []): AheadWindow {
  const near = ridersAlong.filter((m) => Number.isFinite(m) && Math.abs(m - youM) <= RIDERS_REACH_M);
  const fromM = Math.max(0, Math.min(youM, ...near));
  const toM = Math.min(lengthM, Math.max(youM + AHEAD_M, ...near));
  return { fromM, toM: Math.max(toM, fromM + 1), youM, riders: near.sort((a, b) => a - b) };
}

// ---- Traffic stress ----------------------------------------------------------------------------------------------

export interface StressBar {
  fromM: number;
  toM: number;
  /** 1 to 4.5 in half steps, 5 for Avoid; null where no segment was rated. */
  level: number | null;
  /** What the bar says on it: "2", "3.5", "A" (Avoid), "?" (not rated). */
  label: string;
  color: string;
  /** The label's colour on the bar: near-black or white, whichever reads better. */
  ink: string;
  /**
   * In the colour-blind-friendly palette, where a half step has no colour of its own: the next level's colour, drawn
   * as a dash on it, as the map and the route draw one (routeColours.ts halfDash; the owner 2026-10-31, "keep dashes
   * with the same rules"), and the outline under that dash where it needs one.
   */
  halfDash?: string;
  halfOutline?: string;
}

export function spanLevel(span: Pick<StressSpan, "tier" | "half" | "facility">): number | null {
  if (span.tier === null) return span.facility === "path" ? 1 : null;
  if (span.tier >= 5) return 5;
  return span.tier + (span.half === true ? 0.5 : 0);
}

export const INK_DARK = "#16181d";
export const INK_LIGHT = "#ffffff";
/** Near-black on a light bar, white on a dark one (the higher contrast of the two). */
export function inkOn(color: string): string {
  const l = relativeLuminance(color);
  return (l + 0.05) / (relativeLuminance(INK_DARK) + 0.05) >= (1.05) / (l + 0.05) ? INK_DARK : INK_LIGHT;
}

/** The route's sections within the window, joined where two in a row are the same level and colour. */
export function stressBars(spans: readonly StressSpan[], w: Pick<AheadWindow, "fromM" | "toM">): StressBar[] {
  const bars: StressBar[] = [];
  for (const span of spans) {
    const fromM = Math.max(span.from_m, w.fromM);
    const toM = Math.min(span.to_m, w.toM);
    if (toM <= fromM) continue;
    const level = spanLevel(span);
    const cls = spanClass(span);
    const color = cls.color;
    const last = bars[bars.length - 1];
    if (last && last.level === level && last.color === color && last.toM >= fromM - 0.5) {
      last.toM = toM;
      continue;
    }
    const label = level === null ? "?" : level === 5 ? "A" : String(level);
    bars.push({
      fromM,
      toM,
      level,
      label,
      color,
      ink: inkOn(color),
      ...(cls.halfDash ? { halfDash: cls.halfDash, ...(cls.halfOutline ? { halfOutline: cls.halfOutline } : {}) } : {}),
    });
  }
  return bars;
}

/** A bar's height, 0 to 1: higher stress, taller bar, so the level is never told by colour alone. */
export function barHeight(level: number | null): number {
  if (level === null) return 0.2;
  return 0.2 + ((Math.min(level, 5) - 1) / 4) * 0.8;
}

// "Avoid" and "LTS" are the same in every language (the catalogs keep both as they are).
const levelWords = (level: number) => (level === 5 ? "Avoid" : `LTS ${level}`);

/** "Mostly LTS 2, up to LTS 3.5 in 0.6 miles." */
export function stressSentence(bars: readonly StressBar[], youM: number): string {
  const ahead = bars.filter((b) => b.toM > youM && b.level !== null);
  if (!ahead.length) return NO_FIGURES;
  const metres = new Map<number, number>();
  for (const b of ahead) metres.set(b.level as number, (metres.get(b.level as number) ?? 0) + b.toM - Math.max(b.fromM, youM));
  const mostly = [...metres].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0][0];
  const top = Math.max(...metres.keys());
  if (top === mostly) return t("{level} the whole way.", { level: levelWords(mostly) });
  const first = ahead.find((b) => b.level === top) as StressBar;
  if (first.fromM <= youM + 15) return t("Mostly {level}, {top} here.", { level: levelWords(mostly), top: levelWords(top) });
  return t("Mostly {level}, up to {top} in {distance}.", {
    level: levelWords(mostly),
    top: levelWords(top),
    distance: spokenDistance(Math.max(0, first.fromM - youM)),
  });
}

// ---- Trails and bike lanes ---------------------------------------------------------------------------------------

/**
 * A trail or bike lane along the window (Stephen 2026-11-04, of the stress ribbon: "Include when it's a trail and when
 * there's bike infrastructure"), drawn as the map draws its rail: the trail solid, the protected lane in posts, the
 * painted lane in dots. A painted lane on LTS 4 or Avoid is left off, as the map leaves it off (OWNER-DECISIONS 275).
 */
export interface FacilityStretch {
  fromM: number;
  toM: number;
  facility: "path" | "protected" | "lane";
  /** The map's rail colour (stressStyle.js FACILITIES). */
  color: string;
}

/** What each is called when said: "Trail in 0.3 miles, for 0.4 miles." */
export const FACILITY_WORDS: Record<FacilityStretch["facility"], string> = {
  path: t("Trail"),
  protected: t("Protected bike lane"),
  lane: t("Painted bike lane"),
};

export function facilityStretches(
  spans: readonly Pick<StressSpan, "from_m" | "to_m" | "tier" | "facility">[],
  w: Pick<AheadWindow, "fromM" | "toM">,
): FacilityStretch[] {
  const out: FacilityStretch[] = [];
  for (const span of spans) {
    const facility = span.facility;
    if (facility !== "path" && facility !== "protected" && facility !== "lane") continue;
    if (facility === "lane" && typeof span.tier === "number" && span.tier >= HIGH_STRESS_LANE_MIN_TIER) continue;
    const fromM = Math.max(span.from_m, w.fromM);
    const toM = Math.min(span.to_m, w.toM);
    if (toM <= fromM) continue;
    const last = out[out.length - 1];
    if (last && last.facility === facility && last.toM >= fromM - 0.5) {
      last.toM = toM;
      continue;
    }
    const rail = FACILITIES.find((f: { facility: string }) => f.facility === facility) as { color: string };
    out.push({ fromM, toM, facility, color: rail.color });
  }
  return out;
}

/** The next two trails or bike lanes ahead, said: "Trail here, for 0.3 miles. Painted bike lane in 0.8 miles, for 500 feet." */
export function facilitySentence(stretches: readonly FacilityStretch[], youM: number): string {
  return facilitySentenceOf(
    stretches.map((s) => ({ fromM: s.fromM, toM: s.toM, kind: FACILITY_WORDS[s.facility] })),
    youM,
  );
}

function facilitySentenceOf(stretches: readonly { fromM: number; toM: number; kind: string }[], youM: number): string {
  return stretches
    .filter((s) => s.toM > youM + 15)
    .slice(0, 2)
    .map((s) =>
      s.fromM <= youM + 15
        ? t("{kind} here, for {distance}.", { kind: s.kind, distance: spokenDistance(s.toM - youM) })
        : t("{kind} in {distance}, for {length}.", {
            kind: s.kind,
            distance: spokenDistance(s.fromM - youM),
            length: spokenDistance(s.toM - s.fromM),
          }),
    )
    .join(" ");
}

// ---- Mountain-bike trail levels --------------------------------------------------------------------------------

/**
 * A mountain-bike trail along the window (Stephen 2026-11-07: "add mountain bike trail difficulty to the ribbon"; "Use
 * the trail color in the ribbon and brown dots that look like rocks on the edges"; "on unrated, give that a color too"):
 * the ribbon there in the map's trail colour (stressStyle.js MTB_LEVELS, MTB_TRAIL for unrated), and a rated level's
 * sign on it, a green circle, a blue square, a black diamond, a red double diamond, so the shape says it as well.
 */
export interface TrailLevelMark {
  fromM: number;
  toM: number;
  /** 1-4, or 0 on an unrated mountain-bike trail (the map's unrated colour, no sign). */
  level: 0 | 1 | 2 | 3 | 4;
  color: string;
}

/** What each level is called when said: "Blue trail (level 2) in 0.3 miles, for 0.4 miles." */
export const TRAIL_LEVEL_WORDS: Record<TrailLevelMark["level"], string> = {
  0: t("Unrated mountain bike trail"),
  1: t("Green trail (level 1)"),
  2: t("Blue trail (level 2)"),
  3: t("Black trail (level 3)"),
  4: t("Red trail (level 4)"),
};

/** The colour a level is drawn in, the map's: its level's, or the unrated trails' brown. */
export function trailLevelColor(level: number): string | null {
  if (level === 0) return MTB_TRAIL.color;
  return (MTB_LEVELS.find((l: { level: number }) => l.level === level) as { color: string } | undefined)?.color ?? null;
}

export function trailLevelMarks(spans: readonly TrailLevelSpan[], w: Pick<AheadWindow, "fromM" | "toM">): TrailLevelMark[] {
  const out: TrailLevelMark[] = [];
  for (const span of spans) {
    const level = span.level;
    if (level !== 0 && level !== 1 && level !== 2 && level !== 3 && level !== 4) continue;
    const fromM = Math.max(span.from_m, w.fromM);
    const toM = Math.min(span.to_m, w.toM);
    if (toM <= fromM) continue;
    const last = out[out.length - 1];
    if (last && last.level === level && last.toM >= fromM - 0.5) {
      last.toM = toM;
      continue;
    }
    out.push({ fromM, toM, level, color: trailLevelColor(level)! });
  }
  return out;
}

/** The next two trails ahead, said as the trails and lanes are: "Black trail (level 3) here, for 0.2 miles." */
export function trailLevelSentence(marks: readonly TrailLevelMark[], youM: number): string {
  return facilitySentenceOf(
    marks.map((m) => ({ fromM: m.fromM, toM: m.toM, kind: TRAIL_LEVEL_WORDS[m.level] })),
    youM,
  );
}

// ---- Elevation ---------------------------------------------------------------------------------------------------

export interface ElevationShape {
  /** [metres along, metres up], the window's ends included. */
  points: [number, number][];
  /** The steep stretches: 1 is 5% to 8%, 2 is 8% or more (profileChart.ts GRADE_BANDS). */
  steep: { fromM: number; toM: number; band: 1 | 2; gradePct: number }[];
  lowM: number;
  highM: number;
  /** Metres climbed from you to the window's end. */
  climbM: number;
  /** The steepest grade ahead of you, percent, or null. */
  steepestPct: number | null;
}

function lerp(a: number, b: number, f: number): number {
  return a + (b - a) * f;
}

export function elevationShape(profile: RouteProfile, w: Pick<AheadWindow, "fromM" | "toM" | "youM">): ElevationShape | null {
  const { m, elevation_m: e, grade_pct: g } = profile;
  const points: [number, number][] = [];
  const steep: ElevationShape["steep"] = [];
  let steepestPct: number | null = null;
  let climbM = 0;
  let prev: number | null = null;
  const at = (i: number, j: number, target: number): number | null => {
    const a = e[i];
    const b = e[j];
    if (a === null || b === null) return a ?? b;
    return m[j] > m[i] ? lerp(a, b, (target - m[i]) / (m[j] - m[i])) : a;
  };
  // The climb counts from your own height, read between the two samples either side of you.
  for (let i = 1; i < m.length && prev === null; i += 1) if (m[i - 1] <= w.youM && m[i] >= w.youM) prev = at(i - 1, i, w.youM);
  for (let i = 0; i < m.length; i += 1) {
    const inside = m[i] >= w.fromM && m[i] <= w.toM;
    if (i > 0 && m[i - 1] < w.fromM && m[i] > w.fromM) {
      const v = at(i - 1, i, w.fromM);
      if (v !== null) points.push([w.fromM, v]);
    }
    if (inside && e[i] !== null) points.push([m[i], e[i] as number]);
    if (i > 0 && m[i - 1] < w.toM && m[i] > w.toM) {
      const v = at(i - 1, i, w.toM);
      if (v !== null) points.push([w.toM, v]);
    }
    // The steep stretches, each step between two samples that overlaps the window; the steepest grade from you on.
    if (i > 0 && m[i] > w.fromM && m[i - 1] < w.toM && m[i] > m[i - 1]) {
      const band = gradeBand(g[i - 1]);
      const grade = g[i - 1];
      if (band > 0 && typeof grade === "number") {
        const fromM = Math.max(m[i - 1], w.fromM);
        const toM = Math.min(m[i], w.toM);
        const last = steep[steep.length - 1];
        if (last && last.band === band && Math.abs(last.toM - fromM) < 1) {
          last.toM = toM;
          last.gradePct = Math.max(last.gradePct, grade);
        } else steep.push({ fromM, toM, band: band as 1 | 2, gradePct: grade });
      }
      if (typeof grade === "number" && m[i] > w.youM) steepestPct = Math.max(steepestPct ?? 0, grade);
    }
    if (m[i] > w.youM && m[i] <= w.toM && e[i] !== null) {
      if (prev !== null && (e[i] as number) > prev) climbM += (e[i] as number) - prev;
      prev = e[i] as number;
    }
  }
  if (points.length < 2) return null;
  const ups = points.map((p) => p[1]);
  let lowM = Math.min(...ups);
  let highM = Math.max(...ups);
  // At least 20 m (66 ft) tall, so a flat stretch looks flat.
  if (highM - lowM < 20) {
    const mid = (highM + lowM) / 2;
    lowM = mid - 10;
    highM = mid + 10;
  }
  return { points, steep, lowM, highM, climbM, steepestPct };
}


/** "Climb 120 ft in the next 2 miles, steepest 7%." */
export function elevationSentence(shape: ElevationShape, w: Pick<AheadWindow, "youM" | "toM">): string {
  const distance = spokenDistance(w.toM - w.youM);
  if (shape.climbM * FEET_PER_METRE < 15) return t("Mostly level for the next {distance}.", { distance });
  return t("Climb {climb} in the next {distance}, steepest {grade}%.", { climb: formatClimb(shape.climbM), distance, grade: Math.round(shape.steepestPct ?? 0) });
}

// ---- Rider flow (Mass Ride) --------------------------------------------------------------------------------------

export interface FlowStep {
  fromM: number;
  toM: number;
  riders: number;
  color: string;
}

export function flowSteps(profile: RouteProfile, w: Pick<AheadWindow, "fromM" | "toM">): FlowStep[] {
  const r = profile.riders_per_min ?? [];
  const steps: FlowStep[] = [];
  for (let i = 1; i < profile.m.length; i += 1) {
    const fromM = Math.max(profile.m[i - 1], w.fromM);
    const toM = Math.min(profile.m[i], w.toM);
    const riders = r[i - 1];
    if (toM <= fromM || typeof riders !== "number") continue;
    steps.push({ fromM, toM, riders, color: flowBand(riders).color });
  }
  return steps;
}

/** The top of the flow graph: at least the "good" band's start (120), so the 60 and 120 guides are always in it. */
export function flowTop(steps: readonly FlowStep[]): number {
  return Math.max(FLOW_BANDS[2].from * 1.25, ...steps.map((s) => s.riders));
}

export function narrowest(steps: readonly FlowStep[], youM: number): FlowStep | null {
  const ahead = steps.filter((s) => s.toM > youM);
  return ahead.length ? ahead.reduce((a, b) => (b.riders < a.riders ? b : a)) : null;
}

/** "Narrowest 35 riders a minute, in 0.9 miles." */
export function flowSentence(steps: readonly FlowStep[], youM: number): string {
  const low = narrowest(steps, youM);
  if (!low) return NO_FIGURES;
  if (low.fromM <= youM + 15) return t("Narrowest {riders} riders a minute, here.", { riders: Math.round(low.riders) });
  return t("Narrowest {riders} riders a minute, in {distance}.", { riders: Math.round(low.riders), distance: spokenDistance(Math.max(0, low.fromM - youM)) });
}

// ---- Corkers (Mass Ride) -----------------------------------------------------------------------------------------

export interface CorkerMark {
  m: number;
  /** The cross street as mapped, or null. */
  street: string | null;
  corkers: number;
}

export function corkerMarks(profile: RouteProfile, w: Pick<AheadWindow, "fromM" | "toM">): CorkerMark[] {
  return (profile.crossings ?? [])
    .filter((c) => c.corkers_needed && c.m >= w.fromM && c.m <= w.toM)
    .map((c) => ({ m: c.m, street: c.street && c.street.trim() ? c.street : null, corkers: corkersFor(c) }));
}

export const AHEAD_NO_CORKERS = t("No junctions needing corkers ahead.");

/** A street name short enough to sit beside its marker: 16 characters at most. */
export function shortStreet(street: string): string {
  return street.length > 16 ? `${street.slice(0, 15).trimEnd()}\u2026` : street;
}

/** "Junctions needing corkers: 3. Next: 14th St in 0.4 miles, corkers: 2." */
export function corkerSentence(marks: readonly CorkerMark[], youM: number, complete: boolean): string {
  const ahead = marks.filter((c) => c.m >= youM);
  const partial = complete ? "" : ` ${t("Some junctions were not checked.")}`;
  if (!ahead.length) return AHEAD_NO_CORKERS + partial;
  const next = ahead[0];
  return (
    t("Junctions needing corkers: {count}. Next: {street} in {distance}, corkers: {corkers}.", {
      count: ahead.length,
      street: next.street ?? t("an unnamed street"),
      distance: spokenDistance(Math.max(0, next.m - youM)),
      corkers: next.corkers,
    }) + partial
  );
}

// ---- Riders and the axis -----------------------------------------------------------------------------------------

/** "Other riders shown: 4, the last 0.6 miles behind you." */
export function ridersSentence(w: AheadWindow): string {
  if (!w.riders.length) return "";
  const behind = w.riders.filter((m) => m < w.youM);
  if (!behind.length) return t("Other riders shown: {count}, all ahead of you.", { count: w.riders.length });
  return t("Other riders shown: {count}, the last {distance} behind you.", { count: w.riders.length, distance: spokenDistance(w.youM - behind[0]) });
}

// ---- The y axis (Stephen 2026-11-03: "put labels on the y axis") ----------------------------------------------------

/** The stress graph's levels, at the heights its bars are drawn: 1 to 4 and A for Avoid. */
export const STRESS_TICKS: readonly { level: number; label: string }[] = [
  { level: 1, label: "1" },
  { level: 2, label: "2" },
  { level: 3, label: "3" },
  { level: 4, label: "4" },
  { level: 5, label: "A" },
];

/** Two or three round heights in feet between the graph's bottom and top (metres, as drawn): "40 ft", "60 ft", "80 ft". */
export function elevationTicks(lowM: number, highM: number): { m: number; label: string }[] {
  // Metric mode (lib/units.ts): metres, on round steps.
  if (metricFirst()) {
    const stepM = [5, 10, 20, 25, 50, 100, 200, 250, 500].find((s) => (highM - lowM) / s <= 3) ?? 500;
    const out: { m: number; label: string }[] = [];
    for (let m = Math.ceil(lowM / stepM) * stepM; m <= highM; m += stepM) out.push({ m, label: formatAxisMetres(m) });
    return out;
  }
  const lowFt = lowM * FEET_PER_METRE;
  const highFt = highM * FEET_PER_METRE;
  const step = [10, 20, 25, 50, 100, 200, 250, 500, 1000].find((s) => (highFt - lowFt) / s <= 3) ?? 1000;
  const ticks: { m: number; label: string }[] = [];
  for (let ft = Math.ceil(lowFt / step) * step; ft <= highFt; ft += step) ticks.push({ m: ft / FEET_PER_METRE, label: formatAxisFeet(ft) });
  return ticks;
}

/** The flow graph's guides as its y labels: 60 and 120 riders a minute, and 200 where the graph reaches it. */
export function flowTicks(top: number): number[] {
  return [60, 120, 200].filter((r) => r < top);
}

// ---- Turns and junction markers (Stephen 2026-11-03: "an upcoming turns layer on the graph ... on the same scale. Black
// arrows for normal turns, with orange and red for more stressful. Include the other stress markers too.") ----------

export type TurnMovementKey = "left" | "right" | "bear_left" | "bear_right" | "uturn";
export interface TurnMark {
  m: number;
  /** A turn's arrow; null for a junction marker that is not a turn. */
  movement: TurnMovementKey | null;
  /** Orange (a triangle) and red (a diamond) as the planner's junction markers; "avoid" an Avoid stretch's start. */
  severity: "orange" | "red" | "avoid" | null;
}

interface CueLike {
  kind: string;
  atM: number;
  movement: TurnMovementKey | null;
  severity: "orange" | "red" | "avoid" | null;
  /** A jog's later turn: drawn with the jog's first, as the cue card draws it. */
  joined?: boolean;
  /** A short path straight across a road: not a turn on the card, so not one here. */
  cross?: string;
  source?: string;
}

/**
 * The turns and the stress markers in the window: each turn the card shows (a jog as one, a crossing straight over not
 * at all), each junction the planner flagged orange or red, and where an Avoid stretch starts. Not work zones or
 * hazards: they are not junctions.
 */
export function turnMarks(cues: readonly CueLike[], w: Pick<AheadWindow, "fromM" | "toM">): TurnMark[] {
  const marks: TurnMark[] = [];
  for (const c of cues) {
    if (c.atM < w.fromM || c.atM > w.toM) continue;
    if (c.kind === "turn") {
      if (c.movement !== null && !c.joined && !c.cross) marks.push({ m: c.atM, movement: c.movement, severity: c.severity === "orange" || c.severity === "red" ? c.severity : null });
    } else if (c.source === "junction" && (c.severity === "orange" || c.severity === "red")) {
      marks.push({ m: c.atM, movement: null, severity: c.severity });
    } else if (c.source === "avoid") {
      marks.push({ m: c.atM, movement: null, severity: "avoid" });
    }
  }
  return marks;
}

const RANK: Record<string, number> = { red: 3, orange: 2, avoid: 1 };

/** Marks closer than `minM` drawn as one, so they never pile up: the turn's arrow kept, in the worse colour of the two. */
export function spreadMarks(marks: readonly TurnMark[], minM: number): TurnMark[] {
  const out: TurnMark[] = [];
  for (const mark of marks) {
    const last = out[out.length - 1];
    if (last && mark.m - last.m < minM) {
      const severity = (RANK[mark.severity ?? ""] ?? 0) > (RANK[last.severity ?? ""] ?? 0) ? mark.severity : last.severity;
      out[out.length - 1] = { m: last.m, movement: last.movement ?? mark.movement, severity };
      continue;
    }
    out.push({ ...mark });
  }
  return out;
}

/** "Turns ahead: 3. Busy junctions: 1.", or nothing where there are neither. */
export function turnsSentence(marks: readonly TurnMark[], youM: number): string {
  const ahead = marks.filter((mark) => mark.m >= youM);
  const turns = ahead.filter((mark) => mark.movement !== null).length;
  const busy = ahead.filter((mark) => mark.severity === "orange" || mark.severity === "red").length;
  // A part that is zero is left out (the v0.19.0 release review: "Turns ahead: 0" said on a stretch with no turns).
  if (turns && busy) return t("Turns ahead: {turns}. Busy junctions: {busy}.", { turns, busy });
  if (turns) return t("Turns ahead: {turns}.", { turns });
  return busy ? t("Busy junctions: {busy}.", { busy }) : "";
}

/**
 * Only the y labels that keep `minGap` units from the last one kept, from the bottom up (the v0.19.0 release review:
 * 1, 2, 3, 4 and A stacked 9 units apart on a short plot nearly touched). The first is always kept.
 */
export function spacedTicks<T extends { y: number }>(ticks: readonly T[], minGap: number): T[] {
  const kept: T[] = [];
  for (const tick of [...ticks].sort((a, b) => b.y - a.y)) {
    if (!kept.length || kept[kept.length - 1].y - tick.y >= minGap) kept.push(tick);
  }
  return kept;
}

/** The tallest and shortest a graph's plot is drawn, in the drawing's units. */
export const PLOT_MAX = 56;
export const PLOT_MIN = 30;

/**
 * Each graph's plot height, so the stack fits `budget` units (the v0.19.0 release review: with two graphs on a small
 * phone the bottom panel pushed the side buttons over the cue card): as tall as PLOT_MAX where there is room, down to
 * PLOT_MIN; `fixed` is the drawing's height without the plots (the turns strip, the axis, each graph's name and gap).
 */
export function plotHeight(graphs: number, budget: number, fixed: number): number {
  if (graphs <= 0 || !Number.isFinite(budget)) return PLOT_MAX;
  return Math.max(PLOT_MIN, Math.min(PLOT_MAX, Math.floor((budget - fixed) / graphs)));
}

/**
 * How many of `count` graphs are drawn: as many as fit `budget` units with their plots at PLOT_MIN, so the text stays
 * readable on a small phone rather than every graph drawn too small to read; none where even one does not fit (the
 * drawing is never scaled down, which made its text too small to read). `overhead` is the drawing's
 * height without graphs (the turns strip and the axis) and `each` a graph's own (its name and the gap under it).
 */
export function graphsThatFit(count: number, budget: number, overhead: number, each: number): number {
  for (let k = count; k >= 1; k -= 1) if (overhead + k * (each + PLOT_MIN) <= budget) return k;
  return 0;
}

/** The graphs on but not drawn for want of room, in one line under the ones drawn (the v0.19.0 release review). */
export const aheadNoRoom = (views: readonly AheadView[]): string =>
  t("No room on this screen for: {graphs}.", { graphs: views.map((view) => AHEAD_HEADING[view]).join(", ") });

/** A corker's label as placed: its row under the markers (0 to rows - 1), or null where it is left off. */
export interface PlacedLabel {
  row: number | null;
  text: string;
}

/**
 * The corkers' street labels, short ("14th St NW", profileChart shortStreet), each beside its marker's stem on the
 * first of `rows` rows under the markers where it runs into no other label (the v0.19.0 release review: "14th Street
 * Nor…" over "13th Street Nor…" and over the markers), never across another marker's stem; one that fits on none
 * is left off, as the sentence names the
 * next junction. `at` is each marker's x and `charW` a character's width, in the drawing's units; a label goes right
 * of its stem, or left where `leftOf` says (near the drawing's right end).
 */
export function placeCorkerLabels(
  marks: readonly { at: number; street: string | null; leftOf: boolean }[],
  rows: number,
  charW: number,
): PlacedLabel[] {
  const taken: [number, number][][] = Array.from({ length: Math.max(0, rows) }, () => []);
  return marks.map((mark) => {
    const text = mark.street ? labelStreet(mark.street) : "";
    if (!text) return { row: null, text: "" };
    const width = text.length * charW;
    const span: [number, number] = mark.leftOf ? [mark.at - 5 - width, mark.at - 1] : [mark.at + 1, mark.at + 5 + width];
    // Never across another marker's stem, which runs through every row.
    if (marks.some((other) => other !== mark && other.at > span[0] - 2 && other.at < span[1] + 2)) return { row: null, text: "" };
    const row = taken.findIndex((spans) => spans.every(([a, b]) => span[1] <= a || span[0] >= b));
    if (row < 0) return { row: null, text: "" };
    taken[row].push(span);
    return { row, text };
  });
}

/** A street as a label beside a marker: abbreviated ("14th St NW"), 14 characters at most. */
export function labelStreet(street: string): string {
  const short = abbreviate(street.trim());
  return short.length > 14 ? `${short.slice(0, 13).trimEnd()}\u2026` : short;
}

export interface AxisTick {
  m: number;
  label: string;
}

// Decimals, not fractions (Stephen 2026-11-03: "Decimals and not fractions"): "0.5", "1", "1.5".
function mileLabel(miles: number): string {
  const sign = miles < 0 ? "\u2212" : "";
  const a = Math.round(Math.abs(miles) * 100) / 100;
  return sign + String(a);
}

/**
 * Tick steps, smallest first: the axis takes the first that puts at most six ticks on the window (five for the short
 * steps, so a few hundred feet left is not crowded with labels).
 */
const TICK_STEPS = [0.05, 0.1, 0.2, 0.5, 1, 2];

/**
 * Ticks every half mile (a mile, or two, on a long window), counted from you; the last one says "mi". Near the end of
 * a ride, where under two miles are left, the steps shrink (0.2, 0.1, 0.05) so the axis still has labels. In metric
 * mode (lib/units.ts) the same in kilometres, the last saying "km".
 */
export function axisTicks(w: Pick<AheadWindow, "fromM" | "toM" | "youM">): AxisTick[] {
  const unitM = metricFirst() ? 1000 : METRES_PER_MILE;
  const span = (w.toM - w.fromM) / unitM;
  const step = TICK_STEPS.find((s) => span / s <= (s < 0.5 ? 5 : 6)) ?? TICK_STEPS[TICK_STEPS.length - 1];
  const ticks: AxisTick[] = [];
  const first = Math.ceil((w.fromM - w.youM) / unitM / step - 1e-9) * step;
  for (let n = first; w.youM + n * unitM <= w.toM + 1; n += step) {
    if (Math.abs(n) < 1e-9) continue;
    ticks.push({ m: w.youM + n * unitM, label: mileLabel(n) });
  }
  if (ticks.length) ticks[ticks.length - 1].label += metricFirst() ? " km" : " mi";
  return ticks;
}
