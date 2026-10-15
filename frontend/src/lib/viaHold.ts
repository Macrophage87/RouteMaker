/**
 * A long press on a via point's marker (Stephen 2026-10-13: long-press or right-click a stop to remove
 * it). iOS sends no contextmenu for a held touch, so one finger held still this long counts as a long
 * press; a second finger, a move past the slop, a lift or a drag of the marker calls it off.
 */
export const HOLD_MS = 550;
/** How far a held finger may wander, in CSS pixels, and still be a hold. */
export const HOLD_SLOP_PX = 10;

interface TouchPoint {
  clientX: number;
  clientY: number;
}
interface Touches {
  length: number;
  [index: number]: TouchPoint;
}

// Wrapped, so the browser's timers are never called with another `this` (an "Illegal invocation").
const BROWSER_TIMERS = {
  set: ((fn: () => void, ms: number) => setTimeout(fn, ms)) as typeof setTimeout,
  clear: ((id: ReturnType<typeof setTimeout>) => clearTimeout(id)) as typeof clearTimeout,
};

export class ViaHold {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private from: TouchPoint | null = null;
  private readonly onHold: () => void;
  private readonly timers: { set: typeof setTimeout; clear: typeof clearTimeout };

  constructor(onHold: () => void, timers: { set: typeof setTimeout; clear: typeof clearTimeout } = BROWSER_TIMERS) {
    this.onHold = onHold;
    this.timers = timers;
  }

  start(touches: Touches): void {
    this.cancel();
    if (touches.length !== 1) return;
    this.from = { clientX: touches[0].clientX, clientY: touches[0].clientY };
    this.timer = this.timers.set(() => {
      this.timer = null;
      this.from = null;
      this.onHold();
    }, HOLD_MS);
  }

  move(touches: Touches): void {
    if (this.from === null) return;
    if (touches.length !== 1) return this.cancel();
    const dx = touches[0].clientX - this.from.clientX;
    const dy = touches[0].clientY - this.from.clientY;
    if (dx * dx + dy * dy > HOLD_SLOP_PX * HOLD_SLOP_PX) this.cancel();
  }

  cancel(): void {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
    this.from = null;
  }
}
