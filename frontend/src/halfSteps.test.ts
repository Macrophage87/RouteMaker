// Half steps (OWNER-DECISIONS 441i-441v, 458, 458a, 458b, 461a; 2026-10-30/31): from street level a half step's
// own colours, or in the colour-blind-friendly palette the map's dash and the outline where a dash is too close
// to its line; and the editor's words for a half step.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  HALF_DASHED,
  HALF_OUTLINES,
  HALF_PALETTES,
  HALF_OUTLINE_MIN_CONTRAST,
  HALF_OUTLINE_PX,
  HALF_STEP_DASH,
  HALF_STEP_MIN_ZOOM,
  HALF_STEP_TOP_DASH,
  PALETTES,
  SOLID_DASH,
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

test("in the colour-blind-friendly palette each half step's dash is the next level's base colour at the lower level's width (441u, 458)", () => {
  for (const palette of PALETTE_NAMES.filter((p) => HALF_DASHED.has(p))) {
    for (const strong of [false, true]) {
      const tiers = tiersFor(palette, strong) as Tier[];
      for (let tier = 1; tier <= 4; tier++) {
        const half = halfStep(tier, tiers);
        const lower = tiers.find((t) => t.tier === tier)!;
        const upper = tiers.find((t) => t.tier === tier + 1)!;
        assert.equal(half.solid, false);
        assert.equal(half.step, tier + 0.5);
        assert.equal(half.color, upper.color, `${palette} ${tier}.5's dash`);
        assert.equal(half.line, lower.color);
        assert.equal(half.width, lower.width);
        assert.deepEqual(half.dash, tier === 4 ? HALF_STEP_TOP_DASH : HALF_STEP_DASH, "4.5 takes Avoid's dash-dot (441s)");
      }
      assert.equal(halfStep(5, tiers), null, "no step above Avoid");
    }
  }
});

test("in the other palettes each half step has its own line, edge and ring, over its lower level's width and pattern (2026-10-30, 2026-10-31)", () => {
  const solid = PALETTE_NAMES.filter((p) => !HALF_DASHED.has(p));
  assert.deepEqual(solid.sort(), ["blended", "twotone"]);
  for (const palette of solid) {
    const tiers = tiersFor(palette) as (Tier & { dash: number[] | null; casingExtra: number })[];
    for (let tier = 1; tier <= 4; tier++) {
      const half = halfStep(tier, tiers);
      const lower = tiers.find((t) => t.tier === tier)!;
      const own = (HALF_PALETTES as Record<string, Record<number, { color: string; casing: string; ring?: string }>>)[palette][tier];
      assert.equal(half.solid, true);
      assert.equal(half.color, own.color);
      assert.equal(half.outline, own.casing, "its edge is drawn as the outline layer");
      assert.equal(half.ring, own.ring ?? null);
      assert.equal(half.width, lower.width);
      assert.equal(half.outlineWidth, lower.width + lower.casingExtra);
      assert.deepEqual(half.dash, lower.dash ?? SOLID_DASH, `${palette} ${tier}.5 keeps its level's pattern (441v)`);
      assert.notEqual(half.color, lower.color);
    }
  }
  // The owner's reading of the default: today's orange is 3.5, 4.5 a dark red.
  assert.equal(halfStep(3, tiersFor("twotone")).color, "#f28c28");
  assert.equal(halfStep(4, tiersFor("twotone")).color, "#560a0e");
});

test("every half step's line is between its two levels: 3:1 from its own edge, or reported on the route (stressContrast.test.ts)", (t) => {
  for (const palette of PALETTE_NAMES.filter((p) => !HALF_DASHED.has(p))) {
    for (let tier = 1; tier <= 4; tier++) {
      const half = halfStep(tier, tiersFor(palette));
      t.diagnostic(`${palette} ${tier}.5 ${half.color} on ${half.outline}: ${contrastRatio(half.color, half.outline).toFixed(2)}:1`);
    }
  }
  // Only the default's 3.5 (today's LTS 4 look, the two-tone reading) is under 3:1 on its edge, inside its ring.
  const under = PALETTE_NAMES.filter((p) => !HALF_DASHED.has(p)).flatMap((palette) =>
    [1, 2, 3, 4].filter((tier) => contrastRatio(halfStep(tier, tiersFor(palette)).color, halfStep(tier, tiersFor(palette)).outline) < 3).map((tier) => `${palette} ${tier}.5`),
  );
  assert.deepEqual(under, ["twotone 3.5"]);
  assert.equal(halfStep(3, tiersFor("twotone")).ring, "#1c1917");
});

test("458b: the outlined dash is the colour-blind palette's 4.5", () => {
  assert.equal(halfStep(4, tiersFor("cvd")).outline, "#ffffff");
  assert.equal(halfStep(3, tiersFor("cvd")).outline, null);
});

test("every outline is at least 3:1 from both its dash and its line (458b)", () => {
  let checked = 0;
  for (const palette of PALETTE_NAMES.filter((p) => HALF_DASHED.has(p))) {
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
  assert.ok(checked >= 1);
});

test("the half-step layers start at street level: a dash and its outline a pixel wider each side, or a half step's own line and edge", () => {
  const cvd = halfStepLayers("s", undefined, tiersFor("cvd")) as Layer[];
  assert.equal(cvd.length, 8, "an outline and a line for each of 1.5 to 4.5 (their rings are halfRingLayers, under the rails)");
  for (const layer of cvd) assert.equal(layer.minzoom, HALF_STEP_MIN_ZOOM);
  const outline = cvd.find((l) => l.id === "stress-half-outline-4")!;
  const dash = cvd.find((l) => l.id === "stress-half-4")!;
  const width = dash.paint["line-width"] as number;
  assert.equal(outline.paint["line-color"], "#ffffff");
  assert.equal(outline.paint["line-width"], width + 2 * HALF_OUTLINE_PX);
  assert.deepEqual(outline.paint["line-dasharray"], scaledDash(HALF_STEP_TOP_DASH, width, width + 2 * HALF_OUTLINE_PX));
  const plain = cvd.find((l) => l.id === "stress-half-outline-2")!;
  assert.equal(plain.paint["line-color"], "rgba(0, 0, 0, 0)", "no outline where none is needed");

  // The default: the same layers, a half step's own colours, transparent on an unpaved way (its level's brown or grey shows).
  const twotone = halfStepLayers("s", undefined, tiersFor("twotone")) as Layer[];
  assert.deepEqual(twotone.map((l) => l.id), cvd.map((l) => l.id), "a palette flip needs no new layer");
  const edge = twotone.find((l) => l.id === "stress-half-outline-3")!;
  const line = twotone.find((l) => l.id === "stress-half-3")!;
  const lts3 = (tiersFor("twotone") as (Tier & { dash: number[]; casingExtra: number })[])[2];
  const unpaved = ["==", ["get", "unpaved"], true];
  assert.deepEqual(edge.paint["line-color"], ["case", unpaved, "rgba(0, 0, 0, 0)", "#c81e1e"]);
  assert.equal(edge.paint["line-width"], lts3.width + lts3.casingExtra);
  assert.deepEqual(edge.paint["line-dasharray"], SOLID_DASH);
  assert.deepEqual(line.paint["line-color"], ["case", unpaved, "rgba(0, 0, 0, 0)", "#f28c28"]);
  assert.equal(line.paint["line-width"], lts3.width);
  assert.deepEqual(line.paint["line-dasharray"], lts3.dash);
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
