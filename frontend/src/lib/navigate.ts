/**
 * Ride mode's engine (WEB-NAV-plan.md sections 2-4; OWNER-DECISIONS 255, 434, 465): where the rider
 * is along the planned route, which cue is next and when to say it, and whether the rider has left
 * the route. Pure: positions come in as plain fixes with a clock, and what to say comes out as
 * events, so every rule here is tested with synthetic fix sequences (navigate.test.ts) and the page
 * only carries the events to the screen, the live regions and the voice (lib/rideOutput.ts).
 *
 * The cue words are the API's: each cue is a `description` entry (src/routemaker/describe.py), the
 * sentence after its "0.4 to 1.2 mi (0.6 to 1.9 km): " position, so there is still one wording of a
 * stretch to keep right (lib/routeDescription.ts). What is added here is only the timing ("In 500
 * feet, ..."), "now" at a turn, arrival, and the off-route sentences.
 *
 * Distances: the line is measured along its own vertices (trackMatch.ts `cumulative`), and the
 * description's metres (the route's traced length, scaled by describe.py to the route's distance) are
 * mapped onto it piecewise between the stops, whose vertices `leg_ends` gives exactly (the plan's N0:
 * each stop's cue lands on its own vertex however the two measures drift on a long leg).
 *
 * Privacy (plan section 7): nothing here stores or sends a position. The state holds the last fix in
 * memory for the ride only; the one place a position leaves the page is the re-plan's start point
 * (`replanPoints`), in a POST body, as planning with "Use my location" already sends (395).
 */
import { METRES_PER_MILE, formatDistance, formatRoughDistance, spokenDistance } from "./format.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { descriptionEntries } from "./routeDescription.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";

// ---- Settings ---------------------------------------------------------------------------------

/**
 * How much Ride mode says unprompted (plan section 3): Full for a captain or a solo rider, Stoker for
 * the rider behind who is not steering but follows along, Quiet for nothing but arrival.
 */
export type Verbosity = "full" | "stoker" | "quiet";

export const VERBOSITY_LABELS: Record<Verbosity, string> = {
  full: "Full: every turn, early and again close to it",
  stoker: "Stoker: each turn once ahead and as it happens, busy crossings, stops",
  quiet: "Quiet: only arrival; ask Where am I? any time",
};

/** Rides at most this long get Start ride; longer ones go to a bike computer (OD 255, plan Q1). */
export const RIDE_MAX_M = 30 * METRES_PER_MILE;
export const RIDE_TOO_LONG =
  `Ride mode is for rides up to ${formatRoughDistance(RIDE_MAX_M)}. For a longer ride, use Download GPX with a bike computer, which keeps going with the screen off.`;

// ---- Thresholds (plan sections 2 and 4) ---------------------------------------------------------

/** A fix less accurate than this moves the marker but is not used for cues or off route (about 165 ft). */
export const POOR_FIX_M = 50;
/** Seconds ahead, at the current speed, of a turn's first cue; never closer than ADVANCE_MIN_M (500 ft). */
export const ADVANCE_S = 27;
export const ADVANCE_MIN_M = 150;
/** The second cue: about 10 s ahead, never closer than 150 ft. */
export const PREPARE_S = 10;
export const PREPARE_MIN_M = 45;
/** "Left now": about 50 ft before the turn, or 2 s at speed, so a fix a second at 20 mph still lands in it. */
export const NOW_M = 15;
export const NOW_S = 2;
/** The stoker's one warning ahead: about 15-20 s, never closer than 300 ft. */
export const STOKER_S = 17;
export const STOKER_MIN_M = 90;
/** A cue passed by more than this before it was said is dropped, not said late. */
export const PASSED_M = 10;
/** Arrival at a stop or the end: within this of it along the line (and the fix close to it). */
export const ARRIVE_M = 20;
/** A first fix this close to the route's start starts at the start (a loop's start is its end too). */
export const START_M = 50;
/** Progress never moves back by more than this while on route (GPS jitter at a light). */
export const BACK_TOLERANCE_M = 30;
/** The search for the rider's place on the line looks this far behind the last progress... */
export const WINDOW_BEHIND_M = 60;
/** ...and this far ahead, plus FAST_MS a second since the last good fix (a tunnel gap). */
export const WINDOW_AHEAD_M = 250;
export const FAST_MS = 15;
/** Off route: farther than max(100 ft, 1.5 x accuracy), capped at 330 ft... */
export const OFF_MIN_M = 30;
export const OFF_MAX_M = 100;
export const OFF_ACCURACY_FACTOR = 1.5;
/**
 * Rejoining the line beyond WINDOW_AHEAD_M of where the rider left it takes this many near fixes in a
 * row, each farther along: a detour that only crosses the route does not skip the stops between.
 */
