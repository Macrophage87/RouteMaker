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

/** Register the protocol, once per page. */
export function registerStressProtocol(host: ProtocolHost, get?: typeof fetch): void {
  if (registered) return;
  host.addProtocol(STRESS_PROTOCOL, async (params, abort) => ({
    data: await fetchTile(httpUrl(params.url), { get, signal: abort.signal }),
  }));
  registered = true;
}
