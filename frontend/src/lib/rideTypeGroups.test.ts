// RIDE-TYPE-ORGANISE (Stephen, 2026-10-12): the ride types in Transportation, Adventure and Group,
// with a search over name and description, in Go's More ride types and Plan's ride type dialog.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PRESETS } from "./presets.ts";
import {
  NO_RIDE_TYPES_MATCH,
  RIDE_GROUPS,
  RideTypeSearch,
  filterRideGroups,
  matchesRideType,
  rideTypeCount,
  rideTypeCountSaid,
} from "./rideTypeGroups.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

test("every ride type is in exactly one group", () => {
  const grouped = RIDE_GROUPS.flatMap((g) => g.ids);
  assert.equal(new Set(grouped).size, grouped.length);
  assert.deepEqual([...grouped].sort(), PRESETS.map((p) => p.id).sort());
});

test("the groups are the owner's: Transportation, Adventure (Fast with it), Group", () => {
  assert.deepEqual(
    RIDE_GROUPS.map((g) => g.label),
    ["Transportation", "Adventure", "Group"],
  );
  const [transport, adventure, group] = RIDE_GROUPS;
  assert.deepEqual([...transport.ids], ["default", "bike-transit", "bikeshare-transit", "bikeshare", "cargo", "ebike", "kids"]);
  // Rebalance Ride (REBALANCE-RIDE): Stephen named it an adventure mode.
  assert.deepEqual([...adventure.ids], ["fast", "trailmaxxing", "mountain-goat", "mountain-bike", "gravel", "rebalance"]);
  assert.deepEqual([...group.ids], ["group-ride", "mass-ride"]);
});

test("an empty search shows every group and every type", () => {
  for (const query of ["", "   "]) {
    const groups = filterRideGroups(query);
    assert.equal(groups.length, RIDE_GROUPS.length);
    assert.equal(rideTypeCount(groups), PRESETS.length);
  }
});

test("the search matches the name, ignoring case", () => {
  const groups = filterRideGroups("MOUNTAIN");
  assert.deepEqual(
    groups.map((g) => [g.id, [...g.ids]]),
    [["adventure", ["mountain-goat", "mountain-bike"]]],
  );
});

test("the search matches the description, and each word must be there", () => {
  // "parade" is only in Mass Ride's description.
  assert.deepEqual(
    filterRideGroups("parade").flatMap((g) => g.ids),
    ["mass-ride"],
  );
  // Both words, anywhere in name or description.
  const both = filterRideGroups("metro dock").flatMap((g) => g.ids);
  assert.ok(both.includes("bikeshare-transit"));
  assert.ok(!both.includes("bike-transit"), "Own Bike + Transit has no dock");
});

test("a hyphen or an apostrophe does not stop a match", () => {
  const ebike = PRESETS.find((p) => p.id === "ebike")!;
  assert.ok(matchesRideType(ebike, "ebike"));
  assert.ok(matchesRideType(ebike, "e-bike"));
  const kids = PRESETS.find((p) => p.id === "kids")!;
  assert.ok(matchesRideType(kids, "childs pace"));
});

test("no match leaves no groups, and says so", () => {
  const groups = filterRideGroups("zzzz");
  assert.deepEqual(groups, []);
  assert.equal(rideTypeCountSaid(rideTypeCount(groups), "zzzz"), NO_RIDE_TYPES_MATCH);
  assert.equal(NO_RIDE_TYPES_MATCH, "No ride types match.");
});

test("the count is said only once something is typed", () => {
  assert.equal(rideTypeCountSaid(PRESETS.length, ""), "");
  assert.equal(rideTypeCountSaid(1, "fast"), "1 ride type matches.");
  assert.equal(rideTypeCountSaid(3, "bike"), "3 ride types match.");
});

test("the search box has a label and a polite status; no match is shown as well as said", () => {
  const typed = renderToStaticMarkup(createElement(RideTypeSearch, { id: "s", query: "fast", onQuery: () => {}, count: 1 }));
  assert.match(typed, /<label for="s">Search ride types<\/label>/);
  assert.match(typed, /<input id="s" type="search"/);
  assert.match(typed, /<p role="status" aria-live="polite" class="visually-hidden">1 ride type matches.<\/p>/);
  const none = renderToStaticMarkup(createElement(RideTypeSearch, { id: "s", query: "zzzz", onQuery: () => {}, count: 0 }));
  assert.match(none, /<p role="status" aria-live="polite" class="hint ride-type-none">No ride types match.<\/p>/);
  // Nothing typed: the status is there, empty, so the first count is announced.
  const empty = renderToStaticMarkup(createElement(RideTypeSearch, { id: "s", query: "", onQuery: () => {}, count: PRESETS.length }));
  assert.match(empty, /<p role="status" aria-live="polite" class="visually-hidden"><\/p>/);
});

test("Go's More ride types and Plan's dialog: the search first, then each group under a real heading", () => {
  const sheets = src("../app/Sheets.tsx");
  const go = sheets.slice(sheets.indexOf("export function RideGroupChips("), sheets.indexOf("export function RideChips("));
  assert.match(go, /<RideTypeSearch id="ride-sheet-search"/);
  assert.match(go, /<section key=\{group\.id\} className="ride-group" aria-labelledby=\{`ride-sheet-\$\{group\.id\}`\}>\s*<h3 id=\{`ride-sheet-\$\{group\.id\}`\}>\{group\.label\}<\/h3>/);
  assert.ok(go.indexOf("<RideTypeSearch") < go.indexOf("groups.map"), "the search comes before the groups");
  const plan = src("../RideTypePicker.tsx");
  assert.match(plan, /<RideTypeSearch id="ride-types-search"/);
  assert.match(plan, /<section key=\{group\.id\} className="ride-type-group" aria-labelledby=\{`ride-types-\$\{group\.id\}`\}>\s*<h3 id=\{`ride-types-\$\{group\.id\}`\}>\{group\.label\}<\/h3>/);
  assert.ok(plan.indexOf("<RideTypeSearch") < plan.indexOf("groups.map((group)"), "the search comes before the groups");
  // The search is cleared as the dialog closes, so the next opening has every type and the one in
  // use takes the focus (cleared on open, the card would not be there yet to focus).
  assert.match(plan, /const onClose = \(\) => \{\s*setQuery\(""\);\s*openerRef\.current\?\.focus\(\);/);
  assert.doesNotMatch(plan, /setQuery\(""\);\s*dialogRef\.current\?\.showModal\(\);/);
  // The two ids differ, so both can be in the page (Go's sheet holds the Ride line, whose dialog has its own).
  assert.notEqual("ride-sheet-search", "ride-types-search");
});

test("Go's three main buttons are as the transit lane left them", () => {
  const app = src("../App.tsx");
  assert.match(app, /<RideChips ids=\{goRideChips\(myGo\.ride\)\}[^>]*more=\{\(opener\) => openView\("ride", opener\)\}/);
});
