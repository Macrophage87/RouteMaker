// Keeping routes for offline (lib/offlineKeep.ts): nothing frees a tile a keep under way is about to
// name. An in-memory store, a fake of the Web Locks manager (shared and exclusive, first come first
// served, as the browser's), and walks that stop where a test says.
import assert from "node:assert/strict";
import { test } from "node:test";
import type { KeptRange, PrefetchResult } from "./corridor.ts";
import { LAST_RIDE_ID, type KeptRoute } from "./offlineRoutes.ts";
import { keepLastRide, keepRoute, keptLocks, removeKept, setKeptDeps, sweepKept, type KeptStore, type LockManagerLike, type MapKeeping } from "./offlineKeep.ts";

function memoryStore() {
  const records = new Map<string, KeptRoute>();
  const tiles = new Map<string, ArrayBuffer>();
  const ranges = new Map<string, KeptRange>();
  const copy = <T>(r: T): T => structuredClone(r);
  const store: KeptStore = {
    listKept: async <A>() => [...records.values()].map(copy) as KeptRoute<A>[],
    getKept: async <A>(id: string) => (records.has(id) ? (copy(records.get(id)) as KeptRoute<A>) : undefined),
    putKept: async (route) => void records.set(route.id, copy(route)),
    deleteKept: async (id) => void records.delete(id),
    hasTile: async (url) => tiles.has(url),
    putTile: async (url, response) => void tiles.set(url, await response.arrayBuffer()),
    deleteTiles: async (urls) => urls.forEach((u) => tiles.delete(u)),
    getRange: async (key) => ranges.get(key),
    putRange: async (range) => void ranges.set(range.key, range),
    deleteRanges: async (keys) => keys.forEach((k) => ranges.delete(k)),
    tileKeys: async () => [...tiles.keys()].map((u) => new URL(u, "http://localhost/").href),
    rangeKeys: async () => [...ranges.keys()],
    anyKept: () => records.size > 0,
    hasBucket: async () => tiles.size > 0,
  };
  return { store, records, tiles, ranges };
}

/** Web Locks for one name: shared holders together, an exclusive one alone, granted in request order. */
function fakeLockManager(): LockManagerLike {
  let shared = 0;
  let exclusive = false;
  const queue: { mode: "shared" | "exclusive"; start: () => void }[] = [];
  const pump = () => {
    while (queue.length) {
      const next = queue[0];
      if (next.mode === "exclusive" ? shared > 0 || exclusive : exclusive) return;
      if (next.mode === "exclusive") exclusive = true;
      else shared += 1;
      queue.shift();
      next.start();
    }
  };
  return {
    request<T>(_name: string, { mode }: { mode: "shared" | "exclusive" }, callback: () => Promise<T>): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        queue.push({
          mode,
          start: () =>
            void callback()
              .then(resolve, reject)
              .finally(() => {
                if (mode === "exclusive") exclusive = false;
                else shared -= 1;
                pump();
              }),
        });
        pump();
      });
    },
  };
}

const RESULT: PrefetchResult = { kept: 2, failed: 0, total: 2, stress: { kept: 2, total: 2 }, base: { kept: 0, total: 0 }, capped: false, stopped: false };
const tile = (n: number) => `/tiles/stress/14/1/${n}.pbf`;
const body = () => Promise.resolve(new Response(new Uint8Array([1, 2, 3])));
const kept = (id: string, tiles: string[], over: Partial<KeptRoute> = {}): KeptRoute => ({
  id,
  plan: id,
  title: id,
  distanceM: 1000,
  savedAt: 0,
  lastRide: false,
  answer: null,
  tiles,
  ranges: [],
  bytes: 0,
  complete: true,
  ...over,
});
const request = (plan: string) => ({ plan, title: plan, distanceM: 2000, answer: null, line: [] });
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

