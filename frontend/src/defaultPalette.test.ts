// OWNER-DECISIONS 351: the two-tone palette is the default, in the owner's colours. The rules
// still apply on top (the unpaved ramp, 283's ink ladder, 292's harshness, 3:1, colour vision),
// and where the owner's colours break one the break is reported, not fixed: these tests hold the
// default to every rule it keeps and to exactly the breaks in testSupport/defaultConflicts.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIGHT } from "@protomaps/basemaps";
import {
  ACCESSIBILITY_PALETTE,
  DEFAULT_PALETTE,
  PALETTES,
  PALETTE_LINK_NAMES,
  contrastRatio,
  gapHarshness,
  relativeLuminance,
  resolvePalette,
  tiersFor,
} from "./stressStyle.js";
import { VISIONS, deltaE2000, lab, simulate } from "./testSupport/colourVision.ts";
import { DEFAULT_CONFLICTS } from "./testSupport/defaultConflicts.ts";
import { SEVERITY_COLOURS } from "./lib/intersectionMarkers.ts";

type Tier = ReturnType<typeof tiersFor>[number];
const STRENGTHS = [false, true];
const PANELS = ["#ffffff", "#1b1e24", "#f3f4f6", "#262a32"]; // styles.css --bg and --bg-soft, light and dark
const chroma = (hex: string) => Math.hypot(lab(hex)[1], lab(hex)[2]);
const worst = (a: string, b: string) => Math.min(...VISIONS.map((v) => deltaE2000(simulate(a, v), simulate(b, v))));
const legible = (t: Tier, under: string) => Math.max(contrastRatio(t.color, under), Math.min(contrastRatio(t.casing, under), contrastRatio(t.color, t.casing)));
const coverage = (dash: number[] | null) => (dash ? dash.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0) / dash.reduce((a, b) => a + b, 0) : 1);
const SURFACES = Object.entries(LIGHT as unknown as Record<string, unknown>)
  .filter(([k, v]) => typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) && /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|water|minor|major$|buildings)/.test(k) && !k.includes("casing"))
  .map(([, v]) => (v as string).toLowerCase());

test("the default is the two-tone palette, the warm one is still there, and the switch is still the cool one", () => {
  assert.equal(DEFAULT_PALETTE, "twotone");
  assert.equal(resolvePalette("", false), "twotone", "no address parameter needed for the default");
  assert.equal(resolvePalette("?palette=warm", false), "blended", "warm by address");
  assert.equal(ACCESSIBILITY_PALETTE, "cvd");
  assert.equal(PALETTE_LINK_NAMES.cvd, "cool");
  // The owner's colours, as 351 lists them (LTS 4's edge is #c81e1e, which 292 chose over #d42020; reported).
  assert.deepEqual(PALETTES.twotone[1], { color: "#9ed3ac", casing: "#2f5d47" }, "LTS 1's softer edge (357)");
  assert.deepEqual(PALETTES.twotone[2], { color: "#57a06c", casing: "#1a2638", gap: "#7a8fa3" }, "LTS 2's blue edge and gaps (356)");
  assert.deepEqual(PALETTES.twotone[3], { color: "#f2c21b", casing: "#f28c28" });
  assert.deepEqual(PALETTES.twotone[4], { color: "#f28c28", casing: "#c81e1e" });
  assert.deepEqual(PALETTES.twotone[5], { color: "#d42020", casing: "#111111" });
});

test("held: ink rises strictly from LTS 1 to Avoid (283) and harshness from LTS 1 to Avoid (292, 356), plain and strong", (t) => {
  for (const strong of STRENGTHS) {
    const tiers = tiersFor(DEFAULT_PALETTE, strong) as Tier[];
    const ink = tiers.map((x) => coverage(x.dash) * x.width);
    const h = tiers.map((x) => gapHarshness(x));
    t.diagnostic(`${strong ? "strong" : "plain"}: ink ${ink.map((v) => v.toFixed(2)).join(" ")}; harshness ${h.map((v) => v.toFixed(2)).join(" ")}`);
    // Ink is held plain, as stressSalience.test.ts holds it (the switch's half pixel ties LTS 1's solid line with LTS 2's dashes).
    if (!strong) for (let i = 1; i < ink.length; i += 1) assert.ok(ink[i] > ink[i - 1]);
    for (let i = 1; i < h.length; i += 1) assert.ok(h[i - 1] <= h[i], h.map((v) => v.toFixed(2)).join(" "));
  }
});

test("held: paved LTS 3 is 20 CIEDE2000 or more from every unpaved step (normal vision) and 10 under every vision (350)", (t) => {
  const tiers = tiersFor(DEFAULT_PALETTE) as Tier[];
  const yellow = tiers[2].color;
  t.diagnostic(tiers.map((u) => `${u.short} ${u.unpavedColor} ${deltaE2000(yellow, u.unpavedColor).toFixed(1)} / ${worst(yellow, u.unpavedColor).toFixed(1)}`).join(", "));
  for (const u of tiers) {
    assert.ok(deltaE2000(yellow, u.unpavedColor) >= 20, u.short);
    assert.ok(worst(yellow, u.unpavedColor) >= 10, u.short);
  }
});

