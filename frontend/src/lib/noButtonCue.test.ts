// The owner, 2026-11-10: "Remove the 'push button' to cross. It generally only gets the ones that are on timers."
// Before, a route's light_buttons put "Light may need a button press" on Ride's card and "Button for the light." in
// its voice. After, Ride says nothing about a button, even from an older API that still sends light_buttons.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { DescriptionEntry, RouteResponse } from "./api.ts";
import type { LonLat } from "./geo.ts";
import { cueSpoken, rideModel } from "./navigate.ts";
import { routeCues } from "./course.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);

function at(east: number, north: number): LonLat {
  return [-77.05 + east / KX, LAT + north / M_PER_DEG];
}

function stretch(from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: null, tier: 1, facility: null, turn: null, text, ...extra };
}

/** East 1,000 m on A Street, then left 1,000 m on B Street at a signal, with an old API's button signals on it. */
function route(): RouteResponse {
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
    // One at the turn, one on a stretch with nothing else near: before, a cue of its own.
    light_buttons: [
      { at_m: 1000, lon: -77.05, lat: LAT },
      { at_m: 500, lon: -77.05, lat: LAT },
    ],
  } as RouteResponse;
}

test("no button note: neither the card nor the voice mentions a button, and no cue of its own is made", () => {
  const model = rideModel(route());
  assert.deepEqual(
    model.cues.map((cue) => cue.kind),
    ["turn", "end"],
  );
  for (const cue of model.cues) {
    assert.ok(!/button/i.test(cue.text), cue.text);
    for (const phase of ["advance", "prepare"] as const) assert.ok(!/button/i.test(cueSpoken(cue, phase, 300)), cueSpoken(cue, phase, 300));
  }
  assert.ok(routeCues(route()).every((cue) => !/button/i.test(cue.text)));
});

test("no button note: the phrases are gone from every language and from Ride", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const i18n = join(here, "..", "i18n");
  for (const name of readdirSync(i18n).filter((f) => f.endsWith(".ts"))) {
    const text = readFileSync(join(i18n, name), "utf8");
    assert.ok(!text.includes("Light may need a button press") && !text.includes("Button for the light."), name);
  }
  assert.ok(!readFileSync(join(here, "navigate.ts"), "utf8").includes("light_buttons"));
});
