// The whole named stretch at once (HALF-STEP-EDITOR phase 5; lib/stressEditor.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { extentOptions, saveTarget, savedSaid, undoneSaid, type EditorState, type EditorStep, type EditorStretch } from "./stressEditor.ts";

const STEPS: EditorStep[] = [
  { value: 2, words: "Fine for adults" },
  { value: 3, words: "For experienced cyclists" },
  { value: 3.5, words: "Stressful even for experienced cyclists" },
  { value: 4, words: "High stress: busy, fast traffic" },
];

const STRETCH: EditorStretch = {
  name: "Oak Street",
  osm_way_ids: [101, 102, 103],
  pieces: 3,
  length_m: 1609.344,
  capped: false,
  expected: "stretch-token",
};

const STATE = { osm_way_id: 102, expected: "piece-token", stretch: STRETCH } as unknown as EditorState;

test("the extent choice: the piece, or the stretch with its pieces and length in miles, kilometres in brackets", () => {
  assert.deepEqual(extentOptions("Oak Street", STRETCH), [
    { value: "piece", text: "This road piece: Oak Street" },
    { value: "stretch", text: "The whole named stretch of Oak Street: 3 pieces, 1.0 mi (1.6 km)" },
  ]);
});

test("a save sends the piece and its token, or every piece of the stretch and the stretch's token", () => {
  assert.deepEqual(saveTarget(STATE, "piece"), { osm_way_ids: [102], expected: "piece-token" });
  assert.deepEqual(saveTarget(STATE, "stretch"), { osm_way_ids: [101, 102, 103], expected: "stretch-token" });
  // No stretch (any more): the piece.
  assert.deepEqual(saveTarget({ ...STATE, stretch: null }, "stretch"), { osm_way_ids: [102], expected: "piece-token" });
});

test("the sentence after a stretch's save counts the pieces changed", () => {
  const ways = (changed: boolean[]) => changed.map((c, i) => ({ osm_way_id: 101 + i, step: 3.5, changed: c }));
  const result = (changed: boolean[]) => ({ edit_id: 1, ways: ways(changed), generation: 2, undo_until: "" });
  assert.match(savedSaid(result([true, true, true]), STEPS, false), /^Changed all 3 road pieces to LTS 3\.5, stressful even for experienced cyclists\./);
  assert.match(savedSaid(result([true, false, true]), STEPS, false), /^Changed 2 of the 3 road pieces to LTS 3\.5/);
  assert.match(savedSaid(result([false, false, false]), STEPS, false), /^Saved\. All 3 road pieces already had LTS 3\.5/);
  assert.match(savedSaid(result([false, false]), STEPS, true), /^Saved\. All 2 road pieces are already at least that level/);
});

test("the sentence after a stretch's undo", () => {
  const same = { edit_id: 2, generation: 3, undo_until: "", ways: [101, 102].map((w) => ({ osm_way_id: w, step: 3, changed: true })) };
  assert.equal(undoneSaid(same, STEPS), "Undone. All 2 road pieces are back to LTS 3, for experienced cyclists.");
  const mixed = { ...same, ways: [{ osm_way_id: 101, step: 3, changed: true }, { osm_way_id: 102, step: 2, changed: true }] };
  assert.equal(undoneSaid(mixed, STEPS), "Undone. All 2 road pieces are back to their earlier levels.");
});