test("held: the calm tiers, Avoid and the unpaved browns are 3:1 on the base map; reported: LTS 3 and LTS 4 are not (351)", (t) => {
  for (const strong of STRENGTHS) {
    const tiers = tiersFor(DEFAULT_PALETTE, strong) as Tier[];
    const failing = new Set<string>();
    for (const tier of tiers) {
      for (const under of [...SURFACES, "#ffffff"]) if (legible(tier, under) < 3) failing.add(tier.short);
      if (tier.tier >= 3 && contrastRatio(tier.color, tier.casing) < 3) failing.add(tier.short);
    }
    t.diagnostic(`${strong ? "strong" : "plain"}: ` + tiers.map((x) => `${x.short} line on edge ${contrastRatio(x.color, x.casing).toFixed(2)}:1, on the earth ${legible(x, LIGHT.earth as string).toFixed(2)}:1`).join("; "));
    assert.deepEqual([...failing].sort(), [...DEFAULT_CONFLICTS.belowThreeToOne].sort());
  }
});

test("reported: greyscale order (LTS 3 the lightest, LTS 4 lighter than LTS 2), though every neighbour is still 1.4:1 apart (351)", (t) => {
  const tiers = (tiersFor(DEFAULT_PALETTE) as Tier[]).filter((x) => x.tier <= 4);
  const lum = tiers.map((x) => relativeLuminance(x.color));
  t.diagnostic(tiers.map((x, i) => `${x.short} ${lum[i].toFixed(3)}`).join(", "));
  const outOfOrder = tiers.filter((x, i) => i > 0 && lum.slice(0, i).some((l) => l <= lum[i])).map((x) => x.short);
  assert.deepEqual(outOfOrder, [...DEFAULT_CONFLICTS.greyscaleOutOfOrder]);
  for (let i = 1; i < tiers.length; i += 1) assert.ok(contrastRatio(tiers[i].color, tiers[i - 1].color) >= 1.4, `${tiers[i - 1].short}-${tiers[i].short}`);
});

test("reported: for a deuteranope only LTS 3 and LTS 4 are under 1.4:1 apart in grey (351)", (t) => {
  const tiers = tiersFor(DEFAULT_PALETTE) as Tier[];
  const close: string[][] = [];
  for (let i = 1; i < tiers.length; i += 1) {
    const r = contrastRatio(simulate(tiers[i].color, "deutan"), simulate(tiers[i - 1].color, "deutan"));
    t.diagnostic(`${tiers[i - 1].short}-${tiers[i].short} ${r.toFixed(2)}:1`);
    if (r < 1.4 && i !== 2) close.push([tiers[i - 1].short, tiers[i].short]); // LTS 2-3 was never held (stressStyle.test.mjs)
  }
  assert.deepEqual(close, DEFAULT_CONFLICTS.deuteranopeTooClose.map((p) => [...p]));
});

test("reported: 274's salience - LTS 4 is not more saturated than LTS 3; held: it is more contrasting on the base map, and Avoid more still", (t) => {
  const [, , lts3, lts4, avoid] = tiersFor(DEFAULT_PALETTE) as Tier[];
  t.diagnostic(`chroma LTS 3 ${chroma(lts3.color).toFixed(1)}, LTS 4 ${chroma(lts4.color).toFixed(1)}`);
  assert.equal(chroma(lts4.color) < chroma(lts3.color) + 10, DEFAULT_CONFLICTS.lts4NotMoreSaturated);
  const on = (hex: string) => contrastRatio(hex, "#f5f3ef");
  assert.ok(on(lts3.color) < on(lts4.color) && on(lts4.color) < on(avoid.color));
});

test("Avoid against LTS 4: held - the dash-dot, the width and the edge (3:1 apart); reported - the lines 17.8 apart under deuteranopia, and Avoid on the dark soft panel (351)", (t) => {
  const [lts4, avoid] = [tiersFor(DEFAULT_PALETTE)[3], tiersFor(DEFAULT_PALETTE)[4]] as Tier[];
  assert.ok(avoid.dash!.length > lts4.dash!.length && avoid.width >= lts4.width * 1.15);
  assert.ok(contrastRatio(avoid.casing, lts4.casing) >= 3);
  t.diagnostic(`lines ${VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts4.color, v), simulate(avoid.color, v)).toFixed(1)}`).join(", ")}`);
  assert.equal(worst(lts4.color, avoid.color) < 20, DEFAULT_CONFLICTS.avoidNearLts4);
  const dark = PANELS.filter((bg) => legible(avoid, bg) < 3);
  t.diagnostic(PANELS.map((bg) => `${bg} ${legible(avoid, bg).toFixed(2)}:1`).join(", "));
  assert.deepEqual(dark, [...DEFAULT_CONFLICTS.avoidOnDarkPanel]);
});

test("paved LTS 3 against the orange markers (350): the junction marker and the Mass Ride orange, reported under each vision; the line's orange edge is the Mass Ride orange's near twin", (t) => {
  const lts3 = (tiersFor(DEFAULT_PALETTE) as Tier[])[2];
  for (const [name, orange] of Object.entries({ "junction marker": SEVERITY_COLOURS.orange.fill, "Mass Ride": "#f28e2b" })) {
    t.diagnostic(`${lts3.color} vs ${name} ${orange}: ` + VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts3.color, v), simulate(orange, v)).toFixed(1)}`).join(", ") + `; its edge ${lts3.casing} ${deltaE2000(lts3.casing, orange).toFixed(1)}`);
    assert.ok(deltaE2000(lts3.color, orange) >= 12, `${name}: ${deltaE2000(lts3.color, orange).toFixed(1)}`);
  }
});
