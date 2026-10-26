/**
 * Ride mode's engine (WEB-NAV-plan.md sections 2-4; OWNER-DECISIONS 255, 434, 465): where the rider
 * is along the planned route, which cue is next and when to say it, and whether the rider has left
 * the route. Pure: positions come in as plain fixes with a clock, and what to say comes out as
 * events, so every rule here is tested with synthetic fix sequences (navigate.test.ts) and the page
 * only carries the events to the screen, the live regions and the voice (lib/rideOutput.ts).
 *
 * The cue words are the API's: each cue is a `description` entry (src/routemaker/describe.py), the
 * sentence after its "0.4 to 1.2 mi (0.6 to 1.9 km): " position, so there is still one wording of a
 * stretch to keep right (lib/routeDescription.ts). A turn is the exception (v0.7.0, "Go riding
 * fixes" item 2; the owner, 2026-10-15: "Only say the turn and street. LTS is just extra noise, we
 * can see it."): its cue is the turn and the street alone, "Left onto R Street Northwest.", with no
 * stress or junction words; the road panel and Plan keep the detail. What is added here is the timing
 * ("In 500 feet, ..."), "now" at a turn, arrival and the side the destination is on (item 5), and the
 * off-route sentences.
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
import { mileWords, trailMileAt, type TrailMiles } from "./trailMiles.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { JunctionShape } from "./junctionShape.ts";

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

/**
 * In a browser, rides at most this long get Start ride: a browser ride needs the screen on and the page
 * in front, so a longer one goes to a bike computer (OD 255, plan Q1). The phone app rides with the
 * screen locked and has no limit (lib/rideTrip.ts `rideMaxM`; Stephen, 2026-10-18, a 37 mi saved route
 * with no Start ride).
 */
export const RIDE_MAX_M = 30 * METRES_PER_MILE;
export const RIDE_TOO_LONG =
  `Start ride in a browser is for rides up to ${formatRoughDistance(RIDE_MAX_M)}. Use the phone app, or Download GPX for a bike computer.`;

// ---- Thresholds (plan sections 2 and 4) ---------------------------------------------------------

/** A fix less accurate than this moves the marker but is not used for cues or off route (about 165 ft). */
export const POOR_FIX_M = 50;
/**
 * Only poor fixes for this long: the cues are paused without a word otherwise (a poor fix still counts
 * as GPS alive, so the GPS-lost note never comes), so the rider is told once (review RIDE-3).
 */
export const GPS_WEAK_MS = 12_000;
export const GPS_WEAK_SAID = "GPS is weak: turn cues paused.";

/** The last good fix's time, and whether the weak-GPS note is up. */
export interface GpsWeakness {
  goodAt: number;
  weak: boolean;
}

/** A fix of `accuracyM` at `now`: the next state, and `sayNow` the once the note goes up. A good fix takes it down. */
export function weighFix(before: GpsWeakness, accuracyM: number, now: number): GpsWeakness & { sayNow: boolean } {
  if (!(accuracyM > POOR_FIX_M)) return { goodAt: now, weak: false, sayNow: false };
  if (before.weak || now - before.goodAt < GPS_WEAK_MS) return { ...before, sayNow: false };
  return { goodAt: before.goodAt, weak: true, sayNow: true };
}

/**
 * Weak GPS for longer than this, or than the ride would take to reach its next turn from the last good
 * fix, whichever is longer: the card shows the turns ahead as an ordered list (the owner, 2026-10-16,
 * review RIDE-3), since the turn-by-turn card cannot know where the rider is.
 */
export const CUE_SHEET_MIN_MS = 60_000;
export const CUE_SHEET_SAID = "GPS is still weak: the turns ahead are shown as a list, next turn first.";
/** The list's length: the turns of a dead spot, not the whole ride. */
export const CUE_SHEET_ROWS = 10;

/** How long only poor fixes since the last good one (at `progressM`, riding at `speedMs`) before the list shows. */
export function cueSheetAfterMs(model: RideModel, progressM: number, speedMs: number): number {
  const next = model.cues.find((c) => c.kind === "turn" && c.atM > progressM + 1);
  // The ride's own speed; stopped (or not yet measured), the route's pace.
  const speed = speedMs > MIN_SPEED_MS ? speedMs : model.paceMs;
  if (!next || !speed) return CUE_SHEET_MIN_MS;
  return Math.max(CUE_SHEET_MIN_MS, ((next.atM - progressM) / speed) * 1000);
}

/**
 * Whether the list shows at `now`: no good fix since `goodAt` for `afterMs`, whether poor fixes came or
 * none at all (RideMode asks on each fix and on a timer); a good fix (a new `goodAt`) ends it.
 */
export function cueSheetShown(weakness: GpsWeakness, now: number, afterMs: number): boolean {
  return now - weakness.goodAt >= afterMs;
}
/** How often RideMode asks, so the list comes when the fixes stop altogether too. */
export const CUE_SHEET_CHECK_MS = 3000;

/** One row of the list: how far on from the row before (the first from `progressM`), and the cue. */
export interface CueSheetRow {
  index: number;
  distance: string;
  text: string;
}

/**
 * The turns, stops and end ahead of `progressM`, in order, each with the distance from the one before. A jog's
 * second turn has no row: the first's says it.
 */
export function cueSheet(model: RideModel, progressM: number): CueSheetRow[] {
  let from = progressM;
  return model.cues
    .filter((c) => c.atM > progressM + 1 && !c.joined && (c.kind === "turn" || c.kind === "onto" || c.kind === "stop" || c.kind === "end"))
    .slice(0, CUE_SHEET_ROWS)
    .map((c, i) => {
      const row = { index: c.index, distance: `${i === 0 ? "In" : "Then in"} ${formatDistance(c.atM - from)}`, text: c.text };
      from = c.atM;
      return row;
    });
}
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

export type CueKind = "turn" | "onto" | "hazard" | "walk" | "busy" | "calmer" | "unpaved" | "stop" | "end";

/** A turn's movement: a bear is a change of street a little off straight (the API's describe.SLIGHT_MIN_DEG). */
export type TurnMovement = "left" | "right" | "bear_left" | "bear_right" | "uturn";

function isTurnMovement(movement: string | null | undefined): movement is TurnMovement {
  return movement === "left" || movement === "right" || movement === "bear_left" || movement === "bear_right";
}

/**
 * A jog (the owner, 2026-10-16, on Q Street NW: "complex turns which aren't announced"): a turn this
 * close after another is said with it, "Right onto 6th Street, then immediately bear left onto Rhode
 * Island Avenue.", early enough for both.
 */
export const JOG_M = 100;

