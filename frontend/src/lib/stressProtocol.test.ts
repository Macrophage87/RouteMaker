import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ATTEMPTS,
  MAX_WAIT_S,
  STRESS_PROTOCOL,
  fetchTile,
  httpUrl,
  protocolUrl,
  registerStressProtocol,
  retryAfterS,
} from "./stressProtocol.ts";

const TILE = "https://example.test/tiles/stress/14/1/2.pbf";

function answers(...replies: Array<[number, string | null]>) {
  const asked: string[] = [];
  const get = (async (url: string) => {
    asked.push(url);
    const [status, retryAfter] = replies.shift() ?? [500, null];
    const headers = new Headers();
    if (retryAfter !== null) headers.set("Retry-After", retryAfter);
    return new Response(status === 200 ? new Uint8Array([1, 2, 3]) : null, { status, headers });
  }) as unknown as typeof fetch;
  return { get, asked };
}

test("a tile the API asks to be fetched again is, after the wait it names", async () => {
  const { get, asked } = answers([429, "1"], [503, "2"], [200, null]);
  const waits: number[] = [];
  const data = await fetchTile(TILE, { get, wait: async (ms) => void waits.push(ms), jitter: () => 0 });
  assert.deepEqual([...new Uint8Array(data)], [1, 2, 3]);
  assert.deepEqual(waits, [1000, 2000]);
  assert.deepEqual(asked, [TILE, TILE, TILE]);
});

test("it gives up after a few tries, and does not retry what retrying cannot fix", async () => {
  const busy = answers(...Array.from({ length: 10 }, () => [503, "1"] as [number, string]));
  await assert.rejects(fetchTile(TILE, { get: busy.get, wait: async () => {}, jitter: () => 0 }));
  assert.equal(busy.asked.length, MAX_ATTEMPTS);
  for (const status of [400, 404, 500, 502]) {
    const once = answers([status, "1"], [200, null]);
    await assert.rejects(fetchTile(TILE, { get: once.get, wait: async () => {} }));
    assert.equal(once.asked.length, 1, `${status} is not asked again`);
  }
});

test("the wait is the Retry-After, bounded, with a small jitter", async () => {
  assert.equal(retryAfterS("2"), 2);
  assert.equal(retryAfterS("600"), MAX_WAIT_S);
  assert.equal(retryAfterS(null), 1);
  assert.equal(retryAfterS("soon"), 1);
  const { get } = answers([429, "1"], [200, null]);
  const waits: number[] = [];
  await fetchTile(TILE, { get, wait: async (ms) => void waits.push(ms), jitter: () => 180 });
  assert.deepEqual(waits, [1180]);
});

test("an abandoned tile stops waiting", async () => {
  const { get, asked } = answers([429, "3"], [200, null]);
  const abort = new AbortController();
  const pending = fetchTile(TILE, { get, signal: abort.signal, jitter: () => 0 });
  setTimeout(() => abort.abort(), 20);
  await assert.rejects(pending);
  assert.equal(asked.length, 1);
});

test("the protocol's URL carries the real one, which the loader fetches", async () => {
  assert.equal(protocolUrl(TILE), `${STRESS_PROTOCOL}://${TILE}`);
  assert.equal(httpUrl(protocolUrl(TILE)), TILE);
  const added: Array<[string, (p: { url: string }, a: AbortController) => Promise<{ data: ArrayBuffer }>]> = [];
  const { get, asked } = answers([200, null]);
  registerStressProtocol({ addProtocol: (name, loader) => void added.push([name, loader]) }, get);
  registerStressProtocol({ addProtocol: (name, loader) => void added.push([name, loader]) }, get);
  assert.equal(added.length, 1, "registered once");
  assert.equal(added[0][0], STRESS_PROTOCOL);
  const reply = await added[0][1]({ url: protocolUrl(TILE) }, new AbortController());
  assert.equal(reply.data.byteLength, 3);
  assert.deepEqual(asked, [TILE]);
});
