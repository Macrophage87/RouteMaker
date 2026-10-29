// Detail behind an (i) as short bullets (P8): a note's own sentences, one to a bullet.
import { test } from "node:test";
import assert from "node:assert/strict";
import { sentences } from "./sentences.ts";
import { CALM_HOW, TARGET_HOW, calmNote } from "./dialsPanel.ts";

test("a note splits into its sentences, the wording kept", () => {
  assert.deepEqual(sentences("One. Two (LTS 4). Three?"), ["One.", "Two (LTS 4).", "Three?"]);
  assert.deepEqual(sentences("Only one, 1.25 times."), ["Only one, 1.25 times."]);
  assert.deepEqual(sentences(""), []);
});

test("an abbreviation's full stop does not end a sentence", () => {
  assert.deepEqual(sentences("Past St. Elmo Avenue. Then home."), ["Past St. Elmo Avenue.", "Then home."]);
  assert.deepEqual(sentences("Small places, e.g. a park. Next."), ["Small places, e.g. a park.", "Next."]);
});

test("the traffic slider's detail is short bullets, every word kept", () => {
  for (const text of [CALM_HOW, TARGET_HOW, calmNote(95) ?? ""]) {
    const bullets = sentences(text);
    assert.ok(bullets.length >= 2, text);
    assert.equal(bullets.join(" "), text);
    for (const bullet of bullets) assert.ok(bullet.split(/\s+/).length <= 40, bullet);
  }
});