export interface Cue {
  /** Its place in the list, also its key. */
  index: number;
  kind: CueKind;
  /** Metres along the line (the geometry's own length). */
  atM: number;
  /**
   * What the cue says, without a position: a turn's is the turn and the street only ("Left onto R
   * Street Northwest."); any other cue's is the API's sentence ("R Street Northwest, busy road (LTS 3).").
   */
  text: string;
  /** What Ride says and shows in place of `text`, where it differs: a flagged crossing's short line ("Busy crossing at C Street, no signal."). */
  rideText?: string;
  movement: TurnMovement | null;
  /** The street the cue turns onto or is on, as the API names it; null where unnamed. */
  street: string | null;
  severity: "orange" | "red" | "avoid" | null;
  /** The stretch's tier after the cue, 1-5, or null. */
  tier: number | null;
  /** A stop's number (from 1); null on any other cue. */
  stop: number | null;
  /** A stop's own name (2026-10-24: the rider's, or a file's), said and shown with its number; absent with none. */
  stopName?: string;
  /** A jog's first turn: the turn just after it (within JOG_M), said with it. */
  then?: { movement: TurnMovement; street: string | null; exit?: CircleExit };
  /**
   * A jog's second turn: said with the turn before (its `then`); on its own only at "now", and only where the
   * turn before's "now" was never said (a gap in the fixes, a ride started or rejoined between the two). Still on
   * the card and in the courses; not a row of the cue sheets.
   */
  joined?: boolean;
  /** A turn at an unusual junction (v0.10.0): its ways, which the card draws in place of the plain arrow; never said. */
  junction?: JunctionShape;
  /** The way off a circle (v0.10.0): its exit, said ("take the 3rd exit") and drawn as a ring. */
  exit?: CircleExit;
  /** A short path across a road between two turns: the road, said in place of the turn ("Cross Redland Road."), drawn straight on. */
  cross?: string;
  /** A turn onto a path just across a road (describe._far_side_turns): the road, said first ("Cross Saint Paul Street, then right onto ..."), drawn across it. */
  across?: string;
  /** A closure's source and until when (v0.8.2): shown in small print on the card, never said. */
  citation?: string;
  /** The description entry's kind it came from (a course export keeps Avoid and work-zone hazards); absent on the end. */
  source?: DescriptionEntry["kind"];
  /**
   * A stop's place in the plan's points, when it differs from its number (v0.7.0: via points between are not
   * numbered); the re-plan matches on it.
   */
  point?: number;
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
  /**
   * The route's time along the line (the API's time_marks scaled to its duration): metres and the seconds from the
   * start there, hills and junction waits in place. Absent where the API sent none; the time is then spread evenly.
   */
  timeline?: { m: Float64Array; s: Float64Array };
  /**
   * The via points (v0.7.0, "Via points vs stops"): where the line passes each, by its place in the plan's
   * points. Never a cue: a via point is not announced; the re-plan drops the ones passed.
   */
  passes?: { point: number; atM: number }[];
}

/**
 * A turn's cue (v0.7.0, "Go riding fixes" item 2): the turn and the street, nothing else. "Left onto R
 * Street Northwest."; "Right onto the path." for a path with no name; "Left." where the street has none;
 * "Bear right onto ..." for a bear; "Bear right to stay on Paint Branch Trail." at a fork along one way
 * (`stay`, describe.fork_movement).
 */
export function turnWords(movement: TurnMovement, street: string | null, stay = false, exit: CircleExit | null = null): string {
  if (movement === "uturn") return UTURN_SAID;
  if (exit) return `${exitWords(exit, street)}.`;
  const turn = MOVEMENT_WORDS[movement];
  const onto = stay ? "to stay on" : "onto";
  if (street && /^(?:unnamed )?path$/i.test(street.trim())) return `${turn} ${onto} the path.`;
  return street && !isUnnamed(street) ? `${turn} ${onto} ${wayWords(street)}.` : `${turn}.`;
}

/** The way off a circle (describe.circle_exit): its exit, counting the streets off the ring the route passes. */
export interface CircleExit {
  number: number;
  circle: string | null;
}

