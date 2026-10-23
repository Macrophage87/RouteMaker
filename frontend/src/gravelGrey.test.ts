// Gravel grey (the owner, 2026-10-21: "Maybe make natural surface trails brown and gravel grey?"): an unpaved way the
// tiles do not call rough is drawn in the grey ramp, a natural surface in the brown one, with the same dashes and mark.
// The grey ramp is held to the brown ramp's rules (unpavedBrown.test.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIGHT } from "@protomaps/basemaps";
import { GRAVEL_PALETTES, MTB_TRAIL, PALETTES, contrastRatio, relativeLuminance, tiersFor } from "./stressStyle.js";
import { VISIONS, deltaE2000, lab, simulate } from "./testSupport/colourVision.ts";

type Tier = ReturnType<typeof tiersFor>[number];
const worst = (a: string, b: string) => Math.min(...VISIONS.map((v) => deltaE2000(simulate(a, v), simulate(b, v))));
const harshness = (dash: number[] | null, casing: string, line: string) =>
  dash ? (dash.filter((_, i) => i % 2 === 1).reduce((a, b) => a + b, 0) / dash.reduce((a, b) => a + b, 0)) * contrastRatio(casing, line) : 0;

const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|buildings|other|minor|link|major$|highway$)/;
const SURFACES: Record<string, string> = {};
for (const [key, value] of Object.entries(LIGHT)) {
  if (typeof value === "string" && SURFACE.test(key) && !key.includes("casing") && /^#[0-9a-f]{6}$/i.test(value)) SURFACES[key] = value.toLowerCase();
}

test("the grey ramp: light to dark, every step 1.5:1 or more darker and 10 CIEDE2000 or more apart under every vision, and grey", () => {
  for (const palette of Object.keys(PALETTES)) {
    const greys = [1, 2, 3, 4, 5].map((n) => (GRAVEL_PALETTES as Record<string, Record<number, { color: string }>>)[palette][n].color);
    for (let i = 1; i < greys.length; i++) {
      assert.ok(relativeLuminance(greys[i]) < relativeLuminance(greys[i - 1]), `${palette}: LTS ${i + 1} is not darker`);
      assert.ok(contrastRatio(greys[i], greys[i - 1]) >= 1.5, `${palette}: step ${i}`);
      assert.ok(worst(greys[i], greys[i - 1]) >= 10, `${palette}: step ${i} is ${worst(greys[i], greys[i - 1]).toFixed(1)}`);
    }
    for (const c of greys) {
      const [, a, b] = lab(c);
      assert.ok(Math.hypot(a, b) < 8, `${c} is a grey`);
    }
  }
});

test("every gravel tier is 3:1 or more from every surface of the base map and both panels, its line 3:1 from its casing, plain and strong", () => {
  const failures: string[] = [];
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      for (const tier of tiersFor(palette, strong) as Tier[]) {
        const onCasing = contrastRatio(tier.gravelColor, tier.gravelCasing);
        if (onCasing < 3) failures.push(`${palette} ${tier.short}: line on casing ${onCasing.toFixed(2)}:1`);
        for (const [name, under] of Object.entries({ ...SURFACES, panelLight: "#ffffff", panelDark: "#1b1e24" })) {
          const legible = Math.max(contrastRatio(tier.gravelColor, under), Math.min(contrastRatio(tier.gravelCasing, under), onCasing));
          if (legible < 3) failures.push(`${palette}${strong ? " strong" : ""} ${tier.short} on ${name}: ${legible.toFixed(2)}:1`);
        }
      }
    }
  }
  assert.ok(Object.keys(SURFACES).length >= 15);
  assert.deepEqual(failures, []);
});

test("the gaps' harshness never falls as stress rises on gravel, in every palette, plain and strong (292, 356)", () => {
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const h = tiers.map((x) => harshness(x.dash, x.gravelGap, x.gravelColor));
      for (let i = 1; i < h.length; i += 1) assert.ok(h[i - 1] <= h[i], `${palette}${strong ? " strong" : ""}: ${h.map((x) => x.toFixed(2)).join(" ")}`);
    }
  }
});

test("gravel and natural surface of the same tier are 10 CIEDE2000 or more apart under normal vision, and gravel is apart from the paved tiers", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    const tiers = tiersFor(palette) as Tier[];
    t.diagnostic(`${palette}: ` + tiers.map((x) => `${x.short} ${x.gravelColor}/${x.unpavedColor} ${deltaE2000(x.gravelColor, x.unpavedColor).toFixed(1)}`).join("; "));
    for (const x of tiers) {
      assert.ok(deltaE2000(x.gravelColor, x.unpavedColor) >= 10, `${palette} ${x.short}: gravel and brown`);
      for (const paved of tiers) assert.ok(deltaE2000(x.gravelColor, paved.color) >= 10, `${palette} gravel ${x.short} vs paved ${paved.short}`);
    }
  }
});

test("the unrated dirt trails are brown now, not a gravel grey", () => {
  for (const c of [MTB_TRAIL.color, MTB_TRAIL.strongColor]) {
    const [, a, b] = lab(c);
    const hue = (Math.atan2(b, a) * 180) / Math.PI;
    assert.ok(hue > 40 && hue < 95 && Math.hypot(a, b) >= 12, `${c}: hue ${hue.toFixed(0)}, chroma ${Math.hypot(a, b).toFixed(0)}`);
  }
});
