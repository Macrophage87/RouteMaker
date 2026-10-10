/**
 * Keeping a route for offline (WEB-NAV-plan.md section 8 "Offline route", phase P3; OWNER-DECISIONS
 * 465a): the plan and the API's answer into IndexedDB, and the map along it, fetched with the ride
 * corridor's own walk and pacing (corridor.ts `prefetchCorridor`: one request at a time, the stress
 * tiles through the protocol's queue and backoff, 250 ms apart, at most MAX_JOBS tiles and MAX_BYTES).
 * What is already kept (by another route, or by the ride under way) is not fetched again.
 *
 * The last ride (the installed app only) needs no fetch at all: End ride hands this module what the
 * ride kept (`adoptCorridor`) before clearing it.
 *
 * Tiles and ranges are shared between routes, so nothing may delete one a keep under way is about to
 * name. The Web Locks lock KEPT_LOCK orders it, across every tab of the site: each keep and each
 * hand-on holds it shared for its whole run, its final record write included; whatever frees storage
 * (Remove's freeing, the last ride's replacement, the sweep) takes it exclusive, and works out what to
 * free only once it holds it, from the records as they are then. Where the browser has no Web Locks,
 * the freeing waits for this page's keeps, and the sweep (which could take another tab's) is skipped.
 */
import { FetchSource, PMTiles } from "pmtiles";
import { BASEMAP } from "../stressStyle.js";
import { ByteBudget, CorridorSource, prefetchCorridor, type KeptRange, type PrefetchResult, type RangeStore, type TileJob } from "./corridor.ts";
import { corridorStress, styleExtraUrls, stressTileUrl, type CorridorSnapshot } from "./corridorStore.ts";
import type { LonLat } from "./geo.ts";
import { LAST_RIDE_ID, canKeep, keptFor, keptId, keptRecord, orphans, progressSaver, unreferenced, type KeepOutcome, type KeptRoute } from "./offlineRoutes.ts";
import * as idb from "./offlineRouteStore.ts";
import { fetchTile } from "./stressProtocol.ts";

export interface KeepRequest<A> {
  plan: string;
  title: string;
  distanceM: number;
  answer: A;
  line: readonly LonLat[];
}

/** What this module reads and writes (lib/offlineRouteStore.ts; a test gives an in-memory one). */
export interface KeptStore {
  listKept<A = unknown>(): Promise<KeptRoute<A>[]>;
  getKept<A = unknown>(id: string): Promise<KeptRoute<A> | undefined>;
  putKept(route: KeptRoute): Promise<void>;
  deleteKept(id: string): Promise<void>;
  hasTile(url: string): Promise<boolean>;
  putTile(url: string, response: Response): Promise<void>;
  deleteTiles(urls: readonly string[]): Promise<void>;
  getRange(key: string): Promise<KeptRange | undefined>;
  putRange(range: KeptRange): Promise<void>;
  deleteRanges(keys: readonly string[]): Promise<void>;
  tileKeys(): Promise<string[]>;
  rangeKeys(): Promise<string[]>;
  anyKept(): boolean;
  hasBucket(): Promise<boolean>;
}

const browserStore: KeptStore = {
  listKept: idb.listKept,
  getKept: idb.getKept,
  putKept: idb.putKept,
  deleteKept: idb.deleteKept,
  hasTile: idb.hasTile,
  putTile: idb.putTile,
  deleteTiles: idb.deleteTiles,
  getRange: (key) => idb.keptRanges.get(key),
  putRange: idb.putRange,
  deleteRanges: idb.deleteRanges,
  tileKeys: idb.tileKeys,
  rangeKeys: idb.rangeKeys,
  anyKept: idb.anyKept,
  hasBucket: idb.hasBucket,
};

/** The Web Locks name every tab of the site shares for the kept routes' storage. */
export const KEPT_LOCK = "routemaker-kept";

/** The part of `navigator.locks` used here. */
export interface LockManagerLike {
  request<T>(name: string, options: { mode: "shared" | "exclusive" }, callback: () => Promise<T>): Promise<T>;
}

export interface KeptLocks {
  /** A keep or a hand-on: many at once, never during a freeing. */
  shared<T>(work: () => Promise<T>): Promise<T>;
  /** A freeing: alone, after every keep and hand-on under way has ended. */
  exclusive<T>(work: () => Promise<T>): Promise<T>;
  /** Whether other tabs are held off too (Web Locks); without it the sweep is skipped. */
  readonly acrossTabs: boolean;
}

