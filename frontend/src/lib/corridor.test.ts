// Ride mode in dead spots (WEB-NAV-plan.md section 6, N5): which tiles the corridor holds, the
// prefetch's pacing and caps, the base map's kept byte ranges, and the glyphs.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { RangeResponse, Source } from "pmtiles";
import { lonLatToTile, type LonLat } from "./geo.ts";
import { METRES_PER_MILE } from "./format.ts";
import {
  BASE_GAP_MS,
  ByteBudget,
  CorridorSource,
  MAX_JOBS,
  START_JITTER_MS,
  STOP_AFTER_FAILURES,
  STRESS_GAP_MS,
  corridorJobs,
  corridorNote,
  corridorTiles,
  fontStacks,
  glyphUrls,
  jobKey,
  memoryRangeStore,
  prefetchCorridor,
  type TileJob,
} from "./corridor.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

test("corridorTiles: every tile within 1,000 ft of the line, in the order the line reaches them", () => {
  const line = [at(0, 0), at(5000, 0)];
  const tiles = corridorTiles(line, 14);
  const first = lonLatToTile(line[0], 14);
  const last = lonLatToTile(line[1], 14);
  assert.deepEqual([tiles[0].x, tiles[0].y].length, 2);
  assert.ok(tiles.some((t) => t.x === first.x && t.y === first.y));
  assert.ok(tiles.some((t) => t.x === last.x && t.y === last.y));
  // In route order: the start's column comes before the end's.
  assert.ok(tiles.findIndex((t) => t.x === first.x) < tiles.findIndex((t) => t.x === last.x));
  // Every column between the two ends is there (no gap between two samples).
  for (let x = first.x; x <= last.x; x += 1) assert.ok(tiles.some((t) => t.x === x), `column ${x}`);
  // And the buffer reaches across: a point 250 m north of the middle is in a listed tile.
  const north = lonLatToTile(at(2500, 250), 14);
  assert.ok(tiles.some((t) => t.x === north.x && t.y === north.y));
  // No tile twice.
  assert.equal(new Set(tiles.map((t) => `${t.x}/${t.y}`)).size, tiles.length);
});

test("corridorJobs: deepest zooms first, the stress and base map's alternately; a 30 mi ride fits under MAX_JOBS", () => {
  const line = [at(0, 0), at(5000, 0)];
  const { jobs, capped } = corridorJobs(line);
  assert.equal(capped, false);
  assert.equal(jobs[0].kind, "stress");
  assert.equal(jobs[0].z, 14);
  assert.deepEqual([...new Set(jobs.map((j) => `${j.kind}${j.z}`))], ["stress14", "base15", "stress13", "base14", "stress12", "base13", "base12"]);
  // A 30 mi (48 km) ride, zig-zagging: under the cap.
  const long: LonLat[] = [];
  for (let i = 0; i <= 24; i += 1) long.push(at(i * 2000, i % 2 ? 0 : 500));
  const thirty = corridorJobs(long);
  assert.ok(long.length && thirty.jobs.length < MAX_JOBS && !thirty.capped, `${thirty.jobs.length} tiles for ${(48_000 / METRES_PER_MILE).toFixed(0)} mi`);
  // Done ones are left out (a re-plan fetches only what is new), and the cap is honoured.
  const done = new Set(jobs.slice(0, 5).map(jobKey));
  assert.equal(corridorJobs(line, done).jobs.length, jobs.length - 5);
  const small = corridorJobs(line, new Set(), 3);
  assert.equal(small.jobs.length, 3);
  assert.equal(small.capped, true);
});

