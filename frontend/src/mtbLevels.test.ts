// OWNER-DECISIONS 456, 456a-c (docs/MTB-TOPO-PLAN.md, slice 2): the mountain-bike trail layer draws each
// difficulty level (the tiles' `mtb_level`, 1-4) in its colour - green, blue, black, red - with a pattern of
// its own and shared dark cross-ticks, so the colour is never the only cue and no level looks like a routable
// line (452a); an unrated trail keeps the grey dots; each colour is 3:1 or more from every surface of the base
// map (as MTB_TRAIL is); and no level is drawn by a routable layer.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { baseSurfaces } from "./testSupport/baseSurfaces.ts";
import {
  FACILITIES,
  MTB_LABEL,
  MTB_LABEL_LAYER_ID,
  MTB_LABEL_MIN_ZOOM,
  MTB_LAYER_IDS,
  MTB_LINE_LAYER_IDS,
  MTB_LEVEL,
  MTB_LEVEL_MIN_GAP,
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
  mtbLabelColor,
  mtbLabelLayers,
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
      // Darker than the starting #2e7d32, which was 3.0009:1 on the base map's scrub (review of slice 2).
      [1, "green", "#28702c"],
      [2, "blue", "#1565c0"],
      [3, "black", "#1c1917"],
      [4, "red", "#c62828"],
    ],
  );
  assert.deepEqual(
    MTB_LEVELS.map((l: Shape) => l.scale),
    ["S1 or IMBA 1", "S2 or IMBA 2", "S3 or IMBA 3", "S4 or above, or IMBA 4 or above"],
  );
});