/** "1st", "2nd", "3rd", "4th", "11th", "21st" (describe.ordinal). */
export function ordinal(n: number): string {
  if ([11, 12, 13].includes(n % 100)) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/**
 * "Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest" (describe.exit_words; the owner, 2026-10-20,
 * "Ring picture + exit number"): the exit first, so the card shows it whole.
 */
export function exitWords(exit: CircleExit, street: string | null): string {
  const onto = street && !isUnnamed(street) ? ` onto ${wayWords(street)}` : "";
  return `Take the ${ordinal(exit.number)} exit${onto} at ${exit.circle ?? "the roundabout"}`;
}

/**
 * The ways the API names by what they are (src/routemaker/describe.py SERVICE_WORDS and beside_words; the
 * owner, 2026-10-20: "When going on a service road, especially next to a major road, say so"): "service
 * road", "service road beside East-West Highway", "sidewalk beside ...", "path beside ...", "alley".
 */
const COMMON_WAY = /^(?:path|sidewalk|service road|alley|parking aisle)\b/;
/** A service way: going onto one is always said, straight on too, so the rider leaves the main road for it. */
const SERVICE_WAY = /^(?:service road|alley|parking aisle)\b/;

/** A way as a sentence names it: "the service road beside East-West Highway", a street's own name as it is. */
export function wayWords(street: string): string {
  return COMMON_WAY.test(street) ? `the ${street}` : street;
}

const CROSSING_CONTROL_WORDS: Partial<Record<NonNullable<NonNullable<DescriptionEntry["turn"]>["control"]>, string>> = {
  signal: "signal",
  stop: "stop sign",
  all_stop: "stop sign",
  none: "no signal",
};

/**
 * A flagged crossing's line in Ride (the owner, 2026-10-17: "a notice or warning when approaching a busy
 * intersection"): "Busy crossing at C Street, no signal.", no LTS and no stress words; the control left out
 * where unknown.
 */
export function crossingWords(street: string | null, control: NonNullable<DescriptionEntry["turn"]>["control"] | undefined): string {
  const where = street && !isUnnamed(street) ? ` at ${street}` : "";
  const how = control ? CROSSING_CONTROL_WORDS[control] : undefined;
  return `Busy crossing${where}${how ? `, ${how}` : ""}.`;
}

/** Which side the destination is on (item 5), from the router's destination maneuver; null when unknown. */
export type ArrivalSide = "left" | "right" | null | undefined;

/** "Destination on your right." for a known side, else nothing. */
export function arrivalSideWords(side: ArrivalSide): string {
  return side === "left" || side === "right" ? `Destination on your ${side}.` : "";
}

/** The end cue's words: "The end of the route.", with the destination's side where the router knows it. */
export function endWords(side: ArrivalSide): string {
  const where = arrivalSideWords(side);
  return where ? `The end of the route. ${where}` : "The end of the route.";
}

/** "0.4 to 1.2 mi (0.6 to 1.9 km): Left onto ..." without its position: the part after the first ": ". */
export function sentenceOf(entry: Pick<DescriptionEntry, "text">): string {
  const text = entry.text.trim();
  const at = text.indexOf(": ");
  return at >= 0 ? text.slice(at + 2) : text;
}

/** Metres along the geometry's own vertices. */
export function lineAlong(coordinates: readonly LonLat[]): Float64Array {
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

/** A road's new name straight on is said only when it lasts longer than this (a quarter mile). */
export const ONTO_ROAD_MIN_M = METRES_PER_MILE / 4;
/**
 * A new trail's name straight on is said only when it lasts at least this (about 1,000 ft); only a named
 * way this long is the one ridden, and one that resumes within this of where it was left (after a
 * connector or a short other name) is not said again.
 */
export const ONTO_TRAIL_MIN_M = 300;

/** "Continue onto Mount Vernon Trail.": a new name straight on. */
export function ontoWords(street: string): string {
  return `Continue onto ${wayWords(street)}.`;
}

/** The last named way ridden, and where (description metres) it ended. */
type LastNamed = { street: string; toM: number } | null;

/** Whether one name is the other with more after it ("X Street NW" and "X Street NW protected bike lane"). */
function sameStem(a: string | null, b: string): boolean {
  if (!a) return false;
  const x = a.trim().toLowerCase();
  const y = b.trim().toLowerCase();
  return x.startsWith(y) || y.startsWith(x);
}

/**
 * Whether a stretch entered straight on is a new named way worth a cue (the owner, 2026-10-16: "the
 * Custus trail switches to the Mt vernon trail but somehow doesn't state that"): its name is real, is
 * the way's own (not only its trail relation's, `relation_name`), is not the one ridden nor that name
 * with more after it, and a path is on either side and the new name lasts at least ONTO_TRAIL_MIN_M; a
 * road that only changes its name, when the new one lasts more than ONTO_ROAD_MIN_M. A named way that
 * resumes within ONTO_TRAIL_MIN_M of where it was left (a connector, or a short other name) is not
 * said again.
 */
function isOnto(entry: DescriptionEntry, before: DescriptionEntry, lastNamed: LastNamed): boolean {
  if (entry.kind !== "stretch" || before.kind !== "stretch" || entry.relation_name) return false;
  const street = entry.street;
  if (!street || isUnnamed(street) || sameStem(before.street, street)) return false;
  if (lastNamed && lastNamed.street === street && entry.from_m - lastNamed.toM <= ONTO_TRAIL_MIN_M) return false;
  if (SERVICE_WAY.test(street)) return true;
  const length = entry.to_m - entry.from_m;
  if (entry.facility === "path" || before.facility === "path") return length >= ONTO_TRAIL_MIN_M;
  return length > ONTO_ROAD_MIN_M;
}

/**
 * Which cue a description entry is, or null for one that says nothing on the move (a stretch carried
 * straight on, plan section 2: "Straight-on entries get no turn cue unless the junction is flagged"),
 * except a new named trail or a lasting new road name (`isOnto`).
 */
function cueKindOf(entry: DescriptionEntry, before: DescriptionEntry | null, lastNamed: LastNamed = null): CueKind | null {
  if (entry.kind === "via") return "stop";
  if (entry.kind === "walk") return "walk";
  // An Avoid-rated junction ahead (OWNER-DECISIONS 307): a hazard, said at every level but Quiet.
  if (entry.kind === "avoid") return "hazard";
  // A work zone on the route (FOLLOWUP-WORKZONES): a hazard; the disclaimer line says nothing on the move.
  if (entry.kind === "workzone") return entry.severity ? "hazard" : null;
  // A categorised climb (FOLLOWUP-HILL-SEEK) is in the list to read, not a cue on the move.
  if (entry.kind === "climb") return null;
  // A known road hazard on the route (v0.10.0: cobblestones, rails in the road): said ahead, as a hazard.
  if (entry.kind === "hazard") return "hazard";
  if (entry.kind === "junction") return entry.severity || entry.group ? "hazard" : null;
  if (isTurnMovement(entry.turn?.movement)) return "turn";
  if (entry.turn?.severity) return "hazard";
  // The first stretch is where the ride starts: nothing to warn of ahead of it.
  if (before === null) return null;
  const tier = entry.tier ?? 0;
  const was = before.kind === "stretch" ? (before.tier ?? 0) : 0;
  if (tier >= 3 && tier > was) return "busy";
  if (entry.surface && !(before.kind === "stretch" && before.surface)) return "unpaved";
  if (was >= 3 && tier > 0 && tier <= 2) return "calmer";
  if (isOnto(entry, before, lastNamed)) return "onto";
  return null;
}

/** The ride's model: the line, its measure and its cues, from the route as the API answered it. */
/** A stop cue's words: "Stop 2." or, named, "Stop 2, Union Market." */
export function stopText(number: number, name: string | undefined): string {
  return name ? `Stop ${number}, ${name}.` : `Stop ${number}.`;
}

export function rideModel(route: RouteResponse, vias: readonly number[] = [], names: ReadonlyMap<number, string> = new Map()): RideModel {
  const coordinates = route.geometry.coordinates;
  const along = lineAlong(coordinates);
  const lengthM = along.length ? along[along.length - 1] : 0;
  const toLine = measureMap(route, along);
  // The full description, every turn (the overview merges short stretches), worded as the
  // panel words it (painted lanes on busy roads as the lanes switch says, OWNER-DECISIONS 275).
  const entries = descriptionEntries(route, "full") ?? [];
  const cues: Cue[] = [];
  const stretches: RideModel["stretches"] = [];
  const passes: { point: number; atM: number }[] = [];
  let before: DescriptionEntry | null = null;
  let lastNamed: LastNamed = null;
  for (const entry of entries) {
    const fromM = toLine(entry.from_m);
    if (entry.kind === "stretch") stretches.push({ fromM, toM: toLine(entry.to_m), street: entry.street, tier: entry.tier, facility: entry.facility });
    // A via point (v0.7.0): its place is kept for the re-plan, but it is no cue and has no number.
    if (entry.kind === "via" && entry.via != null && vias.includes(entry.via)) {
      passes.push({ point: entry.via, atM: fromM });
      before = null;
      lastNamed = null;
      continue;
    }
    const kind = cueKindOf(entry, before, lastNamed);
    if (kind === "stop" && vias.length && entry.via != null) {
      // Stops are numbered among themselves: the via points before this one are left out of its number.
      const point = entry.via;
      const number = point - vias.filter((v) => v < point).length;
      const stopName = names.get(point);
      cues.push({ index: cues.length, kind, atM: fromM, text: stopText(number, stopName), movement: null, street: entry.turn?.onto ?? entry.street ?? null, severity: entry.severity ?? entry.turn?.severity ?? null, tier: entry.tier, stop: number, point, source: entry.kind, ...(stopName ? { stopName } : {}) });
    } else if (kind !== null) {
      cues.push({
        index: cues.length,
        kind,
        atM: fromM,
        text:
          kind === "stop"
            ? stopText(entry.via ?? cues.filter((c) => c.kind === "stop").length + 1, entry.via != null ? names.get(entry.via) : undefined)
            : kind === "turn" && entry.turn?.cross
              ? crossWords(entry.turn.cross)
              : kind === "turn" && entry.turn?.across
              ? acrossWords(entry.turn.across, entry.turn.movement as TurnMovement, entry.turn.onto ?? entry.street ?? null)
              : kind === "turn"
              ? turnWords(entry.turn?.movement as TurnMovement, entry.turn?.onto ?? entry.street ?? null, entry.turn?.stay === true, entry.turn?.exit ?? null)
              : kind === "onto"
                ? ontoWords(entry.street as string)
                : sentenceOf(entry),
        ...(kind === "hazard" && entry.kind === "junction" && !entry.group ? { rideText: crossingWords(entry.street, entry.turn?.control) } : {}),
        ...(entry.kind === "hazard" ? { rideText: roadHazardWords(entry.text) } : {}),
        ...(entry.citation ? { citation: entry.citation } : {}),
        ...(kind === "turn" && entry.turn?.shape && !entry.turn.cross ? { junction: entry.turn.shape } : {}),
        ...(kind === "turn" && entry.turn?.cross ? { cross: entry.turn.cross } : {}),
        ...(kind === "turn" && entry.turn?.across && !entry.turn.cross ? { across: entry.turn.across } : {}),
        ...(kind === "turn" && entry.turn?.exit ? { exit: entry.turn.exit } : {}),
        movement: kind === "turn" ? (entry.turn?.movement as TurnMovement) : null,
        street: entry.turn?.onto ?? entry.street ?? null,
        severity: entry.severity ?? entry.turn?.severity ?? null,
        tier: entry.tier,
        stop: kind === "stop" ? (entry.via ?? cues.filter((c) => c.kind === "stop").length + 1) : null,
        ...(kind === "stop" && entry.via != null && names.get(entry.via) ? { stopName: names.get(entry.via) } : {}),
        source: entry.kind,
      });
    }
    if (entry.kind === "stretch") {
      before = entry;
      if (!isUnnamed(entry.street) && entry.to_m - entry.from_m >= ONTO_TRAIL_MIN_M) lastNamed = { street: entry.street as string, toM: entry.to_m };
    } else if (entry.kind === "via") {
      before = null;
      lastNamed = null;
    }
  }
  joinJogs(cues);
  cues.push({ index: cues.length, kind: "end", atM: lengthM, text: endWords(route.arrival_side), movement: null, street: null, severity: null, tier: null, stop: null });
  const paceMs = route.distance_m > 0 && route.duration_s > 0 ? route.distance_m / route.duration_s : null;
  const timeline = timelineOf(route.time_marks, lengthM, route.duration_s);
  return { coordinates, along, lengthM, cues, stretches, paceMs, ...(timeline ? { timeline } : {}), ...(vias.length ? { passes } : {}) };
}

/**
 * The API's time marks ([fraction, seconds], routemaker.time_marks) as metres and seconds along a line of `lengthM`,
 * scaled so the end is `durationS` (the route's time also holds a walked stretch, or Mountain bike's singletrack
 * pace, which the marks leave out). Null where they are missing, out of order or carry no time.
 */
export function timelineOf(marks: readonly (readonly number[])[] | null | undefined, lengthM: number, durationS: number): { m: Float64Array; s: Float64Array } | null {
  if (!marks || marks.length < 2 || !(lengthM > 0) || !(durationS > 0)) return null;
  const last = marks[marks.length - 1][1];
  if (!(last > 0)) return null;
  const m = new Float64Array(marks.length);
  const s = new Float64Array(marks.length);
  for (let i = 0; i < marks.length; i++) {
    const [f, t] = marks[i];
    if (!Number.isFinite(f) || !Number.isFinite(t) || (i && (f < marks[i - 1][0] || t < marks[i - 1][1]))) return null;
    m[i] = Math.min(1, Math.max(0, f)) * lengthM;
    s[i] = (t / last) * durationS;
  }
  return { m, s };
}

/**
 * The route's seconds from its start to `atM` along the line: from its timeline (hills and junction waits where they
 * are, the owner 2026-10-26: "make sure intersection waits are considered too"), else at its own even pace; null
 * with neither. A junction's wait counts once the place is reached.
 */
export function secondsAt(model: RideModel, atM: number): number | null {
  const line = model.timeline;
  if (!line) return model.paceMs ? Math.max(0, atM) / model.paceMs : null;
  const { m, s } = line;
  if (atM <= m[0]) return s[0];
  if (atM >= m[m.length - 1]) return s[s.length - 1];
  // The last mark at or before atM (a wait's two marks share a place: the later one, past the wait).
  let lo = 0;
  let hi = m.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (m[mid] <= atM) lo = mid;
    else hi = mid;
  }
  const span = m[hi] - m[lo];
  return span > 0 ? s[lo] + ((s[hi] - s[lo]) * (atM - m[lo])) / span : s[lo];
}

/** The route's seconds from `fromM` to `toM` along the line (secondsAt), or null. */
export function secondsBetween(model: RideModel, fromM: number, toM: number): number | null {
  const a = secondsAt(model, fromM);
  const b = secondsAt(model, toM);
  return a === null || b === null ? null : Math.max(0, b - a);
}

/** The road crossed where it has no name (describe.CROSS_UNNAMED). */
export const CROSS_UNNAMED = "the road";

/** "Cross Redland Road.": a short path across a road between two turns (describe._crossing). */
export function crossWords(road: string): string {
  return `Cross ${wayWords(road)}.`;
}

/**
 * The ride card's arrow across a road, then the turn on its far side (the owner, 2026-10-24: "make it clear both from
 * the arrow and directions to cross the road then turn right"): for a crossing between two turns (crossWords) with the
 * turn after it, or a turn onto a path just across a road (acrossWords). A crossing on its own is "cross", straight
 * over the road; null for any other cue.
 */
export function crossArrow(cue: Pick<Cue, "cross" | "across" | "then" | "movement">): "cross" | "cross_left" | "cross_right" | null {
  const after = cue.cross ? cue.then?.movement : cue.across ? cue.movement : undefined;
  if (after === "left" || after === "bear_left") return "cross_left";
  if (after === "right" || after === "bear_right") return "cross_right";
  return cue.cross ? "cross" : null;
}

/** "Cross Saint Paul Street, then right onto Saint Paul Street bike lane.": a turn onto a path just across a road (describe._far_side_turns). */
export function acrossWords(road: string, movement: TurnMovement, street: string | null): string {
  return `Cross ${wayWords(road)}, then ${lowerFirst(turnWords(movement, street))}`;
}

/**
 * ", then immediately bear left onto Rhode Island Avenue.": a jog's second turn, after the first; after a crossing
 * only ", then left onto ..." (the owner, 2026-10-20: "cross the street and turn left").
 */
function thenWords(then: NonNullable<Cue["then"]>, crossing = false): string {
  return `, then ${crossing ? "" : "immediately "}${lowerFirst(turnWords(then.movement, then.street, false, then.exit ?? null))}`;
}

/**
 * A jog: each turn within JOG_M after a turn (not itself a jog's second) is said with it, the first
 * cue's text "Right onto 6th Street, then immediately bear left onto ...", the second kept (`joined`)
 * for the card and the courses (`phasesFor`, `step`).
 */
function joinJogs(cues: Cue[]): void {
  for (let i = 0; i + 1 < cues.length; i++) {
    const first = cues[i];
    const second = cues[i + 1];
    if (first.kind !== "turn" || second.kind !== "turn" || first.joined || !first.movement || !second.movement) continue;
    // A crossing is never said as a turn after another: it leads its own cue, with the turn after it. A turn across a
    // road already says two things: the turn after it keeps its own cue.
    if (second.cross || second.across || first.across) continue;
    if (second.atM - first.atM > JOG_M) continue;
    first.then = { movement: second.movement, street: second.street, ...(second.exit ? { exit: second.exit } : {}) };
    first.text = first.text.replace(/\.$/, "") + thenWords(first.then, first.cross !== undefined);
    second.joined = true;
  }
}

/** Which cues a verbosity level says unprompted (plan section 3's table; Quiet: arrival only). */
/**
 * Ride's short line for a known road hazard (v0.10.0), from the directions' sentence ("Rails in the road on H
 * Street Northeast, 0.4 to 1.2 mi (...): cross them square on, ..."): "Rails in the road on H Street Northeast.
 * Cross them square on, a wheel can drop into the groove.", said "In 500 feet, rails in the road on ...".
 */
export function roadHazardWords(text: string): string {
  const m = /^(.*?) on (.*?), (?:at [\d.]+|[\d.]+ to [\d.]+) mi \([^)]*\): (.*)$/.exec(text);
  if (!m) return text;
  return `${m[1]} on ${m[2]}. ${m[3].charAt(0).toUpperCase()}${m[3].slice(1)}`;
}

