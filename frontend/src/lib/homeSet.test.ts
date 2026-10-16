// Setting Home simply (v0.7.0; Stephen 2026-10-15: "You should be able to set it with a map tap or address
// search."): the pure parts, the Home sheet rendered, and App's, Go's, Settings' and the road panel's wiring read
// as source (as goPlan.test.ts reads them).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CHANGE_HOME_TEXT, HOME_CLEARED, HOME_PICK_LINE, PICK_ON_MAP_TEXT, SET_AS_HOME_TEXT, homeAtSpot, homeClosesSheet, homeFromPlace, homeName, homeSetKey, homeSetSaid } from "./homeSet.ts";
import { HOME_NOT_SET } from "./myGo.ts";

const src = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const app = src("../App.tsx");
const go = src("../app/Go.tsx");
const sheets = src("../app/Sheets.tsx");
const road = src("../RoadInfoDialog.tsx");

test("Home is said as 'Home set to <name>.', named by its label, else its coordinates", () => {
  const home = homeFromPlace({ lon: -77.03, lat: 38.9, name: "1600 Pennsylvania Ave NW" });
  assert.deepEqual(home, { point: [-77.03, 38.9], label: "1600 Pennsylvania Ave NW" });
  assert.equal(homeSetSaid(home), "Home set to 1600 Pennsylvania Ave NW.");
  assert.equal(homeName({ point: [-77.03, 38.9], label: "  " }), "38.9000, -77.0300");
  assert.equal(HOME_CLEARED, "Home cleared.");
});

test("a spot on the map is Home at that spot, named by a known name, else the reverse look-up, else coordinates", () => {
  const spot: [number, number] = [-77.0434, 38.9125];
  const reverse = { ok: true as const, attribution: [], places: [{ name: "1529 16th St NW", label: "", lon: -77.04, lat: 38.91, kind: "house" }] };
  assert.deepEqual(homeAtSpot(spot, "Logan Circle", reverse), { point: spot, label: "Logan Circle" });
  // The point stays the spot pressed, not the look-up's.
  assert.deepEqual(homeAtSpot(spot, undefined, reverse), { point: spot, label: "1529 16th St NW" });
  assert.deepEqual(homeAtSpot(spot, undefined, { ok: false, status: 429 }), { point: spot, label: "38.9125, -77.0434" });
  assert.deepEqual(homeAtSpot(spot, undefined, null), { point: spot, label: "38.9125, -77.0434" });
  // The account keeps 120 characters of a label (lib/myGo.ts myGoBody).
  assert.equal(homeAtSpot(spot, "x".repeat(300), null).label.length, 120);
});

