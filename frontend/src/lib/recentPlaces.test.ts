// Recent places in the empty search box (lib/recentPlaces.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { KeyValueStore } from "./accessMode.ts";
import type { Place } from "./geocode.ts";
import {
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
