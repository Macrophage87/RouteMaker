// The dark base map (lib/mapFlavour.ts; the owner, 2026-11-01: battery audit): every overlay colour that meets the
// map, held to WCAG 1.4.11's 3:1 on the dark flavour's own surfaces, as stressContrast.test.ts holds them on the
// light one; the dark-map variants change nothing on the light map; and the switch keeps the overlay.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import {
  DARK_MAP,
  DEFAULT_PALETTE,
  FAINT,
  MTB_HALO,
  MTB_LEVELS,
  MTB_TICKS,
  MTB_TRAIL,
  PALETTES,
  FACILITIES,
  contrastRatio,
  currentTiers,
  darkMapOn,
  faintEdgeColour,
  mtbTicksPaint,
  relativeLuminance,
  setDarkMap,
  styleKey,
  subscribePalette,
  tiersFor,
} from "./stressStyle.js";
import { ROUTE_BLUE, ROUTE_BLUE_DARK_MAP, ROUTE_CASING_CVD, ROUTE_CASING_CVD_DARK_MAP, casingOnMap, routePaint } from "./lib/routeColours.ts";
import { DARK_PAINT, MASK_DARK, MASK_EDGE_DARK, SCENIC_DARK_COLOUR, applyDarkPaint, withDarkPaint } from "./lib/darkPaint.ts";
import { MAP_DARK_CLASS, applyMapFlavour, basemapLayers, basemapPaintChanges, flavourColours, isDark, mapFlavourFor, nextLightChange, overlayLightPaint, spriteFor } from "./lib/mapFlavour.ts";
import { COVERAGE_MASK_LAYERS } from "./lib/mapGlue.ts";
import { DC_MASK_LAYERS } from "./lib/dcBoundary.ts";
import { SCENIC_CASING_LAYER, SCENIC_COLOUR, scenicCasingLayer, scenicPointLayers } from "./lib/scenicLayer.ts";
import { OUTLINE, OUTLINE_DARK_MAP, stationIcon } from "./lib/stationIcons.ts";
import { ROLE_COLOURS } from "./lib/rideDotsLayer.ts";
import { CLIMB_COLOUR } from "./lib/climbs.ts";
import { DEFAULT_CONFLICTS } from "./testSupport/defaultConflicts.ts";

const FLOOR = 3;
type Tier = ReturnType<typeof tiersFor>[number];

function toHex(colour: string): string | null {
  const text = colour.trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(text)) return text;
  const rgba = text.match(/^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\s*\)$/);
  if (!rgba || (rgba[4] !== undefined && Number(rgba[4]) < 1)) return null;
  return `#${rgba.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
}

// What a line can lie over on the dark map, read as stressContrast.test.ts reads the light flavour's.
const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|buildings|other|minor|link|major$|highway$|bridges_(other|minor|link|major|highway)$|tunnel_(other|minor|link|major|highway)$)/;
function darkSurfaces(): Record<string, string> {
  const dark = flavourColours("dark") as unknown as Record<string, unknown> & { landcover?: Record<string, string> };
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(dark)) {
    if (typeof value === "string" && SURFACE.test(key) && !key.includes("casing")) {
      const hex = toHex(value);
      if (hex) out[key] = hex;
    }
  }
  for (const [key, value] of Object.entries(dark.landcover ?? {})) {
    const hex = toHex(value);
    if (hex) out[`landcover.${key}`] = hex;
  }
  return out;
}

/** Each surface a colour is under 3:1 on. */
function under(colour: string, floor = FLOOR): string[] {
  return Object.entries(darkSurfaces())
    .filter(([, s]) => contrastRatio(colour, s) < floor)
    .map(([name, s]) => `${colour} on ${name} ${s}: ${contrastRatio(colour, s).toFixed(2)}:1`);
}

function over(foreground: string, alpha: number, background: string): string {
  const channel = (hex: string, i: number) => parseInt(hex.slice(1 + 2 * i, 3 + 2 * i), 16);
  return `#${[0, 1, 2].map((i) => Math.round(channel(foreground, i) * alpha + channel(background, i) * (1 - alpha)).toString(16).padStart(2, "0")).join("")}`;
}

