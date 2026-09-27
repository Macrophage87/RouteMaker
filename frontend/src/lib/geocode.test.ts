// Place search and place names: what is asked of the API, how often, and what
// a pick does to the plan. Properties, not sentences.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  GeoGate,
  MAX_QUERY_CHARS,
  MIN_QUERY_CHARS,
  NAME_DEBOUNCE_MS,
  PlaceNamer,
  PlaceSearchRunner,
  RETRY_CAP_MS,
  SEARCH_DEBOUNCE_MS,
  applyPlace,
  coordinatesText,
  fetchPlaces,
  placeKey,
  placeRole,
  pointRole,
  reverseUrl,
  searchUrl,
  type GeoResult,
  type Place,
  type Timers,
} from "./geocode.ts";
import { MAX_POINTS, type LonLat } from "./geo.ts";
import { decodePlan, encodePlan } from "./planHash.ts";

class FakeTimers implements Timers {
  now = 0;
  private id = 1;
  private pending = new Map<number, { at: number; fn: () => void }>();
  set = (fn: () => void, ms: number) => {
    const id = this.id++;
    this.pending.set(id, { at: this.now + ms, fn });
    return id;
  };
  clear = (handle: unknown) => {
    this.pending.delete(handle as number);
  };
  async advance(ms: number) {
    const until = this.now + ms;
    for (;;) {
      const due = [...this.pending.entries()].filter(([, t]) => t.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      this.pending.delete(due[0]);
      this.now = due[1].at;
      due[1].fn();
      await flush();
    }
    this.now = until;
    await flush();
  }
}

async function flush() {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
}

/** A fake API: each call waits for the test to answer it. */
function fakeSend<T>() {
  const calls: Array<{ arg: T; answer: (r: GeoResult) => void }> = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const send = (arg: T) =>
    new Promise<GeoResult>((resolve) => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      calls.push({
        arg,
        answer: (r) => {
          inFlight -= 1;
          resolve(r);
        },
      });
    });
  return { calls, send, maxInFlight: () => maxInFlight };
}

const PLACE: Place = { name: "Union Station", label: "Union Station, Washington", lon: -77.0065, lat: 38.8973, kind: "house" };
const found = (...places: Place[]): GeoResult => ({ ok: true, places, attribution: ["© OpenStreetMap contributors"] });

// --- the URLs -----------------------------------------------------------------

test("a search asks this site's API for the query, the count and the bias only", () => {
  const url = new URL(searchUrl("Lincoln Memorial", [-77.05, 38.89], 4), "http://site.test");
  assert.equal(url.origin, "http://site.test", "a relative URL: the page's own origin, no third party");
  assert.equal(url.pathname, "/api/geocode");
  assert.deepEqual([...url.searchParams.keys()].sort(), ["lat", "limit", "lon", "q"]);
  assert.equal(url.searchParams.get("q"), "Lincoln Memorial");
  assert.equal(Number(url.searchParams.get("lat")), 38.89);
  assert.equal(Number(url.searchParams.get("lon")), -77.05);
  assert.equal(url.searchParams.get("limit"), "4");
});

test("without a bias no point is sent, and a long paste is cut to the API's limit", () => {
  const url = new URL(searchUrl("x".repeat(MAX_QUERY_CHARS + 50)), "http://site.test");
  assert.equal(url.searchParams.has("lat") || url.searchParams.has("lon"), false);
  assert.equal(url.searchParams.get("q")!.length, MAX_QUERY_CHARS);
});

test("a name is asked of /api/reverse for the point", () => {
  const url = new URL(reverseUrl([-77.0869, 38.887]), "http://site.test");
  assert.equal(url.pathname, "/api/reverse");
  assert.deepEqual([Number(url.searchParams.get("lon")), Number(url.searchParams.get("lat"))], [-77.0869, 38.887]);
});

// --- the answer -----------------------------------------------------------------

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  const seen: Array<{ url: string; init: RequestInit }> = [];
  const impl = async (url: string, init: RequestInit) => {
    seen.push({ url, init });
    return new Response(typeof body === "string" ? body : JSON.stringify(body), { status, headers });
  };
  return { impl, seen };
}

test("an answer's places are kept and anything malformed in it is not", async () => {
  const { impl, seen } = respond(200, {
    results: [PLACE, { name: "", label: "x", lon: 1, lat: 2 }, { name: "n", label: "l", lon: "a", lat: 2 }, null],
    attribution: ["© OpenStreetMap contributors, ODbL"],
  });
  const result = await fetchPlaces("/api/geocode?q=union", impl);
  assert.equal(result.ok, true);
  assert.deepEqual(result.ok && result.places, [PLACE]);
  assert.deepEqual(result.ok && result.attribution, ["© OpenStreetMap contributors, ODbL"]);
  assert.equal(seen[0].init.credentials, "same-origin");
});

