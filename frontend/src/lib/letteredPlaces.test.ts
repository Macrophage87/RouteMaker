// Lettered places (the owner, 2026-10-11 21:04 UTC): the letters, the markers' names, the keys, the list.
import { test } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
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

test("the nearest list: each row has its letter, seen in a pin and heard first, and Ride here as before", () => {
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
  assert.match(html, /<li class="lettered-row"><span class="place-letter" aria-hidden="true"><span>A<\/span><\/span><div class="nearest-place"><span class="visually-hidden">A: <\/span>Drinking water, Garfield Park:/);
  assert.match(html, /<span>B<\/span>/);
  assert.match(html, /aria-label="Ride here: Drinking water, Lincoln Park"/);
  assert.match(html, /a tap on its marker, or its letter(&#x27;|')s key, is the same as Ride here/);
});
