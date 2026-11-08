/**
 * Turn-by-turn on foot (Stephen, 2026-11-02: "turn by turn directions for walking"). A walk the API routed on foot
 * carries its turns (core/walk_turns.py: the movement, the street, the point), and Ride follows the walk as it follows
 * a ride: the same cue words in the rider's language (navigate.ts turnWords, cueSpoken), the same distances, the same
 * voice. The walk is a line of its own (a RideModel with only its turns), stepped with navigate.ts `step` but never
 * re-planned and never "off route": a walker cuts corners and crosses where they like, and the cues pick up again
 * where they rejoin the line. Its end is the trip's own (the dock, the station, the destination), said by the trip.
 *
 * The walks: the walk to the first dock or station before the line (rideTrip.ts approach), and the walks after it
 * (rideTrip.ts onward: from a dock to the destination or a station, and from the stop where the transit ends).
 */
import type { WalkTurn } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { formatDistance } from "./format.ts";
import { t } from "./i18n.ts";
import {
  CROSS_UNNAMED,
  crossingWords,
  crossWords,
  inSentence,
  isUnnamed,
  lineAlong,
  snap,
  startState,
  step,
  turnWords,
  wayWords,
  type Cue,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./navigate.ts";

/** A walk as the plan gives it: its line, its turns (none from an older API) and where it goes, by name. */
export interface WalkPath {
  coordinates: LonLat[];
  turns: readonly WalkTurn[];
  to: string | null;
}

/** A turn further than this from the walk's line is not on it (an older API's straight line): not said. */
const ON_LINE_M = 25;
/**
 * A turn this near the walk's start is not said (Stephen, 2026-11-08: leaving the station, "In 0 ft (0 m), left."): the
 * router's first bend off the point it starts from, often a station's entrance, which a walker is already through.
 * Our default.
 */
export const START_TURN_M = 15;

/**
 * The walk as a line to follow: its turns as cues, in order along it, and its end (`endText`: its words where the
 * walk is the ride screen's own line, Walk's). Null for a walk with no line.
 */
export function walkModel(path: WalkPath, endText = ""): RideModel | null {
  const coordinates = path.coordinates;
  if (coordinates.length < 2) return null;
  const along = lineAlong(coordinates);
  const lengthM = along[along.length - 1];
  const cues: Cue[] = [];
  for (const turn of path.turns) {
    const found = snap({ coordinates, along }, turn.point);
    if (!found || found.offM > ON_LINE_M || found.alongM < START_TURN_M || found.alongM >= lengthM) continue;
    const crossing = turn.movement === "cross";
    cues.push({
      index: cues.length,
      kind: "turn",
      atM: found.alongM,
      text: walkTurnWords(turn),
      // A crossing is drawn as straight on (no turn's arrow) and said in its own words.
      movement: crossing ? null : (turn.movement as Exclude<WalkTurn["movement"], "cross">),
      street: turn.street,
      severity: null,
      tier: null,
      stop: null,
    });
  }
  cues.sort((a, b) => a.atM - b.atM);
  cues.forEach((cue, index) => (cue.index = index));
  cues.push({ index: cues.length, kind: "end", atM: lengthM, text: endText, movement: null, street: null, severity: null, tier: null, stop: null });
  return { coordinates, along, lengthM, cues, stretches: [], paceMs: null, onFoot: true };
}

/** The turns a walk's step lists (the trip's steps, "3 turns"): each in the rider's language. */
export function walkTurnTexts(turns: readonly WalkTurn[] | null | undefined): string[] {
  return (turns ?? []).map(walkTurnWords);
}

/** A walk's turn, or crossing (`walkCrossingWords`), in the rider's language. */
export function walkTurnWords(turn: WalkTurn): string {
  return turn.movement === "cross" ? walkCrossingWords(turn) : turnWords(turn.movement, turn.street);
}

/**
 * A crossing on foot (Stephen, 2026-11-02: "Make sure to note crosswalks and perfer signalled crossings";
 * core/walk_pricing.py): "Cross Pratt Street at the signal.", "Cross at the crosswalk.", a busy road crossed with no
 * signal as a ride's busy crossing is said ("Busy crossing at Pratt Street, no signal."), and a slip lane's warning
 * after it.
 */
export function walkCrossingWords(turn: Pick<WalkTurn, "street" | "control" | "busy" | "slip">): string {
  const named = turn.street && !isUnnamed(turn.street) ? turn.street : null;
  const road = named ? wayWords(named) : null;
  let words: string;
  if (turn.control === "signal") words = road ? t("Cross {road} at the signal.", { road }) : t("Cross at the signal.");
  else if (turn.control === "crosswalk") {
    words = road ? t("Cross {road} at the crosswalk.", { road }) : t("Cross at the crosswalk.");
    if (turn.busy) words = `${words} ${t("Busy road, no signal.")}`;
  } else if (turn.busy) words = crossingWords(named, "none");
  else words = crossWords(named ?? CROSS_UNNAMED);
  return turn.slip ? `${words} ${t("Slip lane: watch for turning cars.")}` : words;
}

export function walkStart(): RideState {
  return startState();
}

/**
 * One fix into the walk: its turns' cues as a ride's are said (navigate.ts step, at the rider's own pace), never off
 * route or a re-plan, and never its end, which the trip says in its own words.
 */
export function walkStep(model: RideModel, state: RideState, fix: RideFix, level: Verbosity): { state: RideState; events: RideEvent[] } {
  const out = step(model, state, fix, level, false);
  // Off the line, a walker is never told so: the state stays on the line's last place, so the cues take up again.
  const next = out.state.off ? { ...out.state, off: false, offSince: null, offCount: 0 } : out.state;
  return { state: next, events: out.events.filter((e) => e.kind === "cue" && e.cue?.kind === "turn") };
}

/** The walk's next turn, and how far: for the ride screen's line under the walk. Null before a fix, or past the last. */
export function nextWalkTurn(model: RideModel, state: RideState): { cue: Cue; metres: number } | null {
  if (state.progressM === null) return null;
  const at = state.progressM;
  const cue = model.cues.find((c) => c.kind === "turn" && c.atM > at - 5);
  return cue ? { cue, metres: Math.max(0, cue.atM - at) } : null;
}

/** The ride screen's line for the walk's next turn: "In 250 ft (76 m), Left onto F St NE." */
export function walkTurnLine(model: RideModel | null, state: RideState | null): string | null {
  if (!model || !state) return null;
  const next = nextWalkTurn(model, state);
  if (!next) return null;
  return t("In {distance}, {cue}", { distance: formatDistance(next.metres), cue: inSentence(next.cue, next.cue.text) });
}
