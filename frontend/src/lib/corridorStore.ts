/**
 * The browser's side of the ride's corridor (lib/corridor.ts; WEB-NAV-plan.md section 6): where the
 * tiles are kept and how the map reads them back.
 *
 * - Stress tiles: Cache Storage, bucket CORRIDOR_BUCKET, keyed by the tile's URL without its `?rev=`
 *   (the edit generation, lib/tileRev.ts), which is kept beside it. During a ride the stress protocol
 *   (stressProtocol.ts) reads a kept tile of the same generation first, and when the network fails or
 *   hangs, one of any generation (an admin's edit mid-ride still leaves the older tile for a dead spot).
 *   It keeps the tiles the map itself loads during a ride. Outside a ride nothing is read or opened.
 * - Base map: the pmtiles protocol's archive is a `CorridorSource` over the usual `FetchSource`, with
 *   its byte ranges kept in IndexedDB (database CORRIDOR_DB).
 * - Glyphs and sprites: fetched once at Start ride into the browser's HTTP cache, which keeps them a day
 *   (Caddyfile: `/basemap/fonts/*` and `/sprites/*` are `private, max-age=86400`) and answers MapLibre's
 *   own requests from it with no network; Cache Storage would not, since MapLibre does not read it.
 *
 * A ride never outlives the page (the service worker keeps the app, never a ride), so what an earlier page kept is of no use:
 * all of it is cleared at End ride, at the start of each ride's first fetch, and at the next page load
 * (`sweepCorridor`, whenever the stamp says something may be kept). Nothing here holds a position.
 *
 * The routes kept for offline (phase P3, lib/offlineRouteStore.ts) are a separate store this module
 * only reads, after its own, when the network fails; End ride never clears them. In the installed app,
 * End ride first hands what the ride kept to the last ride's kept route (`clearCorridor(handOn)`).
 */
import { FetchSource, PMTiles } from "pmtiles";
import { BASEMAP } from "../stressStyle.js";
import { ByteBudget, CorridorSource, glyphUrls, prefetchCorridor, type KeptRange, type PrefetchResult, type RangeStore, type TileJob } from "./corridor.ts";
import type { LonLat } from "./geo.ts";
import { keptRanges, keptTile } from "./offlineRouteStore.ts";
import { fetchTile, httpUrl } from "./stressProtocol.ts";

export const CORRIDOR_BUCKET = "routemaker-corridor-v1";
export const CORRIDOR_DB = "routemaker-corridor";
/** Set while something may be kept, so the next page load knows to clear it (a time, never a place). */
const STAMP_KEY = "routemaker.corridor";
/** The kept tile's edit generation, beside it in Cache Storage. */
const REV_HEADER = "X-Corridor-Rev";

const budget = new ByteBudget();

function indexedDbStore(): RangeStore & { all(): Promise<KeptRange[]> } {
  let opened: Promise<IDBDatabase> | null = null;
  const db = () =>
    (opened ??= new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open(CORRIDOR_DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore("ranges", { keyPath: "key" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => {
        opened = null;
        reject(request.error);
      };
    }));
  const read = async <T>(act: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
    const store = (await db()).transaction("ranges", "readonly").objectStore("ranges");
    return new Promise<T>((resolve, reject) => {
      const request = act(store);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  };
  // A write is done when its transaction completes; a quota error arrives as the transaction's abort.
  const write = async (act: (store: IDBObjectStore) => void): Promise<void> => {
    const tx = (await db()).transaction("ranges", "readwrite");
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error ?? new DOMException("aborted", "AbortError"));
      tx.onerror = () => reject(tx.error);
      act(tx.objectStore("ranges"));
    });
  };
  return {
    get: (key) => read<KeptRange | undefined>((s) => s.get(key) as IDBRequest<KeptRange | undefined>),
    put: (range) => write((s) => void s.put(range)),
    clear: () => write((s) => void s.clear()),
    all: () => read<KeptRange[]>((s) => s.getAll() as IDBRequest<KeptRange[]>),
  };
}

function emptyStore(): RangeStore & { all(): Promise<KeptRange[]> } {
  return { get: async () => undefined, put: async () => undefined, clear: async () => undefined, all: async () => [] };
}

const rangeStore = typeof indexedDB === "undefined" ? emptyStore() : indexedDbStore();
// The routes kept for offline (lib/offlineRouteStore.ts, phase P3) answer after the ride's own store
// when the network fails, so the installed app shows the map along a kept route with no signal.
const source = new CorridorSource(new FetchSource(BASEMAP.path), rangeStore, budget, keptRanges);

