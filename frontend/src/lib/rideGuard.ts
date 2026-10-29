/** What a RideGuard (RideGuard.tsx) does with an error in its part: leave the part out during a ride or Roam, else pass it on. */
export function guardOutcome(onBike: boolean): "leave-out" | "pass-on" {
  return onBike ? "leave-out" : "pass-on";
}

export type GuardState = { error: unknown; failed: boolean; wasOn: boolean };

/**
 * A RideGuard's state for its next draw. When the ride or Roam ends, a part left out is cleared to be drawn again,
 * before it is drawn (were it cleared after, the old error would reach the crash screen at the ride's end).
 */
export function guardForProps(state: GuardState, onBike: boolean): GuardState {
  if (state.wasOn && !onBike && state.failed) return { error: null, failed: false, wasOn: false };
  return state.wasOn === onBike ? state : { ...state, wasOn: onBike };
}
