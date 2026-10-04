// Run with: npm test (from frontend/), or node --test frontend/src/stressStyle.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BASEMAP,
  stressLayers,
  stressCasingLayers,
  gapLayers,
  ringLayers,
  stressOverlayLayers,
  unpavedLayers,
  legend,
  FACILITIES,
  facilityLayers,
  CASING_EXTRA_PX,
  relativeLuminance,
  contrastRatio,
  stressFilters,
  BESIDE_ROAD_MIN_ZOOM,
  DEFAULT_PALETTE,
  FAINT,
  PALETTES,
  SOLID_MIN_ZOOM,
  ALLEY_MIN_ZOOM,
  paletteFrom,
  tiersFor,
  currentTiers,
  furthTiers,
} from "./stressStyle.js";
import * as spec from "@maplibre/maplibre-gl-style-spec";

// These tests assert the default palette's tiers, which is what the module
// starts with here (no address, no storage); the palette-switching tests are in
// lib/accessibilitySwitch.test.ts.
// The warm palette, the default until OWNER-DECISIONS 351, which these rules were tuned on; the
// default two-tone is held to them, and to the breaks the owner's colours make, in defaultPalette.test.ts.
const STRESS_TIERS = tiersFor("blended");
const FURTH_TIERS = STRESS_TIERS.filter((t) => t.tier <= 4);
/** The tiers the layers are built in by default: the two-tone palette (351). */
const DEFAULT_TIERS = tiersFor(DEFAULT_PALETTE);

/** Whether `layer` draws a feature with `properties`, as MapLibre decides it. */
function draws(layer, properties) {
  const { filter } = spec.featureFilter(layer.filter, `layers[${layer.id}].filter`);
  return filter({ zoom: 12 }, { type: 2, properties, geometry: [] });
}

/** A paint expression's value for a feature with `properties`, at `zoom`. */
function paintValue(layer, name, properties, zoom = 12) {
  const value = layer.paint[name];
  if (value === undefined) return name === "line-opacity" ? 1 : undefined;
  if (typeof value === "number" || typeof value === "string") return value;
  const expression = spec.createExpression(value, `layers[${layer.id}].paint.${name}`, spec.latest.paint_line[name]);
  assert.equal(expression.result, "success", JSON.stringify(expression.value));
  const result = expression.value.evaluate({ zoom }, { type: 2, properties, geometry: [] });
  // A colour comes back as channels 0-1; the palettes are written as "#rrggbb".
  return result && typeof result.r === "number" && result.a === 1
    ? `#${[result.r, result.g, result.b].map((n) => Math.round(n * 255).toString(16).padStart(2, "0")).join("")}`
    : result;
}

/** The tiers' own layers. */
const tierLayers = (layers) => layers;

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
  // unreadable. 1.4:1 between neighbours keeps them apart on a photocopy -
  // but for LTS 2 and 3 since the owner's amber (OWNER-DECISIONS 74): an amber
  // 1.4:1 from LTS 2's green is brown. Their dashes (long, even) differ.
  for (let i = 1; i < FURTH_TIERS.length; i += 1) {
    const ratio = contrastRatio(FURTH_TIERS[i].color, FURTH_TIERS[i - 1].color);
    const floor = FURTH_TIERS[i].tier === 3 ? 1.15 : 1.4;
    assert.ok(ratio >= floor, `tiers ${i} and ${i + 1} are ${ratio.toFixed(2)}:1 apart`);
  }
  assert.notDeepEqual(FURTH_TIERS[1].dash, FURTH_TIERS[2].dash);
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
  const layers = tierLayers(stressLayers());
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
  for (const layer of tierLayers(stressLayers("stress-src"))) {
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
    assert.ok(entry.label && entry.dash !== undefined, "a solid line is dash: null, a dash is an array");
  }
});