export const REJOIN_FIXES = 3;
/** ...for at least 3 good fixes in a row over at least 8 s. */
export const OFF_FIXES = 3;
export const OFF_MS = 8_000;
/** Speed is smoothed over fixes; below this a rider counts as stopped (no time-based thresholds). */
const SPEED_SMOOTHING = 0.35;
const MIN_SPEED_MS = 1;
/** A rider's speed is believed up to this (about 45 mph): above it a fix is a jump, not a ride. */
const MAX_SPEED_MS = 20;

// ---- The ride's model ---------------------------------------------------------------------------

export type CueKind = "turn" | "hazard" | "walk" | "busy" | "calmer" | "unpaved" | "stop" | "end";

export interface Cue {
  /** Its place in the list, also its key. */
  index: number;
  kind: CueKind;
  /** Metres along the line (the geometry's own length). */
  atM: number;
  /** The API's sentence, without its position: "Left onto R Street Northwest at a signal, low stress (LTS 1)." */
  text: string;
  movement: "left" | "right" | null;
  /** The street the cue turns onto or is on, as the API names it; null where unnamed. */
  street: string | null;
  severity: "orange" | "red" | null;
  /** The stretch's tier after the cue, 1-5, or null. */
  tier: number | null;
  /** A stop's number (from 1); null on any other cue. */
  stop: number | null;
}

export interface RideModel {
  coordinates: LonLat[];
  /** Metres along the line to each vertex. */
  along: Float64Array;
  /** The line's length in metres. */
  lengthM: number;
  cues: Cue[];
  /** The stretches, to name the street the rider is on: [from, to) along the line, with the API's street and tier. */
  stretches: { fromM: number; toM: number; street: string | null; tier: number | null; facility: DescriptionEntry["facility"] }[];
  /** Metres per second at the route's own pace (distance over moving time), for time to go. */
  paceMs: number | null;
}

/** "0.4 to 1.2 mi (0.6 to 1.9 km): Left onto ..." without its position: the part after the first ": ". */
export function sentenceOf(entry: Pick<DescriptionEntry, "text">): string {
  const text = entry.text.trim();
  const at = text.indexOf(": ");
  return at >= 0 ? text.slice(at + 2) : text;
}

/** Metres along the geometry's own vertices. */
function lineAlong(coordinates: readonly LonLat[]): Float64Array {
  const out = new Float64Array(coordinates.length);
  for (let i = 1; i < coordinates.length; i += 1) out[i] = out[i - 1] + haversineM(coordinates[i - 1], coordinates[i]);
  return out;
}

/**
 * The map from the description's metres to the line's (plan N0): piecewise linear between anchors,
 * the start (0, 0), each stop (its entry's metres, its vertex's), and the end (the route's length,
 * the line's). Where the stops and `leg_ends` disagree (an older API, a long plan), one scale for
 * the whole route, as the route chart's marker does (profileChart.ts lonLatAt).
 */
export function measureMap(route: Pick<RouteResponse, "distance_m" | "leg_ends" | "description">, along: Float64Array): (m: number) => number {
  const lineM = along.length ? along[along.length - 1] : 0;
  const entries = route.description ?? [];
  const lastTo = entries.length ? Math.max(...entries.map((e) => (Number.isFinite(e.to_m) ? e.to_m : 0))) : 0;
  const routeM = lastTo > 0 ? lastTo : route.distance_m > 0 ? route.distance_m : lineM;
  const anchors: [number, number][] = [[0, 0]];
  const ends = route.leg_ends ?? [];
  const vias = entries.filter((e) => e.kind === "via");
  const usable =
    vias.length > 0 &&
    vias.length === ends.length - 1 &&
    vias.every((v, i) => (v.via ?? i + 1) === i + 1 && ends[i] >= 0 && ends[i] < along.length);
  if (usable) {
    vias.forEach((v, i) => {
      const prev = anchors[anchors.length - 1];
      const point: [number, number] = [v.from_m, along[ends[i]]];
      if (point[0] > prev[0] && point[1] >= prev[1]) anchors.push(point);
    });
  }
  anchors.push([Math.max(routeM, anchors[anchors.length - 1][0] + 1e-6), lineM]);
  return (m: number) => {
    if (!(m > 0)) return 0;
    for (let i = 1; i < anchors.length; i += 1) {
      const [m0, l0] = anchors[i - 1];
      const [m1, l1] = anchors[i];
      if (m <= m1 || i === anchors.length - 1) {
        const t = m1 > m0 ? (m - m0) / (m1 - m0) : 0;
        return Math.min(Math.max(l0 + t * (l1 - l0), 0), lineM);
      }
    }
    return lineM;
  };
}

/**
 * Which cue a description entry is, or null for one that says nothing on the move (a stretch carried
 * straight on, plan section 2: "Straight-on entries get no turn cue unless the junction is flagged").
 */
