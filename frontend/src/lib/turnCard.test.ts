// The lock screen's live turn card (lib/turnCard.ts): its words at a place on a made-up route.
import { test } from "node:test";
import assert from "node:assert/strict";
import { rideModel, type LonLat } from "./navigate.ts";
import { cardAtM, noteCard, turnCard } from "./turnCard.ts";
import { cardDistance } from "./format.ts";
import { setUnitsForTest } from "./units.ts";
import type { DescriptionEntry, RouteResponse } from "./api.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
const at = (east: number, north: number): LonLat => [-77.05 + east / KX, LAT + north / M_PER_DEG];

function stretch(from: number, to: number, text: string, extra: Partial<DescriptionEntry> = {}): DescriptionEntry {
  return { kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: null, tier: 1, facility: null, turn: null, text, ...extra };
}

/** East 1,000 m on A Street, left (north) 1,000 m on B Street, right (east) 1,000 m on D Street. */
function zRoute(): RouteResponse {
  return {
    preset: "standard",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [at(0, 0), at(1000, 0), at(1000, 1000), at(2000, 1000)] },
    distance_m: 3000,
    duration_s: 600,
    climb_m: 0,
    descent_m: 0,
    stress_m: {} as RouteResponse["stress_m"],
    attribution: [],
    leg_ends: [3],
    description: [
      stretch(0, 1000, "0.0 to 0.6 mi (0.0 to 1.0 km): A Street, low stress (LTS 1).", { street: "A Street" }),
      stretch(1000, 2000, "0.6 to 1.2 mi (1.0 to 2.0 km): Left onto B Street, low stress (LTS 1).", {
        street: "B Street",
        turn: { movement: "left", onto: "B Street", control: null, severity: null },
      }),
      stretch(2000, 3000, "1.2 to 1.9 mi (2.0 to 3.0 km): Right onto D Street, low stress (LTS 1).", {
        street: "D Street",
        turn: { movement: "right", onto: "D Street", control: null, severity: null },
      }),
    ],
  } as RouteResponse;
}

test("the card: the distance and the turn big, the street, then the turn after it", () => {
  setUnitsForTest("us");
  const model = rideModel(zRoute());
  const card = turnCard(model, 850)!;
  assert.equal(card.arrow, "left");
  assert.match(card.title, /^500 ft · Left$/);
  const [street, after] = card.body.split("\n");
  assert.match(street, /B St/);
  assert.match(after, /^Then in 0\.6 mi · Right · D St/);
  assert.match(card.still, /^Left · B St/, "an older app's words: no distance, so never stale");
  // Counting down; past the turn, the next one leads.
  assert.match(turnCard(model, 900)!.title, /^350 ft · Left$/);
  const next = turnCard(model, 1100)!;
  assert.equal(next.arrow, "right");
  assert.match(next.title, /^0\.6 mi · Right$/);
  // Past the last turn: the end, with a flag.
  assert.equal(turnCard(model, 2100)!.arrow, "end");
  assert.equal(turnCard(model, null), null, "nothing before the first good fix");
  assert.equal(turnCard(model, 3000), null, "nothing left");
});

test("the card's distance: the rider's own unit alone, in steps that change every few seconds, not each fix", () => {
  setUnitsForTest("us");
  assert.equal(cardDistance(152), "500 ft");
  assert.equal(cardDistance(150), "500 ft", "492 ft to the nearest 50");
  assert.equal(cardDistance(30), "100 ft");
  assert.equal(cardDistance(0), "10 ft");
  assert.equal(cardDistance(1609), "1.0 mi");
  setUnitsForTest("metric");
  assert.equal(cardDistance(152), "150 m");
  assert.equal(cardDistance(1609), "1.6 km");
  setUnitsForTest("us");
});

test("a reckoning that ran past a turn keeps the turn on the card until a real fix passes it", () => {
  setUnitsForTest("us");
  const model = rideModel(zRoute());
  const turnAt = model.cues.find((c) => c.kind === "turn")!.atM;
  // Weak GPS: reckoned 100 m past the left turn while the last good fix is 100 m before it.
  const atM = cardAtM(model, turnAt - 100, turnAt + 100)!;
  assert.ok(atM < turnAt && atM >= turnAt - 100);
  assert.equal(turnCard(model, atM)?.arrow, "left");
  assert.equal(cardAtM(model, 500, undefined), 500, "no reckoning: the ride's own place");
  assert.equal(cardAtM(model, null, 700), null);
});

test("a note card says the sentence with no distance", () => {
  const card = noteCard("Off the planned route.");
  assert.equal(card.title, "Off the planned route.");
  assert.equal(card.still, "Off the planned route.");
  assert.equal(card.body, "");
});
