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
import type { ProfileClimb, ProfileCrossing, ProfileRange, RouteProfile, RouteResponse, StressSpan } from "./api.ts";
import { FEET_PER_METRE, METRES_PER_MILE, formatAxisDistance, formatClimb, formatDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import {
  NARROWEST_BOTH,
  NARROWEST_FLAT,
  NARROWEST_HILLS,
  OUTSIDE_DC_FIGURES,
  capacityPair,
  capacitySummary,
  capitalise,
  typicalLines,
  type CapacityPair,
} from "./massCapacity.ts";
import { spanClass } from "./routeColours.ts";

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
  /** 1: 5% to 8%, 2: 8% or more. */
  band: 1 | 2;
  /** The key's words, said as they read ("Grade 5% to 8%", not "5-8%", which a screen reader may say as minus). */
  label: string;
  /** The pattern over the amber, so the band is not told by colour alone (the amber is close to the grey area in the light theme). */
  pattern: "dots" | "hatch";
}

export const GRADE_BAND_FILL = "#f59e0b";
export const GRADE_BAND_STEEP = 5;
export const GRADE_BAND_STEEPER = 8;

export const GRADE_BANDS: readonly GradeBand[] = [
  { band: 1, label: "Grade 5% to 8%", pattern: "dots" },
  { band: 2, label: "Grade 8% or more", pattern: "hatch" },
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

/** The bands' edges and words are `routemaker.flow.BAND_EDGES` and `BAND_WORDS`; tests/test_profile_flow.py holds this list to them. */
export const FLOW_BANDS: readonly FlowBand[] = [
  { index: 0, from: 0, to: 60, color: "#d7191c", word: "bottleneck", label: "Under 60: bottleneck", pattern: "crosshatch" },
  { index: 1, from: 60, to: 120, color: "#f28e2b", word: "tight", label: "60 to 120: tight", pattern: "diagonal" },
  { index: 2, from: 120, to: 200, color: "#1a9850", word: "good", label: "120 to 200: good", pattern: "dots" },
  { index: 3, from: 200, to: null, color: "#6a3d9a", word: "wide open", label: "200 and up: wide open", pattern: "horizontal" },
];

/**
 * The thresholds the dotted guide lines are drawn at (329: "labelled in the band colours"). The label's
 * figure is in the text colour, beside a swatch of the band's colour (the a11y review's S1: the colours
 * are 2.4:1 to 3.7:1 as 10 px text); the line itself is drawn in its CSS class, `pc-guide-N`, which is
 * the band colour wherever that is 3:1 on the panel and a darker shade of it where not (orange in the
 * light theme).
 */
export const FLOW_GUIDES: readonly { at: number; color: string; band: 0 | 1 | 2 }[] = [
  { at: 60, color: FLOW_BANDS[0].color, band: 0 },
  { at: 120, color: FLOW_BANDS[1].color, band: 1 },
  { at: 200, color: FLOW_BANDS[2].color, band: 2 },
];

/**
 * Avoid on the riders track, and on the route line (OWNER-DECISIONS 397: "Avoid as a single color
 * should be magenta. It's a very striking danger color. Only do if a route uses it"; it replaces the
 * coral of 325). The magenta is the route line's (routeColours.ts ROUTE_AVOID_MAGENTA; a test holds
 * the two equal). Its AVOID word is white, 4.9:1 on it; it is 4.9:1 on the light panel and 3.4:1 on
 * the dark one. No fill can be 3:1 from every riders band (the bottleneck red is 1.05:1 from it, the
 * orange 2.0:1, and the bands span too wide a luminance for any one colour), so each Avoid block has
 * a two-tone frame, near-black outside and white inside: whichever band or panel it touches, one of
 * the two is 3:1 or more from it (`AVOID_FRAME`, white), and the white is 4.9:1 from the magenta. It
 * also has a texture of its own (dark chevrons, not the bottleneck's cross-hatch) and its word.
 */
export const AVOID_FILL = "#d6008f";
export const AVOID_INK = "#ffffff";
export const AVOID_FRAME = "#1b1e24";
/** An Avoid block is drawn at least this wide (viewBox units), centred on its stretch, so a short one still carries its "A". */
export const AVOID_MIN_WIDTH = 10;
/** The width the whole word AVOID needs in the chart's bold 11-unit type; a narrower block says "A". */
export const AVOID_WORD_WIDTH = 36;

/** The label an Avoid block of this width carries: the word, or its letter on a narrow block, so a short Avoid is never told by colour alone. */
export function avoidLabel(width: number): string {
  return width >= AVOID_WORD_WIDTH ? "AVOID" : "A";
}

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

/** The stress section at a position: the one it is in (a section's end is the next one's start), the last past the end, the first before the start. */
export function spanAt(spans: readonly StressSpan[] | undefined, metres: number): StressSpan | null {
  if (!spans || spans.length === 0) return null;
  for (const span of spans) if (metres >= span.from_m && metres < span.to_m) return span;
  const last = spans[spans.length - 1];
  return metres >= last.to_m ? last : spans[0];
}

export function tierAt(spans: readonly StressSpan[] | undefined, metres: number): number | null {
  return spanAt(spans, metres)?.tier ?? null;
}

/**
 * A stress section as it is said, the map's way (routeColours.ts spanClass: unpaved first, then
 * Avoid, then a path, then the tier; the a11y review's S7): "traffic-free path", "unpaved, LTS 2",
 * "unpaved traffic-free path", "LTS 3", "Avoid", "unpaved, Avoid"; null where not rated. A path
 * rated Avoid (only an access override makes one) is said "Avoid", as it is drawn, never
 * "traffic-free path" (r4 accessibility, A-SF1).
 */
export function sectionWords(span: Pick<StressSpan, "tier" | "facility"> & Partial<Pick<StressSpan, "unpaved">> | null | undefined): string | null {
  if (!span) return null;
  const path = span.facility === "path" && span.tier !== 5;
  if (span.unpaved === true) {
    if (path) return "unpaved traffic-free path";
    const tier = tierWords(span.tier);
    return tier ? `unpaved, ${tier}` : null;
  }
  if (path) return "traffic-free path";
  return tierWords(span.tier);
}

/** Whether a position lies in one of the ranges (both ends included). */
export function inRanges(ranges: readonly ProfileRange[] | null | undefined, metres: number): boolean {
  return (ranges ?? []).some((r) => metres >= r.from_m && metres <= r.to_m);
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
  /** The section's facility and surface, so the strip draws a path and an unpaved stretch as the map does (S7). */
  facility: StressSpan["facility"];
  unpaved: boolean | null;
}

/** The route's stress sections for the strip, clipped to the axis; unknown stays a section of its own. */
export function stripSections(spans: readonly StressSpan[] | undefined, length: number): StripSection[] {
  if (!spans) return [];
  return spans
    .filter((s) => s.to_m > s.from_m && s.from_m < length)
    .map((s) => ({ from_m: Math.max(0, s.from_m), to_m: Math.min(length, s.to_m), tier: s.tier, facility: s.facility ?? null, unpaved: s.unpaved ?? null }));
}

/** The strip key's entries: the first section of each of the map's classes the strip shows (routeColours.ts spanClass), in the key's order (`sectionRank`). */
export function stripKey(sections: readonly StripSection[]): StripSection[] {
  const seen = new Map<string, StripSection>();
  for (const s of sections) {
    const key = spanClass(s).key;
    if (!seen.has(key)) seen.set(key, s);
  }
  return [...seen.values()].sort((a, b) => sectionRank(a) - sectionRank(b));
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

/** The places the letter keys jump to: the climbs' starts, and on a Mass Ride the major intersections (a11y review N4). */
export interface JumpTargets {
  climbs?: readonly number[];
  crossings?: readonly number[];
}

export function jumpTargets(profile: RouteProfile): JumpTargets {
  return { climbs: profile.climbs.map((c) => c.from_m), crossings: (profile.crossings ?? []).map((c) => c.m) };
}

/** The first target after a position, or the last before it; null where there is none that way. */
function jump(targets: readonly number[] | undefined, at: number, forward: boolean): number | null {
  const sorted = [...(targets ?? [])].sort((a, b) => a - b);
  if (forward) return sorted.find((m) => m > at + 1) ?? null;
  for (let i = sorted.length - 1; i >= 0; i -= 1) if (sorted[i] < at - 1) return sorted[i];
  return null;
}

/**
 * A position after a key: arrows step, Page keys step five, Home and End go to the ends; C and
 * Shift+C the next and previous climb, I and Shift+I the next and previous major intersection.
 * Null for any other key, or a jump with nowhere to go. `shift` is the event's own Shift key, so
 * Caps Lock does not turn C into "previous" (the a11y re-review's N-f); without it the key's case
 * is read.
 */
export function positionAfterKey(key: string, at: number, totalM: number, targets: JumpTargets = {}, shift?: boolean): number | null {
  const step = stepLength(totalM);
  const clamp = (m: number) => Math.min(Math.max(m, 0), totalM);
  switch (key) {
    case "c":
    case "C":
    case "i":
    case "I": {
      const forward = shift === undefined ? key === key.toLowerCase() : !shift;
      const to = jump(key.toLowerCase() === "c" ? targets.climbs : targets.crossings, at, forward);
      return to === null ? null : clamp(to);
    }
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

/** The listed climb a position is on, or null. */
export function climbAt(profile: RouteProfile, metres: number): ProfileClimb | null {
  return profile.climbs.find((c) => metres >= c.from_m && metres <= c.to_m) ?? null;
}

/**
 * The riders clause of the Mass Ride sentence: "about 90 riders per minute (tight, slowed by the
 * climb)" (the mock-up's wording, a11y N6 and spec NIT 1), "marked Avoid, no capacity given" on a stretch
 * marked Avoid (325), and "riders per minute not known" where the width is not known. Never a figure
 * where there is none: an unknown is never "about 0 ... (bottleneck)".
 */
export function ridersWords(profile: RouteProfile, riders: number | null, metres: number, gradePct: number | null): string {
  if (inRanges(profile.outside_dc, metres)) return "outside DC, no riders-per-minute figure yet";
  if (inRanges(profile.avoid, metres)) return "marked Avoid, no capacity given";
  if (riders === null || !Number.isFinite(riders)) return "riders per minute not known";
  const reasons = [flowBand(riders).word];
  const climb = climbAt(profile, metres);
  if (climb && gradePct !== null && gradePct > 1 && (climb.capacity_drop_pct ?? 0) > 0) reasons.push("slowed by the climb");
  else if (gradePct !== null && gradePct < -4) reasons.push("spaced out for the descent");
  return `about ${riders} riders per minute (${reasons.join(", ")})`;
}

/** Whether the major intersections are the flagged ones only (`crossings_complete: false`: finding the busy-road ones failed), so the list may be incomplete (correctness re-review R3). */
export function crossingsPartial(profile: RouteProfile): boolean {
  return profile.crossings !== null && profile.crossings !== undefined && profile.crossings_complete === false;
}

/**
 * What the junctions in a partial list are, in the key's words ("Higher stress junction", "Very high
 * stress junction"), not "flagged" (r3 accessibility, N2).
 */
export const PARTIAL_JUNCTIONS = "higher or very high stress junction";

/**
 * The intersections clause (333, 396): the next major intersection and whether corkers are needed;
 * "Intersections not checked." where they were not read (`crossings: null`, correctness S2), and
 * a note where the way ahead runs over a leg that could not be traced. Nothing on a route that has
 * none at all (the summary says so). Where only the higher and very high stress junctions were
 * found, it names them so ("Next higher or very high stress junction: ...") and never says there
 * are no major intersections ahead. The "may be incomplete" caveat is said once, in the summary and
 * the table's caption, not on every arrow press (r3 accessibility, N2); with an untraced stretch
 * also ahead, it says both (r3 correctness).
 */
export function crossingClause(profile: RouteProfile, metres: number): string {
  const crossings = profile.crossings;
  if (crossings === null || crossings === undefined) return " Intersections not checked.";
  const next = nextCrossing(crossings, metres);
  const unchecked = profile.unchecked ?? [];
  const partial = crossingsPartial(profile);
  if (next) {
    const gap = unchecked.some((r) => r.to_m > metres && r.from_m < next.m);
    return ` Next${partial ? ` ${PARTIAL_JUNCTIONS}` : ""}: ${crossingName(next)} at mile ${miles(next.m)}, ${corkerWords(next)}.${gap ? " Part of the way to it was not checked for intersections." : ""}`;
  }
  const gapAhead = unchecked.some((r) => r.to_m > metres);
  if (partial) return ` No ${PARTIAL_JUNCTIONS}s ahead${gapAhead ? "; part of the way ahead was not checked for intersections" : ""}.`;
  if (gapAhead) return " Part of the way ahead was not checked for intersections.";
  return crossings.length > 0 ? " No major intersections ahead." : "";
}

/**
 * What the scrub says at a position (OWNER-DECISIONS 322, 328(c), 333): "Mile 4.2: elevation 310 ft
 * (94 m), grade 6%, LTS 2"; on a Mass Ride "Mile 1.1: grade 6%, about 90 riders per minute (tight,
 * slowed by the climb). Next: 14th St at mile 1.3, corkers needed".
 */
export function readingAt(route: RouteResponse, profile: RouteProfile, metres: number, kind: ChartKind = chartKind(route)): Reading {
  const index = nearestIndex(profile.m, metres);
  const m = profile.m[index];
  const elevationM = profile.elevation_m[index] ?? null;
  const gradePct = profile.grade_pct[index] ?? null;
  const span = spanAt(route.stress_spans, m);
  const tier = span?.tier ?? null;
  const riders = profile.riders_per_min?.[index] ?? null;
  const parts: string[] = [];
  const grade = gradeWords(gradePct);
  let text: string;
  if (kind === "mass") {
    if (grade) parts.push(grade);
    parts.push(ridersWords(profile, riders, m, gradePct));
    text = `${mileWord(m)}: ${parts.join(", ")}.${crossingClause(profile, m)}`;
  } else {
    if (elevationM !== null) parts.push(`elevation ${elevationWords(elevationM)}`);
    if (grade) parts.push(grade);
    parts.push(sectionWords(span) ?? "stress not rated");
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

/** A stress section's place in the key's order (`stripKey`): a path first, then the tiers, each unpaved after its paved tier; a path rated Avoid is Avoid. */
function sectionRank(span: Pick<StressSpan, "tier" | "facility"> & Partial<Pick<StressSpan, "unpaved">>): number {
  return (span.facility === "path" && span.tier !== 5 ? 0 : (span.tier ?? 99)) + (span.unpaved === true ? 0.5 : 0);
}

/**
 * The share of the route in each of the map's classes, as the key and the sentence say them
 * (`sectionWords`; the a11y re-review's S1): "19% traffic-free path, 69% LTS 2, 12% LTS 3", in the
 * key's order. A traffic-free path is never said as "LTS 1". Unrated sections count in the whole but
 * are not listed.
 */
export function stressShares(spans: readonly StressSpan[] | undefined, length: number): string {
  const metres = new Map<string, { m: number; rank: number }>();
  let total = 0;
  for (const s of spans ?? []) {
    const m = s.to_m - s.from_m;
    total += m;
    const words = sectionWords(s);
    if (!words) continue;
    const seen = metres.get(words);
    metres.set(words, { m: (seen?.m ?? 0) + m, rank: Math.min(seen?.rank ?? Infinity, sectionRank(s)) });
  }
  const whole = total || length || 1;
  return [...metres.entries()]
    .sort((a, b) => a[1].rank - b[1].rank)
    .map(([words, { m }]) => ({ words, share: (m / whole) * 100 }))
    .filter(({ share }) => share >= 0.5)
    .map(({ words, share }) => `${Math.round(share)}% ${words}`)
    .join(", ");
}

/**
 * A climb's Stress cell, the map's way (the a11y re-review's S1): the most stressful section it rides
 * over, said as the key says it ("Traffic-free path", "LTS 3", "Unpaved, LTS 2"); a road outranks a
 * path of the same tier. The API's own tier where the sections are not known.
 */
export function climbStress(climb: Pick<ProfileClimb, "from_m" | "to_m" | "tier">, spans?: readonly StressSpan[]): string {
  const on = (spans ?? []).filter((s) => s.tier !== null && s.from_m < climb.to_m && s.to_m > climb.from_m);
  const worst = on.reduce<StressSpan | null>((best, s) => {
    const score = (x: StressSpan) => (x.tier ?? 0) + (x.facility === "path" ? 0 : 0.25);
    return best === null || score(s) > score(best) ? s : best;
  }, null);
  const words = worst ? sectionWords(worst) : tierWords(climb.tier);
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Not rated";
}

/** "about 55 riders per minute (bottleneck)". */
const aboutFigure = (rpm: number): string => `about ${Math.round(rpm)} riders per minute (${flowBand(rpm).word})`;

/**
 * The chart summary's capacity sentences (OWNER-DECISIONS 424, "Show both."): the narrowest point on the
 * flat and the narrowest with the hills, each with its mile and figure, labelled as in the route view and
 * the directions; said once where they are the same spot. The chart's triangle marks the one with the
 * hills. Then the typical figures, the same way.
 */
export function capacitySentences(pair: CapacityPair): string[] {
  const out: string[] = [];
  const { flat, hills } = pair;
  if (flat && hills && pair.samePlace) {
    const figures =
      Math.round(flat.rpm) === Math.round(hills.rpm)
        ? aboutFigure(flat.rpm)
        : `${aboutFigure(flat.rpm)} on the flat, ${aboutFigure(hills.rpm)} with the hills`;
    out.push(`${capitalise(NARROWEST_BOTH)}: ${figures}, at mile ${miles(hills.atM)}, marked on the chart.`);
  } else {
    if (flat) out.push(`${capitalise(NARROWEST_FLAT)}: ${aboutFigure(flat.rpm)}, at mile ${miles(flat.atM)}.`);
    if (hills) out.push(`${capitalise(NARROWEST_HILLS)}: ${aboutFigure(hills.rpm)}, at mile ${miles(hills.atM)}, marked on the chart.`);
  }
  const typical = typicalLines(pair);
  if (typical.length > 0) out.push(`${typical.map((line, i) => `${i === 0 ? capitalise(line.label) : line.label}: about ${line.text}`).join("; ")}.`);
  return out;
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
    sentences.push(...capacitySentences(capacityPair(capacitySummary(route.stress_spans), profile.flow)));
    // 427: the parts outside DC have no figure, said in words (the narrowest and typical are DC's).
    if ((profile.outside_dc ?? []).length > 0) sentences.push(OUTSIDE_DC_FIGURES);
    const avoid = profile.avoid ?? [];
    if (avoid.length > 0) {
      const at = listWords(avoid.slice(0, 3).map((r) => miles(r.from_m)));
      sentences.push(`${avoid.length === 1 ? "One stretch is" : `${avoid.length} stretches are`} marked Avoid, no capacity given, from mile${avoid.length === 1 ? "" : "s"} ${at}${avoid.length > 3 ? " and more" : ""}.`);
    }
    const crossings = profile.crossings;
    if (crossings === null || crossings === undefined) {
      sentences.push("Major intersections were not checked for this route.");
    } else if (crossingsPartial(profile)) {
      const needing = crossings.filter((c) => c.corkers_needed).length;
      sentences.push(
        `Only the ${PARTIAL_JUNCTIONS}s were found, so the list may be incomplete: ${
          crossings.length === 0
            ? "none found"
            : `${crossings.length} found, ${needing === 0 ? "none needing corkers" : `${needing} needing corkers`}`
        }.`,
      );
      if ((profile.unchecked ?? []).length > 0) sentences.push("Part of the route could not be traced, so its width and intersections are not known.");
    } else {
      const needing = crossings.filter((c) => c.corkers_needed).length;
      sentences.push(
        crossings.length === 0
          ? "No major intersections."
          : `${crossings.length} major ${crossings.length === 1 ? "intersection" : "intersections"}, ${needing === 0 ? "none needing corkers" : `${needing} needing corkers`}.`,
      );
      if ((profile.unchecked ?? []).length > 0) sentences.push("Part of the route could not be traced, so its width and intersections are not known.");
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

/** The climbs table (OWNER-DECISIONS 322: start mile, length, gain, average and maximum grade, stress; 328(c): the capacity drop). `spans`: the route's stress sections, so the Stress cell is said the map's way (`climbStress`). */
export function climbRows(profile: RouteProfile, kind: ChartKind, spans?: readonly StressSpan[]): ClimbRow[] {
  return profile.climbs.map((c: ProfileClimb) => ({
    start: `Mile ${miles(c.from_m)}`,
    length: formatDistance(c.to_m - c.from_m),
    gain: formatClimb(c.gain_m),
    average: `${Math.round(c.avg_grade_pct)}%`,
    maximum: `${Math.round(c.max_grade_pct)}%`,
    stress: climbStress(c, spans),
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

const CONTROL_WORDS: Readonly<Record<ProfileCrossing["control"], string>> = {
  signal: "traffic signal",
  stop: "stop sign",
  all_stop: "all-way stop",
  cross_stop: "cross traffic stops",
  none: "no signal or sign",
};

/**
 * The marker word: its shape and its meaning, so the table says what the chart draws. A dot is a
 * junction major only for the busy road it crosses or joins (396), which the planner draws no
 * marker for: "Crosses a busy road (LTS 3), cross traffic stops (dot)".
 */
export function crossingMarkerWords(crossing: ProfileCrossing): string {
  if (crossing.severity === "red") return "Very high stress (red diamond)";
  if (crossing.severity === "orange") return "Higher stress (orange triangle)";
  const what = crossing.kind === "joining" ? "Joins a busy road" : "Crosses a busy road";
  const tier = tierWords(crossing.crossed_tier);
  return `${what}${tier ? ` (${tier})` : ""}, ${CONTROL_WORDS[crossing.control] ?? "control not known"} (dot)`;
}

export interface BottleneckRow {
  start: string;
  length: string;
  lowest: string;
}

/**
 * The stretches under 60 riders a minute (327's bottleneck band), in the order ridden: the riders
 * track as text (the a11y review's N7). Read from the samples, so a stretch is from its first such
 * sample to its last; the API sends a pair of samples at each place the width changes, so a
 * stretch's ends are its own. One that is a single sample (a thinned long route, or an older API)
 * is "under" the sample spacing, never "0 ft" (the re-reviews' nit).
 */
export function bottleneckRows(profile: RouteProfile): BottleneckRow[] {
  const riders = profile.riders_per_min ?? [];
  const edge = FLOW_BANDS[1].from;
  const rows: BottleneckRow[] = [];
  let from: number | null = null;
  let to = 0;
  let lowest = Infinity;
  const close = () => {
    if (from !== null) {
      const length = to - from > 0 ? formatDistance(to - from) : `under ${formatDistance(profile.interval_m || 30)}`;
      rows.push({ start: `Mile ${miles(from)}`, length, lowest: `About ${lowest} a minute` });
    }
    from = null;
    lowest = Infinity;
  };
  profile.m.forEach((m, i) => {
    const r = riders[i];
    if (r !== null && r !== undefined && r < edge) {
      if (from === null) from = m;
      to = m;
      lowest = Math.min(lowest, r);
    } else {
      close();
    }
  });
  close();
  return rows;
}

/** The intersections table's caption: it says when the list may be incomplete (correctness re-review R3). */
export function crossingCaption(profile: RouteProfile): string {
  return crossingsPartial(profile)
    ? `Major intersections, in the order ridden: only the ${PARTIAL_JUNCTIONS}s were found, so the list may be incomplete`
    : "Major intersections, in the order ridden";
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

/** The chart's type size, in viewBox units (the a11y review's N5: 11, as the mock-up; about 10 px at 375 px wide). */
export const CHART_TYPE = 11;

/** An approximate width of a label in the chart's 11-pixel type. */
export function labelWidth(text: string): number {
  return text.length * 5.9 + 4;
}

export interface BottleneckMark {
  x: number;
  y: number;
  /** "Narrowest 55": the figure is said in the summary and the sentence too. */
  label: string;
  anchor: "start" | "middle" | "end";
}

/**
 * Where the narrowest point is drawn (147: "with the bottleneck marked"): a downward caret on the
 * riders area at `flow.narrowest_m`, a shape and its label, not a colour. Null without a figure.
 */
export function bottleneckMark(profile: RouteProfile, x: (m: number) => number, y: (riders: number) => number, left: number, right: number): BottleneckMark | null {
  const flow = profile.flow;
  if (!flow || flow.narrowest_m === null || flow.narrowest_riders_per_min === null) return null;
  const at = x(flow.narrowest_m);
  const label = `Narrowest ${flow.narrowest_riders_per_min}`;
  const w = labelWidth(label);
  const anchor = at - w / 2 < left ? "start" : at + w / 2 > right ? "end" : "middle";
  return { x: at, y: y(flow.narrowest_riders_per_min), label, anchor };
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
