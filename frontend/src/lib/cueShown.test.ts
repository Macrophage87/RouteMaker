import assert from "node:assert/strict";
import test from "node:test";
import { cueParts, shortStreets } from "./cueShown.ts";

test("street words shortened after a name only", () => {
  assert.equal(shortStreets("Left onto R Street Northwest."), "Left onto R St NW.");
  assert.equal(shortStreets("Continue onto Florida Avenue Northeast"), "Continue onto Florida Ave NE");
  assert.equal(shortStreets("Right onto 16th Street Northwest."), "Right onto 16th St NW.");
  assert.equal(shortStreets("Stay in the bike lane, busy road (LTS 3)."), "Stay in the bike lane, busy road (LTS 3).");
  // Only where a word ends the name (review): a quadrant or a type mid-name stays whole.
  assert.equal(shortStreets("Right onto Northwest Branch Trail."), "Right onto Northwest Branch Trl.");
  assert.equal(shortStreets("Left onto Court House Road"), "Left onto Court House Rd");
  assert.equal(shortStreets("Around Dupont Circle Northwest, busy road."), "Around Dupont Cir NW, busy road.");
});

test("the cue splits at its first comma (the owner's screenshot, 2026-10-19)", () => {
  assert.deepEqual(cueParts("Continue onto Florida Avenue Northeast, no signal mapped (Higher stress junction), busy road (LTS 3)."), {
    head: "Continue onto Florida Ave NE",
    rest: "No signal mapped (Higher stress junction), busy road (LTS 3).",
  });
  assert.deepEqual(cueParts("Left onto R Street Northwest."), { head: "Left onto R St NW.", rest: "" });
});