function cueKindOf(entry: DescriptionEntry, before: DescriptionEntry | null): CueKind | null {
  if (entry.kind === "via") return "stop";
  if (entry.kind === "walk") return "walk";
  if (entry.kind === "junction") return entry.severity || entry.group ? "hazard" : null;
  const movement = entry.turn?.movement ?? null;
  if (movement === "left" || movement === "right") return "turn";
  if (entry.turn?.severity) return "hazard";
  // The first stretch is where the ride starts: nothing to warn of ahead of it.
  if (before === null) return null;
  const tier = entry.tier ?? 0;
  const was = before.kind === "stretch" ? (before.tier ?? 0) : 0;
  if (tier >= 3 && tier > was) return "busy";
  if (entry.surface && !(before.kind === "stretch" && before.surface)) return "unpaved";
  if (was >= 3 && tier > 0 && tier <= 2) return "calmer";
  return null;
}

/** The ride's model: the line, its measure and its cues, from the route as the API answered it. */
export function rideModel(route: RouteResponse): RideModel {
  const coordinates = route.geometry.coordinates;
  const along = lineAlong(coordinates);
  const lengthM = along.length ? along[along.length - 1] : 0;
  const toLine = measureMap(route, along);
  // The full description, every turn (the overview merges short stretches), worded as the
  // panel words it (painted lanes on busy roads as the lanes switch says, OWNER-DECISIONS 275).
  const entries = descriptionEntries(route, "full") ?? [];
  const cues: Cue[] = [];
  const stretches: RideModel["stretches"] = [];
  let before: DescriptionEntry | null = null;
  for (const entry of entries) {
    const fromM = toLine(entry.from_m);
    if (entry.kind === "stretch") stretches.push({ fromM, toM: toLine(entry.to_m), street: entry.street, tier: entry.tier, facility: entry.facility });
    const kind = cueKindOf(entry, before);
    if (kind !== null) {
      cues.push({
        index: cues.length,
        kind,
        atM: fromM,
        text: kind === "stop" ? `Stop ${entry.via ?? cues.filter((c) => c.kind === "stop").length + 1}.` : sentenceOf(entry),
        movement: kind === "turn" ? (entry.turn?.movement as "left" | "right") : null,
        street: entry.turn?.onto ?? entry.street ?? null,
        severity: entry.severity ?? entry.turn?.severity ?? null,
        tier: entry.tier,
        stop: kind === "stop" ? (entry.via ?? cues.filter((c) => c.kind === "stop").length + 1) : null,
      });
    }
    if (entry.kind === "stretch") before = entry;
    else if (entry.kind === "via") before = null;
  }
  cues.push({ index: cues.length, kind: "end", atM: lengthM, text: "The end of the route.", movement: null, street: null, severity: null, tier: null, stop: null });
  const paceMs = route.distance_m > 0 && route.duration_s > 0 ? route.distance_m / route.duration_s : null;
  return { coordinates, along, lengthM, cues, stretches, paceMs };
}

/** Which cues a verbosity level says unprompted (plan section 3's table; Quiet: arrival only). */
export function says(level: Verbosity, cue: Pick<Cue, "kind" | "tier" | "severity">): boolean {
  if (cue.kind === "stop" || cue.kind === "end") return true;
  if (level === "quiet") return false;
  if (level === "full") return true;
  // Stoker: turns, red and orange junctions, walking, and the start of LTS 4 and Avoid stretches.
  if (cue.kind === "turn" || cue.kind === "walk") return true;
  if (cue.kind === "hazard") return cue.severity === "orange" || cue.severity === "red";
  if (cue.kind === "busy") return (cue.tier ?? 0) >= 4;
  return false;
}

// ---- The rider's place on the line ---------------------------------------------------------------

const M_PER_DEG_LAT = 111_195;

export interface Snap {
  /** Metres along the line. */
  alongM: number;
  /** Metres from the fix to the line there. */
  offM: number;
  point: LonLat;
}

/**
 * The nearest point of the line to `p` among the segments that overlap [fromM, toM] along it; among
 * points within `tieM` of the nearest (a loop's start and finish, an out-and-back's two passes), the one
 * nearest `preferM` along: by default the first along, the one a ride reaches first; during a ride, where
 * the rider is expected to be, so the way back of an out-and-back is not taken for the way out. Null on a
 * line of fewer than two vertices.
 */
