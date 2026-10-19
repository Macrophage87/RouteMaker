/** A stop's card (Stephen 2026-10-19): what's there, the website, Route here or Add as stop; never a route by itself. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { openNowText, safeWebsite } from "./stopCard.ts";
import { foodWords, nearbyWords, repairWords, sightWords } from "./stopWords.ts";

// A Monday, 12:00 local time.
const NOON = new Date(2026, 9, 19, 12, 0);

test("a website is followed only when it is a web address", () => {
  assert.equal(safeWebsite("https://example.org/menu"), "https://example.org/menu");
  assert.equal(safeWebsite("http://example.org"), "http://example.org/");
  assert.equal(safeWebsite("javascript:alert(1)"), null);
  assert.equal(safeWebsite("tel:+12025550100"), null);
  assert.equal(safeWebsite("example.org"), null, "no scheme: not a link");
  assert.equal(safeWebsite(undefined), null);
});

test("open or closed now only where the mapped hours can be read", () => {
  assert.equal(openNowText("Mo-Fr 09:00-17:00", NOON), "Open now.");
  assert.equal(openNowText("Mo-Fr 17:00-22:00", NOON), "Closed now.");
  assert.equal(openNowText("Mo-Fr 09:00-17:00; PH off", NOON), null);
  assert.equal(openNowText(undefined, NOON), null);
});

test("food: kind, open now, then how far; the website kept", () => {
  const words = foodWords(
    { place: { id: "n1", lon: -77, lat: 38.9, kind: "r", name: "Ben's", cuisine: ["american"], hours: "Mo-Su 08:00-22:00", website: "https://example.org" }, fromCentreM: 800, fromRider: true },
    NOON,
  );
  assert.equal(words.title, "Ben's");
  assert.deepEqual(words.lines.slice(0, 2), ["Restaurant: american.", "Open now."]);
  assert.match(words.lines[2], /^0\.5 mi \(0\.8 km\) from you/);
  assert.equal(words.website, "https://example.org");
});

test("hours that cannot be read are shown as mapped; a sight's detour is said", () => {
  const place = { id: "n2", lon: -77, lat: 38.9, category: "museum" as const, name: "Gallery", hours: "Tu-Su 10:00-17:00; PH off" };
  const words = sightWords(place, NOON, { place, metres: 0, detour: { alongM: 1609, offM: 200, extraM: 600 } });
  assert.deepEqual(words.lines, ["Museum or gallery.", "Hours as mapped: Tu-Su 10:00-17:00; PH off.", "+0.4 mi (0.6 km) detour."]);
});

test("a repair stand's kit and fee, and a nearest place's details and distance", () => {
  const stand = repairWords({ id: "n3", kind: "stand", lon: -77, lat: 38.9, kit: "pt", fee: "no" }, NOON);
  assert.equal(stand.title, "Repair stand");
  assert.ok(stand.lines.includes("Free."));
  assert.equal(stand.lines.at(-1), "From OpenStreetMap: check it is working before you count on it.", "the repair card keeps its caution");
  const water = nearbyWords({ place: { id: "n4", kind: "water", point: [-77, 38.9], title: "Drinking water", details: ["Bottle filler."] }, distanceM: 1000, timeS: null, byBike: false });
  assert.deepEqual(water.lines, ["Bottle filler.", "0.6 mi (1.0 km) in a straight line."]);
});

test("a press on a lettered pin, its key or a Go row opens the card; the map's stop dots are cards in Plan and Go", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const pick = app.slice(app.indexOf("const pickLettered = (index: number) => {"), app.indexOf("const pickLetteredRef"));
  assert.match(pick, /openStopCard\(map, stop\.point, stop\.words, stopActionFor\(stop\.point, stop\.words\.title\), true\);/);
  assert.doesNotMatch(pick, /goTo|goAddStopAt|rideToNearest/, "no route from a pick");
  assert.match(app, /onPick=\{\(item\) => pickLettered\(/);
  assert.match(app, /onGoPick=\{\(r\) => pickLettered\(/);
  // Nothing while riding; Route here before a route, Add as stop with one.
  assert.match(app, /stopActionNow\.current = \(point, name\) => \{\s*if \(riding\) return null;/);
  // A card's action is for the state it opened in: a ride or a mode switch closes it.
  assert.match(app, /useEffect\(\(\) => closeStopCard\(\), \[riding, mode\]\);/);
  const overlay = readFileSync(new URL("../app/mapOverlay.ts", import.meta.url), "utf8");
  // Escape on the whole card (its close button too); the focus goes back after a keyboard pick; a layer's redraw
  // closes only its own card.
  assert.match(overlay, /element\?\.addEventListener\("keydown"/);
  assert.match(overlay, /if \(lost && returnTo\?\.isConnected\) returnTo\.focus\(\);/);
  assert.match(overlay, /closeStopCard\(layer\);/);
  const sheets = readFileSync(new URL("../app/PlacesSheets.tsx", import.meta.url), "utf8");
  assert.equal((sheets.match(/return stopCard\(map, (REPAIR|PLACES|FOOD)_LAYER/g) ?? []).length, 3);
});
