import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  GIVE_UP_S,
  MAX_ATTEMPTS,
  MAX_IN_FLIGHT,
  MAX_WAIT_S,
  Queue,
  STRESS_PROTOCOL,
  backoffMs,
  fetchTile,
  httpUrl,
  protocolUrl,
  registerStressProtocol,
  retryAfterS,
  stressProbe,
  stressTilesAnswer,
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

/** A clock that the waits move, so the give-up is tested without sleeping. */
function clock() {
  let t = 0;
  const waits: number[] = [];
  return {
    now: () => t,
    wait: async (ms: number) => {
      waits.push(ms);
      t += ms;
    },
    waits,
  };
}

const MIDDLE = () => 0.5; // no stretch: 0.5 + 0.5

test("a tile the API asks to be fetched again is, after a growing wait", async () => {
  const { get, asked } = answers([429, "1"], [503, "1"], [503, "1"], [200, null]);
  const c = clock();
  const data = await fetchTile(TILE, { get, wait: c.wait, now: c.now, random: MIDDLE, queue: new Queue(2) });
  assert.deepEqual([...new Uint8Array(data)], [1, 2, 3]);
  assert.deepEqual(c.waits, [1000, 2000, 4000]);
  assert.deepEqual(asked, [TILE, TILE, TILE, TILE]);
});

test("the wait is the longer of Retry-After and the backoff, stretched 0.5-1.5 at random", () => {
  assert.equal(backoffMs(1, 1, () => 0), 500);
  assert.equal(backoffMs(1, 1, () => 1), 1500);
  assert.equal(backoffMs(1, 3, MIDDLE), 3000);
  assert.equal(backoffMs(3, 1, MIDDLE), 4000);
  assert.equal(backoffMs(10, 1, MIDDLE), MAX_WAIT_S * 1000);
});

test("it gives up after about GIVE_UP_S of refusals, not after a fixed few tries", async () => {
  const busy = answers(...Array.from({ length: 50 }, () => [503, "1"] as [number, string]));
  const c = clock();
  await assert.rejects(
    fetchTile(TILE, { get: busy.get, wait: c.wait, now: c.now, random: MIDDLE, queue: new Queue(2) }),
  );
  const waited = c.waits.reduce((a, b) => a + b, 0);
  assert.ok(waited <= GIVE_UP_S * 1000, `waited ${waited} ms`);
  assert.ok(waited >= (GIVE_UP_S - MAX_WAIT_S * 1.5) * 1000, `gave up early, after ${waited} ms`);
  assert.ok(busy.asked.length <= MAX_ATTEMPTS && busy.asked.length >= 5, `${busy.asked.length} requests`);
});

test("never more than MAX_ATTEMPTS requests, however short the waits", async () => {
  const busy = answers(...Array.from({ length: 50 }, () => [503, "0"] as [number, string]));
  await assert.rejects(
    fetchTile(TILE, { get: busy.get, wait: async () => {}, now: () => 0, random: () => 0, queue: new Queue(2) }),
  );
  assert.equal(busy.asked.length, MAX_ATTEMPTS);
});

test("what retrying cannot fix is not retried", async () => {
  for (const status of [400, 404, 500, 502]) {
    const once = answers([status, "1"], [200, null]);
    await assert.rejects(fetchTile(TILE, { get: once.get, wait: async () => {}, queue: new Queue(2) }));
    assert.equal(once.asked.length, 1, `${status} is not asked again`);
  }
});

test("Retry-After is read as seconds, with a default and a ceiling", () => {
  assert.equal(retryAfterS("2"), 2);
  assert.equal(retryAfterS("600"), MAX_WAIT_S);
  assert.equal(retryAfterS(null), 1);
  assert.equal(retryAfterS("soon"), 1);
  assert.equal(retryAfterS("-1"), 1);
  assert.equal(retryAfterS(""), 1);
  assert.equal(retryAfterS("   "), 1);
});

