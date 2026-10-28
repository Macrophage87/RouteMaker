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
 * stress or junction words; the road panel and Plan keep the detail. A stretch's change (busy, calmer,
 * unpaved) and a walk are Ride's own words too (routing audit D14, approved by the owner 2026-10-27):
 * "Busy road on R Street Northwest.", "Walk your bike for 120 feet.". What is added here is the timing
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
import { language, t } from "./i18n.ts";
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
  full: t("Full: every turn, early and again close to it"),
  stoker: t("Stoker: each turn once ahead and as it happens, busy crossings, stops"),
  quiet: t("Quiet: only arrival; ask Where am I? any time"),
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
export const GPS_WEAK_SAID = t("GPS is weak: turn cues paused.");

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
export const CUE_SHEET_SAID = t("GPS is still weak: the turns ahead are shown as a list, next turn first.");
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
      const distance = formatDistance(c.atM - from);
      const row = { index: c.index, distance: i === 0 ? t("In {distance}", { distance }) : t("Then in {distance}", { distance }), text: c.text };
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
/**
 * The most turns one jog joins (the owner, 2026-10-26: "a series of manuvers in short succession, make an arrow that
 * includes all of them"; voice "a prep command with all three, then go step by step at the intersection").
 */
export const JOG_TURNS = 3;

/** One of a jog's later turns, as the turn before it says it. */
export interface JogTurn {
  movement: TurnMovement;
  street: string | null;
  exit?: CircleExit;
  /** A fork that keeps to the same street or trail: said "bear right to stay on ..." (Cue.stay). */
  stay?: boolean;
  /** The named path an unnamed one leads to (Cue.toward). */
  toward?: string;
}

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
  /**
   * What Ride says and shows in place of `text`, where it differs: a flagged crossing's short line ("Busy crossing at C
   * Street, no signal."); a stretch's change or a walk in the app's own words ("Busy road on R Street Northwest.", D14).
   */
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
  /**
   * A jog's turns after this one (each within JOG_M of the one before, at most JOG_TURNS in all), in order: said
   * with it early, drawn with it as one arrow; at "now" each turn is said on its own.
   */
  then?: JogTurn[];
  /**
   * A jog's later turn: said early with the jog's first (its `then`); on its own at "now", once the rider is past
   * the turn before. Still on the card (with the turns after it) and in the courses; not a row of the cue sheets.
   */
  joined?: boolean;
  /** A turn at an unusual junction (v0.10.0): its ways, which the card draws in place of the plain arrow; never said. */
  junction?: JunctionShape;
  /** The way off a circle (v0.10.0): its exit, said ("take the 3rd exit") and drawn as a ring. */
  exit?: CircleExit;
  /** A fork that keeps to the same street or trail (the API's turn.stay): "Bear right to stay on ...", and at "now" "Bear right now." */
  stay?: boolean;
  /** A short path across a road between two turns: the road, said in place of the turn ("Cross Redland Road."), drawn straight on. */
  cross?: string;
  /** A turn onto a path just across a road (describe._far_side_turns): the road, said first ("Cross Saint Paul Street, then right onto ..."), drawn across it. */
  across?: string;
  /**
   * A turn onto an unnamed path that leads to a named one (describe._toward, round-2 D21): that one's name, said with
   * the path ("Right onto the path to Rock Creek Trail."). `street` stays "path", so the map, a report and "Where am
   * I?" never name the path by it.
   */
  toward?: string;
  /**
   * A walk cue's length (description metres): its words are built for the screen ("120 ft (37 m)") and for the voice
   * ("120 feet") from it (cueWords).
   */
  walkM?: number;
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
 * (`stay`, describe.fork_movement). "Right onto the path to Rock Creek Trail." for a path with no name that leads to a
 * named one (`toward`, describe._toward).
 */
export function turnWords(movement: TurnMovement, street: string | null, stay = false, exit: CircleExit | null = null, toward: string | null = null): string {
  if (movement === "uturn") return t(UTURN_SAID);
  if (exit) return `${exitWords(exit, street)}.`;
  const sentences = TURN_SENTENCES[movement];
  const way = street && UNNAMED_PATH_STREET.test(street.trim()) ? pathWords(toward) : street && !isUnnamed(street) ? wayWords(street) : null;
  return way ? t(stay ? sentences.stay : sentences.onto, { street: way }) : t(sentences.alone);
}

/** The API's street for a path with no name (describe.UNNAMED_PATH). */
const UNNAMED_PATH_STREET = /^(?:unnamed )?path$/i;

/** "the path", or "the path to Rock Creek Trail" where it leads to a named path (describe._toward). */
function pathWords(toward: string | null | undefined): string {
  const way = wayWords("path");
  return toward ? t("{way} to {trail}", { way, trail: wayWords(toward) }) : way;
}

