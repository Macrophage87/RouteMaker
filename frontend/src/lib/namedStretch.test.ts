// The whole named stretch at once (HALF-STEP-EDITOR phase 5; lib/stressEditor.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { UNNAMED_PATH, UNNAMED_ROAD } from "./federalStops.ts";
import { UNNAMED_PATH_TITLE, UNNAMED_ROAD_TITLE } from "./roadInfo.ts";
import {
  STRETCH_ALONE,
  STRETCH_FINDING,
  extentOptions,
  fetchStretch,
  mayHaveStretch,
  saveTarget,
  savedSaid,
  stretchSaid,
  undoneSaid,
  type EditorState,
  type EditorStep,
  type EditorStretch,
} from "./stressEditor.ts";

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

const STATE = { osm_way_id: 102, expected: "piece-token" } as unknown as EditorState;

test("the extent choice: the piece, or the stretch, its pieces and length in miles (kilometres in brackets) once found", () => {
  assert.deepEqual(extentOptions("Oak Street", null), [
    { value: "piece", text: "This road piece: Oak Street" },
    { value: "stretch", text: "The whole named stretch of Oak Street" },
  ]);
  assert.equal(extentOptions("Oak Street", STRETCH)[1].text, "The whole named stretch of Oak Street: 3 pieces, 1.0 mi (1.6 km)");
  assert.equal(mayHaveStretch("Oak Street"), true);
  assert.equal(mayHaveStretch("Unnamed road"), false);
  assert.equal(mayHaveStretch(UNNAMED_PATH_TITLE), false);
  assert.equal(mayHaveStretch("  "), false);
});

test("the unnamed titles are the route description's words, capitalised", () => {
  assert.equal(UNNAMED_ROAD_TITLE, UNNAMED_ROAD.charAt(0).toUpperCase() + UNNAMED_ROAD.slice(1));
  assert.equal(UNNAMED_PATH_TITLE, UNNAMED_PATH.charAt(0).toUpperCase() + UNNAMED_PATH.slice(1));
});

test("the choice's status line says what was found", () => {
  assert.equal(stretchSaid({ kind: "none" }), "");
  assert.equal(stretchSaid({ kind: "loading" }), STRETCH_FINDING);
  assert.equal(stretchSaid({ kind: "alone" }), STRETCH_ALONE);
  assert.equal(stretchSaid({ kind: "ready", stretch: STRETCH }), "The whole named stretch of Oak Street: 3 pieces, 1.0 mi (1.6 km).");
  assert.match(stretchSaid({ kind: "ready", stretch: { ...STRETCH, capped: true } }), /at most 40 pieces/);
});

test("a save sends the piece and its token, or every piece of the stretch and the stretch's token; nothing while it is found", () => {
  assert.deepEqual(saveTarget(STATE, "piece"), { osm_way_ids: [102], expected: "piece-token" });
  assert.deepEqual(saveTarget(STATE, "stretch", { kind: "ready", stretch: STRETCH }), { osm_way_ids: [101, 102, 103], expected: "stretch-token" });
  assert.equal(saveTarget(STATE, "stretch", { kind: "loading" }), null);
  assert.deepEqual(saveTarget(STATE, "stretch", { kind: "alone" }), { osm_way_ids: [102], expected: "piece-token" });
});

test("the stretch is asked for at its own address, and a lone piece answers alone", async () => {
  const asked: string[] = [];
  const reply = (body: unknown) =>
    (async (url: string) => {
      asked.push(url);
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }) as unknown as typeof fetch;
  assert.deepEqual(await fetchStretch("https://x.test", 102, undefined, reply({ stretch: STRETCH })), { kind: "ready", stretch: STRETCH });
  assert.deepEqual(await fetchStretch("https://x.test", 102, undefined, reply({ stretch: null })), { kind: "alone" });
  assert.deepEqual(asked, ["https://x.test/api/stress-edits/way/102/stretch", "https://x.test/api/stress-edits/way/102/stretch"]);
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
