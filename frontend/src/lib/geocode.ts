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
import { MAX_POINTS, addPoint, haversineM, insideCoverage, type LonLat } from "./geo.ts";
import { formatDistance } from "./format.ts";
import { t } from "./i18n.ts";
import { parseRetryAfter } from "./api.ts";
import { pointName } from "./summary.ts";
import { namePoints } from "./pointKinds.ts";

export interface Place {
  name: string;
  label: string;
  lon: number;
  lat: number;
  kind: string;
  /**
   * The OSM element and tag behind the result, when the API knows them: what
   * the list shows as the place's type (`placeType`), and what a station
   * result is matched by to the bundled rail stations (railStations.ts,
   * stationForPlace), so it goes to the station's bike entrance.
   */
  osm_type?: "N" | "W" | "R" | null;
  osm_id?: number | null;
  osm_key?: string | null;
  osm_value?: string | null;
}

export type GeoResult =
  | { ok: true; places: Place[]; attribution: string[] }
  | { ok: false; status: number; retryAfterS?: number };

/** Fewer characters than this match half the region; the box waits for more. */
export const MIN_QUERY_CHARS = 3;
/** The API's own ceiling, so a longer paste is cut rather than refused. */
export const MAX_QUERY_CHARS = 200;
export const SEARCH_RESULTS = 6;
/** A ride's Detour search asks for the API's most (core.geocode.MAX_RESULTS), to measure by bike with food's matches. */
export const MAX_DETOUR_SEARCH = 10;
/** Typing pauses this long before a search is sent. */
export const SEARCH_DEBOUNCE_MS = 250;
/** Points that change settle this long before they are named. */
export const NAME_DEBOUNCE_MS = 400;
/** A busy answer is retried once, after its Retry-After but never later than this. */
export const RETRY_CAP_MS = 1500;

/** A query as it is sent: trimmed, its runs of white space one space. */
export function normalQuery(query: string): string {
  return query.trim().replace(/\s+/g, " ");
}

/**
 * The places to show for what is in the box now: an answer to exactly that
 * query, or none. A list left over from an earlier query is never shown, so
 * Enter or a tap cannot pick a place the rider has already typed past.
 */
export function displayedPlaces(query: string, answered: string, result: GeoResult | null): Place[] {
  if (result === null || !result.ok || normalQuery(query) !== answered) return [];
  return result.places;
}

/**
 * The rider's location as a search bias is rounded to this many degrees (about 1 km by 0.9 km here): inside
 * the 2.3 km radius in which Photon gives a place nearly its full nearness at the server's bias zoom
 * (core/geocode.py BIAS_ZOOM), and no more precise than that in the request, its log line or the browser's cache.
 */
export const BIAS_ROUNDING_DEG = 0.01;

/** The map's view as west, south, east, north. */
export type ViewBounds = readonly [number, number, number, number];

/**
 * The point a search is biased toward: the rider's location when the app already has it (from Use my
 * location or Go's start; never asked for just to search) and it is in the map's view, rounded; else the
 * map's centre, so a rider who has panned away to plan elsewhere searches near what they are looking at;
 * and neither when it is outside the map's coverage. One rule for Go, Plan and My Go's home.
 */
export function searchBiasPoint(
  here: LonLat | null | undefined,
  centre: LonLat | undefined,
  view: ViewBounds | undefined,
): LonLat | undefined {
  const inView = (p: LonLat) => view !== undefined && p[0] >= view[0] && p[0] <= view[2] && p[1] >= view[1] && p[1] <= view[3];
  if (here && inView(here)) {
    const round = (v: number) => Number((Math.round(v / BIAS_ROUNDING_DEG) * BIAS_ROUNDING_DEG).toFixed(2));
    const near: LonLat = [round(here[0]), round(here[1])];
    if (insideCoverage(near)) return near;
  }
  return centre && insideCoverage(centre) ? centre : undefined;
}

/**
 * Go's search bias (P2, "Where to? sorted by distance"): the route's start (the rider's location or the start typed
 * in), rounded as the location is, so a search finds what is near where the ride begins whatever the map shows; none
 * without a start or outside the coverage, where the caller falls back to `searchBiasPoint`.
 */
export function startBiasPoint(start: LonLat | null | undefined): LonLat | undefined {
  if (!start) return undefined;
  const round = (v: number) => Number((Math.round(v / BIAS_ROUNDING_DEG) * BIAS_ROUNDING_DEG).toFixed(2));
  const near: LonLat = [round(start[0]), round(start[1])];
  return insideCoverage(near) ? near : undefined;
}

