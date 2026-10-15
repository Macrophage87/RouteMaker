/**
 * How the map fetches the stress tiles: through a MapLibre protocol of its
 * own, so that a tile the API asks to be fetched again is fetched again, and so
 * that one page does not ask for more than the API will draw for it.
 *
 * The API draws a tile that is not in its cache under an in-flight cap - one
 * draw at a time in the whole deployment at compose's five workers - and
 * answers 429 or 503 with Retry-After when the cap is full or the draw ran out
 * of time (core/stress_tiles.py). Two things follow here:
 *
 * - A queue: at most MAX_IN_FLIGHT tile requests from this page at once. A
 *   screenful of cached tiles still comes quickly (a hit is a lookup), and a
 *   screenful of misses is not sent all at once only to be refused all at once.
 * - Backoff: a refused tile waits the longer of its Retry-After and 1, 2, 4, 8,
 *   8... seconds, each stretched by a random 0.5-1.5, so the refused tiles of a
 *   screen spread out rather than coming back together; it gives up after
 *   GIVE_UP_S (or MAX_ATTEMPTS), and MapLibre shows the parent tile there.
 *   Round 2's five tries a second apart left 2-7 tiles of a cold z14 screen
 *   undelivered (reviews of 2026-09-28).
 *
 * A server that is down (a 502 or 504 from the proxy in front of it, or a
 * request that fails outright, as during a restart) is waited out the same
 * way as a 503, unless the caller says not to (`retryDown`: the availability
 * check, which has its own recheck, and a ride, which has its kept tiles).
 * A tile that still fails is drawn again when the check finds the endpoint
 * back (stressProbe's `reload`).
 *
 * Anything else that is not a 200 fails the tile at once. A tile MapLibre
 * cancels leaves the queue and stops waiting. MapLibre 4+ runs a custom
 * protocol's loader on the page's own thread, so the request is the page's:
 * same origin, with its Referer, and the browser's HTTP cache (an hour, then a
 * 304) works as it did.
 */

import { lonLatToTile, type LonLat } from "./geo.ts";

export const STRESS_PROTOCOL = "rmstress";

export const MAX_IN_FLIGHT = 2;
export const MAX_ATTEMPTS = 10;
export const MAX_WAIT_S = 8;
export const GIVE_UP_S = 30;

export function protocolUrl(url: string): string {
  return `${STRESS_PROTOCOL}://${url}`;
}

export function httpUrl(url: string): string {
  const prefix = `${STRESS_PROTOCOL}://`;
  return url.startsWith(prefix) ? url.slice(prefix.length) : url;
}

function aborted(): DOMException {
  return new DOMException("aborted", "AbortError");
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(aborted());
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(aborted());
    });
  });
}

/** At most `size` holders at once; the rest wait in order. */
export class Queue {
  readonly size: number;
  private holders = 0;
  private waiting: Array<{ go: () => void }> = [];

  constructor(size: number) {
    this.size = size;
  }

  get inFlight(): number {
    return this.holders;
  }

  acquire(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) return Promise.reject(aborted());
    if (this.holders < this.size) {
      this.holders += 1;
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const entry = { go: () => resolve() };
      this.waiting.push(entry);
      signal?.addEventListener("abort", () => {
        const at = this.waiting.indexOf(entry);
        if (at >= 0) {
          this.waiting.splice(at, 1);
          reject(aborted());
        }
      });
    });
  }

  release(): void {
    const next = this.waiting.shift();
    if (next) next.go();
    else this.holders -= 1;
  }
}

const PAGE_QUEUE = new Queue(MAX_IN_FLIGHT);

/** Seconds the API asked for, from a Retry-After of seconds; 1 if it gave none. */
export function retryAfterS(header: string | null): number {
  const seconds = Number(header);
  if (!Number.isFinite(seconds) || seconds < 0 || header === null || header.trim() === "") return 1;
  return Math.min(seconds, MAX_WAIT_S);
}

/** How long to wait after the `refusals`-th refusal (1-based), in ms. */
export function backoffMs(refusals: number, retryAfter: number, random: () => number): number {
  const base = Math.min(MAX_WAIT_S, 2 ** (refusals - 1));
  return Math.max(retryAfter, base) * 1000 * (0.5 + random());
}

/**
 * Whether a tile is asked for again: after a 429 or 503 always, and after a
 * 502, a 504 or a request that failed outright (`status` null) when
 * `retryDown` - the server was down or restarting.
 */
export function retryable(status: number | null, retryDown: boolean): boolean {
  if (status === 429 || status === 503) return true;
  return retryDown && (status === null || status === 502 || status === 504);
}

export interface Fetching {
  get?: typeof fetch;
  /** Wait out a server that is down (502, 504, a failed request) like a 503; true unless said. */
  retryDown?: boolean;
  wait?: (ms: number, signal?: AbortSignal) => Promise<void>;
  random?: () => number;
  now?: () => number;
  queue?: Queue;
  signal?: AbortSignal;
}

