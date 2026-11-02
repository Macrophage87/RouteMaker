// Turn by turn on foot (Stephen, 2026-11-02): a walk's turns, said as a ride's are, never "off route".
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import type { RideFix } from "./navigate.ts";
import { nextWalkTurn, walkModel, walkStart, walkStep, walkTurnLine, walkTurnTexts } from "./walkCues.ts";

const M_PER_DEG = 111_195;
const LAT = 38.9;
const KX = M_PER_DEG * Math.cos((LAT * Math.PI) / 180);
function at(east: number, north: number): LonLat {
  return [-77.0 + east / KX, LAT + north / M_PER_DEG];
}
let clock = 0;
function fix(point: LonLat, accuracyM = 5): RideFix {
  clock += 3000;
  return { point, accuracyM, speedMs: 1.4, headingDeg: null, at: clock };
}

// North 200 m on 1st St, left (west) 200 m on F St, then right (north) 100 m on 3rd St.
const PATH = {
  coordinates: [at(0, 0), at(0, 200), at(-200, 200), at(-200, 300)],
  turns: [
    { movement: "left" as const, street: "F St NE", point: at(0, 200) },
    { movement: "right" as const, street: "3rd St NE", point: at(-200, 200) },
    // A turn off the line (an older API's straight walk): not said.
    { movement: "left" as const, street: "Nowhere St", point: at(500, 500) },
  ],
  to: "Union Station",
};

test("a walk's turns are cues along its line, in order, with its end; one off the line is dropped", () => {
  const model = walkModel(PATH)!;
  assert.deepEqual(
    model.cues.map((c) => [c.kind, Math.round(c.atM), c.text]),
    [
      ["turn", 200, "Left onto F St NE."],
      ["turn", 400, "Right onto 3rd St NE."],
      ["end", 500, ""],
    ],
  );
  assert.equal(walkModel({ coordinates: [at(0, 0)], turns: [], to: null }), null);
  assert.deepEqual(walkTurnTexts(PATH.turns.slice(0, 2)), ["Left onto F St NE.", "Right onto 3rd St NE."]);
});

test("walking, the next turn is said ahead and at the corner, and the screen's line counts down to it", () => {
  const model = walkModel(PATH)!;
  let state = walkStart();
  const said: string[] = [];
  for (const north of [0, 40, 80, 120, 160, 185, 195]) {
    const out = walkStep(model, state, fix(at(0, north)), "full");
    state = out.state;
    said.push(...out.events.map((e) => e.spoken));
  }
  assert.ok(said.some((s) => /Left/.test(s) && /F St NE/.test(s)), said.join(" | "));
  assert.equal(nextWalkTurn(model, state)?.cue.street, "F St NE");
  const line = walkTurnLine(model, { ...state, progressM: 120 });
  assert.equal(line, "In 260 ft (80 m), left onto F St NE.");
});

test("a walker off the line is never told so: the cues take up again where they rejoin it", () => {
  const model = walkModel(PATH)!;
  let state = walkStart();
  state = walkStep(model, state, fix(at(0, 0)), "full").state;
  state = walkStep(model, state, fix(at(0, 50)), "full").state;
  // Across the street and through a plaza, 120 m off the line.
  for (const p of [at(120, 100), at(120, 140), at(120, 160)]) {
    const out = walkStep(model, state, fix(p), "full");
    assert.equal(out.state.off, false);
    assert.ok(out.events.every((e) => e.kind === "cue"));
    state = out.state;
  }
  const back = walkStep(model, state, fix(at(-100, 200)), "full");
  assert.equal(back.state.off, false);
  assert.ok((back.state.progressM ?? 0) > 250);
});

test("no turns, no line on the screen; and none before the first fix", () => {
  const model = walkModel({ ...PATH, turns: [] })!;
  assert.equal(walkTurnLine(model, walkStart()), null);
  assert.equal(walkTurnLine(walkModel(PATH), walkStart()), null);
});