/** Words as a query and a place are compared: lower case, accents off, split at anything not a letter or digit. */
function searchWords(text: string): string[] {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter((w) => w !== "");
}

/**
 * Whether a place answers the words typed by name: every word of three or more letters begins a word of its name or
 * label ("safe" finds Safeway). Numbers and short words ("nw", "st") are left out, since a name rarely carries the
 * house number or the abbreviation the server spells out. A place found another way (a typo, or "grocery", which the
 * server answers with supermarkets) does not.
 */
export function namesQuery(place: Pick<Place, "name" | "label">, query: string): boolean {
  const typed = searchWords(query).filter((w) => w.length >= 3 && !/^\p{N}+$/u.test(w));
  const own = searchWords(`${place.name} ${place.label}`);
  return typed.every((w) => own.some((o) => o.startsWith(w)));
}

/**
 * The places found, nearest the route's start first (P2: a rider who searched "grocery" was offered a store 66 minutes
 * away first): those that answer the words by name (`namesQuery`) ahead of the rest, each group by straight-line
 * distance, ties in the server's order. An address ("1600 Pennsylvania") keeps the server's order, which weighs the
 * number and the street; so does a search with no start known.
 */
export function nearestFirst(places: readonly Place[], start: LonLat | null | undefined, query: string): Place[] {
  if (!start || /^\s*\d/.test(query)) return [...places];
  return places
    .map((place, i) => ({ place, i, named: namesQuery(place, query), m: haversineM(start, [place.lon, place.lat]) }))
    .sort((a, b) => Number(b.named) - Number(a.named) || a.m - b.m || a.i - b.i)
    .map((r) => r.place);
}

/** How far a place is from the start, as its row says it: "0.7 mi (1.1 km)", straight line. */
export function placeDistance(place: Pick<Place, "lon" | "lat">, start: LonLat): string {
  return formatDistance(haversineM(start, [place.lon, place.lat]));
}

/**
 * A row's second line (P2): the label without the name it begins with, which the first line already shows, and the
 * distance: "Dupont Circle, Washington · 0.7 mi (1.1 km)".
 */
export function placeRowLine(place: Pick<Place, "name" | "label" | "lon" | "lat">, start: LonLat | null | undefined): string {
  const area = place.label.startsWith(`${place.name}, `) ? place.label.slice(place.name.length + 2) : place.label === place.name ? "" : place.label;
  const distance = start ? placeDistance(place, start) : "";
  return [area, distance].filter((s) => s !== "").join(" · ");
}

/**
 * Cities a rider may type that the map does not reach (P2): the search finds only streets named for them ("New York
 * Avenue"), or nothing, so the box says what RouteMaker covers. The whole query must be the city, with or without
 * its state, so "New York Ave" is a street search like any other.
 */
const CITIES_OUTSIDE = new Set([
  "new york", "new york city", "nyc", "manhattan", "brooklyn", "philadelphia", "philly", "pittsburgh", "harrisburg",
  "lancaster", "wilmington", "dover", "newark", "boston", "richmond", "norfolk", "virginia beach", "charlottesville",
  "roanoke", "raleigh", "charlotte", "atlanta", "chicago", "los angeles", "san francisco", "ocean city",
]);
const STATE_WORDS = new Set(["ny", "pa", "va", "de", "nj", "ma", "nc", "ga", "il", "ca", "md", "usa", "us", "virginia", "pennsylvania", "delaware", "massachusetts"]);

export function namesCityOutside(query: string): boolean {
  const words = searchWords(query);
  while (words.length > 1 && STATE_WORDS.has(words[words.length - 1])) words.pop();
  return CITIES_OUTSIDE.has(words.join(" "));
}

/** What the coverage is, said where a query names a city outside it. */
export const COVERS_LINE = t("RouteMaker covers DC to Baltimore.");

/** The box's words for a search that found nothing (P2), with the coverage when the query names a city outside it. */
export function nothingFoundText(query: string): string {
  const nothing = t("Nothing found. Check the spelling, or try a street address.");
  return namesCityOutside(query) ? `${nothing} ${COVERS_LINE}` : nothing;
}

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
    places: b.results.filter(isPlace).map((p) => ({
      ...p,
      kind: typeof p.kind === "string" ? p.kind : "other",
      osm_type: p.osm_type === "N" || p.osm_type === "W" || p.osm_type === "R" ? p.osm_type : null,
      osm_id: typeof p.osm_id === "number" && Number.isInteger(p.osm_id) ? p.osm_id : null,
      osm_key: typeof p.osm_key === "string" ? p.osm_key : null,
      osm_value: typeof p.osm_value === "string" ? p.osm_value : null,
    })),
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

