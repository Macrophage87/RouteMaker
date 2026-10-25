/**
 * Go's first route, then a better one (v0.7.0, "Faster routing", steps 2 and 4).
 *
 * Step 2: Go asks for the first good route (`quick`: the router's own route with its closures, stress and words),
 * shows it at once, and the full plan follows it (lib/routeScheduler.ts `refine`). Where the full plan is a
 * different route, Go swaps it in before Start, never mid-ride, with one line said once ("Found a calmer route,
 * +2 min"; `betterRouteSaid`); the focus stays where it is. Where it is the same route, it is swapped in silently
 * (it carries what the first route left out: the calm search's figures, the candidates, the detour check).
 *
 * Step 4: Go starts routing before the tap (`EarlyStart`): to the top search result while the rider is still
 * looking at it, and to Home when Go opens with Home set. The tap then finds the request already made, and
 * waits for it rather than asking again; a finished one is answered by the API's short-term cache (a second ask
 * of the same request, src/core/route_cache.py).
 */
import type { RouteResponse, RouteResult } from "./api.ts";

/** Busy riding (LTS 3, 4 and Avoid) on a route, metres. */
function busyM(route: Pick<RouteResponse, "stress_m">): number {
  const s = route.stress_m;
  return (s["3"] ?? 0) + (s["4"] ?? 0) + (s["5"] ?? 0);
}

/** Less busy riding than this is not "calmer" (about a block). */
export const CALMER_BY_M = 80;
/** Less riding time than this is not "quicker". */
export const QUICKER_BY_S = 30;

/** Whether two answers are the same route on the map: the same line, to the metre. */
export function sameRoute(a: Pick<RouteResponse, "geometry" | "distance_m">, b: Pick<RouteResponse, "geometry" | "distance_m">): boolean {
  if (Math.abs(a.distance_m - b.distance_m) > 1) return false;
  const p = a.geometry.coordinates;
  const q = b.geometry.coordinates;
  if (p.length !== q.length) return false;
  for (let i = 0; i < p.length; i += 1) {
    if (p[i][0] !== q[i][0] || p[i][1] !== q[i][1]) return false;
  }
  return true;
}

/** The time a swap adds or saves, in whole minutes: "+2 min", "2 min less", or "" under a minute. */
function minutesSaid(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  if (minutes >= 1) return `, +${minutes} min`;
  if (minutes <= -1) return `, ${-minutes} min less`;
  return "";
}

/**
 * The one line said when the full plan replaces Go's first route, or null where it is the same route (swapped
 * in silently). Calmer first (what the search is for), then quicker, else "a better route".
 */
export function betterRouteSaid(
  first: Pick<RouteResponse, "geometry" | "distance_m" | "duration_s" | "stress_m">,
  full: Pick<RouteResponse, "geometry" | "distance_m" | "duration_s" | "stress_m">,
): string | null {
  if (sameRoute(first, full)) return null;
  const extra = minutesSaid(full.duration_s - first.duration_s);
  if (busyM(full) <= busyM(first) - CALMER_BY_M) return `Found a calmer route${extra}.`;
  if (full.duration_s <= first.duration_s - QUICKER_BY_S) return `Found a quicker route${extra}.`;
  return `Found a better route${extra}.`;
}

/**
 * Whether a full plan may replace the route shown: only for a first route (`provisional`), and only before Start
 * (no ride on): "never mid-ride without asking".
 */
export function takesRefined(shown: Pick<RouteResponse, "provisional"> | null, riding: boolean): boolean {
  return shown?.provisional === true && !riding;
}

export interface EarlyStartOptions {
  /** Whether a request may go now: Go shown, no ride, and no other route request of Go's in flight. */
  allowed: () => boolean;
  /** Milliseconds a request made early is kept for its tap (the API keeps its answer longer). */
  keepMs?: number;
  /** At most this many early requests a minute, inside the API's 60 a minute. */
  perMinute?: number;
  now?: () => number;
}

export const EARLY_KEEP_MS = 60_000;
export const EARLY_PER_MINUTE = 6;

/**
 * Go's early start (step 4): one request at a time, made before the tap, kept by its request body for the tap
 * that would make the same request. Never aborted (an abort frees no slot in the API); a request not tapped is
 * left to finish, and its answer waits in the API's cache.
 */
export class EarlyStart {
  private readonly options: EarlyStartOptions;
  private kept: { body: string; at: number; answer: Promise<RouteResult> } | null = null;
  private inFlight = false;
  private sent: number[] = [];

  constructor(options: EarlyStartOptions) {
    this.options = options;
  }

  /**
   * Start the request whose body is `body` early (`send` makes it: the API's first route, `quick`), if it may go:
   * none in flight, under the per-minute cap, not kept already.
   */
  start(body: string, send: () => Promise<RouteResult>): boolean {
    const now = (this.options.now ?? Date.now)();
    if (this.inFlight || !this.options.allowed()) return false;
    if (this.kept && this.kept.body === body && now - this.kept.at < (this.options.keepMs ?? EARLY_KEEP_MS)) return false;
    this.sent = this.sent.filter((t) => now - t < 60_000);
    if (this.sent.length >= (this.options.perMinute ?? EARLY_PER_MINUTE)) return false;
    this.sent.push(now);
    this.inFlight = true;
    const answer = send().then(
      (result) => {
        this.inFlight = false;
        return result;
      },
      (error: unknown) => {
        this.inFlight = false;
        throw error;
      },
    );
    // Nothing waits on an early request that is never tapped: its failure is not an error of the page's.
    answer.catch(() => undefined);
    this.kept = { body, at: now, answer };
    return true;
  }

  /** The early request for `body`, taken (once), while it is fresh; null where there is none. */
  take(body: string): Promise<RouteResult> | null {
    const kept = this.kept;
    const now = (this.options.now ?? Date.now)();
    if (!kept || kept.body !== body || now - kept.at >= (this.options.keepMs ?? EARLY_KEEP_MS)) return null;
    this.kept = null;
    return kept.answer;
  }

  /** Whether an early request is in flight (the scheduler's own request waits for no slot it would share). */
  busy(): boolean {
    return this.inFlight;
  }
}
