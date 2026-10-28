/** Farm stands and markets as food (v0.7.0, the owner 2026-10-14: "Add farm stands for food."). */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SEASONAL_HOURS, foodHoursText, foodKindText, foodTerms, foodText, matchesFood, parseFood, searchFood, type FoodPlace } from "./food.ts";
import { FoodFinder } from "./foodFinder.ts";

const file = {
  source: "OpenStreetMap contributors, ODbL 1.0",
  points: [
    { id: "n1", x: -77.2, y: 39.1, k: "fs", n: "Apple Barn" },
    { id: "n2", x: -77.0, y: 38.9, k: "m", n: "Dupont Market", h: "Su 08:30-13:30" },
    { id: "n3", x: -77.0, y: 38.91, k: "r", n: "Crab House", c: "seafood" },
  ],
};

test("farm stands and markets are read, with their own kinds", () => {
  const places = parseFood(file)!;
  assert.deepEqual(
    places.map((p) => [p.id, p.kind]),
    [
      ["n1", "fs"],
      ["n2", "m"],
      ["n3", "r"],
    ],
  );
  assert.equal(foodKindText(places[0]), "Farm stand");
  assert.equal(foodKindText(places[1]), "Market");
});

test("a stand with no hours says they vary by season; mapped hours are kept", () => {
  const [stand, market, crab] = parseFood(file)!;
  assert.equal(foodHoursText(stand), SEASONAL_HOURS);
  assert.equal(foodHoursText(market), "Hours as mapped: Su 08:30-13:30.");
  assert.equal(foodHoursText(crab), "");
  assert.match(foodText({ place: stand, fromCentreM: 1609.344 }), /Apple Barn\. Farm stand\. .* Hours vary by season\.$/);
});

test("apples, farm stands and farmers markets find them by kind", () => {
  const places = parseFood(file)!;
  const found = (q: string) => places.filter((p: FoodPlace) => matchesFood(p, foodTerms(q)!)).map((p) => p.id);
  assert.deepEqual(found("apples"), ["n1", "n2"]);
  assert.deepEqual(found("farm stands"), ["n1"]);
  assert.deepEqual(found("farmers market"), ["n1", "n2"]);
  assert.deepEqual(found("crab"), ["n3"]);
});

test("the list draws the apple beside a farm stand, hidden from screen readers, with its kind in words", () => {
  const places = parseFood(file)!;
  const results = searchFood(places, { query: "apple", scope: "near", bounds: null, centre: [-77, 38.9], route: null });
  const html = renderToStaticMarkup(
    createElement(FoodFinder, {
      query: "apple",
      onQuery: () => {},
      scope: "near",
      onScope: () => {},
      onSearch: () => {},
      busy: false,
      status: "",
      results,
      total: results.length,
      onMore: () => {},
      canAddStop: false,
      onShow: () => {},
      onAddStop: () => {},
    }),
  );
  assert.equal((html.match(/class="icon food-apple"/g) ?? []).length, 2);
  assert.match(html, /aria-hidden="true"/);
  assert.match(html, /Farm stand\./);
  assert.match(html, /Hours vary by season\./);
});

test("the Food sheet has a Farm stands chip with the apple", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /"Ice cream", "Farm stands", "Grocery"\] as const/);
  assert.match(sheets, /\{ "Farm stands": "apple", Grocery: "shop" \}/);
  assert.match(sheets, /<Icon name=\{FOOD_CHIP_ICON\[food\] \?\? "food"\} size=\{16\} \/>/);
});
