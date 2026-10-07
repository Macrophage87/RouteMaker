// OWNER-DECISIONS 452: "Remove the mountain bike trails. MTB mode might be available later."
// No stress-map layer draws a feature the tiles mark `mtb` (core/stress_tiles.py), for any ride
// type, ride time or switch; a rough trail (`rough`, a surface, not the class) still draws; and
// SHOW_MTB_TRAILS / `showMtb` is the one switch that draws them again.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import { massLayers } from "./massStyle.js";
import {
  SHOW_MTB_TRAILS,
  mtbHides,
  setAccessibility,
  setHighStressLanes,
  setMassRide,
  stressFilters,
  stressOverlayLayers,
} from "./stressStyle.js";

type Layer = { id: string; filter?: unknown; type: string };

function drawsWith(filter: unknown, id: string, properties: Record<string, unknown>): boolean {
  const compiled = spec.featureFilter(filter as never, `layers[${id}].filter`).filter;
  return compiled({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

const WHENS = ["weekday_offpeak", "weekday_rush", "weekend"];

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

test("the switch is off: mountain-bike trails are hidden for every ride type", () => {
  assert.equal(SHOW_MTB_TRAILS, false);
  assert.deepEqual(mtbHides, ["!=", ["get", "mtb"], true]);
});

test("no stress, unpaved, surface-unknown, ring, gap or facility layer draws an `mtb` feature, in any ride time or mode", () => {
  for (const mass of [false, true]) {
    for (const lanes of [false, true]) {
      for (const when of WHENS) {
        const filters = stressFilters(when, lanes, mass);
        const ids = Object.keys(filters);
        assert.ok(ids.includes("stress-1") && ids.includes("facility-path") && ids.includes("stress-unpaved-1") && ids.includes("stress-unknown"));
        let drawnPlain = 0;
        for (const [id, filter] of Object.entries(filters)) {
          for (const feature of samples()) {
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

test("only the mountain-bike class is hidden: the filter differs from the old one by `mtb` alone, and a rough trail still draws", () => {
  for (const when of WHENS) {
    const hidden = stressFilters(when, false, false);
    const shown = stressFilters(when, false, false, true);
    for (const [id, filter] of Object.entries(hidden)) {
      // The cut sits after the ride time's drawn-at clause, ahead of the layer's own clauses.
      const plain = shown[id] as unknown[];
      assert.deepEqual(filter, [plain[0], plain[1], mtbHides, ...plain.slice(2)], id);
      for (const feature of samples()) {
        // `rough` (is_rough: a rough surface, paved cobbles among them) is not the class.
        assert.equal(drawsWith(filter, id, { ...feature, rough: true }), drawsWith(shown[id], id, feature), `${id}: rough is not hidden`);
        assert.equal(drawsWith(filter, id, { ...feature, mtb: false }), drawsWith(shown[id], id, feature), `${id}: mtb false draws`);
      }
    }
  }
});

test("a future MTB mode (`showMtb`) draws them as any other trail", () => {
  const shown = stressFilters("weekday_offpeak", false, false, true);
  const trail = { tier: 1, facility: "none", trail: true, unpaved: true, mtb: true };
  assert.equal(drawsWith(shown["stress-unpaved-1"], "stress-unpaved-1", trail), true);
  assert.equal(drawsWith(shown["stress-casing-1"], "stress-casing-1", trail), true);
});

test("every overlay layer the map adds carries the filter, with the accessibility and lane switches either way", () => {
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
              const feature = { tier: 1, facility: "path", trail: true, unpaved: true, mtb: true, rpm: 300 };
              assert.equal(drawsWith(layer.filter ?? true, layer.id, feature), false, `${layer.id} drew a mountain-bike trail`);
              const road = { ...feature, tier: 3, facility: "none", trail: false, unpaved: false };
              assert.equal(drawsWith(layer.filter ?? true, layer.id, road), false, `${layer.id} (as a road)`);
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

test("the Mass Ride map's own layers leave a mountain-bike trail out too, even one with a capacity", () => {
  for (const layer of massLayers("mass", "stress") as Layer[]) {
    for (const tier of [3, 5]) {
      const road = { tier, rpm: 250, facility: "none" };
      assert.equal(drawsWith(layer.filter, layer.id, { ...road, mtb: true }), false, layer.id);
    }
  }
  const drawn = (massLayers("mass", "stress") as Layer[]).filter((l) => drawsWith(l.filter, l.id, { tier: 3, rpm: 250, facility: "none" }));
  assert.ok(drawn.length > 0, "a road with a capacity still draws");
});
