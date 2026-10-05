// OWNER-DECISIONS 375 (2026-10-04): zoomed out Columbia's pathways merged into
// blobs. At z10 and z11 the lines and rails are thinned, so a long trail reads as
// a line; the casing's edge and the colours are not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { STRESS_ZOOMS } from "./lib/mapStyle.ts";
import {
  CASING_EXTRA_PX,
  FACILITIES,
  FULL_WIDTH_MIN_ZOOM,
  PALETTES,
  UNPAVED_PALETTES,
  ZOOMED_OUT_MIN_PX,
  ZOOMED_OUT_NEAR_ZOOM,
  ZOOMED_OUT_SCALE,
  facilityLayers,
  facilityWidthAt,
  gapLayers,
  stressCasingLayers,
  stressLayers,
  tiersFor,
  unpavedLayers,
  unpavedWidth,
  zoomedOutLine,
} from "./stressStyle.js";
import { paintAt } from "./testSupport/paintAt.ts";

type Tier = ReturnType<typeof tiersFor>[number];
type Layer = { id: string; paint: Record<string, unknown> };
type Facility = (typeof FACILITIES)[number];

const PATH = { tier: 1, facility: "path" };
const ZOOMED_OUT = [10, 11];
const tiers = (strong = false) => tiersFor("twotone", strong) as Tier[];
const num = (layer: Layer, name: string, props: Record<string, unknown>, zoom: number) => paintAt(layer, name, props, zoom) as number;
const lineOf = (layers: unknown, tier: number) => (layers as Layer[]).find((l) => l.id.endsWith(`-${tier}`)) as Layer;
const rails = (all: Tier[], facility: Facility = FACILITIES[0]): Layer => ({
  id: "rails",
  paint: { "line-width": facilityWidthAt(facility, undefined, all) },
});

/** What a rider sees of LTS 1 at a zoom: the line, the casing's edge a side, a facility's rail a side, the unpaved mark. */
function seen(strong: boolean, zoom: number, facility: Facility = FACILITIES[0]) {
  const all = tiers(strong);
  const props = { tier: 1, facility: facility.facility };
  const line = num(lineOf(stressLayers("s", undefined, all), 1), "line-width", props, zoom);
  const casing = num(lineOf(stressCasingLayers("s", undefined, all), 1), "line-width", props, zoom);
  const outer = num(rails(all, facility), "line-width", props, zoom);
  const mark = num(lineOf(unpavedLayers("s", undefined, all), 1), "line-width", { tier: 1, unpaved: true }, zoom);
  return { line, edge: (casing - line) / 2, rail: (outer - casing) / 2, mark, whole: outer };
}

test("the widths are thinned below the zoom the busy roads come in at, which is the style's", () => {
  assert.equal(FULL_WIDTH_MIN_ZOOM, STRESS_ZOOMS.busy);
  assert.equal(ZOOMED_OUT_NEAR_ZOOM, 11, "core.stress_tiles.TRAILS_NEAR_MIN_ZOOM, which tests/test_stress_tiles.py holds");
  assert.deepEqual(Object.keys(ZOOMED_OUT_SCALE).map(Number), [STRESS_ZOOMS.min, ZOOMED_OUT_NEAR_ZOOM]);
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
      for (const zoom of ZOOMED_OUT) {
        const edge = (widths(casing)[zoom - 10] - widths(line)[zoom - 10]) / 2;
        assert.equal(edge, (tier.casingExtra ?? CASING_EXTRA_PX) / 2, `${tier.short} z${zoom}: the edge is not thinned`);
      }
    }
  });
}

test("a path reads as a line: 5.5 px or less at z10, 7 px or less at z11, and 9.5 px as it was from z12", () => {
  const path = (zoom: number) => num(rails(tiers()), "line-width", PATH, zoom);
  assert.ok(path(10) <= 5.5, `${path(10)}`);
  assert.ok(path(11) <= 7, `${path(11)}`);
  assert.equal(path(12), 9.5);
  assert.ok(path(10) < path(11) && path(11) < path(12));
});

