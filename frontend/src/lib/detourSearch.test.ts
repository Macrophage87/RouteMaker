import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  DETOUR_CHOICES,
  DETOUR_SUMMARY,
  SEARCH_TOO_SHORT,
  detourFindingSaid,
  findDetour,
  kindForQuery,
  mergeCandidates,
  repairNearestPlaces,
  roundedBias,
  searchedPlaces,
  type DetourDeps,
} from "./detourSearch.ts";
import type { FoodPlace } from "./food.ts";
import type { GeoResult, Place } from "./geocode.ts";
import type { LonLat } from "./geo.ts";
import type { NearestPlace } from "./nearest.ts";
import type { RepairPlace } from "./repair.ts";
import type { WaterPoint } from "./waterRestrooms.ts";

const HERE: LonLat = [-77.0365, 38.8977];
const near = (east: number): LonLat => [HERE[0] + east / 86_700, HERE[1]];

const FOOD: FoodPlace[] = [
  { id: "n1", lon: near(300)[0], lat: HERE[1], kind: "r", name: "Pizza Place", cuisine: ["pizza"] },
  { id: "n2", lon: near(100)[0], lat: HERE[1], kind: "c", name: "Bean", cuisine: ["coffee_shop"] },
  { id: "n3", lon: near(900)[0], lat: HERE[1], kind: "r", name: "Crab Shack", cuisine: ["seafood"] },
];
const REPAIR: RepairPlace[] = [
  { id: "n10", kind: "stand", lon: near(200)[0], lat: HERE[1], kit: "pt", fee: "no" },
  { id: "n11", kind: "shop", lon: near(500)[0], lat: HERE[1], name: "Spokes" },
];
const WATER: WaterPoint[] = [{ id: "n20", lon: near(50)[0], lat: HERE[1], water: "p" } as WaterPoint];

const geoPlace = (name: string, east: number, extra: Partial<Place> = {}): Place => ({
  name,
  label: `${name}, 1 Main St, Washington`,
  lon: near(east)[0],
  lat: HERE[1],
  kind: "house",
  osm_key: "shop",
  osm_value: "supermarket",
  ...extra,
});

/** Stand-ins: the riding distance is the straight one east, times 1.2; every call is kept. */
function deps(over: Partial<DetourDeps> = {}) {
  const asked: { geocode: Array<{ query: string; near: LonLat | undefined }>; request: NearestPlace[][] } = { geocode: [], request: [] };
  const d: DetourDeps = {
    here: HERE,
    water: async () => WATER,
    food: async () => FOOD,
    repair: async () => REPAIR,
    geocode: async (query, at) => {
      asked.geocode.push({ query, near: at });
      return { ok: true, places: [geoPlace("Safeway", 400)], attribution: [] };
    },
    request: async (_from, places) => {
      asked.request.push([...places]);
      return {
        ok: true,
        answer: { by: "riding", places: places.map((p) => ({ distance_m: Math.abs(p.point[0] - HERE[0]) * 86_700 * 1.2, time_s: 60 })) },
      };
    },
    now: () => new Date("2026-10-24T12:00:00-04:00"),
    ...over,
  };
  return { d, asked };
}

test("Detour offers water, restroom, food and repair, and says so on its button", () => {
  assert.deepEqual(
    DETOUR_CHOICES.map((c) => c.kind),
    ["water", "restroom", "food", "repair"],
  );
  assert.equal(DETOUR_SUMMARY, "Water, restroom, food, repair or search");
});

test("words for a button are that button; food's general words are Food; anything else is a search", () => {
  assert.equal(kindForQuery("Bathroom"), "restroom");
  assert.equal(kindForQuery(" water "), "water");
  assert.equal(kindForQuery("pump"), "repair");
  assert.equal(kindForQuery("lunch"), "food");
  assert.equal(kindForQuery("anything"), null);
  assert.equal(kindForQuery("pizza"), null);
  assert.equal(kindForQuery(""), null);
});

test("Food lists the three nearest places to eat by bike", async () => {
  const { d } = deps();
  const out = await findDetour(d, { kind: "food" });
  assert.equal(out.found?.kind, "food");
  assert.equal(out.found?.heading, "Nearest places to eat");
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Bean", "Pizza Place", "Crab Shack"],
  );
  assert.match(out.said, /^The 3 nearest places to eat by bike, nearest first\. Bean: /);
});

test("Repair lists stands and shops together, each with its kit or hours", async () => {
  const { d } = deps();
  const out = await findDetour(d, { kind: "repair" });
  assert.equal(out.found?.heading, "Nearest repair stands and bike shops");
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Repair stand", "Bike shop, Spokes"],
  );
  assert.deepEqual(out.found?.items[0].place.details, ["Pump and tools.", "Free."]);
});

test("water still goes through the nearest search", async () => {
  const { d } = deps();
  const out = await findDetour(d, { kind: "water" });
  assert.equal(out.found?.kind, "water");
  assert.equal(out.found?.items.length, 1);
});

