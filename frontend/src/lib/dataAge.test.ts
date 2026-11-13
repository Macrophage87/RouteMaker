import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dataAgeSaid, dayLabel, mapDataDay, PLACE_FILES, placesAsOf } from "./dataAge.ts";

const AS_OF = JSON.parse(readFileSync(new URL("../amenity-data/as-of.json", import.meta.url), "utf8"));

test("the places' date is the oldest of the place files and the cities' racks, and the barrier list is not a place", () => {
  const fresh = { "water-restrooms": "2026-11-10", food: "2026-11-10", places: "2026-11-10", "trail-miles": "2026-11-10", "bike-parking": "2026-11-10", barriers: "2026-01-01" };
  assert.equal(placesAsOf({ extract: { ...fresh, food: "2026-10-09" }, cities: "2026-11-10" }), "2026-10-09");
  // Racks DDOT and BCDOT listed weeks ago are not called this week's because the OSM part was refreshed.
  assert.equal(placesAsOf({ extract: fresh, cities: "2026-11-01" }), "2026-11-01");
  assert.equal(placesAsOf({ extract: fresh }), null);
  // A file the dates file does not name is not claimed: no date rather than a wrong one.
  assert.equal(placesAsOf({ extract: { food: "2026-11-10" } }), null);
  assert.equal(placesAsOf({ extract: { "water-restrooms": "soon", food: "2026-10-09", places: "2026-11-10", "trail-miles": "2026-11-10", "bike-parking": "2026-11-10" } }), null);
});

test("the committed dates file names every place file (scripts/refresh_places.py writes it)", () => {
  for (const name of PLACE_FILES) assert.match(AS_OF.extract[name], /^\d{4}-\d{2}-\d{2}$/, name);
  assert.ok(placesAsOf(AS_OF));
});

test("the map's day comes from the coverage answer, and only a day", () => {
  assert.equal(mapDataDay({ map_data: "2026-11-10" }), "2026-11-10");
  assert.equal(mapDataDay({}), null);
  assert.equal(mapDataDay({ map_data: "20261110T170245Z" }), null);
  assert.equal(mapDataDay(null), null);
});

test("a calendar day, never shifted by the rider's time zone", () => {
  assert.equal(dayLabel("2026-11-10", "en-US"), "Nov 10, 2026");
  assert.equal(dayLabel("2026-01-01", "en-US"), "Jan 1, 2026");
});

test("one line: both dates, either alone, or nothing", () => {
  assert.equal(dataAgeSaid("2026-11-10", "2026-10-09"), "Map data from Nov 10, 2026. Places and racks from Oct 9, 2026.");
  assert.equal(dataAgeSaid(null, "2026-10-09"), "Places and racks from Oct 9, 2026.");
  assert.equal(dataAgeSaid("2026-11-10", null), "Map data from Nov 10, 2026.");
  assert.equal(dataAgeSaid(null, null), "");
});

test("Settings' About shows it under the version, from the coverage answer App already fetches", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  const version = sheets.indexOf("{versionSaid()}</p>}");
  const line = sheets.indexOf('{dataAge && <p className="hint settings-data-age">{dataAge}</p>}');
  assert.ok(version > 0 && line > version, "the data-age line follows the version line");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /setMapDay\(mapDataDay\(coverage\.properties\)\)/);
  assert.match(app, /mapDataDay: mapDay,/);
});