test("a page has at most MAX_IN_FLIGHT tile requests out, and a refused tile gives its place up", async () => {
  const queue = new Queue(MAX_IN_FLIGHT);
  let out = 0;
  let most = 0;
  const releases: Array<() => void> = [];
  const get = (async () => {
    out += 1;
    most = Math.max(most, out);
    await new Promise<void>((resolve) => releases.push(resolve));
    out -= 1;
    return new Response(new Uint8Array([1]), { status: 200 });
  }) as unknown as typeof fetch;
  const all = Promise.all(Array.from({ length: 6 }, () => fetchTile(TILE, { get, queue })));
  for (let i = 0; i < 6; i += 1) {
    await new Promise((r) => setTimeout(r, 5));
    releases.shift()?.();
  }
  await all;
  assert.equal(most, MAX_IN_FLIGHT);
  assert.ok(MAX_IN_FLIGHT <= 2, "a page asks for no more than the API draws for it, and one more");
  assert.equal(queue.inFlight, 0);

  // While one tile waits out its backoff, the others go ahead.
  const q2 = new Queue(1);
  const refused = answers([503, "1"], [200, null]);
  const other = answers([200, null]);
  let resumeWait = () => {};
  const waiting = fetchTile(TILE, {
    get: refused.get,
    queue: q2,
    random: MIDDLE,
    wait: () => new Promise<void>((r) => (resumeWait = r)),
  });
  await new Promise((r) => setTimeout(r, 5));
  await fetchTile(TILE, { get: other.get, queue: q2 });
  resumeWait();
  await waiting;
  assert.equal(q2.inFlight, 0);
});

test("an abandoned tile stops waiting, and leaves the queue", async () => {
  const { get, asked } = answers([429, "3"], [200, null]);
  const abort = new AbortController();
  const pending = fetchTile(TILE, { get, signal: abort.signal, random: () => 0, queue: new Queue(2) });
  setTimeout(() => abort.abort(), 20);
  await assert.rejects(pending);
  assert.equal(asked.length, 1);

  const queue = new Queue(1);
  await queue.acquire();
  const gone = new AbortController();
  const queued = queue.acquire(gone.signal);
  gone.abort();
  await assert.rejects(queued);
  queue.release();
  assert.equal(queue.inFlight, 0, "the abandoned waiter did not take the slot");
});

test("the protocol's URL carries the real one; the loader fetches it with MapLibre's cancel", async () => {
  assert.equal(protocolUrl(TILE), `${STRESS_PROTOCOL}://${TILE}`);
  assert.equal(httpUrl(protocolUrl(TILE)), TILE);
  const added: Array<[string, (p: { url: string }, a: AbortController) => Promise<{ data: ArrayBuffer }>]> = [];
  const signals: Array<AbortSignal | undefined> = [];
  const asked: string[] = [];
  const get = (async (url: string, init?: RequestInit) => {
    asked.push(url);
    signals.push(init?.signal ?? undefined);
    return new Response(new Uint8Array([1, 2, 3]), { status: 200 });
  }) as unknown as typeof fetch;
  registerStressProtocol({ addProtocol: (name, loader) => void added.push([name, loader]) }, get);
  registerStressProtocol({ addProtocol: (name, loader) => void added.push([name, loader]) }, get);
  assert.equal(added.length, 1, "registered once");
  assert.equal(added[0][0], STRESS_PROTOCOL);
  const abort = new AbortController();
  const reply = await added[0][1]({ url: protocolUrl(TILE) }, abort);
  assert.equal(reply.data.byteLength, 3);
  assert.deepEqual(asked, [TILE]);
  assert.equal(signals[0], abort.signal);
});

test("the page's own queue caps its tile requests at MAX_IN_FLIGHT", async () => {
  // No queue passed: the default, shared by every tile the page asks for.
  let out = 0;
  let most = 0;
  const releases: Array<() => void> = [];
  const get = (async () => {
    out += 1;
    most = Math.max(most, out);
    await new Promise<void>((resolve) => releases.push(resolve));
    out -= 1;
    return new Response(new Uint8Array([1]), { status: 200 });
  }) as unknown as typeof fetch;
  const all = Promise.all(Array.from({ length: 8 }, () => fetchTile(TILE, { get })));
  for (let i = 0; i < 8; i += 1) {
    await new Promise((r) => setTimeout(r, 5));
    releases.shift()?.();
  }
  await all;
  assert.equal(most, MAX_IN_FLIGHT);
});

test("the queue lets waiters in in the order they came", async () => {
  const queue = new Queue(1);
  await queue.acquire();
  const order: number[] = [];
  const waiters = [1, 2, 3].map((n) => queue.acquire().then(() => order.push(n)));
  for (let i = 0; i < 3; i += 1) {
    queue.release();
    await new Promise((r) => setTimeout(r, 1));
  }
  await Promise.all(waiters);
  assert.deepEqual(order, [1, 2, 3]);
});

