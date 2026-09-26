// Run with: npm test (from frontend/), or node --test frontend/src/stressStyle.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  STRESS_TIERS,
  BASEMAP,
  stressLayers,
  stressCasingLayers,
  stressOverlayLayers,
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
  layers.forEach((layer, i) => {
    assert.equal(layer.filter[0], "==");
    assert.equal(layer.filter[2], STRESS_TIERS[i].tier);
  });
});

test("the layers read the shared contract's tile layer and property", () => {
  // SHARED API CONTRACT: /tiles/stress/{z}/{x}/{y}.pbf carries one layer named
  // "stress" whose features have a "tier" property. A layer or property name
  // the tiles do not carry draws nothing and raises nothing.
  for (const layer of stressLayers("stress-src")) {
    assert.equal(layer.source, "stress-src");
    assert.equal(layer["source-layer"], "stress");
    assert.deepEqual(layer.filter[1], ["get", "tier"]);
  }
});

test("the basemap is served from our own disk", () => {
  // No third party sees which routes are being looked at, which matters when
  // some of them are for unpermitted rides.
  assert.ok(BASEMAP.url.startsWith("pmtiles://"));
  assert.ok(!BASEMAP.url.includes("http"));
  // The path Caddy serves the archive at (docs/OPERATIONS.md, "The base map").
  assert.equal(BASEMAP.url, "pmtiles://" + BASEMAP.path);
  assert.equal(BASEMAP.path, "/basemap/region.pmtiles");
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

test("each tier has a casing layer drawn wider, in its own casing colour, on the same features", () => {
  const casings = stressCasingLayers("stress-src");
  const tiers = stressLayers("stress-src");
  assert.equal(casings.length, tiers.length);
  casings.forEach((casing, i) => {
    assert.deepEqual(casing.filter, tiers[i].filter);
    assert.equal(casing["source-layer"], tiers[i]["source-layer"]);
    assert.equal(casing.paint["line-color"], STRESS_TIERS[i].casing);
    assert.notEqual(casing.paint["line-color"], STRESS_TIERS[i].color);
    assert.ok(casing.paint["line-width"] > tiers[i].paint["line-width"]);
    assert.equal(casing.paint["line-dasharray"], undefined, "a casing is solid");
  });
  assert.equal(new Set([...casings, ...tiers].map((l) => l.id)).size, casings.length * 2);
});

test("a casing shows at least a pixel on each side of its tier", () => {
  // The 3:1 figures in stressContrast.test.ts assume a visible halo; a casing
  // a tenth of a pixel wider is a casing in name only.
  const tiers = stressLayers();
  stressCasingLayers().forEach((casing, i) => {
    const extra = casing.paint["line-width"] - tiers[i].paint["line-width"];
    assert.ok(extra >= 2, `LTS ${i + 1}'s casing is only ${extra} px wider`);
  });
});

test("the overlay is added casings first: every casing under every tier", () => {
  const ids = stressOverlayLayers("s").map((l) => l.id);
  const tiers = stressLayers("s").map((l) => l.id);
  const casings = stressCasingLayers("s").map((l) => l.id);
  assert.deepEqual([...ids].sort(), [...tiers, ...casings].sort(), "each layer once");
  casings.forEach((casing, i) => assert.ok(ids.indexOf(casing) < ids.indexOf(tiers[i]), `${casing} is drawn over its tier`));
  const lastCasing = Math.max(...casings.map((c) => ids.indexOf(c)));
  const firstTier = Math.min(...tiers.map((t) => ids.indexOf(t)));
  assert.ok(lastCasing < firstTier, "a casing is drawn over another tier's line");
  for (const layer of stressOverlayLayers("s")) assert.equal(layer.source, "s");
});

test("the contrast maths is WCAG 2's, against its published anchors", () => {
  assert.ok(Math.abs(relativeLuminance("#00ff00") - 0.7152) < 1e-4);
  assert.ok(Math.abs(relativeLuminance("#ff0000") - 0.2126) < 1e-4);
  assert.ok(Math.abs(relativeLuminance("#0000ff") - 0.0722) < 1e-4);
  assert.equal(relativeLuminance("#000000"), 0);
  assert.ok(Math.abs(relativeLuminance("#ffffff") - 1) < 1e-9);
  assert.ok(Math.abs(contrastRatio("#ffffff", "#000000") - 21) < 1e-9);
  assert.ok(Math.abs(contrastRatio("#000000", "#ffffff") - 21) < 1e-9, "the order of the two colours does not matter");
  // #767676 on white is the well-known 4.54:1, the lightest grey that passes AA.
  assert.ok(Math.abs(contrastRatio("#767676", "#ffffff") - 4.54) < 0.01);
  // The linear segment below 0.04045: #0a0a0a is 10/255/12.92.
  assert.ok(Math.abs(relativeLuminance("#0a0a0a") - 10 / 255 / 12.92) < 1e-9);
});