test("each tier has a casing layer drawn wider, in its own casing colour, on the same features", () => {
  const casings = tierLayers(stressCasingLayers("stress-src"));
  const tiers = tierLayers(stressLayers("stress-src"));
  assert.equal(casings.length, tiers.length);
  casings.forEach((casing, i) => {
    assert.deepEqual(casing.filter, tiers[i].filter);
    assert.equal(casing["source-layer"], tiers[i]["source-layer"]);
    const f = { tier: DEFAULT_TIERS[i].tier };
    assert.equal(paintValue(casing, "line-color", f, 14), DEFAULT_TIERS[i].casing);
    assert.notEqual(paintValue(casing, "line-color", f, 14), DEFAULT_TIERS[i].color);
    for (const zoom of [14, 16]) {
      assert.ok(paintValue(casing, "line-width", f, zoom) > paintValue(tiers[i], "line-width", f, zoom));
    }
    // Where the line is faint (z12-13 for the busy tiers) the casing is a ring around it, not a band under it:
    // as wide outside as the band would be, and no gap anywhere else.
    assert.equal(paintValue(casing, "line-gap-width", f, 14), 0);
    assert.equal(casing.paint["line-dasharray"], undefined, "a casing is solid");
  });
  assert.equal(new Set([...casings, ...tiers].map((l) => l.id)).size, casings.length * 2);
});

test("a casing shows at least a pixel on each side of its tier", () => {
  // The 3:1 figures in stressContrast.test.ts assume a visible halo; a casing
  // a tenth of a pixel wider is a casing in name only.
  const tiers = tierLayers(stressLayers());
  tierLayers(stressCasingLayers()).forEach((casing, i) => {
    const f = { tier: STRESS_TIERS[i].tier };
    const extra = paintValue(casing, "line-width", f, 14) - paintValue(tiers[i], "line-width", f, 14);
    assert.ok(extra >= 2, `LTS ${i + 1}'s casing is only ${extra} px wider`);
  });
});

test("a casing is a halo, not a band: no wider on the two sides together than its tier's own line", () => {
  // A casing wider than the line it frames swallows the streets beside it at
  // the zooms the overlay is read at, and the tier becomes a stripe on a band.
  const tiers = tierLayers(stressLayers());
  tierLayers(stressCasingLayers()).forEach((casing, i) => {
    const f = { tier: STRESS_TIERS[i].tier };
    const line = paintValue(tiers[i], "line-width", f, 14);
    const extra = paintValue(casing, "line-width", f, 14) - line;
    assert.ok(extra <= line, `LTS ${i + 1}'s casing is ${extra} px wider than a ${line} px line`);
  });
});

test("the overlay is added casings first: every casing under every tier", () => {
  const ids = stressOverlayLayers("s").map((l) => l.id);
  const tiers = stressLayers("s").map((l) => l.id);
  const casings = stressCasingLayers("s").map((l) => l.id);
  const rails = facilityLayers("s").map((l) => l.id);
  const marks = unpavedLayers("s").map((l) => l.id);
  const gaps = gapLayers("s").map((l) => l.id);
  assert.deepEqual(gaps, ["stress-gap-2"], "LTS 2's own gap colour (OWNER-DECISIONS 356)");
  const rings = ringLayers("s").map((l) => l.id);
  assert.deepEqual(rings, ["stress-ring-3", "stress-ring-4"], "two-tone LTS 3 and 4's ring (OWNER-DECISIONS 371)");
  assert.deepEqual([...ids].sort(), [...rings, ...rails, ...tiers, ...casings, ...gaps, ...marks].sort(), "each layer once");
  // The rings under everything, so a rail still shows over them.
  assert.ok(Math.max(...rings.map((r) => ids.indexOf(r))) < Math.min(...rails.map((r) => ids.indexOf(r))));
  // The gap line lies over its casing and under its dashes.
  assert.ok(ids.indexOf("stress-casing-2") < ids.indexOf("stress-gap-2") && ids.indexOf("stress-gap-2") < ids.indexOf("stress-2"));
  assert.ok(Math.min(...marks.map((m) => ids.indexOf(m))) > Math.max(...tiers.map((t) => ids.indexOf(t))), "the surface mark is drawn over every tier line");
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
  // Bolder is more ink - the rail's width times the share of it drawn - not a wider rail: a path's
  // solid 2.5 px outweighs a protected lane's 4 px blocks (half drawn), and paint is far the least
  // (OWNER-DECISIONS 290: the path rail is no longer the heaviest line).
  const duty = (f) => (f.dash ? f.dash[0] / (f.dash[0] + f.dash[1]) : 1);
  const ink = (f) => f.rail * duty(f);
  assert.ok(ink(path) >= ink(protectedLane) && ink(protectedLane) > 4 * ink(lane), `${ink(path)} ${ink(protectedLane)} ${ink(lane)}`);
  assert.ok(protectedLane.rail > lane.rail && path.rail > lane.rail);
  assert.equal(path.dash, null, "an off-road path's rails are unbroken");
});

