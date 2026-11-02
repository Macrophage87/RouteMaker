// Avoid stairs (Stephen, 2026-11-02: "Add the option to avoid stairs for walking"): a Settings switch of its own, kept on
// this device, sent with the ride types that walk on their own.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { routeRequestBody } from "./api.ts";
import { AVOID_STAIRS_KEY, readAvoidStairs, writeAvoidStairs } from "./avoidStairs.ts";
import type { LonLat } from "./geo.ts";

const LINE: LonLat[] = [
  [-77.05, 38.9],
  [-77.02, 38.9],
];

test("off by default and kept on this device", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (key: string) => kept.get(key) ?? null, setItem: (key: string, value: string) => void kept.set(key, value) };
  assert.equal(readAvoidStairs(store), false);
  writeAvoidStairs(true, store);
  assert.equal(kept.get(AVOID_STAIRS_KEY), "1");
  assert.equal(readAvoidStairs(store), true);
  writeAvoidStairs(false, store);
  assert.equal(readAvoidStairs(store), false);
  assert.equal(readAvoidStairs(null), false);
});

test("a Bikeshare or transit plan says so; a ride on the rider's own bike never does", () => {
  for (const preset of ["bikeshare", "rebalance", "bike-transit", "bikeshare-transit"] as const) {
    assert.equal(JSON.parse(routeRequestBody(LINE, preset, { avoidStairs: true })).avoid_stairs, true, preset);
    assert.equal(JSON.parse(routeRequestBody(LINE, preset, { avoidStairs: false })).avoid_stairs, undefined, preset);
  }
  // Its walks beside the bike keep off stairs anyway, so the request (and the plans' cache key) is unchanged.
  assert.equal(JSON.parse(routeRequestBody(LINE, "default", { avoidStairs: true })).avoid_stairs, undefined);
  // Unset, the device's own choice: none kept here (no browser storage under test).
  assert.equal(JSON.parse(routeRequestBody(LINE, "bikeshare")).avoid_stairs, undefined);
});

test("Settings shows it as a switch on the Riding tab, for Go and Plan alike", () => {
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  const riding = sheets.slice(sheets.indexOf('id="settings-panel-riding"'), sheets.indexOf('id="settings-panel-display"'));
  assert.match(riding, /<AvoidStairsRow \/>/);
  assert.match(sheets, /function AvoidStairsRow\(\)[\s\S]*?role="switch"[\s\S]*?aria-checked=\{on\}/);
});