export function snap(
  model: Pick<RideModel, "coordinates" | "along">,
  p: LonLat,
  fromM = -Infinity,
  toM = Infinity,
  tieM = 15,
  preferM = -Infinity,
): Snap | null {
  const { coordinates: c, along } = model;
  if (c.length < 2) return null;
  const kx = M_PER_DEG_LAT * Math.cos((p[1] * Math.PI) / 180);
  const ky = M_PER_DEG_LAT;
  const found: Snap[] = [];
  let best = Infinity;
  for (let i = 1; i < c.length; i += 1) {
    if (along[i] < fromM || along[i - 1] > toM) continue;
    const ax = (c[i - 1][0] - p[0]) * kx;
    const ay = (c[i - 1][1] - p[1]) * ky;
    const bx = (c[i][0] - p[0]) * kx;
    const by = (c[i][1] - p[1]) * ky;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    // The part of the segment inside the window: a segment that straddles its edge is cut there.
    const span = along[i] - along[i - 1];
    const tLo = span > 0 ? Math.max(0, (fromM - along[i - 1]) / span) : 0;
    const tHi = span > 0 ? Math.min(1, (toM - along[i - 1]) / span) : 1;
    let t = len2 > 0 ? -(ax * dx + ay * dy) / len2 : 0;
    t = Math.max(tLo, Math.min(tHi, t));
    const ex = ax + t * dx;
    const ey = ay + t * dy;
    const off = Math.sqrt(ex * ex + ey * ey);
    const alongM = along[i - 1] + t * span;
    if (off < best) best = off;
    found.push({ alongM, offM: off, point: [c[i - 1][0] + t * (c[i][0] - c[i - 1][0]), c[i - 1][1] + t * (c[i][1] - c[i - 1][1])] });
  }
  if (!found.length) return null;
  const tied = found.filter((s) => s.offM <= best + tieM);
  if (preferM === -Infinity) return tied.sort((a, b) => a.alongM - b.alongM)[0];
  return tied.sort((a, b) => Math.abs(a.alongM - preferM) - Math.abs(b.alongM - preferM) || a.alongM - b.alongM)[0];
}

/** The point `m` metres along the line. */
export function pointAt(model: Pick<RideModel, "coordinates" | "along">, m: number): LonLat {
  const { coordinates: c, along } = model;
  if (c.length === 0) return [0, 0];
  if (m <= 0 || c.length === 1) return c[0];
  const last = c.length - 1;
  if (m >= along[last]) return c[last];
  let lo = 0;
  let hi = last;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (along[mid] <= m) lo = mid;
    else hi = mid;
  }
  const span = along[hi] - along[lo];
  const t = span > 0 ? (m - along[lo]) / span : 0;
  return [c[lo][0] + t * (c[hi][0] - c[lo][0]), c[lo][1] + t * (c[hi][1] - c[lo][1])];
}

// ---- The ride's state and its step ---------------------------------------------------------------

export interface RideFix {
  point: LonLat;
  /** The browser's 68% radius, metres; 0 or less where it gave none. */
  accuracyM: number;
  /** Metres a second from the browser, or null. */
  speedMs: number | null;
  /** Degrees clockwise from north, or null. */
  headingDeg: number | null;
  /** The clock, ms. */
  at: number;
}

export type Phase = "advance" | "prepare" | "ahead" | "now" | "arrive";

export interface RideEvent {
  kind: "cue" | "off-route" | "back-on-route" | "replan";
  /** What is said: US units only (plan Q4), no metric. */
  spoken: string;
  /** "now" cues and leaving the route interrupt (an assertive region; the voice drops what was queued). */
  urgent: boolean;
  cue?: Cue;
  phase?: Phase;
}

export interface RideState {
  /** Metres along the line, or null before the first good fix. */
  progressM: number | null;
  /** The last fix, any quality: the marker. */
  fix: RideFix | null;
  /** The last fix good enough for cues (POOR_FIX_M): where a re-plan starts from. */
  goodFix: RideFix | null;
  /** The last good fix's time, for the window's growth over a gap. */
  goodAt: number | null;
  speedMs: number;
  /** Metres from the line at the last good fix. */
  offM: number;
  /** Phases said, per cue index. */
  said: Record<number, Phase[]>;
  /** Off route, and since when. */
  off: boolean;
  offSince: number | null;
  offCount: number;
  /** Off route and near the line far ahead: the fixes so far, and the last one's place along it. */
  rejoin: { count: number; alongM: number } | null;
  /** Arrived at the end. */
  arrived: boolean;
}

export function startState(): RideState {
  return { progressM: null, fix: null, goodFix: null, goodAt: null, speedMs: 0, offM: 0, said: {}, off: false, offSince: null, offCount: 0, rejoin: null, arrived: false };
}

/** How far off the line counts as off route for a fix of this accuracy (plan section 4). */
export function offThreshold(accuracyM: number): number {
  return Math.min(OFF_MAX_M, Math.max(OFF_MIN_M, OFF_ACCURACY_FACTOR * Math.max(accuracyM, 0)));
}

/** Speech drops the metric the screen keeps: " (90 m)", " (0.6 to 1.9 km)" and "(LTS 1)" kept. */
export function withoutMetric(text: string): string {
  return text.replace(/\s\((?:about )?[\d.,]+(?: to [\d.,]+)? (?:km|m|km\/h)\)/g, "");
}

function lowerFirst(text: string): string {
  return text ? text[0].toLowerCase() + text.slice(1) : text;
}

const MOVEMENT_WORDS = { left: "Left", right: "Right" } as const;

/** What is said for a cue at a phase, `distanceM` before it (US units only). */
export function cueSpoken(cue: Cue, phase: Phase, distanceM: number): string {
  if (cue.kind === "end") return "You have arrived at the end of the route.";
  if (cue.kind === "stop") return `You have reached stop ${cue.stop}.`;
  if (phase === "now" && cue.movement) {
    return `${MOVEMENT_WORDS[cue.movement]} now${cue.street ? ` onto ${cue.street}` : ""}.`;
  }
  return `In ${spokenDistance(distanceM)}, ${lowerFirst(withoutMetric(cue.text))}`;
}