/** The locks over `manager` (navigator.locks), or this page's own ordering where there is none. */
export function keptLocks(manager: LockManagerLike | undefined): KeptLocks {
  if (manager) {
    return {
      shared: (work) => manager.request(KEPT_LOCK, { mode: "shared" }, work),
      exclusive: (work) => manager.request(KEPT_LOCK, { mode: "exclusive" }, work),
      acrossTabs: true,
    };
  }
  const running = new Set<Promise<unknown>>();
  return {
    shared<T>(work: () => Promise<T>): Promise<T> {
      const run = work();
      const settled = run.then(
        () => undefined,
        () => undefined,
      );
      running.add(settled);
      void settled.then(() => running.delete(settled));
      return run;
    },
    async exclusive<T>(work: () => Promise<T>): Promise<T> {
      while (running.size) await Promise.all([...running]);
      return work();
    },
    acrossTabs: false,
  };
}

/** What a walk gets to keep the map with (the route's names are noted as each is kept). */
export interface MapKeeping {
  /** A tile, glyph or sprite: named for the route, then written if not there. */
  keepUrl(url: string, load: () => Promise<Response>): Promise<boolean>;
  /** The base map's ranges, as the keeping archive's store: every range read or written is named. */
  ranges: RangeStore;
  budget: ByteBudget;
}

/** The walk along the line (the corridor's; a test gives its own). */
export type MapWalk = (line: readonly LonLat[], keeping: MapKeeping, signal: AbortSignal) => Promise<PrefetchResult>;

const PROTOBUF = { "Content-Type": "application/x-protobuf" };
/** How often a keep under way writes its record (each write carries the whole answer). */
const SAVE_EVERY_MS = 2000;

const corridorWalk: MapWalk = (line, keeping, signal) => {
  const source = new CorridorSource(new FetchSource(BASEMAP.path), keeping.ranges, keeping.budget);
  source.keeping = true;
  const archive = new PMTiles(source);
  const fetchJob = async (job: TileJob, jobSignal: AbortSignal): Promise<boolean> => {
    if (job.kind === "base") {
      await archive.getZxy(job.z, job.x, job.y, jobSignal);
      return true;
    }
    const url = stressTileUrl(job.z, job.x, job.y);
    if (url === null) return false;
    return keeping.keepUrl(url, async () => {
      // A tile the ride under way already holds is not fetched again; else through the page's queue.
      const data = (await corridorStress.kept(url)) ?? (await fetchTile(url, { signal: jobSignal }));
      return new Response(data, { headers: PROTOBUF });
    });
  };
  const extras = async (extraSignal: AbortSignal) => {
    for (const url of styleExtraUrls()) {
      if (extraSignal.aborted) return;
      await keeping.keepUrl(url, () => fetch(url, { signal: extraSignal })).catch(() => false);
    }
  };
  return prefetchCorridor(line, { fetch: fetchJob, extras, full: () => keeping.budget.full, signal, done: new Set() });
};

let store: KeptStore = browserStore;
let locks: KeptLocks = keptLocks(typeof navigator !== "undefined" ? (navigator as { locks?: LockManagerLike }).locks : undefined);
let walk: MapWalk = corridorWalk;

/** Tests: an in-memory store, fake locks and a walk of their own. */
export function setKeptDeps(deps: { store?: KeptStore; locks?: KeptLocks; walk?: MapWalk }): void {
  store = deps.store ?? store;
  locks = deps.locks ?? locks;
  walk = deps.walk ?? walk;
}

/** This page's keeps under way, by route id: Remove of that route stops it and waits for it first. */
const keeping = new Map<string, { controller: AbortController; done: Promise<unknown> }>();

/**
 * Keep a route: its record at once (so it is listed, and opens with no signal, even before the map
 * along it is in), then the map along it. Resolves with what the keep press says. `signal` stops it
 * (Start ride); what was kept by then stays named.
 */