test("each facility layer reads the tile's facility property and shows beyond the casing", () => {
  const layers = facilityLayers("s");
  layers.forEach((layer) => {
    const i = FACILITIES.findIndex((f) => `facility-${f.facility}` === layer.id);
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
  facilityLayers("s").forEach((layer) => {
    const facility = FACILITIES.find((f) => `facility-${f.facility}` === layer.id);
    assert.deepEqual(layer.paint["line-dasharray"], facility.dash ?? undefined);
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
  assert.deepEqual(drawnBy("weekday_offpeak", sligo), ["stress-3", "stress-casing-3", "stress-ring-3"]);
  assert.deepEqual(drawnBy("weekday_rush", sligo), ["stress-3", "stress-casing-3", "stress-ring-3"]);
  const withLane = { tier: 2, facility: "lane", car_free: "weekend" };
  assert.deepEqual(drawnBy("weekday_offpeak", withLane), ["facility-lane", "stress-2", "stress-casing-2", "stress-gap-2"]);
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

// The owner, 2026-09-29 (OWNER-DECISIONS 73, 76, 77, 78, 80).
function drawnAtZoom(properties, zoom) {
  const out = {};
  for (const layer of stressOverlayLayers("stress")) {
    if (!draws(layer, properties)) continue;
    const opacity = paintValue(layer, "line-opacity", properties, zoom);
    if (opacity > 0) out[layer.id] = { opacity, width: paintValue(layer, "line-width", properties, zoom) };
  }
  return out;
}

test("the overlay has no layer for a road a bicycle may not use: the base map shows it; Avoid keeps its colour", () => {
  // "You can just leave the public roads where bikes aren't allowed as
  // unmarked, using the base map" (OWNER-DECISIONS 89): such roads are not in
  // the tiles, and no layer waits for them.
  assert.ok(stressOverlayLayers("stress").every((l) => !/barred|expressway/.test(l.id)));
  const us340 = { tier: 5 };
  assert.deepEqual(Object.keys(drawnAtZoom(us340, 14)).sort(), ["stress-5", "stress-casing-5"]);
});

test("busy roads are faint at z12-13 and solid from z14; quiet streets and paths are never faint", () => {
  // "Show them faintly" (76), then "Make solid at 14" (77).
  assert.equal(SOLID_MIN_ZOOM, 14);
  for (const tier of [3, 4, 5]) {
    const f = { tier };
    const faint = drawnAtZoom(f, 12)[`stress-${tier}`];
    const solid = drawnAtZoom(f, 14)[`stress-${tier}`];
    const shape = STRESS_TIERS.find((t) => t.tier === tier);
    assert.equal(faint.opacity, FAINT.opacity);
    assert.ok(Math.abs(faint.width - shape.width * FAINT.widthScale) < 1e-9);
    assert.equal(drawnAtZoom(f, 13)[`stress-${tier}`].opacity, FAINT.opacity);
    assert.deepEqual(solid, { opacity: 1, width: shape.width });
    assert.deepEqual(drawnAtZoom(f, 16)[`stress-${tier}`], { opacity: 1, width: shape.width });
  }
  for (const properties of [{ tier: 1 }, { tier: 2 }, { tier: 1, facility: "path", trail: true }]) {
    for (const zoom of [10, 12, 14]) {
      for (const [id, line] of Object.entries(drawnAtZoom(properties, zoom))) assert.equal(line.opacity, 1, id);
    }
  }
});

test("a busy road beside a separately mapped bike lane is hidden until z15 and then faint for good", () => {
  // "hide it until zoom 15-16. The bike lane should show up as the main." (73)
  // and "Keep it faint if it parallels a protected bike path." (78)
  assert.equal(BESIDE_ROAD_MIN_ZOOM, 15);
  for (const tier of [3, 4, 5]) {
    const f = { tier, separate_bikeway: true };
    for (const zoom of [12, 13, 14]) assert.deepEqual(drawnAtZoom(f, zoom), {}, `z${zoom}`);
    for (const zoom of [15, 16, 18]) assert.equal(drawnAtZoom(f, zoom)[`stress-${tier}`].opacity, FAINT.opacity, `z${zoom}`);
  }
  // The cycle track beside it, a trail of its own, is drawn full at every zoom.
  const track = { tier: 1, facility: "protected", trail: true };
  for (const zoom of [10, 12, 14]) {
    const lines = drawnAtZoom(track, zoom);
    assert.deepEqual(Object.keys(lines).sort(), ["facility-protected", "stress-1", "stress-casing-1"]);
    for (const line of Object.values(lines)) assert.equal(line.opacity, 1);
  }
});

test("Avoid is told from LTS 4 at a glance, faint or solid, in every palette", () => {
  for (const palette of Object.keys(PALETTES)) {
    const tiers = tiersFor(palette);
    const [lts4, avoid] = [tiers[3], tiers[4]];
    assert.notDeepEqual(avoid.dash, lts4.dash);
    assert.ok(avoid.width > lts4.width);
    // The colour-blind-friendly palette's pair is held to a CIEDE2000 floor
    // under every vision instead (stressContrast.test.ts): its LTS 4 is a dark
    // red a protanope sees as near-black, which a luminance ratio of 1.8 would
    // have meant a brighter red that crowds LTS 3.
    const floor = palette === "cvd" ? 1.4 : 1.8;
    assert.ok(contrastRatio(avoid.color, lts4.color) >= floor, `${palette}: ${contrastRatio(avoid.color, lts4.color).toFixed(2)}:1`);
  }
});

test("the colours are in one place: LTS 1 and 2 as they were, two readings of the owner's for 3-5", () => {
  // "I like LTS 1 and 2. Maybe yellow and orange for LTS 3, orange and red for
  // LTS 4, and red and black for Avoid." (74)
  const { blended, twotone } = PALETTES;
  for (const palette of [blended, twotone]) {
    // LTS 1's edge is a softer dark green since OWNER-DECISIONS 357 (#17301f before).
    assert.deepEqual(palette[1], { color: "#9ed3ac", casing: "#2f5d47" });
    // LTS 2's edge is a slate blue and its gaps a steel blue since OWNER-DECISIONS 356 ("a blue instead of black").
    assert.deepEqual(palette[2], { color: "#57a06c", casing: "#1a2638", gap: "#7a8fa3" });
    assert.deepEqual(Object.keys(palette).sort(), ["1", "2", "3", "4", "5"]);
  }
  // Two-tone: the first colour the line, the second its casing.
  // 371: the yellow a shade lighter (#f2c21b before).
  assert.deepEqual([twotone[3].color, twotone[3].casing], ["#f3c81a", "#f28c28"]);
  // LTS 4's red casing is a shade deeper than Avoid's red line, so LTS 3's gaps are no harsher than
  // LTS 4's (OWNER-DECISIONS 292; stressSalience.test.ts).
  assert.deepEqual([twotone[4].color, twotone[4].casing], ["#f28c28", "#c81e1e"]);
  assert.deepEqual([twotone[5].color, twotone[5].casing], ["#d42020", "#111111"]);
  assert.equal(DEFAULT_PALETTE, "twotone");
  assert.equal(paletteFrom("?palette=twotone"), "twotone");
  assert.equal(paletteFrom("?x=1&palette=blended"), "blended");
  assert.equal(paletteFrom("?palette=__proto__"), DEFAULT_PALETTE);
  assert.equal(paletteFrom(""), DEFAULT_PALETTE);
  assert.deepEqual(currentTiers(), tiersFor(DEFAULT_PALETTE));
  assert.deepEqual(furthTiers(), tiersFor(DEFAULT_PALETTE).filter((t) => t.tier <= 4));
});

// Machado, Oliveira and Fernandes (2009), deuteranopia at full severity, on
// linear RGB: what a deuteranope sees of a colour.
function deuteranopia(hex) {
  const lin = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  const m = [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ];
  const out = m.map((row) => Math.max(0, Math.min(1, row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2])));
  const srgb = out.map((v) => (v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055));
  return "#" + srgb.map((v) => Math.round(v * 255).toString(16).padStart(2, "0")).join("");
}

test("for a deuteranope the default palette's tiers stay apart", () => {
  // Measured, 2026-09-29: seen through the simulation, LTS 2's green and LTS 3's
  // amber are one olive (1.03:1), told apart only by their dashes (and they
  // share a screen only from z14, LTS 3 being the faint background at z12-13);
  // every other neighbour is 1.4:1 or more apart in luminance.
  const seen = STRESS_TIERS.map((t) => deuteranopia(t.color));
  for (let i = 1; i < seen.length; i += 1) {
    const ratio = contrastRatio(seen[i], seen[i - 1]);
    if (i === 2) {
      assert.notDeepEqual(STRESS_TIERS[1].dash, STRESS_TIERS[2].dash);
      continue;
    }
    assert.ok(ratio >= 1.4, `${STRESS_TIERS[i - 1].short} and ${STRESS_TIERS[i].short}: ${ratio.toFixed(2)}:1`);
  }
});

test("an alley is not drawn below z16 and is faint from it; a tier-5 road keeps the Avoid colour", () => {
  // "Cut down on showing them, and only use them if nessicary." (OWNER-DECISIONS 100)
  assert.equal(ALLEY_MIN_ZOOM, 16);
  assert.ok(SOLID_MIN_ZOOM < BESIDE_ROAD_MIN_ZOOM && BESIDE_ROAD_MIN_ZOOM < ALLEY_MIN_ZOOM, "the stops rise");
  for (const tier of [1, 2, 3]) {
    const alley = { tier, alley: true };
    for (const zoom of [14, 15]) assert.deepEqual(drawnAtZoom(alley, zoom), {}, `LTS ${tier} alley at z${zoom}`);
    for (const zoom of [16, 18]) assert.equal(drawnAtZoom(alley, zoom)[`stress-${tier}`].opacity, FAINT.opacity);
  }
  // Not an alley in the source: a tier-5 road the transform marks service=alley
  // in Valhalla's extract reaches the tiles as a road.
  const avoid = drawnAtZoom({ tier: 5 }, 14)["stress-5"];
  assert.deepEqual(avoid, { opacity: 1, width: DEFAULT_TIERS[4].width });
  const avoidLayer = stressLayers().find((l) => l.id === "stress-5");
  // Its colour when paved: the expression is the surface's (OWNER-DECISIONS 302).
  assert.deepEqual(avoidLayer.paint["line-color"], ["case", ["==", ["get", "unpaved"], true], DEFAULT_TIERS[4].unpavedColor, DEFAULT_TIERS[4].color]);
});
