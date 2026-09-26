import { test } from "node:test";
import assert from "node:assert/strict";
import { formatClimb, formatDistance, formatDuration } from "./format.ts";

test("distance shows both kilometres and miles", () => {
  const text = formatDistance(5480);
  assert.match(text, /5\.5 km/);
  assert.match(text, /3\.4 mi/);
});

test("duration reads as minutes, then hours and minutes", () => {
  assert.match(formatDuration(1296), /^22 min$/);
  assert.match(formatDuration(3900), /^1 h 05 min$/);
  assert.match(formatDuration(20), /^1 min$/);
});

test("climb shows metres and feet, rounded", () => {
  const text = formatClimb(31.3);
  assert.match(text, /31 m/);
  assert.match(text, /103 ft/);
});

test("nonsense in gives a dash, not NaN", () => {
  for (const f of [formatDistance, formatDuration, formatClimb]) {
    assert.equal(f(Number.NaN), "–");
    assert.equal(f(-1), "–");
  }
});
