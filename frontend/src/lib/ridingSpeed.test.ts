// The rider's own riding speed (the owner, 2026-10-27: "Some people who ride much faster than the defaults
// would like to be able to override the speed as an advanced feature"): kept, sent, synced, never linked.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SPEED_MAX_MPH, SPEED_MIN_MPH, SPEED_OWN, SPEED_STORAGE_KEY, readSpeed, speedKmh, speedOf, speedOptions, speedSetting, takesRiderSpeed, withSpeed, writeSpeed } from "./ridingSpeed.ts";
import { dialFields, type Dials } from "./dials.ts";
import { applyToDevice, deviceSettings, parseSettings, planSetting } from "./accountSettings.ts";

function memory(): { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void; data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) };
}

const DIALS: Dials = { stress: 70, hills: 0, when: null, carrying: null, assist: false };

test("only whole mph in the picker's range is a speed", () => {
  assert.equal(speedOf(18), 18);
  assert.equal(speedOf("18"), 18);
  for (const bad of [SPEED_MIN_MPH - 1, SPEED_MAX_MPH + 1, 18.5, "", "fast", null, undefined, true]) assert.equal(speedOf(bad), null);
});

test("it is kept, and set back to the ride type's own as a marker the account carries", () => {
  const store = memory();
  assert.equal(readSpeed(store), null);
  writeSpeed(20, store);
  assert.equal(readSpeed(store), 20);
  writeSpeed(null, store);
  assert.equal(store.data.get(SPEED_STORAGE_KEY), SPEED_OWN);
  assert.equal(readSpeed(store), null);
  assert.equal(speedSetting(SPEED_OWN), null);
  assert.equal(speedSetting(null), undefined);
});

test("the request carries it in km/h; the ride type's own sends nothing", () => {
  assert.equal(dialFields(withSpeed(DIALS, 20)).cycling_speed_kmh, speedKmh(20));
  assert.equal(speedKmh(20), 32.2);
  assert.equal("cycling_speed_kmh" in dialFields(withSpeed({ ...DIALS, ridingSpeedKmh: 30 }, null)), false);
});

test("never in the plan setting (nor so a link)", () => {
  assert.doesNotMatch(planSetting("default", withSpeed(DIALS, 20)), /32|speed/i);
});

test("the picker offers the ride type's own first, then mph with km/h", () => {
  const options = speedOptions();
  assert.equal(options[0][0], "");
  assert.equal(options.length, SPEED_MAX_MPH - SPEED_MIN_MPH + 2);
  assert.deepEqual(options.find(([value]) => value === "20"), ["20", "20 mph (32 km/h)"]);
});

test("signed in it syncs, a set-back included", () => {
  const store = memory();
  writeSpeed(22, store);
  assert.equal(deviceSettings(null, store, undefined).speed, 22);
  writeSpeed(null, store);
  assert.equal(deviceSettings(null, store, undefined).speed, null);
  assert.equal(parseSettings({ v: 1, speed: 25 })?.speed, 25);
  assert.equal(parseSettings({ v: 1, speed: null })?.speed, null);
  assert.equal(parseSettings({ v: 1, speed: 99 })?.speed, undefined);
  const other = memory();
  applyToDevice({ v: 1, speed: 25 }, other);
  assert.equal(readSpeed(other), 25);
  applyToDevice({ v: 1, speed: null }, other);
  assert.equal(readSpeed(other), null);
});

test("offered on own-bike ride types only", () => {
  assert.equal(takesRiderSpeed("default"), true);
  assert.equal(takesRiderSpeed("bike-transit"), true);
  for (const preset of ["mass-ride", "bikeshare", "rebalance", "bikeshare-transit"] as const) assert.equal(takesRiderSpeed(preset), false);
});

test("the picker sits under Hills in the ride settings", async () => {
  const { readFileSync } = await import("node:fs");
  const panel = readFileSync(new URL("../DialsPanel.tsx", import.meta.url), "utf8");
  assert.ok(panel.indexOf('label="Hills"') < panel.indexOf("label={SPEED_LABEL}"));
  assert.match(panel, /ridingSpeed && takesRiderSpeed\(preset\)/);
});
