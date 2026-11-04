/**
 * After the line (Stephen, 2026-11-02: turn by turn on foot and stop by stop on transit): what a Bikeshare or transit
 * trip goes on with once its riding leg ends, followed on the ride screen in order. A walk (from the dock to the
 * destination or a station, from the stop where the transit ends) has its turns said as a ride's are
 * (lib/walkCues.ts); a train or bus has its stops followed and the stop to get off said (lib/onBoard.ts). A riding
 * leg after the transit is Ride the rest's, as before, so the list stops there.
 */
import type { TransitStep } from "./api.ts";
import { haversineM } from "./geo.ts";
import { t } from "./i18n.ts";
import { ARRIVED_SAID, type RideEvent, type RideFix, type RideModel, type RideState, type Verbosity } from "./navigate.ts";
import { onBoardLeg, onBoardStart, onBoardStep, AT_STOP_M, ROUGH_FIX_M, type OnBoardLeg, type OnBoardState } from "./onBoard.ts";
import { drawOf } from "./transit.ts";
import { walkModel, walkStart, walkStep, type WalkPath } from "./walkCues.ts";

/** A walk, with its planned seconds (null: unknown), or a train or bus. */
export type OnwardPart = { kind: "walk"; model: RideModel; to: string | null; seconds: number | null } | { kind: "transit"; leg: OnBoardLeg };

/** A walk is over this near its end, along it or as the crow flies (a door off the line). */
export const WALK_DONE_M = 25;
export const WALK_END_M = 40;
/**
 * A walk not seen to end (its GPS lost on the way down to a platform, a door off its line) is taken as walked once its
 * planned time has gone this many times over, plus WALK_SLACK_S: the train after it is then followed, or the ride may
 * pause at the end as usual.
 */
export const WALK_TIME_FACTOR = 1.5;
export const WALK_SLACK_S = 180;

/** A walk as a part to follow; null for one with no line. */
export function walkPart(path: WalkPath, seconds: number | null = null): OnwardPart | null {
  const model = walkModel(path);
  return model ? { kind: "walk", model, to: path.to, seconds } : null;
}

/** A transit plan's steps after its line, as parts to follow, up to its next riding leg (Ride the rest's). */
export function onwardOf(steps: readonly TransitStep[], after: number): OnwardPart[] {
  const parts: OnwardPart[] = [];
  for (let i = after + 1; i < steps.length; i += 1) {
    const step = steps[i];
    const draw = drawOf(step);
    if (draw === "ride") break;
    if (step.mode === "walk" || step.mode === "take") {
      const part = walkPart({ coordinates: step.coordinates, turns: step.turns ?? [], to: step.to }, step.seconds);
      if (part) parts.push(part);
      // A walk to a dock: the share bike's ride after it is Ride the rest's.
      if (step.mode === "take") break;
    } else if (draw === "transit") {
      // The trip's end from the stop to get off: every step after it, its wait too (as the plan's total adds them).
      const leg = onBoardLeg(step, steps.slice(i + 1).reduce((sum, later) => sum + later.seconds + later.wait_s, 0));
      if (leg) parts.push({ kind: "transit", leg });
    }
  }
  return parts;
}

export interface OnwardState {
  /** The part followed now, by its place; past the last, all done. */
  index: number;
  /** When it began. */
  since: number;
  walk: RideState | null;
  board: OnBoardState | null;
}

function begin(parts: readonly OnwardPart[], index: number, now: number): OnwardState {
  const part = parts[index];
  return { index, since: now, walk: part?.kind === "walk" ? walkStart() : null, board: part?.kind === "transit" ? onBoardStart(now) : null };
}

export function onwardStart(parts: readonly OnwardPart[], now: number): OnwardState {
  return begin(parts, 0, now);
}

/** Whether a part is still being followed (the ride screen keeps awake and never pauses at the end for it). */
export function onwardActive(parts: readonly OnwardPart[], state: OnwardState | null): boolean {
  return !!state && state.index < parts.length;
}

/**
 * A fix (or, on transit, the clock alone) into what follows the line. `events`: a walk's turns, said as a ride's;
 * `said`: the transit's next stop and the stop to get off, and the arrival at the end of the last walk.
 */
export function onwardStep(
  parts: readonly OnwardPart[],
  state: OnwardState,
  now: number,
  fix: RideFix | null,
  level: Verbosity,
): { state: OnwardState; events: RideEvent[]; said: string[] } {
  const part = parts[state.index];
  if (!part) return { state, events: [], said: [] };
  if (part.kind === "walk") {
    const out = fix ? walkStep(part.model, state.walk ?? walkStart(), fix, level) : { state: state.walk ?? walkStart(), events: [] };
    const following = parts[state.index + 1];
    const end = part.model.coordinates[part.model.coordinates.length - 1];
    const accuracy = fix ? Math.max(0, fix.accuracyM) : Infinity;
    const timedOut = part.seconds !== null && now - state.since >= (part.seconds * WALK_TIME_FACTOR + WALK_SLACK_S) * 1000;
    const done =
      timedOut ||
      (out.state.progressM !== null && out.state.progressM >= part.model.lengthM - WALK_DONE_M) ||
      (!!fix && accuracy <= AT_STOP_M && haversineM(fix.point, end) <= WALK_END_M) ||
      // At the stop the train leaves from, a rough fix too (a Wi-Fi fix on the platform).
      (!!fix && following?.kind === "transit" && accuracy <= ROUGH_FIX_M && haversineM(fix.point, following.leg.stops[0].point) <= Math.max(AT_STOP_M, accuracy));
    if (!done) return { state: { ...state, walk: out.state }, events: out.events, said: [] };
    const said = state.index === parts.length - 1 && !timedOut ? [t(ARRIVED_SAID)] : [];
    return { state: begin(parts, state.index + 1, now), events: out.events, said };
  }
  const out = onBoardStep(part.leg, state.board ?? onBoardStart(now), now, fix);
  if (!out.state.done) return { state: { ...state, board: out.state }, events: [], said: out.said };
  return { state: begin(parts, state.index + 1, now), events: [], said: out.said };
}