export function keepRoute<A>(request: KeepRequest<A>, signal?: AbortSignal): Promise<{ outcome: KeepOutcome; route?: KeptRoute<A> }> {
  const id = keptId(request.plan, false);
  const controller = new AbortController();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  const done = locks.shared(() => keepRouteNow(id, request, controller.signal));
  const entry = { controller, done };
  keeping.set(id, entry);
  void done.then(
    () => keeping.get(id) === entry && keeping.delete(id),
    () => keeping.get(id) === entry && keeping.delete(id),
  );
  return done;
}

async function keepRouteNow<A>(id: string, request: KeepRequest<A>, signal: AbortSignal): Promise<{ outcome: KeepOutcome; route?: KeptRoute<A> }> {
  const existing = await store.listKept<A>();
  if (!canKeep(existing, id)) return { outcome: "full" };
  const before = existing.find((r) => r.id === id);
  const route = keptRecord({ id, plan: request.plan, title: request.title, distanceM: request.distanceM, answer: request.answer, lastRide: false }, before, Date.now());
  try {
    await store.putKept(route);
  } catch {
    return { outcome: "failed" };
  }
  let result: PrefetchResult;
  try {
    result = await keepMap(request.line, route, signal);
  } catch {
    return { outcome: "failed" };
  }
  const outcome: KeepOutcome = result.kept === 0 && result.total > 0 ? "no-map" : result.capped || result.failed > 0 || result.stopped ? "partial" : "kept";
  return { outcome, route };
}

/**
 * The map along `line`, into the kept routes' store. Each tile and range is named for the route before
 * it is written, and the record goes to the store every SAVE_EVERY_MS and at the end; the shared lock
 * the caller holds keeps every freeing off until that end.
 */