/** As stressContrast.test.ts: legible by its line, or by its casing with the line 3:1 on it, or by its ring. */
function legible(tier: Tier, surface: string): number {
  const direct = contrastRatio(tier.color, surface);
  const cased = Math.min(contrastRatio(tier.casing, surface), contrastRatio(tier.color, tier.casing));
  const ringed = tier.ring ? Math.min(contrastRatio(tier.ring, surface), contrastRatio(tier.ring, tier.casing)) : 0;
  return Math.max(direct, cased, ringed);
}

const STRENGTHS = [false, true];
const HELD = [DEFAULT_PALETTE, "cvd"] as const;

test("the premise: the dark flavour has the light one's layers, ids and layout alike; only the paint differs", () => {
  const light = protomapsLayers("p", namedFlavor("light"), { lang: "en" }) as Array<Record<string, unknown>>;
  const dark = protomapsLayers("p", namedFlavor("dark"), { lang: "en" }) as Array<Record<string, unknown>>;
  assert.deepEqual(dark.map((l) => l.id), light.map((l) => l.id));
  dark.forEach((layer, i) => {
    const { paint: _d, ...restDark } = layer;
    const { paint: _l, ...restLight } = light[i];
    assert.deepEqual(restDark, restLight, String(layer.id));
  });
  // And so with this app's changes (withClearRoadLabels): the switch is paint alone, layer by layer.
  const ours = { light: basemapLayers("light", false) as Array<{ id: string }>, dark: basemapLayers("dark", false) as Array<{ id: string }> };
  assert.deepEqual(ours.dark.map((l) => l.id), ours.light.map((l) => l.id));
  const changes = basemapPaintChanges(ours.light, ours.dark);
  assert.ok(changes.length > 40, `${changes.length} paint changes`);
  assert.ok(changes.some((c) => c.id === "earth" && c.name === "fill-color"));
});

test("the dark flavour's background is its earth, so beyond the archive is as dark as the land; the light one is Protomaps' own", () => {
  assert.equal(flavourColours("dark").background, namedFlavor("dark").earth);
  assert.deepEqual(flavourColours("light"), namedFlavor("light"));
});

test("DARK_MAP.topSurface is the dark map's lightest surface, the worst case a light-map colour is checked on", () => {
  const lightest = Object.values(darkSurfaces()).reduce((a, b) => (relativeLuminance(b) > relativeLuminance(a) ? b : a));
  assert.equal(DARK_MAP.topSurface, lightest);
  assert.ok(Object.keys(darkSurfaces()).length >= 20);
});

test("the light map's tiers are untouched: tiersFor without the dark map is as before, and the dark map changes the casing alone", () => {
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of STRENGTHS) {
      const light = tiersFor(palette, strong);
      assert.deepEqual(tiersFor(palette, strong, false), light);
      tiersFor(palette, strong, true).forEach((tier: Tier & { darkMap?: boolean }, i: number) => {
        const { casing: _c, darkMap: _d, half, ...rest } = tier;
        const { casing: _lc, half: lightHalf, ...lightRest } = light[i];
        assert.deepEqual(rest, lightRest, `${palette} ${tier.short}`);
        assert.ok(tier.casing === light[i].casing || tier.casing === DARK_MAP.casing);
        // A half step keeps its colour; its ring or casing alone may go white.
        assert.equal(half?.color, lightHalf?.color);
        for (const part of ["ring", "casing"] as const) assert.ok(half?.[part] === lightHalf?.[part] || half?.[part] === DARK_MAP.casing, `${tier.short} half ${part}`);
      });
    }
  }
});

