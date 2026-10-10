// OWNER-DECISIONS 456, 456a-c (docs/MTB-TOPO-PLAN.md, slice 2): the mountain-bike trail layer draws each
// difficulty level (the tiles' `mtb_level`, 1-4) in its colour - green, blue, black, red - with a pattern of
// its own and a casing, so the colour is never the only cue; an unrated trail keeps the grey dots; each colour
// is 3:1 or more from every surface of the base map (as MTB_TRAIL is) and from its casing; and no level is
// drawn by a routable layer.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { baseSurfaces } from "./testSupport/baseSurfaces.ts";
import {
  FACILITIES,
  MTB_LAYER_IDS,
  MTB_LEVEL,
  MTB_LEVELS,
  MTB_MIN_ZOOM,
  MTB_TRAIL,
  MTB_TRAIL_LAYER_ID,
  currentTiers,
  UNKNOWN_SURFACE_DASH,
  UNPAVED_DASH,
  contrastRatio,
  isMtbLayerId,
  mtbLevelCasingLayerId,
  mtbLevelLayerId,
  mtbLevelPaint,
  mtbTrailLayers,
  setAccessibility,
  stressFilters,
  stressOverlayLayers,
} from "./stressStyle.js";

type Layer = { id: string; filter?: unknown; type: string; minzoom?: number; paint: Record<string, unknown> };
type Shape = (typeof MTB_LEVELS)[number];