test("the availability check waits out refusals, and fails only on what retrying cannot fix", async () => {
  const origin = "https://example.test";
  const busyThenOk = answers([503, "1"], [429, "1"], [200, null]);
  const c = clock();
  assert.equal(
    await stressTilesAnswer(origin, { get: busyThenOk.get, wait: c.wait, now: c.now, random: MIDDLE, queue: new Queue(2) }),
    true,
  );
  assert.equal(busyThenOk.asked.length, 3);
  assert.match(busyThenOk.asked[0], /^https:\/\/example\.test\/tiles\/stress\/12\/\d+\/\d+\.pbf$/);
  for (const status of [404, 502]) {
    const gone = answers([status, null]);
    assert.equal(await stressTilesAnswer(origin, { get: gone.get, queue: new Queue(2) }), false);
    assert.equal(gone.asked.length, 1);
  }
});

function probeHarness(answers: boolean[]) {
  const timers: Array<{ run: () => void; ms: number }> = [];
  const events: string[] = [];
  let gone = false;
  const check = stressProbe("https://example.test", 60_000, {
    answer: async () => answers.shift() ?? false,
    add: () => events.push("add"),
    report: (a) => events.push(a),
    disposed: () => gone,
    setTimer: (run, ms) => {
      const timer = { run, ms };
      timers.push(timer);
      return timer;
    },
    clearTimer: (timer) => {
      timers.splice(timers.indexOf(timer as (typeof timers)[number]), 1);
    },
  });
  return { check, timers, events, dispose: () => (gone = true) };
}

test("MapView's check: the overlay goes on when the endpoint answers, and not when it does not", async () => {
  const up = probeHarness([true]);
  await up.check.probe();
  assert.deepEqual(up.events, ["add", "available"]);
  assert.equal(up.timers.length, 0);

  const down = probeHarness([false, true]);
  await down.check.probe();
  assert.deepEqual(down.events, ["unavailable"]);
  assert.deepEqual(down.timers.map((t) => t.ms), [60_000], "asked again a minute later");
  down.timers.shift()!.run();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(down.events, ["unavailable", "add", "available"]);
});

test("a check already waiting is not doubled, a cancelled one never runs, a late answer is dropped", async () => {
  const h = probeHarness([false]);
  await h.check.probe();
  h.check.later(5_000);
  assert.equal(h.timers.length, 1, "the minute's recheck is already waiting");
  h.check.cancel();
  assert.equal(h.timers.length, 0);
  h.check.later(5_000);
  assert.deepEqual(h.timers.map((t) => t.ms), [5_000]);

  const late = probeHarness([true]);
  late.dispose();
  await late.check.probe();
  assert.deepEqual(late.events, []);
});

test("by default the check asks the tile endpoint itself, and a 404 leaves the overlay off", async () => {
  // MERGE-TILES re-check M19: a probe that answered yes without asking passed.
  const real = globalThis.fetch;
  const asked: string[] = [];
  globalThis.fetch = (async (url: string) => {
    asked.push(url);
    return new Response(null, { status: 404 });
  }) as typeof fetch;
  try {
    const events: string[] = [];
    const check = stressProbe("https://example.test", 60_000, {
      add: () => events.push("add"),
      report: (a) => events.push(a),
      disposed: () => false,
      setTimer: () => null,
    });
    await check.probe();
    assert.deepEqual(events, ["unavailable"]);
    assert.equal(asked.length, 1);
    assert.match(asked[0], /^https:\/\/example\.test\/tiles\/stress\/12\/\d+\/\d+\.pbf$/);
  } finally {
    globalThis.fetch = real;
  }
});

test("MapView checks through stressProbe with its own answer, and cancels on the way out", () => {
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const call = view.match(/stressProbe\(origin, STRESS_RECHECK_MS, \{([^}]*)\}\)/);
  assert.ok(call, "MapView no longer checks through stressProbe");
  assert.doesNotMatch(call[1], /answer/, "MapView must not stand its own answer in for the endpoint's");
  assert.match(view, /stressCheck\.cancel\(\);/);
  assert.match(view, /void stressCheck\.probe\(\);/);
});