test("prefetchCorridor: a short random start, then one at a time, paced; done keys kept", async () => {
  const line = [at(0, 0), at(800, 0)];
  const order: string[] = [];
  const waits: number[] = [];
  let inFlight = 0;
  let most = 0;
  const done = new Set<string>();
  const result = await prefetchCorridor(line, {
    fetch: async (job: TileJob) => {
      inFlight += 1;
      most = Math.max(most, inFlight);
      order.push(job.kind);
      await Promise.resolve();
      inFlight -= 1;
      return true;
    },
    wait: async (ms) => void waits.push(ms),
    random: () => 0.5,
    signal: new AbortController().signal,
    done,
  });
  assert.equal(most, 1, "never two at once");
  assert.equal(result.kept, result.total);
  assert.equal(done.size, result.total);
  assert.equal(result.stress.kept + result.base.kept, result.kept);
  assert.equal(result.stress.total + result.base.total, result.total);
  assert.deepEqual(waits, [START_JITTER_MS / 2, ...order.map((k) => (k === "stress" ? STRESS_GAP_MS : BASE_GAP_MS))]);
  assert.ok(STRESS_GAP_MS >= 400 && STRESS_GAP_MS <= 500, "stress tiles 400 to 500 ms apart");
  assert.equal(corridorNote(result), "The map along the route is saved for dead spots.");
});

test("corridorNote: says which kind was saved, and only what was", () => {
  const result = (stress: number, base: number, capped = false) => ({
    kept: stress + base,
    failed: 0,
    total: 20,
    stress: { kept: stress, total: 10 },
    base: { kept: base, total: 10 },
    capped,
    stopped: false,
  });
  assert.equal(corridorNote(result(10, 0)), "Only the stress lines along the route are saved for dead spots, not the base map.");
  assert.equal(corridorNote(result(0, 10)), "Only the base map along the route is saved for dead spots, not the stress lines.");
  assert.equal(corridorNote(result(3, 3, true)), "The map along the first part of the route is saved for dead spots.");
  assert.match(corridorNote(result(0, 0)), /could not be saved/);
});

test("prefetchCorridor: a kind failing in a row is stopped (no signal, or no base map served); End ride stops it all", async () => {
  const line = [at(0, 0), at(3000, 0)];
  const asked = { stress: 0, base: 0 };
  const result = await prefetchCorridor(line, {
    fetch: async (job) => {
      asked[job.kind] += 1;
      if (job.kind === "base") throw new Error("404");
      return true;
    },
    wait: async () => undefined,
    signal: new AbortController().signal,
    done: new Set(),
  });
  assert.equal(asked.base, STOP_AFTER_FAILURES);
  assert.ok(asked.stress > STOP_AFTER_FAILURES);
  assert.equal(result.failed, STOP_AFTER_FAILURES);

  const controller = new AbortController();
  let count = 0;
  const stopped = await prefetchCorridor(line, {
    fetch: async () => {
      count += 1;
      if (count === 3) controller.abort();
      return true;
    },
    wait: async () => undefined,
    signal: controller.signal,
    done: new Set(),
  });
  assert.equal(stopped.stopped, true);
  assert.equal(count, 3);
  assert.equal(corridorNote(stopped), "");

  const none = await prefetchCorridor(line, { fetch: async () => false, wait: async () => undefined, signal: new AbortController().signal, done: new Set() });
  assert.equal(none.kept, 0);
  assert.match(corridorNote(none), /could not be saved/);
  assert.equal(corridorNote("saving"), "Saving the map along the route for dead spots…");
});

test("prefetchCorridor: stops when the kept bytes reach the cap", async () => {
  let count = 0;
  const result = await prefetchCorridor([at(0, 0), at(3000, 0)], {
    fetch: async () => {
      count += 1;
      return true;
    },
    full: () => count >= 4,
    wait: async () => undefined,
    signal: new AbortController().signal,
    done: new Set(),
  });
  assert.equal(count, 4);
  assert.equal(result.capped, true);
  assert.match(corridorNote(result), /first part of the route/);
});

