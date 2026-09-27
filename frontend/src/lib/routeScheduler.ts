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
 *   not on a timer of our own, never less than a second and never more than
 *   RETRY_AFTER_CAP_S - and the latest plan is sent then, up to MAX_WAITS
 *   times for each plan; a refusal without Retry-After, or with it on any
 *   other status, is shown as it is, and so is a long ride that ran out of
 *   its time budget (`noAutoResend`): resent, it would most likely hold the
 *   one long slot for its whole budget again;
 * - once shown, a refusal's Retry-After still holds: "Try again", or any new
 *   plan, waits until it has passed instead of being refused once more;
 * - a wait the rider has been told about counts down, a second at a time.
 */
import { RETRY_AFTER_CAP_S, type RouteResult } from "./api.ts";

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
  /** While set, the API's last Retry-After has not passed: nothing is sent. */
  private hold: unknown = null;
  /** Whole seconds of the hold still to run. */
  private holdLeft = 0;
  /** Whether the last state given out was "waiting", so the countdown shows. */
  private holdAnnounced = false;
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
    if (this.inFlight) return;
    if (this.hold === null) this.state({ kind: "pending" });
    else if (!this.holdAnnounced) this.state({ kind: "waiting", seconds: this.holdLeft });
  }

  /**
   * Nothing to route (fewer than two points): drop what is pending. A
   * Retry-After still holds; it is the API's, not the plan's.
   */
  clear(): void {
    this.latest = null;
    this.generation += 1;
    if (this.debounce !== null) this.timers.clear(this.debounce);
    this.debounce = null;
    if (!this.inFlight) this.state({ kind: "idle" });
  }

  private state(state: SchedulerState): void {
    // Any other state replaces the "waiting" line: once the panel has shown
    // idle (Clear) or a result, the next plan held back is announced afresh.
    this.holdAnnounced = state.kind === "waiting";
    this.options.onState?.(state);
  }

  /**
   * Send nothing for this long; then send the latest plan, if any. Only
   * called as an answer settles, and nothing is sent while a hold is on, so
   * there is never an earlier hold to replace. One second a tick, so the
   * countdown can be shown and no timer is ever long enough to overflow.
   */
  private holdFor(seconds: number): void {
    this.holdLeft = seconds;
    this.tick();
  }

  private tick(): void {
    this.hold = this.timers.set(() => {
      this.holdLeft -= 1;
      if (this.holdLeft > 0) {
        if (this.holdAnnounced) this.state({ kind: "waiting", seconds: this.holdLeft });
        this.tick();
        return;
      }
      this.hold = null;
      this.pump();
    }, 1000);
  }

  private pump(): void {
    if (this.inFlight || this.debounce !== null || this.latest === null) return;
    if (this.hold !== null) {
      if (!this.holdAnnounced) this.state({ kind: "waiting", seconds: this.holdLeft });
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
    // At most the cap; at least a second, since the first tick is a second away.
    if (retryAfterS !== undefined) this.holdFor(Math.min(RETRY_AFTER_CAP_S, retryAfterS));
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
    if (retryAfterS !== undefined && !error?.noAutoResend && this.waitsForLatest < this.maxWaits) {
      // Waited out: pump() says so, and the hold sends the plan when it ends.
      this.waitsForLatest += 1;
      this.pump();
      return;
    }
    // Shown: nothing is left to send, so a hold that ends later sends nothing.
    this.latest = null;
    this.state({ kind: "idle" });
    this.options.onResult(plan, result);
  }
}