function draws(filter: unknown, id: string, properties: Record<string, unknown>): boolean {
  const compiled = spec.featureFilter(filter as never, `layers[${id}].filter`).filter;
  return compiled({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

const WHENS = ["weekday_offpeak", "weekday_rush", "weekend"];

test("four levels, the owner's colours and names, in order", () => {
  assert.deepEqual(
    MTB_LEVELS.map((l: Shape) => [l.level, l.name, l.color]),
    [
      [1, "green", "#2e7d32"],
      [2, "blue", "#1565c0"],
      [3, "black", "#1c1917"],
      [4, "red", "#c62828"],
    ],
  );
  assert.deepEqual(
    MTB_LEVELS.map((l: Shape) => l.scale),
    ["S1 or IMBA 1", "S2 or IMBA 2", "S3 or IMBA 3", "S4 to S6 or IMBA 4"],
  );
});

test("each level's colour is at least 3:1 from every surface of the base map and from its white casing", () => {
  const found = baseSurfaces();
  assert.ok(Object.keys(found).length >= 20 && "park_b" in found && "water" in found && "wood_b" in found, JSON.stringify(found));
  for (const shape of MTB_LEVELS as Shape[]) {
    const failures = Object.entries(found)
      .map(([name, hex]) => [name, contrastRatio(shape.color, hex)] as const)
      .filter(([, ratio]) => ratio < 3)
      .map(([name, ratio]) => `${name} ${ratio.toFixed(2)}:1`);
    assert.deepEqual(failures, [], `level ${shape.level} ${shape.color}`);
    assert.ok(contrastRatio(shape.color, MTB_LEVEL.casing) >= 3, `level ${shape.level} against its casing`);
  }
});

test("each level has a pattern of its own: dashed, unlike every other, and none of the map's other line patterns", () => {
  const others = [MTB_TRAIL.dash, UNPAVED_DASH, UNKNOWN_SURFACE_DASH, ...FACILITIES.map((f: { dash: number[] | null }) => f.dash), ...currentTiers().map((t: { dash: number[] | null }) => t.dash)].filter(Boolean);
  const seen = new Set<string>();
  for (const shape of MTB_LEVELS as Shape[]) {
    assert.ok(shape.dash.length >= 2 && shape.dash.length % 2 === 0, `level ${shape.level}: a dash array`);
    // Dashed, never solid: a solid line is how the map draws a way to ride (452a).
    assert.ok(shape.dash.some((d: number, i: number) => i % 2 === 1 && d > 0), `level ${shape.level} has gaps`);
    for (const other of others) assert.notDeepEqual(shape.dash, other, `level ${shape.level}`);
    assert.ok(!seen.has(JSON.stringify(shape.dash)), `level ${shape.level}'s pattern is another level's`);
    seen.add(JSON.stringify(shape.dash));
    assert.ok(shape.pattern.length > 0, "the pattern has words for the legend");
  }
});

test("the layer: the unrated dots, then each level's casing, then its line, under every routable layer, from zoom 14", () => {
  for (const strong of [false, true]) {
    try {
      setAccessibility(strong, { remember: false });
      const layers = mtbTrailLayers("stress") as Layer[];
      assert.deepEqual(layers.map((l) => l.id), MTB_LAYER_IDS);
      const all = (stressOverlayLayers("stress") as Layer[]).map((l) => l.id);
      assert.deepEqual(all.slice(0, MTB_LAYER_IDS.length), MTB_LAYER_IDS, "every routable line draws over them");
      for (const shape of MTB_LEVELS as Shape[]) {
        const casing = layers.find((l) => l.id === mtbLevelCasingLayerId(shape.level))!;
        const line = layers.find((l) => l.id === mtbLevelLayerId(shape.level))!;
        assert.ok(layers.indexOf(casing) < layers.indexOf(line), "the casing under its line");
        assert.equal(casing.minzoom, MTB_MIN_ZOOM);
        assert.equal(line.minzoom, MTB_MIN_ZOOM);
        const paint = mtbLevelPaint(shape.level, strong);
        assert.deepEqual(line.paint, paint.line);
        assert.deepEqual(casing.paint, paint.casing);
        assert.equal(line.paint["line-color"], shape.color);
        assert.deepEqual(line.paint["line-dasharray"], shape.dash);
        assert.equal(casing.paint["line-color"], MTB_LEVEL.casing);
        assert.ok(!("line-dasharray" in casing.paint), "a solid casing");
        const width = line.paint["line-width"] as number;
        assert.equal(width, strong ? MTB_LEVEL.strongWidth : MTB_LEVEL.width);
        assert.ok((casing.paint["line-width"] as number) > width, "the casing shows either side");
        // Wider than the grey dots, so the colour reads.
        assert.ok(width > (strong ? MTB_TRAIL.strongWidth : MTB_TRAIL.width) - 0.01);
      }
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
});

test("each level's layers draw only that level's mountain-bike trails; the dots draw only the unrated ones; no routable layer draws any", () => {
  for (const mass of [false, true]) {
    for (const when of WHENS) {
      const filters = stressFilters(when, false, mass) as Record<string, unknown>;
      for (const id of MTB_LAYER_IDS) assert.ok(id in filters, id);
      const trail = { tier: 1, facility: "none", trail: true, unpaved: true, mtb: true, rpm: 80 };
      for (const shape of MTB_LEVELS as Shape[]) {
        for (const id of [mtbLevelLayerId(shape.level), mtbLevelCasingLayerId(shape.level)]) {
          for (const level of [1, 2, 3, 4]) assert.equal(draws(filters[id], id, { ...trail, mtb_level: level }), level === shape.level, `${id} and level ${level}`);
          assert.equal(draws(filters[id], id, trail), false, `${id}: an unrated trail is the dots'`);
          assert.equal(draws(filters[id], id, { ...trail, mtb: false, mtb_level: shape.level }), false, `${id}: only the mountain-bike class`);
        }
      }
      assert.equal(draws(filters[MTB_TRAIL_LAYER_ID], MTB_TRAIL_LAYER_ID, trail), true, "an unrated trail keeps the grey dots");
      for (const level of [1, 2, 3, 4]) assert.equal(draws(filters[MTB_TRAIL_LAYER_ID], MTB_TRAIL_LAYER_ID, { ...trail, mtb_level: level }), false, `the dots leave level ${level} to its layer`);
      for (const [id, filter] of Object.entries(filters)) {
        if (isMtbLayerId(id)) continue;
        for (const level of [1, 2, 3, 4]) assert.equal(draws(filter, id, { ...trail, mtb_level: level }), false, `${id} drew a level ${level} trail`);
      }
    }
  }
});

test("a level follows the ride time like the dots, and a future MTB mode (`routableMtb`) moves the levels too", () => {
  const offpeak = stressFilters("weekday_offpeak", false, false) as Record<string, unknown>;
  const weekend = stressFilters("weekend", false, false) as Record<string, unknown>;
  const id = mtbLevelLayerId(2);
  assert.equal(draws(offpeak[id], id, { mtb: true, mtb_level: 2, car_free_only: ["weekend"] }), false);
  assert.equal(draws(weekend[id], id, { mtb: true, mtb_level: 2, car_free_only: ["weekend"] }), true);
  const routable = stressFilters("weekday_offpeak", false, false, true) as Record<string, unknown>;
  for (const layer of MTB_LAYER_IDS) assert.equal(draws(routable[layer], layer, { mtb: true, mtb_level: 2, tier: 1 }), false, layer);
});
