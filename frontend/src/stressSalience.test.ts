// OWNER-DECISIONS 274 (visual weight rises with stress; Avoid is told from
// LTS 4 by more than hue) and 276, 277 (the three bike-facility rails are told
// apart by shape first, painted the weakest). Measured against the palettes
// and the facility definitions, not against numbers typed into the test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  FACILITIES,
  FACILITY_DRAW_ORDER,
  PALETTES,
  contrastRatio,
  facilityLayers,
  gapHarshness,
  gapLayers,
  ringLayers,
  relativeLuminance,
  tiersFor,
} from "./stressStyle.js";
import { VISIONS, deltaE2000, lab, simulate } from "./testSupport/colourVision.ts";
import { paintAt } from "./testSupport/paintAt.ts";

type PaintLayer = { id: string; paint: Record<string, unknown>; filter?: unknown };
import { FACILITY_CLASSES } from "./lib/facilityBar.ts";
import { ROUTE_SECTION_WIDTHS } from "./lib/routeColours.ts";
import { UNRATED, UNRATED_CVD_COLOUR } from "./lib/stressBar.ts";

type Tier = ReturnType<typeof tiersFor>[number];

/** The warm palette (the default until OWNER-DECISIONS 351), which these rules were tuned on; the default two-tone is held in defaultPalette.test.ts. */
const WARM = "blended";

const LIGHT_BASE = "#f5f3ef";
const DARK_PANELS = ["#1b1e24", "#262a32"]; // styles.css --bg and --bg-soft, dark theme
const chroma = (hex: string) => Math.hypot(lab(hex)[1], lab(hex)[2]);
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

/** Share of a dash pattern that is drawn (a solid [1] is 1; the even-indexed entries are dashes, the odd gaps). */
function coverage(dash: number[]): number {
  if (dash.length === 1) return 1;
  const on = dash.filter((_, i) => i % 2 === 0).reduce((a, b) => a + b, 0);
  return on / dash.reduce((a, b) => a + b, 0);
}

/** The smallest CIEDE2000 between two colours over normal vision and each simulated deficiency. */
function worst(a: string, b: string): { delta: number; vision: string } {
  return VISIONS.map((vision) => ({ vision: String(vision), delta: deltaE2000(simulate(a, vision), simulate(b, vision)) })).reduce((x, y) => (y.delta < x.delta ? y : x));
}

// ---------------------------------------------------------------------------
// 274: salience rises with stress
// ---------------------------------------------------------------------------

test("salience: in the warm palette the line gets more saturated from LTS 3 to LTS 4, and more contrasting from LTS 3 up", (t) => {
  const tiers = tiersFor(WARM);
  const [c3, c4, c5] = [tiers[2], tiers[3], tiers[4]].map((x: Tier) => x.color);
  t.diagnostic(`CIELAB chroma LTS 3 ${chroma(c3).toFixed(1)}, LTS 4 ${chroma(c4).toFixed(1)}, Avoid ${chroma(c5).toFixed(1)}`);
  assert.ok(chroma(c4) >= chroma(c3) + 10, `LTS 4 chroma ${chroma(c4).toFixed(1)} is not clearly above LTS 3's ${chroma(c3).toFixed(1)}`);
  // LTS 4 reads as red and LTS 3 as amber: hue angle in CIELAB (about 40 is red, 70 amber-orange).
  const hue = (hex: string) => (Math.atan2(lab(hex)[2], lab(hex)[1]) * 180) / Math.PI;
  assert.ok(hue(c4) < 45 && hue(c3) > 60 && hue(c3) < 90, `hues ${hue(c3).toFixed(0)} and ${hue(c4).toFixed(0)}`);
  const on = (hex: string) => contrastRatio(hex, LIGHT_BASE);
  t.diagnostic(`contrast on the base map LTS 3 ${on(c3).toFixed(2)}, LTS 4 ${on(c4).toFixed(2)}, Avoid ${on(c5).toFixed(2)}`);
  assert.ok(on(c3) < on(c4) && on(c4) < on(c5), "contrast against the base map rises from LTS 3 to Avoid");
});

