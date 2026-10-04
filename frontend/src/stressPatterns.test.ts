// OWNER-DECISIONS 279 and 280: a facility's visible pattern must not depend on
// the tier line drawn over it, no dash array is odd (SVG repeats an odd list
// into a different pattern from the map's), and an unpaved surface is marked.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  DEFAULT_PALETTE,
  FACILITIES,
  PALETTES,
  currentTiers,
  UNPAVED_DASH,
  facilityLayers,
  facilityWidth,
  railWidth,
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
        // The rail shows its width (`rail`, or `strongRail` with the switch on) beyond the casing on each side, at every tier.
        const casing = paintAt(casings[tier.tier - 1], "line-width", { tier: tier.tier }, 14) as number;
        assert.ok(Math.abs((width - casing) / 2 - railWidth(f, strong)) < 1e-9, `${f.facility} over ${tier.short}: ${(width - casing) / 2}px beyond the casing`);
        assert.equal(width, facilityWidth(f, tier.width, tier.casingExtra, strong));
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
  const tiers = tiersFor(DEFAULT_PALETTE) as Tier[];
  assert.equal(marks.length, tiers.length);
  marks.forEach((mark, i) => {
    const tier = tiers[i];
    assert.equal(mark.id, `stress-unpaved-${tier.tier}`);
    assert.equal(draws(mark, { tier: tier.tier, unpaved: true }), true, `${tier.short} unpaved`);
    assert.equal(draws(mark, { tier: tier.tier }), false, `${tier.short} with no unpaved property (paved or unknown)`);
    assert.equal(draws(mark, { tier: tier.tier, unpaved: false }), false);
    assert.equal(draws(mark, { tier: tier.tier === 1 ? 2 : 1, unpaved: true }), false, `only its own tier`);
    assert.deepEqual(mark.paint["line-dasharray"], UNPAVED_DASH);
    assert.equal(mark.paint["line-color"], tier.unpavedCasing, "the unpaved casing, chosen to stand apart from the brown line (OWNER-DECISIONS 302)");
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

// ---- unpaved trails have no path rail (OWNER-DECISIONS 290) -----------------

test("an unpaved trail gets no path rail, at every tier and ride time; a paved one, and one of unknown surface, keep it", () => {
  const path = (when?: string) => (facilityLayers("s", when as never) as Layer[]).find((l) => l.id === "facility-path") as Layer;
  for (const when of [undefined, "weekend", "weekday_rush"]) {
    const layer = path(when);
    for (const tier of [1, 2, 3, 4, 5]) {
      assert.equal(draws(layer, { tier, facility: "path", trail: true, unpaved: true }), false, `LTS ${tier} unpaved trail (${when})`);
      assert.equal(draws(layer, { tier, facility: "path", trail: true, unpaved: false }), true, `LTS ${tier} paved trail`);
      assert.equal(draws(layer, { tier, facility: "path", trail: true }), true, `LTS ${tier} trail of unknown surface`);
    }
  }
  // A road closed to cars this weekend draws as a path: paved, its rails; unpaved, none.
  assert.equal(draws(path("weekend"), { tier: 3, facility: "none", car_free: "weekend" }), true);
  assert.equal(draws(path("weekend"), { tier: 3, facility: "none", car_free: "weekend", unpaved: true }), false);
  // A zoomed-out tile's merged feature carries "unpaved" too (core/stress_tiles.py PROPERTIES), whatever else it carries.
  assert.equal(draws(path(), { tier: 1, facility: "path", trail: true, unpaved: true, car_free_only: ["weekday_offpeak", "weekday_rush", "weekend"] }), false);
});

test("an unpaved trail still draws its tier's line and the dotted mark, and the other rails ignore the surface", () => {
  const all = stressOverlayLayers("s") as Layer[];
  const trail = { tier: 1, facility: "path", trail: true, unpaved: true };
  const drawn = all.filter((l) => draws(l, trail)).map((l) => l.id);
  assert.deepEqual(drawn.sort(), ["stress-1", "stress-casing-1", "stress-unpaved-1"].sort());
  for (const facility of ["protected", "lane"]) {
    const layer = all.find((l) => l.id === `facility-${facility}`) as Layer;
    assert.equal(draws(layer, { tier: 2, facility, unpaved: true }), true, `${facility} on an unpaved road keeps its rail`);
  }
});

test("a path's rail is 2 to 2.5 px at every zoom, plain and strong: lighter than a protected lane's, still the only solid rail", () => {
  const [pathF, protectedF, laneF] = FACILITIES as Array<{ facility: string; rail: number; strongRail?: number; dash: number[] | null }>;
  for (const strong of strengths) {
    assert.ok(railWidth(pathF, strong) >= 2 && railWidth(pathF, strong) <= 2.5, `${railWidth(pathF, strong)}`);
    assert.ok(railWidth(pathF, strong) < railWidth(protectedF, strong));
  }
  assert.equal(pathF.dash, null);
  assert.ok(protectedF.dash && laneF.dash);
  // The width is a number per tier, not a zoom expression: the same at z15-16 as at z12.
  const layer = (facilityLayers("s") as Layer[]).find((l) => l.id === "facility-path") as Layer;
  for (const zoom of [12, 15, 16, 18]) {
    const width = paintAt(layer, "line-width", { tier: 1, facility: "path" }, zoom) as number;
    assert.equal((width - (tiersFor("blended")[0].width + 2)) / 2, railWidth(pathF));
  }
});

test("the painted rail: 1 px by default, 1.5 px with the accessibility switch on, still the thinnest rail either way", () => {
  const lane = (FACILITIES as Array<{ facility: string; rail: number; strongRail?: number }>).find((f) => f.facility === "lane")!;
  assert.equal(railWidth(lane, false), 1);
  assert.equal(railWidth(lane, true), 1.5);
  assert.ok(railWidth(lane, false) < railWidth(lane, true), "the default is the weakest");
  for (const strong of strengths) {
    for (const f of FACILITIES as Array<{ facility: string; rail: number }>) {
      if (f.facility !== "lane") assert.ok(railWidth(lane, strong) < railWidth(f, strong), `painted under ${f.facility} (${strong})`);
    }
  }
  // On the map: the painted layer's width over each tier shows 1.5 px beyond the strong casing.
  for (const strong of strengths) withSwitch(strong, () => {
    const layer = (facilityLayers("s") as Layer[]).find((l) => l.id === "facility-lane") as Layer;
    for (const tier of currentTiers() as Tier[]) {
      const width = paintAt(layer, "line-width", { tier: tier.tier, facility: "lane" }, 14) as number;
      assert.equal((width - tier.width - tier.casingExtra) / 2, strong ? 1.5 : 1, `${tier.short} ${strong}`);
    }
  });
});

