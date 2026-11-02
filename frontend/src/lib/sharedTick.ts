/**
 * One 5-minute clock for the page's background checks (the owner, 2026-11-01: battery audit): the ride's weather, the
 * view's area closures and the rail status each had their own 5-minute timer, started whenever each began, so the
 * phone's radio woke up to three times in five minutes. Here every subscriber is called together on the wall clock's
 * 5-minute boundaries (12:00, 12:05, ...), so the radio wakes once for all of them.
 *
 * While the page is hidden only the subscribers that say they run hidden are called (the app's ride weather, spoken
 * with the screen locked); with none of those the timer is not even set. A subscriber with `catchUp` that missed a
 * boundary while hidden is called as the page comes back, so a check never waits up to five more minutes.
 */

export const TICK_MS = 5 * 60_000;

/** The boundary at or before `now`. */
export function boundaryAt(now: number, every: number = TICK_MS): number {
  return Math.floor(now / every) * every;
}

/** Milliseconds from `now` to the next boundary (a whole period when `now` is on one). */
export function msToNextBoundary(now: number, every: number = TICK_MS): number {
  return boundaryAt(now, every) + every - now;
}

export interface TickOptions {
  /** Called while the page is hidden too (asked at each boundary, so it may change). */
  whileHidden?: () => boolean;
  /** Missed a boundary while hidden: called as the page is shown again. */
  catchUp?: boolean;
}

export interface TickEnv {
  now(): number;
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
  hidden(): boolean;
  /** Calls `fn` on each visibility change; answers the function that stops it. */
  onVisibility(fn: () => void): () => void;
}

export function browserTickEnv(): TickEnv {
  return {
    now: () => Date.now(),
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (id) => window.clearTimeout(id as number),
    hidden: () => typeof document !== "undefined" && document.visibilityState === "hidden",
    onVisibility: (fn) => {
      if (typeof document === "undefined") return () => undefined;
      document.addEventListener("visibilitychange", fn);
      return () => document.removeEventListener("visibilitychange", fn);
    },
  };
}

interface Subscriber {
  fn: () => void;
  options: TickOptions;
  /** The last boundary this subscriber had (or the one before it subscribed). */
  had: number;
}

export interface SharedTick {
  /** `fn` at every boundary from now on; answers the unsubscribe. */
  subscribe(fn: () => void, options?: TickOptions): () => void;
  /** How many subscribe now (tests). */
  size(): number;
  /** Whether the timer is set (tests). */
  armed(): boolean;
}

export function createSharedTick(env: TickEnv, every: number = TICK_MS): SharedTick {
  const subs = new Set<Subscriber>();
  let timer: unknown = null;
  let stopVisibility: (() => void) | null = null;

  const runsHidden = (s: Subscriber) => s.options.whileHidden?.() === true;
  const wanted = () => subs.size > 0 && (!env.hidden() || [...subs].some(runsHidden));

  const disarm = () => {
    if (timer !== null) env.clearTimeout(timer);
    timer = null;
  };
  const arm = () => {
    disarm();
    if (!wanted()) return;
    // A few ms past the boundary, so a timer that fires early still reads the new boundary.
    timer = env.setTimeout(fire, msToNextBoundary(env.now(), every) + 5);
  };
  function fire() {
    timer = null;
    const at = boundaryAt(env.now(), every);
    const hidden = env.hidden();
    for (const s of [...subs]) {
      if (!subs.has(s) || s.had >= at) continue;
      if (hidden && !runsHidden(s)) continue;
      s.had = at;
      s.fn();
    }
    arm();
  }
  const onVisibility = () => {
    if (!env.hidden()) {
      const at = boundaryAt(env.now(), every);
      for (const s of [...subs]) {
        if (!subs.has(s) || s.had >= at) continue;
        s.had = at;
        if (s.options.catchUp) s.fn();
      }
    }
    arm();
  };

  return {
    subscribe(fn, options = {}) {
      const s: Subscriber = { fn, options, had: boundaryAt(env.now(), every) };
      subs.add(s);
      if (!stopVisibility) stopVisibility = env.onVisibility(onVisibility);
      if (timer === null) arm();
      return () => {
        subs.delete(s);
        if (subs.size === 0) {
          disarm();
          stopVisibility?.();
          stopVisibility = null;
        }
      };
    },
    size: () => subs.size,
    armed: () => timer !== null,
  };
}

let shared: SharedTick | null = null;

/** The page's one tick. */
export function sharedTick(): SharedTick {
  shared ??= createSharedTick(browserTickEnv());
  return shared;
}

/** `fn` on the page's shared 5-minute boundaries; answers the unsubscribe. */
export function onSharedTick(fn: () => void, options?: TickOptions): () => void {
  return sharedTick().subscribe(fn, options);
}
