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
  RETRY_CLOCK_SLACK_MS,
  RETRY_FLOOR_MS,
  applyPlace,
  choicesFor,
  coordinatesText,
  defaultChoice,
  fetchPlaces,
  normalQuery,
  placeKey,
  displayedPlaces,
  comboboxKey,
  choiceInForce,
  nameSender,
  placeFromSearch,
  searchSender,
  searchView,
  placeEffect,
  placeType,
  reverseUrl,
  searchUrl,
  type GeoResult,
  type Place,
  type Timers,
} from "./geocode.ts";
import { COVERAGE_BBOX, MAX_POINTS, type LonLat } from "./geo.ts";
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
  /** How many timers are set and not yet fired or cleared. */
  count(): number {
    return this.pending.size;
  }
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

test("several failed lookups are each asked again, one at a time", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B, C]);
  await timers.advance(NAME_DEBOUNCE_MS);
  for (let i = 0; i < 3; i += 1) {
    api.calls[i].answer({ ok: false, status: 500 });
    await flush();
  }
  await timers.advance(FAILED_RETRY_MS);
  assert.equal(api.calls.length, 4, "one re-ask in flight at a time");
  for (let i = 3; i < 6; i += 1) {
    api.calls[i].answer(found({ ...PLACE, name: `Place ${i}` }));
    await flush();
  }
  assert.equal(api.calls.length, 6);
  assert.ok(namer.name(A) && namer.name(B) && namer.name(C));
  assert.equal(api.maxInFlight(), 1);
});

test("staggered failures: a later failed point is still asked again (round-2 probe)", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 500 }); // A fails at t0
  await flush();
  assert.equal(api.calls.length, 2);
  await timers.advance(10_000);
  api.calls[1].answer({ ok: false, status: 500 }); // B fails 10 s later
  await flush();
  await timers.advance(FAILED_RETRY_MS - 10_000); // A is due
  assert.equal(api.calls.length, 3, "A asked again");
  api.calls[2].answer(found({ ...PLACE, name: "Lincoln Memorial" }));
  await flush();
  await timers.advance(FAILED_RETRY_MS * 4);
  assert.equal(api.calls.length, 4, "B asked again too");
  assert.deepEqual(api.calls[3].arg, B);
});

test("a retry timer that fires a little early by the page's clock still asks again", async () => {
  // Date.now ran 9 ms slow over the 30 s in the round-2 browser run.
  const timers = new FakeTimers();
  const api = fakeSend<LonLat>();
  const namer = new PlaceNamer({ send: api.send, onChange: () => {}, timers, now: () => timers.now * 0.9997 });
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 500 });
  await flush();
  await timers.advance(FAILED_RETRY_MS + 50);
  assert.equal(api.calls.length, 2, "asked when the timer fires, not a floor's wait later");
});

test("while a re-ask is in flight the retry timer does not spin", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 500 });
  await flush();
  await timers.advance(FAILED_RETRY_MS);
  assert.equal(api.calls.length, 2, "re-asked, and the answer is slow");
  const before = timers.delays.length;
  await timers.advance(5_000);
  assert.equal(timers.delays.length, before, "no timer set while it waits");
});

test("a retry that meets a busy moment gets its own busy retry", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 429 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  api.calls[1].answer({ ok: false, status: 500 }); // failed after its busy retry
  await flush();
  await timers.advance(FAILED_RETRY_MS);
  assert.equal(api.calls.length, 3, "asked again after 30 s");
  api.calls[2].answer({ ok: false, status: 429 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 4, "and that re-ask, meeting a busy api, is tried once more");
});

