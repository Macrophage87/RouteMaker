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
import { onBoardLeg, onBoardStart, onBoardStep, AT_STOP_M, type OnBoardLeg, type OnBoardState } from "./onBoard.ts";
import { drawOf } from "./transit.ts";
import { walkModel, walkStart, walkStep, type WalkPath } from "./walkCues.ts";

export type OnwardPart = { kind: "walk"; model: RideModel; to: string | null } | { kind: "transit"; leg: OnBoardLeg };

/** A walk is over this near its end. */
export const WALK_DONE_M = 25;

/** A walk as a part to follow; null for one with no line. */
export function walkPart(path: WalkPath): OnwardPart | null {
  const model = walkModel(path);
  return model ? { kind: "walk", model, to: path.to } : null;
}

/** A transit plan's steps after its line, as parts to follow, up to its next riding leg (Ride the rest's). */
export function onwardOf(steps: readonly TransitStep[], after: number): OnwardPart[] {
  const parts: OnwardPart[] = [];
  for (const step of steps.slice(after + 1)) {
    const draw = drawOf(step);
    if (draw === "ride") break;
    if (step.mode === "walk" || step.mode === "take") {
      const part = walkPart({ coordinates: step.coordinates, turns: step.turns ?? [], to: step.to });
      if (part) parts.push(part);
      // A walk to a dock: the share bike's ride after it is Ride the rest's.
      if (step.mode === "take") break;
    } else if (draw === "transit") {
      const leg = onBoardLeg(step);
      if (leg) parts.push({ kind: "transit", leg });
    }
  }
  return parts;
}

export interface OnwardState {
  /** The part followed now, by its place; past the last, all done. */
  index: number;
  walk: RideState | null;
  board: OnBoardState | null;
}

function begin(parts: readonly OnwardPart[], index: number, now: number): OnwardState {
  const part = parts[index];
  return { index, walk: part?.kind === "walk" ? walkStart() : null, board: part?.kind === "transit" ? onBoardStart(now) : null };
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
    if (!fix) return { state, events: [], said: [] };
    const out = walkStep(part.model, state.walk ?? walkStart(), fix, level);
    const following = parts[state.index + 1];
    const done =
      (out.state.progressM !== null && out.state.progressM >= part.model.lengthM - WALK_DONE_M) ||
      (following?.kind === "transit" && fix.accuracyM <= AT_STOP_M && haversineM(fix.point, following.leg.stops[0].point) <= AT_STOP_M);
    if (!done) return { state: { ...state, walk: out.state }, events: out.events, said: [] };
    const said = state.index === parts.length - 1 ? [t(ARRIVED_SAID)] : [];
    return { state: begin(parts, state.index + 1, now), events: out.events, said };
  }
  const out = onBoardStep(part.leg, state.board ?? onBoardStart(now), now, fix);
  if (!out.state.done) return { state: { ...state, board: out.state }, events: [], said: out.said };
  return { state: begin(parts, state.index + 1, now), events: [], said: out.said };
}