/** A turn's whole sentences, one per movement, so a language can word each its own way (lib/i18n.ts). */
const TURN_SENTENCES = {
  left: { onto: "Left onto {street}.", stay: "Left to stay on {street}.", alone: "Left.", now: "Left now onto {street}.", nowAlone: "Left now." },
  right: { onto: "Right onto {street}.", stay: "Right to stay on {street}.", alone: "Right.", now: "Right now onto {street}.", nowAlone: "Right now." },
  bear_left: {
    onto: "Bear left onto {street}.",
    stay: "Bear left to stay on {street}.",
    alone: "Bear left.",
    now: "Bear left now onto {street}.",
    nowAlone: "Bear left now.",
  },
  bear_right: {
    onto: "Bear right onto {street}.",
    stay: "Bear right to stay on {street}.",
    alone: "Bear right.",
    now: "Bear right now onto {street}.",
    nowAlone: "Bear right now.",
  },
} as const satisfies Record<Exclude<TurnMovement, "uturn">, Record<string, string>>;

/** The way off a circle (describe.circle_exit): its exit, counting the streets off the ring the route passes. */
export interface CircleExit {
  number: number;
  circle: string | null;
}

/** "1st", "2nd", "3rd", "4th", "11th", "21st" (describe.ordinal). */
export function ordinal(n: number): string {
  // Spanish: "3.ª" (la salida, feminine).
  if (language() === "es") return `${n}.ª`;
  if ([11, 12, 13].includes(n % 100)) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

/**
 * "Take the 3rd exit onto P Street Northwest at Dupont Circle Northwest" (describe.exit_words; the owner, 2026-10-20,
 * "Ring picture + exit number"): the exit first, so the card shows it whole.
 */
export function exitWords(exit: CircleExit, street: string | null): string {
  const at = exit.circle ?? t("the roundabout");
  return street && !isUnnamed(street)
    ? t("Take the {nth} exit onto {street} at {circle}", { nth: ordinal(exit.number), street: wayWords(street), circle: at })
    : t("Take the {nth} exit at {circle}", { nth: ordinal(exit.number), circle: at });
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
  if (language() === "es") return wayWordsEs(street);
  return COMMON_WAY.test(street) ? `the ${street}` : street;
}

/** The API's names for a way by what it is, in Spanish: "the service road beside X" as "la vía de servicio junto a X". */
const WAY_ES: readonly [RegExp, string][] = [
  [/^path\b/, "el sendero"],
  [/^sidewalk\b/, "la acera"],
  [/^service road\b/, "la vía de servicio"],
  [/^alley\b/, "el callejón"],
  [/^parking aisle\b/, "el pasillo del estacionamiento"],
];

function wayWordsEs(street: string): string {
  // The road crossed where it has no name (describe.CROSS_UNNAMED, the API's own English).
  if (street === CROSS_UNNAMED) return "la calle";
  const found = WAY_ES.find(([head]) => head.test(street));
  return found ? street.replace(found[0], found[1]).replace(" beside ", " junto a ") : street;
}

const CROSSING_CONTROL_WORDS: Partial<Record<NonNullable<NonNullable<DescriptionEntry["turn"]>["control"]>, string>> = {
  signal: "Busy crossing at {street}, signal.",
  stop: "Busy crossing at {street}, stop sign.",
  all_stop: "Busy crossing at {street}, stop sign.",
  none: "Busy crossing at {street}, no signal.",
};
const CROSSING_CONTROL_ALONE: Partial<Record<NonNullable<NonNullable<DescriptionEntry["turn"]>["control"]>, string>> = {
  signal: "Busy crossing, signal.",
  stop: "Busy crossing, stop sign.",
  all_stop: "Busy crossing, stop sign.",
  none: "Busy crossing, no signal.",
};

/**
 * A flagged crossing's line in Ride (the owner, 2026-10-17: "a notice or warning when approaching a busy
 * intersection"): "Busy crossing at C Street, no signal.", no LTS and no stress words; the control left out
 * where unknown.
 */
export function crossingWords(street: string | null, control: NonNullable<DescriptionEntry["turn"]>["control"] | undefined): string {
  // In Spanish the API's way names ("service road beside ...") are said in Spanish too; English as it was.
  const named = street && !isUnnamed(street) ? (language() === "es" ? wayWords(street) : street) : null;
  const sentence = control ? (named ? CROSSING_CONTROL_WORDS : CROSSING_CONTROL_ALONE)[control] : undefined;
  if (sentence) return t(sentence, named ? { street: named } : undefined);
  return named ? t("Busy crossing at {street}.", { street: named }) : t("Busy crossing.");
}

/**
 * A stretch's change as Ride says and shows it, built here from the entry's own fields rather than read from the API's
 * English sentence (routing audit D14; the owner approved the wording, 2026-10-27): "Busy road on Massachusetts Avenue
 * Northwest.", "Heavy traffic on ...", "Calmer riding on ...", "Unpaved surface on ...", with the surface after where it
 * is unpaved ("Busy road on ..., unpaved."). No "(LTS 3)": the rider sees the colour (the owner, 2026-10-15, of turns:
 * "LTS is just extra noise"). Each is the app's own sentence, so it is whole in Spanish too; Plan keeps the API's.
 */
export function stretchWords(kind: "busy" | "calmer" | "unpaved", entry: Pick<DescriptionEntry, "street" | "tier" | "surface">): string {
  const street = entry.street && !isUnnamed(entry.street) ? wayWords(entry.street) : null;
  const partly = entry.surface === "partly unpaved";
  if (kind === "unpaved") {
    if (partly) return street ? t("Partly unpaved surface on {street}.", { street }) : t("Partly unpaved surface.");
    return street ? t("Unpaved surface on {street}.", { street }) : t("Unpaved surface.");
  }
  const tier = entry.tier ?? 0;
  const lead =
    kind === "calmer"
      ? street ? t("Calmer riding on {street}.", { street }) : t("Calmer riding.")
      : tier >= 5
        ? street ? t("Avoid-rated road on {street}.", { street }) : t("Avoid-rated road.")
        : tier === 4
          ? street ? t("Heavy traffic on {street}.", { street }) : t("Heavy traffic.")
          : street ? t("Busy road on {street}.", { street }) : t("Busy road.");
  if (!entry.surface) return lead;
  return t("{cue}, {surface}.", { cue: lead.replace(/\.$/, ""), surface: partly ? t("partly unpaved") : t("unpaved") });
}

/**
 * A walk cue's words (D14): "Walk your bike for 120 ft (37 m)." on the screen, "Walk your bike for 120 feet." said, in
 * place of the API's "walk your bike here", which was said "here" 500 ft early.
 */
export function walkWords(metres: number, spoken = false): string {
  if (!(metres > 0)) return t("Walk your bike.");
  return t("Walk your bike for {distance}.", { distance: spoken ? spokenDistance(metres) : formatDistance(metres) });
}

/** Which side the destination is on (item 5), from the router's destination maneuver; null when unknown. */
export type ArrivalSide = "left" | "right" | null | undefined;

/** "Destination on your right." for a known side, else nothing. */
export function arrivalSideWords(side: ArrivalSide): string {
  if (side === "left") return t("Destination on your left.");
  return side === "right" ? t("Destination on your right.") : "";
}

/** The end cue's words: "The end of the route.", with the destination's side where the router knows it. */
export function endWords(side: ArrivalSide): string {
  const where = arrivalSideWords(side);
  return where ? `${t("The end of the route.")} ${where}` : t("The end of the route.");
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
  return t("Continue onto {street}.", { street: wayWords(street) });
}

/** The last named way ridden, and where (description metres) it ended. */
type LastNamed = { street: string; toM: number } | null;

/** A DC quadrant at the end of a name, as the server's `streets.street_key` strips it. */
const QUADRANT_SUFFIX = / (?:northwest|northeast|southwest|southeast|nw|ne|sw|se)$/;
/** A direction prefix and its opposite: "West Pratt Street" and "East Pratt Street". */
const OPPOSITE_SIDE: Record<string, string> = { north: "south", south: "north", east: "west", west: "east" };
/**
 * What follows such a prefix where the two are different streets (North and South Capitol Street, North
 * and South Carolina Avenue, North and South Dakota Avenue): the server's describe `_NEVER_ONE_STEM`.
 */
const NEVER_ONE_STEM = new Set(["capitol street", "carolina avenue", "dakota avenue"]);

/**
 * Whether two lower-case names are one street's two sides (the server's describe `_side_change`): the
 * same but for the quadrant ("C Street Northwest", "C Street Northeast"), or for opposite direction
 * prefixes before at least two more words ("West Pratt Street", "East Pratt Street"). Never North and
 * South Avenue, nor North and South Capitol Street.
 */
function sameSides(x: string, y: string): boolean {
  const kx = x.replace(/\s+/g, " ").replace(QUADRANT_SUFFIX, "");
  const ky = y.replace(/\s+/g, " ").replace(QUADRANT_SUFFIX, "");
  if (!kx || !ky) return false;
  if (kx === ky) return true;
  const [sx, ...restX] = kx.split(" ");
  const [sy, ...restY] = ky.split(" ");
  const rx = restX.join(" ");
  return OPPOSITE_SIDE[sx] === sy && rx === restY.join(" ") && restX.length >= 2 && !NEVER_ONE_STEM.has(rx);
}

/**
 * Whether one name is the other with more after it ("X Street NW" and "X Street NW protected bike lane"),
 * or the two are one street's two sides (`sameSides`: "West Pratt Street" and "East Pratt Street").
 */
function sameStem(a: string | null, b: string): boolean {
  if (!a) return false;
  const x = a.trim().toLowerCase();
  const y = b.trim().toLowerCase();
  return x.startsWith(y) || y.startsWith(x) || sameSides(x, y);
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

/**
 * The named path a turn's unnamed path leads to (describe._toward), where the turn is said with it: not a crossing, a
 * far-side crossing, a circle's exit or a fork along one way, which the server never sends it with either.
 */
function toward(entry: DescriptionEntry): string | null {
  const turn = entry.turn;
  if (!turn?.toward || turn.cross || turn.across || turn.exit || turn.stay) return null;
  return UNNAMED_PATH_STREET.test((turn.onto ?? entry.street ?? "").trim()) ? turn.toward : null;
}

/** The ride's model: the line, its measure and its cues, from the route as the API answered it. */
/** A stop cue's words: "Stop 2." or, named, "Stop 2, Union Market." */
export function stopText(number: number, name: string | undefined): string {
  return name ? t("Stop {number}, {name}.", { number, name }) : t("Stop {number}.", { number });
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
              ? turnWords(entry.turn?.movement as TurnMovement, entry.turn?.onto ?? entry.street ?? null, entry.turn?.stay === true, entry.turn?.exit ?? null, toward(entry))
              : kind === "onto"
                ? ontoWords(entry.street as string)
                : sentenceOf(entry),
        ...(kind === "hazard" && entry.kind === "junction" && !entry.group ? { rideText: crossingWords(entry.street, entry.turn?.control) } : {}),
        ...(entry.kind === "hazard" ? { rideText: roadHazardWords(entry.text) } : {}),
        // A stretch's change and a walk in the app's own words (D14), not the API's sentence, which Plan keeps.
        ...(kind === "busy" || kind === "calmer" || kind === "unpaved" ? { rideText: stretchWords(kind, entry) } : {}),
        ...(kind === "walk" ? { rideText: walkWords(entry.to_m - entry.from_m), walkM: Math.max(0, entry.to_m - entry.from_m) } : {}),
        ...(entry.citation ? { citation: entry.citation } : {}),
        ...(kind === "turn" && entry.turn?.shape && !entry.turn.cross ? { junction: entry.turn.shape } : {}),
        ...(kind === "turn" && entry.turn?.cross ? { cross: entry.turn.cross } : {}),
        ...(kind === "turn" && entry.turn?.across && !entry.turn.cross ? { across: entry.turn.across } : {}),
        ...(kind === "turn" && entry.turn?.exit ? { exit: entry.turn.exit } : {}),
        ...(kind === "turn" && toward(entry) ? { toward: toward(entry) as string } : {}),
        ...(kind === "turn" && entry.turn?.stay === true && !entry.turn.cross && !entry.turn.across ? { stay: true } : {}),
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
  return t("Cross {road}.", { road: wayWords(road) });
}

/**
 * The ride card's arrow across a road, then the turn on its far side (the owner, 2026-10-24: "make it clear both from
 * the arrow and directions to cross the road then turn right"): for a crossing between two turns (crossWords) with the
 * turn after it, or a turn onto a path just across a road (acrossWords). A crossing on its own is "cross", straight
 * over the road; null for any other cue.
 */
export function crossArrow(cue: Pick<Cue, "cross" | "across" | "then" | "movement">): "cross" | "cross_left" | "cross_right" | null {
  const after = cue.cross ? cue.then?.[0]?.movement : cue.across ? cue.movement : undefined;
  if (after === "left" || after === "bear_left") return "cross_left";
  if (after === "right" || after === "bear_right") return "cross_right";
  return cue.cross ? "cross" : null;
}

/** "Cross Saint Paul Street, then right onto Saint Paul Street bike lane.": a turn onto a path just across a road (describe._far_side_turns). */
export function acrossWords(road: string, movement: TurnMovement, street: string | null): string {
  return t("Cross {road}, then {turn}", { road: wayWords(road), turn: lowerFirst(turnWords(movement, street)) });
}

/**
 * ", then immediately bear left onto Rhode Island Avenue.": a jog's second turn, after the first; after a crossing
 * only ", then left onto ..." (the owner, 2026-10-20: "cross the street and turn left").
 */
function thenWords(then: JogTurn, crossing = false): string {
  const turn = lowerFirst(turnWords(then.movement, then.street, then.stay === true, then.exit ?? null, then.toward ?? null));
  return crossing ? t(", then {turn}", { turn }) : t(", then immediately {turn}", { turn });
}

/** A jog's turns without their streets: "Right, then immediately bear left, then immediately left."; "Cross Redland Road, then left." after a crossing. */
function jogShortWords(cue: Cue): string {
  const lead = cue.cross ? crossWords(cue.cross) : turnWords(cue.movement!, null, false, cue.exit ?? null);
  const then = (cue.then ?? []).map((turn, n) => thenWords({ ...turn, street: null, stay: false }, n === 0 && cue.cross !== undefined).replace(/\.$/, ""));
  return lead.replace(/\.$/, "") + then.join("") + ".";
}

/**
 * A jog: each turn within JOG_M after the one before (up to JOG_TURNS in all) is said with the first, its text
 * "Right onto 6th Street, then immediately bear left onto ...". The later turns are kept (`joined`) for the card and
 * the courses, each with the turns still after it (`phasesFor`, `step`).
 */
function joinJogs(cues: Cue[]): void {
  for (let i = 0; i + 1 < cues.length; i++) {
    const first = cues[i];
    if (first.kind !== "turn" || first.joined || !first.movement || first.across) continue;
    const jog = [first];
    for (let k = i + 1; k < cues.length && jog.length < JOG_TURNS; k++) {
      const next = cues[k];
      // A crossing is never said as a turn after another: it leads its own cue, with the turn after it. A turn across a
      // road already says two things: the turn after it keeps its own cue.
      if (next.kind !== "turn" || !next.movement || next.cross || next.across) break;
      if (next.atM - cues[k - 1].atM > JOG_M) break;
      jog.push(next);
    }
    if (jog.length < 2) continue;
    const plain = jog.map((cue) => cue.text.replace(/\.$/, ""));
    jog.forEach((cue, j) => {
      if (j > 0) cue.joined = true;
      const after = jog.slice(j + 1);
      if (!after.length) return;
      cue.then = after.map((t) => ({ movement: t.movement!, street: t.street, ...(t.exit ? { exit: t.exit } : {}), ...(t.stay ? { stay: true } : {}), ...(t.toward ? { toward: t.toward } : {}) }));
      cue.text = plain[j] + cue.then.map((t, n) => thenWords(t, n === 0 && cue.cross !== undefined).replace(/\.$/, "")).join("") + ".";
    });
    i += jog.length - 1;
  }
}

/** Which cues a verbosity level says unprompted (plan section 3's table; Quiet: arrival only). */
/**
 * Ride's short line for a known road hazard (v0.10.0), from the directions' sentence ("Rails in the road on H
 * Street Northeast, 0.4 to 1.2 mi (...): cross them square on, ..."): "Rails in the road on H Street Northeast.
 * Cross them square on, a wheel can drop into the groove.", said "In 500 feet, rails in the road on ...".
 */
export function roadHazardWords(text: string): string {
  // The server words it in the rider's language (routemaker.lang): "Rieles en la calle en ..., 0.4 a 1.2 mi".
  const m = /^(.*?) (on|en) (.*?), (?:(?:at|en) [\d.]+|[\d.]+ (?:to|a) [\d.]+) mi \([^)]*\): (.*)$/.exec(text);
  if (!m) return text;
  return `${m[1]} ${m[2]} ${m[3]}. ${m[4].charAt(0).toUpperCase()}${m[4].slice(1)}`;
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
  /** A jog's later turn at "now": urgent, but after the turn before is said, not over it (lib/rideOutput.ts). */
  after?: boolean;
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

/**
 * Whether a cue's words lead with the app's own template ("Left onto ...", "Busy road on ...", "Walk your bike ...",
 * "Busy crossing at ..."), so "In 500 feet, {cue}" may lower its first letter: decided by the cue's kind, never by
 * matching its text (D14: a street-led sentence came out "massachusetts Avenue", "uS 29"). A work zone's sentence can
 * lead with the road's own name ("Connecticut Avenue marked closed ahead."), so it keeps its capital.
 */
function leadsWithTemplate(cue: Pick<Cue, "kind"> & Pick<Partial<Cue>, "source">): boolean {
  if (cue.kind === "hazard") return cue.source !== "workzone";
  return cue.kind === "turn" || cue.kind === "onto" || cue.kind === "busy" || cue.kind === "calmer" || cue.kind === "unpaved" || cue.kind === "walk";
}

/** A cue's words placed after "In 500 feet, ": the first letter lowered only where it is the app's template. */
function inSentence(cue: Pick<Cue, "kind"> & Pick<Partial<Cue>, "source">, text: string): string {
  return leadsWithTemplate(cue) ? lowerFirst(text) : text;
}

/** Speech drops the metric the screen keeps: " (90 m)", " (0.6 to 1.9 km)" and "(LTS 1)" kept. */
export function withoutMetric(text: string): string {
  return text.replace(/\s\((?:about |unos )?[\d.,]+(?: (?:to|a) [\d.,]+)? (?:km|m|km\/h)\)/g, "");
}

/**
 * A cue's words as said: no metric, and no "(LTS 3)" (D14; the owner, 2026-10-15: "LTS is just extra noise, we can
 * see it"), which an API sentence a hazard is still read from can carry. The screen keeps both.
 */
export function spokenText(text: string): string {
  return withoutMetric(text).replace(/\s\(LTS \d(?: or Avoid)?\)/g, "");
}

/** A cue's words, as shown (`spoken` false: the card's, with the metric) or as said; a walk's distance in the voice's own words. */
export function cueWords(cue: Pick<Cue, "kind" | "text"> & Pick<Partial<Cue>, "rideText" | "walkM">, spoken: boolean): string {
  if (cue.kind === "walk" && cue.walkM !== undefined) return walkWords(cue.walkM, spoken);
  const text = cue.rideText ?? cue.text;
  return spoken ? spokenText(text) : text;
}

/**
 * What is said for a cue at a phase, `distanceM` before it (US units only). `first`: nothing was said for this cue
 * yet (a ride that starts, or a GPS gap that ends, inside the prepare distance has no advance warning).
 */
export function cueSpoken(cue: Cue, phase: Phase, distanceM: number, first = phase === "advance" || phase === "ahead"): string {
  if (cue.kind === "end") {
    // The side, where known, is the end cue's own last sentence ("Destination on your right.").
    const side = (["left", "right"] as const).map(arrivalSideWords).find((words) => cue.text.endsWith(words));
    return side ? `${t(ARRIVED_SAID)} ${side}` : t(ARRIVED_SAID);
  }
  if (cue.kind === "stop")
    return cue.stopName ? t("You have reached stop {stop}, {name}.", { stop: cue.stop ?? "", name: cue.stopName }) : t("You have reached stop {stop}.", { stop: cue.stop ?? "" });
  if (phase === "now" && cue.movement) {
    // A jog's turns are said one at a time at "now" (the owner, 2026-10-26: "go step by step at the intersection").
    if (cue.cross) return t("Cross {road} now.", { road: wayWords(cue.cross) });
    if (cue.across && cue.movement !== "uturn")
      return t("Cross {road} now, then {turn}", { road: wayWords(cue.across), turn: lowerFirst(turnWords(cue.movement, cue.street)) });
    if (cue.movement === "uturn") return t("Make a U-turn now.");
    if (cue.exit) return cue.street && !isUnnamed(cue.street) ? t("Exit now onto {street}.", { street: wayWords(cue.street) }) : t("Exit now.");
    const sentences = TURN_SENTENCES[cue.movement];
    // A fork on the same trail: "Bear right now.", not "now onto" the trail the rider is already on (its name was said before).
    if (cue.toward) return t(sentences.now, { street: pathWords(cue.toward) });
    return cue.street && !cue.stay ? t(sentences.now, { street: wayWords(cue.street) }) : t(sentences.nowAlone);
  }
  // A turn at a flagged junction says so in its first warning only; "now" is the turn alone.
  const busy = cue.kind === "turn" && (cue.severity === "orange" || cue.severity === "red") && first;
  // A jog's reminder about 10 s out is its turns without the streets, said at the advance cue and on the card, so the
  // urgent "now" does not cut off its last turns; in full when it is the first thing said for the cue.
  const text = phase === "prepare" && !first && cue.then?.length && cue.movement ? jogShortWords(cue) : cueWords(cue, true);
  const said = t("In {distance}, {cue}", { distance: spokenDistance(distanceM), cue: inSentence(cue, text) });
  return busy ? `${said} ${t("Busy junction.")}` : said;
}

/**
 * The phases a cue is said at, at a level, farthest first, with their thresholds at a speed. A jog's later turn
 * has "now" only, which `step` says once the rider is past the turn before.
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
export const OFF_ROUTE_SAID = t("Off the planned route; finding a new way.");
export const OFF_ROUTE_KEPT_SAID = t("Off the planned route.");
export const BACK_ON_ROUTE_SAID = t("Back on the planned route.");

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
    // A jog's later turn waits until the rider is past the turn before: step by step at the junction.
    if (cue.joined && progress < model.cues[cue.index - 1].atM) break;
    // The nearest phase whose threshold is reached; any farther one is then skipped, not said late.
    const reached = phases.filter((p) => distance <= p.withinM);
    if (!reached.length) break;
    const phase = reached[reached.length - 1];
    if (!done.includes(phase.phase)) {
      events.push({
        kind: "cue",
        spoken: cueSpoken(cue, phase.phase, distance, done.length === 0),
        urgent: phase.phase === "now" || phase.phase === "arrive",
        ...(cue.joined ? { after: true } : {}),
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
const COMPASS_ES = ["norte", "noreste", "este", "sureste", "sur", "suroeste", "oeste", "noroeste"];

/** The compass word for the bearing from a to b: "northeast". */
export function compassWord(a: LonLat, b: LonLat): string {
  const y = Math.sin(((b[0] - a[0]) * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180);
  const x =
    Math.cos((a[1] * Math.PI) / 180) * Math.sin((b[1] * Math.PI) / 180) -
    Math.sin((a[1] * Math.PI) / 180) * Math.cos((b[1] * Math.PI) / 180) * Math.cos(((b[0] - a[0]) * Math.PI) / 180);
  const bearing = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
  return (language() === "es" ? COMPASS_ES : COMPASS)[Math.round(bearing / 45) % 8];
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
  if (/\bpath\b/i.test(stretch.street ?? "")) return t("a path");
  if (/\broad\b/i.test(stretch.street ?? "")) return t("an unnamed road");
  return stretch.facility === "path" || stretch.facility === "protected" ? t("a path") : t("an unnamed road");
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
  if (state.arrived) return t(ARRIVED_SAID);
  if (state.progressM === null) return t("Finding your place on the route.");
  if (state.off) {
    const back = wayBack(model, state);
    return back
      ? t("Off the planned route. The route is {distance} to the {direction}.", { distance: dist(back.metres), direction: back.direction })
      : t("Off the planned route.");
  }
  const place = placeOnRoute(model, state.progressM);
  const stretch = stretchAt(model, state.progressM);
  // A named trail is "the" trail, with the marker or without: "On the Capital Crescent Trail."
  const way = isTrail(stretch) ? t("the {trail}", { trail: stretch.street }) : (wayRidden(stretch) ?? t("the route"));
  // Away from a junction on a trail the file knows, its mile marker, posted or computed, in place of the
  // distance from a junction (465: "Navigation cues on those trails can use the same markers").
  const mile =
    place?.kind !== "junction" && stretch && !isUnnamed(stretch.street) ? trailMileAt(miles, stretch.street, pointAt(model, state.progressM)) : null;
  const sentences = [
    mile
      ? t("On {way}, at {mile}.", { way, mile: mileWords(mile) })
      : place?.kind === "trail"
        ? t("On {way}, about {distance} {direction} of {street}.", { way, distance: dist(place.metres), direction: place.direction, street: otherStreet(place.junction, place.trail) })
        : t("On {way}.", { way }),
  ];
  const progress = state.progressM;
  const cue = model.cues.find((c) => ahead(model, c, progress) && (c.kind === "turn" || c.kind === "onto" || c.kind === "hazard" || c.kind === "walk"));
  if (cue?.movement === "uturn") sentences.push(t("Next: {cue}", { cue: lowerFirst(cue.text) }));
  else if (cue) {
    sentences.push(t("Next, in {distance}: {cue}", { distance: dist(cue.atM - state.progressM), cue: inSentence(cue, cueWords(cue, !metric)) }));
  }
  const togo = toGo(model, state.progressM);
  // ", arriving about 6:42 AM" where the caller gives the clock (lib/arrival.ts).
  const at = (seconds: number | null) => (arriving && seconds !== null ? t(", arriving about {time}", { time: arriving(seconds) }) : "");
  if (togo.stop) sentences.push(t("{distance} to stop {number}{arriving}.", { distance: capital(dist(togo.stop.metres)), number: togo.stop.number, arriving: at(togo.stop.seconds) }));
  sentences.push(t("{distance} to the end{arriving}.", { distance: capital(dist(togo.end.metres)), arriving: at(togo.end.seconds) }));
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
 * A re-route leaves out the next via point when its new route takes more than this (5 min) longer to reach it than the
 * planned route would have from the rider's place (Stephen, 2026-10-27: "Vias can be skipped a little more, for instance
 * if a road is closed, you shouldn't expect a 20 minute detour just to get to the other side. Those are guides. Stops
 * are where you want to end up."). Only the next one ("Sometimes people plan very indirect routes for fun, so it
 * shouldn't skip all of the vias"), never a stop.
 */
export const VIA_SKIP_EXTRA_S = 300;

/**
 * The via point a re-route may leave out (VIA_SKIP_EXTRA_S): the first of `kept` (replanKept's answer) where it is a
 * via point, the next point the rider heads for, with its place on the planned line; null where that is a stop or the
 * end. A via point behind a stop is not this one: the stop comes first.
 */
export function skippableVia(model: Pick<RideModel, "passes">, kept: readonly number[]): { point: number; atM: number } | null {
  if (kept.length < 2) return null;
  return model.passes?.find((p) => p.point === kept[0]) ?? null;
}

/**
 * Whether the new route's way to the via point is long enough to leave it out: from its start to the via point
 * (`freshPoint`, its place in the new plan's points) it takes more than VIA_SKIP_EXTRA_S longer than the planned route
 * from `progressM` to the same point at `viaAtM`, each by its own time along its line (secondsAt: the API's time marks,
 * hills and junction waits in place, else the route's own pace). False where either time is unknown.
 */
export function viaSkipWorth(planned: RideModel, progressM: number, viaAtM: number, fresh: RideModel, freshPoint: number): boolean {
  const before = secondsBetween(planned, progressM, viaAtM);
  const pass = fresh.passes?.find((p) => p.point === freshPoint);
  const after = pass ? secondsAt(fresh, pass.atM) : null;
  return before !== null && after !== null && after - before > VIA_SKIP_EXTRA_S;
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

export const REPLAN_FOUND = t("New route found.");
/** A re-route that sets off back the way the rider came (the owner, 2026-10-18: "clearly announce make a u turn"). */
export const REPLAN_UTURN = t("New route found. Make a U-turn.");
/** The English key: turnWords and the U-turn cue translate it where they say it. */
export const UTURN_SAID = "Make a U-turn.";
/** A re-route that keeps the rider's way after they rode on past UTURNS_BEFORE_AHEAD U-turns. */
export const REPLAN_AHEAD = t("New route found. Keep going ahead.");
/** The end said on arrival (cueSpoken, whereAmI). */
const ARRIVED_SAID = "You have arrived at the end of the route.";
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
export const REPLAN_NO_AHEAD = t("No route found ahead. Make a U-turn.");
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
   * say without the U-turns (REPLAN_FOUND, REPLAN_REJOIN or REPLAN_REJOIN_AHEAD); `stopped`, made without a heading because the rider
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
 * back (REPLAN_REJOIN, REPLAN_REJOIN_AHEAD) is never held. Any re-route taken (Re-plan from here's too), UTURN_TAKEN_M along a U-turn
 * route, or the other line lets go of a hold.
 */
export function uturnStep(state: UTurnState, event: UTurnEvent): UTurnStep {
  switch (event.kind) {
    case "rerouted": {
      const inARow = event.turned ? state.inARow + 1 : event.stopped ? state.inARow : 0;
      let note = event.note;
      if (event.turned && note === REPLAN_FOUND) note = REPLAN_UTURN;
      if (!event.turned && event.aheadOnly && note === REPLAN_FOUND) note = REPLAN_AHEAD;
      const held = event.turned && event.aheadOnly && note !== REPLAN_REJOIN && note !== REPLAN_REJOIN_AHEAD;
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
  const uturn: Cue = { index: 0, kind: "turn", atM: 0, text: t(UTURN_SAID), movement: "uturn", street: null, severity: null, tier: null, stop: null };
  return { ...model, cues: [uturn, ...model.cues.map((cue) => ({ ...cue, index: cue.index + 1 }))] };
}
export const REPLAN_NO_SIGNAL = t("No signal: the planned route is still shown.");
export const REPLAN_FAILED = t("No new route was found; the planned route is still shown.");
/** No new route to the end, but one back to the planned route (lib/rejoin.ts), which goes on from there. */
export const REPLAN_REJOIN = t("No new route was found; follow the way back to the planned route.");
/**
 * A re-route on a route the rider chose over the first that rejoins it ahead, tried before a new plan (routing audit D15,
 * lib/rejoin.ts rejoinsFirst). Not REPLAN_REJOIN: here no new route was looked for, and none failed.
 */
export const REPLAN_REJOIN_AHEAD = t("New route found. It rejoins your route ahead.");
/** Said before a re-route's own note where it left out the next via point (VIA_SKIP_EXTRA_S): "Skipping via point. New route found." */
export const VIA_SKIPPED_SAID = t("Skipping via point.");

/** A re-route's note with VIA_SKIPPED_SAID before it, where it found a route; any other note as it is. */
export function viaSkippedNote(note: string): string {
  return note === REPLAN_FOUND || note === REPLAN_UTURN || note === REPLAN_AHEAD ? `${VIA_SKIPPED_SAID} ${note}` : note;
}

/** A note without VIA_SKIPPED_SAID before it: what it says of the new route, for replanTold. */
function replanBase(note: string): string {
  return note.startsWith(`${VIA_SKIPPED_SAID} `) ? note.slice(VIA_SKIPPED_SAID.length + 1) : note;
}
export const REPLAN_FINDING = t("Finding a new way from here.");
export const REPLAN_STILL_WAITING = t("Still waiting for the last re-plan.");

/**
 * How a re-plan's outcome reaches the rider: one the rider asked for (Re-plan from here) is answered
 * whatever the level, as a detour's is (review RIDE-5); an automatic one is said at the full level, and
 * at the stoker's only when a new route (one that keeps going ahead, or a way back to the planned one) was found; the quiet level
 * hears it on screen only.
 */
export function replanTold(asked: boolean, level: Verbosity, note: string): "answer" | "say" | "quiet" {
  if (asked) return "answer";
  const base = replanBase(note);
  const found = base === REPLAN_FOUND || base === REPLAN_AHEAD || base === REPLAN_NO_AHEAD || base === REPLAN_REJOIN || base === REPLAN_REJOIN_AHEAD;
  if (level === "full" || (level === "stoker" && found)) return "say";
  return "quiet";
}
