// OWNER-DECISIONS 279 and 280: a facility's visible pattern must not depend on
// the tier line drawn over it, no dash array is odd (SVG repeats an odd list
// into a different pattern from the map's), and an unpaved surface is marked.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  FACILITIES,
  PALETTES,
  currentTiers,
  UNPAVED_DASH,
  facilityLayers,
  facilityWidth,
  setAccessibility,
  stressCasingLayers,
  stressLayers,
  stressOverlayLayers,
  tiersFor,
  unpavedLayers,
  unpavedWidth,
} from "./stressStyle.js";
import { paintAt } from "./testSupport/paintAt.ts";
import { setStressPalette } from "./lib/mapGlue.ts";

type Tier = ReturnType<typeof tiersFor>[number];
type Layer = { id: string; paint: Record<string, unknown>; filter?: unknown };

const strengths = [false, true];
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);

test("no dash array is odd: solid is no dash at all, in every palette, plain and strong, and in every layer's paint", () => {
  for (const palette of Object.keys(PALETTES)) {
    for (const strong of strengths) {
      for (const tier of tiersFor(palette, strong)) {
        if (tier.dash !== null) assert.equal(tier.dash.length % 2, 0, `${palette} ${tier.short}: ${JSON.stringify(tier.dash)}`);
      }
    }
  }
  assert.equal(tiersFor("blended")[0].dash, null, "LTS 1 is solid: a [1] would be [1, 1] to an SVG legend");
  for (const f of FACILITIES as Array<{ facility: string; dash: number[] | null }>) {
    if (f.dash !== null) assert.equal(f.dash.length % 2, 0, f.facility);
  }
  assert.equal(UNPAVED_DASH.length % 2, 0);
  for (const layer of stressOverlayLayers("s") as Layer[]) {
    const dash = layer.paint["line-dasharray"];
    if (dash !== undefined) assert.equal((dash as number[]).length % 2, 0, `${layer.id}: ${JSON.stringify(dash)}`);
  }
});

test("a solid tier's layer has no dasharray, and a dashed one has its own", () => {
  const lines = stressLayers("s") as Layer[];
  const tiers = tiersFor("blended");
  tiers.forEach((tier: Tier, i: number) => {
    if (tier.dash === null) assert.ok(!("line-dasharray" in lines[i].paint), tier.short);
    else assert.deepEqual(lines[i].paint["line-dasharray"], tier.dash, tier.short);
  });
});

test("the legend and the map draw a tier's dash the same way: the legend's SVG list is the tier's, scaled, and nothing for a solid line", () => {
  const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
  assert.match(app, /strokeDasharray=\{tier\.dash \? tier\.dash\.map\(\(d: number\) => d \* widths\.tiers\[i\]\.line\)\.join\(" "\) : undefined\}/);
});

/** Run `body` with the accessibility switch on or off (a trial that leaves what is stored alone), then off again. */
function withSwitch(on: boolean, body: () => void): void {
  setAccessibility(on, { remember: false });
  try {
    body();
  } finally {
    setAccessibility(false, { remember: false });
  }
}

/** The rail layer for a facility, and its width and dash at a tier (in the tiers in use). */
function rail(facility: string, tier: Tier) {
  const layer = (facilityLayers("s") as Layer[]).find((l) => l.id === `facility-${facility}`) as Layer;
  const width = paintAt(layer, "line-width", { tier: tier.tier, facility }, 14) as number;
  return { layer, width, dash: layer.paint["line-dasharray"] as number[] | undefined };
}

