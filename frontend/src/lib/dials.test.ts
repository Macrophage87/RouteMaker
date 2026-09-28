import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import {
  TRAFFIC_TOLERANT_MAX,
  warnsTrafficTolerant,
  offersAssist,
  stressMax,
  HILLS_MAX,
  HILLS_MIN,
  STARTS,
  STRESS_MAX,
  STRESS_MIN,
  dialFields,
  fitDials,
  hillsMax,
  hillsWords,
  startDials,
  stressWords,
} from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";

test("every ride type has a start for both sliders, inside their ranges", () => {
  for (const preset of PRESETS) {
    const start = startDials(preset.id);
    assert.ok(start.stress >= STRESS_MIN && start.stress <= STRESS_MAX, preset.id);
    assert.ok(start.hills >= HILLS_MIN && start.hills <= hillsMax(preset.id), preset.id);
  }
});

test("the starts say what the owner said", () => {
  // Default more stress-averse than Group Ride, Mass Ride at the direct end,
  // Default's hills at the detent (fastest), Cargo well toward avoid.
  assert.ok(STARTS.default.stress > STARTS["group-ride"].stress);
  assert.equal(STARTS["mass-ride"].stress, STRESS_MIN);
  assert.equal(STARTS.default.hills, 0);
  assert.ok(STARTS.cargo.hills < STARTS.default.hills);
});

test("carrying cargo starts where Default does, carrying people at the top", () => {
  const cargo = startDials("cargo", "cargo");
  const people = startDials("cargo", "people");
  assert.equal(cargo.stress, STARTS.default.stress);
  assert.equal(people.stress, STRESS_MAX);
  assert.equal(people.hills, cargo.hills);
  assert.equal(startDials("cargo").carrying, "cargo");
  assert.equal(startDials("default", "people").carrying, null);
});

test("Mass Ride's hills slider stops at the fastest time", () => {
  assert.equal(hillsMax("mass-ride"), 0);
  assert.equal(hillsMax("default"), HILLS_MAX);
  assert.equal(fitDials("mass-ride", { hills: 80 }).hills, 0);
});

test("a link's dials are clamped to what the API takes", () => {
  assert.deepEqual(fitDials("default", { stress: 250, hills: -400 }), {
    stress: STRESS_MAX,
    hills: HILLS_MIN,
    when: null,
    carrying: null,
    assist: false,
  });
  assert.equal(fitDials("default", { stress: 42.6 }).stress, 43);
  assert.equal(fitDials("default", { stress: Number.NaN }).stress, STARTS.default.stress);
});

test("the sliders travel in the link and come back", () => {
  const dials = { stress: 30, hills: 60, when: "weekday_rush" as const, carrying: null, assist: false };
  const plan = decodePlan(encodePlan([[-77.04, 38.9], [-77.0, 38.89]], "default", dials));
  assert.deepEqual(plan.dials, dials);
  const cargo = decodePlan(encodePlan([], "cargo", startDials("cargo", "people")));
  assert.equal(cargo.dials.carrying, "people");
  assert.equal(cargo.dials.stress, STARTS.cargo.carrying?.people);
});

test("a link without dials opens at the ride type's start, and junk is ignored", () => {
  assert.deepEqual(decodePlan("#preset=group-ride").dials, startDials("group-ride"));
  const junk = decodePlan("#preset=default&stress=abc&hills=&when=someday&carrying=goats");
  assert.deepEqual(junk.dials, startDials("default"));
});

test("the request carries the dials, and the ride time only when chosen", () => {
  assert.deepEqual(dialFields(startDials("default")), { stress: STARTS.default.stress, hills: 0 });
  assert.deepEqual(dialFields({ stress: 10, hills: -20, when: "weekend", carrying: "people", assist: true }), {
    stress: 10,
    hills: -20,
    when: "weekend",
    carrying: "people",
    assist: true,
  });
});

test("the words name both ends and the middle of each slider", () => {
  const ends = [stressWords(STRESS_MIN), stressWords(50), stressWords(STRESS_MAX)];
  assert.equal(new Set(ends).size, 3);
  const hills = [hillsWords(HILLS_MIN), hillsWords(0), hillsWords(HILLS_MAX)];
  assert.equal(new Set(hills).size, 3);
  assert.match(hillsWords(0), /fastest/i);
});

test("Mass Ride's traffic slider is locked at the most direct roadway", () => {
  assert.equal(stressMax("mass-ride"), 0);
  assert.equal(fitDials("mass-ride", { stress: 60 }).stress, 0);
  for (const preset of PRESETS) if (preset.id !== "mass-ride") assert.equal(stressMax(preset.id), STRESS_MAX, preset.id);
});

test("Default starts at the owner's 90", () => {
  assert.equal(STARTS.default.stress, 90);
});

test("electric assist is Cargo Bike's alone, travels in the link and keeps the hills start", () => {
  assert.ok(offersAssist("cargo"));
  assert.equal(offersAssist("ebike"), false);
  assert.equal(startDials("default", null, null, true).assist, false);
  const assisted = startDials("cargo", "people", null, true);
  assert.equal(assisted.assist, true);
  assert.equal(assisted.hills, startDials("cargo", "people").hills);
  assert.equal(decodePlan(encodePlan([], "cargo", assisted)).dials.assist, true);
  assert.equal(decodePlan(encodePlan([], "cargo", startDials("cargo"))).dials.assist, false);
  assert.equal(decodePlan("#preset=default&assist=1").dials.assist, false);
  assert.equal(decodePlan("#preset=cargo&assist=0").dials.assist, false);
  assert.equal(decodePlan("#preset=cargo&assist=1").dials.assist, true);
  assert.equal(dialFields(startDials("cargo")).assist, undefined);
});

test("the bottom of the traffic slider is traffic tolerant and warns", () => {
  assert.equal(stressWords(0), "Traffic tolerant");
  assert.equal(stressWords(TRAFFIC_TOLERANT_MAX), "Traffic tolerant");
  assert.notEqual(stressWords(TRAFFIC_TOLERANT_MAX + 5), "Traffic tolerant");
  assert.ok(warnsTrafficTolerant("default", 0));
  assert.ok(warnsTrafficTolerant("fast", STARTS.fast.stress));
  assert.ok(!warnsTrafficTolerant("default", 15));
  // Mass Ride's slider is locked at 0 and says why; it does not warn.
  assert.ok(!warnsTrafficTolerant("mass-ride", 0));
});