test("Remove of another route during a keep: the tiles they share stay, and the keep ends complete with all of them", async () => {
  const m = memoryStore();
  m.records.set("#a", kept("#a", [tile(1), tile(2)]));
  m.tiles.set(tile(1), new ArrayBuffer(3));
  m.tiles.set(tile(2), new ArrayBuffer(3));
  let release = () => {};
  const walk = async (_line: unknown, k: MapKeeping) => {
    await k.keepUrl(tile(1), body); // already kept (by A): named, not fetched
    await k.keepUrl(tile(3), body);
    await new Promise<void>((resolve) => (release = resolve));
    return RESULT;
  };
  setKeptDeps({ store: m.store, locks: keptLocks(fakeLockManager()), walk });
  const keeping = keepRoute(request("#b"));
  await tick();
  const { freed } = await removeKept("#a");
  assert.equal(m.records.has("#a"), false, "the record goes at once");
  await tick();
  assert.ok(m.tiles.has(tile(2)), "nothing is freed while the keep runs");
  release();
  assert.equal((await keeping).outcome, "kept");
  await freed;
  assert.ok(m.tiles.has(tile(1)), "the shared tile stays: B names it");
  assert.ok(m.tiles.has(tile(3)));
  assert.equal(m.tiles.has(tile(2)), false, "what only A used is freed");
  const b = m.records.get("#b");
  assert.deepEqual([...(b?.tiles ?? [])].sort(), [tile(1), tile(3)]);
  assert.equal(b?.complete, true);
});

test("Start ride right after Keep: the stopped keep writes its record before the last ride frees anything", async () => {
  const m = memoryStore();
  // The last ride before used tile 1, which the keep under way is about to name.
  m.records.set(LAST_RIDE_ID, kept(LAST_RIDE_ID, [tile(1), tile(9)], { lastRide: true }));
  m.tiles.set(tile(1), new ArrayBuffer(3));
  m.tiles.set(tile(9), new ArrayBuffer(3));
  const walk = async (_line: unknown, k: MapKeeping, signal: AbortSignal) => {
    await k.keepUrl(tile(1), body);
    await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    await tick();
    return { ...RESULT, stopped: true };
  };
  setKeptDeps({ store: m.store, locks: keptLocks(fakeLockManager()), walk });
  const controller = new AbortController();
  const keeping = keepRoute(request("#b"), controller.signal);
  await tick();
  controller.abort();
  await keepLastRide({ plan: "#ride", title: "ride", distanceM: 3000, answer: null });
  assert.equal((await keeping).outcome, "partial");
  assert.ok(m.tiles.has(tile(1)), "the stopped keep's tile stays: its record names it");
  assert.equal(m.tiles.has(tile(9)), false, "what only the old last ride used is freed");
  assert.equal(m.records.get(LAST_RIDE_ID)?.plan, "#ride");
});

test("Remove of the route being kept stops the keep first, so its last write cannot bring the route back", async () => {
  const m = memoryStore();
  const walk = async (_line: unknown, k: MapKeeping, signal: AbortSignal) => {
    await k.keepUrl(tile(5), body);
    await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve(), { once: true }));
    return { ...RESULT, stopped: true };
  };
  setKeptDeps({ store: m.store, locks: keptLocks(fakeLockManager()), walk });
  const keeping = keepRoute(request("#b"));
  await tick();
  const { freed } = await removeKept("#b");
  await keeping;
  await freed;
  assert.equal(m.records.has("#b"), false);
  assert.equal(m.tiles.has(tile(5)), false, "its tile is freed");
});

test("with no Web Locks, the sweep is skipped and a freeing still waits for this page's keeps", async () => {
  const m = memoryStore();
  m.tiles.set(tile(7), new ArrayBuffer(3)); // named by nothing yet
  let release = () => {};
  const walk = async (_line: unknown, k: MapKeeping) => {
    await k.keepUrl(tile(8), body);
    await new Promise<void>((resolve) => (release = resolve));
    return RESULT;
  };
  m.records.set("#a", kept("#a", [tile(8)]));
  m.tiles.set(tile(8), new ArrayBuffer(3));
  setKeptDeps({ store: m.store, locks: keptLocks(undefined), walk });
  await sweepKept();
  assert.ok(m.tiles.has(tile(7)), "no sweep: another tab's keep could own it");
  const keeping = keepRoute(request("#b"));
  await tick();
  const { freed } = await removeKept("#a");
  await tick();
  assert.ok(m.tiles.has(tile(8)), "waits for the keep");
  release();
  await keeping;
  await freed;
  assert.ok(m.tiles.has(tile(8)), "B names it now");
});
