// OWNER-DECISIONS 302: unpaved roads and trails in one brown ramp, light to dark from
// LTS 1 to Avoid, with each tier's own dash and width, on the map's overlay and the
// route's sections, and a dotted mark that is not colour. Measured against the ramps,
// the base map's own fills and the layers as the map would draw them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIGHT } from "@protomaps/basemaps";
import {
  DEFAULT_PALETTE,
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
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";
import { DEFAULT_CONFLICTS } from "./testSupport/defaultConflicts.ts";

type Tier = ReturnType<typeof tiersFor>[number];
type Layer = { id: string; paint: Record<string, unknown>; filter?: unknown };

/** The palettes the map is drawn in (twotone is the owner's alternative reading, reported only in places). */
const PALETTE_NAMES = Object.keys(PALETTES);
/** The default (two-tone since OWNER-DECISIONS 351) and the colour-blind-friendly palette; warm is an option, reported in places. */
const HELD = [DEFAULT_PALETTE, "cvd"];
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

test("the gaps' harshness never falls as stress rises on unpaved roads, from LTS 1 to Avoid, in every palette, plain and strong (292, 356)", (t) => {
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const h = tiers.map((x) => harshness(x.dash, x.unpavedGap, x.unpavedColor));
      t.diagnostic(`${palette}${strong ? " strong" : ""} unpaved: ` + tiers.map((x, i) => `${x.short} ${h[i].toFixed(2)}`).join(", "));
      for (let i = 1; i < h.length; i += 1) assert.ok(h[i - 1] <= h[i], `${palette}${strong ? " strong" : ""}: ${h.map((x) => x.toFixed(2)).join(" ")}`);
    }
  }
});

test("unpaved LTS 1 stands apart from its palette's paved LTS 3 line and LTS 3 casing, 15 CIEDE2000 or more under every vision", (t) => {
  for (const palette of PALETTE_NAMES) {
    const tiers = tiersFor(palette) as Tier[];
    const tan = tiers[0].unpavedColor;
    const against = { [`LTS 3 ${tiers[2].color}`]: tiers[2].color, [`LTS 3 casing ${tiers[2].casing}`]: tiers[2].casing };
    const deltas = Object.entries(against).map(([name, c]) => [name, worst(tan, c)] as const);
    t.diagnostic(`${palette} unpaved LTS 1 ${tan}: ` + deltas.map(([name, d]) => `${name} ${d.toFixed(1)}`).join(", "));
    // Every palette since OWNER-DECISIONS 350 (twotone's taupe was held to 9 beside its yellow before).
    for (const [name, d] of deltas) assert.ok(d >= 15, `${palette}: ${name} is ${d.toFixed(1)}`);
  }
});

// ---- OWNER-DECISIONS 350: "LTS3 looks unpaved" ----

test("paved and unpaved of the same tier are 10 CIEDE2000 or more apart under every vision, in every palette, but for the pairs reported (the re-check's SF-A)", (t) => {
  for (const palette of PALETTE_NAMES) {
    const tiers = tiersFor(palette) as Tier[];
    const close = tiers.filter((x) => worst(x.color, x.unpavedColor) < 10).map((x) => x.short);
    t.diagnostic(`${palette}: ` + tiers.map((x) => `${x.short} ${x.color}/${x.unpavedColor} ${VISIONS.map((v) => deltaE2000(simulate(x.color, v), simulate(x.unpavedColor, v)).toFixed(1)).join("/")}`).join("; "));
    assert.deepEqual(close, DEFAULT_CONFLICTS.unpavedSameTierClose[palette], palette);
    // The cue that is not colour is there for every one of them.
    assert.deepEqual(UNPAVED_DASH, [1, 1.2]);
  }
});

/**
 * The oranges a busy road's line is drawn beside: the higher-stress junction marker's fill, and
 * the Mass Ride orange (#f28e2b) the review of 350 named, which is not a token in this tree.
 */
const MARKER_ORANGES = { "higher-stress junction marker": SEVERITY_COLOURS.orange.fill, "Mass Ride orange": "#f28e2b" };

test("paved LTS 3 is 20 CIEDE2000 or more from every unpaved step under normal vision, in every palette, plain and strong (350)", (t) => {
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const lts3 = tiers[2];
      const normal = tiers.map((u) => deltaE2000(lts3.color, u.unpavedColor));
      const every = tiers.map((u) => worst(lts3.color, u.unpavedColor));
      t.diagnostic(`${palette}${strong ? " strong" : ""}: LTS 3 ${lts3.color} to unpaved ` + tiers.map((u, i) => `${u.short} ${u.unpavedColor} ${normal[i].toFixed(1)} (worst vision ${every[i].toFixed(1)})`).join(", "));
      tiers.forEach((u, i) => {
        assert.ok(normal[i] >= 20, `${palette}${strong ? " strong" : ""}: LTS 3 is ${normal[i].toFixed(1)} from unpaved ${u.short}`);
        // And still apart under every deficiency, where the dotted mark carries the rest.
        assert.ok(every[i] >= 10, `${palette}${strong ? " strong" : ""}: LTS 3 is ${every[i].toFixed(1)} from unpaved ${u.short} under some vision`);
      });
    }
  }
});

