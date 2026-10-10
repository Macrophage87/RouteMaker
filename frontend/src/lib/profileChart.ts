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
import type { ProfileCalm, ProfileClimb, ProfileCrossing, ProfileRange, RouteProfile, RouteResponse, StressSpan } from "./api.ts";
import { FEET_PER_METRE, METRES_PER_MILE, formatAxisDistance, formatClimb, formatDistance, formatGroupLength } from "./format.ts";
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

/** "stress": every ride type but Mass Ride (the rolling stress chart under the elevation, 460.12; the stress strip where the API sends no score); "mass": the riders-per-minute area in its place. */
export type ChartKind = "stress" | "mass";

export function chartKind(route: Pick<RouteResponse, "preset">): ChartKind {
  return route.preset === "mass-ride" ? "mass" : "stress";
}

/** The fold's name, and its heading for a screen reader's list. A Mass Ride's fold holds three charts, in the owner's order (2026-10-10). */
export function foldName(kind: ChartKind): string {
  return kind === "mass" ? "Riders per minute, corker load and elevation" : "Elevation and stress";
}

/** A Mass Ride's three charts, in the order drawn (the owner, 2026-10-10: "Riders per minute, Corker load, Elevation"), each with its heading and its slider's name. */
export const MASS_CHARTS = [
  { key: "riders", heading: "Riders per minute", name: "Riders per minute along the route" },
  { key: "corkers", heading: "Corker load", name: "Corker load along the route" },
  { key: "elevation", heading: "Elevation", name: "Elevation along the route" },
] as const;

export type MassChartKey = (typeof MASS_CHARTS)[number]["key"];

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
  return bandedShapes(profile.m, riders, FLOW_GUIDES.map((g) => g.at), flowBand, (b) => b.index, x, y, baseline).map(({ band, d }) => ({ band, d }));
}

/**
 * The filled area under a line of values, each unbroken run of one band one polygon down to the
 * baseline. A segment that crosses an edge is cut there, so the colour changes where the line crosses
 * it and not at the next sample; a missing value (or distance going backwards) breaks the area.
 * Shared by the riders area (`flowShapes`) and the rolling stress area (`calmShapes`).
 */
export function bandedShapes<B>(
  ms: readonly number[],
  values: readonly (number | null)[],
  edges: readonly number[],
  bandOf: (value: number) => B,
  key: (band: B) => number,
  x: (m: number) => number,
  y: (value: number) => number,
  baseline: number,
): { band: B; d: string }[] {
  const out: { band: B; d: string }[] = [];
  let run: { band: B; pts: [number, number][] } | null = null;
  const close = () => {
    if (run && run.pts.length >= 2) {
      const first = run.pts[0];
      const last = run.pts[run.pts.length - 1];
      const line = run.pts.map(([px, py]) => `${f(px)} ${f(py)}`).join(" L");
      out.push({ band: run.band, d: `M${f(first[0])} ${f(baseline)} L${line} L${f(last[0])} ${f(baseline)} Z` });
    }
    run = null;
  };
  const push = (band: B, from: [number, number], to: [number, number]) => {
    if (run && key(run.band) !== key(band)) close();
    if (!run) run = { band, pts: [from] };
    run.pts.push(to);
  };
  for (let i = 1; i < ms.length; i += 1) {
    const v0 = values[i - 1];
    const v1 = values[i];
    if (v0 == null || v1 == null || ms[i] < ms[i - 1]) {
      close();
      continue;
    }
    // Cut the segment at every edge between its two ends, in order from the first end.
    const cuts = edges.filter((e) => (v0 < e && v1 > e) || (v0 > e && v1 < e)).sort((a, b) => (v0 <= v1 ? a - b : b - a));
    let prev: [number, number] = [ms[i - 1], v0];
    const stops: [number, number][] = [...cuts.map((e): [number, number] => [ms[i - 1] + ((e - v0) / (v1 - v0)) * (ms[i] - ms[i - 1]), e]), [ms[i], v1]];
    for (const stop of stops) {
      push(bandOf((prev[1] + stop[1]) / 2), [x(prev[0]), y(prev[1])], [x(stop[0]), y(stop[1])]);
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
  /** The rolling stress score at the sample, calm miles per mile; null where there is none. */
  calm: number | null;
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
    const calm = usableCalm(profile);
    const rolling = calm ? calmWords(calm, calm.ratio[index], m) : null;
    text = `${mileWord(m)}: ${parts.join(", ")}.${rolling ? ` Mile around: ${rolling}.` : ""}${calm ? nextJunctionClause(calm, m) : ""}`;
  }
  return { index, m, elevationM, gradePct, tier, riders, text, calm: usableCalm(profile)?.ratio[index] ?? null };
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
    out.push(`${capitalise(NARROWEST_BOTH)}: ${figures}, at mile ${miles(flat.atM)}, marked on the chart.`);
  } else {
    if (flat) out.push(`${capitalise(NARROWEST_FLAT)}: ${aboutFigure(flat.rpm)}, at mile ${miles(flat.atM)}.`);
    if (hills) out.push(`${capitalise(NARROWEST_HILLS)}: ${aboutFigure(hills.rpm)}, at mile ${miles(hills.atM)}, marked on the chart.`);
  }
  const typical = typicalLines(pair);
  if (typical.length > 0) out.push(`${typical.map((line, i) => `${i === 0 ? capitalise(line.label) : line.label}: about ${line.text}`).join("; ")}.`);
  return out;
}

