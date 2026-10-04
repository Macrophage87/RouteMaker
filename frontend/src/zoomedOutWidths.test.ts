// OWNER-DECISIONS 375 (2026-10-04): zoomed out the casings looked very fat and
// Columbia's pathways merged into blobs. At z10 and z11 the lines, casings and
// rails are thinned, so a long trail reads as a line; the colours are not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRESS_ZOOMS } from "./lib/mapStyle.ts";
import {
  CASING_EXTRA_PX,
  FACILITIES,
  FULL_WIDTH_MIN_ZOOM,
  PALETTES,
  UNPAVED_PALETTES,
  ZOOMED_OUT_SCALE,
  facilityLayers,
  facilityWidthAt,
  gapLayers,
  stressCasingLayers,
  stressLayers,
  tiersFor,
  unpavedLayers,
  unpavedWidth,
} from "./stressStyle.js";
import { paintAt } from "./testSupport/paintAt.ts";

type Tier = ReturnType<typeof tiersFor>[number];
type Layer = { id: string; paint: Record<string, unknown> };

const PATH = { tier: 1, facility: "path" };
const tiers = (strong = false) => tiersFor("twotone", strong) as Tier[];
const num = (layer: Layer, name: string, props: Record<string, unknown>, zoom: number) => paintAt(layer, name, props, zoom) as number;
const lineOf = (layers: unknown, tier: number) => (layers as Layer[]).find((l) => l.id.endsWith(`-${tier}`)) as Layer;
const rails = (all: Tier[]): Layer => ({ id: "rails", paint: { "line-width": facilityWidthAt(FACILITIES[0], undefined, all) } });

test("the widths are thinned below the zoom the busy roads come in at, which is the style's", () => {
  assert.equal(FULL_WIDTH_MIN_ZOOM, STRESS_ZOOMS.busy);
  assert.deepEqual(Object.keys(ZOOMED_OUT_SCALE).map(Number), [10, 11]);
});

for (const strong of [false, true]) {
  test(`${strong ? "with" : "without"} the accessibility switch, line and casing thin out below z12 and grow with the zoom`, () => {
    const all = tiers(strong);
    for (const tier of all.filter((t) => t.tier < 3)) {
      const props = { tier: tier.tier, facility: "path" };
      const line = lineOf(stressLayers("s", undefined, all), tier.tier);
      const casing = lineOf(stressCasingLayers("s", undefined, all), tier.tier);
      const widths = (layer: Layer) => [10, 11, 12, 14].map((z) => num(layer, "line-width", props, z));
      for (const w of [widths(line), widths(casing)]) {
        assert.ok(w[0] < w[1] && w[1] < w[2], `${tier.short}: ${w}`);
        assert.equal(w[2], w[3], "from z12 the widths are what they were");
      }
      assert.equal(widths(line)[3], tier.width);
      assert.equal(widths(casing)[3], tier.width + (tier.casingExtra ?? CASING_EXTRA_PX));
    }
  });
}

test("a path reads as a line: 4.5 px or less at z10, 6.5 px or less at z11, and 9.5 px as it was from z12", () => {
  const path = (zoom: number) => num(rails(tiers()), "line-width", PATH, zoom);
  assert.ok(path(10) <= 4.5, `${path(10)}`);
  assert.ok(path(11) <= 6.5, `${path(11)}`);
  assert.equal(path(12), 9.5);
  assert.ok(path(10) < path(11) && path(11) < path(12));
});

test("what a low-vision rider sees stays: a line of 1.25 px, an edge of half a pixel, a rail of a pixel", () => {
  for (const strong of [false, true]) {
    const all = tiers(strong);
    const line = num(lineOf(stressLayers("s", undefined, all), 1), "line-width", PATH, 10);
    const casing = num(lineOf(stressCasingLayers("s", undefined, all), 1), "line-width", PATH, 10);
    const outer = num(rails(all), "line-width", PATH, 10);
    assert.ok(line >= 1.25, `line ${line}`);
    assert.ok((casing - line) / 2 >= 0.5, `edge ${(casing - line) / 2}`);
    assert.ok((outer - casing) / 2 >= 1, `rail ${(outer - casing) / 2}`);
  }
  for (const zoom of [10, 11]) {
    const w = (all: Tier[]) => num(lineOf(stressCasingLayers("s", undefined, all), 1), "line-width", PATH, zoom);
    assert.ok(w(tiers(true)) > w(tiers(false)), "the switch stays stronger when zoomed out");
  }
});

test("the colours are the same zoomed out: the two-tone line and casing, and the brown unpaved ramp", () => {
  const all = tiers();
  for (const tier of all.filter((t) => t.tier < 3)) {
    for (const unpaved of [false, true]) {
      const props = { tier: tier.tier, unpaved };
      for (const maker of [stressLayers, stressCasingLayers]) {
        const layer = lineOf(maker("s", undefined, all), tier.tier);
        const at = (z: number) => paintAt(layer, "line-color", props, z);
        assert.equal(at(10), at(14), `${tier.short} ${maker.name} unpaved=${unpaved}`);
        assert.equal(at(11), at(14));
      }
    }
    const line = lineOf(stressLayers("s", undefined, all), tier.tier);
    const key = tier.tier as 1 | 2;
    assert.equal(paintAt(line, "line-color", { tier: tier.tier, unpaved: false }, 10), PALETTES.twotone[key].color);
    assert.equal(paintAt(line, "line-color", { tier: tier.tier, unpaved: true }, 10), UNPAVED_PALETTES.twotone[key].color);
  }
});

test("the unpaved mark and LTS 2's gap line are thinned with their line", () => {
  const all = tiers();
  for (const zoom of [10, 11]) {
    const line2 = num(lineOf(stressLayers("s", undefined, all), 2), "line-width", { tier: 2 }, zoom);
    const gap = num(lineOf(gapLayers("s", undefined, all), 2), "line-width", { tier: 2 }, zoom);
    assert.equal(gap, line2, "the gap is drawn at the line's width");
    for (const tier of all.filter((t) => t.tier < 3)) {
      const mark = num(lineOf(unpavedLayers("s", undefined, all), tier.tier), "line-width", { tier: tier.tier, unpaved: true }, zoom);
      const own = num(lineOf(stressLayers("s", undefined, all), tier.tier), "line-width", { tier: tier.tier }, zoom);
      assert.ok(mark < own, `${tier.short} z${zoom}: the mark ${mark} stays inside the line ${own}`);
    }
  }
  const mark1 = lineOf(unpavedLayers("s", undefined, all), 1);
  assert.equal(num(mark1, "line-width", { tier: 1, unpaved: true }, 14), unpavedWidth(all[0]));
});

test("the busy roads, which the tiles do not carry zoomed out, are left as they were", () => {
  const all = tiers();
  for (const tier of all.filter((t) => t.tier >= 3)) {
    const line = lineOf(stressLayers("s", undefined, all), tier.tier);
    assert.equal(num(line, "line-width", { tier: tier.tier }, 10), num(line, "line-width", { tier: tier.tier }, 12));
  }
});

test("every rail layer carries the thinned grades, in the layers the map is given", () => {
  for (const layer of facilityLayers("s")) {
    const width = layer.paint["line-width"] as unknown[];
    assert.equal(width[0], "step");
    assert.deepEqual([width[3], width[5]], [11, FULL_WIDTH_MIN_ZOOM]);
  }
});