test("the retry timings are the ones written down", () => {
  assert.equal(RETRY_CLOCK_SLACK_MS, 250);
  assert.equal(RETRY_FLOOR_MS, 250);
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

test("coordinates read latitude first", () => {
  assert.match(coordinatesText([-77.05, 38.89]), /38\.89.*-77\.05/);
});

test("the link carries points and ride type only, never a name", () => {
  const hash = encodePlan([A, B], "default");
  assert.deepEqual([...new URLSearchParams(hash.slice(1)).keys()].sort(), ["p", "preset"]);
  assert.equal(decodePlan(hash).points.length, 2);
});

test("a list is shown only for the query in the box, never one typed past", () => {
  const answer = found(PLACE);
  assert.deepEqual(displayedPlaces("Union  Station ", normalQuery("Union Station"), answer), [PLACE]);
  assert.deepEqual(displayedPlaces("Purcellville", "Baltimore Penn Station", answer), []);
  assert.deepEqual(displayedPlaces("Union Station", "Union Station", { ok: false, status: 502 }), []);
  assert.deepEqual(displayedPlaces("Union Station", "Union Station", null), []);
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

// --- the search box's own logic (PlaceSearch.tsx renders from these) ---------

test("the constants riders feel are the ones written down", () => {
  assert.equal(SEARCH_DEBOUNCE_MS, 250);
  assert.equal(NAME_DEBOUNCE_MS, 400);
  assert.equal(RETRY_CAP_MS, 1500);
  assert.equal(MIN_QUERY_CHARS, 3);
  assert.equal(MAX_QUERY_CHARS, 200);
  assert.equal(FAILED_RETRY_MS, 30_000);
});

test("the arrows move through the list and wrap; with no list they do nothing", () => {
  const at = (active: number, key: string, count = 3) =>
    comboboxKey(key, { active, count, expanded: true, hasQuery: true });
  assert.deepEqual(at(-1, "ArrowDown"), { kind: "move", active: 0 });
  assert.deepEqual(at(0, "ArrowDown"), { kind: "move", active: 1 });
  assert.deepEqual(at(2, "ArrowDown"), { kind: "move", active: 0 }, "wraps from the last to the first");
  assert.deepEqual(at(0, "ArrowUp"), { kind: "move", active: 2 }, "wraps from the first to the last");
  assert.deepEqual(at(-1, "ArrowUp"), { kind: "move", active: 2 });
  assert.deepEqual(at(-1, "ArrowDown", 0), { kind: "none" });
});

test("Enter picks the highlighted place, else the first, and nothing from a closed list", () => {
  const enter = (active: number, expanded = true) =>
    comboboxKey("Enter", { active, count: 3, expanded, hasQuery: true });
  assert.deepEqual(enter(1), { kind: "pick", index: 1 });
  assert.deepEqual(enter(-1), { kind: "pick", index: 0 });
  assert.deepEqual(enter(1, false), { kind: "none" }, "a list not showing picks nothing");
  assert.deepEqual(comboboxKey("Enter", { active: -1, count: 0, expanded: true, hasQuery: true }), { kind: "none" });
});

test("Escape closes an open list, then clears the box, then does nothing", () => {
  assert.deepEqual(comboboxKey("Escape", { active: 0, count: 2, expanded: true, hasQuery: true }), { kind: "close" });
  assert.deepEqual(comboboxKey("Escape", { active: -1, count: 2, expanded: false, hasQuery: true }), { kind: "clear" });
  assert.deepEqual(comboboxKey("Escape", { active: -1, count: 0, expanded: false, hasQuery: false }), { kind: "none" });
  assert.deepEqual(comboboxKey("x", { active: -1, count: 2, expanded: true, hasQuery: true }), { kind: "none" });
});

test("the list shown is for the query in the box, never one typed past (the round-0 bug)", () => {
  const answer = found(PLACE);
  assert.deepEqual(displayedPlaces("Purcellville", "Baltimore Penn Station", answer), []);
  assert.deepEqual(displayedPlaces("Baltimore Penn Station", "Baltimore Penn Station", answer), [PLACE]);
});

test("a choice no longer on offer gives way to the plan's default", () => {
  assert.equal(choiceInForce("via", 3, false), "via");
  assert.equal(choiceInForce("via", 1, false), "end", "a stop needs a start and an end");
  assert.equal(choiceInForce("via", MAX_POINTS, true), "end", "a full route takes no stop");
  assert.equal(choiceInForce("start", 2, false), "start");
  assert.equal(choiceInForce(null, 0, false), "start");
  assert.equal(choiceInForce(null, 2, false), "end");
});

test("the search box's request goes ahead of names waiting at the gate", async () => {
  const gate = new GeoGate();
  const order: string[] = [];
  let release: () => void = () => {};
  const answered: GeoResult = found();
  const fetchImpl = (url: string) => {
    order.push(url.split("?")[0]);
    if (order.length > 1) return Promise.resolve(answered);
    return new Promise<GeoResult>((resolve) => {
      release = () => resolve(answered);
    });
  };
  const name = nameSender(gate, fetchImpl);
  const search = searchSender(gate, () => [-77.03, 38.9], fetchImpl);
  const first = name(A);
  const queued = name(B);
  const typed = search("Union Station");
  await flush();
  release();
  await Promise.all([first, queued, typed]);
  assert.deepEqual(order, ["/api/reverse", "/api/geocode", "/api/reverse"]);
});

test("a search is sent with the map's bias; a name with its point", async () => {
  const urls: string[] = [];
  const fetchImpl = async (url: string) => {
    urls.push(url);
    return found();
  };
  await searchSender(new GeoGate(), () => [-77.03, 38.9], fetchImpl)("Union Station");
  await nameSender(new GeoGate(), fetchImpl)(A);
  const search = new URL(urls[0], "http://site.test");
  assert.equal(search.searchParams.get("q"), "Union Station");
  assert.equal(Number(search.searchParams.get("lon")), -77.03);
  const name = new URL(urls[1], "http://site.test");
  assert.equal(name.pathname, "/api/reverse");
  assert.deepEqual([Number(name.searchParams.get("lon")), Number(name.searchParams.get("lat"))], A);
});

test("a picked place keeps the name it was found by; one outside the map is refused", () => {
  const remembered: Array<[LonLat, string, string]> = [];
  const remember = (p: LonLat, name: string, label: string) => {
    remembered.push([p, name, label]);
  };
  assert.deepEqual(placeFromSearch(PLACE, remember), [PLACE.lon, PLACE.lat]);
  assert.deepEqual(remembered, [[[PLACE.lon, PLACE.lat], PLACE.name, PLACE.label]]);
  const outside = { ...PLACE, lon: COVERAGE_BBOX[2] + 0.5 };
  assert.equal(placeFromSearch(outside, remember), null);
  assert.equal(remembered.length, 1, "nothing remembered for a place refused");
});

// --- the mutation review's probes (round 1), kept -----------------------------

test("points about 50 m apart are named apart: the cache is ~10 m, not ~1 km", () => {
  assert.notEqual(placeKey(A), placeKey([A[0] + 0.0006, A[1]]));
});

test("a query of exactly the minimum length is sent", async () => {
  const { timers, api, runner } = searchRig();
  runner.request("Uni");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  assert.equal(api.calls.length, 1);
});

test("a search with no answer at all (status 0) is tried once more", async () => {
  const { timers, api, runner } = searchRig();
  runner.request("Lincoln");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 0 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 2);
});

test("a retry waits out a Retry-After shorter than the cap", async () => {
  const { timers, api, runner } = searchRig();
  runner.request("Lincoln");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 429, retryAfterS: 1 });
  await flush();
  await timers.advance(999);
  assert.equal(api.calls.length, 1, "not before the second it was asked to wait");
  await timers.advance(1);
  assert.equal(api.calls.length, 2);
});

test("a new query gets a retry of its own", async () => {
  const { timers, api, runner } = searchRig();
  runner.request("Lincoln");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 503 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  api.calls[1].answer({ ok: false, status: 503 });
  await flush();
  runner.request("Purcellville");
  await timers.advance(SEARCH_DEBOUNCE_MS);
  api.calls[2].answer({ ok: false, status: 503 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  assert.equal(api.calls.length, 4);
});

test("a name busy twice is not asked a third time straight away", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 429 });
  await flush();
  await timers.advance(RETRY_CAP_MS);
  api.calls[1].answer({ ok: false, status: 429 });
  await flush();
  await timers.advance(RETRY_CAP_MS * 4);
  assert.equal(api.calls.length, 2);
});

