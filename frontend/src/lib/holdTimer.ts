/**
 * A short-lived message's timer (review F4, F6): it clears the message after `ms`, but never while the rider's
 * focus or pointer is in it (WCAG 2.2.1); once both leave, the full time starts again. Ride ended's Undo and the
 * 311 line ("Logged for 311: Pothole.") both use it.
 */
export interface Clock {
  set: (run: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}

const realClock: Clock = {
  set: (run, ms) => setTimeout(run, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class HoldTimer {
  private handle: unknown = undefined;
  private focused = false;
  private hovered = false;
  private readonly ms: number;
  private readonly done: () => void;
  private readonly clock: Clock;

  constructor(ms: number, done: () => void, clock: Clock = realClock) {
    this.ms = ms;
    this.done = done;
    this.clock = clock;
  }

  /** (Re)starts the full time, unless the focus or the pointer holds it. */
  start(): void {
    this.stop();
    if (this.focused || this.hovered) return;
    this.handle = this.clock.set(() => {
      this.handle = undefined;
      this.done();
    }, this.ms);
  }

  stop(): void {
    if (this.handle !== undefined) this.clock.clear(this.handle);
    this.handle = undefined;
  }

  /** The message went: stopped, and nothing holds it any more (a gone element sends no blur or leave). */
  reset(): void {
    this.stop();
    this.focused = false;
    this.hovered = false;
  }

  get running(): boolean {
    return this.handle !== undefined;
  }

  /** The focus came in (true) or left the message (false). */
  focus(on: boolean): void {
    this.focused = on;
    this.hold();
  }

  /** The pointer came over (true) or left the message (false). */
  hover(on: boolean): void {
    this.hovered = on;
    this.hold();
  }

  private hold(): void {
    if (this.focused || this.hovered) this.stop();
    else this.start();
  }
}
