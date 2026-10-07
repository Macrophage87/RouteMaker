// OWNER-DECISIONS 452a (refining 452): "I want people to know where the trails are, but make them clear
// that it's not routing." No routable stress-map layer draws a feature the tiles mark `mtb`
// (core/stress_tiles.py), for any ride type, ride time or switch; the not-for-routes layer
// (`mtb-trail`) draws them, and only them, in a look no routable line has; a rough trail (`rough`,
// a surface, not the class) still draws as before; and MTB_TRAILS_ROUTABLE / `routableMtb` is the
// one switch that moves them back into the routable layers.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { LIGHT } from "@protomaps/basemaps";
import { massLayers } from "./massStyle.js";
import { STRESS_ZOOMS } from "./lib/mapStyle.ts";
import {
  FACILITIES,
  MTB_MIN_ZOOM,
  MTB_TRAIL,
  MTB_TRAILS_ROUTABLE,
  PALETTES,
  UNKNOWN_SURFACE_DASH,
  UNPAVED_DASH,
  UNPAVED_PALETTES,
  contrastRatio,
  isMtbTrail,
  mtbHides,
  mtbTrailLayers,
  mtbTrailPaint,
  setAccessibility,
  setHighStressLanes,
  setMassRide,
  stressFilters,
  stressOverlayLayers,
} from "./stressStyle.js";

type Layer = { id: string; filter?: unknown; type: string; minzoom?: number; paint: Record<string, unknown> };