/** The base map's archive for the pmtiles protocol (MapView adds it), keyed as the style's URL names it. */
export const basemapArchive = new PMTiles(source);

// ---- Stress tiles ---------------------------------------------------------------------------------

let keepingStress = false;

/** The tile's key (its URL without `rev`) and its edit generation ("" for none). */
export function stressKey(url: string): { key: string; rev: string } {
  const parsed = new URL(url, "http://localhost");
  const rev = parsed.searchParams.get("rev") ?? "";
  parsed.searchParams.delete("rev");
  const key = /^[a-z]+:\/\//i.test(url) ? parsed.href : `${parsed.pathname}${parsed.search}`;
  return { key, rev };
}

/** The stress protocol's offline side (stressProtocol.ts `registerStressProtocol`). */
export const corridorStress = {
  riding: () => keepingStress,
  /** A tile kept for this ride, else one kept with a route for offline (lib/offlineRouteStore.ts). */
  async kept(url: string, anyRev = false): Promise<ArrayBuffer | null> {
    return (await keptForRide(url, anyRev)) ?? (await keptTile(url, anyRev));
  },
  async keep(url: string, data: ArrayBuffer): Promise<boolean> {
    if (!keepingStress || typeof caches === "undefined" || !budget.take(data.byteLength)) return false;
    try {
      const { key, rev } = stressKey(url);
      const headers = { "Content-Type": "application/x-protobuf", [REV_HEADER]: rev };
      await (await caches.open(CORRIDOR_BUCKET)).put(key, new Response(data.slice(0), { headers }));
      return true;
    } catch {
      // A quota or storage refusal: the bytes were not kept.
      budget.give(data.byteLength);
      return false;
    }
  },
};

/** The ride's own kept tile of this URL's edit generation, or with `anyRev` of any. */
async function keptForRide(url: string, anyRev = false): Promise<ArrayBuffer | null> {
  // Outside a ride nothing is kept, and the bucket is not opened (which would create it).
  if (!keepingStress || typeof caches === "undefined") return null;
  try {
    const { key, rev } = stressKey(url);
    const hit = await (await caches.open(CORRIDOR_BUCKET)).match(key);
    if (!hit || (!anyRev && (hit.headers.get(REV_HEADER) ?? "") !== rev)) return null;
    return await hit.arrayBuffer();
  } catch {
    return null;
  }
}

// ---- The style ------------------------------------------------------------------------------------

let style: { glyphs: string; sprite: string; stacks: string[] } | null = null;
let stressTemplate: (() => string) | null = null;

/** MapView, as it builds the map: what the prefetch asks for besides the tiles. */
export function setCorridorStyle(glyphs: string, sprite: string, stacks: string[], stressTiles: () => string): void {
  style = { glyphs, sprite, stacks };
  stressTemplate = stressTiles;
}

/** The style's glyph and sprite URLs a ride's labels and icons need ([] before the style has loaded). */
export function styleExtraUrls(): string[] {
  if (!style) return [];
  const scale = typeof devicePixelRatio === "number" && devicePixelRatio > 1 ? "@2x" : "";
  return [...glyphUrls(style.glyphs, style.stacks), `${style.sprite}${scale}.json`, `${style.sprite}${scale}.png`];
}

/** A stress tile's URL as the map asks for it, or null before the style has loaded. */
export function stressTileUrl(z: number, x: number, y: number): string | null {
  if (!stressTemplate) return null;
  return httpUrl(stressTemplate()).replace("{z}", String(z)).replace("{x}", String(x)).replace("{y}", String(y));
}

async function fetchExtras(signal: AbortSignal): Promise<void> {
  for (const url of styleExtraUrls()) {
    if (signal.aborted) return;
    // Into the HTTP cache (a day's max-age); the body is read so the entry is complete.
    await fetch(url, { signal }).then((r) => r.arrayBuffer()).catch(() => undefined);
  }
}

/** One tile fetched and kept; true only when it (and for the base map, every range it read) was kept. */
async function fetchJob(job: TileJob, signal: AbortSignal): Promise<boolean> {
  if (job.kind === "base") {
    const before = source.keepFailures;
    await basemapArchive.getZxy(job.z, job.x, job.y, signal);
    return source.keepFailures === before;
  }
  const url = stressTileUrl(job.z, job.x, job.y);
  if (url === null) return false;
  if (await keptForRide(url)) return true;
  // Through the page's queue (two in flight at most, the API's per-client cap) and its backoff.
  const data = await fetchTile(url, { signal });
  return corridorStress.keep(url, data);
}