/**
 * Worth one more try: busy (429, 503), or the geocoder not answering in time
 * (502, or no answer at all) - the first searches after Photon starts read its
 * index from disk and can run past the API's timeout, and the next is quick.
 */
function busy(result: GeoResult): boolean {
  return !result.ok && [0, 429, 502, 503].includes(result.status);
}

function retryDelayMs(result: GeoResult): number {
  const s = result.ok ? undefined : result.retryAfterS;
  return Math.min(RETRY_CAP_MS, Math.max(250, (s ?? 1) * 1000));
}

/**
 * The typeahead's requests: debounced, one in flight, only the latest query
 * answered. A query typed while another is in flight waits for it and is sent
 * next; anything typed in between is never sent. A busy or unanswered search
 * (429, 502, 503, no answer) is retried once for the latest query.
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
    const q = normalQuery(query);
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

type Named =
  | { state: "named"; name: string; label: string }
  | { state: "none" }
  | { state: "failed"; at: number };

/**
 * A lookup that failed (not one that found nothing) is asked again after this
 * long, while its point is still in the plan: a geocoder restarting or a busy
 * minute should not leave a point in coordinates until the page is reloaded
 * (round-1 review).
 */
export const FAILED_RETRY_MS = 30_000;

/**
 * A timer set for 30 s can fire a few milliseconds early by the clock the
 * failure was stamped with (Date.now against the timer's own clock: 29 991 ms
 * in the round-2 browser run), so a point is due this much early; and the
 * retry timer is never set shorter than RETRY_FLOOR_MS.
 */
export const RETRY_CLOCK_SLACK_MS = 250;
export const RETRY_FLOOR_MS = 250;

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
  private retryTimer: unknown = null;
  private retried = new Set<string>();

  private readonly options: {
    send: (point: LonLat) => Promise<GeoResult>;
    onChange: () => void;
    timers?: Timers;
    debounceMs?: number;
    /** Milliseconds now; Date.now by default. */
    now?: () => number;
    /** A name the rider gave the point (a stop's own name, lib/pointKinds.ts): shown before any looked up. */
    own?: (point: LonLat) => string | undefined;
  };

  constructor(options: PlaceNamer["options"]) {
    this.options = options;
  }

  private get timers(): Timers {
    return this.options.timers ?? realTimers;
  }

  /** The name to show for `point`, or undefined to show its coordinates. */
  name(point: LonLat): { name: string; label: string } | undefined {
    const own = this.options.own?.(point);
    if (own) return { name: own, label: own };
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
    // A point put back (undo, or a drag back to where it was) may have failed
    // while it was out of the plan, when there was nothing to arm the retry for.
    this.armRetry();
  }

  private now(): number {
    return (this.options.now ?? Date.now)();
  }

  /** Whether `point` should be looked up: never asked, or failed long enough ago. */
  private due(point: LonLat): boolean {
    if (this.options.own?.(point)) return false;
    const named = this.cache.get(placeKey(point));
    return (
      named === undefined ||
      (named.state === "failed" && this.now() - named.at >= FAILED_RETRY_MS - RETRY_CLOCK_SLACK_MS)
    );
  }

  private pump() {
    if (this.running) return;
    const point = this.wanted.find((p) => this.due(p));
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
      const cached = this.cache.get(key);
      if (cached === undefined || cached.state === "failed") {
        const first = result.ok ? result.places[0] : undefined;
        if (first) this.cache.set(key, { state: "named", name: first.name, label: first.label });
        else if (result.ok) this.cache.set(key, { state: "none" });
        else {
          this.cache.set(key, { state: "failed", at: this.now() });
          this.retried.delete(key);
          this.armRetry();
        }
        this.options.onChange();
      }
      this.pump();
    });
  }

  /**
   * Set the one retry timer for the earliest failed point still in the plan
   * that is not yet due, or clear it if there is none. It is set again each
   * time it fires, so failures at different times are each asked again in
   * turn (round-2 review: a timer that found nothing due was never set
   * again, and a later failure was never retried). Points already due are
   * the pump's: it takes them one after another.
   */
  private armRetry() {
    if (this.retryTimer !== null) this.timers.clear(this.retryTimer);
    this.retryTimer = null;
    let earliest: number | undefined;
    for (const point of this.wanted) {
      const named = this.cache.get(placeKey(point));
      if (named?.state !== "failed" || this.due(point)) continue;
      if (earliest === undefined || named.at < earliest) earliest = named.at;
    }
    if (earliest === undefined) return;
    const wait = Math.max(RETRY_FLOOR_MS, earliest + FAILED_RETRY_MS - this.now());
    this.retryTimer = this.timers.set(() => {
      this.retryTimer = null;
      this.pump();
      this.armRetry();
    }, wait);
  }
}

