import { test } from "node:test";
import assert from "node:assert/strict";
import { stressSegments } from "./stressBar.ts";

const sample = { "1": 1800, "2": 0, "3": 2630, "4": 1040, unknown: 10 };

test("fractions sum to one and follow the metres", () => {
  const segments = stressSegments(sample);
  const total = segments.reduce((sum, s) => sum + s.fraction, 0);
  assert.ok(Math.abs(total - 1) < 1e-9, `fractions sum to ${total}`);
  for (const s of segments) {
    assert.ok(Math.abs(s.fraction - s.metres / 5480) < 1e-9, s.key);
  }
});

test("rounded percentages always add up to one hundred", () => {
  const awkward = [
    { "1": 1, "2": 1, "3": 1, "4": 0, unknown: 0 },
    { "1": 333, "2": 333, "3": 334, "4": 0, unknown: 0 },
    { "1": 0.4, "2": 0.4, "3": 0.2, "4": 99, unknown: 0.1 },
    { "1": 255, "2": 255, "3": 490, "4": 0, unknown: 0 },
    sample,
  ];
  for (const stress of awkward) {
    const sum = stressSegments(stress).reduce((acc, s) => acc + s.percent, 0);
    assert.equal(sum, 100, JSON.stringify(stress));
  }
});

test("every tier and the unrated remainder are present, in tier order", () => {
  const keys = stressSegments(sample).map((s) => s.key);
  assert.deepEqual(keys, ["1", "2", "3", "4", "5", "unknown"]);
});

test("each segment carries a label, so the bar does not rely on colour", () => {
  for (const s of stressSegments(sample)) {
    assert.ok(s.label.length > 0 && s.short.length > 0, s.key);
    assert.match(s.color, /^#[0-9a-f]{6}$/i);
  }
});

test("a route with no metres gives no segments rather than NaN", () => {
  assert.deepEqual(stressSegments({ "1": 0, "2": 0, "3": 0, "4": 0, unknown: 0 }), []);
});

test("missing, negative or non-numeric values count as zero", () => {
  const segments = stressSegments({ "1": 100, "2": -50, "3": Number.NaN } as never);
  const byKey = Object.fromEntries(segments.map((s) => [s.key, s]));
  assert.equal(byKey["1"].fraction, 1);
  assert.equal(byKey["2"].metres, 0);
  assert.equal(byKey["3"].metres, 0);
  assert.equal(byKey["4"].metres, 0);
});

test("the tier colours are the overlay's own", async () => {
  const { currentTiers } = await import("../stressStyle.js");
  const segments = stressSegments(sample);
  for (const tier of currentTiers()) {
    const segment = segments.find((s) => s.key === String(tier.tier));
    assert.equal(segment?.color, tier.color);
  }
});

test("each percent is its own share rounded, and an empty tier reads 0%", () => {
  const cases = [
    sample,
    { "1": 255, "2": 255, "3": 490, "4": 0, unknown: 0 },
    { "1": 1, "2": 1, "3": 1, "4": 0, unknown: 0 },
    { "1": 994, "2": 3, "3": 3, "4": 0, unknown: 0 },
  ];
  for (const stress of cases) {
    for (const s of stressSegments(stress)) {
      assert.ok(Math.abs(s.percent - s.fraction * 100) < 1, `${JSON.stringify(stress)} ${s.key}`);
      if (s.metres === 0) assert.equal(s.percent, 0, `${JSON.stringify(stress)} ${s.key}`);
    }
  }
});