test("salience: line width rises with the tier, strictly from LTS 2 up, in every palette, on the overlay and on the route", () => {
  for (const palette of Object.keys(PALETTES)) {
    const widths = tiersFor(palette).map((x: Tier) => x.width);
    for (let i = 1; i < widths.length; i += 1) assert.ok(widths[i] >= widths[i - 1], `${palette}: ${widths}`);
    for (let i = 2; i < widths.length; i += 1) assert.ok(widths[i] > widths[i - 1], `${palette}: ${widths}`);
  }
  const route = ["path", "1", "2", "3", "4", "5"].map((k) => ROUTE_SECTION_WIDTHS[k as keyof typeof ROUTE_SECTION_WIDTHS]);
  for (let i = 1; i < route.length; i += 1) assert.ok(route[i] >= route[i - 1], `route widths ${route}`);
  for (let i = 3; i < route.length; i += 1) assert.ok(route[i] > route[i - 1], `route widths ${route}`);
});

test("salience: ink - the share of the line drawn (dash duty cycle) times its width - rises strictly from LTS 1 to Avoid, in every palette (OWNER-DECISIONS 283)", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    const ink = tiersFor(palette).map((x: Tier) => coverage(x.dash ?? [1]) * x.width);
    t.diagnostic(`${palette}: duty ${tiersFor(palette).map((x: Tier) => coverage(x.dash ?? [1]).toFixed(2)).join(" ")}; ink ${ink.map((v: number) => v.toFixed(2)).join(" ")}`);
    for (let i = 1; i < ink.length; i += 1) assert.ok(ink[i] > ink[i - 1], `${palette}: ink ${ink.map((v: number) => v.toFixed(2))}`);
  }
});

test("salience: LTS 4 is near-solid and heavy: at least 85% of the line drawn, the heaviest of the Furth tiers, and the calm tiers are lighter", () => {
  const tiers = tiersFor(WARM) as Tier[];
  assert.ok(coverage(tiers[3].dash ?? [1]) >= 0.85, `${coverage(tiers[3].dash ?? [1])}`);
  assert.ok(coverage(tiers[3].dash ?? [1]) > coverage(tiers[2].dash ?? [1]), "denser than LTS 3");
  assert.ok(coverage(tiers[3].dash ?? [1]) > coverage(tiers[1].dash ?? [1]), "denser than LTS 2");
  assert.equal(tiers[0].dash, null, "the calmest tier is a thin solid line");
});

test("the tiers' dash patterns still differ pairwise, and their on-lengths in pixels differ by 15% or more, so they read in greyscale", () => {
  const tiers = tiersFor(WARM) as Tier[];
  const dashed = tiers.filter((x) => x.dash);
  for (let i = 0; i < dashed.length; i += 1) {
    for (let j = i + 1; j < dashed.length; j += 1) {
      const [a, b] = [dashed[i], dashed[j]];
      assert.notDeepEqual(a.dash, b.dash, `${a.short} and ${b.short}`);
      const onA = a.dash![0] * a.width, onB = b.dash![0] * b.width;
      assert.ok(Math.abs(onA - onB) / Math.max(onA, onB) >= 0.15 || a.width !== b.width, `${a.short} ${onA}px, ${b.short} ${onB}px`);
    }
  }
});

// ---------------------------------------------------------------------------
// 292: no calmer tier's gaps are harsher than a busier one's
// ---------------------------------------------------------------------------

/** Harshness measured here, from the dash and the colours, not from gapHarshness: gap share times the gap colour's contrast with the line (the casing's where the tier has no gap colour, OWNER-DECISIONS 356). */
function harshness(t: Tier): number {
  if (!t.dash) return 0;
  const gaps = t.dash.filter((_: number, i: number) => i % 2 === 1).reduce((a: number, b: number) => a + b, 0);
  return (gaps / t.dash.reduce((a: number, b: number) => a + b, 0)) * contrastRatio(t.gap ?? t.casing, t.color);
}

