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
 * - except where the API can stop it (`cancel`; routing audit S7, option B, which the owner
 *   approved on 2026-10-27, reversing "one request at a time" for this case alone): then a
 *   plan asked for while a full plan runs replaces it. The full plan, sent with an id
 *   (X-Plan-Id), is cancelled by that id (POST /api/route/cancel), and the next plan goes
 *   as soon as it would with nothing in flight, naming the plan it replaces (X-Plan-Replaces):
 *   the API stops the old plan at its next router call, and lets the new one wait a moment
 *   for the slot it gives back. Every resend of it names that plan too, until an answer
 *   other than a 429 or 503 comes: the old plan gives its slot back only at its next router
 *   call, which can be tens of seconds away, so those refusals are waited out as the full
 *   plan used to be, for up to REPLACE_PATIENCE_S of Retry-After, without counting against
 *   MAX_WAITS. Nothing the cancelled plan answers is read, its refusal or
 *   Retry-After included. Only a full plan is replaced: a first route still waits, as do
 *   Plan mode's requests, which have no full plan.
 * - once the route shown is final (its full plan, or an answer that was full already), one
 *   more request may follow for the same plan (`after`: Go's More direct and Calmer,
 *   lib/neighbours.ts). It stands outside these rules, at the lowest priority: it is not
 *   the request in flight, so a plan or a ride's re-route asked for meanwhile is sent at
 *   once (the API gives it slots of its own, ratelimit.NEIGHBOURS_IN_FLIGHT); its answer
 *   is given (`onAfter`) only for the plan still asked for, and a refusal of it holds
 *   nothing back. Nothing is shown as loading while it runs: the route is shown already.
 */
import { RETRY_AFTER_CAP_S, type RouteError, type RouteResult } from "./api.ts";

/** What an `after` request answers: the scheduler gives it on, or drops it for a plan since changed. */
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
  /** `replaces`: the id of a full plan this request replaces, cancelled already (`cancel`). */
  send: (plan: P, replaces?: string) => Promise<RouteResult>;
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
  refine?: (plan: P, shown: RouteResult, planId: string) => (() => Promise<RouteResult>) | null;
  /**
   * Stop the full plan sent with `planId` (refine's), which a newer plan replaces (routing audit S7). Fire and
   * forget. Without it, a plan asked for while a full plan runs waits for it.
   */
  cancel?: (planId: string) => void;
  /** A new plan id (default: 32 random hex digits). */
  planId?: () => string;
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
/**
 * How long, in Retry-After seconds, a plan replacing a cancelled full plan waits out 429s and 503s before the
 * refusal is shown: the longest a plan runs (a long ride's 50 s budget), which is the longest the scheduler used to
 * wait for a full plan before it could cancel one. The cancelled plan usually frees its slot far sooner.
 */
export const REPLACE_PATIENCE_S = 50;

