// The route over the road colours (Stephen, 2026-10-12: "The colors on mass ride are so bright that I
// can't see the actual route.", "It's similar for regular routes too" and "Maybe mute most of the
// colors when there's a route, for default too. Like an alpha of 0.8"): a route in sections is a white
// band inside a wider casing, over roads faded to MASS_NETWORK_DIMMED (a Mass Ride's capacity route)
// or ROUTE_OVERLAY_FADE (any other).
import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import { MASS_AVOID, MASS_BANDS, MASS_LAYER_IDS } from "../massStyle.js";
import { contrastRatio, setAccessibility, stressOverlayLayers } from "../stressStyle.js";
import {
  MASS_NETWORK_DIMMED,
  ROUTE_BLUE,
  ROUTE_CASING_CVD,
  ROUTE_CASING_WIDTH,
  ROUTE_HALO_EXTRA,
  ROUTE_BAND,
  ROUTE_BAND_WIDTH,
  ROUTE_CORRIDOR_CASING_WIDTH,
  ROUTE_OVERLAY_FADE,
  routeCorridorPaint,
  overlayFade,
  routeClasses,
  ROUTE_SWATCH_BAND_WIDTH,
  ROUTE_SWATCH_CASING_WIDTH,
  ROUTE_SWATCH_HEIGHT,
} from "./routeColours.ts";
import {
  ROUTE_BAND_LAYER_ID,
  ROUTE_STRESS_SOURCE_ID,
  fadedOpacity,
  keptUnderRoute,
  routeOverlayFade,
  setOverlayFade,
  setRouteSections,
} from "./mapGlue.ts";
import { STRESS_SOURCE_ID } from "./mapStyle.ts";

const COORDS: Array<[number, number]> = [[-77.04, 38.9], [-77.02, 38.9], [-77.0, 38.9]];
const MASS_ROUTE = { geometry: { type: "LineString", coordinates: COORDS }, stress_spans: [{ from_m: 0, to_m: 3460, tier: 2, facility: "none", rpm: 150 }] };
const STRESS_ROUTE = { geometry: { type: "LineString", coordinates: COORDS }, stress_spans: [{ from_m: 0, to_m: 3460, tier: 2, facility: "none" }] };

type Layer = { id: string; type: string; paint?: Record<string, unknown> };
const LAYERS = stressOverlayLayers(STRESS_SOURCE_ID) as Layer[];
const ALL_IDS = LAYERS.map((l) => l.id);

function recordingMap(layers: string[] = ALL_IDS) {
  const paint: Record<string, unknown> = {};
  return {
    paint,
    map: {
      getLayer: (id: string) => (layers.includes(id) ? { id } : undefined),
      getSource: (id: string) => (id === ROUTE_STRESS_SOURCE_ID ? { setData: () => {} } : undefined),
      setPaintProperty: (id: string, name: string, value: unknown) => void (paint[`${id}.${name}`] = value),
    },
  };
}

const NETWORK = [...MASS_LAYER_IDS.casing, ...MASS_LAYER_IDS.line];

test("the band and casing are wider than every section's halo and ring, with room for each", () => {
  const widestHalo = Math.max(
    ...MASS_BANDS.map((b: { width: number }) => b.width + ROUTE_HALO_EXTRA),
    MASS_AVOID.width + ROUTE_HALO_EXTRA,
    ...routeClasses().map((c) => Math.max(c.haloWidth, c.ringWidth ?? 0)),
  );
  assert.ok((ROUTE_BAND_WIDTH - widestHalo) / 2 >= 2, "at least 2 px of white each side of the widest halo");
  assert.ok((ROUTE_CORRIDOR_CASING_WIDTH - ROUTE_BAND_WIDTH) / 2 >= 2, "at least 2 px of casing each side of the band");
  const widestRoad = Math.max(...MASS_BANDS.map((b: { width: number }) => b.width)) + 3;
  assert.ok(ROUTE_CORRIDOR_CASING_WIDTH >= widestRoad + 8, "the corridor stands at least 4 px proud of the widest road each side");
});

test("the casing is 3:1 from the white band in both palettes (WCAG 1.4.11)", () => {
  for (const casing of [ROUTE_BLUE, ROUTE_CASING_CVD]) assert.ok(contrastRatio(casing, ROUTE_BAND) >= 3, casing);
});

