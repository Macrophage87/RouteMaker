/**
 * The route chart's decisions, kept out of the component so a test runs them without a browser
 * (OWNER-DECISIONS 322, 323: the "Elevation and stress" chart; 328, 329, 332, 333: the Mass Ride
 * version, with the grade-adjusted riders-per-minute area and the major intersections).
 *
 * The API's `profile` (core.api.ProfileOut) is parallel arrays, one entry a router sample, every
 * `interval_m` (30 m) along each leg. Everything the chart says is made here from them: where a
 * rider is on the distance axis, what they hear at that spot, the climbs table, the summary, the
 * grade-band and riders-band shapes, and which junction labels are thinned out. Units are US
 * first with metric in brackets, as everywhere else (format.ts).
 */
import type { ProfileClimb, ProfileCrossing, RouteProfile, RouteResponse, StressSpan } from "./api.ts";
import { FEET_PER_METRE, METRES_PER_MILE, formatAxisDistance, formatClimb, formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";

// ---- The two charts ------------------------------------------------------------------------------

/** "stress": every ride type but Mass Ride (a stress strip under the elevation); "mass": the riders-per-minute area in its place. */
export type ChartKind = "stress" | "mass";

export function chartKind(route: Pick<RouteResponse, "preset">): ChartKind {
  return route.preset === "mass-ride" ? "mass" : "stress";
}

/** The fold's name, and its heading for a screen reader's list. */
export function foldName(kind: ChartKind): string {
  return kind === "mass" ? "Elevation and riders per minute" : "Elevation and stress";
}

/** The profile when it can be drawn: at least two samples with a height. */
export function usableProfile(route: Pick<RouteResponse, "profile">): RouteProfile | null {
  const p = route.profile;
  if (!p || !Array.isArray(p.m) || p.m.length < 2) return null;
  if (p.elevation_m.filter((e) => e !== null && Number.isFinite(e)).length < 2) return null;
  return p;
}

// ---- Grade bands (322: a pattern as well as a colour) --------------------------------------------

export interface GradeBand {
  /** 1: 5-8%, 2: 8% or more. */
  band: 1 | 2;
  label: string;
  words: string;
}

export const GRADE_BAND_FILL = "#f59e0b";
export const GRADE_BAND_STEEP = 5;
export const GRADE_BAND_STEEPER = 8;

export const GRADE_BANDS: readonly GradeBand[] = [
  { band: 1, label: "Grade 5-8%", words: "5 to 8 percent, in solid amber" },
  { band: 2, label: "Grade 8% or more", words: "8 percent or more, in hatched amber" },
];

/** 0 under 5%, 1 for 5-8%, 2 for 8% or more, by the size of the grade either way (routemaker.profile.band_of). */
export function gradeBand(gradePct: number | null | undefined): 0 | 1 | 2 {
  if (gradePct === null || gradePct === undefined || !Number.isFinite(gradePct)) return 0;
  const size = Math.abs(gradePct);
  if (size >= GRADE_BAND_STEEPER) return 2;
  return size >= GRADE_BAND_STEEP ? 1 : 0;
}

// ---- Riders per minute bands (327, 332) ----------------------------------------------------------

export interface FlowBand {
  index: 0 | 1 | 2 | 3;
  /** From this many riders a minute (inclusive). */
  from: number;
  /** Up to this many (exclusive); null: no upper end. */
  to: number | null;
  /** The 327 spectral colour. */
  color: string;
  /** The one word the announcement and the legend use. */
  word: string;
  /** The legend's words. */
  label: string;
  /** The pattern the fill carries as well as its colour (332). */
  pattern: "crosshatch" | "diagonal" | "dots" | "horizontal";
}

export const FLOW_BANDS: readonly FlowBand[] = [
  { index: 0, from: 0, to: 60, color: "#d7191c", word: "bottleneck", label: "Under 60: bottleneck", pattern: "crosshatch" },
  { index: 1, from: 60, to: 120, color: "#f28e2b", word: "tight", label: "60 to 120: tight", pattern: "diagonal" },
  { index: 2, from: 120, to: 200, color: "#1a9850", word: "good", label: "120 to 200: good", pattern: "dots" },
  { index: 3, from: 200, to: null, color: "#6a3d9a", word: "wide open", label: "200 and up: wide open", pattern: "horizontal" },
];

/** The thresholds the dotted guide lines are drawn at, each in its band's colour. */
export const FLOW_GUIDES: readonly { at: number; color: string }[] = [
  { at: 60, color: FLOW_BANDS[0].color },
  { at: 120, color: FLOW_BANDS[1].color },
  { at: 200, color: FLOW_BANDS[2].color },
];

export function flowBand(riders: number): FlowBand {
  let found = FLOW_BANDS[0];
  for (const band of FLOW_BANDS) if (riders >= band.from) found = band;
  return found;
}

// ---- Distance and the figures' words -------------------------------------------------------------

/** Miles to one place: "4.2". */
export function miles(metres: number): string {
  return (Math.max(metres, 0) / METRES_PER_MILE).toFixed(1);
}

/** "Mile 4.2", as the announcement says it. */
export function mileWord(metres: number): string {
  return `Mile ${miles(metres)}`;
}

/** A position on the distance axis, miles first: "4 mi (6.4 km)". */
export function axisDistance(metres: number): string {
  return formatAxisDistance(metres);
}

/** Elevation, feet first: "310 ft (94 m)". */
export function elevationWords(metres: number): string {
  return formatClimb(metres);
}

/** A grade the way a rider hears it: "grade 6%", "grade 6% downhill", "level". */
export function gradeWords(gradePct: number | null | undefined): string | null {
  if (gradePct === null || gradePct === undefined || !Number.isFinite(gradePct)) return null;
  const size = Math.round(Math.abs(gradePct));
  if (size === 0) return "level";
  return gradePct < 0 ? `grade ${size}% downhill` : `grade ${size}%`;
}

/** The stress tier at a position as it is said: "LTS 2", "Avoid", or null where not rated. */
export function tierWords(tier: number | null | undefined): string | null {
  if (tier === null || tier === undefined) return null;
  return tier >= 5 ? "Avoid" : `LTS ${tier}`;
}

export function tierAt(spans: readonly StressSpan[] | undefined, metres: number): number | null {
  if (!spans || spans.length === 0) return null;
  for (const span of spans) if (metres >= span.from_m && metres < span.to_m) return span.tier;
  const last = spans[spans.length - 1];
  return metres >= last.to_m ? last.tier : spans[0].tier;
}

// ---- Scales --------------------------------------------------------------------------------------

/** The elevation axis, whole 10-foot steps, at least 40 ft tall so a flat route does not look like a cliff; metres. */
export function elevationRange(profile: RouteProfile): { lo: number; hi: number } {
  const heights = profile.elevation_m.filter((e): e is number => e !== null && Number.isFinite(e));
  const loFt = Math.min(...heights) * FEET_PER_METRE;
  const hiFt = Math.max(...heights) * FEET_PER_METRE;
  let lo = Math.floor(loFt / 10) * 10;
  let hi = Math.ceil(hiFt / 10) * 10;
  if (hi - lo < 40) {
    const mid = (lo + hi) / 2;
    lo = Math.floor((mid - 20) / 10) * 10;
    hi = lo + 40;
  }
  return { lo: lo / FEET_PER_METRE, hi: hi / FEET_PER_METRE };
}

/** The riders axis, up to the next 50 above the highest figure and at least 250 (the bands reach 200). */
export function ridersTop(profile: RouteProfile): number {
  const values = (profile.riders_per_min ?? []).filter((v): v is number => v !== null);
  const top = values.length ? Math.max(...values) : 0;
  return Math.max(250, Math.ceil(top / 50) * 50);
}

export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0;
  return (v) => (span === 0 ? r0 : r0 + ((v - d0) / span) * (r1 - r0));
}

