// The stress overlay against the map it is actually drawn on, and the legend
// against both panel themes. PLAN.md:49 (Accessibility): contrast is checked in
// CI against the palette - which means the colours the overlay sits on, read
// from the base map style this app ships (@protomaps/basemaps, light flavour)
// and from styles.css, not a colour typed into the test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LIGHT } from "@protomaps/basemaps";
import { DEFAULT_PALETTE, PALETTES, contrastRatio, relativeLuminance, tiersFor } from "./stressStyle.js";
import { VISIONS, adjacentDeltas, closestPair } from "./testSupport/colourVision.ts";

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
  return Math.max(direct, cased);
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
      assert.deepEqual(failures, []);
    });

    test(`${palette}${label}: every legend line is at least 3:1 from both themes' panel`, () => {
      const failures: string[] = [];
      for (const bg of panelBackgrounds()) {
        for (const tier of tiersFor(palette, strong)) {
          const ratio = legible(tier, bg);
          if (ratio < FLOOR) failures.push(`${tier.short} on ${bg}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(failures, []);
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

test("cvd: relative luminance falls tier by tier, so the greyscale order holds, by at least 1.4:1 a step", () => {
  const colours = tiersFor("cvd").map((tier: Tier) => tier.color);
  for (let i = 1; i < colours.length; i += 1) {
    assert.ok(relativeLuminance(colours[i]) < relativeLuminance(colours[i - 1]), `tier ${i + 1} is not darker than tier ${i}`);
    const ratio = contrastRatio(colours[i], colours[i - 1]);
    assert.ok(ratio >= 1.4, `tiers ${i} and ${i + 1} are ${ratio.toFixed(2)}:1 apart in luminance`);
  }
});
