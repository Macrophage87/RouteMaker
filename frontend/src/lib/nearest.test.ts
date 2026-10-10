/** The nearest water, restroom or Metro station (owner, 2026-10-10): the finder's logic, words and panel. */
import assert from "node:assert/strict";
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
  rankNearest,
  requestNearest,
  waterPlaces,
  type NearestAnswer,
  type NearestPlace,
} from "./nearest.ts";
import { NEAREST_SUMMARY, NearestFinder, type FinderProps } from "./nearestFinder.ts";
import type { Station } from "./railStations.ts";
import { WATER_CAUTION, WATER_PREFS_DEFAULT, type WaterPoint } from "./waterRestrooms.ts";

const HERE: LonLat = [-77.05, 38.9];

const WATER: WaterPoint[] = [
  { id: "n1", lon: -77.04, lat: 38.9, water: "p", bottle: true, fee: "no", name: "Mile 4" },
  { id: "n2", lon: -77.03, lat: 38.9, water: "n" },
  { id: "n3", lon: -77.02, lat: 38.9, toilet: "f", water: "p" },
  { id: "n4", lon: -77.01, lat: 38.9, toilet: "b" },
  { id: "n5", lon: -77.0, lat: 38.9, toilet: "u" },
];

const ids = (places: readonly NearestPlace[]) => places.map((p) => p.id);

test("water is drinking water, and untreated water only while its switch is on", () => {
  assert.deepEqual(ids(waterPlaces(WATER, "water", WATER_PREFS_DEFAULT)), ["n1", "n2", "n3"]);
  assert.deepEqual(ids(waterPlaces(WATER, "water", { ...WATER_PREFS_DEFAULT, untreated: false })), ["n1", "n3"]);
});

test("restrooms are every type, portable and pit toilets only while their switch is on", () => {
  assert.deepEqual(ids(waterPlaces(WATER, "restroom", WATER_PREFS_DEFAULT)), ["n3", "n4", "n5"]);
  assert.deepEqual(ids(waterPlaces(WATER, "restroom", { ...WATER_PREFS_DEFAULT, basic: false })), ["n3", "n5"]);
});

test("a water place says what it is, with its name and details, at its own point", () => {
  const [first] = waterPlaces(WATER, "water", WATER_PREFS_DEFAULT);
  assert.equal(first.title, "Drinking water, Mile 4");
  assert.deepEqual(first.details, ["Bottle filler.", "Free."]);
  assert.deepEqual(first.point, [-77.04, 38.9]);
  const [untreated] = waterPlaces([WATER[1]], "water", WATER_PREFS_DEFAULT);
  assert.match(untreated.title, /filter or treat it first/);
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
  assert.equal(foundSaid("water", "location", byBike), "The 3 nearest water by bike from your location, nearest first.");
  assert.equal(foundSaid("metro", "centre", byBike.slice(0, 1)), "The nearest Metro station by bike from the map's center.");
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
