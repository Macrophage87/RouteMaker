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

test("prefetchCorridor: one at a time, paced, stress tiles 250 ms apart; done keys kept", async () => {
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
    signal: new AbortController().signal,
    done,
  });
  assert.equal(most, 1, "never two at once");
  assert.equal(result.kept, result.total);
  assert.equal(done.size, result.total);
  assert.deepEqual(waits, order.map((k) => (k === "stress" ? STRESS_GAP_MS : BASE_GAP_MS)));
  assert.equal(corridorNote(result), "The map along the route is saved for dead spots.");
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

test("CorridorSource: the kept routes' ranges (the fallback) answer only when the network fails, with the archive's ETag, and are never written", async () => {
  const { source: inner, state } = fakeArchive("v1");
  const store = memoryRangeStore();
  const saved = memoryRangeStore();
  await saved.put({ key: "0:16384", etag: "v1", data: new Uint8Array([7]).buffer });
  await saved.put({ key: "500:40", etag: "v1", data: new Uint8Array([8]).buffer });
  await saved.put({ key: "600:40", etag: "v0", data: new Uint8Array([9]).buffer });
  const reads: string[] = [];
  const fallback = { get: async (key: string) => (reads.push(key), saved.get(key)) };
  const source = new CorridorSource(inner, store, new ByteBudget(), fallback);
  // Online, outside a ride: the network, and the fallback is not read.
  assert.deepEqual([...new Uint8Array((await source.getBytes(500, 40, undefined, "v1")).data)], [500 % 256, 40]);
  assert.deepEqual(reads, []);
  // Offline, outside a ride: the header and a tile from the kept routes; a range of another file is refused.
  state.online = false;
  assert.deepEqual([...new Uint8Array((await source.getBytes(0, 16384)).data)], [7]);
  assert.deepEqual([...new Uint8Array((await source.getBytes(500, 40, undefined, "v1")).data)], [8]);
  await assert.rejects(() => source.getBytes(600, 40, undefined, "v1"));
  await assert.rejects(() => source.getBytes(700, 40, undefined, "v1"));
  // End ride's clear leaves the kept routes alone.
  await source.clear();
  assert.equal(saved.ranges.size, 3);
  assert.equal(store.ranges.size, 0);
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
