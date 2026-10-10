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

export interface Fetching {
  get?: typeof fetch;
  wait?: (ms: number, signal?: AbortSignal) => Promise<void>;
  random?: () => number;
  now?: () => number;
  queue?: Queue;
  signal?: AbortSignal;
}

/** The tile's bytes, queued, and asked for again after a 429 or 503. */
export async function fetchTile(url: string, options: Fetching = {}): Promise<ArrayBuffer> {
  const get = options.get ?? fetch;
  const wait = options.wait ?? sleep;
  const random = options.random ?? Math.random;
  const now = options.now ?? Date.now;
  const queue = options.queue ?? PAGE_QUEUE;
  const started = now();
  for (let attempt = 1; ; attempt += 1) {
    await queue.acquire(options.signal);
    let status: number;
    let retryAfter: string | null;
    try {
      const response = await get(url, { signal: options.signal });
      if (response.ok) return await response.arrayBuffer();
      status = response.status;
      retryAfter = response.headers.get("Retry-After");
    } finally {
      queue.release();
    }
    const again = status === 429 || status === 503;
    if (!again || attempt >= MAX_ATTEMPTS) throw new Error(`stress tile ${status}`);
    const delay = backoffMs(attempt, retryAfterS(retryAfter), random);
    if (now() - started + delay > GIVE_UP_S * 1000) throw new Error(`stress tile ${status}, gave up`);
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
    const data = await fetchTile(url, { get: riding ? withTimeout(get ?? ((i, o) => fetch(i, o)), timeoutMs) : get, signal });
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
 * - is waited out like any tile's.
 */
export async function stressTilesAnswer(origin: string, options: Fetching = {}): Promise<boolean> {
  const { x, y, z } = lonLatToTile(PROBE_CENTRE, 12);
  try {
    await fetchTile(`${origin}/tiles/stress/${z}/${x}/${y}.pbf`, options);
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
  /** Whether the map has gone; an answer that comes after is dropped. */
  disposed(): boolean;
  /** How the endpoint is asked; `stressTilesAnswer` unless a test says otherwise. */
  answer?: (origin: string) => Promise<boolean>;
  setTimer?: (run: () => void, ms: number) => unknown;
  clearTimer?: (timer: unknown) => void;
}

/**
 * MapView's check of the stress tiles: ask the endpoint; if it answers, put
 * the overlay on; if not, say so and ask again after `recheckMs`, so one bad
 * minute does not take the overlay away for the whole visit. `later` asks
 * again after `ms` unless a check is already waiting (a tile that failed
 * after the endpoint had answered); `cancel` drops the waiting one.
 */
export function stressProbe(origin: string, recheckMs: number, deps: StressProbeDeps) {
  const answer = deps.answer ?? ((o: string) => stressTilesAnswer(o));
  const setTimer = deps.setTimer ?? ((run: () => void, ms: number) => setTimeout(run, ms));
  const clearTimer = deps.clearTimer ?? ((timer: unknown) => clearTimeout(timer as ReturnType<typeof setTimeout>));
  let waiting: unknown = null;

  const later = (ms: number) => {
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
      deps.report("available");
    } else {
      deps.report("unavailable");
      later(recheckMs);
    }
  }

  return {
    probe,
    later,
    cancel() {
      if (waiting !== null) clearTimer(waiting);
      waiting = null;
    },
  };
}
