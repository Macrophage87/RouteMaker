// A transit trip kept checked while it is ridden (Stephen, 2026-11-02: "periodically check to see if there's any
// changes such as delays and the like. Make adjustments if not on the best route").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { CHECKED_PRESETS, LATE_TOLD_S, SWITCH_MIN_S, checkedTripOf, lateSaid, switchSaid, tripChecked, tripVerdict } from "./tripCheck.ts";

const ORANGE = "Ride, Metro to Federal Triangle (Orange Line), ride";
const BLUE = "Ride, Metro to Federal Triangle (Blue Line), ride";
const RIDE = "Ride the whole way";
const option = (label: string, totalS: number, chosen = false) => ({ key: label, label, total_s: totalS, minutes: Math.round(totalS / 60), direct: label === RIDE, chosen });
const NOW = 1_000_000;

test("only the trips with transit are checked: Walk has none", () => {
  assert.deepEqual(CHECKED_PRESETS, ["bike-transit", "bikeshare-transit", "walk-transit"]);
  assert.equal(tripChecked("walk"), false);
  assert.equal(tripChecked("bike-transit"), true);
  assert.equal(tripChecked(null), false);
});

test("the trip ridden is its plan's key; its arrival is read at the first check", () => {
  assert.deepEqual(checkedTripOf({ key: "k-orange" }), { key: "k-orange", arrivesAt: null });
});

const KEYED = (label: string) => `k-${label}`;
const opt = (label: string, totalS: number, chosen = false) => ({ ...option(label, totalS, chosen), key: KEYED(label) });

test("the first check only reads the trip's arrival; never a delay", () => {
  const verdict = tripVerdict({ key: KEYED(ORANGE), arrivesAt: null }, { options: [opt(ORANGE, 1800, true)] }, NOW);
  assert.deepEqual(verdict, { kind: "same", arrivesAt: NOW + 1_800_000, key: KEYED(ORANGE) });
});

test("the best trip (the API's first) replaces the one ridden where it is quicker by enough; barely quicker, not", () => {
  const trip = { key: KEYED(ORANGE), arrivesAt: NOW + 1_800_000 };
  const quicker = tripVerdict(trip, { options: [opt(BLUE, 1500), opt(ORANGE, 1500 + SWITCH_MIN_S, true)] }, NOW);
  assert.deepEqual(quicker, { kind: "switch", key: KEYED(BLUE), label: BLUE, savedS: SWITCH_MIN_S });
  const barely = tripVerdict(trip, { options: [opt(BLUE, 1700), opt(ORANGE, 1760, true)] }, NOW);
  assert.equal(barely?.kind, "same");
});

test("a trip the API says is gone is replaced by the best, however long; a label that changes is not a trip gone", () => {
  const trip = { key: KEYED(ORANGE), arrivesAt: NOW + 1_800_000 };
  assert.deepEqual(tripVerdict(trip, { options: [opt(RIDE, 2400, true)], asked_gone: true }, NOW), { kind: "switch", key: KEYED(RIDE), label: RIDE, savedS: null });
  // The same trip (the API matched its stops and lines) under another label and key: kept, its new key taken.
  const relabelled = tripVerdict(trip, { options: [{ ...opt("Ride, Metro to Smithsonian (Orange Line), ride", 1800, true), key: "k-new" }] }, NOW);
  assert.deepEqual(relabelled, { kind: "same", arrivesAt: NOW + 1_800_000, key: "k-new" });
});

test("a delay on the trip still best is said once it is enough later than last said", () => {
  const trip = { key: KEYED(ORANGE), arrivesAt: NOW + 1_800_000 };
  const late = tripVerdict(trip, { options: [opt(ORANGE, 1800 + LATE_TOLD_S, true)] }, NOW);
  assert.deepEqual(late, { kind: "late", arrivesAt: NOW + (1800 + LATE_TOLD_S) * 1000, key: KEYED(ORANGE) });
  assert.equal(tripVerdict(trip, { options: [opt(ORANGE, 1900, true)] }, NOW)?.kind, "same");
  assert.equal(tripVerdict(trip, { options: [] }, NOW), null);
});

test("the change and the delay are said in words", () => {
  assert.equal(switchSaid({ kind: "switch", key: "b", label: BLUE, savedS: 300 }), `Changed to a quicker trip, about 5 min sooner: ${BLUE}.`);
  assert.equal(switchSaid({ kind: "switch", key: "r", label: RIDE, savedS: null }), `Your trip is no longer running as planned. Changed to: ${RIDE}.`);
  assert.equal(lateSaid(NOW, () => "8:42 am"), "Delays on the way: now arriving about 8:42 am.");
});

// The wiring (App.tsx, RideMode.tsx): asked with the trip's key, checked again after each answer, and a change only
// to a trip that still has its transit after its line.
const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
const ride = readFileSync(new URL("../RideMode.tsx", import.meta.url), "utf8");

test("App asks with the trip's own key, re-checks the ride after every answer, and changes only to a trip with transit", () => {
  assert.match(app, /transitOption: key \} \}\)/);
  assert.match(app, /const result = await ask\(checking\.trip\.key\);\s*if \(!current\(\)/);
  assert.match(app, /const again = await ask\(verdict\.key\);\s*if \(!current\(\)/);
  assert.match(app, /onward\?\.some\(\(part\) => part\.kind === "transit"\)/);
  assert.match(app, /const current = \(\) => open\(\) && ridingNow\.current/);
});

test("the ride screen checks only before boarding, a share bike's only on the walk to its dock, and stops near the departure", () => {
  assert.match(ride, /const tripCheckOpen = !!onTripCheck && firstTransit >= 0 && toBoard && \(!trip\?\.shareBike \|\| walking\);/);
  assert.match(ride, /gate\.boardingSince === null \|\| Date\.now\(\) < gate\.boardingSince \+ gate\.waitS \* 1000 - BOARDING_MS/);
  assert.match(ride, /if \(!gate\.open \|\| ended\.current \|\| pausedRef\.current\) return false;/);
});
