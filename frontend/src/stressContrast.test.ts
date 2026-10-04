// The stress overlay against the map it is actually drawn on, and the legend
// against both panel themes. PLAN.md:49 (Accessibility): contrast is checked in
// CI against the palette - which means the colours the overlay sits on, read
// from the base map style this app ships (@protomaps/basemaps, light flavour)
// and from styles.css, not a colour typed into the test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LIGHT } from "@protomaps/basemaps";
import {
  ALLEY_MIN_ZOOM,
  BESIDE_ROAD_MIN_ZOOM,
  BUSY_MIN_TIER,
  DEFAULT_PALETTE,
  FACILITIES,
  FAINT,
  PALETTES,
  SOLID_MIN_ZOOM,
  contrastRatio,
  faintEdgeColour,
  relativeLuminance,
  setAccessibility,
  stressCasingLayers,
  stressLayers,
  tiersFor,
} from "./stressStyle.js";
import { paintAt } from "./testSupport/paintAt.ts";
import { VISIONS, adjacentDeltas, closestPair, deltaE2000, simulate } from "./testSupport/colourVision.ts";
import { ROUTE_BLUE, ROUTE_CASING_CVD, ROUTE_CASING_WIDTH, ROUTE_HALO_WIDTH, ROUTE_LINE_WIDTH, routeCasing, routeClasses } from "./lib/routeColours.ts";
import { UNRATED, UNRATED_CVD_COLOUR, unrated } from "./lib/stressBar.ts";
import { DEFAULT_CONFLICTS } from "./testSupport/defaultConflicts.ts";

/** The default (two-tone, OWNER-DECISIONS 351) is held here to everything but the 3:1 breaks the owner's colours make, which defaultPalette.test.ts holds exactly. */
const reportedFor = (palette: string): readonly string[] => (palette === DEFAULT_PALETTE ? DEFAULT_CONFLICTS.lineOnEdgeBelowThreeToOne : []);
const notReported = (palette: string, failures: string[]) => failures.filter((f) => !reportedFor(palette).some((short) => f.startsWith(`${short} `)));

type Tier = ReturnType<typeof tiersFor>[number];

/** The palettes held to the rules: the default and the colour-blind-friendly one. `twotone` is reported only. */
const HELD = [DEFAULT_PALETTE, "cvd"] as const;
const STRESS_TIERS = tiersFor(DEFAULT_PALETTE);

/** WCAG 1.4.11: graphical objects need 3:1 against adjacent colours. */
const FLOOR = 3;