// ---- The ride's corridor --------------------------------------------------------------------------

let done = new Set<string>();
let running: AbortController | null = null;
/** Bumped by End ride: a keepCorridor still waiting on a clear when it comes starts nothing. */
let generation = 0;
/** The clears in order, so a quick Start ride after End ride waits for the last one to finish. */
let clearing: Promise<void> = Promise.resolve();

function stamp(): void {
  try {
    localStorage.setItem(STAMP_KEY, String(Date.now()));
  } catch {
    // No storage: the next page load clears anyway (sweepCorridor).
  }
}

function stopped(): PrefetchResult {
  return { kept: 0, failed: 0, total: 0, stress: { kept: 0, total: 0 }, base: { kept: 0, total: 0 }, capped: false, stopped: true };
}

async function clearKept(): Promise<void> {
  budget.reset();
  try {
    localStorage.removeItem(STAMP_KEY);
  } catch {
    // As in stamp().
  }
  await source.clear();
  try {
    if (typeof caches !== "undefined") await caches.delete(CORRIDOR_BUCKET);
  } catch {
    // Nothing kept, or storage refused.
  }
}

function stopKeeping(): Promise<void> {
  running?.abort();
  running = null;
  keepingStress = false;
  source.keeping = false;
  done = new Set();
  clearing = clearing.then(clearKept, clearKept);
  return clearing;
}

/**
 * Fetch and keep the corridor of `line`: at Start ride (`first`, which clears anything kept before),
 * and for each re-plan's new route (a newer call stops an older one's fetching; what it kept stays).
 */
export async function keepCorridor(line: readonly LonLat[], first = false): Promise<PrefetchResult> {
  running?.abort();
  const ticket = generation;
  if (first) await stopKeeping();
  else await clearing;
  if (ticket !== generation) return stopped();
  const controller = new AbortController();
  running = controller;
  keepingStress = true;
  source.keeping = true;
  stamp();
  return prefetchCorridor(line, { fetch: fetchJob, extras: done.size ? undefined : fetchExtras, full: () => budget.full, signal: controller.signal, done });
}

/** What the ride kept, for the installed app's last-ride route (lib/offlineKeep.ts `adoptCorridor`). */
export interface CorridorSnapshot {
  ranges: KeptRange[];
  /** Each stress tile under the URL the map asks for (with its `?rev=`, as kept beside it). */
  tiles: { url: string; data: ArrayBuffer }[];
}

async function snapshot(): Promise<CorridorSnapshot> {
  const ranges = await rangeStore.all().catch(() => [] as KeptRange[]);
  const tiles: CorridorSnapshot["tiles"] = [];
  try {
    if (typeof caches !== "undefined" && (await caches.has(CORRIDOR_BUCKET))) {
      const cache = await caches.open(CORRIDOR_BUCKET);
      for (const request of await cache.keys()) {
        const hit = await cache.match(request);
        if (!hit) continue;
        const rev = hit.headers.get(REV_HEADER) ?? "";
        const url = new URL(request.url);
        if (rev) url.searchParams.set("rev", rev);
        tiles.push({ url: url.href, data: await hit.arrayBuffer() });
      }
    }
  } catch {
    // What could be read is handed on.
  }
  return { ranges, tiles };
}

/**
 * End ride: stop fetching and keeping, and clear what was kept. `handOn`, when given (the installed
 * app's last ride, OWNER-DECISIONS 465a), is shown what the ride kept first, and copies it.
 */
export async function clearCorridor(handOn?: (kept: CorridorSnapshot) => Promise<void>): Promise<void> {
  generation += 1;
  if (handOn) {
    running?.abort();
    running = null;
    try {
      await handOn(await snapshot());
    } catch {
      // The last ride keeps its route without the map; the ride's own copy is cleared all the same.
    }
  }
  return stopKeeping();
}

/**
 * At page load no ride is on, and none survives a reload, so whatever an earlier page kept is cleared
 * (when the stamp says something may be, or storage cannot say; a page that never rode opens nothing).
 */
export function sweepCorridor(): void {
  let maybe = true;
  try {
    maybe = localStorage.getItem(STAMP_KEY) !== null;
  } catch {
    // Cannot tell: clear.
  }
  if (maybe) void clearCorridor();
}
