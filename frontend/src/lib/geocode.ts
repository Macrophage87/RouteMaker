/**
 * Place search and place names: GET /api/geocode and GET /api/reverse.
 *
 * Both go to this site's own API, which proxies the self-hosted Photon
 * (src/core/geocode.py); nothing here talks to any other host, so the page's
 * Content-Security-Policy needs no change. Neither needs a sign-in (owner
 * decision of 2026-09-27).
 *
 * The API gives each client one geocoding request at a time
 * (core.ratelimit.GEOCODE_IN_FLIGHT, shared by search and names), and an
 * abandoned fetch does not free that slot any sooner, so every request from
 * this page goes through one `GeoGate`: one in flight, search ahead of names.
 */
import { MAX_POINTS, addPoint, type LonLat } from "./geo.ts";
import { parseRetryAfter } from "./api.ts";

export interface Place {
  name: string;
  label: string;
  lon: number;
  lat: number;
  kind: string;
}

export type GeoResult =
  | { ok: true; places: Place[]; attribution: string[] }
  | { ok: false; status: number; retryAfterS?: number };

/** Fewer characters than this match half the region; the box waits for more. */
export const MIN_QUERY_CHARS = 3;
/** The API's own ceiling, so a longer paste is cut rather than refused. */
export const MAX_QUERY_CHARS = 200;
export const SEARCH_RESULTS = 6;
/** Typing pauses this long before a search is sent. */
export const SEARCH_DEBOUNCE_MS = 250;
/** Points that change settle this long before they are named. */
export const NAME_DEBOUNCE_MS = 400;
/** A busy answer is retried once, after its Retry-After but never later than this. */
export const RETRY_CAP_MS = 1500;

export function searchUrl(query: string, bias?: LonLat, limit: number = SEARCH_RESULTS): string {
  const params = new URLSearchParams({ q: query.slice(0, MAX_QUERY_CHARS), limit: String(limit) });
  if (bias) {
    params.set("lat", bias[1].toFixed(5));
    params.set("lon", bias[0].toFixed(5));
  }
  return `/api/geocode?${params.toString()}`;
}

export function reverseUrl(point: LonLat): string {
  const params = new URLSearchParams({ lat: point[1].toFixed(6), lon: point[0].toFixed(6) });
  return `/api/reverse?${params.toString()}`;
}

function isPlace(value: unknown): value is Place {
  if (!value || typeof value !== "object") return false;
  const p = value as Partial<Place>;
  return (
    typeof p.name === "string" &&
    p.name.length > 0 &&
    typeof p.label === "string" &&
    typeof p.lon === "number" &&
    Number.isFinite(p.lon) &&
    typeof p.lat === "number" &&
    Number.isFinite(p.lat)
  );
}

type FetchLike = (url: string, init: RequestInit) => Promise<Response>;

export async function fetchPlaces(url: string, fetchImpl?: FetchLike): Promise<GeoResult> {
  const doFetch: FetchLike = fetchImpl ?? ((u, init) => fetch(u, init));
  let response: Response;
  try {
    response = await doFetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
  } catch {
    return { ok: false, status: 0 };
  }
  if (!response.ok) {
    const retryAfterS = parseRetryAfter(response.headers.get("Retry-After"));
    return { ok: false, status: response.status, ...(retryAfterS === undefined ? {} : { retryAfterS }) };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { ok: false, status: 500 };
  }
  const b = body as { results?: unknown; attribution?: unknown } | null;
  if (!b || !Array.isArray(b.results)) return { ok: false, status: 500 };
  return {
    ok: true,
    places: b.results.filter(isPlace).map((p) => ({ ...p, kind: typeof p.kind === "string" ? p.kind : "other" })),
    attribution: Array.isArray(b.attribution) ? b.attribution.filter((a): a is string => typeof a === "string") : [],
  };
}

/** One geocoding request at a time for the page; `urgent` ones (search) go first. */
export class GeoGate {
  private busy = false;
  private queue: Array<{ urgent: boolean; start: () => void }> = [];

  run<T>(task: () => Promise<T>, urgent = false): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const start = () => {
        this.busy = true;
        task()
          .then(resolve, reject)
          .finally(() => {
            this.busy = false;
            this.next();
          });
      };
      if (urgent) {
        const firstCalm = this.queue.findIndex((q) => !q.urgent);
        this.queue.splice(firstCalm === -1 ? this.queue.length : firstCalm, 0, { urgent, start });
      } else {
        this.queue.push({ urgent, start });
      }
      if (!this.busy) this.next();
    });
  }

  get idle(): boolean {
    return !this.busy && this.queue.length === 0;
  }

  private next() {
    if (this.busy) return;
    const job = this.queue.shift();
    if (job) job.start();
  }
}

export interface Timers {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
}

export const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

function busy(result: GeoResult): boolean {
  return !result.ok && (result.status === 429 || result.status === 503);
}

function retryDelayMs(result: GeoResult): number {
  const s = result.ok ? undefined : result.retryAfterS;
  return Math.min(RETRY_CAP_MS, Math.max(250, (s ?? 1) * 1000));
}

/**
 * The typeahead's requests: debounced, one in flight, only the latest query
 * answered. A query typed while another is in flight waits for it and is sent
 * next; anything typed in between is never sent. A busy answer (429, 503) is
 * retried once for the latest query.
 */
export class PlaceSearchRunner {
  private timer: unknown = null;
  private inFlight = false;
  private wanted: string | null = null;
  private sentFor: string | null = null;
  private retried = false;

