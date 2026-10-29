// Lettered places (the owner, 2026-10-11 21:04 UTC): the letters, the markers' names, the keys, the list.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { letterKeyIndex, letterPlaces, letteredName, placeLetter } from "./letteredPlaces.ts";
import { NearestFinder } from "./nearestFinder.ts";

test("letters: A to Z, then AA, AB, as a spreadsheet's columns", () => {
  assert.deepEqual([0, 1, 2, 25, 26, 27, 51, 52].map(placeLetter), ["A", "B", "C", "Z", "AA", "AB", "AZ", "BA"]);
});

test("a marker's name: the letter, the place and how far, US units first", () => {
  assert.equal(letteredName("B", "Drinking water, Garfield Park", 480), "B: Drinking water, Garfield Park, 0.3 mi (0.5 km)");
  assert.equal(letteredName("C", "Dupont Circle", null), "C: Dupont Circle");
  const places = letterPlaces([{ p: [-77, 38.9] as [number, number], t: "One" }, { p: [-77.01, 38.91] as [number, number], t: "Two" }], (x) => ({ point: x.p, title: x.t, metres: null }));
  assert.deepEqual(places.map((p) => [p.letter, p.name]), [["A", "A: One"], ["B", "B: Two"]]);
  assert.equal(places[0].label, undefined, "lettered by default");
});

test("named places (Stephen 2026-10-29: names in a bubble): the marker shows the place's name, its accessible name keeps the letter", () => {
  const places = letterPlaces([{ p: [-77, 38.9] as [number, number], t: "Songbyrd Music House" }], (x) => ({ point: x.p, title: x.t, metres: 480 }), true);
  assert.equal(places[0].label, "Songbyrd Music House");
  assert.equal(places[0].name, "A: Songbyrd Music House, 0.3 mi (0.5 km)");
});

test("keys: a letter in the list picks it; not while typing, on the map, in a dialog, with a modifier, or past the list", () => {
  const button = { tagName: "BUTTON", closest: () => null };
  assert.equal(letterKeyIndex({ key: "b", target: button }, 3), 1);
  assert.equal(letterKeyIndex({ key: "C", target: button }, 3), 2);
  assert.equal(letterKeyIndex({ key: "d", target: button }, 3), null, "past the list");
  assert.equal(letterKeyIndex({ key: "a", target: { tagName: "INPUT" } }, 3), null, "typing in a field");
  assert.equal(letterKeyIndex({ key: "a", target: { tagName: "TEXTAREA" } }, 3), null);
  assert.equal(letterKeyIndex({ key: "a", target: { tagName: "BUTTON", closest: (s: string) => (s.includes(".map") ? {} : null) } }, 3), null, "the map's keys stay its own");
  // A dialog's keys are its own; the list's popup sheet (a <dialog class="popup-sheet">) is not such a dialog.
  const inPopupSheet = { tagName: "H2", closest: (s: string) => (s.split(",").map((x) => x.trim()).includes("dialog") ? {} : null) };
  assert.equal(letterKeyIndex({ key: "b", target: inPopupSheet }, 3), 1, "in the list's popup sheet");
  const inDialog = { tagName: "BUTTON", closest: (s: string) => (s.split(",").some((x) => x.trim().startsWith("dialog")) ? {} : null) };
  assert.equal(letterKeyIndex({ key: "a", target: inDialog }, 3), null, "in another dialog");
  assert.equal(letterKeyIndex({ key: "a", ctrlKey: true, target: button }, 3), null);
  assert.equal(letterKeyIndex({ key: "1", target: button }, 3), null);
  assert.equal(letterKeyIndex({ key: "Enter", target: button }, 3), null);
});

test("the nearest list: each row heard with its letter first, no pin (the map names it), and Ride here as before", () => {
  const item = (id: string, title: string, m: number) => ({ place: { id, kind: "water" as const, point: [-77, 38.9] as [number, number], title, details: [] }, distanceM: m, timeS: null, byBike: false });
  const html = renderToStaticMarkup(
    createElement(NearestFinder, {
      from: "location",
      fromOptions: ["location"],
      onFrom: () => {},
      onFind: () => {},
      busy: false,
      status: "",
      list: { kind: "water", items: [item("n1", "Drinking water, Garfield Park", 480), item("n2", "Drinking water, Lincoln Park", 900)] },
      canAddStop: false,
      onRide: () => {},
      onAddStop: () => {},
      folded: false,
    }),
  );
  assert.match(html, /<li class="lettered-row"><div class="nearest-place"><span class="visually-hidden">A: <\/span>Drinking water, Garfield Park:/);
  assert.match(html, /<span class="visually-hidden">B: <\/span>Drinking water, Lincoln Park:/);
  assert.doesNotMatch(html, /place-letter/, "named on the map, so no letter pin in the row (Stephen 2026-10-29)");
  assert.doesNotMatch(html, /Show all on map/, "no button without its handler");
  const withAll = renderToStaticMarkup(
    createElement(NearestFinder, {
      fromOptions: ["location"],
      from: "location",
      onFrom: () => {},
      onFind: () => {},
      busy: false,
      status: "",
      list: { kind: "water", items: [item("n1", "Drinking water, Garfield Park", 480), item("n2", "Drinking water, Lincoln Park", 900)] },
      canAddStop: false,
      onRide: () => {},
      onAddStop: () => {},
      onShowAll: () => {},
      folded: false,
    }),
  );
  assert.match(withAll, /<button type="button" class="secondary show-all">Show all on map<\/button><div class="nearest-list">/);
  assert.match(html, /aria-label="Ride here: Drinking water, Lincoln Park"/);
  assert.match(html, /Tap a place(&#x27;|')s name on the map to see what(&#x27;|')s there\. Ride here plans a route to it/);
});

test("Show on map and Show all on map are wired (Stephen 2026-10-29): above the sheet, the row's marker marked, Ride and Roam left lettered", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  // A row's Show on map puts the place in the part of the map the sheet leaves (it was centred under a phone's sheet).
  assert.equal(app.match(/ showLettered\(/g)?.length, 3, "its three callers: food, nearest, places");
  assert.match(app, /const showLettered = \(point: LonLat, index: number\) => \{\s*setLetteredShown\(index >= 0 \? index : null\);\s*flyToInView\(point, 15\);/);
  assert.match(app, /onShowAll=\{showAllFood\}/);
  assert.match(app, /onShowAll=\{showAllLettered\}/);
  assert.match(app, /onShowAll: \(\) => \{/);
  assert.match(app, /letteredShown=\{riding \|\| \(roaming && roamLettered\) \? null : letteredShown\}/);
  // Go's and Plan's lists are named; the bike-share options are not (letterPlaces is not used for them).
  assert.equal(app.match(/letterPlaces\([^\n]*\), true\)/g)?.length, 4);
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /classList\.toggle\("is-shown", index === props\.letteredShown\)/);
  assert.match(view, /\[\.\.\.letteredMarkers\.current\]\.reverse\(\)\.forEach\(\(marker\) => marker\.addTo\(map\)\)/);
  assert.match(view, /if \(map && props\.lettered && props\.letteredRefit\) frameLettered\(map, props\.lettered\);/);
});
