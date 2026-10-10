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
 */
import { FetchSource, PMTiles } from "pmtiles";
import { BASEMAP } from "../stressStyle.js";
import { ByteBudget, CorridorSource, KEEP_MS, glyphUrls, prefetchCorridor, type KeptRange, type PrefetchResult, type RangeStore, type TileJob } from "./corridor.ts";
import type { LonLat } from "./geo.ts";
import { fetchTile, httpUrl } from "./stressProtocol.ts";

export const CORRIDOR_BUCKET = "routemaker-corridor-v1";
export const CORRIDOR_DB = "routemaker-corridor";
/** When the ride's corridor was first kept, for the 24 h sweep (a time, never a place). */
const STAMP_KEY = "routemaker.corridor";

const budget = new ByteBudget();

function indexedDbStore(): RangeStore {
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
  };
}

const source = new CorridorSource(new FetchSource(BASEMAP.path), typeof indexedDB === "undefined" ? emptyStore() : indexedDbStore(), budget);

function emptyStore(): RangeStore {
  return { get: async () => undefined, put: async () => undefined, clear: async () => undefined };
}

/** The base map's archive for the pmtiles protocol (MapView adds it), keyed as the style's URL names it. */
export const basemapArchive = new PMTiles(source);

// ---- Stress tiles ---------------------------------------------------------------------------------

let keepingStress = false;

/** The stress protocol's offline side (stressProtocol.ts `registerStressProtocol`). */
export const corridorStress = {
  async kept(url: string): Promise<ArrayBuffer | null> {
    try {
      if (typeof caches === "undefined") return null;
      const hit = await (await caches.open(CORRIDOR_BUCKET)).match(url);
      return hit ? await hit.arrayBuffer() : null;
    } catch {
      return null;
    }
  },
  keep(url: string, data: ArrayBuffer): void {
    if (!keepingStress || typeof caches === "undefined" || !budget.take(data.byteLength)) return;
    void caches
      .open(CORRIDOR_BUCKET)
      .then((cache) => cache.put(url, new Response(data.slice(0), { headers: { "Content-Type": "application/x-protobuf" } })))
      .catch(() => undefined);
  },
};

// ---- The style ------------------------------------------------------------------------------------

let style: { glyphs: string; sprite: string; stacks: string[] } | null = null;
let stressTemplate: (() => string) | null = null;

/** MapView, once the style has loaded: what the prefetch asks for besides the tiles. */
export function setCorridorStyle(glyphs: string, sprite: string, stacks: string[], stressTiles: () => string): void {
  style = { glyphs, sprite, stacks };
  stressTemplate = stressTiles;
}

async function fetchExtras(signal: AbortSignal): Promise<void> {
  if (!style) return;
  const scale = typeof devicePixelRatio === "number" && devicePixelRatio > 1 ? "@2x" : "";
  const urls = [...glyphUrls(style.glyphs, style.stacks), `${style.sprite}${scale}.json`, `${style.sprite}${scale}.png`];
  for (const url of urls) {
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
  if (!stressTemplate) return false;
  const url = httpUrl(stressTemplate()).replace("{z}", String(job.z)).replace("{x}", String(job.x)).replace("{y}", String(job.y));
  if (await corridorStress.kept(url)) return true;
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

/** End ride: stop fetching and keeping, and clear what was kept. */
export async function clearCorridor(): Promise<void> {
  running?.abort();
  running = null;
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
