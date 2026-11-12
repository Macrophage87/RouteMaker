// The cue bench (lib/cueBench.ts): every fixture's transcript and shared cue rows are as kept, and the rules catch what
// they are for. A failing "as kept" test means a change moved a cue: run `node scripts/cueBench.ts --update` and read
// the diff of fixtures/cues/transcripts/ and expected/ (it goes in the pull request).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { benchRun, bendAt, fixtureTranscript, moved, rules, seeded, sharedRows, type CueFixture } from "./cueBench.ts";
import { rideModel } from "./navigate.ts";

const dir = new URL("../../../fixtures/cues/", import.meta.url);
const names = readdirSync(dir)
  .filter((f) => f.endsWith(".json") && f !== "trips.json")
  .map((f) => f.slice(0, -5))
  .sort();
const fixture = (name: string): CueFixture => JSON.parse(readFileSync(new URL(`${name}.json`, dir), "utf8"));

test("there are fixtures, made-up trips only", () => {
  assert.ok(names.length >= 10);
  for (const name of names) {
    const f = fixture(name);
    assert.deepEqual(Object.keys(f).sort(), ["about", "name", "route"]);
    assert.ok(f.route.geometry.coordinates.length > 1, name);
  }
});

for (const name of names) {
  test(`${name}: Ride's transcript and the shared cue rows are as kept`, () => {
    const f = fixture(name);
    const { text } = fixtureTranscript(f);
    const kept = readFileSync(new URL(`transcripts/${name}.txt`, dir), "utf8");
    if (text !== kept) {
      const a = kept.split("\n");
      const b = text.split("\n");
      const at = a.findIndex((line, i) => line !== b[i]);
      assert.fail(`${name}: the transcript changed from line ${at + 1}:\n  kept: ${a[at]}\n  now:  ${b[at]}\nRun node scripts/cueBench.ts --update and read the diff.`);
    }
    const rows = JSON.parse(readFileSync(new URL(`expected/${name}.json`, dir), "utf8"));
    assert.deepEqual(sharedRows(f), rows);
  });
}

test("the same ride gives the same transcript", () => {
  const f = fixture(names[0]);
  assert.equal(fixtureTranscript(f).text, fixtureTranscript(f).text);
  const a = seeded(7);
  const b = seeded(7);
  for (let i = 0; i < 5; i++) assert.equal(a(), b());
});

test("a bend's sign: right is plus", () => {
  const start: [number, number] = [-77.03, 38.9];
  const corner = moved(start, 0, 200);
  const right = moved(corner, 90, 200);
  const left = moved(corner, 270, 200);
  const line = (end: [number, number]) => rideModel({ geometry: { type: "LineString", coordinates: [start, corner, end] }, distance_m: 400, description: [] } as never);
  assert.ok((bendAt(line(right), 200) ?? 0) > 80);
  assert.ok((bendAt(line(left), 200) ?? 0) < -80);
});

test("a turn's arrow on the wrong side is found", () => {
  const f = fixture("dupont-15th-s-st");
  const flipped: CueFixture = structuredClone(f);
  const entry = flipped.route.description.find((e) => e.turn?.movement === "left")!;
  entry.turn!.movement = "right";
  const run = benchRun(flipped, 12);
  assert.ok(run.findings.some((x) => x.rule === "side"), JSON.stringify(run.findings));
  assert.deepEqual(benchRun(f, 12).findings.filter((x) => x.rule === "side"), []);
});

test("a turn never said is found", () => {
  const run = benchRun(fixture("dupont-15th-s-st"), 12);
  const turn = run.model.cues.find((c) => c.kind === "turn")!;
  const quiet = run.heard.filter((h) => h.event.cue?.index !== turn.index);
  assert.ok(rules(run.model, quiet, 12 * 0.44704).some((x) => x.rule === "missing" && x.cue === turn.index));
});

test("a sentence cut off by another cue's is found; a turn's own 'now' cutting its warning is not", () => {
  const run = benchRun(fixture("capitol-hill-stop"), 18);
  const cut = run.findings.filter((x) => x.rule === "cut");
  assert.ok(cut.length >= 1);
  for (const x of cut) assert.match(x.words, /by #\d+'s|by off-route|by another/);
});

test("a missed turn is noticed: off route is said", () => {
  const run = benchRun(fixture("dupont-15th-s-st"), 12, "missed-turn");
  assert.ok(run.heard.some((h) => h.event.kind === "off-route"));
});

test("weak GPS is said once while it lasts", () => {
  const run = benchRun(fixture("rural-poolesville"), 12, "weak-gps");
  assert.equal(run.notes.length, 1);
});
