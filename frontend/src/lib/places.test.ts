/** Places to see (v0.7.0): Plan's sheet with categories, Go's five Sights, words and the layer's switch. */
import assert from "node:assert/strict";
import test from "node:test";
import { CATEGORIES, PLACES_PREF_KEY, parsePlaces, placesSaid, placesToSee, readPlacesLayer, savePlacesLayer, sightHowFar, sightText, sightsForGo } from "./places.ts";

const file = {
  source: "OpenStreetMap contributors, ODbL 1.0",
  points: [
    { id: "n1", x: -77.0, y: 38.9, k: "museum", n: "Small Museum", h: "Tu-Su 10:00-17:00", web: "https://example.org" },
    { id: "n2", x: -77.05, y: 38.9, k: "lighthouse", n: "Point Light" },
    { id: "n3", x: -77.1, y: 38.905, k: "garden", n: "Rose Garden", web: "ftp://nope" },
    { id: "n4", x: -77.2, y: 38.95, k: "viewpoint", n: "Far View" },
    { id: "n5", x: -77.0, y: 38.9, k: "spaceport", n: "Unknown kind" },
    { id: "n6", x: -77.0, y: 38.9, k: "museum" },
  ],
};

const route = {
  line: [
    [-77.0, 38.9],
    [-77.2, 38.9],
  ] as Array<[number, number]>,
  speedMps: 5,
};

test("places are read with a known category and a name; only web links are kept", () => {
  const places = parsePlaces(file)!;
  assert.deepEqual(
    places.map((p) => p.id),
    ["n1", "n2", "n3", "n4"],
  );
  assert.equal(places[0].website, "https://example.org");
  assert.equal(places[2].website, undefined);
  assert.equal(parsePlaces({}), null);
  assert.ok(CATEGORIES.every((c) => c.label && c.one && c.emoji));
});

test("with no route: nearest first, and a category filter", () => {
  const places = parsePlaces(file)!;
  const all = placesToSee(places, [-77.0, 38.9], null);
  assert.deepEqual(
    all.map((r) => r.place.id),
    ["n1", "n2", "n3", "n4"],
  );
  assert.deepEqual(
    placesToSee(places, [-77.0, 38.9], null, "garden").map((r) => r.place.id),
    ["n3"],
  );
  assert.equal(sightsForGo(places, [-77.0, 38.9], null, 2).length, 2);
});

test("along a route: within half a mile, in riding order, with a detour", () => {
  const places = parsePlaces(file)!;
  const along = placesToSee(places, [-77.0, 38.9], route);
  assert.deepEqual(
    along.map((r) => r.place.id),
    ["n1", "n2", "n3"],
    "the far viewpoint (over 3 mi off) is left out",
  );
  assert.equal(sightHowFar(along[0]), "On your route");
  assert.match(sightHowFar(along[2]), /^\+\d+\.\d mi \(\d+\.\d km\)$/);
  assert.match(sightText(along[2]), /^Rose Garden\. Garden\. \+.* there and back, turning off at .* on your route\.$/);
  assert.match(sightText(along[0]), /Small Museum\. Museum or gallery\. On your route at .*\. Hours as mapped: Tu-Su 10:00-17:00\.$/);
});

test("the status line says how many, and from where", () => {
  assert.equal(placesSaid(0, "all", true), "No places to see within half a mile (0.8 km) of your route.");
  assert.equal(placesSaid(3, "lighthouse", false), "3 lighthouses, nearest the map's center first.");
  assert.equal(placesSaid(2, "all", true), "2 places to see within half a mile (0.8 km) of your route, in riding order.");
});

test("the layer's switch: off by default, kept on the device, and safe when storage throws", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readPlacesLayer(store), false);
  savePlacesLayer(true, store);
  assert.equal(kept.get(PLACES_PREF_KEY), "on");
  assert.equal(readPlacesLayer(store), true);
  const broken = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(readPlacesLayer(broken), false);
  assert.doesNotThrow(() => savePlacesLayer(true, broken));
  assert.equal(readPlacesLayer(null), false);
});
