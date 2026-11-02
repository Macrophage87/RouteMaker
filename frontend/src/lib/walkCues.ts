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
import { inSentence, lineAlong, snap, startState, step, turnWords, type Cue, type RideEvent, type RideFix, type RideModel, type RideState, type Verbosity } from "./navigate.ts";

/** A walk as the plan gives it: its line, its turns (none from an older API) and where it goes, by name. */
export interface WalkPath {
  coordinates: LonLat[];
  turns: readonly WalkTurn[];
  to: string | null;
}

/** A turn further than this from the walk's line is not on it (an older API's straight line): not said. */
const ON_LINE_M = 25;

/** The walk as a line to follow: its turns as cues, in order along it, and its end. Null for a walk with no line. */
export function walkModel(path: WalkPath): RideModel | null {
  const coordinates = path.coordinates;
  if (coordinates.length < 2) return null;
  const along = lineAlong(coordinates);
  const lengthM = along[along.length - 1];
  const cues: Cue[] = [];
  for (const turn of path.turns) {
    const found = snap({ coordinates, along }, turn.point);
    if (!found || found.offM > ON_LINE_M || found.alongM <= 0 || found.alongM >= lengthM) continue;
    cues.push({
      index: cues.length,
      kind: "turn",
      atM: found.alongM,
      text: turnWords(turn.movement, turn.street),
      movement: turn.movement,
      street: turn.street,
      severity: null,
      tier: null,
      stop: null,
    });
  }
  cues.sort((a, b) => a.atM - b.atM);
  cues.forEach((cue, index) => (cue.index = index));
  cues.push({ index: cues.length, kind: "end", atM: lengthM, text: "", movement: null, street: null, severity: null, tier: null, stop: null });
  return { coordinates, along, lengthM, cues, stretches: [], paceMs: null };
}

/** The turns a walk's step lists (the trip's steps, "3 turns"): each in the rider's language. */
export function walkTurnTexts(turns: readonly WalkTurn[] | null | undefined): string[] {
  return (turns ?? []).map((turn) => turnWords(turn.movement, turn.street));
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
