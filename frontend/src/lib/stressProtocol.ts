/**
 * How the map fetches the stress tiles: through a MapLibre protocol of its
 * own, so that a tile the API asks to be fetched again is fetched again.
 *
 * The API draws a tile that is not in its cache under an in-flight cap, and
 * answers 429 or 503 with Retry-After when the cap is full or the draw ran out
 * of time (core/stress_tiles.py). MapLibre's own loader leaves such a tile
 * blank until the map moves; this one waits out the Retry-After, a little
 * jittered so a screenful does not come back at once, and asks again, a few
 * times. Anything else that is not a 200 fails the tile as before.
 *
 * MapLibre 4+ runs a custom protocol's loader on the page's own thread, so the
 * request is the page's: same origin, with its Referer, and the browser's HTTP
 * cache (an hour, then a 304) works as it did.
 */

export const STRESS_PROTOCOL = "rmstress";

/** How many times a tile is asked for in all, and the longest wait between. */
export const MAX_ATTEMPTS = 5;
export const MAX_WAIT_S = 5;
const JITTER_MS = 250;

export function protocolUrl(url: string): string {
  return `${STRESS_PROTOCOL}://${url}`;
}

export function httpUrl(url: string): string {
  const prefix = `${STRESS_PROTOCOL}://`;
  return url.startsWith(prefix) ? url.slice(prefix.length) : url;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(new DOMException("aborted", "AbortError"));
    });
  });
}

/** Seconds to wait before asking again, from a Retry-After of seconds. */
export function retryAfterS(header: string | null): number {
  const seconds = Number(header);
  if (!Number.isFinite(seconds) || seconds < 0 || header === null || header.trim() === "") return 1;
  return Math.min(seconds, MAX_WAIT_S);
}

export interface Fetching {
  get?: typeof fetch;
  wait?: (ms: number, signal?: AbortSignal) => Promise<void>;
  jitter?: () => number;
  signal?: AbortSignal;
}

/** The tile's bytes, asking again after a 429 or 503 as the API says. */
export async function fetchTile(url: string, options: Fetching = {}): Promise<ArrayBuffer> {
  const get = options.get ?? fetch;
  const wait = options.wait ?? sleep;
  const jitter = options.jitter ?? (() => Math.random() * JITTER_MS);
  for (let attempt = 1; ; attempt += 1) {
    const response = await get(url, { signal: options.signal });
    if (response.ok) return response.arrayBuffer();
    const again = response.status === 429 || response.status === 503;
    if (!again || attempt >= MAX_ATTEMPTS) {
      throw new Error(`stress tile ${response.status}`);
    }
    await wait(retryAfterS(response.headers.get("Retry-After")) * 1000 + jitter(), options.signal);
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
