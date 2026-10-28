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
  COMMON_RIDE_TYPES,
  rideSections,
  rideTypeSections,
} from "./rideTypeGroups.ts";

const src = (name: string) => readFileSync(new URL(name, import.meta.url), "utf8");

test("every ride type is in exactly one group", () => {
  const grouped = RIDE_GROUPS.flatMap((g) => g.ids);
  assert.equal(new Set(grouped).size, grouped.length);
  assert.deepEqual([...grouped].sort(), PRESETS.map((p) => p.id).sort());
});

test("the groups are the owner's: Transportation (Rebalance Ride with it, P3), Adventure (Fast with it), Group", () => {
  assert.deepEqual(
    RIDE_GROUPS.map((g) => g.label),
    ["Transportation", "Adventure", "Group"],
  );
  const [transport, adventure, group] = RIDE_GROUPS;
  // Rebalance Ride moved from Adventure to Transportation (P3, the owner's approved audit).
  assert.deepEqual([...transport.ids], ["default", "bike-transit", "bikeshare-transit", "bikeshare", "cargo", "ebike", "novice", "rebalance"]);
  assert.deepEqual([...adventure.ids], ["fast", "trailmaxxing", "mountain-goat", "mountain-bike", "gravel"]);
  assert.deepEqual([...group.ids], ["group-ride", "mass-ride"]);
});

test("F9. Go's More ride types: the common types first, the other groups folded; a search shows them all flat", () => {
  // The four exist, and are Default, Novice and Nervous, Bikeshare and Own Bike + transit.
  for (const id of COMMON_RIDE_TYPES) assert.ok(PRESETS.some((p) => p.id === id), id);
  assert.deepEqual([...COMMON_RIDE_TYPES], ["default", "novice", "bikeshare", "bike-transit"]);
  const plain = rideSections("");
  assert.deepEqual(plain.common, ["default", "novice", "bikeshare", "bike-transit"]);
  assert.equal(plain.folded, true);
  // No type twice: the folded groups leave the common ones out, and all the others are in them.
  const rest = plain.groups.flatMap((g) => g.ids);
  assert.ok(rest.every((id) => !COMMON_RIDE_TYPES.includes(id)));
  assert.equal(rest.length + plain.common.length, PRESETS.length);
  assert.deepEqual(plain.groups.map((g) => g.id), ["transportation", "adventure", "group"]);
  const searched = rideSections("mountain");
  assert.equal(searched.folded, false);
  assert.deepEqual(searched.common, []);
  assert.deepEqual(searched.groups.flatMap((g) => g.ids), ["mountain-goat", "mountain-bike"]);
  const sheets = src("../app/Sheets.tsx");
  const go = sheets.slice(sheets.indexOf("export function RideGroupChips("), sheets.indexOf("export function RideChips("));
  assert.match(go, /<details key=\{group\.id\} className="fold ride-sheet-fold" open=\{group\.ids\.includes\(preset\) \|\| undefined\}>/);
  assert.ok(go.indexOf('<h4 id="ride-sheet-common">{t("Common")}</h4>') < go.indexOf("groups.map"), "the common types first");
  assert.doesNotMatch(go, /className="ride-group"/);
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
  assert.ok(!both.includes("bike-transit"), "Own Bike + 🚆🚌 has no dock");
});

