/**
 * When a press on the drawn route becomes a drag of it.
 *
 * A mouse press on the line grabs it at once (the map is told not to pan),
 * and it is a drag once the pointer has moved past MapLibre's own click
 * tolerance; a press released before that is a click, which the map handles.
 *
 * A finger is different. On a phone the route runs through the middle of the
 * screen, so "a touch that starts on the line drags it" would take most pans
 * away from the rider - and a finger is 7-10 mm across, so the line's hit
 * area has to be wide. The finger instead picks the line up by pressing and
 * holding still, the platform's own gesture for picking something up (Android
 * and iOS both start a drag of a list item or an icon with a long press); a
 * touch that moves before then is a pan, as it always was, and two fingers
 * are a pinch. HOLD_MS is shorter than the platforms' ~500 ms because the
 * rider is aiming at the line and the handle appears as the feedback.
 */
import type { Timers } from "./routeScheduler.ts";

export type PointerKind = "mouse" | "touch";

/** How long a finger stays still on the line to pick it up. */
export const HOLD_MS = 400;
/** How far a finger may wander while holding (Android's touch slop is 8 dp). */
export const TOUCH_SLOP_PX = 10;
/** MapLibre's clickTolerance: less than this is a click, not a drag. */
export const MOUSE_SLOP_PX = 3;

type Phase =
  | { kind: "idle" }
  | { kind: "armed"; x: number; y: number }
  | { kind: "holding"; x: number; y: number; timer: unknown }
  | { kind: "dragging"; pointer: PointerKind; x: number; y: number; moved: boolean };

export interface GestureOptions {
  /** A held finger has picked the line up: stop the map panning, show the handle. */
  onPickUp: () => void;
  timers?: Timers;
  holdMs?: number;
}

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class LineGesture {
  private phase: Phase = { kind: "idle" };
  private readonly timers: Timers;
  private readonly holdMs: number;
  private readonly onPickUp: () => void;

  constructor(options: GestureOptions) {
    this.onPickUp = options.onPickUp;
    this.timers = options.timers ?? realTimers;
    this.holdMs = options.holdMs ?? HOLD_MS;
  }

  /** A press that landed on the line (the caller has checked that). */
  press(pointer: PointerKind, x: number, y: number): void {
    this.cancel();
    if (pointer === "mouse") {
      this.phase = { kind: "armed", x, y };
      return;
    }
    const timer = this.timers.set(() => {
      if (this.phase.kind !== "holding") return;
      this.phase = { kind: "dragging", pointer: "touch", x: this.phase.x, y: this.phase.y, moved: false };
      this.onPickUp();
    }, this.holdMs);
    this.phase = { kind: "holding", x, y, timer };
  }

  /**
   * The pointer moved. "drag" while the line is being dragged (show the
   * preview there); "none" otherwise, including a finger that moved before
   * its hold was up, which is a pan and ends the gesture.
   */
  move(x: number, y: number): "drag" | "none" {
    const phase = this.phase;
    if (phase.kind === "armed") {
      if (Math.hypot(x - phase.x, y - phase.y) < MOUSE_SLOP_PX) return "none";
      this.phase = { kind: "dragging", pointer: "mouse", x: phase.x, y: phase.y, moved: true };
      return "drag";
    }
    if (phase.kind === "holding") {
      if (Math.hypot(x - phase.x, y - phase.y) > TOUCH_SLOP_PX) this.cancel();
      return "none";
    }
    if (phase.kind === "dragging") {
      if (!phase.moved && Math.hypot(x - phase.x, y - phase.y) >= MOUSE_SLOP_PX) phase.moved = true;
      return "drag";
    }
    return "none";
  }

  /**
   * The press ended. "drop" when the line was dragged somewhere: put a via
   * there. A finger that picked the line up and let go without moving drops
   * nothing.
   */
  release(): "drop" | "none" {
    const phase = this.phase;
    this.cancel();
    return phase.kind === "dragging" && phase.moved ? "drop" : "none";
  }

  /** Forget the gesture (Escape, a second finger, the plan changed). Whether a drag was under way. */
  cancel(): boolean {
    const phase = this.phase;
    if (phase.kind === "holding") this.timers.clear(phase.timer);
    this.phase = { kind: "idle" };
    return phase.kind === "dragging";
  }

  /** Whether the line has been picked up (the map must not pan). */
  get dragging(): boolean {
    return this.phase.kind === "dragging";
  }

  /** Whether a press on the line is being followed at all. */
  get active(): boolean {
    return this.phase.kind !== "idle";
  }
}
