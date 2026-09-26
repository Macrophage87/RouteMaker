/**
 * When a route request is sent, and which answer is shown.
 *
 * The API holds a small number of in-flight slots per client (two, in
 * src/core/ratelimit.py) and a few for the whole deployment. Aborting a fetch
 * in the browser does not free one: gunicorn goes on computing the dropped
 * request until it finishes. So a planner that sent a request on every click
 * and aborted the previous one ran out of slots at an ordinary clicking pace,
 * and the newest plan - the one the rider wanted - came back "Slow down".
 *
 * The rules, then:
 * - a change waits a short debounce, so a burst of clicks is one request;
 * - at most one request is in flight, and it is never aborted: it is allowed
 *   to finish, so its slot is free again before the next request goes;
 * - only the latest plan is kept while waiting; anything older is dropped
 *   unsent, and an answer for a plan that has since changed is not shown;
 * - a 429 or 503 carrying Retry-After is waited out - for exactly that long,
 *   not on a timer of our own, and never less than a second - and the latest
 *   plan is sent then, up to MAX_WAITS times for each plan; a refusal without
 *   Retry-After, or with it on any other status, is shown as it is;
 * - once shown, a refusal's Retry-After still holds: "Try again", or any new
 *   plan, waits until it has passed instead of being refused once more.
 */
import type { RouteResult } from "./api.ts";

export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
  /** The clock, in milliseconds; Date.now when absent. */
  time?: () => number;
}

export type SchedulerState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "in-flight" }
  | { kind: "waiting"; seconds: number };

export interface SchedulerOptions<P> {
  send: (plan: P) => Promise<RouteResult>;
  onResult: (plan: P, result: RouteResult) => void;
  onState?: (state: SchedulerState) => void;
  timers?: Timers;
  debounceMs?: number;
  /** Automatic resends after a Retry-After, per plan, before the refusal is shown. */
  maxWaits?: number;
}

export const DEBOUNCE_MS = 300;
export const MAX_WAITS = 3;

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class RouteScheduler<P> {
  private latest: P | null = null;
  private generation = 0;
  private inFlight = false;
  private debounce: unknown = null;
  private wait: unknown = null;
  private waitsForLatest = 0;
  /** The API asked not to be asked again before this time (Retry-After). */
  private notBefore = 0;
  private readonly timers: Timers;
  private readonly debounceMs: number;
  private readonly maxWaits: number;
  private readonly options: SchedulerOptions<P>;

  constructor(options: SchedulerOptions<P>) {
    this.options = options;
    this.timers = options.timers ?? realTimers;
    this.debounceMs = options.debounceMs ?? DEBOUNCE_MS;
    this.maxWaits = options.maxWaits ?? MAX_WAITS;
  }

  /** A new plan to route; it replaces any plan not yet sent. */
  request(plan: P): void {
    this.latest = plan;
    this.generation += 1;
    this.waitsForLatest = 0;
    if (this.debounce !== null) this.timers.clear(this.debounce);
    this.debounce = this.timers.set(() => {
      this.debounce = null;
      this.pump();
    }, this.debounceMs);
    if (!this.inFlight && this.wait === null) this.state({ kind: "pending" });
  }

  /** Nothing to route (fewer than two points): drop what is pending. */
  clear(): void {
    this.latest = null;
    this.generation += 1;
    if (this.debounce !== null) this.timers.clear(this.debounce);
    this.debounce = null;
    if (this.wait !== null) this.timers.clear(this.wait);
    this.wait = null;
    if (!this.inFlight) this.state({ kind: "idle" });
  }

  private state(state: SchedulerState): void {
    this.options.onState?.(state);
  }

  private time(): number {
    return this.timers.time?.() ?? Date.now();
  }

  private pump(): void {
    if (this.inFlight || this.wait !== null || this.debounce !== null || this.latest === null) return;
    const hold = this.notBefore - this.time();
    if (hold > 0) {
      this.state({ kind: "waiting", seconds: Math.ceil(hold / 1000) });
      this.wait = this.timers.set(() => {
        this.wait = null;
        this.pump();
      }, hold);
      return;
    }
    const plan = this.latest;
    const generation = this.generation;
    this.inFlight = true;
    this.state({ kind: "in-flight" });
    this.options.send(plan).then(
      (result) => this.settle(plan, generation, result),
      () => this.settle(plan, generation, null),
    );
  }

  private settle(plan: P, generation: number, result: RouteResult | null): void {
    this.inFlight = false;
    // A Retry-After holds for whatever is sent next, this plan or a newer one.
    const error = result && !result.ok ? result.error : null;
    const retryAfterS = error && (error.status === 429 || error.status === 503) ? error.retryAfterS : undefined;
    if (retryAfterS !== undefined) this.notBefore = this.time() + Math.max(1, retryAfterS) * 1000;
    const current = generation === this.generation;
    if (!current) {
      // The plan changed while this was computing: its answer is not shown,
      // and the newer plan goes now that the slot is free.
      if (this.latest === null) this.state({ kind: "idle" });
      this.pump();
      return;
    }
    if (result === null) {
      this.latest = null;
      this.state({ kind: "idle" });
      return;
    }
    if (retryAfterS !== undefined && this.waitsForLatest < this.maxWaits) {
      // Waited out in pump(), which holds until notBefore.
      this.waitsForLatest += 1;
      this.pump();
      return;
    }
    this.state({ kind: "idle" });
    this.options.onResult(plan, result);
  }
}