/** The phases a cue is said at, at a level, farthest first, with their thresholds at a speed. */
export function phasesFor(level: Verbosity, cue: Cue, speedMs: number): { phase: Phase; withinM: number }[] {
  if (!says(level, cue)) return [];
  if (cue.kind === "stop" || cue.kind === "end") return [{ phase: "arrive", withinM: ARRIVE_M }];
  const v = Math.max(speedMs, MIN_SPEED_MS);
  const advance = Math.max(ADVANCE_MIN_M, ADVANCE_S * v);
  const prepare = Math.max(PREPARE_MIN_M, PREPARE_S * v);
  const ahead = Math.max(STOKER_MIN_M, STOKER_S * v);
  const now = Math.max(NOW_M, NOW_S * v);
  if (level === "stoker") {
    // One warning ahead, and "now" at a turn (plan Q6: the stoker braces for the lean).
    return cue.kind === "turn" ? [{ phase: "ahead", withinM: ahead }, { phase: "now", withinM: now }] : [{ phase: "ahead", withinM: ahead }];
  }
  if (cue.kind === "turn") {
    return [
      { phase: "advance", withinM: advance },
      { phase: "prepare", withinM: prepare },
      { phase: "now", withinM: now },
    ];
  }
  // A hazard, a walk, a stretch's change: said once, early.
  return [{ phase: "advance", withinM: advance }];
}

/** The sentences for leaving and rejoining the route (plan section 3: said once, gently). */
export const OFF_ROUTE_SAID = "Off the planned route; finding a new way.";
export const OFF_ROUTE_KEPT_SAID = "Off the planned route.";
export const BACK_ON_ROUTE_SAID = "Back on the planned route.";

/** Near fixes in a row along the line far ahead, counting this one (each at least 2 m farther on). */
function rejoinCount(state: RideState, found: Snap): number {
  return state.rejoin === null || found.alongM <= state.rejoin.alongM + 2 ? 1 : state.rejoin.count + 1;
}

/**
 * One fix into the ride: the new state and what to say. `replan` says whether a new way is looked for
 * automatically when the rider leaves the route (plan Q5: yes, after the gate), which only changes the
 * sentence. A poor fix (worse than POOR_FIX_M) moves the marker only.
 */