test("prefetchCorridor with a real ByteBudget: the first refused tile stops it (tiles never fill it exactly)", async () => {
  const budget = new ByteBudget(1000);
  let count = 0;
  const result = await prefetchCorridor([at(0, 0), at(3000, 0)], {
    // Each tile is 300 bytes: 900 fit, the fourth is refused, and 900 is under the cap.
    fetch: async () => {
      count += 1;
      return budget.take(300);
    },
    full: () => budget.full,
    wait: async () => undefined,
    random: () => 0,
    signal: new AbortController().signal,
    done: new Set(),
  });
  assert.equal(count, 4);
  assert.equal(budget.bytes, 900);
  assert.equal(result.capped, true);
  assert.equal(result.kept, 3);
  budget.give(300);
  assert.equal(budget.full, false, "bytes given back make room again");
});

/** A source over a fake archive: `online` decides whether the network answers. */
function fakeArchive(etag = "v1") {
  const state = { online: true, etag, asked: [] as string[] };
  const source: Source = {
    getKey: () => "/basemap/region.pmtiles",
    getBytes: async (offset: number, length: number, _signal?: AbortSignal, wanted?: string): Promise<RangeResponse> => {
      state.asked.push(`${offset}:${length}`);
      if (!state.online) throw new TypeError("Failed to fetch");
      if (wanted && wanted !== state.etag) throw new Error("etag mismatch");
      return { data: new Uint8Array([offset % 256, length % 256]).buffer, etag: state.etag };
    },
  };
  return { source, state };
}

test("CorridorSource: while keeping, ranges are kept and answer when the network fails", async () => {
  const { source: inner, state } = fakeArchive();
  const store = memoryRangeStore();
  const source = new CorridorSource(inner, store, new ByteBudget());
  // Not riding: nothing kept.
  await source.getBytes(0, 16384);
  assert.equal(store.ranges.size, 0);
  source.keeping = true;
  await source.getBytes(0, 16384);
  await source.getBytes(500, 40, undefined, "v1");
  assert.equal(store.ranges.size, 2);
  // A kept range with the archive's ETag is answered without the network.
  const before = state.asked.length;
  const tile = await source.getBytes(500, 40, undefined, "v1");
  assert.equal(state.asked.length, before);
  assert.deepEqual([...new Uint8Array(tile.data)], [500 % 256, 40]);
  // The header (asked with no ETag) goes to the network first; offline, the kept one answers.
  state.online = false;
  const header = await source.getBytes(0, 16384);
  assert.equal(header.etag, "v1");
  // A range never kept still fails offline.
  await assert.rejects(() => source.getBytes(900, 10, undefined, "v1"));
});

test("CorridorSource: a refreshed archive (a new ETag) empties the store; End ride clears it; the budget caps it", async () => {
  const { source: inner, state } = fakeArchive("v1");
  const store = memoryRangeStore();
  const budget = new ByteBudget(5);
  const source = new CorridorSource(inner, store, budget);
  source.keeping = true;
  await source.getBytes(0, 16384);
  await source.getBytes(100, 10, undefined, "v1");
  assert.equal(store.ranges.size, 2);
  assert.equal(budget.bytes, 4);
  state.etag = "v2";
  await source.getBytes(0, 16384);
  assert.deepEqual([...store.ranges.keys()], ["0:16384"], "the old file's ranges went");
  assert.equal(store.ranges.get("0:16384")?.etag, "v2");
  assert.equal(budget.bytes, 2, "the old file's bytes were given back");
  // Up to the budget (5 bytes) kept, then not.
  await source.getBytes(200, 10, undefined, "v2");
  await source.getBytes(300, 10, undefined, "v2");
  assert.equal(store.ranges.has("200:10"), true);
  assert.equal(store.ranges.has("300:10"), false);
  await source.clear();
  assert.equal(store.ranges.size, 0);
  assert.equal(source.keeping, false);
});

test("CorridorSource: outside a ride with nothing kept, the store is never touched (the plain archive's reads)", async () => {
  const { source: inner, state } = fakeArchive();
  const reads: string[] = [];
  const store = { ...memoryRangeStore(), get: async (key: string) => void reads.push(key) };
  const source = new CorridorSource(inner, store, new ByteBudget());
  await source.getBytes(0, 16384);
  await source.getBytes(500, 40, undefined, "v1");
  state.online = false;
  await assert.rejects(() => source.getBytes(0, 16384));
  assert.deepEqual(reads, []);
});