test("a refusal carries its status and Retry-After; no answer at all is status 0", async () => {
  const busy = await fetchPlaces("/api/geocode?q=a", respond(429, { error: "slow" }, { "Retry-After": "2" }).impl);
  assert.deepEqual(busy, { ok: false, status: 429, retryAfterS: 2 });
  const down = await fetchPlaces("/api/geocode?q=a", respond(502, { error: "down" }).impl);
  assert.equal(!down.ok && down.status, 502);
  const html = await fetchPlaces("/api/geocode?q=a", respond(200, "<html>").impl);
  assert.equal(html.ok, false);
  const offline = await fetchPlaces("/api/geocode?q=a", async () => {
    throw new TypeError("offline");
  });
  assert.deepEqual(offline, { ok: false, status: 0 });
});

// --- one at a time --------------------------------------------------------------

test("the gate runs one request at a time, and a search goes before names waiting", async () => {
  const gate = new GeoGate();
  const order: string[] = [];
  let release!: () => void;
  const first = gate.run(() => new Promise<void>((r) => (release = r)).then(() => void order.push("name 1")));
  const name2 = gate.run(async () => void order.push("name 2"));
  const search = gate.run(async () => void order.push("search"), true);
  await flush();
  assert.deepEqual(order, [], "nothing else starts while one is in flight");
  release();
  await Promise.all([first, name2, search]);
  assert.deepEqual(order, ["name 1", "search", "name 2"]);
  assert.equal(gate.idle, true);
});

test("a failed request does not stop the gate", async () => {
  const gate = new GeoGate();
  await assert.rejects(gate.run(async () => Promise.reject(new Error("x"))));
  assert.equal(await gate.run(async () => 7), 7);
});

// --- the typeahead ---------------------------------------------------------------

function searchRig() {
  const timers = new FakeTimers();
  const api = fakeSend<string>();
  const results: Array<[string, GeoResult]> = [];
  const runner = new PlaceSearchRunner({ send: api.send, onResult: (q, r) => results.push([q, r]), timers });
  return { timers, api, results, runner };
}

test("typing is one search, sent once the typing pauses", async () => {
  const { timers, api, runner } = searchRig();
  for (const prefix of ["Uni", "Unio", "Union", "Union S", "Union St"]) {
    runner.request(prefix);
    await timers.advance(SEARCH_DEBOUNCE_MS - 50);
  }
  assert.equal(api.calls.length, 0);
  await timers.advance(50);
  assert.deepEqual(api.calls.map((c) => c.arg), ["Union St"]);
});

test(`fewer than ${MIN_QUERY_CHARS} characters are never sent`, async () => {
  const { timers, api, runner } = searchRig();
  runner.request("U");
  runner.request("Un ");
  await timers.advance(SEARCH_DEBOUNCE_MS * 4);
  assert.equal(api.calls.length, 0);
});

test("one search in flight; what was typed meanwhile is sent next, and only the latest", async () => {
  const { timers, api, runner, results } = searchRig();
  runner.request("Penn");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  runner.request("Penn Sta");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  runner.request("Penn Station");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  assert.equal(api.calls.length, 1);
  api.calls[0].answer(found(PLACE));
  await flush();
  assert.deepEqual(results, [], "a superseded answer is not shown");
  assert.deepEqual(api.calls.map((c) => c.arg), ["Penn", "Penn Station"]);
  api.calls[1].answer(found(PLACE));
  await flush();
  assert.deepEqual(results.map(([q]) => q), ["Penn Station"]);
  assert.equal(api.maxInFlight(), 1);
});

test("a busy answer is tried again once, soon, for the latest query", async () => {
  const { timers, api, runner, results } = searchRig();
  runner.request("Purcellville");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 503, retryAfterS: 5 });
  await flush();
  assert.equal(results.length, 0);
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 2, "retried within the cap, not after the five seconds asked");
  api.calls[1].answer({ ok: false, status: 503, retryAfterS: 5 });
  await timers.advance(RETRY_CAP_MS * 3);
  assert.equal(api.calls.length, 2, "and only once");
  assert.equal(results.length, 1);
  assert.equal(results[0][1].ok, false);
});

test("clearing the box drops a search not yet sent", async () => {
  const { timers, api, runner } = searchRig();
  runner.request("Baltimore");
  runner.clear();
  await timers.advance(SEARCH_DEBOUNCE_MS * 2);
  assert.equal(api.calls.length, 0);
});

// --- names for points --------------------------------------------------------------