/** The route's length the x axis runs to: the API's distance, or the profile's last sample. */
export function axisLength(route: Pick<RouteResponse, "distance_m">, profile: RouteProfile): number {
  const last = profile.m[profile.m.length - 1] ?? 0;
  return Math.max(route.distance_m || 0, last, 1);
}

// ---- Shapes --------------------------------------------------------------------------------------

export interface Plot {
  x: (m: number) => number;
  y: (metres: number) => number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const f = (n: number): string => (Math.round(n * 100) / 100).toString();

/** The elevation line, broken where a height is missing: one "M ... L ..." path. */
export function elevationLine(profile: RouteProfile, plot: Plot): string {
  let d = "";
  let pen = false;
  profile.m.forEach((m, i) => {
    const e = profile.elevation_m[i];
    if (e === null || e === undefined || !Number.isFinite(e)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${f(plot.x(m))} ${f(plot.y(e))} `;
    pen = true;
  });
  return d.trim();
}

/** The elevation's fill: closed down to the baseline, one subpath for each unbroken run of heights. */
export function elevationArea(profile: RouteProfile, plot: Plot): string {
  const runs: [number, number][][] = [];
  let current: [number, number][] = [];
  profile.m.forEach((m, i) => {
    const e = profile.elevation_m[i];
    if (e === null || e === undefined || !Number.isFinite(e)) {
      if (current.length) runs.push(current);
      current = [];
      return;
    }
    current.push([m, e]);
  });
  if (current.length) runs.push(current);
  return runs
    .filter((run) => run.length >= 2)
    .map((run) => {
      const line = run.map(([m, e]) => `${f(plot.x(m))} ${f(plot.y(e))}`).join(" L");
      return `M${f(plot.x(run[0][0]))} ${f(plot.bottom)} L${line} L${f(plot.x(run[run.length - 1][0]))} ${f(plot.bottom)} Z`;
    })
    .join(" ");
}

export interface BandShape {
  band: 1 | 2;
  /** A closed polygon from the elevation line down to the baseline. */
  d: string;
}

/**
 * The steep sections as polygons under the elevation line, one for each unbroken run of one band
 * (OWNER-DECISIONS 322: 5-8% and 8% or more). A stretch between two samples is in the band of its
 * two grades' mean, so a one-sample spike does not paint a block.
 */
export function gradeBandShapes(profile: RouteProfile, plot: Plot): BandShape[] {
  const out: BandShape[] = [];
  let run: { band: 1 | 2; pts: [number, number][] } | null = null;
  const close = () => {
    if (run && run.pts.length >= 2) {
      const first = run.pts[0];
      const last = run.pts[run.pts.length - 1];
      const line = run.pts.map(([m, e]) => `${f(plot.x(m))} ${f(plot.y(e))}`).join(" L");
      out.push({ band: run.band, d: `M${f(plot.x(first[0]))} ${f(plot.bottom)} L${line} L${f(plot.x(last[0]))} ${f(plot.bottom)} Z` });
    }
    run = null;
  };
  for (let i = 1; i < profile.m.length; i += 1) {
    const e0 = profile.elevation_m[i - 1];
    const e1 = profile.elevation_m[i];
    const g0 = profile.grade_pct[i - 1];
    const g1 = profile.grade_pct[i];
    if (e0 == null || e1 == null || g0 == null || g1 == null || profile.m[i] <= profile.m[i - 1]) {
      close();
      continue;
    }
    const band = gradeBand((g0 + g1) / 2);
    if (band === 0) {
      close();
      continue;
    }
    if (run && run.band !== band) close();
    if (!run) run = { band, pts: [[profile.m[i - 1], e0]] };
    run.pts.push([profile.m[i], e1]);
  }
  close();
  return out;
}

export interface FlowShape {
  band: FlowBand;
  d: string;
}

/**
 * The riders-per-minute area (OWNER-DECISIONS 332): under the estimate, each stretch filled in its
 * band's colour. A segment that crosses a threshold is cut there, so the colour changes where the
 * line crosses 60, 120 or 200 and not at the next sample; each unbroken run of one band is one
 * polygon down to the baseline. `y` maps riders a minute to the plot.
 */
export function flowShapes(profile: RouteProfile, x: (m: number) => number, y: (riders: number) => number, baseline: number): FlowShape[] {
  const riders = profile.riders_per_min;
  if (!riders) return [];
  const edges = FLOW_GUIDES.map((g) => g.at);
  const out: FlowShape[] = [];
  let run: { band: FlowBand; pts: [number, number][] } | null = null;
  const close = () => {
    if (run && run.pts.length >= 2) {
      const first = run.pts[0];
      const last = run.pts[run.pts.length - 1];
      const line = run.pts.map(([px, py]) => `${f(px)} ${f(py)}`).join(" L");
      out.push({ band: run.band, d: `M${f(first[0])} ${f(baseline)} L${line} L${f(last[0])} ${f(baseline)} Z` });
    }
    run = null;
  };
  const push = (band: FlowBand, from: [number, number], to: [number, number]) => {
    if (run && run.band.index !== band.index) close();
    if (!run) run = { band, pts: [from] };
    run.pts.push(to);
  };
  for (let i = 1; i < profile.m.length; i += 1) {
    const r0 = riders[i - 1];
    const r1 = riders[i];
    if (r0 == null || r1 == null || profile.m[i] < profile.m[i - 1]) {
      close();
      continue;
    }
    // Cut the segment at every threshold between its two ends, in order from the first end.
    const cuts = edges.filter((e) => (r0 < e && r1 > e) || (r0 > e && r1 < e)).sort((a, b) => (r0 <= r1 ? a - b : b - a));
    let prev: [number, number] = [profile.m[i - 1], r0];
    const stops: [number, number][] = [...cuts.map((e): [number, number] => [profile.m[i - 1] + ((e - r0) / (r1 - r0)) * (profile.m[i] - profile.m[i - 1]), e]), [profile.m[i], r1]];
    for (const stop of stops) {
      const mid = (prev[1] + stop[1]) / 2;
      push(flowBand(mid), [x(prev[0]), y(prev[1])], [x(stop[0]), y(stop[1])]);
      prev = stop;
    }
  }
  close();
  return out;
}

/** The thin outline of the estimate's upper edge: broken where a figure is missing. */
export function flowLine(profile: RouteProfile, x: (m: number) => number, y: (riders: number) => number): string {
  const riders = profile.riders_per_min ?? [];
  let d = "";
  let pen = false;
  profile.m.forEach((m, i) => {
    const r = riders[i];
    if (r === null || r === undefined) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${f(x(m))} ${f(y(r))} `;
    pen = true;
  });
  return d.trim();
}

// ---- The stress strip ----------------------------------------------------------------------------

export interface StripSection {
  from_m: number;
  to_m: number;
  tier: number | null;
}

/** The route's stress sections for the strip, clipped to the axis; unknown stays a section of its own. */
export function stripSections(spans: readonly StressSpan[] | undefined, length: number): StripSection[] {
  if (!spans) return [];
  return spans
    .filter((s) => s.to_m > s.from_m && s.from_m < length)
    .map((s) => ({ from_m: Math.max(0, s.from_m), to_m: Math.min(length, s.to_m), tier: s.tier }));
}

// ---- The scrub: positions, steps, the map marker -------------------------------------------------

/** The nearest sample's index to a distance. */
export function nearestIndex(ms: readonly number[], metres: number): number {
  let lo = 0;
  let hi = ms.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (ms[mid] < metres) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(ms[lo - 1] - metres) <= Math.abs(ms[lo] - metres)) return lo - 1;
  return lo;
}

/** The step of an arrow key, metres: the smallest of 0.1, 0.25, 0.5, 1, 2 and 5 miles that crosses the route in 80 steps or fewer. */
export function stepLength(totalM: number): number {
  for (const miles of [0.1, 0.25, 0.5, 1, 2, 5]) {
    if (totalM / (miles * METRES_PER_MILE) <= 80) return miles * METRES_PER_MILE;
  }
  return 10 * METRES_PER_MILE;
}

/** A position after a key: arrows step, Page keys step five, Home and End go to the ends; null for any other key. */
export function positionAfterKey(key: string, at: number, totalM: number): number | null {
  const step = stepLength(totalM);
  const clamp = (m: number) => Math.min(Math.max(m, 0), totalM);
  switch (key) {
    case "ArrowRight":
    case "ArrowUp":
      return clamp(at + step);
    case "ArrowLeft":
    case "ArrowDown":
      return clamp(at - step);
    case "PageUp":
      return clamp(at + step * 5);
    case "PageDown":
      return clamp(at - step * 5);
    case "Home":
      return 0;
    case "End":
      return totalM;
    default:
      return null;
  }
}

/** The map point a distance along the route's line; `lineM` is the line's own length, so it is scaled onto the API's distance. */
export function lonLatAt(coordinates: readonly LonLat[], metres: number, totalM: number): LonLat | null {
  if (coordinates.length === 0) return null;
  if (coordinates.length === 1) return coordinates[0];
  const lengths: number[] = [0];
  for (let i = 1; i < coordinates.length; i += 1) lengths.push(lengths[i - 1] + haversineM(coordinates[i - 1], coordinates[i]));
  const lineM = lengths[lengths.length - 1];
  if (lineM <= 0) return coordinates[0];
  const target = Math.min(Math.max(totalM > 0 ? (metres / totalM) * lineM : 0, 0), lineM);
  const i = Math.max(1, nearestIndexAbove(lengths, target));
  const span = lengths[i] - lengths[i - 1];
  const t = span > 0 ? (target - lengths[i - 1]) / span : 0;
  const a = coordinates[i - 1];
  const b = coordinates[i];
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

function nearestIndexAbove(values: readonly number[], v: number): number {
  let lo = 0;
  let hi = values.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

// ---- What a rider hears at a position ------------------------------------------------------------

/** The next major intersection ahead of a position, as it is said. */
export function nextCrossing(crossings: readonly ProfileCrossing[] | null | undefined, metres: number): ProfileCrossing | null {
  if (!crossings) return null;
  // A little ahead of the spot, so standing on one names the one after it.
  return crossings.find((c) => c.m > metres + 1) ?? null;
}

export function crossingName(crossing: ProfileCrossing): string {
  return crossing.street && crossing.street.trim() ? crossing.street : "an unnamed street";
}

export function corkerWords(crossing: ProfileCrossing): string {
  return crossing.corkers_needed ? "corkers needed" : "no corkers needed";
}

export interface Reading {
  index: number;
  /** Metres along the route, the nearest sample's. */
  m: number;
  elevationM: number | null;
  gradePct: number | null;
  tier: number | null;
  riders: number | null;
  /** What the rider hears and sees, the whole sentence. */
  text: string;
}

/**
 * What the scrub says at a position (OWNER-DECISIONS 322, 328(c), 333): "Mile 4.2: elevation 310 ft
 * (94 m), grade 6%, LTS 2"; on a Mass Ride "Mile 1.1: grade 6%, about 90 riders per minute (tight).
 * Next: 14th St at mile 1.3, corkers needed".
 */
export function readingAt(route: RouteResponse, profile: RouteProfile, metres: number, kind: ChartKind = chartKind(route)): Reading {
  const index = nearestIndex(profile.m, metres);
  const m = profile.m[index];
  const elevationM = profile.elevation_m[index] ?? null;
  const gradePct = profile.grade_pct[index] ?? null;
  const tier = tierAt(route.stress_spans, m);
  const riders = profile.riders_per_min?.[index] ?? null;
  const parts: string[] = [];
  const grade = gradeWords(gradePct);
  let text: string;
  if (kind === "mass") {
    if (grade) parts.push(grade);
    parts.push(riders === null ? "riders per minute not known" : `about ${riders} riders per minute (${flowBand(riders).word})`);
    text = `${mileWord(m)}: ${parts.join(", ")}.`;
    const next = nextCrossing(profile.crossings, m);
    if (next) text += ` Next: ${crossingName(next)} at mile ${miles(next.m)}, ${corkerWords(next)}.`;
    else if (profile.crossings && profile.crossings.length > 0) text += " No major intersections ahead.";
  } else {
    if (elevationM !== null) parts.push(`elevation ${elevationWords(elevationM)}`);
    if (grade) parts.push(grade);
    const stress = tierWords(tier);
    parts.push(stress ?? "stress not rated");
    text = `${mileWord(m)}: ${parts.join(", ")}.`;
  }
  return { index, m, elevationM, gradePct, tier, riders, text };
}

// ---- The text alternative ------------------------------------------------------------------------

/** The steepest sample: its grade and where. */
export function steepest(profile: RouteProfile): { gradePct: number; m: number } | null {
  let best: { gradePct: number; m: number } | null = null;
  profile.grade_pct.forEach((g, i) => {
    if (g !== null && (best === null || Math.abs(g) > Math.abs(best.gradePct))) best = { gradePct: g, m: profile.m[i] };
  });
  return best;
}

function listWords(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** Where the route is LTS 3 or worse: the start miles of the first few such sections. */
export function busyPlaces(spans: readonly StressSpan[] | undefined, max = 3): { places: string[]; more: number } {
  const busy = (spans ?? []).filter((s) => s.tier !== null && s.tier >= 3);
  return { places: busy.slice(0, max).map((s) => miles(s.from_m)), more: Math.max(0, busy.length - max) };
}

/** The share of the route on each tier, as words: "61% LTS 1, 30% LTS 2". */
export function stressShares(spans: readonly StressSpan[] | undefined, length: number): string {
  const metres = new Map<number | null, number>();
  for (const s of spans ?? []) metres.set(s.tier, (metres.get(s.tier) ?? 0) + (s.to_m - s.from_m));
  const total = [...metres.values()].reduce((a, b) => a + b, 0) || length || 1;
  const parts: string[] = [];
  for (const tier of [1, 2, 3, 4, 5]) {
    const share = ((metres.get(tier) ?? 0) / total) * 100;
    if (share >= 0.5) parts.push(`${Math.round(share)}% ${tierWords(tier)}`);
  }
  return parts.join(", ");
}

/**
 * The summary: the chart's text alternative, said before it and kept beside it. Elevation range and
 * the steepest section; then the stress along the route, or on a Mass Ride the narrowest point and
 * the climbs' cost.
 */
export function summaryText(route: RouteResponse, profile: RouteProfile, kind: ChartKind = chartKind(route)): string {
  const total = axisLength(route, profile);
  const heights = profile.elevation_m.filter((e): e is number => e !== null);
  const lo = Math.min(...heights);
  const hi = Math.max(...heights);
  const sentences = [`Over ${formatDistance(total)}, elevation runs from ${elevationWords(lo)} to ${elevationWords(hi)}.`];
  const steep = steepest(profile);
  if (steep && Math.abs(steep.gradePct) >= 1) {
    sentences.push(`The steepest section is ${Math.round(Math.abs(steep.gradePct))}% ${steep.gradePct < 0 ? "downhill" : "uphill"} at mile ${miles(steep.m)}.`);
  } else {
    sentences.push("The route is close to level.");
  }
  const climbs = profile.climbs.length;
  sentences.push(climbs === 0 ? "No sustained climbs." : `${climbs} sustained ${climbs === 1 ? "climb" : "climbs"}, listed in the table.`);
  if (kind === "mass") {
    const flow = profile.flow;
    if (flow && flow.narrowest_riders_per_min !== null && flow.narrowest_m !== null) {
      sentences.push(
        `The narrowest point carries about ${flow.narrowest_riders_per_min} riders per minute (${flowBand(flow.narrowest_riders_per_min).word}) at mile ${miles(flow.narrowest_m)}` +
          (flow.typical_riders_per_min !== null ? `; the typical stretch about ${flow.typical_riders_per_min}.` : "."),
      );
    }
    const crossings = profile.crossings ?? [];
    if (crossings.length > 0) {
      const needing = crossings.filter((c) => c.corkers_needed).length;
      sentences.push(`${crossings.length} major ${crossings.length === 1 ? "intersection" : "intersections"}, ${needing === 0 ? "none needing corkers" : `${needing} needing corkers`}.`);
    }
  } else {
    const shares = stressShares(route.stress_spans, total);
    if (shares) sentences.push(`Traffic stress along it: ${shares}.`);
    const { places, more } = busyPlaces(route.stress_spans);
    if (places.length > 0) {
      sentences.push(`LTS 3 or worse starts at mile${places.length === 1 ? "" : "s"} ${listWords(places)}${more > 0 ? `, and ${more} more ${more === 1 ? "place" : "places"}` : ""}.`);
    }
  }
  return sentences.join(" ");
}

export interface ClimbRow {
  start: string;
  length: string;
  gain: string;
  average: string;
  maximum: string;
  stress: string;
  /** Mass Ride only: "52% fewer riders, down to 90 a minute"; null off it. */
  capacity: string | null;
}

/** The climbs table (OWNER-DECISIONS 322: start mile, length, gain, average and maximum grade, stress; 328(c): the capacity drop). */
export function climbRows(profile: RouteProfile, kind: ChartKind): ClimbRow[] {
  return profile.climbs.map((c: ProfileClimb) => ({
    start: `Mile ${miles(c.from_m)}`,
    length: formatDistance(c.to_m - c.from_m),
    gain: formatClimb(c.gain_m),
    average: `${Math.round(c.avg_grade_pct)}%`,
    maximum: `${Math.round(c.max_grade_pct)}%`,
    stress: tierWords(c.tier) ?? "Not rated",
    capacity:
      kind !== "mass"
        ? null
        : c.capacity_drop_pct === null || c.capacity_drop_pct === undefined
          ? "Not known"
          : `${c.capacity_drop_pct}% fewer riders${c.min_riders_per_min != null ? `, down to ${c.min_riders_per_min} a minute` : ""}`,
  }));
}

export interface CrossingRow {
  mile: string;
  street: string;
  marker: string;
  corkers: string;
}

/** The marker word: its shape and its meaning, so the table says what the chart draws. */
export function crossingMarkerWords(crossing: ProfileCrossing): string {
  if (crossing.severity === "red") return "Very high stress (red diamond)";
  if (crossing.severity === "orange") return "Higher stress (orange triangle)";
  const control = crossing.control === "signal" ? "traffic signal" : crossing.control === "none" ? "crossing" : "stop sign";
  return `Major crossing, ${control} (dot)`;
}

export function crossingRows(profile: RouteProfile): CrossingRow[] {
  return (profile.crossings ?? []).map((c) => ({
    mile: `Mile ${miles(c.m)}`,
    street: crossingName(c),
    marker: crossingMarkerWords(c),
    corkers: c.corkers_needed ? "Corkers needed" : "No corkers needed",
  }));
}

// ---- Thinning the junction labels (333) ----------------------------------------------------------

/** The abbreviations a street name is written in on the chart ("15th Street Northwest" is "15th St NW"); the tables and the sentence say it in full. */
const ABBREVIATIONS: Readonly<Record<string, string>> = {
  Street: "St",
  Avenue: "Ave",
  Boulevard: "Blvd",
  Road: "Rd",
  Drive: "Dr",
  Place: "Pl",
  Court: "Ct",
  Lane: "Ln",
  Parkway: "Pkwy",
  Northwest: "NW",
  Northeast: "NE",
  Southwest: "SW",
  Southeast: "SE",
};

export function shortStreet(name: string): string {
  return name
    .split(/\s+/)
    .map((word) => ABBREVIATIONS[word] ?? word)
    .join(" ");
}

export interface PlacedCrossing {
  crossing: ProfileCrossing;
  x: number;
  /** Whether its street name is written (a tick and a marker are always drawn). */
  labelled: boolean;
  /** The line the name is on: 0, or 1 under it where the first line was taken. */
  row: 0 | 1;
  /** What is written: the street, abbreviated. */
  label: string;
  /** Where the text hangs from: centred, or kept inside the plot at its edges. */
  anchor: "start" | "middle" | "end";
}

/** An approximate width of a label in the chart's 10-pixel type. */
export function labelWidth(text: string): number {
  return text.length * 5.4 + 4;
}

const SEVERITY_RANK: Record<string, number> = { red: 2, orange: 1 };

/**
 * Which junction names fit (OWNER-DECISIONS 333: "Thin out the labels when they would collide").
 * Every junction keeps its tick and marker. Names are placed in order of importance (very high
 * stress, higher stress, then the rest, and by route order within each), each on the first of two
 * lines where it clears what is there, and dropped when it clears neither; the table lists every one.
 */
export function placeCrossings(crossings: readonly ProfileCrossing[], x: (m: number) => number, left: number, right: number): PlacedCrossing[] {
  const placed: PlacedCrossing[] = crossings.map((crossing) => ({
    crossing,
    x: x(crossing.m),
    labelled: false,
    row: 0,
    label: shortStreet(crossingName(crossing)),
    anchor: "middle",
  }));
  const order = placed
    .map((p, i) => ({ p, i }))
    .sort((a, b) => (SEVERITY_RANK[b.p.crossing.severity ?? ""] ?? 0) - (SEVERITY_RANK[a.p.crossing.severity ?? ""] ?? 0) || a.i - b.i);
  const taken: [number, number][][] = [[], []];
  for (const { p } of order) {
    const w = labelWidth(p.label);
    let from = p.x - w / 2;
    let to = p.x + w / 2;
    if (from < left) {
      from = left;
      to = left + w;
      p.anchor = "start";
    } else if (to > right) {
      to = right;
      from = right - w;
      p.anchor = "end";
    }
    const row = taken.findIndex((line) => !line.some(([a, b]) => from < b + 4 && to > a - 4));
    if (row < 0) continue;
    taken[row].push([from, to]);
    p.labelled = true;
    p.row = row === 1 ? 1 : 0;
  }
  return placed;
}
