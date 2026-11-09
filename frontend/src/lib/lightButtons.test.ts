// A signal that may need a button press (the owner, 2026-11-08): the API's light_buttons noted on Ride's turn or
// crossing there, "Light may need a button press" on the card and "Button for the light." said, in every language.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { BUTTON_SAID, BUTTON_SHOWN, buttonBefore, buttonOnly, cueSpoken, nextAction, rideModel, whereAmI, whereAmIShown } from "./navigate.ts";
import type { RideState } from "./navigate.ts";
import { routeCues } from "./course.ts";
import { loadLanguage, setLanguageForTest } from "./i18n.ts";

await loadLanguage("es");

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);

function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

function stretch(from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: null, tier: 1, facility: null, turn: null, text, ...extra };
}

/** East 1,000 m on A Street, then left 1,000 m on B Street at a signal; buttons where asked. */
function route(buttons: number[] | undefined): RouteResponse {
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(500, 0), at(1000, 0), at(1000, 500), at(1000, 1000)] },
    distance_m: 2000,
    duration_s: 400,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [4],
    description: [
      stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): A Street, low stress (LTS 1).", { street: "A Street" }),
      stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Left onto B Street at a signal, low stress (LTS 1).", {
        street: "B Street",
        turn: { movement: "left", onto: "B Street", control: "signal", severity: null },
      }),
    ],
    ...(buttons ? { light_buttons: buttons.map((m) => ({ at_m: m, lon: -77.05, lat: LAT })) } : {}),
  } as RouteResponse;
}

test("before: a route with no light_buttons notes no button anywhere", () => {
  const model = rideModel(route(undefined));
  assert.ok(model.cues.every((cue) => !cue.button));
  const turn = model.cues.find((cue) => cue.kind === "turn");
  assert.ok(turn);
  assert.ok(!cueSpoken(turn, "advance", 300).includes("Button"));
});

test("after: the turn at a button signal says the note once, in its first warning only", () => {
  const model = rideModel(route([1005]));
  const turn = model.cues.find((cue) => cue.kind === "turn");
  assert.ok(turn?.button, "the turn 5 m from the signal carries it");
  assert.equal(model.cues.filter((cue) => cue.button).length, 1, "no cue of its own beside the turn");
  assert.ok(!buttonOnly(turn));
  assert.ok(cueSpoken(turn, "advance", 300).endsWith(` ${BUTTON_SAID}`));
  assert.ok(!cueSpoken(turn, "prepare", 60, false).includes(BUTTON_SAID), "not again in the later warnings");
});

test("after: a button signal with no cue near it has a short cue of its own", () => {
  const model = rideModel(route([1500]));
  const own = model.cues.find((cue) => cue.button);
  assert.ok(own);
  assert.equal(own.kind, "hazard");
  assert.ok(buttonOnly(own));
  assert.equal(own.text, BUTTON_SHOWN);
  assert.equal(cueSpoken(own, "advance", 300), "In 0.2 miles, button for the light.");
  // In order along the line, indices kept.
  model.cues.forEach((cue, i) => assert.equal(cue.index, i));
  assert.ok(model.cues.every((cue, i) => i === 0 || model.cues[i - 1].atM <= cue.atM));
});

test("the note's two strings are the owner's, and Spanish says them in Spanish", () => {
  assert.equal(BUTTON_SHOWN, "Light may need a button press");
  assert.equal(BUTTON_SAID, "Button for the light.");
  setLanguageForTest("es");
  try {
    const model = rideModel(route([1500]));
    const own = model.cues.find((cue) => cue.button);
    assert.ok(own);
    assert.equal(own.text, "Puede que el semáforo necesite que pulse el botón");
    assert.ok(cueSpoken(own, "advance", 300).includes("otón del semáforo."));
  } finally {
    setLanguageForTest("en");
  }
});

test("every Go and Ride catalog has both strings, flagged for native review", () => {
  const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "i18n");
  const catalogs = readdirSync(dir).filter((name) => name.endsWith(".ts") && !name.includes(".test."));
  assert.equal(catalogs.length, 20);
  for (const name of catalogs) {
    const text = readFileSync(join(dir, name), "utf8");
    for (const phrase of [BUTTON_SHOWN, BUTTON_SAID]) assert.ok(text.includes(`${JSON.stringify(phrase)}: "`), `${name}: ${phrase}`);
    assert.match(text, /button press \(the owner, 2026-11-08\)[^\n]*\n[^\n]*FLAGGED for review by a native speaker/, name);
  }
});

/** East 1,000 m, left 20 m, right 980 m: a jog of two turns 20 m apart. */
function jogRoute(buttons: number[]): RouteResponse {
  const base = route(buttons);
  return {
    ...base,
    geometry: { type: "LineString", coordinates: [at(0, 0), at(1000, 0), at(1000, 20), at(2000, 20)] },
    leg_ends: [3],
    description: [
      stretch(0, 1000, "A Street.", { street: "A Street" }),
      stretch(1000, 1020, "Left onto B Street.", { street: "B Street", turn: { movement: "left", onto: "B Street", control: null, severity: null } }),
      stretch(1020, 2000, "Right onto C Street.", { street: "C Street", turn: { movement: "right", onto: "C Street", control: "signal", severity: null } }),
    ],
  } as RouteResponse;
}

