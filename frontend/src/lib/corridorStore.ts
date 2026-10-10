/**
 * The browser's side of the ride's corridor (lib/corridor.ts; WEB-NAV-plan.md section 6): where the
 * tiles are kept and how the map reads them back.
 *
 * - Stress tiles: Cache Storage, bucket CORRIDOR_BUCKET, keyed by the tile's URL. The stress protocol
 *   (stressProtocol.ts) reads it when the network fails or the browser says it is offline, and keeps
 *   the tiles the map itself loads during a ride.
 * - Base map: the pmtiles protocol's archive is a `CorridorSource` over the usual `FetchSource`, with
 *   its byte ranges kept in IndexedDB (database CORRIDOR_DB).
 * - Glyphs and sprites: fetched once at Start ride into the browser's HTTP cache, which keeps them a day
 *   (Caddyfile: `/basemap/fonts/*` and `/sprites/*` are `private, max-age=86400`) and answers MapLibre's
 *   own requests from it with no network; Cache Storage would not, since MapLibre does not read it.
 *
 * All of it is cleared at End ride (`clearCorridor`), and at the next page load once older than
 * KEEP_MS (`sweepCorridor`). Nothing here holds a position.
 *
 * The routes kept for offline (phase P3, lib/offlineRouteStore.ts) are a separate store this module
 * only reads, after its own, when the network fails; End ride never clears them. In the installed app,
 * End ride first hands what the ride kept to the last ride's kept route (`clearCorridor(handOn)`).
 */
import { FetchSource, PMTiles } from "pmtiles";
import { BASEMAP } from "../stressStyle.js";
import { ByteBudget, CorridorSource, KEEP_MS, glyphUrls, prefetchCorridor, type KeptRange, type PrefetchResult, type RangeStore, type TileJob } from "./corridor.ts";
import type { LonLat } from "./geo.ts";
import { keptRanges, keptTile } from "./offlineRouteStore.ts";
import { fetchTile, httpUrl } from "./stressProtocol.ts";

export const CORRIDOR_BUCKET = "routemaker-corridor-v1";
export const CORRIDOR_DB = "routemaker-corridor";
/** When the ride's corridor was first kept, for the 24 h sweep (a time, never a place). */
const STAMP_KEY = "routemaker.corridor";

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
  const run = async <T>(mode: IDBTransactionMode, act: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> => {
    const store = (await db()).transaction("ranges", mode).objectStore("ranges");
    return new Promise<T>((resolve, reject) => {
      const request = act(store);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  };
  return {
    get: (key) => run<KeptRange | undefined>("readonly", (s) => s.get(key) as IDBRequest<KeptRange | undefined>),
    put: async (range) => void (await run("readwrite", (s) => s.put(range))),
    clear: async () => void (await run("readwrite", (s) => s.clear())),
    all: () => run<KeptRange[]>("readonly", (s) => s.getAll() as IDBRequest<KeptRange[]>),
  };
}

const rangeStore = typeof indexedDB === "undefined" ? emptyStore() : indexedDbStore();
// The routes kept for offline (lib/offlineRouteStore.ts, phase P3) answer after the ride's own store
// when the network fails, so the installed app shows the map along a kept route with no signal.
const source = new CorridorSource(new FetchSource(BASEMAP.path), rangeStore, budget, keptRanges);

function emptyStore(): RangeStore & { all(): Promise<KeptRange[]> } {
  return { get: async () => undefined, put: async () => undefined, clear: async () => undefined, all: async () => [] };
}

/** The base map's archive for the pmtiles protocol (MapView adds it), keyed as the style's URL names it. */
export const basemapArchive = new PMTiles(source);

// ---- Stress tiles ---------------------------------------------------------------------------------

let keepingStress = false;

/** The stress protocol's offline side (stressProtocol.ts `registerStressProtocol`). */
export const corridorStress = {
  /** A tile kept for this ride, else one kept with a route for offline (lib/offlineRouteStore.ts). */
  async kept(url: string): Promise<ArrayBuffer | null> {
    return (await keptForRide(url)) ?? (await keptTile(url));
  },
  keep(url: string, data: ArrayBuffer): void {
    if (!keepingStress || typeof caches === "undefined" || !budget.take(data.byteLength)) return;
    void caches
      .open(CORRIDOR_BUCKET)
      .then((cache) => cache.put(url, new Response(data.slice(0), { headers: { "Content-Type": "application/x-protobuf" } })))
      .catch(() => undefined);
  },
};

async function keptForRide(url: string): Promise<ArrayBuffer | null> {
  try {
    if (typeof caches === "undefined") return null;
    const hit = await (await caches.open(CORRIDOR_BUCKET)).match(url);
    return hit ? await hit.arrayBuffer() : null;
  } catch {
    return null;
  }
}

// ---- The style ------------------------------------------------------------------------------------

let style: { glyphs: string; sprite: string; stacks: string[] } | null = null;
let stressTemplate: (() => string) | null = null;

/** MapView, once the style has loaded: what the prefetch asks for besides the tiles. */
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

async function fetchJob(job: TileJob, signal: AbortSignal): Promise<boolean> {
  if (job.kind === "base") {
    await basemapArchive.getZxy(job.z, job.x, job.y, signal);
    return true;
  }
  const url = stressTileUrl(job.z, job.x, job.y);
  if (url === null) return false;
  if (await keptForRide(url)) return true;
  // Through the page's queue (two in flight at most, the API's per-client cap) and its backoff.
  const data = await fetchTile(url, { signal });
  corridorStress.keep(url, data);
  return true;
}

// ---- The ride's corridor --------------------------------------------------------------------------

let done = new Set<string>();
let running: AbortController | null = null;

function stamp(): void {
  try {
    if (!localStorage.getItem(STAMP_KEY)) localStorage.setItem(STAMP_KEY, String(Date.now()));
  } catch {
    // No storage: the sweep has no stamp, and End ride still clears.
  }
}

/**
 * Start keeping, and fetch the corridor of `line` (Start ride, and each re-plan's new route; a newer
 * call stops an older one's fetching, and what it kept stays).
 */
export function keepCorridor(line: readonly LonLat[]): Promise<PrefetchResult> {
  running?.abort();
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
        if (hit) tiles.push({ url: request.url, data: await hit.arrayBuffer() });
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
  running?.abort();
  running = null;
  if (handOn) {
    try {
      await handOn(await snapshot());
    } catch {
      // The last ride keeps its route without the map; the ride's own copy is cleared all the same.
    }
  }
  keepingStress = false;
  done = new Set();
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

/** At page load: a corridor kept over KEEP_MS ago (a ride never ended, a closed tab) is cleared. */
export function sweepCorridor(now = Date.now()): void {
  let at: number | null = null;
  try {
    const kept = localStorage.getItem(STAMP_KEY);
    at = kept === null ? null : Number(kept);
  } catch {
    return;
  }
  if (at !== null && !(now - at < KEEP_MS)) void clearCorridor();
}