test("paved LTS 3's casing differs from every unpaved casing, and in the default it is not a brown (350, 351)", (t) => {
  for (const palette of PALETTE_NAMES) {
    for (const strong of STRENGTHS) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const casing = tiers[2].casing;
      const unpavedCasings = [...new Set(tiers.map((u) => u.unpavedCasing))];
      const deltas = unpavedCasings.map((c) => deltaE2000(casing, c));
      t.diagnostic(`${palette}${strong ? " strong" : ""}: LTS 3 casing ${casing} to ` + unpavedCasings.map((c, i) => `${c} ${deltas[i].toFixed(1)}`).join(", ") + (HELD.includes(palette) ? "" : " (reported: warm's amber-brown casing is the 350 look)"));
      if (!HELD.includes(palette)) continue;
      // 20 in the default, 10 in cvd (its navy against the black the switch gives its calm unpaved casings, about 13).
      deltas.forEach((d, i) => assert.ok(d >= (palette === DEFAULT_PALETTE ? 20 : 10), `${palette}${strong ? " strong" : ""}: LTS 3's casing ${casing} is ${d.toFixed(1)} from the unpaved casing ${unpavedCasings[i]}`));
    }
  }
  // The default's LTS 3: a yellow on an orange edge, neither of them a brown (a brown is a warm hue, dark, and of low to mid chroma).
  const brown = (hex: string) => {
    const [L, a, b] = lab(hex);
    const hue = (Math.atan2(b, a) * 180) / Math.PI;
    return hue > 30 && hue < 100 && L < 55 && Math.hypot(a, b) < 50;
  };
  for (const strong of STRENGTHS) {
    const lts3 = (tiersFor(DEFAULT_PALETTE, strong) as Tier[])[2];
    assert.ok(!brown(lts3.color) && !brown(lts3.casing), `${lts3.color} on ${lts3.casing}`);
  }
  assert.ok(brown(PALETTES.blended[3].casing), "the premise: warm's LTS 3 casing #45290a is one");
});

test("paved LTS 3 against the orange markers it is drawn beside (350): 12 CIEDE2000 or more under normal vision, and lighter (reported under each vision)", (t) => {
  for (const palette of HELD) {
    const lts3 = (tiersFor(palette) as Tier[])[2];
    for (const [name, orange] of Object.entries(MARKER_ORANGES)) {
      const d = deltaE2000(lts3.color, orange);
      t.diagnostic(`${palette} LTS 3 ${lts3.color} vs the ${name} ${orange}: ` + VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts3.color, v), simulate(orange, v)).toFixed(1)}`).join(", ") + `; ${contrastRatio(lts3.color, orange).toFixed(2)}:1`);
      assert.ok(d >= 12, `${palette}: LTS 3 is ${d.toFixed(1)} from the ${name}`);
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
  const tiers = tiersFor(DEFAULT_PALETTE) as Tier[];
  for (const tier of tiers) {
    const cls = spanClass({ tier: tier.tier, facility: "none", unpaved: true });
    assert.equal(cls.key, `u${tier.tier}`);
    // An unpaved Avoid on the route is the route's one Avoid magenta, with its dotted mark (OWNER-DECISIONS 397; routeColours.test.ts).
    if (tier.tier !== 5) {
      assert.equal(cls.color, tier.unpavedColor);
      assert.equal(cls.halo, tier.unpavedCasing);
    }
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

test("with the accessibility switch on, LTS 1's unpaved casing is pushed to black as the paved one is, and LTS 2's and the busy ones kept (292, 356)", () => {
  for (const palette of PALETTE_NAMES) {
    const plain = tiersFor(palette) as Tier[];
    const strong = tiersFor(palette, true) as Tier[];
    strong.forEach((tier, i) => {
      if (tier.tier === 1) assert.equal(tier.unpavedCasing, "#000000", `${palette} ${tier.short}: the dark brown casing goes black`);
      else if (tier.tier === 2) assert.equal(tier.unpavedCasing, plain[i].unpavedCasing, `${palette} LTS 2: its edge is kept (OWNER-DECISIONS 356)`);
      else assert.equal(tier.unpavedCasing, plain[i].unpavedCasing, `${palette} ${tier.short}: a busy casing is kept, its gaps no harsher`);
      assert.equal(tier.unpavedColor, plain[i].unpavedColor, "the brown itself is the same");
    });
  }
});