test("harshness - gap share times gap-vs-line contrast - never falls as stress rises, from LTS 1 to Avoid, in every palette, plain and strong (292, 356)", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      const tiers = tiersFor(palette, strong) as Tier[];
      const h = tiers.map(harshness);
      t.diagnostic(`${palette}${strong ? " strong" : ""}: ` + tiers.map((x, i) => `${x.short} ${h[i].toFixed(2)}`).join(", "));
      tiers.forEach((x, i) => assert.ok(Math.abs(gapHarshness(x) - h[i]) < 1e-12, `gapHarshness ${x.short}`));
      // From LTS 1 up since 356 ("LTS2 can almost be harsher than LTS3"): no calmer tier's gaps are harsher.
      assert.ok(h[0] <= h[1], `${palette}${strong ? " strong" : ""}: LTS 1 ${h[0].toFixed(3)} is harsher than LTS 2 ${h[1].toFixed(3)}`);
      assert.ok(h[1] <= h[2], `${palette}${strong ? " strong" : ""}: LTS 2 ${h[1].toFixed(3)} is harsher than LTS 3 ${h[2].toFixed(3)}`);
      assert.ok(h[2] <= h[3], `${palette}${strong ? " strong" : ""}: LTS 3 ${h[2].toFixed(3)} is harsher than LTS 4 ${h[3].toFixed(3)}`);
      assert.ok(h[3] <= h[4], `${palette}${strong ? " strong" : ""}: LTS 4 ${h[3].toFixed(3)} is harsher than Avoid ${h[4].toFixed(3)}`);
    }
  }
});

test("LTS 3's gaps are calmer than before: a softer casing and a smaller gap, the halo still 3:1 and the casing still dark", () => {
  for (const strong of [false, true]) {
    const lts3 = tiersFor(WARM, strong)[2] as Tier;
    assert.ok(harshness(lts3) < 0.67, `${harshness(lts3).toFixed(2)}`);
    assert.ok(contrastRatio(lts3.color, lts3.casing) >= 3, `amber on its casing ${contrastRatio(lts3.color, lts3.casing).toFixed(2)}:1`);
    assert.ok(contrastRatio(lts3.casing, LIGHT_BASE) >= 3, "the casing holds the halo on the base map");
    assert.ok(relativeLuminance(lts3.casing) > relativeLuminance("#2b1a05"), "softer than the old near-black");
  }
  // "That black in the LTS3": no palette puts pure black in LTS 3's gaps, with the switch off or on.
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      const casing = (tiersFor(palette, strong)[2] as Tier).casing.toLowerCase();
      assert.notEqual(casing, "#000000", `${palette}${strong ? " strong" : ""}: LTS 3 over black`);
    }
  }
  // The old LTS 3, for the record: [2, 1] over #2b1a05.
  const old = { ...(tiersFor(WARM)[2] as Tier), dash: [2, 1], casing: "#2b1a05", gap: "#2b1a05" } as Tier;
  assert.ok(harshness(old) > 1.4);
});

test("LTS 2 and LTS 3 still read apart without colour: dash length and rhythm differ by 30% or more, and the width", () => {
  const [, lts2, lts3] = tiersFor(WARM) as Tier[];
  const on = (x: Tier) => x.dash![0] * x.width;
  const period = (x: Tier) => (x.dash![0] + x.dash![1]) * x.width;
  assert.ok(Math.abs(on(lts2) - on(lts3)) / Math.max(on(lts2), on(lts3)) >= 0.3, `${on(lts2)} vs ${on(lts3)} px`);
  assert.ok(Math.abs(period(lts2) - period(lts3)) / Math.max(period(lts2), period(lts3)) >= 0.3, `${period(lts2)} vs ${period(lts3)} px`);
  assert.ok(lts3.width >= lts2.width + 0.75);
});

test("LTS 3 against LTS 2 and LTS 4 under each vision, lines and casings (deuteranopia's luminance held, ΔE reported)", (t) => {
  const [, lts2, lts3, lts4] = tiersFor(WARM) as Tier[];
  for (const [name, other] of [["LTS 2", lts2], ["LTS 4", lts4]] as const) {
    t.diagnostic(
      `LTS 3 vs ${name}: line ` + VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts3.color, v), simulate(other.color, v)).toFixed(1)}`).join(", ") +
        `; casing ` + VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts3.casing, v), simulate(other.casing, v)).toFixed(1)}`).join(", ") +
        `; luminance (deutan) ${contrastRatio(simulate(lts3.color, "deutan"), simulate(other.color, "deutan")).toFixed(2)}:1`,
    );
  }
  // LTS 3 vs LTS 4 keep 1.4:1 in grey under deuteranopia, and their casings are worlds apart.
  assert.ok(contrastRatio(simulate(lts3.color, "deutan"), simulate(lts4.color, "deutan")) >= 1.4);
  for (const v of VISIONS) assert.ok(contrastRatio(simulate(lts3.casing, v), simulate(lts4.casing, v)) >= 7, `casings under ${v}`);
});