function drawsWith(filter: unknown, id: string, properties: Record<string, unknown>): boolean {
  const compiled = spec.featureFilter(filter as never, `layers[${id}].filter`).filter;
  return compiled({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

const WHENS = ["weekday_offpeak", "weekday_rush", "weekend"];
const MTB_ID = "mtb-trail";

/** The features a layer could draw: every tier, surface, facility and car-free time. */
function samples(): Array<Record<string, unknown>> {
  const out: Array<Record<string, unknown>> = [];
  for (const tier of [1, 2, 3, 4, 5]) {
    for (const surface of [{ unpaved: true }, { unpaved: false }, {}]) {
      for (const facility of ["path", "protected", "lane", "none"]) {
        out.push({ tier, facility, trail: true, ...surface });
        out.push({ tier, facility, trail: true, roadside: true, ...surface });
        out.push({ tier, facility, car_free: "weekend", ...surface });
      }
    }
  }
  return out;
}

test("the switch is off: mountain-bike trails are in no routable layer, for any ride type", () => {
  assert.equal(MTB_TRAILS_ROUTABLE, false);
  assert.deepEqual(mtbHides, ["!=", ["get", "mtb"], true]);
  assert.deepEqual(isMtbTrail, ["==", ["get", "mtb"], true]);
});

test("no routable layer (stress, unpaved, surface-unknown, ring, gap, facility) draws an `mtb` feature; the not-for-routes layer draws every one and nothing else, in any ride time or mode", () => {
  for (const mass of [false, true]) {
    for (const lanes of [false, true]) {
      for (const when of WHENS) {
        const filters = stressFilters(when, lanes, mass);
        const ids = Object.keys(filters);
        assert.ok(ids.includes("stress-1") && ids.includes("facility-path") && ids.includes("stress-unpaved-1") && ids.includes("stress-unknown") && ids.includes(MTB_ID));
        let drawnPlain = 0;
        for (const [id, filter] of Object.entries(filters)) {
          for (const feature of samples()) {
            if (id === MTB_ID) {
              assert.equal(drawsWith(filter, id, feature), false, `${id} drew a trail that is not a mountain-bike one`);
              assert.equal(drawsWith(filter, id, { ...feature, mtb: false }), false, id);
              assert.equal(drawsWith(filter, id, { ...feature, rough: true }), false, `${id}: rough is not the class`);
              assert.equal(drawsWith(filter, id, { ...feature, mtb: true }), true, `${id} left out a mountain-bike trail (${when}, mass ${mass})`);
              continue;
            }
            assert.equal(drawsWith(filter, id, { ...feature, mtb: true }), false, `${id} drew a mountain-bike trail (${when}, mass ${mass})`);
            assert.equal(drawsWith(filter, id, { ...feature, mtb: true, rough: true }), false, id);
            if (drawsWith(filter, id, feature)) drawnPlain += 1;
          }
        }
        assert.ok(drawnPlain > 0, "the same features without `mtb` still draw");
      }
    }
  }
});

test("the not-for-routes layer follows the ride time: a zoomed-out tile's trail kept only for other times is not drawn", () => {
  const offpeak = stressFilters("weekday_offpeak", false, false)[MTB_ID];
  const weekend = stressFilters("weekend", false, false)[MTB_ID];
  assert.equal(drawsWith(offpeak, MTB_ID, { mtb: true, car_free_only: ["weekend"] }), false);
  assert.equal(drawsWith(weekend, MTB_ID, { mtb: true, car_free_only: ["weekend"] }), true);
});

test("only the mountain-bike class moves: each routable filter differs from the routable-MTB one by `mtb` alone, and a rough trail still draws", () => {
  for (const when of WHENS) {
    const hidden = stressFilters(when, false, false);
    const routable = stressFilters(when, false, false, true);
    for (const [id, filter] of Object.entries(hidden)) {
      if (id === MTB_ID) continue;
      // The cut sits after the ride time's drawn-at clause, ahead of the layer's own clauses.
      const plain = routable[id] as unknown[];
      assert.deepEqual(filter, [plain[0], plain[1], mtbHides, ...plain.slice(2)], id);
      for (const feature of samples()) {
        // `rough` (is_rough: a rough surface, paved cobbles among them) is not the class.
        assert.equal(drawsWith(filter, id, { ...feature, rough: true }), drawsWith(routable[id], id, feature), `${id}: rough is not hidden`);
        assert.equal(drawsWith(filter, id, { ...feature, mtb: false }), drawsWith(routable[id], id, feature), `${id}: mtb false draws`);
      }
    }
  }
});

test("a future MTB mode (`routableMtb`) draws them as any other trail, and the not-for-routes layer draws nothing", () => {
  const routable = stressFilters("weekday_offpeak", false, false, true);
  const trail = { tier: 1, facility: "none", trail: true, unpaved: true, mtb: true };
  assert.equal(drawsWith(routable["stress-unpaved-1"], "stress-unpaved-1", trail), true);
  assert.equal(drawsWith(routable["stress-casing-1"], "stress-casing-1", trail), true);
  assert.equal(drawsWith(routable[MTB_ID], MTB_ID, trail), false);
});

test("the not-for-routes line: thin, mid-grey, fine dots, no casing or rails, from zoom 14, under every routable layer", () => {
  assert.equal(MTB_MIN_ZOOM, STRESS_ZOOMS.quiet, "where the tiles carry them, as before");
  for (const strong of [false, true]) {
    try {
      setAccessibility(strong, { remember: false });
      const layers = stressOverlayLayers("stress") as Layer[];
      assert.equal(layers[0].id, MTB_ID, "the bottom layer: every routable line draws over it");
      assert.equal(layers.filter((l) => l.id.startsWith("mtb")).length, 1, "one layer: no casing, ring or rail of its own");
      const [layer] = mtbTrailLayers("stress") as Layer[];
      assert.equal(layer.minzoom, MTB_MIN_ZOOM);
      assert.deepEqual(layer.paint, mtbTrailPaint(strong));
      assert.deepEqual(layer.paint["line-dasharray"], MTB_TRAIL.dash);
      assert.ok(!("line-gap-width" in layer.paint));
      const width = layer.paint["line-width"] as number;
      assert.equal(width, strong ? MTB_TRAIL.strongWidth : MTB_TRAIL.width);
      assert.equal(layer.paint["line-color"], strong ? MTB_TRAIL.strongColor : MTB_TRAIL.color);
      // Thinner than any routable line (LTS 1's 2.5 px and up).
      assert.ok(width <= 2);
    } finally {
      setAccessibility(false, { remember: false });
    }
  }
  // The dots are their own pattern: not the unpaved mark's, the surface-unknown dashes or any rail's.
  for (const other of [UNPAVED_DASH, UNKNOWN_SURFACE_DASH, ...FACILITIES.map((f) => f.dash).filter(Boolean)]) {
    assert.notDeepEqual(MTB_TRAIL.dash, other);
  }
  assert.ok(MTB_TRAIL.dash[1] >= 2 * MTB_TRAIL.dash[0], "gaps at least twice the dots: separate dots, not a dashed line");
});

/** The light base map's surfaces a trail can lie over (as stressContrast.test.ts). */
function surfaces(): Record<string, string> {
  const out: Record<string, string> = {};
  const SURFACE = /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|other|minor|link|major$|highway$|bridges_)/;
  for (const [key, value] of Object.entries(LIGHT)) {
    if (typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) && SURFACE.test(key) && !key.includes("casing")) out[key] = value.toLowerCase();
  }
  for (const [key, value] of Object.entries((LIGHT as { landcover?: Record<string, string> }).landcover ?? {})) {
    const m = value.match(/^rgba?\(\s*(\d+),\s*(\d+),\s*(\d+)/);
    if (m) out[`landcover.${key}`] = `#${m.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, "0")).join("")}`;
  }
  return out;
}

test("the grey is at least 3:1 from every surface of the base map, plain and (stronger) with the accessibility switch, and is no stress colour", () => {
  const found = surfaces();
  assert.ok(Object.keys(found).length >= 20 && "park_b" in found && "water" in found && "wood_b" in found, JSON.stringify(found));
  for (const strong of [false, true]) {
    const colour = mtbTrailPaint(strong)["line-color"] as string;
    const failures = Object.entries(found)
      .map(([name, hex]) => [name, contrastRatio(colour, hex)] as const)
      .filter(([, ratio]) => ratio < 3)
      .map(([name, ratio]) => `${name} ${ratio.toFixed(2)}:1`);
    assert.deepEqual(failures, [], colour);
  }
  for (const name of Object.keys(found)) {
    assert.ok(contrastRatio(MTB_TRAIL.strongColor, found[name]) >= contrastRatio(MTB_TRAIL.color, found[name]), name);
  }
  // The legend draws it on the base map's earth, so it reads the same in the dark theme's panel.
  assert.equal(MTB_TRAIL.legendGround, (LIGHT as unknown as { earth: string }).earth.toLowerCase());
  const used = new Set<string>();
  for (const palettes of [PALETTES, UNPAVED_PALETTES]) {
    for (const palette of Object.values(palettes) as Array<Record<string, Record<string, unknown>>>) {
      for (const tier of Object.values(palette)) for (const v of Object.values(tier)) if (typeof v === "string") used.add(v.toLowerCase());
    }
  }
  assert.ok(!used.has(MTB_TRAIL.color) && !used.has(MTB_TRAIL.strongColor), "not a stress colour in any palette");
});

test("every overlay layer the map adds but the not-for-routes one leaves them out, with the accessibility and lane switches either way", () => {
  for (const strong of [false, true]) {
    for (const lanes of [false, true]) {
      try {
        setAccessibility(strong, { remember: false });
        setHighStressLanes(lanes, { remember: false });
        for (const mass of [false, true]) {
          setMassRide(mass);
          for (const when of WHENS) {
            const layers = stressOverlayLayers("stress", when) as Layer[];
            assert.ok(layers.length > 20);
            for (const layer of layers) {
              // Without a capacity (`rpm`), so the Mass Ride map's massHides does not take it out.
              const feature = { tier: 1, facility: "path", trail: true, unpaved: true, mtb: true };
              const expected = layer.id === MTB_ID;
              assert.equal(drawsWith(layer.filter ?? true, layer.id, feature), expected, `${layer.id} and a mountain-bike trail`);
              const road = { ...feature, tier: 3, facility: "none", trail: false, unpaved: false };
              assert.equal(drawsWith(layer.filter ?? true, layer.id, road), expected, `${layer.id} (as a road)`);
            }
          }
        }
      } finally {
        setMassRide(false);
        setAccessibility(false, { remember: false });
        setHighStressLanes(false, { remember: false });
      }
    }
  }
});

test("the Mass Ride map's own layers leave a mountain-bike trail out, even one with a capacity", () => {
  for (const layer of massLayers("mass", "stress") as Layer[]) {
    for (const tier of [3, 5]) {
      const road = { tier, rpm: 250, facility: "none" };
      assert.equal(drawsWith(layer.filter, layer.id, { ...road, mtb: true }), false, layer.id);
    }
  }
  const drawn = (massLayers("mass", "stress") as Layer[]).filter((l) => drawsWith(l.filter, l.id, { tier: 3, rpm: 250, facility: "none" }));
  assert.ok(drawn.length > 0, "a road with a capacity still draws");
});