  private readonly options: {
    send: (query: string) => Promise<GeoResult>;
    onResult: (query: string, result: GeoResult) => void;
    timers?: Timers;
    debounceMs?: number;
  };

  constructor(options: PlaceSearchRunner["options"]) {
    this.options = options;
  }

  private get timers(): Timers {
    return this.options.timers ?? realTimers;
  }

  /** Ask for `query`'s places; an empty or too-short one clears instead. */
  request(query: string) {
    const q = query.trim().replace(/\s+/g, " ");
    this.cancelTimer();
    if (q.length < MIN_QUERY_CHARS) {
      this.wanted = null;
      return;
    }
    this.wanted = q;
    this.retried = false;
    this.timer = this.timers.set(() => {
      this.timer = null;
      this.pump();
    }, this.options.debounceMs ?? SEARCH_DEBOUNCE_MS);
  }

  clear() {
    this.cancelTimer();
    this.wanted = null;
  }

  private cancelTimer() {
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }

  private pump() {
    if (this.inFlight || this.wanted === null || this.wanted === this.sentFor) return;
    const q = this.wanted;
    this.inFlight = true;
    this.sentFor = q;
    this.options.send(q).then((result) => {
      this.inFlight = false;
      if (this.wanted !== q) {
        // Superseded while in flight: send the latest instead, show nothing.
        this.sentFor = null;
        this.pump();
        return;
      }
      if (busy(result) && !this.retried) {
        this.retried = true;
        this.sentFor = null;
        this.timer = this.timers.set(() => {
          this.timer = null;
          this.pump();
        }, retryDelayMs(result));
        return;
      }
      this.sentFor = null;
      this.wanted = null;
      this.options.onResult(q, result);
    });
  }
}

/** A point's key for naming: about 10 m, so a point dropped where it was keeps its name. */
export function placeKey([lon, lat]: LonLat): string {
  return `${lon.toFixed(4)},${lat.toFixed(4)}`;
}

type Named = { state: "named"; name: string; label: string } | { state: "none" } | { state: "failed" };

/**
 * Names for route points, one lookup per point: a cache by `placeKey`, one
 * request at a time, only the points still in the plan asked about. A point
 * whose lookup failed, or that has no name nearby, shows its coordinates. A
 * point placed from search keeps the name it was chosen by (`remember`).
 */
export class PlaceNamer {
  private cache = new Map<string, Named>();
  private wanted: LonLat[] = [];
  private running = false;
  private timer: unknown = null;
  private retried = new Set<string>();

  private readonly options: {
    send: (point: LonLat) => Promise<GeoResult>;
    onChange: () => void;
    timers?: Timers;
    debounceMs?: number;
  };

  constructor(options: PlaceNamer["options"]) {
    this.options = options;
  }

  private get timers(): Timers {
    return this.options.timers ?? realTimers;
  }

  /** The name to show for `point`, or undefined to show its coordinates. */
  name(point: LonLat): { name: string; label: string } | undefined {
    const named = this.cache.get(placeKey(point));
    return named?.state === "named" ? { name: named.name, label: named.label } : undefined;
  }

  remember(point: LonLat, name: string, label: string = name) {
    this.cache.set(placeKey(point), { state: "named", name, label });
    this.options.onChange();
  }

  /** The plan's points now; the unnamed ones are looked up once they settle. */
  want(points: readonly LonLat[]) {
    this.wanted = points.slice(0, MAX_POINTS);
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = this.timers.set(() => {
      this.timer = null;
      this.pump();
    }, this.options.debounceMs ?? NAME_DEBOUNCE_MS);
  }

  private pump() {
    if (this.running) return;
    const point = this.wanted.find((p) => !this.cache.has(placeKey(p)));
    if (!point) return;
    const key = placeKey(point);
    this.running = true;
    this.options.send(point).then((result) => {
      this.running = false;
      if (busy(result) && !this.retried.has(key)) {
        this.retried.add(key);
        this.timer = this.timers.set(() => {
          this.timer = null;
          this.pump();
        }, retryDelayMs(result));
        return;
      }
      if (!this.cache.has(key)) {
        const first = result.ok ? result.places[0] : undefined;
        this.cache.set(
          key,
          first ? { state: "named", name: first.name, label: first.label } : { state: result.ok ? "none" : "failed" },
        );
        this.options.onChange();
      }
      this.pump();
    });
  }
}

export type PlaceRole = "start" | "end" | "replace-end" | "via";

/** What choosing a search result does to a plan of `count` points. */
export function placeRole(count: number, asVia: boolean): PlaceRole {
  if (count === 0) return "start";
  if (count === 1) return "end";
  return asVia ? "via" : "replace-end";
}

/**
 * The plan after choosing `point` from search: the start when there is none,
 * the destination when there is a start, and with a route already there
 * either a new destination or, asked for, a via on the leg it lengthens least.
 */
export function applyPlace(points: readonly LonLat[], point: LonLat, asVia: boolean): LonLat[] {
  switch (placeRole(points.length, asVia)) {
    case "start":
    case "end":
      return [...points, point];
    case "replace-end":
      return [...points.slice(0, -1), point];
    case "via":
      return addPoint(points, point);
  }
}

/** The start's, the end's or a via's name in the points list. */
export function pointRole(index: number, count: number): string {
  if (index === 0) return "Start";
  if (index === count - 1 && count > 1) return "End";
  return `Via ${index}`;
}

export function coordinatesText([lon, lat]: LonLat): string {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}