function namerRig() {
  const timers = new FakeTimers();
  const api = fakeSend<LonLat>();
  let changes = 0;
  const namer = new PlaceNamer({ send: api.send, onChange: () => (changes += 1), timers });
  return { timers, api, namer, changes: () => changes };
}

const A: LonLat = [-77.0502, 38.8893];
const B: LonLat = [-77.0065, 38.8973];
const C: LonLat = [-76.6158, 39.3072];

test("each point is named once, one lookup at a time, after the points settle", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS - 1);
  assert.equal(api.calls.length, 0, "not while the points are still changing");
  await timers.advance(1);
  assert.equal(api.calls.length, 1);
  api.calls[0].answer(found({ ...PLACE, name: "Lincoln Memorial" }));
  await flush();
  assert.equal(api.calls.length, 2);
  api.calls[1].answer(found(PLACE));
  await flush();
  assert.equal(namer.name(A)?.name, "Lincoln Memorial");
  assert.equal(namer.name(B)?.name, "Union Station");
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS * 2);
  assert.equal(api.calls.length, 2, "cached");
  assert.equal(api.maxInFlight(), 1);
});

test("a point put back within a few metres keeps its name without a lookup", async () => {
  const { timers, api, namer } = namerRig();
  namer.remember(A, "Lincoln Memorial");
  namer.want([[A[0] + 0.00002, A[1] - 0.00002]]);
  await timers.advance(NAME_DEBOUNCE_MS);
  assert.equal(api.calls.length, 0);
  assert.equal(placeKey(A), placeKey([A[0] + 0.00002, A[1] - 0.00002]));
});

test("a point chosen from search keeps the search's name", async () => {
  const { timers, api, namer, changes } = namerRig();
  namer.remember(C, "Baltimore Penn Station", "Baltimore Penn Station, Baltimore");
  namer.want([C]);
  await timers.advance(NAME_DEBOUNCE_MS);
  assert.equal(api.calls.length, 0);
  assert.deepEqual(namer.name(C), { name: "Baltimore Penn Station", label: "Baltimore Penn Station, Baltimore" });
  assert.ok(changes() >= 1);
});

test("a failed or empty lookup falls back to coordinates and is not asked again", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 502 });
  await flush();
  api.calls[1].answer(found());
  await flush();
  assert.equal(namer.name(A), undefined);
  assert.equal(namer.name(B), undefined);
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS * 2);
  assert.equal(api.calls.length, 2);
});

test("a point no longer in the plan is not looked up", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B, C]);
  await timers.advance(NAME_DEBOUNCE_MS);
  namer.want([A]);
  api.calls[0].answer(found(PLACE));
  await timers.advance(NAME_DEBOUNCE_MS * 2);
  assert.deepEqual(api.calls.map((c) => c.arg), [A]);
});

test("a busy lookup is tried again once", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 429, retryAfterS: 1 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 2);
  api.calls[1].answer(found(PLACE));
  await flush();
  assert.equal(namer.name(A)?.name, "Union Station");
});

// --- what a pick does -----------------------------------------------------------

test("a pick is the start, then the destination, then a new destination", () => {
  assert.deepEqual(applyPlace([], A, false), [A]);
  assert.deepEqual(applyPlace([A], B, false), [A, B]);
  assert.deepEqual(applyPlace([A, B], C, false), [A, C]);
  assert.deepEqual(applyPlace([A, B, C], B, false), [A, B, B]);
});

test("asked for, a pick is a via between the start and the end", () => {
  const via: LonLat = [-77.03, 38.893];
  const next = applyPlace([A, B], via, true);
  assert.deepEqual(next, [A, via, B]);
  assert.equal(placeRole(2, true), "via");
});

test("with fewer than two points, a via is the start or the end", () => {
  assert.deepEqual(applyPlace([], A, true), [A]);
  assert.deepEqual(applyPlace([A], B, true), [A, B]);
  assert.deepEqual([placeRole(0, true), placeRole(1, true)], ["start", "end"]);
});

test("a via on a full route changes nothing", () => {
  const full: LonLat[] = Array.from({ length: MAX_POINTS }, (_, i) => [-77 + i / 100, 38.9]);
  assert.deepEqual(applyPlace(full, A, true), full);
});

test("roles in the points list", () => {
  assert.deepEqual([0, 1, 2].map((i) => pointRole(i, 3)), ["Start", "Via 1", "End"]);
  assert.equal(pointRole(0, 1), "Start");
  assert.match(coordinatesText([-77.05, 38.89]), /38\.89.*-77\.05/);
});

test("the link carries points and ride type only, never a name", () => {
  const hash = encodePlan([A, B], "default");
  assert.deepEqual([...new URLSearchParams(hash.slice(1)).keys()].sort(), ["p", "preset"]);
  assert.equal(decodePlan(hash).points.length, 2);
});
