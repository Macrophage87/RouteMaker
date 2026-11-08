/** Which exit to take off a train (Stephen, 2026-11-08: "the cue should mention which exit to use"). */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EXIT_NEAR_M, exitAt, exitWords, parseExits } from "./stationExit.ts";

test("DC's words for where an entrance comes up become a short sentence", () => {
  assert.equal(exitWords("NE CORNER OF ABLEMARLE STREET NW AND WISCONSIN AVENUE NW"), "Take the exit at Albemarle Street NW and Wisconsin Avenue NW.");
  assert.equal(exitWords("WISCONSIN AVENUE NW BETWEEN RIVER RD NW AND ALBEMARLE ST NW"), "Take the exit on Wisconsin Avenue NW.");
  assert.equal(exitWords("SE CORNER OF 7TH STREET NW AND H STREET NW"), "Take the exit at 7th Street NW and H Street NW.");
  assert.equal(exitWords("NORTH SIDE OF M STREET NE AT INTERSECTION WITH DELAWARE AVENUE NE"), "Take the exit at M Street NE and Delaware Avenue NE.");
  assert.equal(exitWords("SW CORNER OF EAST-WEST HWY AND WISCONSIN AVE"), "Take the exit at East-West Hwy and Wisconsin Ave.");
  assert.equal(exitWords("NW CORNER OF MONTGOMERY LN AND MD-355 S "), "Take the exit at Montgomery Ln and MD-355 S.");
  assert.equal(exitWords("WEST SIDE OF GEORGIA AVE "), "Take the exit on Georgia Ave.");
  assert.equal(exitWords("NORTH SIDE OF DULLES TOLL ROAD NORTH ELEVATOR"), "Take the exit on Dulles Toll Road.");
  // No street named: nothing said.
  assert.equal(exitWords("AIRPORT PARKING GARAGE"), null);
});

test("the walk's start picks the entrance, and every shipped entrance parses", () => {
  const exits = parseExits(readFileSync(new URL("../rail-data/metro-entrances.geojson", import.meta.url), "utf8"));
  assert.ok(exits.length > 200);
  // Tenleytown-AU: the entrance on Wisconsin Avenue's west side, and the one at Albemarle Street.
  assert.equal(exitAt(exits, [-77.08017, 38.94832]), "Take the exit on Wisconsin Avenue NW.");
  assert.equal(exitAt(exits, [-77.07936, 38.94809]), "Take the exit at Albemarle Street NW and Wisconsin Avenue NW.");
  // Far from any entrance (a bus stop's walk), or no point: none.
  assert.equal(exitAt(exits, [-77.0, 38.5]), null);
  assert.equal(exitAt(exits, null), null);
  assert.equal(EXIT_NEAR_M, 60);
  assert.ok(exits.filter((e) => exitWords(e.to) === null).length <= 8);
  assert.deepEqual(parseExits("not json"), []);
});