test("a button signal's own cue is no course point and no cue sheet row", () => {
  const cues = routeCues(route([1500]));
  assert.ok(cues.every((cue) => cue.name !== "Caution" && cue.text !== BUTTON_SHOWN), JSON.stringify(cues));
  // A turn that carries the note keeps its own row.
  assert.ok(routeCues(route([1005])).some((cue) => cue.kind === "turn"));
});

test("a button signal's own cue is not drawn as a warning", () => {
  const ride = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "RideMode.tsx"), "utf8");
  assert.match(ride, /cue\.kind === "hazard" && !cue\.buttonOnly\) \|\| cue\.kind === "walk"\) return "warn"/);
});

test("a button at a jog's later turn is said in the jog's first warning", () => {
  const model = rideModel(jogRoute([1020]));
  const [first, second] = model.cues.filter((cue) => cue.kind === "turn");
  assert.ok(second.joined, "the two turns are one jog");
  assert.ok(first.button, "the jog's first turn carries the note");
  assert.ok(cueSpoken(first, "advance", 300).endsWith(` ${BUTTON_SAID}`));
});

test("the note is found by its flag: a switch of language mid-ride never says it twice", () => {
  // Read in Spanish, said in English: the own cue's words are Spanish, but it is still the note alone.
  setLanguageForTest("es");
  let model;
  try {
    model = rideModel(route([1500]));
  } finally {
    setLanguageForTest("en");
  }
  const own = model.cues.find((cue) => cue.button);
  assert.ok(own && buttonOnly(own));
  assert.equal(cueSpoken(own, "advance", 300), "In 0.2 miles, button for the light.");
  assert.ok(!buttonOnly({ button: true }), "a turn with the note is not the note alone");
});

// The hunt, round 2, R2-2: a button signal 60 m before the left turn, gone straight through. Before, the card led with
// "Light may need a button press" and a straight arrow over the whole approach, and Where am I said "Next, in 450
// feet: light may need a button press 0.7 miles to the end." with no turn named.
test("a button's own note just before a turn leaves the card to the turn, the note under it; Where am I names the turn", () => {
  const model = rideModel(route([940]));
  const own = model.cues.find((cue) => buttonOnly(cue));
  assert.ok(own, "60 m from the turn: a cue of its own");
  const card = nextAction(model, 800);
  assert.equal(card?.kind, "turn");
  assert.equal(card?.street, "B Street");
  assert.ok(buttonBefore(model, 800, card), "the note shown under the turn");
  // Past the signal: no note under the turn.
  assert.ok(!buttonBefore(model, 960, nextAction(model, 960)));
  const state = { progressM: 800, off: false, arrived: false } as RideState;
  const said = whereAmI(model, state);
  assert.match(said, /Next, in [^:]+: left onto B Street/i);
  assert.ok(!said.includes(BUTTON_SHOWN.toLowerCase()), said);
  assert.match(whereAmIShown(model, state)[1] ?? "", /B St/);
  // Still said on its own.
  assert.equal(cueSpoken(own, "advance", 300), "In 0.2 miles, button for the light.");
});

test("a button's own note on a stretch with no turn near still leads the card, with no note under it", () => {
  const model = rideModel(route([500]));
  const card = nextAction(model, 300);
  assert.ok(card && buttonOnly(card));
  assert.ok(!buttonBefore(model, 300, card));
});

// The hunt, round 2, R2-3: a left then a right 90 m later, a button signal between them at neither turn.
function jog(buttons: number[]): RouteResponse {
  return {
    ...route(undefined),
    geometry: { type: "LineString", coordinates: [at(0, 0), at(1000, 0), at(1000, 90), at(2000, 90)] },
    distance_m: 2090,
    leg_ends: [3],
    description: [
      stretch(0, 1000, "A Street.", { street: "A Street" }),
      stretch(1000, 1090, "Left onto B Street.", { street: "B Street", turn: { movement: "left", onto: "B Street", control: null, severity: null } }),
      stretch(1090, 2090, "Right onto C Street.", { street: "C Street", turn: { movement: "right", onto: "C Street", control: null, severity: null } }),
    ],
    light_buttons: buttons.map((m) => ({ at_m: m, lon: -77.05, lat: LAT })),
  } as RouteResponse;
}

test("a button's own note between a jog's two turns does not part them (before: the right lost its then and its now)", () => {
  const plain = rideModel(jog([]));
  assert.ok(plain.cues.some((cue) => cue.joined));
  const model = rideModel(jog([1045]));
  assert.ok(model.cues.some((cue) => buttonOnly(cue)), "the note between them");
  const turns = model.cues.filter((cue) => cue.kind === "turn");
  assert.equal(turns.length, 2);
  assert.ok(turns[1].joined, "the right is the jog's");
  assert.match(turns[0].text, /then/i);
});