// ---------------------------------------------------------------------------
// 274: Avoid against LTS 4, by more than hue
// ---------------------------------------------------------------------------

test("Avoid vs LTS 4: dash-dot, width and (default palette) casing differ in every palette, so colour is never the only cue", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    const [lts4, avoid] = [tiersFor(palette)[3], tiersFor(palette)[4]];
    t.diagnostic(
      `${palette}: LTS 4 ${lts4.color} on ${lts4.casing}, ${lts4.width}px ${JSON.stringify(lts4.dash)}; Avoid ${avoid.color} on ${avoid.casing}, ${avoid.width}px ${JSON.stringify(avoid.dash)}`,
    );
    assert.notDeepEqual(avoid.dash, lts4.dash, `${palette}: the same dash`);
    assert.ok(avoid.dash.length > lts4.dash.length, `${palette}: Avoid is a dash-dot, LTS 4 a dash`);
    assert.ok(avoid.width >= lts4.width * 1.15, `${palette}: ${avoid.width}px against ${lts4.width}px`);
  }
});

test("Avoid vs LTS 4: in the warm palette the casing differs too, and the colours stand apart (greyscale and CIEDE2000)", (t) => {
  const [lts4, avoid] = [tiersFor(WARM)[3], tiersFor(WARM)[4]];
  assert.notEqual(lts4.casing, avoid.casing);
  assert.ok(contrastRatio(avoid.casing, lts4.casing) >= 3, "the casings differ in lightness, not just hue");
  const delta = worst(lts4.color, avoid.color);
  t.diagnostic(`LTS 4 vs Avoid line: CIEDE2000 ${delta.delta.toFixed(1)} at worst (${delta.vision}), ${contrastRatio(lts4.color, avoid.color).toFixed(2)}:1; casings ${deltaE2000(lts4.casing, avoid.casing).toFixed(1)}`);
  assert.ok(delta.delta >= 20, `${delta.delta.toFixed(1)} under ${delta.vision}`);
  assert.ok(contrastRatio(lts4.color, avoid.color) >= 2.5);
  // The old pair, for the record: both dark, low-chroma reds.
  const [old4, old5] = ["#a32814", "#4a0810"];
  t.diagnostic(`the old pair: CIEDE2000 ${deltaE2000(old4, old5).toFixed(1)}, ${contrastRatio(old4, old5).toFixed(2)}:1`);
  assert.ok(delta.delta > deltaE2000(old4, old5));
});

test("Avoid vs LTS 4 under each deficiency, in all three palettes (reported)", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    const [lts4, avoid] = [tiersFor(palette)[3], tiersFor(palette)[4]];
    t.diagnostic(
      `${palette}: ` + VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts4.color, v), simulate(avoid.color, v)).toFixed(1)}`).join(", ") + `; casings ${lts4.casing}/${avoid.casing}`,
    );
  }
});

test("Avoid vs LTS 4 in the colour-blind-friendly palette the switch turns on, plain and strong: the casings differ (white, light yellow) as much as the default's do (the a11y review's SF5)", (t) => {
  for (const strong of [false, true]) {
    const [lts4, avoid] = [tiersFor("cvd", strong)[3], tiersFor("cvd", strong)[4]];
    const line = Math.min(...(["protan", "deutan"] as const).map((v) => deltaE2000(simulate(lts4.color, v), simulate(avoid.color, v))));
    const casings = VISIONS.map((v) => `${v} ${deltaE2000(simulate(lts4.casing, v), simulate(avoid.casing, v)).toFixed(1)}`).join(", ");
    // Under normal vision and the two red-green deficiencies the switch is mostly for (tritanopia reported).
    const casing = Math.min(...(["normal", "protan", "deutan"] as const).map((v) => deltaE2000(simulate(lts4.casing, v), simulate(avoid.casing, v))));
    t.diagnostic(`cvd${strong ? " strong" : ""}: LTS 4 ${lts4.color} on ${lts4.casing}, Avoid ${avoid.color} on ${avoid.casing}; lines ${line.toFixed(1)} at worst under protanopia and deuteranopia, casings ${casings}`);
    // The rule: the casing differs, or the lines are 20 apart under protanopia and deuteranopia. The lines are not (a protanope sees the dark red as near-black), so the casing must.
    assert.ok(lts4.casing !== avoid.casing || line >= 20, `cvd${strong ? " strong" : ""}: the same casing and lines ${line.toFixed(1)} apart`);
    assert.notEqual(avoid.casing.toLowerCase(), "#ffffff", "not white: LTS 4's is");
    assert.notEqual(avoid.casing.toLowerCase(), tiersFor("cvd", strong)[2].color.toLowerCase(), "not LTS 3's orange");
    assert.ok(casing >= 20, `the casings are ${casing.toFixed(1)} apart at worst`);
    assert.ok(contrastRatio(avoid.color, avoid.casing) >= 3, `Avoid's line on its casing ${contrastRatio(avoid.color, avoid.casing).toFixed(2)}:1`);
  }
});