test("what a low-vision rider sees stays, at z10 and z11, switch on and off: a line of 1.25 px, an edge, a rail and an unpaved mark of a pixel", () => {
  assert.equal(ZOOMED_OUT_MIN_PX, 1);
  for (const strong of [false, true]) {
    for (const zoom of ZOOMED_OUT) {
      const { line, edge, rail, mark } = seen(strong, zoom);
      const at = `strong=${strong} z${zoom}`;
      assert.ok(line >= 1.25, `${at}: line ${line}`);
      assert.ok(edge >= 1, `${at}: edge ${edge}`);
      assert.ok(rail >= 1, `${at}: rail ${rail}`);
      assert.ok(mark >= 1, `${at}: unpaved mark ${mark}`);
      for (const facility of FACILITIES) {
        const r = seen(strong, zoom, facility).rail;
        assert.ok(r >= 1, `${at} ${facility.facility}: rail ${r}`);
      }
    }
  }
});

test("the switch stays wider zoomed out: its line and its edge each, and its rails never narrower", () => {
  for (const zoom of ZOOMED_OUT) {
    const plain = seen(false, zoom);
    const strong = seen(true, zoom);
    assert.ok(strong.line > plain.line, `z${zoom} line ${strong.line} > ${plain.line}`);
    assert.ok(strong.edge > plain.edge, `z${zoom} edge ${strong.edge} > ${plain.edge}`);
    assert.ok(strong.whole > plain.whole, `z${zoom} whole path ${strong.whole} > ${plain.whole}`);
    assert.ok(strong.mark >= plain.mark, `z${zoom} mark ${strong.mark} >= ${plain.mark}`);
    for (const facility of FACILITIES) {
      // The path's rail is the same with the switch, as it is from z12.
      const [p, s] = [seen(false, zoom, facility).rail, seen(true, zoom, facility).rail];
      assert.ok(s >= p, `z${zoom} ${facility.facility}: rail ${s} >= ${p}`);
    }
  }
  assert.equal(seen(true, 12).rail, seen(false, 12).rail, "from z12 too, the path's rail is the switch's");
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

test("the unpaved mark is three fifths of its thinned line, a pixel at least, never wider than from z12; LTS 2's gap is its line", () => {
  for (const strong of [false, true]) {
    const all = tiers(strong);
    for (const zoom of ZOOMED_OUT) {
      const line2 = num(lineOf(stressLayers("s", undefined, all), 2), "line-width", { tier: 2 }, zoom);
      const gap = num(lineOf(gapLayers("s", undefined, all), 2), "line-width", { tier: 2 }, zoom);
      assert.equal(gap, line2, "the gap is drawn at the line's width");
      for (const tier of all.filter((t) => t.tier < 3)) {
        const mark = num(lineOf(unpavedLayers("s", undefined, all), tier.tier), "line-width", { tier: tier.tier, unpaved: true }, zoom);
        const own = num(lineOf(stressLayers("s", undefined, all), tier.tier), "line-width", { tier: tier.tier }, zoom);
        assert.equal(own, zoomedOutLine(tier, zoom));
        const expected = Math.min(unpavedWidth(tier), Math.max(1, own * 0.6));
        assert.equal(mark, expected, `${tier.short} z${zoom} strong=${strong}`);
        assert.ok(mark < own, `${tier.short} z${zoom}: the mark ${mark} stays inside the line ${own}`);
        const later = num(lineOf(unpavedLayers("s", undefined, all), tier.tier), "line-width", { tier: tier.tier, unpaved: true }, zoom + 1);
        assert.ok(mark <= later, `${tier.short}: the mark does not shrink as the map zooms in (${mark} > ${later} at z${zoom + 1})`);
      }
    }
    const mark1 = lineOf(unpavedLayers("s", undefined, all), 1);
    assert.equal(num(mark1, "line-width", { tier: 1, unpaved: true }, 14), unpavedWidth(all[0]));
  }
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
    assert.deepEqual([width[3], width[5]], [ZOOMED_OUT_NEAR_ZOOM, FULL_WIDTH_MIN_ZOOM]);
  }
});