test("a facility's rail is the same pattern over every tier: its dash is its own, not the tier's, and the solid casing lies between", () => {
  for (const strong of strengths) withSwitch(strong, () => {
    const tiers = currentTiers() as Tier[];
    const casings = stressCasingLayers("s", undefined, tiers) as Layer[];
    for (const f of FACILITIES as Array<{ facility: string; rail: number; dash: number[] | null }>) {
      const blocks: number[] = [];
      for (const tier of tiers) {
        const { width, dash } = rail(f.facility, tier);
        // The dash (a fraction of the rail layer's width) is the facility's alone.
        assert.deepEqual(dash, f.dash ?? undefined, `${f.facility} over ${tier.short}`);
        // The rail shows `rail` px beyond the casing on each side, at every tier.
        const casing = paintAt(casings[tier.tier - 1], "line-width", { tier: tier.tier }, 14) as number;
        assert.ok(Math.abs((width - casing) / 2 - f.rail) < 1e-9, `${f.facility} over ${tier.short}: ${(width - casing) / 2}px beyond the casing`);
        assert.equal(width, facilityWidth(f, tier.width, tier.casingExtra));
        if (dash) blocks.push(dash[0] * width);
      }
      // The block length in pixels hardly changes with the tier under it (the layer's width does, a little).
      if (blocks.length > 0) assert.ok(Math.max(...blocks) / Math.min(...blocks) < 1.8, `${f.facility}: ${blocks.map((b) => b.toFixed(1))}`);
    }
    // Between the rail and the tier's dashes lies a casing that is solid and wider than the line.
    for (const tier of tiers) {
      const casing = casings[tier.tier - 1];
      assert.ok(!("line-dasharray" in casing.paint), `${tier.short}'s casing is solid`);
      assert.ok((paintAt(casing, "line-width", { tier: tier.tier }, 14) as number) > tier.width, `${tier.short}'s casing hides its dashes' gaps`);
    }
  });
});

test("over every tier, the three facilities are told apart by pattern: solid, blocks and sparse dots differ in pixels", () => {
  for (const strong of strengths) withSwitch(strong, () => {
    for (const tier of currentTiers() as Tier[]) {
      const sig = (FACILITIES as Array<{ facility: string; rail: number; dash: number[] | null }>).map((f) => {
        const { width, dash } = rail(f.facility, tier);
        const on = dash ? dash[0] * width : Infinity;
        const off = dash ? dash[1] * width : 0;
        return { facility: f.facility, on, off, width: (f as { rail: number }).rail };
      });
      const [path, prot, painted] = sig;
      assert.equal(path.off, 0, `${tier.short}: a path's rails are solid`);
      assert.ok(prot.on >= 3 && prot.off >= 3, `${tier.short}: blocks ${prot.on.toFixed(1)}px on, ${prot.off.toFixed(1)}px off`);
      assert.ok(painted.on <= 2.5 && painted.off >= 2 * painted.on, `${tier.short}: dots ${painted.on.toFixed(1)}px, ${painted.off.toFixed(1)}px apart`);
      assert.ok(painted.width < prot.width && painted.width < path.width, `${tier.short}: painted is the thinnest`);
    }
  });
});

test("under the accessibility switch the facility patterns are the same ones (the switch widens lines, not patterns)", () => {
  const plain = JSON.stringify((facilityLayers("s") as Layer[]).map((l) => l.paint["line-dasharray"]));
  setAccessibility(true, { remember: false });
  try {
    assert.equal(JSON.stringify((facilityLayers("s") as Layer[]).map((l) => l.paint["line-dasharray"])), plain);
  } finally {
    setAccessibility(false, { remember: false });
  }
});

// ---- unpaved surfaces (OWNER-DECISIONS 280) --------------------------------

