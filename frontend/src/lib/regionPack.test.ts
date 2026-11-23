// The region packs for riding off grid (lib/regionPack.ts): listed, downloaded and checked, kept (one, several or the
// whole map), deleted, and the one covering the rider opened for a ride.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import {
  areaName,
  covers,
  downloadPack,
  downloads,
  fetchPackList,
  keptPacks,
  mapDateText,
  openPack,
  packFor,
  removeAll,
  removePack,
  ridePacks,
  type PackList,
  type PackStore,
} from "./regionPack.ts";

// localStorage, as a phone has it.
const items = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (k: string) => items.get(k) ?? null,
    setItem: (k: string, v: string) => void items.set(k, v),
    removeItem: (k: string) => void items.delete(k),
  },
});
beforeEach(() => items.clear());

const GRAPH = { v: 1, nodes: [-77000000, 38900000, -77001000, 38900000], edges: [0, 1, 87, 2, 0, -1], names: [] };
const GZ = gzipSync(JSON.stringify(GRAPH));
const SHA = createHash("sha256").update(GZ).digest("hex");
const asBuffer = (b: Buffer) => b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;
// A second pack's bytes: the same network, another file.
const GZ2 = gzipSync(JSON.stringify({ ...GRAPH, names: ["Other"] }));
const SHA2 = createHash("sha256").update(GZ2).digest("hex");
const GZ3 = gzipSync(JSON.stringify({ ...GRAPH, names: ["Whole"] }));
const SHA3 = createHash("sha256").update(GZ3).digest("hex");

// Squares for areas: the Beltway in the middle of Northern Virginia's square, which cuts it out; the rest is the box less both.
const BELTWAY: [number, number][] = [[-77.2, 38.8], [-76.9, 38.8], [-76.9, 39.0], [-77.2, 39.0], [-77.2, 38.8]];
const NOVA: [number, number][] = [[-78, 38.3], [-76.8, 38.3], [-76.8, 39.1], [-78, 39.1], [-78, 38.3]];
const url = (id: string) => `/offline-packs/packs-20261115T125405Z/${id}.json.gz`;
const LISTED = {
  build_id: "20261115T125405Z",
  built_at: "2026-11-15T12:54:05+00:00",
  graph_v: 1,
  level_factor: [1, 1, 1, 1, 1.2, 1.5, 2, 3, 4, 6, 12],
  box: [-78.05, 38.2, -76.02, 39.72],
  packs: [
    { id: "beltway", name: "Inside the Beltway", bytes: GZ.byteLength, sha256: SHA, url: url("beltway"), area: { outline: BELTWAY, outside_beltway: false, whole: false } },
    { id: "nova", name: "Northern Virginia", bytes: GZ2.byteLength, sha256: SHA2, url: url("nova"), area: { outline: NOVA, outside_beltway: true, whole: false } },
    { id: "rest", name: "Southern Maryland", bytes: 9, sha256: "r", url: url("rest"), area: { outline: null, outside_beltway: false, whole: false } },
    { id: "all", name: "Everything", bytes: GZ3.byteLength, sha256: SHA3, url: url("all"), area: { outline: null, outside_beltway: false, whole: true } },
    // Refused: not where the packs are served.
    { id: "evil", name: "Elsewhere", bytes: 1, sha256: "0", url: "https://example.com/x.json.gz" },
  ],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const BYTES: Record<string, Buffer> = { [url("beltway")]: GZ, [url("nova")]: GZ2, [url("all")]: GZ3 };
const served = (async (u: string) => (BYTES[u] ? new Response(BYTES[u]) : new Response("", { status: 404 }))) as unknown as typeof fetch;

function memoryStore(fail?: Error): PackStore & { bytes: Map<string, ArrayBuffer> } {
  const bytes = new Map<string, ArrayBuffer>();
  return {
    bytes,
    put: async (key, b) => {
      if (fail) throw fail;
      bytes.set(key, b);
    },
    get: async (key) => bytes.get(key) ?? null,
    delete: async (key) => void bytes.delete(key),
  };
}

async function listed(): Promise<PackList> {
  const list = await fetchPackList(async () => json(LISTED));
  assert.ok(list);
  return list;
}
const pack = (list: PackList, id: string) => list.packs.find((p) => p.id === id)!;

test("the list: the packs served from /offline-packs/ only, each with its area, and null with no signal or before any are built", async () => {
  const list = await listed();
  assert.deepEqual(
    list.packs.map((p) => p.id),
    ["beltway", "nova", "rest", "all"],
  );
  assert.equal(list.buildId, "20261115T125405Z");
  assert.deepEqual(list.box, [-78.05, 38.2, -76.02, 39.72]);
  assert.deepEqual(pack(list, "nova").area, { outline: NOVA, outsideBeltway: true, whole: false });
  assert.equal(pack(list, "all").area?.whole, true);
  assert.equal(await fetchPackList(async () => json({ error: "not_built" }, 503)), null);
  assert.equal(
    await fetchPackList(async () => {
      throw new TypeError("Failed to fetch");
    }),
    null,
  );
});

test("a pack is kept only when its checksum matches, and opens to the network for a ride", async () => {
  const list = await listed();
  const store = memoryStore();
  assert.equal(await downloadPack(pack(list, "beltway"), list, async () => new Response(Buffer.from("not it")), store), "failed");
  assert.deepEqual(keptPacks(), []);
  assert.equal(await downloadPack(pack(list, "beltway"), list, served, store), "kept");
  assert.deepEqual(
    keptPacks().map((k) => [k.id, k.bytes]),
    [["beltway", GZ.byteLength]],
  );
  const opened = await openPack("beltway", store);
  assert.deepEqual(opened?.graph, GRAPH);
  assert.deepEqual(opened?.levelFactor, LISTED.level_factor);
});

test("several areas are kept side by side; one or all can be deleted", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "beltway"), list, served, store);
  await downloadPack(pack(list, "nova"), list, served, store);
  assert.deepEqual(
    keptPacks().map((k) => k.id),
    ["beltway", "nova"],
  );
  await removePack("beltway", store);
  assert.deepEqual(
    keptPacks().map((k) => k.id),
    ["nova"],
  );
  assert.deepEqual([...store.bytes.keys()], ["nova"]);
  assert.equal(await openPack("beltway", store), null);
  await removeAll(store);
  assert.deepEqual(keptPacks(), []);
  assert.equal(store.bytes.size, 0);
});