type FetchPlaces = (url: string) => Promise<GeoResult>;

/** How the search box asks: through the page's gate, ahead of any name waiting. */
export function searchSender(
  gate: GeoGate,
  bias: () => LonLat | undefined,
  fetchImpl: FetchPlaces = (url) => fetchPlaces(url),
): (query: string) => Promise<GeoResult> {
  return (query) => gate.run(() => fetchImpl(searchUrl(query, bias())), true);
}

/** How a point's name is asked: through the same gate, behind any search. */
export function nameSender(
  gate: GeoGate,
  fetchImpl: FetchPlaces = (url) => fetchPlaces(url),
): (point: LonLat) => Promise<GeoResult> {
  return (point) => gate.run(() => fetchImpl(reverseUrl(point)));
}

/**
 * Where a picked place goes, or null if it is outside the map's area (the
 * API fences results to the box, so that is a result to refuse, not trust).
 * The point keeps the name it was found by: `remember` is the namer's.
 * `entrance` moves a station to its bike entrance (railData.ts,
 * stationEntranceForPlace), where a tap on the station would put it; the
 * point is still named for the station, not the entrance's street.
 */
export function placeFromSearch(
  found: Place,
  remember: (point: LonLat, name: string, label: string) => void,
  entrance?: (found: Place) => LonLat | null,
): LonLat | null {
  if (!insideCoverage([found.lon, found.lat])) return null;
  const moved = entrance?.(found) ?? null;
  const point: LonLat = moved && insideCoverage(moved) ? moved : [found.lon, found.lat];
  remember(point, found.name, found.label);
  return point;
}

/** What the search box shows, from its state: the one place its derived state is worked out. */
export function searchView(state: {
  query: string;
  answered: string;
  result: GeoResult | null;
  open: boolean;
  pointCount: number;
  full: boolean;
  chosen: PlaceChoice | null;
  /** "Make it a loop" is on (OWNER-DECISIONS 374): no destination, every later place is a stop. */
  loop?: boolean;
}) {
  const current = normalQuery(state.query);
  const places = displayedPlaces(state.query, state.answered, state.result);
  const answeredNow = state.result !== null && current === state.answered;
  const choice = choiceInForce(state.chosen, state.pointCount, state.full, state.loop);
  return {
    places,
    // Open only with places for the query in the box: Enter picks from these.
    expanded: state.open && places.length > 0,
    answeredNow,
    searching: current.length >= MIN_QUERY_CHARS && !answeredNow,
    choices: choicesFor(state.pointCount, state.full, state.loop),
    choice,
    effect: placeEffect(state.pointCount, choice, state.loop),
  };
}

/**
 * A place picked from search, into the plan: the point it becomes (or null
 * when it is outside the map), named as it was found, and the plan changed
 * through `commit` - the undo history's one way in (App.tsx), so a pick is one
 * step Ctrl+Z takes back, like any other edit (merge re-check B1: a pick that
 * set the points directly was not undoable, and Ctrl+Z took back the edit
 * before it instead).
 */
export function pickIntoPlan(
  found: Place,
  choice: PlaceChoice,
  plan: {
    current: () => LonLat[];
    commit: (next: LonLat[]) => void;
    remember: (point: LonLat, name: string, label: string) => void;
    /** "Make it a loop" is on (OWNER-DECISIONS 374). */
    loop?: boolean;
    /** A station's bike entrance, for a result that is a station (placeFromSearch). */
    entrance?: (found: Place) => LonLat | null;
  },
): LonLat | null {
  const point = placeFromSearch(found, plan.remember, plan.entrance);
  if (point === null) return null;
  plan.commit(applyPlace(plan.current(), point, choice, plan.loop === true));
  return point;
}