function toHex(colour: string): string | null {
  const text = colour.trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(text)) return text;
  const rgba = text.match(/^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\s*\)$/);
  if (!rgba) return null;
  if (rgba[4] !== undefined && Number(rgba[4]) < 1) return null;
  return `#${rgba.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
}

// What a segment line can lie over: land and landcover fills, the road and
// bridge fills a street is drawn along, water under a bridge, and buildings.
// Labels, casings drawn by the base map, and POI icon colours are not surfaces.
const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|buildings|other|minor|link|major$|highway$|bridges_(other|minor|link|major|highway)$|tunnel_(other|minor|link|major|highway)$)/;

function baseMapSurfaces(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(LIGHT)) {
    if (typeof value === "string" && SURFACE.test(key) && !key.includes("casing")) {
      const hex = toHex(value);
      if (hex) out[key] = hex;
    }
  }
  for (const [key, value] of Object.entries((LIGHT as { landcover?: Record<string, string> }).landcover ?? {})) {
    const hex = toHex(value);
    if (hex) out[`landcover.${key}`] = hex;
  }
  return out;
}

function panelBackgrounds(): string[] {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  return [...css.matchAll(/--bg:\s*(#[0-9a-fA-F]{6})/g)].map((m) => m[1].toLowerCase());
}

/** A tier is legible over a colour if its line is, or if its casing is and the line stands on the casing. */
function legible(tier: Tier, under: string): number {
  const direct = contrastRatio(tier.color, under);
  const cased = Math.min(contrastRatio(tier.casing, under), contrastRatio(tier.color, tier.casing));
  // A ring outside the casing (two-tone LTS 3 and 4, OWNER-DECISIONS 371): 3:1 from the surface and from the casing it rings.
  const ringed = tier.ring ? Math.min(contrastRatio(tier.ring, under), contrastRatio(tier.ring, tier.casing)) : 0;
  return Math.max(direct, cased, ringed);
}

test("the premise: the surfaces were found, parkland among them", () => {
  const surfaces = baseMapSurfaces();
  assert.ok(Object.keys(surfaces).length >= 20, JSON.stringify(surfaces));
  for (const key of ["earth", "park_a", "park_b", "wood_a", "wood_b", "scrub_b", "minor_a", "major"]) {
    assert.ok(key in surfaces, `${key} missing from the surfaces checked`);
  }
  assert.deepEqual(panelBackgrounds().length, 2, "one --bg per theme in styles.css");
});

test("without a casing the calm tiers vanish into the parkland (why the casing exists)", () => {
  const park = baseMapSurfaces().park_b;
  assert.ok(contrastRatio(STRESS_TIERS[0].color, park) < 1.5);
});

// Plain, and as the accessibility switch draws them (casings pushed to black or white).
const STRENGTHS = [
  { label: "", strong: false },
  { label: " (accessibility on)", strong: true },
];

for (const palette of HELD) {
  for (const { label, strong } of STRENGTHS) {
    test(`${palette}${label}: every tier is at least 3:1 from every surface of the base map it can be drawn over`, () => {
      const failures: string[] = [];
      for (const [name, colour] of Object.entries(baseMapSurfaces())) {
        for (const tier of tiersFor(palette, strong)) {
          const ratio = legible(tier, colour);
          if (ratio < FLOOR) failures.push(`${tier.short} on ${name} ${colour}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(notReported(palette, failures), []);
    });

    test(`${palette}${label}: every legend line is at least 3:1 from both themes' panel`, () => {
      const failures: string[] = [];
      for (const bg of panelBackgrounds()) {
        for (const tier of tiersFor(palette, strong)) {
          const ratio = legible(tier, bg);
          if (ratio < FLOOR) failures.push(`${tier.short} on ${bg}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(notReported(palette, failures), []);
    });
  }
}


/** The CIEDE2000 floor between neighbouring tiers, for the colour-blind-friendly palette, under every vision. */
const DELTA_E_FLOOR = 20;
/** LTS 2 against LTS 3 is the pair the rider most needs to tell apart: the busy roads start there. */
const LTS2_VS_LTS3_FLOOR = 35;

for (const palette of Object.keys(PALETTES)) {
  test(`${palette}: neighbouring tiers' CIEDE2000 under each colour vision (reported${palette === "cvd" ? ", and held to the floor" : ""})`, (t) => {
    const colours = tiersFor(palette).map((tier: Tier) => tier.color);
    const failures: string[] = [];
    for (const vision of VISIONS) {
      const deltas = adjacentDeltas(colours, vision);
      const closest = closestPair(colours, vision);
      t.diagnostic(
        `${vision.padEnd(6)} adjacent ${deltas.map((d) => d.toFixed(1)).join(" ")}; closest pair LTS${closest.pair[0] + 1}-LTS${closest.pair[1] + 1} ${closest.delta.toFixed(1)}`,
      );
      deltas.forEach((delta, i) => {
        if (delta < DELTA_E_FLOOR) failures.push(`${vision}: tier ${i + 1} to ${i + 2} is ${delta.toFixed(1)}`);
      });
      if (palette === "cvd" && deltas[1] < LTS2_VS_LTS3_FLOOR) failures.push(`${vision}: LTS 2 to LTS 3 is only ${deltas[1].toFixed(1)}`);
    }
    if (palette === "cvd") assert.deepEqual(failures, []);
  });
}

// The search that chose the palette held each step to 1.5:1 as a target; the
// test's floor is 1.4:1, the margin a later retune may spend (the smallest
// step now is LTS 2 to 3, 1.51:1).
test("cvd: relative luminance falls tier by tier, so the greyscale order holds, by at least 1.4:1 a step", () => {
  const colours = tiersFor("cvd").map((tier: Tier) => tier.color);
  for (let i = 1; i < colours.length; i += 1) {
    assert.ok(relativeLuminance(colours[i]) < relativeLuminance(colours[i - 1]), `tier ${i + 1} is not darker than tier ${i}`);
    const ratio = contrastRatio(colours[i], colours[i - 1]);
    assert.ok(ratio >= 1.4, `tiers ${i} and ${i + 1} are ${ratio.toFixed(2)}:1 apart in luminance`);
  }
});

/** The smallest CIEDE2000 between two colours over every vision, and the vision it is under. */
function worstDelta(a: string, b: string): { delta: number; vision: string } {
  return VISIONS.map((vision) => ({ vision, delta: deltaE2000(simulate(a, vision), simulate(b, vision)) })).reduce((x, y) => (y.delta < x.delta ? y : x));
}

/** What a route section can be drawn in under the cvd palette: the tiers, the unrated grey and the traffic-free violet. */
function cvdRouteClasses(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const tier of tiersFor("cvd")) out[tier.short] = tier.color;
  out["Not rated"] = unrated("cvd").color;
  out["Traffic-free"] = (FACILITIES.find((f: { facility: string }) => f.facility === "path") as { color: string }).color;
  return out;
}

/** The route casing's floor against every class: the best a search of sRGB reached with LTS 2 at 3:1 and 30 apart (19.1). */
const ROUTE_CASING_DELTA_FLOOR = 19;

test("cvd: the route's casing gives LTS 2 3:1 and 30 CIEDE2000 under every vision, where the blue gave 2.22:1 and about 20", (t) => {
  const lts2 = PALETTES.cvd[2].color;
  assert.equal(routeCasing("cvd"), ROUTE_CASING_CVD);
  assert.ok(contrastRatio(ROUTE_CASING_CVD, lts2) >= 3, `${contrastRatio(ROUTE_CASING_CVD, lts2).toFixed(2)}:1`);
  const delta = worstDelta(ROUTE_CASING_CVD, lts2);
  assert.ok(delta.delta >= 30, `${delta.delta.toFixed(1)} under ${delta.vision}`);
  // The premise: the blue the default palette uses fails it.
  assert.ok(contrastRatio(ROUTE_BLUE, lts2) < 2.5 && worstDelta(ROUTE_BLUE, lts2).delta < 21);
  for (const [name, colour] of Object.entries(cvdRouteClasses())) {
    const d = worstDelta(ROUTE_CASING_CVD, colour);
    t.diagnostic(`${ROUTE_CASING_CVD} against ${name} ${colour}: ${contrastRatio(ROUTE_CASING_CVD, colour).toFixed(2)}:1, CIEDE2000 at least ${d.delta.toFixed(1)} (${d.vision})`);
  }
});

test("cvd: the route's casing stands apart from every class it carries, under every vision", () => {
  const failures: string[] = [];
  for (const [name, colour] of Object.entries(cvdRouteClasses())) {
    const d = worstDelta(ROUTE_CASING_CVD, colour);
    if (d.delta < ROUTE_CASING_DELTA_FLOOR) failures.push(`${name} ${colour}: ${d.delta.toFixed(1)} under ${d.vision}`);
  }
  assert.deepEqual(failures, []);
  // Better than the blue on the closest of them: the blue is 11 from the traffic-free violet under deuteranopia.
  const closest = (casing: string) => Math.min(...Object.values(cvdRouteClasses()).map((c) => worstDelta(casing, c).delta));
  assert.ok(closest(ROUTE_CASING_CVD) > closest(ROUTE_BLUE) + 5);
});

test("cvd: the route's casing is 3:1 from every base-map surface, so the route still stands out from the map", () => {
  const failures: string[] = [];
  for (const [name, colour] of Object.entries(baseMapSurfaces())) {
    const ratio = contrastRatio(ROUTE_CASING_CVD, colour);
    if (ratio < FLOOR) failures.push(`${name} ${colour}: ${ratio.toFixed(2)}:1`);
  }
  assert.deepEqual(failures, []);
});

/** "Not rated" is held to the palette's own floor against every tier and the traffic-free violet. */
test("cvd: the unrated colour is at least 20 CIEDE2000 from every tier and the traffic-free violet, under every vision", (t) => {
  const classes = cvdRouteClasses();
  const failures: string[] = [];
  for (const [name, colour] of Object.entries(classes)) {
    if (name === "Not rated") continue;
    const d = worstDelta(UNRATED_CVD_COLOUR, colour);
    t.diagnostic(`${UNRATED_CVD_COLOUR} against ${name}: ${d.delta.toFixed(1)} (${d.vision}); the default grey ${UNRATED.color}: ${worstDelta(UNRATED.color, colour).delta.toFixed(1)}`);
    if (d.delta < DELTA_E_FLOOR) failures.push(`${name}: ${d.delta.toFixed(1)} under ${d.vision}`);
  }
  assert.deepEqual(failures, []);
  // The premise: the default grey is under the floor against the cvd blues.
  assert.ok(worstDelta(UNRATED.color, PALETTES.cvd[2].color).delta < DELTA_E_FLOOR);
  assert.ok(worstDelta(UNRATED.color, PALETTES.cvd[1].color).delta < DELTA_E_FLOOR);
  // And it stays the grey it was, a near-neutral of about the same lightness.
  assert.ok(Math.abs(relativeLuminance(UNRATED_CVD_COLOUR) - relativeLuminance(UNRATED.color)) < 0.02);
  // Inside the route's casing it is 3:1.
  assert.ok(contrastRatio(UNRATED_CVD_COLOUR, ROUTE_CASING_CVD) >= 3);
});

// ---------------------------------------------------------------------------
// Item 215 (WCAG 1.4.11, non-text contrast): the route line, the faint busy
// roads and the swatch borders.
// ---------------------------------------------------------------------------

/** Run `body` with the accessibility switch on or off (a trial that leaves what is stored alone), then off again. */
function withSwitch<T>(on: boolean, body: () => T): T {
  setAccessibility(on, { remember: false });
  try {
    return body();
  } finally {
    setAccessibility(false, { remember: false });
  }
}

/** The palette and strength a rider can reach: the default, plain; and the colour-blind-friendly one, which the switch draws stronger. */
const REACHABLE = [
  { name: DEFAULT_PALETTE, on: false },
  { name: "cvd", on: true },
];

for (const { name, on } of REACHABLE) {
  test(`${name}${on ? " (accessibility on)" : ""}: every route class is at least 3:1 from the halo under it`, () => {
    withSwitch(on, () => {
      const classes = routeClasses();
      assert.equal(classes.length, 12, "the traffic-free path, five tiers, five unpaved browns (OWNER-DECISIONS 302) and the unrated");
      const failures: string[] = [];
      for (const c of classes) {
        const ratio = contrastRatio(c.color, c.halo);
        if (ratio < FLOOR) failures.push(`${c.short} ${c.color} on ${c.halo}: ${ratio.toFixed(2)}:1`);
      }
      assert.deepEqual(notReported(name, failures), []);
    });
  });
}

test("the premise: the casing alone fails several classes, in both palettes", () => {
  for (const { name, on } of REACHABLE) {
    withSwitch(on, () => {
      const casing = routeCasing();
      const under = routeClasses().filter((c) => contrastRatio(c.color, casing) < FLOOR).map((c) => c.short);
      assert.ok(under.length >= 2, `${name}: only ${under.join(", ")} fail the casing alone`);
    });
  }
});

test("no single casing colour can be 3:1 from every route class, so each class has its own halo", () => {
  for (const { name, on } of REACHABLE) {
    withSwitch(on, () => {
      const lum = routeClasses().map((c) => relativeLuminance(c.color));
      let best = 0;
      // Contrast depends only on luminance, so scanning every luminance covers every colour.
      for (let i = 0; i <= 1000; i += 1) {
        const l = i / 1000;
        const worst = Math.min(...lum.map((k) => (Math.max(l, k) + 0.05) / (Math.min(l, k) + 0.05)));
        best = Math.max(best, worst);
      }
      assert.ok(best < FLOOR, `${name}: a casing could reach ${best.toFixed(2)}:1 from every class`);
    });
  }
});

test("a halo is dark under the light classes and white under the dark ones (never the blue)", () => {
  for (const { name, on } of REACHABLE) {
    withSwitch(on, () => {
      for (const c of routeClasses()) {
        // Only the default palette's Avoid is exempt: its halo is its own red casing, a colour of its own
        // (OWNER-DECISIONS 274), neither dark nor light, and 3:1 from the near-black line. Every other
        // palette's Avoid keeps the dark-or-light rule (review SF4).
        if (c.key === "5" && name === "blended") {
          assert.equal(c.halo, PALETTES.blended[5].casing, "the exemption is for the palette's own Avoid casing only");
          assert.ok(contrastRatio(c.color, c.halo) >= 3, `${c.short}: ${c.color} on ${c.halo}`);
          continue;
        }
        assert.equal(relativeLuminance(c.halo) < 0.5, relativeLuminance(c.color) > 0.14, `${c.short}: ${c.color} on ${c.halo}`);
        assert.notEqual(c.halo, ROUTE_BLUE);
      }
    });
  }
});

test("the route's outer ring in the default palette (the blue) is 3:1 from every base-map surface", () => {
  const failures: string[] = [];
  for (const [name, colour] of Object.entries(baseMapSurfaces())) {
    const ratio = contrastRatio(ROUTE_BLUE, colour);
    if (ratio < FLOOR) failures.push(`${name} ${colour}: ${ratio.toFixed(2)}:1`);
  }
  assert.deepEqual(failures, []);
});

/** sRGB-space source-over compositing, as the map draws a translucent line. */
function over(foreground: string, alpha: number, background: string): string {
  const channel = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `#${[0, 1, 2].map((i) => Math.round(channel(foreground, i) * alpha + channel(background, i) * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
}

for (const { name, on } of REACHABLE) {
  test(`${name}${on ? " (accessibility on)" : ""}: a faint line's dark edge is at least 3:1 from every surface of the base map`, () => {
    withSwitch(on, () => {
      const failures: string[] = [];
      for (const tier of tiersFor(name, on)) {
        const edge = faintEdgeColour(tier);
        assert.ok(relativeLuminance(edge) < 0.05, `${tier.short}'s edge ${edge} is not dark`);
        for (const [surface, colour] of Object.entries(baseMapSurfaces())) {
          const ratio = contrastRatio(over(edge, FAINT.edgeOpacity, colour), colour);
          if (ratio < FLOOR) failures.push(`${tier.short} edge on ${surface} ${colour}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(failures, []);
    });
  });
}

test("the premise: a faint line alone, at the owner's 40%, is under 3:1 on the earth for the busy tiers, and it stays faint", () => {
  const earth = baseMapSurfaces().earth;
  const under = tiersFor(DEFAULT_PALETTE).filter((t: Tier) => contrastRatio(over(t.color, FAINT.opacity, earth), earth) < FLOOR);
  assert.ok(under.length >= 2, under.map((t: Tier) => t.short).join(", "));
  assert.equal(FAINT.opacity, 0.4);
  assert.equal(FAINT.widthScale, 0.6);
});

test("the casing layers carry the edge exactly where the line is faint: z12-13 busy roads, a road beside a bikeway, an alley", () => {
  const tiers = tiersFor(DEFAULT_PALETTE);
  const casings = stressCasingLayers("s", undefined, tiers) as Array<{ id: string; paint: Record<string, unknown> }>;
  const lines = stressLayers("s", undefined, tiers) as Array<{ id: string; paint: Record<string, unknown> }>;
  tiers.forEach((tier: Tier, i: number) => {
    const busy = tier.tier >= BUSY_MIN_TIER;
    const states: Array<[string, Record<string, unknown>, number, boolean]> = [
      ["plain road at z12", {}, SOLID_MIN_ZOOM - 2, busy],
      ["plain road at z13", {}, SOLID_MIN_ZOOM - 1, busy],
      ["plain road at z14", {}, SOLID_MIN_ZOOM, false],
      ["beside a bikeway at z15", { separate_bikeway: true }, BESIDE_ROAD_MIN_ZOOM, busy],
      ["alley at z16", { alley: true }, ALLEY_MIN_ZOOM, true],
    ];
    for (const [label, props, zoom, faint] of states) {
      const where = `${tier.short} ${label}`;
      const opacity = paintAt(casings[i], "line-opacity", props, zoom);
      const gap = paintAt(casings[i], "line-gap-width", props, zoom);
      const width = paintAt(casings[i], "line-width", props, zoom);
      const colour = paintAt(casings[i], "line-color", props, zoom);
      const lineWidth = paintAt(lines[i], "line-width", props, zoom) as number;
      if (faint) {
        assert.equal(paintAt(lines[i], "line-opacity", props, zoom), FAINT.opacity, where);
        assert.equal(opacity, FAINT.edgeOpacity, where);
        assert.equal(width, FAINT.edgePx, where);
        assert.ok(Math.abs((gap as number) - lineWidth) < 1e-9, `${where}: the ring sits against the line (gap ${gap}, line ${lineWidth})`);
        assert.equal(colour, faintEdgeColour(tier), where);
      } else {
        assert.equal(opacity, 1, where);
        assert.equal(gap, 0, where);
        assert.equal(width, tier.width + 2, where);
        assert.equal(colour, tier.casing, where);
      }
    }
    // An alley is not drawn below z16: nothing of its casing either.
    assert.equal(paintAt(casings[i], "line-opacity", { alley: true }, ALLEY_MIN_ZOOM - 1), 0, `${tier.short} alley at z15`);
  });
});

/** The panel and swatch colours of each theme, from styles.css. */
function themeColours(): Array<{ theme: string; bg: string; soft: string; swatch: string; border: string }> {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  const pick = (block: string, name: string) => block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1].toLowerCase() ?? "";
  const light = css.slice(css.indexOf(":root {"), css.indexOf("@media (prefers-color-scheme: dark)"));
  const darkStart = css.indexOf("@media (prefers-color-scheme: dark)");
  const dark = css.slice(darkStart, css.indexOf("}", css.indexOf(":root {", darkStart)));
  return [
    { theme: "light", bg: pick(light, "--bg"), soft: pick(light, "--bg-soft"), swatch: pick(light, "--swatch-border"), border: pick(light, "--border") },
    { theme: "dark", bg: pick(dark, "--bg"), soft: pick(dark, "--bg-soft"), swatch: pick(dark, "--swatch-border"), border: pick(dark, "--border") },
  ];
}

test("swatch borders (switch off) are at least 3:1 from the panel in both themes, where --border was about 1.5:1", () => {
  for (const t of themeColours()) {
    for (const c of [t.bg, t.soft, t.swatch, t.border]) assert.match(c, /^#[0-9a-f]{6}$/, `${t.theme}: a colour was not read`);
    assert.ok(contrastRatio(t.swatch, t.bg) >= FLOOR, `${t.theme} on --bg: ${contrastRatio(t.swatch, t.bg).toFixed(2)}:1`);
    assert.ok(contrastRatio(t.swatch, t.soft) >= FLOOR, `${t.theme} on --bg-soft: ${contrastRatio(t.swatch, t.soft).toFixed(2)}:1`);
    assert.ok(contrastRatio(t.border, t.bg) < 1.8, `the premise: ${t.theme}'s --border is ${contrastRatio(t.border, t.bg).toFixed(2)}:1`);
  }
});

test("the legend swatch and the stress bar take their border from --swatch-border, not --border", () => {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  for (const selector of [".swatch", ".stress-bar"]) {
    const body = css.match(new RegExp(`\\n\\${selector} \\{([^}]*)\\}`))?.[1] ?? "";
    assert.match(body, /border:\s*1px solid var\(--swatch-border\)/, selector);
  }
});

test("the faint edge is at least a pixel wide each side, not a hairline the antialiasing loses", () => {
  assert.ok(FAINT.edgePx >= 1);
});

test("the map adds the route's halo between its casing and its sections, coloured by the feature, and the legend draws it too", () => {
  const mapView = readFileSync(new URL("./MapView.tsx", import.meta.url), "utf8");
  const at = (id: string) => mapView.indexOf(`id: "${id}"`);
  assert.ok(at("route-casing") >= 0 && at("route-casing") < at("route-halo") && at("route-halo") < at("route-stress"));
  const halo = mapView.slice(at("route-halo"), at("route-stress"));
  assert.match(halo, /"line-color": \["get", "halo"\]/);
  assert.match(halo, /"line-width": \["coalesce", \["get", "haloWidth"\], ROUTE_HALO_WIDTH\]/);
  const legendSource = readFileSync(new URL("./FacilityBreakdown.tsx", import.meta.url), "utf8");
  const casingAt = legendSource.indexOf("stroke={casing}");
  const haloAt = legendSource.indexOf("stroke={row.halo}");
  const colourAt = legendSource.indexOf("stroke={row.color}");
  assert.ok(casingAt >= 0 && casingAt < haloAt && haloAt < colourAt, "casing, then halo, then the section's colour");
});

test("the route's widths nest: line < halo < casing, so the halo shows and the casing is outside it", () => {
  assert.ok(ROUTE_LINE_WIDTH < ROUTE_HALO_WIDTH && ROUTE_HALO_WIDTH < ROUTE_CASING_WIDTH, `${ROUTE_LINE_WIDTH} ${ROUTE_HALO_WIDTH} ${ROUTE_CASING_WIDTH}`);
});

test("with the switch on, the swatch border is the strengthened border, at least as strong as the plain swatch border, in both themes", () => {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  const blocks = [...css.matchAll(/:root\.a11y \{([^}]*)\}/g)].map((m) => m[1]);
  assert.equal(blocks.length, 2, "one :root.a11y block per theme");
  const plain = themeColours();
  blocks.forEach((block, i) => {
    const pick = (name: string) => block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1].toLowerCase() ?? "";
    assert.match(pick("--swatch-border"), /^#[0-9a-f]{6}$/, `block ${i}`);
    assert.equal(pick("--swatch-border"), pick("--border"), `block ${i}`);
    assert.ok(contrastRatio(pick("--swatch-border"), plain[i].bg) >= contrastRatio(plain[i].swatch, plain[i].bg), `block ${i}`);
  });
});