test("a search's name, remembered while that point's lookup is in flight, is kept", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A]);
  await timers.advance(NAME_DEBOUNCE_MS);
  namer.remember(A, "Lincoln Memorial");
  api.calls[0].answer(found({ ...PLACE, name: "Henry Bacon Drive Northwest" }));
  await flush();
  assert.equal(namer.name(A)?.name, "Lincoln Memorial");
});

test("the box shows no list, and Enter has nothing to pick, for a query typed past", () => {
  const view = searchView({
    query: "Purcellville",
    answered: "Baltimore Penn Station",
    result: found(PLACE),
    open: true,
    pointCount: 2,
    full: false,
    chosen: null,
  });
  assert.deepEqual(view.places, []);
  assert.equal(view.expanded, false);
  assert.equal(view.searching, true, "the query in the box is still being looked up");
  const enter = comboboxKey("Enter", { active: 0, count: view.places.length, expanded: view.expanded, hasQuery: true });
  assert.deepEqual(enter, { kind: "none" });
});

test("the box's view of an answered query: its places, its choice and what a pick does", () => {
  const view = searchView({
    query: " Union  Station",
    answered: "Union Station",
    result: found(PLACE),
    open: true,
    pointCount: 1,
    full: false,
    chosen: "via",
  });
  assert.deepEqual(view.places, [PLACE]);
  assert.equal(view.expanded, true);
  assert.equal(view.answeredNow, true);
  assert.equal(view.searching, false);
  assert.deepEqual(view.choices, ["start", "end"]);
  assert.equal(view.choice, "end", "a stale stop gives way");
  assert.equal(view.effect, "end");
  const closed = searchView({ query: "Union Station", answered: "Union Station", result: found(PLACE), open: false, pointCount: 0, full: false, chosen: null });
  assert.equal(closed.expanded, false);
  const short = searchView({ query: "Un", answered: "", result: null, open: true, pointCount: 0, full: false, chosen: null });
  assert.equal(short.searching, false, "too short to be looked up");
});

