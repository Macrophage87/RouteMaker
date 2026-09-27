// The stress overlay against the map it is actually drawn on, and the legend
// against both panel themes. PLAN.md:49 (Accessibility): contrast is checked in
// CI against the palette - which means the colours the overlay sits on, read
// from the base map style this app ships (@protomaps/basemaps, light flavour)
// and from styles.css, not a colour typed into the test.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { LIGHT } from "@protomaps/basemaps";
import { STRESS_TIERS, contrastRatio } from "./stressStyle.js";

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
function legible(tier: (typeof STRESS_TIERS)[number], under: string): number {
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

test("every tier is at least 3:1 from every surface of the base map it can be drawn over", () => {
  const failures: string[] = [];
  for (const [name, colour] of Object.entries(baseMapSurfaces())) {
    for (const tier of STRESS_TIERS) {
      const ratio = legible(tier, colour);
      if (ratio < FLOOR) failures.push(`${tier.short} on ${name} ${colour}: ${ratio.toFixed(2)}:1`);
    }
  }
  assert.deepEqual(failures, []);
});

test("every legend line is at least 3:1 from both themes' panel", () => {
  const failures: string[] = [];
  for (const bg of panelBackgrounds()) {
    for (const tier of STRESS_TIERS) {
      const ratio = legible(tier, bg);
      if (ratio < FLOOR) failures.push(`${tier.short} on ${bg}: ${ratio.toFixed(2)}:1`);
    }
  }
  assert.deepEqual(failures, []);
});
