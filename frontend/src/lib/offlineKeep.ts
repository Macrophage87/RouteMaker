/**
 * Keeping a route for offline (WEB-NAV-plan.md section 8 "Offline route", phase P3; OWNER-DECISIONS
 * 465a): the plan and the API's answer into IndexedDB, and the map along it, fetched with the ride
 * corridor's own walk and pacing (corridor.ts `prefetchCorridor`: one request at a time, the stress
 * tiles through the protocol's queue and backoff, 250 ms apart, at most MAX_JOBS tiles and MAX_BYTES).
 * What is already kept (by another route, or by the ride under way) is not fetched again.
 *
 * The last ride (the installed app only) needs no fetch at all: End ride hands this module what the
 * ride kept (`adoptCorridor`) before clearing it.
 */
import { FetchSource, PMTiles } from "pmtiles";
import { BASEMAP } from "../stressStyle.js";
import { ByteBudget, CorridorSource, prefetchCorridor, type KeptRange, type PrefetchResult, type RangeStore, type TileJob } from "./corridor.ts";
import { corridorStress, styleExtraUrls, stressTileUrl, type CorridorSnapshot } from "./corridorStore.ts";
import type { LonLat } from "./geo.ts";
import { LAST_RIDE_ID, canKeep, keptFor, keptId, orphans, type KeepOutcome, type KeptRoute } from "./offlineRoutes.ts";
import { deleteKept, deleteRanges, deleteTiles, getKept, hasTile, keptRanges, listKept, putKept, putRange, putTile } from "./offlineRouteStore.ts";
import { fetchTile } from "./stressProtocol.ts";

export interface KeepRequest<A> {
  plan: string;
  title: string;
  distanceM: number;
  answer: A;
  line: readonly LonLat[];
}

/** The kept ranges as the keeping archive's store: every range it reads or writes is noted for the route. */
function notingStore(noted: Set<string>, bytes: { n: number }): RangeStore {
  return {
    async get(key) {
      const kept = await keptRanges.get(key).catch(() => undefined);
      if (kept) noted.add(key);
      return kept;
    },
    async put(range: KeptRange) {
      await putRange(range);
      noted.add(range.key);
      bytes.n += range.data.byteLength;
    },
    // Never: other routes share these ranges, and only a removal frees them (offlineRoutes.ts orphans).
    async clear() {},
  };
}

const PROTOBUF = { "Content-Type": "application/x-protobuf" };

/**
 * Keep a route: its record at once (so it is listed, and opens with no signal, even before the map
 * along it is in), then the map along it. Resolves with what the keep press says.
 */
export async function keepRoute<A>(request: KeepRequest<A>, signal?: AbortSignal): Promise<{ outcome: KeepOutcome; route?: KeptRoute<A> }> {
  const id = keptId(request.plan, false);
  const existing = await listKept<A>();
  if (!canKeep(existing, id)) return { outcome: "full" };
  const route: KeptRoute<A> = {
    id,
    plan: request.plan,
    title: request.title,
    distanceM: request.distanceM,
    savedAt: Date.now(),
    lastRide: false,
    answer: request.answer,
    tiles: [],
    ranges: [],
    bytes: 0,
    complete: false,
  };
  try {
    await putKept(route);
  } catch {
    return { outcome: "failed" };
  }
  const result = await fetchMap(request.line, route, signal ?? new AbortController().signal);
  try {
    await putKept(route);
  } catch {
    return { outcome: "failed" };
  }
  const outcome: KeepOutcome = result.kept === 0 && result.total > 0 ? "no-map" : result.capped || result.failed > 0 || result.stopped ? "partial" : "kept";
  return { outcome, route };
}

