// Run with: npm test (from frontend/), or node --test frontend/src/stressStyle.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  FURTH_TIERS,
  STRESS_TIERS,
  BASEMAP,
  stressLayers,
  stressCasingLayers,
  stressOverlayLayers,
  legend,
  FACILITIES,
  facilityLayers,
  CASING_EXTRA_PX,
  relativeLuminance,
  contrastRatio,
  stressFilters,
} from "./stressStyle.js";
import * as spec from "@maplibre/maplibre-gl-style-spec";

/** Whether `layer` draws a feature with `properties`, as MapLibre decides it. */
function draws(layer, properties) {
  const { filter } = spec.featureFilter(layer.filter, `layers[${layer.id}].filter`);
  return filter({ zoom: 12 }, { type: 2, properties, geometry: [] });
}

/** A paint expression's value for a feature with `properties`. */
function paintValue(layer, name, properties) {
  const expression = spec.createExpression(layer.paint[name], `layers[${layer.id}].paint.${name}`, spec.latest.paint_line[name]);
  assert.equal(expression.result, "success", JSON.stringify(expression.value));
  return expression.value.evaluate({ zoom: 12 }, { type: 2, properties, geometry: [] });
}

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
  const luminance = FURTH_TIERS.map((t) => relativeLuminance(t.color));
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
  for (let i = 1; i < FURTH_TIERS.length; i += 1) {
    const ratio = contrastRatio(FURTH_TIERS[i].color, FURTH_TIERS[i - 1].color);
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

test("tiers cover exactly the Furth scale, and legal-but-avoid above it", () => {
  assert.deepEqual(
    STRESS_TIERS.map((t) => t.tier),
    [1, 2, 3, 4, 5],
  );
  assert.deepEqual(
    FURTH_TIERS.map((t) => t.tier),
    [1, 2, 3, 4],
  );
});

test("legal-but-avoid stands apart from every Furth tier", () => {
  const avoid = STRESS_TIERS.find((t) => t.tier === 5);
  for (const tier of FURTH_TIERS) {
    assert.ok(avoid.width > tier.width, `wider than ${tier.short}`);
    assert.ok(contrastRatio(avoid.color, tier.color) >= 1.4 || relativeLuminance(avoid.color) > 0.05, tier.short);
  }
  assert.ok(avoid.dash.length > 2, "a dash-dot pattern, unlike the Furth tiers' dashes");
  assert.match(avoid.label, /avoid/i);
});

test("one layer per tier, each filtered to its own tier", () => {
  const layers = stressLayers();
  assert.equal(layers.length, STRESS_TIERS.length);
  layers.forEach((layer, i) => {
    for (const tier of STRESS_TIERS) {
      assert.equal(draws(layer, { tier: tier.tier }), tier.tier === STRESS_TIERS[i].tier, `${layer.id} and LTS ${tier.tier}`);
    }
  });
});

test("the layers read the shared contract's tile layer and property", () => {
  // SHARED API CONTRACT: /tiles/stress/{z}/{x}/{y}.pbf carries one layer named
  // "stress" whose features have a "tier" property. A layer or property name
  // the tiles do not carry draws nothing and raises nothing.
  for (const layer of stressLayers("stress-src")) {
    assert.equal(layer.source, "stress-src");
    assert.equal(layer["source-layer"], "stress");
    assert.ok(JSON.stringify(layer.filter).includes('["get","tier"]'));
    assert.equal(draws(layer, {}), false, "a feature with no tier is drawn by no tier's layer");
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

test("a casing is a halo, not a band: no wider on the two sides together than its tier's own line", () => {
  // A casing wider than the line it frames swallows the streets beside it at
  // the zooms the overlay is read at, and the tier becomes a stripe on a band.
  const tiers = stressLayers();
  stressCasingLayers().forEach((casing, i) => {
    const extra = casing.paint["line-width"] - tiers[i].paint["line-width"];
    assert.ok(extra <= tiers[i].paint["line-width"], `LTS ${i + 1}'s casing is ${extra} px wider than a ${tiers[i].paint["line-width"]} px line`);
  });
});

test("the overlay is added casings first: every casing under every tier", () => {
  const ids = stressOverlayLayers("s").map((l) => l.id);
  const tiers = stressLayers("s").map((l) => l.id);
  const casings = stressCasingLayers("s").map((l) => l.id);
  const rails = facilityLayers("s").map((l) => l.id);
  assert.deepEqual([...ids].sort(), [...rails, ...tiers, ...casings].sort(), "each layer once");
  casings.forEach((casing, i) => assert.ok(ids.indexOf(casing) < ids.indexOf(tiers[i]), `${casing} is drawn over its tier`));
  const lastCasing = Math.max(...casings.map((c) => ids.indexOf(c)));
  const firstTier = Math.min(...tiers.map((t) => ids.indexOf(t)));
  assert.ok(lastCasing < firstTier, "a casing is drawn over another tier's line");
  const lastRail = Math.max(...rails.map((r) => ids.indexOf(r)));
  const firstCasing = Math.min(...casings.map((c) => ids.indexOf(c)));
  assert.ok(lastRail < firstCasing, "a facility's rails are drawn over a stress line");
  for (const layer of stressOverlayLayers("s")) assert.equal(layer.source, "s");
});

test("the bike facilities are the owner's three, and sharrows are not one of them", () => {
  assert.deepEqual(
    FACILITIES.map((f) => f.facility),
    ["path", "protected", "lane"],
  );
  for (const f of FACILITIES) assert.ok(f.label.length > 0 && f.short.length > 0);
});

test("each facility is told apart from the others without colour, and the stronger read bolder", () => {
  const cues = FACILITIES.map((f) => JSON.stringify([f.rail, f.dash]));
  assert.equal(new Set(cues).size, FACILITIES.length);
  const [path, protectedLane, lane] = FACILITIES;
  assert.ok(path.rail >= protectedLane.rail && protectedLane.rail > lane.rail);
  assert.equal(path.dash, null, "an off-road path's rails are unbroken");
});

test("each facility layer reads the tile's facility property and shows beyond the casing", () => {
  const layers = facilityLayers("s");
  layers.forEach((layer, i) => {
    for (const f of FACILITIES) {
      assert.equal(draws(layer, { tier: 1, facility: f.facility }), f === FACILITIES[i], `${layer.id} and ${f.facility}`);
    }
    assert.equal(draws(layer, { tier: 1, facility: "none" }), false);
    assert.equal(layer["source-layer"], "stress");
    for (const tier of STRESS_TIERS) {
      const w = paintValue(layer, "line-width", { tier: tier.tier, facility: FACILITIES[i].facility });
      assert.ok(w >= tier.width + CASING_EXTRA_PX + 2, `${layer.id} at LTS ${tier.tier} hides under the casing`);
    }
    assert.ok(paintValue(layer, "line-width", { tier: 9 }) > 0, "a tier the style does not know still gets rails");
  });
});

test("the facility colours are legible on the base map and not the route's blue", () => {
  for (const f of FACILITIES) {
    assert.ok(contrastRatio(f.color, "#f5f3ef") >= 3, `${f.facility} is under 3:1 on the base map`);
    assert.notEqual(f.color.toLowerCase(), "#1d4ed8");
  }
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

test("each facility layer draws its own dash, or none", () => {
  // The dash is the only thing that tells a path from a protected lane on the
  // map: both are bold violet (mutation review, round 1).
  facilityLayers("s").forEach((layer, i) => {
    assert.deepEqual(layer.paint["line-dasharray"], FACILITIES[i].dash ?? undefined);
  });
});

test("an unknown tier's rails still show beyond the casing", () => {
  for (const layer of facilityLayers("s")) {
    const width = layer.paint["line-width"];
    assert.ok(width.at(-1) >= STRESS_TIERS[0].width + CASING_EXTRA_PX + 2);
  }
});

// The owner, 2026-09-29: "One note: Car-free roads should be regarded the same
// as an off-road path on a map." and, for the weekend closures, "Path on
// weekends only" (OWNER-DECISIONS 67).
function drawnBy(when, properties) {
  return stressOverlayLayers("stress", when)
    .filter((layer) => draws(layer, properties))
    .map((layer) => layer.id)
    .sort();
}

const ASPATH = ["facility-path", "stress-1", "stress-casing-1"];

test("a road closed to cars for good draws as an off-road path in every ride time", () => {
  // The tiles carry it as a path already (routemaker.facility, the rebuild).
  const beachDrive = { tier: 1, facility: "path", trail: false };
  const trail = { tier: 1, facility: "path", trail: true };
  for (const when of ["weekend", "weekday_rush", "weekday_offpeak"]) {
    assert.deepEqual(drawnBy(when, beachDrive), ASPATH);
    assert.deepEqual(drawnBy(when, beachDrive), drawnBy(when, trail));
  }
});

test("a road closed on weekends is a path on weekends and its own road otherwise", () => {
  const sligo = { tier: 3, facility: "none", car_free: "weekend" };
  assert.deepEqual(drawnBy("weekend", sligo), ASPATH);
  assert.deepEqual(drawnBy("weekday_offpeak", sligo), ["stress-3", "stress-casing-3"]);
  assert.deepEqual(drawnBy("weekday_rush", sligo), ["stress-3", "stress-casing-3"]);
  const withLane = { tier: 2, facility: "lane", car_free: "weekend" };
  assert.deepEqual(drawnBy("weekday_offpeak", withLane), ["facility-lane", "stress-2", "stress-casing-2"]);
  assert.deepEqual(drawnBy("weekend", withLane), ASPATH);
});

test("zoomed out, such a road is drawn only in the ride times it is closed in", () => {
  const sligo = { tier: 3, facility: "none", car_free_only: "weekend" };
  assert.deepEqual(drawnBy("weekend", sligo), ASPATH);
  assert.deepEqual(drawnBy("weekday_offpeak", sligo), []);
  const clark = { tier: 2, facility: "none", car_free_only: "weekday_rush" };
  assert.deepEqual(drawnBy("weekday_rush", clark), ASPATH);
  assert.deepEqual(drawnBy("weekend", clark), []);
  const both = { tier: 3, facility: "none", car_free_only: "weekday_rush,weekend" };
  assert.deepEqual(drawnBy("weekend", both), ASPATH);
  assert.deepEqual(drawnBy("weekday_offpeak", both), []);
});

test("a path's rails are a path's width when a closure makes a road one", () => {
  const [path] = facilityLayers("stress", "weekend");
  const tier1 = paintValue(path, "line-width", { tier: 1, facility: "path" });
  assert.equal(paintValue(path, "line-width", { tier: 4, facility: "none", car_free: "weekend" }), tier1);
});

test("stressFilters covers every overlay layer, and a style with them validates", () => {
  const filters = stressFilters("weekend");
  assert.deepEqual(Object.keys(filters).sort(), stressOverlayLayers("stress").map((l) => l.id).sort());
  const style = {
    version: 8,
    sources: { stress: { type: "vector", tiles: ["https://example.test/{z}/{x}/{y}.pbf"] } },
    layers: stressOverlayLayers("stress", "weekday_rush"),
  };
  assert.deepEqual(spec.validateStyleMin(style), []);
});
