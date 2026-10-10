// Half steps (OWNER-DECISIONS 441i-441v, 458, 458a, 458b, 461a): the map's dash from street level, the
// outline where a dash is too close to its line, and the editor's words for a half step.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  HALF_OUTLINES,
  HALF_OUTLINE_MIN_CONTRAST,
  HALF_OUTLINE_PX,
  HALF_STEP_DASH,
  HALF_STEP_MIN_ZOOM,
  HALF_STEP_TOP_DASH,
  PALETTES,
  contrastRatio,
  halfStep,
  halfStepLayers,
  scaledDash,
  tiersFor,
} from "./stressStyle.js";
import { levelPhrase, sliderHelp, sliderStep, stepLabel, stepValueText } from "./lib/stressEditor.ts";

const PALETTE_NAMES = Object.keys(PALETTES);
type Tier = { tier: number; color: string; width: number };
type Layer = { id: string; minzoom: number; filter: unknown; paint: Record<string, unknown> };

test("each half step's dash is the next level's base colour at the lower level's width (441u, 458)", () => {
  for (const palette of PALETTE_NAMES) {
    const tiers = tiersFor(palette) as Tier[];
    for (let tier = 1; tier <= 4; tier++) {
      const half = halfStep(tier, tiers);
      const lower = tiers.find((t) => t.tier === tier)!;
      const upper = tiers.find((t) => t.tier === tier + 1)!;
      assert.equal(half.step, tier + 0.5);
      assert.equal(half.color, upper.color, `${palette} ${tier}.5's dash`);
      assert.equal(half.line, lower.color);
      assert.equal(half.width, lower.width);
      assert.deepEqual(half.dash, tier === 4 ? HALF_STEP_TOP_DASH : HALF_STEP_DASH, "4.5 takes Avoid's dash-dot (441s)");
    }
    assert.equal(halfStep(5, tiers), null, "no step above Avoid");
  }
});

test("458b: the outlined dashes are the default palette's 3.5 and the colour-blind palette's 4.5", () => {
  assert.equal(halfStep(3, tiersFor("twotone")).outline, "#1c1917");
  assert.equal(halfStep(4, tiersFor("cvd")).outline, "#ffffff");
  assert.equal(halfStep(2, tiersFor("twotone")).outline, null);
});

test("every outline is at least 3:1 from both its dash and its line (458b)", () => {
  let checked = 0;
  for (const palette of PALETTE_NAMES) {
    const tiers = tiersFor(palette);
    for (let tier = 1; tier <= 4; tier++) {
      const half = halfStep(tier, tiers);
      if (!half.outline) continue;
      checked += 1;
      const fromDash = contrastRatio(half.outline, half.color);
      const fromLine = contrastRatio(half.outline, half.line);
      assert.ok(fromDash >= HALF_OUTLINE_MIN_CONTRAST, `${palette} ${tier}.5: outline ${fromDash.toFixed(2)}:1 from the dash`);
      assert.ok(fromLine >= HALF_OUTLINE_MIN_CONTRAST, `${palette} ${tier}.5: outline ${fromLine.toFixed(2)}:1 from the line`);
    }
  }
  const declared = Object.entries(HALF_OUTLINES as Record<string, Record<string, string>>)
    .filter(([palette]) => PALETTE_NAMES.includes(palette))
    .reduce((n, [, byTier]) => n + Object.keys(byTier).length, 0);
  assert.equal(checked, declared, "each declared outline is drawn on its palette");
  assert.ok(checked >= 2);
});

test("the half-step layers start at street level, the outline a pixel wider each side with its dash scaled", () => {
  const layers = halfStepLayers("s", undefined, tiersFor("twotone")) as Layer[];
  assert.equal(layers.length, 8);
  for (const layer of layers) assert.equal(layer.minzoom, HALF_STEP_MIN_ZOOM);
  const outline = layers.find((l) => l.id === "stress-half-outline-3")!;
  const dash = layers.find((l) => l.id === "stress-half-3")!;
  const width = dash.paint["line-width"] as number;
  assert.equal(outline.paint["line-color"], "#1c1917");
  assert.equal(outline.paint["line-width"], width + 2 * HALF_OUTLINE_PX);
  assert.deepEqual(outline.paint["line-dasharray"], scaledDash(HALF_STEP_DASH, width, width + 2 * HALF_OUTLINE_PX));
  const plain = layers.find((l) => l.id === "stress-half-outline-2")!;
  assert.equal(plain.paint["line-color"], "rgba(0, 0, 0, 0)", "no outline where none is needed");
});

test("a half step's dash shows only on a feature carrying its tier and the half", () => {
  const layer = (halfStepLayers("s", undefined, tiersFor("twotone")) as Layer[]).find((l) => l.id === "stress-half-2")!;
  const text = JSON.stringify(layer.filter);
  assert.ok(text.includes('["==",["get","tier"],2]'));
  assert.ok(text.includes('["==",["get","half"],true]'));
});

test("a scaled dash keeps its blocks where the narrower line's fall", () => {
  assert.deepEqual(scaledDash([1.5, 4.5], 4, 6), [1, 3]);
});

const STEPS = [
  { value: 1, words: "Comfortable for all ages" },
  { value: 2.5, words: "Fine for most confident adults" },
  { value: 4.5, words: "A very high-stress road" },
  { value: 5, words: "Avoid" },
];

test("the editor reads a half step as its number and words (441i, 441l)", () => {
  assert.equal(stepLabel(3), "3");
  assert.equal(stepLabel(3.5), "3.5");
  assert.equal(stepValueText(2.5, STEPS), "2.5, Fine for most confident adults");
  assert.equal(levelPhrase(4.5, STEPS), "LTS 4.5, a very high-stress road");
  assert.equal(levelPhrase(5, STEPS), "Avoid");
});

test("the slider moves by halves only where the road data can hold a half step", () => {
  assert.equal(sliderStep({ half_steps: true }), 0.5);
  assert.equal(sliderStep({ half_steps: false }), 1);
  assert.equal(sliderStep(null), 1);
  assert.match(sliderHelp(true), /half a step/);
  assert.doesNotMatch(sliderHelp(false), /half/);
});
