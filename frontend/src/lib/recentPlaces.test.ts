// Recent places in the empty search box (lib/recentPlaces.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { KeyValueStore } from "./accessMode.ts";
import type { Place } from "./geocode.ts";
import {
  RECENT_PLACES_DAYS,
  RECENT_PLACES_KEY,
  RECENT_PLACES_MAX,
  placeKey,
  readRecentPlaces,
  rememberRecentPlace,
  withRecent,
} from "./recentPlaces.ts";

function memory(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}
const refusing: KeyValueStore = {
  getItem() {
    throw new Error("blocked");
  },
  setItem() {
    throw new Error("blocked");
  },
};
const place = (name: string, id?: number): Place => ({
  name,
  label: `${name}, Washington, DC`,
  lon: -77 - (id ?? 0) / 1000,
  lat: 38.9,
  kind: "place",
  osm_type: id === undefined ? null : "N",
  osm_id: id ?? null,
});

test("newest first, a repeat moves to the top instead of showing twice", () => {
  let list: Place[] = [];
  list = withRecent(list, place("A", 1));
  list = withRecent(list, place("B", 2));
  list = withRecent(list, { ...place("A", 1), label: "found again" });
  assert.deepEqual(
    list.map((p) => p.name),
    ["A", "B"],
  );
  assert.equal(list[0].label, "found again");
});

test("keeps at most five", () => {
  let list: Place[] = [];
  for (let i = 1; i <= 8; i++) list = withRecent(list, place(`P${i}`, i));
  assert.equal(list.length, RECENT_PLACES_MAX);
  assert.deepEqual(
    list.map((p) => p.name),
    ["P8", "P7", "P6", "P5", "P4"],
  );
});

test("a place without an OSM element is matched by name and spot", () => {
  assert.equal(placeKey(place("Corner")), placeKey({ ...place("Corner"), label: "other" }));
  assert.notEqual(placeKey(place("Corner")), placeKey({ ...place("Corner"), lat: 39.1 }));
});

test("remembered on the device and read back", () => {
  const store = memory();
  rememberRecentPlace(place("A", 1), store);
  rememberRecentPlace(place("B", 2), store);
  assert.deepEqual(
    readRecentPlaces(store).map((p) => p.name),
    ["B", "A"],
  );
});

test("a refusing or garbled store gives an empty list and does not throw", () => {
  assert.deepEqual(readRecentPlaces(refusing), []);
  assert.deepEqual(readRecentPlaces(null), []);
  assert.equal(rememberRecentPlace(place("A", 1), refusing).length, 1);
  const store = memory();
  store.setItem(RECENT_PLACES_KEY, "{not json");
  assert.deepEqual(readRecentPlaces(store), []);
  store.setItem(RECENT_PLACES_KEY, JSON.stringify([{ name: "x" }, place("Ok", 3)]));
  assert.deepEqual(
    readRecentPlaces(store).map((p) => p.name),
    ["Ok"],
  );
});

test("a place goes 30 days after it was last picked, from the list and the store", () => {
  const store = memory();
  const day = 24 * 60 * 60 * 1000;
  const t0 = 1_800_000_000_000;
  rememberRecentPlace(place("Old", 1), store, t0);
  rememberRecentPlace(place("New", 2), store, t0 + 20 * day);
  assert.equal(RECENT_PLACES_DAYS, 30);
  assert.deepEqual(
    readRecentPlaces(store, t0 + 29 * day).map((p) => p.name),
    ["New", "Old"],
  );
  assert.deepEqual(
    readRecentPlaces(store, t0 + 31 * day).map((p) => p.name),
    ["New"],
  );
  assert.ok(!store.data.get(RECENT_PLACES_KEY)!.includes("Old"));
  // Picked again, its 30 days start again; what is handed out carries no time.
  const again = rememberRecentPlace(place("New", 2), store, t0 + 45 * day);
  assert.ok(!("at" in again[0]));
  assert.deepEqual(
    readRecentPlaces(store, t0 + 70 * day).map((p) => p.name),
    ["New"],
  );
});

test("a list kept before dates were starts its 30 days when first read", () => {
  const store = memory();
  const day = 24 * 60 * 60 * 1000;
  const t0 = 1_800_000_000_000;
  store.setItem(RECENT_PLACES_KEY, JSON.stringify([place("Before", 4)]));
  assert.deepEqual(
    readRecentPlaces(store, t0).map((p) => p.name),
    ["Before"],
  );
  assert.deepEqual(readRecentPlaces(store, t0 + 31 * day), []);
});
