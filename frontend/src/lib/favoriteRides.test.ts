// Favorite ride types (Stephen, 2026-10-19: "Allow users to select favorite ride types that appear
// first when selecting ride mode"): a star on each card, the favorites first under their own heading.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { FAVORITES_KEY, FavoriteStar, favoriteLabel, parseFavorites, readFavorites, reloadFavorites, setFavorites, subscribe, toggleFromPicker, toggled } from "./favoriteRides.ts";
import { PRESETS } from "./presets.ts";
import { RideTypeCards } from "./rideTypeCards.ts";
import { filterRideGroups, rideSections, withFavorites } from "./rideTypeGroups.ts";
import { applyToDevice, deviceSettings, parseSettings } from "./accountSettings.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

test("a stored list keeps known ride types, each once, in order", () => {
  assert.deepEqual(parseFavorites(["gravel", "nope", 3, "cargo", "gravel"]), ["gravel", "cargo"]);
  assert.deepEqual(parseFavorites("cargo"), []);
  assert.deepEqual(readFavorites(memory({ [FAVORITES_KEY]: '["cargo"]' })), ["cargo"]);
  assert.deepEqual(readFavorites(memory({ [FAVORITES_KEY]: "{broken" })), []);
  assert.deepEqual(readFavorites(null), []);
});

test("starring adds last; starring again removes", () => {
  assert.deepEqual(toggled(["cargo"], "gravel"), ["cargo", "gravel"]);
  assert.deepEqual(toggled(["cargo", "gravel"], "cargo"), ["gravel"]);
});

test("Plan's dialog: the favorites first, in starred order, and not again in their groups", () => {
  const groups = withFavorites(filterRideGroups(""), ["gravel", "cargo"]);
  assert.equal(groups[0].label, "Favorites");
  assert.deepEqual([...groups[0].ids], ["gravel", "cargo"]);
  const all = groups.flatMap((g) => g.ids);
  assert.equal(all.length, PRESETS.length, "each ride type once");
  // No favorites: the groups as they were.
  assert.deepEqual(withFavorites(filterRideGroups(""), []), filterRideGroups(""));
  // A search keeps only the favorites it matches.
  const searched = withFavorites(filterRideGroups("mountain"), ["gravel", "mountain-bike"]);
  assert.deepEqual([...searched[0].ids], ["mountain-bike"]);
});

test("Go's More ride types: favorites before Common, and neither repeated", () => {
  const plain = rideSections("", undefined, ["mass-ride", "novice"]);
  assert.deepEqual(plain.favorites, ["mass-ride", "novice"]);
  assert.deepEqual(plain.common, ["default", "bikeshare", "bike-transit"]);
  const rest = plain.groups.flatMap((g) => g.ids);
  assert.equal(rest.length + plain.common.length + plain.favorites.length, PRESETS.length);
  const searched = rideSections("mountain", undefined, ["mountain-goat"]);
  assert.deepEqual(searched.favorites, ["mountain-goat"]);
  assert.deepEqual(searched.groups.flatMap((g) => g.ids), ["mountain-bike"]);
  const sheets = src("../app/Sheets.tsx");
  const go = sheets.slice(sheets.indexOf("export function RideGroupChips("), sheets.indexOf("export function RideChips("));
  assert.ok(go.indexOf('<h4 id="ride-sheet-favorites">Favorites</h4>') < go.indexOf('<h4 id="ride-sheet-common">Common</h4>'));
});

test("the star is a toggle button named for its ride type, its state said", () => {
  const off = renderToStaticMarkup(createElement(FavoriteStar, { id: "cargo", on: false, onToggle: () => {} }));
  assert.match(off, /<button type="button" class="ride-fav"[^>]* aria-pressed="false" aria-label="Favorite Cargo Bike"/);
  assert.match(off, /<svg[^>]*aria-hidden="true"/);
  const on = renderToStaticMarkup(createElement(FavoriteStar, { id: "cargo", on: true, onToggle: () => {} }));
  assert.match(on, /aria-pressed="true"/);
  assert.equal(favoriteLabel("cargo"), "Favorite Cargo Bike");
});

test("Go's cards carry the star only when asked; Plan's dialog has it on every card", () => {
  const plain = renderToStaticMarkup(createElement(RideTypeCards, { ids: ["cargo"], preset: "default", onPick: () => {}, idPrefix: "t" }));
  assert.doesNotMatch(plain, /ride-fav/);
  const starred = renderToStaticMarkup(
    createElement(RideTypeCards, { ids: ["cargo", "gravel"], preset: "default", onPick: () => {}, idPrefix: "t", favorites: ["gravel"], onFavorite: () => {} }),
  );
  assert.equal((starred.match(/class="ride-fav"/g) ?? []).length, 2);
  assert.match(starred, /aria-pressed="true" aria-label="Favorite Gravel/);
  const picker = src("../RideTypePicker.tsx");
  assert.match(picker, /<FavoriteStar id=\{option\.id\}/);
  assert.match(picker, /withFavorites\(filterRideGroups\(query\), favorites\)/);
  // Both pickers hand toggleFromPicker their own part of the page, so the focus follows the star there.
  assert.match(picker, /toggleFromPicker\(id, dialogRef\.current\)/);
  assert.match(src("../app/Sheets.tsx"), /toggleFromPicker\(id, scopeRef\.current\)/);
});

test("favorites sync with the account's settings", () => {
  const store = memory({ [FAVORITES_KEY]: '["gravel"]' });
  assert.deepEqual(deviceSettings(null, store).favorites, ["gravel"]);
  assert.equal(deviceSettings(null, memory()).favorites, undefined);
  assert.deepEqual(parseSettings({ v: 1, favorites: ["cargo", "x"] })?.favorites, ["cargo"]);
  const other = memory();
  applyToDevice({ v: 1, favorites: ["cargo"] }, other);
  assert.equal(other.data.get(FAVORITES_KEY), '["cargo"]');
});

test("the store tells every picker of a change, and a star pressed moves the focus to its new place", () => {
  let heard = 0;
  const stop = subscribe(() => heard++);
  setFavorites(["cargo"], null);
  reloadFavorites();
  assert.equal(heard, 2);
  // The card moved into a folded group: the group opens and the star takes the focus.
  const fold = { open: false };
  let focused = "";
  let asked = "";
  const scope = {
    querySelector: (selector: string) => {
      asked = selector;
      return { focus: () => (focused = "gravel"), closest: () => fold };
    },
  };
  toggleFromPicker("gravel", scope, (run) => run());
  assert.equal(asked, '.ride-fav[data-fav="gravel"]');
  assert.equal(focused, "gravel");
  assert.equal(fold.open, true);
  assert.equal(heard, 3);
  stop();
  setFavorites([], null);
  assert.equal(heard, 3, "no longer told once unsubscribed");
});

test("a star pressed is a settings change: App saves when the favorites change", () => {
  const app = src("../App.tsx");
  assert.match(app, /const favoriteRides = useFavoriteRides\(\);/);
  assert.match(app, /showTopoLines, favoriteRides, weight\]\);/);
  assert.match(app, /applyToDevice\(step\.doc\);\s*reloadFavorites\(\);/);
});