/** The summary's elevation sentences: the range, the steepest section and the climbs (every chart kind; on a Mass Ride, the Elevation chart's summary). */
export function elevationSentences(route: Pick<RouteResponse, "distance_m">, profile: RouteProfile): string[] {
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
  return sentences;
}

/** A Mass Ride's riders sentences: the narrowest points and the typical figures (424), the parts outside DC (427), and the stretches marked Avoid (325). */
export function ridersSentences(route: Pick<RouteResponse, "stress_spans">, profile: RouteProfile): string[] {
  const sentences = capacitySentences(capacityPair(capacitySummary(route.stress_spans), profile.flow));
  // 427: the parts outside DC have no figure, said in words (the narrowest and typical are DC's).
  if ((profile.outside_dc ?? []).length > 0) sentences.push(OUTSIDE_DC_FIGURES);
  const avoid = profile.avoid ?? [];
  if (avoid.length > 0) {
    const at = listWords(avoid.slice(0, 3).map((r) => miles(r.from_m)));
    sentences.push(`${avoid.length === 1 ? "One stretch is" : `${avoid.length} stretches are`} marked Avoid, no capacity given, from mile${avoid.length === 1 ? "" : "s"} ${at}${avoid.length > 3 ? " and more" : ""}.`);
  }
  return sentences;
}

/** A Mass Ride's intersection sentences (333, 396): how many major intersections and how many need corkers, said as partial, or not checked, where they are. */
export function crossingSentences(profile: RouteProfile): string[] {
  const crossings = profile.crossings;
  if (crossings === null || crossings === undefined) return ["Major intersections were not checked for this route."];
  const needing = crossings.filter((c) => c.corkers_needed).length;
  const sentences = [
    crossingsPartial(profile)
      ? `Only the ${PARTIAL_JUNCTIONS}s were found, so the list may be incomplete: ${
          crossings.length === 0 ? "none found" : `${crossings.length} found, ${needing === 0 ? "none needing corkers" : `${needing} needing corkers`}`
        }.`
      : crossings.length === 0
        ? "No major intersections."
        : `${crossings.length} major ${crossings.length === 1 ? "intersection" : "intersections"}, ${needing === 0 ? "none needing corkers" : `${needing} needing corkers`}.`,
  ];
  if ((profile.unchecked ?? []).length > 0) sentences.push("Part of the route could not be traced, so its width and intersections are not known.");
  return sentences;
}

/**
 * The summary: the chart's text alternative, said before it and kept beside it. Elevation range and
 * the steepest section; then the stress along the route, or on a Mass Ride the narrowest point and
 * the climbs' cost. A Mass Ride draws three charts, each with its own part of this (`massSummaries`).
 */