async function fetchMap<A>(line: readonly LonLat[], route: KeptRoute<A>, signal: AbortSignal): Promise<PrefetchResult> {
  const ranges = new Set<string>(route.ranges);
  const tiles = new Set<string>(route.tiles);
  const bytes = { n: route.bytes };
  const budget = new ByteBudget();
  const source = new CorridorSource(new FetchSource(BASEMAP.path), notingStore(ranges, bytes), budget);
  source.keeping = true;
  const archive = new PMTiles(source);

  const keepUrl = async (url: string, load: () => Promise<Response>): Promise<boolean> => {
    if (await hasTile(url)) {
      tiles.add(url);
      return true;
    }
    const response = await load();
    if (!response.ok) return false;
    const data = await response.arrayBuffer();
    if (!budget.take(data.byteLength)) return false;
    await putTile(url, new Response(data, { headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream" } }));
    tiles.add(url);
    bytes.n += data.byteLength;
    return true;
  };

  const fetchJob = async (job: TileJob, jobSignal: AbortSignal): Promise<boolean> => {
    if (job.kind === "base") {
      await archive.getZxy(job.z, job.x, job.y, jobSignal);
      return true;
    }
    const url = stressTileUrl(job.z, job.x, job.y);
    if (url === null) return false;
    return keepUrl(url, async () => {
      // A tile the ride under way already holds is not fetched again; else through the page's queue.
      const data = (await corridorStress.kept(url)) ?? (await fetchTile(url, { signal: jobSignal }));
      return new Response(data, { headers: PROTOBUF });
    });
  };

  const extras = async (extraSignal: AbortSignal) => {
    for (const url of styleExtraUrls()) {
      if (extraSignal.aborted) return;
      await keepUrl(url, () => fetch(url, { signal: extraSignal })).catch(() => false);
    }
  };

  const result = await prefetchCorridor(line, { fetch: fetchJob, extras, full: () => budget.full, signal, done: new Set() });
  route.ranges = [...ranges];
  route.tiles = [...tiles];
  route.bytes = bytes.n;
  route.complete = !result.capped && !result.stopped && result.failed === 0;
  return result;
}

/**
 * Start ride in the installed app: the ride's route is kept as the last ride (replacing the one
 * before), with no map yet; End ride hands it the ride's own (`adoptCorridor`).
 */
export async function keepLastRide<A>(request: Omit<KeepRequest<A>, "line">): Promise<void> {
  const before = await getKept<A>(LAST_RIDE_ID);
  const route: KeptRoute<A> = {
    id: LAST_RIDE_ID,
    plan: request.plan,
    title: request.title,
    distanceM: request.distanceM,
    savedAt: Date.now(),
    lastRide: true,
    answer: request.answer,
    tiles: [],
    ranges: [],
    bytes: 0,
    complete: false,
  };
  const others = (await listKept()).filter((r) => r.id !== LAST_RIDE_ID);
  if (before) await freeFor(before, others);
  // Ten kept by the rider already: the last ride is not kept (theirs come first).
  if (!canKeep(others, LAST_RIDE_ID)) {
    if (before) await deleteKept(LAST_RIDE_ID);
    return;
  }
  await putKept(route);
  await listKept();
}

/** End ride in the installed app: what the ride kept becomes the last ride's map. */
export async function adoptCorridor(kept: CorridorSnapshot): Promise<void> {
  const route = await getKept(LAST_RIDE_ID);
  if (!route) return;
  let bytes = 0;
  for (const range of kept.ranges) {
    await putRange(range);
    bytes += range.data.byteLength;
  }
  for (const tile of kept.tiles) {
    await putTile(tile.url, new Response(tile.data, { headers: PROTOBUF }));
    bytes += tile.data.byteLength;
  }
  const tiles = new Set(kept.tiles.map((t) => t.url));
  // The glyphs and sprite: the ride fetched them into the HTTP cache, which answers these at once.
  for (const url of styleExtraUrls()) {
    try {
      if (await hasTile(url)) {
        tiles.add(url);
        continue;
      }
      const response = await fetch(url);
      if (!response.ok) continue;
      const data = await response.arrayBuffer();
      await putTile(url, new Response(data, { headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/octet-stream" } }));
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
  await putKept(route);
}

async function freeFor(removed: KeptRoute, remaining: readonly KeptRoute[]): Promise<void> {
  const free = orphans(removed, remaining);
  await deleteTiles(free.tiles).catch(() => undefined);
  await deleteRanges(free.ranges).catch(() => undefined);
}

/** Settings' Remove: the record, and the tiles and ranges no other kept route uses. */
export async function removeKept(id: string): Promise<void> {
  const all = await listKept();
  const removed = all.find((r) => r.id === id);
  if (!removed) return;
  await deleteKept(id);
  await freeFor(removed, all.filter((r) => r.id !== id));
  await listKept();
}

/** The kept answer for a plan, when the planner cannot be reached (App.tsx's route scheduler). */
export async function keptAnswerFor<A>(plan: string): Promise<KeptRoute<A> | undefined> {
  return keptFor(await listKept<A>(), plan);
}
