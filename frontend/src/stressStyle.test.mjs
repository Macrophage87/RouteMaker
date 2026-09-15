// Run with: node --test frontend/src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRESS_TIERS, BASEMAP, stressLayers, legend } from "./stressStyle.js";

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

test("lightness increases with stress so greyscale keeps the ordering", () => {
  // Hues that flatten into the same grey would make the printed overlay
  // meaningless even though it looks fine on screen.
  const lightness = STRESS_TIERS.map((t) => t.lightness);
  for (let i = 1; i < lightness.length; i += 1) {
    assert.ok(lightness[i] > lightness[i - 1], "lightness must increase with tier");
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
