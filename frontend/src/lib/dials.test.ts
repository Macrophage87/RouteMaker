import { test } from "node:test";
import assert from "node:assert/strict";
import { PRESETS } from "./presets.ts";
import {
  CALM_FAR_FROM,
  CALM_RATE_MAX,
  STRESS_DEFAULT_AT,
  STRESS_TODAYS_TOP,
  calmRate,
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
  WHENS,
  carries,
  isWhen,
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

test("carrying cargo starts where Default does, cargo with passengers at the old top", () => {
  const cargo = startDials("cargo", "cargo");
  const people = startDials("cargo", "people");
  assert.equal(cargo.stress, STARTS.default.stress);
  assert.equal(people.stress, STRESS_TODAYS_TOP);
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

test("Default starts at the owner's 90, which is 70 on the rescaled slider", () => {
  // OWNER-DECISIONS 163: the slider has room above its old top; the old 90 is 70.
  assert.equal(STARTS.default.stress, STRESS_DEFAULT_AT);
  assert.equal(STRESS_DEFAULT_AT, 70);
  assert.equal(STRESS_TODAYS_TOP, 80);
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

test("each word's range starts where the next one ends", () => {
  // Mutation review r1, FE13 and FE14: the boundaries, not only the ends.
  assert.equal(stressWords(TRAFFIC_TOLERANT_MAX + 1), "Direct, some busy streets");
  assert.equal(stressWords(29), "Direct, some busy streets");
  assert.equal(stressWords(30), "Balanced");
  assert.equal(stressWords(50), "Balanced");
  assert.equal(stressWords(51), "Prefers quiet streets and paths");
  assert.equal(stressWords(74), "Prefers quiet streets and paths");
  assert.equal(stressWords(75), "Low-stress, unless avoiding busy streets takes much longer");
  assert.equal(stressWords(STRESS_TODAYS_TOP), "Low-stress, unless avoiding busy streets takes much longer");
  // Past the old top the route goes out of its way (OWNER-DECISIONS 163, 164).
  assert.equal(stressWords(STRESS_TODAYS_TOP + 1), "Calm: will go well out of the way to avoid busy roads");
  assert.equal(stressWords(CALM_FAR_FROM - 1), "Calm: will go well out of the way to avoid busy roads");
  assert.equal(stressWords(CALM_FAR_FROM), "Calmest: detours many times the straight line to avoid busy roads");
  assert.equal(stressWords(STRESS_MAX - 1), "Calmest: detours many times the straight line to avoid busy roads");
  // The top is the least stressful route, aiming at the target distance (OWNER-DECISIONS 256, 271).
  assert.equal(stressWords(STRESS_MAX), "Calmest: the least stressful route, aiming at your target distance");
  assert.equal(hillsWords(-80), "Avoids hills");
  assert.equal(hillsWords(-79), "Gentler grades");
  assert.equal(hillsWords(-11), "Gentler grades");
  assert.equal(hillsWords(-10), "Fastest time");
  assert.equal(hillsWords(10), "Fastest time");
  assert.equal(hillsWords(11), "Some extra climbing");
  assert.equal(hillsWords(79), "Some extra climbing");
  assert.equal(hillsWords(80), "Seeks hills");
});

test("only Cargo Bike carries a load", () => {
  // FE17.
  for (const preset of PRESETS) assert.equal(carries(preset.id), preset.id === "cargo", preset.id);
});

test("the three ride times, and nothing else, are ride times", () => {
  // FE32: dropping weekday_offpeak from WHENS left every test green.
  assert.deepEqual(
    WHENS.map((w) => w.id),
    ["weekend", "weekday_rush", "weekday_offpeak"],
  );
  for (const when of ["weekend", "weekday_rush", "weekday_offpeak"]) assert.ok(isWhen(when), when);
  assert.equal(isWhen("now"), false);
  assert.equal(decodePlan("#preset=default&when=weekday_offpeak").dials.when, "weekday_offpeak");
});

test("an empty stress or hills in a link is the ride type's start, not 0", () => {
  // FE27: Number("") is 0, and 0 is traffic tolerant.
  for (const preset of ["default", "group-ride", "cargo"] as const) {
    const plan = decodePlan(`#preset=${preset}&stress=&hills=`);
    assert.equal(plan.dials.stress, STARTS[preset].carrying?.cargo ?? STARTS[preset].stress, preset);
    assert.equal(plan.dials.hills, STARTS[preset].hills, preset);
    assert.equal(decodePlan(`#preset=${preset}&stress=%20`).dials.stress, plan.dials.stress, preset);
  }
});

test("avoid gravel is off by default, travels in the link and the request, and survives a ride-type change", () => {
  // OWNER-DECISIONS 91, 92, 111.
  for (const preset of PRESETS) {
    assert.equal(startDials(preset.id).avoidGravel, undefined, preset.id);
    assert.equal(dialFields(startDials(preset.id)).avoid_gravel, undefined, preset.id);
  }
  const dials = { ...startDials("default"), avoidGravel: true };
  assert.equal(dialFields(dials).avoid_gravel, true);
  const back = decodePlan(encodePlan([], "default", dials)).dials;
  assert.equal(back.avoidGravel, true);
  assert.equal(decodePlan(encodePlan([], "default", startDials("default"))).dials.avoidGravel, undefined);
  assert.equal(decodePlan("#preset=cargo&avoidgravel=0").dials.avoidGravel, undefined);
  assert.equal(fitDials("gravel", { avoidGravel: true }).avoidGravel, true);
});

test("the calm rate is nothing up to the old top, then rises exponentially to its maximum", () => {
  // OWNER-DECISIONS 163: "a steep (exponential) curve above Default"; tests/test_calm_slider.py
  // holds these equal to the API's `calm_rate_for`.
  for (let stress = 0; stress <= STRESS_TODAYS_TOP; stress += 5) assert.equal(calmRate(stress), 0, String(stress));
  assert.equal(calmRate(STRESS_MAX), CALM_RATE_MAX);
  assert.equal(calmRate(150), CALM_RATE_MAX);
  const rates = [85, 90, 95, 100].map(calmRate);
  assert.deepEqual([...rates].sort((a, b) => a - b), rates);
  const steps = rates.slice(1).map((rate, i) => rate - rates[i]);
  assert.deepEqual([...steps].sort((a, b) => a - b), steps, "each step is longer than the last");
  assert.ok(calmRate(90) < CALM_RATE_MAX * 0.2, "not linear");
  assert.deepEqual([85, 90, 95, 100].map(calmRate), [0.585, 1.824, 4.447, 10]);
});

test("every ride type starts where it planned before the rescale, Trailmaxxing at the new top", () => {
  // OWNER-DECISIONS 194 (2026-10-02): "Trailmaxxing moves to 100 and
  // Cargo-carrying-people stays at 80".
  assert.deepEqual(
    Object.fromEntries(PRESETS.map((p) => [p.id, STARTS[p.id].stress])),
    { default: 70, trailmaxxing: 100, "group-ride": 40, "mass-ride": 0, "mountain-goat": 40, gravel: 40, fast: 10, cargo: 70, ebike: 70 },
  );
});