export function says(level: Verbosity, cue: Pick<Cue, "kind" | "tier" | "severity"> & Pick<Partial<Cue>, "source">): boolean {
  if (cue.kind === "stop" || cue.kind === "end") return true;
  if (level === "quiet") return false;
  if (level === "full") return true;
  // Stoker: turns, red and orange junctions, walking, and the start of LTS 4 and Avoid stretches.
  if (cue.kind === "turn" || cue.kind === "walk") return true;
  if (cue.kind === "hazard") return cue.source === "hazard" || cue.severity === "orange" || cue.severity === "red" || cue.severity === "avoid";
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

function lowerFirst(text: string): string {
  return text ? text[0].toLowerCase() + text.slice(1) : text;
}

/** Speech drops the metric the screen keeps: " (90 m)", " (0.6 to 1.9 km)" and "(LTS 1)" kept. */
export function withoutMetric(text: string): string {
  return text.replace(/\s\((?:about )?[\d.,]+(?: to [\d.,]+)? (?:km|m|km\/h)\)/g, "");
}

const MOVEMENT_WORDS = { left: "Left", right: "Right", bear_left: "Bear left", bear_right: "Bear right", uturn: "Make a U-turn" } as const;

/**
 * What is said for a cue at a phase, `distanceM` before it (US units only). `first`: nothing was said for this cue
 * yet (a ride that starts, or a GPS gap that ends, inside the prepare distance has no advance warning).
 */
export function cueSpoken(cue: Cue, phase: Phase, distanceM: number, first = phase === "advance" || phase === "ahead"): string {
  if (cue.kind === "end") {
    // The side, where known, is the end cue's own last sentence ("Destination on your right.").
    const side = cue.text.match(/Destination on your (?:left|right)\.$/)?.[0];
    return side ? `You have arrived at the end of the route. ${side}` : "You have arrived at the end of the route.";
  }
  if (cue.kind === "stop") return cue.stopName ? `You have reached stop ${cue.stop}, ${cue.stopName}.` : `You have reached stop ${cue.stop}.`;
  if (phase === "now" && cue.movement) {
    // A jog's "now" is short, the second turn being only seconds on: "Right now, then bear left onto ...".
    const lead = cue.cross ? `Cross ${wayWords(cue.cross)}` : cue.exit ? "Exit" : MOVEMENT_WORDS[cue.movement];
    if (cue.then) return `${lead} now, then ${lowerFirst(turnWords(cue.then.movement, cue.then.street, false, cue.then.exit ?? null))}`;
    if (cue.cross) return `Cross ${wayWords(cue.cross)} now.`;
    if (cue.across && cue.movement !== "uturn") return `Cross ${wayWords(cue.across)} now, then ${lowerFirst(turnWords(cue.movement, cue.street))}`;
    if (cue.movement === "uturn") return "Make a U-turn now.";
    if (cue.exit) return `Exit now${cue.street && !isUnnamed(cue.street) ? ` onto ${wayWords(cue.street)}` : ""}.`;
    return `${MOVEMENT_WORDS[cue.movement]} now${cue.street ? ` onto ${wayWords(cue.street)}` : ""}.`;
  }
  // A turn at a flagged junction says so in its first warning only; "now" is the turn alone.
  const busy = cue.kind === "turn" && (cue.severity === "orange" || cue.severity === "red") && first;
  return `In ${spokenDistance(distanceM)}, ${lowerFirst(withoutMetric(cue.rideText ?? cue.text))}${busy ? " Busy junction." : ""}`;
}

/**
 * The phases a cue is said at, at a level, farthest first, with their thresholds at a speed. A jog's second turn
 * has "now" only, which `step` marks said when the turn before says its own "now".
 */
export function phasesFor(level: Verbosity, cue: Cue, speedMs: number): { phase: Phase; withinM: number }[] {
  if (!says(level, cue)) return [];
  if (cue.kind === "stop" || cue.kind === "end") return [{ phase: "arrive", withinM: ARRIVE_M }];
  const v = Math.max(speedMs, MIN_SPEED_MS);
  const advance = Math.max(ADVANCE_MIN_M, ADVANCE_S * v);
  const prepare = Math.max(PREPARE_MIN_M, PREPARE_S * v);
  const ahead = Math.max(STOKER_MIN_M, STOKER_S * v);
  const now = Math.max(NOW_M, NOW_S * v);
  if (cue.joined) return [{ phase: "now", withinM: now }];
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
        spoken: cueSpoken(cue, phase.phase, distance, done.length === 0),
        urgent: phase.phase === "now" || phase.phase === "arrive",
        cue,
        phase: phase.phase,
      });
      // A jog's "now" says its second turn too, which then says nothing of its own.
      if (phase.phase === "now" && cue.then) said[cue.index + 1] = ["now"];
    }
    said[cue.index] = phases.slice(0, phases.indexOf(phase) + 1).map((p) => p.phase);
    // A stop is passed once reached; the next cue waits for the next fix.
    break;
  }
  next.said = said;
  return { state: next, events };
}