/** 32 random hex digits: a plan's id, unguessable, so no other page names it (the API scopes it per client too). */
export function newPlanId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class RouteScheduler<P, A extends AfterResult = AfterResult> {
  private latest: P | null = null;
  private generation = 0;
  private inFlight = false;
  /** The request in flight is a full plan following a first route shown (`refine`). */
  private refining = false;
  /** The full plan in flight: its id, and a count that tells a replaced one's answer from the current one's. */
  private refineId: string | null = null;
  private refineToken = 0;
  /** A full plan replaced and cancelled: named by the next request sent (X-Plan-Replaces). */
  private replaced: string | null = null;
  /** Retry-After seconds waited out so far for the plan replacing `replaced`. */
  private replaceWaitedS = 0;
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
    this.replaceRefine();
    if (this.inFlight && !this.refining) return;
    if (this.hold === null) this.state({ kind: "pending" });
    else if (!this.holdAnnounced) this.state({ kind: "waiting", seconds: this.holdLeft });
    if (options.now) this.pump();
  }

  /**
   * Whether a request of the scheduler's is in flight (a first route's full plan included), or a full plan just
   * replaced may still hold its slot, until the plan replacing it has an answer other than a 429 or 503 (Go's early
   * start waits that out).
   */
  busy(): boolean {
    return this.inFlight || this.replaced !== null;
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
    // Its answer would not be shown: the API stops computing it. Nothing replaces it yet.
    this.replaceRefine(false);
    if (!this.inFlight) this.state({ kind: "idle" });
  }

  /**
   * The full plan in flight, where the API can stop it (`cancel`): cancelled, and its slot counted free at once
   * (routing audit S7, option B; the owner, 2026-10-27). Its answer is then never read.
   */
  private replaceRefine(replaced = true): void {
    const id = this.refineId;
    if (!this.refining || id === null || !this.options.cancel) return;
    this.refineToken += 1;
    this.refineId = null;
    this.inFlight = false;
    this.refining = false;
    if (replaced) {
      this.replaced = id;
      this.replaceWaitedS = 0;
    }
    this.options.cancel(id);
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
    // Kept for every resend until the slot is given back (`settle`).
    const replaces = this.replaced;
    this.inFlight = true;
    this.state({ kind: "in-flight" });
    (replaces === null ? this.options.send(plan) : this.options.send(plan, replaces)).then(
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
    // A plan replacing a cancelled full plan: until an answer other than a 429 or 503, the old plan may still
    // hold the slot, so what is sent next still names it (and the API still lets it wait a moment).
    let replacing = false;
    if (this.replaced !== null) {
      if (retryAfterS !== undefined && !error?.noAutoResend && this.replaceWaitedS < REPLACE_PATIENCE_S) {
        this.replaceWaitedS += Math.min(RETRY_AFTER_CAP_S, retryAfterS);
        replacing = true;
      } else if (retryAfterS === undefined || error?.noAutoResend) {
        this.replaced = null;
      }
    }
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
    if (replacing) {
      // The cancelled plan's slot, waited out as the full plan itself used to be: not one of MAX_WAITS.
      this.pump();
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
    this.replaced = null;
    this.state({ kind: "idle" });
    this.options.onResult(plan, result);
    // A new plan asked for inside onResult is sent as usual; the full plan of this one is not wanted.
    if (generation !== this.generation || this.latest !== null) return;
    const id = this.options.cancel ? (this.options.planId ?? newPlanId)() : "";
    const follow = this.options.refine?.(plan, result, id) ?? null;
    if (follow === null) {
      this.startAfter(plan, generation, result);
      return;
    }
    this.inFlight = true;
    this.refining = true;
    this.refineId = this.options.cancel ? id : null;
    this.refineToken += 1;
    const token = this.refineToken;
    follow().then(
      (refined) => this.settleRefined(plan, generation, token, refined),
      () => this.settleRefined(plan, generation, token, null),
    );
  }

  /** The full plan after a first route: shown only for the plan still asked for, then the next plan goes. */
  private settleRefined(plan: P, generation: number, token: number, result: RouteResult | null): void {
    // Replaced and cancelled (`replaceRefine`): its slot was counted free then, and nothing it says is read.
    if (token !== this.refineToken) return;
    this.refineId = null;
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
    // Not the request in flight: nothing waits for it, and its refusal holds nothing back.
    follow().then(
      (answer) => {
        if (generation === this.generation) this.options.onAfter?.(plan, answer);
      },
      () => {},
    );
  }

  /** The full plan settled: the slot is free, and a Retry-After it carried holds for what is sent next. */
  private settleFollow(result: RouteResult | null): void {
    this.inFlight = false;
    this.refining = false;
    const error = result && !result.ok ? result.error : null;
    const retryAfterS = error && (error.status === 429 || error.status === 503) ? error.retryAfterS : undefined;
    if (retryAfterS !== undefined && this.hold === null) this.holdFor(Math.min(RETRY_AFTER_CAP_S, retryAfterS));
  }

  /** After the full plan: the plan asked for meanwhile goes now, or the scheduler is idle again. */
  private next(generation: number): void {
    if (this.latest === null) {
      if (generation !== this.generation) this.state({ kind: "idle" });
      return;
    }
    this.pump();
  }
}
