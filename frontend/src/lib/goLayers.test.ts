// Go's map layers (follow-up review of PR #95; owner decision pending): Go opens with water and restrooms and the
// Metro and MARC stations off, Plan as before; the rider's own Layers choice is kept and wins in both.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { RAIL_PREFS_KEY, layersOnByDefault, railFor, readRailChoice, saveRailChoice, waterPrefsFor } from "./goLayers.ts";
import { WATER_PREFS_KEY, readWaterChoice, saveWaterPrefs } from "./waterRestrooms.ts";

function memory() {
  const kept = new Map<string, string>();
  return { kept, store: { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) } };
}

test("unchosen, Go opens with the layers off and Plan with them on", () => {
  assert.equal(layersOnByDefault("go"), false);
  assert.equal(layersOnByDefault("plan"), true);
  assert.deepEqual(waterPrefsFor(null, "go"), { on: false, basic: true, untreated: true });
  assert.deepEqual(waterPrefsFor(null, "plan"), { on: true, basic: true, untreated: true });
  assert.deepEqual(railFor(null, "go"), { metro: false, marc: false });
  assert.deepEqual(railFor(null, "plan"), { metro: true, marc: true });
});

test("the rider's choice wins in both views", () => {
  const on = { on: true, basic: false, untreated: true };
  const off = { on: false, basic: true, untreated: true };
  assert.deepEqual(waterPrefsFor(on, "go"), on);
  assert.deepEqual(waterPrefsFor(off, "plan"), off);
  assert.deepEqual(railFor({ metro: true, marc: false }, "go"), { metro: true, marc: false });
  assert.deepEqual(railFor({ metro: false, marc: false }, "plan"), { metro: false, marc: false });
});

test("the choices are kept on this device; never changed, or unreadable, there is none", () => {
  const { kept, store } = memory();
  assert.equal(readWaterChoice(store), null);
  assert.equal(readRailChoice(store), null);
  saveWaterPrefs({ on: true, basic: true, untreated: false }, store);
  assert.deepEqual(readWaterChoice(store), { on: true, basic: true, untreated: false });
  assert.equal(saveRailChoice({ metro: true, marc: false }, store), true);
  assert.equal(kept.get(RAIL_PREFS_KEY), '{"metro":true,"marc":false}');
  assert.deepEqual(readRailChoice(store), { metro: true, marc: false });
  kept.set(RAIL_PREFS_KEY, '{"metro":"yes"}');
  assert.equal(readRailChoice(store), null, "not the shape: unchosen");
  kept.set(RAIL_PREFS_KEY, "{");
  assert.equal(readRailChoice(store), null);
  const refused = { getItem: () => { throw new Error("refused"); }, setItem: () => { throw new Error("refused"); } };
  assert.equal(readWaterChoice(refused), null);
  assert.equal(readRailChoice(refused), null);
  assert.equal(saveRailChoice({ metro: true, marc: true }, refused), false);
  assert.equal(saveRailChoice({ metro: true, marc: true }, null), false);
  assert.ok(WATER_PREFS_KEY);
});

test("App shows the view's default until the rider chooses, and keeps the choice", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const \[railChoice, setRailChoice\] = useState<RailVisibility \| null>\(\(\) => readRailChoice\(\)\);\s*const rail = useMemo\(\(\) => railFor\(railChoice, mode\), \[railChoice, mode\]\);/);
  assert.match(app, /const setRail = \(next: RailVisibility\) => \{\s*setRailChoice\(next\);\s*saveRailChoice\(next\);/);
  assert.match(app, /const \[waterChoice, setWaterChoice\] = useState<WaterPrefs \| null>\(\(\) => readWaterChoice\(\)\);\s*const waterPrefs = useMemo\(\(\) => waterPrefsFor\(waterChoice, mode\), \[waterChoice, mode\]\);/);
  assert.match(app, /const changeWaterPrefs = \(next: WaterPrefs\) => \{\s*setWaterChoice\(next\);\s*saveWaterPrefs\(next\);/);
  assert.doesNotMatch(app, /useState<RailVisibility>\(\{ metro: true, marc: true \}\)/);
});