test("the 3:1 line-to-casing floor: every busy line (LTS 3, LTS 4, Avoid) keeps 3:1 or more against its casing with the accessibility switch on, in the palettes the map is drawn in (twotone reported)", (t) => {
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of [false, true]) {
      const busy = (tiersFor(palette, strong) as Tier[]).filter((x) => x.tier >= 3);
      t.diagnostic(`${palette}${strong ? " strong" : ""}: ` + busy.map((x) => `${x.short} ${contrastRatio(x.color, x.casing).toFixed(2)}:1`).join(", "));
      if (palette === "twotone") continue; // the owner's reading to compare, which does not hold 3:1 (stressStyle.js)
      for (const x of busy) {
        assert.ok(contrastRatio(x.color, x.casing) >= 3, `${palette}${strong ? " strong" : ""} ${x.short}: ${contrastRatio(x.color, x.casing).toFixed(2)}:1`);
      }
    }
  }
});

test("Avoid's line is 3:1 from its casing in every palette, and in the warm one the pair is 3:1 from the base map and both dark panels", () => {
  for (const palette of Object.keys(PALETTES)) {
    const avoid = tiersFor(palette)[4];
    assert.ok(contrastRatio(avoid.color, avoid.casing) >= 3, `${palette}: line on casing ${contrastRatio(avoid.color, avoid.casing).toFixed(2)}:1`);
  }
  const avoid = tiersFor(WARM)[4];
  for (const bg of [LIGHT_BASE, ...DARK_PANELS]) {
    const legible = Math.max(contrastRatio(avoid.color, bg), Math.min(contrastRatio(avoid.casing, bg), contrastRatio(avoid.color, avoid.casing)));
    assert.ok(legible >= 3, `${bg}: ${legible.toFixed(2)}:1`);
  }
});