test("a hyphen or an apostrophe does not stop a match", () => {
  const ebike = PRESETS.find((p) => p.id === "ebike")!;
  assert.ok(matchesRideType(ebike, "ebike"));
  assert.ok(matchesRideType(ebike, "e-bike"));
  const cargo = PRESETS.find((p) => p.id === "cargo")!;
  assert.ok(matchesRideType(cargo, "cargo bikes pace"));
  // Novice and Nervous is found by the words a rider may look for (its keywords).
  const novice = PRESETS.find((p) => p.id === "novice")!;
  assert.ok(matchesRideType(novice, "kids"));
  assert.ok(matchesRideType(novice, "beginner"));
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
  // Go: the list under its own h3, the groups as h4 under it, so the Ride line's "Ride type" h3 after
  // it in the sheet is not read as a fourth group; each group named once, by its heading.
  assert.match(go, /<section ref=\{scopeRef\} className="ride-groups" aria-labelledby="ride-sheet-types">\s*<h3 id="ride-sheet-types" className="visually-hidden">\s*\{t\("Every ride type"\)\}\s*<\/h3>/);
  // Review F9: a search's groups are ride-sheet-group (.ride-group is the group ride overlay's, absolutely placed).
  assert.match(go, /<section key=\{group\.id\} className="ride-sheet-group" aria-labelledby=\{`ride-sheet-\$\{group\.id\}`\}>\s*<h4 id=\{`ride-sheet-\$\{group\.id\}`\}>\{group\.label\}<\/h4>\s*<RideTypeCards ids=\{group\.ids\} preset=\{preset\} onPick=\{onPick\} idPrefix="ride-sheet" icon=\{rideIcon\} \{\.\.\.star\} \/>/);
  assert.match(sheets, /role=\{label \? "group" : undefined\} aria-label=\{label\}/);
  // Go: the search is cleared whenever the sheet is left (as Plan's dialog on closing).
  assert.match(go, /useEffect\(\(\) => \{\s*if \(!open\) setQuery\(""\);\s*\}, \[open\]\);/);
  // P3: a pick closes the sheet.
  assert.match(src("../App.tsx"), /<RideGroupChips preset=\{preset\} onPick=\{pickRideAndClose\} open=\{view === "ride"\} \/>/);
  assert.ok(go.indexOf("<RideTypeSearch") < go.indexOf("groups.map"), "the search comes before the groups");
  const plan = src("../RideTypePicker.tsx");
  assert.match(plan, /<RideTypeSearch id="ride-types-search"/);
  // Each group under its heading; in the popup (the owner, 2026-10-28) the groups after Favorites and Common are
  // folded, as Go's sheet folds them, the one in use open, its heading then read and the fold's summary shown.
  assert.match(plan, /<GroupFold key=\{group\.id\} fold=\{folded && !OPEN_GROUPS\.includes\(group\.id\)\} label=\{group\.label\} count=\{group\.ids\.length\} open=\{group\.ids\.includes\(preset\)\}>\s*<section className="ride-type-group" aria-labelledby=\{`ride-types-\$\{group\.id\}`\}>\s*<h3 id=\{`ride-types-\$\{group\.id\}`\} className=\{folded && !OPEN_GROUPS\.includes\(group\.id\) \? "visually-hidden" : undefined\}>\{group\.label\}<\/h3>/);
  assert.match(plan, /const folded = rideSections\(query, undefined, favorites\)\.folded;/);
  assert.match(plan, /const OPEN_GROUPS: readonly string\[\] = \["favorites", "common"\];/);
  assert.ok(plan.indexOf("<RideTypeSearch") < plan.indexOf("groups.map((group)"), "the search comes before the groups");
  // The search is cleared as the dialog closes, so the next opening has every type and the one in
  // use takes the focus (cleared on open, the card would not be there yet to focus).
  assert.match(plan, /const onClose = \(\) => \{\s*setQuery\(""\);\s*openerRef\.current\?\.focus\(\);/);
  assert.doesNotMatch(plan, /setQuery\(""\);\s*dialogRef\.current\?\.showModal\(\);/);
  // The two ids differ, so both can be in the page (Go's sheet holds the Ride line, whose dialog has its own).
  const goId = go.match(/<RideTypeSearch id="([^"]+)"/)?.[1];
  const planId = plan.match(/<RideTypeSearch id="([^"]+)"/)?.[1];
  assert.ok(goId && planId);
  assert.notEqual(goId, planId);
});

test("Go's three main buttons are as the transit lane left them", () => {
  const app = src("../App.tsx");
  assert.match(app, /<RideChips\s+ids=\{goRideChips\(myGo\.ride, preset, favoriteRides\)\}[^>]*more=\{\(opener\) => openView\("ride", opener\)\}/);
});

test("the transit types are found by transit, walk, train or bus, though their names show emoji", () => {
  // Stephen, 2026-10-12: renamed "Own Bike + 🚆🚌" and "Bikeshare + 🚶🚆🚌"; the search still finds them.
  const found = (query: string) => filterRideGroups(query).flatMap((group) => group.ids);
  for (const word of ["transit", "train", "bus", "Transit"]) {
    assert.ok(found(word).includes("bike-transit") && found(word).includes("bikeshare-transit"), word);
  }
  assert.ok(found("walk").includes("bikeshare-transit"));
  assert.ok(found("plus walk").includes("bikeshare-transit"));
});

