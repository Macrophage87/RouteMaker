/** The nearest water, restroom or Metro station (owner, 2026-10-10): the finder's logic, words and panel. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { startDials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import {
  NEAREST_CANDIDATES,
  NEAREST_SHOWN,
  STRAIGHT_LINE_NOTE,
  foundSaid,
  howFar,
  metroPlaces,
  nearbyText,
  nearestInStraightLine,
  DETOUR_FULL,
  DETOUR_KINDS,
  LOCATION_BUSY,
  detourPoints,
  rideLocate,
  WATER_NOT_LOADED,
  rankNearest,
  requestNearest,
  searchNearest,
  type SearchDeps,
  waterPlaces,
  type NearestAnswer,
  type NearestPlace,
} from "./nearest.ts";
import { NEAREST_SUMMARY, NearestFinder, type FinderProps } from "./nearestFinder.ts";
import type { Station } from "./railStations.ts";
import { WATER_CAUTION, type WaterPoint } from "./waterRestrooms.ts";
import { LOCATE_MESSAGES, LOCATION_OUTSIDE } from "./geolocation.ts";
import { MAX_POINTS, insideCoverage } from "./geo.ts";

const HERE: LonLat = [-77.05, 38.9];

const WATER: WaterPoint[] = [
  { id: "n1", lon: -77.04, lat: 38.9, water: "p", bottle: true, fee: "no", name: "Mile 4" },
  { id: "n2", lon: -77.03, lat: 38.9, water: "n" },
  { id: "n3", lon: -77.02, lat: 38.9, toilet: "f", water: "p" },
  { id: "n4", lon: -77.01, lat: 38.9, toilet: "b" },
  { id: "n5", lon: -77.0, lat: 38.9, toilet: "u" },
];

const ids = (places: readonly NearestPlace[]) => places.map((p) => p.id);

test("water is drinking water only: untreated water is not what a rider asking for water wants", () => {
  assert.deepEqual(ids(waterPlaces(WATER, "water")), ["n1", "n3"]);
});

test("restrooms are every type, each titled with its type", () => {
  const places = waterPlaces(WATER, "restroom");
  assert.deepEqual(ids(places), ["n3", "n4", "n5"]);
  assert.deepEqual(
    places.map((p) => p.title),
    ["Flush restroom, with drinking water", "Portable, pit or composting toilet", "Restroom, type not mapped"],
  );
});

test("a water place says what it is, with its name and details, at its own point", () => {
  const [first] = waterPlaces(WATER, "water");
  assert.equal(first.title, "Drinking water, Mile 4");
  assert.deepEqual(first.details, ["Bottle filler.", "Free."]);
  assert.deepEqual(first.point, [-77.04, 38.9]);
});

const station = (over: Partial<Station>): Station => ({
  id: "metro-1",
  name: "Dupont Circle",
  point: [-77.0434, 38.9096],
  metro: ["red"],
  penn: false,
  elevators: [],
  osmElevators: [],
  entrances: [],
  ...over,
});

test("Metro stations are Metrorail's, each at its bike entrance; MARC-only stations are left out", () => {
  const elevator: LonLat = [-77.0433, 38.9098];
  const stations = [
    station({ elevators: [elevator], entrances: [[-77.0436, 38.9093]] }),
    station({ id: "marc-1", name: "Odenton", metro: [], penn: true }),
    station({ id: "metro-2", name: "Farragut North", point: [-77.0397, 38.9032] }),
  ];
  const places = metroPlaces(stations);
  assert.deepEqual(ids(places), ["metro-1", "metro-2"]);
  assert.deepEqual(places[0].point, elevator, "the elevator, as the station's own End here");
  assert.equal(places[0].title, "Dupont Circle Metro station");
  assert.deepEqual(places[0].details, ["Red line.", "Routes use its elevator, the way in with a bike."]);
  assert.deepEqual(places[1].point, [-77.0397, 38.9032], "with nothing listed, the station itself");
});

const place = (id: string, point: LonLat): NearestPlace => ({ id, kind: "water", point, title: `Place ${id}`, details: [] });

test("the candidates are the nearest in straight lines, nearest first, at most NEAREST_CANDIDATES", () => {
  const far = Array.from({ length: 12 }, (_, i) => place(`p${i}`, [-77.05 + 0.01 * (12 - i), 38.9]));
  const picked = nearestInStraightLine(HERE, far);
  assert.equal(picked.length, NEAREST_CANDIDATES);
  assert.deepEqual(ids(picked).slice(0, 3), ["p11", "p10", "p9"]);
  assert.ok(NEAREST_CANDIDATES <= 10, "the API takes at most ten places");
  // A tie keeps the order given.
  assert.deepEqual(ids(nearestInStraightLine(HERE, [place("a", [-77.04, 38.9]), place("b", [-77.06, 38.9])], 2)), ["a", "b"]);
});

const CANDIDATES = [place("a", [-77.04, 38.9]), place("b", [-77.03, 38.9]), place("c", [-77.02, 38.9]), place("d", [-77.01, 38.9])];

test("the three nearest by bike are offered, and one the router cannot reach is left out", () => {
  const answer: NearestAnswer = {
    by: "riding",
    places: [
      { distance_m: 3000, time_s: 600 }, // nearest in a straight line, but a long way round
      { distance_m: 1200, time_s: 240 },
      { distance_m: null, time_s: null },
      { distance_m: 2000, time_s: 400 },
    ],
  };
  const ranked = rankNearest(CANDIDATES, answer);
  assert.equal(ranked.length, NEAREST_SHOWN);
  assert.deepEqual(ranked.map((r) => r.place.id), ["b", "d", "a"]);
  assert.deepEqual(ranked[0], { place: CANDIDATES[1], distanceM: 1200, timeS: 240, byBike: true });
});

test("by straight line, the order is the straight line's and there is no time", () => {
  const answer: NearestAnswer = {
    by: "straight_line",
    places: [
      { distance_m: 860, time_s: null },
      { distance_m: 1730, time_s: null },
      { distance_m: 2600, time_s: null },
      { distance_m: 3460, time_s: null },
    ],
  };
  const ranked = rankNearest(CANDIDATES, answer);
  assert.deepEqual(ranked.map((r) => r.place.id), ["a", "b", "c"]);
  assert.ok(ranked.every((r) => !r.byBike && r.timeS === null));
  assert.equal(howFar(ranked[0]), "0.5 mi (0.9 km) in a straight line");
});

test("each line says what, how far by bike in US units first, about how long, and its details", () => {
  const item = { place: { ...CANDIDATES[0], title: "Drinking water, Mile 4", details: ["Bottle filler.", "Free."] }, distanceM: 1609.344, timeS: 300, byBike: true };
  assert.equal(nearbyText(item), "Drinking water, Mile 4: 1.0 mi (1.6 km) by bike, about 5 min. Bottle filler. Free.");
  assert.equal(howFar({ ...item, distanceM: 100, timeS: 30 }), "330 ft (100 m) by bike, about 1 min");
});

test("the status line says how many, of what, from where, and how they were measured", () => {
  const byBike = rankNearest(CANDIDATES, {
    by: "riding",
    places: CANDIDATES.map((_, i) => ({ distance_m: 1000 * (i + 1), time_s: 100 })),
  });
  assert.equal(
    foundSaid("water", "location", byBike),
    "The 3 nearest water by bike from your location, nearest first. Nearest: Place a, 0.6 mi (1.0 km) by bike, about 2 min.",
  );
  assert.equal(
    foundSaid("metro", "centre", byBike.slice(0, 1)),
    "The nearest Metro station by bike from the map's center. Nearest: Place a, 0.6 mi (1.0 km) by bike, about 2 min.",
  );
  const straight = byBike.map((r) => ({ ...r, byBike: false, timeS: null }));
  assert.ok(foundSaid("restroom", "start", straight).endsWith(STRAIGHT_LINE_NOTE));
  assert.equal(foundSaid("restroom", "start", []), "No restrooms could be reached by bike from the start of the plan.");
});

test("the request sends where the rider is, then the places, with the dials but not the weight, loop or target", async () => {
  const sent: Array<{ url: string; body: Record<string, unknown> }> = [];
  const fetchImpl = async (url: string, init: RequestInit) => {
    sent.push({ url, body: JSON.parse(String(init.body)) });
    return new Response(JSON.stringify({ by: "riding", places: [{ distance_m: 1, time_s: 1 }, { distance_m: 2, time_s: 2 }] }), { status: 200 });
  };
  const dials = { ...startDials("default"), systemWeightKg: 80, targetDistanceM: 40_000, loop: true };
  const result = await requestNearest(HERE, CANDIDATES.slice(0, 2), "default", dials, fetchImpl);
  assert.ok(result.ok);
  assert.equal(sent[0].url, "/api/nearest");
  assert.deepEqual(sent[0].body.points, [HERE, [-77.04, 38.9], [-77.03, 38.9]]);
  assert.equal(sent[0].body.preset, "default");
  assert.equal(sent[0].body.stress, dials.stress);
  assert.equal(sent[0].body.system_weight_kg, undefined);
  assert.equal(sent[0].body.target_distance_m, undefined);
  assert.equal(sent[0].body.loop, undefined);
});

test("on Bikeshare the search rides like the default type: no dock walk, no bike fields, any number of places", async () => {
  const sent: Array<Record<string, unknown>> = [];
  const fetchImpl = async (_url: string, init: RequestInit) => {
    sent.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ by: "riding", places: CANDIDATES.map(() => ({ distance_m: 1, time_s: 1 })) }), { status: 200 });
  };
  const dials = { ...startDials("bikeshare"), bike: "ebike" as const, ending: "outside_dock" as const, pickupStation: "s1", dropoffStation: "s2" };
  const result = await requestNearest(HERE, CANDIDATES, "bikeshare", dials, fetchImpl);
  assert.ok(result.ok);
  assert.equal(sent[0].preset, "default");
  for (const field of ["bike", "ending", "pickup_station", "dropoff_station", "loop"]) assert.equal(sent[0][field], undefined, field);
  assert.equal((sent[0].points as unknown[]).length, 1 + CANDIDATES.length);
});

test("a refusal, a lost connection or an answer of the wrong shape is a sentence to say", async () => {
  const busy = await requestNearest(HERE, CANDIDATES, "default", startDials("default"), async () =>
    new Response(JSON.stringify({ error: "busy" }), { status: 503, headers: { "Retry-After": "5" } }),
  );
  assert.ok(!busy.ok && busy.message.length > 0);
  const lost = await requestNearest(HERE, CANDIDATES, "default", startDials("default"), async () => {
    throw new TypeError("offline");
  });
  assert.ok(!lost.ok && /connection/.test(lost.message));
  const short = await requestNearest(HERE, CANDIDATES, "default", startDials("default"), async () =>
    new Response(JSON.stringify({ by: "riding", places: [] }), { status: 200 }),
  );
  assert.ok(!short.ok, "one entry per place, or it is not used");
});

const props = (over: Partial<FinderProps> = {}): FinderProps => ({
  from: "location",
  fromOptions: ["location", "centre"],
  onFrom: () => {},
  onFind: () => {},
  busy: false,
  status: "",
  list: null,
  canAddStop: false,
  onRide: () => {},
  onAddStop: () => {},
  ...over,
});

const items = rankNearest(CANDIDATES, { by: "riding", places: CANDIDATES.map((_, i) => ({ distance_m: 500 * (i + 1), time_s: 60 })) });

test("the panel: a fold with where from, three buttons and a status line that is always there", () => {
  const html = renderToStaticMarkup(createElement(NearestFinder, props()));
  assert.ok(html.startsWith('<details class="fold nearest"><summary>' + NEAREST_SUMMARY));
  assert.match(html, /<legend>Search from<\/legend>/);
  assert.match(html, /type="radio" name="nearest-from" checked="" value="location"/);
  for (const label of ["Nearest water", "Nearest restroom", "Nearest Metro"]) assert.ok(html.includes(`>${label}</button>`), label);
  assert.match(html, /<p class="hint nearest-status" role="status"><\/p>/);
  assert.ok(!html.includes("<ol"));
  assert.ok(!html.includes("aria-disabled"));
  assert.match(renderToStaticMarkup(createElement(NearestFinder, props({ busy: true }))), /aria-disabled="true"/);
});

test("the list: each place in words with Ride here, and Add as stop for water in a planned ride", () => {
  const html = renderToStaticMarkup(createElement(NearestFinder, props({ list: { kind: "water", items }, canAddStop: true })));
  assert.match(html, /<h3 id="nearest-list-heading">Nearest water<\/h3>/);
  assert.match(html, /<ol role="list" aria-labelledby="nearest-list-heading">/);
  assert.equal((html.match(/>Ride here</g) ?? []).length, 3);
  assert.equal((html.match(/>Add as stop</g) ?? []).length, 3);
  assert.ok(html.includes('aria-label="Ride here: Place a"'));
  assert.ok(html.includes(WATER_CAUTION));
  const noPlan = renderToStaticMarkup(createElement(NearestFinder, props({ list: { kind: "water", items } })));
  assert.ok(!noPlan.includes(">Add as stop<"), "no plan, nothing to add a stop to");
  const metro = renderToStaticMarkup(createElement(NearestFinder, props({ list: { kind: "metro", items }, canAddStop: true })));
  assert.ok(!metro.includes(">Add as stop<"), "a Metro station is where a ride ends");
  assert.ok(!metro.includes(WATER_CAUTION));
});

// --- One search, start to end (App's findNearest hands it the page's parts) ---

const DUPONT = station({ elevators: [[-77.0433, 38.9098]] });
const FAR_STATION = station({ id: "metro-9", name: "Shady Grove", point: [-77.1462, 39.1199] });

function deps(over: Partial<SearchDeps> = {}): SearchDeps & { asked: Array<{ from: LonLat; places: readonly NearestPlace[] }> } {
  const asked: Array<{ from: LonLat; places: readonly NearestPlace[] }> = [];
  return {
    asked,
    kind: "water",
    from: "location",
    locate: async () => ({ ok: true, fix: { point: HERE, accuracyM: 20 } }),
    start: () => null,
    centre: () => [-77.0365, 38.8977],
    inside: insideCoverage,
    water: async () => WATER,
    stations: [FAR_STATION, DUPONT],
    request: async (from, places) => {
      asked.push({ from, places });
      return { ok: true, answer: { by: "riding", places: places.map((_, i) => ({ distance_m: 1000 * (places.length - i), time_s: 60 })) } };
    },
    ...over,
  };
}

test("a search from the rider's location: the fix is kept, the places are sent from it, the nearest by bike come back", async () => {
  const d = deps();
  const outcome = await searchNearest(d);
  assert.deepEqual(outcome.fix, { point: HERE, accuracyM: 20 });
  assert.deepEqual(d.asked[0].from, HERE);
  assert.deepEqual(ids(d.asked[0].places), ["n1", "n3"], "drinking water, nearest in a straight line first");
  assert.deepEqual(outcome.found?.items.map((i) => i.place.id), ["n3", "n1"], "then by bike");
  assert.deepEqual(outcome.found?.origin, HERE);
  assert.equal(outcome.found?.from, "location");
  assert.match(outcome.said, /^The 2 nearest water by bike from your location/);
});

test("from the map's center or the plan's start, no look-up is made", async () => {
  let looked = 0;
  const locate = async () => {
    looked += 1;
    return { ok: true as const, fix: { point: HERE, accuracyM: 5 } };
  };
  const centre = deps({ from: "centre", locate });
  await searchNearest(centre);
  assert.deepEqual(centre.asked[0].from, [-77.0365, 38.8977]);
  const start = deps({ from: "start", locate, start: () => [-77.04, 38.91] });
  const outcome = await searchNearest(start);
  assert.deepEqual(start.asked[0].from, [-77.04, 38.91]);
  assert.equal(outcome.fix, undefined);
  assert.equal(looked, 0);
  assert.equal((await searchNearest(deps({ from: "start" }))).said, "There is nowhere to search from yet.");
});

test("Metro: Metrorail's stations at their bike entrance", async () => {
  const d = deps({ kind: "metro" });
  const outcome = await searchNearest(d);
  assert.deepEqual(d.asked[0].places.map((p) => p.point), [[-77.0433, 38.9098], FAR_STATION.point]);
  assert.equal(outcome.found?.kind, "metro");
});

test("a look-up that is busy, refused or outside the map ends the search with its reason, asking nothing", async () => {
  const busy = deps({ locate: async () => "busy" });
  assert.equal((await searchNearest(busy)).said, LOCATION_BUSY);
  const denied = deps({ locate: async () => ({ ok: false, reason: "denied" }) });
  assert.equal((await searchNearest(denied)).said, LOCATE_MESSAGES.denied);
  const away = deps({ locate: async () => ({ ok: true, fix: { point: [-80, 38.9], accuracyM: 5 } }) });
  const outcome = await searchNearest(away);
  assert.equal(outcome.said, LOCATION_OUTSIDE);
  assert.ok(outcome.fix, "the fix is still the rider's, for the circle");
  assert.equal((await searchNearest(deps({ from: "centre", centre: () => [-80, 38.9] }))).said, "That spot is outside the area this map covers.");
  for (const d of [busy, denied, away]) assert.equal(d.asked.length, 0);
});

test("no water file, no places, or a refusal is said, and nothing is listed", async () => {
  const noFile = await searchNearest(deps({ water: async () => null }));
  assert.equal(noFile.said, WATER_NOT_LOADED);
  assert.equal(noFile.found, undefined);
  const none = await searchNearest(deps({ water: async () => [] }));
  assert.equal(none.said, "No water on the map to search.");
  const refused = await searchNearest(deps({ request: async () => ({ ok: false, message: "Too many requests." }) }));
  assert.equal(refused.said, "The search failed. Too many requests.");
  assert.equal(refused.found, undefined);
});

// --- While riding: water and restrooms as detours (RideMode.tsx) ---

test("riding: the ride's own fix is the search's position, and none yet is said, not looked up", async () => {
  assert.deepEqual(rideLocate({ point: HERE, accuracyM: 12 }), { ok: true, fix: { point: HERE, accuracyM: 12 } });
  assert.deepEqual(rideLocate(null), { ok: false, reason: "unavailable" });
  const d = deps({ locate: async () => rideLocate({ point: HERE, accuracyM: 12 }), kind: "restroom" });
  const outcome = await searchNearest(d);
  assert.deepEqual(d.asked[0].from, HERE);
  assert.equal(outcome.found?.kind, "restroom");
});

test("riding: only water and restrooms are offered as detours", () => {
  assert.deepEqual([...DETOUR_KINDS], ["water", "restroom"]);
});

test("a detour goes from here to the place, then on through the stops left and the end", () => {
  const here: LonLat = [-77.05, 38.9];
  const stop: LonLat = [-77.0, 38.92];
  const end: LonLat = [-76.98, 38.95];
  const fountain: LonLat = [-77.04, 38.905];
  assert.deepEqual(detourPoints([here, stop, end], fountain), [here, fountain, stop, end]);
  assert.deepEqual(detourPoints([here, end], fountain), [here, fountain, end]);
});

test("a detour is refused, not cut short, when the route already has as many points as one can take", () => {
  const here: LonLat = [-77.05, 38.9];
  const fountain: LonLat = [-77.04, 38.905];
  const almost = Array.from({ length: MAX_POINTS - 1 }, (_, i): LonLat => [-77.05 + i * 0.001, 38.9]);
  assert.equal(detourPoints(almost, fountain)?.length, MAX_POINTS);
  assert.equal(detourPoints([...almost, here], fountain), null);
  assert.match(DETOUR_FULL, new RegExp(`${MAX_POINTS} points`));
});

test("Ride mode wires the detour: the ride's fix, the ride's settings without the loop, and a re-plan through the place", () => {
  const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");
  assert.match(ride, /const points = via \? detourPoints\(left, via\) : left;/);
  assert.match(ride, /locate: async \(\) => rideLocate\(fix\)/);
  assert.match(ride, /requestNearest\(from, places, preset, \{ \.\.\.dials, loop: false \}\)/);
  assert.match(ride, /void replan\(here, item\.place\.point\);/);
  // The rider's own ask is never dropped in silence: a full route, a busy gate and the outcome are said
  // through sayDetour (an answer, whatever the verbosity), and the focus goes to Where am I?.
  assert.match(ride, /if \(!points\) \{\s*sayDetour\(DETOUR_FULL\);/);
  assert.match(ride, /if \(!gate\.begin\(Date\.now\(\)\)\) \{[^}]*if \(via\) sayDetour\(DETOUR_BUSY\);/);
  assert.match(ride, /const tell = \(note: string\) => \{\s*if \(via\) \{\s*sayDetour\(note\);/);
  assert.match(ride, /if \(gate\.busy\) \{\s*sayDetour\(DETOUR_BUSY\);/);
  assert.match(ride, /whereRef\.current\?\.focus\(\);\s*sayDetour\(`Finding a way to/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /water=\{ensureWater\}/);
});
