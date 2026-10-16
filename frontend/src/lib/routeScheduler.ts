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
 * - a wait the rider has been told about counts down, a second at a time;
 * - an answer that is only a first route (v0.7.0, "Faster routing": Go's `quick`) is
 *   shown at once, and its full plan (`refine`) is then the one request in flight: it
 *   is never aborted either, and is shown (`onRefined`) only if the plan has not changed
 *   meanwhile. A plan asked for meanwhile waits for it, as for any request in flight,
 *   and is said to be pending; a refusal of the full plan leaves the first route shown
 *   (a Retry-After still holds for what is sent next).
 * - once the route shown is final (its full plan, or an answer that was full already), one
 *   more request may follow for the same plan (`after`: Go's More direct and Calmer,
 *   lib/neighbours.ts), the same way: the one request in flight, never aborted, its answer
 *   given (`onAfter`) only for the plan still asked for, and a plan asked for meanwhile
 *   waiting for it. Nothing is shown as loading while it runs: the route is shown already.
 */
import { RETRY_AFTER_CAP_S, type RouteError, type RouteResult } from "./api.ts";

/** What an `after` request answers: the scheduler reads only whether it was refused, and its Retry-After. */
export type AfterResult = { ok: true } | { ok: false; error: RouteError };

export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}

export type SchedulerState =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "in-flight" }
  | { kind: "waiting"; seconds: number };

export interface SchedulerOptions<P, A extends AfterResult = AfterResult> {
  send: (plan: P) => Promise<RouteResult>;
  onResult: (plan: P, result: RouteResult) => void;
  onState?: (state: SchedulerState) => void;
  timers?: Timers;
  debounceMs?: number;
  /** Automatic resends after a Retry-After, per plan, before the refusal is shown. */
  maxWaits?: number;
  /**
   * After an answer is shown: the request for its full plan where it was only a first route (v0.7.0, "Faster
   * routing"), else null. Called once per answer shown.
   */
  refine?: (plan: P, shown: RouteResult) => (() => Promise<RouteResult>) | null;
  /** The full plan, for the plan still asked for: swap it in (before Start only; the caller decides). */
  onRefined?: (plan: P, result: RouteResult) => void;
  /**
   * Once the route shown is final: one more request for the same plan, else null (v0.7.0, Go's More direct and
   * Calmer). `final` is the full plan's answer. Called at most once per plan answered.
   */
  after?: (plan: P, final: RouteResult) => (() => Promise<A>) | null;
  /** That request's answer, for the plan still asked for. */
  onAfter?: (plan: P, result: A) => void;
}

export const DEBOUNCE_MS = 300;
export const MAX_WAITS = 3;

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class RouteScheduler<P, A extends AfterResult = AfterResult> {
  private latest: P | null = null;
  private generation = 0;
  private inFlight = false;
  /** The request in flight follows a route shown: its full plan (`refine`) or the request after it (`after`). */
  private refining = false;
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
  private readonly options: SchedulerOptions<P, A>;

  constructor(options: SchedulerOptions<P, A>) {
    this.options = options;
    this.timers = options.timers ?? realTimers;
    this.debounceMs = options.debounceMs ?? DEBOUNCE_MS;
    this.maxWaits = options.maxWaits ?? MAX_WAITS;
  }

  /**
   * A new plan to route; it replaces any plan not yet sent. `now`: one deliberate pick (Go's destination; v0.7.0
   * "Faster routing" step 4), sent without the debounce, which is there to fold a burst of edits into one.
   */
  request(plan: P, options: { now?: boolean } = {}): void {
    this.latest = plan;
    this.generation += 1;
    this.waitsForLatest = 0;
    if (this.debounce !== null) this.timers.clear(this.debounce);
    this.debounce = null;
    if (!options.now) {
      this.debounce = this.timers.set(() => {
        this.debounce = null;
        this.pump();
      }, this.debounceMs);
    }
    if (this.inFlight && !this.refining) return;
    if (this.hold === null) this.state({ kind: "pending" });
    else if (!this.holdAnnounced) this.state({ kind: "waiting", seconds: this.holdLeft });
    if (options.now) this.pump();
  }

  /** Whether a request of the scheduler's is in flight (a first route's full plan included). */
  busy(): boolean {
    return this.inFlight;
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
    // A new plan asked for inside onResult is sent as usual; the full plan of this one is not wanted.
    if (generation !== this.generation || this.latest !== null) return;
    const follow = this.options.refine?.(plan, result) ?? null;
    if (follow === null) {
      this.startAfter(plan, generation, result);
      return;
    }
    this.inFlight = true;
    this.refining = true;
    follow().then(
      (refined) => this.settleRefined(plan, generation, refined),
      () => this.settleRefined(plan, generation, null),
    );
  }

  /** The full plan after a first route: shown only for the plan still asked for, then the next plan goes. */
  private settleRefined(plan: P, generation: number, result: RouteResult | null): void {
    this.settleFollow(result);
    if (generation === this.generation && result !== null && result.ok) {
      this.options.onRefined?.(plan, result);
      // A plan asked for inside onRefined is sent as usual, below; the request after this one is not wanted.
      if (generation === this.generation && this.latest === null) {
        this.startAfter(plan, generation, result);
        return;
      }
    }
    this.next(generation);
  }

  /** The request after a final route (`after`), where one is wanted for the plan still asked for. */
  private startAfter(plan: P, generation: number, final: RouteResult): void {
    const follow = this.options.after?.(plan, final) ?? null;
    if (follow === null || generation !== this.generation || this.latest !== null) return;
    this.inFlight = true;
    this.refining = true;
    follow().then(
      (answer) => this.settleAfter(plan, generation, answer),
      () => this.settleAfter(plan, generation, null),
    );
  }

  private settleAfter(plan: P, generation: number, result: A | null): void {
    this.settleFollow(result);
    if (generation === this.generation && result !== null) this.options.onAfter?.(plan, result);
    this.next(generation);
  }

  /** A follow-up request settled: the slot is free, and a Retry-After it carried holds for what is sent next. */
  private settleFollow(result: AfterResult | null): void {
    this.inFlight = false;
    this.refining = false;
    const error = result && !result.ok ? result.error : null;
    const retryAfterS = error && (error.status === 429 || error.status === 503) ? error.retryAfterS : undefined;
    if (retryAfterS !== undefined && this.hold === null) this.holdFor(Math.min(RETRY_AFTER_CAP_S, retryAfterS));
  }

  /** After a follow-up: the plan asked for meanwhile goes now, or the scheduler is idle again. */
  private next(generation: number): void {
    if (this.latest === null) {
      if (generation !== this.generation) this.state({ kind: "idle" });
      return;
    }
    this.pump();
  }
}