/** The tile's bytes, queued, and asked for again after a 429 or 503 (and, with `retryDown`, a 502, 504 or failed request). */
export async function fetchTile(url: string, options: Fetching = {}): Promise<ArrayBuffer> {
  const get = options.get ?? fetch;
  const wait = options.wait ?? sleep;
  const random = options.random ?? Math.random;
  const now = options.now ?? Date.now;
  const queue = options.queue ?? PAGE_QUEUE;
  const retryDown = options.retryDown ?? true;
  const started = now();
  for (let attempt = 1; ; attempt += 1) {
    await queue.acquire(options.signal);
    let status: number | null;
    let retryAfter: string | null = null;
    let failure: unknown = null;
    try {
      const response = await get(url, { signal: options.signal });
      if (response.ok) return await response.arrayBuffer();
      status = response.status;
      retryAfter = response.headers.get("Retry-After");
    } catch (error) {
      // A cancelled tile is not asked again; a request that failed outright is a server that is down.
      if (options.signal?.aborted) throw error;
      status = null;
      failure = error;
    } finally {
      queue.release();
    }
    const what = status ?? "request failed";
    if (!retryable(status, retryDown) || attempt >= MAX_ATTEMPTS) {
      if (failure !== null) throw failure;
      throw new Error(`stress tile ${what}`);
    }
    const delay = backoffMs(attempt, retryAfterS(retryAfter), random);
    if (now() - started + delay > GIVE_UP_S * 1000) throw new Error(`stress tile ${what}, gave up`);
    await wait(delay, options.signal);
  }
}

type Loader = (params: { url: string }, abort: AbortController) => Promise<{ data: ArrayBuffer }>;

/** The part of maplibregl this uses. */
export interface ProtocolHost {
  addProtocol(name: string, loader: Loader): void;
}

let registered = false;

/**
 * Ride mode's kept tiles (lib/corridorStore.ts; WEB-NAV-plan.md section 6). During a ride the kept tile
 * is read first (in a real dead spot the phone still says it is online, and a request can hang rather
 * than fail), and the network gets NETWORK_TIMEOUT_MS before the kept tiles are tried again with any
 * edit generation. Outside a ride nothing is kept, so the kept tiles answer nothing (`kept` gives null).
 */
export interface OfflineTiles {
  /** Whether a ride is keeping tiles now. */
  riding(): boolean;
  /** A kept tile of this URL's own edit generation (`?rev=`), or with `anyRev` of any. */
  kept(url: string, anyRev?: boolean): Promise<ArrayBuffer | null>;
  /** Keep a tile the map loaded; whether it was kept. */
  keep(url: string, data: ArrayBuffer): Promise<boolean>;
}

/** How long a ride's tile request may take before the kept tiles answer (a hung request in a dead spot): above
 * the 5.46 s a cold draw on a busy host once took (docs/OPERATIONS.md), so a slow draw is not cut off. */
export const NETWORK_TIMEOUT_MS = 6000;

function offlineNow(): boolean {
  return typeof navigator !== "undefined" && navigator.onLine === false;
}

/**
 * `get` with each request aborted after `ms`. The timer is left to run out rather than cleared at the
 * headers, so a body that stalls is cut too; aborting a finished request does nothing.
 */
export function withTimeout(get: typeof fetch, ms: number): typeof fetch {
  return ((input: RequestInfo | URL, init?: RequestInit) => {
    const controller = new AbortController();
    const outer = init?.signal;
    if (outer?.aborted) controller.abort();
    else outer?.addEventListener("abort", () => controller.abort(), { once: true });
    setTimeout(() => controller.abort(), ms);
    return get(input, { ...init, signal: controller.signal });
  }) as typeof fetch;
}

/** One tile through the protocol: the network, and with `offline` the ride's kept tiles around it. */
export async function loadTile(
  url: string,
  signal: AbortSignal,
  get?: typeof fetch,
  offline?: OfflineTiles,
  timeoutMs = NETWORK_TIMEOUT_MS,
): Promise<ArrayBuffer> {
  const riding = offline?.riding() ?? false;
  if (offline && (riding || offlineNow())) {
    const kept = await offline.kept(url);
    if (kept) return kept;
  }
  try {
    // A ride falls back to its kept tiles at once rather than waiting out a server that is down.
    const data = await fetchTile(url, {
      get: riding ? withTimeout(get ?? ((i, o) => fetch(i, o)), timeoutMs) : get,
      signal,
      retryDown: !riding,
    });
    if (riding) void offline?.keep(url, data);
    return data;
  } catch (error) {
    if (!offline || signal.aborted) throw error;
    const kept = await offline.kept(url, true);
    if (kept) return kept;
    throw error;
  }
}

/**
 * Register the protocol, once per page. With `offline`, a tile the network fails to give (or any, while
 * the browser says it is offline) is looked for among the ride's kept tiles before it fails.
 */