test("CorridorSource: a range with no ETag, or one the store or budget refuses, is not kept and is counted", async () => {
  const { source: inner, state } = fakeArchive();
  const store = memoryRangeStore();
  const source = new CorridorSource(inner, store, new ByteBudget());
  source.keeping = true;
  state.etag = undefined as unknown as string;
  await source.getBytes(0, 16384);
  assert.equal(store.ranges.size, 0, "no ETag: a later file could not be told apart");
  assert.equal(source.keepFailures, 1);
  state.etag = "v1";
  const failing = new CorridorSource(inner, { ...memoryRangeStore(), put: async () => Promise.reject(new DOMException("full", "QuotaExceededError")) }, new ByteBudget());
  failing.keeping = true;
  const budgetBefore = failing.keepFailures;
  await failing.getBytes(0, 16384);
  assert.equal(failing.keepFailures, budgetBefore + 1);
});

test("CorridorSource: a write still in flight at End ride is not counted, and the store stays untouched after", async () => {
  const { source: inner, state } = fakeArchive();
  const base = memoryRangeStore();
  let release = () => {};
  const reads: string[] = [];
  const store = {
    ...base,
    get: async (key: string) => {
      reads.push(key);
      return base.get(key);
    },
    put: async (range: Parameters<typeof base.put>[0]) => {
      await new Promise<void>((resolve) => (release = resolve));
      await base.put(range);
    },
  };
  const budget = new ByteBudget();
  const source = new CorridorSource(inner, store, budget);
  source.keeping = true;
  const reading = source.getBytes(0, 16384);
  await new Promise((r) => setTimeout(r, 0));
  await source.clear(); // End ride, with the put still waiting
  release();
  await reading;
  assert.equal(budget.bytes, 0, "the in-flight write's bytes were given back");
  assert.equal(base.ranges.size, 0, "a write that landed after the clear is cleared again");
  state.online = false;
  await assert.rejects(() => source.getBytes(0, 16384));
  assert.deepEqual(reads, [], "outside the ride the store is not read");
});

test("CorridorSource: an aborted read is not answered from the store", async () => {
  const store = memoryRangeStore();
  await store.put({ key: "0:16384", etag: "v1", data: new ArrayBuffer(2) });
  const inner: Source = {
    getKey: () => "k",
    getBytes: async () => {
      throw new DOMException("aborted", "AbortError");
    },
  };
  const source = new CorridorSource(inner, store, new ByteBudget());
  source.keeping = true;
  await assert.rejects(() => source.getBytes(0, 16384), { name: "AbortError" });
});

test("fontStacks and glyphUrls: the style's Latin fonts, plain or inside expressions", () => {
  const layers = [
    { layout: { "text-font": ["Noto Sans Regular"] } },
    { layout: { "text-font": ["case", ["==", ["get", "script"], "Devanagari"], ["literal", ["Noto Sans Devanagari Regular v1"]], ["literal", ["Noto Sans Italic"]]] } },
    { layout: { "text-font": ["Noto Sans Medium"] } },
    { layout: {} },
    { paint: {} },
  ];
  assert.deepEqual(fontStacks(layers), ["Noto Sans Italic", "Noto Sans Medium", "Noto Sans Regular"]);
  assert.deepEqual(glyphUrls("https://x.test/basemap/fonts/{fontstack}/{range}.pbf", ["Noto Sans Regular"]), [
    "https://x.test/basemap/fonts/Noto Sans Regular/0-255.pbf",
    "https://x.test/basemap/fonts/Noto Sans Regular/256-511.pbf",
    "https://x.test/basemap/fonts/Noto Sans Regular/8192-8447.pbf",
  ]);
});