test("the stress bar and the swatches carry Avoid's own pattern, in the tier's casing colour, 3:1 from its fill", () => {
  const rule = css.match(/\.stress-seg-5 \{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /repeating-linear-gradient\(45deg, var\(--seg-accent/);
  assert.match(rule, /repeating-linear-gradient\(-45deg, var\(--seg-accent/, "a cross-hatch, which no other tier has");
  for (const n of [2, 3, 4]) {
    assert.doesNotMatch(css.match(new RegExp(`\\.stress-seg-${n} \\{([^}]*)\\}`))?.[1] ?? "", /var\(--seg-accent/);
  }
  for (const palette of Object.keys(PALETTES)) {
    const avoid = tiersFor(palette)[4];
    assert.ok(contrastRatio(avoid.casing, avoid.color) >= 3, `${palette}: the hatch is ${contrastRatio(avoid.casing, avoid.color).toFixed(2)}:1 on the fill`);
  }
  const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
  assert.ok((app.match(/--seg-accent/g) ?? []).length >= 2, "both the bar's segments and the list's swatches set the accent");
});

// ---------------------------------------------------------------------------
// 276, 277: the three bike-facility rails
// ---------------------------------------------------------------------------

type Facility = { facility: string; short: string; label: string; color: string; rail: number; dash: number[] | null };
const [PATH, PROTECTED, PAINTED] = FACILITIES as Facility[];

test("the facilities are listed path, protected, painted: the real infrastructure first and the paint last", () => {
  assert.deepEqual(FACILITIES.map((f: Facility) => f.facility), ["path", "protected", "lane"]);
  assert.deepEqual(FACILITY_CLASSES.slice(0, 3).map((c) => c.key), ["path", "protected", "lane"]);
  assert.equal(PAINTED.label, "Painted lane (no separation)");
  assert.equal(FACILITY_CLASSES[2].label, "Painted lane (no separation)");
});

test("the rails differ pairwise in pattern, not only in colour: solid, blocks, sparse dots", () => {
  const key = (f: Facility) => JSON.stringify([f.rail, f.dash]);
  assert.equal(new Set([PATH, PROTECTED, PAINTED].map(key)).size, 3);
  assert.equal(PATH.dash, null, "a path's rails are solid");
  assert.ok(PROTECTED.dash && PROTECTED.dash[0] >= 0.25 && PROTECTED.dash[1] >= 0.25, "a protected lane's rails are broken into blocks");
  assert.ok(PAINTED.dash && PAINTED.dash[1] > PAINTED.dash[0] * 2, "painted's dots are far apart");
  for (const [a, b] of [[PATH, PROTECTED], [PATH, PAINTED], [PROTECTED, PAINTED]]) {
    assert.notDeepEqual(a.dash, b.dash, `${a.facility} and ${b.facility} share a dash`);
  }
});

test("painted is strictly the weakest rail: the thinnest, the sparsest and the lowest contrast with the base map (277)", (t) => {
  assert.ok(PAINTED.rail < PROTECTED.rail && PAINTED.rail < PATH.rail, `${PAINTED.rail} vs ${PROTECTED.rail}, ${PATH.rail}`);
  assert.ok(PAINTED.rail <= 1, "the thinnest line on the map: a pixel");
  const share = (f: Facility) => (f.dash ? coverage(f.dash) : 1);
  assert.ok(share(PAINTED) < share(PROTECTED) && share(PROTECTED) < share(PATH));
  assert.ok(share(PAINTED) <= 0.3, "sparse");
  const light = (f: Facility) => contrastRatio(f.color, LIGHT_BASE);
  t.diagnostic(`contrast with the base map: path ${light(PATH).toFixed(2)}, protected ${light(PROTECTED).toFixed(2)}, painted ${light(PAINTED).toFixed(2)}`);
  assert.ok(light(PAINTED) < light(PROTECTED) && light(PAINTED) < light(PATH));
  // The weakest that still passes: 3:1 on the light base and on both dark panels, and not paler than needed.
  assert.ok(light(PAINTED) >= 3);
  for (const bg of DARK_PANELS) assert.ok(contrastRatio(PAINTED.color, bg) >= 3, `painted on ${bg}: ${contrastRatio(PAINTED.color, bg).toFixed(2)}:1`);
  assert.ok(light(PAINTED) < 3.5, `painted is ${light(PAINTED).toFixed(2)}:1, more than it needs`);
  for (const f of [PATH, PROTECTED]) assert.ok(light(f) >= 3, f.facility);
});

test("painted is drawn under protected, and protected under path", () => {
  assert.deepEqual(FACILITY_DRAW_ORDER, ["lane", "protected", "path"]);
  assert.deepEqual(facilityLayers("s").map((l: { id: string }) => l.id), ["facility-lane", "facility-protected", "facility-path"]);
});

test("the three rail colours differ pairwise, and from every stress colour, the route's blue and the unrated greys (reported under each vision)", (t) => {
  const FLOOR = 15; // normal vision, CIEDE2000
  const rails = [PATH, PROTECTED, PAINTED];
  for (let i = 0; i < rails.length; i += 1) {
    for (let j = i + 1; j < rails.length; j += 1) {
      const d = deltaE2000(rails[i].color, rails[j].color);
      assert.ok(d >= FLOOR, `${rails[i].facility} vs ${rails[j].facility}: ${d.toFixed(1)}`);
    }
  }
  const others: Record<string, string> = { "route blue": "#1d4ed8", "unrated grey": UNRATED.color, "unrated grey (cvd)": UNRATED_CVD_COLOUR };
  for (const palette of Object.keys(PALETTES)) for (const tier of tiersFor(palette)) others[`${palette} ${tier.short}`] = tier.color;
  for (const f of rails) {
    let closest = { name: "", delta: Infinity };
    let worstSeen = { name: "", delta: Infinity, vision: "" };
    for (const [name, colour] of Object.entries(others)) {
      const d = deltaE2000(f.color, colour);
      if (d < closest.delta) closest = { name, delta: d };
      const w = worst(f.color, colour);
      if (w.delta < worstSeen.delta) worstSeen = { name, delta: w.delta, vision: w.vision };
    }
    t.diagnostic(`${f.facility} ${f.color}: closest colour ${closest.name} ${closest.delta.toFixed(1)}; under any vision ${worstSeen.name} ${worstSeen.delta.toFixed(1)} (${worstSeen.vision})`);
    assert.ok(closest.delta >= FLOOR, `${f.facility} is ${closest.delta.toFixed(1)} from ${closest.name}`);
    assert.notEqual(f.color.toLowerCase(), "#1d4ed8");
  }
});

test("the facility bar and its swatches match the rails: the same colours, and a pattern for each that is not colour", () => {
  assert.deepEqual(
    FACILITY_CLASSES.slice(0, 3).map((c) => c.color),
    [PATH.color, PROTECTED.color, PAINTED.color],
  );
  assert.doesNotMatch(css.match(/\.facility-seg-path \{([^}]*)\}/)?.[1] ?? "", /gradient/, "a path is solid");
  assert.match(css.match(/\.facility-seg-protected \{([^}]*)\}/)?.[1] ?? "", /repeating-linear-gradient\(90deg/);
  assert.match(css.match(/\.facility-seg-lane \{([^}]*)\}/)?.[1] ?? "", /radial-gradient/, "painted is dots");
  const breakdown = readFileSync(new URL("./FacilityBreakdown.tsx", import.meta.url), "utf8");
  assert.match(breakdown, /className=\{`stress-seg facility-seg-\$\{r\.key\}`\}/);
  assert.match(breakdown, /className=\{`swatch facility-seg-\$\{r\.key\}`\}/, "the swatch too");
});

test("the rails' colours go dark to light: path, protected, painted", () => {
  assert.ok(relativeLuminance(PAINTED.color) > relativeLuminance(PROTECTED.color) && relativeLuminance(PROTECTED.color) > relativeLuminance(PATH.color));
});

// ---------------------------------------------------------------------------
// The ring (371) and LTS 2's gap line (356): their paint, faint zooms and unpaved colour
// (the mutation re-check's SF2)
// ---------------------------------------------------------------------------

test("the ring and the gap line are not drawn where the line is faint (z12-13, alleys), and are at z14", () => {
  const layers = [...(ringLayers("s") as PaintLayer[]), ...(gapLayers("s") as PaintLayer[])];
  assert.deepEqual(layers.map((l) => l.id), ["stress-ring-3", "stress-ring-4", "stress-gap-2"]);
  for (const layer of layers) {
    const tier = Number(layer.id.split("-").pop());
    const busy = tier >= 3;
    for (const zoom of [12, 13]) assert.equal(paintAt(layer, "line-opacity", { tier }, zoom), busy ? 0 : 1, `${layer.id} z${zoom}`);
    assert.equal(paintAt(layer, "line-opacity", { tier }, 14), 1, `${layer.id} z14`);
    assert.equal(paintAt(layer, "line-opacity", { tier, alley: true }, 16), 0, `${layer.id} alley`);
  }
});

test("the gap line's colour follows the surface: in the cool palette, steel blue unpaved and pale grey-blue paved", () => {
  const cool = tiersFor("cvd") as Tier[];
  const gap = (gapLayers("s", undefined, cool) as PaintLayer[])[0];
  assert.equal(paintAt(gap, "line-color", { tier: 2, unpaved: true }, 15), "#7a8fa3");
  assert.equal(paintAt(gap, "line-color", { tier: 2, unpaved: false }, 15), "#a7b4c1");
  assert.equal(paintAt(gap, "line-color", { tier: 2 }, 15), "#a7b4c1", "an unknown surface as paved");
});