export function registerStressProtocol(host: ProtocolHost, get?: typeof fetch, offline?: OfflineTiles): void {
  if (registered) return;
  host.addProtocol(STRESS_PROTOCOL, async (params, abort) => ({
    data: await loadTile(httpUrl(params.url), abort.signal, get, offline),
  }));
  registered = true;
}

/** The tile the availability check asks for: central DC at z12. */
export const PROBE_CENTRE: LonLat = [-77.03, 38.9];

/**
 * Whether the stress tiles answer, for MapView's check at load. One tile over
 * central DC at a zoom the contract serves. A 404 means the endpoint is not
 * deployed, a 502 that the API is down: either way the map shows without the
 * overlay rather than with a legend for nothing. It goes through `fetchTile`,
 * so a 429 or 503 - the tile's draw refused a slot before the pre-draw has run
 * - is waited out like any tile's; a server that is down is not (`retryDown`
 * false), since the check asks again on its own.
 */
export async function stressTilesAnswer(origin: string, options: Fetching = {}): Promise<boolean> {
  const { x, y, z } = lonLatToTile(PROBE_CENTRE, 12);
  try {
    await fetchTile(`${origin}/tiles/stress/${z}/${x}/${y}.pbf`, { retryDown: false, ...options });
    return true;
  } catch {
    return false;
  }
}

export type StressAvailability = "available" | "unavailable";

export interface StressProbeDeps {
  /** Put the overlay on the map (once: MapView's addStressOverlay does nothing the second time). */
  add(): void;
  report(availability: StressAvailability): void;
  /**
   * Ask for the overlay's tiles again: after a tile failed (`later`), once the endpoint answers again,
   * so a tile that failed while the server was down is drawn rather than left blank.
   */
  reload?(): void;
  /** Whether the map has gone; an answer that comes after is dropped. */
  disposed(): boolean;
  /** How the endpoint is asked; `stressTilesAnswer` unless a test says otherwise. */
  answer?: (origin: string) => Promise<boolean>;
  setTimer?: (run: () => void, ms: number) => unknown;
  clearTimer?: (timer: unknown) => void;
  now?: () => number;
}

/**
 * MapView's check of the stress tiles: ask the endpoint; if it answers, put
 * the overlay on; if not, say so and ask again after `recheckMs`, so one bad
 * minute does not take the overlay away for the whole visit. `later` asks
 * again after `ms` unless a check is already waiting (a tile that failed
 * after the endpoint had answered); `cancel` drops the waiting one. A tile
 * failure is remembered until a check finds the endpoint answering, and then
 * the overlay's tiles are asked for again (`reload`, see `reloadAfterCheck`),
 * at most once per `recheckMs`: a tile that keeps failing while the endpoint
 * answers is asked for again then, not after every check.
 */
export function stressProbe(origin: string, recheckMs: number, deps: StressProbeDeps) {
  const answer = deps.answer ?? ((o: string) => stressTilesAnswer(o));
  const setTimer = deps.setTimer ?? ((run: () => void, ms: number) => setTimeout(run, ms));
  const clearTimer = deps.clearTimer ?? ((timer: unknown) => clearTimeout(timer as ReturnType<typeof setTimeout>));
  let waiting: unknown = null;
  const now = deps.now ?? Date.now;
  let tileFailed = false;
  let reloadedAt = -Infinity;

  const schedule = (ms: number) => {
    if (waiting !== null) return;
    waiting = setTimer(() => {
      waiting = null;
      void probe();
    }, ms);
  };

  async function probe(): Promise<void> {
    const available = await answer(origin);
    if (deps.disposed()) return;
    if (available) {
      deps.add();
      const decision = reloadAfterCheck(available, tileFailed, now() - reloadedAt, recheckMs);
      if (decision === "reload") {
        tileFailed = false;
        reloadedAt = now();
        deps.reload?.();
      } else if (decision === "wait") {
        schedule(recheckMs - (now() - reloadedAt));
      }
      deps.report("available");
    } else {
      deps.report("unavailable");
      schedule(recheckMs);
    }
  }

  return {
    probe,
    /** A tile failed: check again after `ms`, and draw the tiles again if the endpoint answers. */
    later(ms: number) {
      tileFailed = true;
      schedule(ms);
    },
    cancel() {
      if (waiting !== null) clearTimer(waiting);
      waiting = null;
    },
  };
}

/**
 * What a check's answer does about the overlay's tiles: "reload" them when the endpoint answers and a
 * tile had failed, unless they were reloaded less than `gapMs` ago - then "wait" and check again when
 * the gap is up; otherwise nothing ("none").
 */
export function reloadAfterCheck(
  available: boolean,
  tileFailed: boolean,
  msSinceReload: number,
  gapMs: number,
): "reload" | "wait" | "none" {
  if (!available || !tileFailed) return "none";
  return msSinceReload >= gapMs ? "reload" : "wait";
}