/** One row of the points list: its role, its name if it has one, its coordinates. */
export interface PointRow {
  role: string;
  place: { name: string; label: string } | undefined;
  coords: string;
}

/** The points list the panel shows (App.tsx renders these). */
export function pointRows(
  points: readonly LonLat[],
  names: { name: (point: LonLat) => { name: string; label: string } | undefined },
  loop = false,
  isVia?: (point: LonLat) => boolean,
): PointRow[] {
  // With the points' kinds (v0.7.0, lib/pointKinds.ts): stops numbered among themselves, via points unnumbered.
  const named = isVia ? namePoints(points, isVia, loop) : null;
  return points.map((point, index) => ({
    role: named ? named[index].name : pointName(index, points.length, loop),
    place: names.name(point),
    coords: coordinatesText(point),
  }));
}

export type KeyAction =
  | { kind: "none" }
  | { kind: "move"; active: number }
  | { kind: "pick"; index: number }
  | { kind: "close" }
  | { kind: "clear" };

/**
 * What a key does in the search box (the ARIA combobox pattern): the arrows
 * move through the options and wrap, Enter picks the highlighted option or
 * else the first, Escape closes an open list and then clears the box.
 */
export function comboboxKey(
  key: string,
  state: { active: number; count: number; expanded: boolean; hasQuery: boolean },
): KeyAction {
  const { active, count, expanded, hasQuery } = state;
  if (key === "ArrowDown" || key === "ArrowUp") {
    if (count === 0) return { kind: "none" };
    const step = key === "ArrowDown" ? 1 : -1;
    // With nothing highlighted, Down is the first and Up the last.
    if (active < 0) return { kind: "move", active: step > 0 ? 0 : count - 1 };
    return { kind: "move", active: (active + step + count) % count };
  }
  if (key === "Enter") {
    if (!expanded || count === 0) return { kind: "none" };
    return { kind: "pick", index: active >= 0 && active < count ? active : 0 };
  }
  if (key === "Escape") {
    if (expanded) return { kind: "close" };
    if (hasQuery) return { kind: "clear" };
  }
  return { kind: "none" };
}

/**
 * The option an Enter picks (comboboxKey's "pick"), from the list as shown
 * (`items`, which may lead with an extra option such as "Your location") and
 * the places in it. With nothing highlighted it is the first *place*, never the
 * extra option: "Your location" asks the browser's permission, so only a
 * deliberate highlight picks it (OWNER-DECISIONS 395).
 */
export function pickTarget<T, P extends T>(active: number, index: number, items: readonly T[], places: readonly P[]): T | undefined {
  return active < 0 ? places[0] : items[index];
}

/** What a picked place is made: the start, the destination, or a stop on the way. */
export type PlaceChoice = "start" | "end" | "via";

/** The choice the box starts on: the start for an empty plan, else the destination (a stop in a loop). */
export function defaultChoice(count: number, loop = false, full = false): PlaceChoice {
  if (count === 0) return "start";
  if (loop) return "via";
  // With a start and an end, a picked place is a stop where it adds the least distance (v0.7.0, "Keep adding
  // stops by search"); the result row's "Make this the destination" puts it at the end instead. A full route
  // takes no stop, so a pick is a new destination there, as before.
  return count >= 2 && !full ? "via" : "end";
}

/**
 * The choice in force: the rider's, while it is still on offer - a "stop"
 * chosen on a route that has since lost its end, or filled up, is not - and
 * otherwise the plan's default.
 */
export function choiceInForce(chosen: PlaceChoice | null, count: number, full: boolean, loop = false): PlaceChoice {
  return chosen !== null && choicesFor(count, full, loop).includes(chosen) ? chosen : defaultChoice(count, loop, full);
}

/**
 * The choices open to a plan of `count` points: a stop needs a start and an
 * end, and room; in a loop the start alone is enough, and there is no end.
 */
export function choicesFor(count: number, full: boolean, loop = false): PlaceChoice[] {
  if (count === 0) return ["start"];
  // A loop finishes at its start (OWNER-DECISIONS 374): a stop can follow the start alone, and there is no destination.
  if (loop) return full ? ["start"] : ["start", "via"];
  return count >= 2 && !full ? ["start", "end", "via"] : ["start", "end"];
}

export type PlaceEffect = "start" | "replace-start" | "end" | "replace-end" | "via";

