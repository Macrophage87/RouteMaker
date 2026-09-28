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
  FAILED_RETRY_MS,
  applyPlace,
  choicesFor,
  coordinatesText,
  defaultChoice,
  fetchPlaces,
  normalQuery,
  placeKey,
  placesFor,
  placeEffect,
  placeType,
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
  delays: number[] = [];
  set = (fn: () => void, ms: number) => {
    this.delays.push(ms);
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
  assert.deepEqual(result.ok && result.places, [{ ...PLACE, osm_type: null, osm_id: null, osm_key: null, osm_value: null }]);
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
  const namer = new PlaceNamer({ send: api.send, onChange: () => (changes += 1), timers, now: () => timers.now });
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

test("an empty lookup falls back to coordinates and is not asked again", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer(found());
  await flush();
  assert.equal(namer.name(B), undefined);
  namer.want([B]);
  await timers.advance(FAILED_RETRY_MS * 2);
  assert.equal(api.calls.length, 1);
});

test("several failed lookups wait on one timer, not one each", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B, C]);
  await timers.advance(NAME_DEBOUNCE_MS);
  for (let i = 0; i < 3; i += 1) {
    api.calls[i].answer({ ok: false, status: 500 });
    await flush();
  }
  assert.equal(timers.delays.filter((ms) => ms === FAILED_RETRY_MS).length, 1);
  await timers.advance(FAILED_RETRY_MS);
  assert.equal(api.calls.length, 4, "the three are asked again, one at a time");
});

test("a failed lookup shows coordinates, then is asked again later, not for the session", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 500 });
  await flush();
  assert.equal(namer.name(A), undefined, "coordinates meanwhile");
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  assert.equal(api.calls.length, 1, "not asked again at once");
  await timers.advance(FAILED_RETRY_MS);
  assert.equal(api.calls.length, 2, "asked again once the wait is over, with no new change to the plan");
  api.calls[1].answer(found({ ...PLACE, name: "Lincoln Memorial" }));
  await flush();
  assert.equal(namer.name(A)?.name, "Lincoln Memorial");
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

test("by default a pick is the start, then the destination, then a new destination", () => {
  assert.deepEqual(applyPlace([], A, defaultChoice(0)), [A]);
  assert.deepEqual(applyPlace([A], B, defaultChoice(1)), [A, B]);
  assert.deepEqual(applyPlace([A, B], C, defaultChoice(2)), [A, C]);
  assert.deepEqual(applyPlace([A, B, C], B, defaultChoice(3)), [A, B, B]);
});

test("a pick can be made the start once there is one", () => {
  assert.deepEqual(applyPlace([A], B, "start"), [B]);
  assert.deepEqual(applyPlace([A, B], C, "start"), [C, B]);
  assert.deepEqual(applyPlace([A, C, B], B, "start"), [B, C, B]);
  assert.equal(placeEffect(2, "start"), "replace-start");
});

test("asked for, a pick is a via between the start and the end", () => {
  const via: LonLat = [-77.03, 38.893];
  assert.deepEqual(applyPlace([A, B], via, "via"), [A, via, B]);
  assert.equal(placeEffect(2, "via"), "via");
});

test("with fewer than two points, a via is the start or the end", () => {
  assert.deepEqual(applyPlace([], A, "via"), [A]);
  assert.deepEqual(applyPlace([A], B, "via"), [A, B]);
  assert.deepEqual([placeEffect(0, "via"), placeEffect(1, "via")], ["start", "end"]);
});

test("the choice the box starts on is always one on offer", () => {
  for (const count of [0, 1, 2, 5, MAX_POINTS]) {
    assert.ok(choicesFor(count, count >= MAX_POINTS).includes(defaultChoice(count)), `count ${count}`);
  }
});

test("the choices on offer follow the plan", () => {
  assert.deepEqual(choicesFor(0, false), ["start"]);
  assert.deepEqual(choicesFor(1, false), ["start", "end"]);
  assert.deepEqual(choicesFor(2, false), ["start", "end", "via"]);
  assert.deepEqual(choicesFor(MAX_POINTS, true), ["start", "end"], "a full route can still move its ends");
});

test("a via on a full route changes nothing", () => {
  const full: LonLat[] = Array.from({ length: MAX_POINTS }, (_, i) => [-77 + i / 100, 38.9]);
  assert.deepEqual(applyPlace(full, A, "via"), full);
  assert.equal(applyPlace(full, A, "end").length, MAX_POINTS);
});

test("each result has a short type from its OSM tag", () => {
  const type = (osm_key: string | null, osm_value: string | null, kind = "other") => placeType({ kind, osm_key, osm_value });
  assert.equal(type("railway", "station"), "Rail station");
  assert.equal(type("public_transport", "station"), "Station");
  assert.equal(type("shop", "bicycle"), "Bike shop");
  assert.equal(type("leisure", "park"), "Park");
  assert.equal(type("highway", "cycleway"), "Trail");
  assert.equal(type("highway", "residential"), "Street");
  assert.equal(type("place", "house"), "Address");
  assert.equal(type("place", "neighbourhood"), "Neighborhood");
  assert.equal(type("place", "town"), "Town");
  assert.equal(type("amenity", "bicycle_rental"), "Bike share");
  assert.equal(type("highway", "bus_stop"), "Bus stop");
  assert.equal(type(null, null, "trail"), "Trail");
  assert.equal(type("highway", null, "street"), "Street");
  assert.equal(type(null, null, "street"), "Street", "a point named for its street");
  assert.equal(type("amenity", "yes"), "Place", "a bare yes says nothing");
  assert.equal(type("tourism", "information_office"), "Information office");
  assert.equal(type(null, null), "Place");
  assert.equal(type("building", "yes"), "Building");
  const types = new Set([
    type("railway", "station"),
    type("railway", "subway_entrance"),
    type("shop", "bicycle"),
    type("shop", "gift"),
    type("amenity", "restaurant"),
    type("aeroway", "aerodrome"),
  ]);
  assert.equal(types.size, 6, "different places, different types");
});

test("a result keeps its OSM identity and tag, and a malformed one is dropped", async () => {
  const { impl } = respond(200, {
    results: [
      { ...PLACE, osm_type: "N", osm_id: 738189330, osm_key: "railway", osm_value: "station" },
      { ...PLACE, name: "Odd", osm_type: "X", osm_id: 1.5, osm_key: 7, osm_value: null },
    ],
    attribution: [],
  });
  const result = await fetchPlaces("/api/geocode?q=union", impl);
  assert.ok(result.ok);
  const [station, odd] = result.places;
  assert.deepEqual([station.osm_type, station.osm_id, station.osm_key, station.osm_value], ["N", 738189330, "railway", "station"]);
  assert.deepEqual([odd.osm_type, odd.osm_id, odd.osm_key, odd.osm_value], [null, null, null, null]);
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

test("a list is shown only for the query in the box, never one typed past", () => {
  const answer = found(PLACE);
  assert.deepEqual(placesFor("Union  Station ", normalQuery("Union Station"), answer), [PLACE]);
  assert.deepEqual(placesFor("Purcellville", "Baltimore Penn Station", answer), []);
  assert.deepEqual(placesFor("Union Station", "Union Station", { ok: false, status: 502 }), []);
  assert.deepEqual(placesFor("Union Station", "Union Station", null), []);
});

test("a search the geocoder did not answer in time is tried once more", async () => {
  const { timers, api, runner, results } = searchRig();
  runner.request("Lincoln Memorial");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 502 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 2);
  api.calls[1].answer(found(PLACE));
  await flush();
  assert.equal(results.length, 1);
  assert.equal(results[0][1].ok, true);
});
