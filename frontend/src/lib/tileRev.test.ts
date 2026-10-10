// The stress tiles asked for again after an instance admin's change (lib/tileRev.ts, lib/mapStyle.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { massSource, refreshStressTiles, stressSource, stressTileTemplate, massTileTemplate, STRESS_SOURCE_ID, MASS_SOURCE_ID } from "./mapStyle.ts";
import { revSuffix, setTileRev, tileRev } from "./tileRev.ts";

const ORIGIN = "https://example.test";

test("before a change the tile addresses are the contract's, with no parameter", () => {
  setTileRev(0);
  assert.equal(revSuffix(), "");
  assert.deepEqual(stressSource(ORIGIN).tiles, ["rmstress://https://example.test/tiles/stress/{z}/{x}/{y}.pbf"]);
  assert.deepEqual(massSource(ORIGIN).tiles, ["rmstress://https://example.test/tiles/mass/{z}/{x}/{y}.pbf"]);
});

test("after a change both tile sources are asked for under the edit generation, and a rebuilt style keeps it", () => {
  const told: Record<string, string[]> = {};
  const map = {
    getSource: (id: string) => ({ setTiles: (tiles: string[]) => (told[id] = tiles) }),
  };
  assert.equal(refreshStressTiles(map, ORIGIN, 3), 2);
  assert.equal(tileRev(), 3);
  assert.deepEqual(told[STRESS_SOURCE_ID], ["rmstress://https://example.test/tiles/stress/{z}/{x}/{y}.pbf?rev=3"]);
  assert.deepEqual(told[MASS_SOURCE_ID], ["rmstress://https://example.test/tiles/mass/{z}/{x}/{y}.pbf?rev=3"]);
  // A source added later (a style rebuilt for the palette) asks the same way.
  assert.equal(stressTileTemplate(ORIGIN), told[STRESS_SOURCE_ID][0]);
  assert.equal(massTileTemplate(ORIGIN), told[MASS_SOURCE_ID][0]);
  assert.deepEqual(stressSource(ORIGIN).tiles, [told[STRESS_SOURCE_ID][0]]);
  setTileRev(0);
});

test("a source that is not on the map, or has no setTiles, is skipped", () => {
  assert.equal(refreshStressTiles({ getSource: () => undefined }, ORIGIN, 1), 0);
  assert.equal(refreshStressTiles({ getSource: () => ({}) }, ORIGIN, 2), 0);
  setTileRev(0);
});

test("the generation is a positive whole number or nothing", () => {
  for (const bad of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
    setTileRev(bad);
    assert.equal(tileRev(), 0, String(bad));
  }
  setTileRev(7);
  assert.equal(revSuffix(), "?rev=7");
  setTileRev(0);
});