function draws(layer: Layer, properties: Record<string, unknown>): boolean {
  const { filter } = spec.featureFilter(layer.filter as never, `layers[${layer.id}].filter`);
  return filter({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

test("an unpaved road or trail gets a dotted centre mark at every tier, over the tier's line, and a paved one does not", () => {
  const marks = unpavedLayers("s") as Layer[];
  const tiers = tiersFor("blended") as Tier[];
  assert.equal(marks.length, tiers.length);
  marks.forEach((mark, i) => {
    const tier = tiers[i];
    assert.equal(mark.id, `stress-unpaved-${tier.tier}`);
    assert.equal(draws(mark, { tier: tier.tier, unpaved: true }), true, `${tier.short} unpaved`);
    assert.equal(draws(mark, { tier: tier.tier }), false, `${tier.short} with no unpaved property (paved or unknown)`);
    assert.equal(draws(mark, { tier: tier.tier, unpaved: false }), false);
    assert.equal(draws(mark, { tier: tier.tier === 1 ? 2 : 1, unpaved: true }), false, `only its own tier`);
    assert.deepEqual(mark.paint["line-dasharray"], UNPAVED_DASH);
    assert.equal(mark.paint["line-color"], tier.casing, "the colour chosen to stand apart from the line");
    assert.equal(mark.paint["line-width"], unpavedWidth(tier));
    assert.ok(unpavedWidth(tier) < tier.width && unpavedWidth(tier) >= 1.5);
  });
});

test("the unpaved mark is a pattern no tier or facility uses, so it reads without colour", () => {
  const dashes = [...tiersFor("blended").map((t: Tier) => t.dash), ...(FACILITIES as Array<{ dash: number[] | null }>).map((f) => f.dash)];
  assert.ok(!dashes.some((d) => JSON.stringify(d) === JSON.stringify(UNPAVED_DASH)));
  assert.ok(UNPAVED_DASH[0] <= 1.2 * UNPAVED_DASH[1], "dots, not dashes");
});

test("the mark is not drawn where its line is faint or hidden: z12-13 busy roads and alleys", () => {
  const marks = unpavedLayers("s") as Layer[];
  const opacity = (tier: number, props: Record<string, unknown>, zoom: number) => paintAt(marks[tier - 1], "line-opacity", { tier, ...props }, zoom);
  for (const tier of [1, 2]) assert.equal(opacity(tier, {}, 13), 1, `LTS ${tier} z13`);
  for (const tier of [3, 4, 5]) {
    assert.equal(opacity(tier, {}, 13), 0, `LTS ${tier} z13 is faint`);
    assert.equal(opacity(tier, {}, 14), 1, `LTS ${tier} z14`);
    assert.equal(opacity(tier, { separate_bikeway: true }, 15), 0, `LTS ${tier} beside a bikeway`);
  }
  for (const tier of [1, 2, 3, 4, 5]) assert.equal(opacity(tier, { alley: true }, 16), 0, `LTS ${tier} alley`);
});

test("a flip of the accessibility switch repaints the unpaved marks too, in colour and width", () => {
  const ids = (unpavedLayers("s") as Layer[]).map((l) => l.id);
  const calls: Array<[string, string, unknown]> = [];
  const map = {
    getLayer: (id: string) => (ids.includes(id) ? { id } : undefined),
    setPaintProperty: (id: string, name: string, value: unknown) => void calls.push([id, name, value]),
  };
  const strong = tiersFor("cvd", true);
  setStressPalette(map as never, undefined, strong);
  for (const mark of unpavedLayers("s", undefined, strong) as Layer[]) {
    const mine = calls.filter(([id]) => id === mark.id);
    assert.deepEqual(mine.map(([, n, v]) => [n, JSON.stringify(v)]), [
      ["line-color", JSON.stringify(mark.paint["line-color"])],
      ["line-width", JSON.stringify(mark.paint["line-width"])],
    ]);
  }
  assert.equal(calls.length, ids.length * 2);
});

test("the legend lists Unpaved, drawn with the same dots from the same constants as the map", () => {
  const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");
  assert.match(app, /<span className="stress-name">Unpaved<\/span>/);
  assert.match(app, /UNPAVED_DASH\.map\(\(d: number\) => d \* unpavedWidth\(tiers\[0\]\)\)/);
  assert.match(app, /strokeWidth=\{unpavedWidth\(tiers\[0\]\)\}/);
});
