import assert from "node:assert/strict";
import test from "node:test";
import { cueParts, shortStreets } from "./cueShown.ts";
import { setLanguageForTest } from "./i18n.ts";

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

test("a quadrant before plain words shortens too (the owner's screenshot, 2026-10-27)", () => {
  assert.equal(shortStreets("Left onto S Street Northeast bike lane."), "Left onto S St NE bike lane.");
});

test("Spanish turn words shown shorter, the voice's sentence untouched (the owner, 2026-10-27)", () => {
  setLanguageForTest("es");
  try {
    assert.deepEqual(cueParts("Gire a la izquierda hacia S Street Northeast bike lane, luego inmediatamente gire a la derecha hacia S Street Northeast."), {
      head: "A la izquierda hacia S St NE bike lane",
      // "luego enseguida" shown as "luego" (the UI review, 2026-10-28), as "then immediately" is "then".
      rest: "Luego a la derecha hacia S St NE.",
    });
    assert.equal(cueParts("Gire ligeramente a la derecha ahora.").head, "Leve a la derecha ahora.");
    assert.equal(cueParts("Dé la vuelta en U.").head, "Vuelta en U.");
  } finally {
    setLanguageForTest("en");
  }
  assert.equal(cueParts("Gire a la izquierda.").head, "Gire a la izquierda.");
});
