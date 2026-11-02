// A transit trip kept checked while it is ridden (Stephen, 2026-11-02: "periodically check to see if there's any
// changes such as delays and the like. Make adjustments if not on the best route").
import { test } from "node:test";
import assert from "node:assert/strict";
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

test("the trip ridden is its plan's chosen option, arriving its total time from now", () => {
  const trip = checkedTripOf({ options: [option(ORANGE, 1800, true), option(RIDE, 2400)], total_s: 1800 }, NOW);
  assert.deepEqual(trip, { label: ORANGE, arrivesAt: NOW + 1_800_000 });
});

test("another trip quicker by enough replaces it; one barely quicker does not", () => {
  const trip = { label: ORANGE, arrivesAt: NOW + 1_800_000 };
  const quicker = tripVerdict(trip, { options: [option(BLUE, 1500, true), option(ORANGE, 1500 + SWITCH_MIN_S)] }, NOW);
  assert.deepEqual(quicker, { kind: "switch", label: BLUE, savedS: SWITCH_MIN_S });
  const barely = tripVerdict(trip, { options: [option(BLUE, 1700, true), option(ORANGE, 1760)] }, NOW);
  assert.deepEqual(barely, { kind: "same" });
});

test("a trip no longer offered (its train gone, its line suspended) is replaced by the best", () => {
  const trip = { label: ORANGE, arrivesAt: NOW + 1_800_000 };
  assert.deepEqual(tripVerdict(trip, { options: [option(RIDE, 2400, true)] }, NOW), { kind: "switch", label: RIDE, savedS: null });
});

test("a delay on the trip still best is said once it is enough later than last said", () => {
  const trip = { label: ORANGE, arrivesAt: NOW + 1_800_000 };
  const late = tripVerdict(trip, { options: [option(ORANGE, 1800 + LATE_TOLD_S, true)] }, NOW);
  assert.deepEqual(late, { kind: "late", arrivesAt: NOW + (1800 + LATE_TOLD_S) * 1000 });
  assert.deepEqual(tripVerdict(trip, { options: [option(ORANGE, 1900, true)] }, NOW), { kind: "same" });
  // Its own option where another is chosen, but not quick enough to change to: its time is the one compared.
  const mine = tripVerdict(trip, { options: [option(BLUE, 2000, true), option(ORANGE, 2100)] }, NOW);
  assert.deepEqual(mine, { kind: "late", arrivesAt: NOW + 2_100_000 });
});

test("the change and the delay are said in words", () => {
  assert.equal(switchSaid({ kind: "switch", label: BLUE, savedS: 300 }), `Changed to a quicker trip, about 5 min sooner: ${BLUE}.`);
  assert.equal(switchSaid({ kind: "switch", label: RIDE, savedS: null }), `Your trip is no longer running as planned. Changed to: ${RIDE}.`);
  assert.equal(lateSaid(NOW, () => "8:42 am"), "Delays on the way: now arriving about 8:42 am.");
});
