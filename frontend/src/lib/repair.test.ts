/** Repair stands and bike shops (v0.7.0, Go's Repair chip behind More): reading, hours, nearest and words. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  REPAIR_NONE,
  kitWords,
  nearestRepair,
  openNow,
  parseRepair,
  repairDetails,
  repairFoundSaid,
  repairGeoJson,
  repairHowFar,
  repairText,
  repairTitle,
  type RepairPlace,
} from "./repair.ts";
import type { LonLat } from "./geo.ts";

const file = {
  source: "OpenStreetMap contributors, ODbL 1.0",
  points: [
    { id: "n1", x: -77.0, y: 38.9, d: 1 },
    { id: "n2", x: -77.001, y: 38.9, rs: "pt", n: "Union Station", fee: "no" },
    { id: "n3", x: -77.01, y: 38.9, rs: "" },
    { id: "n4", x: -77.02, y: 38.9, rs: "c" },
    { id: "w5", x: -77.002, y: 38.9, bs: 1, n: "Spokes Etc", h: "Mo-Sa 10:00-19:00; Su off", web: "https://example.org" },
    { id: "w6", x: -77.03, y: 38.9, bs: 1, n: "Far Shop", web: "javascript:alert(1)" },
    { id: "w7", x: -77.05, y: 38.9, bs: 1, n: "Farther Shop" },
    { id: "bad", x: "x", y: 38.9, rs: "p" },
  ],
};

test("stands and shops are read; water, restrooms and bad rows are skipped; only web links are kept", () => {
  const places = parseRepair(file)!;
  assert.deepEqual(
    places.map((p) => [p.id, p.kind]),
    [
      ["n2", "stand"],
      ["n3", "stand"],
      ["n4", "stand"],
      ["w5", "shop"],
      ["w6", "shop"],
      ["w7", "shop"],
    ],
  );
  assert.equal(places[0].kit, "pt");
  assert.equal(places[0].fee, "no");
  assert.equal(places[3].website, "https://example.org");
  assert.equal(places[4].website, undefined);
  assert.equal(parseRepair({ nope: 1 }), null);
  assert.deepEqual(parseRepair({ points: [] }), []);
});

test("the nearest two stands and two shops, together, nearest first", () => {
  const near = nearestRepair([-77.0, 38.9], parseRepair(file)!);
  assert.deepEqual(
    near.map((r) => r.place.id),
    ["n2", "w5", "n3", "w6"],
  );
  assert.ok(near.every((r, i) => i === 0 || r.metres >= near[i - 1].metres));
});

test("opening hours: read when simple, null (nothing claimed) when not", () => {
  const wedNoon = new Date(2026, 9, 14, 12, 0);
  const sunNoon = new Date(2026, 9, 18, 12, 0);
  const satLate = new Date(2026, 9, 17, 23, 30);
  const sunEarly = new Date(2026, 9, 18, 1, 0);
  assert.equal(openNow("Mo-Sa 10:00-19:00; Su off", wedNoon), true);
  assert.equal(openNow("Mo-Sa 10:00-19:00; Su off", sunNoon), false);
  assert.equal(openNow("24/7", sunNoon), true);
  assert.equal(openNow("10:00-12:00,13:00-18:00", wedNoon), false);
  assert.equal(openNow("Sa 22:00-02:00", satLate), true);
  assert.equal(openNow("Sa 22:00-02:00", sunEarly), true);
  assert.equal(openNow("Mo-Fr sunrise-sunset", wedNoon), null);
  assert.equal(openNow("Apr-Oct Mo-Fr 09:00-17:00", wedNoon), null);
  assert.equal(openNow("PH off; Mo-Fr 09:00-17:00", wedNoon), null);
});

test("words: a stand's kit and fee, a shop's hours, US units first with metric in brackets", () => {
  const places = parseRepair(file)!;
  const at = new Date(2026, 9, 14, 12, 0);
  assert.equal(kitWords("ptc"), "Pump, tools and chain tool");
  assert.equal(kitWords("p"), "Pump");
  assert.equal(kitWords(""), "");
  assert.equal(repairTitle(places[0]), "Repair stand, Union Station");
  assert.equal(repairTitle(places[1]), "Repair stand");
  assert.deepEqual(repairDetails(places[0], at), ["Pump and tools.", "Free."]);
  assert.deepEqual(repairDetails(places[1], at), ["Tools not listed."]);
  assert.deepEqual(repairDetails(places[3], at), ["Open now.", "Hours: Mo-Sa 10:00-19:00; Su off."]);
  assert.deepEqual(repairDetails(places[5], at), ["Hours not listed."]);
  const line = repairText({ place: places[0], metres: 500 }, at);
  assert.match(line, /^Repair stand, Union Station: 0\.3 mi \(0\.5 km\) away\. Pump and tools\. Free\.$/);
  assert.equal(repairFoundSaid([], true), REPAIR_NONE);
  // Review F7: one short line, the nearest first (the count is the list's).
  assert.equal(repairFoundSaid([{ place: places[0], metres: 500 }], true), "Nearest to you: Repair stand, Union Station, 0.3 mi (0.5 km).");
  assert.match(repairFoundSaid([{ place: places[0], metres: 500 }], false), /^Nearest to the map's center: /);
});

test("the map shows stands only (shops are in the list), and carries no names", () => {
  const places: RepairPlace[] = parseRepair(file)!;
  const geo = repairGeoJson(places) as { features: Array<{ properties: Record<string, unknown> }> };
  assert.equal(geo.features.length, 3);
  assert.ok(geo.features.every((f) => Object.keys(f.properties).every((k) => k === "id")));
});

test("Go: Repair and Sights sit behind More, with its expanded state said", () => {
  const go = readFileSync(new URL("../app/Go.tsx", import.meta.url), "utf8");
  const row = go.slice(go.indexOf('aria-label="Places"'), go.indexOf('aria-label="More places"'));
  assert.ok(!/Repair|Sights/.test(row), "the main row stays Home, Food, Water, Restroom, More");
  assert.match(go, /aria-expanded=\{moreOpen\} aria-controls=\{moreId\}/);
  assert.match(go, /id=\{moreId\}[^>]*aria-label="More places" hidden=\{!moreOpen\}/);
  assert.match(go, /places\.onRepair[\s\S]*Repair[\s\S]*places\.onSights[\s\S]*Sights/);
});

test("F13. a Repair row is named by its place and distance; its details are its description", () => {
  const sheet = readFileSync(new URL("../app/PlacesSheets.tsx", import.meta.url), "utf8");
  const repair = sheet.slice(sheet.indexOf("export function RepairSheet("), sheet.indexOf("function SightRow("));
  assert.match(repair, /aria-label=\{`\$\{placeLetter\(i\)\}: Ride to \$\{repairTitle\(item\.place\)\}, \$\{repairHowFar\(item\)\}`\}\s*aria-describedby=\{`\$\{rowId\}-\$\{i\}`\}/);
  assert.match(repair, /<span id=\{`\$\{rowId\}-\$\{i\}`\}>\{repairDetails\(item\.place, at\)\.join\(" "\)\}<\/span>/);
  // The name no longer repeats the details.
  assert.doesNotMatch(repair, /aria-label=\{[^}]*repairDetails/);
});

test("with a route: the least detour off it first, in words (the owner, 2026-10-18)", () => {
  const places = [
    { id: "n1", lon: -77.0, lat: 38.95, kind: "stand", name: "Far stand" },
    { id: "n2", lon: -76.95, lat: 38.9001, kind: "stand", name: "Route stand" },
    { id: "n3", lon: -76.98, lat: 38.91, kind: "shop", name: "Near shop" },
  ] as unknown as RepairPlace[];
  const route = { line: [[-77.0, 38.9], [-76.9, 38.9]] as LonLat[], speedMps: 4 };
  const items = nearestRepair([-77.0, 38.9], places, 2, 2, route);
  assert.deepEqual(items.map((i) => i.place.id), ["n2", "n3", "n1"]);
  assert.match(repairHowFar(items[0]), /^On your route at /);
  assert.match(repairHowFar(items[1]), /^\+[\d.]+ mi \([\d.]+ km\) detour, turning off at /);
  assert.match(repairFoundSaid(items, true), /^Least detour off your route: /);
  assert.equal(nearestRepair([-77.0, 38.9], places)[0].detour, undefined);
});