test("a search matches food and the place search together, measured by bike", async () => {
  const { d, asked } = deps({
    geocode: async (query, at) => {
      asked.geocode.push({ query, near: at });
      return { ok: true, places: [geoPlace("Pizza Palace", 600, { osm_key: "amenity", osm_value: "restaurant" })], attribution: [] };
    },
  });
  const out = await findDetour(d, { query: "  pizza " });
  assert.equal(out.found?.kind, "search");
  assert.equal(out.found?.heading, "Nearest matches for “pizza”");
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Pizza Place", "Pizza Palace"],
  );
  assert.equal(asked.geocode[0].query, "pizza");
  // The place search gets the rider's point rounded, never the fix itself.
  assert.deepEqual(asked.geocode[0].near, roundedBias(HERE));
  assert.notDeepEqual(asked.geocode[0].near, HERE);
  assert.match(out.said, /^The 2 nearest matches for “pizza” by bike/);
});

test("a name or shop not in the food list is found by the place search", async () => {
  const { d } = deps();
  const out = await findDetour(d, { query: "grocery" });
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Safeway"],
  );
  assert.deepEqual(out.found?.items[0].place.details, ["Shop.", "1 Main St, Washington."]);
});

test("a button's word typed in the box asks no place search", async () => {
  const { d, asked } = deps();
  const out = await findDetour(d, { query: "restroom" });
  assert.equal(asked.geocode.length, 0);
  assert.equal(out.found, undefined);
  assert.match(out.said, /restroom/i);
  assert.equal(detourFindingSaid({ query: "restroom" }), "Finding the nearest restrooms.");
  assert.equal(detourFindingSaid({ query: "tacos" }), "Searching for “tacos”.");
});

test("too short a search asks nothing", async () => {
  const { d, asked } = deps();
  const out = await findDetour(d, { query: "ab" });
  assert.equal(out.said, SEARCH_TOO_SHORT);
  assert.equal(asked.geocode.length + asked.request.length, 0);
});

test("a place search that fails says why when nothing else matched, and is not needed when food did", async () => {
  const failing = async (): Promise<GeoResult> => ({ ok: false, status: 429 });
  const { d } = deps({ geocode: failing });
  assert.equal((await findDetour(d, { query: "Safeway" })).said, "The place search is busy; try again in a moment.");
  const out = await findDetour(d, { query: "coffee" });
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Bean"],
  );
});

test("the place search's credit shows when its places are listed; 'anything' is not every food place", async () => {
  const { d } = deps({
    geocode: async () => ({ ok: true, places: [geoPlace("Safeway", 400)], attribution: ["Photon, OpenStreetMap"] }),
  });
  const out = await findDetour(d, { query: "anything" });
  assert.deepEqual(
    out.found?.items.map((i) => i.place.title),
    ["Safeway"],
  );
  assert.deepEqual(out.found?.attribution, ["Photon, OpenStreetMap"]);
  const { d: onlyFood } = deps({ geocode: async () => ({ ok: true, places: [], attribution: ["Photon, OpenStreetMap"] }) });
  assert.equal((await findDetour(onlyFood, { query: "coffee" })).found?.attribution, undefined);
});

test("a rounded point outside the map's area is not sent", () => {
  assert.equal(roundedBias([-100, 40]), undefined);
});

test("nothing matching says so", async () => {
  const { d } = deps({ geocode: async () => ({ ok: true, places: [], attribution: [] }) });
  assert.equal((await findDetour(d, { query: "zzzz" })).said, "Nothing near you matches “zzzz”.");
});

test("food that will not load says so", async () => {
  const { d } = deps({ food: async () => null, repair: async () => null });
  assert.match((await findDetour(d, { kind: "food" })).said, /places to eat are unavailable/);
  assert.match((await findDetour(d, { kind: "repair" })).said, /Repair stands and bike shops are unavailable/);
});

test("a searched place the food list already has is listed once, with the food list's words", () => {
  const food: NearestPlace[] = [{ id: "n1", kind: "water", point: near(300), title: "Pizza Place", details: ["Restaurant: pizza."] }];
  const searched = searchedPlaces([geoPlace("Pizza Place", 300.2), geoPlace("Other", 50)]);
  const merged = mergeCandidates(food, searched);
  assert.deepEqual(
    merged.map((p) => p.id),
    ["n1", searched[1].id],
  );
});

test("a searched place outside the map's area is left out", () => {
  assert.equal(searchedPlaces([{ ...geoPlace("Far", 0), lon: -100, lat: 40 }]).length, 0);
});

test("repair places are titled as Go's Repair list titles them", () => {
  const [stand, shop] = repairNearestPlaces(REPAIR, new Date());
  assert.equal(stand.title, "Repair stand");
  assert.equal(shop.title, "Bike shop, Spokes");
});

test("Ride mode and Roam both use the shared Detour search and its box", () => {
  for (const file of ["../RideMode.tsx", "../RoamMode.tsx"]) {
    const src = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.match(src, /DETOUR_CHOICES\.map/);
    assert.match(src, /className="detour-search"/);
    assert.match(src, /<label htmlFor=\{`\$\{detourId\}-search`\}>/);
  }
});