export function step(
  model: RideModel,
  state: RideState,
  fix: RideFix,
  level: Verbosity,
  replan = true,
): { state: RideState; events: RideEvent[] } {
  const next: RideState = { ...state, fix, said: state.said };
  const events: RideEvent[] = [];
  const accuracy = fix.accuracyM > 0 ? fix.accuracyM : 0;
  if (accuracy > POOR_FIX_M || state.arrived) return { state: next, events };

  next.goodFix = fix;

  // Where on the line: a window round the last progress, growing over a gap in the fixes; among two
  // passes of the same street, the one nearest where the rider is expected to be by now.
  let found: Snap | null;
  if (state.progressM === null) {
    // The first fix: near the start, the start (a loop's return leg passes it too); else anywhere.
    const start = model.coordinates[0];
    found = start && haversineM(fix.point, start) <= START_M ? snap(model, fix.point, 0, WINDOW_AHEAD_M) : null;
  } else if (state.off) {
    // Off route: back on anywhere ahead (or just behind), however far the detour went.
    found = snap(model, fix.point, state.progressM - WINDOW_BEHIND_M, Infinity, 15, state.progressM);
  } else {
    const gapS = state.goodAt === null ? 0 : Math.max(0, (fix.at - state.goodAt) / 1000);
    const expected = state.progressM + Math.max(state.speedMs, MIN_SPEED_MS) * gapS;
    found = snap(model, fix.point, state.progressM - WINDOW_BEHIND_M, state.progressM + WINDOW_AHEAD_M + FAST_MS * gapS, 15, expected);
  }
  // Off the window entirely (a long gap) or a first fix away from the start: the whole line.
  if (found === null) found = snap(model, fix.point);
  if (found === null) return { state: next, events };

  // Speed: the browser's where it gives one, else from progress over time, smoothed.
  let measured: number | null = fix.speedMs !== null && Number.isFinite(fix.speedMs) && fix.speedMs >= 0 ? fix.speedMs : null;
  if (measured === null && state.progressM !== null && state.goodAt !== null && fix.at > state.goodAt) {
    measured = Math.abs(found.alongM - state.progressM) / ((fix.at - state.goodAt) / 1000);
  }
  if (measured !== null) next.speedMs = Math.min(MAX_SPEED_MS, state.speedMs + SPEED_SMOOTHING * (Math.min(measured, MAX_SPEED_MS) - state.speedMs));
  next.goodAt = fix.at;
  next.offM = found.offM;

  // Off route: far from the line for OFF_FIXES good fixes over OFF_MS; back within half the threshold clears it.
  const threshold = offThreshold(accuracy);
  if (!state.off) {
    if (found.offM > threshold) {
      next.offCount = state.offCount + 1;
      next.offSince = state.offSince ?? fix.at;
      if (next.offCount >= OFF_FIXES && fix.at - next.offSince >= OFF_MS) {
        next.off = true;
        if (level !== "quiet") events.push({ kind: "off-route", spoken: replan ? OFF_ROUTE_SAID : OFF_ROUTE_KEPT_SAID, urgent: true });
      }
    } else {
      next.offCount = 0;
      next.offSince = null;
    }
    // Progress moves only while on the line: an excursion does not drag it along a parallel street.
    if (found.offM <= threshold || state.progressM === null) {
      next.progressM = state.progressM === null ? found.alongM : Math.max(found.alongM, state.progressM - BACK_TOLERANCE_M);
    }
  } else if (found.offM > threshold / 2) {
    next.rejoin = null;
  } else if (state.progressM !== null && found.alongM - state.progressM > WINDOW_AHEAD_M && rejoinCount(state, found) < REJOIN_FIXES) {
    // Near the line far ahead: back on only after REJOIN_FIXES fixes in a row riding along it.
    next.rejoin = { count: rejoinCount(state, found), alongM: found.alongM };
  } else {
    next.rejoin = null;
    next.off = false;
    next.offCount = 0;
    next.offSince = null;
    next.progressM = found.alongM;
    // Full only: the stoker hears leaving the route once (plan section 3), quiet nothing.
    if (level === "full") events.push({ kind: "back-on-route", spoken: BACK_ON_ROUTE_SAID, urgent: false });
  }
  if (next.off || next.progressM === null) return { state: next, events };

  // The cues: the first not yet done, at most one sentence per fix.
  const progress = next.progressM;
  const said: Record<number, Phase[]> = { ...state.said };
  for (const cue of model.cues) {
    const phases = phasesFor(level, cue, next.speedMs);
    const done = said[cue.index] ?? [];
    if (phases.every((p) => done.includes(p.phase))) continue;
    const distance = cue.atM - progress;
    if (cue.kind === "end") {
      // The end: along the line within ARRIVE_M of it, and the fix itself near it (a loop's
      // start is its end too, so the line's measure decides, not the distance to the point).
      if (model.lengthM - progress <= ARRIVE_M) {
        said[cue.index] = ["arrive"];
        next.arrived = true;
        events.push({ kind: "cue", spoken: cueSpoken(cue, "arrive", 0), urgent: true, cue, phase: "arrive" });
      }
      break;
    }
    if (distance < -PASSED_M) {
      // Passed before it was said (a gap, or the ride started past it): dropped, never said late.
      said[cue.index] = phases.map((p) => p.phase);
      continue;
    }
    // The nearest phase whose threshold is reached; any farther one is then skipped, not said late.
    const reached = phases.filter((p) => distance <= p.withinM);
    if (!reached.length) break;
    const phase = reached[reached.length - 1];
    if (!done.includes(phase.phase)) {
      events.push({
        kind: "cue",
        spoken: cueSpoken(cue, phase.phase, distance),
        urgent: phase.phase === "now" || phase.phase === "arrive",
        cue,
        phase: phase.phase,
      });
    }
    said[cue.index] = phases.slice(0, phases.indexOf(phase) + 1).map((p) => p.phase);
    // A stop is passed once reached; the next cue waits for the next fix.
    break;
  }
  next.said = said;
  return { state: next, events };
}

// ---- What the screen shows and "Where am I?" says ---------------------------------------------------

/** The next cue the rider will meet (any kind, whatever the level says aloud), or null. */
export function nextCue(model: RideModel, progressM: number): Cue | null {
  return model.cues.find((c) => c.atM > progressM + 1 && c.kind !== "calmer") ?? model.cues[model.cues.length - 1] ?? null;
}

/** The next turn, flagged junction or walk: what the cue card leads with. */
export function nextAction(model: RideModel, progressM: number): Cue | null {
  return model.cues.find((c) => c.atM > progressM + 1 && (c.kind === "turn" || c.kind === "hazard" || c.kind === "walk" || c.kind === "stop" || c.kind === "end")) ?? null;
}

/** The stretch the rider is on: its street as the API names it, or null. */
export function stretchAt(model: RideModel, progressM: number): RideModel["stretches"][number] | null {
  return model.stretches.find((s) => progressM >= s.fromM && progressM < s.toM) ?? model.stretches[model.stretches.length - 1] ?? null;
}

/** The next stop ahead, or null where none is left. */
export function nextStop(model: RideModel, progressM: number): Cue | null {
  return model.cues.find((c) => c.kind === "stop" && c.atM > progressM + ARRIVE_M) ?? null;
}

export interface ToGo {
  /** To the next stop, or null. */
  stop: { number: number; metres: number; seconds: number | null } | null;
  end: { metres: number; seconds: number | null };
}