const EFFECT_HINT: Record<PlaceEffect, string> = {
  start: "The place you pick becomes the start.",
  "replace-start": "The place you pick becomes the new start.",
  end: "The place you pick becomes the destination.",
  "replace-end": "The place you pick becomes the new destination.",
  via: "The place you pick is added as a stop along the way.",
};

/**
 * The search box's hint for what a pick does. In a loop (OWNER-DECISIONS 374)
 * the start is also the finish, so a new start is the new start and finish.
 */
export function placeEffectHint(effect: PlaceEffect, loop = false): string {
  if (loop && effect === "start") return "The place you pick becomes the start and finish.";
  if (loop && effect === "replace-start") return "The place you pick becomes the new start and finish.";
  return EFFECT_HINT[effect];
}

/** What choosing a search result as `choice` does to a plan of `count` points. */
export function placeEffect(count: number, choice: PlaceChoice, loop = false): PlaceEffect {
  if (count === 0) return "start";
  if (choice === "start") return "replace-start";
  // In a loop, "Make this the destination" ends the ride there, after the stops (the owner, 2026-10-22: "Setting a
  // destination should end the loop"); App's pickPlace turns the loop off in the same edit.
  if (loop) return choice === "end" ? "end" : "via";
  if (choice === "via" && count >= 2) return "via";
  return count === 1 ? "end" : "replace-end";
}

/**
 * The plan after choosing `point` from search: the start of an empty plan;
 * then, as chosen, a new start, the destination (added after a lone start,
 * replacing an end), or a stop on the leg it lengthens least.
 */
export function applyPlace(points: readonly LonLat[], point: LonLat, choice: PlaceChoice, loop = false): LonLat[] {
  switch (placeEffect(points.length, choice, loop)) {
    case "start":
    case "end":
      return [...points, point];
    case "replace-start":
      return [point, ...points.slice(1)];
    case "replace-end":
      return [...points.slice(0, -1), point];
    case "via":
      return addPoint(points, point, loop);
  }
}

const TRAIL_VALUES = new Set(["cycleway", "path", "footway", "bridleway", "track", "pedestrian"]);
const NEIGHBORHOOD_VALUES = new Set(["neighbourhood", "suburb", "quarter", "borough"]);
const TOWN_VALUES = new Set(["city", "town", "village", "hamlet"]);
const FOOD_VALUES = new Set(["restaurant", "cafe", "fast_food", "bar", "pub", "ice_cream"]);

/**
 * A short type for a result, from its OSM tag: what tells "Bethesda" the
 * station from Bethesda the town (round-1 review). The API cannot say which
 * rail network a station is on (Photon keeps no network tag here), so a
 * Metro, MARC or VRE station is "Rail station".
 */
export function placeType(place: Pick<Place, "kind" | "osm_key" | "osm_value">): string {
  const key = place.osm_key ?? "";
  const value = place.osm_value ?? "";
  // A place read from a pasted or shared map link (lib/sharedLocation.ts).
  if (place.kind === "shared") return "From a map link";
  if (key === "railway" && (value === "station" || value === "halt")) return "Rail station";
  if (key === "public_transport" && value === "station") return "Station";
  if (key === "railway" && value === "subway_entrance") return "Station entrance";
  if ((key === "highway" && value === "bus_stop") || (key === "amenity" && value === "bus_station")) return "Bus stop";
  if (key === "shop" && value === "bicycle") return "Bike shop";
  if (key === "amenity" && value === "bicycle_rental") return "Bike share";
  if (key === "amenity" && value === "bicycle_parking") return "Bike parking";
  if (key === "leisure" && (value === "park" || value === "nature_reserve" || value === "garden")) return "Park";
  if ((key === "highway" && TRAIL_VALUES.has(value)) || place.kind === "trail") return "Trail";
  if (key === "highway" || place.kind === "street") return "Street";
  if (key === "place" && value === "house") return "Address";
  if (key === "place" && NEIGHBORHOOD_VALUES.has(value)) return "Neighborhood";
  if (key === "place" && TOWN_VALUES.has(value)) return "Town";
  if (key === "aeroway" && value === "aerodrome") return "Airport";
  if (key === "amenity" && FOOD_VALUES.has(value)) return "Food and drink";
  if (key === "shop") return "Shop";
  if (key === "building" || key === "office") return "Building";
  if (value && value !== "yes") {
    const words = value.replaceAll("_", " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  return "Place";
}

export function coordinatesText([lon, lat]: LonLat): string {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}
