/** Find food (FOOD-SEARCH, owner 2026-10-11): the file, the matching, the detour, the words, the panel and the markers. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { LonLat } from "./geo.ts";
import {
  CIRCUITY,
  FOOD_SYNONYMS,
  NO_FOOD_DATA,
  ON_ROUTE_M,
  detourOf,
  foodFoundSaid,
  foodHowFar,
  foodKindText,
  foodTerms,
  foodText,
  loadFood,
  matchesFood,
  normaliseQuery,
  parseFood,
  projector,
  routeForDetour,
  searchFood,
  type FoodPlace,
  type FoodResult,
} from "./food.ts";
import { FOOD_SUMMARY, FoodFinder, type FoodFinderProps } from "./foodFinder.ts";
import { appSource } from "../testSupport/appSource.mjs";

const place = (id: string, name: string, cuisine: string[], lon = -77.0, lat = 38.9, kind: FoodPlace["kind"] = "r"): FoodPlace => ({
  id,
  lon,
  lat,
  kind,
  name,
  cuisine,
});

test("the file: places with a name and a kind; cuisine split; only web addresses kept", () => {
  const parsed = parseFood({
    points: [
      { id: "n1", x: -77, y: 38.9, k: "r", n: "Crab House", c: "seafood;Crab", h: "Mo-Su 11:00-22:00", web: "https://crab.example" },
      { id: "n2", x: -77, y: 38.9, k: "r" }, // no name
      { id: "n3", x: -77, y: 38.9, k: "bar", n: "Bar" }, // not a kind
      { id: "n4", x: "x", y: 38.9, k: "c", n: "Bad" },
      { id: "n5", x: -77, y: 38.9, k: "c", n: "Cafe", web: "javascript:alert(1)" },
    ],
  });
  assert.deepEqual(parsed, [
    { id: "n1", lon: -77, lat: 38.9, kind: "r", name: "Crab House", cuisine: ["seafood", "crab"], hours: "Mo-Su 11:00-22:00", website: "https://crab.example" },
    { id: "n5", lon: -77, lat: 38.9, kind: "c", name: "Cafe", cuisine: [] },
  ]);
  assert.equal(parseFood({ nope: 1 }), null);
  assert.deepEqual(parseFood({ points: [] }), []);
});

test("the committed file parses (an empty placeholder until the v0.5.0 rebuild is a list, not a failure)", () => {
  const raw = JSON.parse(readFileSync(new URL("../amenity-data/food.json", import.meta.url), "utf8"));
  const places = parseFood(raw);
  assert.ok(Array.isArray(places));
  assert.equal(raw.source, "OpenStreetMap contributors, ODbL 1.0");
});

test("loading: an empty file is an empty list (No food data yet), a failure is null", async () => {
  const ok = (body: unknown) => async () => ({ ok: true, json: async () => body });
  assert.deepEqual(await loadFood("u", ok({ points: [] })), []);
  assert.equal(await loadFood("u", async () => ({ ok: false, json: async () => ({}) })), null);
  assert.equal(await loadFood("u", async () => { throw new Error("offline"); }), null);
  assert.match(NO_FOOD_DATA, /^No food data yet/);
});

test("queries are normalised", () => {
  assert.equal(normaliseQuery("  Crab-House!  "), "crab-house");
  assert.equal(normaliseQuery("Ben's   Chili Bowl"), "ben's chili bowl");
  assert.equal(foodTerms("   "), null);
});

test("crab finds seafood places, and pizza places by cuisine or name", () => {
  const crab = foodTerms("crab")!;
  assert.ok(matchesFood(place("n1", "The Dock", ["seafood"]), crab));
  assert.ok(matchesFood(place("n2", "Shack", ["crab"]), crab));
  assert.ok(matchesFood(place("n3", "Crab Cake Corner", []), crab));
  assert.ok(!matchesFood(place("n4", "Slice", ["pizza"]), crab));
  const pizza = foodTerms("Pizza")!;
  assert.ok(matchesFood(place("n4", "Slice", ["pizza"]), pizza));
  assert.ok(matchesFood(place("n5", "Joe's Pizza", ["italian"]), pizza));
  assert.ok(!matchesFood(place("n6", "Trattoria", ["italian"]), pizza));
});

test("plurals, parts of a cuisine value and kinds", () => {
  assert.ok(matchesFood(place("n1", "A", ["crab"]), foodTerms("crabs")!));
  assert.ok(matchesFood(place("n1", "A", ["sandwich"]), foodTerms("sandwiches")!));
  assert.ok(matchesFood(place("n1", "A", ["fried_chicken"]), foodTerms("chicken")!));
  // "food" is not a part of "seafood".
  assert.ok(!matchesFood(place("n1", "A", ["seafood"]), foodTerms("food")!));
  assert.ok(matchesFood(place("n1", "Corner", [], -77, 38.9, "c"), foodTerms("coffee")!));
  assert.ok(matchesFood(place("n1", "Scoops", [], -77, 38.9, "i"), foodTerms("ice cream")!));
  assert.ok(matchesFood(place("n1", "A", ["ice_cream"]), foodTerms("ice cream")!));
  assert.ok(matchesFood(place("n1", "The Local", [], -77, 38.9, "p"), foodTerms("beer")!));
  // A word not in the list still finds its own cuisine value.
  assert.ok(matchesFood(place("n1", "A", ["ethiopian"]), foodTerms("Ethiopian")!));
});

test("the synonym list's words are singular and lower case, and crab is in it", () => {
  for (const [word, values] of Object.entries(FOOD_SYNONYMS)) {
    assert.equal(word, normaliseQuery(word));
    assert.ok(values.length > 0);
  }
  assert.deepEqual([...FOOD_SYNONYMS.crab].sort(), ["crab", "seafood"]);
});

// A straight route east along 38.9 N, 10 km long, at 4 m/s.
const ROUTE_LINE: LonLat[] = [
  [-77.1, 38.9],
  [-76.98451, 38.9],
];

test("the nearest spot on the route: how far off and how far along", () => {
  const project = projector(ROUTE_LINE);
  const { offM, alongM } = project([-77.05, 38.901]);
  assert.ok(Math.abs(offM - 111.3) < 1, `off ${offM}`);
  assert.ok(Math.abs(alongM - 4330) < 20, `along ${alongM}`);
  // Past the end: the end is nearest.
  assert.ok(Math.abs(project([-76.9, 38.9]).alongM - 10000) < 30);
});

test("the detour: there and back times the circuity, at the route's speed; nothing on the route", () => {
  assert.deepEqual(detourOf(ON_ROUTE_M - 1, 4), { extraM: 0, extraS: 0 });
  const d = detourOf(500, 4);
  assert.equal(d.extraM, 2 * 500 * CIRCUITY);
  assert.equal(d.extraS, (2 * 500 * CIRCUITY) / 4);
});

test("the route for a detour: its line and average speed; none without a usable route", () => {
  const r = routeForDetour({ geometry: { coordinates: ROUTE_LINE }, distance_m: 10_000, duration_s: 2_500 });
  assert.equal(r?.speedMps, 4);
  assert.equal(routeForDetour(null), null);
  assert.equal(routeForDetour({ geometry: { coordinates: ROUTE_LINE }, distance_m: 10_000, duration_s: 0 }), null);
});

const PLACES: FoodPlace[] = [
  place("n1", "Far Crab", ["seafood"], -77.05, 38.95), // ~5.6 km off the route
  place("n2", "Near Crab", ["crab"], -77.0, 38.902), // ~220 m off
  place("n3", "Pizza", ["pizza"], -77.0, 38.9),
  place("n4", "On Route Crab", ["seafood"], -77.08, 38.9), // on it, early
  place("n5", "Out of view Crab", ["crab"], -76.5, 39.3),
];

test("search: in the view, sorted by detour with a route, no distance cap", () => {
  const route = { line: ROUTE_LINE, speedMps: 4 };
  const results = searchFood(PLACES, { query: "crab", scope: "view", bounds: [-77.2, 38.8, -76.9, 39.0], centre: [-77.0, 38.9], route });
  assert.deepEqual(results.map((r) => r.place.id), ["n4", "n2", "n1"]);
  assert.equal(results[0].detour?.extraM, 0);
  // The whole area adds the one out of view, last (the biggest detour), however far.
  const all = searchFood(PLACES, { query: "crab", scope: "area", bounds: [-77.2, 38.8, -76.9, 39.0], centre: [-77.0, 38.9], route });
  assert.deepEqual(all.map((r) => r.place.id), ["n4", "n2", "n1", "n5"]);
});

test("search without a route: by distance from the map's center, no detour", () => {
  const results = searchFood(PLACES, { query: "crab", scope: "area", bounds: null, centre: [-77.0, 38.9], route: null });
  assert.deepEqual(results.map((r) => r.place.id), ["n2", "n4", "n1", "n5"]);
  assert.equal(results[0].detour, undefined);
  assert.deepEqual(searchFood(PLACES, { query: " ", scope: "area", bounds: null, centre: [-77, 38.9], route: null }), []);
});

test("words: US units first with metric in brackets; the detour, the turn-off and the hours", () => {
  const r: FoodResult = {
    place: { ...place("n2", "Near Crab", ["seafood", "soft_shell_crab"]), hours: "Mo-Su 11:00-22:00" },
    fromCentreM: 800,
    detour: { offM: 300, alongM: 19_800, extraM: 840, extraS: 210 },
  };
  assert.equal(foodKindText(r.place), "Restaurant: seafood, soft shell crab");
  assert.equal(foodHowFar(r), "Detour about +0.5 mi (0.8 km) and 4 min there and back, turning off at 12.3 mi (19.8 km) on your route.");
  assert.equal(
    foodText(r),
    "Near Crab. Restaurant: seafood, soft shell crab. Detour about +0.5 mi (0.8 km) and 4 min there and back, turning off at 12.3 mi (19.8 km) on your route. Hours as mapped: Mo-Su 11:00-22:00.",
  );
  assert.equal(foodHowFar({ ...r, detour: { ...r.detour!, extraM: 0, extraS: 0 } }), "On your route at 12.3 mi (19.8 km).");
  // Just past the on-route margin the detour rounds to 0.0 mi: on your route, not "+0.0 mi (0.0 km)".
  assert.equal(foodHowFar({ ...r, detour: { offM: 20, alongM: 19_800, extraM: 56, extraS: 14 } }), "On your route at 12.3 mi (19.8 km).");
  assert.equal(foodHowFar({ ...r, detour: { offM: 28, alongM: 19_800, extraM: 80, extraS: 20 } }), "On your route at 12.3 mi (19.8 km).");
  assert.match(foodHowFar({ ...r, detour: { offM: 29, alongM: 19_800, extraM: 81, extraS: 20 } }), /^Detour about \+0\.1 mi \(0\.1 km\)/);
  assert.equal(foodHowFar({ place: r.place, fromCentreM: 800 }), "0.5 mi (0.8 km) from the map's center in a straight line.");
});

test("the status line says the count, where and the order", () => {
  assert.equal(foodFoundSaid(" Crab ", "view", 12, 10, true), "12 places match “crab” in the map view, least detour first. Showing the first 10.");
  assert.equal(foodFoundSaid("pizza", "area", 1, 1, false), "1 place matches “pizza” in the whole area, nearest the map's center first.");
  assert.equal(foodFoundSaid("crab", "view", 0, 0, true), "No places match “crab” in the map view. Try Search the whole area, or move the map.");
  assert.equal(foodFoundSaid("crab", "area", 0, 0, true), "No places match “crab” in the whole area.");
});

const noop = () => {};
const baseProps: FoodFinderProps = {
  query: "crab",
  onQuery: noop,
  scope: "view",
  onScope: noop,
  onSearch: noop,
  busy: false,
  status: "",
  results: null,
  total: 0,
  onMore: noop,
  canAddStop: true,
  onShow: noop,
  onAddStop: noop,
};

test("the panel: a labelled search, the two scopes, a status line, collapsed", () => {
  const html = renderToStaticMarkup(createElement(FoodFinder, baseProps));
  assert.match(html, /^<details class="fold food"><summary>Find food<\/summary>/);
  assert.equal(FOOD_SUMMARY, "Find food");
  assert.match(html, /<form role="search" aria-label="Find food"/);
  assert.match(html, /<label for="food-query"[^>]*>Food or name<\/label>/);
  assert.match(html, /<input id="food-query" type="search"/);
  assert.match(html, /In the map view/);
  assert.match(html, /Search the whole area/);
  assert.match(html, /<p class="hint food-status" role="status"><\/p>/);
  assert.doesNotMatch(html, /<ol/);
});

test("the panel's list: lettered as the markers, Show on map, Add as stop, website, Show more", () => {
  const results: FoodResult[] = [
    { place: { ...place("n2", "Near Crab", ["crab"]), website: "https://crab.example" }, fromCentreM: 100, detour: { offM: 300, alongM: 1000, extraM: 840, extraS: 210 } },
    { place: place("n4", "Dock", ["seafood"]), fromCentreM: 200, detour: { offM: 1, alongM: 500, extraM: 0, extraS: 0 } },
  ];
  const html = renderToStaticMarkup(createElement(FoodFinder, { ...baseProps, results, total: 25 }));
  assert.match(html, /<ol role="list" aria-labelledby="food-list-heading">/);
  assert.match(html, /<strong>A\. Near Crab<\/strong>/);
  assert.match(html, /<strong>B\. Dock<\/strong>/);
  assert.match(html, /aria-label="Show on map: Near Crab, marker A"/);
  assert.doesNotMatch(html, /Ride here/, "Ride here is Go's (onRide)");
  assert.match(html, /aria-label="Add as stop: Dock"/);
  assert.match(html, /href="https:\/\/crab.example" target="_blank" rel="noopener noreferrer" aria-label="Website: Near Crab \(opens in a new tab\)"/);
  assert.match(html, />Show 10 more</);
  assert.match(html, /Detours are estimates/);
  // No plan to add to: no Add as stop.
  const none = renderToStaticMarkup(createElement(FoodFinder, { ...baseProps, results, total: 2, canAddStop: false }));
  assert.doesNotMatch(none, /aria-label="Add as stop/);
  assert.doesNotMatch(none, /Show \d+ more/);
});


test("the planner renders Find food right after the nearest finder, and fetches the file only on a search", () => {
  const app = appSource();
  const nearest = app.indexOf("<NearestFinder");
  const food = app.indexOf("{foodFinder}");
  assert.ok(nearest > 0 && food > nearest, "Find food follows the nearest finder");
  assert.match(app, /import foodUrl from "\.\/amenity-data\/food\.json\?url&no-inline";/);
  assert.match(app, /loadFood\(foodUrl\)/);
  // Add as stop is the road panel's own: the coverage check, the cap, an edit like any other.
  assert.match(app, /placeSpot\("via", point\)/);
});