// ---- P3: one grouping everywhere, the chips, the climb figure -------------------------------------------------

test("P3: one grouping everywhere: Common, Transportation, Adventure, Group (favorites first where starred)", () => {
  const plain = rideTypeSections();
  assert.deepEqual(plain.map((g) => g.id), ["common", "transportation", "adventure", "group"]);
  assert.deepEqual([...plain[0].ids], [...COMMON_RIDE_TYPES]);
  assert.equal(rideTypeCount(plain), PRESETS.length);
  const starred = rideTypeSections("", ["gravel"]);
  assert.deepEqual(starred.map((g) => g.id), ["favorites", "common", "transportation", "adventure", "group"]);
  assert.ok(!starred.find((g) => g.id === "adventure")?.ids.includes("gravel"));
  // A search: its matches, without Common.
  assert.deepEqual(rideTypeSections("mountain").map((g) => [g.id, [...g.ids]]), [["adventure", ["mountain-goat", "mountain-bike"]]]);
  // Plan's dialog and Settings' Default ride type (option groups) take them.
  assert.match(src("../RideTypePicker.tsx"), /const groups = rideTypeSections\(query, favorites\);/);
  const sheets = src("../app/Sheets.tsx");
  assert.match(sheets, /label=\{t\("Default ride type"\)\}[\s\S]{0,200}groups=\{rideTypeSections\(\)\}/);
  assert.doesNotMatch(sheets, /Go's ride type"\)/);
  assert.match(src("../SettingRow.tsx"), /<optgroup key=\{group\.label\} label=\{group\.label\}>/);
});

test("P3: Go's chips are one sideways row, the one in use first, marked when its sliders moved", () => {
  const sheets = src("../app/Sheets.tsx");
  const chips = sheets.slice(sheets.indexOf("export function RideChips("));
  assert.match(chips, /\{t\("Ride type & settings"\)\}/);
  assert.doesNotMatch(sheets, /More ride types"\)/);
  // "(changed)" is shown; the whole of it is heard.
  assert.match(chips, /<span className="ride-changed" aria-hidden="true">\s*\{t\("\(changed\)"\)\}\s*<\/span>\s*<span className="visually-hidden">\{t\(", settings changed from this ride type's start"\)\}<\/span>/);
  assert.match(chips, /rowRef\.current\?\.scrollTo\?\.\(\{ left: 0 \}\);\s*\}, \[preset\]\);/);
  const css = src("../styles.css");
  assert.match(css, /\.chip-row\.ride-chips \{\s*flex-wrap: nowrap;\s*overflow-x: auto;/);
  assert.match(css, /\.chip-row\.ride-chips \.chip \{\s*flex: none;\s*white-space: nowrap;/);
  // No two-column grid of chips on a phone any more.
  assert.doesNotMatch(css, /\.go-sheet \.ride-chips \{\s*display: grid;/);
});

test("P3: Go's climb figure is a button to the Hills slider; the Ride sheet closes on a pick and shows the totals", () => {
  const panel = src("../app/RoutePanel.tsx");
  assert.match(panel, /<button type="button" className="go-climb" onClick=\{\(event\) => go\.onClimb\?\.\(event\.currentTarget\)\} aria-describedby="go-climb-hint">/);
  const app = src("../App.tsx");
  assert.match(app, /onClimb: openHills,/);
  assert.match(app, /sheet\?\.querySelector<HTMLElement>\('\[data-dial="hills"\]'\)/);
  assert.match(src("../DialsPanel.tsx"), /label=\{t\("Hills"\)\}\s*dial="hills"/);
  // A pick in the Ride sheet goes back; a changed ride shows Go's sheet from the top.
  assert.match(app, /const pickRideAndClose = \(id: PresetId\) => \{\s*pickRide\(id\);\s*if \(modeRef\.current === "go" && viewNow\.current === "ride"\) backToPlanner\(\);/);
  assert.match(app, /const toTotals = was === "ride" && view !== "ride" && modeRef\.current === "go" && rideAtSheet\.current !== rideKey;/);
  // Plan's dialog already closes on a pick.
  assert.match(src("../RideTypePicker.tsx"), /onChoose\(id, mtbChosen\(preset, id, choose\(id, load, dials\)\)\);\s*close\(\);/);
});