// ---- What the screen shows and "Where am I?" says ---------------------------------------------------

/**
 * Whether a cue is still ahead of the rider: past its point by less than a metre, or a re-route's U-turn (at the
 * line's start, so never ahead) until the rider is PASSED_M along the new way, turned round (the owner, 2026-10-20:
 * "There's no U turn symbol.").
 */
function ahead(model: RideModel, cue: Cue, progressM: number): boolean {
  if (cue.atM > progressM + 1) return true;
  // A next cue close to the start takes over halfway to it, as the voice turns to it.
  const then = model.cues[cue.index + 1]?.atM ?? Infinity;
  return cue.movement === "uturn" && progressM < Math.min(PASSED_M, then / 2);
}

/** The next turn, new named way, flagged junction or walk: what the cue card leads with. */
export function nextAction(model: RideModel, progressM: number): Cue | null {
  return model.cues.find((c) => ahead(model, c, progressM) && (c.kind === "turn" || c.kind === "onto" || c.kind === "hazard" || c.kind === "walk" || c.kind === "stop" || c.kind === "end")) ?? null;
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

/** Distance and time to the next stop and to the end, at the route's own time along the line (secondsBetween). */
export function toGo(model: RideModel, progressM: number): ToGo {
  const stop = nextStop(model, progressM);
  const endM = Math.max(0, model.lengthM - progressM);
  return {
    stop: stop ? { number: stop.stop ?? 0, metres: stop.atM - progressM, seconds: secondsBetween(model, progressM, stop.atM) } : null,
    end: { metres: endM, seconds: secondsBetween(model, progressM, model.lengthM) },
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

/**
 * Whether a street name says nothing: the API's stand-ins for a way with no name ("unnamed path",
 * "unnamed road", "this part of the route"; src/routemaker/describe.py, lib/federalStops.ts). Such a
 * name is never a place to measure from or a trail to name.
 */
export function isUnnamed(street: string | null | undefined): boolean {
  return !street || /\bunnamed\b/i.test(street) || /^(?:path|this part of the route)$/i.test(street.trim());
}

/**
 * The way ridden as said, for "Where am I?" and the 311 report: its name ("R Street Northwest"), else
 * what it is ("a path", the owner's word since v0.7.0, or "an unnamed road"), else null (not traced, or
 * "this part of the route").
 */
export function wayRidden(stretch: RideModel["stretches"][number] | null): string | null {
  if (!stretch) return null;
  if (!isUnnamed(stretch.street)) return wayWords(stretch.street as string);
  if (stretch.street && /^this part of the route$/i.test(stretch.street.trim())) return null;
  // The API's own word first ("unnamed road"), else the facility.
  if (/\bpath\b/i.test(stretch.street ?? "")) return "a path";
  if (/\broad\b/i.test(stretch.street ?? "")) return "an unnamed road";
  return stretch.facility === "path" || stretch.facility === "protected" ? "a path" : "an unnamed road";
}

// ---- The rider's place in street names ("Where am I?", OWNER-DECISIONS 369, 465) -----------------------

/** On a trail, a named junction farther than this (a quarter mile) gives way to the trail marker (465). */
export const TRAIL_MARKER_M = METRES_PER_MILE / 4;

export interface RouteJunction {
  /** Metres along the line. */
  atM: number;
  /** The two streets, as the API names them: the one ridden, then the one met. */
  streets: [string, string];
}

/**
 * The junctions of the route with a named street, from its own data only: each change of street between
 * two stretches, and each flagged crossing (a junction entry names the street crossed). At least one of
 * the two streets has a real name (isUnnamed: "unnamed path" is the API's stand-in, not a name); the
 * other may be unnamed (a trail leaving an unnamed path). Never a lookup: the position does not leave
 * the page (plan section 7, owner question 7).
 */
export function routeJunctions(model: RideModel): RouteJunction[] {
  const out: RouteJunction[] = [];
  const seen = new Set<string>();
  const add = (atM: number, a: string | null, b: string | null) => {
    if (!a || !b || a === b || (isUnnamed(a) && isUnnamed(b))) return;
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

/** Whether a stretch is a named trail: a path with a name of its own (the MBT, the CCT), not "unnamed path". */
function isTrail(stretch: RideModel["stretches"][number] | null): stretch is RideModel["stretches"][number] & { street: string } {
  return !!stretch && stretch.facility === "path" && !isUnnamed(stretch.street);
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
 * northwest of Massachusetts Avenue"). The trail's mile markers are not in the route's data (whereAmI
 * takes them from lib/trailMiles.ts where the file knows the trail), so here the distance is from a
 * junction a reader can find on any map: one
 * on the trail itself whose other street has a real name. With none, just the trail. An unnamed way is never a trail and
 * never the street measured from (the owner, 2026-10-12: "about 1.2 miles south of unnamed path").
 */
export function placeOnRoute(model: RideModel, progressM: number): RoutePlace {
  const junctions = routeJunctions(model);
  const stretch = stretchAt(model, progressM);
  const nearest = nearestOf(junctions, progressM);
  if (isTrail(stretch) && (!nearest || Math.abs(nearest.atM - progressM) > TRAIL_MARKER_M)) {
    // Only the trail's own junctions with a named street (where the route met it, the roads it
    // crosses), the last behind before the next ahead. Never a junction off the trail: a distance from
    // there helps no one find the rider.
    const onTrail = junctions.filter((j) => j.streets.includes(stretch.street) && !isUnnamed(otherStreet(j, stretch.street)));
    const behind = onTrail.filter((j) => j.atM <= progressM).at(-1);
    const from = behind ?? onTrail.find((j) => j.atM > progressM);
    if (!from) return { kind: "street", street: stretch.street };
    const here = pointAt(model, progressM);
    const there = pointAt(model, from.atM);
    return { kind: "trail", trail: stretch.street, junction: from, metres: Math.abs(progressM - from.atM), direction: compassWord(there, here) };
  }
  if (nearest) return { kind: "junction", junction: nearest };
  return stretch?.street && !isUnnamed(stretch.street) ? { kind: "street", street: stretch.street } : null;
}

function nearestOf(junctions: RouteJunction[], progressM: number): RouteJunction | null {
  let nearest: RouteJunction | null = null;
  for (const j of junctions) if (!nearest || Math.abs(j.atM - progressM) < Math.abs(nearest.atM - progressM)) nearest = j;
  return nearest;
}

/**
 * The other street of a trail's junction: "Massachusetts Avenue Northwest". For a junction the trail is
 * not part of, the named one of its two streets (the first when both are).
 */
export function otherStreet(junction: RouteJunction, trail: string): string {
  const [a, b] = junction.streets;
  if (a === trail) return b;
  if (b === trail) return a;
  return isUnnamed(a) ? b : a;
}

/**
 * "Where am I?" (plan section 3): the street now, the next cue and its distance, the miles to the next
 * stop and to the end. `metric` adds the brackets for the screen; speech has US units only. On a named
 * trail far from any junction, the trail marker of OWNER-DECISIONS 465 ("Navigation cues on those
 * trails can use the same markers"): its mile marker where `miles` (lib/trailMiles.ts) knows the trail
 * ("On the Capital Crescent Trail, at mile marker 3." or "at about mile 3.2."), else the distance from a
 * junction of it. An unnamed way is said plainly ("On an unnamed path."), with no distance from anywhere.
 */
export function whereAmI(
  model: RideModel,
  state: RideState,
  metric = false,
  miles: TrailMiles | null = null,
  arriving: ((seconds: number) => string) | null = null,
): string {
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
  const stretch = stretchAt(model, state.progressM);
  // A named trail is "the" trail, with the marker or without: "On the Capital Crescent Trail."
  const way = isTrail(stretch) ? `the ${stretch.street}` : (wayRidden(stretch) ?? "the route");
  // Away from a junction on a trail the file knows, its mile marker, posted or computed, in place of the
  // distance from a junction (465: "Navigation cues on those trails can use the same markers").
  const mile =
    place?.kind !== "junction" && stretch && !isUnnamed(stretch.street) ? trailMileAt(miles, stretch.street, pointAt(model, state.progressM)) : null;
  const sentences = [
    mile
      ? `On ${way}, at ${mileWords(mile)}.`
      : place?.kind === "trail"
        ? `On ${way}, about ${dist(place.metres)} ${place.direction} of ${otherStreet(place.junction, place.trail)}.`
        : `On ${way}.`,
  ];
  const progress = state.progressM;
  const cue = model.cues.find((c) => ahead(model, c, progress) && (c.kind === "turn" || c.kind === "onto" || c.kind === "hazard" || c.kind === "walk"));
  if (cue?.movement === "uturn") sentences.push(`Next: ${lowerFirst(cue.text)}`);
  else if (cue) {
    const text = metric ? (cue.rideText ?? cue.text) : withoutMetric(cue.rideText ?? cue.text);
    sentences.push(`Next, in ${dist(cue.atM - state.progressM)}: ${lowerFirst(text)}`);
  }
  const togo = toGo(model, state.progressM);
  // ", arriving about 6:42 AM" where the caller gives the clock (lib/arrival.ts).
  const at = (seconds: number | null) => (arriving && seconds !== null ? `, arriving about ${arriving(seconds)}` : "");
  if (togo.stop) sentences.push(`${capital(dist(togo.stop.metres))} to stop ${togo.stop.number}${at(togo.stop.seconds)}.`);
  sentences.push(`${capital(dist(togo.end.metres))} to the end${at(togo.end.seconds)}.`);
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
export function replanPoints(model: RideModel, progressM: number, here: LonLat, points: readonly LonLat[], loop: boolean, guides = false): LonLat[] {
  return [here, ...replanKept(model, progressM, points, loop, guides).map((i) => points[i])];
}

/**
 * A re-route's via points are guides, its stops mandatory (Stephen 2026-10-24: "If a reroute needs to be done assume
 * via points are guides and stops are mandatory"): a via point less than this far ahead on the planned line (half a
 * mile) is dropped, so the rider is never sent back to touch it; one further on still shapes the rest of the ride.
 */
export const VIA_GUIDE_SKIP_M = 800;

/**
 * Which of the plan's points a re-plan keeps, by their index in `points`: the stops not yet passed, the via points
 * not yet passed (with `guides`, a re-route's, only those VIA_GUIDE_SKIP_M on or more), then the end (a loop's is
 * its start, index 0). `replanPoints` sends these after the rider's position.
 */
export function replanKept(model: RideModel, progressM: number, points: readonly LonLat[], loop: boolean, guides = false): number[] {
  const last = loop ? points.length : points.length - 1;
  const left: number[] = [];
  for (let i = 1; i < last; i += 1) {
    // A via point passed is dropped as a stop passed is (v0.7.0); the line's own place for it. A re-route (`guides`)
    // also drops one close ahead (VIA_GUIDE_SKIP_M): via points are guides; stops are never dropped.
    const pass = model.passes?.find((p) => p.point === i);
    if (pass) {
      if (pass.atM > progressM + (guides ? VIA_GUIDE_SKIP_M : ARRIVE_M)) left.push(i);
      continue;
    }
    const cue = model.cues.find((c) => c.kind === "stop" && (c.point ?? c.stop) === i);
    // A stop the description does not place (an older API) is kept: better one extra point than one lost.
    if (cue === undefined || cue.atM > progressM + ARRIVE_M) left.push(i);
  }
  left.push(loop ? 0 : points.length - 1);
  return left;
}

/**
 * The stops still ahead, for the ride's map (2026-10-24: "Stops should appear on the map when riding"): each stop
 * cue not yet reached, with its place in `points` and its number. Via points are no cues, so none is drawn.
 */
export function stopsAhead(model: RideModel, progressM: number, points: readonly LonLat[]): Array<{ point: LonLat; index: number; number: number }> {
  const out: Array<{ point: LonLat; index: number; number: number }> = [];
  for (const cue of model.cues) {
    if (cue.kind !== "stop" || cue.atM <= progressM + ARRIVE_M || cue.stop === null) continue;
    const index = cue.point ?? cue.stop;
    const point = points[index];
    if (point) out.push({ point, index, number: cue.stop });
  }
  return out;
}

/** End ride this far along the line or more is part way: the plan left behind starts where the rider is. */
export const END_PART_WAY_M = 100;
/** The last good fix is where the rider is at End ride for this long (a minute); older, the plan keeps its start. */
export const END_FIX_MAX_AGE_MS = 60_000;
/** Less left than this (about a quarter mile), or than END_LEFT_MIN_SHARE of the route: the plan as it was (a loop never shrinks to a stub). */
export const END_LEFT_MIN_M = 400;
export const END_LEFT_MIN_SHARE = 0.1;

/**
 * The plan End ride leaves (the owner, 2026-10-16: "If you went part way it changes your start location"):
 * part way along, from the last good fix through the stops not yet passed to the end (`replanPoints`; a
 * loop's finish stays its start); "no-fix" part way with no recent good fix, so the plan keeps its start
 * and the rider is told; null at or near the start, with little left (END_LEFT_MIN_M, END_LEFT_MIN_SHARE),
 * or after arrival: the plan as it was.
 */
export function planAfterEnd(
  model: RideModel,
  state: Pick<RideState, "progressM" | "goodFix" | "arrived">,
  points: readonly LonLat[],
  loop: boolean,
  now: number,
): { points: LonLat[] } | "no-fix" | null {
  const progress = state.progressM;
  if (state.arrived || progress === null || progress < END_PART_WAY_M) return null;
  const left = model.lengthM - progress;
  if (left < END_LEFT_MIN_M || left < END_LEFT_MIN_SHARE * model.lengthM) return null;
  const fix = state.goodFix;
  if (!fix || now - fix.at > END_FIX_MAX_AGE_MS) return "no-fix";
  return { points: replanPoints(model, progress, fix.point, points, loop) };
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
/** A re-route that sets off back the way the rider came (the owner, 2026-10-18: "clearly announce make a u turn"). */
export const REPLAN_UTURN = "New route found. Make a U-turn.";
export const UTURN_SAID = "Make a U-turn.";
/** A re-route that keeps the rider's way after they rode on past UTURNS_BEFORE_AHEAD U-turns. */
export const REPLAN_AHEAD = "New route found. Keep going ahead.";
/**
 * Re-routes in a row that may ask for a U-turn before the next one keeps the rider's way (the owner, 2026-10-20:
 * "give two reroutes and on the third time assume that the user wants to stay on that path").
 */
export const UTURNS_BEFORE_AHEAD = 2;
/**
 * That third re-route still turns round: there is no way ahead (or the map is wrong there). Said plainly, once; the
 * route is left up and not re-planned again until the rider turns round or asks (the owner, 2026-10-20: "There is no
 * route found ahead, make a U Turn. It could also be a mapping error, so just leave it up and don't keep annoying the user").
 */
export const REPLAN_NO_AHEAD = "No route found ahead. Make a U-turn.";
/** How often a held U-turn route is checked, silently, for a way ahead (the owner: "check periodically... silently"). */
export const UTURN_RECHECK_MS = 60_000;
/** How far along a U-turn route the rider is once they have turned round as asked: the count of U-turns starts again. */
export const UTURN_TAKEN_M = 50;

/** Whether the next re-route keeps the rider's way, after `uturns` U-turn re-routes in a row they rode on past. */
export function keepsAhead(uturns: number): boolean {
  return uturns >= UTURNS_BEFORE_AHEAD;
}

/**
 * A ride's U-turn re-routes, as RideMode keeps them (moved here out of RideMode.tsx so the sequence is tested, the
 * v0.10.1 end review): how many in a row asked for a U-turn the rider rode on past, whether a U-turn route is held
 * after "No route found ahead", and when the held route was last checked for a way ahead.
 */
export interface UTurnState {
  inARow: number;
  held: boolean;
  checkedAt: number;
}

export const UTURN_START: UTurnState = { inARow: 0, held: false, checkedAt: 0 };

/** What happened: a re-route's route taken, the rider along the line, off route, or moved to the other line. */
export type UTurnEvent =
  /**
   * A re-route's route taken (a held route's silent check only when it found a way ahead). `note` is what it would
   * say without the U-turns (REPLAN_FOUND or REPLAN_REJOIN); `stopped`, made without a heading because the rider
   * had none (not Road closed, which turns round on purpose).
   */
  | { kind: "rerouted"; turned: boolean; aheadOnly: boolean; stopped: boolean; note: string; now: number }
  /** A fix placed on the ride's route; `onUTurnRoute`, that route is one that asked for a U-turn. */
  | { kind: "along"; onUTurnRoute: boolean; off: boolean; progressM: number | null }
  /** Off route, with an automatic re-plan allowed (not kept, not fixed, the gate free, a good fix). */
  | { kind: "off-route"; now: number }
  /** The rider took the other line (lib/roadClosed.ts onOtherLine). */
  | { kind: "other-line" };

export interface UTurnStep {
  state: UTurnState;
  /** For "rerouted": the note to show and say. */
  note?: string;
  /** For "off-route": re-plan out loud, check the held route silently, or nothing. */
  replan?: "ask" | "check" | null;
}

/** Whether a re-route made with `headingDeg` sets off ahead whatever turning round saves (keepsAhead). */
export function uturnAheadOnly(state: UTurnState, headingDeg: number | null): boolean {
  return headingDeg !== null && keepsAhead(state.inARow);
}

/**
 * The U-turn re-routes' next state. Each U-turn re-route counts one; a re-route that keeps ahead starts the count
 * again, and one made while stopped (no heading) leaves it as it is, so a rider who pauses between U-turns they ride
 * past is not asked again and again (the v0.10.1 end review). The third, ahead only, that still turns round says
 * REPLAN_NO_AHEAD once and is held: off route, no re-plan out loud, only a silent check each UTURN_RECHECK_MS. A way
 * back (REPLAN_REJOIN) is never held. Any re-route taken (Re-plan from here's too), UTURN_TAKEN_M along a U-turn
 * route, or the other line lets go of a hold.
 */
export function uturnStep(state: UTurnState, event: UTurnEvent): UTurnStep {
  switch (event.kind) {
    case "rerouted": {
      const inARow = event.turned ? state.inARow + 1 : event.stopped ? state.inARow : 0;
      let note = event.note;
      if (event.turned && note === REPLAN_FOUND) note = REPLAN_UTURN;
      if (!event.turned && event.aheadOnly && note === REPLAN_FOUND) note = REPLAN_AHEAD;
      const held = event.turned && event.aheadOnly && note !== REPLAN_REJOIN;
      return { state: { inARow, held, checkedAt: event.now }, note: held ? REPLAN_NO_AHEAD : note };
    }
    case "along":
      // UTURN_TAKEN_M along the route: the rider follows it, so the count starts again (on any route, so a count a
      // re-route made while stopped left is not carried down the next one); along the U-turn route the hold goes too.
      if (event.off || (event.progressM ?? 0) < UTURN_TAKEN_M || (state.inARow === 0 && !state.held)) return { state };
      return { state: { ...state, inARow: 0, held: event.onUTurnRoute ? false : state.held } };
    case "off-route":
      if (!state.held) return { state, replan: "ask" };
      if (event.now - state.checkedAt >= UTURN_RECHECK_MS) return { state: { ...state, checkedAt: event.now }, replan: "check" };
      return { state, replan: null };
    case "other-line":
      return { state: { ...state, held: false } };
  }
}
/** A start this far off the rider's heading is a U-turn (the API's routing.UTURN_MIN_DEG). */
export const UTURN_MIN_DEG = 120;
/** How far along the line its setting-off direction is read: past the snap to the road (routing.UTURN_READ_M). */
export const UTURN_READ_M = 25;

/** Whether a route's line sets off back against the rider's heading (degrees), as the API judges a re-route's U-turn. */
export function setsOffBack(coordinates: readonly LonLat[], headingDeg: number | null): boolean {
  if (headingDeg === null || !Number.isFinite(headingDeg) || coordinates.length < 2) return false;
  let along = 0;
  let to = coordinates[0];
  for (let i = 1; i < coordinates.length && along < UTURN_READ_M; i += 1) {
    along += haversineM(coordinates[i - 1], coordinates[i]);
    to = coordinates[i];
  }
  if (along < 1) return false;
  const [lon1, lat1] = coordinates[0].map((v) => (v * Math.PI) / 180);
  const [lon2, lat2] = to.map((v) => (v * Math.PI) / 180);
  const y = Math.sin(lon2 - lon1) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lon2 - lon1);
  const bearing = (Math.atan2(y, x) * 180) / Math.PI;
  const delta = Math.abs(((((bearing - headingDeg) % 360) + 540) % 360) - 180);
  return delta >= UTURN_MIN_DEG;
}

/** The model with "Make a U-turn." as its first cue, at the start of the line: the card shows it and Ride says it at once. */
export function withUTurn(model: RideModel): RideModel {
  const uturn: Cue = { index: 0, kind: "turn", atM: 0, text: UTURN_SAID, movement: "uturn", street: null, severity: null, tier: null, stop: null };
  return { ...model, cues: [uturn, ...model.cues.map((cue) => ({ ...cue, index: cue.index + 1 }))] };
}
export const REPLAN_NO_SIGNAL = "No signal: the planned route is still shown.";
export const REPLAN_FAILED = "No new route was found; the planned route is still shown.";
/** No new route to the end, but one back to the planned route (lib/rejoin.ts), which goes on from there. */
export const REPLAN_REJOIN = "No new route was found; follow the way back to the planned route.";
export const REPLAN_FINDING = "Finding a new way from here.";
export const REPLAN_STILL_WAITING = "Still waiting for the last re-plan.";

/**
 * How a re-plan's outcome reaches the rider: one the rider asked for (Re-plan from here) is answered
 * whatever the level, as a detour's is (review RIDE-5); an automatic one is said at the full level, and
 * at the stoker's only when a new route (one that keeps going ahead, or a way back to the planned one) was found; the quiet level
 * hears it on screen only.
 */
export function replanTold(asked: boolean, level: Verbosity, note: string): "answer" | "say" | "quiet" {
  if (asked) return "answer";
  if (level === "full" || (level === "stoker" && (note === REPLAN_FOUND || note === REPLAN_AHEAD || note === REPLAN_NO_AHEAD || note === REPLAN_REJOIN))) return "say";
  return "quiet";
}
