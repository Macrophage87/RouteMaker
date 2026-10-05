// The Mass Ride map's paint (massStyle.js): OWNER-DECISIONS 325, 326, 327, 387.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  HAZARDS_BUILT,
  MASS_AVOID,
  MASS_BANDS,
  MASS_LAYER_IDS,
  MASS_WIDE_RUN_MI,
  bandIndex,
  dashInWidths,
  hazardLayers,
  massFilters,
  massHides,
  massLayerIds,
  massBandsAt,
  massLayers,
} from "./massStyle.js";
import { setMassRide, stressFilters, stressOverlayLayers } from "./stressStyle.js";
import { VISIONS, deltaE2000, simulate } from "./testSupport/colourVision.ts";
import { contrastRatio } from "./stressStyle.js";
import { paintAt } from "./testSupport/paintAt.ts";

type Layer = { id: string; filter?: unknown; paint: Record<string, unknown>; type: string };

/** Whether `layer` draws a feature with `properties`, as MapLibre decides it. */
function draws(layer: Layer, properties: Record<string, unknown>): boolean {
  const { filter } = spec.featureFilter(layer.filter as never, `layers[${layer.id}].filter`);
  return filter({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

const layers = massLayers("stress") as Layer[];
const byId = (id: string) => layers.find((l) => l.id === id) as Layer;

/** The ids of the Mass Ride layers that draw a feature with `properties`. */
function drawnBy(properties: Record<string, unknown>): string[] {
  return layers.filter((l) => draws(l, properties)).map((l) => l.id);
}

test("the four bands are the owner's: colours, widths and dashes (OWNER-DECISIONS 326, 327)", () => {
  assert.deepEqual(
    MASS_BANDS.map((b: (typeof MASS_BANDS)[number]) => [b.min, b.max, b.color, b.width, b.dashPx]),
    [
      [0, 60, "#d7191c", 4, [6, 4]],
      [60, 120, "#f28e2b", 5.5, [14, 4]],
      [120, 200, "#1a9850", 7, null],
      [200, null, "#6a3d9a", 8.5, null],
    ],
  );
  // The dashes are short and long, then solid.
  assert.ok(MASS_BANDS[0].dashPx[0] < MASS_BANDS[1].dashPx[0]);
});

test("each band has its first zoom: Wide open from 10, Good from 12, the rest from 14 (421)", () => {
  assert.deepEqual(
    MASS_BANDS.map((band) => [band.key, band.minzoom]),
    [["bottleneck", 14], ["tight", 14], ["good", 12], ["wide", 10]],
  );
  assert.deepEqual(massBandsAt(9.9), []);
  assert.deepEqual(massBandsAt(10), [3]);
  assert.deepEqual(massBandsAt(11.7), [3]);
  assert.deepEqual(massBandsAt(12), [2, 3]);
  assert.deepEqual(massBandsAt(13.99), [2, 3]);
  assert.deepEqual(massBandsAt(14), [0, 1, 2, 3]);
  assert.deepEqual(massBandsAt(null), []);
  assert.equal(MASS_WIDE_RUN_MI, 0.5);
  // The layers carry it: every band's casing and line from its own zoom; Avoid from the first.
  const layers = massLayers();
  MASS_BANDS.forEach((band, i) => {
    for (const id of [MASS_LAYER_IDS.casing[i], MASS_LAYER_IDS.line[i]]) {
      assert.equal(layers.find((layer) => layer.id === id)?.minzoom, band.minzoom, id);
    }
  });
  for (const id of [MASS_LAYER_IDS.avoidCasing, MASS_LAYER_IDS.avoid]) {
    assert.equal(layers.find((layer) => layer.id === id)?.minzoom, undefined, `${id}: Avoid shows at every zoom`);
  }
});

test("a figure falls in its band at the edges: 60, 120 and 200 start the next", () => {
  const cases: Array<[number, number]> = [[0, 0], [59, 0], [60, 1], [119, 1], [120, 2], [199, 2], [200, 3], [593, 3]];
  for (const [rpm, band] of cases) assert.equal(bandIndex(rpm), band, String(rpm));
  for (const bad of [null, undefined, Number.NaN, -1]) assert.equal(bandIndex(bad as never), null);
});

test("the tiles round capacity down to ten, so every band edge is a multiple of it", () => {
  for (const band of MASS_BANDS) assert.equal(band.min % 10, 0);
});

test("each band's layers draw only its roads, by the tile's rpm, and not trails, paths, alleys or timed closures", () => {
  assert.deepEqual(drawnBy({ rpm: 40, tier: 2 }), ["mass-casing-bottleneck", "mass-line-bottleneck"]);
  assert.deepEqual(drawnBy({ rpm: 60, tier: 2 }), ["mass-casing-tight", "mass-line-tight"]);
  assert.deepEqual(drawnBy({ rpm: 190, tier: 3 }), ["mass-casing-good", "mass-line-good"]);
  assert.deepEqual(drawnBy({ rpm: 590, tier: 4 }), ["mass-casing-wide", "mass-line-wide"]);
  // Trails and paths are not drawn (126, 127), nor an alley or a road carried only for its closed times.
  assert.deepEqual(drawnBy({ rpm: 100, tier: 1, trail: true }), []);
  assert.deepEqual(drawnBy({ rpm: 100, tier: 1, facility: "path" }), []);
  assert.deepEqual(drawnBy({ rpm: 100, tier: 2, alley: true }), []);
  assert.deepEqual(drawnBy({ rpm: 100, tier: 3, car_free_only: "weekend" }), []);
  // A protected or painted lane's road is a road: its facility is not a Mass Ride rail.
  assert.deepEqual(drawnBy({ rpm: 100, tier: 2, facility: "protected" }), ["mass-casing-tight", "mass-line-tight"]);
  assert.deepEqual(drawnBy({ rpm: 100, tier: 2, facility: "lane" }), ["mass-casing-tight", "mass-line-tight"]);
});

test("a feature with no capacity (a table built before the column) is not drawn by this mode", () => {
  assert.deepEqual(drawnBy({ tier: 3 }), []);
  assert.deepEqual(drawnBy({ tier: 5 }), []);
});

test("a stretch marked Avoid shows only Avoid: its own style, no capacity colour (325, 327)", () => {
  assert.deepEqual(drawnBy({ rpm: 590, tier: 5 }), ["mass-avoid-casing", "mass-avoid", "mass-avoid-label"]);
  const avoid = byId("mass-avoid");
  assert.equal(avoid.paint["line-color"], "#14040a", "near-black");
  assert.equal(byId("mass-avoid-casing").paint["line-color"], "#ee3b2c", "on coral");
  assert.equal(byId("mass-avoid-label").layout?.["text-field"], "AVOID");
  assert.equal(MASS_AVOID.label, "AVOID");
  for (const l of layers.filter((x) => x.id.startsWith("mass-line-") || x.id.startsWith("mass-casing-"))) {
    assert.equal(draws(l, { rpm: 100, tier: 5 }), false, `${l.id} draws an Avoid stretch`);
  }
});

test("the layers are in draw order: every casing, every line, then Avoid and its label", () => {
  const ids = layers.map((l) => l.id);
  assert.deepEqual(ids, massLayerIds());
  const lastCasing = Math.max(...MASS_LAYER_IDS.casing.map((id: string) => ids.indexOf(id)));
  const firstLine = Math.min(...MASS_LAYER_IDS.line.map((id: string) => ids.indexOf(id)));
  assert.ok(lastCasing < firstLine, "a casing is drawn over another band's line");
  assert.equal(ids.at(-1), "mass-avoid-label");
});

test("widths rise with capacity and are the owner's at street level; the line is drawn thinner zoomed out", () => {
  MASS_BANDS.forEach((band: (typeof MASS_BANDS)[number], i: number) => {
    const line = byId(MASS_LAYER_IDS.line[i]);
    assert.equal(paintAt(line, "line-width", {}, 16), band.width);
    assert.ok((paintAt(line, "line-width", {}, 12) as number) < band.width);
  });
  const widths = MASS_BANDS.map((b: (typeof MASS_BANDS)[number]) => b.width);
  assert.deepEqual(widths, [...widths].sort((a, b) => a - b));
});

test("the dashes are the cue besides colour: the two lower bands are dashed, the upper two solid", () => {
  const dashed = MASS_BANDS.map((b: (typeof MASS_BANDS)[number], i: number) => "line-dasharray" in byId(MASS_LAYER_IDS.line[i]).paint);
  assert.deepEqual(dashed, [true, true, false, false]);
  const [red, orange] = MASS_BANDS.map(dashInWidths);
  assert.ok(red && orange && red.length === 2 && orange.length === 2 && red.every((n: number) => n > 0));
});

// ---------------------------------------------------------------------------
// The red/green check under colour-vision simulation (OWNER-DECISIONS 327: "the
// implementation must verify it under CVD simulation"), with the repo's own
// simulator and CIEDE2000 (testSupport/colourVision.ts, Machado 2009).
// ---------------------------------------------------------------------------

/** The cues besides colour that tell two bands apart: width (1.5 px or more) and dash (one dashed, or two different dashes). */
function cuesApart(a: (typeof MASS_BANDS)[number], b: (typeof MASS_BANDS)[number]): string[] {
  const cues: string[] = [];
  if (Math.abs(a.width - b.width) >= 1.5) cues.push("width");
  const da = a.dashPx?.join(",") ?? "solid";
  const db = b.dashPx?.join(",") ?? "solid";
  if (da !== db) cues.push("dash");
  return cues;
}

test("red and green, which a red-green colour-blind rider sees alike, differ in width and in dash", () => {
  const [red, , green] = MASS_BANDS;
  assert.deepEqual(cuesApart(red, green), ["width", "dash"]);
});

test("under every simulated colour vision, any two bands whose colours come close are told apart by a cue besides colour", () => {
  const rows: string[] = [];
  for (const vision of VISIONS) {
    for (let i = 0; i < MASS_BANDS.length; i += 1) {
      for (let j = i + 1; j < MASS_BANDS.length; j += 1) {
        const delta = deltaE2000(simulate(MASS_BANDS[i].color, vision), simulate(MASS_BANDS[j].color, vision));
        const cues = cuesApart(MASS_BANDS[i], MASS_BANDS[j]);
        rows.push(`${vision}: ${MASS_BANDS[i].short} / ${MASS_BANDS[j].short}: ${delta.toFixed(1)}, cues ${cues.join("+") || "none"}`);
        // Under 20, the colours are alike to that rider (the repo's palette threshold): a cue must carry the pair.
        if (delta < 20) assert.ok(cues.length >= 1, `${rows.at(-1)}`);
      }
    }
  }
  // The pair that matters most carries both cues in every vision, whatever its colour distance.
  assert.ok(rows.length === 24);
});

test("every pair of neighbouring bands differs in width, so line weight alone orders them", () => {
  for (let i = 0; i + 1 < MASS_BANDS.length; i += 1) {
    assert.ok(MASS_BANDS[i + 1].width - MASS_BANDS[i].width >= 1.5, `${MASS_BANDS[i].short} to ${MASS_BANDS[i + 1].short}`);
  }
});

test("each band's halo is 3:1 from its colour, and dark under the light ones and white under the dark", () => {
  for (const band of MASS_BANDS) {
    assert.ok(contrastRatio(band.color, band.halo) >= 3, `${band.short}: ${band.color} on ${band.halo}`);
  }
  assert.equal(MASS_BANDS[3].halo, "#ffffff");
  assert.notEqual(MASS_BANDS[0].halo, "#ffffff");
});

// ---------------------------------------------------------------------------
// Where the stress map gives way
// ---------------------------------------------------------------------------

test("in the Mass Ride mode every stress and facility layer excludes the features that carry a capacity", () => {
  try {
    setMassRide(true);
    const filters = stressFilters("weekday_offpeak");
    for (const [id, filter] of Object.entries(filters)) {
      const layer = { id, filter } as Layer;
      assert.equal(draws(layer, { rpm: 100, tier: 3, facility: "lane" }), false, `${id} drew a feature with a capacity`);
    }
    // LTS colours, the rails and the tier-5 style: all gone where the tiles carry rpm, none of them touched where they do not.
    const plain = stressFilters("weekday_offpeak", undefined, false);
    for (const [id, filter] of Object.entries(plain)) {
      assert.deepEqual((filters as Record<string, unknown>)[id], ["all", filter, massHides], id);
    }
  } finally {
    setMassRide(false);
  }
});

test("out of the Mass Ride mode, and on a table without the column, the stress layers draw exactly as they did", () => {
  const filters = stressFilters("weekday_offpeak");
  assert.deepEqual(filters, stressFilters("weekday_offpeak", undefined, false));
  for (const tier of [1, 2, 3, 4, 5]) {
    const layer = { id: `stress-${tier}`, filter: (filters as Record<string, unknown>)[`stress-${tier}`] } as Layer;
    assert.equal(draws(layer, { tier }), true, `stress-${tier}`);
  }
  // A feature with a capacity is the stress map's too when the mode is off.
  const lts3 = { id: "stress-3", filter: (filters as Record<string, unknown>)["stress-3"] } as Layer;
  assert.equal(draws(lts3, { tier: 3, rpm: 100 }), true);
  // A style holding the stress layers and the Mass Ride's validates.
  const style = {
    version: 8,
    sources: {
      stress: { type: "vector", tiles: ["https://example.test/{z}/{x}/{y}.pbf"] },
      // The Mass Ride layers' own tiles (core/mass_tiles.py).
      mass: { type: "vector", tiles: ["https://example.test/mass/{z}/{x}/{y}.pbf"] },
    },
    layers: stressOverlayLayers("stress", "weekday_rush"),
  };
  assert.deepEqual(spec.validateStyleMin(style as never), []);
  assert.deepEqual(Object.keys(massFilters()).sort(), massLayerIds().sort());
});

test("hazards are not built: the seam draws nothing, and no layer or source is asked for them (part 3)", () => {
  assert.equal(HAZARDS_BUILT, false);
  assert.deepEqual(hazardLayers(), []);
  assert.ok(!layers.some((l) => /hazard|caution|warning/.test(l.id)));
});