test("each level's colour is at least 3:1 from every surface of the base map, with margin, and its ticks too", () => {
  const found = baseSurfaces();
  assert.ok(Object.keys(found).length >= 20 && "park_b" in found && "water" in found && "wood_b" in found, JSON.stringify(found));
  for (const shape of MTB_LEVELS as Shape[]) {
    const failures = Object.entries(found)
      .map(([name, hex]) => [name, contrastRatio(shape.color, hex)] as const)
      .filter(([, ratio]) => ratio < 3)
      .map(([name, ratio]) => `${name} ${ratio.toFixed(2)}:1`);
    assert.deepEqual(failures, [], `level ${shape.level} ${shape.color}`);
    // The line's gaps show the base map (no solid casing behind them), so no colour sits at the bar's edge.
    const lowest = Math.min(...Object.values(found).map((hex) => contrastRatio(shape.color, hex)));
    assert.ok(lowest >= 3.25, `level ${shape.level}: lowest ${lowest.toFixed(2)}:1`);
    // The light roads a trail crosses too.
    for (const road of ["minor_a", "minor_b", "minor_service"]) if (road in found) assert.ok(contrastRatio(shape.color, found[road]) >= 3, `level ${shape.level} on ${road}`);
  }
  const ticks = Math.min(...Object.values(found).map((hex) => contrastRatio(MTB_LEVEL.tick, hex)));
  assert.ok(ticks >= 3, `the ticks: ${ticks.toFixed(2)}:1`);
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

test("the layer: the unrated dots, then each level's ticks, then its line, under every routable layer, from zoom 14", () => {
  for (const strong of [false, true]) {
    try {
      setAccessibility(strong, { remember: false });
      const layers = mtbTrailLayers("stress") as Layer[];
      assert.deepEqual(layers.map((l) => l.id), MTB_LINE_LAYER_IDS);
      const all = (stressOverlayLayers("stress") as Layer[]).map((l) => l.id);
      assert.deepEqual(all.slice(0, MTB_LINE_LAYER_IDS.length), MTB_LINE_LAYER_IDS, "every routable line draws over them");
      for (const shape of MTB_LEVELS as Shape[]) {
        const casing = layers.find((l) => l.id === mtbLevelCasingLayerId(shape.level))!;
        const line = layers.find((l) => l.id === mtbLevelLayerId(shape.level))!;
        assert.ok(layers.indexOf(casing) < layers.indexOf(line), "the ticks under its line");
        assert.equal(casing.minzoom, MTB_MIN_ZOOM);
        assert.equal(line.minzoom, MTB_MIN_ZOOM);
        const paint = mtbLevelPaint(shape.level, strong);
        assert.deepEqual(line.paint, paint.line);
        assert.deepEqual(casing.paint, paint.casing);
        assert.equal(line.paint["line-color"], shape.color);
        assert.deepEqual(line.paint["line-dasharray"], shape.dash);
        assert.equal(casing.paint["line-color"], MTB_LEVEL.tick);
        assert.deepEqual(casing.paint["line-dasharray"], MTB_LEVEL.tickDash, "the shared cross-ticks");
        const width = line.paint["line-width"] as number;
        assert.equal(width, strong ? MTB_LEVEL.strongWidth : MTB_LEVEL.width);
        assert.ok((casing.paint["line-width"] as number) >= width + 4, "the ticks show 2 px or more either side");
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

// ---- 452a: "clearly unlike any routable trail or road" (review of slice 2) ------------------------------------

/** The gaps of a dash list (its odd entries), in widths; none for a solid line. */
const gaps = (dash: readonly number[] | null) => (dash ? dash.filter((_, i) => i % 2 === 1) : []);

test("every level differs from every stress tier on its dash, its edge and its width, plain and strong", () => {
  for (const strong of [false, true]) {
    try {
      setAccessibility(strong, { remember: false });
      const layers = stressOverlayLayers("stress") as Layer[];
      for (const shape of MTB_LEVELS as Shape[]) {
        const paint = mtbLevelPaint(shape.level, strong);
        const levelWidth = paint.line["line-width"] as number;
        // One mark every level shares: the same ticks and width, whatever the level.
        assert.deepEqual(paint.casing, mtbLevelPaint(1, strong).casing);
        assert.ok(Math.min(...gaps(shape.dash)) >= MTB_LEVEL_MIN_GAP, `level ${shape.level}'s gaps`);
        const [tickOn, tickOff] = MTB_LEVEL.tickDash;
        assert.ok(tickOn / (tickOn + tickOff) <= 0.2, "ticks, not a broken edge: mostly gap");
        for (const tier of currentTiers() as { tier: number; dash: number[] | null; width: number }[]) {
          const where = `level ${shape.level} against tier ${tier.tier}${strong ? " (strong)" : ""}`;
          // Dash: a tier is solid, or its gaps are 1 width or less; every level's are 1.5 or more.
          assert.ok(Math.max(0, ...gaps(tier.dash)) < MTB_LEVEL_MIN_GAP, where);
          assert.notDeepEqual(shape.dash, tier.dash, where);
          // Edge: every tier's casing is a solid line; a level's is the dashed ticks.
          const casing = layers.find((l) => l.id === `stress-casing-${tier.tier}`)!;
          assert.ok(casing, `stress-casing-${tier.tier}`);
          assert.ok(!("line-dasharray" in casing.paint), `${where}: the tier's casing is solid`);
          assert.ok("line-dasharray" in paint.casing, `${where}: the level's edge is ticked`);
          // Width: thinner than every tier's line.
          assert.ok(levelWidth < tier.width, `${where}: ${levelWidth} px against ${tier.width}`);
        }
        // The one dashed edge a routable line has (surface unknown, LTS 1) follows the line's dashes, not ticks.
        assert.notDeepEqual(MTB_LEVEL.tickDash, UNKNOWN_SURFACE_DASH);
      }
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
});

// ---- the trail names (the owner, 2026-10-10: "Also, for mountain bikes, try to make sure trail names are
// added in if they are available.") ----------------------------------------------------------------------

type Symbol = { id: string; type: string; minzoom?: number; filter: unknown; layout: Record<string, unknown>; paint: Record<string, unknown> };

/** The label colour MapLibre picks for a feature (the `match` on `mtb_level`). */
function labelColour(expression: unknown, properties: Record<string, unknown>): string {
  const compiled = spec.expression.createExpression(expression as never, spec.latest.paint_symbol["text-color"] as never, "layers[0].paint.text-color" as never);
  assert.equal(compiled.result, "success");
  const colour = (compiled.value as { evaluate: (g: unknown, f: unknown) => { toString(): string } }).evaluate({ zoom: 15 }, { properties, type: 2 });
  // The `match` hands back its output as written: a hex string.
  return String(colour).toLowerCase();
}

test("the names are drawn along the line on the mountain-bike layer only, from zoom 15, haloed, and thinned by collision", () => {
  const [label] = mtbLabelLayers("stress") as Symbol[];
  assert.equal(label.id, MTB_LABEL_LAYER_ID);
  assert.equal(label.type, "symbol");
  assert.equal(label.minzoom, MTB_LABEL_MIN_ZOOM);
  assert.equal(MTB_LABEL_MIN_ZOOM, 15);
  assert.equal(label.layout["symbol-placement"], "line");
  assert.deepEqual(label.layout["text-field"], ["get", "name"]);
  assert.deepEqual(label.layout["text-font"], ["Noto Sans Medium"], "a face the base map's glyphs carry (lib/railLayer.ts LABEL_FONT)");
  // Collision on (MapLibre's default), with room around each label and between repeats.
  assert.ok(!("text-allow-overlap" in label.layout) && !("text-ignore-placement" in label.layout));
  assert.ok((label.layout["text-padding"] as number) >= 4 && (label.layout["symbol-spacing"] as number) >= 250);
  // Curvy singletrack bends more than a road: MapLibre's default 45, not the 30 the Mass Ride labels use.
  assert.equal(label.layout["text-max-angle"], 45);
  assert.equal(label.paint["text-halo-color"], "#ffffff");
  assert.ok((label.paint["text-halo-width"] as number) >= 1);
  assert.ok(isMtbLayerId(MTB_LABEL_LAYER_ID), "it follows the layer's switch");
  assert.ok(MTB_LAYER_IDS.includes(MTB_LABEL_LAYER_ID));
  const errors = spec.validateStyleMin({ version: 8, sources: { stress: { type: "vector", tiles: ["https://x/{z}/{x}/{y}"] } }, glyphs: "https://x/{fontstack}/{range}.pbf", layers: [label] } as never);
  assert.deepEqual(errors, []);
});

test("only named mountain-bike trails are labelled, rated or not, in every ride time and mode", () => {
  for (const mass of [false, true]) {
    for (const when of WHENS) {
      const filter = (stressFilters(when, false, mass) as Record<string, unknown>)[MTB_LABEL_LAYER_ID];
      const trail = { tier: 1, trail: true, mtb: true, rpm: 80 };
      assert.equal(draws(filter, MTB_LABEL_LAYER_ID, { ...trail, name: "Rosaryville Trail" }), true);
      assert.equal(draws(filter, MTB_LABEL_LAYER_ID, { ...trail, name: "Loop 3", mtb_level: 3 }), true);
      assert.equal(draws(filter, MTB_LABEL_LAYER_ID, trail), false, "no name, no label");
      assert.equal(draws(filter, MTB_LABEL_LAYER_ID, { tier: 1, trail: true, name: "Rock Creek Trail" }), false, "not a mountain-bike trail");
    }
  }
  const routable = stressFilters("weekday_offpeak", false, false, true) as Record<string, unknown>;
  assert.equal(draws(routable[MTB_LABEL_LAYER_ID], MTB_LABEL_LAYER_ID, { mtb: true, name: "X" }), false);
});

test("a name is in its line's colour, each 4.5:1 or more against the white halo, darker grey with the accessibility switch", () => {
  for (const strong of [false, true]) {
    const expression = mtbLabelColor(strong);
    for (const shape of MTB_LEVELS as Shape[]) {
      const colour = labelColour(expression, { mtb_level: shape.level });
      assert.equal(colour, shape.color);
      assert.ok(contrastRatio(colour, MTB_LABEL.halo) >= 4.5, `level ${shape.level} ${contrastRatio(colour, MTB_LABEL.halo).toFixed(2)}:1`);
    }
    const unrated = labelColour(expression, {});
    assert.equal(unrated, strong ? MTB_TRAIL.strongColor : MTB_TRAIL.color);
    assert.ok(contrastRatio(unrated, MTB_LABEL.halo) >= 4.5);
  }
  const [label] = mtbLabelLayers("stress", "weekday_offpeak", false) as Symbol[];
  assert.deepEqual(label.paint["text-color"], mtbLabelColor(false));
});
