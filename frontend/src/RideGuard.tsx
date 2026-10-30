/**
 * RIDE GETS ITS OWN ERROR BOUNDARY (the 2026-10-29 review). The page has one boundary, round the whole app
 * (CrashScreen.tsx CrashBoundary): an error in any part of it, even one hidden during a ride (the planner panel), took
 * Ride mode down with it, and the turn cues and the voice stopped until the rider noticed and pressed Reload.
 *
 * RideGuard goes round a part that is not the ride itself (the hidden planner, the map). While the rider is on the bike
 * (`on`: a ride or Roam), an error in it is kept for the error report (lib/crashReport.ts) and the part is left out,
 * so the ride goes on. Off the bike the error goes on up to the crash screen as before. When the ride ends the part is
 * drawn again: if it fails again, the crash screen shows then, with the ride over.
 */
import { Component, type ReactNode } from "react";
import { logError } from "./lib/crashReport.ts";
import { guardForProps, guardOutcome, type GuardState } from "./lib/rideGuard.ts";

export class RideGuard extends Component<{ on: boolean; children: ReactNode }, GuardState> {
  state: GuardState = { error: null, failed: false, wasOn: this.props.on };

  static getDerivedStateFromError(error: unknown): Partial<GuardState> {
    return { error: error ?? new Error("Unknown error"), failed: true };
  }

  // The ride over: the part is drawn again, cleared before that draw (lib/rideGuard.ts guardForProps).
  static getDerivedStateFromProps(props: { on: boolean }, state: GuardState): GuardState {
    return guardForProps(state, props.on);
  }

  componentDidCatch(error: unknown) {
    // Kept for the error report only where the guard holds it; passed on, the crash screen reports it.
    if (guardOutcome(this.props.on) === "leave-out") logError("error", error);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    if (guardOutcome(this.props.on) === "pass-on") throw this.state.error;
    return null;
  }
}
