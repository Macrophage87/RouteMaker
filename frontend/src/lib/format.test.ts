import { test } from "node:test";
import assert from "node:assert/strict";
import { formatClimb, formatDistance, formatDuration, formatSeconds } from "./format.ts";

test("distance shows both kilometres and miles", () => {
  const text = formatDistance(5480);
  assert.match(text, /5\.5 km/);
  assert.match(text, /3\.4 mi/);
});

test("duration reads as minutes, then hours and minutes", () => {
  assert.match(formatDuration(1296), /^22 min$/);
  assert.match(formatDuration(3900), /^1 h 05 min$/);
  assert.match(formatDuration(20), /^1 min$/);
  assert.match(formatDuration(5400), /^1 h 30 min$/);
  assert.match(formatDuration(3599), /^1 h 00 min$/);
});

test("climb shows metres and feet, rounded", () => {
  const text = formatClimb(31.3);
  assert.match(text, /31 m/);
  assert.match(text, /103 ft/);
  assert.match(formatClimb(0), /^0 m \(0 ft\)$/);
});

test("nonsense in gives a dash, not NaN", () => {
  for (const f of [formatDistance, formatDuration, formatClimb]) {
    assert.equal(f(Number.NaN), "–");
    assert.equal(f(-1), "–");
  }
});

test("a count of seconds is singular at one and carries its number", () => {
  assert.doesNotMatch(formatSeconds(1), /seconds/);
  assert.match(formatSeconds(1), /^1 \S+$/);
  for (const n of [2, 5, 60]) {
    assert.match(formatSeconds(n), new RegExp(`^${n} `));
    assert.notEqual(formatSeconds(n).replace(String(n), ""), formatSeconds(1).replace("1", ""), `${n}`);
  }
});