test("every class's edge on the white band is 3:1, in both palettes and strengths (WCAG 1.4.11)", () => {
  for (const on of [false, true]) {
    setAccessibility(on, { remember: false });
    for (const c of routeClasses()) {
      // What meets the white: the ring if any, else the halo, else (a light halo, white or cream, that
      // merges into the band) the section itself.
      const edge = c.ring ?? (contrastRatio(c.halo, ROUTE_BAND) >= 3 ? c.halo : c.color);
      assert.ok(contrastRatio(edge, ROUTE_BAND) >= 3, `${on ? "high contrast " : ""}${c.key}: ${edge}`);
    }
  }
  setAccessibility(false, { remember: false });
});

test("routeCorridorPaint and overlayFade: the corridor for a route in sections; the fade by kind of route", () => {
  assert.deepEqual(routeCorridorPaint(true, false), { casingWidth: ROUTE_CORRIDOR_CASING_WIDTH, bandOpacity: 1 });
  assert.deepEqual(routeCorridorPaint(true, true), { casingWidth: ROUTE_CORRIDOR_CASING_WIDTH, bandOpacity: 0.45 });
  assert.deepEqual(routeCorridorPaint(false, false), { casingWidth: ROUTE_CASING_WIDTH, bandOpacity: 0 }, "a one-colour route is as before");
  assert.equal(overlayFade(false, false), 1);
  assert.equal(overlayFade(true, true), MASS_NETWORK_DIMMED);
  assert.equal(overlayFade(true, false), ROUTE_OVERLAY_FADE);
  assert.equal(ROUTE_OVERLAY_FADE, 0.8, "Stephen's alpha");
  assert.ok(MASS_NETWORK_DIMMED > 0.3 && MASS_NETWORK_DIMMED < ROUTE_OVERLAY_FADE);
});

test("fadedOpacity scales a zoom step's outputs, keeps its stops, and wraps or multiplies the rest", () => {
  assert.equal(fadedOpacity(undefined, 0.8), 0.8);
  assert.equal(fadedOpacity(undefined, 1), 1);
  assert.equal(fadedOpacity(0.5, 0.8), 0.4);
  const step = ["step", ["zoom"], 0, 12, ["case", ["has", "x"], 1, 0.5], 14, 1];
  assert.deepEqual(fadedOpacity(step, 0.8), ["step", ["zoom"], 0, 12, ["*", 0.8, ["case", ["has", "x"], 1, 0.5]], 14, 0.8]);
  assert.equal(fadedOpacity(step, 1), step, "no fade is the layer's own value");
  const interp = ["interpolate", ["linear"], ["zoom"], 12, 0.5, 16, 1];
  assert.deepEqual(fadedOpacity(interp, 0.5), ["interpolate", ["linear"], ["zoom"], 12, 0.25, 16, 0.5]);
  assert.deepEqual(fadedOpacity(["get", "o"], 0.8), ["*", 0.8, ["get", "o"]]);
});

test("every faded stress layer's opacity keeps ['zoom'] only at the top of its expression", () => {
  for (const layer of LAYERS) {
    if (layer.type !== "line") continue;
    const faded = fadedOpacity(layer.paint?.["line-opacity"], ROUTE_OVERLAY_FADE) as unknown[];
    if (!Array.isArray(faded)) continue;
    // The top-level ["zoom"] input sits at index 1 (step) or 2 (interpolate); nowhere else.
    const rest = faded.filter((_, i) => i !== 1 && i !== 2);
    assert.ok(!rest.some((x) => JSON.stringify(x).includes('["zoom"]')), layer.id);
  }
});

test("Avoid, the hazard rails and the trail names are kept at full strength under a route", () => {
  for (const id of ["stress-5", "stress-casing-5", "stress-unpaved-5", MASS_LAYER_IDS.avoid, MASS_LAYER_IDS.avoidCasing, "mass-hazard-caution-left"]) assert.ok(keptUnderRoute(id), id);
  for (const id of ["stress-1", "stress-casing-4", "facility-protected", ...NETWORK]) assert.ok(!keptUnderRoute(id), id);
});

test("setRouteSections: a Mass Ride route widens the casing, shows the band, dims the capacity roads; clearing it puts them back", () => {
  const { map, paint } = recordingMap();
  setRouteSections(map as never, MASS_ROUTE as never, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_CORRIDOR_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_BAND_LAYER_ID}.line-opacity`], 1);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], MASS_NETWORK_DIMMED, id);
  assert.equal(paint[`${MASS_LAYER_IDS.avoid}.line-opacity`], undefined, "Avoid is not touched");
  setRouteSections(map as never, MASS_ROUTE as never, true);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], MASS_NETWORK_DIMMED, `a stale route keeps the roads dimmed: ${id}`);
  setRouteSections(map as never, null, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_BAND_LAYER_ID}.line-opacity`], 0);
  for (const id of NETWORK) assert.equal(paint[`${id}.line-opacity`], 1, id);
});

