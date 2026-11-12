// The ride's cue log (lib/cueRecorder.ts): what became of each cue, with no place, street, words or time of day in it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { benchRun, type CueFixture } from "./cueBench.ts";
import { CUE_LOG_KEPT, CueRecorder } from "./cueRecorder.ts";
import type { Cue, RideEvent } from "./navigate.ts";

const fixture = (name: string): CueFixture => JSON.parse(readFileSync(new URL(`../../../fixtures/cues/${name}.json`, import.meta.url), "utf8"));

const cue = (index: number, atM: number): Cue => ({ index, kind: "turn", atM, text: "Left onto R Street Northwest.", movement: "left", street: "R Street Northwest", severity: null, tier: 2, stop: null });
const event = (c: Cue, phase: RideEvent["phase"], spoken: string): RideEvent => ({ kind: "cue", spoken, urgent: phase === "now", cue: c, phase });

test("a cue made, held, and dropped: by number and kind, metres to it and the fix, seconds since the start", () => {
  const log = new CueRecorder();
  log.start(1_000_000);
  const c = cue(4, 600);
  log.made(event(c, "advance", "In 500 feet, left onto R Street Northwest."), 455, 8, 1_003_000);
  log.voice("waits", "In 500 feet, left onto R Street Northwest.", 1_003_000);
  log.voice("dropped", "In 500 feet, left onto R Street Northwest.", 1_009_000);
  log.note("gps-weak", 1_010_000);
  const text = log.text();
  assert.match(text, /\+3 s {2}#4 left advance {2}made {2}to_m=145 {2}good/);
  assert.match(text, /\+9 s {2}#4 left advance {2}dropped/);
  assert.match(text, /\+10 s {2}gps-weak/);
  assert.doesNotMatch(text, /R Street|500 feet/);
});

test("nothing is kept before a ride starts, and a new ride starts afresh", () => {
  const log = new CueRecorder();
  log.note("gps-weak", 5);
  assert.equal(log.text(), "");
  log.start(0);
  log.note("gps-weak", 1000);
  log.start(2000);
  assert.equal(log.lines().length, 0);
});

test("the oldest lines go past CUE_LOG_KEPT", () => {
  const log = new CueRecorder();
  log.start(0);
  for (let i = 0; i < CUE_LOG_KEPT + 50; i++) log.note(`n${i}`, i * 1000);
  assert.equal(log.lines().length, CUE_LOG_KEPT);
  assert.equal(log.lines()[0].what, "n50");
});

test("a whole ride's log (the cue bench) names no street, no place and no sentence", () => {
  const f = fixture("near-northeast");
  const log = new CueRecorder();
  const run = benchRun(f, 18, "steady", "full", log);
  const text = log.text();
  assert.ok(log.lines().some((l) => l.what === "made"));
  assert.ok(log.lines().some((l) => l.what === "dropped"), "the bench's dropped warning before G Street is in the log");
  const streets = new Set(run.model.cues.map((c) => c.street).filter((s): s is string => !!s && s.length > 4));
  for (const s of streets) assert.ok(!text.includes(s), s);
  assert.doesNotMatch(text, /-?\d{1,3}\.\d{3,}/);
  assert.doesNotMatch(text, /feet|onto|Northeast/);
  // Every sentence the bench says was made appears as made in the log.
  assert.equal(log.lines().filter((l) => l.what === "made").length, run.heard.filter((h) => h.event.kind === "cue").length);
});