/** Distance and time to the next stop and to the end, at the route's own pace. */
export function toGo(model: RideModel, progressM: number): ToGo {
  const seconds = (m: number) => (model.paceMs ? m / model.paceMs : null);
  const stop = nextStop(model, progressM);
  const endM = Math.max(0, model.lengthM - progressM);
  return {
    stop: stop ? { number: stop.stop ?? 0, metres: stop.atM - progressM, seconds: seconds(stop.atM - progressM) } : null,
    end: { metres: endM, seconds: seconds(endM) },
  };
}

const COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];

/** The compass word for the bearing from a to b: "northeast". */
export function compassWord(a: LonLat, b: LonLat): string {
  const y = Math.sin(((b[0] - a[0]) * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180);
  const x =
    Math.cos((a[1] * Math.PI) / 180) * Math.sin((b[1] * Math.PI) / 180) -
    Math.sin((a[1] * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180) * Math.cos(((b[0] - a[0]) * Math.PI) / 180);
  const bearing = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
  return COMPASS[Math.round(bearing / 45) % 8];
}

/**
 * Back to the planned route ("Keep the planned route", plan section 4): the nearest point of the
 * line at or ahead of the last progress, its distance and its direction from the rider.
 */
export function wayBack(model: RideModel, state: RideState): { metres: number; direction: string; point: LonLat } | null {
  if (!state.fix) return null;
  const found = snap(model, state.fix.point, state.progressM ?? 0, Infinity);
  if (!found) return null;
  return { metres: haversineM(state.fix.point, found.point), direction: compassWord(state.fix.point, found.point), point: found.point };
}

/** A street as said: "R Street Northwest", or the unnamed kinds. */
function streetWords(stretch: RideModel["stretches"][number] | null): string {
  if (!stretch) return "the route";
  if (stretch.street) return stretch.street;
  return stretch.facility === "path" || stretch.facility === "protected" ? "an unnamed path" : "an unnamed road";
}

// ---- The rider's place in street names (the 311 text, OWNER-DECISIONS 369, 465) -----------------------

/** On a trail, a named junction farther than this (a quarter mile) gives way to the trail marker (465). */
export const TRAIL_MARKER_M = METRES_PER_MILE / 4;

export interface RouteJunction {
  /** Metres along the line. */
  atM: number;
  /** The two streets, as the API names them: the one ridden, then the one met. */
  streets: [string, string];
}

/**
 * The named junctions of the route, from its own data only: each change of named street between two
 * stretches, and each flagged crossing (a junction entry names the street crossed). Never a lookup: the
 * position does not leave the page (plan section 7, owner question 7).
 */
export function routeJunctions(model: RideModel): RouteJunction[] {
  const out: RouteJunction[] = [];
  const seen = new Set<string>();
  const add = (atM: number, a: string | null, b: string | null) => {
    if (!a || !b || a === b) return;
    const key = `${Math.round(atM)}|${a}|${b}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ atM, streets: [a, b] });
  };
  model.stretches.forEach((s, i) => {
    if (i > 0) add(s.fromM, model.stretches[i - 1].street, s.street);
  });
  for (const cue of model.cues) {
    if (cue.kind === "hazard" && cue.movement === null) add(cue.atM, stretchAt(model, cue.atM)?.street ?? null, cue.street);
  }
  return out.sort((a, b) => a.atM - b.atM);
}

/** Whether a stretch is a named trail: a path with a name of its own (the MBT, the CCT). */
function isTrail(stretch: RideModel["stretches"][number] | null): stretch is RideModel["stretches"][number] & { street: string } {
  return !!stretch && stretch.facility === "path" && !!stretch.street;
}

export type RoutePlace =
  | { kind: "junction"; junction: RouteJunction }
  | { kind: "trail"; trail: string; junction: RouteJunction; metres: number; direction: string }
  | { kind: "street"; street: string }
  | null;

/**
 * Where the rider is, in the route's own street names (OWNER-DECISIONS 369, 465): the nearest named
 * junction, behind or ahead (so it may be the last one passed rather than the true nearest, as the owner
 * accepted); on a named trail with no junction within TRAIL_MARKER_M, the trail and a distance from the
 * nearest junction of it, with the direction from there ("Capital Crescent Trail, about 1.2 miles
 * northwest of Massachusetts Avenue"). The trail's posted mile markers are not in the route's data
 * (PLAN.md, FOLLOWUP-WEB-NAV), so the distance is from a junction a reader can find on any map.
 */
export function placeOnRoute(model: RideModel, progressM: number): RoutePlace {
  const junctions = routeJunctions(model);
  const stretch = stretchAt(model, progressM);
  let nearest: RouteJunction | null = null;
  for (const j of junctions) if (!nearest || Math.abs(j.atM - progressM) < Math.abs(nearest.atM - progressM)) nearest = j;
  if (isTrail(stretch) && (!nearest || Math.abs(nearest.atM - progressM) > TRAIL_MARKER_M)) {
    // The trail's own junctions first (where the route met it, the roads it crosses), the last behind
    // before the next ahead; else any.
    const onTrail = junctions.filter((j) => j.streets.includes(stretch.street));
    const behind = onTrail.filter((j) => j.atM <= progressM).at(-1);
    const from = behind ?? onTrail.find((j) => j.atM > progressM) ?? nearest;
    if (!from) return { kind: "street", street: stretch.street };
    const here = pointAt(model, progressM);
    const there = pointAt(model, from.atM);
    return { kind: "trail", trail: stretch.street, junction: from, metres: Math.abs(progressM - from.atM), direction: compassWord(there, here) };
  }
  if (nearest) return { kind: "junction", junction: nearest };
  return stretch?.street ? { kind: "street", street: stretch.street } : null;
}

/** The other street of a trail's junction: "Massachusetts Avenue Northwest". */
export function otherStreet(junction: RouteJunction, trail: string): string {
  return junction.streets[0] === trail ? junction.streets[1] : junction.streets[0];
}

/**
 * "Where am I?" (plan section 3): the street now, the next cue and its distance, the miles to the next
 * stop and to the end. `metric` adds the brackets for the screen; speech has US units only. On a named
 * trail far from any junction, the trail marker of OWNER-DECISIONS 465 ("Navigation cues on those
 * trails can use the same markers").
 */
export function whereAmI(model: RideModel, state: RideState, metric = false): string {
  const dist = (m: number) => (metric ? formatDistance(m) : spokenDistance(m));
  if (state.arrived) return "You have arrived at the end of the route.";
  if (state.progressM === null) return "Finding your place on the route.";
  if (state.off) {
    const back = wayBack(model, state);
    return back
      ? `Off the planned route. The route is ${dist(back.metres)} to the ${back.direction}.`
      : "Off the planned route.";
  }
  const place = placeOnRoute(model, state.progressM);
  const sentences = [
    place?.kind === "trail"
      ? `On ${place.trail}, about ${dist(place.metres)} ${place.direction} of ${otherStreet(place.junction, place.trail)}.`
      : `On ${streetWords(stretchAt(model, state.progressM))}.`,
  ];
  const progress = state.progressM;
  const cue = model.cues.find((c) => c.atM > progress + 1 && (c.kind === "turn" || c.kind === "hazard" || c.kind === "walk"));
  if (cue) {
    const text = metric ? cue.text : withoutMetric(cue.text);
    sentences.push(`Next, in ${dist(cue.atM - state.progressM)}: ${lowerFirst(text)}`);
  }
  const togo = toGo(model, state.progressM);
  if (togo.stop) sentences.push(`${capital(dist(togo.stop.metres))} to stop ${togo.stop.number}.`);
  sentences.push(`${capital(dist(togo.end.metres))} to the end.`);
  return sentences.join(" ");
}

function capital(text: string): string {
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

// ---- Re-planning (plan section 4) ----------------------------------------------------------------------

/**
 * The points a re-plan sends: the rider's position, the stops not yet passed, and the end. A loop
 * re-plans back onto the loop: its end is its start, sent as the last point (the request is then not
 * a loop). `points` are the plan's (the route's own stops in order); the stops' places on the line come
 * from the model's stop cues.
 */
export function replanPoints(model: RideModel, progressM: number, here: LonLat, points: readonly LonLat[], loop: boolean): LonLat[] {
  const stops = loop ? points.slice(1) : points.slice(1, -1);
  const end = loop ? points[0] : points[points.length - 1];
  const left = stops.filter((_, i) => {
    const cue = model.cues.find((c) => c.kind === "stop" && c.stop === i + 1);
    // A stop the description does not place (an older API) is kept: better one extra point than one lost.
    return cue === undefined || cue.atM > progressM + ARRIVE_M;
  });
  return [here, ...left, end];
}

/** The pacing of automatic re-plans: one in flight, 30 s apart, 2 min after two failures in a row. */
export const REPLAN_GAP_MS = 30_000;
export const REPLAN_BACKOFF_MS = 120_000;

export class ReplanGate {
  private inFlight = false;
  private lastAt: number | null = null;
  private failures = 0;

  /** Whether a re-plan may start at `now`; if so it is now in flight. */
  begin(now: number): boolean {
    if (this.inFlight) return false;
    const gap = this.failures >= 2 ? REPLAN_BACKOFF_MS : REPLAN_GAP_MS;
    if (this.lastAt !== null && now - this.lastAt < gap) return false;
    this.inFlight = true;
    this.lastAt = now;
    return true;
  }

  /** The re-plan answered: `ok` resets the backoff. */
  finish(ok: boolean): void {
    this.inFlight = false;
    this.failures = ok ? 0 : this.failures + 1;
  }

  /** The `online` event: the next try need not wait out the gap. */
  online(): void {
    if (!this.inFlight) this.lastAt = null;
  }

  get busy(): boolean {
    return this.inFlight;
  }
}

export const REPLAN_FOUND = "New route found.";
export const REPLAN_NO_SIGNAL = "No signal: the planned route is still shown.";
export const REPLAN_FAILED = "No new route was found; the planned route is still shown.";