test("Go stays clean: the always-shown place row is still five chips, and the one line is short", () => {
  const row = go.slice(go.indexOf('aria-label="Places"'), go.indexOf("go-more-row"));
  assert.equal((row.match(/<button/g) ?? []).length, 5, "Home, Food, Water, Restroom and More");
  // Change Home is in More's row; the Home sheet is hidden until asked for.
  const more = go.slice(go.indexOf("go-more-row"), go.indexOf("go-home-sheet"));
  assert.match(more, /\{places\.homeReady && \([\s\S]*?\{CHANGE_HOME_TEXT\}/);
  assert.match(go, /className="go-home-sheet" role="group" aria-label="Home" hidden=\{!homeShown\}/);
  // One short line at most: the no-Home hint while the sheet is shut, or the pick line while picking.
  assert.ok(HOME_NOT_SET.length <= 40 && HOME_PICK_LINE.length <= 40);
  assert.match(go, /\{!places\.homeReady && !homeShown && \(/);
});

test("the Home chip with no Home opens the sheet in place: a disclosure, its hint only while shut", () => {
  assert.match(go, /aria-expanded=\{places\.homeReady \? undefined : homeShown\}/);
  assert.match(go, /aria-controls=\{places\.homeReady \? undefined : homeSheetId\}/);
  // Review F3 (changed from "the sheet stays open"): Home set from the sheet closes it, and the focus goes back
  // to the Home chip, which then rides Home (no aria-expanded: it no longer opens the sheet).
  assert.match(go, /if \(!homeClosesSheet\(was, homeKey, homeOpen\)\) return;\s*setHomeOpen\(false\);\s*homeChip\.current\?\.focus\(\);/);
  assert.match(go, /<button\s*ref=\{homeChip\}\s*type="button"\s*className="chip place-chip"/);
  assert.match(go, /aria-expanded=\{places\.homeReady \? undefined : homeShown\}/);
});

test("F3. the Home sheet closes once a Home is set from it, never on a clear or while shut", () => {
  const a = homeSetKey({ point: [-77.03, 38.9], label: "Home A" });
  const b = homeSetKey({ point: [-77.04, 38.91], label: "Home B" });
  assert.equal(homeSetKey(null), "");
  assert.equal(homeClosesSheet("", a, true), true, "the first Home set: the sheet closes");
  assert.equal(homeClosesSheet(a, b, true), true, "Change Home to another place: closes");
  assert.equal(homeClosesSheet(a, "", true), false, "Clear Home: the sheet stays, for the next one");
  assert.equal(homeClosesSheet(a, a, true), false, "no change");
  assert.equal(homeClosesSheet("", a, false), false, "set elsewhere (Settings, the road panel) with the sheet shut");
});

test("the Home sheet offers exactly the two ways: the search and Pick on the map; with a Home, its name and Clear", () => {
  // Node runs no .tsx (the suite reads components as source): the sheet's parts and when each shows.
  const setter = go.slice(go.indexOf("export function HomeSetter"), go.indexOf("export function GoAddStop"));
  assert.equal((setter.match(/<PlaceSearch variant="home"/g) ?? []).length, 1, "the app's search box, as Settings had it");
  assert.equal((setter.match(/<button/g) ?? []).length, 2, "Pick on the map and Clear Home, nothing else");
  assert.match(setter, /\{onPickOnMap && \(\s*<button type="button" className="secondary" aria-pressed=\{picking\} onClick=\{onPickOnMap\}>[\s\S]*?\{PICK_ON_MAP_TEXT\}/);
  assert.match(setter, /\{home && \(\s*<p className="home-now">\s*<strong>Home: <\/strong>\s*\{homeName\(home\)\}/);
  assert.match(setter, /\{home && \(\s*<button[\s\S]*?\{CLEAR_HOME_TEXT\}/);
  assert.match(setter, /\{picking && <p className="hint home-pick-line">\{HOME_PICK_LINE\}<\/p>\}/);
  assert.equal(PICK_ON_MAP_TEXT, "Pick on the map");
  // Go passes the map way; Settings' copy has none (the map is behind Settings).
  assert.match(go, /picking=\{places\.homePicking\}\s*onPickOnMap=\{places\.onPickHome\}/);
  assert.doesNotMatch(sheets, /onPickOnMap/);
  assert.match(sheets, /<HomeSetter home=\{myGo\.home\} [^>]*onPlace=\{\(place: Place\) => setHome\(homeFromPlace\(place\)\)\} onClear=\{\(\) => setHome\(null\)\} \/>/);
});

test("the focus is never taken: only Clear Home moves it, to the search box, since the button goes with the Home", () => {
  const setter = go.slice(go.indexOf("export function HomeSetter"), go.indexOf("export function GoAddStop"));
  assert.equal((setter.match(/\.focus\(/g) ?? []).length, 1);
  assert.match(setter, /onClear\(\);\s*\/\/[^\n]*\n\s*box\.current\?\.querySelector<HTMLInputElement>\("input"\)\?\.focus\(\);/);
  const setHome = app.slice(app.indexOf("const setHome = "), app.indexOf("// Saved settings (v0.7.0)"));
  assert.doesNotMatch(setHome, /focus/);
  const at = app.slice(app.indexOf("const setHomeAt = async"), app.indexOf("const setHomeAtRef"));
  assert.doesNotMatch(at, /focus/);
});

test("App: Home is said politely at once, saved to the account signed in or this device signed out, and a refusal is said", () => {
  const setHome = app.slice(app.indexOf("const setHome = "), app.indexOf("// Saved settings (v0.7.0)"));
  assert.match(setHome, /announce\(home \? homeSetSaid\(home\) : HOME_CLEARED\);/);
  assert.match(setHome, /saveMyGoNow\(\{ \.\.\.myGoRef\.current, home \}, false, \(saved\) => \{\s*if \(!saved\) announce\(MY_GO_NOT_SAVED\);/);
  // The page's region is a polite status (announce writes it).
  assert.match(app, /<p className="visually-hidden" role="status" aria-live="polite">/);
  // Signed out it stays on this device (saveDeviceMyGo), Home included; signed in, POST /api/me/go as before.
  assert.match(app, /saveDeviceMyGo\(next\);\s*if \(speak\) sayMyGo\(MY_GO_SAVED_DEVICE\);\s*onSaved\?\.\(true\);/);
  assert.match(app, /void saveMyGo\(window\.location\.origin, next\)\.then\(\(saved\) => \{/);
  // Go's sheet and Settings both set Home through it.
  assert.match(app, /onHomePlace: \(found\) => setHome\(homeFromPlace\(found\)\),\s*onClearHome: \(\) => setHome\(null\),/);
  assert.match(app, /const myGoControls = \{ myGo, signedIn: me\.signed_in, save: saveMyGoNow, setHome,/);
});

test("the map: Set as Home in the road panel (hold or right-click a spot), and Pick on the map's next tap", () => {
  assert.equal(SET_AS_HOME_TEXT, "Set as Home");
  // The road panel's "Use this spot" row has Set as Home; it closes the panel, whose close gives the focus back.
  const row = road.slice(road.indexOf('aria-label="Use this spot"'), road.indexOf("road-info-place-why"));
  assert.match(row, /onSetHome\(request\.point\);\s*close\(\);/);
  assert.match(row, /\{SET_AS_HOME_TEXT\}/);
  assert.match(app, /onSetHome=\{\(point\) => void setHomeAt\(point\)\}/);
  // A tap while picking is Home, before Go's destination or a plan point; the pick ends with it.
  const place = app.slice(app.indexOf("const place = useCallback("), app.indexOf("if (goTapSetsEnd(modeRef.current))"));
  assert.match(place, /if \(homePickRef\.current\) \{\s*setHomePick\(false\);\s*void setHomeAtRef\.current\(point\);\s*return;/);
  // Named by a known name, else the reverse look-up through the page's one gate.
  assert.match(app, /const reverse = known \? null : await geoGate\.run\(\(\) => fetchPlaces\(reverseUrl\(point\)\)\)\.catch\(\(\) => null\);\s*setHome\(homeAtSpot\(point, known, reverse\)\);/);
  // Picking is said, and ends when Go does or a ride starts.
  assert.match(app, /announce\(on \? HOME_PICK_LINE : HOME_PICK_CANCELLED\);/);
  assert.match(app, /if \(mode !== "go" \|\| riding\) setHomePick\(false\);/);
  assert.equal(CHANGE_HOME_TEXT, "Change Home");
});

test("privacy-1: the Home search does not keep its pick in recent places; every other search does", () => {
  const search = src("../PlaceSearch.tsx");
  const at = search.indexOf("const pick = (place: Place");
  const pick = search.slice(at, search.indexOf('setQuery("");', at));
  assert.match(pick, /if \(variant !== "home"\) setRecent\(rememberRecentPlace\(place\)\);/);
  assert.equal((search.match(/rememberRecentPlace\(/g) ?? []).length, 1, "no other way in");
});
