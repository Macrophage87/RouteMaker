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
import { METRES_PER_MILE, formatDistanceChange, formatMilesChange } from "./format.ts";
import { t } from "./i18n.ts";

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

/** Less climbing than this is not "flatter": 20 ft, or a tenth of the climb before, whichever is more. */
export const FLATTER_BY_M = 6;

type Compared = Pick<RouteResponse, "geometry" | "distance_m" | "duration_s" | "stress_m" | "climb_m">;

/**
 * The toast after the rider changes Go's ride settings or ride type (P3): what the new plan changed against the route
 * shown before the change, not against Go's own first route (`betterRouteSaid`, which said "Found a quicker route"
 * here). Flatter or hillier, calmer or busier where it is, then the time it adds or saves, else the distance:
 * "Re-planned: flatter, 3 min less." On screen the distance is in miles; said, with its kilometres too. With a new
 * ride type (`ride`, its name) the line names it: "Re-planned for Mass Ride: 2 min more."
 */
export function replannedSaid(before: Compared, after: Compared, ride: string | null = null): { shown: string; said: string } {
  const head = (change: string) => (ride ? t("Re-planned for {ride}: {change}.", { ride, change }) : t("Re-planned: {change}.", { change }));
  if (sameRoute(before, after)) {
    const same = t("the same route");
    return { shown: head(same), said: head(same) };
  }
  const words: string[] = [];
  const climb = after.climb_m - before.climb_m;
  const climbBy = Math.max(FLATTER_BY_M, before.climb_m / 10);
  if (climb <= -climbBy) words.push(t("flatter"));
  else if (climb >= climbBy) words.push(t("hillier"));
  const busy = busyM(after) - busyM(before);
  if (busy <= -CALMER_BY_M) words.push(t("calmer"));
  else if (busy >= CALMER_BY_M) words.push(t("busier"));
  const minutes = Math.round((after.duration_s - before.duration_s) / 60);
  const moved = after.distance_m - before.distance_m;
  let shownLast = "";
  let saidLast = "";
  if (minutes !== 0) {
    shownLast = minutes > 0 ? t("{minutes} min more", { minutes }) : t("{minutes} min less", { minutes: -minutes });
    saidLast = shownLast;
  } else if (Math.abs(moved) >= METRES_PER_MILE / 20) {
    const more = moved > 0;
    shownLast = more ? t("{distance} more", { distance: formatMilesChange(moved) }) : t("{distance} less", { distance: formatMilesChange(moved) });
    saidLast = more ? t("{distance} more", { distance: formatDistanceChange(moved) }) : t("{distance} less", { distance: formatDistanceChange(moved) });
  } else {
    shownLast = t("about the same time");
    saidLast = shownLast;
  }
  return { shown: head([...words, shownLast].join(", ")), said: head([...words, saidLast].join(", ")) };
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
 * left to finish, and its answer waits in the API's cache. One asked for while another is in flight waits as
 * `next`, the latest only, and goes when that one settles if it still may (routing audit S4: the rider typed on
 * past the first result, "Union Market" on the way to "Union Station").
 */
export class EarlyStart {
  private readonly options: EarlyStartOptions;
  private kept: { body: string; at: number; answer: Promise<RouteResult> } | null = null;
  private inFlight = false;
  private next: { body: string; send: () => Promise<RouteResult> } | null = null;
  private sent: number[] = [];

  constructor(options: EarlyStartOptions) {
    this.options = options;
  }

  /**
   * Start the request whose body is `body` early (`send` makes it: the API's first route, `quick`), if it may go:
   * none in flight, under the per-minute cap, not kept already. With one in flight it waits as `next` (false).
   */
  start(body: string, send: () => Promise<RouteResult>): boolean {
    const now = (this.options.now ?? Date.now)();
    if (!this.options.allowed()) return false;
    if (this.kept && this.kept.body === body && now - this.kept.at < (this.options.keepMs ?? EARLY_KEEP_MS)) {
      // Back to the place already asked for: nothing newer waits.
      this.next = null;
      return false;
    }
    if (this.inFlight) {
      this.next = { body, send };
      return false;
    }
    this.sent = this.sent.filter((t) => now - t < 60_000);
    if (this.sent.length >= (this.options.perMinute ?? EARLY_PER_MINUTE)) return false;
    this.sent.push(now);
    this.inFlight = true;
    const answer = send().then(
      (result) => {
        this.settled();
        return result;
      },
      (error: unknown) => {
        this.settled();
        throw error;
      },
    );
    // Nothing waits on an early request that is never tapped: its failure is not an error of the page's.
    answer.catch(() => undefined);
    this.kept = { body, at: now, answer };
    return true;
  }

  /** The one in flight is done: the place wanted since goes now, if it still may (`start` asks again). */
  private settled(): void {
    this.inFlight = false;
    const next = this.next;
    this.next = null;
    if (!next) return;
    try {
      this.start(next.body, next.send);
    } catch {
      // A request that cannot be made early is made by the tap; the answer settling here is not touched.
    }
  }

  /** Nothing waits to go next: the place it was for is no longer offered (the box cleared, no results). */
  forget(): void {
    this.next = null;
  }

  /** The early request for `body`, taken (once), while it is fresh; null where there is none. */
  take(body: string): Promise<RouteResult> | null {
    // The tap makes its own request: one waiting for the same place would ask twice, and one waiting for another place
    // is for a place not chosen (batch-1 review of S4), so either way the wait goes.
    this.next = null;
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