test("the whole map, once kept, removes the separate areas (it holds them, in one smaller file)", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "beltway"), list, served, store);
  await downloadPack(pack(list, "all"), list, served, store);
  assert.deepEqual(
    keptPacks().map((k) => k.id),
    ["all"],
  );
  assert.deepEqual([...store.bytes.keys()], ["all"]);
});

test("a failed download leaves what was kept; no room says so", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "beltway"), list, served, store);
  assert.equal(await downloadPack({ ...pack(list, "beltway"), sha256: "newer" }, list, async () => new Response("", { status: 502 }), store), "failed");
  assert.equal(keptPacks()[0]?.sha256, SHA);
  assert.ok(store.bytes.get("beltway"));
  const full = memoryStore(new DOMException("full", "QuotaExceededError"));
  assert.equal(await downloadPack(pack(list, "nova"), list, served, full), "no-room");
});

test("the one pack v0.27.0 kept is still kept, and is replaced by the same area's download", async () => {
  items.set("routemaker.regionPack", JSON.stringify({ id: "beltway", name: "Inside the Beltway", buildId: "20261113T050000Z", bytes: 5, sha256: "old", levelFactor: [1] }));
  const store = memoryStore();
  store.bytes.set("pack", asBuffer(GZ));
  assert.deepEqual(
    keptPacks().map((k) => [k.id, k.key]),
    [["beltway", "pack"]],
  );
  assert.deepEqual((await openPack("beltway", store))?.graph, GRAPH);
  const list = await listed();
  await downloadPack(pack(list, "beltway"), list, served, store);
  assert.deepEqual(
    keptPacks().map((k) => [k.id, k.key, k.sha256]),
    [["beltway", "beltway", SHA]],
  );
  assert.deepEqual([...store.bytes.keys()], ["beltway"]);
  assert.equal(items.get("routemaker.regionPack"), undefined);
});

test("bytes that are not a pack open to nothing, not an error", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "beltway"), list, served, store);
  store.bytes.set("beltway", asBuffer(gzipSync("{}")));
  assert.equal(await openPack("beltway", store), null);
  store.bytes.set("beltway", asBuffer(Buffer.from("plain")));
  assert.equal(await openPack("beltway", store), null);
});

test("one download at a time: the same pack joins the one under way, another waits its turn", async () => {
  const list = await listed();
  const store = memoryStore();
  let fetches = 0;
  const slow = (async (u: string) => {
    fetches += 1;
    await new Promise((done) => setTimeout(done, 5));
    return served(u);
  }) as unknown as typeof fetch;
  const first = downloadPack(pack(list, "beltway"), list, slow, store);
  const again = downloadPack(pack(list, "beltway"), list, slow, store);
  const second = downloadPack(pack(list, "nova"), list, slow, store);
  assert.equal(again, first);
  assert.deepEqual(downloads(), { active: "beltway", waiting: ["nova"] });
  assert.equal(await first, "kept");
  assert.equal(await second, "kept");
  assert.equal(fetches, 2);
  assert.deepEqual(downloads(), { active: null, waiting: [] });
});

test("a pack deleted while it downloads is not kept when it lands; Delete all stops the rest", async () => {
  const list = await listed();
  const store = memoryStore();
  const slow = (async (u: string) => {
    await new Promise((done) => setTimeout(done, 5));
    return served(u);
  }) as unknown as typeof fetch;
  const whole = downloadPack(pack(list, "all"), list, slow, store);
  const area = downloadPack(pack(list, "beltway"), list, slow, store);
  await removeAll(store);
  assert.equal(await whole, "cancelled");
  assert.equal(await area, "cancelled");
  assert.deepEqual(keptPacks(), []);
  assert.equal(store.bytes.size, 0);
  const one = downloadPack(pack(list, "nova"), list, slow, store);
  await removePack("nova", store);
  assert.equal(await one, "cancelled");
  assert.deepEqual(keptPacks(), []);
});

