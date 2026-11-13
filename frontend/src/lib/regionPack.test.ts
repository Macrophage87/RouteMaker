// The region pack for riding off grid (lib/regionPack.ts): listed, downloaded and checked, kept, opened for a ride.
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { downloadPack, downloading, fetchPackList, keptPack, openPack, removePack, areaName, type PackList, type PackStore } from "./regionPack.ts";

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

const LISTED = {
  build_id: "20261113T050000Z",
  built_at: "2026-11-13T05:00:00+00:00",
  graph_v: 1,
  level_factor: [1, 1, 1, 1, 1.2, 1.5, 2, 3, 4, 6, 12],
  packs: [
    { id: "beltway", name: "Inside the Beltway", bytes: GZ.byteLength, sha256: SHA, url: "/offline-packs/packs-20261113T050000Z/beltway.json.gz" },
    // Refused: not where the packs are served.
    { id: "evil", name: "Elsewhere", bytes: 1, sha256: "0", url: "https://example.com/x.json.gz" },
  ],
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function memoryStore(fail?: Error): PackStore & { bytes: ArrayBuffer | null } {
  const store = {
    bytes: null as ArrayBuffer | null,
    put: async (bytes: ArrayBuffer) => {
      if (fail) throw fail;
      store.bytes = bytes;
    },
    get: async () => store.bytes,
    clear: async () => {
      store.bytes = null;
    },
  };
  return store;
}

async function listed(): Promise<PackList> {
  const list = await fetchPackList(async () => json(LISTED));
  assert.ok(list);
  return list;
}

test("the list: the packs served from /offline-packs/ only, and null with no signal or before any are built", async () => {
  const list = await listed();
  assert.deepEqual(
    list.packs.map((p) => p.id),
    ["beltway"],
  );
  assert.equal(list.buildId, "20261113T050000Z");
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
  assert.equal(await downloadPack(list.packs[0], list, async () => new Response(Buffer.from("not it")), store), "failed");
  assert.equal(keptPack(), null);
  assert.equal(await downloadPack(list.packs[0], list, async () => new Response(GZ), store), "kept");
  assert.equal(keptPack()?.id, "beltway");
  assert.equal(keptPack()?.bytes, GZ.byteLength);
  const opened = await openPack(store);
  assert.deepEqual(opened?.graph, GRAPH);
  assert.deepEqual(opened?.levelFactor, LISTED.level_factor);
});

test("a failed download leaves the pack kept before; no room says so", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(list.packs[0], list, async () => new Response(GZ), store);
  assert.equal(await downloadPack(list.packs[0], list, async () => new Response("", { status: 502 }), store), "failed");
  assert.equal(keptPack()?.id, "beltway");
  assert.ok(store.bytes);
  const full = memoryStore(new DOMException("full", "QuotaExceededError"));
  assert.equal(await downloadPack(list.packs[0], list, async () => new Response(GZ), full), "no-room");
});

test("removed: nothing kept, nothing opened", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(list.packs[0], list, async () => new Response(GZ), store);
  await removePack(store);
  assert.equal(keptPack(), null);
  assert.equal(store.bytes, null);
  assert.equal(await openPack(store), null);
});

test("bytes that are not a pack open to nothing, not an error", async () => {
  const list = await listed();
  const store = memoryStore();
  await downloadPack(list.packs[0], list, async () => new Response(GZ), store);
  store.bytes = asBuffer(gzipSync("{}"));
  assert.equal(await openPack(store), null);
  store.bytes = asBuffer(Buffer.from("plain"));
  assert.equal(await openPack(store), null);
});

test("each area the server builds has its name in the page's words; any other keeps the server's", () => {
  const server = readFileSync(new URL("../../../src/core/offline_packs.py", import.meta.url), "utf8");
  const ids = [...server.matchAll(/^\s+id="([a-z-]+)",$/gm)].map((m) => m[1]);
  assert.deepEqual(ids, ["beltway", "nova", "nw-exurbs", "baltimore", "rest", "all"]);
  for (const id of ids) assert.notEqual(areaName(id, "x"), "x", id);
  assert.equal(areaName("shenandoah", "Shenandoah Valley"), "Shenandoah Valley");
});

test("one download at a time: a second ask for the same pack joins the first", async () => {
  const list = await listed();
  const store = memoryStore();
  let fetches = 0;
  const slow = async () => {
    fetches += 1;
    await new Promise((done) => setTimeout(done, 5));
    return new Response(GZ);
  };
  const first = downloadPack(list.packs[0], list, slow, store);
  assert.equal(downloading()?.done, first);
  const second = downloadPack(list.packs[0], list, slow, store);
  assert.equal(second, first);
  assert.equal(await second, "kept");
  assert.equal(fetches, 1);
  assert.equal(downloading(), null);
});
