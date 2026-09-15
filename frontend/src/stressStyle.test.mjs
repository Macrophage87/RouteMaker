// Run with: node --test frontend/src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  STRESS_TIERS,
  BASEMAP,
  stressLayers,
  legend,
  relativeLuminance,
  contrastRatio,
} from "./stressStyle.js";

test("every stress tier is distinguishable without colour", () => {
  // The accessibility rule, and also what makes the overlay readable on the
  // black-and-white sheet a marshal carries.
  const dashes = STRESS_TIERS.map((t) => JSON.stringify(t.dash));
  assert.equal(new Set(dashes).size, STRESS_TIERS.length, "dash patterns must be unique");
});

test("every stress tier carries a label", () => {
  for (const tier of STRESS_TIERS) {
    assert.ok(tier.label.length > 0, `tier ${tier.tier} has no label`);
    assert.ok(tier.short.length > 0, `tier ${tier.tier} has no short label`);
  }
});

test("luminance is computed from the colour and falls monotonically with stress", () => {
  // Computed from the colour rather than from a number typed beside it. The
  // earlier version compared a hand-written `lightness` field, so setting LTS4
  // to pure black left the test green while the printed overlay became
  // meaningless.
  const luminance = STRESS_TIERS.map((t) => relativeLuminance(t.color));
  for (let i = 1; i < luminance.length; i += 1) {
    assert.ok(
      luminance[i] < luminance[i - 1],
      `tier ${i + 1} must be darker than tier ${i} in greyscale`,
    );
  }
});

test("adjacent tiers are separable in greyscale, not merely ordered", () => {
  // Monotonic is not enough: four tiers one grey level apart are ordered and
  // unreadable. 1.4:1 between neighbours keeps them apart on a photocopy.
  for (let i = 1; i < STRESS_TIERS.length; i += 1) {
    const ratio = contrastRatio(STRESS_TIERS[i].color, STRESS_TIERS[i - 1].color);
    assert.ok(ratio >= 1.4, `tiers ${i} and ${i + 1} are ${ratio.toFixed(2)}:1 apart`);
  }
});

test("every tier is legible against the map background", () => {
  // The contrast check PLAN.md requires of CI, which previously existed nowhere.
  for (const tier of STRESS_TIERS) {
    const ratio = contrastRatio(tier.color, "#f5f3ef");
    assert.ok(ratio >= 1.5, `tier ${tier.tier} is ${ratio.toFixed(2)}:1 on the basemap`);
  }
});

test("tiers cover exactly the Furth scale", () => {
  assert.deepEqual(
    STRESS_TIERS.map((t) => t.tier),
    [1, 2, 3, 4],
  );
});

test("one layer per tier, each filtered to its own tier", () => {
  const layers = stressLayers();
  assert.equal(layers.length, 4);
  for (const layer of layers) {
    assert.equal(layer.filter[0], "==");
    assert.equal(layer.filter[1][1], "stress_tier");
  }
});

test("the basemap is served from our own disk", () => {
  // No third party sees which routes are being looked at, which matters when
  // some of them are for unpermitted rides.
  assert.ok(BASEMAP.url.startsWith("pmtiles://"));
  assert.ok(!BASEMAP.url.includes("http"));
});

test("attribution names OpenStreetMap and the basemap", () => {
  // The credit follows the renderer, so anything drawn from this basemap
  // carries it - thumbnails and share cards included.
  assert.match(BASEMAP.attribution, /OpenStreetMap/);
  assert.match(BASEMAP.attribution, /Protomaps/);
});

test("the legend carries what colour alone cannot", () => {
  for (const entry of legend()) {
    assert.ok(entry.label && entry.dash);
  }
});