test("setRouteSections: a default route gets the corridor too and fades the stress colours to 0.8; clearing it restores each layer's own", () => {
  const { map, paint } = recordingMap();
  setRouteSections(map as never, STRESS_ROUTE as never, false);
  assert.equal(paint["route-casing.line-width"], ROUTE_CORRIDOR_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_BAND_LAYER_ID}.line-opacity`], 1);
  const stress2 = LAYERS.find((l) => l.id === "stress-2")!;
  assert.deepEqual(paint["stress-2.line-opacity"], fadedOpacity(stress2.paint?.["line-opacity"], ROUTE_OVERLAY_FADE));
  assert.equal(paint["facility-protected.line-opacity"], ROUTE_OVERLAY_FADE);
  assert.equal(paint["stress-5.line-opacity"], undefined, "Avoid is not touched");
  setRouteSections(map as never, null, false);
  assert.deepEqual(paint["stress-2.line-opacity"], stress2.paint?.["line-opacity"]);
  assert.equal(paint["facility-protected.line-opacity"], 1);
  assert.equal(paint["route-casing.line-width"], ROUTE_CASING_WIDTH);
  assert.equal(paint[`${ROUTE_BAND_LAYER_ID}.line-opacity`], 0);
});

test("routeOverlayFade uses the corridor's own test: capacity figures on spans that do not meet are not a corridor", () => {
  assert.equal(routeOverlayFade(null), 1);
  assert.equal(routeOverlayFade(MASS_ROUTE as never), MASS_NETWORK_DIMMED);
  assert.equal(routeOverlayFade(STRESS_ROUTE as never), ROUTE_OVERLAY_FADE);
  const gapped = { ...MASS_ROUTE, stress_spans: [{ from_m: 10, to_m: 3460, tier: 2, facility: "none", rpm: 150 }] };
  assert.equal(routeOverlayFade(gapped as never), ROUTE_OVERLAY_FADE);
});

test("with High contrast on the map is not faded under a route, and the corridor still is drawn", () => {
  setAccessibility(true, { remember: false });
  try {
    assert.equal(routeOverlayFade(STRESS_ROUTE as never), 1);
    assert.equal(routeOverlayFade(MASS_ROUTE as never), 1);
    const { map, paint } = recordingMap();
    setRouteSections(map as never, STRESS_ROUTE as never, false);
    assert.equal(paint["facility-protected.line-opacity"], 1);
    assert.equal(paint[`${ROUTE_BAND_LAYER_ID}.line-opacity`], 1);
  } finally {
    setAccessibility(false, { remember: false });
  }
});

test("setOverlayFade skips layers the map does not have yet", () => {
  const { map, paint } = recordingMap([]);
  setOverlayFade(map, MASS_NETWORK_DIMMED);
  assert.deepEqual(paint, {});
});

test("MapView adds the band between the casing and the sections, hidden until setRouteSections shows it, and fades an overlay added after the route", () => {
  const mapView = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const at = (id: string) => mapView.indexOf(id);
  assert.ok(at('id: "route-casing"') < at("id: ROUTE_BAND_LAYER_ID") && at("id: ROUTE_BAND_LAYER_ID") < at('id: "route-ring"'));
  assert.match(mapView.slice(at("id: ROUTE_BAND_LAYER_ID"), at('id: "route-ring"')), /"line-opacity": 0/);
  assert.match(mapView, /setOverlayFade\(map, routeOverlayFade\(callbacks\.current\.route\)\)/);
});

test("the legend swatch is the corridor in miniature: white band round the widest halo, casing round the band", () => {
  const widest = Math.max(...routeClasses().map((c) => Math.max(c.haloWidth, c.ringWidth ?? 0)));
  assert.ok((ROUTE_SWATCH_BAND_WIDTH - widest) / 2 >= 1, `${widest}`);
  assert.ok((ROUTE_SWATCH_CASING_WIDTH - ROUTE_SWATCH_BAND_WIDTH) / 2 >= 2);
  assert.ok(ROUTE_SWATCH_CASING_WIDTH <= ROUTE_SWATCH_HEIGHT);
  for (const file of ["../FacilityBreakdown.tsx", "./massLegend.ts"]) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.match(source, /ROUTE_SWATCH_CASING_WIDTH[\s\S]*ROUTE_BAND, ROUTE_SWATCH_BAND_WIDTH|ROUTE_SWATCH_CASING_WIDTH\}[\s\S]*stroke=\{ROUTE_BAND\} strokeWidth=\{ROUTE_SWATCH_BAND_WIDTH\}/, file);
  }
});