test("a point put back after its lookup failed out of the plan is asked again (undo)", async () => {
  // The round-3 review's probe: Ctrl+Z (wip/tiles) makes this easy to reach.
  const { timers, api, namer } = namerRig();
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  namer.want([B]); // A removed while its request is in flight
  api.calls[0].answer({ ok: false, status: 500 }); // A fails, out of the plan
  await flush();
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[1].answer(found({ ...PLACE, name: "Bee" }));
  await flush();
  namer.want([A, B]); // undo: A is back, failed and not yet due
  await timers.advance(FAILED_RETRY_MS * 4);
  assert.equal(api.calls.length, 3, "A is asked again");
  assert.deepEqual(api.calls[2].arg, A);
});

test("re-arming replaces the retry timer rather than adding one", async () => {
  const { timers, api, namer } = namerRig();
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  api.calls[0].answer({ ok: false, status: 500 });
  await flush();
  await timers.advance(5_000);
  api.calls[1].answer({ ok: false, status: 500 });
  await flush();
  assert.equal(timers.count(), 1, "one retry timer for the two failures");
  namer.want([A, B]);
  namer.want([A, B]);
  await timers.advance(NAME_DEBOUNCE_MS);
  assert.equal(timers.count(), 1, "and still one after the plan is re-sent");
});
