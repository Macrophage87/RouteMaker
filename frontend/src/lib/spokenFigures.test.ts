// The planner's figures as a screen reader says them: the units in words, US units first (the a11y review's a11y-6).
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatClimbSpoken, formatDistanceSpoken, formatDurationSpoken } from "./spokenFigures.ts";
import { formatClimb, formatDistance } from "./format.ts";

test("a distance in words: miles to a tenth, kilometers in brackets; feet below a tenth of a mile", () => {
  assert.equal(formatDistanceSpoken(19800), "12.3 miles (19.8 kilometers)");
  assert.equal(formatDistance(19800), "12.3 mi (19.8 km)", "the same figures as on screen");
  assert.equal(formatDistanceSpoken(1609.344), "1 mile (1.6 kilometers)");
  assert.equal(formatDistanceSpoken(150), "490 feet (150 meters)");
  assert.equal(formatDistanceSpoken(Number.NaN), formatDistance(Number.NaN));
});

test("a time in words: minutes, then hours and minutes, never 'h' or 'min'", () => {
  assert.equal(formatDurationSpoken(45 * 60), "45 minutes");
  assert.equal(formatDurationSpoken(20), "1 minute");
  assert.equal(formatDurationSpoken(3600), "1 hour");
  assert.equal(formatDurationSpoken(65 * 60), "1 hour 5 minutes");
  assert.equal(formatDurationSpoken(150 * 60), "2 hours 30 minutes");
});

test("a climb in words: feet first, meters in brackets, thousands separated", () => {
  assert.equal(formatClimbSpoken(104), "341 feet (104 meters)");
  assert.equal(formatClimb(104), "341 ft (104 m)", "the same figures as on screen");
  assert.equal(formatClimbSpoken(893), "2,930 feet (893 meters)");
});
