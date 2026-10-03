/**
 * Waiting for things to settle before acting on them (a11y review of
 * integrate-2: every slider key press planned a route, and each plan was
 * announced twice, "Planning..." and then the route). Kept out of the
 * components so it is tested without a DOM or real time.
 */

/** The timer functions, so a test can drive time itself. */
export interface Clock {
  set(run: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

export const REAL_CLOCK: Clock = {
  set: (run, ms) => setTimeout(run, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** One pending action at a time: a newer one replaces it, and `now` runs one at once. */
export class Debounce {
  private handle: unknown = null;
  private readonly waitMs: number;
  private readonly clock: Clock;

  constructor(waitMs: number, clock: Clock = REAL_CLOCK) {
    this.waitMs = waitMs;
    this.clock = clock;
  }

  /** Run `action` once nothing newer has come for the wait. */
  later(action: () => void): void {
    this.cancel();
    this.handle = this.clock.set(() => {
      this.handle = null;
      action();
    }, this.waitMs);
  }

  /** Drop what is pending and run `action` now. */
  now(action: () => void): void {
    this.cancel();
    action();
  }

  get pending(): boolean {
    return this.handle !== null;
  }

  cancel(): void {
    if (this.handle !== null) this.clock.clear(this.handle);
    this.handle = null;
  }
}

/**
 * How long a slider's keys must rest before the route is planned: a rider
 * pressing an arrow five times plans once. A pointer let go, or the focus
 * leaving, plans at once.
 */
export const KEY_SETTLE_MS = 600;

/**
 * How long a planned route's sentence waits before the live region says it,
 * so routes that replace each other quickly are said once, the last.
 */
export const ANNOUNCE_SETTLE_MS = 700;

/**
 * The live region's words: a sentence is shown once it has stood for the
 * wait; clearing ("") is at once, so the same sentence after a new plan is
 * said again.
 */
export class SettledText {
  private readonly debounce: Debounce;
  private readonly show: (text: string) => void;

  constructor(waitMs: number, show: (text: string) => void, clock: Clock = REAL_CLOCK) {
    this.debounce = new Debounce(waitMs, clock);
    this.show = show;
  }

  offer(text: string): void {
    if (text === "") this.debounce.now(() => this.show(""));
    else this.debounce.later(() => this.show(text));
  }

  cancel(): void {
    this.debounce.cancel();
  }
}