for (const palette of HELD) {
  for (const strong of STRENGTHS) {
    test(`${palette}${strong ? " (accessibility on)" : ""}: on the dark map every tier is 3:1 from every surface (the light map's reported breaks aside)`, () => {
      const failures: string[] = [];
      for (const [name, colour] of Object.entries(darkSurfaces())) {
        for (const tier of tiersFor(palette, strong, true)) {
          const ratio = legible(tier, colour);
          if (ratio < FLOOR) failures.push(`${tier.short} on ${name} ${colour}: ${ratio.toFixed(2)}:1`);
        }
      }
      const reported = palette === DEFAULT_PALETTE ? DEFAULT_CONFLICTS.lineOnEdgeBelowThreeToOne : [];
      assert.deepEqual(failures.filter((f) => !reported.some((short) => f.startsWith(`${short} `))), []);
    });

    test(`${palette}${strong ? " (accessibility on)" : ""}: on the dark map a half step is 3:1 from every surface by its line, casing or ring`, () => {
      const failures: string[] = [];
      for (const tier of tiersFor(palette, strong, true)) {
        if (!tier.half) continue;
        const half = { ...tier, ...tier.half } as Tier;
        for (const [name, colour] of Object.entries(darkSurfaces())) {
          const ratio = legible(half, colour);
          if (ratio < FLOOR) failures.push(`${tier.short}'s half step on ${name}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(failures, []);
    });

    test(`${palette}${strong ? " (accessibility on)" : ""}: on the dark map a faint line's edge is light, and 3:1 from every surface`, () => {
      const failures: string[] = [];
      for (const tier of tiersFor(palette, strong, true)) {
        const edge = faintEdgeColour(tier);
        assert.equal(edge, DARK_MAP.edge);
        for (const [name, colour] of Object.entries(darkSurfaces())) {
          const ratio = contrastRatio(over(edge, FAINT.edgeOpacity, colour), colour);
          if (ratio < FLOOR) failures.push(`${tier.short} edge on ${name}: ${ratio.toFixed(2)}:1`);
        }
      }
      assert.deepEqual(failures, []);
    });

    test(`${palette}${strong ? " (accessibility on)" : ""}: on the dark map the unpaved and gravel lines are 3:1 by their line or casing`, () => {
      const failures: string[] = [];
      for (const tier of tiersFor(palette, strong, true)) {
        for (const [kind, color, casing] of [
          ["unpaved", tier.unpavedColor, tier.unpavedCasing],
          ["gravel", tier.gravelColor, tier.gravelCasing],
        ] as const) {
          for (const [name, colour] of Object.entries(darkSurfaces())) {
            const ratio = Math.max(contrastRatio(color, colour), Math.min(contrastRatio(casing, colour), contrastRatio(color, casing)));
            if (ratio < FLOOR) failures.push(`${tier.short} ${kind} on ${name}: ${ratio.toFixed(2)}:1`);
          }
        }
      }
      assert.deepEqual(failures, []);
    });
  }
}

test("the premise: without its dark-map casing the default's LTS 4 and the colour-blind-friendly LTS 3 are under 3:1 on the dark map", () => {
  const lts4 = tiersFor(DEFAULT_PALETTE)[3];
  assert.ok(legible(lts4, DARK_MAP.topSurface) < FLOOR);
  assert.ok(legible(tiersFor("cvd")[2], DARK_MAP.topSurface) < FLOOR);
  assert.equal(tiersFor(DEFAULT_PALETTE, false, true)[3].casing, DARK_MAP.casing);
  assert.equal(tiersFor("cvd", false, true)[2].casing, DARK_MAP.casing);
});

test("the route's casing on the dark map: the blue and the slate have light variants 3:1 on every dark surface; the light map's stay", () => {
  assert.deepEqual(under(ROUTE_BLUE_DARK_MAP), []);
  assert.deepEqual(under(ROUTE_CASING_CVD_DARK_MAP), []);
  // The premise: the light map's casings are under 3:1 there.
  assert.ok(under(ROUTE_BLUE).length > 0 && under(ROUTE_CASING_CVD).length > 0);
  // The slate's own rule, LTS 2 3:1 from the casing, still holds.
  assert.ok(contrastRatio(ROUTE_CASING_CVD_DARK_MAP, PALETTES.cvd[2].color) >= FLOOR);
  assert.equal(casingOnMap(ROUTE_BLUE, false), ROUTE_BLUE);
  assert.equal(casingOnMap(ROUTE_CASING_CVD, false), ROUTE_CASING_CVD);
  assert.equal(casingOnMap(ROUTE_BLUE, true), ROUTE_BLUE_DARK_MAP);
  assert.equal(casingOnMap(ROUTE_CASING_CVD, true), ROUTE_CASING_CVD_DARK_MAP);
  // A route choice's own colour is left as it is.
  assert.equal(casingOnMap("#1f2937", true), "#1f2937");
});

test("the mountain-bike trails on the dark map: their white edge carries them, and the ticks are light enough to show", () => {
  assert.deepEqual(under(MTB_HALO.color), []);
  for (const { color, name } of [...MTB_LEVELS, { color: MTB_TRAIL.color, name: "unrated" }]) assert.ok(contrastRatio(color, MTB_HALO.color) >= FLOOR, name);
  assert.deepEqual(under(DARK_MAP.ticks), []);
  assert.ok(under(MTB_TICKS.color).length > 0, "the premise: the dark ticks vanish");
  assert.equal(mtbTicksPaint(false, true)["line-color"], DARK_MAP.ticks);
  assert.equal(mtbTicksPaint(false, false)["line-color"], MTB_TICKS.color);
});

test("the Scenic casing's dark-map teal is 3:1 on every dark surface, and no stress, rail, route or mountain-bike colour", () => {
  assert.deepEqual(under(SCENIC_DARK_COLOUR), []);
  assert.ok(under(SCENIC_COLOUR).length > 0, "the premise: the teal is under 3:1 there");
  const taken = new Set<string>();
  for (const palette of Object.values(PALETTES) as Array<Record<string, Record<string, string>>>) {
    for (const tier of Object.values(palette)) for (const value of Object.values(tier)) taken.add(String(value).toLowerCase());
  }
  for (const f of FACILITIES as Array<{ color: string }>) taken.add(f.color.toLowerCase());
  for (const l of MTB_LEVELS as Array<{ color: string }>) taken.add(l.color.toLowerCase());
  for (const c of [ROUTE_BLUE, ROUTE_BLUE_DARK_MAP, MTB_TRAIL.color]) taken.add(c.toLowerCase());
  assert.ok(!taken.has(SCENIC_DARK_COLOUR));
  assert.equal((scenicCasingLayer("s", currentTiers(), false) as { paint: Record<string, unknown> }).paint["line-color"], darkMapOn() ? SCENIC_DARK_COLOUR : SCENIC_COLOUR);
  const viewpoint = (dark: boolean) => (scenicPointLayers(dark).find((l) => l.id === "scenic-viewpoints") as { paint: Record<string, unknown> }).paint["circle-stroke-color"];
  assert.equal(viewpoint(false), SCENIC_COLOUR);
  assert.equal(viewpoint(true), SCENIC_DARK_COLOUR);
});

test("the masks darken what is outside on the dark map, and their edges are 3:1 on the dark surfaces, masked or not", () => {
  for (const [name, surface] of Object.entries(darkSurfaces())) {
    const masked = over(MASK_DARK, Number(DARK_PAINT["coverage-mask"]["fill-opacity"]), surface);
    assert.ok(relativeLuminance(masked) <= relativeLuminance(surface), `${name}: the mask lightens it`);
    assert.ok(contrastRatio(MASK_EDGE_DARK, masked) >= FLOOR, `edge on masked ${name}`);
  }
  assert.deepEqual(under(MASK_EDGE_DARK), []);
  // Every layer darkPaint paints exists by that id, and has a light paint to go back to.
  const light = new Map(overlayLightPaint().map((l) => [l.id, l.paint ?? {}]));
  for (const [id, paint] of Object.entries(DARK_PAINT)) {
    assert.ok(light.has(id), id);
    for (const name of Object.keys(paint)) assert.notEqual(light.get(id)?.[name], undefined, `${id} ${name}`);
  }
  assert.ok(COVERAGE_MASK_LAYERS.every((l) => l.id in DARK_PAINT) && DC_MASK_LAYERS.every((l) => l.id in DARK_PAINT));
  assert.ok(SCENIC_CASING_LAYER in DARK_PAINT);
});

test("withDarkPaint: the dark paint over the layer's own on the dark map; the layer as given on the light one", () => {
  const layer = { ...COVERAGE_MASK_LAYERS[0] };
  assert.deepEqual(withDarkPaint(layer, false), layer);
  assert.deepEqual(withDarkPaint(layer, true).paint, { ...layer.paint, ...DARK_PAINT["coverage-mask"] });
  const other = { id: "route-line", paint: { "line-color": "#123456" } };
  assert.equal(withDarkPaint(other, true), other);
});

test("the station icons' ring on the dark map is light and 3:1 on every dark surface; the light map's ring stays", () => {
  assert.deepEqual(under(OUTLINE_DARK_MAP), []);
  assert.ok(under(OUTLINE).length > 0, "the premise: the dark ring vanishes");
  const edgePixel = (ring: string) => {
    const icon = stationIcon(["#bf0d3e"], "circle", 2, undefined, ring);
    const y = Math.floor(icon.height / 2);
    const i = (y * icon.width + 1) * 4;
    return `#${Array.from(icon.data.slice(i, i + 3)).map((n) => n.toString(16).padStart(2, "0")).join("")}`;
  };
  assert.equal(edgePixel(OUTLINE), OUTLINE);
  assert.equal(edgePixel(OUTLINE_DARK_MAP), OUTLINE_DARK_MAP);
  assert.deepEqual(stationIcon(["#bf0d3e"], "circle", 2), stationIcon(["#bf0d3e"], "circle", 2, undefined, OUTLINE));
});

test("the map's focus ring on the dark map: light outside, dark inside, 3:1 on every dark surface; the light map's is unchanged", () => {
  const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
  const block = css.match(new RegExp(`:root\\.${MAP_DARK_CLASS} \\{([^}]*)\\}`))?.[1] ?? "";
  const pick = (name: string) => block.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`))?.[1].toLowerCase() ?? "";
  const ring = pick("--map-focus");
  const inner = pick("--map-focus-inner");
  assert.match(ring, /^#[0-9a-f]{6}$/);
  assert.deepEqual(under(ring), []);
  assert.ok(contrastRatio(ring, inner) >= FLOOR);
  for (const light of [ROUTE_BLUE_DARK_MAP, ROUTE_CASING_CVD_DARK_MAP, OUTLINE_DARK_MAP, SCENIC_DARK_COLOUR]) assert.ok(contrastRatio(inner, light) >= FLOOR, light);
});

test("what already carries a white edge needs no dark-map colour: the climbs' markers and a fresh or faded rider's mark", () => {
  // Both are drawn inside a white edge (climbs.ts climbIcon, rideDotsLayer.ts dotImage), which is what meets the map.
  assert.deepEqual(under("#ffffff"), []);
  assert.ok(contrastRatio("#ffffff", CLIMB_COLOUR) >= FLOOR);
  for (const colour of Object.values(ROLE_COLOURS)) assert.ok(contrastRatio("#ffffff", colour) >= FLOOR, colour);
});

test("reported, not fixed here: a two-minute-old rider's ring (rideDotsLayer.ts, edited elsewhere) is under 3:1 on the dark map for these roles", (t) => {
  const failing = Object.entries(ROLE_COLOURS).filter(([, colour]) => under(colour).length > 0).map(([role]) => role);
  t.diagnostic(`under 3:1 on the dark map: ${failing.join(", ")}`);
  assert.ok(failing.length > 0);
});

// --- When the map is dark ----------------------------------------------------------------------------------------

const DC: [number, number] = [-77.03, 38.9];
/** 2026-11-01 in Washington (EDT until 2 am, then EST): noon and 10 pm local. */
const NOON = Date.UTC(2026, 10, 1, 17, 0);
const NIGHT = Date.UTC(2026, 10, 2, 3, 0);

test("dark between civil dusk and civil dawn, light between", () => {
  assert.equal(isDark(NOON, DC[1], DC[0]), false);
  assert.equal(isDark(NIGHT, DC[1], DC[0]), true);
  const next = nextLightChange(NOON, DC[1], DC[0]);
  assert.ok(next !== null && next > NOON && next - NOON < 12 * 3600_000, "the next change from noon is the evening's dusk");
  assert.equal(isDark(next! + 1000, DC[1], DC[0]), true);
  assert.equal(isDark(next! - 1000, DC[1], DC[0]), false);
});

test("the flavour: dark in the dark theme; in the light theme, dark only on the bike after dusk", () => {
  const at = DC;
  assert.equal(mapFlavourFor({ themeDark: true, onBike: false, now: NOON, at }), "dark");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: false, now: NOON, at }), "light");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: false, now: NIGHT, at }), "light");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: true, now: NOON, at }), "light");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: true, now: NIGHT, at }), "dark");
});

/** A map that keeps what is set on it. */
function fakeMap(ids: readonly string[]) {
  const paint = new Map<string, unknown>();
  const sprites: string[] = [];
  return {
    paint,
    sprites,
    getLayer: (id: string) => (ids.includes(id) ? { id } : undefined),
    setPaintProperty: (id: string, name: string, value: unknown) => {
      assert.ok(ids.includes(id), `paint set on ${id}, not on the map`);
      paint.set(`${id}|${name}`, value);
    },
    setSprite: (url: string) => {
      sprites.push(url);
    },
  };
}

test("the switch is in place: the base paint, the sprite, the root's class, the overlay's colours by the palette's repaint, and back", () => {
  const ids = [...(basemapLayers("light") as Array<{ id: string }>).map((l) => l.id), "coverage-mask", "coverage-edge", "route-casing", "stress-lts1"];
  const map = fakeMap(ids);
  const classes = new Set<string>();
  const root = { classList: { toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)) } };
  let told = 0;
  const stop = subscribePalette(() => {
    told += 1;
  });
  try {
    const keyBefore = styleKey();
    applyMapFlavour(map, "light", "dark", "https://x.example", undefined, root);
    assert.equal(darkMapOn(), true);
    assert.notEqual(styleKey(), keyBefore, "the style key changes, so the overlays that rebuild by it do");
    assert.equal(told, 1, "the palette's listeners repaint the stress lines and the route");
    assert.deepEqual(map.sprites, [spriteFor("https://x.example", "dark")]);
    assert.ok(classes.has(MAP_DARK_CLASS));
    assert.equal(map.paint.get("earth|fill-color"), flavourColours("dark").earth);
    assert.equal(map.paint.get("coverage-mask|fill-color"), MASK_DARK);
    // Nothing the base map does not have is touched: the route and the stress lines are the palette's.
    assert.ok(![...map.paint.keys()].some((k) => k.startsWith("route-") || k.startsWith("stress-")));
    assert.equal(routePaint(true, false).casingColor, casingOnMap(ROUTE_BLUE, true));
    assert.equal(currentTiers()[0].darkMap, true);

    applyMapFlavour(map, "dark", "light", "https://x.example", undefined, root);
    assert.equal(darkMapOn(), false);
    assert.equal(told, 2);
    assert.equal(map.paint.get("earth|fill-color"), flavourColours("light").earth);
    assert.equal(map.paint.get("coverage-mask|fill-color"), COVERAGE_MASK_LAYERS[0].paint["fill-color"]);
    assert.ok(!classes.has(MAP_DARK_CLASS));
    assert.equal(map.sprites.at(-1), spriteFor("https://x.example", "light"));
    assert.equal(routePaint(true, false).casingColor, ROUTE_BLUE);

    // The same flavour again sets no base paint and no sprite.
    const before = map.sprites.length;
    applyMapFlavour(map, "light", "light", "https://x.example", undefined, root);
    assert.equal(map.sprites.length, before);
    assert.equal(told, 2);
  } finally {
    stop();
    setDarkMap(false);
  }
});

test("applyDarkPaint leaves a layer not on the map alone (it takes its paint when added)", () => {
  const map = fakeMap(["coverage-edge"]);
  applyDarkPaint(map, true, overlayLightPaint());
  assert.deepEqual([...map.paint.keys()], ["coverage-edge|line-color"]);
});
