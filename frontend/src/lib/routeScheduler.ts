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
 *   not on a timer of our own - and the latest plan is sent then, a bounded
 *   number of times; a refusal without Retry-After is shown as it is.
 */
import type { RouteResult } from "./api.ts";

export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
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

  private pump(): void {
    if (this.inFlight || this.wait !== null || this.debounce !== null || this.latest === null) return;
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
    const error = result.ok ? null : result.error;
    const waitable =
      error &&
      (error.status === 429 || error.status === 503) &&
      error.retryAfterS !== undefined &&
      this.waitsForLatest < this.maxWaits;
    if (error && waitable) {
      this.waitsForLatest += 1;
      const seconds = Math.max(1, error.retryAfterS ?? 1);
      this.state({ kind: "waiting", seconds });
      this.wait = this.timers.set(() => {
        this.wait = null;
        this.pump();
      }, seconds * 1000);
      return;
    }
    this.state({ kind: "idle" });
    this.options.onResult(plan, result);
  }
}
