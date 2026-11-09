// Food words in the search box: which queries are food, and the places to eat they list.
import { test } from "node:test";
import assert from "node:assert/strict";
import type { FoodPlace } from "./food.ts";
import type { Place } from "./geocode.ts";
import { FOOD_ROWS, foodPlaceRow, foodRows, foodWords, withoutFoodRows } from "./placeFood.ts";

const HERE: [number, number] = [-77.0365, 38.9077];
const eat = (id: string, name: string, lon: number, cuisine: string[], kind: FoodPlace["kind"] = "r"): FoodPlace => ({
  id,
  lon,
  lat: 38.9077,
  kind,
  name,
  cuisine,
});
const PLACES = [
  eat("n1", "El Chucho", -77.03, ["mexican"]),
  eat("n2", "Taco Bamba", -77.0, ["tacos"], "f"),
  eat("w3", "Pizzeria Paradiso", -77.035, ["pizza"]),
  eat("n4", "Compass Coffee", -77.036, [], "c"),
  eat("n5", "Far Taqueria", -76.9, ["mexican"]),
];

test("words for food are food searches; names and addresses are not", () => {
  for (const q of ["tacos", "Taco", "pizza", "coffee", "crab", "chinese food", "pizza places", "taco spot", "lunch", "tacos near me", "Mexican restaurant"]) {
    assert.notEqual(foodWords(q), null, q);
  }
  for (const q of ["Safeway", "Satay Club", "4654 Wisconsin Ave NW", "Union Station", "grocery stores", "anything", "all", "", "Taco Bamba"]) {
    assert.equal(foodWords(q), null, q);
  }
  assert.equal(foodWords("Chinese food"), "chinese");
});

test("a food word lists the matching places to eat nearest first, by cuisine as well as name", () => {
  const rows = foodRows("tacos", PLACES, HERE);
  assert.deepEqual(rows.map((r) => r.name), ["El Chucho", "Taco Bamba", "Far Taqueria"]);
  assert.deepEqual(foodRows("coffee", PLACES, HERE).map((r) => r.name), ["Compass Coffee"]);
});

test("no rows for a name, before the places load, or with nowhere to measure from", () => {
  assert.deepEqual(foodRows("Safeway", PLACES, HERE), []);
  assert.deepEqual(foodRows("tacos", null, HERE), []);
  assert.deepEqual(foodRows("tacos", PLACES, undefined), []);
});

test("at most FOOD_ROWS places lead the list", () => {
  const many = Array.from({ length: 12 }, (_, i) => eat(`n${i + 10}`, `Pizza ${i}`, -77.03 - i / 1000, ["pizza"]));
  assert.equal(foodRows("pizza", many, HERE).length, FOOD_ROWS);
});

test("a row says what the place is and keeps its OSM element", () => {
  const row = foodPlaceRow(PLACES[2]);
  assert.equal(row.osm_type, "W");
  assert.equal(row.osm_id, 3);
  assert.equal(row.osm_key, "amenity");
  assert.equal(row.osm_value, "restaurant");
  assert.match(row.label, /^Pizzeria Paradiso, /);
});

test("a searched place that is a place to eat already listed is shown once", () => {
  const food = foodRows("tacos", PLACES, HERE);
  const searched: Place[] = [
    { name: "Taco Bamba", label: "Taco Bamba, Washington", lon: -77.0001, lat: 38.9077, kind: "house" },
    { name: "Taco Bell", label: "Taco Bell, Washington", lon: -77.02, lat: 38.9077, kind: "house" },
  ];
  assert.deepEqual(withoutFoodRows(searched, food).map((p) => p.name), ["Taco Bell"]);
});