async function keepMap<A>(line: readonly LonLat[], route: KeptRoute<A>, signal: AbortSignal): Promise<PrefetchResult> {
  const ranges = new Set<string>(route.ranges);
  const tiles = new Set<string>(route.tiles);
  const bytes = { n: route.bytes };
  const saver = progressSaver(async () => {
    route.ranges = [...ranges];
    route.tiles = [...tiles];
    route.bytes = bytes.n;
    await store.putKept(route);
  }, SAVE_EVERY_MS);
  const budget = new ByteBudget();
  const name = (set: Set<string>, key: string) => {
    if (set.has(key)) return;
    set.add(key);
    saver.noted();
  };
  const rangeStore: RangeStore = {
    async get(key) {
      const kept = await store.getRange(key).catch(() => undefined);
      if (kept) name(ranges, key);
      return kept;
    },
    async put(range: KeptRange) {
      name(ranges, range.key);
      await store.putRange(range);
      bytes.n += range.data.byteLength;
    },
    // Never: other routes share these ranges, and only a freeing removes them.
    async clear() {},
  };
  const keepUrl = async (url: string, load: () => Promise<Response>): Promise<boolean> => {
    if (await store.hasTile(url)) {
      name(tiles, url);
      return true;
    }
    const response = await load();
    if (!response.ok) return false;
    const data = await response.arrayBuffer();
    if (!budget.take(data.byteLength)) return false;
    name(tiles, url);
    await store.putTile(url, new Response(data, { headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream" } }));
    bytes.n += data.byteLength;
    return true;
  };
  let result: PrefetchResult | null = null;
  try {
    result = await walk(line, { keepUrl, ranges: rangeStore, budget }, signal);
  } finally {
    route.complete = !!result && !result.capped && !result.stopped && result.failed === 0;
    await saver.flush();
  }
  return result;
}

/**
 * Start ride in the installed app: the ride's route is kept as the last ride (replacing the one
 * before), with no map yet; End ride hands it the ride's own (`adoptCorridor`). Its freeing waits for
 * any keep under way (a Keep for offline Start ride has just stopped included) to write its record.
 */
export function keepLastRide<A>(request: Omit<KeepRequest<A>, "line">): Promise<void> {
  return locks.exclusive(async () => {
    const before = await store.getKept<A>(LAST_RIDE_ID);
    // Not one of the rider's ten (canKeep): the next ride replaces it.
    const route = keptRecord({ id: LAST_RIDE_ID, plan: request.plan, title: request.title, distanceM: request.distanceM, answer: request.answer, lastRide: true }, undefined, Date.now());
    await store.putKept(route);
    if (before) await freeFor(before);
  });
}

/** End ride in the installed app: what the ride kept becomes the last ride's map. */
export function adoptCorridor(kept: CorridorSnapshot): Promise<void> {
  return locks.shared(() => adoptNow(kept));
}

async function adoptNow(kept: CorridorSnapshot): Promise<void> {
  const route = await store.getKept(LAST_RIDE_ID);
  if (!route) return;
  // Named before they are copied, so a copy cut short leaves nothing unnamed (a name with no tile is harmless).
  route.ranges = kept.ranges.map((r) => r.key);
  route.tiles = [...new Set([...kept.tiles.map((t) => t.url), ...styleExtraUrls()])];
  await store.putKept(route);
  let bytes = 0;
  for (const range of kept.ranges) {
    await store.putRange(range);
    bytes += range.data.byteLength;
  }
  for (const tile of kept.tiles) {
    await store.putTile(tile.url, new Response(tile.data, { headers: PROTOBUF }));
    bytes += tile.data.byteLength;
  }
  const tiles = new Set(kept.tiles.map((t) => t.url));
  // The glyphs and sprite: the ride fetched them into the HTTP cache, which answers these at once.
  for (const url of styleExtraUrls()) {
    try {
      if (await store.hasTile(url)) {
        tiles.add(url);
        continue;
      }
      const response = await fetch(url);
      if (!response.ok) continue;
      const data = await response.arrayBuffer();
      await store.putTile(url, new Response(data, { headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream" } }));
      tiles.add(url);
      bytes += data.byteLength;
    } catch {
      // Labels and icons may be missing offline; the tiles still show.
    }
  }
  route.ranges = kept.ranges.map((r) => r.key);
  route.tiles = [...tiles];
  route.bytes = bytes;
  route.complete = kept.ranges.length > 0 && kept.tiles.length > 0;
  await store.putKept(route);
}

/** Inside the exclusive lock, once `removed`'s record is gone or replaced: what it used that no record names now. */
async function freeFor(removed: KeptRoute): Promise<void> {
  const free = orphans(removed, await store.listKept());
  await store.deleteTiles(free.tiles).catch(() => undefined);
  await store.deleteRanges(free.ranges).catch(() => undefined);
}

/**
 * Settings' Remove: the record at once (the list shows it gone), then, once no keep runs, the tiles and
 * ranges no record names. A keep of this same route in this page is stopped and waited for first, so
 * its last record write cannot bring the route back.
 */
export async function removeKept(id: string): Promise<{ freed: Promise<void> }> {
  const running = keeping.get(id);
  if (running) {
    running.controller.abort();
    await running.done.catch(() => undefined);
  }
  const removed = await store.getKept(id);
  if (!removed) return { freed: Promise.resolve() };
  await store.deleteKept(id);
  await store.listKept();
  // Resolves now (the list and the announcement need not wait); the storage is freed when the lock allows.
  const freed = locks
    .exclusive(async () => {
      await freeFor(removed);
      await sweepNow();
    })
    .catch(() => undefined);
  return { freed };
}

/**
 * Delete what the store holds that no kept route names (a keep or a removal cut short, in this tab or
 * another, now or on an earlier visit). Run after a removal and once a while after load, in the
 * exclusive lock; skipped where the browser has no Web Locks (it could take another tab's keep).
 */
export function sweepKept(): Promise<void> {
  if (!locks.acrossTabs) return Promise.resolve();
  return locks.exclusive(sweepNow);
}

async function sweepNow(): Promise<void> {
  if (!locks.acrossTabs) return;
  // Nothing counted and no bucket: nothing to sweep, and the database is not opened.
  if (!store.anyKept() && !(await store.hasBucket())) return;
  try {
    const routes = await store.listKept();
    const tiles = await store.tileKeys();
    const ranges = await store.rangeKeys().catch(() => [] as string[]);
    const base = typeof location === "undefined" ? "http://localhost/" : location.href;
    const free = unreferenced(routes, tiles, ranges, (url) => new URL(url, base).href);
    await store.deleteTiles(free.tiles);
    await store.deleteRanges(free.ranges);
  } catch {
    // Storage refused: the next sweep tries again.
  }
}

/** The kept answer for a plan, when the planner cannot be reached (App.tsx's route scheduler). */
export async function keptAnswerFor<A>(plan: string): Promise<KeptRoute<A> | undefined> {
  return keptFor(await store.listKept<A>(), plan);
}
