// OWNER-DECISIONS 302: unpaved roads and trails in one brown ramp, light to dark from
// LTS 1 to Avoid, with each tier's own dash and width, on the map's overlay and the
// route's sections, and a dotted mark that is not colour. Measured against the ramps,
// the base map's own fills and the layers as the map would draw them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIGHT } from "@protomaps/basemaps";
import {
  PALETTES,
  UNPAVED_DASH,
  UNPAVED_PALETTES,
  contrastRatio,
  relativeLuminance,
  stressCasingLayers,
  stressLayers,
  tiersFor,
  unpavedLayers,
  unpavedWidth,
} from "./stressStyle.js";
import { VISIONS, deltaE2000, lab, simulate } from "./testSupport/colourVision.ts";
import { paintAt } from "./testSupport/paintAt.ts";
import { isUnpavedClass, routeClasses, routeSections, sectionFeatures, spanClass } from "./lib/routeColours.ts";
import { ROUTE_UNPAVED_LAYER_ID, routeUnpavedLayer, setRouteSections } from "./lib/mapGlue.ts";

type Tier = ReturnType<typeof tiersFor>[number];
type Layer = { id: string; paint: Record<string, unknown>; filter?: unknown };

/** The palettes the map is drawn in (twotone is the owner's alternative reading, reported only in places). */
const PALETTE_NAMES = Object.keys(PALETTES);
const HELD = ["blended", "cvd"];
const STRENGTHS = [false, true];

/** The base map's surfaces, as stressContrast.test.ts reads them. */
const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|buildings|other|minor|link|major$|highway$|bridges_(other|minor|link|major|highway)$|tunnel_(other|minor|link|major|highway)$)/;
const SURFACES: Record<string, string> = {};
for (const [key, value] of Object.entries(LIGHT)) {
  if (typeof value === "string" && SURFACE.test(key) && !key.includes("casing") && /^#[0-9a-f]{6}$/i.test(value)) SURFACES[key] = value.toLowerCase();
}
for (const [key, value] of Object.entries((LIGHT as { landcover?: Record<string, string> }).landcover ?? {})) {
  if (/^#[0-9a-f]{6}$/i.test(value)) SURFACES[`landcover.${key}`] = value.toLowerCase();
}

const worst = (a: string, b: string) => Math.min(...VISIONS.map((v) => deltaE2000(simulate(a, v), simulate(b, v))));
const harshness = (dash: number[] | null, casing: string, line: string) =>
  dash ? (dash.filter((_, i) => i % 2 === 1).reduce((a, b) => a + b, 0) / dash.reduce((a, b) => a + b, 0)) * contrastRatio(casing, line) : 0;

test("the ramp: one brown per tier, light to dark, every step 1.5:1 or more darker and 10 CIEDE2000 or more apart under every vision", (t) => {
  for (const palette of PALETTE_NAMES) {
    const browns = [1, 2, 3, 4, 5].map((n) => (UNPAVED_PALETTES as Record<string, Record<number, { color: string }>>)[palette][n].color);
    t.diagnostic(
      `${palette}: ` +
        browns.map((c, i) => `LTS ${i + 1} ${c} L*${lab(c)[0].toFixed(1)}`).join(", ") +
        "; steps " +
        browns.slice(1).map((c, i) => `${contrastRatio(browns[i], c).toFixed(2)}:1 dE ${VISIONS.map((v) => deltaE2000(simulate(browns[i], v), simulate(c, v)).toFixed(1)).join("/")}`).join("; "),
    );
    for (let i = 1; i < browns.length; i++) {
      assert.ok(relativeLuminance(browns[i]) < relativeLuminance(browns[i - 1]), `${palette}: LTS ${i + 1} is not darker`);
      assert.ok(contrastRatio(browns[i], browns[i - 1]) >= 1.5, `${palette}: step ${i} is ${contrastRatio(browns[i], browns[i - 1]).toFixed(2)}:1`);
      assert.ok(worst(browns[i], browns[i - 1]) >= 10, `${palette}: step ${i} is ${worst(browns[i], browns[i - 1]).toFixed(1)}`);
    }
    // Brown: a warm or olive hue, low to mid chroma, in every step.
    for (const c of browns) {
      const [, a, b] = lab(c);
      const hue = (Math.atan2(b, a) * 180) / Math.PI;
      assert.ok(hue > 45 && hue < 95 && Math.hypot(a, b) < 45, `${palette} ${c}: hue ${hue.toFixed(0)}, chroma ${Math.hypot(a, b).toFixed(0)}`);
    }
  }
});

test("each tier keeps its own dash and width when unpaved: the overlay's line layer is the tier's, only its colour follows the surface (283)", () => {
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const layers = stressLayers("s", undefined, tiers) as Layer[];
      tiers.forEach((tier, i) => {
        const layer = layers[i];
        assert.deepEqual(layer.paint["line-dasharray"], tier.dash ?? undefined, `${tier.short}: one dash for paved and unpaved`);
        for (const unpaved of [true, false, undefined]) {
          assert.equal(paintAt(layer, "line-width", { tier: tier.tier, unpaved }, 15), tier.width, `${tier.short} width`);
        }
        assert.equal(paintAt(layer, "line-color", { tier: tier.tier, unpaved: true }, 15), tier.unpavedColor, `${palette} ${tier.short} unpaved`);
        assert.equal(paintAt(layer, "line-color", { tier: tier.tier, unpaved: false }, 15), tier.color, "paved");
        assert.equal(paintAt(layer, "line-color", { tier: tier.tier }, 15), tier.color, "an unknown surface is drawn as paved");
      });
      const casings = stressCasingLayers("s", undefined, tiers) as Layer[];
      tiers.forEach((tier, i) => {
        assert.equal(paintAt(casings[i], "line-color", { tier: tier.tier, unpaved: true }, 15), tier.unpavedCasing, `${tier.short} unpaved casing`);
        assert.equal(paintAt(casings[i], "line-color", { tier: tier.tier, unpaved: false }, 15), tier.casing);
      });
      // The dotted mark, the cue that is not colour, in the unpaved casing over the brown.
      const marks = unpavedLayers("s", undefined, tiers) as Layer[];
      tiers.forEach((tier, i) => {
        assert.equal(marks[i].paint["line-color"], tier.unpavedCasing);
        assert.deepEqual(marks[i].paint["line-dasharray"], UNPAVED_DASH);
        assert.ok(JSON.stringify(marks[i].filter).includes(JSON.stringify(["==", ["get", "unpaved"], true])));
      });
    }
  }
});

