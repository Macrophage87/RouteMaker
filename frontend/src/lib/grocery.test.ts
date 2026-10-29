/** The Eat sheet's Grocery chip (the owner, 2026-10-28): grocery stores nearest the start, from the geocoder. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { foodHowFar, foodText } from "./food.ts";
import { FoodFinder, type FoodFinderProps } from "./foodFinder.ts";
import type { LonLat } from "./geo.ts";
import type { Place } from "./geocode.ts";
import { GROCERY_HEADING, GROCERY_QUERY, groceryFoundSaid, groceryResults, isGroceryQuery } from "./grocery.ts";

const START: LonLat = [-77.0369, 38.9072];
const store = (name: string, lon: number, lat: number, id: number, value = "supermarket", key = "shop"): Place => ({
  name,
  label: `${name}, Washington`,
  lon,
  lat,
  kind: "house",
  osm_type: "N",
  osm_id: id,
  osm_key: key,
  osm_value: value,
});

test("the chip's words, and the same words typed, are a grocery search; food words are not", () => {
  for (const q of ["grocery", "Groceries", " grocery store ", "Supermarket", "supermercado"]) assert.ok(isGroceryQuery(q), q);
  for (const q of ["", "crab", "farm stands", "market", "grocery outlet bakery"]) assert.ok(!isGroceryQuery(q), q);
  // One of the server's tag searches (src/core/geocode.py TAG_SEARCHES): shop=supermarket near the bias point.
  assert.equal(GROCERY_QUERY, "supermarket");
  const tags = readFileSync(new URL("../../../src/core/geocode.py", import.meta.url), "utf8");
  assert.match(tags, /phrase: "shop:supermarket"[\s\S]*?"supermarket",/);
});

test("the stores are listed nearest the start first, as food rows with their distance and no hours", () => {
  const far = store("Giant", -77.0, 38.95, 2);
  const near = store("Whole Foods Market", -77.0336, 38.9094, 1);
  // A store named for its kind is not put ahead of a nearer one.
  const named = store("Mid Supermarket", -77.02, 38.92, 3);
  const results = groceryResults([far, named, near], START, "rider");
  assert.deepEqual(results.map((r) => r.place.name), ["Whole Foods Market", "Mid Supermarket", "Giant"]);
  const first = results[0];
  assert.deepEqual(first.place, { id: "n1", lon: -77.0336, lat: 38.9094, kind: "g", name: "Whole Foods Market", cuisine: [] });
  assert.ok(first.fromCentreM > 300 && first.fromCentreM < 500, String(first.fromCentreM));
  assert.equal(foodHowFar(first), "0.2 mi (0.4 km) from you in a straight line.");
  assert.equal(foodText(first), "Whole Foods Market. Grocery store. 0.2 mi (0.4 km) from you in a straight line.");
  // From a start typed in: "from your start".
  assert.equal(foodHowFar(groceryResults([near], START, "start")[0]), "0.2 mi (0.4 km) from your start in a straight line.");
  assert.equal(foodHowFar(groceryResults([near], START, "centre")[0]), "0.2 mi (0.4 km) from the map's center in a straight line.");
});

test("only grocery shops in the map's area, once each", () => {
  const results = groceryResults(
    [
      store("Safeway", -77.04, 38.91, 5),
      store("Safeway", -77.04, 38.91, 5),
      store("Safeway Pharmacy", -77.04, 38.91, 6, "pharmacy", "amenity"),
      store("Corner Market", -77.03, 38.9, 7, "convenience"),
      store("Fresh Greens", -77.03, 38.905, 8, "greengrocer"),
      store("Far Away Foods", -74.0, 40.7, 9),
    ],
    START,
    "rider",
  );
  assert.deepEqual(results.map((r) => r.place.name).sort(), ["Corner Market", "Fresh Greens", "Safeway"]);
});

test("the status line says how many and from where", () => {
  assert.equal(groceryFoundSaid(0, "rider"), "No grocery stores found near here.");
  assert.equal(groceryFoundSaid(1, "rider"), "1 grocery store, nearest you first.");
  assert.equal(groceryFoundSaid(4, "start"), "4 grocery stores, nearest your start first.");
  assert.equal(groceryFoundSaid(4, "centre"), "4 grocery stores, nearest the map's center first.");
});

test("the list is the Food sheet's own, under Grocery stores, with Ride here in Go", () => {
  const results = groceryResults([store("Whole Foods Market", -77.0336, 38.9094, 1)], START, "rider");
  const props: FoodFinderProps = {
    query: "grocery",
    onQuery: () => {},
    scope: "near",
    onScope: () => {},
    onSearch: () => {},
    busy: false,
    status: groceryFoundSaid(1, "rider"),
    results,
    total: 1,
    onMore: () => {},
    canAddStop: false,
    onShow: () => {},
    onRide: () => {},
    onAddStop: () => {},
    folded: false,
    heading: GROCERY_HEADING,
  };
  const html = renderToStaticMarkup(createElement(FoodFinder, props));
  assert.match(html, /<h3 id="food-list-heading" class="visually-hidden">Grocery stores<\/h3>/);
  assert.match(html, /<strong><span class="visually-hidden">A\. <\/span>Whole Foods Market<\/strong> Grocery store\. 0\.2 mi \(0\.4 km\) from you in a straight line\./);
  assert.match(html, /aria-label="Ride here: Whole Foods Market"/);
  assert.match(html, /aria-label="Show on map: Whole Foods Market, marker A"/);
  assert.doesNotMatch(html, /Show \d+ more/);
  // Without a heading the list is still Places to eat.
  assert.match(renderToStaticMarkup(createElement(FoodFinder, { ...props, heading: undefined })), />Places to eat<\/h3>/);
});

test("App: the Grocery chip searches the geocoder near the route's start and lists the stores in place of the food", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(isGroceryQuery\(query\)\) \{\s*void searchGrocery\(seq\);\s*return;\s*\}\s*setGrocery\(null\);/);
  assert.match(app, /const start = goSearchOrigin\(\);/);
  assert.match(app, /geoGate\.run\(\(\) => fetchPlaces\(searchUrl\(GROCERY_QUERY, startBiasPoint\(origin\) \?\? searchBias\(\), MAX_DETOUR_SEARCH\)\)\)/);
  assert.match(app, /const foodResults = grocery \?\? foodPage;/);
  assert.match(app, /heading=\{grocery \? GROCERY_HEADING : undefined\}/);
  assert.match(app, /<FoodOverlay getMap=\{getMap\} results=\{grocery \? null : foodAll\}/);
  const es = readFileSync(new URL("../i18n/es.ts", import.meta.url), "utf8");
  assert.match(es, /"Grocery": "Supermercado",/);
});