test("an area that lands after the whole map is kept is not kept beside it", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "all"), list, served, store);
  assert.equal(await downloadPack(pack(list, "beltway"), list, served, store), "cancelled");
  assert.deepEqual(
    keptPacks().map((k) => k.id),
    ["all"],
  );
  assert.deepEqual([...store.bytes.keys()], ["all"]);
});

test("which area holds a place: the Beltway cut out of the areas around it, the rest the box less the others", async () => {
  await listed();
  const downtown: [number, number] = [-77.03, 38.9];
  const manassas: [number, number] = [-77.47, 38.75];
  const laPlata: [number, number] = [-76.6, 38.5];
  assert.ok(covers("beltway", downtown));
  assert.ok(!covers("nova", downtown), "the Beltway is cut out of Northern Virginia");
  assert.ok(covers("nova", manassas));
  assert.ok(covers("rest", laPlata) && !covers("rest", downtown) && !covers("rest", manassas));
  assert.ok(covers("all", laPlata) && covers("all", downtown));
  assert.ok(!covers("all", [-80, 38]), "outside the map");
});

test("a ride opens the kept pack that covers the rider, one at a time; the only one kept where the areas are not known", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(pack(list, "beltway"), list, served, store);
  await downloadPack(pack(list, "nova"), list, served, store);
  assert.equal(packFor([-77.03, 38.9]), "beltway");
  assert.equal(packFor([-77.47, 38.75]), "nova");
  assert.equal(packFor([-76.6, 38.5]), null, "no kept area holds Southern Maryland");
  const ride = ridePacks(store);
  const first = ride.open([-77.03, 38.9]);
  assert.equal(ride.open([-77.02, 38.91]), first, "held while it still covers");
  assert.deepEqual((await first)?.graph, GRAPH);
  assert.deepEqual((await ride.open([-77.47, 38.75]))?.graph.names, ["Other"]);
  // The whole map stands in where no kept area holds the rider.
  await downloadPack(pack(list, "all"), list, served, store);
  assert.equal(packFor([-76.6, 38.5]), "all");
  // Kept before the areas were listed: the only one kept.
  items.delete("routemaker.regionPackAreas");
  assert.equal(packFor([-76.6, 38.5]), "all");
});

test("the map's date, from the build id", () => {
  assert.equal(mapDateText("20261115T125405Z", "en-US"), "Map of Nov 15, 2026");
  assert.equal(mapDateText("not a build"), "");
});

test("each area the server builds has its name in the page's words; any other keeps the server's", () => {
  const server = readFileSync(new URL("../../../src/core/offline_packs.py", import.meta.url), "utf8");
  const ids = [...server.matchAll(/^\s+id="([a-z-]+)",$/gm)].map((m) => m[1]);
  assert.deepEqual(ids, ["beltway", "nova", "nw-exurbs", "baltimore", "rest", "all"]);
  for (const id of ids) assert.notEqual(areaName(id, "x"), "x", id);
  assert.equal(areaName("shenandoah", "Shenandoah Valley"), "Shenandoah Valley");
});

test("a later map area (Southwest Florida) is its own pack: the whole map neither holds it nor removes it", async () => {
  const FLORIDA: [number, number][] = [[-82.35, 25.85], [-81.25, 25.85], [-81.25, 27.05], [-82.35, 27.05], [-82.35, 25.85]];
  const swfl = { id: "southwest-florida", name: "Southwest Florida", bytes: GZ2.byteLength, sha256: SHA2, url: url("southwest-florida"), area: { outline: FLORIDA, outside_beltway: false, whole: false, separate: true } };
  const list = await fetchPackList(async () => json({ ...LISTED, packs: [...LISTED.packs, swfl] }));
  assert.ok(list);
  assert.equal(pack(list, "southwest-florida").area?.separate, true);
  const bytes = { ...BYTES, [url("southwest-florida")]: GZ2 };
  const servedToo = (async (u: string) => (bytes[u] ? new Response(bytes[u]) : new Response("", { status: 404 }))) as unknown as typeof fetch;
  const store = memoryStore();
  await downloadPack(pack(list, "southwest-florida"), list, servedToo, store);
  await downloadPack(pack(list, "all"), list, servedToo, store);
  assert.deepEqual(keptPacks().map((k) => k.id).sort(), ["all", "southwest-florida"]);
  // Kept after the whole map, it is still kept: the whole map is the home area only.
  await removePack("southwest-florida", store);
  assert.equal(await downloadPack(pack(list, "southwest-florida"), list, servedToo, store), "kept");
  const naples: [number, number] = [-81.79, 26.14];
  assert.ok(covers("southwest-florida", naples) && !covers("all", naples));
  assert.ok(!covers("rest", naples), "the rest of the home map does not reach Florida");
  assert.equal(packFor(naples), "southwest-florida");
  assert.equal(packFor([-76.6, 38.5]), "all");
});