test("every unpaved tier is 3:1 or more from every surface of the base map and both panels, and its line 3:1 from its casing, plain and strong", () => {
  const failures: string[] = [];
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      for (const tier of tiersFor(palette, strong) as Tier[]) {
        const onCasing = contrastRatio(tier.unpavedColor, tier.unpavedCasing);
        if (onCasing < 3) failures.push(`${palette}${strong ? " strong" : ""} ${tier.short}: line on casing ${onCasing.toFixed(2)}:1`);
        for (const [name, under] of Object.entries({ ...SURFACES, panelLight: "#ffffff", panelDark: "#1b1e24" })) {
          const legible = Math.max(contrastRatio(tier.unpavedColor, under), Math.min(contrastRatio(tier.unpavedCasing, under), onCasing));
          if (legible < 3) failures.push(`${palette}${strong ? " strong" : ""} ${tier.short} on ${name}: ${legible.toFixed(2)}:1`);
        }
        // The dots are 3:1 from the brown they are drawn on.
        if (contrastRatio(tier.unpavedCasing, tier.unpavedColor) < 3) failures.push(`${palette} ${tier.short}: dots`);
      }
    }
  }
  assert.ok(Object.keys(SURFACES).length >= 20);
  assert.deepEqual(failures, []);
});

test("the gaps' harshness still rises from LTS 3 to LTS 4 to Avoid on unpaved roads, in every palette, plain and strong (292)", (t) => {
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const h = tiers.map((x) => harshness(x.dash, x.unpavedCasing, x.unpavedColor));
      t.diagnostic(`${palette}${strong ? " strong" : ""} unpaved: ` + tiers.map((x, i) => `${x.short} ${h[i].toFixed(2)}`).join(", "));
      assert.ok(h[2] <= h[3] && h[3] <= h[4], `${palette}${strong ? " strong" : ""}: ${h.map((x) => x.toFixed(2)).join(" ")}`);
    }
  }
});

test("unpaved LTS 1 stands apart from the paved LTS 3 amber and the LTS 3 casing, under every vision", (t) => {
  for (const palette of PALETTE_NAMES) {
    const tiers = tiersFor(palette) as Tier[];
    const tan = tiers[0].unpavedColor;
    const against = { "the default amber #bf730b": "#bf730b", "the default LTS 3 casing #45290a": "#45290a", [`${palette}'s LTS 3 ${tiers[2].color}`]: tiers[2].color, [`${palette}'s LTS 3 casing ${tiers[2].casing}`]: tiers[2].casing };
    const deltas = Object.entries(against).map(([name, c]) => [name, worst(tan, c)] as const);
    t.diagnostic(`${palette} unpaved LTS 1 ${tan}: ` + deltas.map(([name, d]) => `${name} ${d.toFixed(1)}`).join(", "));
    for (const [name, d] of deltas) {
      // The palettes the map is held to: 15 or more; twotone (whose LTS 3 is a yellow) 9 or more, reported.
      assert.ok(d >= (HELD.includes(palette) ? 15 : 9), `${palette}: ${name} is ${d.toFixed(1)}`);
    }
  }
});