export function summaryText(route: RouteResponse, profile: RouteProfile, kind: ChartKind = chartKind(route)): string {
  const total = axisLength(route, profile);
  const sentences = elevationSentences(route, profile);
  if (kind === "mass") {
    sentences.push(...ridersSentences(route, profile), ...crossingSentences(profile));
  } else {
    const shares = stressShares(route.stress_spans, total);
    if (shares) sentences.push(`Traffic stress along it: ${shares}.`);
    const { places, more } = busyPlaces(route.stress_spans);
    if (places.length > 0) {
      sentences.push(`LTS 3 or worse starts at mile${places.length === 1 ? "" : "s"} ${listWords(places)}${more > 0 ? `, and ${more} more ${more === 1 ? "place" : "places"}` : ""}.`);
    }
    const calm = usableCalm(profile);
    if (calm) sentences.push(...calmSentences(profile, calm));
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
  /** The corker load at the junction ("6 per mile (3.7 per km)"), when the table is given one. */
  load?: string;
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

/** The intersections table's rows; with the corker load, each row also says the load at that junction (`load`, the Corker load chart in words). */
export function crossingRows(profile: RouteProfile, load?: CorkerLoad | null): CrossingRow[] {
  return (profile.crossings ?? []).map((c) => ({
    mile: `Mile ${miles(c.m)}`,
    street: crossingName(c),
    marker: crossingMarkerWords(c),
    corkers: c.corkers_needed ? "Corkers needed" : "No corkers needed",
    ...(load ? { load: corkerCell(corkerAt(load, c.m)) } : {}),
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

// ---- The rolling stress chart (OWNER-DECISIONS 460.12, 461, 461d, 461e) ---------------------------

/**
 * 460.12: "A chart of rolling traffic stress makes more sense than a strip. That way, spikes show up."
 * The line is calm miles per actual mile (461d) over the mile around each point (461e), from the API's
 * `profile.calm` (routemaker.calm): each road at its own routing cost over a quiet street's, so 1 is a
 * quiet street and a path counts below it, and each junction's own cost is counted in every
 * window that holds it. The vertical scale is logarithmic, from
 * `CALM_FLOOR`, so a mile at 1.4 and a spike at 14 both read; the bands' guides are drawn at the API's
 * band edges (`calm.bands`, read from representative roads), where the words change.
 */
export const CALM_FLOOR = 0.5;

/** The three bands the area is filled in, below, between and above the two guides: the map's tier colour and the stress bar's pattern for each. */
export interface CalmBand {
  index: 0 | 1 | 2;
  /** The tier whose colour and pattern it borrows. */
  tier: 2 | 3 | 4;
  /** What a window in the band reads as. */
  word: string;
  /** The key's words. */
  label: string;
}

export const CALM_BANDS: readonly CalmBand[] = [
  { index: 0, tier: 2, word: "LTS 1 to 2 level", label: "Low stress (LTS 1 to 2 level)" },
  { index: 1, tier: 3, word: "LTS 3 level", label: "LTS 3 level" },
  { index: 2, tier: 4, word: "LTS 4 level", label: "LTS 4 level or higher" },
];

export function usableCalm(profile: RouteProfile): ProfileCalm | null {
  const c = profile.calm;
  if (!c || !Array.isArray(c.ratio) || c.ratio.length !== profile.m.length) return null;
  if (!c.ratio.some((r) => r !== null && Number.isFinite(r))) return null;
  return c;
}

/** The band a value reads in: LTS 4 level from the upper edge, LTS 3 level above the lower one (strictly, so a quiet street at 1 never reads as LTS 3 where the edge is 1). */
export function calmBand(ratio: number, bands: readonly number[]): CalmBand {
  if (bands.length >= 2 && ratio >= bands[1]) return CALM_BANDS[2];
  if (bands.length >= 1 && ratio > bands[0]) return CALM_BANDS[1];
  return CALM_BANDS[0];
}

/** "1.4", "0.6", "12": two figures, so a small change near 1 shows and a big figure is not over-precise. */
export function calmFigure(ratio: number): string {
  return ratio >= 10 ? String(Math.round(ratio)) : ratio.toFixed(1);
}

/** The top of the scale: the next of 2, 5, 10, 20, 50, ... above the highest value and the upper guide. */
export function calmTop(calm: ProfileCalm): number {
  const values = calm.ratio.filter((r): r is number => r !== null && Number.isFinite(r));
  const steps = calm.steps.map((s) => s.ratio).filter((r): r is number => r !== null && Number.isFinite(r));
  const high = Math.max(...values, ...steps, (calm.bands[1] ?? 1) * 1.15, 1.5);
  for (let decade = 1; ; decade *= 10) {
    for (const k of [2, 5, 10]) if (k * decade >= high) return k * decade;
  }
}

/**
 * The side's figures: the top, 1 and the floor first, then 2, 5, 10 ... between, each kept only where it
 * is at least `gap` viewBox units from every figure already kept, so the 11-unit labels never overlap.
 * Returned low to high.
 */
export function calmTicks(top: number, y: (ratio: number) => number = (r) => -Math.log(r) * 100, gap = 12): number[] {
  const wanted = [top, 1, CALM_FLOOR];
  for (let decade = 1; decade < top; decade *= 10) {
    for (const k of [2, 5, 10]) if (k * decade < top) wanted.push(k * decade);
  }
  const kept: number[] = [];
  for (const t of wanted) if (!kept.includes(t) && kept.every((k) => Math.abs(y(k) - y(t)) >= gap)) kept.push(t);
  return kept.sort((a, b) => a - b);
}

/** A logarithmic scale from `CALM_FLOOR` to `top`; values below the floor sit on it. */
export function calmScale(top: number, bottomY: number, topY: number): (ratio: number) => number {
  const lo = Math.log(CALM_FLOOR);
  const span = Math.log(top) - lo;
  return (ratio) => bottomY + ((Math.log(Math.max(ratio, CALM_FLOOR)) - lo) / span) * (topY - bottomY);
}

export interface CalmShape {
  band: CalmBand;
  d: string;
}

/**
 * The area under the rolling line, each run of one band one polygon down to the baseline, cut where
 * the line crosses a guide (as `flowShapes` cuts at the riders' thresholds), so the colour changes at
 * the guide and not at the next sample. Broken where the value is missing (an unrated mile).
 */
export function calmShapes(profile: RouteProfile, calm: ProfileCalm, x: (m: number) => number, y: (ratio: number) => number, baseline: number): CalmShape[] {
  return bandedShapes(profile.m, calm.ratio, calm.bands.slice(0, 2), (r) => calmBand(r, calm.bands), (b) => b.index, x, y, baseline);
}

/** The rolling line itself, broken where the value is missing. */
export function calmLine(profile: RouteProfile, calm: ProfileCalm, x: (m: number) => number, y: (ratio: number) => number): string {
  let d = "";
  let pen = false;
  profile.m.forEach((m, i) => {
    const r = calm.ratio[i];
    if (r === null || r === undefined || !Number.isFinite(r)) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${f(x(m))} ${f(y(r))} `;
    pen = true;
  });
  return d.trim();
}

/** The faint step line: each stretch at its own multiplier, so a short busy stretch is still seen at its true level behind the mile-long average. */
export function calmStepLine(calm: ProfileCalm, x: (m: number) => number, y: (ratio: number) => number, length: number): string {
  let d = "";
  let pen = false;
  let lastX: number | null = null;
  for (const s of calm.steps) {
    if (s.ratio === null || s.to_m <= s.from_m || s.from_m >= length) {
      pen = false;
      continue;
    }
    const x0 = x(Math.max(0, s.from_m));
    const x1 = x(Math.min(length, s.to_m));
    const yy = y(s.ratio);
    d += pen && lastX !== null && Math.abs(lastX - x0) < 0.01 ? `L${f(x0)} ${f(yy)} L${f(x1)} ${f(yy)} ` : `M${f(x0)} ${f(yy)} L${f(x1)} ${f(yy)} `;
    pen = true;
    lastX = x1;
  }
  return d.trim();
}

/** The stretches rated Avoid, which the chart marks in the Avoid magenta (397) whatever the line says. */
export function calmAvoid(calm: ProfileCalm, length: number): ProfileRange[] {
  const out: ProfileRange[] = [];
  for (const s of calm.steps) {
    if (s.tier !== 5 || s.to_m <= s.from_m || s.from_m >= length) continue;
    const last = out[out.length - 1];
    if (last && last.to_m >= s.from_m) last.to_m = Math.max(last.to_m, Math.min(length, s.to_m));
    else out.push({ from_m: Math.max(0, s.from_m), to_m: Math.min(length, s.to_m) });
  }
  return out;
}

/** Whether the window around a position holds any Avoid. */
export function avoidNear(calm: ProfileCalm, metres: number): boolean {
  const half = calm.window_m / 2;
  return calm.steps.some((s) => s.tier === 5 && s.from_m <= metres + half && s.to_m >= metres - half);
}

/** "1.4 calm miles per mile, LTS 1 to 2 level", with ", Avoid nearby" where the mile around holds some; null where not rated. */
export function calmWords(calm: ProfileCalm, ratio: number | null | undefined, metres: number): string | null {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return null;
  const words = [`${calmFigure(ratio)} calm miles per mile`, calmBand(ratio, calm.bands).word];
  if (avoidNear(calm, metres)) words.push("Avoid nearby");
  return words.join(", ");
}

const SEVERITY_WORDS: Readonly<Record<"orange" | "red", string>> = { orange: "higher stress", red: "very high stress" };

/**
 * The next flagged junction ahead, said as the key names it, so the chart's triangles and diamonds have
 * words (a11y review SF1): " Next junction to watch: very high stress, mile 1.4."; "" where none is ahead.
 */
export function nextJunctionClause(calm: ProfileCalm, metres: number): string {
  const next = calm.points.find((p) => p.kind === "junction" && p.severity !== null && p.m >= metres);
  return next && next.severity ? ` Next junction to watch: ${SEVERITY_WORDS[next.severity]}, mile ${miles(next.m)}.` : "";
}

/** The highest window: its value and where (the first, where several tie). */
export function calmPeak(profile: RouteProfile, calm: ProfileCalm): { ratio: number; m: number } | null {
  let best: { ratio: number; m: number } | null = null;
  calm.ratio.forEach((r, i) => {
    if (r !== null && Number.isFinite(r) && (best === null || r > best.ratio)) best = { ratio: r, m: profile.m[i] };
  });
  return best;
}

/** The flagged junctions inside the window around a position, worst first: what the peak sentence names. */
export function junctionsNear(calm: ProfileCalm, metres: number): { orange: number; red: number } {
  const half = calm.window_m / 2;
  const near = calm.points.filter((p) => p.kind === "junction" && Math.abs(p.m - metres) <= half);
  return { orange: near.filter((p) => p.severity === "orange").length, red: near.filter((p) => p.severity === "red").length };
}

/** The window's length in words: "1 mi (1.6 km)". */
export function windowWords(calm: ProfileCalm): string {
  return formatDistance(calm.window_m);
}

/**
 * The chart summary's rolling-stress sentences: the route's total in calm miles (461d: "The route summary
 * can also give the route total in calm miles"; calm km in brackets), the average, the most stressful
 * mile and what is in it, and whether junctions were counted. Whether it is an estimate is said by the
 * key and the source line (`calmSource`).
 */
export function calmSentences(profile: RouteProfile, calm: ProfileCalm): string[] {
  const out: string[] = [];
  const rated = calm.rated_m;
  if (rated > 0) {
    const average = calm.total_calm_m / rated;
    out.push(
      `Rolling stress: ${calmDistance(calm.total_calm_m)} over ${formatDistance(rated)} rated, ${calmFigure(average)} calm miles per mile (calm km per km) on average; about 1 is all quiet streets.`,
    );
  }
  const peak = calmPeak(profile, calm);
  if (peak) {
    const { orange, red } = junctionsNear(calm, peak.m);
    const junctions: string[] = [];
    if (red > 0) junctions.push(`${red} very high stress ${red === 1 ? "junction" : "junctions"}`);
    if (orange > 0) junctions.push(`${orange} higher stress ${orange === 1 ? "junction" : "junctions"}`);
    const avoid = avoidNear(calm, peak.m) ? ", Avoid nearby" : "";
    out.push(
      `The most stressful mile is around mile ${miles(peak.m)}: ${calmFigure(peak.ratio)} calm miles per mile, ${calmBand(peak.ratio, calm.bands).word}${avoid}${junctions.length ? `, with ${listWords(junctions)}` : ""}.`,
    );
  }
  if (!calm.junctions_counted) out.push("Junctions could not be read for this route, so they are not counted.");
  return out;
}

/**
 * The source line under the chart: what the figure is made from. Each road is priced by its own routing
 * cost (docs/stress/stress-number.md section 4); where the router gave no road details for some stretch,
 * that stretch took its stress level's figure and the line says the whole is an estimate.
 */
export function calmSource(calm: ProfileCalm): string {
  return calm.estimate
    ? "Rolling stress: an estimate of what the routing charges for each road and junction, as quiet-street miles, over the mile around each point; some roads are priced by their stress level, as the router did not give their speed and lanes (stress ratings: RouteMaker, from OpenStreetMap)."
    : "Rolling stress: what the routing charges for each road, by its own speed, lanes and bike lane, and for each junction, as quiet-street miles, over the mile around each point (stress ratings: RouteMaker, from OpenStreetMap).";
}

/** Calm miles, km in brackets: "7.4 calm mi (11.9 calm km)". */
export function calmDistance(metres: number): string {
  const mi = metres / METRES_PER_MILE;
  const km = metres / 1000;
  return `${mi.toFixed(1)} calm mi (${km.toFixed(1)} calm km)`;
}

export interface CalmRow {
  at: string;
  value: string;
  reads: string;
  /** The flagged junctions since the row before (from the start, on the first): "1 very high stress", "None". */
  junctions: string;
}

/** The interval the rolling-stress table reads at: half a mile up to 10 mi, a mile up to 40 mi, then 2 mi (at most about 40 rows on a ride the planner makes). */
export function calmRowStep(totalM: number): number {
  const mi = totalM / METRES_PER_MILE;
  return (mi <= 10 ? 0.5 : mi <= 40 ? 1 : mi <= 80 ? 2 : 5) * METRES_PER_MILE;
}

/** The rolling-stress table: the value at the start, every `calmRowStep`, and the end (the picture's text alternative). */
export function calmRows(profile: RouteProfile, calm: ProfileCalm, totalM: number): CalmRow[] {
  const step = calmRowStep(totalM);
  const at: number[] = [];
  for (let m = 0; m < totalM - step / 4; m += step) at.push(m);
  at.push(totalM);
  return at.map((m, k) => {
    const from = k === 0 ? -1 : at[k - 1];
    const since = calm.points.filter((p) => p.kind === "junction" && p.severity !== null && p.m > from && p.m <= m);
    const red = since.filter((p) => p.severity === "red").length;
    const orange = since.filter((p) => p.severity === "orange").length;
    const junctions = [red ? `${red} very high stress` : "", orange ? `${orange} higher stress` : ""].filter(Boolean).join(", ") || "None";
    const i = nearestIndex(profile.m, m);
    const r = calm.ratio[i];
    const known = r !== null && r !== undefined && Number.isFinite(r);
    return {
      at: mileWord(m),
      value: known ? calmFigure(r) : "Not rated",
      reads: known ? capitalise(calmBand(r, calm.bands).word) + (avoidNear(calm, m) ? ", Avoid nearby" : "") : "Not rated",
      junctions,
    };
  });
}

// ---- The corker load (OWNER-DECISIONS 139, 142, 147, 400; the owner, 2026-10-10) -----------------

/**
 * A Mass Ride's second chart: the corkers held at once along the route (the owner, 2026-10-10:
 * "Have 3 charts for mass ride: Riders per minute, Corker load, Elevation", and then "Corkers were
 * intended to also have a rollback based on the length of the ride"). PLAN "Corkers needed" (139):
 * a window the length of the group at the chosen ride size (128) is slid along the route, and the
 * corkers its junctions need are the number held at once.
 *
 * - The group's length (PLAN, "The main control"): riders over the cruising density times the
 *   effective width, which is riders over the flow a second times the cruising pace. The API sends
 *   the level figure at each sample (`level_riders_per_min`, from the width alone) and the pace
 *   (`flow.cruise_pace_ms`), so no constant of the flow model is repeated here. The width is read
 *   at each point: the group fills the road behind its head until the road holds every rider, so
 *   it is shorter on a wide avenue and longer on a narrow street. Where no width is known (Avoid,
 *   an untraced leg, outside DC) the route's median level figure stands in, or, with none at all,
 *   `flow.default_level_riders_per_min` (two 11 ft lanes).
 * - The window is the group with its head at the point: a junction is held from when the head
 *   reaches it until the tail passes it (`[j, exit)`), so the load steps up at each tick and down
 *   a group's length later. Near the start the group is still behind the start, and past the end
 *   the junctions stay held to the end, so a group longer than the route holds them all at its end.
 * - Corkers per junction needing them (`corkers_needed`, 142, 400): 2 for a two-way road and 1 for
 *   a one-way (`oneway`), 2 where it is not known (an older answer, or no mapping).
 * - The ride's headline: the most held at once times the rotation factor (2, corkers leapfrog to
 *   the junctions ahead), rounded up. Where the list may be incomplete (only the flagged junctions
 *   found) or part of the route was not checked, it is "at least", never a firm figure.
 */
export const ROTATION_FACTOR = 2;
export const CORKERS_TWO_WAY = 2;
export const CORKERS_ONE_WAY = 1;

/** The corkers a junction needing them takes: one an approach (PLAN 139). */
export function corkersFor(crossing: Pick<ProfileCrossing, "oneway">): number {
  return crossing.oneway === true ? CORKERS_ONE_WAY : CORKERS_TWO_WAY;
}

/** A group's length, metres: riders over the flow a second, times the cruising pace (PLAN 128). */
export function groupLengthM(riders: number, levelRidersPerMin: number, cruisePaceMs: number): number {
  return levelRidersPerMin > 0 ? (riders / (levelRidersPerMin / 60)) * cruisePaceMs : 0;
}

/** The road as a group fills it: riders a metre at cruise along the route, and their running total. */
export interface GroupRoad {
  riders: number;
  /** Sample positions, and the riders a metre on the stretch from each to the next. */
  m: number[];
  density: number[];
  /** Riders the road holds from 0 to each sample. */
  held: number[];
  /** The group's length on the route's median width. */
  typicalLengthM: number;
}

function median(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/** The road a group of `riders` fills, or null where the answer has no pace (an older API). */
export function groupRoad(profile: Pick<RouteProfile, "m" | "level_riders_per_min" | "flow">, riders: number): GroupRoad | null {
  const pace = profile.flow?.cruise_pace_ms;
  if (!pace || pace <= 0 || profile.m.length === 0) return null;
  const levels = profile.level_riders_per_min ?? [];
  const typical = median(levels.filter((v): v is number => v !== null && v !== undefined && v > 0)) ?? profile.flow?.default_level_riders_per_min ?? null;
  if (!typical || typical <= 0) return null;
  const density = profile.m.map((_, i) => {
    const level = levels[i];
    return ((level !== null && level !== undefined && level > 0 ? level : typical) / 60) / pace;
  });
  const held = [0];
  for (let i = 1; i < profile.m.length; i += 1) held.push(held[i - 1] + density[i - 1] * Math.max(profile.m[i] - profile.m[i - 1], 0));
  return { riders, m: [...profile.m], density, held, typicalLengthM: groupLengthM(riders, typical, pace) };
}

/** The last index whose value is at or below `v` (0 when none is). */
function lastAtOrBelow(values: readonly number[], v: number): number {
  let lo = 0;
  let hi = values.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (values[mid] <= v) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

/** Riders the road holds from the start to `x`; before the start and past the end at the first and last stretch's density. */
export function heldTo(road: GroupRoad, x: number): number {
  const last = road.m.length - 1;
  if (x <= road.m[0]) return (x - road.m[0]) * road.density[0];
  if (x >= road.m[last]) return road.held[last] + (x - road.m[last]) * road.density[last];
  const i = lastAtOrBelow(road.m, x);
  return road.held[i] + (x - road.m[i]) * road.density[i];
}

/** Where the road has held `riders` from the start: `heldTo`'s inverse. */
export function placeHolding(road: GroupRoad, riders: number): number {
  const last = road.m.length - 1;
  if (riders <= 0) return road.m[0] + riders / road.density[0];
  if (riders >= road.held[last]) return road.m[last] + (riders - road.held[last]) / road.density[last];
  const i = lastAtOrBelow(road.held, riders);
  // A run of samples at one place holds nothing: step to the last of them.
  let k = i;
  while (k < last && road.held[k + 1] === road.held[i] && road.m[k + 1] === road.m[k]) k += 1;
  return road.m[k] + (riders - road.held[k]) / road.density[k];
}

/** The group's tail with its head at `x` (before the start while it is still forming). */
export function tailAt(road: GroupRoad, x: number): number {
  return placeHolding(road, heldTo(road, x) - road.riders);
}

/** The group's length with its head at `x`, metres. */
export function groupLengthAt(road: GroupRoad, x: number): number {
  return x - tailAt(road, x);
}

/** Where the head is when the tail passes `j`. */
export function exitOf(road: GroupRoad, j: number): number {
  return placeHolding(road, heldTo(road, j) + road.riders);
}

export interface CorkerStep {
  from_m: number;
  to_m: number;
  /** Corkers held at once with the head anywhere in the step. */
  corkers: number;
  /** The junctions they hold. */
  junctions: number;
}

export interface CorkerLoad {
  riders: number;
  road: GroupRoad;
  /** The steps, end to end from 0 to the route's length, neighbours with the same figures merged. */
  steps: CorkerStep[];
  /** Each junction needing corkers, in order: where (the chart's ticks), its corkers, and where the head is when the tail passes it. */
  junctions: { m: number; corkers: number; exit: number }[];
  /** The first step with the most corkers; null where no junction needs corkers. */
  peak: CorkerStep | null;
  /** About this many for the ride: the peak times ROTATION_FACTOR, rounded up (0 with no peak). */
  headline: number;
  /** Only the flagged junctions were found (`crossings_complete: false`). */
  partial: boolean;
  /** The stretches not checked for intersections. */
  unchecked: ProfileRange[];
}

/** Whether the count may be low: the list may be incomplete, or part of the route was not checked. */
export function corkersMayBeLow(load: Pick<CorkerLoad, "partial" | "unchecked">): boolean {
  return load.partial || load.unchecked.length > 0;
}

/**
 * The corkers held at once along a route of `totalM` metres by a group of `riders`; null where the
 * intersections were not checked (`crossings: null`), so the chart says "not checked", never 0, or
 * where the answer gives no group length (`groupRoad`).
 */
export function corkerLoad(profile: RouteProfile, totalM: number, riders: number): CorkerLoad | null {
  const crossings = profile.crossings;
  if (crossings === null || crossings === undefined) return null;
  const road = groupRoad(profile, riders);
  if (!road) return null;
  const length = Math.max(totalM, 0);
  const junctions = crossings
    .filter((c) => c.corkers_needed && Number.isFinite(c.m))
    .map((c) => {
      const m = Math.min(Math.max(c.m, 0), length);
      return { m, corkers: corkersFor(c), exit: exitOf(road, m) };
    })
    .sort((a, b) => a.m - b.m);
  const cuts = new Set<number>([0, length]);
  for (const j of junctions) for (const at of [j.m, j.exit]) if (at > 0 && at < length) cuts.add(at);
  const edges = [...cuts].sort((a, b) => a - b);
  const at = (x: number) => {
    const held = junctions.filter((j) => j.m <= x && x < j.exit);
    return { corkers: held.reduce((sum, j) => sum + j.corkers, 0), junctions: held.length };
  };
  const steps: CorkerStep[] = [];
  for (let i = 1; i < edges.length; i += 1) {
    const here = at(edges[i - 1]);
    const last = steps[steps.length - 1];
    if (last && last.corkers === here.corkers && last.junctions === here.junctions) last.to_m = edges[i];
    else steps.push({ from_m: edges[i - 1], to_m: edges[i], ...here });
  }
  if (steps.length === 0) steps.push({ from_m: 0, to_m: length, ...at(0) });
  // At the very end the last step's figures hold, with every junction whose tail has not passed.
  const end = at(length);
  const lastStep = steps[steps.length - 1];
  if (length > 0 && (end.corkers !== lastStep.corkers || end.junctions !== lastStep.junctions)) {
    steps.push({ from_m: length, to_m: length, ...end });
  }
  const peak = steps.reduce<CorkerStep | null>((best, s) => (s.corkers > 0 && (best === null || s.corkers > best.corkers) ? s : best), null);
  const unchecked = (profile.unchecked ?? []).filter((r) => r.to_m > r.from_m && r.from_m < length);
  return {
    riders,
    road,
    steps,
    junctions,
    peak,
    headline: peak ? Math.ceil(peak.corkers * ROTATION_FACTOR) : 0,
    partial: crossingsPartial(profile),
    unchecked,
  };
}

/** The step the head at a position lies in (the first before the start, the last at or past the end). */
export function corkerAt(load: CorkerLoad, metres: number): CorkerStep {
  const last = load.steps[load.steps.length - 1];
  if (metres >= last.to_m) return last;
  for (const s of load.steps) if (metres >= s.from_m && metres < s.to_m) return s;
  return load.steps[0];
}

/** "4 corkers holding 2 junctions", "1 corker holding 1 junction". */
export function heldWords(step: Pick<CorkerStep, "corkers" | "junctions">): string {
  if (step.corkers === 0) return "no corkers held";
  return `${step.corkers} ${step.corkers === 1 ? "corker" : "corkers"} holding ${step.junctions} ${step.junctions === 1 ? "junction" : "junctions"}`;
}

/** "500 riders, group about 1,560 ft (475 m) long". */
export function groupWords(riders: number, lengthM: number): string {
  return `${riders.toLocaleString("en-US")} riders, group about ${formatGroupLength(lengthM)} long`;
}

/** The intersections table's cell: the corkers held at once as the head reaches the junction ("4 at 2 junctions"), or "None". */
export function corkerCell(step: CorkerStep): string {
  if (step.corkers === 0) return "None";
  return `${step.corkers} at ${step.junctions} ${step.junctions === 1 ? "junction" : "junctions"}`;
}

/** The chart's top, corkers: the peak rounded up to an even number, and at least 4. */
export function corkerTop(load: CorkerLoad): number {
  return Math.max(4, Math.ceil((load.peak?.corkers ?? 0) / 2) * 2);
}

/** Whether any of a stretch was not checked for intersections. */
export function uncheckedWithin(load: Pick<CorkerLoad, "unchecked">, from: number, to: number): boolean {
  return load.unchecked.some((r) => r.to_m > from && r.from_m < to);
}

/** The load's outline: one step line from the start to the end. */
export function corkerLine(load: CorkerLoad, x: (m: number) => number, y: (corkers: number) => number): string {
  return load.steps
    .filter((s) => s.to_m > s.from_m || load.steps.length === 1)
    .map((s, i) => `${i === 0 ? "M" : "L"}${f(x(s.from_m))} ${f(y(s.corkers))} L${f(x(s.to_m))} ${f(y(s.corkers))}`)
    .join(" ");
}

/** The load's area: the step line closed down to the baseline. */
export function corkerArea(load: CorkerLoad, x: (m: number) => number, y: (corkers: number) => number, baseline: number): string {
  const line = corkerLine(load, x, y);
  if (!line) return "";
  const first = load.steps[0];
  const last = load.steps[load.steps.length - 1];
  return `M${f(x(first.from_m))} ${f(baseline)} L${line.slice(1)} L${f(x(last.to_m))} ${f(baseline)} Z`;
}

/** Why there is no corker load: the intersections were not checked, or the answer gives no group length. */
export function corkerMissing(profile: Pick<RouteProfile, "crossings">): string {
  return profile.crossings === null || profile.crossings === undefined
    ? "intersections not checked, so the corkers needed are not known"
    : "the group's length is not known for this answer, so the corkers needed are not known";
}

/**
 * What the Corker load slider says at a position: "Mile 1.2: 4 corkers holding 2 junctions at once
 * (500 riders, group about 1,560 ft (475 m) long). Next: 15th Street Northwest at mile 1.3, corkers
 * needed." Where part of the group's stretch was not checked it says so.
 */
export function corkerReading(profile: RouteProfile, load: CorkerLoad | null, metres: number): string {
  const m = profile.m[nearestIndex(profile.m, metres)] ?? metres;
  if (!load) return `${mileWord(m)}: ${corkerMissing(profile)}.`;
  const step = corkerAt(load, m);
  const tail = tailAt(load.road, m);
  const gap = uncheckedWithin(load, tail, m) ? " Part of the group's stretch was not checked for intersections." : "";
  const held = step.corkers === 0 ? heldWords(step) : `${heldWords(step)} at once`;
  return `${mileWord(m)}: ${held} (${groupWords(load.riders, m - tail)}).${gap}${crossingClause(profile, m)}`;
}

/** Why the count may be low, as a clause. */
function lowReason(load: Pick<CorkerLoad, "partial" | "unchecked">): string {
  if (load.partial) return `only the ${PARTIAL_JUNCTIONS}s were found`;
  return "part of the route was not checked for intersections";
}

/** The ride's corkers, as the summary and the route's figures say it: "about 8", "at least about 8". */
export function corkerHeadline(load: CorkerLoad): string {
  return `${corkersMayBeLow(load) ? "at least about" : "about"} ${load.headline}`;
}

/** The Corker load chart's summary sentences: the intersections, the group, the most held at once, the ride's headline, and how it is counted. */
export function corkerSentences(profile: RouteProfile, load: CorkerLoad | null): string[] {
  if (!load) {
    if (profile.crossings === null || profile.crossings === undefined) return ["Major intersections were not checked for this route, so the corkers needed are not known."];
    return [...crossingSentences(profile), "The group's length is not known for this answer, so the corker load is not drawn."];
  }
  const sentences = crossingSentences(profile);
  sentences.push(`At ${load.riders.toLocaleString("en-US")} riders the group is about ${formatGroupLength(load.road.typicalLengthM)} long at cruise, on this route's typical width.`);
  const peak = load.peak;
  if (!peak) {
    sentences.push(corkersMayBeLow(load) ? `None of the junctions found needs corkers, but ${lowReason(load)}, so some may.` : "No junction needs corkers, so no corkers are needed.");
  } else {
    const from = miles(peak.from_m);
    const to = miles(peak.to_m);
    const where = from === to ? `with the head around mile ${from}` : `with the head from mile ${from} to ${to}`;
    const more = load.steps.filter((s) => s !== peak && s.corkers === peak.corkers).length;
    const also = more === 0 ? "" : `, and at ${more} more ${more === 1 ? "place" : "places"}`;
    sentences.push(`The most held at once is ${heldWords(peak)}, ${where}${also}.`);
    const low = corkersMayBeLow(load) ? `; the count may be low, as ${lowReason(load)}` : "";
    sentences.push(`${capitalise(corkerHeadline(load))} corkers for the ride: the most held at once times ${ROTATION_FACTOR}, as corkers leapfrog to the junctions ahead${low}.`);
  }
  sentences.push(
    `Each junction needing corkers takes ${CORKERS_TWO_WAY}, or ${CORKERS_ONE_WAY} where the road is one-way, and is held from when the group's head reaches it until its tail passes; a tick marks each one.`,
  );
  return sentences;
}

/** What the Elevation slider says at a position: "Mile 1.2: elevation 310 ft (94 m), grade 6%." */
export function elevationReading(profile: RouteProfile, metres: number): string {
  const index = nearestIndex(profile.m, metres);
  const e = profile.elevation_m[index];
  const parts = [e === null || e === undefined ? "elevation not known" : `elevation ${elevationWords(e)}`];
  const grade = gradeWords(profile.grade_pct[index]);
  if (grade) parts.push(grade);
  return `${mileWord(profile.m[index])}: ${parts.join(", ")}.`;
}

/** Each of a Mass Ride's three charts' summaries, said before its picture. */
export function massSummaries(route: RouteResponse, profile: RouteProfile, load: CorkerLoad | null): Record<MassChartKey, string> {
  const riders = ridersSentences(route, profile);
  return {
    riders: (riders.length > 0 ? riders : ["Riders per minute are not known for this route."]).join(" "),
    corkers: corkerSentences(profile, load).join(" "),
    elevation: elevationSentences(route, profile).join(" "),
  };
}

/** Each of a Mass Ride's three sliders' value text at a position. */
export function massReadings(route: RouteResponse, profile: RouteProfile, load: CorkerLoad | null, metres: number): Record<MassChartKey, string> {
  return {
    riders: readingAt(route, profile, metres, "mass").text,
    corkers: corkerReading(profile, load, metres),
    elevation: elevationReading(profile, metres),
  };
}

/**
 * The ride's corkers as the route's figures list them (beside the carrying capacity): "About 8 for
 * 500 riders", or "At least about 8 for 500 riders (may be low: part of the route was not checked
 * for intersections)"; null off a Mass Ride or where the load is not known.
 */
export function corkerFigure(route: Pick<RouteResponse, "preset" | "distance_m">, profile: RouteProfile | null, riders: number): { label: string; text: string } | null {
  if (!profile || chartKind(route) !== "mass") return null;
  const load = corkerLoad(profile, axisLength(route, profile), riders);
  if (!load) return null;
  const size = `${riders.toLocaleString("en-US")} riders`;
  const low = corkersMayBeLow(load) ? ` (may be low: ${lowReason(load)})` : "";
  if (!load.peak) return { label: "Corkers", text: `${corkersMayBeLow(load) ? "None found" : "None needed"} for ${size}${low}` };
  return { label: "Corkers", text: `${capitalise(corkerHeadline(load))} for ${size}${low}` };
}