test("in the colour-blind-friendly palette the ochre ramp is 25 CIEDE2000 or more from the blue calm tiers under every vision", () => {
  const tiers = tiersFor("cvd") as Tier[];
  for (const tier of tiers) {
    for (const calm of [tiers[0].color, tiers[1].color]) assert.ok(worst(tier.unpavedColor, calm) >= 25, `${tier.unpavedColor} vs ${calm}: ${worst(tier.unpavedColor, calm).toFixed(1)}`);
  }
});

// ---- the route's sections ----

test("an unpaved section of the route is drawn in its tier's brown, with its unpaved casing as the halo and the tier's width", () => {
  const tiers = tiersFor("blended") as Tier[];
  for (const tier of tiers) {
    const cls = spanClass({ tier: tier.tier, facility: "none", unpaved: true });
    assert.equal(cls.key, `u${tier.tier}`);
    assert.equal(cls.color, tier.unpavedColor);
    assert.equal(cls.halo, tier.unpavedCasing);
    assert.equal(cls.width, spanClass({ tier: tier.tier, facility: "none" }).width, "the paved tier's width");
    assert.ok(isUnpavedClass(cls.key));
  }
  assert.equal(spanClass({ tier: 1, facility: "path", unpaved: true }).key, "u1", "an unpaved trail is brown, not the path's violet");
  assert.equal(spanClass({ tier: null, facility: "path", unpaved: true }).key, "u1");
  assert.equal(spanClass({ tier: 1, facility: "path", unpaved: false }).key, "path");
  assert.equal(spanClass({ tier: 3, facility: "none", unpaved: null }).key, "3", "an unknown surface is drawn as paved");
  assert.equal(spanClass({ tier: 3, facility: "none" }).key, "3", "an older API");
  assert.equal(spanClass({ tier: null, facility: "none", unpaved: true }).key, "unknown", "no tier: the unrated grey");
  assert.equal(routeClasses().filter((c) => isUnpavedClass(c.key)).length, 5);
});

test("the route's unpaved sections carry the dotted mark: a layer over them in their halo, the map's own dash", () => {
  const coords: [number, number][] = [[-77, 38.9], [-77, 38.91], [-77, 38.92]];
  const sections = routeSections(coords, [
    { from_m: 0, to_m: 1100, tier: 2, facility: "none", unpaved: false },
    { from_m: 1100, to_m: 2200, tier: 2, facility: "none", unpaved: true },
  ])!;
  assert.deepEqual(sections.map((s) => s.key), ["2", "u2"], "a change of surface is a new section");
  const features = sectionFeatures(sections).features;
  assert.deepEqual(features.map((f) => f.properties.unpaved), [false, true]);
  assert.equal(features[1].properties.markWidth, Math.max(1.5, features[1].properties.width * 0.4));
  const layer = routeUnpavedLayer("route-stress");
  assert.equal(layer.id, ROUTE_UNPAVED_LAYER_ID);
  assert.deepEqual(layer.filter, ["==", ["get", "unpaved"], true]);
  assert.deepEqual(layer.paint["line-color"], ["get", "halo"]);
  assert.deepEqual(layer.paint["line-dasharray"], UNPAVED_DASH);
  assert.ok(unpavedWidth({ width: 2.5 }) === 1.5);
  // Dimmed and shown with the sections.
  const paints: Record<string, unknown> = {};
  const map = { getSource: () => ({ setData: () => {} }), setPaintProperty: (id: string, name: string, value: unknown) => void (paints[`${id}.${name}`] = value) };
  setRouteSections(map as never, { geometry: { type: "LineString", coordinates: coords }, stress_spans: [{ from_m: 0, to_m: 2200, tier: 1, facility: "none", unpaved: true }] } as never, true);
  assert.equal(paints[`${ROUTE_UNPAVED_LAYER_ID}.line-opacity`], 0.45);
  setRouteSections(map as never, null, false);
  assert.equal(paints[`${ROUTE_UNPAVED_LAYER_ID}.line-opacity`], 0);
});
